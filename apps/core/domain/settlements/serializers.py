"""정산 직렬화 — 프론트 `types/domain.ts`의 Settlement(camelCase)와 정합.

프론트가 USE_MOCK=false로 전환하면 이 셰이프를 그대로 소비한다.
"""
from rest_framework import serializers

from domain.risk.models import RiskReview

from .models import Settlement, SettlementEvent


class RiskReviewSerializer(serializers.ModelSerializer):
    anomalyScore = serializers.FloatField(source="anomaly_score", read_only=True)
    # 1차 등급(HIGH/MEDIUM/LOW) — 원시 점수는 사람이 크기를 가늠할 수 없어 같이 내려준다.
    riskTier = serializers.CharField(source="risk_tier", read_only=True)
    featureContribs = serializers.JSONField(source="reasons", read_only=True)
    ragRefs = serializers.JSONField(source="rag_refs", read_only=True)
    ragReport = serializers.CharField(source="rag_report", read_only=True)
    aiRecommendation = serializers.CharField(source="ai_recommendation", read_only=True)
    aiConfidence = serializers.FloatField(source="ai_confidence", read_only=True)

    class Meta:
        model = RiskReview
        fields = ["anomalyScore", "riskTier", "featureContribs", "ragRefs", "ragReport",
                  "aiRecommendation", "aiConfidence"]


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
    #  구분만으로는 **어느 카드인지** 알 수 없다. 화면이 카드를 직접 고르므로 id를 함께 낸다
    #  (예전엔 화면이 구분만 보내고 서버가 그 구분의 아무 카드나 붙였다 — 남의 카드가 붙었다).
    cardId = serializers.SerializerMethodField()
    cardName = serializers.SerializerMethodField()
    aiCategory = serializers.CharField(source="ai_category", read_only=True)
    aiSuggested = serializers.BooleanField(source="ai_suggested", read_only=True)
    merchantIndustry = serializers.CharField(source="merchant_industry", read_only=True)
    # 라벨 옆에 코드도 함께 낸다 — 화면 배지·필터가 표기(개정 가능)가 아니라 키를 잡게 한다.
    merchantIndustryCode = serializers.CharField(source="merchant_industry_code", read_only=True)
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
    # 1차 이상탐지 점수의 3단계 등급. Agent가 아직 안 돈 건은 `''`(없는 판단을 지어내지 않는다).
    riskTier = serializers.SerializerMethodField()
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
    # 판정 경로(그래프·노드) — viewset이 이미 `rule_hits__graph`를 prefetch하므로 목록에
    #  실어도 추가 쿼리가 없다. 검토 화면이 "왜 이 결론인가"를 상세 조회 없이 보여준다.
    ruleHits = serializers.SerializerMethodField()
    # **Risk Review(이상탐지+RAG)를 거쳤는가.** 룰 판정 PASS로 승인 대기에 바로 온 건은
    #  거치지 않는다(`risk_review.schedule`은 IN_REVIEW만 예약한다). 이 값이 없으면 화면이
    #  `anomaly_score`가 없는 것과 **0점인 것**을 구분하지 못해 "정상 0점"으로 그린다.
    #  상태 변경 이력 — viewset이 이미 `events`를 prefetch하므로 목록에 실어도 추가 쿼리가
    #  없다. 검토 화면이 **누가 무슨 사유로** 처리했는지를 상세 조회 없이 보여준다
    #  (예전엔 화면이 이력을 하드코딩한 세 줄로 흉내내고 있었다).
    events = SettlementEventSerializer(many=True, read_only=True)
    riskReviewed = serializers.SerializerMethodField()
    #  **「결과가 없다」의 세 가지 상황을 가른다** — 미실시(룰 통과) / 검토 중 / 실패.
    #  결과 유무만 보면 검토 중인 건에 "룰 판정으로 통과된 건입니다"가 뜬다(실제로 겪었다).
    riskReviewState = serializers.CharField(source="risk_review_state", read_only=True)
    riskReviewError = serializers.CharField(source="risk_review_error", read_only=True)

    class Meta:
        model = Settlement
        fields = [
            "id", "date", "time", "merchant", "amount", "cardType", "cardId", "cardName",
            "category", "aiCategory", "aiSuggested", "merchantIndustry", "merchantIndustryCode", "purpose",
            "evidence", "status", "statusLabel", "user", "dept", "teamId", "claimPending",
            "anomalyScore", "riskTier", "aiRecommendation", "aiConfidence",
            "featureContribs", "ragRefs", "ragReport", "anomalyReasons", "violationVerdict",
            "evalContext", "ruleDecision", "ruleFlags", "ruleFlagInfo", "ruleJudgedAt",
            "ruleHits", "riskReviewed", "riskReviewState", "riskReviewError", "events",
            # 판정 입력 컬럼. 화면이 되읽어야 수정이 유지된다 — 안 내려주면 모달이 매번
            # 빈 칸으로 열려 "적었는데 사라졌다"가 된다(`null`=모름 계약도 함께 깨진다).
            "headcount",
        ]
        read_only_fields = ["status"]  # 상태 전이는 서비스(services.py)를 통해서만

    def get_date(self, obj):
        return obj.transaction.ts.date().isoformat() if obj.transaction_id else None

    def get_time(self, obj):
        return obj.transaction.ts.strftime("%H:%M") if obj.transaction_id else None

    def get_cardType(self, obj):
        card = getattr(obj.transaction, "card", None)
        return card.card_type if card else None

    def get_cardId(self, obj):
        card = getattr(obj.transaction, "card", None)
        return card.id if card else None

    def get_cardName(self, obj):
        card = getattr(obj.transaction, "card", None)
        if card is None:
            return None
        return f"{card.name or card.get_card_type_display()}" + (f" {card.number_masked}" if card.number_masked else "")

    def get_evidence(self, obj):
        """증빙이 **실제로 있는가**. 판정이 보는 사실(`evidence.has_valid_receipt`)과 같은 기준이다.

        예전엔 무조건 `"OK"`를 돌려줬다 — 화면은 전건 「증빙 완료」로 보이는데 판정은
        「증빙 누락」으로 걸어서, 담당자가 화면과 판정 사유가 어긋나는 걸 설명할 수 없었다.
        (누락을 **차단하지 않는다**는 원래 방침은 그대로다 — 차단은 룰이 정하고 여기는 표시만 한다.)
        """
        if not obj.transaction_id:
            return "MISSING"
        return "OK" if obj.transaction.receipts.exclude(status="MISSING").exists() else "MISSING"

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

    def get_riskTier(self, obj):
        r = self._risk(obj)
        return r.risk_tier if r else ""

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


    def get_riskReviewed(self, obj):
        return self._risk(obj) is not None

    def get_evalContext(self, obj):
        """검토 화면이 보는 "판정 시점 사실" — **가장 최근 판정**의 스냅샷이다.

        보완요청 후 재제출되면 판정이 다시 돌아 `rule_hits`가 쌓인다. 예전엔 첫 행을
        집어 **옛 스냅샷**을 보여줬는데, 그러면 담당자가 이미 고쳐진 값을 보고 판단한다.
        """
        latest = max(obj.rule_hits.all(), key=lambda hit: hit.pk, default=None)
        return latest.eval_context if latest and latest.eval_context else None


class AttachmentSerializer(serializers.ModelSerializer):
    """증빙 첨부 1건 + 판독 결과.

    `extracted`(dot-path→값)를 화면이 그대로 읽을 수 있게 **경로를 감추지 않는다** —
    "이 문서에서 무엇을 읽어냈는가"가 판정 근거라, 요약해 버리면 사람이 대조할 수 없다.
    """
    kindLabel = serializers.CharField(source="get_kind_display", read_only=True)
    originalName = serializers.CharField(source="original_name", read_only=True)
    mimeType = serializers.CharField(source="mime_type", read_only=True)
    uploadedAt = serializers.DateTimeField(source="uploaded_at", read_only=True)
    extractionStatus = serializers.CharField(source="extraction_status", read_only=True)
    extractionStatusLabel = serializers.CharField(source="get_extraction_status_display", read_only=True)
    fieldConfidence = serializers.JSONField(source="field_confidence", read_only=True)
    evidenceSpans = serializers.JSONField(source="evidence_spans", read_only=True)
    extractorVersion = serializers.CharField(source="extractor_version", read_only=True)
    extractedAt = serializers.DateTimeField(source="extracted_at", read_only=True)

    class Meta:
        from .attachments import Attachment

        model = Attachment
        fields = [
            "id", "kind", "kindLabel", "originalName", "mimeType", "uploadedAt",
            "extractionStatus", "extractionStatusLabel",
            "extracted", "fieldConfidence", "evidenceSpans",
            "extractorVersion", "extractedAt", "error",
        ]

class SettlementDetailSerializer(SettlementSerializer):
    """상세: Risk(이상탐지+RAG) 원본 + 첨부 + facts 포함. (`events`는 베이스로 올렸다)"""
    risk = serializers.SerializerMethodField()
    additionalEvidence = serializers.SerializerMethodField()
    facts = serializers.SerializerMethodField()

    class Meta(SettlementSerializer.Meta):
        # `ruleHits`는 베이스로 올렸다 — 검토 화면이 목록에서 바로 판정 경로를 본다.
        fields = SettlementSerializer.Meta.fields + [
            "risk", "additionalEvidence", "facts",
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
