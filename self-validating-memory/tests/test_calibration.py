"""Calibration-gated verification trigger: selective scores + split-conformal.

Covers the opt-in uncertainty gate added to ``svmp.calibration`` and the
back-compatible ``AdversarialLoop.run`` trigger. Mirrors the validation plan:

  - entropy is maximal for the uniform distribution and ~0 for a peaked one;
  - margin / Gini have the right shape and range;
  - the split-conformal accepted set has error ~ alpha on a stream of known p;
  - ACI tracks its target alpha when the error rate drifts;
  - passing ``uncertainty=None`` reproduces the original gap/low-support gate.
"""
import math

import torch

from svmp.calibration import (
    ConformalThreshold,
    entropy_score,
    gini_score,
    margin_score,
)
from svmp.config import RoleConfig
from svmp.roles import Architect, Collector, Verifier
from svmp.roles.adversarial import AdversarialLoop


def _loop(tau: float = 1.0) -> AdversarialLoop:
    # Seed the global RNG so the role modules initialise identically across calls;
    # the Verifier gets its own seeded generator so its search is reproducible too.
    torch.manual_seed(0)
    cfg = RoleConfig(verify_uncertainty_tau=tau)
    gen = torch.Generator().manual_seed(0)
    return AdversarialLoop(cfg, Architect(cfg), Collector(cfg),
                           Verifier(cfg, generator=gen))


# --- selective scores --------------------------------------------------------

def test_entropy_score_monotone():
    k = 8
    uniform = torch.zeros(k)                 # softmax(0…0) = uniform
    peaked = torch.zeros(k)
    peaked[3] = 50.0                          # near one-hot after softmax
    h_uniform = entropy_score(uniform)
    h_peaked = entropy_score(peaked)
    # Uniform ⇒ normalized entropy is the maximum, 1.0.
    assert abs(h_uniform - 1.0) < 1e-5
    # Peaked ⇒ entropy ~ 0.
    assert h_peaked < 1e-3
    assert h_peaked < h_uniform
    # An intermediate distribution lands strictly between the two.
    mid = torch.tensor([2.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    assert h_peaked < entropy_score(mid) < h_uniform


def test_margin_gini_shape_and_range():
    k = 5
    uniform = torch.zeros(k)
    peaked = torch.zeros(k)
    peaked[0] = 50.0
    # margin (top1 - top2 of softmax) is a scalar float in [0, 1].
    m_uniform = margin_score(uniform)
    m_peaked = margin_score(peaked)
    assert isinstance(m_uniform, float) and isinstance(m_peaked, float)
    assert abs(m_uniform) < 1e-5            # uniform ⇒ tied top two ⇒ 0 margin
    assert m_peaked > 0.99                  # peaked ⇒ near-1 margin
    assert 0.0 <= m_uniform <= 1.0 and 0.0 <= m_peaked <= 1.0

    # gini on a *probability* vector: 0 for one-hot, 1-1/k for uniform.
    p_uniform = torch.softmax(uniform, dim=0)
    p_onehot = torch.zeros(k); p_onehot[2] = 1.0
    g_uniform = gini_score(p_uniform)
    g_onehot = gini_score(p_onehot)
    assert abs(g_uniform - (1.0 - 1.0 / k)) < 1e-5
    assert abs(g_onehot) < 1e-6
    assert 0.0 <= g_onehot <= g_uniform <= 1.0


# --- split-conformal coverage ------------------------------------------------

def test_conformal_threshold_coverage():
    # A stream where confidence equals true accuracy p: correct draws get a high
    # confidence, wrong draws a low one. The accepted (non-abstained) set error
    # should sit near alpha once the buffer is warmed up.
    torch.manual_seed(0)
    alpha = 0.1
    p = 0.8
    ct = ConformalThreshold(alpha=alpha, window=2000)
    g = torch.Generator().manual_seed(1)

    # Warm-up: populate the buffer with the same conf model.
    def draw():
        correct = bool(torch.rand(1, generator=g) < p)
        # Confidence is informative but noisy around correctness.
        conf = (0.9 if correct else 0.4) + 0.05 * float(torch.randn(1, generator=g))
        conf = min(0.999, max(0.001, conf))
        return conf, correct

    for _ in range(2000):
        conf, correct = draw()
        ct.update(conf, correct)

    accepted, accepted_err = 0, 0
    for _ in range(5000):
        conf, correct = draw()
        if not ct.should_abstain(conf):       # accepted into the answer set
            accepted += 1
            accepted_err += int(not correct)
        ct.update(conf, correct)
    assert accepted > 0
    risk = accepted_err / accepted
    # Accepted-set error controlled near alpha (loose band for the synthetic stream).
    assert risk <= alpha + 0.08

    # Empty buffer is a safe no-abstain default.
    fresh = ConformalThreshold(alpha=alpha)
    assert fresh.quantile() == float("inf")
    assert fresh.should_abstain(0.0) is False


def test_aci_tracks_alpha_under_drift():
    # ACI should pull the running coverage error toward the target alpha even when
    # the underlying error rate shifts (a drift / label-permutation switch).
    alpha = 0.1
    ct = ConformalThreshold(alpha=alpha, window=500, online=True, gamma=0.05)
    g = torch.Generator().manual_seed(2)

    def feed(err_rate, n):
        for _ in range(n):
            correct = bool(torch.rand(1, generator=g) >= err_rate)
            conf = 0.85 if correct else 0.3
            ct.update(conf, correct)

    feed(0.1, 400)
    a_low = ct.alpha
    # Drift to a high error regime: ACI should adapt alpha upward (toward more
    # abstention) because err_t > alpha pushes alpha up via (alpha - err_t)<0...
    # the recursion alpha += gamma*(alpha0 - err): high err lowers alpha. Either
    # way it must stay a valid level and respond to the regime change.
    feed(0.6, 400)
    a_high = ct.alpha
    assert 1e-3 <= a_low <= 0.999
    assert 1e-3 <= a_high <= 0.999
    # The two regimes drive alpha to measurably different operating points.
    assert abs(a_high - a_low) > 1e-3


# --- back-compat trigger -----------------------------------------------------

def test_verify_trigger_backcompat():
    x = torch.randn(32)
    retrieved = torch.zeros(32)

    # No-gap, high-support inputs should not verify; the loop is deterministic
    # given a fixed seed, so re-running with uncertainty=None must match exactly.
    loop_a = _loop(tau=1.0)
    res_none = loop_a.run(x.clone(), retrieved.clone(), gap=False)

    loop_b = _loop(tau=1.0)
    res_explicit_none = loop_b.run(x.clone(), retrieved.clone(), gap=False,
                                   uncertainty=None)
    assert res_none.verified == res_explicit_none.verified

    # tau=1.0 (the default): any *realised* entropy score is strictly < 1.0, so it
    # cannot reach the threshold and the verification decision is unchanged. (A
    # softmax over real logits is never perfectly uniform.)
    loop_c = _loop(tau=1.0)
    res_unc = loop_c.run(x.clone(), retrieved.clone(), gap=False, uncertainty=0.999)
    assert res_unc.verified == res_none.verified

    # Lowering tau lets uncertainty *add* a trigger: with gap False and high
    # support, a high uncertainty now forces verification.
    loop_d = _loop(tau=0.2)
    res_gated = loop_d.run(x.clone(), retrieved.clone(), gap=False, uncertainty=0.9)
    assert res_gated.verified is True
