"""Central configuration for the Self-Validating Memory-Plasticity (SVMP) system.

All hyperparameters live here so experiments are reproducible and the mapping
to the design document (docs/architecture.md) stays explicit.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BudgetConfig:
    """Budget economy — computation as a finite survival resource (§4.2)."""

    total: float = 4000.0
    # Per-operation costs (deducted from the budget).
    cost_inference: float = 1.0
    cost_search: float = 6.0          # external verification is expensive
    cost_expert: float = 0.5          # per activated MoE expert
    # Maintenance: fixed per-round deduction that *tightens* like a curriculum.
    maintenance_base: float = 1.0
    maintenance_growth: float = 0.001  # added to maintenance each round
    # Reward is paid back into the budget, scaled by this factor.
    reward_to_budget: float = 6.0


@dataclass
class VaultConfig:
    """Growing vault — calibrated, evolving knowledge store (§4.1)."""

    dim: int = 32
    capacity: int = 512
    sim_temperature: float = 0.5
    gap_threshold: float = 0.45        # max similarity below this ⇒ knowledge gap
    init_conviction: float = 0.3
    calibration_lr: float = 0.2        # θ ← θ + α(target − θ)
    decay: float = 0.999              # per-round conviction decay (forgetting)
    prune_floor: float = 0.05          # entries below this are pruned
    merge_threshold: float = 0.9       # similarity above which we strengthen, not add


@dataclass
class MoEConfig:
    """Mixture-of-Experts — variable top-k routing priced against the budget (§4.3)."""

    dim: int = 32
    hidden: int = 64
    n_experts: int = 8
    top_k: int = 2
    load_balance_coef: float = 1e-2    # anti-collapse auxiliary loss


@dataclass
class LearningConfig:
    """Three-factor learning rule Δw = η · e · m · g (§4.4)."""

    lr: float = 0.05                   # η
    eligibility_decay: float = 0.9     # λ
    neuromod_baseline_decay: float = 0.99
    gate_surprise_coef: float = 1.0
    gate_gap_coef: float = 1.0
    gate_source_coef: float = 1.0
    gate_bias: float = -0.5            # default closed; opens under surprise/gap

    # Benna-Fusi metaplastic consolidation buffer (opt-in, default OFF).
    # Real-valued consolidation variable c that hardens synapses that have been
    # written often: c += alpha·g·|dw|, and each write is scaled by 1/(c+eps).
    # Reference: Zenke & Laborieux, "Theories of synaptic memory consolidation
    # and intelligent plasticity for continual learning"
    # (https://arxiv.org/abs/2405.16922), §Benna-Fusi cascade / metaplasticity.
    # Defaults reproduce the plain three-factor update bitwise (metaplastic=False).
    metaplastic: bool = False          # 켜면 consolidation buffer 활성화
    meta_alpha: float = 0.1            # consolidation 누적 속도 (c += alpha·g·|dw|)
    meta_eps: float = 1.0             # write 스케일 1/(c+eps); eps=1 ⇒ 초기 무변화


@dataclass
class RoleConfig:
    """Adversarial roles — Architect / Collector / Verifier (§3)."""

    dim: int = 32
    hidden: int = 64
    collector_agree_threshold: float = 0.5
    # Verifier: simulated source quality. Real systems plug a retriever here.
    source_quality_mean: float = 0.6
    source_quality_std: float = 0.25
    triangulation_k: int = 3           # independent sources cross-checked


@dataclass
class SVMPConfig:
    """Top-level config bundling every subsystem."""

    dim: int = 32
    n_classes: int = 4
    seed: int = 0

    budget: BudgetConfig = field(default_factory=BudgetConfig)
    vault: VaultConfig = field(default_factory=VaultConfig)
    moe: MoEConfig = field(default_factory=MoEConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    roles: RoleConfig = field(default_factory=RoleConfig)

    def __post_init__(self) -> None:
        # Keep the shared embedding dimension consistent across subsystems.
        self.vault.dim = self.dim
        self.moe.dim = self.dim
        self.roles.dim = self.dim
