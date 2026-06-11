"""SelfValidatingAgent: orchestrates one full self-validation step (§6).

This is where every subsystem meets. Per round the agent:

1. charges maintenance + inference against the **budget**,
2. **queries the vault** and detects knowledge gaps,
3. runs the **architect → collector (→ verifier)** adversarial loop,
4. produces a decision + confidence through the **model / MoE**,
5. gets an **external reward** (the only legitimate source of valence),
6. updates the decision head by the **three-factor rule** and consolidates
   verified knowledge into the **vault** through the gate.

Two learning pathways run side by side, by design:

- **Three-factor plasticity** writes the *decision head* from reward × eligibility
  × gate (no autograd) — the headline mechanism.
- **Backprop** shapes representations and the auxiliary heads (encoder, MoE, fuse,
  calibration, and the adversarial roles) from the externally revealed label.
"""
from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

from .budget import BudgetEconomy
from .calibration import ECEMeter, jeopardy_reward
from .config import SVMPConfig
from .learning import RewardTopology, ThreeFactorLearner
from .model import SelfValidatingModel
from .roles import AdversarialLoop, Architect, Collector, Verifier
from .vault import GrowingVault


@dataclass
class StepLog:
    action: int
    correct: bool
    confidence: float
    reward: float
    gap: bool
    verified: bool
    source_quality: float
    gate: float
    neuromod: float
    experts_used: int
    vault_size: int
    budget: float
    alive: bool
    vault_action: str


class SelfValidatingAgent:
    def __init__(self, cfg: SVMPConfig, input_dim: int,
                 reward_mode: str = "independent"):
        torch.manual_seed(cfg.seed)
        self.cfg = cfg
        self.model = SelfValidatingModel(cfg, input_dim)
        self.vault = GrowingVault(cfg.vault)
        self.budget = BudgetEconomy(cfg.budget)
        self.reward_topology = RewardTopology(reward_mode)
        self.ece = ECEMeter()
        self.gen = torch.Generator().manual_seed(cfg.seed)

        # Roles + adversarial loop.
        self.architect = Architect(cfg.roles)
        self.collector = Collector(cfg.roles)
        self.verifier = Verifier(cfg.roles, generator=self.gen)
        self.loop = AdversarialLoop(cfg.roles, self.architect, self.collector,
                                    self.verifier)

        # Three-factor learner writes only the decision head; freeze it from
        # autograd so backprop never fights the local rule.
        self.model.decision.weight.requires_grad_(False)
        self.model.decision.bias.requires_grad_(False)
        self.learner = ThreeFactorLearner(self.model.decision, cfg.learning)

        # Backprop optimizer for representation + auxiliary heads only.
        backprop_params = (
            list(self.model.encoder.parameters())
            + list(self.model.fuse.parameters())
            + list(self.model.moe.parameters())
            + list(self.model.calib.parameters())
            + list(self.architect.parameters())
            + list(self.collector.parameters())
        )
        self.opt = torch.optim.Adam(backprop_params, lr=1e-3)
        self._history: list[int] = []

    # ---------------------------------------------------------------------
    def step(self, x: torch.Tensor, target: int,
             order_target: list[int] | None = None) -> StepLog:
        cfg = self.cfg
        self.budget.tick()
        self.budget.spend("inference")

        # 1) Encode + read the vault.
        with torch.no_grad():
            enc = self.model.encoder(x.flatten())
        qr = self.vault.query(enc, top_k=4)
        gap_signal = 1.0 if qr.gap else 0.0

        # 2) Adversarial verification loop (charges search budget if used).
        loop_res = self.loop.run(enc, qr.value, qr.gap,
                                 on_search=lambda: self.budget.spend("search"))

        # 3) Decision through the model. Budget pressure shrinks top-k (Phase 2).
        frac = self.budget.balance / cfg.budget.total
        top_k = cfg.moe.top_k if frac > 0.3 else 1
        out = self.model(x, qr.value, top_k=top_k)
        self.budget.spend_experts(out.moe.experts_used)

        # 4) Sample an action from the policy (REINFORCE-as-three-factor).
        pi = torch.softmax(out.logits.detach(), dim=0)
        action = int(torch.multinomial(pi, 1, generator=self.gen))
        correct = action == target
        conf_val = float(out.confidence.detach())

        # 5) External reward — the only legitimate valence source.
        task_reward = self.reward_topology(action, target,
                                           order_target=order_target,
                                           history=self._history)
        bet_reward = jeopardy_reward(correct, conf_val)
        reward = 0.5 * task_reward + 0.5 * bet_reward
        self.budget.earn(reward)
        self._history.append(action)

        # 6a) Three-factor update of the decision head.
        onehot = F.one_hot(torch.tensor(action), cfg.n_classes).float()
        post_signal = onehot - pi                      # ∇ log π(action)
        self.learner.observe(out.feature.detach(), post_signal)
        surprise = 1.0 - float(pi[action])
        factors = self.learner.update(reward, surprise, gap_signal,
                                      loop_res.source_quality)

        # 6b) Gated consolidation into the vault (verified knowledge only).
        vault_action = self.vault.consolidate(
            enc, enc, gate=self.learner.gate.last,
            target=1.0 if correct else 0.0)
        self.vault.decay()

        # 7) Backprop pathway: representation + auxiliary heads.
        self._backprop_step(x, qr.value, target, correct, loop_res)

        self.ece.update(conf_val, correct)
        return StepLog(
            action=action, correct=correct, confidence=conf_val,
            reward=reward, gap=qr.gap, verified=loop_res.verified,
            source_quality=loop_res.source_quality, gate=factors["gate"],
            neuromod=factors["neuromod"], experts_used=out.moe.experts_used,
            vault_size=len(self.vault), budget=round(self.budget.balance, 2),
            alive=self.budget.alive, vault_action=vault_action,
        )

    # ---------------------------------------------------------------------
    def _backprop_step(self, x: torch.Tensor, retrieved: torch.Tensor,
                       target: int, correct: bool, loop_res) -> None:
        self.opt.zero_grad()
        out = self.model(x, retrieved)
        tgt = torch.tensor(target)

        # Representation: shape features so the (frozen) readout separates classes.
        rep_loss = F.cross_entropy(out.logits.unsqueeze(0), tgt.unsqueeze(0))
        # Anti-collapse for the experts (Phase 2).
        lb_loss = out.moe.load_balance_loss
        # Calibration head learns correctness from confidence (detached logits).
        conf = self.model.calib(out.logits.detach())
        calib_loss = F.binary_cross_entropy(conf, torch.tensor(1.0 if correct else 0.0))

        # Adversarial roles (simultaneous-gradient GAN approximation).
        evidence = loop_res.evidence.embedding if loop_res.evidence is not None else retrieved
        hypo = self.architect(self.model.encoder(x.flatten()).detach(), retrieved)
        support = self.collector(hypo, evidence)
        collector_loss = F.binary_cross_entropy(
            self.collector(hypo.detach(), evidence),
            torch.tensor(1.0 if correct else 0.0))
        architect_loss = 0.5 * F.binary_cross_entropy(support, torch.tensor(1.0))

        loss = rep_loss + lb_loss + calib_loss + collector_loss + architect_loss
        loss.backward()
        self.opt.step()

    # ---------------------------------------------------------------------
    def metrics(self) -> dict[str, float]:
        return {
            "ece": round(self.ece.compute(), 4),
            "vault": self.vault.stats(),
            "budget": self.budget.snapshot(),
        }
