"""Risk 결과 / 학습 라벨 (기술명세서 §3.1).

MVP: 비지도 이상탐지(1차) + RAG 내규검증(2차) 결과. review_prob는 post-MVP(nullable).
decision_labels는 MVP에선 '적재만' — 향후 지도학습용.
"""
from django.conf import settings
from django.db import models


class RiskReview(models.Model):
    settlement = models.ForeignKey(
        "settlements.Settlement", on_delete=models.CASCADE, related_name="risk_reviews"
    )
    anomaly_score = models.FloatField(default=0.0)          # 1차 비지도 이상탐지
    # 1차 점수의 3단계 등급(HIGH/MEDIUM/LOW). anomaly_score에서 파생되지만 **판정 시점 스냅샷**
    # 으로 저장한다 — 임계값은 코드 상수(`risk_review_agent.RISK_TIER_*`)라 사람이 튜닝할 수
    # 있고, 그때 과거 판정의 등급까지 소급해 바뀌면 감사 기록이 흔들린다(`rule_hits.eval_context`
    # 스냅샷과 같은 이유). 재판정(`/judge/`)하면 새 임계값으로 다시 매겨진다.
    risk_tier = models.CharField(max_length=10, blank=True)
    #: 1차 이상탐지가 **실제로 채점했는가**. `Settlement.risk_review_state`(호출 단위 성공/실패)와
    #  다른 축이다 — 호출은 성공했는데 1차만 못 돈 경우가 실재한다(모델 미배치·경로 어긋남).
    #  이 축이 없던 동안 그런 건이 `anomaly_score=0.0` + `risk_tier="LOW"`로 저장돼
    #  화면에서 **「검사해보니 안전한 건」으로 둔갑**했다.
    #  값: ok | no_model | error (빈 문자열 = 옛 행)
    stage1_status = models.CharField(max_length=16, blank=True)
    #: 못 채점한 이유(사람이 읽는 문장). 화면이 점수 자리에 대신 띄운다.
    stage1_note = models.CharField(max_length=300, blank=True)
    reasons = models.JSONField(default=list, blank=True)    # 피처 기여도 [{feature, weight}]
    anomaly_reasons = models.JSONField(default=list, blank=True)  # 요약 사유 문구(리스트)
    rag_refs = models.JSONField(default=list, blank=True)   # 2차 RAG 근거(출처·조문·발췌 포함)
    rag_report = models.TextField(blank=True)               # 2차 RAG 내규 검증 보고서(마크다운)
    ai_recommendation = models.CharField(max_length=10, blank=True)  # APPROVE/RETURN/REJECT
    ai_confidence = models.FloatField(default=0.0)
    review_prob = models.FloatField(null=True, blank=True)  # post-MVP 지도학습
    # 2차 RAG 검증 LLM 구조화 출력 원본(violation_verdict/review_reasons/recommendation/
    # citations/similar_cases 전체) — 기존 reasons(1차 feature contribs 전용)와 분리해서 보존한다.
    stage2_verdict = models.JSONField(default=dict, blank=True)
    #: 담당자가 읽는 **구조화 보고서**(summary/recommendation/highlights/findings/advisories).
    #  `rag_report`(마크다운 TextField)는 시드 하이라이트 전용으로 남는다 — 실 운영 경로는
    #  한 번도 채운 적이 없고, 마크다운 한 덩어리로는 화면이 미리보기/자세히를 못 가른다.
    report = models.JSONField(default=dict, blank=True)
    #: 어느 등급 경로로 돌았나(low = LLM 미사용 / fast / heavy)와 실제 사용 모델.
    #  안 남기면 나중에 어느 결과가 어느 모델의 것인지 알 수 없다(모델 비교의 전제).
    tier_path = models.CharField(max_length=10, blank=True)
    model_name = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # **최신순이다(점수순이 아니다).** 재판정(`/judge/`)·재제출은 이 테이블에 행을 새로
        # 쌓는다 — 갱신이 아니라 이력이다. 그런데 예전 정렬은 `-anomaly_score`라서, 소비처가
        # 전부 "이 정산의 현재 검토 결과"를 뜻하는 `.first()`/`rrs[0]`로 읽는데도 **점수가
        # 같거나 더 높은 옛 행이 최신 행을 가렸다**(실측: settlement 383에서 03:08 행이
        # 04:45 행을 가려 화면에 옛 판정이 떴다). 검토 큐의 위험도 정렬은 프론트가
        # `anomalyScore`로 따로 하므로 여기서 점수순을 유지할 이유가 없다.
        # 같은 종류의 결함을 EvalContext 스냅샷에서 이미 한 번 고쳤다(CLAUDE.md 룰 엔진 ⑧).
        ordering = ["-created_at", "-id"]


class DecisionLabel(models.Model):
    class Label(models.TextChoices):
        APPROVE = "APPROVE", "승인"
        RETURN = "RETURN", "보완요청"
        REJECT = "REJECT", "반려"
        CORRECT = "CORRECT", "수정"

    settlement = models.ForeignKey(
        "settlements.Settlement", on_delete=models.CASCADE, related_name="decision_labels"
    )
    label = models.CharField(max_length=10, choices=Label.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)


class DecisionCase(models.Model):
    """**AI·룰과 다른 사람의 판단**을 사례로 남긴 기록 — RAG `case_history`의 원천.

    ## 왜 「다른 판단」만 남기나

    AI 권고대로 처리한 건은 새로 배울 게 없다. 사례의 가치는 **"AI는 이렇게 봤는데
    사람은 다르게 판단했다, 그 이유는 이것이다"** 에 있다 — 다음에 비슷한 건이 오면
    2차 RAG 검증이 이 기록을 근거로 끌어와, 같은 실수를 반복하지 않게 한다.

    모든 결정을 다 넣으면 검색이 **다수결에 묻힌다**: 대부분은 AI 권고와 일치하므로
    유사도 상위가 전부 "권고대로 처리함"으로 채워지고, 정작 봐야 할 예외가 밀려난다.

    ## 왜 스냅샷인가

    `text`·`facts`는 **결정 시점의 사실을 얼려 둔 것**이다. 정산은 이후에도 고쳐질 수
    있는데(보완요청 → 수정 → 재제출), 검색이 지금 값을 따라가면 "그때 왜 그렇게 판단
    했는가"를 설명할 수 없게 된다. `rule_hits.eval_context`가 판정 스냅샷을 남기는 것과
    같은 이유다.

    ## 인덱싱은 별개다

    `indexed_at`이 비어 있으면 아직 Chroma(`case_history`)에 안 올라간 것이다. 적재
    실패가 **결정을 되돌리지 않는다** — 결정은 이미 확정됐고 사례는 나중에 다시 올리면
    된다(`domain/risk/case_index.py`).
    """

    class Source(models.TextChoices):
        """사람이 무엇과 다르게 판단했는가 — 사례의 성격을 가른다."""
        AI = "AI", "AI 권고와 다름"
        RULE = "RULE", "룰 판정과 다름"

    settlement = models.ForeignKey(
        "settlements.Settlement", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="decision_cases",
        help_text="정산이 지워져도 사례는 남는다 — 이미 임베딩돼 검색에 쓰이고 있다.",
    )
    #: Chroma 문서 id. 사람이 읽는 값이 아니라 **적재 멱등성의 키**다(재적재해도 중복되지 않는다).
    case_id = models.CharField(max_length=64, unique=True)
    category = models.CharField("비용분류", max_length=20, blank=True)
    #: 사람의 최종 결정 — APPROVE / RETURN / REJECT.
    outcome = models.CharField(max_length=10)
    #: 사람이 뒤집은 대상. 둘 다 있을 수 있지만 **비교 기준 하나**만 남긴다(AI 우선).
    diverged_from = models.CharField(max_length=8, choices=Source.choices)
    expected = models.CharField("AI 권고 또는 룰 판정", max_length=16, blank=True)
    ai_recommendation = models.CharField(max_length=10, blank=True)
    rule_decision = models.CharField(max_length=10, blank=True)
    rule_flags = models.JSONField(default=list, blank=True)
    #: **회계 담당자가 쓴 사유.** 이 문장이 사례의 핵심이다 — 판정 사실만으로는
    #  "왜 다르게 봤는지"를 알 수 없다.
    reason = models.TextField()
    #: 임베딩 대상 본문(스냅샷). 검색이 실제로 매칭하는 텍스트라 자체로 완결돼야 한다.
    text = models.TextField()
    #: 결정 시점 사실 요약(금액·가맹점·업종 등). 감사·재현용이며 임베딩하지 않는다.
    facts = models.JSONField(default=dict, blank=True)
    citation = models.CharField("표시용 출처", max_length=100, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    decided_at = models.DateTimeField(auto_now_add=True)
    indexed_at = models.DateTimeField("Chroma 적재 시각", null=True, blank=True)
    index_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-decided_at"]
        indexes = [models.Index(fields=["indexed_at"], name="ix_decisioncase_indexed")]

    def __str__(self):
        return f"{self.case_id} {self.expected}→{self.outcome}"

    def to_payload(self) -> dict:
        """`case_store.upsert_cases()` 계약 그대로 — 골든 데이터와 같은 모양이다."""
        return {
            "case_id": self.case_id,
            "text": self.text,
            "outcome": self.outcome,
            "category": self.category,
            "citation": self.citation or self.case_id,
        }
