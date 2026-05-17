---
description: "Run one agile sprint cycle: planning → execution (parallel) → cross-validation → review → retrospective → Hermes learning"
---

# /sprint — Single Sprint Cycle

You are the **PM Coordinator** orchestrating one complete sprint. Follow each phase strictly. Never skip gates. Refer to `roadmap.md` for milestones and `CLAUDE.md` for project conventions.

---

## INVARIANT RULES (never bypass)

1. `bash .claude/bin/audit-verify.sh` MUST pass before any phase starts
2. No agent may review its own work — `owner_agent ≠ reviewer_agent`
3. Story/AC confirmation always goes to the human — never auto-approve
4. Parallel agents touch different files — coordinate before spawning
5. On any policy violation: append `policy.violation_detected` to audit log, halt, report to human

---

## Phase 0 — Pre-flight

```
bash .claude/bin/audit-verify.sh
```

If verification fails: stop, report `[HALT] Audit chain broken at seq=N`. Do not proceed.

Read `roadmap.md`. Identify the current milestone and its pending ACs. If `roadmap.md` does not exist, ask the human to run `/roadmap init` first.

Append to audit log:
```bash
bash .claude/bin/audit-append.sh '{"event":"sprint.started","sprint":"<N>","milestone":"<M>","goal":"<one-line goal from roadmap>"}'
```

---

## Phase 1 — Sprint Planning

**Skills used**: `brainstorming` (when AC is ambiguous), `writing-plans` (mandatory output is a plan with 2–5 min granular tasks).

Using the `spec-writer` agent, refine the sprint goal into concrete tasks:

**Invoke spec-writer**:
> "Given roadmap milestone `<M>` and the following pending ACs: `<list>`, break this sprint into implementation tasks. For each task output: id, description, owner_agent, reviewer_agent (must differ from owner), affected_files, dependencies."

Validate the task list:
- Every task has `owner_agent ≠ reviewer_agent`
- No two parallel tasks share the same file path
- Each task maps to at least one AC in `roadmap.md`

Append:
```bash
bash .claude/bin/audit-append.sh '{"event":"sprint.planned","sprint":"<N>","task_count":<N>,"tasks":<json-array>}'
```

---

## Phase 2 — Parallel Execution

**Skills used**: `dispatching-parallel-agents`, `using-git-worktrees`, `subagent-driven-development`, `executing-plans`, `test-driven-development`, `verification-before-completion`.

Each specialist agent runs in an isolated worktree (`.worktrees/sprint-<N>-<agent>`). Before reporting DONE, every agent must pass `verification-before-completion`'s 5 gates.

Fan-out independent tasks to specialist agents **simultaneously** (use multiple Agent tool calls in one message — see `dispatching-parallel-agents`):

| Task type | Agent |
|-----------|-------|
| Backend API / services | `backend-eng` |
| Frontend / UI | `frontend-eng` |
| Database schema | `db-engineer` |
| ML / data pipeline | `ml-engineer` (if applicable) |
| Mobile | `mobile-eng` (if applicable) |

**Key instruction to each agent**: Include the AC IDs this task satisfies, affected files, and the constraint "do not touch files owned by parallel tasks: `<list>`".

Wait for all agents to complete. Collect results.

---

## Phase 3 — Cross-Validation (Interface Checking)

Invoke `interface-validator`:
> "Validate that the following agent outputs are mutually consistent: `<summary of each agent's changes>`. Check: API contracts, shared type definitions, DB schema ↔ ORM models, import paths."

If mismatches found: spawn the relevant agents to fix (one round only). If still broken after one round, halt and report.

Append:
```bash
bash .claude/bin/audit-append.sh '{"event":"sprint.interfaces_validated","sprint":"<N>","issues_found":<N>,"issues_resolved":<N>}'
```

---

## Phase 4 — Quality & Security Gate

**Skills used**: `requesting-code-review`, `receiving-code-review`, `systematic-debugging` (when defects surface).

The PM dispatches review agents via `requesting-code-review`. Implementer agents process findings via `receiving-code-review` — counters must be logged via `audit-append.sh review.counter_raised`.

Run review agents **in parallel**:

**Invoke code-reviewer**:
> "Review all files changed in this sprint. Output: findings array with file, line, severity (Critical/Warning/Info), issue, suggested_fix."

**Invoke security-auditor** (mandatory if any auth/payments/user-data files changed):
> "Security audit of sprint changes. Focus: injection, auth bypass, secrets exposure, CVEs. Output: findings with exploitability rating."

**Invoke qa-tester**:
> "Write and run tests for all ACs in this sprint. For each AC output: ac_id, test_file, test_name, passed (bool), evidence."

Collect all findings. For each Critical finding: the owning agent MUST fix it before proceeding.

### Phase 4.3 — Story-level DoD Gate (MANDATORY HUMAN CONFIRMATION)

For each AC with passing tests and no unresolved Critical findings:

```
═══════════════════════════════════════════════════════
🔍 AC CONFIRMATION REQUIRED — Sprint <N>

AC ID:     <ac_id>
Title:     <ac title from roadmap.md>
Evidence:
  ✓ Tests:    <test_file>::<test_name> — PASSED
  ✓ Security: <finding count> findings (<severity breakdown>)
  ✓ Review:   <finding count> findings

Audit seq range: <from>–<to>

Respond: yes | no <reason> | needs-more <description>
═══════════════════════════════════════════════════════
```

**Wait for human response for EACH AC.** Do not batch-approve.

On `yes`:
```bash
bash .claude/bin/audit-append.sh '{"event":"ac.confirmed","ac_id":"<ac_id>","approver":"<human>","sprint":"<N>","rationale":"<their comment>"}'
```

On `no <reason>`:
```bash
bash .claude/bin/audit-append.sh '{"event":"ac.rejected","ac_id":"<ac_id>","rejector":"<human>","reason":"<reason>","sprint":"<N>"}'
```

On `needs-more <desc>`:
```bash
bash .claude/bin/audit-append.sh '{"event":"ac.needs_more","ac_id":"<ac_id>","sprint":"<N>","description":"<desc>"}'
```

**POLICY**: No AC may be auto-confirmed. No shortcut. Even if `CLAUDE_RC_ACTIVE=1`, individual AC confirmation is allowed. Milestone/project confirmation is NOT allowed via RC.

---

## Phase 5 — Sprint Review

**Skills used**: `finishing-a-development-branch` (executed by `ci-cd-engineer`).

Invoke `release-manager`:
> "Prepare sprint review: list of completed ACs, changed files, PR description, changelog entry."

Create PR if all confirmed ACs have passing CI:
```bash
bash .claude/bin/audit-append.sh '{"event":"sprint.pr_created","sprint":"<N>","pr_url":"<url>","confirmed_acs":<list>}'
```

---

## Phase 6 — Retrospective

Summarize:
- Completed: `<AC IDs>`
- Rejected/deferred: `<AC IDs with reasons>`
- Velocity: `<confirmed / planned>%`
- Blockers encountered

Append:
```bash
bash .claude/bin/audit-append.sh '{"event":"sprint.retro","sprint":"<N>","velocity":<pct>,"completed":<list>,"deferred":<list>,"notes":"<summary>"}'
```

---

## Phase 7 — Hermes Learning

Invoke `hermes` agent:
> "Analyze sprint `<N>`. Identify: repeated friction points, patterns in rejected ACs, workflow inefficiencies. Output proposals to `.hermes/proposals/sprint-<N>.md`. Do NOT modify system prompts or CLAUDE.md directly. Threshold: only propose if issue occurred 2+ times or caused >30min delay."

After Hermes outputs proposals:
1. Present each proposal to the human: "Hermes proposes: `<proposal>`. Apply? yes/no"
2. Only apply approved proposals (edit the relevant .md file)
3. Log applied ones:
```bash
bash .claude/bin/audit-append.sh '{"event":"hermes.applied","sprint":"<N>","proposals_reviewed":<N>,"proposals_applied":<N>}'
```

---

## Phase 8 — Close

```bash
bash .claude/bin/audit-append.sh '{"event":"sprint.completed","sprint":"<N>","milestone":"<M>","confirmed_acs":<list>}'
bash .claude/bin/audit-attest.sh --from <start_seq> --to <end_seq> --label "sprint-<N>"
```

Report to human:
- Sprint `<N>` complete
- ACs confirmed: `<list>`
- ACs deferred: `<list>`  
- Next: run `/roadmap continue` to evaluate milestone DoD
