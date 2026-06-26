"""End-to-end smoke + learning checks for the full self-validation loop."""
from svmp.train import train


def test_agent_learns_calibration_task():
    final = train(phase=1, steps=1200, log_every=10_000, seed=0, verbose=False)
    # A competent agent should clear chance (0.25 for 4 classes) comfortably and
    # stay alive (its earned reward must outpace the tightening maintenance).
    assert final["final_accuracy"] > 0.6
    assert final["budget"]["alive"] is True
    assert final["vault"]["size"] > 0


def test_positional_phase_runs():
    final = train(phase=2, steps=600, log_every=10_000, seed=0, verbose=False)
    assert final["final_accuracy"] > 0.5
    assert final["steps_run"] > 0


def test_single_step_log_shape():
    import torch
    from svmp.agent import SelfValidatingAgent
    from svmp.config import SVMPConfig

    cfg = SVMPConfig(seed=1)
    agent = SelfValidatingAgent(cfg, input_dim=16)
    log = agent.step(torch.randn(16), target=2)
    assert 0 <= log.action < cfg.n_classes
    assert 0.0 <= log.confidence <= 1.0
    assert 0.0 <= log.gate <= 1.0
    assert log.vault_action in ("add", "strengthen", "skipped")
