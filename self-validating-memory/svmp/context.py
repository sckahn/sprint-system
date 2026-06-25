"""Task-free context inference from the reward stream (Phase-6 part 4).

The context-keyed ``LabelVault`` resolves conflicting label mappings *if* it is
told which task it is in. But in domain-incremental learning with an identical
input distribution across tasks (``PermutedLabelTask``), the task identity is not
observable from the input at all — only the *reward contingency* changes. So a
task-free agent must infer context from its own prediction-error dynamics: when
it suddenly starts being punished on inputs it used to get right, the regime has
shifted and a new context should be allocated.

``ContextInferrer`` is a minimal change-point detector over the reward stream. It
emits a one-hot context vector and rotates to a fresh slot when a sustained
accuracy collapse signals a regime change. It segments an A→B→… stream into
distinct contexts without a task oracle. ``RecognizingContextManager`` extends
this with reward-probing so a *returned* context (B→A) re-selects its original
slot instead of allocating a new one (`experiment_context_recognition.py`).
"""
from __future__ import annotations

import torch


class BOCDDetector:
    """Bayesian Online Changepoint Detection over the binary reward stream.

    EMA 기반 collapse 검출기(``ContextInferrer``의 ``fast < slow - drop``)는
    drop/established 같은 임계값을 손으로 맞춰야 하고, 느린 EMA가 새 regime을
    쫓아가기 전까지 발화가 지연된다. 대안으로 Adams & MacKay 2007의
    Bayesian Online Changepoint Detection (BOCD)을 쓴다: 매 스텝마다
    *run-length* (마지막 changepoint 이후 경과 스텝 수)의 posterior를 정확히
    갱신하고, run_length==0 의 사후 질량이 곧 "지금 막 바뀌었다"는 확률이다.

    Adams & MacKay 2007, "Bayesian Online Changepoint Detection",
    https://arxiv.org/abs/0710.3742. 보상 스트림은 이진(맞음/틀림)이므로
    각 run-length 가설마다 Beta-Bernoulli 켤레(conjugate) predictive 를 두는
    MOCA 틀(Titsias et al. 2020, https://arxiv.org/abs/1912.08866)을 따른다:
    run-length r 의 예측 확률은 그 run 안에서 누적한 (alpha, beta) 로부터
    ``p = a / (a + b)`` 로 닫힌 형태(closed form)다.

    상태:
      * ``rl`` — run-length 사후분포 (정규화된 텐서).
      * ``a``, ``b`` — run-length 별 Beta 충분통계(보상 1/0 누적 카운트).
    ``observe`` 는 한 번의 이진 보상을 받아, run_length==0 의 사후 질량이
    ``min_change_prob`` 이상이고 warmup 을 지났을 때 True(=regime 변경)를 낸다.
    """

    def __init__(self, hazard: float = 1 / 200, alpha0: float = 1.0,
                 beta0: float = 1.0, warmup: int = 80, max_run: int = 300,
                 min_change_prob: float = 0.5, change_window: int = 5):
        self.hazard = hazard
        self.alpha0 = alpha0
        self.beta0 = beta0
        self.warmup = warmup
        self.max_run = max_run
        self.min_change_prob = min_change_prob
        # ``rl[0]`` 만으로는 한 스텝당 changepoint 사후가 hazard 수준에 머물러
        # (Adams-MacKay 재귀의 성질) 임계 0.5 에 닿지 않는다. 그래서 "방금
        # 리셋됐다"는 신호를 가장 짧은 run-length 들의 사후 질량 합으로 본다:
        # P(run_length < change_window). changepoint 직후 이 값이 급등한다.
        self.change_window = change_window
        self.reset()

    def reset(self) -> None:
        self.t = 0
        # run-length 사후는 r=0 한 점에서 시작; Beta 사전(alpha0, beta0).
        self.rl = torch.ones(1)
        self.a = torch.tensor([self.alpha0])
        self.b = torch.tensor([self.beta0])

    def observe(self, reward01: float) -> bool:
        """이진 보상 하나를 받아 run-length 사후를 갱신; changepoint면 True.

        run_length==0 의 사후 질량이 ``min_change_prob`` 이상이고 warmup 을
        지났을 때만 발화한다. warmup 가드는 EMA 검출기와 동일하게, 학습 초기
        정확도가 낮지만 *상승 중*일 때의 거짓 경보를 막는다.
        """
        self.t += 1
        x = 1.0 if reward01 >= 0.5 else 0.0
        # 각 run-length 가설의 Beta-Bernoulli predictive.
        p_pred = self.a / (self.a + self.b)
        lik = p_pred if x >= 0.5 else (1.0 - p_pred)
        # changepoint 가설(r=0)은 사전 predictive 로 이번 보상을 평가한다(표준
        # BOCD): 이미 자신만만한 run 의 우도가 아니라, 새 run 의 prior 우도.
        p0 = self.alpha0 / (self.alpha0 + self.beta0)
        lik0 = p0 if x >= 0.5 else (1.0 - p0)
        # growth: run-length 가 1 늘어 살아남는 질량; cp: changepoint 로 r=0 으로.
        growth = self.rl * (1.0 - self.hazard) * lik
        cp_mass = (self.rl * self.hazard * lik0).sum().reshape(1)
        new_rl = torch.cat([cp_mass, growth])
        new_rl = new_rl / new_rl.sum()
        # Beta 충분통계: r=0 에 사전을 prepend, 살아남은 run 들은 이번 보상으로 증분.
        new_a = torch.cat([torch.tensor([self.alpha0]), self.a + x])
        new_b = torch.cat([torch.tensor([self.beta0]), self.b + (1.0 - x)])
        # max_run 초과 시 사후 질량 상위-K 만 유지(가지치기)해 메모리를 묶는다.
        if new_rl.numel() > self.max_run:
            keep = torch.topk(new_rl, self.max_run).indices
            keep = keep.sort().values
            new_rl = new_rl[keep]
            new_rl = new_rl / new_rl.sum()
            new_a = new_a[keep]
            new_b = new_b[keep]
        self.rl, self.a, self.b = new_rl, new_a, new_b
        # changepoint 신호: 가장 짧은 run-length 들의 사후 질량(=방금 리셋됐을 확률).
        change_prob = float(self.rl[:self.change_window].sum())
        return bool(change_prob >= self.min_change_prob and self.t > self.warmup)


class ContextInferrer:
    def __init__(self, ctx_dim: int = 6, fast: float = 0.2, slow: float = 0.02,
                 drop: float = 0.3, warmup: int = 80, established: float = 0.55,
                 detector: str = 'ema'):
        self.ctx_dim = ctx_dim
        self.afast = fast
        self.aslow = slow
        self.drop = drop
        self.warmup = warmup
        self.established = established
        self.detector = detector
        self.reset()

    def reset(self) -> None:
        self.slot = 0
        self.fast: float | None = None
        self.slow: float | None = None
        self.t_since_switch = 0
        self._bocd = BOCDDetector(warmup=self.warmup) if self.detector == 'bocd' else None

    def context(self) -> torch.Tensor:
        v = torch.zeros(self.ctx_dim)
        v[self.slot] = 1.0
        return v

    def observe(self, reward01: float) -> bool:
        """Feed the latest outcome (1.0 correct, 0.0 wrong). Returns True on switch.

        A regime change is declared only when we *were* doing well on the current
        context (slow baseline established above ``established``) and the fast EMA
        then collapses well below it. Gating on a high baseline avoids false
        switches during the noisy learning phase, when accuracy is low but rising.

        ``detector='bocd'`` 일 때는 EMA collapse 술어를 BOCD 의 changepoint
        확률로 대체한다(warmup 가드는 유지). 기본 ``'ema'`` 는 기존 동작 그대로.
        """
        if self.fast is None:
            self.fast = self.slow = reward01
        self.fast += self.afast * (reward01 - self.fast)
        self.slow += self.aslow * (reward01 - self.slow)
        self.t_since_switch += 1
        if self._bocd is not None:
            collapsed = self._bocd.observe(reward01)
        else:
            collapsed = (self.slow > self.established
                         and self.fast < self.slow - self.drop)
        if (self.t_since_switch > self.warmup
                and collapsed
                and self.slot < self.ctx_dim - 1):
            self.slot += 1
            self.t_since_switch = 0
            self.fast = self.slow = reward01     # rebaseline on the new regime
            if self._bocd is not None:
                self._bocd.reset()
            return True
        return False


class RecognizingContextManager:
    """Context manager that RE-RECOGNISES a returned context via reward probing.

    The forward-only :class:`ContextInferrer` allocates a *fresh* slot at every
    regime change, so revisiting an earlier task (B→A) lands on an empty context
    and forgets it again. Because conflicting tasks share the same input regions,
    context is observable only through reward — there is no input-only signal to
    re-identify the old task. So on a detected collapse this manager *probes* each
    known slot (plus one fresh slot) for a short window and adopts whichever yields
    the best reward, re-selecting an earlier task's original slot when it returns.

    Slot ids are allocated in first-encounter order (0, 1, …); the experiment tags
    the memory in the same order, so a probed slot id refers to the same context.
    """

    def __init__(self, ctx_dim: int = 6, probe_steps: int = 25, fast: float = 0.2,
                 slow: float = 0.02, drop: float = 0.3, warmup: int = 80,
                 established: float = 0.55, auto_detect: bool = True,
                 accept: float = 0.6, detector: str = 'ema'):
        self.ctx_dim = ctx_dim
        self.probe_steps = probe_steps
        self.afast = fast
        self.aslow = slow
        self.drop = drop
        self.warmup = warmup
        self.established = established
        self.auto_detect = auto_detect          # False ⇒ search only on force_search()
        self.accept = accept                    # early-accept the current slot if it
        self.detector = detector                # 'ema' (default) or 'bocd'
        self.reset()                            # still rewards this well (cheap on
        #                                         a false alarm)

    def reset(self) -> None:
        self.slot = 0
        self.n_known = 1
        self.mode = "normal"
        self.probe_cost = 0
        # True only on the step a search FINALIZED onto a freshly-allocated slot —
        # i.e. a confirmed genuine new regime (not a re-recognised returning one).
        # Consumed by the opt-in AMR path in the agent to trigger realignment.
        self.new_regime = False
        self._reset_ema()
        self._cands: list[int] = []
        self._ci = 0
        self._pcount = 0
        self._psum = 0.0
        self._scores: dict[int, float] = {}

    def _reset_ema(self) -> None:
        self.fast: float | None = None
        self.slow: float | None = None
        self.t = 0
        self._bocd = BOCDDetector(warmup=self.warmup) if self.detector == 'bocd' else None

    def context(self) -> torch.Tensor:
        v = torch.zeros(self.ctx_dim)
        v[self.slot] = 1.0
        return v

    def _detect_collapse(self, r: float) -> bool:
        if self.fast is None:
            self.fast = self.slow = r
        self.fast += self.afast * (r - self.fast)
        self.slow += self.aslow * (r - self.slow)
        self.t += 1
        if self._bocd is not None:
            # BOCD changepoint probability replaces the EMA predicate; keep the
            # same t>warmup guard so behaviour matches the EMA path's gating.
            return self.t > self.warmup and self._bocd.observe(r)
        return (self.t > self.warmup and self.slow > self.established
                and self.fast < self.slow - self.drop)

    def force_search(self) -> None:
        """Begin a probing search now (e.g. on an externally signalled boundary),
        independent of the reward-collapse detector."""
        if self.mode == "normal":
            self._start_search()

    def _start_search(self) -> None:
        self.mode = "search"
        # Probe the CURRENT slot first so a false alarm (current still best) can be
        # accepted after one window; then the other known slots, then a fresh one.
        cur = self.slot
        cands = [cur] + [c for c in range(self.n_known) if c != cur]
        if self.n_known < self.ctx_dim:
            cands.append(self.n_known)        # one fresh slot
        self._cands = cands
        self._scores = {}
        self._ci = 0
        self._pcount = 0
        self._psum = 0.0
        self.slot = cands[0]

    def observe(self, reward01: float) -> None:
        """Feed the latest outcome; drives change detection and probing search."""
        self.new_regime = False              # one-shot; set only by _finalize below
        if self.mode == "normal":
            if self.auto_detect and self._detect_collapse(reward01):
                self._start_search()
            return
        # search mode: accumulate reward for the candidate currently in use
        self.probe_cost += 1
        self._psum += reward01
        self._pcount += 1
        if self._pcount < self.probe_steps:
            return
        cand = self._cands[self._ci]
        score = self._psum / self._pcount
        self._scores[cand] = score
        # Early-accept: if the current slot (probed first) still rewards well, the
        # alarm was spurious — keep it and stop, so noise costs just one window.
        if self._ci == 0 and score >= self.accept:
            self._finalize()
            return
        self._ci += 1
        if self._ci < len(self._cands):
            self.slot = self._cands[self._ci]
            self._pcount = 0
            self._psum = 0.0
        else:
            self._finalize()

    def _finalize(self) -> None:
        best = max(self._scores, key=self._scores.get)
        self.slot = best
        if best == self.n_known:
            self.n_known += 1
            self.new_regime = True           # confirmed genuine new regime
        self.mode = "normal"
        self._reset_ema()
