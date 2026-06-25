"""Tests for the decay-free verified-fact memory and its wiring into the agent."""
import torch
import torch.nn.functional as F

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.label_vault import LabelVault
from svmp.context import BOCDDetector, ContextInferrer, RecognizingContextManager
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


# --- Adaptive Memory Realignment (opt-in) ----------------------------------
def test_realign_region_prunes_only_matching():
    # Two distinct (orthogonal) regions; realigning one leaves the other intact.
    lv = LabelVault(dim=4, n_classes=5, merge_threshold=0.9)
    lv.write(_unit(1, 0, 0, 0), label=3, gate=1.0)
    lv.write(_unit(0, 1, 0, 0), label=1, gate=1.0)
    pruned = lv.realign_region(_unit(1, 0, 0.02, 0))   # near region A only
    assert pruned == 1
    assert len(lv) == 1
    assert int(lv.labels[0]) == 1                      # region B survived
    assert int(lv.vote(_unit(0, 1, 0, 0)).argmax()) == 1


def test_realign_region_noop_on_empty_vault():
    lv = LabelVault(dim=4, n_classes=5)
    assert lv.realign_region(_unit(1, 0, 0, 0)) == 0
    assert len(lv) == 0


def test_realign_region_repopulates_new_label():
    # Drift: the same region's correct label changes; prune the stale entry then
    # write the new fact → the vote returns the NEW label.
    lv = LabelVault(dim=4, n_classes=5, sim_threshold=0.5, merge_threshold=0.9)
    lv.write(_unit(1, 0, 0, 0), label=3, gate=1.0)
    assert int(lv.vote(_unit(1, 0, 0.05, 0)).argmax()) == 3
    lv.realign_region(_unit(1, 0, 0, 0))
    assert len(lv) == 0
    lv.write(_unit(1, 0, 0, 0), label=4, gate=1.0)     # repopulate with new label
    assert int(lv.vote(_unit(1, 0, 0.05, 0)).argmax()) == 4


def test_amr_disabled_by_default():
    cfg = SVMPConfig(seed=0, n_classes=8)
    agent = SelfValidatingAgent(cfg, 16, direct_vote=True)
    assert agent.amr is False
    assert agent.amr_manager is None


# --- Learnable Drift Compensation: realign stored keys (opt-in) ------------
def test_realign_preserves_norms():
    # A near-identity projector must leave each key's magnitude exactly unchanged
    # (only direction is realigned), just like write() preserves per-key norm.
    torch.manual_seed(0)
    lv = LabelVault(dim=6, n_classes=5)
    for _ in range(5):
        k = torch.randn(6)
        lv.write(k, label=int(torch.randint(5, (1,))), gate=1.0)
    before = lv.keys.norm(dim=1).clone()
    proj = torch.nn.Linear(6, 6)
    with torch.no_grad():                      # near-identity map
        proj.weight.copy_(torch.eye(6) + 0.01 * torch.randn(6, 6))
        proj.bias.zero_()
    lv.realign(proj)
    after = lv.keys.norm(dim=1)
    assert torch.allclose(before, after, atol=1e-5)


def test_realign_noop_on_empty_vault():
    lv = LabelVault(dim=4, n_classes=5)
    proj = torch.nn.Linear(4, 4)
    lv.realign(proj)                           # must not raise / change anything
    assert len(lv) == 0


def test_realign_recovers_alignment():
    # Synthetically rotate the stored keys (simulating encoder drift), fit a
    # projector on (rotated, original) pairs, then realign: cosine of the realigned
    # keys back to the originals must improve toward 1.
    torch.manual_seed(0)
    dim = 8
    originals = F.normalize(torch.randn(10, dim), dim=1)
    # A fixed rotation stands in for the encoder's drift old->new.
    a = torch.randn(dim, dim)
    rot, _ = torch.linalg.qr(a)                # orthogonal rotation
    rotated = originals @ rot.T

    lv = LabelVault(dim=dim, n_classes=5)
    for i in range(len(rotated)):
        lv.write(rotated[i], label=i % 5, gate=1.0)
    pre = F.cosine_similarity(F.normalize(lv.keys, dim=1), originals, dim=1).mean()

    # Fit projector mapping rotated(old) -> original(new).
    proj = torch.nn.Linear(dim, dim)
    opt = torch.optim.Adam(proj.parameters(), lr=1e-2)
    for _ in range(400):
        opt.zero_grad()
        loss = F.mse_loss(proj(rotated), originals)
        loss.backward()
        opt.step()

    lv.realign(proj)
    post = F.cosine_similarity(F.normalize(lv.keys, dim=1), originals, dim=1).mean()
    assert float(post) > float(pre)
    assert float(post) > 0.9


def test_drift_realign_disabled_by_default():
    cfg = SVMPConfig(seed=0, n_classes=8)
    agent = SelfValidatingAgent(cfg, 16, direct_vote=True)
    assert agent.drift_realign is False
    assert agent._drift_proj is None
    assert agent._enc_snapshot is None


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


# --- BOCD change detector (opt-in) over the reward stream -----------------
def test_bocd_holds_slot_when_rewards_stay_high():
    inf = ContextInferrer(ctx_dim=4, detector='bocd')
    switched = any(inf.observe(1.0) for _ in range(500))
    assert not switched
    assert inf.slot == 0


def test_bocd_fires_on_reward_collapse():
    inf = ContextInferrer(ctx_dim=4, detector='bocd')
    for _ in range(300):          # establish a high-reward run on context 0
        inf.observe(1.0)
    switched = any(inf.observe(0.0) for _ in range(200))   # regime collapses
    assert switched
    assert inf.slot == 1
    assert float(inf.context()[1]) == 1.0


def test_bocd_does_not_fire_during_rising_warmup():
    # Noisy reward whose mean rises 0.2 -> 0.6 within the warmup window must not
    # be mistaken for a changepoint (no established high run yet to collapse from).
    torch.manual_seed(0)
    inf = ContextInferrer(ctx_dim=4, detector='bocd', warmup=80)
    fired = False
    for i in range(80):
        mean = 0.2 + 0.4 * (i / 79)            # rising 0.2 -> 0.6
        r = 1.0 if float(torch.rand(1)) < mean else 0.0
        fired = fired or inf.observe(r)
    assert not fired
    assert inf.slot == 0


def test_bocd_default_detector_is_ema():
    # No detector flag == current EMA behaviour, including the internal state.
    inf = ContextInferrer(ctx_dim=4)
    assert inf.detector == 'ema'
    assert inf._bocd is None
    mgr = RecognizingContextManager(ctx_dim=4, auto_detect=False)
    assert mgr.detector == 'ema'
    assert mgr._bocd is None


# --- re-recognition of a returned context via reward probing --------------
def _probe(mgr, reward, n):
    for _ in range(n):
        mgr.observe(reward)


def test_recognise_probes_and_adopts_best_rewarded_slot():
    mgr = RecognizingContextManager(ctx_dim=4, probe_steps=3, auto_detect=False)
    mgr.force_search()                 # candidates: [slot0, fresh slot1]
    _probe(mgr, 0.0, 3)                # slot0 probes poorly
    _probe(mgr, 1.0, 3)                # fresh slot1 probes well → adopted
    assert mgr.slot == 1
    assert mgr.n_known == 2


def test_recognise_reselects_returned_slot_without_allocating():
    mgr = RecognizingContextManager(ctx_dim=4, probe_steps=3, auto_detect=False)
    mgr.force_search(); _probe(mgr, 0.0, 3); _probe(mgr, 1.0, 3)   # learn slot1 (now current)
    mgr.force_search()                 # candidates: [slot1(cur), slot0, fresh slot2]
    _probe(mgr, 0.0, 3)                # current slot1 probes poorly (back on A)
    _probe(mgr, 1.0, 3)                # slot0 rewards best → re-selected
    _probe(mgr, 0.0, 3)                # fresh slot2 poor
    assert mgr.slot == 0
    assert mgr.n_known == 2            # no new slot allocated on return


def test_recognise_early_accepts_current_on_false_alarm():
    # A spurious search when the current slot is still good costs ONE probe window.
    mgr = RecognizingContextManager(ctx_dim=4, probe_steps=3, auto_detect=False,
                                    accept=0.6)
    mgr.force_search(); _probe(mgr, 0.0, 3); _probe(mgr, 1.0, 3)   # settle on slot1
    base = mgr.probe_cost
    mgr.force_search()                 # false alarm; slot1 is still correct
    _probe(mgr, 1.0, 3)                # current probes high → early-accept, stop
    assert mgr.slot == 1
    assert mgr.mode == "normal"
    assert mgr.probe_cost - base == 3  # only one window, not the whole candidate set


def test_recognise_no_autodetect_holds_through_collapse():
    mgr = RecognizingContextManager(ctx_dim=4, auto_detect=False)
    _probe(mgr, 1.0, 200)
    _probe(mgr, 0.0, 200)             # would trigger a detector, but auto_detect off
    assert mgr.slot == 0
    assert mgr.mode == "normal"


def test_recognise_tracks_probe_cost():
    mgr = RecognizingContextManager(ctx_dim=4, probe_steps=3, auto_detect=False)
    mgr.force_search()
    _probe(mgr, 0.0, 3); _probe(mgr, 1.0, 3)
    assert mgr.probe_cost == 6
