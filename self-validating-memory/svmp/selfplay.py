"""Phase 5 — self-play in answer-key-free domains (artifact §5).

The system's first principle is that valence must come from *external*
verification — it cannot define its own reward. In keyless domains there is no
oracle, so the design resolves this with a **frozen judge grounded in Phase 1**:
a reward model trained on keyed data (where external verification was available),
then frozen and used to score actions during keyless self-play. Because the judge
is frozen and externally grounded, self-play is anchored to previously-verified
competence rather than free-floating self-reward (which would collapse).

Concretely:
  1. ``SelfPlayJudge`` is a reward model P(correct | context, action), trained on
     Phase-1 (context, action, correct) tuples by ``train_judge``.
  2. ``self_play`` runs keyless episodes: the agent acts, the *frozen* judge gives
     a pseudo-reward 2·P(correct)−1, and the decision head is updated by the
     three-factor rule. The representation is held fixed so the judge's input
     distribution stays the one it was grounded on.

Honest caveat: this is distillation from a grounded reward model — self-play
cannot exceed the judge's competence. That is the point: you cannot bootstrap
past your external grounding.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from .config import SVMPConfig
from .learning import ThreeFactorLearner
from .model import SelfValidatingModel


class SelfPlayJudge(nn.Module):
    """Reward model: P(correct | raw context, action one-hot)."""

    def __init__(self, input_dim: int, n_classes: int, hidden: int = 32):
        super().__init__()
        self.n_classes = n_classes
        self.net = nn.Sequential(
            nn.Linear(input_dim + n_classes, hidden), nn.GELU(),
            nn.Linear(hidden, 1),
        )

    def forward(self, x: torch.Tensor, action_onehot: torch.Tensor) -> torch.Tensor:
        h = torch.cat([x.flatten(), action_onehot.flatten()])
        return torch.sigmoid(self.net(h)).squeeze(-1)


def train_judge(judge: SelfPlayJudge, episodes, epochs: int = 5,
                lr: float = 1e-2) -> SelfPlayJudge:
    """Train the judge on Phase-1 (context, action, correct) tuples (BCE)."""
    opt = torch.optim.Adam(judge.parameters(), lr=lr)
    for _ in range(epochs):
        for x, action, correct in episodes:
            onehot = F.one_hot(torch.tensor(int(action)), judge.n_classes).float()
            p = judge(x, onehot)
            loss = F.binary_cross_entropy(p, torch.tensor(1.0 if correct else 0.0))
            opt.zero_grad()
            loss.backward()
            opt.step()
    return judge


def reset_decision_head(model: SelfValidatingModel) -> None:
    """Re-randomise the decision head (and keep it frozen from autograd)."""
    model.decision.reset_parameters()
    model.decision.weight.requires_grad_(False)
    model.decision.bias.requires_grad_(False)


def self_play(model: SelfValidatingModel, judge: SelfPlayJudge, contexts,
              cfg: SVMPConfig, seed: int = 0) -> ThreeFactorLearner:
    """Keyless self-play: learn the decision head from the frozen judge's reward.

    The representation (encoder/MoE/fuse) is *not* updated — only the decision
    head, by the three-factor rule, so the judge always sees the input space it
    was grounded on. Returns the learner (for inspection).
    """
    learner = ThreeFactorLearner(model.decision, cfg.learning)
    gen = torch.Generator().manual_seed(seed)
    retrieved = torch.zeros(cfg.dim)
    judge.eval()
    for x in contexts:
        out = model(x, retrieved)
        pi = torch.softmax(out.logits.detach(), dim=0)
        action = int(torch.multinomial(pi, 1, generator=gen))
        onehot = F.one_hot(torch.tensor(action), cfg.n_classes).float()
        with torch.no_grad():
            p = float(judge(x, onehot))
        pseudo_reward = 2.0 * p - 1.0                      # P(correct) → [-1, 1]

        post_signal = onehot - pi                          # ∇ log π(action)
        learner.observe(out.feature.detach(), post_signal)
        surprise = 1.0 - float(pi[action])
        # No vault gap in self-play; the judge is the (only) evidence source, so
        # its confidence stands in for source quality.
        learner.update(pseudo_reward, surprise, gap=0.0, source_quality=abs(2 * p - 1))
    return learner
