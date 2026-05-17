#!/usr/bin/env bash
# start-rc.sh — start Claude Code Remote Control session with audit logging
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel 2>/dev/null || echo ".")"
HOST="$(hostname -s)"
PROJECT_DIR="$ROOT"
GIT_REPO="$(git -C "$ROOT" remote get-url origin 2>/dev/null || echo 'local')"

echo "[start-rc] Starting Remote Control session..." >&2

bash "$ROOT/.claude/bin/audit-append.sh" \
  "{\"event\":\"session.rc_started\",\"host\":\"${HOST}\",\"project_dir\":\"${PROJECT_DIR}\",\"git_repo\":\"${GIT_REPO}\"}" \
  >/dev/null

RC_START_TS=$(date +%s)

cleanup() {
  EXIT_CODE=$?
  DURATION=$(( $(date +%s) - RC_START_TS ))
  bash "$ROOT/.claude/bin/audit-append.sh" \
    "{\"event\":\"session.rc_ended\",\"host\":\"${HOST}\",\"duration_seconds\":${DURATION},\"exit_code\":${EXIT_CODE}}" \
    >/dev/null 2>&1 || true
  echo "" >&2
  echo "[start-rc] RC session ended (${DURATION}s)" >&2
}
trap cleanup EXIT

echo "[start-rc] Audit log: session.rc_started recorded" >&2
echo "[start-rc] AC/Story confirmations via RC are allowed." >&2
echo "[start-rc] Milestone/Project confirmations require GitHub PR (4-eyes)." >&2
echo "" >&2

# Launch claude with RC flag
claude remote-control "$@"
