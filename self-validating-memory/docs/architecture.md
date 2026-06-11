# 자기검증 기반 기억가소성 학습 시스템 (SVMP)

> **S**elf-**V**alidating **M**emory-**P**lasticity learning system
>
> 아티팩트 *"자기검증 기반 기억가소성 학습 시스템"* 개념 설계를 실행 가능한
> 모델 구조 + 학습 아키텍처로 구현한 것. 설계 철학 → 코드 매핑을 이 문서에 고정한다.

---

## 1. 핵심 개념

에이전트는 **자기검증(self-validation)** 으로 학습한다.

1. 모르는 것에 대해 **가설**을 세우고 (Architect)
2. 기존 지식과 대조해 **검증**하고 (Collector)
3. 빈틈이 있으면 **외부 검색**으로 확인한 뒤 (Verifier)
4. *검증된 지식만* 가중치에 **통합(consolidate)** 한다.

연산(추론·검색·전문가 활성화)은 **유한한 예산**에서 차감되는 생존 자원이다.

---

## 2. 안정성–가소성 딜레마와 4대 원칙

| 원칙 | 의미 | 구현 모듈 |
|------|------|-----------|
| **외부 검증** | 보상을 스스로 정의하지 못함. 외부 현실 또는 적대적 역할 분리에서만 valence를 얻음 | `roles/`, `learning/rewards.py` |
| **연산 = 생존 자원** | 모든 연산이 유한 예산에서 차감 → 수동성과 근거 없는 시도 모두 억제 | `budget.py` |
| **게이트형 통합** | 모든 입력이 가중치를 바꾸지 않음. 게이트 신호가 영구 통합 여부 결정 | `learning/gating.py` |
| **동적 지식 성장** | 고정 KB 대신 진화하는 확신도(conviction) 점수 유지 | `vault.py` |

---

## 3. 시스템 아키텍처 — 3개 역할 (적대적, GAN 유사)

```
        ┌──────────────┐  구조 가설   ┌──────────────┐
 입력 → │  Architect   │ ───────────▶ │  Collector   │
        │ (가설 생성)  │              │ (창고와 대조)│
        └──────────────┘              └──────┬───────┘
                                    빈틈 감지 │ (max sim < τ)
                                              ▼
                                      ┌──────────────┐  출처품질
                                      │  Verifier    │  평가
                                      │ (외부 검색)  │
                                      └──────┬───────┘
                                             ▼
                                     검증된 지식만
                                     Growing Vault 통합
```

- **Architect** (`roles/architect.py`): 지식 연결에 대한 구조적 가설 생성
- **Collector** (`roles/collector.py`): 가설을 기존 지식(Vault)과 대조 검증
- **Verifier** (`roles/verifier.py`): 빈틈 존재 시 외부 검색 + **출처 신뢰도 평가**
- 외부 심판 없이 GAN처럼 적대적으로 동작 (`roles/adversarial.py`)

> ⚠️ 설계 문서가 지목한 **가장 약한 실제 부품**: 화려한 GAN 구조가 아니라
> *"검색 결과의 출처 품질을 평가하는 능력"* (`Verifier.assess_source`).

---

## 4. 핵심 구현 요소

### 4.1 Growing Vault (`vault.py`)
이진 판정이 아니라 **보정된 확신도(calibrated conviction)** 로 저장.

- 엔트리: `key ∈ R^d`, `value ∈ R^d`, `conviction θ ∈ [0,1]`, `evidence_count n`
- `query(q, k)` → 유사도 softmax 가중 회수 + **빈틈 신호**(`max_sim < τ_gap`)
- `consolidate(key, value, gate, target)` → 게이트 통과 시에만 기록.
  유사 엔트리는 보정 갱신 `θ ← θ + α(target − θ)`, 신규는 추가
- `decay()` → 미검증 엔트리 확신도 감쇠, floor 이하 가지치기 (망각)

### 4.2 Budget Economy (`budget.py`)
- 연산마다 차감: `c_inf`(추론), `c_search`(검색), `c_expert`(전문가당)
- 라운드마다 `maintenance_cost` 차감 — **커리큘럼처럼 점증**(tightening)
- 보상은 예산으로 환급 → 예산은 곧 통화(currency). 0 미만 = 사망(death)

### 4.3 MoE (`moe.py`)
- `top-k` 가변 전문가 라우팅. **전문가 활성화마다 예산 차감** → 비용으로 부하분산
- 전문가 붕괴(collapse) 방지용 load-balance aux loss 병행

### 4.4 3-인자 학습 (`learning/three_factor.py`)
역전파가 아닌 **국소 학습 규칙**:

```
Δw_ij = η · e_ij · m · g
```

- `e_ij` **적격흔적(eligibility trace)**: `e ← λ·e + pre_i · post_j` (감쇠 동시성)
- `m` **신경조절자(neuromodulator)**: 전역 보상 신호 `reward − baseline` (도파민 유사, 부호 있음)
- `g` **게이트(gate)** ∈ [0,1]: 통합 여부 (놀라움·신규성·검증상태 함수)

게이트가 열릴 때만 갱신 → **파국적 망각 없는 가소성**.
(REINFORCE도 3-인자로 표현됨: `e = ∇log π`, `m = reward − baseline`.)

### 4.5 보상 위상 (`learning/rewards.py`)
- **독립 보상(independent)**: 사실 도메인 — 항목별 독립 정오
- **위치 보상(positional)**: 구조 도메인 — 관계적 위치·일관성에 의존

### 4.6 확신도 보정 (`calibration.py`)
- confidence head → `p̂`. **Jeopardy 베팅**: 확신도 비례 스테이크,
  정답 `+stake` / 오답 `−stake` → 보정 유도
- 평가: ECE(Expected Calibration Error)

---

## 5. 5단계 로드맵 (구현 매핑)

| Phase | 설계 문서 | 구현 |
|-------|-----------|------|
| **1** | 1층 단독 (calibration 엔진) — math/code, Jeopardy 베팅 | `tasks.py::CalibrationBanditTask` + `train.py --phase 1` |
| **2** | 예산 경제 + MoE 결합 — 전문가 붕괴 회피 | `budget.py` × `moe.py`, load-balance loss |
| **3** | 건축가/수집가 GAN — 적대적 가설-검증 루프 | `roles/adversarial.py` |
| **4** | 검증 에이전트 + 자라는 창고 — 검색 검증 인식적 성장, 삼각측량 | `roles/verifier.py` + `vault.py` |
| **5** | 2층 자기놀이 개척 — 정답키 없는 도메인, Phase1 value net을 심판으로 | `roles/adversarial.py::SelfPlay` (스켈레톤) |

---

## 6. 학습 루프 (한 에피소드)

```
for each round:
  budget.tick()                         # maintenance 차감 (점증)
  x = encoder(input)                     # budget.spend(c_inf)
  retrieved, gap = vault.query(x)        # 빈틈 감지
  hypo = architect(x, retrieved)         # 구조 가설
  agree = collector(hypo, retrieved)     # 창고 대조
  if gap or not agree:
      evidence, src_q = verifier(x)      # budget.spend(c_search), 출처 평가
  y, conf = decision_head(x, retrieved)  # MoE: budget.spend(c_expert·k)
  reward = reward_topology(y, target)    # 외부 검증
  budget.earn(reward)                    # 예산 환급
  m = neuromod(reward)                   # 신경조절자
  g = gate(surprise, gap, src_q)         # 통합 게이트
  three_factor.update(η, e, m, g)        # 국소 가중치 갱신
  vault.consolidate(x, y, g, target)     # 검증된 것만 통합
  vault.decay()                          # 미검증 망각
```

---

## 7. 코드 ↔ 설계 매핑 요약

| 설계 용어 | 코드 |
|-----------|------|
| 자라는 창고 | `svmp.vault.GrowingVault` |
| 예산 경제 | `svmp.budget.BudgetEconomy` |
| 건축가/수집가/검증가 | `svmp.roles.{Architect,Collector,Verifier}` |
| 적대적 루프 | `svmp.roles.AdversarialLoop` |
| 3-인자 학습 | `svmp.learning.ThreeFactorLearner` |
| 적격흔적 | `svmp.learning.EligibilityTrace` |
| 신경조절자 | `svmp.learning.Neuromodulator` |
| 통합 게이트 | `svmp.learning.ConsolidationGate` |
| 보상 위상 | `svmp.learning.RewardTopology` |
| MoE 가변 top-k | `svmp.moe.MoELayer` |
| 보정/베팅 | `svmp.calibration.CalibrationHead` |
| 전체 모델 | `svmp.model.SelfValidatingModel` |
