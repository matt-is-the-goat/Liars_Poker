"""Entry point for the Liar's Poker CLI.

Usage:
    python main.py            # interactive game vs bots
    python main.py --seed 42  # reproducible shuffle/bots
"""

import argparse

from liars_poker.cli import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Play Liar's Poker against bots.")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducible games.")
    args = parser.parse_args()
    main(seed=args.seed)
