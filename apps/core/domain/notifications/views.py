"""알림 API.

**queryset은 언제나 `recipient=request.user`로 좁힌다.** 목록만 좁히고 읽음 처리를 안 막으면
남의 알림 id를 찍어 읽음으로 만들 수 있다(카드 선택에서 「목록만 좁히고 저장을 안 막으면
요청을 손댄 값이 들어간다」와 같은 자리).
"""
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification

#: 패널이 한 번에 받는 최대 행 수. 더 오래된 것은 안 보여준다 — 알림함은 아카이브가 아니다.
PAGE_SIZE = 30


class NotificationSerializer(serializers.ModelSerializer):
    kindLabel = serializers.CharField(source="get_kind_display", read_only=True)
    unread = serializers.BooleanField(read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)
    actorName = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id", "kind", "kindLabel", "title", "body", "link", "target",
            "count", "unread", "createdAt", "updatedAt", "actorName",
        ]

    def get_actorName(self, obj):
        actor = obj.actor
        if actor is None:
            return ""
        return actor.get_full_name() or actor.username


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/notifications/ · unread-count · read · read-all"""
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    queryset = Notification.objects.none()   # 라우터 등록용 — 실제 조회는 get_queryset

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Notification.objects.none()
        qs = Notification.objects.filter(recipient=user).select_related("actor")
        if str(self.request.query_params.get("unread") or "") in ("1", "true"):
            qs = qs.filter(read_at__isnull=True)
        return qs

    def list(self, request, *args, **kwargs):
        rows = self.get_queryset()[:PAGE_SIZE]
        return Response({
            "results": self.get_serializer(rows, many=True).data,
            "unreadCount": Notification.objects.filter(
                recipient=request.user, read_at__isnull=True,
            ).count(),
        })

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        """벨 배지가 폴링하는 자리 — **개수만** 돌려준다.

        목록을 폴링하면 서버만 친다(`RiskReviewStatus`가 진행 중일 때만 폴링하는 것과 같은 규율).
        """
        return Response({"count": self.get_queryset().filter(read_at__isnull=True).count()})

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_object()          # get_queryset이 본인 것으로 이미 좁혔다
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        updated = self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response({"updated": updated})

    @action(detail=False, methods=["post"], url_path="read-target")
    def read_target(self, request):
        """대상이 지금 화면에 열려 있어 **이미 확인한** 알림을 접는다.

        룰 콘솔이 그래프를 열 때 부른다 — 「그래프 수정 화면을 벗어나 있는 경우만 알린다」를
        서버가 판단할 수 없기 때문이다(서버는 화면이 어디 있는지 모른다). 그래서 알림은
        **항상 만들고 화면이 접는다.**
        """
        target = str(request.data.get("target") or "").strip()
        if not target:
            return Response({"detail": "target이 필요합니다."}, status=400)
        updated = (
            self.get_queryset()
            .filter(target=target, read_at__isnull=True)
            .update(read_at=timezone.now())
        )
        return Response({"updated": updated})
