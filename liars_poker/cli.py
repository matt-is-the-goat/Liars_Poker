"""Terminal interface: human agent, game setup, and the run loop."""

from __future__ import annotations

import os
import random
from typing import List, Optional

from .bids import Bid, Category
from .cards import Card, RANK_VALUES, SUITS, SUIT_KEYS, VALUE_TO_RANK
from .bots import DIFFICULTIES, PERSONALITIES, make_bot
from .game import Action, Agent, Game, GameConfig, TableView

_NAMES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot_names.txt")
_FALLBACK_NAMES = ["Slick", "Boomer", "Maverick", "Vera", "Domino", "Switch",
                   "Ace", "Bluff", "Cricket", "Hex"]


def load_name_pool() -> List[str]:
    """Names for the bots, read from bot_names.txt (editable by the player)."""
    try:
        with open(_NAMES_FILE, encoding="utf-8") as f:
            names = [ln.strip() for ln in f
                     if ln.strip() and not ln.lstrip().startswith("#")]
        return names or list(_FALLBACK_NAMES)
    except OSError:
        return list(_FALLBACK_NAMES)


def pick_names(pool: List[str], n: int, rng: random.Random) -> List[str]:
    """n unique names; if the pool is too small, pad with numbered extras."""
    if len(pool) >= n:
        return rng.sample(pool, n)
    names = list(pool)
    rng.shuffle(names)
    i = 1
    while len(names) < n:
        names.append(f"Bot{i}")
        i += 1
    return names[:n]


# --- small input helpers ----------------------------------------------------
def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        raise SystemExit("\nInput closed — exiting.")


def _ask_int(msg: str, lo: int, hi: int, default: Optional[int] = None) -> int:
    while True:
        d = f" [{default}]" if default is not None else ""
        raw = _prompt(f"{msg}{d}: ")
        if not raw and default is not None:
            return default
        try:
            v = int(raw)
            if lo <= v <= hi:
                return v
        except ValueError:
            pass
        print(f"  Please enter a number from {lo} to {hi}.")


def _ask_rank(msg: str) -> Optional[int]:
    while True:
        raw = _prompt(msg).upper()
        if raw == "":
            return None
        if raw in RANK_VALUES:
            return RANK_VALUES[raw]
        print("  Enter a rank: 2-10, J, Q, K, or A (blank to cancel).")


def _ask_suit(msg: str) -> Optional[str]:
    while True:
        raw = _prompt(msg).upper()
        if raw == "":
            return None
        if raw in SUIT_KEYS:
            return raw
        print("  Enter a suit: S, H, D, or C (blank to cancel).")


# --- human agent ------------------------------------------------------------
_CATEGORY_MENU = [
    ("1", Category.HIGH_CARD, "High card"),
    ("2", Category.PAIR, "Pair"),
    ("3", Category.TWO_PAIR, "Two pair"),
    ("4", Category.TRIPS, "Three of a kind"),
    ("5", Category.STRAIGHT, "Straight"),
    ("6", Category.FLUSH, "Flush"),
    ("7", Category.FULL_HOUSE, "Full house"),
    ("8", Category.QUADS, "Four of a kind"),
    ("9", Category.STRAIGHT_FLUSH, "Straight flush"),
]


_WIDTH = 56


class HumanAgent(Agent):
    is_human = True

    def __init__(self, name: str = "You"):
        self.name = name

    def on_event(self, message: str) -> None:
        print(f"   {message}")

    def _show_table(self, view: TableView) -> None:
        bar = "═" * _WIDTH
        print("\n" + bar)
        hand = "  ".join(str(c) for c in view.my_hand)
        print(f" YOUR HAND   {hand}")
        print("─" * _WIDTH)
        print(f" {'PLAYER':<16}{'CARDS':>6}")
        for p in view.players:
            marker = "▸" if p.index == view.my_index else " "
            name = "You" if p.is_you else p.name
            if p.eliminated:
                print(f" {marker} {name:<14}{'—':>6}   (out)")
            else:
                print(f" {marker} {name:<14}{p.card_count:>6}")
        print("─" * _WIDTH)
        if view.current_bid is not None:
            bidder = "you" if view.players[view.current_bidder].is_you \
                else view.players[view.current_bidder].name
            print(f" CURRENT BID   {view.current_bid}")
            print(f"               (called by {bidder})")
        else:
            print(" CURRENT BID   none — you open the round")
        extras = f"{view.total_cards_in_play} cards in play"
        if view.num_jokers:
            extras += f" · {view.num_jokers} joker(s) in deck"
        print(f" {extras}")
        print(bar)

    def act(self, view: TableView) -> Action:
        self._show_table(view)
        can_challenge = view.current_bid is not None
        while True:
            opts = "[b]id" + (", [c]all bullshit" if can_challenge else "")
            choice = _prompt(f"Your move ({opts}): ").lower()
            if choice in ("c", "call", "bullshit") and can_challenge:
                return Action.challenge()
            if choice in ("b", "bid", ""):
                bid = self._build_bid(view)
                if bid is None:
                    continue
                if view.current_bid is not None and not bid.beats(view.current_bid):
                    print(f"  That bid ({bid}) does not beat {view.current_bid}. Try again.")
                    continue
                return Action.make_bid(bid)
            print("  Unrecognised choice.")

    def _build_bid(self, view: TableView) -> Optional[Bid]:
        print("\n  Choose a hand to bid:")
        for key, _cat, label in _CATEGORY_MENU:
            print(f"    {key}) {label}")
        sel = _prompt("  Category (blank to cancel): ")
        cat = next((c for k, c, _ in _CATEGORY_MENU if k == sel), None)
        if cat is None:
            return None

        if cat in (Category.HIGH_CARD, Category.PAIR, Category.TRIPS, Category.QUADS):
            r = _ask_rank("  Rank: ")
            return None if r is None else Bid(cat, rank=r)

        if cat == Category.TWO_PAIR:
            hi = _ask_rank("  Higher pair rank: ")
            lo = _ask_rank("  Lower pair rank: ")
            if hi is None or lo is None or hi == lo:
                print("  Two pair needs two different ranks.")
                return None
            if hi < lo:
                hi, lo = lo, hi
            return Bid(Category.TWO_PAIR, rank=hi, rank2=lo)

        if cat == Category.FULL_HOUSE:
            t = _ask_rank("  Three-of-a-kind rank: ")
            p = _ask_rank("  Pair rank: ")
            if t is None or p is None or t == p:
                print("  Full house needs two different ranks.")
                return None
            return Bid(Category.FULL_HOUSE, rank=t, rank2=p)

        if cat == Category.STRAIGHT:
            r = _ask_rank("  A rank the straight contains: ")
            return None if r is None else Bid(Category.STRAIGHT, rank=r)

        if cat == Category.STRAIGHT_FLUSH:
            r = _ask_rank("  A rank it contains: ")
            s = _ask_suit("  Suit (S/H/D/C): ")
            if r is None or s is None:
                return None
            return Bid(Category.STRAIGHT_FLUSH, rank=r, suit=s)

        if cat == Category.FLUSH:
            r = _ask_rank("  Highest card of the flush: ")
            s = _ask_suit("  Suit (S/H/D/C): ")
            if r is None or s is None:
                return None
            if r < 6:
                print("  A flush's high card must be at least 6.")
                return None
            return Bid(Category.FLUSH, rank=r, suit=s)

        return None


# --- setup & run ------------------------------------------------------------
def setup_game(rng: random.Random) -> Game:
    print("=" * 60)
    print("           LIAR'S POKER")
    print("=" * 60)
    print("Make escalating poker-hand claims about everyone's combined")
    print("cards — or call BULLSHIT. Last player standing wins.\n")

    num_bots = _ask_int("Number of bots", 1, 7, default=3)
    start_count = _ask_int("Starting cards per player", 1, 5, default=2)
    threshold = _ask_int("Cards that knock you out (elimination threshold)",
                         start_count + 1, 12, default=start_count + 3)
    num_jokers = _ask_int("Jokers to add (0-2)", 0, 2, default=0)

    print("\nBot personalities: trusting / balanced / liar")
    print("Bot difficulties:   easy / medium / hard")

    print("\nOpponent modelling: should bots treat others' bids as evidence the")
    print("claimed hand is real? Off (default) = skeptical, plays the raw odds.")
    print("On = credulous; A/B tests show this actually plays WEAKER in a bluffing")
    print("game. Toggle it to see the difference.")
    sig_raw = _prompt("Opponent modelling on/off? [off]: ").lower()
    use_signals = True if sig_raw in ("on", "yes", "y") else False
    print(f"Opponent modelling: {'ON' if use_signals else 'OFF'} (all bots)")

    names = pick_names(load_name_pool(), num_bots, rng)
    print(f"\nYour opponents: {', '.join(names)}")

    agents: List[Agent] = [HumanAgent("You")]
    pers_keys = list(PERSONALITIES.keys())
    for i in range(num_bots):
        default_pers = pers_keys[i % len(pers_keys)]
        pers = _prompt(f"{names[i]} personality [{default_pers}]: ").lower() or default_pers
        if pers not in PERSONALITIES:
            pers = default_pers
        diff = _prompt(f"{names[i]} difficulty [medium]: ").lower() or "medium"
        if diff not in DIFFICULTIES:
            diff = "medium"
        agents.append(make_bot(names[i], pers, diff, rng, use_signals=use_signals))

    config = GameConfig(start_count=start_count,
                        elimination_threshold=threshold,
                        num_jokers=num_jokers)
    # Random first starter.
    game = Game(agents, config, rng)
    game.starter = rng.randrange(len(agents))
    return game


def main(seed: Optional[int] = None) -> None:
    rng = random.Random(seed)
    game = setup_game(rng)
    print("\nStarting game! First to open is chosen at random.\n")
    winner = game.play()
    name = "You" if getattr(winner.agent, "is_human", False) else winner.name
    print(f"\nGame over. Winner: {name}")


if __name__ == "__main__":
    main()
