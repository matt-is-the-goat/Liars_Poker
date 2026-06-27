"""Cards, ranks, suits, and the deck."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional

# Rank values. Ace is high (14). The wheel straight (A-2-3-4-5) is handled
# specially in the evaluator by also letting the ace act as 1.
RANK_VALUES = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "10": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
}
VALUE_TO_RANK = {v: k for k, v in RANK_VALUES.items()}
RANKS: List[str] = list(RANK_VALUES.keys())

SUITS = {
    "S": "♠",
    "H": "♥",
    "D": "♦",
    "C": "♣",
}
SUIT_KEYS = list(SUITS.keys())


@dataclass(frozen=True)
class Card:
    """A single card. If ``is_joker`` is True, rank/suit are ignored."""

    rank: Optional[str] = None
    suit: Optional[str] = None
    is_joker: bool = False

    @property
    def value(self) -> int:
        if self.is_joker:
            return 0
        return RANK_VALUES[self.rank]

    def __str__(self) -> str:
        if self.is_joker:
            return "🃏"
        return f"{self.rank}{SUITS[self.suit]}"

    def __repr__(self) -> str:
        return str(self)


def build_deck(num_jokers: int = 0) -> List[Card]:
    """Return a fresh standard 52-card deck plus ``num_jokers`` jokers."""
    deck = [Card(rank=r, suit=s) for s in SUIT_KEYS for r in RANKS]
    deck.extend(Card(is_joker=True) for _ in range(num_jokers))
    return deck


def deal(deck: List[Card], counts: List[int], rng: random.Random) -> List[List[Card]]:
    """Shuffle ``deck`` and deal ``counts[i]`` cards to player ``i``.

    Returns a list of hands. Assumes ``sum(counts) <= len(deck)``.
    """
    shuffled = deck[:]
    rng.shuffle(shuffled)
    hands: List[List[Card]] = []
    idx = 0
    for n in counts:
        hands.append(shuffled[idx:idx + n])
        idx += n
    return hands
