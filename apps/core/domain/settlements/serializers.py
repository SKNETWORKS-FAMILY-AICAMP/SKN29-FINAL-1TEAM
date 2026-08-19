"""정산 직렬화 — 프론트 `types/domain.ts`의 Settlement(camelCase)와 정합.

프론트가 USE_MOCK=false로 전환하면 이 셰이프를 그대로 소비한다.
"""
from rest_framework import serializers

from domain.risk.models import RiskReview

from .models import Settlement, SettlementEvent


class RiskReviewSerializer(serializers.ModelSerializer):
    anomalyScore = serializers.FloatField(source="anomaly_score", read_only=True)
    featureContribs = serializers.JSONField(source="reasons", read_only=True)
    ragRefs = serializers.JSONField(source="rag_refs", read_only=True)
    ragReport = serializers.CharField(source="rag_report", read_only=True)
    aiRecommendation = serializers.CharField(source="ai_recommendation", read_only=True)
    aiConfidence = serializers.FloatField(source="ai_confidence", read_only=True)

    class Meta:
        model = RiskReview
        fields = ["anomalyScore", "featureContribs", "ragRefs", "ragReport", "aiRecommendation", "aiConfidence"]


class SettlementEventSerializer(serializers.ModelSerializer):
    fromState = serializers.CharField(source="from_state", read_only=True)
    toState = serializers.CharField(source="to_state", read_only=True)
    actor = serializers.CharField(source="actor.username", read_only=True, default=None)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = SettlementEvent
        fields = ["id", "fromState", "toState", "actor", "reason", "createdAt"]


class SettlementSerializer(serializers.ModelSerializer):
    """목록/상세 공용 — 거래·부서·Risk 파생 필드를 평탄화(camelCase).

    프론트 Settlement/ReviewItem 셰이프와 정합. Risk 필드는 위험검토(IN_REVIEW) 건에만 채워진다.
    """
    date = serializers.SerializerMethodField()
    time = serializers.SerializerMethodField()
    merchant = serializers.CharField(source="transaction.merchant", read_only=True)
    amount = serializers.DecimalField(
        source="transaction.amount", max_digits=12, decimal_places=0, read_only=True
    )
    cardType = serializers.SerializerMethodField()
    aiCategory = serializers.CharField(source="ai_category", read_only=True)
    aiSuggested = serializers.BooleanField(source="ai_suggested", read_only=True)
    merchantIndustry = serializers.CharField(source="merchant_industry", read_only=True)
    evidence = serializers.SerializerMethodField()
    statusLabel = serializers.CharField(source="get_status_display", read_only=True)
    user = serializers.CharField(source="submitted_by.username", read_only=True, default=None)
    dept = serializers.SerializerMethodField()
    teamId = serializers.IntegerField(source="team_id", read_only=True)
    # 팀·공용 카드 결제인데 아직 실사용자가 정해지지 않은 건. 팀원 **전원**에게 보여야
    # 실사용자가 본인 등록을 할 수 있다(주인이 없으니 `user` 기준으로는 아무에게도 안 보인다).
    claimPending = serializers.SerializerMethodField()
    # ── Risk 평탄화 (ReviewItem 셰이프) ──
    anomalyScore = serializers.SerializerMethodField()
    aiRecommendation = serializers.SerializerMethodField()
    aiConfidence = serializers.SerializerMethodField()
    featureContribs = serializers.SerializerMethodField()
    ragRefs = serializers.SerializerMethodField()
    ragReport = serializers.SerializerMethodField()
    anomalyReasons = serializers.SerializerMethodField()
    # 2차 RAG 검증의 판정(위반/문제없음/판단보류) — 권고(aiRecommendation)와 다른 축이다.
    violationVerdict = serializers.SerializerMethodField()
    # 판정 시점 EvalContext 스냅샷(rule_hits) — 있으면 검토 화면의 fact.json이 이걸 보여준다.
    evalContext = serializers.SerializerMethodField()
    # ── 룰 판정 결과 (팀 취합 진입 시 1회) ──
    #  팀 화면의 "이상 건"이 이 값이다. 예전엔 프론트가 `amount >= 300000` 같은 상수로
    #  이상 여부를 흉내냈는데, 그 숫자는 어느 규정에서도 오지 않은 값이었다.
    ruleDecision = serializers.CharField(source="rule_decision", read_only=True)
    ruleFlags = serializers.JSONField(source="rule_flags", read_only=True)
    # 사람이 읽을 사유 — 레지스트리(`policies.flags`)가 라벨의 단일 원천이다.
    #  프론트에 같은 사전을 복사해 두면 곧 어긋난다(실제로 27 vs 9로 어긋나 있었다).
    ruleFlagInfo = serializers.SerializerMethodField()
    ruleJudgedAt = serializers.DateTimeField(source="rule_judged_at", read_only=True)

    class Meta:
        model = Settlement
        fields = [
            "id", "date", "time", "merchant", "amount", "cardType",
            "category", "aiCategory", "aiSuggested", "merchantIndustry", "purpose",
            "evidence", "status", "statusLabel", "user", "dept", "teamId", "claimPending",
            "anomalyScore", "aiRecommendation", "aiConfidence",
            "featureContribs", "ragRefs", "ragReport", "anomalyReasons", "violationVerdict",
            "evalContext", "ruleDecision", "ruleFlags", "ruleFlagInfo", "ruleJudgedAt",
        ]
        read_only_fields = ["status"]  # 상태 전이는 서비스(services.py)를 통해서만

    def get_date(self, obj):
        return obj.transaction.ts.date().isoformat() if obj.transaction_id else None

    def get_time(self, obj):
        return obj.transaction.ts.strftime("%H:%M") if obj.transaction_id else None

    def get_cardType(self, obj):
        card = getattr(obj.transaction, "card", None)
        return card.card_type if card else None

    def get_evidence(self, obj):
        # 증빙 '누락'은 하드 플래그로 차단하지 않는다 — 영수증 없이도 자동 유연처리 지원(AI가 별도 판단).
        # 영수증이 매칭되면 'OK', 없어도 누락으로 막지 않고 'OK'로 통과시킨다(누락 여부 판단은 AI 몫, post-MVP).
        return "OK"

    def get_claimPending(self, obj):
        return obj.submitted_by_id is None and obj.status == "DRAFT"

    def get_dept(self, obj):
        return obj.submitted_by.team.name if (obj.submitted_by_id and obj.submitted_by.team_id) else None

    def _risk(self, obj):
        rrs = list(obj.risk_reviews.all())  # viewset에서 prefetch
        return rrs[0] if rrs else None

    def get_anomalyScore(self, obj):
        r = self._risk(obj)
        return r.anomaly_score if r else None

    def get_aiRecommendation(self, obj):
        r = self._risk(obj)
        return r.ai_recommendation if r else None

    def get_aiConfidence(self, obj):
        r = self._risk(obj)
        return r.ai_confidence if r else None

    def get_featureContribs(self, obj):
        r = self._risk(obj)
        return r.reasons if r else []

    def get_ragRefs(self, obj):
        r = self._risk(obj)
        return r.rag_refs if r else []

    def get_ragReport(self, obj):
        r = self._risk(obj)
        return r.rag_report if r else ""

    def get_anomalyReasons(self, obj):
        r = self._risk(obj)
        return r.anomaly_reasons if r else []

    def get_violationVerdict(self, obj):
        """Risk Review 2차(RAG 내규검증)의 **판정 자체** — VIOLATION / NO_VIOLATION /
        INSUFFICIENT_INFO.

        `aiRecommendation`(승인/보완/반려 권고)과는 다른 축이다: "규정 위반인가"와
        "그래서 어떻게 하라는 건가"는 같이 봐야 판단이 선다. 특히 `INSUFFICIENT_INFO`는
        "문제없음"이 아니라 **판단 보류**라서, 권고만 보면 그 구분이 사라진다.
        """
        r = self._risk(obj)
        return (r.stage2_verdict or {}).get("violation_verdict", "") if r else ""

    def _flag_labels(self):
        """요청당 한 번만 레지스트리를 읽는다. 목록 응답에서 행마다 조회하면 N+1이다.

        DRF는 `many=True`여도 자식 시리얼라이저 **인스턴스 하나**를 재사용하므로
        여기 캐시하면 요청 단위 캐시가 된다(프로세스에 남지 않아 admin 수정이 바로 반영된다).
        """
        if not hasattr(self, "_flag_label_cache"):
            from domain.policies.flags import label_map

            self._flag_label_cache = label_map()
        return self._flag_label_cache

    def get_ruleFlagInfo(self, obj):
        from domain.policies.flags import describe

        labels = self._flag_labels()
        return [describe(flag, labels) for flag in (obj.rule_flags or [])]

    def get_evalContext(self, obj):
        """검토 화면이 보는 "판정 시점 사실" — **가장 최근 판정**의 스냅샷이다.

        보완요청 후 재제출되면 판정이 다시 돌아 `rule_hits`가 쌓인다. 예전엔 첫 행을
        집어 **옛 스냅샷**을 보여줬는데, 그러면 담당자가 이미 고쳐진 값을 보고 판단한다.
        """
        latest = max(obj.rule_hits.all(), key=lambda hit: hit.pk, default=None)
        return latest.eval_context if latest and latest.eval_context else None


class SettlementDetailSerializer(SettlementSerializer):
    """상세: Audit Trail(상태 이력) + Risk(이상탐지+RAG) 포함."""
    events = SettlementEventSerializer(many=True, read_only=True)
    risk = serializers.SerializerMethodField()
    additionalEvidence = serializers.SerializerMethodField()
    facts = serializers.SerializerMethodField()
    ruleHits = serializers.SerializerMethodField()

    class Meta(SettlementSerializer.Meta):
        fields = SettlementSerializer.Meta.fields + [
            "events", "risk", "additionalEvidence", "facts", "ruleHits",
        ]

    def get_risk(self, obj):
        rr = obj.risk_reviews.first()
        return RiskReviewSerializer(rr).data if rr else None

    def get_additionalEvidence(self, obj):
        if not obj.transaction_id:
            return []
        return [
            {"id": receipt.id, "name": receipt.file_ref or f"증빙 #{receipt.id}", "status": receipt.status}
            for receipt in obj.transaction.receipts.all()
        ]

    def get_facts(self, obj):
        tx = obj.transaction
        card = tx.card if tx else None
        return {
            "settlement_id": obj.id,
            "transaction": {
                "merchant": tx.merchant,
                "amount": int(tx.amount),
                "occurred_at": tx.ts.isoformat(),
                "has_receipt": tx.receipts.filter(status="MATCHED").exists(),
            },
            "card": {"type": card.card_type if card else None, "name": card.name if card else None},
            "submitter": {
                "username": obj.submitted_by.username if obj.submitted_by_id else None,
                "team": obj.team.name if obj.team_id else None,
            },
            "settlement": {
                "category": obj.category,
                "ai_category": obj.ai_category,
                "merchant_industry": obj.merchant_industry,
                "purpose": obj.purpose,
                "status": obj.status,
            },
        }

    def get_ruleHits(self, obj):
        return [
            {
                "graph": hit.graph.name if hit.graph_id else None,
                "graphVersion": hit.graph_version,
                "path": hit.path,
                "decision": hit.decision,
                # 사유 코드. 빠져 있어서 화면이 "무슨 판정인지"는 알아도 "왜"를 몰랐다.
                "flags": hit.flags,
                "confidence": hit.confidence,
            }
            for hit in obj.rule_hits.select_related("graph").all()
        ]
