# sprint-system

**Claude Code 기반 멀티에이전트 개발팀 템플릿** — 17개 전문 에이전트, 8단계 스프린트 사이클, 3계층 DoD 게이트, 해시체인 감사 로그, GitHub Actions 헤드리스 자동화까지 한 번에.

> 금융권·SOX·PCI-DSS·ISO27001 감사 대응 가능한 수준의 추적성을 목표로 설계.

---

## 한눈에 보기

| 영역 | 구성 |
|------|------|
| **에이전트 17종** | spec-writer · architect · backend-eng · frontend-eng · db-engineer · code-reviewer · security-auditor · qa-tester · interface-validator · ci-cd-engineer · release-manager · sre-incident · hermes · ml-engineer · data-engineer · mobile-eng · accessibility-auditor |
| **슬래시 명령** | `/sprint` · `/roadmap` · `/dod` |
| **스킬 15종** | sprint-system 고유 3종 + obra/superpowers 12종 (TDD · 디버깅 · 검증 · 브레인스토밍 · 플래닝 · 병렬 디스패치 · 코드리뷰 · 워크트리 등) |
| **DoD 3계층** | Story-AC → Milestone → Project, 모두 사람 사인오프 필수 |
| **감사 로그** | SHA256 해시체인 (tamper-evident), mkdir 기반 크로스플랫폼 뮤텍스 |
| **GitHub 통합** | roadmap-loop · dod-handler · audit-verify · audit-shift 4개 워크플로 |
| **컴플라이언스** | K-FSC · SOX · PCI-DSS v4.0 · ISO 27001:2022 매핑 문서 포함 |

---

## 빠른 시작

### 방법 1: 템플릿으로 새 프로젝트 만들기 (권장)

```bash
gh repo create my-app --template sckahn/sprint-system --private --clone
cd my-app
bash .claude/bin/bootstrap.sh
claude
# 안에서 — 한 문장이면 끝:
/start "친구랑 같이 하는 빙수 빨리먹기 게임 만들고 싶어"
```

`/start`이 architect·spec-writer로 로드맵 자동 생성 → 사람 컨펌 1회 → 모든 스프린트 자동 실행 → DoD 게이트마다만 멈춤.

수동 제어를 원하면:
```
/roadmap init   # 마일스톤·AC 직접 작성
/sprint         # 첫 스프린트
```

### 방법 2: 기존 프로젝트에 얹기

```bash
cd ~/existing-project
git clone https://github.com/sckahn/sprint-system.git /tmp/ss
cp -r /tmp/ss/.claude /tmp/ss/.github /tmp/ss/compliance /tmp/ss/infra .
cp /tmp/ss/roadmap.template.md roadmap.md
bash .claude/bin/bootstrap.sh
```

---

## 첫 사이클 흐름 (8단계)

```
Phase 0  사전 점검 (audit chain, roadmap, baseline tests)
Phase 1  스프린트 플래닝   ← spec-writer + brainstorming/writing-plans
Phase 2  병렬 실행         ← backend/frontend/db 동시 dispatch + worktrees + TDD
Phase 3  인터페이스 검증   ← interface-validator
Phase 4  품질·보안 게이트  ← code-reviewer + security-auditor + qa-tester
         Phase 4.3  Story DoD 게이트 (사람 컨펌 필수)
Phase 5  스프린트 리뷰     ← release-manager + ci-cd-engineer (PR 생성)
Phase 6  레트로
Phase 7  Hermes 학습       ← 패턴 추출, 코디네이터 개선 제안
Phase 8  종료
```

---

## 📱 모바일에서 한 문장으로 시작 (헤드리스)

**데스크톱 없이 GitHub 모바일 앱만으로 전체 사이클 운영 가능.**

### 처음 한 번 (데스크톱)

```bash
gh repo create my-app --template sckahn/sprint-system --private --clone
cd my-app
bash .claude/bin/bootstrap.sh
gh secret set ANTHROPIC_API_KEY      # 필수
# 라벨 생성 (bootstrap.sh 마지막 출력 한 줄 복붙)
git push
```

### 이후 — 모바일 GitHub 앱에서

1. 레포 열기 → **Issues** → **New** → **🚀 Project Brief**
2. 한 문장 입력 (예: "친구랑 같이 하는 빙수 빨리먹기 게임 만들고 싶어")
3. 규모 선택 → **Submit**
4. ~2분 후 이슈에 로드맵 코멘트 달림
5. **답글**:
   - `/yes` — 진행
   - `/edit 마일스톤 2 빼고 인증 추가` — 수정 요청
   - `/no` — 취소
6. 이후 AC/마일스톤/프로젝트 게이트마다 자동으로 이슈 생성됨
   - AC 이슈: `/confirm AC-1.1`
   - 마일스톤 이슈: `/yes` 또는 `/halt 사유`
   - 프로젝트 이슈: `/close` (최종 사인오프 + attestation)

데스크톱은 다시 켤 필요 없음.

---

## GitHub Actions로 헤드리스 운영

### 필수 Secrets

```bash
gh secret set ANTHROPIC_API_KEY
# 선택
gh secret set SLACK_WEBHOOK_DOD
gh secret set SLACK_WEBHOOK_ALERTS
gh secret set AWS_ROLE_ARN AWS_AUDIT_BUCKET   # S3 Object Lock 쓸 때만
```

### 필수 Labels

```bash
for l in "dod:pending#FBCA04" "dod:ac#0E8A16" "dod:milestone#1D76DB" \
         "dod:confirmed#5319E7" "dod:rejected#D93F0B" "dod:needs-more#FEF2C0"; do
  gh label create "${l%%#*}" --color "${l##*#}" --force
done
```

### Branch Protection

`main`에 CODEOWNERS 리뷰 + `audit-verify` 상태 체크 통과 강제. 자세한 명령은 [docs/github-setup.md](docs/github-setup.md) 참고 (사용자가 생성).

### DoD 컨펌 (PR/이슈 코멘트)

```
/confirm AC-1.1 AC-1.2
/needs-more AC-1.3
/reject AC-1.4 reason="성능 SLO 미달"
```

---

## 디렉터리 구조

```
.claude/
  agents/          17개 전문 에이전트
  commands/        sprint · roadmap · dod
  skills/          15개 스킬 (3 + 12 superpowers)
  bin/             audit·gh·notify·bootstrap 스크립트
.github/workflows/ 4개 자동화 워크플로
.audit/            해시체인 감사 로그 (런타임, gitignore)
.dod/              컨펌 대기·완료 상태 (런타임, gitignore)
.hermes/proposals/ 메타학습 제안 (런타임, gitignore)
compliance/        K-FSC · SOX · PCI-DSS · ISO27001 매핑
infra/terraform/   S3 Object Lock WORM 인프라
docs/adr/          아키텍처 결정 기록
docs/superpowers/  superpowers 스킬이 생성하는 plans·specs
sprint-system-plugin/  Claude Code 플러그인 패키징
```

---

## 핵심 원칙 (절대 우회 금지)

1. **Separation of duties** — 구현자와 리뷰어는 다른 에이전트
2. **DoD 3-tier human gate** — AC·마일스톤·프로젝트 모두 사람 사인오프
3. **Hash-chained audit** — 모든 이벤트는 `prev_hash → this_hash`로 연결, 직접 편집 차단
4. **Verification before completion** — 5게이트 통과 없이 "완료" 보고 불가
5. **No performative agreement** — 리뷰 피드백은 기술적 평가, 무조건 수용 금지

---

## 라이선스

MIT

## 크레딧

- [obra/superpowers](https://github.com/obra/superpowers) — 12개 핵심 스킬을 통합 사용
- Claude Code subagent / plugin 아키텍처
