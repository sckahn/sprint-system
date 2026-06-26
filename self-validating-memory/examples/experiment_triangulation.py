"""Phase 4, isolated & statistically powered: does source-quality assessment
actually discriminate reliable from misleading evidence?

This isolates the Verifier's ``assess_source`` (the design's self-declared
weakest part) from the learning loop. For each seed we build a real retrieval
corpus over digit-class prototypes (40% misleading documents) and probe the
Verifier with every held-out test image, recording the assessed source quality
bucketed by whether the *retrieved* documents were actually reliable.

Two factors, fully crossed, n=8 seeds:
  prior  : informative  (reliable/unreliable trust priors differ — the source
                          truthfully self-reports authority)
           uninformative(both priors identical — self-report is useless, so the
                          ONLY signal is cross-source agreement)
  verifier: triangulated (k=3, agreement-discounted)
            naive        (k=1, trusts the prior at face value)

Metric: AUC = P(quality(reliable) > quality(unreliable)). 0.5 = no
discrimination, 1.0 = perfect. We also report the raw mean gap.

    PYTHONPATH=. python examples/experiment_triangulation.py
"""
from __future__ import annotations

import itertools
import statistics as st

import torch

from svmp.config import RoleConfig
from svmp.retrieval import CorpusRetriever, DocumentCorpus
from svmp.roles import Verifier
from svmp.tasks import RealDigitsTask

SEEDS = [0, 1, 2, 3, 4, 5, 6, 7]
MAX_QUERIES = 300  # held-out test images probed per condition


class NaiveVerifier(Verifier):
    """Trusts the source prior at face value — no triangulation."""

    def assess_source(self, raw_trust, agreement):
        return float(raw_trust.mean())


def auc(reliable: list[float], unreliable: list[float], rng) -> float:
    """Mann-Whitney AUC = P(reliable quality > unreliable quality)."""
    if not reliable or not unreliable:
        return float("nan")
    # Subsample pairs for speed when both lists are large.
    pairs = 20000
    wins = ties = 0
    for _ in range(pairs):
        r = reliable[int(rng.random() * len(reliable))]
        u = unreliable[int(rng.random() * len(unreliable))]
        if r > u:
            wins += 1
        elif r == u:
            ties += 1
    return (wins + 0.5 * ties) / pairs


def probe(seed: int, prior: str, verifier: str) -> dict:
    """Operational metric: does the assessed source quality predict whether the
    *aggregated evidence* actually points to the true class?

    That is the question the consolidation gate needs answered — a high quality
    score should mean "safe to consolidate this evidence". We bucket each query's
    quality by whether the trust-weighted evidence embedding is nearest the true
    prototype, and report AUC = P(quality | evidence correct > quality | wrong).
    """
    task = RealDigitsTask(seed=seed)
    protos = task.class_prototypes()
    mus = ((0.72, 0.58) if prior == "informative" else (0.65, 0.65))
    corpus = DocumentCorpus(protos, docs_per_class=20, unreliable_frac=0.5,
                            reliable_trust_mu=mus[0], unreliable_trust_mu=mus[1],
                            seed=seed)
    retriever = CorpusRetriever(corpus)
    cfg = RoleConfig(dim=task.feature_dim)
    if verifier == "naive":
        cfg.triangulation_k = 1
        v = NaiveVerifier(cfg, search_fn=retriever, aggregation="mean",
                          generator=torch.Generator().manual_seed(seed))
    else:
        # Baseline triangulation = mean aggregate + agreement-based quality.
        cfg.triangulation_k = 3
        v = Verifier(cfg, search_fn=retriever, aggregation="mean",
                     generator=torch.Generator().manual_seed(seed))

    q_correct, q_wrong = [], []
    X, Y = task.X_test[:MAX_QUERIES], task.y_test[:MAX_QUERIES]
    for x, true_c in zip(X, Y):
        ev = v.verify(x)
        pred_c = int(torch.cdist(ev.embedding.unsqueeze(0), protos).argmin())
        if pred_c == int(true_c):
            q_correct.append(ev.source_quality)
        else:
            q_wrong.append(ev.source_quality)

    rng = __import__("random").Random(seed)
    return {
        "auc": auc(q_correct, q_wrong, rng),
        "gap": ((st.mean(q_correct) if q_correct else 0.0)
                - (st.mean(q_wrong) if q_wrong else 0.0)),
        "evidence_acc": len(q_correct) / max(1, len(q_correct) + len(q_wrong)),
        "n_correct": len(q_correct), "n_wrong": len(q_wrong),
    }


def cell(prior: str, verifier: str) -> dict:
    runs = [probe(s, prior, verifier) for s in SEEDS]
    aucs = [r["auc"] for r in runs if r["auc"] == r["auc"]]  # drop nan
    gaps = [r["gap"] for r in runs]
    return {
        "auc_mean": st.mean(aucs), "auc_std": st.pstdev(aucs),
        "gap_mean": st.mean(gaps), "gap_std": st.pstdev(gaps),
        "aucs": aucs,
    }


def main() -> None:
    print("=" * 72)
    print(f"Phase 4 isolated — source-quality discrimination  (n={len(SEEDS)} seeds)")
    print("AUC = P(quality(reliable) > quality(unreliable));  0.5 = chance")
    print("=" * 72)

    results = {}
    for prior, verifier in itertools.product(["informative", "uninformative"],
                                             ["triangulated", "naive"]):
        results[(prior, verifier)] = cell(prior, verifier)

    print(f"\n{'prior':<14}{'verifier':<16}{'AUC':<18}{'mean gap':<14}")
    print("-" * 62)
    for (prior, verifier), r in results.items():
        print(f"{prior:<14}{verifier:<16}"
              f"{r['auc_mean']:.3f} ± {r['auc_std']:.3f}     "
              f"{r['gap_mean']:+.3f} ± {r['gap_std']:.3f}")

    print("\nKey contrast — when the source prior is UNINFORMATIVE")
    print("(self-reported authority is useless, agreement is the only signal):")
    tri = results[("uninformative", "triangulated")]
    nai = results[("uninformative", "naive")]
    print(f"  triangulated AUC = {tri['auc_mean']:.3f} ± {tri['auc_std']:.3f}")
    print(f"  naive        AUC = {nai['auc_mean']:.3f} ± {nai['auc_std']:.3f}")
    wins = sum(1 for t, n in zip(tri["aucs"], nai["aucs"]) if t > n)
    print(f"  triangulated beat naive on {wins}/{len(tri['aucs'])} seeds")
    delta = st.mean(t - n for t, n in zip(tri["aucs"], nai["aucs"]))
    print(f"  mean per-seed AUC advantage of triangulation: {delta:+.3f}")


if __name__ == "__main__":
    main()
