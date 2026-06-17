"""WHERE the forgetting fix breaks (Phase 6 follow-up, part 3).

Part 2 (`experiment_continual_fix.py`) showed that voting verified facts straight
into the logits cuts catastrophic forgetting — *but only* under the assumptions
the diagnosis identified: input regions map to a stable label, and the encoder
key barely drifts. ``PermutedLabelTask`` violates the *label-stability* assumption
(every task reuses the same input regions but permutes their labels) while — as it
turns out — preserving key stability (the input distribution is identical across
tasks). So it cleanly isolates label conflict as the failure cause.

We measure, for Split (separable, the friendly case) vs Permuted (conflicting):
  1. forgetting / final accuracy, fix off vs on  — does the fix still help?
  2. key drift  — cosine between a region's encoding after A vs after B
                  (tests the "key barely drifts" assumption directly)
  3. vote-only task-0 accuracy after B  — if we decided purely by the memory's
                  vote, how reliably does it still answer the first task?

The instructive result is that the fix degrades to the *baseline* (not worse):
under conflict, each region's verified entries commit the vote to one task's
label arbitrarily, so it helps that task and hurts the other in roughly equal
measure — a context-free input→label memory has no task signal to choose.

    PYTHONPATH=. python examples/experiment_forgetting_limits.py
"""
from __future__ import annotations

import statistics as st

import torch
import torch.nn.functional as F

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.tasks import SplitContinualTask, PermutedLabelTask
from svmp.continual import eval_accuracy

SEEDS = [0, 1, 2, 3]
STEPS = 2500
VOTE_SCALE = 10.0


@torch.no_grad()
def region_encodings(agent, task):
    return torch.stack([agent.model.encoder(task.prototypes[r])
                        for r in range(task.n_classes)])


@torch.no_grad()
def vote_only_accuracy(agent, task, task_idx, n=300):
    """Accuracy if the decision were made by the memory's vote alone."""
    correct = 0
    for _ in range(n):
        x, y = task.sample(task_idx)
        vote = agent.label_vault.vote(agent.model.encoder(x.flatten()))
        if float(vote.sum()) <= 1e-6:
            continue                       # no confident match → abstain (miss)
        correct += int(int(vote.argmax()) == y)
    return correct / n


def train_and_measure(TaskCls, direct_vote, seed):
    cfg = SVMPConfig(seed=seed, n_classes=8)
    agent = SelfValidatingAgent(cfg, 16, direct_vote=direct_vote,
                                vote_scale=VOTE_SCALE)
    task = TaskCls(8, 2, 16, seed=seed)

    for _ in range(STEPS):
        x, y = task.sample(0)
        agent.step(x, y)
    peak_A = eval_accuracy(agent, task, 0)
    enc_A = region_encodings(agent, task)

    for _ in range(STEPS):
        x, y = task.sample(1)
        agent.step(x, y)
    final_A = eval_accuracy(agent, task, 0)
    final_B = eval_accuracy(agent, task, 1)
    enc_B = region_encodings(agent, task)

    key_drift = float(F.cosine_similarity(enc_A, enc_B, dim=1).mean())

    # If we decided purely by the memory's vote, how reliable is task 0 after B?
    vote_acc0 = vote_only_accuracy(agent, task, 0) if direct_vote else None

    return dict(forget=peak_A - final_A, final=(final_A + final_B) / 2,
                peak_A=peak_A, key_drift=key_drift, vote_acc0=vote_acc0)


def aggregate(TaskCls, direct_vote):
    rs = [train_and_measure(TaskCls, direct_vote, s) for s in SEEDS]
    out = {k: st.mean(r[k] for r in rs)
           for k in ("forget", "final", "peak_A", "key_drift")}
    if direct_vote:
        out["vote_acc0"] = st.mean(r["vote_acc0"] for r in rs)
    return out


def main():
    print("WHERE does the forgetting fix break? (n=4 seeds, 8cls/2tasks)\n")
    rows = []
    for name, TaskCls in [("Split (separable)", SplitContinualTask),
                          ("Permuted (conflicting labels)", PermutedLabelTask)]:
        base = aggregate(TaskCls, False)
        fix = aggregate(TaskCls, True)
        rows.append((name, base, fix))
        print(f"{name}")
        print(f"  baseline   forget {base['forget']:+.3f} | final {base['final']:.3f}")
        print(f"  fix        forget {fix['forget']:+.3f} | final {fix['final']:.3f}"
              f"  (final Δ {fix['final'] - base['final']:+.3f})")
        print(f"  key drift (region enc cosine A→B)     {fix['key_drift']:.3f}")
        print(f"  vote-only task-0 accuracy after B     {fix['vote_acc0']:.3f}\n")

    sp, pe = rows[0], rows[1]
    print("Reading:")
    print(f"  The fix lifts final accuracy {sp[2]['final'] - sp[1]['final']:+.3f} on "
          f"separable tasks but only {pe[2]['final'] - pe[1]['final']:+.3f} on "
          f"conflicting ones — it\n  degrades to the baseline, not below it.")
    print(f"  It is NOT key drift: the key is actually MORE stable under conflict "
          f"({sp[2]['key_drift']:.2f}→\n  {pe[2]['key_drift']:.2f} cosine), since the "
          f"input distribution is unchanged. The cause is pure label\n  conflict — "
          f"the memory's vote alone answers task 0 at {sp[2]['vote_acc0']:.2f} when "
          f"regions own one label\n  but only {pe[2]['vote_acc0']:.2f} when each "
          f"region accrues both tasks' labels and the vote commits to\n  one "
          f"arbitrarily. A context-free input→label memory has no task signal to "
          f"choose, so it\n  helps one task and hurts the other in equal measure.")


if __name__ == "__main__":
    main()
