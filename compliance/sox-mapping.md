# Sarbanes-Oxley (SOX) — Audit Event 매핑

SOX §302 (CEO/CFO 인증) 및 §404 (내부통제 평가) 기준.  
IT General Controls (ITGC) 및 Application Controls 관점에

---

## ITGC — Change Management Controls

### CC6.1 — Access Control to Programs and Data

| Control | 대응 |
|---------|------|
| 변경은 승인된 사용자만 가능 | Branch protection (CODEOWNERS) + `ac.confirmed` 사인오프자 기록 |
| 접근 이력 기록 | 모든 `session.*` 이벤트 + GitHub audit log |
| Privileged access 모니터링 | `audit-verify.yml` — bot 외 `.audit/events.jsonl` 직접 수정 차단 |

### CC8.1 — Change Management

| Control | 대응 audit 이벤트 |
|---------|-----------------|
| 변경 요청 문서화 | `sprint.planned` (tasks 배열 — owner, reviewer, AC 링크) |
| 변경 테스트 증적 | `sprint.quality_gate_passed` + qa-tester output JSON |
| 변경 승인 이력 | `ac.confirmed` (approver + github_username + via) |
| 운영 배포 승인 | `release.deployed` (authorized_by 필드) |
| 4-eyes principle | `milestone.completed` (GitHub PR merged, CODEOWNERS review) |

```bash
# SOX CC8.1 — 분기별 변경 이력 보고서 생성
python3 -c "
import json
q = '2026-Q1'  # 조정
start = '2026-01-01'; end = '2026-03-31'
change_events = ['sprint.planned','ac.confirmed','milestone.completed','release.deployed']
with open('.audit/events.jsonl') as f:
    events = [json.loads(l) for l in f if l.strip()]
report = [e for e in events if e['event'] in change_events and start <= e['ts'][:10] <= end]
print(f'Change events in {q}: {len(report)}')
for e in report:
    print(f\"  {e['ts'][:10]}  {e['event']}  seq={e['seq']}\")
"
```

---

## SOX §302 — CEO/CFO Certification Support

Project closure sign-off 이벤트가 §302 인증의 IT 통제 근거가 됩니다:

```json
{
  "event": "roadmap.project_closed",
  "signed_by": "CTO / Compliance Officer",
  "signing_method": "interactive_dod_command",
  "ts": "2026-03-31T09:00:00Z",
  "all_milestones": ["M1","M2","M3"]
}
```

**포함된 증적**:
1. 모든 마일스톤 완료 (`milestone.completed` × N)
2. 모든 AC 사람이 사인오프 (`ac.confirmed` × N, approver 명시)
3. 보안 감사 완료 (`security.audit_completed` × N, critical=0)
4. Hash chain 무결성 (`audit-verify.sh` OK)
5. S3 Object Lock WORM 보존 (삭제 불가)

---

## SOX §404 — Internal Control Assessment

### Evidence Package for External Auditors

```bash
# 1. Chain 무결성 증명
bash .claude/bin/audit-verify.sh

# 2. 프로젝트 전체 attestation
bash .claude/bin/audit-attest.sh --from 1 --to $(python3 -c "
import json
with open('.audit/events.jsonl') as f:
    lines = list(f)
    print(json.loads(lines[-1])['seq'])
") --label "sox-annual-2026"

# 3. 사람 사인오프 이벤트 수 집계
python3 -c "
import json
human_events = {'ac.confirmed','milestone.completed','roadmap.project_closed','release.deployed'}
count = 0
with open('.audit/events.jsonl') as f:
    for line in f:
        ev = json.loads(line)
        if ev['event'] in human_events and any(k in ev for k in ['approver','confirmed_by','authorized_by','signed_by']):
            count += 1
print(f'Total human sign-off events: {count}')
"
```

---

## Deficiency Classification

| 찾은 것 | SOX 분류 | 대응 |
|--------|---------|------|
| `audit-verify.sh` FAIL | Material Weakness | 즉시 chain 복구 및 경위 조사 |
| `ac.confirmed` 없이 배포된 경우 | Significant Deficiency | `sprint.planned` vs `release.deployed` 불일치 조사 |
| 4-eyes 미충족 (owner=reviewer) | Control Deficiency | `sprint.planned` tasks 재검토 |
| 감사 로그 gap (seq 불연속) | Material Weakness | 누락 구간 경위 조사 |
