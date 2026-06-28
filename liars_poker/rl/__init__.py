"""Reinforcement-learning layer for Liar's Poker (Phase 3).

``env.LiarsPokerEnv`` is a Gymnasium environment that drives the game's turn loop
in step form (the core engine is pull/blocking, so we re-orchestrate it here
using the engine's pure functions). The learning agent occupies one seat; the
others are pluggable ``Agent`` policies (heuristic bots now, policy snapshots for
self-play later). Action masking exposes only legal bids/challenges each turn.
"""
