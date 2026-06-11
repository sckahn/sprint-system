"""Adversarial roles: Architect, Collector, Verifier and their loop."""
from .adversarial import AdversarialLoop, LoopResult, SelfPlay
from .architect import Architect
from .collector import Collector
from .trust_estimator import SourceTrustEstimator, train_trust_estimator
from .verifier import Evidence, Verifier

__all__ = [
    "Architect",
    "Collector",
    "Verifier",
    "Evidence",
    "AdversarialLoop",
    "LoopResult",
    "SelfPlay",
    "SourceTrustEstimator",
    "train_trust_estimator",
]
