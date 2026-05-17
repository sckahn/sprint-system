# PCI DSS v4.0 — Audit Event 매핑

결제 카드 데이터를 처리하는 시스템에 적용. 관련 Requirements만 발췌.

---

## Requirement 6 — Secure Systems and Software

### 6.3.2 — Inventory of Bespoke and Custom Software

| 요건 | 대응 |
|------|------|
| 소프트웨어 목록 유지 | `sprint.planned` + ADR 파일 (docs/adr/) |
| 소프트웨어 변경 이력 | `sprint.started` → `sprint.completed` 시계열 |

### 6.4.1 — Public-Facing Web App Security

| 요건 | 대응 audit 이벤트 |
|------|-----------------|
| 코드 취약점 검토 | `security.audit_completed` (OWASP Top 10 포함) |
| 보안 테스트 | security-auditor: exploitability 필드로 분류 |
| 취약점 조치 | Critical AC가 ac.confirmed에 선행 |

### 6.5 — Change Control

| 요건 | 대응 |
|------|------|
| 승인된 변경만 운영 반영 | Branch protection + `release.deployed` (authorized_by) |
| 영향 분석 | `interface-validator` 에이전트 실행 기록 |
| 백아웃 계획 | db-engineer 마이그레이션의 DOWN 스크립트 필수 |

---

## Requirement 7 — Restrict Access

| 요건 | 대응 |
|------|------|
| 최소 권한 원칙 | 에이전트별 tools 필드 제한 (read-only 에이전트 분리) |
| 접근 승인 기록 | `ac.confirmed` 이벤트 (approver 필드) |

---

## Requirement 10 — Log and Monitor

| 요건 | 대응 |
|------|------|
| 감사 로그 생성 | 모든 audit 이벤트 (JSON Lines) |
| 로그 무결성 | hash chain (prev_hash → this_hash) |
| 로그 보존 12개월 + 3개월 즉시 접근 | S3 Object Lock 12개월 + events.jsonl 로컬 3개월 |
| 로그 검토 | `audit-verify.sh` 일별 CI 실행 |

```bash
# Requirement 10 — 로그 보존 상태 확인
aws s3api list-objects-v2 \
  --bucket "$AWS_AUDIT_BUCKET" \
  --prefix "audit-logs/" \
  --query 'Contents[].{Key:Key,LastModified:LastModified}' \
  --output table
```

---

## Requirement 12 — Policies and Procedures

| 요건 | 대응 |
|------|------|
| 정보보안 정책 문서화 | `.claude/agents/security-auditor.md` + CLAUDE.md |
| 연간 검토 | Hermes 에이전트 제안 + 사람 승인 기록 (`hermes.applied`) |

---

## SAQ / ROC 제출용 증적 추출

```bash
# 최근 12개월 보안 감사 완료 횟수
python3 -c "
import json
from datetime import datetime, timedelta
cutoff = (datetime.utcnow() - timedelta(days=365)).isoformat()[:10]
count = 0
with open('.audit/events.jsonl') as f:
    for line in f:
        ev = json.loads(line)
        if ev['event'] == 'security.audit_completed' and ev['ts'][:10] >= cutoff:
            count += 1
print(f'Security audits in last 12 months: {count}')
"

# 변경 승인 없이 배포된 릴리스 검색
python3 -c "
import json
deployments = []
confirmed_sprints = set()
with open('.audit/events.jsonl') as f:
    for line in f:
        ev = json.loads(line)
        if ev['event'] == 'sprint.completed':
            confirmed_sprints.add(ev.get('sprint'))
        elif ev['event'] == 'release.deployed':
            deployments.append(ev)
for dep in deployments:
    if dep.get('sprint') not in confirmed_sprints:
        print(f'WARNING: release {dep.get(\"version\")} deployed without confirmed sprint')
"
```
