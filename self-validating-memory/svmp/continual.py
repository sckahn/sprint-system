"""Continual-learning harness for the catastrophic-forgetting study.

This directly tests the design's central stability-plasticity claim: an agent is
trained on a *sequence* of tasks (A → B → C …) and we measure how much accuracy
on an earlier task is lost after learning later ones. If the gated consolidation
and external vault genuinely protect old knowledge, forgetting should be small.

The harness is deliberately mechanism-level and deterministic so the experiment
in ``examples/experiment_continual.py`` and the tests in ``tests/test_continual.py``
share exactly the same measurement code.
"""
from __future__ import annotations

from .agent import SelfValidatingAgent
from .tasks import SplitContinualTask


def infer(agent: SelfValidatingAgent, x) -> int:
    """Inference along the agent's own decision path (vault read + model + vote)."""
    return agent.predict(x)


def eval_accuracy(agent: SelfValidatingAgent, task: SplitContinualTask,
                  task_idx: int, n: int = 300) -> float:
    correct = 0
    for _ in range(n):
        x, y = task.sample(task_idx)
        correct += int(infer(agent, x) == y)
    return correct / n


def run_continual(agent: SelfValidatingAgent, task: SplitContinualTask,
                  steps_per_task: int, eval_n: int = 300) -> list[list[float | None]]:
    """Train tasks 0…T-1 in sequence; after each, eval every task seen so far.

    Returns a lower-triangular matrix ``acc`` where ``acc[i][j]`` is the accuracy
    on task ``j`` measured right after finishing training on task ``i`` (``j <= i``;
    not-yet-seen tasks are left as ``None``).
    """
    T = task.n_tasks
    acc: list[list[float | None]] = [[None] * T for _ in range(T)]
    for i in range(T):
        for _ in range(steps_per_task):
            x, y = task.sample(i)
            agent.step(x, y)
        for j in range(i + 1):
            acc[i][j] = eval_accuracy(agent, task, j, eval_n)
    return acc


def forgetting(acc: list[list[float | None]]) -> float:
    """Average forgetting: mean over earlier tasks of (peak − final) accuracy.

    ``peak`` is the accuracy right after that task was learned (the diagonal);
    ``final`` is its accuracy after the whole sequence (the last row).
    """
    T = len(acc)
    if T < 2:
        return 0.0
    drops = [acc[j][j] - acc[T - 1][j] for j in range(T - 1)]
    return sum(drops) / len(drops)


def final_accuracy(acc: list[list[float | None]]) -> float:
    """Mean accuracy over all tasks at the end of the sequence (last row)."""
    T = len(acc)
    return sum(acc[T - 1][j] for j in range(T)) / T
