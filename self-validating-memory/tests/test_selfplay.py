"""TDD for Phase 5 — self-play in answer-key-free domains via a frozen judge.

Design (artifact §5): in keyless domains there is no external oracle, so a frozen
judge grounded by Phase-1 external verification provides the pseudo-reward. We
train a reward-model judge on keyed data, freeze it, reset the agent's decision
head, and check that keyless self-play with the *grounded* judge recovers
accuracy — while self-play with a *random* judge does not. The frozen
representation is reused; only the decision head is re-learned by the three-factor
rule from the judge's pseudo-reward.

Tests written BEFORE the implementation; they must fail first.
"""
import torch

from svmp.agent import SelfValidatingAgent
from svmp.config import SVMPConfig
from svmp.selfplay import (
    SelfPlayJudge,
    reset_decision_head,
    self_play,
    train_judge,
)
from svmp.tasks import CalibrationBanditTask


def _eval_acc(model, task, n=400):
    g = task  # CalibrationBanditTask draws fresh noisy samples (same prototypes)
    correct = 0
    for _ in range(n):
        x, target = g.sample()
        with torch.no_grad():
            retrieved = torch.zeros(model.cfg.dim)
            out = model(x, retrieved)
        correct += int(int(out.logits.argmax()) == target)
    return correct / n


def _phase1(seed=0, steps=1200):
    cfg = SVMPConfig(seed=seed)
    task = CalibrationBanditTask(cfg.n_classes, seed=seed)
    agent = SelfValidatingAgent(cfg, task.feature_dim)
    data = []
    for _ in range(steps):
        x, target = task.sample()
        log = agent.step(x, target)
        data.append((x, log.action, log.correct))
    return cfg, task, agent, data


def test_judge_learns_to_predict_correctness():
    cfg, task, agent, data = _phase1()
    judge = SelfPlayJudge(task.feature_dim, cfg.n_classes)
    train_judge(judge, data, epochs=5)
    # On held-out (context, action) pairs the judge should beat chance at saying
    # whether the action is the true class.
    correct = total = 0
    for _ in range(400):
        x, target = task.sample()
        for a in range(cfg.n_classes):
            with torch.no_grad():
                p = float(judge(x, torch.nn.functional.one_hot(
                    torch.tensor(a), cfg.n_classes).float()))
            pred_correct = p > 0.5
            total += 1
            correct += int(pred_correct == (a == target))
    assert correct / total > 0.7


def test_keyless_selfplay_with_grounded_judge_recovers_accuracy():
    cfg, task, agent, data = _phase1()
    judge = SelfPlayJudge(task.feature_dim, cfg.n_classes)
    train_judge(judge, data, epochs=6)

    # Reset the decision head → accuracy collapses toward chance.
    reset_decision_head(agent.model)
    acc_reset = _eval_acc(agent.model, task)

    # Keyless self-play with the grounded frozen judge.
    contexts = [task.sample()[0] for _ in range(1500)]
    self_play(agent.model, judge, contexts, cfg, seed=0)
    acc_grounded = _eval_acc(agent.model, task)

    # Control: reset again, self-play with a RANDOM (untrained) judge.
    reset_decision_head(agent.model)
    random_judge = SelfPlayJudge(task.feature_dim, cfg.n_classes)
    self_play(agent.model, random_judge, contexts, cfg, seed=0)
    acc_random = _eval_acc(agent.model, task)

    assert acc_grounded > acc_reset + 0.1          # self-play taught something
    assert acc_grounded > acc_random + 0.1         # and it was the grounded judge
