"""SVMP vs. how people actually do continual learning (Phase-6 reality check).

The Phase-6 arc shows SVMP's decay-free direct-vote memory resists catastrophic
forgetting. But is that machinery worth it next to the STANDARD tools a practitioner
would reach for on the same streaming problem? This pits SVMP head-to-head against
the conventional baselines, on the same ``SplitContinualTask``, same step budget,
same seeds, same online (one-sample-at-a-time) regime:

  * joint (i.i.d.)   — a plain MLP trained on all tasks MIXED. No forgetting because
                       it never sees a task boundary. The upper-bound "if you had all
                       the data at once" ceiling — not a continual method.
  * naive sequential — a plain MLP fine-tuned A then B with Adam. The floor everyone
                       knows forgets.
  * replay           — naive + a reservoir buffer replayed each step. THE standard,
                       boringly-strong practical method. Stores raw (x, y).
  * EWC              — Elastic Weight Consolidation: a Fisher-weighted penalty pinning
                       important weights. The classic regulariser. Needs task
                       boundaries; stores Fisher + a param snapshot, no raw data.
  * SVMP             — our agent with direct_vote=True (decay-free LabelVault).

What each needs is part of the comparison: replay stores raw inputs; EWC needs task
boundaries; SVMP stores encoded keys + verified labels and needs neither an explicit
boundary nor a raw-input buffer.

    PYTHONPATH=. python examples/experiment_vs_baselines.py
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


class MLP(nn.Module):
    def __init__(self, n_cls):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(IN_DIM, HID), nn.ReLU(),
            nn.Linear(HID, HID), nn.ReLU(),
            nn.Linear(HID, n_cls))

    def forward(self, x):
        return self.net(x)


# --- learners: each exposes train_step(x, y), predict(x), end_task(samples) ---
class Naive:
    def __init__(self, seed, lr=1e-3):
        torch.manual_seed(seed)
        self.m = MLP(N_CLASSES)
        self.opt = torch.optim.Adam(self.m.parameters(), lr=lr)

    def train_step(self, x, y):
        self.opt.zero_grad()
        loss = F.cross_entropy(self.m(x).unsqueeze(0), torch.tensor([y]))
        loss.backward()
        self.opt.step()

    @torch.no_grad()
    def predict(self, x):
        return int(self.m(x).argmax())

    def end_task(self, samples):
        pass


class Replay(Naive):
    """Reservoir-sampled experience replay — the standard practical CL workhorse."""
    def __init__(self, seed, cap=200, k=8, lr=1e-3):
        super().__init__(seed, lr)
        self.cap, self.k = cap, k
        self.buf: list[tuple[torch.Tensor, int]] = []
        self.seen = 0
        self.g = torch.Generator().manual_seed(seed + 99)

    def train_step(self, x, y):
        self.seen += 1
        if len(self.buf) < self.cap:                       # reservoir add
            self.buf.append((x.detach().clone(), y))
        else:
            j = int(torch.randint(self.seen, (1,), generator=self.g))
            if j < self.cap:
                self.buf[j] = (x.detach().clone(), y)
        xs, ys = [x], [y]
        for _ in range(min(self.k, len(self.buf))):
            i = int(torch.randint(len(self.buf), (1,), generator=self.g))
            bx, by = self.buf[i]
            xs.append(bx)
            ys.append(by)
        self.opt.zero_grad()
        loss = F.cross_entropy(self.m(torch.stack(xs)), torch.tensor(ys))
        loss.backward()
        self.opt.step()


class EWC(Naive):
    """Elastic Weight Consolidation (Kirkpatrick et al. 2017): Fisher-weighted L2
    anchor to past optima. Needs task boundaries (consolidates at end_task)."""
    def __init__(self, seed, lam=400.0, lr=1e-3):
        super().__init__(seed, lr)
        self.lam = lam
        self.anchors: list[tuple[dict, dict]] = []         # (fisher, star)

    def train_step(self, x, y):
        self.opt.zero_grad()
        loss = F.cross_entropy(self.m(x).unsqueeze(0), torch.tensor([y]))
        for fisher, star in self.anchors:
            for n, p in self.m.named_parameters():
                loss = loss + (self.lam / 2) * (fisher[n] * (p - star[n]) ** 2).sum()
        loss.backward()
        self.opt.step()

    def end_task(self, samples):
        fisher = {n: torch.zeros_like(p) for n, p in self.m.named_parameters()}
        for x, y in samples:
            self.opt.zero_grad()
            F.cross_entropy(self.m(x).unsqueeze(0), torch.tensor([y])).backward()
            for n, p in self.m.named_parameters():
                if p.grad is not None:
                    fisher[n] += p.grad.detach() ** 2
        for n in fisher:
            fisher[n] /= max(1, len(samples))
        star = {n: p.detach().clone() for n, p in self.m.named_parameters()}
        self.anchors.append((fisher, star))


class SVMP:
    def __init__(self, seed):
        cfg = SVMPConfig(seed=seed, n_classes=N_CLASSES)
        self.a = SelfValidatingAgent(cfg, IN_DIM, direct_vote=True, vote_scale=10.0)

    def train_step(self, x, y):
        self.a.step(x, y)

    def predict(self, x):
        return self.a.predict(x)

    def end_task(self, samples):
        pass


def _eval(learner, task, t):
    c = 0
    for _ in range(EVAL_N):
        x, y = task.sample(t)
        c += int(learner.predict(x) == y)
    return c / EVAL_N


def run_continual(make, make_task):
    rows = []
    for seed in SEEDS:
        learner = make(seed)
        task = make_task(seed)
        acc = [[None] * N_TASKS for _ in range(N_TASKS)]
        for i in range(N_TASKS):
            samples = []
            for _ in range(STEPS):
                x, y = task.sample(i)
                learner.train_step(x, y)
                if len(samples) < 256:
                    samples.append((x.detach().clone(), y))
            learner.end_task(samples)
            for j in range(i + 1):
                acc[i][j] = _eval(learner, task, j)
        peak = acc[0][0]
        forget = sum(acc[j][j] - acc[N_TASKS - 1][j]
                     for j in range(N_TASKS - 1)) / (N_TASKS - 1)
        final = sum(acc[N_TASKS - 1][j] for j in range(N_TASKS)) / N_TASKS
        rows.append((peak, forget, final))
    return rows


def run_joint(make_task):
    """Plain MLP on a MIXED i.i.d. stream — the no-forgetting ceiling."""
    rows = []
    for seed in SEEDS:
        torch.manual_seed(seed)
        m = MLP(N_CLASSES)
        opt = torch.optim.Adam(m.parameters(), lr=1e-3)
        task = make_task(seed)
        g = torch.Generator().manual_seed(seed + 7)
        for _ in range(STEPS * N_TASKS):
            t = int(torch.randint(N_TASKS, (1,), generator=g))
            x, y = task.sample(t)
            opt.zero_grad()
            F.cross_entropy(m(x).unsqueeze(0), torch.tensor([y])).backward()
            opt.step()

        class _W:
            @torch.no_grad()
            def predict(self, x):
                return int(m(x).argmax())
        w = _W()
        final = st.mean(_eval(w, task, j) for j in range(N_TASKS))
        rows.append((None, None, final))
    return rows


def _agg(rows):
    finals = [r[2] for r in rows]
    forgets = [r[1] for r in rows if r[1] is not None]
    peaks = [r[0] for r in rows if r[0] is not None]
    return (st.mean(peaks) if peaks else None,
            st.mean(forgets) if forgets else None,
            st.mean(finals), st.pstdev(finals))


def _regime(title, make_task):
    print(title)
    print(f"  {'method':24s} | peak-A | forget | final acc (±sd) | note")
    conds = [
        ("joint (i.i.d.) ceiling", lambda: run_joint(make_task), "all mixed; not CL"),
        ("naive sequential", lambda: run_continual(Naive, make_task), "plain fine-tune"),
        ("replay (reservoir)", lambda: run_continual(Replay, make_task), "stores raw (x,y)"),
        ("EWC", lambda: run_continual(EWC, make_task), "needs task boundaries"),
        ("SVMP direct_vote", lambda: run_continual(SVMP, make_task), "verified-fact vote"),
    ]
    out = {}
    for name, fn, note in conds:
        peak, forget, final, sd = _agg(fn())
        out[name] = final
        ps = f"{peak:.3f}" if peak is not None else "  -  "
        fs = f"{forget:+.3f}" if forget is not None else "  -   "
        print(f"  {name:24s} | {ps}  | {fs} | {final:.3f} (±{sd:.3f}) | {note}")
    return out


def main():
    print("SVMP vs standard continual-learning baselines "
          f"({N_CLASSES}cls/{N_TASKS}tasks, {STEPS} steps/task, online, "
          f"n={len(SEEDS)} seeds, chance={1/N_CLASSES:.2f})\n")

    split = _regime("[A] CLASS-incremental (SplitContinualTask — disjoint classes)",
                    lambda s: SplitContinualTask(N_CLASSES, N_TASKS, IN_DIM, seed=s))
    print()
    perm = _regime("[B] DOMAIN-incremental (PermutedLabelTask — same inputs, "
                   "conflicting labels)",
                   lambda s: PermutedLabelTask(N_CLASSES, N_TASKS, IN_DIM, seed=s))

    print("\nReading — the gap to 'general usage' depends entirely on the regime:")
    print(f"  [A] class-incremental: plain experience REPLAY is the boringly-strong "
          f"winner ({split['replay (reservoir)']:.2f},")
    print(f"      ≈ the {split['joint (i.i.d.) ceiling']:.2f} joint ceiling); SVMP "
          f"{split['SVMP direct_vote']:.2f} clearly beats naive "
          f"{split['naive sequential']:.2f} and EWC {split['EWC']:.2f} but trails "
          f"replay. On\n      disjoint classes, replaying a few stored exemplars "
          f"simply solves it.")
    print(f"  [B] domain-incremental: the SAME input has conflicting labels, so even "
          f"the i.i.d. ceiling")
    print(f"      ({perm['joint (i.i.d.) ceiling']:.2f}) is low and REPLAY loses its "
          f"edge ({perm['replay (reservoir)']:.2f}) — replaying (x, old-label) now "
          f"contradicts")
    print(f"      (x, new-label). Here no method without a CONTEXT signal wins; SVMP "
          f"{perm['SVMP direct_vote']:.2f} ≈ the others.")
    print("  Takeaway: SVMP is in the league of standard tools (beats naive/EWC) but "
          "does not beat plain")
    print("  replay where replay applies. Its distinct value is the assumption "
          "profile — boundary-free,")
    print("  no raw-input buffer, verified-only — and the domain-incremental case "
          "(part 4-5 context keys),")
    print("  which is exactly where the standard replay workhorse breaks down too.")


if __name__ == "__main__":
    main()
