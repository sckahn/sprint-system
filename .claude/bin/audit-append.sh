#!/usr/bin/env bash
# audit-append.sh — append a tamper-evident event to the hash chain
# Usage: bash audit-append.sh [--git-sync] '<json-payload>'
#
# Flags:
#   --git-sync   After appending, commit the audit log and push to the
#                current branch's upstream. On non-fast-forward, fetch +
#                rebase + REPLAY the new event on top (rebuilding seq +
#                prev_hash + this_hash) and retry. Up to 8 attempts.
#                Use when multiple humans append on the same shared branch.
#
# Reserved fields (seq, ts, prev_hash, this_hash) are injected automatically.
set -euo pipefail

GIT_SYNC=0
if [[ "${1:-}" == "--git-sync" ]]; then
  GIT_SYNC=1
  shift
fi

REPO_ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel 2>/dev/null || echo ".")"
AUDIT_FILE="$REPO_ROOT/.audit/events.jsonl"
LOCK_DIR="${AUDIT_FILE}.lock.d"

# Cross-platform mutex: mkdir is atomic on POSIX + macOS + Linux
acquire_lock() {
  local retries=0
  while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    retries=$((retries + 1))
    if [[ $retries -gt 50 ]]; then
      echo "[audit-append] ERROR: could not acquire lock after 5s" >&2; exit 1
    fi
    sleep 0.1
  done
}
release_lock() { rmdir "$LOCK_DIR" 2>/dev/null || true; }
trap release_lock EXIT

payload="${1:-}"
if [[ -z "$payload" ]]; then
  echo "[audit-append] ERROR: payload required" >&2; exit 1
fi

# Reject reserved field injection
for reserved in seq ts prev_hash this_hash; do
  if echo "$payload" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if '$reserved' not in d else 1)" 2>/dev/null; then
    :
  else
    echo "[audit-append] ERROR: reserved field '$reserved' must not be set by caller" >&2; exit 1
  fi
done

acquire_lock

  mkdir -p "$(dirname "$AUDIT_FILE")"

  # Determine seq and prev_hash
  if [[ -f "$AUDIT_FILE" ]] && [[ -s "$AUDIT_FILE" ]]; then
    last_line=$(tail -1 "$AUDIT_FILE")
    prev_hash=$(echo "$last_line" | python3 -c "import sys,json; print(json.load(sys.stdin)['this_hash'])")
    last_seq=$(echo "$last_line"  | python3 -c "import sys,json; print(json.load(sys.stdin)['seq'])")
    seq=$((last_seq + 1))
  else
    prev_hash="0000000000000000000000000000000000000000000000000000000000000000"
    seq=1
  fi

  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  # Build canonical event (sorted keys deterministically)
  event=$(python3 - <<PYEOF
import json, sys
payload = json.loads('''${payload}''')
payload['seq']       = ${seq}
payload['ts']        = '${ts}'
payload['prev_hash'] = '${prev_hash}'
# Canonical: sort keys, no whitespace
canonical = json.dumps(payload, sort_keys=True, separators=(',',':'))
print(canonical)
PYEOF
)

  # Compute this_hash
  this_hash=$(echo -n "$event" | sha256sum | awk '{print $1}')

  # Final event with this_hash appended
  final=$(python3 - <<PYEOF
import json
event = json.loads('${event}')
event['this_hash'] = '${this_hash}'
print(json.dumps(event, sort_keys=True, separators=(',',':')))
PYEOF
)

  echo "$final" >> "$AUDIT_FILE"
  echo "[audit-append] seq=${seq} event_type=$(echo "$payload" | python3 -c "import sys,json; print(json.load(sys.stdin).get('event','?'))")" >&2
  echo "$final"

release_lock

# ─── optional: sync to shared branch ──────────────────────────────────
if [[ $GIT_SYNC -eq 1 ]]; then
  cd "$REPO_ROOT"
  BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "")
  if [[ -z "$BRANCH" ]] || [[ "$BRANCH" == "HEAD" ]]; then
    echo "[audit-append] --git-sync: detached HEAD, skipping push" >&2
    exit 0
  fi

  attempt=0; max_attempts=8
  while (( attempt < max_attempts )); do
    attempt=$((attempt+1))

    git add "$AUDIT_FILE"
    if ! git diff --cached --quiet "$AUDIT_FILE"; then
      EVT_TYPE=$(echo "$payload" | python3 -c "import sys,json; print(json.load(sys.stdin).get('event','?'))")
      git -c commit.gpgsign=false commit -m "audit: ${EVT_TYPE} (seq=$(tail -1 "$AUDIT_FILE" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['seq'])"))" >/dev/null
    fi

    if git push origin "$BRANCH" 2>/tmp/audit-push-err; then
      echo "[audit-append] --git-sync: pushed to origin/$BRANCH (attempt $attempt)" >&2
      exit 0
    fi

    if ! grep -qE "non-fast-forward|fetch first|rejected" /tmp/audit-push-err; then
      echo "[audit-append] --git-sync: push failed with non-recoverable error:" >&2
      cat /tmp/audit-push-err >&2
      exit 1
    fi

    echo "[audit-append] --git-sync: push race detected, replaying event (attempt $attempt)" >&2

    # Extract the original user payload (strip injected fields) from the last line, then undo.
    USER_PAYLOAD=$(tail -1 "$AUDIT_FILE" | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
for k in ('seq','ts','prev_hash','this_hash'):
    d.pop(k, None)
print(json.dumps(d, separators=(',',':')))
")
    # Rewind our local commit + working change
    git reset --hard "HEAD~1" >/dev/null 2>&1 || git checkout -- "$AUDIT_FILE"
    git fetch origin "$BRANCH" --quiet
    git rebase "origin/$BRANCH" --quiet || { echo "[audit-append] --git-sync: rebase failed, aborting" >&2; git rebase --abort >/dev/null 2>&1 || true; exit 1; }

    # Replay: re-run ourselves WITHOUT --git-sync, then loop to push.
    bash "$0" "$USER_PAYLOAD" >/dev/null
  done

  echo "[audit-append] --git-sync: exhausted $max_attempts attempts, giving up" >&2
  exit 1
fi
