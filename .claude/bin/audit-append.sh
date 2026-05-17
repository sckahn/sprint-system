#!/usr/bin/env bash
# audit-append.sh — append a tamper-evident event to the hash chain
# Usage: bash audit-append.sh '<json-payload>'
# Reserved fields (seq, ts, prev_hash, this_hash) are injected automatically.
set -euo pipefail

AUDIT_FILE="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel 2>/dev/null || echo ".")/.audit/events.jsonl"
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
