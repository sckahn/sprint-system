#!/usr/bin/env bash
# audit-attest.sh — create attestation snapshot for a seq range
# Usage: bash audit-attest.sh --from N --to N --label "sprint-7"
set -euo pipefail

FROM_SEQ="" TO_SEQ="" LABEL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) FROM_SEQ="$2"; shift ;;
    --to)   TO_SEQ="$2";   shift ;;
    --label) LABEL="$2";   shift ;;
    *) ;;
  esac
  shift
done

[[ -z "$FROM_SEQ" || -z "$TO_SEQ" || -z "$LABEL" ]] && {
  echo "Usage: audit-attest.sh --from N --to N --label LABEL" >&2; exit 1
}

ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel 2>/dev/null || echo ".")"
AUDIT_FILE="$ROOT/.audit/events.jsonl"
ATTEST_DIR="$ROOT/.audit/attestations"
mkdir -p "$ATTEST_DIR"

fingerprint=$(python3 - <<PYEOF
import json, hashlib

with open('${AUDIT_FILE}') as f:
    lines = [l.strip() for l in f if l.strip()]

subset = []
for line in lines:
    ev = json.loads(line)
    if ${FROM_SEQ} <= ev['seq'] <= ${TO_SEQ}:
        subset.append(ev)

if not subset:
    print('ERROR: no events in range')
    import sys; sys.exit(1)

combined = json.dumps(subset, sort_keys=True, separators=(',',':'))
fp = hashlib.sha256(combined.encode()).hexdigest()
print(fp)
PYEOF
)

ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
attest_file="$ATTEST_DIR/attest-${LABEL}-$(date -u +%Y%m%d%H%M%S).json"

python3 - <<PYEOF
import json
attest = {
    "label":       "${LABEL}",
    "from_seq":    ${FROM_SEQ},
    "to_seq":      ${TO_SEQ},
    "ts":          "${ts}",
    "fingerprint": "${fingerprint}",
    "attested_by": "$(git config user.email 2>/dev/null || echo unknown)"
}
with open('${attest_file}', 'w') as f:
    json.dump(attest, f, indent=2)
print(json.dumps(attest, indent=2))
PYEOF

echo "[audit-attest] saved: $attest_file" >&2

# Optional GPG sign
if command -v gpg &>/dev/null && [[ -n "$(gpg --list-secret-keys 2>/dev/null)" ]]; then
  gpg --detach-sign --armor "$attest_file" 2>/dev/null && \
    echo "[audit-attest] GPG signature created: ${attest_file}.asc" >&2 || true
fi
