"""Sanity tests for card evaluation, bid ordering, and a full bot-only game."""

import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from liars_poker.bids import Bid, Category
from liars_poker.cards import Card
from liars_poker.evaluator import bid_exists
from liars_poker.moves import legal_raises
from liars_poker.bots import make_bot
from liars_poker.game import Game, GameConfig


def C(rank, suit):
    return Card(rank=rank, suit=suit)


JOKER = Card(is_joker=True)


def check(cond, label):
    print(("PASS" if cond else "FAIL"), label)
    assert cond, label


def test_pair():
    pool = [C("9", "S"), C("9", "H"), C("3", "D")]
    check(bid_exists(Bid(Category.PAIR, rank=9), pool), "pair of 9s exists")
    check(not bid_exists(Bid(Category.PAIR, rank=10), pool), "pair of 10s absent")
    # joker completes the pair
    pool2 = [C("9", "S"), JOKER]
    check(bid_exists(Bid(Category.PAIR, rank=9), pool2), "joker completes pair of 9s")


def test_trips_with_joker():
    pool = [C("9", "S"), C("9", "H"), JOKER]
    check(bid_exists(Bid(Category.TRIPS, rank=9), pool), "two 9s + joker = trips")
    check(not bid_exists(Bid(Category.QUADS, rank=9), pool), "not enough for quads")
    pool2 = [C("9", "S"), C("9", "H"), JOKER, JOKER]
    check(bid_exists(Bid(Category.QUADS, rank=9), pool2), "two 9s + two jokers = quads")


def test_two_pair():
    pool = [C("Q", "S"), C("Q", "H"), C("3", "D"), C("3", "C")]
    check(bid_exists(Bid(Category.TWO_PAIR, rank=12, rank2=3), pool), "QQ33 two pair")
    # ordering: Q+3 high pair beats 9+8 high pair
    a = Bid(Category.TWO_PAIR, rank=12, rank2=3)
    b = Bid(Category.TWO_PAIR, rank=9, rank2=8)
    check(a.beats(b), "QQ over 33 beats 99 over 88 (compare high pair first)")


def test_straight():
    pool = [C("3", "S"), C("4", "H"), C("5", "D"), C("6", "C"), C("7", "S")]
    check(bid_exists(Bid(Category.STRAIGHT, rank=5), pool), "3-7 straight contains 5")
    check(bid_exists(Bid(Category.STRAIGHT, rank=7), pool), "3-7 straight contains 7")
    check(not bid_exists(Bid(Category.STRAIGHT, rank=8), pool), "no straight with an 8")
    # improve by raising the called rank, even same straight
    check(Bid(Category.STRAIGHT, rank=6).beats(Bid(Category.STRAIGHT, rank=5)),
          "straight containing 6 beats containing 5")
    # wheel
    wheel = [C("A", "S"), C("2", "H"), C("3", "D"), C("4", "C"), C("5", "S")]
    check(bid_exists(Bid(Category.STRAIGHT, rank=5), wheel), "wheel A-5 contains 5")


def test_straight_joker():
    pool = [C("3", "S"), C("4", "H"), JOKER, C("6", "C"), C("7", "S")]
    check(bid_exists(Bid(Category.STRAIGHT, rank=6), pool), "joker fills 5 in 3-7")


def test_flush():
    pool = [C("A", "H"), C("J", "H"), C("9", "H"), C("4", "H"), C("2", "H")]
    check(bid_exists(Bid(Category.FLUSH, rank=14, suit="H"), pool), "ace-high H flush")
    # queen-high should fail: ace counted out, only 4 hearts <= Q
    check(not bid_exists(Bid(Category.FLUSH, rank=12, suit="H"), pool),
          "queen-high H flush fails (ace excluded)")
    # lower called rank is stronger
    check(Bid(Category.FLUSH, rank=12, suit="H").beats(Bid(Category.FLUSH, rank=14, suit="H")),
          "queen-high beats ace-high (lower is harder)")
    # called rank must be present
    pool2 = [C("A", "H"), C("K", "H"), C("9", "H"), C("4", "H"), C("2", "H")]
    check(not bid_exists(Bid(Category.FLUSH, rank=12, suit="H"), pool2),
          "queen-high fails when no queen present")


def test_full_house():
    pool = [C("8", "S"), C("8", "H"), C("8", "D"), C("2", "C"), C("2", "S")]
    check(bid_exists(Bid(Category.FULL_HOUSE, rank=8, rank2=2), pool), "888 22 full house")
    check(Bid(Category.FULL_HOUSE, rank=9, rank2=2).beats(
        Bid(Category.FULL_HOUSE, rank=8, rank2=14)), "trips rank dominates pair rank")


def test_hierarchy():
    order = [
        Bid(Category.HIGH_CARD, rank=14),
        Bid(Category.PAIR, rank=2),
        Bid(Category.TWO_PAIR, rank=3, rank2=2),
        Bid(Category.TRIPS, rank=2),
        Bid(Category.STRAIGHT, rank=2),
        Bid(Category.FLUSH, rank=14, suit="S"),
        Bid(Category.FULL_HOUSE, rank=2, rank2=3),
        Bid(Category.QUADS, rank=2),
        Bid(Category.STRAIGHT_FLUSH, rank=2, suit="S"),
    ]
    for i in range(len(order) - 1):
        check(order[i + 1].beats(order[i]),
              f"{order[i+1].category.name} beats {order[i].category.name}")


def test_legal_raises():
    cur = Bid(Category.PAIR, rank=9)
    raises = legal_raises(cur)
    check(all(b.beats(cur) for b in raises), "all legal raises beat current")
    check(Bid(Category.PAIR, rank=10) in raises, "pair of 10s is a legal raise over pair of 9s")
    check(Bid(Category.PAIR, rank=8) not in raises, "pair of 8s not a legal raise")


def test_full_game():
    rng = random.Random(7)
    agents = [
        make_bot("Trust", "trusting", "medium", rng),
        make_bot("Bal", "balanced", "medium", rng),
        make_bot("Liar", "liar", "medium", rng),
    ]
    cfg = GameConfig(start_count=2, elimination_threshold=4, num_jokers=1)
    game = Game(agents, cfg, rng)
    winner = game.play()
    check(winner is not None, "bot-only game produced a winner")
    check(sum(not p.eliminated for p in game.players) == 1, "exactly one survivor")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        print(f"\n--- {fn.__name__} ---")
        fn()
    print("\nAll tests passed.")
