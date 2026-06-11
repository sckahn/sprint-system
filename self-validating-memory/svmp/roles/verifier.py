"""Verifier: external search + source-quality assessment (§3, §4).

When the Collector cannot support a hypothesis from existing knowledge (a gap),
the Verifier reaches *outside* the system to gather evidence. The design document
flags this as the single weakest real component:

    "가장 약한 실제 부품은 화려한 GAN 구조가 아니라
     '검색 결과의 출처 품질을 평가하는 능력'이다."

So the Verifier does two things, and the *second* is the hard one:

1. ``search`` — retrieve candidate evidence (here: a pluggable callback; the
   default is a simulator so the system is runnable end-to-end).
2. ``assess_source`` — estimate how trustworthy that evidence is, using
   **triangulation**: agreement across multiple independent sources raises trust,
   disagreement lowers it. This is deliberately conservative.

Plug a real retriever by passing ``search_fn`` to the constructor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import torch

from ..config import RoleConfig


@dataclass
class Evidence:
    embedding: torch.Tensor      # (dim,) aggregated evidence
    source_quality: float        # [0, 1] triangulated trust
    n_sources: int
    agreement: float             # [0, 1] cross-source agreement


# A search function maps a query embedding to a list of (evidence, raw_trust).
SearchFn = Callable[[torch.Tensor, int], Sequence[tuple[torch.Tensor, float]]]


class Verifier:
    def __init__(self, cfg: RoleConfig, search_fn: SearchFn | None = None,
                 generator: torch.Generator | None = None):
        self.cfg = cfg
        self.search_fn = search_fn or self._simulated_search
        self.gen = generator or torch.Generator().manual_seed(0)

    def verify(self, query: torch.Tensor) -> Evidence:
        results = self.search_fn(query, self.cfg.triangulation_k)
        if not results:
            return Evidence(torch.zeros(self.cfg.dim), 0.0, 0, 0.0)
        embs = torch.stack([e.flatten() for e, _ in results])
        raw_trust = torch.tensor([t for _, t in results])
        agreement = self._agreement(embs)
        quality = self.assess_source(raw_trust, agreement)
        # Trust-weighted evidence aggregate.
        w = torch.softmax(raw_trust, dim=0).unsqueeze(1)
        agg = (w * embs).sum(0)
        return Evidence(agg, quality, len(results), agreement)

    # --- the hard part -----------------------------------------------------
    def assess_source(self, raw_trust: torch.Tensor, agreement: float) -> float:
        """Triangulated source-quality estimate in [0, 1].

        Conservative by design: a single high-trust source is discounted, while
        independent corroboration is rewarded. We never return full confidence
        from one source.
        """
        mean_trust = float(raw_trust.mean())
        n = len(raw_trust)
        # Corroboration factor: 1 source ⇒ 0.5, saturating toward 1 with more.
        corroboration = 1.0 - 0.5 ** n
        quality = mean_trust * (0.5 + 0.5 * agreement) * corroboration
        return float(min(max(quality, 0.0), 1.0))

    @staticmethod
    def _agreement(embs: torch.Tensor) -> float:
        if embs.shape[0] < 2:
            return 0.0
        n = torch.nn.functional.normalize(embs, dim=1)
        sims = n @ n.t()
        off = sims[~torch.eye(len(embs), dtype=torch.bool)]
        return float((off.mean() + 1) / 2)  # map cosine [-1,1] → [0,1]

    # --- default simulator (replace with a real retriever) -----------------
    def _simulated_search(self, query: torch.Tensor,
                          k: int) -> list[tuple[torch.Tensor, float]]:
        q = query.flatten()
        out = []
        for _ in range(k):
            noise = torch.randn(self.cfg.dim, generator=self.gen) * self.cfg.source_quality_std
            emb = q + noise
            trust = float(torch.clamp(
                torch.randn(1, generator=self.gen) * self.cfg.source_quality_std
                + self.cfg.source_quality_mean, 0.0, 1.0))
            out.append((emb, trust))
        return out
