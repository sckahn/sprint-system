# SVMP — 자기검증 기반 기억가소성 학습 시스템

> **S**elf-**V**alidating **M**emory-**P**lasticity learning system
>
> 아티팩트 *"자기검증 기반 기억가소성 학습 시스템"* 개념 설계를 **실행 가능한
> 모델 구조 + 학습 아키텍처**로 구현한 PyTorch 패키지.

가설을 세우고(Architect) → 기존 지식과 대조하고(Collector) → 빈틈은 외부 검색으로
확인한 뒤(Verifier) → **검증된 지식만** 가중치에 통합(gated consolidation)한다.
모든 연산은 **유한한 예산**에서 차감되는 생존 자원이다.

설계 ↔ 코드 전체 매핑은 [`docs/architecture.md`](docs/architecture.md) 참고.

---

## 빠른 시작

```bash
cd self-validating-memory
pip install -r requirements.txt      # torch
python examples/demo.py              # Phase 1 + Phase 2 데모
# 또는
python -m svmp.train --phase 1 --steps 2500
```

대표 출력 (Phase 1):

```
[step   300] acc=0.61 reward=+0.18 ece=0.074 vault=131 budget=3134.8 maint=1.30
[step   600] acc=0.95 reward=+0.78 ece=0.142 vault=207 budget=3511.1 maint=1.60
[step  1200] acc=0.95 reward=+0.81 ece=0.152 vault=348 budget=4030.3 maint=2.20
Final: acc=0.96 ece=0.133 vault=441 alive=True
```

세 가지가 함께 진화한다:
- **정확도 ↑** — 3-인자 규칙이 좋은 결정 정책을 통합
- **예산 회복** — 유능해지면 벌어들인 보상이 점증하는 유지비를 추월 (연산=생존자원)
- **창고 성장 후 안정** — decay/prune가 미검증 엔트리를 망각

수동적인(학습 못 하는) 에이전트는 보상을 못 벌어 **예산 고갈로 사망**한다 —
이것이 설계 의도다.

---

## 아키텍처 한눈에

```
입력 x
  │  budget.tick() + spend(inference)        ← 예산 경제 (§4.2)
  ▼
encoder(x) ──▶ GrowingVault.query ──▶ gap? ──┐  ← 자라는 창고 (§4.1)
  │                                          │
  │   Architect ─가설→ Collector ─빈틈→ Verifier(외부검색+출처평가)  ← 3역할 GAN (§3)
  │                                          │
  ▼                                          ▼
fuse ─▶ MoE(top-k, 예산과금) ─▶ decision head ─▶ logits ─▶ action
  │                                          │
  │   external reward (유일한 valence)        │  ← 외부 검증
  ▼                                          ▼
3-인자 학습  Δw = η·e·m·g                  calibration head (Jeopardy 베팅)
  e=적격흔적  m=신경조절자  g=통합게이트         ← §4.4 / §4.6
  ▼
GrowingVault.consolidate (게이트 열릴 때만) + decay (망각)
```

---

## 모듈 구조

| 파일 | 역할 | 설계 §|
|------|------|-------|
| `svmp/config.py` | 모든 하이퍼파라미터 (dataclass) | — |
| `svmp/budget.py` | `BudgetEconomy` — 유한 연산 자원, 유지비 점증, 보상 환급 | §4.2 |
| `svmp/vault.py` | `GrowingVault` — 보정 확신도 저장, 게이트 통합, 망각 | §4.1 |
| `svmp/moe.py` | `MoELayer` — 가변 top-k, 전문가 활성화 과금, 붕괴방지 | §4.3 |
| `svmp/learning/eligibility.py` | `EligibilityTrace` — 1st factor (e) | §4.4 |
| `svmp/learning/neuromod.py` | `Neuromodulator` — 2nd factor (m), 보상예측오차 | §4.4 |
| `svmp/learning/gating.py` | `ConsolidationGate` — 3rd factor (g) | §4.4 |
| `svmp/learning/three_factor.py` | `ThreeFactorLearner` — Δw=η·e·m·g (역전파 아님) | §4.4 |
| `svmp/learning/rewards.py` | `RewardTopology` — 독립 vs 위치 보상 | §4.5 |
| `svmp/roles/architect.py` | `Architect` — 구조 가설 생성기 | §3 |
| `svmp/roles/collector.py` | `Collector` — 창고 대조 판별기 | §3 |
| `svmp/roles/verifier.py` | `Verifier` — 외부검색 + **출처품질 평가**(삼각측량) | §3,§4 |
| `svmp/roles/adversarial.py` | `AdversarialLoop`, `SelfPlay`(Phase 5 스켈레톤) | §3 |
| `svmp/calibration.py` | `CalibrationHead`, Jeopardy 베팅, ECE | §4.6 |
| `svmp/model.py` | `SelfValidatingModel` — 미분 가능한 신경 코어 | §7 |
| `svmp/agent.py` | `SelfValidatingAgent` — 전체 스텝 오케스트레이션 | §6 |
| `svmp/tasks.py` | 합성 과제 (calibration bandit, positional ordering) | §5 |
| `svmp/train.py` | 학습 루프 / CLI | §6 |

---

## 핵심 학습 규칙 — 3-인자 (역전파 아님)

```
Δw_ij = η · e_ij · m · g
```

- `e` **적격흔적**: `e ← λ·e + pre·post` — 어떤 시냅스가 최근 활동했나
- `m` **신경조절자**: `reward − baseline` — 전역 보상예측오차 (외부에서만 옴)
- `g` **통합게이트**: σ(놀라움·빈틈·출처품질) — 통합할 가치가 있나

`g`가 대부분 0에 가까워 대부분의 라운드는 가중치를 건드리지 않는다 →
**파국적 망각 없는 가소성**. (REINFORCE가 이 규칙의 특수해: `e=∇logπ, m=보상−기준, g=1`.)

두 학습 경로가 의도적으로 병행된다:
- **3-인자 가소성** → *결정 헤드*를 보상으로 갱신 (autograd 없음, 핵심 메커니즘)
- **역전파** → 표현/보조헤드(encoder·MoE·calibration·역할)를 외부에서 드러난 라벨로 학습

---

## 5단계 로드맵 매핑

| Phase | 설계 | 구현 |
|-------|------|------|
| 1 | calibration 엔진, Jeopardy 베팅 | `train --phase 1` + `CalibrationBanditTask` |
| 2 | 예산 경제 + MoE | 예산↔top-k 결합, load-balance loss |
| 3 | 건축가/수집가 GAN | `roles/adversarial.py` |
| 4 | 검증 에이전트 + 자라는 창고 | `roles/verifier.py` + `vault.py` |
| 5 | 2층 자기놀이 (정답키 없음) | `roles/adversarial.py::SelfPlay` (스켈레톤) |

> ⚠️ 설계가 지목한 **가장 약한 실제 부품**은 GAN 구조가 아니라
> *"검색 결과 출처 품질 평가 능력"* — `Verifier.assess_source`에 삼각측량 기반으로
> 보수적으로 구현했고, 진짜 retriever를 `search_fn`으로 주입하면 된다.

---

## 테스트

```bash
pip install pytest
python -m pytest -q          # 23 passed
```

`tests/`는 예산 사망/회복, 게이트 차단, 확신도 보정, top-k 과금, 3-인자 갱신 조건,
end-to-end 학습(정확도 > chance, 생존)을 검증한다.

---

## 한계 / 다음 단계

- `Verifier`의 외부 검색은 **시뮬레이터**(`_simulated_search`) — 실제 retriever 주입 필요
- 과제는 합성 스캐폴드 — 메커니즘 시연용이지 벤치마크 아님
- `SelfPlay`(Phase 5)는 배선만 문서화한 스켈레톤
- 적대적 역할 학습은 단일 옵티마이저 동시경사 근사 (정식 alternating minimax 아님)
