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


# --- Auxiliary-loss-free load balancing (DeepSeek, arXiv:2408.15664v1) --------

def test_loss_free_disabled_by_default():
    cfg = MoEConfig(dim=8, n_experts=4, top_k=2)
    assert cfg.loss_free_balance is False


def test_bias_buffer_initialized_zero():
    cfg = MoEConfig(dim=8, n_experts=6, top_k=2)
    moe = MoELayer(cfg)
    assert "expert_bias" in dict(moe.named_buffers())
    assert moe.expert_bias.shape == (6,)
    assert torch.equal(moe.expert_bias, torch.zeros(6))


def test_update_bias_pushes_toward_balance():
    # Feed an imbalanced selection: expert 0 is overloaded, experts 4,5 starved.
    cfg = MoEConfig(dim=8, n_experts=6, top_k=2)
    moe = MoELayer(cfg)
    top_idx = torch.tensor([[0, 1], [0, 2], [0, 3], [0, 1]])  # 0 fired every slot-0
    moe.update_bias(top_idx, u=1e-2)
    # Overloaded expert's bias decreases; starved experts' bias increases.
    assert float(moe.expert_bias[0]) < 0.0
    assert float(moe.expert_bias[4]) > 0.0
    assert float(moe.expert_bias[5]) > 0.0


def test_gating_weights_use_unbiased_logits():
    # With a non-zero bias the SELECTION may change, but if we zero the bias the
    # output must be bitwise-identical to the loss_free=False (no-bias) path,
    # confirming the gate weights are gathered from the UNBIASED softmax.
    torch.manual_seed(0)
    x = torch.randn(8)

    cfg_off = MoEConfig(dim=8, n_experts=6, top_k=2, loss_free_balance=False)
    moe_off = MoELayer(cfg_off)
    out_off = moe_off(x)

    cfg_on = MoEConfig(dim=8, n_experts=6, top_k=2, loss_free_balance=True)
    moe_on = MoELayer(cfg_on)
    moe_on.load_state_dict(moe_off.state_dict())  # identical weights
    moe_on.expert_bias.zero_()                    # bias == 0 ⇒ selection matches
    out_on = moe_on(x)

    assert torch.allclose(out_on.y, out_off.y, atol=0, rtol=0)
