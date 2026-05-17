---
description: "Initialize sprint-system in the current project. Provisions GitHub Actions workflows, audit scripts, and creates the first audit event. Run once per project after installing the plugin."
---

# /sprint-system:init — Project Initialization

You are the sprint-system installer. Provision project-bound files into the current working directory.

## Step 1 — Detect project state

Check what exists:
- `roadmap.md` — exists or not?
- `.audit/events.jsonl` — exists or not?
- `.github/workflows/roadmap-loop.yml` — exists or not?
- `.claude/bin/audit-append.sh` — exists or not?

If `.audit/events.jsonl` already exists and has content, ask: "A sprint-system audit log already exists. Re-init will reset scripts but preserve the audit chain. Continue? yes/no"

## Step 2 — Ask configuration questions

One at a time:

1. "What is your project name?" (used in audit log metadata)
2. "What tech stack? (Python / TypeScript-Node / Go / Other)" 
3. "Do you have a GitHub repository? If yes, what is the org/repo?" (for workflow secrets guidance)
4. "Which compliance frameworks apply? (K-FSC / SOX / PCI-DSS / ISO27001 / None)" (for compliance/ folder guidance)
5. "Do you want to set up S3 Object Lock for long-term audit preservation? (yes / not now)"

## Step 3 — Provision scripts

Create the following in the current directory:

### .claude/bin/ scripts (copy from plugin)
The plugin includes all audit scripts. Write them to `.claude/bin/`:
- `audit-append.sh`
- `audit-verify.sh`
- `audit-attest.sh`
- `audit-shift.sh`
- `audit-mcp-hook.sh`
- `gh-sync-pending.sh`
- `gh-process-comment.sh`
- `notify-pending.sh`
- `start-rc.sh`

Make all scripts executable:
```bash
chmod +x .claude/bin/*.sh
```

### .github/workflows/
- `roadmap-loop.yml`
- `dod-handler.yml`
- `audit-verify.yml`
- `audit-shift.yml` (only if S3 answer was yes)

### Directories
```bash
mkdir -p .audit .dod .hermes/proposals docs/adr
```

## Step 4 — Initialize audit chain (genesis event)

```bash
bash .claude/bin/audit-append.sh "{\"event\":\"audit.genesis\",\"project\":\"<project_name>\",\"initialized_by\":\"$(git config user.email 2>/dev/null || echo 'unknown')\",\"stack\":\"<stack>\"}"
```

Verify:
```bash
bash .claude/bin/audit-verify.sh
```

Expected: `OK: 1 events verified`

## Step 5 — Create CLAUDE.md (if not exists)

If no `CLAUDE.md`, create a starter:
```markdown
# Project Context

## Project
<project_name>

## Stack
<stack>

## Sprint system
- Audit log: .audit/events.jsonl
- Run: /roadmap init to create roadmap.md
- Run: /roadmap continue to start sprinting
```

## Step 6 — Create roadmap.md (if not exists)

If no `roadmap.md`, copy the template:
```bash
cp <plugin_path>/templates/roadmap.template.md roadmap.md
```
Tell user: "Edit `roadmap.md` to add your milestones, then run `/roadmap init` to finalize."

## Step 7 — Compliance folder (conditional)

If user selected compliance frameworks, create:
```bash
mkdir -p compliance
```
And note: "Compliance mapping documents are in the plugin's `compliance/` folder. Copy the relevant ones to your project's `compliance/` directory."

## Step 8 — Summary

Report:
```
✅ sprint-system initialized

Created:
  .claude/bin/          — 9 audit scripts
  .github/workflows/    — 3-4 GitHub Actions
  .audit/               — audit chain started (seq #1)
  CLAUDE.md             — project context
  roadmap.md            — roadmap template

GitHub Secrets needed:
  ANTHROPIC_API_KEY     — required (Claude API access)
  SLACK_WEBHOOK_DOD     — optional (DoD notifications)
  SLACK_WEBHOOK_ALERTS  — optional (halt alerts)
  AWS_AUDIT_BUCKET      — optional (S3 long-term storage)
  AWS_AUDIT_ROLE_ARN    — optional (S3 OIDC auth)

Next steps:
  1. git add -A && git commit -m "chore: init sprint-system"
  2. git push
  3. Add GitHub Secrets (Settings → Secrets → Actions)
  4. Set up branch protection (Settings → Branches → main)
  5. Create labels: dod:pending, dod:ac, dod:milestone, dod:confirmed, dod:rejected
  6. Run: /roadmap init  — to define your project's milestones
  7. Run: /roadmap continue  — to start your first sprint
```
