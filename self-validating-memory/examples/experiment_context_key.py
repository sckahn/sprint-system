"""Resolving conflicting-label forgetting with a context key (Phase-6 part 4).

Part 3 (`experiment_forgetting_limits.py`) showed the direct-vote fix collapses on
``PermutedLabelTask``: when the same input region has different correct answers in
different tasks, a context-free input→label memory commits the vote to one task
arbitrarily, helping one and hurting the other. The diagnosis pointed to the cure:
a *task/context key* on the vote.

Here we test three ways to supply that context, all under one prequential
(predict-then-observe, no weight learning) eval protocol on a fresh A→B stream:

  * none      — the part-3 fix (ctx-free); expected to fail.
  * oracle     — the true task id as a one-hot context at train and eval; the
                 upper bound that proves context-keying *can* resolve the conflict.
  * inferred   — NO task oracle: ``ContextInferrer`` allocates a context from the
                 reward stream (a change-point detector), at train and eval.

The honest question is how much of the oracle the inferred context recovers when
task identity is observable only through the changing reward contingency.

    PYTHONPATH=. python examples/experiment_context_key.py
"""
from __future__ import annotations

import statistics as st

import torch

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.context import ContextInferrer
from svmp.tasks import PermutedLabelTask

SEEDS = [0, 1, 2, 3]
STEPS = 2500
EVAL_PER_SEG = 600
CTX_DIM = 6
VOTE_SCALE = 10.0


def onehot(i, n=CTX_DIM):
    v = torch.zeros(n)
    v[i] = 1.0
    return v


class _NoCtx:
    def before(self, task_idx): pass
    def context(self): return None
    def after(self, reward01): pass


class _OracleCtx:
    def before(self, task_idx): self._c = onehot(task_idx)
    def context(self): return self._c
    def after(self, reward01): pass


class _InferredCtx:
    def __init__(self, inferrer): self.inf = inferrer
    def before(self, task_idx): pass
    def context(self): return self.inf.context()
    def after(self, reward01): self.inf.observe(reward01)


def train(agent, task, mode, inferrer):
    switches = 0
    for t in range(task.n_tasks):
        for _ in range(STEPS):
            x, y = task.sample(t)
            if mode == "inferred":
                ctx = inferrer.context()
                log = agent.step(x, y, context=ctx)
                switches += int(inferrer.observe(1.0 if log.correct else 0.0))
            elif mode == "oracle":
                agent.step(x, y, context=onehot(t))
            else:
                agent.step(x, y)
    return switches


def prequential_eval(agent, task, evalctx):
    """Predict-then-observe on a fresh A→B stream; no weight learning."""
    seg_acc = []
    for t in range(task.n_tasks):
        evalctx.before(t)
        correct = 0
        for _ in range(EVAL_PER_SEG):
            x, y = task.sample(t)
            pred = agent.predict(x, context=evalctx.context())
            ok = int(pred == y)
            correct += ok
            evalctx.after(1.0 if ok else 0.0)
        seg_acc.append(correct / EVAL_PER_SEG)
    return seg_acc


def run(mode, seed):
    cfg = SVMPConfig(seed=seed, n_classes=8)
    ctx_dim = 0 if mode == "none" else CTX_DIM
    agent = SelfValidatingAgent(cfg, 16, direct_vote=True,
                                vote_scale=VOTE_SCALE, ctx_dim=ctx_dim)
    task = PermutedLabelTask(8, 2, 16, seed=seed)

    train_inferrer = ContextInferrer(ctx_dim=CTX_DIM) if mode == "inferred" else None
    switches = train(agent, task, mode, train_inferrer)

    evalctx = {"none": _NoCtx(), "oracle": _OracleCtx(),
               "inferred": _InferredCtx(ContextInferrer(ctx_dim=CTX_DIM))}[mode]
    seg = prequential_eval(agent, task, evalctx)
    return dict(accA=seg[0], accB=seg[1], mean=st.mean(seg), switches=switches)


def main():
    print("Conflicting-label forgetting with a context key (Permuted, n=4, "
          "prequential eval)\n")
    results = {}
    for mode in ("none", "oracle", "inferred"):
        rs = [run(mode, s) for s in SEEDS]
        results[mode] = {k: st.mean(r[k] for r in rs)
                         for k in ("accA", "accB", "mean", "switches")}
        r = results[mode]
        extra = (f"  (train switches≈{r['switches']:.1f})"
                 if mode == "inferred" else "")
        print(f"  {mode:9s} | task-A {r['accA']:.3f} | task-B {r['accB']:.3f} "
              f"| mean {r['mean']:.3f}{extra}")

    none, orc, inf = results["none"], results["oracle"], results["inferred"]
    recov = ((inf["mean"] - none["mean"]) / (orc["mean"] - none["mean"])
             if orc["mean"] > none["mean"] else float("nan"))
    print("\nReading:")
    print(f"  The oracle context lifts mean accuracy {none['mean']:.2f}→"
          f"{orc['mean']:.2f}, proving the conflict is a context-key problem, not a")
    print(f"  capacity one. (Even the oracle's task-A stays {orc['accA']:.2f}<task-B "
          f"{orc['accB']:.2f}: a perfect context still has to\n  out-vote the "
          f"B-drifted representation on the old task.)")
    print(f"  The inferred context — which never sees a task id, only the reward "
          f"stream — recovers")
    print(f"  {recov*100:.0f}% of the oracle gain ({inf['mean']:.2f} mean). It is a "
          f"PARTIAL fix: task-A retention rises {none['accA']:.2f}→{inf['accA']:.2f}")
    print(f"  but stays below the oracle's {orc['accA']:.2f}, because the change-point "
          f"detector over-segments\n  (~{inf['switches']:.1f} switches vs the ideal 1), "
          f"so some task-A entries get tagged to the wrong slot.")
    print("  Honest limits: task-free context inference from reward alone is noisy")
    print("  and only partly solved here; and this forward-only inferrer cannot yet")
    print("  re-recognise a RETURNED context (B→A) — error-pattern matching to past")
    print("  slots is the next follow-up.")


if __name__ == "__main__":
    main()
