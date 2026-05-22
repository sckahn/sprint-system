#!/usr/bin/env bash
# stub-detect.sh — detect shell-only / stub / fake implementations in changed files
#
# Usage:
#   bash .claude/bin/stub-detect.sh [--base <ref>] [--strict] [--json]
#
# Exit codes:
#   0  no stubs detected
#   1  stubs detected (details on stdout/stderr)
#   2  invocation error
#
# Detection scope: files changed vs --base (default: main).
# Supported languages: Python, JS/TS, Go, Java, Rust, Ruby.
# Test files (tests/, *_test.*, *.test.*, *.spec.*) are excluded from stub
# checks but still scanned for "fake test" patterns (assert True, expect(true)).

set -euo pipefail

BASE="main"
STRICT=0
EMIT_JSON=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="$2"; shift 2 ;;
    --strict) STRICT=1; shift ;;
    --json) EMIT_JSON=1; shift ;;
    -h|--help)
      sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "[stub-detect] unknown arg: $1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[stub-detect] not a git repo" >&2; exit 2; }
cd "$REPO_ROOT"

# Resolve base ref; fall back to empty-tree if base unreachable (first commit case)
if git rev-parse --verify "$BASE" >/dev/null 2>&1; then
  CHANGED=$(git diff --name-only --diff-filter=AM "$BASE"...HEAD 2>/dev/null || true)
else
  CHANGED=$(git diff --name-only --diff-filter=AM HEAD 2>/dev/null || true)
fi

if [[ -z "$CHANGED" ]]; then
  [[ $EMIT_JSON -eq 1 ]] && echo '{"status":"ok","findings":[],"changed":0}' \
    || echo "[stub-detect] no changed files vs $BASE — ok"
  exit 0
fi

FINDINGS_FILE=$(mktemp)
trap 'rm -f "$FINDINGS_FILE"' EXIT

is_test_path() {
  case "$1" in
    tests/*|*/tests/*|test/*|*/test/*) return 0 ;;
    *_test.go|*_test.py|*.test.ts|*.test.tsx|*.test.js|*.test.jsx) return 0 ;;
    *.spec.ts|*.spec.tsx|*.spec.js|*.spec.jsx) return 0 ;;
    *Test.java|*Tests.java|*Spec.rb|*_spec.rb) return 0 ;;
  esac
  return 1
}

ext_of() { printf '%s' "${1##*.}"; }

emit() {
  # emit <file> <line> <kind> <snippet>
  local file="$1" line="$2" kind="$3" snippet="$4"
  printf '%s\t%s\t%s\t%s\n' "$file" "$line" "$kind" "$snippet" >> "$FINDINGS_FILE"
}

# Regex bank per category — POSIX ERE
RE_TODO_ONLY='^[[:space:]]*(#|//|--)[[:space:]]*(TODO|FIXME|XXX)([:[:space:]]|$)'
RE_NOT_IMPL='(NotImplementedError|NotImplementedException|raise[[:space:]]+NotImplemented|panic\("not[[:space:]]+implement|todo!\(|unimplemented!\(|throw[[:space:]]+new[[:space:]]+Error\(["'\'']not[[:space:]]+implemented)'
RE_BODY_PASS='^[[:space:]]*(pass|return None|return null|return;|return nil)[[:space:]]*$'
RE_FAKE_TEST='(assert[[:space:]]+True[[:space:]]*$|assert[[:space:]]+1[[:space:]]*==[[:space:]]*1|expect\(true\)\.toBe\(true\)|expect\(1\)\.toBe\(1\)|t\.Skip\(|xit\(|xdescribe\(|@Disabled|@Ignore)'

scan_file_general() {
  local f="$1"
  # 1. NotImplemented-style throws
  while IFS=: read -r ln rest; do
    [[ -n "$ln" ]] && emit "$f" "$ln" "not_implemented" "$(printf '%s' "$rest" | head -c 120)"
  done < <(grep -nE "$RE_NOT_IMPL" "$f" 2>/dev/null || true)

  # 2. Body-of-function == single trivial statement.
  #    Heuristic: a line matching trivial-body whose *previous non-blank* line
  #    ends with a function-definition signature.
  awk -v file="$f" '
    function is_def(l) {
      return l ~ /^[[:space:]]*(def|fn|func|function|public|private|protected|static|async)[[:space:]].*[({:]/ \
          || l ~ /=>[[:space:]]*\{?[[:space:]]*$/
    }
    {
      raw=$0
      gsub(/^[[:space:]]+|[[:space:]]+$/,"",raw)
      if (raw=="") next
      if (prev_was_def && (raw=="pass" || raw=="return None" || raw=="return null" || raw=="return;" || raw=="return nil" || raw=="{}" || raw=="return {}" || raw=="return []")) {
        printf "%s\t%d\tbody_trivial\t%s\n", file, NR, raw
      }
      prev_was_def = is_def(raw)
    }
  ' "$f" >> "$FINDINGS_FILE"

  # 3. TODO-only function bodies (simple heuristic: file changed but body is
  #    one comment line referencing TODO/FIXME within 3 lines after a def).
  awk -v file="$f" '
    function is_def(l) {
      return l ~ /^[[:space:]]*(def|fn|func|function|public|private|protected)[[:space:]].*[({:]/
    }
    {
      if (is_def($0)) { def_line=NR; counted=0; next }
      if (def_line && NR-def_line<=3 && counted==0) {
        s=$0; gsub(/^[[:space:]]+|[[:space:]]+$/,"",s)
        if (s ~ /^(#|\/\/|--)[[:space:]]*(TODO|FIXME|XXX)/) {
          printf "%s\t%d\ttodo_only_body\t%s\n", file, NR, s
          counted=1; def_line=0
        }
      }
    }
  ' "$f" >> "$FINDINGS_FILE"
}

scan_test_file() {
  local f="$1"
  while IFS=: read -r ln rest; do
    [[ -n "$ln" ]] && emit "$f" "$ln" "fake_test" "$(printf '%s' "$rest" | head -c 120)"
  done < <(grep -nE "$RE_FAKE_TEST" "$f" 2>/dev/null || true)
}

count=0
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  [[ ! -f "$f" ]] && continue
  case "$(ext_of "$f")" in
    py|js|jsx|ts|tsx|go|java|rs|rb) ;;
    *) continue ;;
  esac
  count=$((count+1))
  if is_test_path "$f"; then
    scan_test_file "$f"
  else
    scan_file_general "$f"
  fi
done <<< "$CHANGED"

n_findings=$(wc -l < "$FINDINGS_FILE" | tr -d ' ')

if [[ $EMIT_JSON -eq 1 ]]; then
  printf '{"status":"%s","changed":%d,"findings":[' \
    "$([[ $n_findings -eq 0 ]] && echo ok || echo fail)" "$count"
  first=1
  while IFS=$'\t' read -r f ln kind snip; do
    [[ -z "$f" ]] && continue
    [[ $first -eq 0 ]] && printf ','
    first=0
    # JSON-escape snippet minimally
    esc=$(printf '%s' "$snip" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/ /g')
    printf '{"file":"%s","line":%s,"kind":"%s","snippet":"%s"}' "$f" "$ln" "$kind" "$esc"
  done < "$FINDINGS_FILE"
  printf ']}\n'
else
  if [[ $n_findings -eq 0 ]]; then
    echo "[stub-detect] OK — $count files scanned, no stubs detected"
  else
    echo "[stub-detect] FAIL — $n_findings finding(s) across $count file(s):" >&2
    while IFS=$'\t' read -r f ln kind snip; do
      printf '  %s:%s  [%s]  %s\n' "$f" "$ln" "$kind" "$snip" >&2
    done < "$FINDINGS_FILE"
  fi
fi

if [[ $n_findings -gt 0 ]]; then
  if [[ $STRICT -eq 1 ]] || [[ $STRICT -eq 0 ]]; then
    exit 1
  fi
fi
exit 0
