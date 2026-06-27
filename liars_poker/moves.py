"""Enumerate possible bids and legal raises over the current bid."""

from __future__ import annotations

from typing import List, Optional

from .bids import Bid, Category
from .cards import SUIT_KEYS

_RANKS = list(range(2, 15))  # 2..14 (Ace high)
_FLUSH_HIGHS = list(range(6, 15))  # need 5 distinct ranks <= high, so >= 6


def all_bids() -> List[Bid]:
    """Every distinct bid that can legally be named in the game."""
    bids: List[Bid] = []
    for r in _RANKS:
        bids.append(Bid(Category.HIGH_CARD, rank=r))
        bids.append(Bid(Category.PAIR, rank=r))
        bids.append(Bid(Category.TRIPS, rank=r))
        bids.append(Bid(Category.QUADS, rank=r))
        bids.append(Bid(Category.STRAIGHT, rank=r))
        for suit in SUIT_KEYS:
            bids.append(Bid(Category.STRAIGHT_FLUSH, rank=r, suit=suit))
    for high in _RANKS:
        for low in _RANKS:
            if high > low:
                bids.append(Bid(Category.TWO_PAIR, rank=high, rank2=low))
    for t in _RANKS:
        for p in _RANKS:
            if t != p:
                bids.append(Bid(Category.FULL_HOUSE, rank=t, rank2=p))
    for high in _FLUSH_HIGHS:
        for suit in SUIT_KEYS:
            bids.append(Bid(Category.FLUSH, rank=high, suit=suit))
    return bids


# Cached, sorted weakest -> strongest.
_ALL_SORTED = sorted(all_bids(), key=lambda b: b.sort_key())


def legal_raises(current: Optional[Bid]) -> List[Bid]:
    """All bids that strictly beat ``current`` (all bids if ``current`` is None),
    sorted weakest first."""
    if current is None:
        return list(_ALL_SORTED)
    key = current.sort_key()
    return [b for b in _ALL_SORTED if b.sort_key() > key]
