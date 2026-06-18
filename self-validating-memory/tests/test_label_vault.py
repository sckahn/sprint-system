"""Tests for the decay-free verified-fact memory and its wiring into the agent."""
import torch

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.label_vault import LabelVault
from svmp.context import ContextInferrer
from svmp.tasks import SplitContinualTask


def _unit(*vals):
    v = torch.tensor(vals, dtype=torch.float32)
    return v / v.norm()


def test_write_then_vote_returns_stored_class():
    lv = LabelVault(dim=4, n_classes=5, sim_threshold=0.5)
    lv.write(_unit(1, 0, 0, 0), label=3, gate=1.0)
    vote = lv.vote(_unit(1, 0, 0.05, 0))     # near the stored key
    assert int(vote.argmax()) == 3
    assert vote[3] > 0


def test_vote_zero_for_unrelated_query():
    lv = LabelVault(dim=4, n_classes=5, sim_threshold=0.5)
    lv.write(_unit(1, 0, 0, 0), label=3, gate=1.0)
    vote = lv.vote(_unit(0, 1, 0, 0))        # orthogonal → below threshold
    assert torch.count_nonzero(vote) == 0


def test_vote_empty_memory_is_zero():
    lv = LabelVault(dim=4, n_classes=5)
    assert torch.count_nonzero(lv.vote(_unit(1, 0, 0, 0))) == 0


def test_gate_zero_skips_write():
    lv = LabelVault(dim=4, n_classes=5)
    assert lv.write(_unit(1, 0, 0, 0), label=2, gate=0.0) == "skipped"
    assert len(lv) == 0


def test_same_class_near_key_strengthens_not_adds():
    lv = LabelVault(dim=4, n_classes=5, merge_threshold=0.9)
    lv.write(_unit(1, 0, 0, 0), label=3, gate=1.0)
    c0 = float(lv.conviction[0])
    action = lv.write(_unit(1, 0.02, 0, 0), label=3, gate=1.0)
    assert action == "strengthen"
    assert len(lv) == 1
    assert lv.conviction[0] > c0             # conviction grows, never decays


def test_distinct_region_adds_entry():
    lv = LabelVault(dim=4, n_classes=5, merge_threshold=0.9)
    lv.write(_unit(1, 0, 0, 0), label=3, gate=1.0)
    lv.write(_unit(0, 1, 0, 0), label=1, gate=1.0)
    assert len(lv) == 2


def test_agent_direct_vote_populates_memory_and_predicts():
    cfg = SVMPConfig(seed=0, n_classes=8)
    agent = SelfValidatingAgent(cfg, 16, direct_vote=True, vote_scale=10.0)
    task = SplitContinualTask(8, 2, 16, seed=0)
    for _ in range(60):
        x, y = task.sample(0)
        agent.step(x, y)
    assert agent.label_vault is not None
    assert len(agent.label_vault) > 0
    pred = agent.predict(task.sample(0)[0])
    assert 0 <= pred < cfg.n_classes


def test_agent_without_direct_vote_has_no_label_vault():
    cfg = SVMPConfig(seed=0, n_classes=8)
    agent = SelfValidatingAgent(cfg, 16)
    assert agent.label_vault is None


# --- context keys: conflicting mappings disambiguated by context ----------
def _ctx(i, n=2):
    v = torch.zeros(n)
    v[i] = 1.0
    return v


def test_context_key_separates_conflicting_labels():
    # Same input region, two contexts, two different verified labels.
    lv = LabelVault(dim=4, n_classes=5, sim_threshold=0.5, ctx_dim=2)
    lv.write(_unit(1, 0, 0, 0), label=3, gate=1.0, context=_ctx(0))
    lv.write(_unit(1, 0, 0, 0), label=4, gate=1.0, context=_ctx(1))
    q = _unit(1, 0, 0.05, 0)
    assert int(lv.vote(q, context=_ctx(0)).argmax()) == 3
    assert int(lv.vote(q, context=_ctx(1)).argmax()) == 4


def test_context_mismatch_suppresses_vote():
    lv = LabelVault(dim=4, n_classes=5, sim_threshold=0.5, ctx_dim=2)
    lv.write(_unit(1, 0, 0, 0), label=3, gate=1.0, context=_ctx(0))
    # An orthogonal context shares no entries → no confident vote.
    assert torch.count_nonzero(lv.vote(_unit(1, 0, 0, 0), context=_ctx(1))) == 0


def test_no_context_path_is_backward_compatible():
    lv = LabelVault(dim=4, n_classes=5, sim_threshold=0.5)  # ctx_dim=0
    lv.write(_unit(1, 0, 0, 0), label=2, gate=1.0)
    assert int(lv.vote(_unit(1, 0, 0, 0)).argmax()) == 2


# --- task-free context inference from the reward stream -------------------
def test_inferrer_holds_slot_when_rewards_stay_high():
    inf = ContextInferrer(ctx_dim=4)
    switched = any(inf.observe(1.0) for _ in range(500))
    assert not switched
    assert inf.slot == 0


def test_inferrer_switches_on_reward_collapse():
    inf = ContextInferrer(ctx_dim=4)
    for _ in range(300):          # establish a high baseline on context 0
        inf.observe(1.0)
    switched = any(inf.observe(0.0) for _ in range(200))   # regime collapses
    assert switched
    assert inf.slot == 1
    assert float(inf.context()[1]) == 1.0


def test_inferrer_never_exceeds_slots():
    inf = ContextInferrer(ctx_dim=2)
    for _ in range(5):
        for _ in range(200):
            inf.observe(1.0)
        for _ in range(200):
            inf.observe(0.0)
    assert inf.slot <= 1
