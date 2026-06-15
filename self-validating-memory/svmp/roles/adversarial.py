"""Adversarial loop tying Architect, Collector, Verifier together (§3, Phase 3/5).

The three roles form a GAN-like, self-supervised verification loop that needs *no
external judge* for its internal consistency signal:

- The **Architect** proposes a hypothesis (generator).
- The **Collector** scores its support from known knowledge (discriminator).
- When support is low (or the vault reports a gap), the **Verifier** searches
  externally and the Collector is re-scored against the gathered evidence.

The loop returns everything the learning step needs: the hypothesis, the
collector's support, whether external verification happened, and the source
quality (which feeds the consolidation gate).
"""
from __future__ import annotations

from dataclasses import dataclass

import torch

from ..config import RoleConfig
from .architect import Architect
from .collector import Collector
from .verifier import Evidence, Verifier


@dataclass
class LoopResult:
    hypothesis: torch.Tensor
    support: float               # collector support after the loop
    verified: bool               # did we call the Verifier?
    source_quality: float        # 0.0 if no external search
    evidence: Evidence | None


class AdversarialLoop:
    def __init__(self, cfg: RoleConfig, architect: Architect, collector: Collector,
                 verifier: Verifier):
        self.cfg = cfg
        self.architect = architect
        self.collector = collector
        self.verifier = verifier

    def run(self, x: torch.Tensor, retrieved: torch.Tensor, gap: bool,
            on_search=None) -> LoopResult:
        """Run one architect→collector(→verifier) cycle.

        ``on_search`` is an optional callback (e.g. to charge the budget) invoked
        only when the Verifier is actually used.
        """
        hypo = self.architect(x, retrieved)
        with torch.no_grad():
            support = float(self.collector(hypo, retrieved))

        verified, src_q, evidence = False, 0.0, None
        if gap or support < self.cfg.collector_agree_threshold:
            if on_search is not None:
                on_search()
            evidence = self.verifier.verify(x)
            verified, src_q = True, evidence.source_quality
            # Re-score the hypothesis against external evidence.
            with torch.no_grad():
                support = float(self.collector(hypo, evidence.embedding))

        return LoopResult(hypo, support, verified, src_q, evidence)


# Phase 5 self-play (answer-key-free domains judged by a frozen Phase-1 net) is
# now a full implementation in svmp/selfplay.py — SelfPlayJudge / train_judge /
# self_play. It is re-exported here for backward compatibility.
from ..selfplay import SelfPlayJudge, reset_decision_head, self_play, train_judge  # noqa: E402,F401
