#!/usr/bin/env bash
# install-global.sh — install sprint-system globally so /start works from any directory.
#
# Run ONCE from inside the sprint-system root:
#   bash .claude/bin/install-global.sh
#
# Effect:
#   - Records this repo's path in ~/.claude/sprint-system-root
#   - Symlinks agents/commands/skills into ~/.claude/
#   - Adds a shell function `sprint-init` for first-time project setup
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC}  $1"; }
info() { echo -e "${BLUE}→${NC} $1"; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Sanity check — must be run from a sprint-system repo
[[ -f "$ROOT/.claude/commands/start.md" ]] || {
  echo "ERROR: must run from a sprint-system root (no .claude/commands/start.md found)" >&2
  exit 1
}

mkdir -p ~/.claude/{agents,commands,skills,bin}

# Record sprint-system root
echo "$ROOT" > ~/.claude/sprint-system-root
ok "recorded sprint-system root: $ROOT"

# Symlink agents (skip if exists)
for f in "$ROOT/.claude/agents"/*.md; do
  name="$(basename "$f")"
  ln -sf "$f" ~/.claude/agents/"$name"
done
ok "symlinked $(ls "$ROOT/.claude/agents"/*.md | wc -l | tr -d ' ') agents"

# Symlink commands
for f in "$ROOT/.claude/commands"/*.md; do
  name="$(basename "$f")"
  ln -sf "$f" ~/.claude/commands/"$name"
done
ok "symlinked $(ls "$ROOT/.claude/commands"/*.md | wc -l | tr -d ' ') commands"

# Symlink skills (directory-level)
for d in "$ROOT/.claude/skills"/*/; do
  name="$(basename "$d")"
  ln -sf "$d" ~/.claude/skills/"$name"
done
ok "symlinked $(ls -d "$ROOT/.claude/skills"/*/ | wc -l | tr -d ' ') skills"

# Symlink bin scripts (so audit-append etc. callable from anywhere)
for f in "$ROOT/.claude/bin"/*.sh; do
  name="$(basename "$f")"
  ln -sf "$f" ~/.claude/bin/"$name"
done
ok "symlinked $(ls "$ROOT/.claude/bin"/*.sh | wc -l | tr -d ' ') bin scripts"

echo ""
ok "Global install complete."
echo ""
info "From any directory:"
echo "    cd ~/some-new-project"
echo "    claude          # /start auto-bootstraps the project on first use"
echo ""
info "To verify in claude:"
echo "    /start \"한 문장으로 만들고 싶은 것\""
echo ""
info "Sprint-system root will be re-used from: ~/.claude/sprint-system-root"
