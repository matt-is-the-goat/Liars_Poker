"""Validity checks: does a bid actually exist in a revealed pool of cards?

Jokers are wildcards resolved in favour of the claim: each joker may become
whatever single card best helps satisfy the bid.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Iterable, List

from .bids import Bid, Category
from .cards import Card, SUIT_KEYS


class PoolStats:
    """Pre-computed counts over a pool of cards for fast bid checking."""

    def __init__(self, cards: Iterable[Card]):
        self.rank_counts: Counter = Counter()
        self.suit_rank: Dict[str, Counter] = defaultdict(Counter)
        self.jokers = 0
        for c in cards:
            if c.is_joker:
                self.jokers += 1
            else:
                self.rank_counts[c.value] += 1
                self.suit_rank[c.suit][c.value] += 1

    def of_rank(self, value: int) -> int:
        return self.rank_counts[value]

    def suit_of_rank(self, suit: str, value: int) -> int:
        return self.suit_rank[suit][value]


# All straight windows as sets of rank values. The wheel (A-2-3-4-5) lets the
# ace (14) act low.
_STRAIGHT_WINDOWS: List[frozenset] = [
    frozenset(range(start, start + 5)) for start in range(2, 11)
] + [frozenset({14, 2, 3, 4, 5})]


def _straight_ok(present_ok, jokers: int, contains: int) -> bool:
    """Is there a 5-straight containing rank ``contains`` we can complete?

    ``present_ok(value)`` returns True if a real card of that rank exists in the
    relevant set (whole pool, or one suit for a straight flush).
    """
    for window in _STRAIGHT_WINDOWS:
        if contains not in window:
            continue
        missing = sum(1 for v in window if not present_ok(v))
        if missing <= jokers:
            return True
    return False


def bid_exists(bid: Bid, cards: Iterable[Card]) -> bool:
    """Return True if ``bid`` can be satisfied by ``cards`` (jokers as wild)."""
    s = PoolStats(cards)
    j = s.jokers
    cat = bid.category

    if cat == Category.HIGH_CARD:
        return s.of_rank(bid.rank) + j >= 1
    if cat == Category.PAIR:
        return s.of_rank(bid.rank) + j >= 2
    if cat == Category.TRIPS:
        return s.of_rank(bid.rank) + j >= 3
    if cat == Category.QUADS:
        return s.of_rank(bid.rank) + j >= 4
    if cat == Category.QUINTS:
        return s.of_rank(bid.rank) + j >= 5
    if cat == Category.SEXES:
        return s.of_rank(bid.rank) + j >= 6

    if cat == Category.TWO_PAIR:
        need = max(0, 2 - s.of_rank(bid.rank)) + max(0, 2 - s.of_rank(bid.rank2))
        return need <= j
    if cat == Category.FULL_HOUSE:
        need = max(0, 3 - s.of_rank(bid.rank)) + max(0, 2 - s.of_rank(bid.rank2))
        return need <= j
    if cat == Category.MANSION:
        need = max(0, 4 - s.of_rank(bid.rank)) + max(0, 3 - s.of_rank(bid.rank2))
        return need <= j
    if cat == Category.HOTEL:
        need = max(0, 5 - s.of_rank(bid.rank)) + max(0, 4 - s.of_rank(bid.rank2))
        return need <= j

    if cat == Category.STRAIGHT:
        return _straight_ok(lambda v: s.of_rank(v) > 0, j, bid.rank)
    if cat == Category.STRAIGHT_FLUSH:
        return _straight_ok(lambda v: s.suit_of_rank(bid.suit, v) > 0, j, bid.rank)

    if cat == Category.FLUSH:
        real = sum(s.suit_of_rank(bid.suit, v) for v in range(2, bid.rank + 1))
        has_r = s.suit_of_rank(bid.suit, bid.rank) > 0
        return real + j >= 5 and (has_r or j >= 1)

    return False
