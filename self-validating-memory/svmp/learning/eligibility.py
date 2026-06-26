"""Eligibility traces: the *first* factor of the three-factor rule (§4.4).

An eligibility trace is a decaying memory of recent pre×post coincidence on each
synapse. It marks *which* connections are eligible for change; the global
neuromodulator and the gate then decide *whether* and *how much* they change.

    e_ij(t) = λ · e_ij(t-1) + pre_i · post_j
"""
from __future__ import annotations

import torch


class EligibilityTrace:
    """Per-parameter eligibility trace for a single weight matrix W: (out, in)."""

    def __init__(self, out_dim: int, in_dim: int, decay: float):
        self.decay = decay
        self.trace = torch.zeros(out_dim, in_dim)

    def accumulate(self, pre: torch.Tensor, post: torch.Tensor) -> torch.Tensor:
        """Add the outer product of post (out) and pre (in) to the trace.

        ``pre`` is the layer input (in_dim,), ``post`` the layer output or an
        output-side learning signal (out_dim,).
        """
        pre = pre.detach().flatten()
        post = post.detach().flatten()
        coincidence = torch.outer(post, pre)                    # (out, in)
        self.trace = self.decay * self.trace + coincidence
        return self.trace

    def reset(self) -> None:
        self.trace.zero_()
