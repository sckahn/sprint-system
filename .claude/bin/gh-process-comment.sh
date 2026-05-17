#!/usr/bin/env bash
# gh-process-comment.sh — process /confirm, /reject, /needs-more on DoD issues
# Called by dod-handler.yml with env: ISSUE_NUMBER, COMMENT_BODY, COMMENT_AUTHOR
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel 2>/dev/null || echo ".")"

ISSUE_NUMBER="${ISSUE_NUMBER:-}"
COMMENT_BODY="${COMMENT_BODY:-}"
COMMENT_AUTHOR="${COMMENT_AUTHOR:-}"

[[ -z "$ISSUE_NUMBER" ]] && { echo "[gh-process] ERROR: ISSUE_NUMBER required" >&2; exit 1; }

# Parse command from comment
cmd=$(echo "$COMMENT_BODY" | head -1 | awk '{print $1}')
rest=$(echo "$COMMENT_BODY" | head -1 | cut -d' ' -f2-)

case "$cmd" in
  /confirm|/yes)    action="confirmed"; reason="${rest:-approved}" ;;
  /reject|/no)      action="rejected";  reason="$rest" ;;
  /needs-more)      action="needs_more"; reason="$rest" ;;
  *)
    echo "[gh-process] Not a DoD command: $cmd" >&2; exit 0 ;;
esac

[[ "$action" == "rejected" || "$action" == "needs_more" ]] && [[ -z "$reason" ]] && {
  gh issue comment "$ISSUE_NUMBER" --body "❌ **Reason required** for \`${cmd}\`. Please add a description."
  exit 0
}

# Extract AC ID from issue title
ac_id=$(gh issue view "$ISSUE_NUMBER" --json title --jq '.title' | grep -oE 'AC-[0-9]+\.[0-9]+' | head -1)
[[ -z "$ac_id" ]] && { echo "[gh-process] Could not extract AC ID" >&2; exit 1; }

# Check evidence_ready event exists
has_evidence=$(python3 - <<PYEOF
import json
found = False
try:
    with open('${ROOT}/.audit/events.jsonl') as f:
        for line in f:
            ev = json.loads(line.strip())
            if ev.get('event') == 'ac.evidence_ready' and ev.get('ac_id') == '${ac_id}':
                found = True; break
except: pass
print('yes' if found else 'no')
PYEOF
)

if [[ "$has_evidence" != "yes" ]]; then
  gh issue comment "$ISSUE_NUMBER" --body "⚠️ Cannot confirm **${ac_id}**: no \`ac.evidence_ready\` event found in audit log. Evidence must be recorded before confirmation."
  exit 0
fi

# Check not already processed
already=$(python3 - <<PYEOF
import json
try:
    with open('${ROOT}/.audit/events.jsonl') as f:
        for line in f:
            ev = json.loads(line.strip())
            if ev.get('event') in ('ac.confirmed','ac.rejected') and ev.get('ac_id') == '${ac_id}':
                print('yes'); exit()
except: pass
print('no')
PYEOF
)

if [[ "$already" == "yes" ]]; then
  gh issue comment "$ISSUE_NUMBER" --body "ℹ️ **${ac_id}** has already been processed. Check the audit log for details."
  exit 0
fi

# Verify chain integrity
bash "$ROOT/.claude/bin/audit-verify.sh" --quiet || {
  gh issue comment "$ISSUE_NUMBER" --body "🔴 **Chain verification failed** — audit log integrity error. Cannot process confirmation."
  exit 1
}

# Append audit event
github_url="https://github.com/${GITHUB_REPOSITORY:-unknown}/issues/${ISSUE_NUMBER}#issuecomment-$(date +%s)"
payload="{\"event\":\"ac.${action}\",\"ac_id\":\"${ac_id}\",\"approver\":\"${COMMENT_AUTHOR}\",\"github_username\":\"${COMMENT_AUTHOR}\",\"via\":\"github_issue_comment\",\"github_issue\":\"${ISSUE_NUMBER}\",\"github_comment\":\"${github_url}\",\"reason\":\"${reason}\"}"

bash "$ROOT/.claude/bin/audit-append.sh" "$payload" >/dev/null

# Git commit + push
cd "$ROOT"
git add .audit/events.jsonl
git commit -m "audit: ${action} ${ac_id} via GitHub Issue #${ISSUE_NUMBER} by @${COMMENT_AUTHOR}" --no-verify 2>/dev/null || true
git push 2>/dev/null || true

# Respond on issue
case "$action" in
  confirmed)
    gh issue comment "$ISSUE_NUMBER" --body "✅ **${ac_id} confirmed** by @${COMMENT_AUTHOR}\n\n> ${reason}\n\n_Audit event recorded in hash chain._"
    gh issue close "$ISSUE_NUMBER" --comment "DoD confirmed." 2>/dev/null || true
    gh issue edit "$ISSUE_NUMBER" --add-label "dod:confirmed" --remove-label "dod:pending" 2>/dev/null || true
    ;;
  rejected)
    gh issue comment "$ISSUE_NUMBER" --body "❌ **${ac_id} rejected** by @${COMMENT_AUTHOR}\n\n**Reason**: ${reason}\n\n_Returned to backlog for next sprint._"
    gh issue edit "$ISSUE_NUMBER" --add-label "dod:rejected" --remove-label "dod:pending" 2>/dev/null || true
    ;;
  needs_more)
    gh issue comment "$ISSUE_NUMBER" --body "🔄 **${ac_id} needs more work** — @${COMMENT_AUTHOR}\n\n**Required**: ${reason}\n\n_Issue stays open until evidence is updated._"
    gh issue edit "$ISSUE_NUMBER" --add-label "dod:needs-more" --remove-label "dod:pending" 2>/dev/null || true
    ;;
esac

echo "[gh-process] Done: ${ac_id} → ${action}" >&2
