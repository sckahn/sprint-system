---
name: requesting-code-review
description: Use after completing any implementation task to get a code review before marking work done
---

# Requesting Code Review

## When to invoke

- **Mandatory**: after each task in subagent-driven development
- After completing a major feature
- Before merging to main
- When stuck (optional)
- Before large refactors (optional)

## Process

1. Get the git SHA for the commits to review
2. Dispatch a reviewer subagent with the template below
3. Handle feedback by priority level

## Reviewer subagent template

```markdown
Review the changes in git commit(s) <SHA> for:
- Correctness: does it do what it's supposed to?
- Code quality: readability, maintainability, conventions
- Security: any obvious vulnerabilities?
- Tests: are they adequate?

Focus on: <specific concern if any>
Context: <what the feature does in one sentence>

Output JSON:
{
  "findings": [
    {
      "severity": "Critical | Important | Minor",
      "file": "<path>",
      "line": <N>,
      "issue": "<description>",
      "suggested_fix": "<fix>"
    }
  ],
  "summary": { "critical": N, "important": N, "minor": N, "approve": true/false }
}
```

## Handling feedback

| Severity | Action |
|----------|--------|
| Critical | Fix immediately before proceeding |
| Important | Fix before proceeding |
| Minor | Log for later; may proceed |

You may counter feedback with technical grounds (see `receiving-code-review`).

## Prohibited

- Skipping review for "simple" changes
- Ignoring Critical feedback
- Proceeding with unresolved Important issues (without valid technical counter)

---

## sprint-system integration

**Used in**: `/sprint` Phase 4 (Quality Gate)

The `code-reviewer` agent is the primary reviewer. In sprint-system:
- `backend-eng` → requests review from `code-reviewer` after each task
- `code-reviewer` uses the `receiving-code-review` skill when processing feedback
- Review findings are part of the AC evidence before `ac.evidence_ready` is appended

Audit event on review completion:
```bash
bash .claude/bin/audit-append.sh '{"event":"code.review_completed","reviewer":"code-reviewer","critical":<N>,"important":<N>}'
```
