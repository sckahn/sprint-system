"""Training loop wiring the agent to a task (§6).

Run directly:

    python -m svmp.train --phase 1 --steps 2000

or import :func:`train` for programmatic use / tests.
"""
from __future__ import annotations

import argparse
from collections import deque

from .agent import SelfValidatingAgent
from .config import SVMPConfig
from .tasks import CalibrationBanditTask, PositionalOrderingTask


def train(phase: int = 1, steps: int = 2000, log_every: int = 200,
          seed: int = 0, verbose: bool = True) -> dict:
    """Run ``steps`` of self-validation learning. Returns final metrics."""
    cfg = SVMPConfig(seed=seed)
    reward_mode = "positional" if phase >= 2 else "independent"

    if reward_mode == "positional":
        task = PositionalOrderingTask(cfg.n_classes, seed=seed)
    else:
        task = CalibrationBanditTask(cfg.n_classes, seed=seed)
    input_dim = task.feature_dim

    agent = SelfValidatingAgent(cfg, input_dim, reward_mode=reward_mode)

    acc_window: deque[int] = deque(maxlen=log_every)
    rewards: deque[float] = deque(maxlen=log_every)
    history = []

    for t in range(1, steps + 1):
        if reward_mode == "positional":
            x, target, order = task.sample()
            log = agent.step(x, target, order_target=order)
        else:
            x, target = task.sample()
            log = agent.step(x, target)

        acc_window.append(1 if log.correct else 0)
        rewards.append(log.reward)

        if not log.alive:
            if verbose:
                print(f"[step {t}] budget exhausted — agent died. "
                      f"(survived {t} rounds)")
            break

        if verbose and t % log_every == 0:
            acc = sum(acc_window) / len(acc_window)
            avg_r = sum(rewards) / len(rewards)
            m = agent.metrics()
            print(f"[step {t:5d}] acc={acc:.2f} reward={avg_r:+.2f} "
                  f"ece={m['ece']:.3f} vault={m['vault']['size']:3d} "
                  f"conv={m['vault']['mean_conviction']:.2f} "
                  f"budget={m['budget']['balance']:7.1f} "
                  f"maint={m['budget']['maintenance']:.2f}")
        history.append(log)

    final = agent.metrics()
    final["steps_run"] = len(history)
    final["final_accuracy"] = (sum(acc_window) / len(acc_window)) if acc_window else 0.0
    if verbose:
        print(f"\nFinal: acc={final['final_accuracy']:.2f} "
              f"ece={final['ece']:.3f} vault={final['vault']['size']} "
              f"alive={final['budget']['alive']}")
    return final


def main() -> None:
    p = argparse.ArgumentParser(description="Train the SVMP self-validating agent")
    p.add_argument("--phase", type=int, default=1, choices=[1, 2],
                   help="1=calibration bandit (independent reward), "
                        "2=positional ordering (structural reward)")
    p.add_argument("--steps", type=int, default=2000)
    p.add_argument("--log-every", type=int, default=200)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    train(phase=args.phase, steps=args.steps, log_every=args.log_every,
          seed=args.seed)


if __name__ == "__main__":
    main()
