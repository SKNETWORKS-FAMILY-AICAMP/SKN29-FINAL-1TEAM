import logging
import re
from datetime import datetime, time

import httpx
from django.conf import settings
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

from domain.cards.models import Card
from domain.accounts.models import Team
from domain.common.permissions import (
    CanAccountingReview, CanAccountingReviewOrGovernance, CanTeamAggregate,
)
from domain.transactions import industry as industry_vocab
from domain.transactions.models import Receipt, Transaction

from . import (
    decision_reasons, draft_agent, draft_context, erp_import, evidence_extract,
    risk_review, services, submit_prep,
)
from .attachments import Attachment, AttachmentKind
from .models import Category, Settlement, SettlementEvent, SettlementStatus, TeamBudget
from .serializers import AttachmentSerializer, SettlementDetailSerializer, SettlementSerializer

#  비전 판독기가 여는 형식만 받는다. 상한은 nginx `client_max_body_size 50m`보다 낮게 둔다 —
#  프록시에서 잘리면 사용자는 원인을 알 수 없는 413만 본다.
ALLOWED_ATTACHMENT_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic")
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024

# 본인이 직접 지울 수 있는 상태 — 아직 팀·회계로 넘어가기 전 단계만.
DELETABLE_STATUSES = {"DRAFT", "TEAM_RETURNED", "TEAM_REJECTED"}
# 수정 가능한 상태 — 회계 검토가 시작되기 전까지. 팀 취합 중과 보완요청 받은 건은
#  고쳐서 다시 올려야 하므로 포함한다(고칠 수 없으면 보완요청이 의미가 없다).
EDITABLE_STATUSES = {"DRAFT", "TEAM_COLLECTING", "TEAM_RETURNED", "TEAM_REJECTED", "RETURNED"}


def _invalid_category(*values):
    """저장하려는 비용분류가 정본(`Category`) 밖이면 사유 문자열, 아니면 None.

    `choices=`는 Django에서 **DB 제약이 아니고** DRF 커스텀 create/update는 `full_clean()`을
    부르지 않는다 — 그래서 여기서 막지 않으면 임의 문자열이 그대로 저장된다. 이 값은
    `category.value` 판정 사실이자 룰 그래프 scope 선택 키라, 오타 하나가 "적용할 룰이
    없다"로 조용히 흘러간다(화면 드롭다운만 믿을 자리가 아니다).

    빈 값은 통과시킨다 — `""`는 「아직 못 정했다」는 유효한 상태이고, 기본 게이트가
    `CATEGORY_MISSING`으로 잡아 검토로 보낸다(`기타`와는 다른 상태다).
    """
    allowed = set(Category.values)
    for value in values:
        if value and value not in allowed:
            return (f"알 수 없는 비용분류입니다: {value} "
                    f"(가능한 값: {', '.join(Category.values)})")
    return None


def _resolve_card(data, actor):
    """요청이 지정한 카드 → `Card`. **본인이 쓸 수 없는 카드는 붙이지 않는다.**

    화면 목록(`/api/cards/mine/`)과 같은 범위를 서버에서도 확인한다 — 목록만 좁히고
    저장을 안 막으면 요청을 손댄 값이 그대로 들어간다.
    """
    card_id = data.get("cardId")
    if card_id:
        card = Card.objects.filter(pk=card_id).first()
        if card is None:
            return None
        if actor is not None and card.owner_id and card.owner_id != actor.id:
            return None                      # 남의 개인카드
        if actor is not None and card.team_id and card.team_id != getattr(actor, "team_id", None):
            return None                      # 다른 팀 카드
        return card
    #  하위호환: 구분만 보내던 옛 호출. 본인 범위 안에서 고른다(아무 카드나 집지 않는다).
    card_type = data.get("cardType")
    if not card_type:
        return None
    qs = Card.objects.filter(card_type=card_type)
    if actor is not None:
        qs = qs.filter(Q(owner=actor) | Q(team_id=getattr(actor, "team_id", None), owner__isnull=True)
                       | Q(team__isnull=True, owner__isnull=True))
    return qs.first()


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
        if self.action in ("review", "confirm", "review_stats"):
            return [CanAccountingReview()]
        if self.action == "team_decision":  # 팀 취합(보완요청/반려/제출) — 기존 미보호 구멍 방어
            return [CanTeamAggregate()]
        return super().get_permissions()

    # POST /api/settlements/  (신규 지출 등록 — 거래+정산 생성)
    #  영수증 파일을 함께 받으므로 multipart를 허용한다(JSON도 계속 받는다 — 옛 호출부).
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def create(self, request, *args, **kwargs):
        """신규 지출 등록. **영수증 파일이 필수다.**

        예전엔 화면이 `evidence: "OK"` 한 글자만 보내면 서버가 `receipts/<tx>.jpg`라는
        **있지도 않은 경로**로 `Receipt`를 만들었다 — 증빙이 있다고 기록됐지만 파일은
        어디에도 없었고, 판정(`evidence.has_valid_receipt`)은 그걸 사실로 읽었다.
        비전 판독도 열 파일이 없어 돌 수 없었다.

        이제 실제 파일을 받아 저장하고, 같은 파일을 `Attachment(RECEIPT)`로도 걸어
        **업로드가 곧 판독 트리거**가 되게 한다(첨부 경로와 같은 규약).
        """
        d = request.data
        upload = request.FILES.get("receipt")
        if upload is None:
            return Response(
                {"detail": "영수증 파일이 필요합니다. 지출 등록에는 증빙 첨부가 필수입니다."},
                status=400,
            )
        if not (upload.name or "").lower().endswith(ALLOWED_ATTACHMENT_SUFFIXES):
            return Response(
                {"detail": f"지원하지 않는 형식입니다: {upload.name} "
                           f"({', '.join(ALLOWED_ATTACHMENT_SUFFIXES)}만 가능)"},
                status=400,
            )
        if upload.size > MAX_ATTACHMENT_BYTES:
            return Response(
                {"detail": f"파일이 너무 큽니다. {MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB 이하만 올릴 수 있습니다."},
                status=400,
            )
        raw_date = (d.get("date") or "")[:10]
        pd = parse_date(raw_date) if raw_date else None
        ts = timezone.make_aware(datetime.combine(pd, time(12, 0))) if pd else timezone.now()
        amount = int(re.sub(r"[^0-9]", "", str(d.get("amount") or "0")) or 0)
        # 화면이 **어느 카드인지** 보낸다. 예전엔 구분(개인/팀/공용)만 받아 그 구분의
        #  `first()`를 붙였다 — 남의 개인카드가 내 지출에 붙을 수 있었고, 카드 귀속이
        #  판정 사실(`card.actual_user_recorded` 등)이라 그대로 오판이 된다.
        #  `cardId`가 없는 옛 호출은 종전대로 구분 매칭으로 떨어진다(하위호환).
        card = _resolve_card(d, _actor(request))
        category = d.get("category") or d.get("aiCategory") or ""
        bad = _invalid_category(category, d.get("aiCategory"))
        if bad:
            return Response({"detail": bad}, status=400)

        #  **기본 내역을 사람이 안 넣었으면 영수증 판독이 채우도록 표시한다.**
        #  화면이 파일만 받고 저장하는 흐름(비전이 가맹점·금액을 읽어 채운다)의 진입점이다.
        #  사람이 직접 친 값에는 표시를 달지 않는다 — 나중에 판독이 그 값을 덮으면
        #  사용자가 보는 앞에서 사실이 바뀐다.
        typed_merchant = str(d.get("merchant") or "").strip()
        basics_pending = not typed_merchant or amount <= 0
        tx = Transaction.objects.create(
            card=card,
            merchant=typed_merchant or evidence_extract.PLACEHOLDER_MERCHANT,
            amount=amount,
            ts=ts,
            raw_payload={"source": "USER_UPLOAD",
                         evidence_extract.BASICS_PENDING_KEY: basics_pending},
        )
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

        #  같은 파일을 두 자리에 건다. 역할이 다르다:
        #   · `Receipt` — 거래-영수증 매칭(판정의 `evidence.has_valid_receipt`가 이걸 본다)
        #   · `Attachment(RECEIPT)` — 판독 대상(비전이 품목·주류 여부 등 **판정 사실**을 뽑는다)
        attachment = Attachment.objects.create(
            settlement=s, kind=AttachmentKind.RECEIPT, file=upload,
            original_name=upload.name[:200], mime_type=(upload.content_type or "")[:100],
            uploaded_by=actor,
        )
        attachment.file_ref = attachment.file.name
        attachment.save(update_fields=["file_ref"])
        Receipt.objects.create(
            matched_tx=tx, status=Receipt.Status.MATCHED, file_ref=attachment.file_ref,
        )
        evidence_extract.schedule(attachment)
        return Response(self.get_serializer(s).data, status=201)

    # PATCH /api/settlements/{id}/  — 상세 화면 수정 저장
    def update(self, request, *args, **kwargs):
        """화면에서 고친 값을 저장한다. **제출 버튼이 이걸 먼저 부른다.**

        이게 없던 동안 상세 모달은 제목만 "수정"이었고 실제로는 아무것도 저장하지 않았다
        — 분류를 고르고 목적을 적어 제출해도 서버에는 그대로 남아, 판정이 「분류 미기재」로
        걸었다. 사람이 확인하고 올린 값이 판정에 닿지 않으면 확인 자체가 의미가 없다.

        **`category`는 사람이 확정한 값이다.** 화면 드롭다운에 AI 제안이 미리 채워져 있어도,
        저장하는 순간 그건 「사람이 그 값으로 확정했다」는 기록이 된다. `ai_category`는
        건드리지 않는다 — AI가 원래 뭐라고 했는지를 남겨둬야 나중에 제안↔확정을 대조해
        정확도를 잴 수 있다(그게 지도학습 피드백의 원천이다).

        DRF 기본 `update`를 쓰지 않는 이유: 금액·가맹점·일자는 `Transaction`에 있고
        시리얼라이저에서 read-only라 그대로는 저장되지 않는다.
        """
        settlement = self.get_object()
        if settlement.status not in EDITABLE_STATUSES:
            return Response(
                {"detail": "회계 검토가 시작된 뒤에는 수정할 수 없습니다. 보완요청을 받은 뒤 고쳐주세요."},
                status=400,
            )
        actor = _actor(request)
        if actor and settlement.submitted_by_id and settlement.submitted_by_id != actor.id:
            return Response({"detail": "본인이 등록한 건만 수정할 수 있습니다."}, status=403)

        d = request.data
        fields = []
        if "category" in d:
            # 빈 값이면 지우지 않고 그대로 둔다 — 화면이 실수로 빈 값을 보내 확정 분류를
            # 날리는 편보다, 안 바뀌는 편이 낫다(지우려면 사용자가 다른 분류를 고른다).
            if d.get("category"):
                bad = _invalid_category(d["category"])
                if bad:
                    return Response({"detail": bad}, status=400)
                settlement.category = d["category"]
                # **사람이 확인한 순간 AI 제안 딱지를 뗀다.** `ai_suggested`는 "이 분류는 AI가
                # 넣은 값이라 사람 확인이 필요하다"는 뜻인데, 지금 그 확인이 일어났다. 남겨두면
                # `category.confidence`가 계속 저신뢰(0.5)로 내려가 확인된 건이 다시 걸린다.
                # (`ai_category`는 그대로 둔다 — AI가 원래 뭐라고 했는지는 대조에 쓴다.)
                settlement.ai_suggested = False
                fields += ["category", "ai_suggested"]
        if "purpose" in d:
            settlement.purpose = d.get("purpose") or ""
            fields.append("purpose")
        if "merchantIndustry" in d or "merchantIndustryCode" in d:
            code, label = industry_vocab.resolve(
                d.get("merchantIndustryCode") or d.get("merchantIndustry")
            )
            settlement.merchant_industry, settlement.merchant_industry_code = label, code
            fields += ["merchant_industry", "merchant_industry_code"]
        # 판정 입력 컬럼 — 전부 null 허용이고 `None`은 「모름」이다. 키가 없으면 건드리지 않는다.
        for key, column in (
            ("headcount", "headcount"), ("externalHeadcount", "external_headcount"),
            ("preApproved", "pre_approved"), ("itemType", "item_type"),
            ("kickbackTarget", "kickback_target"), ("isSecondaryVenue", "is_secondary_venue"),
            ("includesAlcohol", "includes_alcohol"),
        ):
            if key in d:
                setattr(settlement, column, d[key])
                fields.append(column)
        if fields:
            settlement.save(update_fields=[*fields, "updated_at"] if hasattr(settlement, "updated_at") else fields)

        tx = settlement.transaction
        tx_fields = []
        if d.get("cardId"):
            card = _resolve_card(d, actor)
            if card is None:
                return Response({"detail": "선택한 카드를 사용할 수 없습니다."}, status=400)
            tx.card = card
            tx_fields.append("card")
        if d.get("merchant"):
            tx.merchant = d["merchant"]
            tx_fields.append("merchant")
        if d.get("amount") not in (None, ""):
            tx.amount = int(re.sub(r"[^0-9]", "", str(d["amount"])) or 0)
            tx_fields.append("amount")
        if d.get("date"):
            pd = parse_date(str(d["date"])[:10])
            if pd:
                # 시각은 유지한다 — 날짜만 고쳤는데 결제 시각이 정오로 밀리면
                # 심야 결제 판정(`derived.is_late_night`)이 조용히 뒤집힌다.
                current = timezone.localtime(tx.ts) if tx.ts else None
                tx.ts = timezone.make_aware(datetime.combine(pd, current.time() if current else time(12, 0)))
                tx_fields.append("ts")
        if tx_fields:
            tx.save(update_fields=tx_fields)

        settlement.refresh_from_db()
        return Response(self.get_serializer(settlement).data)

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

    # POST /api/settlements/{id}/risk-review/  — AI 위험 검토 재실행
    @action(detail=True, methods=["post"], url_path="draft")
    def draft_for_settlement(self, request, pk=None):
        """POST /api/settlements/{id}/draft/ — 저장된 건으로 초안 작성(분류·목적·설명·안내).

        폼 값을 보내는 `draft-suggest`와 다르다. 여기서는 **기본 내역을 화면이 보내지 않는다** —
        ERP 수집·영수증 비전·카드 원장이 확정한 사실을 ai가 서버에서 직접 읽어 간다
        (`/api/internal/settlement-draft-context/`). 그래서 모델이 가맹점·금액을 지어낼 자리가 없다.

        **폴백을 두지 않는다.** 사실 조회가 실패했는데 폼 값으로 그럴듯한 초안을 만들면
        사용자는 그걸 성공으로 읽는다 — 이 모드가 없애려던 상태로 되돌아간다.
        """
        settlement = self.get_object()
        actor = _actor(request)
        if actor and settlement.submitted_by_id and settlement.submitted_by_id != actor.id:
            return Response({"detail": "본인이 등록한 건만 초안을 만들 수 있습니다."}, status=403)

        try:
            resp = httpx.post(
                f"{settings.AI_BASE_URL}/agent/draft/settlement",
                json={"settlementId": settlement.pk,
                      "instruction": str(request.data.get("instruction") or "")},
                timeout=60,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return Response({"detail": f"초안 작성 실패: {exc.response.text[:300]}"},
                            status=exc.response.status_code)
        except httpx.HTTPError as exc:
            return Response(
                {"detail": f"AI 서비스({settings.AI_BASE_URL})에 연결하지 못했습니다 — "
                           f"{type(exc).__name__}: {exc}"},
                status=503,
            )
        return Response(resp.json())

    @action(detail=True, methods=["post"], url_path="prepare-submit")
    def prepare_submit(self, request, pk=None):
        """POST /api/settlements/{id}/prepare-submit/ — 제출 직전 다듬기 + 확인 필요 여부.

        기본 동작은 **조용히 다듬어 그대로 제출**이다. `shouldConfirm`이 참일 때만 화면이
        사람을 멈춰 세운다 — 그 기준은 서버가 정한다(화면이 갖고 있으면 곧 갈린다).
        """
        settlement = self.get_object()
        actor = _actor(request)
        if actor and settlement.submitted_by_id and settlement.submitted_by_id != actor.id:
            return Response({"detail": "본인이 등록한 건만 제출 준비를 할 수 있습니다."}, status=403)
        if settlement.status not in EDITABLE_STATUSES:
            return Response({"detail": "이미 넘어간 건은 제출 준비를 할 수 없습니다."}, status=400)
        return Response(submit_prep.prepare(settlement))

    @action(detail=True, methods=["post"], url_path="risk-review")
    def rerun_risk_review(self, request, pk=None):
        """실패한(또는 결과가 안 온) Risk Review를 다시 돌린다.

        `/judge/`로는 안 된다 — 판정 재실행은 `SUBMITTED → RPA_JUDGED` 전이를 전제하는데
        이 건은 이미 `IN_REVIEW`다. 상태를 건드리지 않고 **AI 호출만** 다시 예약한다.
        """
        settlement = self.get_object()
        if settlement.status != SettlementStatus.IN_REVIEW:
            return Response(
                {"detail": "검토중(IN_REVIEW) 건만 위험 검토를 다시 실행할 수 있습니다."}, status=400,
            )
        risk_review.schedule(settlement)
        settlement.refresh_from_db()
        return Response(self.get_serializer(settlement).data)

    # POST /api/settlements/{id}/decision-reason/  — 보완요청·반려 사유 **초안**
    @action(detail=True, methods=["post"], url_path="decision-reason")
    def decision_reason(self, request, pk=None):
        """결정 사유 모달이 열릴 때 부른다. 판정 결과와 내역을 보고 문장을 채워 준다.

        **대신 결정해 주지 않는다** — 초안은 화면에서 편집 가능하고, 저장되는 건 사람이
        최종적으로 보낸 문구다. ai가 없어도 판정 플래그로 폴백하므로 결정이 막히지 않는다.
        """
        settlement = self.get_object()
        decision = str(request.data.get("decision") or "RETURN").upper()
        if decision not in decision_reasons.DECISIONS:
            return Response(
                {"detail": f"decision은 {', '.join(decision_reasons.DECISIONS)} 중 하나여야 합니다."},
                status=400,
            )
        return Response(decision_reasons.draft(settlement, decision))

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


    # ── 증빙 첨부 + 판독 ──────────────────────────────────────────────
    #  업로드가 곧 판독 트리거다. 별도 "분석" 버튼을 두면 아무도 누르지 않고, 추출 결과가
    #  없는 채로 제출되면 판정이 그 사실을 `None`(모름)으로 보고 검토로 강등한다.

    @action(detail=True, methods=["get", "post"], url_path="attachments",
            parser_classes=[MultiPartParser, FormParser, JSONParser])
    def attachments(self, request, pk=None):
        s = self.get_object()
        if request.method == "GET":
            return Response(AttachmentSerializer(s.attachments.all(), many=True).data)

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "파일이 필요합니다."}, status=400)
        if upload.size > MAX_ATTACHMENT_BYTES:
            return Response(
                {"detail": f"파일이 너무 큽니다({upload.size // (1024 * 1024)}MB). "
                           f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB 이하만 올릴 수 있습니다."},
                status=400,
            )
        name = (upload.name or "").lower()
        if not name.endswith(ALLOWED_ATTACHMENT_SUFFIXES):
            # 비전 판독기가 이미지·PDF만 연다. 다른 형식을 받아 두면 업로드는 성공했는데
            # 판독만 조용히 실패해서, 사용자는 "첨부했으니 됐다"고 믿는다.
            return Response(
                {"detail": f"지원하지 않는 형식입니다: {upload.name} "
                           f"({', '.join(ALLOWED_ATTACHMENT_SUFFIXES)}만 가능)"},
                status=400,
            )

        kind = str(request.data.get("kind") or AttachmentKind.OTHER).upper()
        if kind not in AttachmentKind.values:
            return Response({"detail": f"알 수 없는 첨부 종류: {kind}"}, status=400)

        att = Attachment.objects.create(
            settlement=s, kind=kind, file=upload,
            original_name=upload.name[:200], mime_type=(upload.content_type or "")[:100],
            uploaded_by=_actor(request),
        )
        #  ai에 넘길 경로는 **media 볼륨 기준 상대경로**다(`app/media.py`가 절대경로를 거부한다).
        att.file_ref = att.file.name
        att.save(update_fields=["file_ref"])
        evidence_extract.schedule(att)
        return Response(AttachmentSerializer(att).data, status=201)

    @action(detail=True, methods=["delete"], url_path=r"attachments/(?P<attachment_id>[0-9]+)")
    def delete_attachment(self, request, pk=None, attachment_id=None):
        s = self.get_object()
        att = s.attachments.filter(pk=attachment_id).first()
        if att is None:
            return Response({"detail": "첨부를 찾을 수 없습니다."}, status=404)
        att.delete()
        return Response(status=204)

    @action(detail=True, methods=["post"], url_path=r"attachments/(?P<attachment_id>[0-9]+)/reextract")
    def reextract_attachment(self, request, pk=None, attachment_id=None):
        """판독 재시도 — ai가 안 떠 있었거나 타임아웃으로 `FAILED`가 된 건을 다시 태운다."""
        s = self.get_object()
        att = s.attachments.filter(pk=attachment_id).first()
        if att is None:
            return Response({"detail": "첨부를 찾을 수 없습니다."}, status=404)
        evidence_extract.schedule(att)
        return Response(AttachmentSerializer(att).data)


class SettlementDraftContextView(APIView):
    """GET /api/internal/settlement-draft-context/<settlement_id>/ — Draft Agent 입력(내부 read API).

    초안 Agent가 **지어낼 수 없는 것을 전부 사실로** 받아 가는 창구다. 기본 내역(ERP 수집·
    영수증 비전·카드 원장)·업종·첨부 추출 사실·EvalContext·**엔진 판정 미리보기**·보완요청 맥락.

    판정 미리보기가 여기 있는 이유: 「보완요청/반려될 것 같은가」는 결정론적 엔진이 이미
    답을 갖고 있다. 룰 그래프를 LLM에 주고 예측시키면 틀리고, 틀려도 티가 안 난다
    (`draft_context` 모듈 docstring 참조).

    조립은 `domain/settlements/draft_context.py`가 한다 — 뷰는 창구만 연다.
    """
    permission_classes = [AllowAny]

    def get(self, request, settlement_id):
        s = (
            Settlement.objects
            .select_related("transaction", "transaction__card")
            .prefetch_related("attachments", "events")
            .filter(pk=settlement_id)
            .first()
        )
        if s is None:
            return Response({"detail": "정산을 찾을 수 없습니다."}, status=404)
        return Response(draft_context.build(s))


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


class TeamBudgetOverviewView(APIView):
    """GET /api/team-budget/overview/?month=YYYY-MM — **전 팀** 예산 현황(S-08 예산 관리).

    `TeamBudgetView`(팀 하나)와 같은 계산을 팀 수만큼 돌린 것이다. 계산을 복제하지 않고
    같은 규약을 쓴다 — 한도는 `TeamBudget`(DB), 사용액은 그 팀·월 `Settlement` 집계,
    최종 반려(`REJECT`)만 제외.

    별도 엔드포인트로 둔 이유: 응답 셰이프가 다르다(팀 배열). 기존 뷰에 `all=1` 같은
    플래그를 얹으면 같은 URL이 두 가지 모양을 돌려주게 되고, 호출부가 그때그때 분기해야 한다.

    인가는 회계 검토 또는 거버넌스 열람 — Sidebar의 `/budget` 메뉴 조건과 같다.
    """
    permission_classes = [CanAccountingReviewOrGovernance]

    def get(self, request):
        month = request.query_params.get("month") or timezone.localdate().strftime("%Y-%m")

        used_qs = Settlement.objects.exclude(status__in=_BUDGET_EXCLUDE)
        if "-" in month:
            y, m = month.split("-")[:2]
            used_qs = used_qs.filter(transaction__ts__year=int(y), transaction__ts__month=int(m))
        used: dict[tuple[int, str], int] = {
            (r["team_id"], r["category"]): int(r["s"] or 0)
            for r in used_qs.values("team_id", "category").annotate(s=Sum("transaction__amount"))
            if r["team_id"]
        }

        limits: dict[int, dict[str, int]] = {}
        for b in TeamBudget.objects.filter(year_month=month):
            limits.setdefault(b.team_id, {})[b.category] = b.limit_amount

        teams = []
        for team in Team.objects.order_by("name"):
            by_cat = limits.get(team.id, {})
            categories = [
                {"label": cat, "limit": lim, "used": used.get((team.id, cat), 0)}
                for cat, lim in sorted(by_cat.items()) if cat != ""
            ]
            #  예산 행이 없는 과목의 지출 — 총 사용액엔 들어가지만 항목 카드엔 없다.
            #  숨기면 "항목 합 ≠ 총액"이 되어 화면이 어긋나 보인다(TeamBudgetView와 같은 처리).
            budgeted = {c["label"] for c in categories}
            unbudgeted = {
                cat: amt for (tid, cat), amt in used.items()
                if tid == team.id and cat not in budgeted and amt
            }
            team_used = sum(v for (tid, _), v in used.items() if tid == team.id)
            teams.append({
                "id": team.id, "name": team.name,
                "total": by_cat.get("", 0), "used": team_used,
                "categories": categories,
                "unbudgeted": unbudgeted, "unbudgetedUsed": sum(unbudgeted.values()),
            })

        return Response({"month": month, "teams": teams})
