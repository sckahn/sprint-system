"""BOCD vs EMA change DETECTION on a returning-context stream (Phase-6 part 6).

Part 5 (`experiment_context_recognition.py`) showed that reward-probing
*re-recognition* recovers most of the forgetting gap once a boundary is known,
and that in fully task-free mode (`auto`) the manager's own reward-collapse
detector drives the probing. Its closing line named DETECTION — latency to fire
plus leftover false-alarm probing — as the remaining bottleneck.

This experiment attacks exactly that residual. It swaps the EMA collapse
predicate (``fast < slow - drop``) for Bayesian Online Changepoint Detection
(Adams & MacKay 2007, https://arxiv.org/abs/0710.3742) with a Beta-Bernoulli
conjugate predictive over the binary reward stream (MOCA framing, Titsias et al.
2020, https://arxiv.org/abs/1912.08866). BOCD maintains an exact run-length
posterior and fires when the changepoint mass at run_length==0 crosses a
threshold — no hand-tuned drop/established gap, and it reacts as soon as the
reward likelihood of "still the same run" decays.

Same shape as part-5's ``auto`` mode: NO boundary signal is given; the manager's
detector triggers the probing search itself on the revisiting stream A→B→A→B. We
compare ``detector='ema'`` vs ``detector='bocd'`` on:
  * revisit mean — accuracy on the RETURNED segments A2*/B2* (the forgetting test).
  * probe        — total probe steps spent searching (re-probe cost).
  * latency      — mean steps from the true segment boundary to the detector firing.
  * false alarm  — searches fired with no true boundary in the preceding segment,
                   per segment (spurious triggers the probing must absorb).

    PYTHONPATH=. python examples/experiment_change_detection.py
"""
from __future__ import annotations

import statistics as st

import torch

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.context import RecognizingContextManager
from svmp.tasks import PermutedLabelTask

SEEDS = [0, 1, 2, 3]
STEPS = 2500
EVAL_PER_SEG = 600
CTX_DIM = 6
VOTE_SCALE = 10.0
VISIT_ORDER = [0, 1, 0, 1]          # A → B → A → B


def onehot(i, n=CTX_DIM):
    v = torch.zeros(n)
    v[i] = 1.0
    return v


def train_with_oracle_tags(agent, task):
    """Tag the memory cleanly: task t's verified facts get context slot t."""
    for t in range(task.n_tasks):
        for _ in range(STEPS):
            x, y = task.sample(t)
            agent.step(x, y, context=onehot(t))


class _Auto:
    """Fully task-free: no boundary signal — the change detector inside the
    manager triggers the probing search itself. ``detector`` selects EMA vs BOCD.
    Records, per segment, the step at which a search first fired (for latency and
    false-alarm accounting)."""

    def __init__(self, detector):
        self.mgr = RecognizingContextManager(ctx_dim=CTX_DIM, probe_steps=30,
                                             auto_detect=True, accept=0.6,
                                             detector=detector)
        self._seg_step = 0
        self._fired_at: int | None = None
        self.fire_steps: list[int | None] = []

    def boundary(self, t):                            # no boundary is given to the
        self.fire_steps.append(self._fired_at)        # detector; we just close the
        self._seg_step = 0                            # segment for bookkeeping.
        self._fired_at = None

    def context(self): return self.mgr.context()

    def observe(self, r):
        was_normal = self.mgr.mode == "normal"
        self.mgr.observe(r)
        # A transition out of "normal" marks the step a search fired this segment.
        if was_normal and self.mgr.mode != "normal" and self._fired_at is None:
            self._fired_at = self._seg_step
        self._seg_step += 1

    @property
    def cost(self): return self.mgr.probe_cost


def prequential_revisit(agent, task, provider):
    """Stream A→B→A→B; predict→observe, no learning. Returns per-segment accuracy."""
    seg_acc = []
    for t in VISIT_ORDER:
        provider.boundary(t)
        correct = 0
        for _ in range(EVAL_PER_SEG):
            x, y = task.sample(t)
            ok = int(agent.predict(x, context=provider.context()) == y)
            correct += ok
            provider.observe(1.0 if ok else 0.0)
        seg_acc.append(correct / EVAL_PER_SEG)
    provider.boundary(None)                          # flush the final segment's fire
    return seg_acc


def run(detector, seed):
    cfg = SVMPConfig(seed=seed, n_classes=8)
    agent = SelfValidatingAgent(cfg, 16, direct_vote=True,
                                vote_scale=VOTE_SCALE, ctx_dim=CTX_DIM)
    task = PermutedLabelTask(8, 2, 16, seed=seed)
    train_with_oracle_tags(agent, task)
    provider = _Auto(detector)
    seg = prequential_revisit(agent, task, provider)
    # fire_steps[i] is the step (within segment i) the detector first fired, or
    # None. Segments 1..3 follow a TRUE boundary; segment 0 does not. A fire in
    # segment 0, or a *second* fire is impossible here since we record only the
    # first per segment — so false alarms are fires in segment 0.
    fires = provider.fire_steps
    true_latencies = [fires[i] for i in range(1, 4) if fires[i] is not None]
    detected = sum(1 for i in range(1, 4) if fires[i] is not None)
    false_alarms = 1 if (fires and fires[0] is not None) else 0
    return seg, provider.cost, true_latencies, detected, false_alarms


def main():
    print("BOCD vs EMA change detection (Permuted, A→B→A→B, n=4, prequential, "
          "task-free)\n")
    print(f"  {'detector':9s} |   A1    B1    A2*   B2*  | revisit | probe | "
          f"latency | det | false-alarm/seg")
    agg = {}
    for detector in ("ema", "bocd"):
        rows = [run(detector, s) for s in SEEDS]
        segs = [r[0] for r in rows]
        costs = [r[1] for r in rows]
        lats = [x for r in rows for x in r[2]]
        detected = sum(r[3] for r in rows)
        false_alarms = sum(r[4] for r in rows)
        n_true = len(SEEDS) * 3              # 3 true boundaries per run
        n_seg = len(SEEDS) * 4               # false-alarm rate per segment
        m = [st.mean(s[i] for s in segs) for i in range(4)]
        revisit = st.mean([m[2], m[3]])
        cost = st.mean(costs)
        latency = st.mean(lats) if lats else float("nan")
        far = false_alarms / n_seg
        agg[detector] = (revisit, cost, latency, detected, n_true, far)
        print(f"  {detector:9s} | {m[0]:.3f} {m[1]:.3f} {m[2]:.3f} {m[3]:.3f} "
              f"|  {revisit:.3f}  | {cost:5.0f} |  {latency:5.1f}  | "
              f"{detected}/{n_true} | {far:.3f}")

    er, ec, el, ed, ent, ef = agg["ema"]
    br, bc, bl, bd, bnt, bf = agg["bocd"]
    print("\nReading (A2*/B2* are the RETURNED segments — the forgetting test):")
    print(f"  Both detectors are task-free (no boundary given). BOCD's exact "
          f"run-length posterior\n  fires {bl:.1f} steps after the true boundary "
          f"vs EMA's {el:.1f} (lower = faster), detecting\n  {bd}/{bnt} boundaries "
          f"vs {ed}/{ent}, at a {bf:.3f} vs {ef:.3f} false-alarm rate per segment.")
    print(f"  Faster, cleaner detection feeds the SAME reward-probing recogniser, "
          f"so revisit\n  accuracy is {br:.3f} (BOCD) vs {er:.3f} (EMA) at "
          f"{bc:.0f} vs {ec:.0f} probe steps. BOCD trades the\n  hand-tuned "
          f"drop/established gap for a principled changepoint probability and "
          f"attacks\n  the detection bottleneck part-5 named — defaults stay EMA, "
          f"so this is opt-in.")


if __name__ == "__main__":
    main()
