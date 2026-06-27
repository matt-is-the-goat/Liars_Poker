"""Bid types and the strict-ordering comparison rules.

A bid is a claim that a particular poker hand exists in the combined cards of
all players. Bids are totally ordered; a player must strictly beat the previous
bid. See PROJECT_MEMORY.md for the rule definitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Tuple

from .cards import SUITS, VALUE_TO_RANK


class Category(IntEnum):
    HIGH_CARD = 0
    PAIR = 1
    TWO_PAIR = 2
    TRIPS = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    QUADS = 7
    STRAIGHT_FLUSH = 8


@dataclass(frozen=True)
class Bid:
    """A poker-hand claim.

    Fields used depend on ``category``:
      HIGH_CARD/PAIR/TRIPS/QUADS : ``rank``
      TWO_PAIR                   : ``rank`` (high pair), ``rank2`` (low pair)
      STRAIGHT                   : ``rank`` (a rank the straight contains)
      FLUSH                      : ``rank`` (high card), ``suit``
      FULL_HOUSE                 : ``rank`` (trips), ``rank2`` (pair)
      STRAIGHT_FLUSH             : ``rank`` (a rank it contains), ``suit``

    Ranks are stored as integer values (2..14, Ace high).
    """

    category: Category
    rank: int = 0
    rank2: int = 0
    suit: str = ""

    def sort_key(self) -> Tuple:
        """Total-ordering key. Higher key = stronger bid."""
        c = int(self.category)
        if self.category == Category.TWO_PAIR:
            return (c, self.rank, self.rank2)
        if self.category == Category.FULL_HOUSE:
            return (c, self.rank, self.rank2)
        if self.category == Category.FLUSH:
            # Lower called rank is harder to make, so it is stronger.
            return (c, -self.rank)
        # Single-rank categories (and straights/straight-flushes): higher rank wins.
        return (c, self.rank)

    def beats(self, other: "Bid") -> bool:
        return self.sort_key() > other.sort_key()

    # ---- display -------------------------------------------------------
    def describe(self) -> str:
        r = VALUE_TO_RANK.get(self.rank, "?")
        r2 = VALUE_TO_RANK.get(self.rank2, "?")
        s = SUITS.get(self.suit, self.suit)
        if self.category == Category.HIGH_CARD:
            return f"{r} high"
        if self.category == Category.PAIR:
            return f"pair of {r}s"
        if self.category == Category.TWO_PAIR:
            return f"two pair, {r}s and {r2}s"
        if self.category == Category.TRIPS:
            return f"three {r}s"
        if self.category == Category.STRAIGHT:
            return f"straight containing a {r}"
        if self.category == Category.FLUSH:
            return f"{r}-high {s} flush"
        if self.category == Category.FULL_HOUSE:
            return f"full house, {r}s over {r2}s"
        if self.category == Category.QUADS:
            return f"four {r}s"
        if self.category == Category.STRAIGHT_FLUSH:
            return f"{s} straight flush containing a {r}"
        return "?"

    def __str__(self) -> str:
        return self.describe()
