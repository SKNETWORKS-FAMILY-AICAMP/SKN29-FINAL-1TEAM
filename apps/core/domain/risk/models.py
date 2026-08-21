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
