#!/usr/bin/env bash
# gh-process-gate.sh — process /yes /edit /no /close /halt on gate:roadmap / gate:milestone / gate:project issues
# Called by start-handler.yml with env: ISSUE_NUMBER, COMMENT_BODY, COMMENT_AUTHOR, ISSUE_LABELS
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel 2>/dev/null || echo ".")"
cd "$ROOT"

ISSUE_NUMBER="${ISSUE_NUMBER:?required}"
COMMENT_BODY="${COMMENT_BODY:?required}"
COMMENT_AUTHOR="${COMMENT_AUTHOR:?required}"
ISSUE_LABELS="${ISSUE_LABELS:-[]}"

# Parse command + rest
cmd=$(echo "$COMMENT_BODY" | head -1 | awk '{print $1}')
rest=$(echo "$COMMENT_BODY" | head -1 | cut -d' ' -f2- || true)
[[ "$cmd" == "$rest" ]] && rest=""

# Detect which gate (priority: project > milestone > roadmap)
gate=""
for g in project milestone roadmap; do
  if echo "$ISSUE_LABELS" | python3 -c "import sys,json; ls=json.load(sys.stdin); sys.exit(0 if any(l['name']=='gate:$g' for l in ls) else 1)" 2>/dev/null; then
    gate="$g"; break
  fi
done

[[ -z "$gate" ]] && { echo "[gh-gate] No gate label on issue #$ISSUE_NUMBER"; exit 0; }

log()      { echo "[gh-gate] $*" >&2; }
respond()  { gh issue comment "$ISSUE_NUMBER" --body "$1"; }
audit()    { bash "$ROOT/.claude/bin/audit-append.sh" "$1" >/dev/null; }
move_lbl() { gh issue edit "$ISSUE_NUMBER" --add-label "$1" --remove-label "$2" 2>/dev/null || true; }
close_iss(){ gh issue close "$ISSUE_NUMBER" --comment "$1" 2>/dev/null || true; }
claude_h() { CLAUDE_HEADLESS=1 claude --headless -p "$1" 2>&1 | tee -a /tmp/start-output.txt; }

log "Gate=$gate cmd=$cmd author=$COMMENT_AUTHOR"

audit "{\"event\":\"gate.comment_received\",\"gate\":\"$gate\",\"command\":\"$cmd\",\"author\":\"$COMMENT_AUTHOR\",\"issue\":$ISSUE_NUMBER}"

# ─── ROADMAP GATE ──────────────────────────────────────────────
if [[ "$gate" == "roadmap" ]]; then
  case "$cmd" in
    /yes)
      audit "{\"event\":\"roadmap.approved_by_human\",\"approver\":\"$COMMENT_AUTHOR\",\"via\":\"github\",\"issue\":$ISSUE_NUMBER}"
      respond "✅ 로드맵 승인됨 by @$COMMENT_AUTHOR. 첫 스프린트를 시작합니다. 각 AC는 자동으로 생성될 \`dod:ac\` 이슈에서 \`/confirm\`으로 승인하세요."
      move_lbl "gate:active" "gate:roadmap"
      claude_h "/sprint" || true
      ;;
    /edit)
      [[ -z "$rest" ]] && { respond "❌ \`/edit\` 뒤에 수정 사항을 적어주세요. 예: \`/edit 마일스톤 2 빼고 인증 추가\`"; exit 0; }
      audit "{\"event\":\"roadmap.edit_requested\",\"requester\":\"$COMMENT_AUTHOR\",\"diff\":\"$(echo "$rest" | sed 's/"/\\"/g')\"}"
      respond "🔄 수정 요청 접수: \`$rest\`\n\n로드맵 재작성 중..."
      claude_h "/start --issue=$ISSUE_NUMBER --headless --edit=\"$rest\"" || true
      ;;
    /no)
      audit "{\"event\":\"project.cancelled\",\"cancelled_by\":\"$COMMENT_AUTHOR\",\"reason\":\"$rest\",\"stage\":\"roadmap\"}"
      respond "❌ 프로젝트 취소됨 by @$COMMENT_AUTHOR."
      move_lbl "gate:cancelled" "gate:roadmap"
      close_iss "Cancelled."
      ;;
    *)
      respond "🤔 \`$cmd\`는 roadmap 게이트에서 인식되지 않습니다. 사용 가능: \`/yes\` · \`/edit ...\` · \`/no\`"
      ;;
  esac
  exit 0
fi

# ─── MILESTONE GATE ────────────────────────────────────────────
if [[ "$gate" == "milestone" ]]; then
  # Extract milestone ID from issue title (e.g. "Milestone M2 sign-off")
  milestone_id=$(gh issue view "$ISSUE_NUMBER" --json title --jq '.title' | grep -oE 'M[0-9]+' | head -1)
  case "$cmd" in
    /yes)
      audit "{\"event\":\"milestone.completed\",\"milestone_id\":\"$milestone_id\",\"confirmed_by\":\"$COMMENT_AUTHOR\",\"via\":\"github\",\"issue\":$ISSUE_NUMBER}"
      respond "🏁 마일스톤 $milestone_id 사인오프됨 by @$COMMENT_AUTHOR. 다음 마일스톤 진행."
      move_lbl "gate:done" "gate:milestone"
      close_iss "Milestone sign-off complete."
      # Continue to next milestone in background
      claude_h "/sprint" || true
      ;;
    /halt)
      audit "{\"event\":\"project.paused\",\"paused_by\":\"$COMMENT_AUTHOR\",\"stage\":\"milestone:$milestone_id\",\"reason\":\"$rest\"}"
      respond "⏸ 프로젝트 일시 정지됨 by @$COMMENT_AUTHOR. 재개하려면 새 이슈를 만드세요."
      ;;
    *)
      respond "🤔 사용 가능: \`/yes\` (마일스톤 승인) · \`/halt 사유\` (정지)"
      ;;
  esac
  exit 0
fi

# ─── PROJECT GATE ──────────────────────────────────────────────
if [[ "$gate" == "project" ]]; then
  case "$cmd" in
    /close)
      attestation=$(bash "$ROOT/.claude/bin/audit-attest.sh" 2>/dev/null || echo "n/a")
      audit "{\"event\":\"roadmap.project_closed\",\"closed_by\":\"$COMMENT_AUTHOR\",\"via\":\"github\",\"attestation\":\"$attestation\"}"
      respond "🎉 **프로젝트 종료** by @$COMMENT_AUTHOR\n\n최종 감사 attestation:\n\`\`\`\n$attestation\n\`\`\`"
      move_lbl "gate:closed" "gate:project"
      close_iss "Project closed."
      ;;
    /no)
      respond "🔄 추가 작업이 필요하신가요? 새 이슈로 마일스톤을 추가하거나 \`/edit\`으로 알려주세요."
      ;;
    *)
      respond "🤔 사용 가능: \`/close\` (프로젝트 종료) · \`/no\` (추가 작업)"
      ;;
  esac
  exit 0
fi

log "Unhandled gate: $gate"
