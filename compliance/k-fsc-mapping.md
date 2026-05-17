# K-FSC 전자금융감독규정 — Audit Event 매핑

금융감독원 전자금융감독규정(2024년 개정) 기준.  
각 통제 요건이 어느 audit 이벤트로 입증되는지 양방향으로 정리합니다.

---

## §11 — 정보보호 최고책임자

| 요건 | 대응 audit 이벤트 | 검증 명령 |
|------|-----------------|-----------|
| 정보보호 정책 수립·시행 | `roadmap.initialized`, ADR 파일 | `bash .claude/bin/audit-verify.sh` |
| 보안 조치 이행 결과 검토 | `security.audit_completed` (sprint별) | audit log grep: `security.audit_completed` |

---

## §13 — 접근통제 및 로그 관리

| 요건 | 대응 audit 이벤트 | 검증 명령 |
|------|-----------------|-----------|
| 접근 로그 기록 및 보존 | 모든 이벤트 (hash-chained) | `bash .claude/bin/audit-verify.sh` |
| 로그 위·변조 방지 | hash chain (prev_hash → this_hash) | chain 검증 후 `FAIL` = 변조 탐지 |
| 로그 보존기간 (최소 5년) | S3 Object Lock COMPLIANCE 모드 | `aws s3api head-object` + Object Lock 확인 |
| 원격접속 로그 | `session.rc_started`, `session.rc_ended` | grep으로 추출 가능 |
| 접속자 식별 | 모든 이벤트의 `approver`/`actor`/`github_username` 필드 | - |

```bash
# §13 감사 증적 추출 예시
python3 -c "
import json
with open('.audit/events.jsonl') as f:
    for line in f:
        ev = json.loads(line)
        if 'approver' in ev or 'actor' in ev:
            print(ev['seq'], ev['ts'], ev['event'], ev.get('approver', ev.get('actor', '?')))
"
```

---

## §15 — 변경관리

| 요건 | 대응 audit 이벤트 | 검증 |
|------|-----------------|------|
| 변경 신청자와 승인자 분리 | `owner_agent ≠ reviewer_agent` (sprint.planned task 구조) | sprint.planned 이벤트의 tasks 배열 검사 |
| 변경 승인 기록 | `ac.confirmed` (approver 필드), `milestone.completed` | audit log 직접 확인 |
| 변경 테스트 결과 | `sprint.quality_gate_passed` + qa-tester evidence | sprint 이벤트 시계열 |
| 운영 반영 이력 | `release.deployed` (version, sha, authorized_by) | audit grep |
| 장애 발생 시 롤백 | `incident.mitigated` (action 필드에 rollback 포함) | - |

```bash
# §15 변경이력 감사관 보고 예시
python3 -c "
import json
events_of_interest = {'sprint.started','sprint.completed','ac.confirmed','ac.rejected',
                       'milestone.completed','release.deployed'}
with open('.audit/events.jsonl') as f:
    for line in f:
        ev = json.loads(line)
        if ev['event'] in events_of_interest:
            print(f\"seq={ev['seq']} ts={ev['ts']} event={ev['event']}\")
            for k in ['approver','confirmed_by','authorized_by','signed_by']:
                if k in ev: print(f\"  {k}: {ev[k]}\")
"
```

---

## §17 — 재해복구

| 요건 | 대응 |
|------|------|
| 복구 시간 목표(RTO) 정의 | `roadmap.md` quality gates 섹션에 명시 |
| 복구 훈련 이력 | `sre-incident` 에이전트 postmortem (incident.closed 이벤트) |
| 백업 데이터 무결성 | audit log S3 Object Lock + `audit-verify.sh` |

---

## §22 — 소프트웨어 개발 보안

| 요건 | 대응 audit 이벤트 |
|------|-----------------|
| 보안 요구사항 정의 | `sprint.planned` + security-auditor 항시 호출 정책 |
| 보안 코딩 기준 적용 | `security.audit_completed` (sprint별 Critical=0 gate) |
| 보안 테스트 수행 | `security.audit_completed` + dependency_scan 결과 |
| 취약점 조치 | `ac.confirmed`에 선행하는 security finding 해소 기록 |

---

## §31 — 전자금융거래 기록 보존

| 요건 | 대응 |
|------|------|
| 거래기록 5년 보존 | S3 Object Lock COMPLIANCE (retention: 1825 days) |
| 기록 위변조 방지 | hash chain + Object Lock (관리자도 삭제 불가) |
| 감사 추적 가능성 | seq 번호 + prev_hash/this_hash로 임의 이벤트 도달 가능 |

---

## 감사관 FAQ

**Q: 특정 날짜 범위의 모든 변경 이력을 보여달라**
```bash
python3 -c "
import json, sys
start, end = '2026-01-01', '2026-03-31'
with open('.audit/events.jsonl') as f:
    for line in f:
        ev = json.loads(line)
        if start <= ev['ts'][:10] <= end:
            print(json.dumps(ev, ensure_ascii=False))
"
```

**Q: 이 시스템의 로그가 변조되지 않았음을 증명하라**
```bash
bash .claude/bin/audit-verify.sh
# OK: N events verified, head=<sha256>... 출력되면 무결성 증명
```

**Q: 누가 어떤 결정을 내렸는지 추적할 수 있는가**
```bash
# 모든 사람이 서명한 이벤트 추출
python3 -c "
import json
human_events = {'ac.confirmed','ac.rejected','milestone.completed','roadmap.project_closed','release.deployed'}
with open('.audit/events.jsonl') as f:
    for line in f:
        ev = json.loads(line)
        if ev['event'] in human_events:
            actor = ev.get('approver') or ev.get('confirmed_by') or ev.get('authorized_by') or ev.get('signed_by','?')
            print(f\"{ev['ts']}  {ev['event']}  signed_by={actor}  seq={ev['seq']}\")
"
```
