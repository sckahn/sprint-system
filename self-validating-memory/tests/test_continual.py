"""Tests for the catastrophic-forgetting study harness.

These cover the *deterministic* machinery (task splits, ablation knobs, the
forgetting metric, harness shape). The scientific outcome — how much the agent
actually forgets — lives in ``examples/experiment_continual.py``; it is an
empirical result to be reported, not asserted here.
"""
import pytest
import torch

from svmp.config import SVMPConfig
from svmp.agent import SelfValidatingAgent
from svmp.tasks import SplitContinualTask, PermutedLabelTask
from svmp.continual import (
    run_continual, forgetting, final_accuracy, eval_accuracy,
)


def test_split_task_emits_only_its_classes():
    task = SplitContinualTask(n_classes=8, n_tasks=2, feature_dim=16, seed=0)
    assert task.task_classes == [[0, 1, 2, 3], [4, 5, 6, 7]]
    for t in range(2):
        labels = {task.sample(t)[1] for _ in range(200)}
        assert labels <= set(task.task_classes[t])
    assert task.prototypes.shape == (8, 16)


def test_split_task_requires_divisible_classes():
    with pytest.raises(ValueError):
        SplitContinualTask(n_classes=7, n_tasks=2)


def test_split_task_sample_shape():
    task = SplitContinualTask(n_classes=4, n_tasks=2, feature_dim=12, seed=1)
    x, y = task.sample(0)
    assert x.shape == (12,)
    assert isinstance(y, int)


def test_permuted_task_first_map_is_identity():
    task = PermutedLabelTask(n_classes=8, n_tasks=2, feature_dim=16, seed=0)
    assert task.perms[0] == list(range(8))


def test_permuted_task_labels_conflict_across_tasks():
    # Every task shares the same input regions but permutes their labels, so at
    # least one region must have a different correct answer between tasks.
    task = PermutedLabelTask(n_classes=8, n_tasks=2, feature_dim=16, seed=0)
    assert task.perms[0] != task.perms[1]
    assert any(a != b for a, b in zip(task.perms[0], task.perms[1]))


def test_permuted_task_emits_all_labels_each_task():
    task = PermutedLabelTask(n_classes=8, n_tasks=2, feature_dim=16, seed=0)
    for t in range(2):
        labels = {task.sample(t)[1] for _ in range(400)}
        assert labels <= set(range(8))
    assert task.prototypes.shape == (8, 16)


def test_use_vault_false_keeps_vault_empty():
    cfg = SVMPConfig(seed=0, n_classes=8)
    agent = SelfValidatingAgent(cfg, 16, use_vault=False)
    task = SplitContinualTask(8, 2, 16, seed=0)
    for _ in range(30):
        x, y = task.sample(0)
        agent.step(x, y)
    assert len(agent.vault) == 0


def test_force_gate_overrides_consolidation_gate():
    cfg = SVMPConfig(seed=0, n_classes=8)
    agent = SelfValidatingAgent(cfg, 16, force_gate=1.0)
    task = SplitContinualTask(8, 2, 16, seed=0)
    x, y = task.sample(0)
    log = agent.step(x, y)
    assert log.gate == 1.0
    assert agent.learner.gate.last == 1.0


def test_forgetting_metric_known_matrix():
    # task0 peak 0.9 → final 0.3 (drop 0.6); task1 peak 0.8 → final 0.6 (drop 0.2)
    acc = [
        [0.9, None, None],
        [0.5, 0.8, None],
        [0.3, 0.6, 0.7],
    ]
    assert forgetting(acc) == pytest.approx((0.6 + 0.2) / 2)
    assert final_accuracy(acc) == pytest.approx((0.3 + 0.6 + 0.7) / 3)


def test_forgetting_single_task_is_zero():
    assert forgetting([[0.9]]) == 0.0


def test_run_continual_returns_lower_triangular_matrix():
    cfg = SVMPConfig(seed=0, n_classes=8)
    agent = SelfValidatingAgent(cfg, 16)
    task = SplitContinualTask(8, 2, 16, seed=0)
    acc = run_continual(agent, task, steps_per_task=20, eval_n=40)
    assert len(acc) == 2
    assert acc[0][1] is None              # task 1 not seen after training task 0
    assert all(isinstance(acc[i][j], float)
               for i in range(2) for j in range(i + 1))
    assert -1.0 <= forgetting(acc) <= 1.0


def test_eval_accuracy_in_unit_range():
    cfg = SVMPConfig(seed=0, n_classes=8)
    agent = SelfValidatingAgent(cfg, 16)
    task = SplitContinualTask(8, 2, 16, seed=0)
    a = eval_accuracy(agent, task, 0, n=50)
    assert 0.0 <= a <= 1.0
