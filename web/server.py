"""Flask + Socket.IO server hosting one Liar's Poker game (you vs bots).

Run with:  python -m web.server   (then open http://localhost:5000)

The engine blocks on human input, so each game runs in a Socket.IO background
task. The browser drives a single global session; starting a new game replaces
the previous one.
"""

from __future__ import annotations

import os
import random
from typing import List, Optional

from flask import Flask, send_from_directory
from flask_socketio import SocketIO

from liars_poker.bids import Bid, Category
from liars_poker.bots import DIFFICULTIES, PERSONALITIES, make_bot
from liars_poker.cli import load_name_pool, pick_names
from liars_poker.game import Action, Agent, Game, GameConfig
from liars_poker.moves import legal_raises

from .agent import WebHumanAgent

_STATIC = os.path.join(os.path.dirname(__file__), "static")

app = Flask(__name__, static_folder=_STATIC, static_url_path="/static")
app.config["SECRET_KEY"] = "liars-poker-dev"
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")


class GameSession:
    """One game in progress: the engine, the human bridge, and its thread."""

    def __init__(self, human: WebHumanAgent, game: Game):
        self.human = human
        self.game = game
        # Let the human bridge read everyone's hands at showdown time.
        human.game = game
        self.running = True

    def run(self) -> None:
        try:
            winner = self.game.play()
            name = "You" if getattr(winner.agent, "is_human", False) else winner.name
            socketio.emit("game_over", {"winner": name})
        finally:
            self.running = False


SESSION: Optional[GameSession] = None


def _emit(event: str, data: dict) -> None:
    socketio.emit(event, data)


# ---- routes ----------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(_STATIC, "index.html")


# ---- socket handlers -------------------------------------------------------
@socketio.on("start_game")
def on_start_game(payload):
    global SESSION
    payload = payload or {}
    num_bots = max(1, min(7, int(payload.get("num_bots", 3))))
    start_count = max(1, min(5, int(payload.get("start_count", 2))))
    threshold = max(start_count + 1, min(12, int(payload.get("threshold", start_count + 3))))
    num_jokers = max(0, min(2, int(payload.get("num_jokers", 0))))

    difficulty = str(payload.get("difficulty", "medium")).lower()
    if difficulty not in DIFFICULTIES:
        difficulty = "medium"
    style = str(payload.get("personality", "mixed")).lower()

    rng = random.Random()
    names = pick_names(load_name_pool(), num_bots, rng)
    human = WebHumanAgent("You", _emit, sleep=socketio.sleep)
    agents: List[Agent] = [human]
    pers_keys = list(PERSONALITIES.keys())
    bot_meta = []
    for i in range(num_bots):
        # "mixed" rotates through the personalities; a specific style applies to all.
        pers = style if style in PERSONALITIES else pers_keys[i % len(pers_keys)]
        agents.append(make_bot(names[i], pers, difficulty, rng))
        bot_meta.append({"index": i + 1, "name": names[i],
                         "personality": pers, "difficulty": difficulty})

    config = GameConfig(start_count=start_count,
                        elimination_threshold=threshold,
                        num_jokers=num_jokers)
    game = Game(agents, config, rng)
    game.starter = rng.randrange(len(agents))

    SESSION = GameSession(human, game)
    socketio.emit("game_started", {
        "opponents": names,
        "bots": bot_meta,
        "config": {
            "start_count": start_count,
            "threshold": threshold,
            "num_jokers": num_jokers,
        },
    })
    socketio.start_background_task(SESSION.run)


@socketio.on("continue_round")
def on_continue_round():
    sess = SESSION
    if sess is not None:
        sess.human.continue_box.put(True)


@socketio.on("submit_action")
def on_submit_action(payload):
    sess = SESSION
    if sess is None or sess.human.pending_view is None:
        socketio.emit("error", {"message": "It's not your turn."})
        return
    view = sess.human.pending_view
    payload = payload or {}

    if payload.get("type") == "challenge":
        if view.current_bid is None:
            socketio.emit("error", {"message": "Nothing to call bullshit on yet."})
            return
        sess.human.inbox.put(Action.challenge())
        return

    # Otherwise it's a bid.
    try:
        category = Category[payload["category"]]
    except (KeyError, TypeError):
        socketio.emit("error", {"message": "Pick a hand category."})
        return
    bid = Bid(
        category,
        rank=int(payload.get("rank") or 0),
        rank2=int(payload.get("rank2") or 0),
        suit=(payload.get("suit") or ""),
    )
    if bid in set(legal_raises(view.current_bid)):
        sess.human.inbox.put(Action.make_bid(bid))
    else:
        reason = "doesn't beat the current bid" if view.current_bid else "isn't a valid bid"
        socketio.emit("error", {"message": f"{bid} {reason}."})


def main() -> None:
    port = int(os.environ.get("PORT", "5000"))
    print(f"Liar's Poker web running at http://localhost:{port}")
    socketio.run(app, host="0.0.0.0", port=port,
                 debug=False, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
