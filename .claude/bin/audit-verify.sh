#!/usr/bin/env bash
# audit-verify.sh — verify the entire audit hash chain
# Usage: bash audit-verify.sh [--quiet] [--from-seq N]
# Exit 0 = OK, Exit 1 = tampered/broken
set -euo pipefail

QUIET=false
FROM_SEQ=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet) QUIET=true ;;
    --from-seq) FROM_SEQ="$2"; shift ;;
    *) ;;
  esac
  shift
done

AUDIT_FILE="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel 2>/dev/null || echo ".")/.audit/events.jsonl"

if [[ ! -f "$AUDIT_FILE" ]] || [[ ! -s "$AUDIT_FILE" ]]; then
  [[ "$QUIET" == false ]] && echo "WARN: No audit log found at $AUDIT_FILE"
  exit 0
fi

# Pass variables via environment to avoid heredoc expansion conflicts
AUDIT_FILE="$AUDIT_FILE" FROM_SEQ="$FROM_SEQ" python3 - <<'PYEOF'
import json, hashlib, sys, os

audit_file = os.environ['AUDIT_FILE']
from_seq   = int(os.environ['FROM_SEQ'])

events = []
with open(audit_file) as f:
    for line in f:
        line = line.strip()
        if line:
            events.append(json.loads(line))

prev_hash = '0' * 64
errors = []

for ev in events:
    seq = ev['seq']
    if seq < from_seq:
        prev_hash = ev['this_hash']
        continue

    stored_this = ev.pop('this_hash')
    stored_prev = ev.get('prev_hash')

    if stored_prev != prev_hash:
        errors.append(f'seq={seq}: prev_hash mismatch (expected {prev_hash[:8]}... got {stored_prev[:8]}...)')

    canonical = json.dumps(ev, sort_keys=True, separators=(',',':'))
    computed  = hashlib.sha256(canonical.encode()).hexdigest()
    if computed != stored_this:
        errors.append(f'seq={seq}: hash mismatch (stored {stored_this[:8]}... computed {computed[:8]}...)')

    ev['this_hash'] = stored_this
    prev_hash = stored_this

if errors:
    for e in errors:
        print(f'FAIL: {e}')
    sys.exit(1)
else:
    print(f'OK: {len(events)} events verified, head={prev_hash[:16]}...')
    sys.exit(0)
PYEOF

exit_code=$?
[[ "$QUIET" == true && $exit_code -eq 0 ]] && true
exit $exit_code
