"""Game engine: round loop, turns, challenges, elimination.

The engine is display-agnostic. Each player is driven by an ``Agent`` (human or
bot) implementing ``act(view) -> Action``. UI concerns live in the CLI layer so
the same engine can back a web server later.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .bids import Bid
from .cards import Card, build_deck, deal
from .evaluator import bid_exists


# --- actions ----------------------------------------------------------------
@dataclass(frozen=True)
class Action:
    kind: str  # "bid" or "challenge"
    bid: Optional[Bid] = None

    @staticmethod
    def make_bid(bid: Bid) -> "Action":
        return Action("bid", bid)

    @staticmethod
    def challenge() -> "Action":
        return Action("challenge")


# --- views passed to agents -------------------------------------------------
@dataclass
class PlayerInfo:
    index: int
    name: str
    card_count: int
    eliminated: bool
    is_you: bool


@dataclass
class TableView:
    my_index: int
    my_hand: List[Card]
    players: List[PlayerInfo]
    current_bid: Optional[Bid]
    current_bidder: Optional[int]
    num_jokers: int
    total_cards_in_play: int
    round_history: List[Tuple[int, Bid]] = field(default_factory=list)


class Agent(ABC):
    name: str
    is_human: bool = False

    @abstractmethod
    def act(self, view: TableView) -> Action:
        ...

    # Optional hooks for UI; default no-ops.
    def on_round_start(self, view: TableView) -> None:
        pass

    def on_event(self, message: str) -> None:
        pass

    def on_round_result(self, result: "RoundResult") -> None:
        """Structured notification after a challenge resolves. Bots use this to
        learn which opponents bluff (whose claims turned out false)."""
        pass


# --- engine -----------------------------------------------------------------
@dataclass
class Player:
    index: int
    agent: Agent
    card_count: int
    eliminated: bool = False
    hand: List[Card] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.agent.name


class RoundResult:
    def __init__(self, loser: int, challenger: int, bidder: int,
                 bid: Bid, existed: bool, pool: List[Card]):
        self.loser = loser
        self.challenger = challenger
        self.bidder = bidder
        self.bid = bid
        self.existed = existed
        self.pool = pool


@dataclass
class GameConfig:
    start_count: int = 1
    elimination_threshold: int = 4
    num_jokers: int = 0


class Game:
    def __init__(self, agents: List[Agent], config: GameConfig,
                 rng: Optional[random.Random] = None):
        self.config = config
        self.rng = rng or random.Random()
        self.players = [
            Player(index=i, agent=a, card_count=config.start_count)
            for i, a in enumerate(agents)
        ]
        self.starter = 0  # index of who opens the next round
        self.observers: List[Agent] = list(agents)

    # ---- helpers -------------------------------------------------------
    def active_players(self) -> List[Player]:
        return [p for p in self.players if not p.eliminated]

    def _broadcast(self, message: str) -> None:
        for a in self.observers:
            a.on_event(message)

    def _ref(self, idx: int):
        """Return (display_name, is_human) for grammar-correct messages."""
        p = self.players[idx]
        human = getattr(p.agent, "is_human", False)
        return ("You" if human else p.name), human

    def _player_infos(self, me: int) -> List[PlayerInfo]:
        return [
            PlayerInfo(p.index, p.name, p.card_count, p.eliminated, p.index == me)
            for p in self.players
        ]

    def _make_view(self, player: Player, current_bid, current_bidder,
                   history) -> TableView:
        total = sum(p.card_count for p in self.active_players())
        return TableView(
            my_index=player.index,
            my_hand=list(player.hand),
            players=self._player_infos(player.index),
            current_bid=current_bid,
            current_bidder=current_bidder,
            num_jokers=self.config.num_jokers,
            total_cards_in_play=total,
            round_history=list(history),
        )

    def _next_active_after(self, idx: int) -> int:
        n = len(self.players)
        j = (idx + 1) % n
        while self.players[j].eliminated:
            j = (j + 1) % n
        return j

    # ---- the round -----------------------------------------------------
    def play_round(self) -> RoundResult:
        active = self.active_players()
        deck = build_deck(self.config.num_jokers)
        counts = [p.card_count for p in active]
        hands = deal(deck, counts, self.rng)
        for p, h in zip(active, hands):
            p.hand = h

        order = [p.index for p in active]
        # rotate so starter is first
        if self.starter in order:
            s = order.index(self.starter)
            order = order[s:] + order[:s]

        for p in active:
            self.players[p.index].agent.on_round_start(
                self._make_view(self.players[p.index], None, None, [])
            )

        current_bid: Optional[Bid] = None
        current_bidder: Optional[int] = None
        history: List[Tuple[int, Bid]] = []

        turn = 0
        while True:
            idx = order[turn % len(order)]
            player = self.players[idx]
            view = self._make_view(player, current_bid, current_bidder, history)
            action = player.agent.act(view)

            if action.kind == "challenge":
                if current_bid is None or current_bidder is None:
                    # illegal opening challenge; coerce to forced minimal bid is
                    # not possible, so treat as a no-op skip (shouldn't happen).
                    raise ValueError("Cannot challenge before any bid is made.")
                pool = [c for p in active for c in p.hand]
                existed = bid_exists(current_bid, pool)
                loser = current_bidder if not existed else idx
                nm, human = self._ref(idx)
                tn, t_human = self._ref(current_bidder)
                calls = "call" if human else "calls"
                target = "your" if t_human else f"{tn}'s"
                self._broadcast(f"{nm} {calls} BULLSHIT on {target} {current_bid}!")
                return RoundResult(loser, idx, current_bidder, current_bid,
                                   existed, pool)

            # action is a bid
            bid = action.bid
            assert bid is not None
            if current_bid is not None and not bid.beats(current_bid):
                raise ValueError(
                    f"{player.name} made non-increasing bid {bid} over {current_bid}"
                )
            current_bid = bid
            current_bidder = idx
            history.append((idx, bid))
            nm, human = self._ref(idx)
            self._broadcast(f"{nm} {'bid' if human else 'bids'}: {bid}")
            turn += 1

    # ---- the game ------------------------------------------------------
    def apply_result(self, result: RoundResult) -> None:
        for a in self.observers:
            a.on_round_result(result)
        loser = self.players[result.loser]
        loser.card_count += 1
        nm, human = self._ref(result.loser)
        loses = "lose" if human else "loses"
        gets = "get" if human else "gets"
        self._broadcast(
            f"The hand {'existed' if result.existed else 'did NOT exist'}. "
            f"{nm} {loses} the round and {gets} a card (now {loser.card_count})."
        )
        if loser.card_count >= self.config.elimination_threshold:
            loser.eliminated = True
            self._broadcast(f"💀 {nm} {'are' if human else 'is'} eliminated!")
            # If the loser is out, the next active player starts.
            self.starter = self._next_active_after(loser.index)
        else:
            self.starter = loser.index

    def winner(self) -> Optional[Player]:
        alive = self.active_players()
        return alive[0] if len(alive) == 1 else None

    def play(self) -> Player:
        """Run rounds until a single winner remains; returns the winner."""
        while self.winner() is None:
            result = self.play_round()
            self.apply_result(result)
        w = self.winner()
        assert w is not None
        wn, whuman = self._ref(w.index)
        self._broadcast(f"🏆 {wn} {'win' if whuman else 'wins'} the game!")
        return w
