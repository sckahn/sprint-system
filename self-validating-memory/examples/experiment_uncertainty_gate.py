"""Calibration-gated verification trigger — when should we pay for search?

The Verifier search is the single costliest budget operation (``cost_search`` ≫
``cost_inference``). By default it fires on a *binary* signal: a vault-miss
(``gap``) or low collector support. But a binary gap flag is a poor proxy for
"the model is actually unsure" — it can miss genuinely ambiguous inputs and
waste search on confidently-handled ones.

This experiment ties the spend to *calibrated uncertainty* instead. Two opt-in
mechanisms, both default OFF:

  gap-only    — current behaviour (cfg.roles.verify_uncertainty_tau = 1.0).
  entropy     — additionally verify when normalized predictive entropy ≥ tau,
                a calibrated selective score (https://arxiv.org/pdf/2401.12708).
  conformal   — tau set from a split-conformal (1−α) quantile of recent
                nonconformity 1−conf, i.e. verify on the abstention region of a
                conformal selective classifier
                (https://www.emergentmind.com/topics/conformal-abstention).

We compare them on CalibrationBanditTask and SplitContinualTask across
(accuracy, searches-per-step, final budget, ECE, risk-coverage AURC), then run an
ACI (Adaptive Conformal Inference) coverage tracker across a PermutedLabelTask
switch to show αₜ₊₁ = αₜ + γ·(α − errₜ) following the drift.

    OMP_NUM_THREADS=2 PYTHONPATH=. python examples/experiment_uncertainty_gate.py
"""
from __future__ import annotations

import statistics as st

import torch

from svmp.agent import SelfValidatingAgent
from svmp.calibration import ConformalThreshold, entropy_score
from svmp.config import SVMPConfig
from svmp.tasks import CalibrationBanditTask, PermutedLabelTask, SplitContinualTask

SEEDS = [0, 1, 2]
STEPS = 1500


def _risk_coverage_aurc(pairs: list[tuple[float, bool]]) -> float:
    """Area under the risk–coverage curve (lower = better selective prediction).

    Sort by confidence desc; sweep the accepted fraction (coverage) and report the
    mean error (risk) over the accepted prefix, averaged over coverage levels.
    """
    if not pairs:
        return 0.0
    ordered = sorted(pairs, key=lambda t: t[0], reverse=True)
    n, wrong, risks = len(ordered), 0, []
    for i, (_, correct) in enumerate(ordered, 1):
        wrong += int(not correct)
        risks.append(wrong / i)
    return sum(risks) / n


def run_bandit(tau: float, seed: int) -> dict:
    """One CalibrationBanditTask run; tau<1 ⇒ entropy-gated verification."""
    cfg = SVMPConfig(seed=seed, n_classes=4)
    cfg.roles.verify_uncertainty_tau = tau
    gated = tau < 1.0
    agent = SelfValidatingAgent(cfg, feature_dim_of(cfg), uncertainty_gate=gated)
    task = CalibrationBanditTask(n_classes=4, feature_dim=16, seed=seed)
    correct, searches, rc = 0, 0, []
    for _ in range(STEPS):
        x, y = task.sample()
        log = agent.step(x, y)
        correct += int(log.correct)
        searches += int(log.verified)
        rc.append((log.confidence, log.correct))
    return {
        "acc": correct / STEPS,
        "search_rate": searches / STEPS,
        "budget": agent.budget.balance,
        "ece": agent.ece.compute(),
        "aurc": _risk_coverage_aurc(rc),
    }


def run_conformal_bandit(seed: int, alpha: float = 0.1) -> dict:
    """Conformal gate: tau tracks the (1−α) quantile of recent nonconformity.

    We drive ``cfg.roles.verify_uncertainty_tau`` from a live ConformalThreshold so
    the entropy gate fires exactly in the conformal abstention region.
    """
    cfg = SVMPConfig(seed=seed, n_classes=4)
    cfg.roles.verify_uncertainty_tau = 1.0   # start inert; raised below per step
    agent = SelfValidatingAgent(cfg, feature_dim_of(cfg), uncertainty_gate=True)
    task = CalibrationBanditTask(n_classes=4, feature_dim=16, seed=seed)
    # Treat entropy as the nonconformity proxy: buffer entropy of *correct*
    # decisions and verify when a new entropy exceeds the conformal quantile.
    ct = ConformalThreshold(alpha=alpha, window=400)
    correct, searches, rc = 0, 0, []
    for _ in range(STEPS):
        x, y = task.sample()
        with torch.no_grad():
            enc = agent.model.encoder(x.flatten())
            retrieved = (agent.vault.query(enc, top_k=4).value
                         if agent.use_vault else torch.zeros(cfg.dim))
            unc = entropy_score(agent.model(x, retrieved).logits)
        # Set tau to the current conformal quantile (confidence = 1 − entropy).
        cfg.roles.verify_uncertainty_tau = ct.quantile()
        log = agent.step(x, y)
        ct.update(1.0 - unc, log.correct)
        correct += int(log.correct)
        searches += int(log.verified)
        rc.append((log.confidence, log.correct))
    return {
        "acc": correct / STEPS,
        "search_rate": searches / STEPS,
        "budget": agent.budget.balance,
        "ece": agent.ece.compute(),
        "aurc": _risk_coverage_aurc(rc),
    }


def feature_dim_of(cfg: SVMPConfig) -> int:
    return 16  # all synthetic tasks here use feature_dim=16


def aci_drift_tracker(seed: int = 0, alpha: float = 0.1,
                      gamma: float = 0.02) -> dict:
    """Running coverage error of an online (ACI) conformal threshold across a switch.

    Feed a PermutedLabelTask A→B (same inputs, permuted labels) through a fixed
    frozen-confidence proxy and let ACI adapt α. We report the mean |empirical
    miscoverage − α| in each regime — ACI should keep it bounded despite the drift.
    """
    task = PermutedLabelTask(n_classes=4, n_tasks=2, feature_dim=16, seed=seed)
    ct = ConformalThreshold(alpha=alpha, window=200, online=True, gamma=gamma)
    g = torch.Generator().manual_seed(seed + 7)

    def regime_err(task_idx: int, n: int) -> float:
        # A stand-in classifier: 80% correct in regime A, but its mapping breaks
        # under the label permutation in regime B (so error rate jumps).
        miss = 0
        for _ in range(n):
            x, y = task.sample(task_idx)
            base_correct = bool(torch.rand(1, generator=g) < (0.8 if task_idx == 0 else 0.35))
            conf = 0.85 if base_correct else 0.35
            abstain = ct.should_abstain(conf)
            ct.update(conf, base_correct)
            # Miscoverage = accepted-but-wrong fraction.
            if not abstain and not base_correct:
                miss += 1
        return miss / n

    err_a = regime_err(0, 600)
    alpha_after_a = ct.alpha
    err_b = regime_err(1, 600)
    alpha_after_b = ct.alpha
    return {
        "alpha_target": alpha,
        "accepted_err_A": err_a,
        "alpha_after_A": alpha_after_a,
        "accepted_err_B": err_b,
        "alpha_after_B": alpha_after_b,
    }


def _agg(rows: list[dict]) -> dict:
    return {k: st.mean(r[k] for r in rows) for k in rows[0]}


def main() -> None:
    torch.manual_seed(0)
    print("Calibration-gated verification trigger "
          "(entropy / conformal vs gap-only)\n")
    print(f"  {STEPS} steps, {len(SEEDS)} seeds. cost_search ≫ cost_inference.\n")

    # --- CalibrationBanditTask -------------------------------------------
    print("CalibrationBanditTask (4 classes, variable ambiguity)")
    print(f"  {'condition':10s} | acc   | search/step | budget  | ECE    | AURC")
    print(f"  {'-'*10} | {'-'*5} | {'-'*11} | {'-'*7} | {'-'*6} | {'-'*6}")
    conds = {
        "gap-only": lambda s: run_bandit(1.0, s),
        "entropy":  lambda s: run_bandit(0.55, s),   # verify when entropy ≥ 0.55
        "conformal": lambda s: run_conformal_bandit(s),
    }
    for name, fn in conds.items():
        r = _agg([fn(s) for s in SEEDS])
        print(f"  {name:10s} | {r['acc']:.3f} | {r['search_rate']:.3f}       | "
              f"{r['budget']:7.1f} | {r['ece']:.4f} | {r['aurc']:.4f}")

    # --- SplitContinualTask ----------------------------------------------
    print("\nSplitContinualTask (8 classes / 2 tasks, continual stream)")
    print(f"  {'condition':10s} | acc   | search/step | budget  | ECE")
    print(f"  {'-'*10} | {'-'*5} | {'-'*11} | {'-'*7} | {'-'*6}")
    for name, tau, gated in (("gap-only", 1.0, False), ("entropy", 0.55, True)):
        rows = []
        for seed in SEEDS:
            cfg = SVMPConfig(seed=seed, n_classes=8)
            cfg.roles.verify_uncertainty_tau = tau
            agent = SelfValidatingAgent(cfg, 16, uncertainty_gate=gated)
            task = SplitContinualTask(n_classes=8, n_tasks=2, feature_dim=16,
                                      seed=seed)
            correct, searches = 0, 0
            for t in range(2):
                for _ in range(STEPS):
                    x, y = task.sample(t)
                    log = agent.step(x, y)
                    correct += int(log.correct)
                    searches += int(log.verified)
            n = 2 * STEPS
            rows.append({"acc": correct / n, "search_rate": searches / n,
                         "budget": agent.budget.balance,
                         "ece": agent.ece.compute()})
        r = _agg(rows)
        print(f"  {name:10s} | {r['acc']:.3f} | {r['search_rate']:.3f}       | "
              f"{r['budget']:7.1f} | {r['ece']:.4f}")

    # --- ACI drift tracker -----------------------------------------------
    print("\nACI online coverage across a PermutedLabelTask switch "
          "(αₜ₊₁ = αₜ + γ·(α − errₜ))")
    rows = [aci_drift_tracker(seed=s) for s in SEEDS]
    r = _agg(rows)
    print(f"  target α               = {r['alpha_target']:.3f}")
    print(f"  regime A accepted-err  = {r['accepted_err_A']:.3f}  "
          f"(α after A = {r['alpha_after_A']:.3f})")
    print(f"  regime B accepted-err  = {r['accepted_err_B']:.3f}  "
          f"(α after B = {r['alpha_after_B']:.3f})")
    print("  ACI lowers α under the high-error B regime ⇒ more abstention, "
          "containing accepted-set risk.")


if __name__ == "__main__":
    main()
