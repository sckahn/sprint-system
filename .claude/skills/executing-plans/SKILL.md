---
name: executing-plans
description: Use when a plan document exists and it's time to implement it step by step
---

# Executing Plans

**First: announce** "I'm using the executing-plans skill to implement this plan."

## Initial phase

1. Load the plan document from `docs/superpowers/plans/`
2. Read it critically — flag any concerns to the user before proceeding
3. Do NOT start on main/master without explicit user consent

## Execution phase

For each task:
- Show progress status
- Follow each step exactly as written (do not improvise)
- Run the specified verifications (`verification-before-completion`)
- Confirm completion with actual output

## Blockers — stop immediately for any of these

- Missing dependency
- Test failure that the plan doesn't account for
- Unclear instructions (ask, don't guess)
- Architecture mismatch between plan and reality

**"Ask, don't guess."**

## Completion

When all tasks are done, hand off to `finishing-a-development-branch` skill.

## Required skills

This skill works together with:
- `using-git-worktrees` — for isolated execution
- `writing-plans` — the plan must exist before this skill runs
- `finishing-a-development-branch` — for branch integration after completion
- `verification-before-completion` — every "done" requires evidence

## Best performance

Works best with subagent support (`dispatching-parallel-agents`). Subagent-driven development produces significantly higher quality results.

---

## sprint-system integration

**Used in**: `/sprint` Phase 2 (Parallel Execution)

Each implementation agent (`backend-eng`, `frontend-eng`, `db-engineer`) receives a task from the sprint plan and executes it using this skill.

The PM coordinator does NOT execute plans itself — it dispatches them to specialist agents. After all parallel agents complete, the PM coordinator runs Phase 3 (Cross-Validation) before accepting results.

Blockers surfaced during plan execution are logged to audit:
```bash
bash .claude/bin/audit-append.sh '{"event":"sprint.blocker","sprint":"<N>","task":"<id>","reason":"<description>"}'
```
