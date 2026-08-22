"""GET /api/internal/agent-context/ — 에이전트 프롬프트용 카탈로그 조회.

기존 내부 read API(`PolicyLookupView`·`RuleContextView`·`EvalContextSchemaView`)와 같은
패턴이다: AllowAny · 단일 GET · 관계형 데이터는 Django만 만진다.

쿼리 파라미터
    profile   프로파일 이름 (`profiles.PROFILES`) — 이것만으로 충분한 게 보통이다
    sections  쉼표 구분 섹션 id — 특정 섹션만 집어올 때(툴콜링 중 "쓸 수 있는 플래그 뭐야")

두 개를 동시에 주면 `sections`가 이긴다(더 좁은 요청이므로).
"""
from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import profiles, sections as sections_mod


class AgentContextView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        raw_sections = (request.query_params.get("sections") or "").strip()
        profile = (request.query_params.get("profile") or "").strip()

        if raw_sections:
            ids = [s.strip() for s in raw_sections.split(",") if s.strip()]
            unknown = [s for s in ids if s not in sections_mod.BUILDERS]
            if unknown:
                return Response(
                    {"detail": f"알 수 없는 섹션: {', '.join(unknown)}",
                     "available": sorted(sections_mod.BUILDERS)},
                    status=400,
                )
        elif profile:
            try:
                ids = list(profiles.sections_for(profile))
            except KeyError:
                return Response(
                    {"detail": f"알 수 없는 프로파일: {profile}",
                     "available": sorted(profiles.PROFILES)},
                    status=400,
                )
        else:
            return Response({"detail": "profile 또는 sections 중 하나가 필요합니다."}, status=400)

        payload = sections_mod.build(ids, params=request.query_params.dict())
        payload["profile"] = profile or None
        return Response(payload)
