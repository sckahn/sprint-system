---
name: subagent-driven-development
description: Use when you have a complete implementation plan and want to delegate tasks to specialized subagents for higher quality output
---

# Subagent-Driven Development

**"One new subagent per task + two-stage review (spec compliance + code quality) = high quality, fast iteration."**

Delegate implementation tasks to specialist agents with isolated contexts. Validate with two sequential reviews.

## Execution model

The coordinator interrupts **only** when blocked:
- Unresolvable blocker
- Genuine ambiguity that prevents progress
- Task complete

## When to use

- You have a complete implementation plan (`writing-plans`)
- Most tasks are independent
- You intend to stay in the current session

## Subagent status handling

| Status | Action |
|--------|--------|
| DONE | Proceed to review |
| DONE_WITH_CONCERNS | Evaluate concerns → proceed or fix |
| NEEDS_CONTEXT | Provide information |
| BLOCKED | Re-evaluate task scope |

## Review sequence

1. Subagent completes implementation
2. **Review Stage 1**: spec compliance — does it match the AC?
3. **Review Stage 2**: code quality — `requesting-code-review` skill
4. Issues found → send back to implementer → re-review → approve

## Model economics

| Model tier | When to use |
|------------|-------------|
| Lower capability | Mechanical implementation with complete spec |
| Standard | Multi-file integration tasks |
| Premium (Opus) | Architecture decisions, comprehensive reviews |

---

## sprint-system integration

**This skill IS the sprint-system pattern.**

The PM coordinator IS a subagent-driven development coordinator. Every `/sprint` execution follows this model:

```
PM Coordinator (subagent-driven-development)
  ↓ dispatches-parallel-agents
  ├── backend-eng (executing-plans + test-driven-development)
  ├── frontend-eng (executing-plans + test-driven-development)
  └── db-engineer (executing-plans)
  ↓ cross-validates (interface-validator)
  ↓ two-stage review
  ├── Stage 1: qa-tester (spec/AC compliance)
  └── Stage 2: code-reviewer + security-auditor (quality + security)
  ↓ DoD gate (human confirmation)
  ↓ finishing-a-development-branch (ci-cd-engineer)
```

**Key integration points**:
- `sprint.planned` event records the delegation plan
- Each delegated task must use `verification-before-completion` before reporting DONE
- `interface-validator` runs between parallel execution and review stages
- `hermes` observes the whole cycle and proposes improvements to the coordinator's task decomposition

**Coordinator quality metric**: velocity (`ac.confirmed / ac.planned`). Hermes uses this to evaluate if the coordinator's task decomposition is improving over sprints.
