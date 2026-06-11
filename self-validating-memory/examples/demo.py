"""Minimal end-to-end demo of the SVMP self-validating agent.

Run:

    cd self-validating-memory
    python examples/demo.py

Watch three things co-evolve:
  • accuracy rises as the three-factor rule consolidates a good decision policy,
  • the budget *recovers* once earned reward outpaces tightening maintenance
    (computation as a survival resource), and
  • the vault grows then stabilises as decay/pruning forget unverified entries.
"""
from svmp.train import train

if __name__ == "__main__":
    print("=== Phase 1: calibration bandit (independent reward) ===")
    train(phase=1, steps=2500, log_every=300, seed=0)

    print("\n=== Phase 2: positional ordering (structural reward) ===")
    train(phase=2, steps=1200, log_every=300, seed=0)
