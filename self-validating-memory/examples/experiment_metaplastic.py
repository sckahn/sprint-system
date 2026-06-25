"""Metaplastic consolidation buffer — can Benna-Fusi hardening protect the head?

The catastrophic-forgetting study (``experiment_continual.py``) showed that the
LabelVault vote does NOT cover decision-head forgetting: when the shared head
re-specialises onto a new task, task-A structure is overwritten. This experiment
isolates that head pathway (``use_vault=False, direct_vote=False`` ⇒ all the
forgetting lives in the three-factor decision head) and asks whether a
Benna-Fusi metaplastic consolidation buffer mitigates it.

Mechanism (opt-in, default OFF). Each synapse carries a real-valued
consolidation variable ``c``. A gated write is scaled by ``1/(c+eps)`` and then
hardens the synapse via ``c += alpha·g·|dw|`` (Zenke & Laborieux, "Theories of
synaptic memory consolidation and intelligent plasticity for continual
learning", https://arxiv.org/abs/2405.16922). Synapses written often during
task A grow large ``c`` and resist being overwritten by task B.

We compare two conditions on the head-only continual agent:

  plain        — cfg.learning.metaplastic = False (current behaviour, bitwise)
  metaplastic  — cfg.learning.metaplastic = True

Metric: forgetting = (task-A accuracy right after learning A) − (task-A accuracy
after also learning B). 0 = perfect retention; ~1 = total catastrophic
forgetting. Chance is 0.25 (4 classes per task). n=4 seeds.

    PYTHONPATH=. python examples/experiment_metaplastic.py
"""
from __future__ import annotations

import statistics as st

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.tasks import SplitContinualTask
from svmp.continual import run_continual, forgetting, final_accuracy

SEEDS = [0, 1, 2, 3]
STEPS_PER_TASK = 2500
# Head-only agent: no vault read, no direct vote ⇒ forgetting lives in the head.
AGENT_KNOBS = dict(use_vault=False, direct_vote=False, force_gate=None)
CONDITIONS = {
    "plain":       dict(metaplastic=False),
    "metaplastic": dict(metaplastic=True),
}


def run_condition(meta_knobs: dict) -> dict:
    forgets, finals, peaks = [], [], []
    for seed in SEEDS:
        cfg = SVMPConfig(seed=seed, n_classes=8)
        # Opt-in metaplasticity is a learning-rule knob.
        for k, v in meta_knobs.items():
            setattr(cfg.learning, k, v)
        agent = SelfValidatingAgent(cfg, 16, **AGENT_KNOBS)
        task = SplitContinualTask(n_classes=8, n_tasks=2, feature_dim=16,
                                  seed=seed)
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
    print("Benna-Fusi metaplastic buffer — head-only continual learning "
          "(8 classes / 2 tasks)")
    print(f"  {STEPS_PER_TASK} steps/task, {len(SEEDS)} seeds, chance = 0.25, "
          f"vault OFF\n")
    print(f"  {'condition':12s} | peak-A | forgetting (±sd)   | final acc")
    print(f"  {'-'*12} | {'-'*6} | {'-'*18} | {'-'*9}")
    results = {}
    for name, knobs in CONDITIONS.items():
        r = run_condition(knobs)
        results[name] = r
        print(f"  {name:12s} | {r['peak_A']:.3f}  | "
              f"{r['forget']:+.3f} (±{r['forget_sd']:.3f})   | {r['final']:.3f}")

    plain, meta = results["plain"], results["metaplastic"]
    delta = plain["forget"] - meta["forget"]
    print(f"\n  metaplastic advantage (plain − metaplastic forgetting): "
          f"{delta:+.3f}")
    print("  final-accuracy change (metaplastic − plain): "
          f"{meta['final'] - plain['final']:+.3f}")


if __name__ == "__main__":
    main()
