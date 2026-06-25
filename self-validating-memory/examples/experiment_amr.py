"""Adaptive Memory Realignment under concept drift (Phase-6 part 6).

The decay-free ``LabelVault`` never forgets — which is exactly its virtue on the
class-incremental study, but its failure mode under *concept drift*: when a
region's correct label permanently changes, the vault keeps casting its stale
pre-drift vote and out-votes the (correctly) re-learned model, so the agent stays
stuck on the old answer. Two repairs are possible:

  * blanket-decay — decay *every* entry each step and prune below a floor. This
    eventually clears the stale fact, but it also erases the unflipped regions the
    vault is meant to protect (it re-introduces the forgetting we removed).
  * AMR — Adaptive Memory Realignment (Ashrafee et al. 2025, "Holistic Continual
    Learning under Concept Drift with Adaptive Memory Realignment",
    https://arxiv.org/abs/2507.02310): on a CONFIRMED true drift, selectively
    remove only the *drifted region's* outdated entries and let verified writes
    repopulate the new mapping — leaving unflipped regions untouched.

This experiment runs the same ``ConceptDriftTask`` stream (half the regions flip
PERMANENTLY at a known step) under three regimes and reports, per drifted vs.
unflipped region:

  * post-flip accuracy on the FLIPPED regions (recovery): AMR recovers; decay-free
    stays stuck on the stale label.
  * retention on the UNFLIPPED regions: AMR ≈ decay-free (both high); blanket-decay
    sacrifices it.
  * final vault size.

    PYTHONPATH=. python examples/experiment_amr.py
"""
from __future__ import annotations

import statistics as st

import torch

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.tasks import ConceptDriftTask

SEEDS = [0, 1, 2, 3]
N_CLASSES = 8
FEATURE_DIM = 16
FLIP_STEP = 1500
TOTAL_STEPS = 3000
EVAL_N = 200
VOTE_SCALE = 10.0
DECAY = 0.97               # blanket-decay rate (per consolidating step)
PRUNE_FLOOR = 0.05         # blanket-decay prune floor


def eval_region_set(agent, task, regions, n=EVAL_N):
    """Greedy accuracy averaged over a set of regions at the current drift phase."""
    if not regions:
        return float("nan")
    correct = total = 0
    for r in regions:
        for _ in range(n):
            x, y = task.sample_region(r)
            correct += int(agent.predict(x) == y)
            total += 1
    return correct / total


def run(mode, seed):
    cfg = SVMPConfig(seed=seed, n_classes=N_CLASSES)
    agent = SelfValidatingAgent(cfg, FEATURE_DIM, direct_vote=True,
                                vote_scale=VOTE_SCALE,
                                amr=(mode == "amr"))
    task = ConceptDriftTask(N_CLASSES, FEATURE_DIM, flip_step=FLIP_STEP, seed=seed)
    for _ in range(TOTAL_STEPS):
        x, y = task.sample()
        agent.step(x, y)
        # blanket-decay baseline: indiscriminately decay every label-vault entry
        # and prune below the floor (the indiscriminate alternative to AMR).
        if mode == "decay" and len(agent.label_vault) > 0:
            lv = agent.label_vault
            lv.conviction *= DECAY
            keep = lv.conviction >= PRUNE_FLOOR
            lv.keys, lv.labels = lv.keys[keep], lv.labels[keep]
            lv.conviction = lv.conviction[keep]
    flipped = eval_region_set(agent, task, task.drift_regions)
    unflipped = eval_region_set(agent, task, task.unflipped_regions)
    return flipped, unflipped, len(agent.label_vault)


def main():
    print("Adaptive Memory Realignment under concept drift "
          f"(ConceptDrift, flip@{FLIP_STEP}/{TOTAL_STEPS}, n={len(SEEDS)})\n")
    print(f"  {'mode':12s} | flipped-acc | unflipped-acc | vault")
    agg = {}
    for mode in ("decay-free", "amr", "decay"):
        run_key = {"decay-free": "none", "amr": "amr", "decay": "decay"}[mode]
        runs = [run(run_key, s) for s in SEEDS]
        f = st.mean(r[0] for r in runs)
        u = st.mean(r[1] for r in runs)
        v = st.mean(r[2] for r in runs)
        agg[mode] = (f, u, v)
        label = {"decay-free": "decay-free", "amr": "AMR",
                 "decay": "blanket-decay"}[mode]
        print(f"  {label:12s} |    {f:.3f}    |     {u:.3f}     | {v:.1f}")

    df = agg["decay-free"]; am = agg["amr"]; dc = agg["decay"]
    print("\nReading (FLIPPED regions are the concept-drift test):")
    print(f"  decay-free never forgets, so on the FLIPPED regions it stays stuck on "
          f"the stale\n  pre-drift label ({df[0]:.2f}); AMR selectively prunes them "
          f"and recovers to {am[0]:.2f}.")
    print(f"  On the UNFLIPPED regions AMR retains {am[1]:.2f} ≈ decay-free "
          f"{df[1]:.2f} — it touches only\n  the drifted region, leaving the rest of "
          f"the never-forget memory intact.")
    print(f"  blanket-decay reaches the FLIPPED regions too ({dc[0]:.2f}) but pays "
          f"for it by collapsing\n  the vault to {dc[2]:.0f} entries (vs "
          f"{am[2]:.0f} for AMR / decay-free): it indiscriminately erases every\n"
          f"  verified fact each step, keeping only what is re-confirmed in the last "
          f"few steps — the\n  protection the decay-free vault was built to give. AMR "
          f"gets the flipped-region recovery\n  WITHOUT that cost, realigning only "
          f"the drifted region on a confirmed-true-drift signal.")


if __name__ == "__main__":
    main()
