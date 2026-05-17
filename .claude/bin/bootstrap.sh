#!/usr/bin/env bash
# bootstrap.sh — initialize or verify sprint-system in the current project
# Idempotent: safe to re-run
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
err()  { echo -e "${RED}✗${NC}  $1"; }
info() { echo -e "${BLUE}→${NC} $1"; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo ""
echo "════════════════════════════════════════════════════════"
echo "   sprint-system bootstrap"
echo "   Project: $ROOT"
echo "════════════════════════════════════════════════════════"
echo ""

ERRORS=0

# ─── Phase 1: Dependencies ───────────────────────────────────
echo "── Phase 1: Dependencies"

check_cmd() {
  if command -v "$1" &>/dev/null; then ok "$1"; else err "$1 not found"; ERRORS=$((ERRORS+1)); fi
}

check_cmd python3
check_cmd git
check_cmd sha256sum
check_cmd jq
check_cmd gh

# Python version
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"; then
  ok "python3 $PY_VER"
else
  err "python3 >= 3.9 required (found $PY_VER)"
  ERRORS=$((ERRORS+1))
fi

# Claude CLI
if command -v claude &>/dev/null; then
  CLAUDE_VER=$(claude --version 2>/dev/null | head -1 || echo "unknown")
  ok "claude ($CLAUDE_VER)"
else
  warn "claude CLI not found — install from https://claude.ai/download"
fi

echo ""

# ─── Phase 2: Directory structure ────────────────────────────
echo "── Phase 2: Directory structure"

DIRS=(
  ".claude/agents"
  ".claude/commands"
  ".claude/bin"
  ".claude/skills/coding-style"
  ".claude/skills/api-contract"
  ".claude/skills/postmortem-template"
  ".claude/skills/test-driven-development"
  ".claude/skills/systematic-debugging"
  ".claude/skills/verification-before-completion"
  ".claude/skills/brainstorming"
  ".claude/skills/writing-plans"
  ".claude/skills/executing-plans"
  ".claude/skills/dispatching-parallel-agents"
  ".claude/skills/requesting-code-review"
  ".claude/skills/receiving-code-review"
  ".claude/skills/using-git-worktrees"
  ".claude/skills/finishing-a-development-branch"
  ".claude/skills/subagent-driven-development"
  "docs/superpowers/plans"
  "docs/superpowers/specs"
  ".audit"
  ".dod"
  ".hermes/proposals"
  ".github/workflows"
  "docs/adr"
)

for d in "${DIRS[@]}"; do
  mkdir -p "$d"
  ok "$d"
done

echo ""

# ─── Phase 3: Scripts ────────────────────────────────────────
echo "── Phase 3: Audit scripts"

SCRIPTS=(
  ".claude/bin/audit-append.sh"
  ".claude/bin/audit-verify.sh"
  ".claude/bin/audit-attest.sh"
  ".claude/bin/audit-shift.sh"
  ".claude/bin/audit-mcp-hook.sh"
  ".claude/bin/gh-sync-pending.sh"
  ".claude/bin/gh-process-comment.sh"
  ".claude/bin/notify-pending.sh"
  ".claude/bin/start-rc.sh"
  ".claude/bin/bootstrap.sh"
)

for s in "${SCRIPTS[@]}"; do
  if [[ -f "$s" ]]; then
    chmod +x "$s"
    ok "$s"
  else
    err "$s missing"
    ERRORS=$((ERRORS+1))
  fi
done

echo ""

# ─── Phase 4: Commands ───────────────────────────────────────
echo "── Phase 4: Slash commands"

COMMANDS=(
  ".claude/commands/sprint.md"
  ".claude/commands/roadmap.md"
  ".claude/commands/dod.md"
)

for c in "${COMMANDS[@]}"; do
  if [[ -f "$c" ]]; then ok "$c"; else err "$c missing"; ERRORS=$((ERRORS+1)); fi
done

echo ""

# ─── Phase 5: Agents ─────────────────────────────────────────
echo "── Phase 5: Specialist agents"

REQUIRED_AGENTS=(
  "spec-writer" "architect"
  "backend-eng" "frontend-eng" "db-engineer"
  "code-reviewer" "security-auditor" "qa-tester" "interface-validator"
  "ci-cd-engineer" "release-manager" "sre-incident" "hermes"
)

OPTIONAL_AGENTS=("ml-engineer" "data-engineer" "mobile-eng" "accessibility-auditor")

for a in "${REQUIRED_AGENTS[@]}"; do
  if [[ -f ".claude/agents/${a}.md" ]]; then
    ok ".claude/agents/${a}.md"
  else
    err ".claude/agents/${a}.md missing (required)"
    ERRORS=$((ERRORS+1))
  fi
done

for a in "${OPTIONAL_AGENTS[@]}"; do
  if [[ -f ".claude/agents/${a}.md" ]]; then
    ok ".claude/agents/${a}.md"
  else
    info ".claude/agents/${a}.md not present (optional — add if needed)"
  fi
done

echo ""

# ─── Phase 6: Skills ─────────────────────────────────────────
echo "── Phase 6: Skills"

SKILLS=(
  ".claude/skills/coding-style/SKILL.md"
  ".claude/skills/api-contract/SKILL.md"
  ".claude/skills/postmortem-template/SKILL.md"
)

SUPERPOWERS_SKILLS=(
  ".claude/skills/test-driven-development/SKILL.md"
  ".claude/skills/systematic-debugging/SKILL.md"
  ".claude/skills/verification-before-completion/SKILL.md"
  ".claude/skills/brainstorming/SKILL.md"
  ".claude/skills/writing-plans/SKILL.md"
  ".claude/skills/executing-plans/SKILL.md"
  ".claude/skills/dispatching-parallel-agents/SKILL.md"
  ".claude/skills/requesting-code-review/SKILL.md"
  ".claude/skills/receiving-code-review/SKILL.md"
  ".claude/skills/using-git-worktrees/SKILL.md"
  ".claude/skills/finishing-a-development-branch/SKILL.md"
  ".claude/skills/subagent-driven-development/SKILL.md"
)

for sk in "${SKILLS[@]}"; do
  if [[ -f "$sk" ]]; then ok "$sk"; else warn "$sk missing (optional but recommended)"; fi
done

echo ""
echo "── Phase 6b: Superpowers skills (obra/superpowers)"

for sk in "${SUPERPOWERS_SKILLS[@]}"; do
  if [[ -f "$sk" ]]; then ok "$sk"; else warn "$sk missing — agents won't reach full quality"; fi
done

echo ""

# ─── Phase 7: GitHub Actions ─────────────────────────────────
echo "── Phase 7: GitHub Actions"

WORKFLOWS=(
  ".github/workflows/roadmap-loop.yml"
  ".github/workflows/dod-handler.yml"
  ".github/workflows/audit-verify.yml"
)

for w in "${WORKFLOWS[@]}"; do
  if [[ -f "$w" ]]; then ok "$w"; else warn "$w missing — CI automation won't work"; fi
done

echo ""

# ─── Phase 8: Audit chain ────────────────────────────────────
echo "── Phase 8: Audit chain"

if [[ ! -f ".audit/events.jsonl" ]] || [[ ! -s ".audit/events.jsonl" ]]; then
  info "No audit log found — creating genesis event"
  GIT_EMAIL=$(git config user.email 2>/dev/null || echo "unknown")
  GIT_REPO=$(git remote get-url origin 2>/dev/null || echo "local")
  bash .claude/bin/audit-append.sh \
    "{\"event\":\"audit.genesis\",\"project\":\"$(basename "$ROOT")\",\"initialized_by\":\"${GIT_EMAIL}\",\"git_repo\":\"${GIT_REPO}\"}" \
    >/dev/null
  ok "audit.genesis event created"
fi

if bash .claude/bin/audit-verify.sh --quiet; then
  CHAIN_EVENTS=$(wc -l < .audit/events.jsonl | tr -d ' ')
  ok "audit chain verified ($CHAIN_EVENTS events)"
else
  err "audit chain BROKEN — run: bash .claude/bin/audit-verify.sh"
  ERRORS=$((ERRORS+1))
fi

echo ""

# ─── Phase 9: Add-ons status ────────────────────────────────
echo "── Phase 9: Optional add-ons"

[[ -f "compliance/k-fsc-mapping.md" ]]   && ok "K-FSC compliance mapping"    || info "compliance/ not present (activate for financial sector)"
[[ -f "infra/terraform/audit-bucket.tf" ]] && ok "S3 Object Lock infra"       || info "infra/terraform/ not present (activate for long-term preservation)"
[[ -f ".mcp.json" ]]                       && ok ".mcp.json configured"       || info ".mcp.json not present (copy from .mcp.json.example to add Linear/Sentry/Datadog)"
[[ -f "CLAUDE.md" ]]                       && ok "CLAUDE.md present"          || warn "CLAUDE.md missing — create it for project context"
[[ -f "roadmap.md" ]]                      && ok "roadmap.md present"         || info "roadmap.md not present — run /roadmap init to create"

echo ""

# ─── Summary ─────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════"
if [[ $ERRORS -eq 0 ]]; then
  echo -e "${GREEN}✅ Bootstrap complete — 0 errors${NC}"
  echo ""
  echo "Next steps:"
  echo "  1. git add -A && git commit -m 'chore: init sprint-system'"
  echo "  2. Add GitHub Secrets: ANTHROPIC_API_KEY (required)"
  echo "     Optional: SLACK_WEBHOOK_DOD, SLACK_WEBHOOK_ALERTS"
  echo "  3. Set up branch protection on main"
  echo "  4. Create GitHub labels: dod:pending dod:ac dod:milestone"
  echo "     dod:confirmed dod:rejected dod:needs-more"
  echo "  5. Run: claude → /roadmap init"
else
  echo -e "${RED}❌ Bootstrap found $ERRORS error(s) — fix above before proceeding${NC}"
fi
echo "════════════════════════════════════════════════════════"
echo ""

exit $ERRORS
