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

    def __init__(self, name: str, emit: Callable[[str, dict], None]):
        self.name = name
        self._emit = emit
        # Moves arrive here from the Socket.IO handler; act() blocks on get().
        self.inbox: "queue.Queue[Action]" = queue.Queue()
        # The view we last handed the player — used to validate their reply.
        self.pending_view: Optional[TableView] = None

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

    def on_round_result(self, result: RoundResult) -> None:
        self._emit("round_result", result_to_dict(result))
