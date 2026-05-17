---
name: writing-plans
description: Use after brainstorming is complete and a design is approved, to create a detailed step-by-step implementation plan
---

# Writing Plans

Create comprehensive, granular implementation plans that any engineer can execute with minimal codebase context.

## Core principle

Write every step as if the engineer has **zero context** about the codebase.
- Every step: 2–5 minutes (test → run → implement → verify → commit)
- No placeholders: no "TBD", no "handle edge cases" — real code in every step
- Plans saved to: `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`

## Before writing

- Confirm the spec doesn't span multiple independent subsystems (split if it does)
- Map file structure with clear boundaries
- Ensure each task produces independently testable, working software

## Plan document structure

```markdown
# Implementation Plan: <feature>
Date: YYYY-MM-DD
Spec: docs/superpowers/specs/YYYY-MM-DD-<feature>.md
Tech stack: <stack>
Architecture summary: <one paragraph>

## Task 1: <task name>
Files: src/path/to/file.ts

### Step 1.1 — Write failing test
\`\`\`typescript
// exact test code
\`\`\`
Expected failure: <exact error message>

### Step 1.2 — Implement
\`\`\`typescript
// exact implementation code
\`\`\`

### Step 1.3 — Verify
\`\`\`bash
npm test -- --testPathPattern="<file>"
\`\`\`
Expected output: <exact output>

### Step 1.4 — Commit
\`\`\`bash
git add <files>
git commit -m "feat(<scope>): <description>"
\`\`\`

## Task 2: ...
```

## Self-review checklist

1. Every spec requirement maps to a task?
2. No red flags:
   - Unspecified error handling
   - Missing code blocks
   - Vague instructions ("handle appropriately")
   - Type/method inconsistencies across tasks
3. Each task produces working, testable software?

## Completion

After writing the plan, offer:
- **Subagent-driven execution** (recommended): each task dispatched to a fresh agent
- **Inline execution**: execute in current session

---

## sprint-system integration

**Invoked by**: `spec-writer` after ACs are written, OR by `architect` after an ADR is approved.

**Output location**: `docs/superpowers/plans/YYYY-MM-DD-<sprint>-<feature>.md`

The `/sprint` command's Phase 1 (Planning) uses this skill to produce the task list that gets passed to parallel implementation agents in Phase 2.

Plans created here map directly to `sprint.planned` audit events — each task in the plan becomes an `owner_agent` + `reviewer_agent` assignment.
