"""Growing Vault: a calibrated, evolving knowledge store (§4.1).

Knowledge is *not* stored as binary facts. Each entry carries a calibrated
``conviction`` score in [0, 1] that is meant to track empirical accuracy: among
entries with conviction ≈ p, roughly a fraction p should be correct.

Consolidation is *gated* — only inputs whose gate signal opens write to the
vault — and unverified entries decay and are pruned (forgetting).
"""
from __future__ import annotations

from dataclasses import dataclass

import torch

from .config import VaultConfig


@dataclass
class QueryResult:
    value: torch.Tensor          # (dim,) attention-weighted value
    max_similarity: float        # closeness to nearest known key
    gap: bool                    # True ⇒ knowledge gap (trigger the Verifier)
    weights: torch.Tensor        # (n,) attention over current entries
    top_index: int               # index of the nearest entry (-1 if empty)


class GrowingVault:
    def __init__(self, cfg: VaultConfig):
        self.cfg = cfg
        self.keys = torch.zeros(0, cfg.dim)
        self.values = torch.zeros(0, cfg.dim)
        self.conviction = torch.zeros(0)
        self.evidence = torch.zeros(0)

    def __len__(self) -> int:
        return self.keys.shape[0]

    # --- retrieval ---------------------------------------------------------
    def query(self, q: torch.Tensor, top_k: int = 4) -> QueryResult:
        q = q.detach().flatten()
        if len(self) == 0:
            return QueryResult(torch.zeros(self.cfg.dim), 0.0, True,
                               torch.zeros(0), -1)
        sims = self._cosine(q)                                   # (n,)
        k = min(top_k, len(self))
        top_sim, top_idx = torch.topk(sims, k)
        # Conviction-weighted attention over the top-k neighbours.
        logits = top_sim / self.cfg.sim_temperature
        attn = torch.softmax(logits, dim=0) * self.conviction[top_idx]
        attn = attn / (attn.sum() + 1e-8)
        value = (attn.unsqueeze(1) * self.values[top_idx]).sum(0)
        max_sim = float(top_sim[0])
        gap = max_sim < self.cfg.gap_threshold
        return QueryResult(value, max_sim, gap, attn, int(top_idx[0]))

    # --- consolidation (gated write) --------------------------------------
    def consolidate(self, key: torch.Tensor, value: torch.Tensor,
                    gate: float, target: float) -> str:
        """Write to the vault only if the gate is open.

        ``target`` is the calibration target in [0, 1] (e.g. 1.0 if the
        externally verified answer was correct, 0.0 otherwise). Returns the
        action taken: ``"add"`` | ``"strengthen"`` | ``"skipped"``.
        """
        if gate <= 0.0:
            return "skipped"
        key = key.detach().flatten()
        value = value.detach().flatten()
        if len(self) > 0:
            sims = self._cosine(key)
            best = int(torch.argmax(sims))
            if float(sims[best]) >= self.cfg.merge_threshold:
                self._strengthen(best, value, target, gate)
                return "strengthen"
        self._add(key, value, target, gate)
        return "add"

    def _strengthen(self, i: int, value: torch.Tensor, target: float,
                    gate: float) -> None:
        a = self.cfg.calibration_lr * gate
        # Calibrated conviction update toward the empirical target.
        self.conviction[i] = self.conviction[i] + a * (target - self.conviction[i])
        self.conviction[i] = float(torch.clamp(self.conviction[i], 0.0, 1.0))
        # Slow EMA on the stored value.
        self.values[i] = (1 - a) * self.values[i] + a * value
        self.evidence[i] += gate

    def _add(self, key: torch.Tensor, value: torch.Tensor, target: float,
             gate: float) -> None:
        init = self.cfg.init_conviction + (target - 0.5) * 0.2 * gate
        init = float(min(max(init, 0.0), 1.0))
        self.keys = torch.cat([self.keys, key.unsqueeze(0)], 0)
        self.values = torch.cat([self.values, value.unsqueeze(0)], 0)
        self.conviction = torch.cat([self.conviction, torch.tensor([init])])
        self.evidence = torch.cat([self.evidence, torch.tensor([gate])])
        if len(self) > self.cfg.capacity:
            self._evict()

    # --- forgetting --------------------------------------------------------
    def decay(self) -> int:
        """Decay unverified convictions and prune entries below the floor."""
        if len(self) == 0:
            return 0
        self.conviction *= self.cfg.decay
        keep = self.conviction >= self.cfg.prune_floor
        pruned = int((~keep).sum())
        if pruned:
            self.keys = self.keys[keep]
            self.values = self.values[keep]
            self.conviction = self.conviction[keep]
            self.evidence = self.evidence[keep]
        return pruned

    def _evict(self) -> None:
        # Evict the least-supported entry (lowest conviction × evidence).
        score = self.conviction * (1 + self.evidence)
        i = int(torch.argmin(score))
        mask = torch.ones(len(self), dtype=torch.bool)
        mask[i] = False
        self.keys, self.values = self.keys[mask], self.values[mask]
        self.conviction, self.evidence = self.conviction[mask], self.evidence[mask]

    # --- helpers -----------------------------------------------------------
    def _cosine(self, q: torch.Tensor) -> torch.Tensor:
        kn = torch.nn.functional.normalize(self.keys, dim=1)
        qn = torch.nn.functional.normalize(q, dim=0)
        return kn @ qn

    def calibration_error(self, n_bins: int = 10) -> float:
        """Expected Calibration Error of the stored convictions vs evidence.

        Uses evidence-weighted reliability as a proxy for empirical accuracy.
        """
        if len(self) == 0:
            return 0.0
        conv = self.conviction
        # Proxy "accuracy" per entry: convictions that accrued more evidence are
        # treated as better calibrated; we compare conviction to a reliability
        # estimate evidence / (evidence + 1).
        acc = self.evidence / (self.evidence + 1.0)
        ece, n = 0.0, len(self)
        edges = torch.linspace(0, 1, n_bins + 1)
        for b in range(n_bins):
            m = (conv > edges[b]) & (conv <= edges[b + 1])
            if m.any():
                ece += float(m.sum()) / n * abs(float(conv[m].mean() - acc[m].mean()))
        return ece

    def stats(self) -> dict[str, float]:
        if len(self) == 0:
            return {"size": 0, "mean_conviction": 0.0}
        return {
            "size": len(self),
            "mean_conviction": round(float(self.conviction.mean()), 3),
        }
