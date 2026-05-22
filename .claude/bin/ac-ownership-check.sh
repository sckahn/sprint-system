#!/usr/bin/env bash
# ac-ownership-check.sh — query AC ownership + confirmation state from audit log
#
# Subcommands:
#   owner <ac_id>            Print the owner (or "" if unassigned). Exit 0 iff found.
#   verify <ac_id> <name>    Exit 0 iff <name> is the recorded owner of <ac_id>.
#   matrix <sprint>          Pretty-print AC × owner × status matrix.
#   sprint-ready <sprint>    Exit 0 iff every AC in sprint is confirmed; 1 otherwise.
#   list-mine <name> [sprint]  List AC IDs owned by <name> (optionally filter by sprint).
#
# Status precedence (latest event wins per AC):
#   confirmed > rejected > needs_more > pending
#
# Reads .audit/events.jsonl in repo root.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[ac-ownership-check] not a git repo" >&2; exit 2; }
AUDIT="$REPO_ROOT/.audit/events.jsonl"
[[ -f "$AUDIT" ]] || { echo "[ac-ownership-check] no audit log" >&2; exit 2; }

command -v jq >/dev/null 2>&1 || {
  echo "[ac-ownership-check] jq required" >&2; exit 2; }

# Latest owner for an AC (last ac.owner_assigned wins).
owner_of() {
  local ac="$1"
  jq -r --arg ac "$ac" '
    select(.event=="ac.owner_assigned" and .ac_id==$ac) | .owner
  ' "$AUDIT" | tail -1
}

# Latest status for an AC: confirmed | rejected | needs_more | pending.
status_of() {
  local ac="$1"
  local latest
  latest=$(jq -r --arg ac "$ac" '
    select(.ac_id==$ac and (.event=="ac.confirmed" or .event=="ac.rejected" or .event=="ac.needs_more")) | .event
  ' "$AUDIT" | tail -1)
  case "$latest" in
    ac.confirmed) echo "confirmed" ;;
    ac.rejected)  echo "rejected" ;;
    ac.needs_more) echo "needs_more" ;;
    *)             echo "pending" ;;
  esac
}

# Timestamp of the last status event for an AC (or "-").
status_ts_of() {
  local ac="$1"
  jq -r --arg ac "$ac" '
    select(.ac_id==$ac and (.event=="ac.confirmed" or .event=="ac.rejected" or .event=="ac.needs_more")) | .ts
  ' "$AUDIT" | tail -1
}

# All ACs that have an owner_assigned event in the given sprint.
acs_for_sprint() {
  local sprint="$1"
  jq -r --arg s "$sprint" '
    select(.event=="ac.owner_assigned" and (.sprint|tostring)==$s) | .ac_id
  ' "$AUDIT" | sort -u
}

case "${1:-}" in
  owner)
    [[ $# -ge 2 ]] || { echo "usage: $0 owner <ac_id>" >&2; exit 2; }
    o=$(owner_of "$2")
    [[ -n "$o" ]] && { echo "$o"; exit 0; } || { echo ""; exit 1; }
    ;;

  verify)
    [[ $# -ge 3 ]] || { echo "usage: $0 verify <ac_id> <name>" >&2; exit 2; }
    o=$(owner_of "$2")
    if [[ -z "$o" ]]; then
      echo "[ac-ownership-check] AC $2 has no recorded owner" >&2; exit 1
    fi
    # Case-insensitive substring match (owner string may include "<email>")
    if printf '%s' "$o" | grep -qiF "$3"; then
      exit 0
    else
      echo "[ac-ownership-check] AC $2 is owned by '$o', not '$3'" >&2
      exit 1
    fi
    ;;

  matrix)
    [[ $# -ge 2 ]] || { echo "usage: $0 matrix <sprint>" >&2; exit 2; }
    sprint="$2"
    acs=$(acs_for_sprint "$sprint")
    if [[ -z "$acs" ]]; then
      echo "No ACs registered for sprint $sprint"; exit 0
    fi
    printf '%-10s  %-25s  %-14s  %s\n' "AC ID" "Owner" "Status" "Updated"
    printf '%s\n' "──────────────────────────────────────────────────────────────────────"
    confirmed=0; total=0; rejected=0
    while IFS= read -r ac; do
      total=$((total+1))
      o=$(owner_of "$ac")
      s=$(status_of "$ac")
      t=$(status_ts_of "$ac")
      case "$s" in
        confirmed) icon="✅"; confirmed=$((confirmed+1)) ;;
        rejected)  icon="❌"; rejected=$((rejected+1)) ;;
        needs_more) icon="🔄" ;;
        *)         icon="⏳" ;;
      esac
      printf '%-10s  %-25s  %s %-12s  %s\n' "$ac" "${o:-?}" "$icon" "$s" "${t:--}"
    done <<<"$acs"
    echo
    echo "Confirmed: $confirmed / $total   Rejected: $rejected"
    if [[ $confirmed -eq $total && $rejected -eq 0 ]]; then
      echo "✅ Sprint $sprint ready — PM may run /sprint promote"
    else
      echo "⏳ Not ready for /sprint promote"
    fi
    ;;

  sprint-ready)
    [[ $# -ge 2 ]] || { echo "usage: $0 sprint-ready <sprint>" >&2; exit 2; }
    sprint="$2"
    acs=$(acs_for_sprint "$sprint")
    [[ -z "$acs" ]] && exit 1
    while IFS= read -r ac; do
      s=$(status_of "$ac")
      [[ "$s" != "confirmed" ]] && exit 1
    done <<<"$acs"
    exit 0
    ;;

  list-mine)
    [[ $# -ge 2 ]] || { echo "usage: $0 list-mine <name> [sprint]" >&2; exit 2; }
    name="$2"; sprint="${3:-}"
    jq -r --arg n "$name" --arg s "$sprint" '
      select(.event=="ac.owner_assigned")
      | select(($s=="") or ((.sprint|tostring)==$s))
      | select(.owner | ascii_downcase | contains($n|ascii_downcase))
      | "\(.ac_id)\tsprint=\(.sprint)\towner=\(.owner)"
    ' "$AUDIT" | sort -u
    ;;

  *)
    sed -n '2,15p' "$0"
    exit 2
    ;;
esac
