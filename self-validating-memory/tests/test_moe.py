import torch

from svmp.config import MoEConfig
from svmp.moe import MoELayer


def test_topk_limits_active_experts():
    cfg = MoEConfig(dim=8, hidden=16, n_experts=6, top_k=2)
    moe = MoELayer(cfg)
    out = moe(torch.randn(8))
    assert out.experts_used <= 2
    assert out.y.shape == (8,)


def test_variable_topk_overrides_default():
    cfg = MoEConfig(dim=8, n_experts=6, top_k=2)
    moe = MoELayer(cfg)
    out = moe(torch.randn(8), top_k=1)
    assert out.experts_used == 1


def test_load_balance_loss_is_nonnegative():
    cfg = MoEConfig(dim=8, n_experts=4, top_k=2)
    moe = MoELayer(cfg)
    out = moe(torch.randn(4, 8))
    assert float(out.load_balance_loss.detach()) >= 0.0


def test_batched_and_single_consistent_shapes():
    cfg = MoEConfig(dim=8, n_experts=4, top_k=2)
    moe = MoELayer(cfg)
    assert moe(torch.randn(8)).y.shape == (8,)
    assert moe(torch.randn(5, 8)).y.shape == (5, 8)
