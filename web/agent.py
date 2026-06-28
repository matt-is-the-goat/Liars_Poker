"""The browser-backed human agent.

``WebHumanAgent`` plugs into the engine like any other ``Agent``, but instead of
reading from a terminal it emits the table state to the connected browser and
blocks until the browser submits a move (delivered through ``inbox``).
"""

from __future__ import annotations

import queue
from typing import Callable, Optional

from liars_poker.game import Action, Agent, RoundResult, TableView

from .serialize import result_to_dict, view_to_dict


class WebHumanAgent(Agent):
    is_human = True

    def __init__(self, name: str, emit: Callable[[str, dict], None],
                 sleep: Optional[Callable[[float], None]] = None):
        self.name = name
        self._emit = emit
        # Pauses the game-loop thread so the browser can show the showdown flip.
        self._sleep = sleep or (lambda _s: None)
        # Moves arrive here from the Socket.IO handler; act() blocks on get().
        self.inbox: "queue.Queue[Action]" = queue.Queue()
        # The browser drops a token here when the player clicks "Next hand".
        self.continue_box: "queue.Queue[bool]" = queue.Queue()
        # The view we last handed the player, used to validate their reply.
        self.pending_view: Optional[TableView] = None
        # Set by the session so the showdown reveal can read everyone's hands.
        self.game = None

    def act(self, view: TableView) -> Action:
        self.pending_view = view
        self._emit("your_turn", {
            "view": view_to_dict(view),
            "can_challenge": view.current_bid is not None,
        })
        action = self.inbox.get()  # blocks until the browser replies
        self.pending_view = None
        return action

    def on_round_start(self, view: TableView) -> None:
        # Push the fresh hand so the UI updates before it's our turn.
        self._emit("state", {"view": view_to_dict(view)})

    def on_event(self, message: str) -> None:
        self._emit("log", {"message": message})
        bid = self._parse_bid(message)
        if bid is not None:
            # Push a structured per-bid update so each seat shows its latest call
            # live as the round is played.
            self._emit("bid_made", bid)
            if not bid["is_you"]:
                # Pause after each opponent's bid so the player can read it.
                self._sleep(1.0)

    def _parse_bid(self, message: str) -> Optional[dict]:
        """Pull (player, bid text) out of a '<name> bids: <bid>' broadcast."""
        for sep, is_you in ((" bids: ", False), (" bid: ", True)):
            if sep in message:
                name, _, text = message.partition(sep)
                return {"index": self._index_for(name, is_you),
                        "name": name, "text": text, "is_you": is_you}
        return None

    def _index_for(self, name: str, is_you: bool) -> Optional[int]:
        if self.game is None:
            return None
        for p in self.game.players:
            human = getattr(p.agent, "is_human", False)
            if is_you and human:
                return p.index
            if not is_you and not human and p.name == name:
                return p.index
        return None

    def _is_eliminated(self) -> bool:
        if self.game is None:
            return False
        return any(p.agent is self and p.eliminated for p in self.game.players)

    def on_round_result(self, result: RoundResult) -> None:
        # Called first thing in apply_result, so hands are still dealt; read them now.
        self._emit("round_result", result_to_dict(result, self.game))
        if self._is_eliminated():
            # Already out and just spectating, so auto-advance so they're not forced
            # to click through bot-only rounds.
            self._sleep(2.0)
        else:
            # Hold the game-loop thread until the player clicks "Next hand".
            self.continue_box.get()
