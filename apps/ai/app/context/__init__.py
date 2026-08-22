"""Agent Context (ai 쪽) — core 카탈로그를 받아 프롬프트 블록으로 편다.

core(`domain/context`)가 **사실**을 JSON으로 주고, 여기가 **문장**을 만든다. 프롬프트
문구·순서·토큰 예산은 프롬프트를 쓰는 쪽에 있어야 손댈 수 있다.

    from app.context import get_context
    ctx = get_context("rule_generate")
    prompt_block = ctx.prompt()          # 마크다운
    allowed = set(ctx.paths)             # 같은 값이 검증기 기준이 된다
"""
from .client import Bundle, get_context, invalidate

__all__ = ["Bundle", "get_context", "invalidate"]
