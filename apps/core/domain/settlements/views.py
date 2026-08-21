import logging
import re
from datetime import datetime, time

import httpx
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

from domain.cards.models import Card
from domain.common.permissions import CanAccountingReview, CanTeamAggregate
from domain.transactions import industry as industry_vocab
from domain.transactions.models import Receipt, Transaction

from . import draft_agent, erp_import, services
from .models import Attachment, AttachmentKind, Settlement, SettlementEvent, TeamBudget
from .serializers import AttachmentSerializer, SettlementDetailSerializer, SettlementSerializer

# 증빙 추출 Agent 호출 — 비전 판독(다쪽 렌더+LLM)이라 넉넉히 잡는다(`app/vision/client.py TIMEOUT=90`과 정합).
EXTRACT_TIMEOUT = 100.0

# 본인이 직접 지울 수 있는 상태 — 아직 팀·회계로 넘어가기 전 단계만.
DELETABLE_STATUSES = {"DRAFT", "TEAM_RETURNED", "TEAM_REJECTED"}


def _actor(request):
    """인증된 사용자만 actor로. (개발단계 AllowAny → 익명은 None)"""
    user = getattr(request, "user", None)
    return user if (user and user.is_authenticated) else None


class SettlementViewSet(viewsets.ModelViewSet):
    """정산 조회/보정 + 상태 액션(submit/review/confirm/judge).

    상태 전이는 services.py를 통해서만 이뤄진다(직접 PATCH로 status 변경 불가).
    프론트 client.ts의 settlements/submit/confirm/review에 대응.
    """
    queryset = Settlement.objects.select_related(
        "transaction", "transaction__card", "submitted_by"
    ).prefetch_related("events", "risk_reviews", "rule_hits__graph", "transaction__receipts")
    serializer_class = SettlementSerializer
    http_method_names = ["get", "patch", "post", "delete", "head", "options"]

    def get_serializer_class(self):
        return SettlementDetailSerializer if self.action == "retrieve" else SettlementSerializer

    def get_permissions(self):
        # 기능 단위 인가(Capability RBAC)
        if self.action in ("review", "confirm", "review_stats", "draft_decision_reason"):
            return [CanAccountingReview()]
        if self.action == "team_decision":  # 팀 취합(보완요청/반려/제출) — 기존 미보호 구멍 방어
            return [CanTeamAggregate()]
        return super().get_permissions()

    # POST /api/settlements/  (신규 지출 등록 — 거래+정산 생성)
    def create(self, request, *args, **kwargs):
        d = request.data
        raw_date = (d.get("date") or "")[:10]
        pd = parse_date(raw_date) if raw_date else None
        ts = timezone.make_aware(datetime.combine(pd, time(12, 0))) if pd else timezone.now()
        amount = int(re.sub(r"[^0-9]", "", str(d.get("amount") or "0")) or 0)
        card = Card.objects.filter(card_type=d.get("cardType")).first() if d.get("cardType") else None
        category = d.get("category") or d.get("aiCategory") or ""

        tx = Transaction.objects.create(
            card=card, merchant=d.get("merchant") or "미상 가맹점", amount=amount, ts=ts,
        )
        if d.get("evidence") == "OK":
            Receipt.objects.create(matched_tx=tx, status=Receipt.Status.MATCHED, file_ref=f"receipts/{tx.id}.jpg")
        actor = _actor(request)
        industry_code, industry_label = industry_vocab.resolve(
            d.get("merchantIndustryCode") or d.get("merchantIndustry")
        )
        s = Settlement.objects.create(
            transaction=tx, category=category, ai_category=d.get("aiCategory") or category,
            ai_suggested=bool(d.get("aiSuggested")),
            # 업종은 화면이 보낸 표기를 그대로 믿지 않고 정본 어휘로 접어 저장한다(§7-1) —
            #  이 값이 곧 `merchant.merchant_type` 판정 사실이라, 표기가 갈리면 룰이 안 걸린다.
            merchant_industry=industry_label, merchant_industry_code=industry_code,
            purpose=d.get("purpose", ""), submitted_by=actor,
            team=getattr(actor, "team", None), status="DRAFT",
        )
        return Response(self.get_serializer(s).data, status=201)

    # DELETE /api/settlements/{id}/  — '내 지출'에서 아직 올리지 않은 건만 본인이 삭제
    def destroy(self, request, *args, **kwargs):
        settlement = self.get_object()
        if settlement.status not in DELETABLE_STATUSES:
            return Response(
                {"detail": "이미 팀·회계로 넘어간 건은 삭제할 수 없습니다. 보완요청·반려 절차를 따라주세요."},
                status=400,
            )
        actor = _actor(request)
        if actor and settlement.submitted_by_id and settlement.submitted_by_id != actor.id:
            return Response({"detail": "본인이 등록한 건만 삭제할 수 있습니다."}, status=403)
        transaction = settlement.transaction
        settlement.delete()
        # 정산이 사라진 거래는 남겨둘 이유가 없다(다른 정산이 참조 중이면 유지).
        if transaction and not transaction.settlements.exists():
            transaction.receipts.all().delete()
            transaction.delete()
        return Response(status=204)

    # POST /api/settlements/draft-suggest/  — 초안 작성 Agent
    @action(detail=False, methods=["post"], url_path="draft-suggest")
    def draft_suggest(self, request):
        """영수증·거래로 초안 생성, 또는 자연어 지시로 초안 수정.

        `instruction`이 있으면 수정 모드, 없으면 생성 모드. FastAPI Draft Agent(`/agent/draft`)를
        우선 호출하고, 미기동·타임아웃 등으로 실패하면 로컬 플레이스홀더로 폴백한다(응답 셰이프는
        두 경로가 동일하므로 화면은 어느 쪽이 응답했는지 알 필요가 없다).
        """
        data = request.data if isinstance(request.data, dict) else {}

        ai_result = self._call_draft_agent(data)
        if ai_result is not None:
            return Response(ai_result)

        if str(data.get("instruction", "")).strip():
            return Response(draft_agent.revise_draft(data))
        return Response(draft_agent.suggest_draft(data))

    @staticmethod
    def _call_draft_agent(data):
        """FastAPI `/agent/draft` 호출. 실패(미기동·타임아웃·5xx 등)하면 None을 돌려줘 폴백을 유도한다.

        타임아웃 40s는 ai 쪽 최악 경로를 담는 값이다 — 초안 LLM 15s + 가맹점 업종 조회
        (캐시 3 + 카카오 4 + 재분류 LLM 8 + 캐시적재 4 = 최악 19s). 20s로 두면 **캐시 미스일 때만**
        조용히 목업 폴백으로 떨어져, 화면에는 그럴듯한 가짜 초안이 뜬다(원인 파악이 어렵다).
        캐시 히트가 정상 경로라 실사용 지연은 여전히 LLM 한 번 수준이다.
        """
        try:
            resp = httpx.post(f"{settings.AI_BASE_URL}/agent/draft", json=data, timeout=40)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("FastAPI Draft Agent 호출 실패, 로컬 폴백 사용: %s", exc)
            return None

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("category"):
            qs = qs.filter(category=p["category"])
        if p.get("card_type"):
            qs = qs.filter(transaction__card__card_type=p["card_type"])
        if p.get("submitted_by"):
            qs = qs.filter(submitted_by_id=p["submitted_by"])
        if p.get("team"):
            qs = qs.filter(team_id=p["team"])
        return qs

    # POST /api/settlements/import/  — ERP/카드사 결제기록 수집("내역 불러오기")
    @action(detail=False, methods=["post"], url_path="import")
    def import_transactions(self, request):
        """다음 회차 결제기록을 가져와 초안(DRAFT)으로 만든다.

        인증이 필요하다 — 누구 카드의 결제를 가져올지는 **요청자**로 정해지고, 개인카드 건은
        그 사람에게 바로 귀속되기 때문이다. 익명으로 열어두면 주인 없는 초안만 쌓인다.
        """
        actor = _actor(request)
        if actor is None:
            return Response({"detail": "로그인이 필요합니다."}, status=401)
        result = erp_import.import_next_batch(actor)
        return Response(result.to_dict())

    # POST /api/settlements/{id}/claim/  — 팀·공용 카드 결제의 실사용자 본인 등록
    @action(detail=True, methods=["post"])
    def claim(self, request, pk=None):
        """"내가 사용했어요" — 주인 없는 팀카드 결제를 본인에게 귀속시킨다."""
        actor = _actor(request)
        if actor is None:
            return Response({"detail": "로그인이 필요합니다."}, status=401)
        try:
            settlement = erp_import.claim(self.get_object(), actor)
        except erp_import.ClaimError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(self.get_serializer(settlement).data)

    # POST /api/settlements/raise/  {ids:[...]}  개인 '올림'(DRAFT → TEAM_COLLECTING)
    @action(detail=False, methods=["post"], url_path="raise")
    def raise_to_team(self, request):
        ids = request.data.get("ids", [])
        raised, skipped = [], []
        for s in Settlement.objects.filter(id__in=ids):
            try:
                services.raise_to_team(s, _actor(request))
                raised.append(s.id)
            except services.TransitionError:
                skipped.append(s.id)
        return Response({"raised": raised, "skipped": skipped})

    # POST /api/settlements/submit/  {ids:[...]}  팀 제출(TEAM_COLLECTING → SUBMITTED)·재제출(RETURNED → SUBMITTED)
    @action(detail=False, methods=["post"])
    def submit(self, request):
        """제출 후 곧바로 판정 결과를 상태에 반영한다 (SUBMITTED → RPA_JUDGED → …).

        상태 반영을 따로 떼어 두면 아무도 부르지 않아 정산이 SUBMITTED에 고인다 —
        상태머신상 제출의 다음 단계는 룰 판정이고, 그건 사람이 누르는 단계가 아니다.

        **엔진을 여기서 다시 돌리지는 않는다.** 판정은 팀 취합에 올라온 시점에 이미 돌았고
        (`services.raise_to_team`), 같은 사실·같은 그래프면 결과가 같다. 다시 돌리면
        `rule_hits`가 회차별로 쌓여 검토 화면이 어느 게 최신 근거인지 잃는다. 다만 회계
        보완요청 재제출(`RETURNED → SUBMITTED`)은 팀 단계를 거치지 않고 사실이 바뀐 뒤라
        옛 판정을 쓸 수 없다 — 그 경로만 재판정한다.

        판정 실패는 제출을 되돌리지 않는다. 제출은 이미 성공했고 판정은 다시 돌릴 수 있다
        (`POST /settlements/{id}/judge/`). 실패를 감추면 SUBMITTED에 고인 건이 왜 안 넘어가는지
        알 수 없으므로 `judgeFailed`로 함께 돌려준다.
        """
        ids = request.data.get("ids", [])
        actor = _actor(request)
        submitted, skipped, judged, judge_failed = [], [], {}, {}
        for s in Settlement.objects.filter(id__in=ids):
            # 전이 전에 봐야 한다 — `submit()` 뒤엔 전부 SUBMITTED라 출처를 알 수 없다.
            came_from_team = s.status == "TEAM_COLLECTING"
            try:
                services.submit(s, actor)
            except services.TransitionError:
                skipped.append(s.id)
                continue
            submitted.append(s.id)
            try:
                result = services.judge(s, actor, reuse_recorded=came_from_team)
            except Exception as exc:  # noqa: BLE001  # 조립기·엔진·DB 어느 쪽이든
                logger.warning("정산 %s 판정 실패: %s", s.id, exc, exc_info=True)
                judge_failed[str(s.id)] = f"{type(exc).__name__}: {exc}"
                continue
            judged[str(s.id)] = {"decision": result.decision, "status": s.status, "flags": result.flags}
        return Response({
            "submitted": submitted, "skipped": skipped,
            "judged": judged, "judgeFailed": judge_failed,
        })

    # GET /api/settlements/review-stats/  — S-03 헤더 요약 지표(자동처리율·평균 검토시간)
    @action(detail=False, methods=["get"], url_path="review-stats")
    def review_stats(self, request):
        """이번 달 자동처리율·평균 검토 소요시간. 예전엔 화면에 82%/6.2분이 하드코딩돼 있었다.

        **자동처리율**은 룰 엔진 자체 판정(`rule_decision`)이 REVIEW가 아닌 비율이다 — REVIEW만
        사람(Risk Review)에게 넘어가고 PASS/RETURN/REJECT는 룰이 그 자리에서 결론냈다는 뜻이라,
        이게 "사람 손 없이 처리된 비율"의 정확한 정의다(현재 상태가 아니라 **룰의 최초 판정**
        기준 — CONFIRMED건도 원래 REVIEW를 거쳤을 수 있어 현재 상태만 봐선 구분이 안 된다).

        **평균 검토시간**은 `SettlementEvent`에서 `IN_REVIEW` 진입 시각 → 그 IN_REVIEW를 벗어난
        결정 시각(이번 달)까지의 차를 건별로 구해 평균한다. 이 정보는 목록 API에 없다 —
        `events`는 상세 조회에서만 내려가므로, 집계는 여기서 서버가 직접 한다.
        """
        now = timezone.now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start.replace(year=start.year + 1, month=1) if start.month == 12
               else start.replace(month=start.month + 1))

        judged_this_month = Settlement.objects.filter(rule_judged_at__gte=start, rule_judged_at__lt=end)
        total_judged = judged_this_month.count()
        needed_review = judged_this_month.filter(events__to_state="IN_REVIEW").distinct().count()
        auto_processed_rate = round(1 - needed_review / total_judged, 4) if total_judged else None

        decisions = (
            SettlementEvent.objects
            .filter(from_state="IN_REVIEW", created_at__gte=start, created_at__lt=end)
            .order_by("settlement_id", "created_at")
        )
        durations_sec = []
        for ev in decisions:
            entered = (
                SettlementEvent.objects
                .filter(settlement_id=ev.settlement_id, to_state="IN_REVIEW", created_at__lte=ev.created_at)
                .order_by("-created_at")
                .first()
            )
            if entered:
                durations_sec.append((ev.created_at - entered.created_at).total_seconds())
        avg_review_minutes = round(sum(durations_sec) / len(durations_sec) / 60, 1) if durations_sec else None

        return Response({
            "month": start.strftime("%Y-%m"),
            "totalJudged": total_judged,
            "autoProcessedRate": auto_processed_rate,
            "reviewedCount": len(durations_sec),
            "avgReviewMinutes": avg_review_minutes,
        })

    # POST /api/settlements/{id}/confirm/  (사람 최종 확정, FR-ST-03)
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        s = self.get_object()
        try:
            services.confirm(s, _actor(request))
        except services.TransitionError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(self.get_serializer(s).data)

    # POST /api/settlements/{id}/draft-decision-reason/  {decision, reasonCategory}
    @action(detail=True, methods=["post"], url_path="draft-decision-reason")
    def draft_decision_reason(self, request, pk=None):
        """보완요청/반려 사유 **초안**(2026-08-21) — 담당자가 사유칸에 매번 손으로 다시
        타이핑하던 걸 돕는다. 화면엔 이미 판정 근거(룰 플래그·2차 RAG 검증 사유·1차 이상탐지
        사유)가 떠 있는데, 사유 입력칸은 그걸 다시 사람이 요약해서 써야 했다 — 이미 아는
        정보를 문장으로 정리하는 단순 작업이라 LLM에게 초안만 맡긴다.

        **초안이지 확정이 아니다.** 프론트가 이 텍스트를 입력칸에 채우되 그대로 제출을
        막지 않는다(편집 가능) — 새 판단을 만드는 게 아니라 이미 있는 근거를 문장으로
        다듬을 뿐이므로, 승인 없이 제출 자체는 막을 이유가 없다(강제 편집은 §4.2 결정
        참조: 여기서는 안 함). 실패하면 빈 문자열 대신 에러를 그대로 올린다 — 조용히
        일반 문구로 채우면 "AI가 판단했다"고 착각한다.
        """
        s = self.get_object()
        decision = request.data.get("decision")
        if decision not in ("RETURN", "REJECT"):
            return Response({"detail": "decision은 RETURN 또는 REJECT여야 합니다."}, status=400)

        from domain.policies.flags import describe, label_map

        labels = label_map()
        flag_info = [describe(f, labels) for f in (s.rule_flags or [])]
        review = s.risk_reviews.first()
        stage2 = (review.stage2_verdict or {}) if review else {}

        payload = {
            "decision": decision,
            "reasonCategory": request.data.get("reasonCategory", ""),
            "merchant": s.transaction.merchant if s.transaction_id else "",
            "amount": int(s.transaction.amount) if s.transaction_id else 0,
            "category": s.category or s.ai_category,
            "purpose": s.purpose,
            "ruleFlags": [{"label": f["label"], "severity": f["severity"]} for f in flag_info],
            "violationVerdict": stage2.get("violation_verdict", ""),
            "reviewReasons": stage2.get("review_reasons", []),
            "anomalyReasons": review.anomaly_reasons if review else [],
        }
        try:
            resp = httpx.post(f"{settings.AI_BASE_URL}/agent/draft-decision-reason", json=payload, timeout=20)
            resp.raise_for_status()
            detail = resp.json().get("detail", "")
        except Exception as exc:  # noqa: BLE001  # AI 미기동·타임아웃·5xx 전부
            logger.warning("사유 초안 생성 실패(settlement=%s): %s", pk, exc)
            return Response({"detail": "AI 초안 생성에 실패했습니다 — 직접 입력해주세요."}, status=503)
        if not detail:
            return Response({"detail": "AI가 초안을 만들지 못했습니다 — 직접 입력해주세요."}, status=503)
        return Response({"detail": detail})

    # POST /api/settlements/{id}/review/  {decision, reason}
    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        s = self.get_object()
        try:
            services.review(s, request.data.get("decision"), _actor(request), request.data.get("reason", ""))
        except services.TransitionError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(self.get_serializer(s).data)

    # POST /api/settlements/{id}/team-decision/  {decision, reason}
    @action(detail=True, methods=["post"], url_path="team-decision")
    def team_decision(self, request, pk=None):
        s = self.get_object()
        try:
            services.team_decide(
                s, request.data.get("decision"), _actor(request), request.data.get("reason", "")
            )
        except services.TransitionError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(self.get_serializer(s).data)

    # POST /api/settlements/{id}/judge/  (RPA 1차판정 — 재판정·수동 실행용)
    @action(detail=True, methods=["post"])
    def judge(self, request, pk=None):
        """단건 RPA 1차판정. 제출 시 자동으로 돌지만, 판정이 실패했거나 룰 그래프를
        바꾼 뒤 다시 돌려야 할 때 쓴다. 판정 근거(`ruleResult`)를 응답에 함께 싣는다."""
        s = self.get_object()
        try:
            result = services.judge(s, _actor(request))
        except services.TransitionError as e:
            return Response({"detail": str(e)}, status=400)
        # Risk Review 호출은 `services.judge`가 소유한다(커밋 후 실행) — 여기서 따로 부르면
        # 제출 경로와 수동 판정 경로 중 한쪽만 도는 상황이 다시 생긴다.
        return Response({**self.get_serializer(s).data, "ruleResult": result.to_dict()})

    # GET/POST /api/settlements/{id}/attachments/  — 목록 조회 · 업로드(+동기 추출)
    #
    # 규정 문서 업로드(`PolicyDocViewSet`)와 달리 **동기**로 처리한다: 첨부 1건은
    # 비전 판독 1회(최대 수십 초, `app/vision/client.py TIMEOUT=90`)면 끝나서 문서
    # 파싱(수십 초~분, docling)만큼 무겁지 않다. 업로드 응답이 곧 추출 결과라 화면이
    # 폴링할 필요가 없다 — MVP 동기 REST 원칙(CLAUDE.md §1)과도 맞는다.
    @action(
        detail=True, methods=["get", "post"], url_path="attachments",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def attachments(self, request, pk=None):
        s = self.get_object()
        if request.method == "GET":
            return Response(
                AttachmentSerializer(s.attachments.all(), many=True, context={"request": request}).data
            )

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "file 필드가 필요합니다."}, status=400)
        kind = (request.data.get("kind") or AttachmentKind.OTHER).upper()
        if kind not in AttachmentKind.values:
            return Response({"detail": f"알 수 없는 종류입니다: {kind}"}, status=400)

        attachment = Attachment.objects.create(
            settlement=s, kind=kind, file=upload, original_name=upload.name,
            mime_type=getattr(upload, "content_type", "") or "",
            uploaded_by=_actor(request),
        )
        # `file.name`(볼륨 기준 상대경로)이 곧 추출 Agent가 받는 `file_ref` 계약이다
        # (`Attachment.file_ref`는 표시·감사용으로 같은 값을 들고 있는다).
        attachment.file_ref = attachment.file.name
        attachment.save(update_fields=["file_ref"])

        _run_extraction(attachment)
        attachment.refresh_from_db()
        return Response(
            AttachmentSerializer(attachment, context={"request": request}).data, status=201,
        )

    # DELETE /api/settlements/{id}/attachments/{attachment_id}/
    @action(detail=True, methods=["delete"], url_path=r"attachments/(?P<attachment_id>\d+)")
    def attachment_detail(self, request, pk=None, attachment_id=None):
        s = self.get_object()
        attachment = s.attachments.filter(pk=attachment_id).first()
        if attachment is None:
            return Response({"detail": "첨부를 찾을 수 없습니다."}, status=404)
        attachment.file.delete(save=False)
        attachment.delete()
        return Response(status=204)

    # POST /api/settlements/{id}/attachments/{attachment_id}/re-extract/
    #
    # E-5(재추출) 최소 구현: 스키마·추출기 버전이 바뀐 뒤 사람이 눌러 다시 돌린다.
    # 전량 자동 재추출은 하지 않는다 — 참조되지 않는 첨부까지 매번 비전 호출을 태우면
    # 비용만 나가고 아무도 안 본다(§6 결정 4, 참조되는 것만이 실익 있다).
    @action(detail=True, methods=["post"], url_path=r"attachments/(?P<attachment_id>\d+)/re-extract")
    def attachment_re_extract(self, request, pk=None, attachment_id=None):
        s = self.get_object()
        attachment = s.attachments.filter(pk=attachment_id).first()
        if attachment is None:
            return Response({"detail": "첨부를 찾을 수 없습니다."}, status=404)
        _run_extraction(attachment)
        attachment.refresh_from_db()
        return Response(AttachmentSerializer(attachment, context={"request": request}).data)


def _run_extraction(attachment: Attachment) -> None:
    """FastAPI 증빙 추출 Agent(`/agent/extract`) 호출 → `Attachment` 갱신.

    업로드 자체는 이미 성공했으므로 추출 실패는 예외로 올리지 않는다 — `FAILED` +
    사유만 남기고, 담당자가 사람이 직접 값을 볼 수 있게 둔다(조용한 실패 금지, 단
    업로드 자체를 막지는 않는다).
    """
    attachment.extraction_status = "RUNNING"
    attachment.save(update_fields=["extraction_status"])
    try:
        resp = httpx.post(
            f"{settings.AI_BASE_URL}/agent/extract",
            json={"file_ref": attachment.file.name, "kind": attachment.kind},
            timeout=EXTRACT_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as exc:  # noqa: BLE001  # AI 미기동·타임아웃·5xx·판독 실패(502) 전부
        logger.warning("증빙 추출 실패(attachment=%s): %s", attachment.pk, exc)
        attachment.extraction_status = "FAILED"
        attachment.error = f"{type(exc).__name__}: {exc}"
        attachment.save(update_fields=["extraction_status", "error"])
        return

    attachment.extraction_status = result.get("extractionStatus", "DONE")
    attachment.extracted = result.get("extracted", {})
    attachment.field_confidence = result.get("fieldConfidence", {})
    attachment.evidence_spans = result.get("evidenceSpans", [])
    attachment.extractor_version = result.get("extractorVersion", "")
    attachment.extracted_at = timezone.now()
    attachment.error = "; ".join(result.get("warnings") or [])
    attachment.save(update_fields=[
        "extraction_status", "extracted", "field_confidence", "evidence_spans",
        "extractor_version", "extracted_at", "error",
    ])


class SettlementSummaryView(APIView):
    """GET /api/internal/settlement-summary/<settlement_id>/ — Risk Review 2차 검증 진입점(Django 내부 read API).

    FastAPI(ai) Risk Review Agent가 settlement_id만 갖고 tx_id·분류·가맹점·목적을 얻는 최소
    조회. 관계형 데이터는 Django 경유 원칙(CLAUDE.md §1)에 따라 Postgres를 직접 조회하지 않는다.

    판정 입력 필드(headcount 등) 6종도 함께 내려준다 — Risk Review 2차 검증 질의(retrieve)에
    "판정 사실"로 녹여 넣기 위함(retrive 브랜치 `retrieval_strategy_evaluation.ipynb` §11 실측,
    자연어+facts 방식이 블롭 대비 MRR을 유의하게 끌어올림). 전부 null 허용 필드다 — `None`은
    "거짓"이 아니라 "모름"이므로 여기서도 그대로 null로 내려보내고, 임의로 false/0으로 채우지
    않는다(`Settlement` 모델 §76 주석의 계약과 동일).
    """
    permission_classes = [AllowAny]

    def get(self, request, settlement_id):
        s = Settlement.objects.select_related("transaction").filter(pk=settlement_id).first()
        if s is None:
            return Response({"detail": "정산을 찾을 수 없습니다."}, status=404)
        tx = s.transaction
        return Response({
            "settlement_id": s.pk,
            "tx_id": tx.pk,
            "category": s.category or s.ai_category,
            "merchant": tx.merchant,
            "amount": int(tx.amount),
            "purpose": s.purpose,
            "headcount": s.headcount,
            "preApproved": s.pre_approved,
            "itemType": s.item_type or None,
            "kickbackTarget": s.kickback_target,
            "isSecondaryVenue": s.is_secondary_venue,
            "includesAlcohol": s.includes_alcohol,
        })


# 팀 사용액은 진행 상태와 무관하게 "이미 쓴 돈"으로 잡는다.
#  카드는 이미 결제됐으므로 제출·검토 단계가 어디든 사용액이다. 최종 반려(REJECT)만 제외한다.
_BUDGET_EXCLUDE = ["REJECT"]


class TeamBudgetView(APIView):
    """GET /api/team-budget/?team=<id>&month=YYYY-MM — 팀 예산 현황(S-02).

    한도(limit)는 TeamBudget(DB)에서, 사용액(used)은 해당 팀·월 Settlement 집계로 산출한다(실 내역 기반).
    프론트 data/mock.ts의 teamBudget 셰이프({total, used, categories:[{label,limit,used}]})와 정합.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        team_id = request.query_params.get("team")
        month = request.query_params.get("month") or ""

        budgets = TeamBudget.objects.all()
        if team_id:
            budgets = budgets.filter(team_id=team_id)
        if month:
            budgets = budgets.filter(year_month=month)

        used_qs = Settlement.objects.exclude(status__in=_BUDGET_EXCLUDE)
        if team_id:
            used_qs = used_qs.filter(team_id=team_id)
        if month and "-" in month:
            y, m = month.split("-")[:2]
            used_qs = used_qs.filter(transaction__ts__year=int(y), transaction__ts__month=int(m))
        used_by_cat = {
            r["category"]: int(r["s"] or 0)
            for r in used_qs.values("category").annotate(s=Sum("transaction__amount"))
        }

        total_limit, categories = 0, []
        for b in budgets:
            if b.category == "":
                total_limit = b.limit_amount
            else:
                categories.append({"label": b.category, "limit": b.limit_amount, "used": used_by_cat.get(b.category, 0)})

        # 예산 행이 없는 과목(또는 분류 미지정)의 지출 — 총 사용액에는 들어가지만 항목별 카드엔 없다.
        # 그대로 두면 "항목 합 ≠ 총 사용액"이 되어 대시보드가 어긋나 보이므로 따로 내려준다.
        budgeted_labels = {c["label"] for c in categories}
        unbudgeted = {k: v for k, v in used_by_cat.items() if k not in budgeted_labels and v}
        return Response({
            "team": int(team_id) if team_id else None, "month": month,
            "total": total_limit, "used": sum(used_by_cat.values()), "categories": categories,
            # {계정과목(또는 ''): 금액} — 비어 있으면 항목 합 == 총 사용액이라는 뜻.
            "unbudgeted": unbudgeted, "unbudgetedUsed": sum(unbudgeted.values()),
        })
