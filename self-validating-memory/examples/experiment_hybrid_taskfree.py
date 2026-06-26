"""Fully TASK-FREE combination: standard replay + SVMP's reward-based context.

`experiment_hybrid.py` showed that bolting an ORACLE context key onto plain replay
rescues the conflicting-label regime (0.56 -> 0.985). But the oracle is a cheat —
it hands the learner the task id. SVMP's actual research contribution (parts 4-5)
is discovering that context *task-free*, purely from the reward stream. This wires
that real contribution into the standard tool: a reservoir-replay model whose
context tag comes from ``ContextInferrer`` (a reward-collapse change detector) — no
task id anywhere, at train OR test.

On ``PermutedLabelTask`` the input distribution is identical across tasks, so
context is observable only through reward; the inferred-context arm is therefore
evaluated PREQUENTIALLY (predict -> observe reward -> the inferrer tracks context),
the same protocol as part 5. The none/oracle arms use block eval.

Conditions (Permuted, the regime where context is decisive), n=4:
  * replay (no context)            — the floor (block eval).
  * replay + ORACLE context        — upper bound (block eval).
  * replay + INFERRED context      — task-free; ContextInferrer tags train + drives
                                     prequential eval. The honest combination.

    PYTHONPATH=. python examples/experiment_hybrid_taskfree.py
"""
from __future__ import annotations

import statistics as st

import torch
import torch.nn as nn
import torch.nn.functional as F

from svmp.context import ContextInferrer
from svmp.tasks import PermutedLabelTask

IN_DIM = 16
N_CLASSES = 8
N_TASKS = 2
HID = 64
CTX = 6                # context one-hot width (room for over-segmentation)
STEPS = 2500
EVAL_N = 300
EVAL_PER_SEG = 600
SEEDS = [0, 1, 2, 3]


def onehot(i, n):
    v = torch.zeros(n)
    if n > 0:
        v[i] = 1.0
    return v


class MLP(nn.Module):
    def __init__(self, in_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, HID), nn.ReLU(),
            nn.Linear(HID, HID), nn.ReLU(),
            nn.Linear(HID, N_CLASSES))

    def forward(self, x):
        return self.net(x)


class Replay:
    def __init__(self, seed, ctx_dim, cap=200, k=8, lr=1e-3):
        torch.manual_seed(seed)
        self.ctx_dim = ctx_dim
        self.m = MLP(IN_DIM + ctx_dim)
        self.opt = torch.optim.Adam(self.m.parameters(), lr=lr)
        self.cap, self.k = cap, k
        self.buf = []
        self.seen = 0
        self.g = torch.Generator().manual_seed(seed + 99)

    def _in(self, x, ctx):
        return torch.cat([x, ctx]) if self.ctx_dim > 0 else x

    def train(self, x, y, ctx):
        self.seen += 1
        item = (x.detach().clone(), y, ctx.detach().clone())
        if len(self.buf) < self.cap:
            self.buf.append(item)
        else:
            j = int(torch.randint(self.seen, (1,), generator=self.g))
            if j < self.cap:
                self.buf[j] = item
        ins, ys = [self._in(x, ctx)], [y]
        for _ in range(min(self.k, len(self.buf))):
            i = int(torch.randint(len(self.buf), (1,), generator=self.g))
            bx, by, bc = self.buf[i]
            ins.append(self._in(bx, bc))
            ys.append(by)
        self.opt.zero_grad()
        F.cross_entropy(self.m(torch.stack(ins)), torch.tensor(ys)).backward()
        self.opt.step()

    @torch.no_grad()
    def predict(self, x, ctx):
        return int(self.m(self._in(x, ctx)).argmax())


def run(mode, seed):
    ctx_dim = 0 if mode == "none" else CTX
    learner = Replay(seed, ctx_dim)
    task = PermutedLabelTask(N_CLASSES, N_TASKS, IN_DIM, seed=seed)
    inferrer = ContextInferrer(ctx_dim=CTX) if mode == "inferred" else None

    # --- train ---
    for i in range(N_TASKS):
        for _ in range(STEPS):
            x, y = task.sample(i)
            if mode == "none":
                ctx = onehot(0, 0)
            elif mode == "oracle":
                ctx = onehot(i, CTX)
            else:                                   # inferred: tag by the reward-
                ctx = onehot(inferrer.slot, CTX)    # driven context slot
                correct = learner.predict(x, ctx) == y
                inferrer.observe(1.0 if correct else 0.0)
                ctx = onehot(inferrer.slot, CTX)
            learner.train(x, y, ctx)

    # --- eval ---
    if mode in ("none", "oracle"):                  # block eval per task
        accs = []
        for j in range(N_TASKS):
            ctx = onehot(0, 0) if mode == "none" else onehot(j, CTX)
            c = 0
            for _ in range(EVAL_N):
                x, y = task.sample(j)
                c += int(learner.predict(x, ctx) == y)
            accs.append(c / EVAL_N)
        return st.mean(accs)
    # inferred: prequential A->B with a fresh inferrer (no task id)
    inf = ContextInferrer(ctx_dim=CTX)
    seg = []
    for j in range(N_TASKS):
        c = 0
        for _ in range(EVAL_PER_SEG):
            x, y = task.sample(j)
            ctx = onehot(inf.slot, CTX)
            pred = learner.predict(x, ctx)
            c += int(pred == y)
            inf.observe(1.0 if pred == y else 0.0)
        seg.append(c / EVAL_PER_SEG)
    return st.mean(seg)


def main():
    print("Task-free combination: standard replay + SVMP reward-based context")
    print(f"  PermutedLabelTask (conflicting labels), {STEPS} steps/task, "
          f"n={len(SEEDS)}\n")
    res = {}
    for mode, label in [("none", "replay (no context)"),
                        ("oracle", "replay + ORACLE context"),
                        ("inferred", "replay + INFERRED context (task-free)")]:
        vals = [run(mode, s) for s in SEEDS]
        res[mode] = (st.mean(vals), st.pstdev(vals))
        print(f"  {label:38s} | final acc {res[mode][0]:.3f} (±{res[mode][1]:.3f})")

    none, orc, inf = res["none"][0], res["oracle"][0], res["inferred"][0]
    recov = (inf - none) / (orc - none) * 100 if orc > none else float("nan")
    print("\nReading:")
    print(f"  Plain replay collapses on conflicting labels ({none:.2f}); the ORACLE "
          f"context key lifts it to")
    print(f"  {orc:.2f}. Replacing the oracle with SVMP's task-free ContextInferrer "
          f"(reward stream only,")
    print(f"  no task id at train or test) reaches {inf:.2f} — recovering "
          f"{recov:.0f}% of the oracle's gain.")
    print(f"  This is the genuine two-system combination: the standard replay "
          f"workhorse + SVMP's")
    print(f"  task-free context discovery. The residual gap to the oracle is the "
          f"same detection cost")
    print(f"  parts 4-5 quantified (noisy reward-based segmentation) — the honest "
          f"price of dropping the oracle.")


if __name__ == "__main__":
    main()
