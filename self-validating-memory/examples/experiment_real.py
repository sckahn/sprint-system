"""Real-data experiments for the SVMP architecture.

    PYTHONPATH=. python examples/experiment_real.py

Experiment A — REAL DATA LEARNING (sklearn digits, 1797 images, 10 classes)
    Online training on real handwritten digits, then frozen evaluation on a
    held-out test split. Full agent vs passive control.

Experiment B — SOURCE-QUALITY ASSESSMENT (Phase 4, the design's weakest part)
    The Verifier searches a *real retrieval corpus* built over digit-class
    prototypes where 40% of documents are misleading (evidence pulled toward a
    wrong class) and trust priors overlap. We compare:
      • triangulated  — k=3 sources, agreement + corroboration discounting
      • naive         — k=1 source, trusts the prior at face value
    and measure whether the assessor's quality score actually discriminates
    reliable from unreliable retrievals, plus the end-to-end effect.
"""
from __future__ import annotations

import statistics as st

import torch

from svmp.agent import SelfValidatingAgent
from svmp.config import SVMPConfig
from svmp.retrieval import CorpusRetriever, DocumentCorpus
from svmp.roles import Verifier
from svmp.tasks import RealDigitsTask

SEEDS = [0, 1, 2]
STEPS = 3000
CHANCE = 0.10  # 10 classes


class NaiveVerifier(Verifier):
    """Trusts the source prior at face value — no triangulation."""

    def assess_source(self, raw_trust, agreement):
        return float(raw_trust.mean())


def make_config(seed: int) -> SVMPConfig:
    cfg = SVMPConfig(seed=seed, n_classes=10)
    # 10-way chance is 0.1, so early rewards are deeply negative and the agent
    # burns ~10 budget/round while exploring. Size the runway so death still
    # means "failed to learn in time" rather than "never had a chance": with
    # total=8000 the full agent died at ~870 steps with test-acc 0.41 — i.e.
    # mid-learning. 24000 gives ~2.5k rounds of pure exploration.
    cfg.budget.total = 24000.0
    cfg.budget.maintenance_growth = 0.0005
    cfg.budget.reward_to_budget = 8.0
    return cfg


def frozen_eval(agent: SelfValidatingAgent, X, y) -> float:
    correct = 0
    with torch.no_grad():
        for x, t in zip(X, y):
            enc = agent.model.encoder(x)
            qr = agent.vault.query(enc)
            out = agent.model(x, qr.value)
            correct += int(int(out.logits.argmax()) == int(t))
    return correct / len(y)


def run_digits(seed: int, learn: bool, verifier: str = "simulated") -> dict:
    task = RealDigitsTask(seed=seed)
    cfg = make_config(seed)
    agent = SelfValidatingAgent(cfg, task.feature_dim, learn=learn)

    quality_when_reliable: list[float] = []
    quality_when_unreliable: list[float] = []
    retriever = None
    if verifier != "simulated":
        corpus = DocumentCorpus(task.class_prototypes(), docs_per_class=20,
                                unreliable_frac=0.4, seed=seed)
        retriever = CorpusRetriever(
            corpus, encode_fn=lambda e: agent.model.encoder(e))
        # Pin aggregation="mean" so this experiment's reported numbers stay a
        # like-for-like baseline (the package default is now "robust").
        if verifier == "naive":
            cfg.roles.triangulation_k = 1
            v = NaiveVerifier(cfg.roles, search_fn=retriever, aggregation="mean")
        else:  # "triangulated"
            v = Verifier(cfg.roles, search_fn=retriever, aggregation="mean")
        agent.verifier = v
        agent.loop.verifier = v

    steps_run = 0
    for _ in range(STEPS):
        x, target = task.sample()
        log = agent.step(x, target)
        steps_run += 1
        if retriever is not None and log.verified:
            if retriever.last_reliability >= 0.5:
                quality_when_reliable.append(log.source_quality)
            else:
                quality_when_unreliable.append(log.source_quality)
        if not log.alive:
            break

    return {
        "test_acc": frozen_eval(agent, task.X_test, task.y_test),
        "alive": agent.budget.alive,
        "steps": steps_run,
        "vault": len(agent.vault),
        "q_reliable": st.mean(quality_when_reliable) if quality_when_reliable else None,
        "q_unreliable": st.mean(quality_when_unreliable) if quality_when_unreliable else None,
        "n_verifications": len(quality_when_reliable) + len(quality_when_unreliable),
    }


def summarize(name: str, runs: list[dict]) -> None:
    acc = [r["test_acc"] for r in runs]
    alive = sum(1 for r in runs if r["alive"])
    print(f"\n[{name}]  (n={len(runs)} seeds)")
    print(f"  held-out test accuracy : {st.mean(acc):.3f} ± {st.pstdev(acc):.3f}  "
          f"| chance={CHANCE}")
    print(f"  survived               : {alive}/{len(runs)}   "
          f"steps: {st.mean([r['steps'] for r in runs]):.0f} avg")
    qr = [r["q_reliable"] for r in runs if r["q_reliable"] is not None]
    qu = [r["q_unreliable"] for r in runs if r["q_unreliable"] is not None]
    if qr and qu:
        gap = st.mean(qr) - st.mean(qu)
        print(f"  source-quality score   : reliable={st.mean(qr):.3f}  "
              f"unreliable={st.mean(qu):.3f}  gap={gap:+.3f}")
        print(f"  verifications          : "
              f"{st.mean([r['n_verifications'] for r in runs]):.0f} avg per run")


def main() -> None:
    print("=" * 68)
    print("Experiment A — real data (digits): full agent vs passive control")
    print("=" * 68)
    full = [run_digits(s, learn=True) for s in SEEDS]
    passive = [run_digits(s, learn=False) for s in SEEDS]
    summarize("FULL on real digits", full)
    summarize("PASSIVE on real digits", passive)

    print()
    print("=" * 68)
    print("Experiment B — Phase 4: source quality under a 40%-misleading corpus")
    print("=" * 68)
    tri = [run_digits(s, learn=True, verifier="triangulated") for s in SEEDS]
    naive = [run_digits(s, learn=True, verifier="naive") for s in SEEDS]
    summarize("TRIANGULATED verifier (k=3, agreement-discounted)", tri)
    summarize("NAIVE verifier (k=1, trusts prior)", naive)

    print("\nVerdict:")
    print(f"  A: real-data learning  full={st.mean(r['test_acc'] for r in full):.2f} "
          f"vs passive={st.mean(r['test_acc'] for r in passive):.2f} "
          f"(chance {CHANCE})")
    tg = st.mean(r["q_reliable"] - r["q_unreliable"] for r in tri
                 if r["q_reliable"] and r["q_unreliable"])
    ng = st.mean(r["q_reliable"] - r["q_unreliable"] for r in naive
                 if r["q_reliable"] and r["q_unreliable"])
    print(f"  B: reliability discrimination gap  triangulated={tg:+.3f} "
          f"vs naive={ng:+.3f}")


if __name__ == "__main__":
    main()
