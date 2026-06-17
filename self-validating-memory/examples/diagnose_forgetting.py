"""Diagnose WHERE catastrophic forgetting lives (Phase 6 follow-up, part 1).

Phase 6 showed the agent forgets task A almost entirely after learning task B,
and that neither the vault nor the gate prevents it. This script asks *why*, by
attributing the forgetting to a component and testing the vault's failure mode.

The agent has two cleanly separated learning pathways:
  - decision head   = model.decision   (written ONLY by the three-factor rule)
  - representation   = encoder+fuse+moe+calib (written ONLY by Adam backprop)

Analysis 1 — component restore.  Snapshot both pathways right after task A. After
also training task B, restore one pathway at a time to its post-A state and
re-measure task-A accuracy. Whatever pathway, when rolled back, *recovers* task A
is the one that forgot it.

Analysis 2 — vault key drift.  The vault is keyed on the encoder output. If the
encoder drifts while learning B, task-A inputs no longer hash to their stored
entries, so retrieval silently misses. We measure the nearest-key similarity for
task-A queries right after A vs after B.

    PYTHONPATH=. python examples/diagnose_forgetting.py
"""
from __future__ import annotations

import copy
import statistics as st

import torch

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.tasks import SplitContinualTask

SEEDS = [0, 1, 2, 3]
STEPS = 2500
REPR_PARTS = ("encoder", "fuse", "moe", "calib")


# --- snapshot / restore helpers -------------------------------------------
def snap_repr(agent):
    return {p: copy.deepcopy(getattr(agent.model, p).state_dict())
            for p in REPR_PARTS}


def load_repr(agent, snap):
    for p in REPR_PARTS:
        getattr(agent.model, p).load_state_dict(snap[p])


def snap_head(agent):
    return (agent.model.decision.weight.detach().clone(),
            agent.model.decision.bias.detach().clone())


def load_head(agent, snap):
    with torch.no_grad():
        agent.model.decision.weight.copy_(snap[0])
        agent.model.decision.bias.copy_(snap[1])


@torch.no_grad()
def acc_novault(agent, task, t, n=300):
    """Pure model pathway: retrieved = zeros, so only head+repr decide."""
    z = torch.zeros(agent.cfg.dim)
    correct = 0
    for _ in range(n):
        x, y = task.sample(t)
        out = agent.model(x, z)
        correct += int(int(out.logits.argmax()) == y)
    return correct / n


@torch.no_grad()
def mean_key_similarity(agent, task, t, n=300):
    """Average nearest-key cosine for task-t queries (vault retrieval quality)."""
    sims = []
    for _ in range(n):
        x, _ = task.sample(t)
        enc = agent.model.encoder(x.flatten())
        sims.append(agent.vault.query(enc).max_similarity)
    return st.mean(sims)


# --- Analysis 1: where does the forgetting live? --------------------------
def decomposition():
    rows = {"baseline": [], "restore_head": [], "restore_repr": [],
            "restore_both": [], "peak_A": []}
    for seed in SEEDS:
        cfg = SVMPConfig(seed=seed, n_classes=8)
        agent = SelfValidatingAgent(cfg, 16, use_vault=False)
        task = SplitContinualTask(8, 2, 16, seed=seed)

        for _ in range(STEPS):
            x, y = task.sample(0)
            agent.step(x, y)
        repr_A, head_A = snap_repr(agent), snap_head(agent)
        rows["peak_A"].append(acc_novault(agent, task, 0))

        for _ in range(STEPS):
            x, y = task.sample(1)
            agent.step(x, y)
        repr_B, head_B = snap_repr(agent), snap_head(agent)

        def measure(rp, hd):
            load_repr(agent, rp); load_head(agent, hd)
            return acc_novault(agent, task, 0)

        rows["baseline"].append(measure(repr_B, head_B))
        rows["restore_head"].append(measure(repr_B, head_A))
        rows["restore_repr"].append(measure(repr_A, head_B))
        rows["restore_both"].append(measure(repr_A, head_A))
    return {k: st.mean(v) for k, v in rows.items()}


# --- Analysis 2: vault key drift ------------------------------------------
def key_drift():
    after_A, after_B = [], []
    for seed in SEEDS:
        cfg = SVMPConfig(seed=seed, n_classes=8)
        agent = SelfValidatingAgent(cfg, 16, use_vault=True)
        task = SplitContinualTask(8, 2, 16, seed=seed)
        for _ in range(STEPS):
            x, y = task.sample(0)
            agent.step(x, y)
        after_A.append(mean_key_similarity(agent, task, 0))
        for _ in range(STEPS):
            x, y = task.sample(1)
            agent.step(x, y)
        after_B.append(mean_key_similarity(agent, task, 0))
    return st.mean(after_A), st.mean(after_B)


def main():
    print("WHERE does catastrophic forgetting live? (n=4 seeds, 8cls/2tasks)\n")

    d = decomposition()
    print("Analysis 1 — component restore (task-A accuracy, retrieved=zeros):")
    print(f"  task-A peak (after A) ............ {d['peak_A']:.3f}")
    print(f"  baseline (full post-B) .......... {d['baseline']:.3f}  "
          f"forgotten {d['peak_A']-d['baseline']:+.3f}")
    print(f"  restore DECISION HEAD only ...... {d['restore_head']:.3f}  "
          f"recovered {d['restore_head']-d['baseline']:+.3f}")
    print(f"  restore REPRESENTATION only ..... {d['restore_repr']:.3f}  "
          f"recovered {d['restore_repr']-d['baseline']:+.3f}")
    print(f"  restore BOTH (sanity) ........... {d['restore_both']:.3f}")

    sa, sb = key_drift()
    print("\nAnalysis 2 — vault key drift (nearest-key cosine for task-A queries):")
    print(f"  right after task A .............. {sa:.3f}")
    print(f"  after task B ................... {sb:.3f}   drift {sb-sa:+.3f}")

    head_share = d["restore_head"] - d["baseline"]
    repr_share = d["restore_repr"] - d["baseline"]
    print("\nReading:")
    print(f"  Restoring the head recovers {head_share:+.3f}; restoring the "
          f"representation recovers {repr_share:+.3f}.")
    print("  The larger recovery is the dominant locus of forgetting. If the")
    print("  encoder similarity (Analysis 2) also drops, the vault key has moved,")
    print("  which explains why retrieval cannot rescue the old task.")


if __name__ == "__main__":
    main()
