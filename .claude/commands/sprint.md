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

### Phase 0.0 — Sprint Branch Creation (MANDATORY)

Every sprint runs on its own branch so multiple reviewers can collaborate without polluting main.

Compute slug from sprint goal: lowercase, hyphenated, max 4 words.
```bash
SLUG=$(echo "<goal>" | tr '[:upper:]' '[:lower:]' \
       | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' \
       | cut -c1-40)
BRANCH="sprint/<N>-${SLUG}"

# Must start from up-to-date main
git fetch origin main --quiet
git checkout main && git pull --ff-only origin main

# Create if not exists, switch otherwise
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git checkout "$BRANCH"
else
  git checkout -b "$BRANCH"
  git push -u origin "$BRANCH"
fi
export VIBE_SPRINT_BRANCH="$BRANCH"
```

Append:
```bash
bash .claude/bin/audit-append.sh --git-sync '{"event":"sprint.branch_created","sprint":"<N>","branch":"'"$BRANCH"'","base":"main"}'
```

Append to audit log:
```bash
bash .claude/bin/audit-append.sh --git-sync '{"event":"sprint.started","sprint":"<N>","milestone":"<M>","goal":"<one-line goal from roadmap>"}'
```

### Phase 0.1 — Driver + AC Ownership Registration (MANDATORY, INTERACTIVE)

Identify who is "driving" this sprint (PM) AND who owns each AC for human-check. **Always ask the human at sprint start** — do NOT silently reuse a stale value. Use AskUserQuestion with these 4 questions in a single message:

1. **Driver identity (PM)** — present `git config user.name` + `git config user.email` as the default option.
2. **Driver role** — options: `founder` | `dev` | `reviewer` | `qa`.
3. **Co-driver?** — options: `없음` | `있음 (Other로 "Name <email>" 입력)`.
4. **Require driver for commits?** — options: `예, 차단 (권장)` | `아니오, 허용`. Default to BLOCK.

Then, after Phase 1 (spec-writer outputs the AC list), ask **per-AC owner assignment** in a second AskUserQuestion batch — one question per AC (or one multi-select question if many ACs and same candidate pool):

> "AC-1.1 < title >의 owner(human check 담당자)는?"
> options: 입력된 reviewer 후보들 + Other

**INVARIANT (4-eyes)**: AC owner는 driver(PM)와 달라야 한다. 같으면 다른 사람으로 다시 받는다. 예외: 1인 프로젝트(`SOLO_MODE=1` 환경변수 명시 시).

After answers, set session env (these MUST be exported into the shell the rest of the sprint uses — including agent worktrees via their dispatch env):

```bash
export VIBE_DRIVER="<answer 1>"
export VIBE_DRIVER_ROLE="<answer 2>"
export VIBE_CO_DRIVER="<answer 3 or empty>"
export VIBE_REQUIRE_DRIVER=<1 or 0>
export VIBE_SPRINT=<N>
```

Also persist to `.vibe-driver` at repo root (overwrite, gitignored) so any sub-process / worktree that doesn't inherit the env still finds it:

```bash
cat > .vibe-driver <<EOF
VIBE_DRIVER='$VIBE_DRIVER'
VIBE_DRIVER_ROLE='$VIBE_DRIVER_ROLE'
VIBE_CO_DRIVER='$VIBE_CO_DRIVER'
VIBE_REQUIRE_DRIVER=$VIBE_REQUIRE_DRIVER
VIBE_SPRINT=$VIBE_SPRINT
EOF
grep -qxF '.vibe-driver' .gitignore 2>/dev/null || echo '.vibe-driver' >> .gitignore
```

Ensure the prepare-commit-msg hook is wired (idempotent):
```bash
[ -e .git/hooks/prepare-commit-msg ] || \
  ln -s ../../.claude/bin/git-vibe-trailer.sh .git/hooks/prepare-commit-msg
```

Append audit event:
```bash
bash .claude/bin/audit-append.sh --git-sync '{
  "event":"sprint.driver_registered",
  "sprint":"<N>",
  "driver":"'"$VIBE_DRIVER"'",
  "role":"'"$VIBE_DRIVER_ROLE"'",
  "co_driver":"'"$VIBE_CO_DRIVER"'",
  "require_driver":'"$VIBE_REQUIRE_DRIVER"',
  "branch":"'"$VIBE_SPRINT_BRANCH"'",
  "claude_model":"'"${ANTHROPIC_MODEL:-${CLAUDE_MODEL:-unknown}}"'",
  "session_id":"'"${CLAUDE_SESSION_ID:-unknown}"'"
}'
```

After AC ownership is collected (post Phase 1), for each AC:
```bash
bash .claude/bin/audit-append.sh --git-sync '{
  "event":"ac.owner_assigned",
  "sprint":"<N>",
  "ac_id":"<id>",
  "owner":"'"$AC_OWNER"'",
  "assigned_by":"'"$VIBE_DRIVER"'"
}'
```

**INVARIANT**: any commit produced during this sprint MUST carry `Vibe-Driver:` and `Vibe-Sprint:` trailers. At Phase 5 review, verify and halt if any commit on the sprint branch lacks them:
```bash
MISSING=$(git log --format='%H %s' "$BASE..HEAD" | while read sha rest; do
  git log -1 --format='%B' "$sha" | grep -q '^Vibe-Driver:' || echo "$sha $rest"
done)
[ -n "$MISSING" ] && {
  bash .claude/bin/audit-append.sh '{"event":"vibe.trailer_missing","sprint":"<N>","commits":"'"$MISSING"'"}'
  echo "[HALT] commits without Vibe-Driver trailer:"; echo "$MISSING"; exit 1
}
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

**Isolation contract check (mandatory)**: when a task is dispatched with `isolation: worktree`, the PM MUST verify the contract was honored:

1. Before dispatch: snapshot `git worktree list --porcelain` (call it `WT_BEFORE`).
2. After agent returns: snapshot again (`WT_AFTER`).
3. If `WT_AFTER` shows no new worktree path vs `WT_BEFORE` AND the agent reported changed files, the isolation contract was silently violated. Append:
   ```bash
   bash .claude/bin/audit-append.sh '{"event":"isolation.violated","agent":"<name>","sprint":"<N>","note":"worktree flag set but no new worktree materialized"}'
   ```
   and fail loud to the human — do NOT silently accept the files.

Rationale: a no-op isolation flag means parallel agents in the same sprint could collide on shared files without warning.

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

## Phase 3.5 — Compile Smoke Test (Hermes P1, applied 2026-05-21)

After interface validation, PM MUST run a standalone javac/tsc/etc compile smoke test on all files that do NOT require external lib jars. Goal: catch compilation-blocking bugs (e.g., unicode escapes in comments, malformed JSON in tsconfig) BEFORE they reach Phase 4 reviewers.

For Java projects (JDK 1.6+ target):
```bash
# Extract files with no external lib dep (heuristic: exclude tests, build/, files that import lib packages)
COMPILE_ERRS=$(find . -name "*.java" -not -path "*/tests/*" -not -path "*/build*/*" \
  | xargs javac -source 1.6 -target 1.6 -Xlint:none -d /tmp/sprint-$$ 2>&1 \
  | grep -E "error:" | head -50)
if [ -n "$COMPILE_ERRS" ]; then
  bash .claude/bin/audit-append.sh '{"event":"compile.smoke_failed","sprint":"<N>","errors":"<truncated>"}'
  # Dispatch fix round to the file owner agent BEFORE Phase 4
fi
```

Files that legitimately depend on unavailable jars (Lucene, JDT, custom internal libs) are excluded — document that exclusion explicitly.

Append:
```bash
bash .claude/bin/audit-append.sh '{"event":"compile.smoke_verified","sprint":"<N>","files_checked":<N>,"errors":0}'
```

---

## Phase 3.6 — Shell-Code Gate (anti-hallucination, MANDATORY)

Purpose: machine-verify that implementer agents did not deliver stubs, fake tests, or false claims. Runs **after** compile smoke and **before** Phase 4 reviewers see anything. PM trust is irrelevant here — only code-derived signals count.

### 3.6.a Stub Detection

```bash
bash .claude/bin/stub-detect.sh --base main --json > /tmp/sprint-<N>-stubs.json
```

Detects across changed files (Python/JS/TS/Go/Java/Rust/Ruby):
- `not_implemented` — `NotImplementedError`, `panic("not implemented")`, `todo!()`, `unimplemented!()`, JS `throw new Error("not implemented")`
- `body_trivial` — function body is just `pass` / `return None` / `return null` / `{}` / `return []`
- `todo_only_body` — function body is only a `TODO`/`FIXME` comment
- `fake_test` — `assert True`, `expect(true).toBe(true)`, `@Disabled`, `xit(`, `t.Skip(` in test files

On any finding:
```bash
bash .claude/bin/audit-append.sh '{"event":"stub.detected","sprint":"<N>","findings":<paste-json>}'
```
Dispatch the owning agent for re-implementation (cite each file:line). Do NOT proceed to Phase 4 until `stub-detect.sh` exits 0.

### 3.6.b Liveness / Claim Verification

During Phase 2, every implementer agent MUST report each function/class/endpoint it created via:
```bash
bash .claude/bin/audit-append.sh '{"event":"code.claim","agent":"<name>","ac_id":"<id>","symbol":"<name>","file":"<path>","kind":"function|class|endpoint"}'
```
This is contractually part of the agent's DONE report. An agent reporting DONE without `code.claim` events for new symbols is treated as a protocol violation.

Then verify:
```bash
bash .claude/bin/liveness-check.sh --since-seq <sprint_start_seq> --json > /tmp/sprint-<N>-liveness.json
```

Fails any claim where:
- `missing_file` — the file does not exist
- `symbol_not_defined` — the symbol is not actually defined in that file
- `no_callers` — symbol is defined but referenced nowhere (dead code; skipped for `kind=endpoint`)

On failure: re-dispatch owner with the failure record. Log:
```bash
bash .claude/bin/audit-append.sh '{"event":"liveness.failed","sprint":"<N>","failures":<paste-json>}'
```

### 3.6.c Diff Coverage Gate (where applicable)

If the project has a test runner with coverage (`pytest --cov`, `c8`, `go test -cover`):
- Run tests, produce coverage report
- Require ≥80% coverage on lines changed in this sprint (use `diff-cover` or equivalent)
- On failure: dispatch owner to add real tests (NOT to lower the threshold)

If no coverage tooling exists, skip this sub-gate but log `coverage.skipped` with reason.

### 3.6.d Gate Outcome

Append exactly one of:
```bash
bash .claude/bin/audit-append.sh '{"event":"shell_gate.passed","sprint":"<N>","stubs":0,"liveness_failures":0,"diff_coverage_pct":<N>}'
# or
bash .claude/bin/audit-append.sh '{"event":"shell_gate.failed","sprint":"<N>","reason":"stubs|liveness|coverage","details":"..."}'
```

**INVARIANT**: Phase 4 may not begin while the latest `shell_gate.*` event for this sprint is `failed`. Two re-dispatch rounds maximum; on the third failure, halt and report to human.

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

### Phase 4.2 — AC Review Packet Generation (MANDATORY before 4.3)

Before requesting any human confirmation, PM MUST generate a review packet under `.sprint-reports/sprint-<N>/` so the human reviewer has full context (보고서 / 구현내용 / 기능명세 / 코드명세) in a single MD file.

Directory layout:
```
.sprint-reports/sprint-<N>/
  SUMMARY.md          # 스프린트 전체 요약 + AC 인덱스
  AC-<id>.md          # AC당 한 파일 — 아래 4섹션 필수
```

For **each AC** that passed Phase 4, write `.sprint-reports/sprint-<N>/AC-<ac_id>.md` with this exact structure:

```markdown
# AC-<id> — <AC 제목>

- Sprint: <N>   Milestone: <M>
- Owner agent: <name>   Reviewer agent: <name>
- Audit seq range: <from>–<to>
- Status: ready-for-confirmation

## 1. 보고서 (Report)
- 스프린트 목표 대비 이 AC가 해결한 것 (2–4줄)
- 테스트 결과: <test_file>::<test_name> — PASSED/FAILED
- 보안 감사: <count> findings (<severity breakdown>)
- 코드 리뷰: <count> findings (<severity breakdown>)
- 미해결 이슈/리스크 (없으면 "없음")

## 2. 구현내용 (Implementation)
- 변경된 파일 목록 (`git diff --name-status` 기반)
- 주요 변경 요약 (파일별 1–2줄)
- 의존성/마이그레이션 영향
- 롤백 절차 (필요 시)

## 3. 기능명세 (Functional Spec)
- 사용자/호출자 관점 동작 정의
- 입력 → 출력 계약
- 엣지 케이스 및 에러 동작
- 이 AC가 충족하는 roadmap.md ACID 인용

## 4. 코드명세 (Code Spec)
- 신규/수정된 공개 API 시그니처 (함수/클래스/엔드포인트)
- 데이터 모델/스키마 변경
- 핵심 알고리즘/제어흐름 (간단한 의사코드 또는 파일:라인 인용)
- 테스트 매트릭스 (입력 케이스 ↔ 기대결과)
```

또한 `.sprint-reports/sprint-<N>/SUMMARY.md`를 작성해 스프린트 전체 통계와 AC 패킷 인덱스를 제공한다:

```markdown
# Sprint <N> Summary

- Milestone: <M>
- Goal: <one-line>
- Confirmed ACs (대기 중): <list>
- Deferred: <list>
- Audit seq range: <from>–<to>

## AC Packets
- [AC-<id>](AC-<id>.md) — <title>
- ...
```

Append:
```bash
bash .claude/bin/audit-append.sh '{"event":"ac.evidence_ready","sprint":"<N>","ac_id":"<ac_id>","packet":".sprint-reports/sprint-<N>/AC-<ac_id>.md"}'
```

**INVARIANT**: Phase 4.3 confirmation prompts MUST include the packet path. If the packet file is missing for an AC, halt — do not ask the human to confirm without the packet.

---

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

📄 Review packet (보고서/구현내용/기능명세/코드명세):
   .sprint-reports/sprint-<N>/AC-<ac_id>.md
   (스프린트 요약: .sprint-reports/sprint-<N>/SUMMARY.md)

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

## Phase 5 — Sprint Branch Publication

**Skills used**: `finishing-a-development-branch` (executed by `ci-cd-engineer`).

Invoke `release-manager`:
> "Prepare sprint summary on branch `$VIBE_SPRINT_BRANCH`: list of completed ACs, changed files, changelog entry."

**Do NOT open a PR to main yet.** Only push the sprint branch and notify AC owners:

```bash
# Verify every commit on this sprint branch has Vibe-Driver trailer
MISSING=$(git log --format='%H %s' "main..HEAD" | while read sha rest; do
  git log -1 --format='%B' "$sha" | grep -q '^Vibe-Driver:' || echo "$sha $rest"
done)
[ -n "$MISSING" ] && {
  bash .claude/bin/audit-append.sh --git-sync '{"event":"vibe.trailer_missing","sprint":"<N>","commits":"'"$MISSING"'"}'
  echo "[HALT] commits without Vibe-Driver trailer:"; echo "$MISSING"; exit 1
}

git push origin "$VIBE_SPRINT_BRANCH"

bash .claude/bin/audit-append.sh --git-sync '{
  "event":"sprint.ready_for_human_check",
  "sprint":"<N>",
  "branch":"'"$VIBE_SPRINT_BRANCH"'",
  "ac_owners":<json-map-of-ac-to-owner>,
  "instructions":"Each owner: git fetch && git checkout '"$VIBE_SPRINT_BRANCH"' && /dod review --as <self>"
}'
```

Print to PM and each AC owner:

```
═══════════════════════════════════════════════════════
✅ Sprint <N> ready for human check on branch:
   $VIBE_SPRINT_BRANCH

AC owners — run on your own machine:
  git fetch origin
  git checkout $VIBE_SPRINT_BRANCH
  git pull --ff-only
  claude → /dod review --as "<your name>"

When ALL ACs are owner-confirmed, PM runs:
  /sprint promote   # opens main-merge PR
═══════════════════════════════════════════════════════
```

**The actual main-merge PR is created by `/sprint promote` (separate command), run by PM after all AC owners have confirmed.**

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
