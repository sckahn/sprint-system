# Sprint System — Validation Examples

This directory contains files for running the first validation cycle.

## Quick start

```bash
# 1. Copy into your project root
cp examples/validation-roadmap.md ../roadmap.md
cp examples/CLAUDE.md ../CLAUDE.md

# 2. Edit CLAUDE.md — pick one stack (Python/TS/Go), delete the others

# 3. Run bootstrap
bash ../.claude/bin/bootstrap.sh

# 4. Start Claude Code
cd ..
claude

# 5. In the Claude chat:
# > /roadmap init
# > /roadmap continue
```

## What should happen

1. `spec-writer` refines AC-val.1–3 into concrete tasks
2. `backend-eng` creates `src/hello.py`
3. `qa-tester` creates `tests/test_hello.py` and runs pytest
4. `code-reviewer` reviews the code
5. `security-auditor` audits (should be clean for hello world)
6. PM coordinator presents each AC to you for confirmation
7. You type: `yes` for each one
8. `ci-cd-engineer` creates a PR
9. You run `/dod confirm-milestone M-val` after PR is merged
10. You run `/dod confirm-project` to close

## Expected audit events after completion

```
sprint.started
sprint.planned
sprint.interfaces_validated
security.audit_completed (critical=0)
ac.evidence_ready (×3)
ac.confirmed (×3, approver=you)
sprint.retro
sprint.completed
milestone.evidence_ready
milestone.completed
hermes.applied
roadmap.project_closed
```

Total: ~15–20 events. All verifiable with `bash .claude/bin/audit-verify.sh`.
