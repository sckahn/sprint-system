"""Auxiliary-loss-free MoE load balancing — does a gradient-free routing bias
even out expert usage without hurting accuracy or calibration?

The MoE layer's anti-collapse pressure is normally an auxiliary load-balance loss
mixed into the backprop objective. DeepSeek's "Auxiliary-Loss-Free Load Balancing
Strategy for Mixture-of-Experts" (https://arxiv.org/html/2408.15664v1) proposes a
gradient-free alternative: a per-expert bias added to the top-k SELECTION scores
only (never to the output gate weights), nudged after every routing decision by

    b_i += u · sign(mean_load − load_i),

so overloaded experts are de-prioritised and starved ones promoted, with no extra
gradient term and no change to output magnitude (the gate weights stay unbiased).

이 실험은 ``loss_free_balance`` 를 False vs True 로 두고, expert 사용량이 얼마나
고르게 분포하는지(MaxVio, selection-entropy)와 정확도/ECE 가 유지되는지를
CalibrationBanditTask 와 SplitContinualTask 에서 비교한다.

Metrics (per condition, averaged over seeds):
  MaxVio    = max_e |load_e − mean_load|   (lower = better balanced; 0 = perfect)
  sel-entropy = −Σ p_e log p_e / log E      (1.0 = uniform usage; lower = collapsed)
  accuracy  = online correct-rate on the stream
  ECE       = expected calibration error    (lower = better calibrated)

    cd self-validating-memory
    OMP_NUM_THREADS=2 PYTHONPATH=. python examples/experiment_moe_balance.py
"""
from __future__ import annotations

import math
import statistics as st

import torch

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.tasks import CalibrationBanditTask, SplitContinualTask

SEEDS = [0, 1, 2, 3]
STEPS = 2500


def _selection_counts(agent: SelfValidatingAgent) -> torch.Tensor:
    """Per-expert selection counts accumulated over the whole run (via hook)."""
    return agent._sel_counts


def _instrument(agent: SelfValidatingAgent) -> None:
    """Attach a forward hook that tallies which experts get selected."""
    n = agent.cfg.moe.n_experts
    agent._sel_counts = torch.zeros(n)

    def hook(_module, _inp, out):
        idx = out.last_top_idx.reshape(-1)
        for e in range(n):
            agent._sel_counts[e] += float((idx == e).sum())

    agent.model.moe.register_forward_hook(hook)


def _balance_metrics(counts: torch.Tensor) -> tuple[float, float]:
    """MaxVio and normalised selection-entropy from raw selection counts."""
    total = float(counts.sum())
    load = counts / total                      # fraction of slots per expert
    mean = float(load.mean())
    maxvio = float((load - mean).abs().max())
    p = load.clamp_min(1e-12)
    entropy = float(-(p * p.log()).sum() / math.log(len(load)))
    return maxvio, entropy


def run_bandit(loss_free: bool, seed: int) -> dict:
    cfg = SVMPConfig(seed=seed, n_classes=4)
    cfg.moe.loss_free_balance = loss_free
    agent = SelfValidatingAgent(cfg, 16)
    _instrument(agent)
    task = CalibrationBanditTask(n_classes=4, feature_dim=16, seed=seed)
    correct = 0
    for _ in range(STEPS):
        x, y = task.sample()
        log = agent.step(x, y)
        correct += int(log.correct)
    maxvio, entropy = _balance_metrics(_selection_counts(agent))
    return {"acc": correct / STEPS, "ece": agent.ece.compute(),
            "maxvio": maxvio, "entropy": entropy}


def run_continual(loss_free: bool, seed: int) -> dict:
    cfg = SVMPConfig(seed=seed, n_classes=8)
    cfg.moe.loss_free_balance = loss_free
    agent = SelfValidatingAgent(cfg, 16)
    _instrument(agent)
    task = SplitContinualTask(n_classes=8, n_tasks=2, feature_dim=16, seed=seed)
    correct = 0
    steps = 0
    for t in range(task.n_tasks):
        for _ in range(STEPS):
            x, y = task.sample(t)
            log = agent.step(x, y)
            correct += int(log.correct)
            steps += 1
    maxvio, entropy = _balance_metrics(_selection_counts(agent))
    return {"acc": correct / steps, "ece": agent.ece.compute(),
            "maxvio": maxvio, "entropy": entropy}


def summarize(runner, loss_free: bool) -> dict:
    rs = [runner(loss_free, s) for s in SEEDS]
    return {k: st.mean(r[k] for r in rs) for k in ("acc", "ece", "maxvio", "entropy")}


def report(name: str, runner) -> None:
    off = summarize(runner, False)
    on = summarize(runner, True)
    print(f"\n[{name}]  (n={len(SEEDS)} seeds, {STEPS} steps/task)")
    print(f"  {'condition':18s} | MaxVio | sel-entropy | accuracy | ECE")
    print(f"  {'-'*18} | {'-'*6} | {'-'*11} | {'-'*8} | {'-'*5}")
    for label, r in (("loss_free_balance OFF", off), ("loss_free_balance ON", on)):
        print(f"  {label:18s} | {r['maxvio']:.4f} | {r['entropy']:.4f}      "
              f"| {r['acc']:.3f}    | {r['ece']:.3f}")
    print(f"  → MaxVio reduction (OFF − ON):  {off['maxvio'] - on['maxvio']:+.4f}")
    print(f"  → entropy gain   (ON − OFF):    {on['entropy'] - off['entropy']:+.4f}")
    print(f"  → accuracy change (ON − OFF):   {on['acc'] - off['acc']:+.4f}")
    print(f"  → ECE change      (ON − OFF):   {on['ece'] - off['ece']:+.4f}")


def main() -> None:
    print("=" * 64)
    print("Auxiliary-loss-free MoE load balancing — gradient-free routing bias")
    print("=" * 64)
    report("CalibrationBanditTask", run_bandit)
    report("SplitContinualTask", run_continual)


if __name__ == "__main__":
    main()
