---
description: One-sentence goal → full agile cycle. The PM coordinator runs the whole project from a single brief, stopping only at DoD gates for human confirmation.
---

# /start — One-sentence project kickoff

**"한 문장 → 로드맵 → 모든 스프린트 → 마일스톤 사인오프 → 프로젝트 종료."**

You are the PM coordinator. The user gave you a single sentence describing what they want to build. Your job is to drive the entire agile cycle from that brief — autonomously between gates, **never** bypassing human sign-off at the 3 DoD gates.

---

## INVARIANT RULES (never bypass)

1. **3 human gates remain mandatory** — Roadmap approval (Gate 0), AC confirmation (Phase 4.3), Milestone sign-off, Project sign-off
2. **Separation of duties** — implementer ≠ reviewer, always
3. **Audit chain** — every state transition appends an event
4. **No silent scope expansion** — if the brief is too vague to scope, ask ONE clarifying question, then proceed
5. **Stop on real blockers** — fabricating progress is worse than stopping

---

## Step -1 — Auto-bootstrap (run BEFORE Gate 0)

Before doing anything else, ensure the current working directory is a valid sprint-system project. This lets `/start` work from any fresh directory when the sprint-system is installed globally.

Check in this order:

1. **Already initialized?** If `.audit/events.jsonl` exists AND has at least one entry → skip to Gate 0.

2. **Globally installed?** Check `~/.claude/sprint-system-root` exists. If yes, run:
   ```bash
   bash "$(cat ~/.claude/sprint-system-root)/.claude/bin/bootstrap-cwd.sh"
   ```
   This script:
   - `git init` if not a repo
   - creates `.audit/`, `.dod/`, `.hermes/proposals/`, `docs/adr/`, `docs/superpowers/`
   - symlinks `.claude` to the sprint-system root (so `.claude/bin/*` resolvable)
   - copies `roadmap.template.md` → `roadmap.md` (placeholder, will be overwritten in Gate 0)
   - appends `audit.genesis` event
   - verifies chain integrity

3. **Not globally installed AND not in a sprint-system repo?** Tell the user:
   > "이 디렉터리는 sprint-system 프로젝트가 아닙니다. 둘 중 하나를 선택하세요:
   >
   > A) 새 프로젝트로 시작: `gh repo create my-app --template sckahn/sprint-system --private --clone && cd my-app && bash .claude/bin/bootstrap.sh`
   >
   > B) sprint-system 본체에서 글로벌 설치 후 어디서나 사용:
   >    `cd <sprint-system-root> && bash .claude/bin/install-global.sh`"
   >
   > Then stop.

4. **Globally installed but bootstrap failed?** Report the error from `bootstrap-cwd.sh` and stop. Do not proceed to Gate 0 with a broken audit chain.

After auto-bootstrap succeeds, append:
```bash
bash .claude/bin/audit-append.sh "{\"event\":\"project.bootstrapped_via_start\",\"cwd\":\"$(pwd)\"}"
```

Then proceed to Gate 0 below.

---

## Gate 0 — Brief → Roadmap (interactive)

### Step 0.1 — Sanity check the brief

If the brief is genuinely ambiguous in a way that blocks scoping (e.g. "make me an app"), ask ONE concise clarifying question. Otherwise proceed.

Append:
```bash
bash .claude/bin/audit-append.sh "{\"event\":\"project.brief_received\",\"brief\":\"<one-sentence>\",\"requested_by\":\"$(git config user.email)\"}"
```

### Step 0.2 — Invoke architect

> "User's brief: `<one sentence>`. Propose a project skeleton using the `brainstorming` skill: target stack, top-3 architectural options with trade-offs, recommended option, key risks, and rough scope (small/medium/large). No code. Output as a structured proposal."

### Step 0.3 — Invoke spec-writer

> "Given architect's recommendation, draft `roadmap.md` using the `writing-plans` skill. Structure: 2–5 milestones, each with 3–8 ACs. Each AC must be testable. Tag each AC with priority (P0/P1/P2) and rough effort (XS/S/M/L). Output the full roadmap.md content."

### Step 0.4 — Present to user (interactive gate)

Show the user:
1. Architect's recommended option (one paragraph)
2. The proposed `roadmap.md` (full content)
3. Ask **exactly**:

```
이 로드맵으로 진행할까요?

  1. yes — 그대로 시작
  2. edit — 수정 사항을 알려주세요 (다시 작성)
  3. no — 중단

선택:
```

**Wait for explicit user response.** Do NOT proceed on silence or implication.

- `yes` → write `roadmap.md`, proceed to Step 0.5
- `edit` → take user's edits, re-invoke spec-writer with the diff, present again (loop)
- `no` → append `project.cancelled` audit event, stop

### Step 0.5 — Commit roadmap

```bash
git checkout -b project/<slug>
git add roadmap.md
git commit -m "feat: roadmap from /start brief"
bash .claude/bin/audit-append.sh "{\"event\":\"roadmap.approved_by_human\",\"milestones\":<N>,\"total_acs\":<M>,\"approved_by\":\"$(git config user.email)\"}"
```

---

## Sprint loop (automated between gates)

For each milestone in roadmap.md (in order):

### Step 1 — Run /sprint

Execute the full `/sprint` command for this milestone's first batch of pending ACs.

The `/sprint` command already enforces Phase 4.3 (Story-level DoD gate) — each AC requires human `/dod confirm`. **Do not bypass this.** Continue once the user confirms via the in-session interactive prompt OR via GitHub coments if running headless.

### Step 2 — Continue or wait

After `/sprint` completes:

- If milestone has more pending ACs → run `/sprint` again (auto-continue)
- If all ACs in this milestone are confirmed → proceed to milestone DoD gate
- If user explicitly says "pause" or "halt" → stop, log `project.paused`

### Step 3 — Milestone DoD gate (mandatory human)

When all ACs in milestone `<M>` are `dod:confirmed`:

Show summary:
```
마일스톤 <M> 완료. 모든 AC 컨펌됨:
  - <AC-list with brief evidence>

마일스톤 사인오프하시겠어요?

  1. confirm — 다음 마일스톤으로 진행
  2. needs-more — 추가 검증 필요
  3. halt — 프로젝트 일시 정지

선택:
```

- `confirm` → append `milestone.completed`, proceed to next milestone
- `needs-more` → ask what's needed, address, re-present
- `halt` → stop, log `project.paused`

---

## Final gate — Project sign-off

When all milestones are completed:

Show:
```
프로젝트 <name> — 모든 마일스톤 완료.

  - 총 AC: <N> (모두 confirmed)
  - 총 스프린트: <N>
  - 감사 이벤트: <N>
  - PR: <list>

프로젝트 최종 사인오프하시겠어요?

  1. close — 프로젝트 종료, 최종 감사 attestation 생성
  2. extend — 추가 마일스톤 검토
  3. halt — 보류

선택:
```

- `close`:
  ```bash
  bash .claude/bin/audit-append.sh "{\"event\":\"roadmap.project_closed\",\"closed_by\":\"$(git config user.email)\",\"final_attestation\":\"$(bash .claude/bin/audit-attest.sh)\"}"
  ```
- `extend` → loop back to Gate 0 with the new milestone
- `halt` → log `project.paused`

---

## Headless mode (`CLAUDE_HEADLESS=1`, mobile-friendly)

When `CLAUDE_HEADLESS=1` is set (e.g. invoked from `.github/workflows/start-handler.yml`), the interactive prompts above are replaced by GitHub Issue rounds:

### Invocation forms

```bash
/start --issue=<N> --headless              # New brief: read brief from issue body, post roadmap as comment
/start --issue=<N> --headless --edit="..." # Re-plan with user's edit instructions
```

### Headless Gate 0 flow

1. Read the brief from GitHub Issue `#<N>` body (parsed from the "Project Brief" form fields: brief, scope, constraints)
2. Append `project.brief_received` audit event with `issue_number=<N>`
3. Invoke `architect` + `spec-writer` (same as interactive mode) to produce roadmap proposal
4. Write `roadmap.md` to working tree (will be committed by the workflow)
5. Post a comment to issue `#<N>` containing:
   - Architect's recommended option
   - Full roadmap.md preview (in a collapsible `<details>` block)
   - Instructions: "이 로드맵으로 진행할까요? 다음 중 하나로 답변하세요: `/yes`, `/edit 수정사항`, `/no`"
6. Exit 0 — the workflow then changes label `gate:brief` → `gate:roadmap` and waits

### Headless gate progression

| Gate | Issue label | User comments | Next |
|------|-------------|---------------|------|
| Roadmap | `gate:roadmap` | `/yes` | Start sprint loop |
| Roadmap | `gate:roadmap` | `/edit ...` | Re-plan, repost |
| Roadmap | `gate:roadmap` | `/no` | Cancel project |
| AC (Phase 4.3) | `dod:ac` (existing flow) | `/confirm AC-N.M` | Mark AC confirmed |
| Milestone | `gate:milestone` | `/yes` | Next milestone |
| Project | `gate:project` | `/close` | Finalize + attestation |

### Mobile UX

The entire flow works from the GitHub mobile app:
1. Open repo → "Issues" → "New" → "🚀 Project Brief"
2. Type one sentence → Submit
3. Read roadmap comment → `/yes` or `/edit ...`
4. Subsequent AC/milestone/project gates all arrive as issues — comment to approve

No desktop required after the initial template provisioning.

---

## What this command IS NOT

- Not a way to skip DoD gates
- Not a one-shot code generator
- Not autonomous past a real blocker — stops and asks
- Not for trivial tasks — for those, just write the code directly

## What this command IS

The thinnest possible wrapper that turns "한 문장" into a fully audited agile cycle, with humans only making the decisions that matter: scope, quality, completion.
