"""Convert engine objects to JSON-friendly dicts for the browser."""

from __future__ import annotations

from typing import List, Optional

from liars_poker.bids import Bid
from liars_poker.cards import Card
from liars_poker.game import RoundResult, TableView


def card_to_dict(c: Card) -> dict:
    return {
        "text": str(c),
        "rank": c.rank,
        "suit": c.suit,
        "value": c.value,
        "is_joker": c.is_joker,
    }


def bid_to_dict(b: Optional[Bid]) -> Optional[dict]:
    if b is None:
        return None
    return {
        "text": str(b),
        "category": b.category.name,
        "rank": b.rank,
        "rank2": b.rank2,
        "suit": b.suit,
    }


def view_to_dict(view: TableView) -> dict:
    return {
        "my_index": view.my_index,
        "my_hand": [card_to_dict(c) for c in view.my_hand],
        "players": [
            {
                "index": p.index,
                "name": p.name,
                "card_count": p.card_count,
                "eliminated": p.eliminated,
                "is_you": p.is_you,
            }
            for p in view.players
        ],
        "current_bid": bid_to_dict(view.current_bid),
        "current_bidder": view.current_bidder,
        "num_jokers": view.num_jokers,
        "total_cards_in_play": view.total_cards_in_play,
    }


def result_to_dict(result: RoundResult) -> dict:
    pool = sorted(result.pool, key=lambda c: (c.is_joker, c.value))
    return {
        "existed": result.existed,
        "loser": result.loser,
        "challenger": result.challenger,
        "bidder": result.bidder,
        "bid": bid_to_dict(result.bid),
        "pool": [card_to_dict(c) for c in pool],
    }
