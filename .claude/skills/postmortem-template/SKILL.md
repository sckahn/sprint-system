# Postmortem Template — Blameless Incident Review

## When to use this skill

Use when writing or reviewing a postmortem after any production incident (SEV1, SEV2, or significant SEV3).

---

## Blameless principle

Postmortems name **systems, processes, and conditions** — never individuals.

- ❌ "John deployed broken code"
- ✅ "A deployment proceeded without a required review because the branch protection rule was bypassed"

The goal is to understand how the system allowed the incident to happen, and to prevent recurrence.

---

## Required sections

### 1. Impact
Quantify everything:
- Users affected: N (or X%)
- Revenue impact: estimated
- Duration: start → mitigated → resolved
- SLO burn: how much error budget consumed?

### 2. Timeline
Chronological, UTC, factual:

| Time (UTC) | Event |
|------------|-------|
| 14:23 | Deployment of v2.1.4 completed |
| 14:31 | Error rate spike detected by Datadog alert |
| 14:33 | On-call engineer paged |
| 14:45 | Root cause identified: null pointer in payment handler |
| 14:52 | Rollback to v2.1.3 initiated |
| 14:58 | Service restored, error rate nominal |
| 15:20 | Postmortem started |

### 3. Root Cause
One clear sentence: "The incident was caused by X, which allowed Y to occur."

Then: 5 Whys analysis — keep asking "why" until you reach a systemic cause.

### 4. Contributing Factors
Additional conditions that made the incident worse or harder to detect:
- Monitoring gap: alert threshold too high
- On-call runbook outdated
- Test coverage missing for this code path

### 5. What Went Well
Honestly note things that worked:
- Alert fired within 2 minutes
- On-call response was fast
- Rollback script was ready and tested

### 6. Action Items

| Action | Type | Owner | Due | Status |
|--------|------|-------|-----|--------|
| Add integration test for payment null case | Prevent | @team | 2026-01-15 | open |
| Lower alert threshold from 5% to 1% error rate | Detect | @sre | 2026-01-10 | open |
| Update on-call runbook for payment failures | Respond | @oncall | 2026-01-12 | open |

Action types: **Prevent** (stop recurrence) | **Detect** (catch faster) | **Respond** (recover faster)

---

## File location

`docs/postmortems/YYYY-MM-DD-<slug>.md`

Example: `docs/postmortems/2026-01-09-payment-null-pointer.md`

---

## Audit logging

After writing a postmortem:
```bash
bash .claude/bin/audit-append.sh '{"event":"incident.postmortem_published","file":"docs/postmortems/<filename>","severity":"<SEV>","duration_min":<N>,"action_items":<N>}'
```

---

## Review checklist

Before publishing:
- [ ] No individual named in blame context
- [ ] All impact metrics filled in (even if estimated)
- [ ] Timeline is chronological and factual
- [ ] Root cause is systemic, not personal
- [ ] Every action item has owner and due date
- [ ] Audit event appended
