#!/usr/bin/env bash
# git-vibe-trailer.sh — prepare-commit-msg hook that records the human
# "driver" of a vibe-coding session into commit trailers.
#
# Behavior:
#   * Reads VIBE_DRIVER / VIBE_DRIVER_ROLE / VIBE_CO_DRIVER from the env
#     (loaded from .vibe-driver if present in repo root).
#   * Appends Vibe-Driver / Vibe-Driver-Role / Vibe-Co-Driver / Vibe-Session
#     / Vibe-Sprint trailers to the commit message (idempotent).
#   * If VIBE_DRIVER is unset AND VIBE_REQUIRE_DRIVER=1, blocks the commit.
#   * Idempotent: re-running on an already-trailered message is a no-op.
#
# Installation (per-repo):
#   ln -sf ../../.claude/bin/git-vibe-trailer.sh .git/hooks/prepare-commit-msg
# Or invoke from an existing prepare-commit-msg hook.
#
# Manual invocation (also works as a standalone CLI):
#   bash .claude/bin/git-vibe-trailer.sh <commit-msg-file> [<source>] [<sha>]

set -euo pipefail

MSG_FILE="${1:-}"
SOURCE="${2:-}"
# SHA="${3:-}"  # unused but accepted (git passes it for amends/squashes)

if [[ -z "$MSG_FILE" || ! -f "$MSG_FILE" ]]; then
  echo "[vibe-trailer] missing commit message file" >&2
  exit 1
fi

# Don't add trailers for merge/squash/fixup commits — they aren't authored work.
case "$SOURCE" in
  merge|squash) exit 0 ;;
esac

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0

# Load .vibe-driver if present (key=value lines; comments ok).
# Repo-level overrides user-level.
for dotfile in "$HOME/.vibe-driver" "$REPO_ROOT/.vibe-driver"; do
  if [[ -f "$dotfile" ]]; then
    # shellcheck disable=SC1090
    set -a; . "$dotfile"; set +a
  fi
done

DRIVER="${VIBE_DRIVER:-}"
ROLE="${VIBE_DRIVER_ROLE:-}"
CODRIVER="${VIBE_CO_DRIVER:-}"
REQUIRE="${VIBE_REQUIRE_DRIVER:-0}"

if [[ -z "$DRIVER" ]]; then
  if [[ "$REQUIRE" = "1" ]]; then
    echo "[vibe-trailer] BLOCKED — VIBE_DRIVER not set." >&2
    echo "  Fix one of:" >&2
    echo "    export VIBE_DRIVER='Your Name <you@example.com>'" >&2
    echo "    echo \"VIBE_DRIVER='Your Name <you@example.com>'\" > $REPO_ROOT/.vibe-driver" >&2
    echo "    bash .claude/bin/bootstrap.sh   # interactive setup" >&2
    exit 1
  fi
  DRIVER="unknown <unknown@local>"
fi

# Already trailered? Idempotent exit.
if grep -q "^Vibe-Driver:" "$MSG_FILE"; then
  exit 0
fi

# Resolve session + sprint context.
SESSION="${CLAUDE_SESSION_ID:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
SPRINT="${VIBE_SPRINT:-}"
if [[ -z "$SPRINT" && -f "$REPO_ROOT/roadmap.md" ]]; then
  SPRINT=$(grep -m1 -iE 'current[[:space:]]+sprint[[:space:]]*:' "$REPO_ROOT/roadmap.md" \
            | awk -F: '{print $2}' | tr -d ' ' || true)
fi
SPRINT="${SPRINT:-unknown}"
MODEL="${ANTHROPIC_MODEL:-${CLAUDE_MODEL:-unknown}}"

# Append trailers (preserve a blank line above the trailer block).
REVIEWER="${VIBE_REVIEWER:-}"
AC="${VIBE_AC:-}"
COMMITTER_NAME=$(git config user.name  2>/dev/null || echo "")
COMMITTER_MAIL=$(git config user.email 2>/dev/null || echo "")
COMMITTER="${COMMITTER_NAME:+$COMMITTER_NAME }<${COMMITTER_MAIL:-unknown@local}>"

{
  cat "$MSG_FILE"
  # Ensure trailing newline + blank separator
  tail -c1 "$MSG_FILE" | od -An -c | grep -q '\\n' || echo
  echo
  echo "Vibe-Driver: $DRIVER"
  [[ -n "$ROLE" ]]      && echo "Vibe-Driver-Role: $ROLE"
  [[ -n "$CODRIVER" ]]  && echo "Vibe-Co-Driver: $CODRIVER"
  # Only emit Reviewer/Committer if distinct from Driver (avoid noise on solo runs)
  if [[ -n "$REVIEWER" && "$REVIEWER" != "$DRIVER" ]]; then
    echo "Vibe-Reviewer: $REVIEWER"
  fi
  if [[ "$COMMITTER" != "$DRIVER" ]]; then
    echo "Vibe-Committer: $COMMITTER"
  fi
  [[ -n "$AC" ]]        && echo "Vibe-AC: $AC"
  echo "Vibe-Session: $SESSION"
  echo "Vibe-Sprint: $SPRINT"
  echo "Vibe-Model: $MODEL"
} > "${MSG_FILE}.tmp"

mv "${MSG_FILE}.tmp" "$MSG_FILE"
exit 0
