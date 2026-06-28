"""Tests for the RL Gym environment. Skipped if gymnasium isn't installed
(the core engine / base interpreter doesn't need it)."""

import random

import pytest

pytest.importorskip("gymnasium")
np = pytest.importorskip("numpy")

from liars_poker.rl.env import (  # noqa: E402
    LiarsPokerEnv, N_ACTIONS, NUM_RAISE_SLOTS, CHALLENGE,
)
from liars_poker.moves import legal_raises  # noqa: E402


def test_spaces_and_reset():
    env = LiarsPokerEnv(num_players=3, num_jokers=2)
    obs, info = env.reset(seed=0)
    assert env.observation_space.contains(obs)
    assert env.action_masks().shape == (N_ACTIONS,)
    assert env.action_masks().any(), "at least one legal action at reset"


def test_random_rollouts_terminate():
    env = LiarsPokerEnv(num_players=3, start_count=2, elimination_threshold=5, num_jokers=1)
    rng = random.Random(0)
    for ep in range(40):
        obs, info = env.reset(seed=ep)
        done = False
        steps = 0
        while not done:
            mask = env.action_masks()
            assert mask.any()
            a = rng.choice(np.flatnonzero(mask).tolist())
            obs, r, term, trunc, info = env.step(a)
            assert env.observation_space.contains(obs)
            assert np.isfinite(r)
            done = term or trunc
            steps += 1
            assert steps < 5000


def test_compact_action_space():
    env = LiarsPokerEnv(num_players=2, num_jokers=0)
    env.reset(seed=3)
    # Opening (no standing bid): challenge illegal, some raise slots legal.
    env.current_bid = None
    mask = env.action_masks()
    assert not mask[CHALLENGE]
    assert mask[1:].any()
    # With a standing bid: challenge legal, and every legal slot maps to a bid
    # that actually beats the current one.
    env.current_bid = legal_raises(None)[50]
    mask = env.action_masks()
    assert mask[CHALLENGE]
    slots = env._raise_slots()
    for j in range(NUM_RAISE_SLOTS):
        if mask[1 + j]:
            assert slots[j] is not None and slots[j].beats(env.current_bid)


def test_challenge_is_explorable_fraction():
    # The whole point of the compact space: challenge isn't drowned out.
    assert N_ACTIONS <= 40


def test_determinism():
    a = LiarsPokerEnv(num_players=3, num_jokers=2)
    b = LiarsPokerEnv(num_players=3, num_jokers=2)
    o1, _ = a.reset(seed=42)
    o2, _ = b.reset(seed=42)
    assert np.array_equal(o1, o2)
