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
| `svmp/roles/verifier.py` | `Verifier` — 외부검색 + 출처품질 평가 (mean/robust/learned 집계) | §3,§4 |
| `svmp/roles/trust_estimator.py` | `SourceTrustEstimator` — 학습 가능한 출처 가중치 (엔트로피 prior) | §4 |
| `svmp/roles/adversarial.py` | `AdversarialLoop` — 건축가→수집가→검증가 루프 | §3 |
| `svmp/retrieval.py` | `CorpusRetriever`, `DocumentCorpus` — 합성 코퍼스 | §4 |
| `svmp/real_retriever.py` | `EmbeddingRetriever` + 20newsgroups·MiniLM 로더 — 실제 검색 | §4 |
| `svmp/selfplay.py` | `SelfPlayJudge`, `self_play` — Phase 5 정답키 없는 자기놀이 | §5 |
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
| 5 | 2층 자기놀이 (정답키 없음) | `selfplay.py` — 동결 심판 + keyless 3-인자 자기놀이 |

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

#### 전이 검증 — 실 retriever(digits)로 넘어가면? (`experiment_learned_real.py`)

합성 적대 레짐에서 통한 추정기를 **실제 digit 검색 코퍼스**로 전이했더니 처음엔
오히려 *손해*를 봤다 — **음의 전이**. 원인: 양성 검색(top-k가 이미 대부분 정답)에선
전체 평균이 최적인데, 추정기가 굳이 *선택적*으로 굴면서 유용한 신호를 버린다.

처방: **최대 엔트로피 prior**(`entropy_reg`, 기본 0.1) — 가중치를 기본적으로 균등(=평균)
쪽으로 당기고, *측정 가능하게 도움 될 때만* 집중하게 한다. n=6 시드:

| 레짐 | mean | robust | learned (reg=0) | learned (reg=0.1) |
|------|------|--------|------|------|
| 합성 적대 (홈그라운드) | 0.637 | 0.693 | — | **0.724** |
| 실 digits (양성) | 0.863 | 0.863 | 0.829 ❌ | **0.861 ✅** |

reg=0 추정기는 digits에서 −0.033 손해(음의 전이), reg=0.1은 −0.002로 **패리티 회복**
하면서 적대 레짐 이득(0.724)은 그대로다. 즉 추정기는 *기본은 평균, 필요할 때만 선택*.

#### 실제 연결 — 진짜 텍스트·임베딩·검색 (`experiment_real_retriever.py`)

합성 코퍼스를 버리고 **완전한 실제 파이프라인**을 붙였다:
- 실 문서: **20 Newsgroups** 뉴스그룹 글
- 실 임베딩: **sentence-transformer all-MiniLM-L6-v2** (384-d)
- 실 검색: 코사인 top-k (`svmp/real_retriever.py::EmbeddingRetriever`)
- 실 감독: 쿼리 글의 진짜 주제 (test 글이 train 코퍼스를 검색 → self-match 없음)

서로 다른 주제(양성) vs 혼동되는 주제(적대) 두 레짐 — **n=12 random split, paired**
(`experiment_real_significance.py`):

**CONFUSABLE (적대, comp.* 4종, on-topic 0.67):**

| 비교 | Δ (n=12) | 승률 | t | 결론 |
|------|----------|------|-----|------|
| learned − mean | **−0.002 ± 0.006** | 5/12 | −0.96 | ❌ 유의하지 않음 |
| learned − robust | +0.052 ± 0.008 | 12/12 | +23.3 | ✅ 매우 유의 |
| robust − mean | −0.053 ± 0.009 | 0/12 | −20.1 | ✅ 매우 유의 |

**DISTINCT (양성, on-topic 0.90):** 세 비교 모두 |Δ|<0.002, |t|<1 → 통계적으로 동일.

**실데이터가 드러낸 것 (엄밀):**
1. ❌ **learned는 mean 대비 성능 증대 없음** (Δ=−0.002, t=−0.96). 합성서 mean을 +0.08
   이기던 이득이 실데이터로 **전이 안 됨** — 단일 split의 +0.005는 노이즈였다(코드리뷰가
   단일 시드 과장을 지적 → n=12로 확인).
2. ✅ **손튜닝 robust는 실 적대 검색에서 확실히 손해** (Δ=−0.053, t=−20, 0/12). 합성서
   좋아 보이던 휴리스틱의 **sim2real 격차** — 경직된 τ 합의가 실데이터선 유용 신호를 버린다.
3. ✅ **learned > robust** (Δ=+0.052, 12/12). 단 이는 learned가 mean과 같고 robust가
   mean보다 나빠서지, learned가 mean을 넘어서가 아니다.

**정직한 결론**: 실데이터에선 **단순 평균(mean)이 강력한 베이스라인**이고 어떤 정교한
집계도 이를 통계적으로 못 넘는다. 학습 추정기의 가치는 *성능 증대*가 아니라 **안전성**
— robust처럼 망가지지 않고 항상 mean과 동급을 지킨다. 실행:
`pip install -r requirements-real.txt && PYTHONPATH=. OMP_NUM_THREADS=1 \
python examples/experiment_real_retriever.py`(단일 split 예시) ·
`… experiment_real_significance.py`(n=12 검정)
(임베딩은 `examples/.cache/`에 캐시).

> **Phase 4 종합 (5단계)**: ① 기본 삼각측량 → 무정보 사전서 chance 근처 · ② robust 합의
> → 합성 적대만 +0.04 · ③ 학습 추정기 → (지표 정렬 후) 합성서 naive·robust 능가 ·
> ④ 엔트로피 prior → 음의 전이 차단 · ⑤ **실 retriever(n=12) → mean이 강력해 learned는
> 증대 없음(≈mean), robust는 실 적대서 유의하게 손해**. 결론: 합성서 보이던 이득은
> 실데이터로 전이되지 않고 단순 평균이 강한 베이스라인이다. 학습 추정기의 실데이터
> 가치는 *성능 증대*가 아니라 **안전성**(robust처럼 망가지지 않음)이며, 손튜닝 휴리스틱의
> sim2real 격차를 실험으로 드러낸 것이 핵심 교훈.

### Phase 5 — 정답키 없는 자기놀이 (`experiment_selfplay.py`)

설계 §5: 정답키 없는 도메인엔 외부 oracle이 없으니 **Phase-1에서 외부 검증으로 grounded된
심판을 동결**해 pseudo-reward로 쓴다. ① 정답키 단계서 reward model(`SelfPlayJudge`)
학습 → ② 결정헤드 리셋(정확도 붕괴) → ③ **라벨 없이** 동결 심판의 보상으로 3-인자 자기놀이.
n=5 시드:

| 단계 | 정확도 |
|------|--------|
| Phase-1 학습 (상한) | 0.947 ± 0.008 |
| 결정헤드 리셋 (바닥) | 0.170 ± 0.167 |
| **keyless 자기놀이 — grounded 심판** | **0.904 ± 0.074** |
| keyless 자기놀이 — 랜덤 심판 (대조군) | 0.165 ± 0.205 |

**정직한 결론:**
1. ✅ **동결 grounded 심판으로 정답키 없이 학습 가능** — 바닥 0.17 → 0.90 복구(라벨 0개 사용).
2. ✅ **랜덤 심판은 바닥 유지(0.165)** → 자기놀이 자체가 아니라 **grounding이 가르친다**.
3. ⚠️ **상한 격차 −0.043** → 자기놀이는 심판을 못 넘는다. *외부 grounding 너머로는
   부트스트랩 불가* — SVMP "보상은 외부에서만" 원칙과 일치(self-reward 붕괴 회피).

---

### Phase 6 — 파국적 망각 검증 (`experiment_continual.py`)

설계의 **중심 주장**: 게이트형 통합(닫힌 게이트 → 가중치 동결) + 외부 vault(옛 컨텍스트
회수)가 **안정성-가소성 딜레마**를 푼다 — 새 과제를 배워도 옛 지식이 안 망가진다.
이 주장을 직접 시험한다. 8클래스를 2개 과제로 분할(A={0–3}, B={4–7})해 A→B 순차 학습 후
**A 정확도가 얼마나 붕괴**하는지 측정. 망각 = (A 학습 직후 A정확도) − (B까지 학습 후 A정확도).
0=완전 보존, ~1=완전 파국적 망각. chance=0.25, n=4 시드:

| 조건 | A 학습직후 | 망각 (±sd) | 최종 평균 |
|------|-----------|-----------|-----------|
| full (vault+게이트) | 0.998 | **+0.942** (±0.059) | 0.523 |
| no_vault (메모리 제거) | 0.998 | +0.962 (±0.033) | 0.478 |
| no_gate (게이트 강제 개방) | 0.993 | +0.939 (±0.100) | 0.523 |

**정직한 결론 (중심 주장 반증):**
1. ❌ **현 아키텍처는 안정성-가소성을 풀지 못한다.** 각 과제는 천장(0.99)까지 배우지만,
   다음 과제가 오면 옛 과제를 **거의 완전히 망각**(+0.94)한다. 공유 결정헤드·표현이 새
   과제로 재특화된다.
2. ❌ **vault 이점 +0.02** — 외부 메모리가 망각을 막지 못한다. 회수값은 *문맥*으로 융합될
   뿐 표류한 결정헤드를 되돌리지 못하고, decay가 옛 항목까지 지운다(지평 민감도 실험:
   B를 100스텝만 학습해도 이미 +0.4–0.5 망각, vault 이점은 ±0.1로 부호조차 불안정).
3. ❌ **게이트 보호 효과 없음** — 게이트를 강제 개방(no_gate)해도 망각이 안 늘어난다.
   3-인자 게이팅은 *가소성*을 조절할 뿐, 옛 가중치를 *선택적으로 보호*하지 않는다.

#### 원인 해부 — 망각은 어디서 오는가? (`diagnose_forgetting.py`)

결정헤드(3-인자)와 표현(encoder+MoE+fuse, backprop)은 학습 경로가 분리돼 있다. A 학습 후
두 경로를 스냅샷 → B까지 학습 후 **한 경로씩 post-A로 되돌려** task-A 회복량 측정. n=4:

| 복원 | task-A 정확도 | 회복 |
|------|--------------|------|
| post-B 그대로(baseline) | 0.036 | — |
| **표현만 복원** | **0.918** | **+0.882** |
| 결정헤드만 복원 | 0.497 | +0.462 |
| 둘 다(sanity) | 0.992 | — |

- ✅ **망각은 주로 backprop 표현**의 재특화에서 온다(표현 복원이 0.88 회복, 헤드는 0.46).
- ✅ **vault 키는 안정적** — task-A 쿼리의 최근접 키 코사인 0.938→0.912(−0.026). 즉 회수는
  *옳은 항목을 찾는다*. vault 실패 원인은 키 표류가 아니라, 회수값이 *표류한 표현*을 거쳐
  *부드러운 문맥*으로만 융합되는 배선이다.

#### 설계적 수정 — 검증 사실의 직접 투표 (`experiment_continual_fix.py`)

진단이 가리키는 수정: 설계 원칙("검증 지식은 통합·회수되어 결정에 반영")을 충실히 따르되
**표현을 우회**한다. `LabelVault`가 검증된 (입력영역→클래스)를 저장하고 **로짓에 직접 투표**,
검증 항목은 **decay 안 함**(옛 과제 사실 영구 보존). `direct_vote=True`로 활성화. n=4:

| 시퀀스 | baseline 망각 | **fix 망각** | 최종 정확도 |
|--------|--------------|-------------|------------|
| 2과제(8cls) | +0.942 | **+0.407** (±0.203) | 0.523 → **0.790** |
| 3과제(9cls) | +0.885 | **+0.170** (±0.114) | 0.402 → **0.883** |

- ✅ **망각 ~2×(2과제, 분산 큼)–5×(3과제) 감소**, 최종 정확도 0.40→0.88. peak-A는 0.998 유지
  → **가소성 손상 없이** 안정성 확보. 신선한 샘플 평가라 점 암기가 아니라 코사인 영역 회상.
- ✅ **핵심 결론**: **설계의 메모리 원칙은 결정에 닿기만 하면 옛 과제를 지킨다** — 원판의
  soft-context 융합은 못 했다. 투표 품질은 검증 신호(외부 reward/동결 심판)에 종속.

#### 한계 — 어디서 무너지는가 (`experiment_forgetting_limits.py`)

수정의 전제를 의도적으로 깬다. `PermutedLabelTask`: 모든 과제가 **같은 입력 영역**을 쓰되
**라벨 순열이 다름**(영역 r은 task0에서 r, task1에서 π[r]) — 같은 입력, 다른 정답. n=4:

| 과제 | fix 최종 Δ | 키 표류(코사인 A→B) | 투표 단독 task-0 정확도 |
|------|-----------|--------------------|----------------------|
| Split(분리 가능) | **+0.267** | 0.822 | **0.979** |
| Permuted(라벨 충돌) | **−0.009** | 0.969 | **0.451** |

- ❌ **충돌 라벨에선 수정이 무효**(최종 Δ −0.009) — baseline으로 *퇴화*하되 더 나빠지진 않음.
- 🔬 **내 키-표류 가설은 데이터로 반증**: Permuted가 오히려 *더* 키-안정적(0.97 vs 0.82) —
  입력 분포가 과제 간 동일하므로. 원인은 순수 **라벨 충돌**이다.
- 🔬 **메커니즘**(계측): 각 입력 영역이 두 과제의 라벨 엔트리를 함께 쌓고, 회수는 어느 한
  과제 라벨로 **임의 commit**(여기선 task0:task1≈5:3). 그 결과 메모리 단독 task-0 정확도가
  0.98(분리)→0.45(충돌)로 붕괴 — 한 과제를 돕는 만큼 다른 과제를 해쳐 상쇄된다.
- ➡️ **함의**: 문맥 없는 input→class 메모리는 도메인 증분(충돌 매핑)을 풀 수 없다. 진짜 해법은
  **과제/문맥 키**(투표에 컨텍스트를 더해 어느 매핑인지 선택)거나 컨텍스트 게이팅 — 다음 후속.

#### 컨텍스트 키 — 충돌을 해결한다 (`experiment_context_key.py`)

part 3의 함의를 실행: `LabelVault`에 **컨텍스트 벡터**를 추가해, 투표를 입력 영역 *그리고*
컨텍스트가 둘 다 맞을 때만 집계(`ctx_dim>0`). 컨텍스트를 세 방식으로 공급, **동일 prequential
(예측→관측, 가중치 학습 없음) 평가**, Permuted n=4:

| 컨텍스트 | task-A | task-B | mean |
|----------|--------|--------|------|
| 없음(part 3) | 0.452 | 0.714 | 0.583 |
| **오라클**(과제 ID) | 0.753 | 0.990 | **0.872** |
| **추론**(보상 스트림) | 0.526 | 0.866 | 0.696 |

- ✅ **오라클 컨텍스트가 충돌을 해결**(0.58→0.87) — 즉 충돌형 망각은 *용량* 문제가 아니라
  **컨텍스트 키** 문제다. (오라클조차 task-A 0.75<task-B 0.99인 건, 완벽한 컨텍스트도 옛 과제에선
  B로 표류한 표현을 vote로 *덮어써야* 하기 때문.)
- ⚠️ **추론 컨텍스트는 부분 해결**(오라클 이득의 ~39% 회복). 과제 ID 없이 **보상 붕괴 체제전환
  감지**(`ContextInferrer`)로 슬롯을 할당 — task-A retention 0.45→0.53로 오르지만 오라클 0.75엔
  못 미침. 감지기가 과분절(~2.2회, 이상은 1회)해 일부 task-A 엔트리가 엉뚱한 슬롯에 태깅됨.
- 🔬 **정직한 한계**: 입력 분포가 과제 간 동일하므로 과제 정체성은 *보상 contingency*로만 관측
  가능 → 무피드백 단발 추론은 원리적으로 모호. task-free 추론은 노이지하고 부분만 풀림. 또
  forward-only 감지기는 **되돌아온 컨텍스트**(B→A) 재인식 불가 — 아래 part 5에서 해결.

#### 컨텍스트 재인식 — 되돌아온 과제 (`experiment_context_recognition.py`)

forward 추론은 변화마다 *새* 슬롯을 할당하므로 과제가 **되돌아오면**(B→A) 빈 컨텍스트에 떨어져
다시 망각한다. 재인식의 본질은 변화를 *감지*함이 아니라 어느 컨텍스트인지 *식별*함 — 그래서
경계 신호는 주되 **정체는 숨기고**, 깨끗이 태깅된 메모리에서 복귀 스트림 A→B→A→B를 재인식하는지
격리 측정. 입력은 모든 컨텍스트가 같은 영역을 공유해 무신호 → 식별은 **보상 프로빙**으로만 가능:
경계마다 알려진 슬롯+새 슬롯을 짧게 시도해 보상 최고를 채택(`RecognizingContextManager`). n=4,
prequential, A2*/B2*는 **되돌아온** 세그먼트:

| 컨텍스트 | A2* | B2* | 복귀 mean | probe |
|----------|-----|-----|-----------|-------|
| 오라클(정체 앎) | 0.750 | 0.995 | **0.872** | 0 |
| forward(새 슬롯) | **0.160** | 0.735 | 0.447 | 0 |
| **재인식**(경계 줌, 보상 프로빙) | 0.703 | 0.950 | **0.827** | 210 |
| **auto**(경계 없음, 완전 task-free) | 0.678 | 0.760 | **0.719** | 360 |

- ✅ **재인식이 복귀 망각을 복원**: A2 0.16→0.70, 복귀 mean 0.447→0.827 — 오라클(0.872) 대비
  **갭의 89% 회복**. 과제 ID 없이 보상만으로 옛 과제의 원래 슬롯을 재선택.
- ✅ **감지+프로빙 합성도 흡수**(auto, 경계조차 없음): 자체 붕괴감지기가 프로빙을 구동해 0.719 —
  forward 0.447보다 훨씬 위. **프로빙이 감지 노이즈를 흡수**: 오발 시 *현재 슬롯*을 한 윈도우만에
  early-accept(싼 재프로빙) → 노이즈가 망각이 아니라 프로빙 비용이 됨.
- ⚠️ **이제 감지가 병목**: auto가 천장(0.827)에 못 미치는 잔여 갭은 감지 비용(발화 지연+잔여
  오발 프로빙)이다. **재인식이 가장 큰 가치를 더하고, 감지가 다음 병목**. (재인식 격리를 위해
  recognise는 경계를 가정; auto는 그 가정을 제거한 완전 task-free.)

---

## 신기술 애드온 (2024–2026 SOTA, 전부 opt-in·기본 OFF)

웹검색으로 조사·검증한 최신 기법 6종을 각 서브시스템에 도입했다. **전부 기본 OFF**(플래그/임계)라
켜지 않으면 기존 동작·실험·테스트가 바이트 동일 — 무회귀. 각 항목은 전용 실험으로 전/후를 측정한다.

| 애드온 | 근거 기법 (논문) | 모듈 / 켜는 법 | 측정된 효과 (전 → 후, n=4) |
|--------|------------------|----------------|---------------------------|
| **BOCD 변화감지** | Bayesian Online Changepoint Detection (Adams&MacKay'07, arXiv:0710.3742; Beta-Bernoulli/MOCA) | `context.py:BOCDDetector`, `ContextInferrer(detector='bocd')` | ✅ revisit 0.719(EMA)≈**0.696**을 **probe 360→194(−46%)** 로. 손튜닝 임계 0개 |
| **Benna-Fusi 메타가소성** | metaplasticity (Zenke&Laborieux, arXiv:2405.16922) | `learning/three_factor.py`, `LearningConfig.metaplastic` | ✅ 헤드 망각 +0.962→**+0.903**, 최종 0.478→**0.541** |
| **무손실 MoE 균형** | aux-loss-free balancing (DeepSeek, arXiv:2408.15664) | `moe.py` expert_bias, `MoEConfig.loss_free_balance` | ✅ 부하불균형 MaxVio 0.118→**0.028(4.2×)**, 정확도 −0.003 |
| **보정-게이트 검증** | entropy/conformal abstention + ACI (arXiv:2401.12708) | `calibration.py`+`adversarial.py`, `uncertainty_gate`, `verify_uncertainty_tau` | ◐ Split: acc 0.880→**0.889**, ECE 0.069→**0.055**, 검색비용↑ (품질↔연산 노브) |
| **AMR 드리프트 정렬** | Adaptive Memory Realignment (Ashrafee'25, arXiv:2507.02310) | `label_vault.py:realign_region`, `tasks.py:ConceptDriftTask`, `amr` | ✅ 드리프트영역 acc 0.833→**0.893**, 비드리프트 0.99 유지, vault 257 보존(blanket-decay는 10으로 붕괴) |
| **드리프트 보정 (SDC)** | Semantic Drift Compensation (Yu'20, arXiv:2004.00440) — 전역선형 LDC(Gomez-Villa'24, arXiv:2407.08536) 회귀를 대체 | `label_vault.py:realign_sdc`, `drift_realign` | ✅ 망각 0.262→0.235, 키-드리프트 cos 0.723→0.736 (전역선형은 0.75/0.49로 역효과였음) |

**스코어카드**: 명확한 승리 5종(BOCD·Benna-Fusi·MoE·AMR·SDC) + 유용한 노브 1종(보정 게이트).
모두 전용 실험(`examples/experiment_*.py`)으로 재현 가능.

- **BOCD**가 part-5에서 지목한 *감지 병목*을 직접 공략: EMA의 손튜닝 `drop/established` 임계를
  hazard 사전 하나로 대체하고, **MAP run-length 리셋** 신호로 동등 정확도를 절반 연산에 달성.
- **드리프트 보정의 교훈**(측정으로 갈림): 같은 "키가 낡았다" 문제에서 *전역 선형 재투영*(LDC)은
  현재-과제 입력으로 적합해 옛-과제 키를 외삽 → **역효과**(0.26→0.75)였다. *영역-국소 드리프트*
  (SDC, 앵커 기반)로 바꾸자 부호가 뒤집혀 **유효**(0.26→0.235)해졌다. AMR(영역 선택 제거)도
  같은 "국소가 전역을 이긴다" 원리.

---

## 표준 방법과의 비교 — "실제 일반 사용법"과 얼마나 다른가 (`experiment_vs_baselines.py`)

이 모든 기계장치가 실무자가 *실제로 쓰는* 표준 도구보다 나은지 정면 검증. 동일 과제·스텝·시드·
온라인(1샘플) 조건, n=4. **joint(i.i.d. 상한)** · **naive 순차** · **replay(저수지 버퍼, 실무
표준)** · **EWC(고전 정규화)** · **SVMP direct_vote**.

**[A] Class-incremental (분리 클래스, SplitContinualTask)** — chance 0.12:

| 방법 | 망각 | 최종 acc | 비용/가정 |
|------|------|----------|-----------|
| joint (i.i.d.) 상한 | — | 0.991 | 전 데이터 혼합(CL 아님) |
| naive 순차 | +0.880 | 0.557 | 바닥 |
| **replay** | **+0.012** | **0.990** | 원시 (x,y) 저장 |
| EWC | +0.862 | 0.565 | 과제 경계 필요 |
| **SVMP** | +0.407 | **0.790** | 검증 키+라벨, 경계 불요 |

**[B] Domain-incremental (라벨 충돌, PermutedLabelTask)** — 같은 입력, 다른 정답:

| 방법 | 망각 | 최종 acc |
|------|------|----------|
| joint (i.i.d.) 상한 | — | **0.572** (본질적 모호) |
| naive 순차 | +0.836 | 0.575 |
| replay | +0.532 | 0.560 |
| EWC | +0.834 | 0.575 |
| SVMP | +0.571 | 0.562 |

**정직한 결론 — 격차는 레짐에 전적으로 의존:**
- **[A] 분리 클래스에선 평범한 replay가 압승**(0.99 ≈ 상한). SVMP(0.79)는 naive(0.56)·EWC(0.57)를
  **명확히 능가하나 replay엔 못 미침** — 소수 예시만 재생하면 풀리는 문제다.
- **[B] 충돌 라벨에선 i.i.d. 상한조차 0.57**로 낮고 **replay도 우위 상실**(0.56, 망각 +0.53) —
  (x, 옛라벨) 재생이 (x, 새라벨)과 모순되기 때문. **컨텍스트 신호 없이는 어떤 방법도 못 이긴다**;
  SVMP도 ≈ 동급. 이게 바로 part 4–5의 컨텍스트 키가 겨냥한, *표준 replay마저 무너지는* 지점.
- **요지**: SVMP는 표준 도구의 *리그 안*(naive·EWC 능가)이지만 replay가 통하는 곳에선 replay를
  못 이긴다. 차별점은 **가정 프로파일**(경계 불요·원시입력 버퍼 없음·검증 전용)과 **충돌 레짐**이다.

### 조합 — 표준 replay + SVMP의 컨텍스트 키 (`experiment_hybrid.py`)

위 [B]에서 replay·SVMP가 *둘 다* 무너진 이유는 컨텍스트 부재였다(part 4–5). 그렇다면 그 컨텍스트를
*표준 도구에 붙이면* 되살아나는가? 오라클 컨텍스트로 검증 (n=4):

| 방법 | [A] 분리 클래스 | [B] 충돌 라벨 |
|------|----------------|---------------|
| replay | 0.990 | 0.560 |
| **replay + context** | 0.993 | **0.985** |
| SVMP vote | 0.790 | 0.562 |
| **SVMP vote + context** | 0.898 | **0.899** |

- ✅ **조합이 정답**: 충돌 레짐에서 컨텍스트 키를 붙이면 *어느 방법이든* 실패→성공으로 뒤집힌다
  — plain replay 0.56→**0.985**, SVMP vote 0.56→**0.90**. 분리 클래스([A])에선 컨텍스트가
  무해(redundant).
- 🔑 **누가 무엇을 기여하나**: 강한 운반체는 *표준 replay*(0.985 > vote 0.90)이고, 빠진 재료는
  *컨텍스트* — 그리고 그 컨텍스트를 **과제 ID 없이 보상 스트림에서 발견**하는 것이 SVMP part 4–5의
  연구 기여다(오라클 없이는 ~부분 해결). 즉 **SVMP의 컨텍스트 모듈을 replay에 이식하면, 평범한
  일꾼이 깨지던 레짐을 구제**한다. 가장 약한 부품은 vote가 아니라, "검증된 컨텍스트를 task-free로
  얻는" 능력이라는 게 정직한 결론.

---

## 테스트

```bash
pip install pytest
python -m pytest -q          # 104 passed
```

`tests/`는 예산 사망/회복, 게이트 차단, 확신도 보정, top-k 과금, 3-인자 갱신 조건,
출처품질 평가, robust 합의 집계(이상치 무시·증거정확도 개선), 학습 추정기(naive 능가·
엔트로피 정규화), 실 EmbeddingRetriever(코사인 top-k), Phase 5 자기놀이(grounded 심판
복구 vs 랜덤 심판), end-to-end 학습(정확도 > chance, 생존), 연속학습 harness·ablation
손잡이·망각 지표·LabelVault 직접투표·컨텍스트 키 분리·ContextInferrer 체제전환·
RecognizingContextManager 보상 프로빙 재인식·early-accept 흡수(Phase 6 + 후속), 그리고
신기술 애드온 6종(BOCD 변화감지·Benna-Fusi 메타가소성·무손실 MoE 균형·entropy/conformal
보정·AMR 영역 정렬·SDC 드리프트 보정 — 전부 default-OFF 무회귀 포함)을 검증한다.
실 retriever 실험은 다운로드가 필요해 테스트엔 미포함.

---

## 한계 / 다음 단계

- 실 retriever 연결됨(`EmbeddingRetriever` + 20newsgroups·MiniLM); 웹 검색 API는 미연결
- 손튜닝 robust는 실 적대 검색에서 손해(sim2real 격차) — learned가 더 안전
- robust 합의 집계는 거짓이 코사인-분리 가능한 기하에서만 유효 — 양성 검색엔 no-op
- 학습 추정기 효과는 modest(+0.02 vs robust); 양성 검색엔 엔트로피 prior로 패리티만
  (이득 없음). 실데이터 검증은 합성 코퍼스(`DocumentCorpus`) 한정 — 실 임베딩 DB·웹 미연결
- 과제는 합성 스캐폴드 + sklearn digits — 메커니즘 시연용이지 벤치마크 아님
- Phase 5 자기놀이는 동결 reward-model 증류 — 심판 품질이 상한(설계 의도). 표현은
  동결하고 결정헤드만 재학습 — 표현까지 키우는 keyless 학습은 후속 과제
- 적대적 역할 학습은 단일 옵티마이저 동시경사 근사 (정식 alternating minimax 아님)
- **파국적 망각**(Phase 6): 원판 vault·게이트만으론 순차 과제 망각 못 막음(+0.94, 중심 주장
  반증). 진단 결과 망각은 backprop 표현 재특화가 주범, vault 키는 안정. **수정**(`direct_vote`:
  검증 사실의 decay-free 직접 투표)으로 **영역 분리형** 망각 ~2–5× 감소·최종 0.40→0.88. 단
  **라벨 충돌형**(도메인 증분)에선 무효(최종 Δ−0.01). **컨텍스트 키**(`ctx_dim`)로 충돌도
  해결됨을 증명(오라클 0.58→0.87); 과제 ID 없는 **추론 컨텍스트**는 부분 해결(~39%), **보상
  프로빙 재인식**으로 되돌아온 과제(B→A) 복원은 갭의 89%(경계 줌). 완전 task-free 합성(감지+프로빙)도
  0.72로 망각 흡수 — 잔여 병목은 이제 *감지*(`RecognizingContextManager`). 이 감지 병목은
  **BOCD 애드온**으로 일부 완화(동등 정확도·절반 연산, 위 *신기술 애드온* 참조)
- **드리프트 보정**: 장기 인코더 드리프트로 decay-free 키가 자기 영역을 빗나가는 문제. 전역 선형
  재투영(LDC)은 옛-과제 키 외삽으로 역효과였고(0.26→0.75), **영역-국소 SDC**(앵커 기반)로
  교체해 유효(0.26→0.235)해짐. 효과는 modest(합성 과제의 인코더 드리프트가 작음) — 더 큰
  드리프트 레짐·실데이터에서의 검증은 후속. opt-in(`drift_realign`)이라 기본 경로엔 무영향
