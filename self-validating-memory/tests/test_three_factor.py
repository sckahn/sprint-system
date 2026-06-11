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
