"""세션 인증(SPA용). dev 편의를 위해 CSRF 검사를 생략한다.

⚠️ 운영 전환 시 CSRF를 재활성화(기본 SessionAuthentication 사용 + 프론트에서 X-CSRFToken 전송)해야 한다.
"""
from rest_framework.authentication import SessionAuthentication


class CsrfExemptSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):  # noqa: ARG002
        return  # dev: CSRF 생략
