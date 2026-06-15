"""Phase 5 — self-play in an answer-key-free domain (artifact §5).

Demonstrates that a frozen, Phase-1-grounded judge enables learning where there
is no answer key, and that the *grounding* is what does the work:

  1. Phase 1 (keyed): train a full agent on the calibration task; collect
     (context, action, correct) and train a SelfPlayJudge reward model.
  2. Reset the agent's decision head → accuracy collapses to chance.
  3. Keyless self-play: re-learn the decision head by the three-factor rule from
     the FROZEN judge's pseudo-reward (no labels used).
  4. Controls: self-play with a RANDOM judge (no grounding) and the upper bound
     (the original trained agent).

    PYTHONPATH=. OMP_NUM_THREADS=1 python examples/experiment_selfplay.py
"""
from __future__ import annotations

import statistics as st

import torch

from svmp.agent import SelfValidatingAgent
from svmp.config import SVMPConfig
from svmp.selfplay import SelfPlayJudge, reset_decision_head, self_play, train_judge
from svmp.tasks import CalibrationBanditTask

SEEDS = [0, 1, 2, 3, 4]


def _acc(model, task, n=500):
    c = 0
    for _ in range(n):
        x, target = task.sample()
        with torch.no_grad():
            out = model(x, torch.zeros(model.cfg.dim))
        c += int(int(out.logits.argmax()) == target)
    return c / n


def run(seed):
    cfg = SVMPConfig(seed=seed)
    task = CalibrationBanditTask(cfg.n_classes, seed=seed)
    agent = SelfValidatingAgent(cfg, task.feature_dim)

    data = []
    for _ in range(1500):
        x, target = task.sample()
        log = agent.step(x, target)
        data.append((x, log.action, log.correct))
    acc_trained = _acc(agent.model, task)               # upper bound

    judge = SelfPlayJudge(task.feature_dim, cfg.n_classes)
    train_judge(judge, data, epochs=6)

    contexts = [task.sample()[0] for _ in range(2000)]  # keyless (labels dropped)

    reset_decision_head(agent.model)
    acc_reset = _acc(agent.model, task)                 # ~chance
    self_play(agent.model, judge, contexts, cfg, seed=seed)
    acc_grounded = _acc(agent.model, task)

    reset_decision_head(agent.model)
    self_play(agent.model, SelfPlayJudge(task.feature_dim, cfg.n_classes),
              contexts, cfg, seed=seed)
    acc_random = _acc(agent.model, task)

    return acc_trained, acc_reset, acc_grounded, acc_random


def main():
    print("=" * 64)
    print(f"Phase 5 — keyless self-play via a frozen judge (n={len(SEEDS)} seeds)")
    print("=" * 64)
    rows = [run(s) for s in SEEDS]
    trained, reset, grounded, rand = (([r[i] for r in rows]) for i in range(4))

    def line(name, v):
        print(f"  {name:<34} {st.mean(v):.3f} ± {st.pstdev(v):.3f}")

    print(f"\n  chance = {1/4:.3f}")
    line("Phase-1 trained (upper bound)", trained)
    line("decision head reset (floor)", reset)
    line("keyless self-play, GROUNDED judge", grounded)
    line("keyless self-play, RANDOM judge", rand)

    print("\nVerdict:")
    print(f"  grounded self-play recovers {st.mean(grounded) - st.mean(reset):+.3f} "
          f"over the reset floor")
    print(f"  vs random-judge self-play:  {st.mean(grounded) - st.mean(rand):+.3f} "
          f"(the grounding is what teaches)")
    print(f"  ceiling gap to Phase-1:     {st.mean(grounded) - st.mean(trained):+.3f} "
          f"(self-play cannot exceed the judge)")


if __name__ == "__main__":
    main()
