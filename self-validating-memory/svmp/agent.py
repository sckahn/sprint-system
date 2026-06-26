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

import copy
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

from .budget import BudgetEconomy
from .calibration import ConformalThreshold, ECEMeter, entropy_score, jeopardy_reward
from .config import SVMPConfig
from .learning import RewardTopology, ThreeFactorLearner
from .model import SelfValidatingModel
from .roles import AdversarialLoop, Architect, Collector, Verifier
from .context import RecognizingContextManager
from .label_vault import LabelVault
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
                 reward_mode: str = "independent", learn: bool = True,
                 use_vault: bool = True, force_gate: float | None = None,
                 direct_vote: bool = False, vote_scale: float = 6.0,
                 ctx_dim: int = 0, uncertainty_gate: bool = False,
                 amr: bool = False, drift_realign: bool = False):
        torch.manual_seed(cfg.seed)
        self.cfg = cfg
        self.learn = learn
        # Ablation knobs for the catastrophic-forgetting study:
        #   use_vault=False  → no external memory (decision head only)
        #   force_gate=1.0   → always consolidate (no gated protection)
        #   direct_vote=True → verified facts vote straight into the logits
        #                      (the design-consistent forgetting fix; see label_vault)
        self.use_vault = use_vault
        self.force_gate = force_gate
        self.direct_vote = direct_vote
        self.vote_scale = vote_scale
        # Calibration-gated verification (opt-in; default OFF ⇒ behaviour
        # unchanged). When on, a calibrated uncertainty score is passed into the
        # adversarial loop, and the (conf, correct) stream feeds a split-conformal
        # threshold for risk-coverage / abstention analysis. The actual trigger is
        # governed by cfg.roles.verify_uncertainty_tau (1.0 ⇒ inert by default).
        self.uncertainty_gate = uncertainty_gate
        # Adaptive Memory Realignment (opt-in; default OFF ⇒ never-forget semantics
        # unchanged). When on, the agent watches its own reward stream with a task-
        # free change detector; on a CONFIRMED genuine new regime (the manager
        # finalised onto a fresh slot) it selectively prunes the drifted region of
        # the decay-free label vault so later verified writes repopulate the new
        # mapping. See LabelVault.realign_region (Ashrafee et al. 2025,
        # https://arxiv.org/abs/2507.02310).
        self.amr = amr
        self.amr_manager = (RecognizingContextManager(auto_detect=True)
                            if amr else None)
        # Learnable Drift Compensation (opt-in; default OFF ⇒ unchanged). When on,
        # the agent periodically fits a small linear projector mapping the FROZEN
        # snapshot encoder's features to the CURRENT encoder's features and re-
        # projects the decay-free label-vault keys through it, so the stored keys
        # track the drifting representation rather than mis-targeting the moving
        # space. See LabelVault.realign (Gomez-Villa et al. 2024,
        # https://arxiv.org/abs/2407.08536). Built lazily below once the model
        # exists; default flag False ⇒ none of this is created or run.
        self.drift_realign = drift_realign
        self._enc_snapshot = None
        # Region-covering anchor cache for Semantic Drift Compensation: a small set
        # of raw inputs spanning the distinct input regions seen so far (added by an
        # input-space novelty gate), replayed through old/new encoders to estimate
        # the LOCAL drift field. Covers old-task regions too, unlike a recent-input
        # ring — which is why the global-linear projector regressed.
        self._anchors: list[torch.Tensor] = []
        self._anchor_cov = 0.8
        self._anchor_cap = 96
        self._step_count = 0
        self.conformal = ConformalThreshold(alpha=0.1, window=500)
        self.model = SelfValidatingModel(cfg, input_dim)
        self.vault = GrowingVault(cfg.vault)
        self.label_vault = (LabelVault(cfg.dim, cfg.n_classes, ctx_dim=ctx_dim)
                            if direct_vote else None)
        self.budget = BudgetEconomy(cfg.budget)
        self.reward_topology = RewardTopology(reward_mode)
        self.ece = ECEMeter()
        self.gen = torch.Generator().manual_seed(cfg.seed)

        # Roles + adversarial loop.
        self.architect = Architect(cfg.roles)
        self.collector = Collector(cfg.roles)
        self.verifier = Verifier(cfg.roles, generator=self.gen,
                                 aggregation="robust")
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

        # Semantic Drift Compensation is parameter-free (a local, similarity-weighted
        # drift average over replayed anchors), so no projector/optimizer is needed.

    # ---------------------------------------------------------------------
    def step(self, x: torch.Tensor, target: int,
             order_target: list[int] | None = None,
             context: torch.Tensor | None = None) -> StepLog:
        cfg = self.cfg
        self.budget.tick()
        self.budget.spend("inference")

        # 1) Encode + read the vault (skipped when the vault is ablated).
        with torch.no_grad():
            enc = self.model.encoder(x.flatten())
        if self.use_vault:
            qr = self.vault.query(enc, top_k=4)
            retrieved, gap, gap_signal = qr.value, qr.gap, (1.0 if qr.gap else 0.0)
        else:
            retrieved, gap, gap_signal = torch.zeros(cfg.dim), False, 0.0

        # 2) Adversarial verification loop (charges search budget if used).
        #    When the uncertainty gate is on, score the model's current predictive
        #    entropy (a calibrated selective score) and let it co-trigger the
        #    Verifier search alongside the binary gap signal. Default OFF ⇒ the
        #    uncertainty stays None and the trigger is exactly the original one.
        unc: float | None = None
        if self.uncertainty_gate:
            with torch.no_grad():
                unc = entropy_score(self.model(x, retrieved).logits)
        loop_res = self.loop.run(enc, retrieved, gap,
                                 on_search=lambda: self.budget.spend("search"),
                                 uncertainty=unc)

        # 3) Decision through the model. Budget pressure shrinks top-k (Phase 2).
        frac = self.budget.balance / cfg.budget.total
        top_k = cfg.moe.top_k if frac > 0.3 else 1
        out = self.model(x, retrieved, top_k=top_k)
        self.budget.spend_experts(out.moe.experts_used)
        # Auxiliary-loss-free balancing: nudge the gradient-free routing bias toward
        # an even load (opt-in; default OFF ⇒ this is skipped, behaviour unchanged).
        if cfg.moe.loss_free_balance:
            self.model.moe.update_bias(out.moe.last_top_idx)

        # 4) Sample an action from the policy (REINFORCE-as-three-factor).
        #    Verified facts vote directly onto the logits (forgetting fix).
        logits = out.logits.detach()
        if self.direct_vote:
            logits = logits + self.vote_scale * self.label_vault.vote(enc, context)
        pi = torch.softmax(logits, dim=0)
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
        if self.learn:
            factors = self.learner.update(reward, surprise, gap_signal,
                                          loop_res.source_quality,
                                          gate_override=self.force_gate)
        else:
            # No plasticity: still compute the gate (for the vault) but don't
            # write the decision head. This is the "passive" control.
            factors = {"gate": self.learner.gate(surprise, gap_signal,
                                                 loop_res.source_quality),
                       "neuromod": 0.0}

        # 6b) Gated consolidation into the vault (verified knowledge only).
        #     Verified-correct facts also enter the decay-free label vault.
        # Adaptive Memory Realignment (opt-in): feed the outcome to the task-free
        # detector; only on a CONFIRMED true drift (it finalised onto a fresh slot)
        # do we realign — selectively prune this region's stale entries BEFORE the
        # write so later verified-correct facts repopulate the new mapping. Default
        # off ⇒ this whole block is skipped and never-forget semantics hold.
        if self.amr and self.direct_vote:
            self.amr_manager.observe(1.0 if correct else 0.0)
            if self.amr_manager.new_regime:
                self.label_vault.realign_region(enc)
        if self.direct_vote and correct:
            self.label_vault.write(enc, action, gate=self.learner.gate.last,
                                   context=context)
        if self.use_vault:
            vault_action = self.vault.consolidate(
                enc, enc, gate=self.learner.gate.last,
                target=1.0 if correct else 0.0)
            self.vault.decay()
        else:
            vault_action = "skipped"

        # 7) Backprop pathway: representation + auxiliary heads.
        if self.learn:
            self._backprop_step(x, retrieved, target, correct, loop_res)

        # 7b) Drift compensation (opt-in): maintain a region-covering anchor cache
        #     (input-space novelty gate) and, every cfg.learning.realign_every steps,
        #     realign the label-vault keys by the locally-estimated encoder drift.
        #     Default off ⇒ skipped.
        if self.drift_realign and self.direct_vote:
            xf = x.detach().flatten()
            if not self._anchors:
                self._anchors.append(xf)
            elif len(self._anchors) < self._anchor_cap:
                a = torch.stack(self._anchors)
                novel = float(F.cosine_similarity(a, xf.unsqueeze(0), dim=1).max())
                if novel < self._anchor_cov:        # a region not yet covered
                    self._anchors.append(xf)
            self._step_count += 1
            if self._step_count % cfg.learning.realign_every == 0:
                self._maybe_realign()

        self.ece.update(conf_val, correct)
        # Feed the calibrated (confidence, correctness) stream into the conformal
        # threshold so its empirical quantile / coverage can be inspected. Pure
        # bookkeeping — it does not alter the step's behaviour.
        if self.uncertainty_gate:
            self.conformal.update(conf_val, correct)
        return StepLog(
            action=action, correct=correct, confidence=conf_val,
            reward=reward, gap=gap, verified=loop_res.verified,
            source_quality=loop_res.source_quality, gate=factors["gate"],
            neuromod=factors["neuromod"], experts_used=out.moe.experts_used,
            vault_size=len(self.vault), budget=round(self.budget.balance, 2),
            alive=self.budget.alive, vault_action=vault_action,
        )

    # ---------------------------------------------------------------------
    @torch.no_grad()
    def predict(self, x: torch.Tensor, context: torch.Tensor | None = None) -> int:
        """Greedy inference along the same path as :meth:`step` (vault + vote)."""
        enc = self.model.encoder(x.flatten())
        retrieved = (self.vault.query(enc).value if self.use_vault
                     else torch.zeros(self.cfg.dim))
        logits = self.model(x, retrieved).logits
        if self.direct_vote:
            logits = logits + self.vote_scale * self.label_vault.vote(enc, context)
        return int(logits.argmax())

    # ---------------------------------------------------------------------
    def _maybe_realign(self) -> None:
        """Realign the decay-free vault keys to the drifting encoder (opt-in, SDC).

        Semantic Drift Compensation (Yu et al. 2020, https://arxiv.org/abs/2004.00440)
        — the robust replacement for the global-linear projector, which regressed
        because it was fit on current-task inputs yet applied to old-task keys. On
        the FIRST trigger there is no old encoder, so we only cache a frozen
        snapshot. On every later trigger we encode the region-covering anchor cache
        through both the frozen snapshot (old features) and the live encoder (new
        features) and pass the pair to :meth:`LabelVault.realign_sdc`, which moves
        each key by the similarity-weighted *local* drift of nearby anchors. Then we
        refresh the snapshot. Default off ⇒ never reached.
        """
        if self._enc_snapshot is None:
            self._snapshot_encoder()
            return
        if not self._anchors:
            return
        batch = torch.stack(self._anchors)
        with torch.no_grad():
            old_enc = self._enc_snapshot(batch)
            new_enc = self.model.encoder(batch)
        self.label_vault.realign_sdc(old_enc, new_enc)
        self._snapshot_encoder()

    def _snapshot_encoder(self) -> None:
        self._enc_snapshot = copy.deepcopy(self.model.encoder)
        for p in self._enc_snapshot.parameters():
            p.requires_grad_(False)
        self._enc_snapshot.eval()

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
