"""Bot agents.

Belief model: a bot knows its own cards, the total number of cards in play, and
how many jokers are in the deck — but not what anyone else holds. It estimates
P(a bid exists in the full pool) by Monte Carlo: repeatedly deal the unknown
cards from the remaining deck, combine with its own hand, and check the bid.

Opponent modelling (toggleable):
    When ``signal_strength > 0`` the bot treats other players' bids as evidence
    about the hidden cards. Monte Carlo samples whose pool is *consistent* with
    what trustworthy opponents have claimed are weighted up (importance
    sampling). Each opponent has a ``trust`` score that adapts over the game:
    players whose challenged bids turn out false become less trusted, so their
    claims sway the bot less. With ``signal_strength == 0`` the bot ignores all
    bids and samples uniformly (the old behaviour) — useful as an A/B baseline.

Two axes shape behaviour:
  * difficulty  -> estimate quality (sample count + noise) and default signal use
  * personality -> thresholds for challenging and for how far to bid (bluffing)

"How far to bid beyond what your own cards support" is the crux of the game and
is governed by ``bid_floor`` below — the lowest believed probability a bot will
still claim. Lower floor = bigger bluffs.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from collections import Counter

from .bids import Bid, Category
from .cards import Card, build_deck
from .evaluator import bid_exists
from .game import Action, Agent, RoundResult, TableView
from .moves import legal_raises


@dataclass
class Difficulty:
    name: str
    samples: int          # Monte Carlo samples; more = sharper belief
    noise: float          # random error added to each probability estimate
    signal_strength: float  # default opponent-signal weight (0 = ignore)


# NOTE: opponent modelling is OFF by default at every difficulty. A/B testing
# showed that hand-coded "trust the claims" play is a NET LOSS in this game
# (you get bluffed more and bid overconfidently). It's kept as a toggle for
# experimentation and as a baseline for the future RL bot. See PROJECT_MEMORY.
EASY = Difficulty("easy", samples=40, noise=0.18, signal_strength=0.0)
MEDIUM = Difficulty("medium", samples=120, noise=0.07, signal_strength=0.0)
HARD = Difficulty("hard", samples=220, noise=0.0, signal_strength=0.0)

DIFFICULTIES = {d.name: d for d in (EASY, MEDIUM, HARD)}

# Strength applied when opponent modelling is explicitly switched ON.
ON_SIGNAL_STRENGTH = 0.6


@dataclass
class Personality:
    name: str
    # Call bullshit if believed P(current bid exists) < challenge_threshold.
    challenge_threshold: float
    # Lowest believed P a bot will still claim when bidding (bluff appetite).
    bid_floor: float
    # When raising and no "safe" bid exists, how willing to bluff the cheapest
    # raise anyway (vs. challenging instead), 0..1.
    forced_bluff: float
    # How hard to press: 0 = always the smallest legal raise (timid), 1 = jump to
    # the strongest bid still above the safety floor (maximum pressure). This is
    # what makes a bot exploit a card/information advantage instead of inching up.
    aggression: float


TRUSTING = Personality("Trusting", challenge_threshold=0.12, bid_floor=0.60,
                       forced_bluff=0.20, aggression=0.30)
BALANCED = Personality("Balanced", challenge_threshold=0.30, bid_floor=0.45,
                       forced_bluff=0.45, aggression=0.60)
LIAR = Personality("Liar", challenge_threshold=0.05, bid_floor=0.30,
                   forced_bluff=0.80, aggression=0.85)

PERSONALITIES = {p.name.lower(): p for p in (TRUSTING, BALANCED, LIAR)}

# Candidate raises evaluated per turn. Realistic bids (high cards, pairs, two
# pair, trips, low straights) all sit in the cheap end of the ordering; the long
# tail is huge combinations that are nearly impossible unless you hold the cards.
# So we densely sample the realistic "head" and only lightly probe the tail.
_NEAR_CANDIDATES = 5
_SPREAD_CANDIDATES = 22
_REALISTIC_HEAD = 130
_TAIL_CANDIDATES = 4
# Beta-style smoothing for trust: prior mean and strength.
_TRUST_PRIOR = 0.7
_TRUST_PRIOR_WEIGHT = 2.0


class BotAgent(Agent):
    def __init__(self, name: str, personality: Personality,
                 difficulty: Difficulty, rng: Optional[random.Random] = None,
                 signal_strength: Optional[float] = None):
        self.name = name
        self.personality = personality
        self.difficulty = difficulty
        self.rng = rng or random.Random()
        # signal_strength: None -> use difficulty default.
        self.signal_strength = (difficulty.signal_strength
                                if signal_strength is None else signal_strength)
        # Opponents' claims inform which raises WE make (their bids hint at what
        # exists), but we stay skeptical when deciding to challenge — trusting
        # claims there just gets you bluffed. See the A/B notes in PROJECT_MEMORY.
        self.use_signals_for_challenge = False
        # Per-opponent honesty record: index -> [true_bids, resolved_bids].
        self._trust_stats = defaultdict(lambda: [0, 0])

    # ---- learning from revealed rounds ---------------------------------
    def on_round_result(self, result: RoundResult) -> None:
        """A challenge resolved, so the standing bidder's claim is now known to
        be true or false. Update our trust in that player."""
        if self.signal_strength <= 0:
            return
        stats = self._trust_stats[result.bidder]
        stats[1] += 1
        if result.existed:
            stats[0] += 1

    def _trust_for(self, player_index: int) -> float:
        true_bids, total = self._trust_stats[player_index]
        return ((true_bids + _TRUST_PRIOR * _TRUST_PRIOR_WEIGHT) /
                (total + _TRUST_PRIOR_WEIGHT))

    # ---- belief --------------------------------------------------------
    def _unknown_deck(self, view: TableView) -> List[Card]:
        """The deck minus the cards the bot can see (its own hand)."""
        remaining = build_deck(view.num_jokers)
        for c in view.my_hand:
            for i, d in enumerate(remaining):
                if d == c:
                    remaining.pop(i)
                    break
        return remaining

    def _signal_weight(self, pool: List[Card],
                       signals: Sequence[Tuple[int, Bid]],
                       view: TableView) -> float:
        """Importance weight for a sampled pool, given opponents' prior claims.

        A pool that contradicts a trusted opponent's bid is unlikely, so it gets
        a small weight; a pool consistent with all claims keeps weight 1.0.
        """
        if self.signal_strength <= 0 or not signals:
            return 1.0
        w = 1.0
        for bidder, bid in signals:
            if bidder == view.my_index:
                continue  # our own past bids carry no outside information
            if not bid_exists(bid, pool):
                w *= max(0.0, 1.0 - self.signal_strength * self._trust_for(bidder))
        return w

    def estimate(self, bid: Bid, view: TableView, unknown_deck: List[Card],
                 signals: Sequence[Tuple[int, Bid]] = (),
                 samples: Optional[int] = None) -> float:
        """Monte Carlo estimate of P(bid exists), weighted by opponent signals."""
        n_unknown = view.total_cards_in_play - len(view.my_hand)
        if n_unknown <= 0:
            return 1.0 if bid_exists(bid, view.my_hand) else 0.0

        n = samples or self.difficulty.samples
        take = min(n_unknown, len(unknown_deck))
        num = 0.0
        den = 0.0
        for _ in range(n):
            others = self.rng.sample(unknown_deck, take)
            pool = view.my_hand + others
            w = self._signal_weight(pool, signals, view)
            den += w
            if bid_exists(bid, pool):
                num += w
        p = (num / den) if den > 0 else 0.0
        if self.difficulty.noise:
            p += self.rng.uniform(-self.difficulty.noise, self.difficulty.noise)
        return max(0.0, min(1.0, p))

    # ---- decision ------------------------------------------------------
    def act(self, view: TableView) -> Action:
        unknown = self._unknown_deck(view)
        pers = self.personality

        if view.current_bid is None:
            return Action.make_bid(self._opening_bid(view, unknown))

        history = view.round_history
        # When judging the standing bid for a challenge, don't let that very bid
        # vouch for itself. By default we also ignore other claims here and judge
        # the bid on raw odds — staying a tough challenger (see PROJECT_MEMORY).
        challenge_signals = history[:-1] if self.use_signals_for_challenge else ()
        p_current = self.estimate(view.current_bid, view, unknown, challenge_signals)

        if p_current < pers.challenge_threshold:
            return Action.challenge()

        # Must raise. For our own candidate bids, all prior bids are evidence.
        raises = legal_raises(view.current_bid)
        chosen = self._choose_bid(raises, view.current_bid, view, unknown,
                                  pers.bid_floor, history)
        if chosen is not None:
            return Action.make_bid(chosen)

        # No bid clears the safety floor — bluff or fold to a challenge.
        if raises and self.rng.random() < pers.forced_bluff:
            return Action.make_bid(self._bluff_bid(raises))
        if p_current < max(pers.challenge_threshold * 2.0, 0.5):
            return Action.challenge()
        return Action.make_bid(raises[0]) if raises else Action.challenge()

    def _candidate_raises(self, raises: List[Bid]) -> List[Bid]:
        """The cheapest few raises, a dense spread across the realistic head of
        the range, and a light probe of the tail (for when we hold big cards)."""
        n = len(raises)
        if n <= _NEAR_CANDIDATES + _SPREAD_CANDIDATES:
            return list(raises)
        idxs = set(range(_NEAR_CANDIDATES))
        head = min(n, _REALISTIC_HEAD)
        for k in range(_SPREAD_CANDIDATES):
            idxs.add(round(k * (head - 1) / (_SPREAD_CANDIDATES - 1)))
        if n > head:
            for k in range(_TAIL_CANDIDATES):
                idxs.add(head + round(k * (n - 1 - head) / max(1, _TAIL_CANDIDATES - 1)))
        return [raises[i] for i in sorted(i for i in idxs if i < n)]

    def _hand_candidates(self, view: TableView) -> List[Bid]:
        """Bids the bot's own cards directly support — the hands it can most
        confidently claim, so it leverages the cards it holds (and a bigger hand
        means more of these)."""
        ranks = Counter(c.value for c in view.my_hand if not c.is_joker)
        suits: Counter = Counter()
        suit_hi: dict = {}
        for c in view.my_hand:
            if not c.is_joker:
                suits[c.suit] += 1
                suit_hi[c.suit] = max(suit_hi.get(c.suit, 0), c.value)
        held = sorted(ranks)
        out: List[Bid] = []
        for v in held:
            out.append(Bid(Category.HIGH_CARD, rank=v))
            out.append(Bid(Category.PAIR, rank=v))
            out.append(Bid(Category.TRIPS, rank=v))
            out.append(Bid(Category.QUADS, rank=v))
            out.append(Bid(Category.STRAIGHT, rank=v))
        for i, hi in enumerate(held):
            for lo in held[:i]:
                out.append(Bid(Category.TWO_PAIR, rank=hi, rank2=lo))
            for other in held:
                if other != hi:
                    out.append(Bid(Category.FULL_HOUSE, rank=hi, rank2=other))
        for s, hi in suit_hi.items():
            out.append(Bid(Category.FLUSH, rank=max(6, hi), suit=s))
            out.append(Bid(Category.FLUSH, rank=14, suit=s))
        for c in view.my_hand:
            if not c.is_joker:
                out.append(Bid(Category.STRAIGHT_FLUSH, rank=c.value, suit=c.suit))
        return out

    def _choose_bid(self, raises: List[Bid], current: Optional[Bid],
                    view: TableView, unknown: List[Card], floor: float,
                    signals: Sequence[Tuple[int, Bid]]) -> Optional[Bid]:
        """Pick a bid above the safety floor, pressing as hard as ``aggression``
        dictates. Candidates combine a spread of legal raises with the hands the
        bot's own cards support; a timid bot takes the weakest safe option, an
        aggressive bot jumps near the strongest safe one."""
        pool = list(self._candidate_raises(raises))
        for b in self._hand_candidates(view):
            if current is None or b.beats(current):
                pool.append(b)
        # de-duplicate, keep weakest->strongest order
        seen = set()
        ordered = []
        for b in sorted(pool, key=lambda x: x.sort_key()):
            k = b.sort_key()
            if k not in seen:
                seen.add(k)
                ordered.append(b)
        scan_samples = min(self.difficulty.samples, 80)
        safe = [b for b in ordered
                if self.estimate(b, view, unknown, signals, samples=scan_samples) >= floor]
        if not safe:
            return None
        a = self.personality.aggression
        idx = int(round(a * (len(safe) - 1)))
        return safe[idx]

    def _bluff_bid(self, raises: List[Bid]) -> Bid:
        """A pressure bluff when nothing is safe: aggressive bots jump a bit past
        the minimum raise rather than nudging by one."""
        reach = int(self.personality.aggression * 4)
        return raises[min(reach, len(raises) - 1)]

    def _opening_bid(self, view: TableView, unknown: List[Card]) -> Bid:
        """Open with a believable bid, pressed according to aggression."""
        raises = legal_raises(None)
        chosen = self._choose_bid(raises, None, view, unknown,
                                  self.personality.bid_floor, ())
        return chosen if chosen is not None else raises[0]


def make_bot(name: str, personality: str, difficulty: str,
             rng: Optional[random.Random] = None,
             use_signals: Optional[bool] = None) -> BotAgent:
    """Create a bot.

    ``use_signals``: None -> difficulty default; True -> force opponent modelling
    on (even for easy); False -> force it off (uniform belief, the A/B baseline).
    """
    pers = PERSONALITIES[personality.lower()]
    diff = DIFFICULTIES[difficulty.lower()]
    strength: Optional[float] = None
    if use_signals is False:
        strength = 0.0
    elif use_signals is True:
        strength = ON_SIGNAL_STRENGTH
    return BotAgent(name, pers, diff, rng, signal_strength=strength)
