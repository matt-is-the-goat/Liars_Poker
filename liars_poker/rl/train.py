"""Train a MaskablePPO agent for Liar's Poker against a randomized panel of the
heuristic bots, across a mix of player counts.

Overnight launch (from the repo root, using the venv):

    .venv/bin/python -m liars_poker.rl.train --timesteps 20000000 --subproc

Checkpoints land in liars_poker/rl/checkpoints/ every --checkpoint-freq steps,
and win-rate-vs-heuristics is evaluated/printed every --eval-freq steps, so a run
can be stopped any time and the best checkpoint kept.
"""

from __future__ import annotations

import argparse
import os
import random
from typing import List

# One math-thread per process: with SubprocVecEnv each worker otherwise spawns a
# full thread pool, oversubscribing the cores and thrashing (huge sys time). Must
# be set before numpy/torch import (workers re-import this module).
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np
import torch
from sb3_contrib import MaskablePPO
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv

from liars_poker.rl.env import LiarsPokerEnv, RandomOpponentFactory

HERE = os.path.dirname(os.path.abspath(__file__))
CKPT_DIR = os.path.join(HERE, "checkpoints")

# Fixed game settings (randomized per-episode within these): players 2-5,
# 2 jokers, threshold 6, starting cards 1-3.
PLAYERS_RANGE = (2, 5)
JOKERS_RANGE = (2, 2)
START_RANGE = (1, 3)
THRESHOLD_RANGE = (6, 6)


def make_env(difficulties: List[str], seed: int):
    def _init():
        env = LiarsPokerEnv(
            randomize=True,
            players_range=PLAYERS_RANGE,
            jokers_range=JOKERS_RANGE,
            start_range=START_RANGE,
            threshold_range=THRESHOLD_RANGE,
            make_opponent=RandomOpponentFactory(difficulties),
        )
        env.reset(seed=seed)
        return env
    return _init


def build_vec_env(n_envs: int, difficulties: List[str], subproc: bool, seed: int):
    fns = [make_env(difficulties, seed + i) for i in range(n_envs)]
    return (SubprocVecEnv(fns) if subproc else DummyVecEnv(fns))


def eval_winrate(model, num_players: int, difficulties: List[str],
                 n_games: int = 80, seed: int = 10_000) -> float:
    """Win rate of the (deterministic) policy vs a random heuristic panel, at a
    FIXED config (players given; 2 jokers, threshold 6, 2 starting cards)."""
    env = LiarsPokerEnv(num_players=num_players, start_count=2,
                        elimination_threshold=6, num_jokers=2,
                        make_opponent=RandomOpponentFactory(difficulties))
    wins = 0
    for ep in range(n_games):
        obs, info = env.reset(seed=seed + ep)
        done = False
        while not done:
            mask = env.action_masks()
            action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            obs, _, term, trunc, info = env.step(int(action))
            done = term or trunc
        wins += int(info["winner"] == env.agent_seat)
    return wins / n_games


class EvalWinRateCallback(BaseCallback):
    def __init__(self, eval_freq: int, difficulties: List[str], verbose: int = 1):
        super().__init__(verbose)
        self.eval_freq = eval_freq
        self.difficulties = difficulties
        self.best = -1.0

    def _on_step(self) -> bool:
        if self.num_timesteps % self.eval_freq < self.training_env.num_envs:
            line = []
            avg = 0.0
            panels = (2, 3, 4, 5)
            for npl in panels:
                wr = eval_winrate(self.model, npl, self.difficulties)
                chance = 1.0 / npl
                line.append(f"{npl}p {wr:.0%}(chance {chance:.0%})")
                avg += wr
            avg /= len(panels)
            print(f"[eval @ {self.num_timesteps:>9} steps]  " + " | ".join(line)
                  + f"  avg={avg:.0%}", flush=True)
            self.logger.record("eval/avg_winrate", avg)
            if avg > self.best:
                self.best = avg
                self.model.save(os.path.join(CKPT_DIR, "best"))
                print(f"  -> new best avg winrate {avg:.0%}; saved checkpoints/best", flush=True)
        return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--timesteps", type=int, default=2_000_000)
    p.add_argument("--n-envs", type=int, default=8)
    p.add_argument("--subproc", action="store_true", help="parallel envs (faster)")
    p.add_argument("--difficulties", default="easy,medium,hard",
                   help="comma list the opponents sample from")
    p.add_argument("--checkpoint-freq", type=int, default=200_000)
    p.add_argument("--eval-freq", type=int, default=100_000)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    torch.set_num_threads(1)
    os.makedirs(CKPT_DIR, exist_ok=True)
    difficulties = [d.strip() for d in args.difficulties.split(",") if d.strip()]
    random.seed(args.seed)
    np.random.seed(args.seed)

    venv = build_vec_env(args.n_envs, difficulties, args.subproc, args.seed)
    print(f"Training MaskablePPO | envs={args.n_envs} | players 2-5, 2 jokers, "
          f"threshold 6, start 1-3 (randomized) | opponents={difficulties} "
          f"| target={args.timesteps:,} steps", flush=True)

    model = MaskablePPO(
        "MlpPolicy", venv,
        n_steps=512, batch_size=512, n_epochs=4,
        gamma=0.995, gae_lambda=0.95, ent_coef=0.01,
        learning_rate=3e-4,
        policy_kwargs=dict(net_arch=[256, 256]),
        verbose=0, seed=args.seed,
    )

    callbacks = [
        CheckpointCallback(save_freq=max(args.checkpoint_freq // args.n_envs, 1),
                           save_path=CKPT_DIR, name_prefix="ppo"),
        EvalWinRateCallback(args.eval_freq, difficulties),
    ]
    try:
        model.learn(total_timesteps=args.timesteps, callback=callbacks, progress_bar=False)
    finally:
        model.save(os.path.join(CKPT_DIR, "final"))
        print("Saved checkpoints/final", flush=True)


if __name__ == "__main__":
    main()
