"""세션 로그인/로그아웃/현재 사용자 — JWT 대신 Django 세션 인증 사용."""
from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


def user_payload(u):
    if not (u and u.is_authenticated):
        return {"isAuthenticated": False}
    return {
        "isAuthenticated": True,
        "username": u.username,
        "role": getattr(u, "role", "EMPLOYEE"),
        "dept": u.team.name if getattr(u, "team_id", None) else None,
        "teamId": getattr(u, "team_id", None),
        "capabilities": u.capabilities if hasattr(u, "capabilities") else [],
        "isSuperuser": u.is_superuser,
    }


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """csrftoken 쿠키 발급(운영 CSRF 재활성화 대비)."""
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "csrf cookie set"})


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        user = authenticate(request, username=request.data.get("username"), password=request.data.get("password"))
        if user is None:
            return Response({"detail": "아이디 또는 비밀번호가 올바르지 않습니다."}, status=400)
        login(request, user)
        return Response(user_payload(user))


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response({"detail": "logged out"})


class MeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(user_payload(request.user))
