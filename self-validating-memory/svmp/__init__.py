"""SVMP — Self-Validating Memory-Plasticity learning system.

An executable realisation of the design "자기검증 기반 기억가소성 학습 시스템":
an agent that learns by forming hypotheses, verifying them externally, and
consolidating only verified knowledge — while treating computation as a finite
survival resource.

See docs/architecture.md for the full design-to-code mapping.
"""
from .agent import SelfValidatingAgent, StepLog
from .budget import BudgetEconomy
from .config import SVMPConfig
from .learning import (
    ConsolidationGate,
    EligibilityTrace,
    Neuromodulator,
    RewardTopology,
    ThreeFactorLearner,
)
from .model import SelfValidatingModel
from .moe import MoELayer
from .roles import AdversarialLoop, Architect, Collector, Verifier
from .vault import GrowingVault

__version__ = "0.1.0"

__all__ = [
    "SVMPConfig",
    "SelfValidatingAgent",
    "StepLog",
    "SelfValidatingModel",
    "GrowingVault",
    "BudgetEconomy",
    "MoELayer",
    "Architect",
    "Collector",
    "Verifier",
    "AdversarialLoop",
    "ThreeFactorLearner",
    "EligibilityTrace",
    "Neuromodulator",
    "ConsolidationGate",
    "RewardTopology",
]
