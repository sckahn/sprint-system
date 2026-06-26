"""Learning subsystem: three-factor plasticity and reward topology."""
from .eligibility import EligibilityTrace
from .gating import ConsolidationGate
from .neuromod import Neuromodulator
from .rewards import RewardTopology
from .three_factor import ThreeFactorLearner

__all__ = [
    "EligibilityTrace",
    "Neuromodulator",
    "ConsolidationGate",
    "ThreeFactorLearner",
    "RewardTopology",
]
