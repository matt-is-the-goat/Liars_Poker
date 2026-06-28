"""Gymnasium environment for Liar's Poker.

One seat is the learning agent; the rest are arbitrary ``Agent`` policies. The
env re-implements the round/turn loop (deal -> bids -> challenge -> resolve ->
re-deal) in ``step`` form, reusing the engine's pure functions so the rules stay
in one place. Actions are an index into a fixed list of every possible bid, plus
one "challenge" action; ``action_masks`` marks which are legal right now.
"""

from __future__ import annotations

import random
from typing import Callable, List, Optional

import numpy as np
import gymnasium as gym
from gymnasium import spaces

from liars_poker.bids import Bid, Category
from liars_poker.cards import Card, SUIT_KEYS, build_deck, deal
from liars_poker.evaluator import bid_exists
from liars_poker.game import Action, Agent, PlayerInfo, TableView
from liars_poker.bots import make_bot
from liars_poker.moves import legal_raises

# Compact, RELATIVE action space. Slot 0 = challenge; slots 1..K = "raise to the
# j-th representative legal bid" — the cheapest few raises (fine control) then a
# spread across the rest by strength (for jumps/bluffs). Crucially this makes
# challenge ~1-of-(K+1) instead of 1-of-725, so the policy actually explores it.
K_NEAR = 14      # the cheapest legal raises, one slot each
K_SPREAD = 10    # spread across the remaining (stronger) raises
NUM_RAISE_SLOTS = K_NEAR + K_SPREAD
N_ACTIONS = NUM_RAISE_SLOTS + 1
CHALLENGE = 0

MAX_PLAYERS = 8  # used to size the (padded) observation


PERSONAS = ["trusting", "balanced", "liar"]


def _default_opponent(seat: int, rng: random.Random) -> Agent:
    # Fast-ish heuristics for bootstrapping/benchmarking. Difficulty 'easy' keeps
    # Monte-Carlo cheap so self-play rollouts stay quick.
    return make_bot(f"Opp{seat}", PERSONAS[seat % 3], "easy", rng)


class RandomOpponentFactory:
    """Random persona + difficulty per opponent each game. Defined here (not in
    the ``__main__`` training script) so it pickles by reference for
    SubprocVecEnv workers, which re-import this module under its real name."""

    def __init__(self, difficulties):
        self.difficulties = difficulties

    def __call__(self, seat: int, rng: random.Random) -> Agent:
        return make_bot(f"Opp{seat}", rng.choice(PERSONAS),
                        rng.choice(self.difficulties), rng)


class LiarsPokerEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        num_players: int = 3,
        start_count: int = 2,
        elimination_threshold: int = 4,
        num_jokers: int = 0,
        agent_seat: int = 0,
        make_opponent: Callable[[int, random.Random], Agent] = _default_opponent,
        max_rounds: int = 300,
        reward_round_loss: float = -1.0,
        reward_opp_eliminated: float = 1.0,
        reward_win: float = 10.0,
        reward_eliminated: float = -5.0,
        randomize: bool = False,
        players_range=(2, 5),
        jokers_range=(2, 2),
        start_range=(1, 3),
        threshold_range=(6, 6),
    ):
        super().__init__()
        assert 2 <= num_players <= MAX_PLAYERS
        assert 0 <= agent_seat < num_players
        self.n = num_players
        self.start_count = start_count
        self.threshold = elimination_threshold
        self.num_jokers = num_jokers
        self.agent_seat = agent_seat
        self.make_opponent = make_opponent
        # When set, the per-episode config is re-rolled on each reset so one
        # policy generalises across table sizes / card counts.
        self.randomize = randomize
        self.players_range = players_range
        self.jokers_range = jokers_range
        self.start_range = start_range
        self.threshold_range = threshold_range
        self.max_rounds = max_rounds
        self.r_loss = reward_round_loss
        self.r_opp_elim = reward_opp_eliminated
        self.r_win = reward_win
        self.r_elim = reward_eliminated

        self.action_space = spaces.Discrete(N_ACTIONS)
        self._slots: List[Optional[Bid]] = [None] * NUM_RAISE_SLOTS
        obs_dim = 52 + 20 + 7 + (MAX_PLAYERS - 1)
        self.observation_space = spaces.Box(0.0, 1.0, (obs_dim,), dtype=np.float32)

        self._py_rng = random.Random()

    # ---- gym API -------------------------------------------------------
    def reset(self, *, seed: Optional[int] = None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self._py_rng.seed(seed)
        if self.randomize:
            self.n = self._py_rng.randint(*self.players_range)
            self.num_jokers = self._py_rng.randint(*self.jokers_range)
            self.start_count = self._py_rng.randint(*self.start_range)
            thr = self._py_rng.randint(*self.threshold_range)
            self.threshold = max(self.start_count + 1, thr)
            self.agent_seat = 0
        self.card_counts = [self.start_count] * self.n
        self.eliminated = [False] * self.n
        self.hands: List[List[Card]] = [[] for _ in range(self.n)]
        self.opponents = {
            s: self.make_opponent(s, self._py_rng)
            for s in range(self.n) if s != self.agent_seat
        }
        self.starter = self._py_rng.randrange(self.n)
        self.round_num = 0
        self._game_over = False
        self._winner: Optional[int] = None

        self._begin_round()
        self._pending_reward = 0.0
        self._advance()  # run opponents until it's the agent's turn (or game ends)
        return self._encode_obs(self.agent_seat), {"action_mask": self.action_masks()}

    def step(self, action: int):
        self._pending_reward = 0.0
        if not self._game_over:
            self._apply_agent_action(int(action))
            if not self._game_over:
                self._advance()

        terminated = self._game_over
        truncated = self.round_num > self.max_rounds and not terminated
        obs = self._encode_obs(self.agent_seat)
        info = {"action_mask": self.action_masks(),
                "winner": self._winner, "rounds": self.round_num}
        return obs, float(self._pending_reward), terminated, truncated, info

    def _raise_slots(self) -> List[Optional[Bid]]:
        """Map the K raise slots to representative legal bids for the current
        state: the cheapest K_NEAR raises, then K_SPREAD spread across the rest."""
        legal = legal_raises(self.current_bid)  # weakest -> strongest
        slots: List[Optional[Bid]] = [None] * NUM_RAISE_SLOTS
        L = len(legal)
        if L == 0:
            return slots
        for j in range(min(K_NEAR, L)):
            slots[j] = legal[j]
        if L > K_NEAR:
            lo, hi = K_NEAR, L - 1
            for t in range(K_SPREAD):
                frac = t / (K_SPREAD - 1) if K_SPREAD > 1 else 1.0
                slots[K_NEAR + t] = legal[lo + round(frac * (hi - lo))]
        return slots

    def action_masks(self) -> np.ndarray:
        """Boolean legality mask over the compact action space (for MaskablePPO)."""
        mask = np.zeros(N_ACTIONS, dtype=bool)
        if self._game_over:
            mask[CHALLENGE] = True  # dummy; episode is over
            return mask
        self._slots = self._raise_slots()
        for j, b in enumerate(self._slots):
            if b is not None:
                mask[1 + j] = True
        if self.current_bid is not None:
            mask[CHALLENGE] = True  # can only challenge a standing bid
        return mask

    # ---- round orchestration ------------------------------------------
    def _active(self) -> List[int]:
        return [i for i in range(self.n) if not self.eliminated[i]]

    def _begin_round(self) -> None:
        self.round_num += 1
        active = self._active()
        counts = [self.card_counts[i] for i in active]
        deck = build_deck(self.num_jokers)
        dealt = deal(deck, counts, self._py_rng)
        self.hands = [[] for _ in range(self.n)]
        for seat, hand in zip(active, dealt):
            self.hands[seat] = hand
        if self.starter not in active:
            self.starter = self._next_active_after(self.starter)
        s = active.index(self.starter)
        self.order = active[s:] + active[:s]
        self.turn_ptr = 0
        self.current_bid: Optional[Bid] = None
        self.current_bidder: Optional[int] = None
        self.round_history: List = []

    def _next_active_after(self, idx: int) -> int:
        j = (idx + 1) % self.n
        while self.eliminated[j]:
            j = (j + 1) % self.n
        return j

    def _current_seat(self) -> int:
        return self.order[self.turn_ptr % len(self.order)]

    def _advance(self) -> None:
        """Run opponent turns (and round resolutions) until the agent must act."""
        guard = 0
        while not self._game_over:
            guard += 1
            if guard > 100000:
                raise RuntimeError("advance loop did not terminate")
            seat = self._current_seat()
            if seat == self.agent_seat:
                return
            action = self.opponents[seat].act(self._view_for(seat))
            if action.kind == "challenge" and self.current_bid is not None:
                self._resolve_round(challenger=seat)
            elif action.kind == "challenge":
                self.turn_ptr += 1  # defensive: illegal opening challenge -> skip
            else:
                self._apply_bid(seat, action.bid)

    def _apply_agent_action(self, action: int) -> None:
        if action == CHALLENGE:
            if self.current_bid is not None:
                self._resolve_round(challenger=self.agent_seat)
            return
        slots = self._raise_slots()
        bid = slots[action - 1] if 1 <= action <= NUM_RAISE_SLOTS else None
        if bid is not None:
            self._apply_bid(self.agent_seat, bid)
        # bid is None only if the action was masked-out; ignore defensively.

    def _apply_bid(self, seat: int, bid: Bid) -> None:
        self.current_bid = bid
        self.current_bidder = seat
        self.round_history.append((seat, bid))
        self.turn_ptr += 1

    def _resolve_round(self, challenger: int) -> None:
        active = self._active()
        pool = [c for i in active for c in self.hands[i]]
        existed = bid_exists(self.current_bid, pool)
        loser = self.current_bidder if not existed else challenger
        self.card_counts[loser] += 1
        if loser == self.agent_seat:
            self._pending_reward += self.r_loss

        if self.card_counts[loser] >= self.threshold:
            self.eliminated[loser] = True
            if loser == self.agent_seat:
                self._pending_reward += self.r_elim
                self._game_over = True
                return
            self._pending_reward += self.r_opp_elim
            self.starter = self._next_active_after(loser)
        else:
            self.starter = loser

        if len(self._active()) <= 1:
            self._game_over = True
            self._winner = self._active()[0] if self._active() else None
            if self._winner == self.agent_seat:
                self._pending_reward += self.r_win
            return
        self._begin_round()

    # ---- views / encoding ---------------------------------------------
    def _player_infos(self, me: int) -> List[PlayerInfo]:
        return [
            PlayerInfo(i, getattr(self.opponents.get(i), "name", "You"),
                       self.card_counts[i], self.eliminated[i], i == me)
            for i in range(self.n)
        ]

    def _view_for(self, seat: int) -> TableView:
        total = sum(self.card_counts[i] for i in self._active())
        return TableView(
            my_index=seat,
            my_hand=list(self.hands[seat]),
            players=self._player_infos(seat),
            current_bid=self.current_bid,
            current_bidder=self.current_bidder,
            num_jokers=self.num_jokers,
            total_cards_in_play=total,
            round_history=list(self.round_history),
        )

    def _encode_obs(self, seat: int) -> np.ndarray:
        hand = self.hands[seat]
        cardvec = np.zeros(52, dtype=np.float32)
        jokers = 0
        for c in hand:
            if c.is_joker:
                jokers += 1
            else:
                cardvec[SUIT_KEYS.index(c.suit) * 13 + (c.value - 2)] = 1.0

        bidvec = np.zeros(20, dtype=np.float32)  # cat(13) rank rank2 suit(5)
        b = self.current_bid
        if b is not None:
            bidvec[int(b.category)] = 1.0
            bidvec[13] = b.rank / 14.0
            bidvec[14] = b.rank2 / 14.0
            bidvec[15 + (0 if not b.suit else SUIT_KEYS.index(b.suit) + 1)] = 1.0

        active = self._active()
        scalars = np.array([
            jokers / 2.0,
            self.card_counts[seat] / self.threshold,
            1.0 if b is not None else 0.0,
            len(active) / MAX_PLAYERS,
            sum(self.card_counts[i] for i in active) / (MAX_PLAYERS * self.threshold),
            self.num_jokers / 2.0,
            len(self.round_history) / 20.0,
        ], dtype=np.float32)

        opp = np.zeros(MAX_PLAYERS - 1, dtype=np.float32)
        for k, off in enumerate(range(1, self.n)):
            i = (seat + off) % self.n
            opp[k] = 0.0 if self.eliminated[i] else self.card_counts[i] / self.threshold

        obs = np.concatenate([cardvec, bidvec, scalars, opp]).astype(np.float32)
        return np.clip(obs, 0.0, 1.0)
