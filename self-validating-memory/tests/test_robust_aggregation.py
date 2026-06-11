"""TDD for the Phase-4 improvement: robust consensus aggregation in the Verifier.

Motivation (from the n=8 study): the baseline trust-weighted *mean* aggregate is
corrupted by incoherent outlier sources, so the verified evidence is often wrong
(evidence accuracy ~0.68) even when a coherent majority tells the truth. A robust
aggregate that keeps only the consensus cluster of sources should ignore diverse
lies and produce more accurate evidence — the exact weakness the design flags.

These tests are written BEFORE the implementation exists. They must fail first.
"""
import random
import statistics as st

import torch
import torch.nn.functional as F

from svmp.config import RoleConfig
from svmp.roles import Verifier


def _cos(a, b):
    return float(F.cosine_similarity(a.flatten(), b.flatten(), dim=0))


def test_robust_aggregate_ignores_incoherent_outlier():
    """With two coherent sources and one orthogonal liar (uniform trust), the
    robust aggregate should stay closer to the coherent direction than the mean
    aggregate, which is dragged toward the outlier."""
    cfg = RoleConfig(dim=8)
    u = torch.zeros(8); u[0] = 1.0          # coherent truth direction
    w = torch.zeros(8); w[1] = 1.0          # orthogonal lie
    sources = [(u.clone(), 0.6), (u.clone(), 0.6), (w.clone(), 0.6)]
    query = u.clone()

    mean_v = Verifier(cfg, search_fn=lambda q, k: sources, aggregation="mean")
    robust_v = Verifier(cfg, search_fn=lambda q, k: sources, aggregation="robust")

    agg_mean = mean_v.verify(query).embedding
    agg_robust = robust_v.verify(query).embedding
    assert _cos(agg_robust, u) > _cos(agg_mean, u)


def _scenario(seed, k=4, n=200):
    g = torch.Generator().manual_seed(seed)
    dim, nclass = 16, 8
    protos = torch.randn(nclass, dim, generator=g)
    out = []
    for _ in range(n):
        true_c = int(torch.randint(nclass, (1,), generator=g))
        n_true = int(torch.randint(0, k + 1, (1,), generator=g))
        srcs = []
        for i in range(k):
            if i < n_true:                                   # coherent truth
                emb = protos[true_c] + 0.25 * torch.randn(dim, generator=g)
            else:                                            # diverse lie
                wrong = int(torch.randint(nclass, (1,), generator=g))
                emb = protos[wrong] + 0.25 * torch.randn(dim, generator=g)
            trust = float(torch.clamp(0.65 + 0.12 * torch.randn(1, generator=g),
                                      0.05, 0.95))            # uninformative
            srcs.append((emb, trust))
        out.append((srcs, true_c, protos))
    return out


def _evidence_accuracy(aggregation: str) -> float:
    cfg = RoleConfig(dim=16)
    accs = []
    for seed in range(3):
        scen = _scenario(seed)
        correct = 0
        for srcs, true_c, protos in scen:
            v = Verifier(cfg, search_fn=lambda q, k, s=srcs: s,
                         aggregation=aggregation)
            ev = v.verify(torch.zeros(16))
            pred = int(torch.cdist(ev.embedding.unsqueeze(0), protos).argmin())
            correct += int(pred == true_c)
        accs.append(correct / len(scen))
    return st.mean(accs)


def test_robust_aggregation_improves_evidence_accuracy():
    """On coherent-truth / diverse-lies retrievals with uninformative trust,
    robust consensus aggregation must yield meaningfully more accurate evidence
    than the trust-weighted mean."""
    mean_acc = _evidence_accuracy("mean")
    robust_acc = _evidence_accuracy("robust")
    assert robust_acc > mean_acc + 0.05
