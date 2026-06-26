"""Catastrophic-forgetting study — does the architecture solve stability-plasticity?

The design claims its gated consolidation (closed gate → weights frozen) plus an
external vault (old contexts retrievable) should let the agent learn new tasks
without destroying old knowledge. We test that claim directly: train the agent on
a sequence of disjoint class groups (task A → task B) and measure how much task-A
accuracy collapses after learning task B.

We compare three conditions to attribute any protection to a mechanism:

  full     — vault + gated consolidation (the full design)
  no_vault — external memory ablated (decision head only)
  no_gate  — gate forced open (always consolidate; no gated protection)

Metric: forgetting = (task-A accuracy right after learning A) − (task-A accuracy
after also learning B). 0 = perfect retention; ~1 = total catastrophic forgetting.
Chance is 0.25 (4 classes per task). n=4 seeds.

    PYTHONPATH=. python examples/experiment_continual.py
"""
from __future__ import annotations

import statistics as st

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.tasks import SplitContinualTask
from svmp.continual import run_continual, forgetting, final_accuracy

SEEDS = [0, 1, 2, 3]
STEPS_PER_TASK = 2500
CONDITIONS = {
    "full":     dict(use_vault=True,  force_gate=None),
    "no_vault": dict(use_vault=False, force_gate=None),
    "no_gate":  dict(use_vault=True,  force_gate=1.0),
}


def run_condition(name: str, knobs: dict) -> dict:
    forgets, finals, peaks = [], [], []
    for seed in SEEDS:
        cfg = SVMPConfig(seed=seed, n_classes=8)
        agent = SelfValidatingAgent(cfg, 16, **knobs)
        task = SplitContinualTask(n_classes=8, n_tasks=2, feature_dim=16, seed=seed)
        acc = run_continual(agent, task, STEPS_PER_TASK)
        forgets.append(forgetting(acc))
        finals.append(final_accuracy(acc))
        peaks.append(acc[0][0])
    return {
        "peak_A": st.mean(peaks),
        "forget": st.mean(forgets),
        "forget_sd": st.pstdev(forgets),
        "final": st.mean(finals),
    }


def main() -> None:
    print("Catastrophic forgetting — split continual learning (8 classes / 2 tasks)")
    print(f"  {STEPS_PER_TASK} steps/task, {len(SEEDS)} seeds, chance = 0.25\n")
    print(f"  {'condition':9s} | peak-A | forgetting (±sd)   | final acc")
    print(f"  {'-'*9} | {'-'*6} | {'-'*18} | {'-'*9}")
    results = {}
    for name, knobs in CONDITIONS.items():
        r = run_condition(name, knobs)
        results[name] = r
        print(f"  {name:9s} | {r['peak_A']:.3f}  | "
              f"{r['forget']:+.3f} (±{r['forget_sd']:.3f})   | {r['final']:.3f}")

    full, nv = results["full"], results["no_vault"]
    print(f"\n  vault advantage (no_vault − full forgetting): "
          f"{nv['forget'] - full['forget']:+.3f}")
    print("\nVerdict: the agent learns each task to near-ceiling (high peak-A) but")
    print("forgets it almost entirely once the next task arrives. Neither the vault")
    print("nor the gate provides meaningful protection — the shared decision head")
    print("and representation re-specialise onto the new task. The stability side of")
    print("the stability-plasticity claim is NOT met by the current architecture.")


if __name__ == "__main__":
    main()
