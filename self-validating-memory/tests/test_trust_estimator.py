"""TDD for a *learnable* source-trust estimator (Phase 4, the design's gap).

The fixed-tau robust aggregator is a hand-tuned heuristic with a hand-set
threshold. The design says the missing capability is *learning to assess source
quality*. This trains a small estimator to weight retrieved sources using only
the same external signal the rest of the system uses — the externally revealed
correct answer — never per-source reliability labels.

Honest, seed-stable findings (see examples/experiment_learned_trust.py, n=8),
with the training objective aligned to the L2 evaluation metric:
  - the estimator clearly beats the trust-only mean aggregate (+~0.08, 8/8), and
  - it modestly beats the hand-tuned fixed-tau robust heuristic (+~0.02, 7/8).
We hard-assert only the rock-solid claim (beats mean); the +0.02 robust margin
is reported in the experiment, not gated by a brittle unit test.

Tests written BEFORE the implementation; they must fail first.
"""
import functools

import torch

from svmp.config import RoleConfig
from svmp.roles import Verifier
from svmp.roles.trust_estimator import SourceTrustEstimator, train_trust_estimator


def _episodes(seed, protos=None, n=400, k=4, dim=16, nclass=8):
    g = torch.Generator().manual_seed(seed)
    if protos is None:
        protos = torch.randn(nclass, dim, generator=g)
    eps = []
    for _ in range(n):
        tc = int(torch.randint(nclass, (1,), generator=g))
        n_true = int(torch.randint(0, k + 1, (1,), generator=g))
        embs, trust = [], []
        for i in range(k):
            if i < n_true:                                   # coherent truth
                e = protos[tc] + 0.25 * torch.randn(dim, generator=g)
                mu = 0.75                                    # partially-informative
            else:                                            # diverse, strict lie
                w = int(torch.randint(nclass - 1, (1,), generator=g))
                w = w if w < tc else w + 1
                e = protos[w] + 0.25 * torch.randn(dim, generator=g)
                mu = 0.50
            embs.append(e)
            trust.append(float(torch.clamp(mu + 0.15 * torch.randn(1, generator=g),
                                           0.05, 0.95)))
        eps.append((torch.stack(embs), torch.tensor(trust), tc))
    return eps, protos


@functools.lru_cache(maxsize=1)
def _trained():
    """Train once (seed 0) and reuse across tests; return (est, test_eps, protos)."""
    train_eps, protos = _episodes(0)
    est = train_trust_estimator(train_eps, protos, epochs=25)
    test_eps, _ = _episodes(1000, protos=protos)            # held-out, same task
    return est, test_eps, protos


def _evidence_acc(weight_fn, eps, protos) -> float:
    correct = 0
    for embs, trust, tc in eps:
        agg = (weight_fn(embs, trust).unsqueeze(1) * embs).sum(0)
        correct += int(int(torch.cdist(agg.unsqueeze(0), protos).argmin()) == tc)
    return correct / len(eps)


def _verifier_acc(aggregation, eps, protos) -> float:
    cfg = RoleConfig(dim=16)
    v = Verifier(cfg, search_fn=lambda q, k: [], aggregation=aggregation)
    correct = 0
    for embs, trust, tc in eps:
        v.search_fn = lambda q, k, s=(embs, trust): list(zip(s[0], s[1].tolist()))
        ev = v.verify(torch.zeros(16))
        correct += int(int(torch.cdist(ev.embedding.unsqueeze(0), protos).argmin()) == tc)
    return correct / len(eps)


def test_estimator_outputs_valid_weights():
    est = SourceTrustEstimator()
    embs = torch.randn(4, 16)
    trust = torch.tensor([0.5, 0.6, 0.7, 0.4])
    w = est(embs, trust).detach()
    assert w.shape == (4,)
    assert abs(float(w.sum()) - 1.0) < 1e-5
    assert float(w.min()) >= 0.0


def test_trained_estimator_beats_trust_only_mean():
    est, test_eps, protos = _trained()
    mean_acc = _verifier_acc("mean", test_eps, protos)
    learned_acc = _evidence_acc(lambda e, t: est(e, t).detach(), test_eps, protos)
    assert learned_acc > mean_acc + 0.02


def test_verifier_learned_path_returns_valid_evidence():
    """Exercise the Verifier aggregation='learned' integration end-to-end."""
    est, _, _ = _trained()
    cfg = RoleConfig(dim=16)
    sources = [(torch.randn(16), 0.6) for _ in range(4)]
    v = Verifier(cfg, search_fn=lambda q, k: sources, aggregation="learned",
                 trust_estimator=est)
    ev = v.verify(torch.randn(16))
    assert ev.embedding.shape == (16,)
    assert 0.0 <= ev.source_quality <= 1.0
    assert ev.n_sources == 4


def test_learned_aggregation_requires_an_estimator():
    cfg = RoleConfig(dim=16)
    try:
        Verifier(cfg, aggregation="learned")
        assert False, "expected ValueError when trust_estimator is missing"
    except ValueError:
        pass
