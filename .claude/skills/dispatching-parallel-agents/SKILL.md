---
name: dispatching-parallel-agents
description: Use when facing 2+ independent tasks that can be worked on without shared state or sequential dependencies
---

# Dispatching Parallel Agents

**"One agent per independent problem domain. Let them work simultaneously."**

Each agent: isolated context, specific problem, no inheritance from this session's context or history.

## When to use

✅ Use when:
- 3+ test files failing with different root causes
- Multiple subsystems independently broken
- Each problem understandable without context from others
- No shared state between investigations

❌ Do NOT use when:
- Failures are related (fixing one might fix others)
- Understanding the whole system state is needed first
- Agents would interfere (same files, same resources)

## Pattern

### 1. Identify independent domains

Group failures by what is broken:
- File A tests: tool approval flow
- File B tests: batch completion behavior
- File C tests: interrupt functionality

### 2. Create focused agent tasks

Each agent gets:
- **Specific scope**: one test file or subsystem
- **Clear goal**: make these tests pass
- **Constraint**: do not change other code
- **Expected output**: summary of what was found and fixed

### 3. Dispatch in parallel (single message, multiple Agent calls)

```
Task("Fix agent-tool-abort.test.ts failures")
Task("Fix batch-completion-behavior.test.ts failures")
Task("Fix tool-approval-race-conditions.test.ts failures")
// All three execute simultaneously
```

### 4. Review and integrate

When agents return:
- Read each summary
- Confirm fixes don't conflict (`interface-validator`)
- Run the full test suite
- Integrate all changes

## Good agent prompt structure

```markdown
Fix the 3 failing tests in src/agents/agent-tool-abort.test.ts:

1. "should abort tool with partial output capture" — expects 'interrupted at' in message
2. "should handle mixed completed and aborted tools" — fast tool aborted instead of completed
3. "should properly track pendingToolCount" — expects 3 results but gets 0

These are timing/race condition issues. Your task:
1. Read the test file and understand what each test verifies
2. Identify root cause — timing issues or actual bugs?
3. Fix by:
   - Replacing arbitrary timeouts with event-based waiting
   - Fixing bugs in abort implementation if found
   - Adjusting test expectations if testing changed behavior

Do NOT just increase timeouts — find the real issue.
Do NOT modify files outside src/agents/agent-tool-abort.ts and its test.

Return: Summary of what you found and what you fixed.
```

## Common mistakes

| Mistake | Effect |
|---------|--------|
| Too broad: "fix all tests" | Agent gets lost |
| No context: "fix race conditions" | Agent doesn't know where |
| No constraints | Agent refactors everything |
| Vague output: "fix it" | Can't tell what changed |

---

## sprint-system integration

**Used in**: `/sprint` Phase 2 (Parallel Execution)

The PM coordinator uses this skill to fan out implementation tasks. The rule:
- Only tasks that touch **different files** may run in parallel
- `interface-validator` runs after all parallel agents complete (Phase 3)
- `sprint.planned` event records `owner_agent` + `reviewer_agent` for each task
- Conflicts detected by `interface-validator` → the conflicting agents re-run with updated constraints

Parallel dispatch audit event:
```bash
bash .claude/bin/audit-append.sh '{"event":"sprint.parallel_dispatch","sprint":"<N>","agents":<list>,"task_count":<N>}'
```
