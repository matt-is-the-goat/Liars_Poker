"""Web front end for Liar's Poker.

A thin Flask + Socket.IO layer over the existing game engine. The engine is
pull-based (``agent.act(view)`` blocks until a decision), so the game loop runs
in a background thread and the human's ``act`` blocks on a queue that the
WebSocket fills when the browser submits a move. Nothing in ``liars_poker`` is
modified.
"""
