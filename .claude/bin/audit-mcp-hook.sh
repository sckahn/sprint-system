#!/usr/bin/env bash
# audit-mcp-hook.sh — log every MCP tool call to the audit chain
# Configure in .mcp.json as a hook: { "hook": "bash .claude/bin/audit-mcp-hook.sh" }
# Receives JSON on stdin: { "tool": "...", "server": "...", "input": {...} }
set -euo pipefail

input=$(cat)
tool=$(echo "$input"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool','unknown'))")
server=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('server','unknown'))")

# Redact sensitive fields
sanitized=$(echo "$input" | python3 - <<'PYEOF'
import sys, json, re
d = json.load(sys.stdin)
inp = d.get('input', {})
SENSITIVE = {'token','secret','password','key','api_key','auth','credentials'}
def redact(obj):
    if isinstance(obj, dict):
        return {k: '[REDACTED]' if any(s in k.lower() for s in SENSITIVE) else redact(v)
                for k, v in obj.items()}
    return obj
d['input'] = redact(inp)
print(json.dumps(d, separators=(',',':')))
PYEOF
)

payload="{\"event\":\"mcp.tool_called\",\"tool\":\"${tool}\",\"server\":\"${server}\",\"sanitized_input\":$(echo "$sanitized" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('input',{})))")}"

bash "$(dirname "$0")/audit-append.sh" "$payload" >/dev/null 2>&1 || true
