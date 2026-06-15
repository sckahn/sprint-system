"""Statistical-rigor check for the real-retriever result.

The headline numbers in experiment_real_retriever.py come from a single
query split. This re-runs the CONFUSABLE (adversarial) regime across many random
splits + estimator seeds — reusing the cached embeddings — and reports the
distribution of paired deltas so we can tell whether the effects are real:

  - does robust really HURT vs mean? (robust − mean < 0 consistently?)
  - does learned stay safe? (learned − mean ≈ 0 or > 0?)
  - does learned really beat robust? (learned − robust > 0 consistently?)

    pip install -r requirements-real.txt
    PYTHONPATH=. OMP_NUM_THREADS=1 python examples/experiment_real_significance.py
"""
from __future__ import annotations

import statistics as st

import torch

from svmp.real_retriever import EmbeddingRetriever, topic_centroids
from svmp.roles import train_trust_estimator

from experiment_real_retriever import (  # reuse cached-embedding builder
    CONFUSABLE,
    DISTINCT,
    K,
    _episodes,
    _evidence_acc,
    build,
)

N_SEEDS = 12


def run_regime(categories, tag, label):
    corpus_emb, corpus_labels, q_emb, q_labels, names = build(categories, tag)
    protos = topic_centroids(corpus_emb, corpus_labels, len(names))
    retr = EmbeddingRetriever(corpus_emb, corpus_labels, trust_mode="uniform")
    n = len(q_labels)
    h = n // 2

    d_lm, d_lr, d_rm = [], [], []   # learned-mean, learned-robust, robust-mean
    means, robusts, learneds = [], [], []
    for seed in range(N_SEEDS):
        perm = torch.randperm(n, generator=torch.Generator().manual_seed(seed))
        qe, ql = q_emb[perm], q_labels[perm]
        train_eps = _episodes(retr, qe[:h], ql[:h])
        est = train_trust_estimator(train_eps, protos, epochs=15,
                                    temperature=0.5, seed=seed)
        m = _evidence_acc(retr, protos, qe[h:], ql[h:], "mean")
        r = _evidence_acc(retr, protos, qe[h:], ql[h:], "robust")
        le = _evidence_acc(retr, protos, qe[h:], ql[h:], "learned", est=est)
        means.append(m); robusts.append(r); learneds.append(le)
        d_lm.append(le - m); d_lr.append(le - r); d_rm.append(r - m)

    def stat(name, d):
        mean = st.mean(d)
        sd = st.pstdev(d)
        # paired "wins" and a rough t-stat (mean / (sd/sqrt(n)))
        wins = sum(1 for x in d if x > 0)
        t = mean / (sd / (len(d) ** 0.5)) if sd > 0 else float("inf")
        print(f"    {name:<16} Δ = {mean:+.4f} ± {sd:.4f}   "
              f"wins {wins}/{len(d)}   t≈{t:+.2f}")

    print(f"\n[{label}]  (n={N_SEEDS} splits)")
    print(f"    mean={st.mean(means):.3f}  robust={st.mean(robusts):.3f}  "
          f"learned={st.mean(learneds):.3f}")
    stat("learned-mean", d_lm)
    stat("learned-robust", d_lr)
    stat("robust-mean", d_rm)
    print("    (|t|>2.2 ≈ significant at p<0.05 for n=12, paired)")


def main():
    print("=" * 72)
    print("Real-retriever significance — paired deltas across random splits")
    print("=" * 72)
    run_regime(CONFUSABLE, "confusable", "CONFUSABLE (adversarial real retrieval)")
    run_regime(DISTINCT, "distinct", "DISTINCT (benign real retrieval)")


if __name__ == "__main__":
    main()
