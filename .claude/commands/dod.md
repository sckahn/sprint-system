---
description: "Manage Definition-of-Done confirmations asynchronously. Review pending ACs, confirm/reject individual items, check milestone and project gates."
---

# /dod — Definition of Done Manager

Async confirmation interface for DoD gates. Use this when GitHub Issues have accumulated pending confirmations and you want to process them in one session.

Sub-commands:
- `/dod review` — interactively process all pending items
- `/dod status` — show pending/confirmed counts (no audit write)
- `/dod pending` — list pending items only (no audit write)
- `/dod confirm <id> [comment]` — confirm a single AC
- `/dod reject <id> <reason>` — reject a single AC
- `/dod needs-more <id> <description>` — request more evidence
- `/dod confirm-milestone <id> [comment]` — confirm a milestone (requires GitHub PR to exist)
- `/dod confirm-project [signer]` — final project sign-off

---

## INVARIANT RULES

1. `bash .claude/bin/audit-verify.sh` must pass before any confirmation
2. Evidence (`ac.evidence_ready` event) MUST exist before any AC can be confirmed
3. Already-confirmed items cannot be re-confirmed (immutable)
4. Milestone confirmation requires ALL its ACs to be confirmed AND a GitHub PR to exist
5. Project confirmation requires ALL milestones to be `milestone.completed`
6. Auto-confirm (`/dod confirm --all`, `--yes-all`, etc.) is NOT supported
7. **RC restriction**: `/dod confirm-milestone` and `/dod confirm-project` are BLOCKED when `CLAUDE_RC_ACTIVE=1`

---

## `/dod status` / `/dod pending`

Read `.audit/events.jsonl`. Tally:

```
DoD Status — <project name>

Pending confirmations:
  ACs:        <N> pending  /  <N> total
  Milestones: <N> pending  /  <N> total
  Project:    <open/closed>

Pending AC list:
  • AC-3.2  sprint 7   milestone M2  (evidence: seq #198)
  • AC-4.1  sprint 8   milestone M3  (evidence: seq #212)

No audit writes performed.
Run `/dod review` to process.
```

---

## `/dod review`

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

═══════════════════════════════════════════════════════
> yes [comment] | no <reason> | needs-more <description> | skip
```

On `yes [comment]`:
- Verify chain integrity
- Verify evidence_ready event exists
- Verify not already processed
- Append `ac.confirmed` event
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
