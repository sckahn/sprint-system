---
description: "Manage Definition-of-Done confirmations asynchronously. Review pending ACs, confirm/reject individual items, check milestone and project gates."
---

# /dod — Definition of Done Manager

Async confirmation interface for DoD gates. Use this when GitHub Issues have accumulated pending confirmations and you want to process them in one session.

Sub-commands:
- `/dod review --as <name>` — interactively process the ACs you own (multi-human mode)
- `/dod review` — process all pending items (PM/solo mode — only allowed if `SOLO_MODE=1`)
- `/dod status` — show ownership matrix + confirmation status (no audit write)
- `/dod pending` — list pending items only (no audit write)
- `/dod confirm <id> [comment] [--as <name>]` — confirm a single AC
- `/dod reject <id> <reason> [--as <name>]` — reject a single AC
- `/dod needs-more <id> <description> [--as <name>]` — request more evidence
- `/dod confirm-milestone <id> [comment]` — confirm a milestone (requires GitHub PR to exist)
- `/dod confirm-project [signer]` — final project sign-off

**Multi-human ownership model**: each AC has one `owner` recorded via `ac.owner_assigned` events at sprint start. Only that owner may confirm/reject their AC (4-eyes: owner ≠ driver/PM). `--as <name>` MUST match the AC's recorded owner; mismatch → refused.

---

## INVARIANT RULES

1. `bash .claude/bin/audit-verify.sh` must pass before any confirmation
2. Evidence (`ac.evidence_ready` event) MUST exist before any AC can be confirmed
3. Already-confirmed items cannot be re-confirmed (immutable)
4. Milestone confirmation requires ALL its ACs to be confirmed AND a GitHub PR to exist
5. Project confirmation requires ALL milestones to be `milestone.completed`
6. Auto-confirm (`/dod confirm --all`, `--yes-all`, etc.) is NOT supported
7. **RC restriction**: `/dod confirm-milestone` and `/dod confirm-project` are BLOCKED when `CLAUDE_RC_ACTIVE=1`
8. **Ownership invariant**: every confirm/reject MUST match the AC's recorded owner. Look up via `bash .claude/bin/ac-ownership-check.sh owner <ac_id>`. Mismatch → refuse with "AC-X is owned by <X>, not <Y>".
9. **Shared-branch syncing**: all confirm/reject events MUST be appended with `audit-append.sh --git-sync` so other owners on other machines see the latest state.

---

## `/dod status` / `/dod pending`

First `git fetch origin && git pull --ff-only` on the current sprint branch (so you see other owners' confirms). Then read `.audit/events.jsonl` and call `bash .claude/bin/ac-ownership-check.sh matrix <sprint>`:

```
DoD Status — <project name>
Branch: sprint/10-add-payment-flow   (head: 0a3f1c2)

Sprint 10 — Human Check Matrix:
  AC ID     Owner              Status            Confirmed at
  ──────────────────────────────────────────────────────────────
  AC-1.1    jdoe               ✅ confirmed       2026-05-22 10:30
  AC-1.2    asmith             ⏳ pending         -
  AC-1.3    bkim               ❌ rejected        2026-05-22 11:05  reason: edge case missing
  AC-1.4    jdoe               ⏳ pending         -

Sprint promotion:
  2 / 4 ACs confirmed.  1 rejected → owner must re-work.
  Not ready for /sprint promote.

Pending milestones: 0 / 1
Project: open

No audit writes performed.
Run `/dod review --as <your name>` to confirm your own ACs.
```

---

## `/dod review [--as <name>]`

**Multi-human mode (`--as` given)**:
- Filter ACs to those whose owner matches `<name>` (case-insensitive name match against `ac.owner_assigned` events). If 0 matches, print "No ACs owned by <name> in current sprint" and exit.
- Export `VIBE_REVIEWER="<name>"` so commit trailers get stamped (if you make code edits during review).
- First sync: `git fetch origin && git pull --ff-only`.

**Solo mode (no `--as`)**: requires `SOLO_MODE=1`; otherwise refuse with "multi-human sprint — use --as <your name>".

Process each pending item interactively, one at a time.

For each pending AC (ordered by sprint ASC, then AC ID):

```
═══════════════════════════════════════════════════════
[<N>/<total>] AC CONFIRMATION: <ac_id>

Title:     <AC title from roadmap.md>
Sprint:    <N>   Milestone: <M>
Audit seq: #<seq>

Evidence:
  Tests:     <test_file>::<test_name>  ✓ PASSED
  Security:  <finding_count> findings — <severity>
  Review:    <finding_count> findings — <severity>
  Code:      <file>:<lines>

📄 Review packet (보고서/구현내용/기능명세/코드명세):
   .sprint-reports/sprint-<N>/AC-<ac_id>.md
   (요약: .sprint-reports/sprint-<N>/SUMMARY.md)
   ⚠ 패킷 파일이 없으면 confirm 차단 — sprint Phase 4.2 재실행 필요

═══════════════════════════════════════════════════════
> yes [comment] | no <reason> | needs-more <description> | skip
```

On `yes [comment]`:
- Verify chain integrity
- Verify evidence_ready event exists
- **Verify review packet file exists at `.sprint-reports/sprint-<N>/AC-<ac_id>.md`** — if missing, refuse and instruct human to re-run sprint Phase 4.2
- **Verify caller's `--as <name>` matches the AC's owner** (via `ac-ownership-check.sh owner <ac_id>`) — mismatch refuses
- Verify not already processed
- Append `ac.confirmed` event with `--git-sync` so other owners see it
- After append, check via `ac-ownership-check.sh sprint-ready <N>` — if ALL ACs are confirmed, also emit `sprint.fully_reviewed` and print "✅ Sprint <N> ready — PM can run /sprint promote"
- Close GitHub Issue if exists
- Print: `✅ AC-<id> confirmed (seq #<N>)`

On `no <reason>`:
- Append `ac.rejected` event
- Update GitHub Issue label
- Print: `❌ AC-<id> rejected — returned to backlog`

On `needs-more <description>`:
- Append `ac.needs_more` event
- Update GitHub Issue
- Print: `🔄 AC-<id> needs more work`

On `skip`:
- No audit write
- Move to next item

After all ACs processed, check if any milestone is now fully confirmed and present milestone gate if applicable.

---

## `/dod confirm <ac_id> [comment]`

Single AC confirmation:

1. Verify chain: `bash .claude/bin/audit-verify.sh --quiet`
2. Check `ac.evidence_ready` exists for `<ac_id>`
3. Check not already confirmed/rejected
4. Append:
```bash
bash .claude/bin/audit-append.sh '{"event":"ac.confirmed","ac_id":"<ac_id>","approver":"<human>","rationale":"<comment>"}'
```
5. Update GitHub Issue if exists

---

## `/dod confirm-milestone <milestone_id> [comment]`

**RC BLOCK**: If `CLAUDE_RC_ACTIVE=1`, respond:
> "❌ Milestone confirmation requires desktop session with 4-eyes PR review. RC single-user confirmation is not permitted for milestone gates."

Steps:
1. Verify all ACs in milestone are `ac.confirmed`
2. Verify quality gates (from roadmap.md)
3. Check GitHub PR exists for this milestone (`gh pr list --label dod:milestone:<id>`)
4. If PR not merged yet: "PR #<N> must be merged by a second reviewer before milestone can be closed."
5. If PR merged:
```bash
bash .claude/bin/audit-append.sh '{"event":"milestone.completed","milestone_id":"<id>","confirmed_by":"<human>","pr_merged":"<PR url>","comment":"<comment>"}'
```

```
═══════════════════════════════════════════════════════
🏁 MILESTONE CONFIRMED: <id>

Signed by:    <human>
PR merged:    #<N>
ACs closed:   <N>
Audit seq:    #<N>

Next: run `/roadmap continue` for next milestone
═══════════════════════════════════════════════════════
```

---

## `/dod confirm-project [signer]`

**RC BLOCK**: Always blocked via RC.

Steps:
1. Verify ALL milestones are `milestone.completed`
2. Run full audit verify
3. Present final summary (total sprints, ACs, audit events, fingerprint)
4. Require explicit signer name/title

```
═══════════════════════════════════════════════════════
🎉 PROJECT SIGN-OFF

All milestones: ✓
Audit chain:    verified ✓
Chain head:     <sha256[:16]>...

This is irreversible. Signing as: <signer>

Type CONFIRM to proceed:
═══════════════════════════════════════════════════════
```

On `CONFIRM`:
```bash
bash .claude/bin/audit-append.sh '{"event":"roadmap.project_closed","signed_by":"<signer>","signing_method":"interactive_dod_command"}'
bash .claude/bin/audit-attest.sh --from 1 --to <last_seq> --label "project-final"
```

Print attestation path and fingerprint.
