#!/usr/bin/env bash
# liveness-check.sh — verify that symbols claimed by agents actually exist
# and are referenced (not dead code).
#
# Reads claims from the audit log (events of type `code.claim`) and for each:
#   { "event":"code.claim", "agent":"...", "symbol":"foo", "file":"src/x.py",
#     "kind":"function|class|endpoint", "ac_id":"..." }
# verifies:
#   1. file exists
#   2. symbol is defined in file (kind-aware grep)
#   3. symbol is referenced at least once outside its own definition
#      (skipped if kind=endpoint, since callers may be external)
#
# Usage:
#   bash .claude/bin/liveness-check.sh [--since-seq <N>] [--ac <ac_id>] [--json]
#
# Exit 0 if all claims pass, 1 if any fail, 2 on invocation error.

set -euo pipefail

SINCE_SEQ=0
AC_FILTER=""
EMIT_JSON=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --since-seq) SINCE_SEQ="$2"; shift 2 ;;
    --ac) AC_FILTER="$2"; shift 2 ;;
    --json) EMIT_JSON=1; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "[liveness-check] unknown arg: $1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[liveness-check] not a git repo" >&2; exit 2; }
cd "$REPO_ROOT"

AUDIT_FILE=".audit/events.jsonl"
[[ -f "$AUDIT_FILE" ]] || {
  echo "[liveness-check] no audit log at $AUDIT_FILE — nothing to verify"
  exit 0
}

command -v jq >/dev/null 2>&1 || {
  echo "[liveness-check] jq required (brew install jq)" >&2; exit 2; }

# Extract code.claim events. Filter by seq and (optionally) ac_id.
JQ_FILTER='select(.event=="code.claim")'
if [[ -n "$AC_FILTER" ]]; then
  JQ_FILTER="$JQ_FILTER | select(.ac_id==\"$AC_FILTER\")"
fi
if [[ "$SINCE_SEQ" -gt 0 ]]; then
  JQ_FILTER="$JQ_FILTER | select(.seq >= $SINCE_SEQ)"
fi

CLAIMS=$(jq -c "$JQ_FILTER" "$AUDIT_FILE" 2>/dev/null || true)

if [[ -z "$CLAIMS" ]]; then
  [[ $EMIT_JSON -eq 1 ]] && echo '{"status":"ok","checked":0,"failures":[]}' \
    || echo "[liveness-check] no code.claim events found — ok"
  exit 0
fi

FAIL_FILE=$(mktemp); trap 'rm -f "$FAIL_FILE"' EXIT
checked=0

# Definition patterns per kind/language (ext-based heuristic)
def_pattern() {
  local sym="$1" file="$2"
  # Escape regex metas in symbol
  local s
  s=$(printf '%s' "$sym" | sed 's/[][\/.^$*]/\\&/g')
  case "${file##*.}" in
    py)   printf '^[[:space:]]*(def|class)[[:space:]]+%s[[:space:]]*[(:]' "$s" ;;
    js|jsx|ts|tsx)
      printf '(function[[:space:]]+%s[[:space:]]*\(|(const|let|var)[[:space:]]+%s[[:space:]]*=|class[[:space:]]+%s[[:space:]]*[{<]|%s[[:space:]]*[:=][[:space:]]*(async[[:space:]]+)?(function|\()|%s[[:space:]]*\([^)]*\)[[:space:]]*\{)' \
        "$s" "$s" "$s" "$s" "$s" ;;
    go)   printf '^func[[:space:]]+(\([^)]*\)[[:space:]]+)?%s[[:space:]]*\(' "$s" ;;
    java) printf '(class|interface|enum)[[:space:]]+%s\b|\b%s[[:space:]]*\([^)]*\)[[:space:]]*\{' "$s" "$s" ;;
    rs)   printf '^[[:space:]]*(pub[[:space:]]+)?(fn|struct|enum|trait)[[:space:]]+%s\b' "$s" ;;
    rb)   printf '^[[:space:]]*(def|class|module)[[:space:]]+%s\b' "$s" ;;
    *)    printf '\\b%s\\b' "$s" ;;
  esac
}

while IFS= read -r claim; do
  [[ -z "$claim" ]] && continue
  checked=$((checked+1))
  symbol=$(jq -r '.symbol // empty' <<<"$claim")
  file=$(jq -r '.file // empty' <<<"$claim")
  kind=$(jq -r '.kind // "function"' <<<"$claim")
  agent=$(jq -r '.agent // "unknown"' <<<"$claim")
  ac=$(jq -r '.ac_id // "?"' <<<"$claim")

  if [[ -z "$symbol" || -z "$file" ]]; then
    printf 'malformed_claim\t%s\t%s\t%s\t%s\n' "$agent" "$ac" "$symbol" "$file" >> "$FAIL_FILE"
    continue
  fi

  if [[ ! -f "$file" ]]; then
    printf 'missing_file\t%s\t%s\t%s\t%s\n' "$agent" "$ac" "$symbol" "$file" >> "$FAIL_FILE"
    continue
  fi

  pat=$(def_pattern "$symbol" "$file")
  if ! grep -qE "$pat" "$file" 2>/dev/null; then
    printf 'symbol_not_defined\t%s\t%s\t%s\t%s\n' "$agent" "$ac" "$symbol" "$file" >> "$FAIL_FILE"
    continue
  fi

  if [[ "$kind" != "endpoint" ]]; then
    # Look for at least one reference outside the file (or in a test).
    refs=$(grep -rEln "\\b${symbol}\\b" \
              --include='*.py' --include='*.js' --include='*.jsx' \
              --include='*.ts' --include='*.tsx' --include='*.go' \
              --include='*.java' --include='*.rs' --include='*.rb' \
              . 2>/dev/null | grep -v "^./${file#./}$" | head -5)
    if [[ -z "$refs" ]]; then
      printf 'no_callers\t%s\t%s\t%s\t%s\n' "$agent" "$ac" "$symbol" "$file" >> "$FAIL_FILE"
    fi
  fi
done <<< "$CLAIMS"

n_fail=$(wc -l < "$FAIL_FILE" | tr -d ' ')

if [[ $EMIT_JSON -eq 1 ]]; then
  printf '{"status":"%s","checked":%d,"failures":[' \
    "$([[ $n_fail -eq 0 ]] && echo ok || echo fail)" "$checked"
  first=1
  while IFS=$'\t' read -r kind agent ac sym file; do
    [[ -z "$kind" ]] && continue
    [[ $first -eq 0 ]] && printf ','
    first=0
    printf '{"kind":"%s","agent":"%s","ac":"%s","symbol":"%s","file":"%s"}' \
      "$kind" "$agent" "$ac" "$sym" "$file"
  done < "$FAIL_FILE"
  printf ']}\n'
else
  if [[ $n_fail -eq 0 ]]; then
    echo "[liveness-check] OK — $checked claim(s) verified"
  else
    echo "[liveness-check] FAIL — $n_fail of $checked claim(s) failed:" >&2
    while IFS=$'\t' read -r kind agent ac sym file; do
      printf '  [%s] agent=%s ac=%s symbol=%s file=%s\n' "$kind" "$agent" "$ac" "$sym" "$file" >&2
    done < "$FAIL_FILE"
  fi
fi

[[ $n_fail -gt 0 ]] && exit 1 || exit 0
