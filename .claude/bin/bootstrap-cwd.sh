#!/usr/bin/env bash
# bootstrap-cwd.sh — initialize sprint-system structure in the current directory.
# Called by /start when invoked in a fresh directory that lacks .audit/.
#
# Idempotent: safe to re-run.
set -euo pipefail

CWD="$(pwd)"
ROOT_FILE="${HOME}/.claude/sprint-system-root"

[[ -f "$ROOT_FILE" ]] || {
  echo "ERROR: ~/.claude/sprint-system-root missing. Run install-global.sh from sprint-system repo first." >&2
  exit 1
}

SS_ROOT="$(cat "$ROOT_FILE")"
[[ -d "$SS_ROOT" ]] || { echo "ERROR: sprint-system root not found at $SS_ROOT" >&2; exit 1; }

echo "→ Bootstrapping sprint-system in: $CWD"
echo "→ Source: $SS_ROOT"

# 1. Ensure git repo (audit/dod assume git workflow)
if [[ ! -d .git ]]; then
  git init -q -b main
  echo "✓ initialized git repo"
fi

# 2. Create runtime directories
mkdir -p .audit .dod .hermes/proposals docs/adr docs/superpowers/{plans,specs}
echo "✓ created runtime directories"

# 3. Symlink .claude into cwd so claude picks up commands/agents/skills locally too
#    (Also lets `claude` outside ~/.claude/ pick up project-bound files)
if [[ ! -e .claude ]]; then
  ln -s "$SS_ROOT/.claude" .claude
  echo "✓ linked .claude → $SS_ROOT/.claude"
fi

# 4. Copy roadmap template if no roadmap exists yet
if [[ ! -f roadmap.md ]] && [[ -f "$SS_ROOT/roadmap.template.md" ]]; then
  cp "$SS_ROOT/roadmap.template.md" roadmap.md
  echo "✓ created roadmap.md from template (will be replaced by /start)"
fi

# 5. Initial audit chain genesis event (if not yet)
if [[ ! -s .audit/events.jsonl ]]; then
  GIT_EMAIL="$(git config user.email 2>/dev/null || echo unknown)"
  PROJECT="$(basename "$CWD")"
  bash "$SS_ROOT/.claude/bin/audit-append.sh" \
    "{\"event\":\"audit.genesis\",\"project\":\"$PROJECT\",\"initialized_by\":\"$GIT_EMAIL\",\"via\":\"bootstrap-cwd\"}" \
    >/dev/null
  echo "✓ audit chain genesis event created"
fi

# 6. Verify chain
if bash "$SS_ROOT/.claude/bin/audit-verify.sh" --quiet 2>/dev/null; then
  echo "✓ audit chain verified"
else
  echo "⚠  audit chain verification skipped"
fi

echo ""
echo "✅ Sprint-system ready in: $CWD"
