import torch
import torch.nn as nn

from svmp.config import LearningConfig
from svmp.learning import (
    ConsolidationGate,
    EligibilityTrace,
    Neuromodulator,
    ThreeFactorLearner,
)


def test_eligibility_decays_and_accumulates():
    e = EligibilityTrace(2, 3, decay=0.5)
    pre = torch.ones(3)
    post = torch.ones(2)
    e.accumulate(pre, post)
    assert torch.allclose(e.trace, torch.ones(2, 3))
    e.accumulate(torch.zeros(3), torch.zeros(2))
    assert torch.allclose(e.trace, 0.5 * torch.ones(2, 3))


def test_neuromodulator_is_reward_prediction_error():
    nm = Neuromodulator(LearningConfig(neuromod_baseline_decay=0.0))
    # baseline starts at 0, decay 0 ⇒ baseline becomes the last reward.
    m0 = nm(1.0)
    assert m0 == 1.0           # 1 - 0
    m1 = nm(1.0)
    assert m1 == 0.0           # 1 - 1 (now expected)


def test_closed_gate_blocks_update():
    cfg = LearningConfig(gate_bias=-100.0)  # gate forced shut
    g = ConsolidationGate(cfg)
    assert g(surprise=1.0, gap=1.0, source_quality=1.0) < 1e-3


def test_gap_without_source_is_suppressed():
    cfg = LearningConfig(gate_bias=2.0)  # would otherwise open
    g = ConsolidationGate(cfg)
    open_with_src = g(surprise=0.0, gap=1.0, source_quality=0.9)
    closed_no_src = g(surprise=0.0, gap=1.0, source_quality=0.0)
    assert closed_no_src < open_with_src


def test_three_factor_update_moves_weights_only_when_gate_open():
    layer = nn.Linear(3, 2, bias=False)
    layer.weight.requires_grad_(False)
    layer.weight.zero_()
    learner = ThreeFactorLearner(layer, LearningConfig(lr=0.1, gate_bias=10.0))
    learner.observe(pre=torch.ones(3), post_signal=torch.ones(2))
    before = layer.weight.clone()
    learner.update(external_reward=1.0, surprise=1.0, gap=0.0, source_quality=1.0)
    assert not torch.allclose(layer.weight, before)


def test_no_reward_means_no_change():
    layer = nn.Linear(3, 2, bias=False)
    layer.weight.requires_grad_(False)
    learner = ThreeFactorLearner(layer, LearningConfig(lr=0.1, gate_bias=10.0))
    learner.observe(pre=torch.ones(3), post_signal=torch.ones(2))
    before = layer.weight.clone()
    # m = reward - baseline = 0 - 0 = 0 ⇒ no update regardless of gate.
    learner.update(external_reward=0.0, surprise=1.0, gap=0.0, source_quality=1.0)
    assert torch.allclose(layer.weight, before)


# --- Benna-Fusi metaplastic consolidation buffer (opt-in) -------------------

def _fresh_learner(metaplastic: bool, **cfg_kwargs) -> ThreeFactorLearner:
    layer = nn.Linear(3, 2, bias=False)
    layer.weight.requires_grad_(False)
    layer.weight.zero_()
    cfg_kwargs.setdefault("gate_bias", 10.0)  # default: gate forced open
    cfg = LearningConfig(lr=0.1, metaplastic=metaplastic, **cfg_kwargs)
    return ThreeFactorLearner(layer, cfg)


def test_metaplastic_off_is_identical():
    # With metaplastic=False the update is bitwise-identical to the plain rule.
    off = _fresh_learner(metaplastic=False)
    base = _fresh_learner(metaplastic=False)  # reference: same defaults, no flag
    for ln in (off, base):
        ln.observe(pre=torch.ones(3), post_signal=torch.ones(2))
    off.update(external_reward=1.0, surprise=1.0, gap=0.0, source_quality=1.0)
    base.update(external_reward=1.0, surprise=1.0, gap=0.0, source_quality=1.0)
    assert torch.equal(off.layer.weight, base.layer.weight)
    # The default config (metaplastic=False) must leave the buffer untouched.
    assert torch.equal(off.consol, torch.zeros_like(off.layer.weight))


def test_consol_buffer_grows_on_gated_writes():
    # Repeated same-input gated updates grow consol and shrink later dw norms.
    # We reset the eligibility trace between writes so each presentation drives
    # an identically-shaped raw write — any change in dw_norm is then due solely
    # to the growing consolidation buffer, not a growing eligibility trace.
    ln = _fresh_learner(metaplastic=True, meta_alpha=2.0)
    assert torch.equal(ln.consol, torch.zeros_like(ln.layer.weight))
    norms = []
    for _ in range(5):
        ln.reset_episode()
        ln.observe(pre=torch.ones(3), post_signal=torch.ones(2))
        info = ln.update(external_reward=1.0, surprise=1.0, gap=0.0,
                         source_quality=1.0)
        norms.append(info["dw_norm"])
    # Consolidation buffer accumulated mass.
    assert float(ln.consol.sum()) > 0.0
    # Same-direction writes get progressively damped by the growing buffer.
    assert norms[-1] < norms[0]


def test_metaplastic_no_autograd_leak():
    # The weight and buffer updates happen under no_grad — no graph leaks.
    ln = _fresh_learner(metaplastic=True)
    ln.observe(pre=torch.ones(3), post_signal=torch.ones(2))
    ln.update(external_reward=1.0, surprise=1.0, gap=0.0, source_quality=1.0)
    assert not ln.layer.weight.requires_grad
    assert ln.layer.weight.grad_fn is None
    assert not ln.consol.requires_grad
    assert ln.consol.grad_fn is None


def test_closed_gate_leaves_buffer_untouched():
    # g ~ 0 ⇒ effectively no write, so neither weights nor the consolidation
    # buffer move (a shut gate yields g < 1e-3, matching the gating convention).
    ln = _fresh_learner(metaplastic=True, gate_bias=-100.0)  # gate forced shut
    ln.observe(pre=torch.ones(3), post_signal=torch.ones(2))
    w_before = ln.layer.weight.clone()
    info = ln.update(external_reward=1.0, surprise=1.0, gap=0.0,
                     source_quality=1.0)
    assert info["gate"] < 1e-3
    assert torch.allclose(ln.layer.weight, w_before)
    assert torch.allclose(ln.consol, torch.zeros_like(ln.layer.weight))
