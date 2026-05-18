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

## Headless mode

If `CLAUDE_HEADLESS=1` (set by GitHub Actions):
- Gate 0 → post roadmap as GitHub Issue, wait for `/confirm` comment
- Phase 4.3 → existing PR comment flow (no change)
- Milestone gate → existing dod-handler flow
- Project gate → existing dod-handler flow

The interactive prompts above are wrapped automatically by `.claude/bin/gh-sync-pending.sh`.

---

## What this command IS NOT

- Not a way to skip DoD gates
- Not a one-shot code generator
- Not autonomous past a real blocker — stops and asks
- Not for trivial tasks — for those, just write the code directly

## What this command IS

The thinnest possible wrapper that turns "한 문장" into a fully audited agile cycle, with humans only making the decisions that matter: scope, quality, completion.
