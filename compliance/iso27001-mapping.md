# ISO/IEC 27001:2022 — Audit Event 매핑

Annex A 통제 항목 기준 (관련 통제만 발췌).

---

## A.8 — Technological Controls

### A.8.8 — Management of Technical Vulnerabilities

| 통제 | 대응 |
|------|------|
| 취약점 식별 | `security.audit_completed` (CVE scan 포함) |
| 취약점 평가 | security-auditor의 exploitability 분류 |
| 패치 적용 | Critical CVE → 해당 sprint의 AC로 등록 후 `ac.confirmed` |
| 조치 이력 | audit log 시계열 |

### A.8.9 — Configuration Management

| 통제 | 대응 |
|------|------|
| 구성 변경 이력 | `sprint.started` + 변경 파일 목록 |
| 승인된 구성만 적용 | `release.deployed` (authorized_by) |

### A.8.32 — Change Management

| 통제 | 대응 audit 이벤트 |
|------|-----------------|
| 변경 계획 | `sprint.planned` |
| 영향 분석 | `interface-validator` 실행 + ADR (architect 에이전트) |
| 변경 테스트 | `sprint.quality_gate_passed` |
| 변경 승인 | `ac.confirmed` (human signer) |
| 긴급 변경 | `incident.mitigated` (authorized_by 필수) |
| 변경 검토 | `sprint.retro` 이벤트 |

---

## A.5 — Organizational Controls

### A.5.36 — Compliance with Policies

```bash
# 정책 위반 이벤트 확인
python3 -c "
import json
with open('.audit/events.jsonl') as f:
    for line in f:
        ev = json.loads(line)
        if ev['event'] == 'policy.violation_detected':
            print(f\"VIOLATION seq={ev['seq']} ts={ev['ts']} : {ev.get('detail','?')}\")
"
```

---

## A.6 — People Controls

### A.6.4 — Disciplinary Process

인간이 DoD 컨펌을 거부(`ac.rejected`)한 경우, 그 기록이 감사 근거:

```bash
python3 -c "
import json
with open('.audit/events.jsonl') as f:
    for line in f:
        ev = json.loads(line)
        if ev['event'] == 'ac.rejected':
            print(f\"Rejected: {ev.get('ac_id')} by {ev.get('rejector')} reason: {ev.get('reason')}\")
"
```

---

## ISMS-P (한국 정보보호 관리체계) 추가 대응

| 인증 요건 | 대응 |
|----------|------|
| 2.9 시스템 개발 보안 | `security.audit_completed` + `sprint.planned` (보안 요구사항 포함) |
| 2.10 시스템 및 서비스 운영 관리 | `release.deployed` + `sre-incident` postmortem |
| 2.11 사고 예방 및 대응 | `incident.opened` → `incident.mitigated` → `incident.closed` 시계열 |
| 3.1 개인정보 수집 시 보호조치 | security-auditor PII 탐지 (`ac.confirmed` 선행) |

---

## 내부 감사 증적 패키지 (ISO 27001 연간 심사용)

```bash
# 전체 증적 패키지 생성 스크립트
OUTPUT_DIR="compliance/evidence-$(date +%Y)"
mkdir -p "$OUTPUT_DIR"

# 1. Chain 무결성 보고서
bash .claude/bin/audit-verify.sh > "$OUTPUT_DIR/chain-integrity.txt" 2>&1

# 2. 연간 attestation
LAST_SEQ=$(python3 -c "import json; lines=list(open('.audit/events.jsonl')); print(json.loads(lines[-1])['seq'])")
bash .claude/bin/audit-attest.sh --from 1 --to "$LAST_SEQ" --label "iso27001-annual-$(date +%Y)"

# 3. 변경 이력 요약
python3 -c "
import json
events = []
with open('.audit/events.jsonl') as f:
    for line in f:
        ev = json.loads(line)
        if ev['event'] in ('sprint.completed','milestone.completed','release.deployed'):
            events.append(ev)
print(f'Total change events: {len(events)}')
for e in events:
    print(f\"  {e['ts'][:10]}  {e['event']}\")
" > "$OUTPUT_DIR/change-summary.txt"

# 4. 보안 감사 이력
python3 -c "
import json
with open('.audit/events.jsonl') as f:
    for line in f:
        ev = json.loads(line)
        if ev['event'] == 'security.audit_completed':
            print(f\"{ev['ts']}  sprint={ev.get('sprint')}  critical={ev.get('critical',0)}  high={ev.get('high',0)}\")
" > "$OUTPUT_DIR/security-audit-history.txt"

echo "Evidence package created: $OUTPUT_DIR/"
```
