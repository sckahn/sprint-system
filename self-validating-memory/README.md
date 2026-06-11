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

## 실험 — 실제로 학습되나?

대조 실험(5시드 × 2500스텝, full vs 학습 끈 passive 대조군):

```bash
PYTHONPATH=. python examples/experiment.py
```

실측 결과:

```
[FULL  (three-factor + backprop ON)]
  final accuracy : 0.952 ± 0.027   | chance=0.25
  ECE            : 0.146 ± 0.012
  survived       : 5/5 agents stayed alive

[PASSIVE  (all learning OFF)]
  final accuracy : 0.234 ± 0.017   | chance=0.25  (= 무작위)
  survived       : 0/5  (평균 722스텝 만에 예산 고갈로 사망)
```

두 가지 핵심 주장이 정량적으로 확인된다:
1. **학습된다** — 정확도 0.43→0.95, chance(0.25)와 passive(0.23)를 크게 상회.
2. **연산=생존자원이 실제로 작동** — 학습 못 하는 에이전트는 보상을 못 벌어
   100% 예산 고갈 사망, 학습하는 에이전트는 100% 생존.

`learn=False`는 3-인자 갱신과 역전파를 모두 끄는 passive 대조군이다.

### 실데이터 실험 (sklearn digits, 1797개 실제 손글씨, 10클래스)

```bash
pip install scikit-learn
PYTHONPATH=. python examples/experiment_real.py
```

**A — 실데이터 학습** (3시드 × 3000스텝, held-out 테스트셋 평가):

```
FULL    : test acc 0.791 ± 0.064  (chance 0.10), 3/3 생존
PASSIVE : test acc 0.105 ± 0.003  (= 무작위),    0/3 생존
```

**B — Phase 4: 출처품질 평가 분리 실험** (설계가 지목한 "가장 약한 부품")

학습 혼동변수를 제거하고 `assess_source`만 분리해, held-out 이미지로 Verifier를
프로빙. 측정값은 **운영상 의미 있는 질문**의 AUC: *"품질 점수가 '집계된 증거가
실제로 맞는지'를 예측하는가?"* (게이트가 이걸로 오도 증거 통합을 막아야 하므로).
사전 정보성 × 검증방식 2×2, **n=8 시드** (`experiment_triangulation.py`):

| prior | verifier | AUC (0.5=chance) |
|-------|----------|------------------|
| informative | triangulated | **0.689 ± 0.044** |
| informative | naive | 0.647 ± 0.044 |
| uninformative | triangulated | 0.537 ± 0.032 |
| uninformative | naive | 0.524 ± 0.045 |

**정직한 결론 (2개의 견고한 효과 + 1개의 약한 효과):**
1. ✅ **사전이 진실하면** 삼각측량이 증거 정확성을 잘 예측 (AUC 0.69).
2. ✅ **사전이 무정보면** naive는 chance로 붕괴 (0.52) — 자기보고 권위가 신호를
   못 줄 때 단일 출처는 무력하다.
3. ⚠️ **무정보 사전에서 삼각측량 우위는 미미** (+0.013 AUC, 6/8 시드). 방향은
   맞으나 효과가 작다 — **이것이 설계 문서가 경고한 "출처품질 평가가 시스템의
   가장 약한 실제 부품"이라는 주장을 실험으로 확인**한다.

즉, 화려한 GAN 구조는 동작하지만, 검색 결과의 출처 품질을 *자기보고에 기대지
않고* 평가하는 능력은 여전히 미해결 과제다 — 설계자가 정확히 예견한 지점.

`svmp/retrieval.py`의 `CorpusRetriever`가 실 retriever 인터페이스이며,
`Verifier(search_fn=...)`로 어떤 검색 백엔드(임베딩 DB, 웹 검색 등)든 주입 가능하다.

### 개선 시도 — robust 합의 집계 (`Verifier(aggregation="robust")`)

위 약점의 한 갈래(오도 출처가 집계 증거를 오염)를 겨냥해 **robust 합의 집계**를
TDD로 구현했다. *진실은 일관되고 거짓은 다양하다*는 가정 하에, 가장 많은 출처와
일치하는 medoid를 중심으로 합의 클러스터만 모아 집계 → 비일관 이상치(다양한 거짓)를
버린다. 평가지표는 **증거 정확도**(집계 증거가 진짜 클래스를 가리키는 비율), n=8 시드:

| 레짐 | mean 집계 | robust 집계 | Δ |
|------|-----------|-------------|---|
| **A — 적대적** (일관된 진실 / 코사인-다양 거짓) | 0.605 ± 0.031 | **0.642 ± 0.018** | **+0.037 (7/8)** |
| **B — 양성 실데이터** (digits 검색) | 0.871 ± 0.017 | 0.871 ± 0.017 | +0.000 (0/8) |

> 거짓 출처가 *반드시 틀린 클래스*를 가리키도록 시나리오를 정화한 수치다. 초기엔
> 거짓이 우연히 정답을 가리키는 12.5%가 효과를 +0.098로 부풀렸는데, 코드리뷰에서
> 지적받아 정화하니 정직한 효과는 **+0.037**로 줄었다.

**정직한 결론**: robust 집계는 *실패 모드가 존재하는 곳*(다양한 거짓)에서만
증거 정확도를 +0.04 회복하고, 양성 검색(digits — top-k가 이미 대부분 정답이라 전체
평균이 최적)에서는 **무해한 no-op**이다. 즉 만능 해법이 아니라 **기하학 의존적**
부분 개선이며, 디짓처럼 임베딩이 공통성분을 공유하는 양성 레짐에선 어떤 선택적
집계도 도움이 안 된다(평균-센터링은 오히려 −0.09로 악화). 이는 출처품질 평가가
*여전히 미해결*이라는 위 결론을 뒤집지 않고 **언제 무엇이 통하는지를 한정**한다.

`PYTHONPATH=. python examples/experiment_improvement.py` 로 두 레짐 모두 재현.

### 개선 시도 2 — 학습 가능한 출처 신뢰도 추정기 (`aggregation="learned"`)

고정 τ 휴리스틱 대신, 설계가 "없다"고 한 능력(*출처 품질을 학습으로 평가*)을 직접
구현했다. 작은 MLP가 출처별 특징(자기보고 신뢰도·상호 코사인 일치도·중심과의 유사도)
으로 가중치를 내고, 가중 집계 증거를 알려진 프로토타입으로 디코딩해 **외부에서 드러난
정답만으로** end-to-end 학습한다(출처별 신뢰 라벨은 절대 사용 안 함 — 배포 시 없으므로).

부분-정보성 신뢰 사전 + 다양한 거짓, held-out 평가, **n=8 시드**:

| 집계 | 사용 신호 | 증거 정확도 |
|------|-----------|-------------|
| mean | 신뢰 사전만 | 0.635 ± 0.030 |
| robust (고정 τ) | 일치도만 | 0.697 ± 0.024 |
| **learned** | 학습으로 융합 | **0.718 ± 0.023** |

**정직한 결론**: 학습된 추정기는 naive 신뢰-only를 분명히 이기고(+0.083, 8/8),
손튜닝 robust 휴리스틱도 **모듈하게 이긴다**(+0.022, 7/8). 외부 정답 신호만으로,
손으로 정한 τ 없이 신뢰+일치도를 융합해 학습한 결과다.

> ⚠️ 코드리뷰가 핵심 결함을 잡아냈다: 처음엔 학습은 코사인 디코더로, 평가는 L2 NN으로
> 해서 **목표·평가 지표가 어긋났고**, 이게 학습을 *손해* 보게 했다(learned 0.673,
> robust에 −0.023 패배). 평가에 쓰는 L2 거리로 학습 목표를 정렬하니 +0.045 올라
> 0.718로 robust를 역전했다. 지표 정렬 하나로 결론이 뒤집힌 것 — 적대적 리뷰가
> 없었으면 "robust가 최선"이라는 틀린 결론을 낼 뻔했다.

`PYTHONPATH=. python examples/experiment_learned_trust.py` 로 재현.

> **Phase 4 종합**: ① 기본 삼각측량은 무정보 사전에서 chance 근처 → ② robust 합의는
> 적대적 레짐에서만 +0.04 → ③ 학습 추정기는 (지표 정렬 후) naive·robust 모두 능가.
> 출처품질 평가는 어렵지만, *외부 정답 신호만으로 손튜닝 휴리스틱을 학습으로 따라잡고
> 넘어설 수 있다*는 건설적 결론에 도달.

---

## 테스트

```bash
pip install pytest
python -m pytest -q          # 34 passed
```

`tests/`는 예산 사망/회복, 게이트 차단, 확신도 보정, top-k 과금, 3-인자 갱신 조건,
실 retriever 출처품질, robust 합의 집계(이상치 무시·증거정확도 개선), 학습 추정기
(naive 베이스라인 능가), end-to-end 학습(정확도 > chance, 생존)을 검증한다.

---

## 한계 / 다음 단계

- `Verifier`의 외부 검색은 시뮬레이터 또는 `CorpusRetriever`(합성 코퍼스) — 실
  retriever(임베딩 DB·웹) 주입 가능하나 미연결
- robust 합의 집계는 거짓이 코사인-분리 가능한 기하에서만 유효 — 양성 검색엔 no-op
- 학습 추정기는 합성 적대적 레짐에서만 검증 — 실데이터·실 retriever 전이는 미검증
- 학습 추정기 효과는 modest(+0.02 vs robust); 지표 정렬에 민감(리뷰에서 발견)
- 과제는 합성 스캐폴드 + sklearn digits — 메커니즘 시연용이지 벤치마크 아님
- `SelfPlay`(Phase 5)는 배선만 문서화한 스켈레톤
- 적대적 역할 학습은 단일 옵티마이저 동시경사 근사 (정식 alternating minimax 아님)
