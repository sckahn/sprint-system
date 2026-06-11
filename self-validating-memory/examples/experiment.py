"""Controlled experiment: does the SVMP agent actually learn — and does the
budget economy actually punish passivity?

Runs the full self-validating agent against a passive control (learning
disabled) across several seeds and prints a comparison.

    cd self-validating-memory
    python examples/experiment.py
"""
from __future__ import annotations

import statistics as st

from svmp.train import train

SEEDS = [0, 1, 2, 3, 4]
STEPS = 2500
CHANCE = 0.25  # 4 classes


def run(learn: bool) -> list[dict]:
    out = []
    for s in SEEDS:
        out.append(train(phase=1, steps=STEPS, seed=s, verbose=False, learn=learn))
    return out


def summarize(name: str, runs: list[dict]) -> None:
    acc = [r["final_accuracy"] for r in runs]
    ece = [r["ece"] for r in runs]
    survived = sum(1 for r in runs if r["budget"]["alive"])
    steps = [r["steps_run"] for r in runs]
    print(f"\n[{name}]  (n={len(runs)} seeds, {STEPS} steps each)")
    print(f"  final accuracy : {st.mean(acc):.3f} ± {st.pstdev(acc):.3f}  "
          f"(min {min(acc):.2f}, max {max(acc):.2f})  | chance={CHANCE}")
    print(f"  ECE            : {st.mean(ece):.3f} ± {st.pstdev(ece):.3f}")
    print(f"  survived       : {survived}/{len(runs)} agents stayed alive")
    print(f"  steps survived : {st.mean(steps):.0f} avg "
          f"(min {min(steps)}, max {max(steps)})")


def main() -> None:
    print("=" * 64)
    print("SVMP controlled experiment — full agent vs passive control")
    print("=" * 64)

    full = run(learn=True)
    passive = run(learn=False)

    summarize("FULL  (three-factor + backprop ON)", full)
    summarize("PASSIVE  (all learning OFF)", passive)

    # Learning curve of the first full-agent seed.
    print("\nLearning curve (full agent, seed 0): step -> rolling accuracy")
    for step, acc in full[0]["curve"]:
        bar = "#" * int(acc * 40)
        print(f"  {step:5d} | {acc:.2f} {bar}")

    full_acc = st.mean(r["final_accuracy"] for r in full)
    pass_acc = st.mean(r["final_accuracy"] for r in passive)
    print("\nVerdict:")
    print(f"  full agent learns: {full_acc:.2f} vs chance {CHANCE:.2f} "
          f"and passive {pass_acc:.2f}")
    print(f"  budget economy bites: passive survived "
          f"{sum(1 for r in passive if r['budget']['alive'])}/{len(passive)}, "
          f"full survived {sum(1 for r in full if r['budget']['alive'])}/{len(full)}")


if __name__ == "__main__":
    main()
