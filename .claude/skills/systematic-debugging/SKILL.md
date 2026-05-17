---
name: systematic-debugging
description: Use when diagnosing any bug, test failure, or unexpected behavior
---

# Systematic Debugging

**"NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST"**

Applying a patch without understanding the root cause creates two bugs: the original and the patch.

## 4 mandatory phases

### Phase 1 — Root cause investigation

- Read error messages and stack traces carefully (all the way)
- Reproduce the problem reliably
- Review recent changes with version control
- Add diagnostic instrumentation at component boundaries
- Trace data flow backward from the symptom

### Phase 2 — Pattern analysis

- Find similar working code
- Read the reference implementation fully
- Compare working vs. non-working implementations
- Understand all dependencies and assumptions

### Phase 3 — Hypothesis and test

- Form a specific, testable hypothesis
- Apply minimal, isolated changes
- Test one variable at a time
- If hypothesis fails: form a new one, don't patch

### Phase 4 — Implementation

- Write a failing test case first (see `test-driven-development`)
- Implement the single root-cause fix
- Verify the fix resolves the problem
- If fix fails 3+ times: reconsider the architecture

## Critical warning

**After 3+ failed fix attempts:** stop patching. Reconsider the fundamental architecture. You are not debugging — you are guessing.

## Output format for sprint-system

When `sre-incident` or any agent reports a debugging result:

```json
{
  "bug_id": "<ac_id or incident_id>",
  "root_cause": "<one clear sentence>",
  "evidence": ["<stack trace or log line>", "<test that reproduced it>"],
  "fix_description": "<what was changed and why>",
  "test_added": "<test file and test name>",
  "hypothesis_count": 1
}
```

If `hypothesis_count > 3`: escalate to human with architecture assessment.
