import torch

from svmp.config import VaultConfig
from svmp.vault import GrowingVault


def _vault(**kw):
    cfg = VaultConfig(dim=8, **kw)
    return GrowingVault(cfg)


def test_empty_vault_reports_gap():
    v = _vault()
    r = v.query(torch.randn(8))
    assert r.gap is True
    assert len(v) == 0


def test_closed_gate_never_writes():
    v = _vault()
    action = v.consolidate(torch.randn(8), torch.randn(8), gate=0.0, target=1.0)
    assert action == "skipped"
    assert len(v) == 0


def test_open_gate_adds_entry():
    v = _vault()
    action = v.consolidate(torch.randn(8), torch.randn(8), gate=0.9, target=1.0)
    assert action == "add"
    assert len(v) == 1


def test_similar_key_strengthens_not_duplicates():
    v = _vault(merge_threshold=0.9)
    key = torch.randn(8)
    v.consolidate(key, key, gate=0.9, target=1.0)
    # Near-identical key should strengthen the existing entry.
    action = v.consolidate(key + 1e-3, key, gate=0.9, target=1.0)
    assert action == "strengthen"
    assert len(v) == 1


def test_conviction_calibrates_toward_target():
    v = _vault(merge_threshold=0.9, calibration_lr=0.5, init_conviction=0.3)
    key = torch.randn(8)
    v.consolidate(key, key, gate=1.0, target=1.0)
    before = float(v.conviction[0])
    for _ in range(10):
        v.consolidate(key, key, gate=1.0, target=1.0)
    after = float(v.conviction[0])
    assert after > before
    assert after <= 1.0


def test_decay_prunes_unsupported_entries():
    v = _vault(decay=0.5, prune_floor=0.2, init_conviction=0.3)
    v.consolidate(torch.randn(8), torch.randn(8), gate=0.5, target=0.0)
    assert len(v) == 1
    for _ in range(5):
        v.decay()
    assert len(v) == 0
