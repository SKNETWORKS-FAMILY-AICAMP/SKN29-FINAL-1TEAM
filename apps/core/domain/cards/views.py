"""법인카드 관리 (S-09) — 조회 · 배정 변경 · 회수/정지.

## 저장하는 것과 계산하는 것

**저장**은 사람이 내린 결정뿐이다 — 배정(`owner`/`team`)과 정지(`status`·사유). 나머지는
요청 시점에 계산한다:

  · `usage`     그 카드·그 달의 `Transaction` 합계 (`TeamBudget`과 같은 규율 — 한도만 DB)
  · `attention` "회수/중지가 필요한가" — 퇴사(`owner.is_active=False`)·반복 이상사용

`attention`을 컬럼으로 굳히지 않는 이유: 퇴사 처리를 한 뒤에도 카드가 `NORMAL`로 남아
**조용히 어긋난다**. 계산값이면 원인이 사라지는 순간 같이 사라진다.

인가는 `accounting_review` — 카드 배정·회수는 회계 업무 범주다(Sidebar 주석과 동일 기준).
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from domain.accounts.models import Team, User
from domain.common.permissions import CanAccountingReview
from domain.transactions.models import Transaction

from .models import Card, CardStatus, CardType
from .serializers import CardSerializer

#: 반복 이상사용 판정 — 최근 N일 안에 **같은 가맹점**에서 K회 이상.
#  이건 Risk Review(건별 이상탐지)와 다른 축이다: 여기서 보는 건 거래 한 건의 이상함이
#  아니라 "이 카드를 계속 들고 있어도 되는가"다. 임계값은 화면에 그대로 표기한다 —
#  근거를 숨기면 회수 결정을 내리는 사람이 판단할 수 없다.
ANOMALY_WINDOW_DAYS = 30
ANOMALY_MIN_COUNT = 10


def _month_bounds(month: str) -> tuple[int, int] | None:
    """'YYYY-MM' → (year, month). 비었거나 형식이 틀리면 None(= 이번 달)."""
    if month and "-" in month:
        try:
            y, m = month.split("-")[:2]
            return int(y), int(m)
        except ValueError:
            return None
    return None


def usage_by_card(month: str = "") -> dict[int, int]:
    """카드별 해당 월 사용액. 요청당 한 번만 부르고 이후는 메모리 룩업(N+1 방지)."""
    qs = Transaction.objects.filter(card__isnull=False)
    bounds = _month_bounds(month) or (timezone.localdate().year, timezone.localdate().month)
    qs = qs.filter(ts__year=bounds[0], ts__month=bounds[1])
    return {
        r["card_id"]: int(r["s"] or 0)
        for r in qs.values("card_id").annotate(s=Sum("amount"))
    }


def repeat_anomaly_cards() -> dict[int, dict]:
    """최근 창 안에서 같은 가맹점 반복 결제가 임계값을 넘은 카드 → 근거."""
    since = timezone.now() - timedelta(days=ANOMALY_WINDOW_DAYS)
    rows = (
        Transaction.objects.filter(card__isnull=False, ts__gte=since)
        .values("card_id", "merchant")
        .annotate(n=Count("id"))
        .filter(n__gte=ANOMALY_MIN_COUNT)
        .order_by("-n")
    )
    out: dict[int, dict] = {}
    for r in rows:
        out.setdefault(r["card_id"], {
            "merchant": r["merchant"], "count": r["n"], "windowDays": ANOMALY_WINDOW_DAYS,
        })
    return out


def attention_of(card: Card, anomalies: dict[int, dict]) -> dict | None:
    """이 카드가 조치 대상인가 — 정지된 카드는 이미 처리된 것이므로 제외한다."""
    if card.status == CardStatus.STOPPED:
        return None
    if card.owner_id and not card.owner.is_active:
        who = card.owner.first_name or card.owner.username
        return {
            "reason": "RETIRED_OWNER",
            "label": "퇴사 처리",
            "note": f"{who} 퇴사 처리 완료 — 카드 회수 필요",
            "dateLabel": "퇴사일",
            # 퇴사일 컬럼이 없다. 지어내지 않고 비워 둔다(화면이 '-'로 표시).
            "date": "",
        }
    hit = anomalies.get(card.id)
    if hit:
        return {
            "reason": "REPEAT_ANOMALY",
            "label": "반복 이상사용 감지",
            "note": f"최근 {hit['windowDays']}일 내 동일 가맹점({hit['merchant']}) {hit['count']}회 결제 감지",
            "dateLabel": "감지일",
            "date": timezone.localdate().isoformat(),
        }
    return None


class CardViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/cards/ · POST /api/cards/{id}/assign/ · POST /api/cards/{id}/stop/

    쓰기는 전용 액션 둘뿐이다(일반 PATCH를 열지 않는다) — 배정과 정지는 사유가 함께
    남아야 하는 결정이라, 아무 필드나 고칠 수 있는 통로를 두면 그 기록이 비어버린다.
    """
    queryset = Card.objects.select_related("owner", "owner__team", "team")
    serializer_class = CardSerializer
    permission_classes = [CanAccountingReview]

    def get_permissions(self):
        #  「내 카드」는 **본인이 쓸 수 있는 카드**를 고르는 목록이라 회계 권한을 요구하면
        #  안 된다(지출 등록은 임직원 누구나 한다). 대신 결과가 본인 것으로 제한된다.
        if self.action == "mine":
            return [IsAuthenticated()]
        return super().get_permissions()

    @action(detail=False, methods=["get"], url_path="mine")
    def mine(self, request):
        """지출 등록·수정 화면의 카드 선택지 — **이 사람이 실제로 쓸 수 있는 카드만.**

        예전엔 화면이 카드 **구분**(개인/팀/공용)만 골랐고, 서버가 그 구분의 카드 중
        `first()`를 붙였다 — 남의 개인카드가 내 지출에 붙을 수 있는 상태였다. 카드는
        `card.card_type`·귀속을 통해 판정 사실(`card.actual_user_recorded` 등)이 되므로
        엉뚱한 카드가 붙으면 그대로 오판이 된다.

        범위: 본인에게 배정된 개인카드 ∪ 소속 팀의 팀·공용카드 ∪ 팀이 없는 공용카드
        (후정산·선불처럼 팀이 안 붙는 회사 공용 수단). **정지된 카드는 제외**한다.
        """
        user = request.user
        qs = self.get_queryset().filter(status=CardStatus.ACTIVE)
        scope = Q(owner=user)
        if user.team_id:
            scope |= Q(team_id=user.team_id, owner__isnull=True)
        # 팀도 주인도 없는 카드는 회사 공용 수단이라 누구나 고를 수 있다.
        scope |= Q(team__isnull=True, owner__isnull=True)
        cards = qs.filter(scope).order_by("card_type", "name")
        return Response(self.get_serializer(cards, many=True).data)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        month = self.request.query_params.get("month") or ""
        ctx["usage"] = usage_by_card(month)
        ctx["anomalies"] = repeat_anomaly_cards()
        return ctx

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        if (t := request.query_params.get("type")):
            qs = qs.filter(card_type=t)
        if (team := request.query_params.get("team")):
            qs = qs.filter(team_id=team)
        if (st := request.query_params.get("status")):
            qs = qs.filter(status=st)
        ser = self.get_serializer(qs, many=True)
        return Response({
            "month": request.query_params.get("month") or timezone.localdate().strftime("%Y-%m"),
            "cards": ser.data,
            "cardTypes": [{"value": c.value, "label": c.label} for c in CardType],
            #  배정 변경 모달의 선택지. 화면이 이름 문자열을 들고 다니지 않게 **id로** 내려준다 —
            #  동명이인이 생기면 이름 매칭은 조용히 엉뚱한 사람에게 카드를 붙인다.
            "teams": [{"id": t.id, "name": t.name} for t in Team.objects.order_by("name")],
            "people": [
                {
                    "id": u.id,
                    "name": u.first_name or u.username,
                    "team": u.team.name if u.team_id else "",
                    "active": u.is_active,
                }
                for u in User.objects.filter(is_active=True).select_related("team").order_by("first_name", "username")
            ],
        })

    @action(detail=False, methods=["get"], url_path="attention")
    def attention(self, request):
        """조치가 필요한 카드만 사유별로 묶어 돌려준다(화면의 '회수/중지 필요' 뷰)."""
        ser = self.get_serializer(self.get_queryset(), many=True)
        rows = [c for c in ser.data if c.get("attention")]
        groups: dict[str, list] = {}
        for c in rows:
            groups.setdefault(c["attention"]["reason"], []).append(c)
        return Response({
            "total": len(rows),
            "groups": [
                {"reason": k, "label": v[0]["attention"]["label"], "cards": v}
                for k, v in groups.items()
            ],
            "anomalyRule": {"windowDays": ANOMALY_WINDOW_DAYS, "minCount": ANOMALY_MIN_COUNT},
        })

    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        """배정 변경 — 팀 배정과 개인 배정은 **서로를 지운다**.

        둘 다 채워두면 `card_type`과 실제 귀속이 어긋나고, 정산 귀속(`erp_import`)이
        어느 쪽을 볼지 알 수 없게 된다.
        """
        card = self.get_object()
        mode = str(request.data.get("mode") or "").upper()
        if mode not in {"TEAM", "PERSONAL"}:
            return Response({"detail": "mode는 TEAM 또는 PERSONAL이어야 합니다."}, status=400)

        if mode == "TEAM":
            team = Team.objects.filter(pk=request.data.get("teamId")).first()
            if team is None:
                return Response({"detail": "배정할 팀을 찾을 수 없습니다."}, status=400)
            card.card_type, card.team, card.owner = CardType.TEAM, team, None
        else:
            user = User.objects.filter(pk=request.data.get("userId")).first()
            if user is None:
                return Response({"detail": "배정할 사용자를 찾을 수 없습니다."}, status=400)
            card.card_type, card.owner, card.team = CardType.PERSONAL, user, user.team
        card.save(update_fields=["card_type", "owner", "team"])
        return Response(self.get_serializer(card).data)

    @action(detail=True, methods=["post"], url_path="stop")
    def stop(self, request, pk=None):
        """회수·정지. 사유는 필수다 — "왜 정지됐지"를 나중에 묻는 사람이 반드시 나온다."""
        card = self.get_object()
        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            return Response({"detail": "정지 사유를 입력해 주세요."}, status=400)
        card.status = CardStatus.STOPPED
        card.stopped_reason = reason
        card.stopped_at = timezone.now()
        card.stopped_by = request.user
        card.save(update_fields=["status", "stopped_reason", "stopped_at", "stopped_by"])
        return Response(self.get_serializer(card).data)

    @action(detail=True, methods=["post"], url_path="reactivate")
    def reactivate(self, request, pk=None):
        """정지 해제. 사유 기록은 남긴 채 상태만 되돌린다(무슨 일이 있었는지가 지워지면 안 된다)."""
        card = self.get_object()
        card.status = CardStatus.ACTIVE
        card.save(update_fields=["status"])
        return Response(self.get_serializer(card).data)
