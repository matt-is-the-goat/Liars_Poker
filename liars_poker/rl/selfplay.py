"""Self-play support: a pool of frozen policy snapshots that opponent seats play
against, plus a callback that periodically snapshots the live policy.

Opponents driven by these snapshots are a fast NN forward pass (no Monte-Carlo),
which is both far quicker than the heuristic bots and what pushes the agent
toward a less-exploitable strategy. Single-process (DummyVecEnv) so every env
shares one controller; snapshots are only mutated between rollouts.
"""

from __future__ import annotations

import copy

import numpy as np
import torch
from stable_baselines3.common.callbacks import BaseCallback


class SelfPlayController:
    def __init__(self, max_snapshots: int = 6):
        self.snaps: list = []          # frozen policy modules (eval, no grad)
        self.max_snapshots = max_snapshots

    def ready(self) -> bool:
        return len(self.snaps) > 0

    def update(self, policy) -> None:
        snap = copy.deepcopy(policy).to("cpu").eval()
        for p in snap.parameters():
            p.requires_grad_(False)
        self.snaps.append(snap)
        if len(self.snaps) > self.max_snapshots:
            self.snaps.pop(0)

    def pick(self, rng):
        """Return a snapshot OBJECT (not an index) so an in-progress game is
        unaffected if the pool rotates between rollouts."""
        return rng.choice(self.snaps) if self.snaps else None

    def act(self, snap, obs: np.ndarray, mask: np.ndarray) -> int:
        with torch.no_grad():
            obs_t, _ = snap.obs_to_tensor(obs)
            actions, _, _ = snap(
                obs_t, deterministic=False,
                action_masks=np.asarray(mask, dtype=bool).reshape(1, -1),
            )
        return int(np.asarray(actions).reshape(-1)[0])


class SnapshotCallback(BaseCallback):
    """Adds the current policy to the opponent pool every ``snapshot_freq`` steps."""

    def __init__(self, controller: SelfPlayController, snapshot_freq: int, verbose: int = 1):
        super().__init__(verbose)
        self.controller = controller
        self.freq = snapshot_freq
        self._last = 0

    def _on_step(self) -> bool:
        if self.num_timesteps - self._last >= self.freq:
            self._last = self.num_timesteps
            self.controller.update(self.model.policy)
            print(f"[selfplay] snapshot @ {self.num_timesteps:>9} steps "
                  f"(pool={len(self.controller.snaps)})", flush=True)
        return True
