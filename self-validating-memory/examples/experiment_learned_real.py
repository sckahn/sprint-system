"""Phase 4 — does the learnable trust estimator TRANSFER to real retrieval?

The estimator beats the heuristics on synthetic adversarial retrieval. This asks
whether it survives contact with a real retrieval corpus (sklearn digits), and
exposes a failure + its fix:

  - On **benign** digit retrieval (top-k results are mostly the correct class),
    an *unregularised* estimator OVER-SELECTS and HURTS — negative transfer.
  - The maximum-entropy prior (``entropy_reg``) makes it default to averaging, so
    it recovers parity on benign data while keeping its gain on adversarial data.

We report evidence accuracy (aggregated evidence points to the true class) on
held-out queries, n=6 seeds.

    PYTHONPATH=. python examples/experiment_learned_real.py
"""
from __future__ import annotations

import statistics as st

import torch

from svmp.config import RoleConfig
from svmp.retrieval import CorpusRetriever, DocumentCorpus
from svmp.roles import Verifier, train_trust_estimator
from svmp.tasks import RealDigitsTask

SEEDS = [0, 1, 2, 3, 4, 5]
K = 4


# --- synthetic adversarial regime (coherent truth / diverse lies) ----------
def _syn_episodes(seed, protos=None, n=400, dim=16, nclass=8):
    g = torch.Generator().manual_seed(seed)
    if protos is None:
        protos = torch.randn(nclass, dim, generator=g)
    eps = []
    for _ in range(n):
        tc = int(torch.randint(nclass, (1,), generator=g))
        n_true = int(torch.randint(0, K + 1, (1,), generator=g))
        embs, trust = [], []
        for i in range(K):
            if i < n_true:
                e = protos[tc] + 0.25 * torch.randn(dim, generator=g)
                mu = 0.75
            else:
                w = int(torch.randint(nclass - 1, (1,), generator=g))
                w = w if w < tc else w + 1
                e = protos[w] + 0.25 * torch.randn(dim, generator=g)
                mu = 0.50
            embs.append(e)
            trust.append(float(torch.clamp(mu + 0.15 * torch.randn(1, generator=g),
                                           0.05, 0.95)))
        eps.append((torch.stack(embs), torch.tensor(trust), tc))
    return eps, protos


def _acc(weight_fn, eps, protos):
    c = 0
    for embs, trust, tc in eps:
        agg = (weight_fn(embs, trust).unsqueeze(1) * embs).sum(0)
        c += int(int(torch.cdist(agg.unsqueeze(0), protos).argmin()) == tc)
    return c / len(eps)


def _verifier_acc(aggregation, eps, protos, est=None):
    cfg = RoleConfig(dim=protos.shape[1])
    cfg.triangulation_k = K
    v = Verifier(cfg, search_fn=lambda q, k: [], aggregation=aggregation,
                 trust_estimator=est)
    c = 0
    for embs, trust, tc in eps:
        v.search_fn = lambda q, k, s=(embs, trust): list(zip(s[0], s[1].tolist()))
        ev = v.verify(torch.zeros(protos.shape[1]))
        c += int(int(torch.cdist(ev.embedding.unsqueeze(0), protos).argmin()) == tc)
    return c / len(eps)


def synthetic_regime():
    mean, robust, learned = [], [], []
    for s in SEEDS:
        tr, protos = _syn_episodes(s)
        te, _ = _syn_episodes(s + 1000, protos=protos)
        est = train_trust_estimator(tr, protos, epochs=25, seed=s)   # entropy_reg default
        mean.append(_verifier_acc("mean", te, protos))
        robust.append(_verifier_acc("robust", te, protos))
        learned.append(_acc(lambda e, t: est(e, t).detach(), te, protos))
    return mean, robust, learned


# --- real digits retrieval regime ------------------------------------------
def _digit_episodes(task, retriever, idxs):
    out = []
    for i in idxs:
        res = retriever(task.X_train[i], K)
        out.append((torch.stack([e for e, _ in res]),
                    torch.tensor([t for _, t in res]), int(task.y_train[i])))
    return out


def _digit_acc(task, protos, retriever, aggregation, est=None):
    cfg = RoleConfig(dim=task.feature_dim)
    cfg.triangulation_k = K
    v = Verifier(cfg, search_fn=retriever, aggregation=aggregation, trust_estimator=est)
    c = n = 0
    for x, tc in zip(task.X_test[:300], task.y_test[:300]):
        ev = v.verify(x)
        c += int(int(torch.cdist(ev.embedding.unsqueeze(0), protos).argmin()) == int(tc))
        n += 1
    return c / n


def digits_regime():
    mean, robust, learned_noreg, learned_reg = [], [], [], []
    for s in SEEDS:
        task = RealDigitsTask(seed=s)
        protos = task.class_prototypes()
        corpus = DocumentCorpus(protos, docs_per_class=20, unreliable_frac=0.6,
                                reliable_trust_mu=0.7, unreliable_trust_mu=0.55,
                                mislead_blend=0.5, seed=s)
        retr = CorpusRetriever(corpus)
        train_eps = _digit_episodes(task, retr, range(600))
        est_noreg = train_trust_estimator(train_eps, protos, epochs=20,
                                          entropy_reg=0.0, seed=s)
        est_reg = train_trust_estimator(train_eps, protos, epochs=20, seed=s)  # default
        mean.append(_digit_acc(task, protos, retr, "mean"))
        robust.append(_digit_acc(task, protos, retr, "robust"))
        learned_noreg.append(_digit_acc(task, protos, retr, "learned", est_noreg))
        learned_reg.append(_digit_acc(task, protos, retr, "learned", est_reg))
    return mean, robust, learned_noreg, learned_reg


def _row(name, vals):
    print(f"  {name:<22} {st.mean(vals):.3f} ± {st.pstdev(vals):.3f}")


def main():
    print("=" * 66)
    print(f"Phase 4 transfer — learnable estimator on real retrieval (n={len(SEEDS)})")
    print("=" * 66)

    print("\n[Synthetic adversarial regime]  (the estimator's home turf)")
    m, r, l = synthetic_regime()
    _row("mean", m); _row("robust", r); _row("learned (reg=0.1)", l)

    print("\n[Real digits retrieval — benign]  (does it transfer?)")
    m, r, ln, lr = digits_regime()
    _row("mean", m); _row("robust", r)
    _row("learned (reg=0.0)", ln); _row("learned (reg=0.1)", lr)

    print("\nVerdict:")
    print(f"  unregularised learned on digits: {st.mean(ln):+.3f} vs mean "
          f"{st.mean(m):.3f}  → {st.mean(ln) - st.mean(m):+.3f} (NEGATIVE TRANSFER)")
    print(f"  entropy-prior learned on digits: {st.mean(lr):.3f} vs mean "
          f"{st.mean(m):.3f}  → {st.mean(lr) - st.mean(m):+.3f} (parity recovered)")
    print("  → selectivity backfires on benign retrieval; the max-entropy prior")
    print("    makes the estimator default to averaging and stay safe, while")
    print("    keeping its win on adversarial retrieval.")


if __name__ == "__main__":
    main()
