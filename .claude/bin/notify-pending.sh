#!/usr/bin/env bash
# notify-pending.sh — summarize pending DoD confirmations
# Usage: notify-pending.sh [--slack] [--post] [--json]
set -euo pipefail

MODE="text"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --slack) MODE="slack" ;;
    --post)  MODE="post"  ;;
    --json)  MODE="json"  ;;
    *) ;;
  esac
  shift
done

ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel 2>/dev/null || echo ".")"
AUDIT_FILE="$ROOT/.audit/events.jsonl"

summary=$(python3 - <<PYEOF
import json

pending = {}
confirmed = set()

try:
    with open('${AUDIT_FILE}') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            ev = json.loads(line)
            et = ev.get('event','')
            if et == 'ac.evidence_ready':
                pending[ev.get('ac_id','')] = ev
            elif et == 'milestone.evidence_ready':
                pending[f"MILESTONE:{ev.get('milestone_id','')}"] = ev
            elif et in ('ac.confirmed','ac.rejected','milestone.completed'):
                key = ev.get('ac_id') or f"MILESTONE:{ev.get('milestone_id','')}"
                confirmed.add(key)
except FileNotFoundError:
    pass

items = [v for k,v in pending.items() if k not in confirmed]

print(json.dumps({
    "count": len(items),
    "items": items
}))
PYEOF
)

count=$(echo "$summary" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])")

if [[ "$MODE" == "json" ]]; then
  echo "$summary"; exit 0
fi

if [[ "$MODE" == "text" ]]; then
  if [[ "$count" == "0" ]]; then
    echo "✓ No pending DoD confirmations"; exit 0
  fi
  echo "🚦 ${count} DoD confirmation(s) pending:"
  echo "$summary" | python3 -c "
import sys,json
d = json.load(sys.stdin)
for item in d['items']:
    print(f\"  • {item.get('ac_id', item.get('milestone_id','?'))} — sprint {item.get('sprint','?')}\")
"
  echo ""
  echo "Run: claude > /dod review"
  exit 0
fi

if [[ "$MODE" == "slack" || "$MODE" == "post" ]]; then
  if [[ "$count" == "0" ]]; then
    [[ "$MODE" == "post" ]] && exit 0
    echo '{"text":"✓ No pending DoD confirmations"}'; exit 0
  fi

  items_text=$(echo "$summary" | python3 -c "
import sys,json
d = json.load(sys.stdin)
lines = []
for item in d['items']:
    ac = item.get('ac_id', item.get('milestone_id','?'))
    sprint = item.get('sprint','?')
    lines.append(f'• {ac}  (sprint {sprint})')
print('\n'.join(lines))
")

  payload=$(python3 - <<PYEOF
import json
text = """🚦 *${count} DoD confirmation(s) pending*

${items_text}

Run \`claude\` → \`/dod review\` to process."""
block = {
    "blocks": [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "sprint-system · $(date -u +%Y-%m-%dT%H:%M:%SZ)"}]}
    ]
}
print(json.dumps(block))
PYEOF
)

  if [[ "$MODE" == "post" ]]; then
    WEBHOOK="${SLACK_WEBHOOK_DOD:-}"
    [[ -z "$WEBHOOK" ]] && { echo "[notify] SKIP: SLACK_WEBHOOK_DOD not set" >&2; exit 0; }
    curl -s -X POST -H 'Content-type: application/json' --data "$payload" "$WEBHOOK"
    echo ""
  else
    echo "$payload"
  fi
fi
