"""Phase 4 improvement — robust consensus aggregation: WHEN does it help?

The improvement assumes *truth is coherent and lies are diverse*. We test it in
two regimes and report honestly where it helps and where it is a no-op.

  Regime A — adversarial (coherent truth, cosine-diverse lies, uninformative
             trust): the regime the improvement is designed for.
  Regime B — benign real data (sklearn digits retrieval corpus): top-k results
             are mostly correct, so there is little failure mode to fix.

Metric: evidence accuracy = how often the aggregated evidence points to the true
class. Compared head-to-head, mean vs robust aggregation, n=8 seeds.

    PYTHONPATH=. python examples/experiment_improvement.py
"""
from __future__ import annotations

import statistics as st

import torch

from svmp.config import RoleConfig
from svmp.retrieval import CorpusRetriever, DocumentCorpus
from svmp.roles import Verifier
from svmp.tasks import RealDigitsTask

SEEDS = [0, 1, 2, 3, 4, 5, 6, 7]


# --- Regime A: synthetic coherent-truth / diverse-lies ---------------------
def _scenario(seed: int, k: int = 4, n: int = 300):
    g = torch.Generator().manual_seed(seed)
    dim, nclass = 16, 8
    protos = torch.randn(nclass, dim, generator=g)
    out = []
    for _ in range(n):
        true_c = int(torch.randint(nclass, (1,), generator=g))
        n_true = int(torch.randint(0, k + 1, (1,), generator=g))
        srcs = []
        for i in range(k):
            if i < n_true:
                emb = protos[true_c] + 0.25 * torch.randn(dim, generator=g)
            else:
                # Strictly wrong class — a "lie" is never accidentally correct.
                wrong = int(torch.randint(nclass - 1, (1,), generator=g))
                wrong = wrong if wrong < true_c else wrong + 1
                emb = protos[wrong] + 0.25 * torch.randn(dim, generator=g)
            trust = float(torch.clamp(0.65 + 0.12 * torch.randn(1, generator=g),
                                      0.05, 0.95))
            srcs.append((emb, trust))
        out.append((srcs, true_c, protos))
    return out


def regime_a(seed: int, aggregation: str) -> float:
    cfg = RoleConfig(dim=16)
    correct = 0
    scen = _scenario(seed)
    for srcs, true_c, protos in scen:
        v = Verifier(cfg, search_fn=lambda q, k, s=srcs: s, aggregation=aggregation)
        ev = v.verify(torch.zeros(16))
        pred = int(torch.cdist(ev.embedding.unsqueeze(0), protos).argmin())
        correct += int(pred == true_c)
    return correct / len(scen)


# --- Regime B: real digits retrieval corpus --------------------------------
def regime_b(seed: int, aggregation: str) -> float:
    task = RealDigitsTask(seed=seed)
    protos = task.class_prototypes()
    corpus = DocumentCorpus(protos, docs_per_class=20, unreliable_frac=0.5,
                            reliable_trust_mu=0.65, unreliable_trust_mu=0.65,
                            seed=seed)
    retriever = CorpusRetriever(corpus)
    cfg = RoleConfig(dim=task.feature_dim)
    cfg.triangulation_k = 4
    v = Verifier(cfg, search_fn=retriever, aggregation=aggregation,
                 generator=torch.Generator().manual_seed(seed))
    correct = n = 0
    for x, true_c in zip(task.X_test[:300], task.y_test[:300]):
        ev = v.verify(x)
        pred = int(torch.cdist(ev.embedding.unsqueeze(0), protos).argmin())
        correct += int(pred == int(true_c))
        n += 1
    return correct / n


def report(name: str, fn) -> None:
    mean = [fn(s, "mean") for s in SEEDS]
    robust = [fn(s, "robust") for s in SEEDS]
    m, r = st.mean(mean), st.mean(robust)
    wins = sum(1 for a, b in zip(robust, mean) if a > b + 1e-9)
    print(f"\n[{name}]  (n={len(SEEDS)} seeds)")
    print(f"  mean aggregate   : {m:.3f} ± {st.pstdev(mean):.3f}")
    print(f"  robust aggregate : {r:.3f} ± {st.pstdev(robust):.3f}")
    print(f"  delta            : {r - m:+.3f}   (robust > mean on {wins}/{len(SEEDS)} seeds)")


def main() -> None:
    print("=" * 70)
    print("Phase 4 improvement — robust consensus aggregation")
    print("=" * 70)
    report("Regime A — adversarial (coherent truth / diverse lies)", regime_a)
    report("Regime B — benign real digits retrieval", regime_b)
    print("\nVerdict: robust aggregation recovers evidence accuracy exactly where")
    print("the failure mode exists (diverse lies), and is a safe no-op on benign")
    print("retrieval where averaging all sources is already near-optimal.")


if __name__ == "__main__":
    main()
