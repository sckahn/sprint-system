"""Can we COMBINE the standard method (replay) with SVMP's contribution (context)?

`experiment_vs_baselines.py` found two things:
  * On class-incremental tasks, plain experience replay wins outright.
  * On domain-incremental tasks (conflicting labels), BOTH replay AND SVMP's
    context-free vote collapse to ~chance — because the same input has two correct
    answers and neither method can tell which task it is in.

The Phase-6 arc already identified the missing ingredient for that second regime: a
CONTEXT key (parts 4-5). SVMP's actual research contribution there is task-free
context discovery from the reward stream. This experiment asks whether that
ingredient COMBINES with the standard tool: does adding a context key rescue plain
replay (and the SVMP vote) on the conflict regime where each fails alone?

Conditions, both regimes, oracle context (the clean upper bound; the task-free
version is parts 4-5):
  * replay            — standard reservoir replay, no context.
  * replay + context  — reservoir replay over a CONTEXT-CONDITIONAL model
                        (input ⊕ context one-hot); buffer stores (x, y, ctx).
  * SVMP vote         — direct_vote, no context.
  * SVMP vote + ctx   — direct_vote with a context-keyed LabelVault (ctx_dim>0).

    PYTHONPATH=. python examples/experiment_hybrid.py
"""
from __future__ import annotations

import statistics as st

import torch
import torch.nn as nn
import torch.nn.functional as F

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.tasks import SplitContinualTask, PermutedLabelTask

IN_DIM = 16
N_CLASSES = 8
N_TASKS = 2
HID = 64
STEPS = 2500
EVAL_N = 300
SEEDS = [0, 1, 2, 3]


def onehot(i, n):
    v = torch.zeros(n)
    if n > 0:
        v[i] = 1.0
    return v


class MLP(nn.Module):
    def __init__(self, in_dim, n_cls):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, HID), nn.ReLU(),
            nn.Linear(HID, HID), nn.ReLU(),
            nn.Linear(HID, n_cls))

    def forward(self, x):
        return self.net(x)


class CtxReplay:
    """Reservoir replay over a context-conditional model. ctx_dim=0 ⇒ plain replay."""
    def __init__(self, seed, ctx_dim, cap=200, k=8, lr=1e-3):
        torch.manual_seed(seed)
        self.ctx_dim = ctx_dim
        self.m = MLP(IN_DIM + ctx_dim, N_CLASSES)
        self.opt = torch.optim.Adam(self.m.parameters(), lr=lr)
        self.cap, self.k = cap, k
        self.buf: list[tuple[torch.Tensor, int, torch.Tensor]] = []
        self.seen = 0
        self.g = torch.Generator().manual_seed(seed + 99)

    def _in(self, x, ctx):
        return torch.cat([x, ctx]) if self.ctx_dim > 0 else x

    def train_step(self, x, y, ctx):
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


class SVMPVote:
    """SVMP direct_vote; ctx_dim>0 ⇒ context-keyed LabelVault."""
    def __init__(self, seed, ctx_dim):
        cfg = SVMPConfig(seed=seed, n_classes=N_CLASSES)
        self.ctx_dim = ctx_dim
        self.a = SelfValidatingAgent(cfg, IN_DIM, direct_vote=True,
                                     vote_scale=10.0, ctx_dim=ctx_dim)

    def train_step(self, x, y, ctx):
        self.a.step(x, y, context=ctx if self.ctx_dim > 0 else None)

    def predict(self, x, ctx):
        return self.a.predict(x, context=ctx if self.ctx_dim > 0 else None)


def run(make, make_task, ctx_dim):
    finals = []
    for seed in SEEDS:
        learner = make(seed, ctx_dim)
        task = make_task(seed)
        T = task.n_tasks
        acc = [[None] * T for _ in range(T)]
        for i in range(T):
            ctx = onehot(i, ctx_dim)
            for _ in range(STEPS):
                x, y = task.sample(i)
                learner.train_step(x, y, ctx)
            for j in range(i + 1):
                cj = onehot(j, ctx_dim)
                c = 0
                for _ in range(EVAL_N):
                    x, y = task.sample(j)
                    c += int(learner.predict(x, cj) == y)
                acc[i][j] = c / EVAL_N
        finals.append(sum(acc[T - 1][j] for j in range(T)) / T)
    return st.mean(finals), st.pstdev(finals)


def regime(title, make_task):
    print(title)
    print(f"  {'method':22s} | final acc (±sd)")
    conds = [
        ("replay", CtxReplay, 0),
        ("replay + context", CtxReplay, N_TASKS),
        ("SVMP vote", SVMPVote, 0),
        ("SVMP vote + context", SVMPVote, N_TASKS),
    ]
    out = {}
    for name, cls, cd in conds:
        m, sd = run(cls, make_task, cd)
        out[name] = m
        print(f"  {name:22s} | {m:.3f} (±{sd:.3f})")
    return out


def main():
    print("Combining standard replay with SVMP's context key "
          f"({N_CLASSES}cls/{N_TASKS}tasks, {STEPS} steps/task, n={len(SEEDS)}, "
          f"oracle context)\n")
    split = regime("[A] CLASS-incremental (disjoint classes)",
                   lambda s: SplitContinualTask(N_CLASSES, N_TASKS, IN_DIM, seed=s))
    print()
    perm = regime("[B] DOMAIN-incremental (conflicting labels)",
                  lambda s: PermutedLabelTask(N_CLASSES, N_TASKS, IN_DIM, seed=s))

    print("\nReading:")
    print(f"  [A] disjoint classes: context is redundant — replay {split['replay']:.2f} "
          f"≈ replay+ctx {split['replay + context']:.2f},")
    print(f"      SVMP {split['SVMP vote']:.2f} ≈ SVMP+ctx "
          f"{split['SVMP vote + context']:.2f}. Adding context does no harm.")
    print(f"  [B] conflicting labels — where BOTH methods failed alone: adding the "
          f"context key FLIPS")
    print(f"      failure→success on EITHER. Plain replay {perm['replay']:.2f} → "
          f"replay+ctx {perm['replay + context']:.2f}; SVMP vote")
    print(f"      {perm['SVMP vote']:.2f} → SVMP+ctx {perm['SVMP vote + context']:.2f}. "
          f"The combination is the answer: the standard")
    print(f"      rehearsal tool + a context signal. SVMP's research contribution is "
          f"discovering that context")
    print(f"      task-free from the reward stream (parts 4-5, ~partial without the "
          f"oracle) — bolt it onto")
    print(f"      replay and you rescue the regime where the boring workhorse breaks.")


if __name__ == "__main__":
    main()
