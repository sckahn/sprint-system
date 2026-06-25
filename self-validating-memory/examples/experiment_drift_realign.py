"""Learnable Drift Compensation for the decay-free LabelVault (Phase-6 part 7).

The decay-free ``LabelVault`` votes a verified region→class fact straight onto the
logits, and ``experiment_continual_fix.py`` shows that cutting forgetting this way
relies on one assumption: the encoder *key* of a region stays put across tasks, so
a key written under task A still lands where task-A inputs encode later. Over a
LONG continual run that assumption weakens — the encoder keeps training on later
tasks and its feature space *drifts*, so the stored task-A key slowly mis-targets
its own region and the never-forget vote starts missing.

Learnable Drift Compensation (Gomez-Villa et al. 2024, "Exemplar-free Continual
Representation Learning via Learnable Drift Compensation",
https://arxiv.org/abs/2407.08536) repairs this without rehearsal: periodically fit
a small linear projector mapping the OLD encoder's features to the NEW encoder's
features and push the stored keys through it, so they track the moving
representation instead of being re-collected from exemplars.

This experiment runs a LENGTHENED ``SplitContinualTask`` (more steps/task ⇒ more
encoder drift) with ``direct_vote=True`` under two arms — drift_realign off vs on —
and reports, for each:

  * continual.forgetting() — average peak−final accuracy on earlier tasks.
  * key-drift: the mean cosine between a stored OLD-task key and a FRESH encoding
    of the SAME region at the end of training. Higher = the key still points at its
    region (LDC should raise this; without it the key drifts away).

    PYTHONPATH=. python examples/experiment_drift_realign.py
"""
from __future__ import annotations

import statistics as st

import torch
import torch.nn.functional as F

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.tasks import SplitContinualTask
from svmp.continual import run_continual, forgetting

SEEDS = [0, 1, 2, 3]
N_CLASSES = 8
N_TASKS = 2
FEATURE_DIM = 16
# Lengthened so the encoder drifts further than the short continual_fix run.
STEPS_PER_TASK = 6000
VOTE_SCALE = 10.0
KEY_DRIFT_PROBES = 200


def key_drift_alignment(agent, task) -> float:
    """Mean cosine of each stored TASK-0 key to a fresh encoding of its region.

    For every label-vault key whose label belongs to task 0 (the earliest, so the
    most drifted-away-from), draw a fresh input from that exact class region, encode
    it with the CURRENT encoder, and measure cosine(stored_key, fresh_enc). A key
    that still points at its own region scores high; a drifted key scores low.
    """
    lv = agent.label_vault
    if lv is None or len(lv) == 0:
        return float("nan")
    task0_classes = set(task.task_classes[0])
    sims = []
    with torch.no_grad():
        for i in range(len(lv)):
            label = int(lv.labels[i])
            if label not in task0_classes:
                continue
            acc = 0.0
            for _ in range(KEY_DRIFT_PROBES // 4):
                # Sample inputs of this specific class, encode fresh, average cosine.
                x = _sample_class(task, label)
                enc = agent.model.encoder(x.flatten())
                acc += float(F.cosine_similarity(lv.keys[i], enc, dim=0))
            sims.append(acc / (KEY_DRIFT_PROBES // 4))
    return st.mean(sims) if sims else float("nan")


def _sample_class(task, c: int) -> torch.Tensor:
    """Draw one input from class ``c``'s region (same recipe as the task)."""
    signal = 0.5 + 0.5 * float(torch.rand(1, generator=task.gen))
    noise = torch.randn(task.feature_dim, generator=task.gen) * (1 - signal)
    return signal * task.prototypes[c] + noise


def run(drift_realign, seed):
    cfg = SVMPConfig(seed=seed, n_classes=N_CLASSES)
    agent = SelfValidatingAgent(cfg, FEATURE_DIM, direct_vote=True,
                                vote_scale=VOTE_SCALE,
                                drift_realign=drift_realign)
    task = SplitContinualTask(N_CLASSES, N_TASKS, FEATURE_DIM, seed=seed)
    acc = run_continual(agent, task, STEPS_PER_TASK)
    return forgetting(acc), key_drift_alignment(agent, task)


def condition(label, drift_realign):
    rs = [run(drift_realign, s) for s in SEEDS]
    f = st.mean(r[0] for r in rs)
    fsd = st.pstdev(r[0] for r in rs)
    kd = st.mean(r[1] for r in rs)
    print(f"  {label:24s} | forgetting {f:+.3f} (±{fsd:.3f}) | key-drift cos {kd:.3f}")
    return f, kd


def main():
    print("Learnable Drift Compensation for the decay-free LabelVault")
    print(f"  {N_TASKS} tasks ({N_CLASSES} classes, {STEPS_PER_TASK} steps/task), "
          f"n={len(SEEDS)} seeds, vote_scale={VOTE_SCALE}\n")

    off = condition("baseline (LDC off)", False)
    on = condition("fix (drift_realign)", True)

    print(f"\n  forgetting: {off[0]:.3f} → {on[0]:.3f} ({off[0] - on[0]:+.3f})")
    print(f"  key-drift cosine: {off[1]:.3f} → {on[1]:.3f} ({on[1] - off[1]:+.3f})")
    print("\nReading: over a LONG run the encoder drifts, so the never-forget key")
    print("written under task 0 slowly stops matching task-0 inputs (lower key-drift")
    print("cosine). LDC re-projects the stored keys through a fitted old→new linear")
    print("map so they track the moving representation — raising the key-drift cosine")
    print("and keeping the verified vote on-target, which protects the earlier task.")


if __name__ == "__main__":
    main()
