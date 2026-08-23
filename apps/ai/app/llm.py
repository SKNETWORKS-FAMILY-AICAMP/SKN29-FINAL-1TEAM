"""LLM 호출 어댑터 — **모델 이름과 파라미터 차이를 여기서만 안다.**

## 왜 이 계층이 생겼나

모델 이름이 Agent마다 `MODEL = "gpt-4o-mini"` 상수로 흩어져 있었다(6곳). 모델을 바꾸려면
전부 고쳐야 하고, 어느 호출이 어느 모델을 쓰는지 한눈에 볼 수 없었다.

더 나쁜 건 **모델 계열마다 호출 규칙이 다르다**는 점이다. `gpt-5-mini`류 추론 모델은
커스텀 `temperature`를 받지 않고(기본 1만 허용, 다른 값은 400) 대신 `reasoning_effort`를
받는다. 그 규칙을 호출부가 각자 알고 있으면 새 모델을 끼울 때마다 같은 실수가 반복된다 —
실제로 `rule_agent_v0`의 세 호출부가 같은 주석("gpt-5-mini류는 temperature 미지원")을
각자 달고 있었다.

## 호출부는 **역할**로 부른다

    llm.chat("fast",  messages=..., temperature=0.3, ...)   # 표시용 변환·문체 다듬기
    llm.chat("heavy", messages=..., ...)                    # 판단이 결과가 되는 자리

`temperature`를 heavy에 넘겨도 **조용히 떨어뜨린다**(400 대신). 호출부가 프로파일을 바꿔
끼울 때 파라미터까지 같이 고치게 만들면, 안 고치고 400을 만나는 쪽이 더 흔하다.

## 구조화 출력은 `create()` + json_schema를 쓴다

`beta.chat.completions.parse(response_format=PydanticModel)`가 heavy 계열에서 되는지는
이 저장소에 실측 기록이 없다. 검증된 경로(`create()` + 명시적 json_schema)만 쓴다 —
`schema_of()`가 pydantic 모델에서 그 스키마를 뽑아 준다.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

Profile = Literal["fast", "heavy"]
T = TypeVar("T", bound=BaseModel)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """지연 생성 — import 시점에 키가 없어도 서비스 전체가 죽지 않게."""
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY 가 비어 있다 — 레포 루트 `.env`에 넣을 것")
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def model_of(profile: Profile) -> str:
    """프로파일이 실제로 쓰는 모델 이름 — 추적·기록용(어느 모델의 결과인지 남겨야 한다)."""
    return settings.llm_heavy_model if profile == "heavy" else settings.llm_fast_model


def schema_of(model: type[BaseModel], name: str) -> dict[str, Any]:
    """pydantic 모델 → OpenAI structured output 스키마.

    `additionalProperties: false`와 전 필드 required는 API가 strict 모드에서 요구한다.
    pydantic이 만드는 스키마에 그게 빠져 있으면 스키마 자체가 거부되므로 여기서 채운다.
    """
    schema = model.model_json_schema()
    _harden(schema)
    return {"name": name, "strict": True, "schema": schema}


def _harden(node: Any) -> None:
    """중첩 객체까지 strict 요건을 채운다(`$defs` 포함)."""
    if not isinstance(node, dict):
        return
    if node.get("type") == "object":
        node.setdefault("additionalProperties", False)
        props = node.get("properties")
        if isinstance(props, dict):
            #  strict 모드는 **모든** 프로퍼티가 required여야 한다. 선택 필드는 스키마에서
            #  기본값으로 채워지지 않으므로, 모델 쪽에서 빈 값을 허용하는 타입을 쓴다.
            node["required"] = list(props)
    for value in node.values() if isinstance(node, dict) else []:
        if isinstance(value, dict):
            _harden(value)
        elif isinstance(value, list):
            for item in value:
                _harden(item)


def chat(
    profile: Profile,
    *,
    messages: list[dict[str, Any]],
    timeout: float = 60,
    temperature: float | None = None,
    response_format: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
):
    """모델 호출 1회. 프로파일별 파라미터 차이는 여기서 흡수한다."""
    kwargs: dict[str, Any] = {
        "model": model_of(profile),
        "timeout": timeout,
        "messages": messages,
    }

    if profile == "heavy":
        kwargs["reasoning_effort"] = settings.llm_heavy_reasoning_effort
        if temperature is not None:
            #  조용히 떨어뜨리지 않고 티를 낸다 — 호출부가 온도를 의도했는데 무시됐다는
            #  사실을 알아야, "왜 출력이 안 조여지지"를 여기서 찾을 수 있다.
            logger.debug("heavy 프로파일은 temperature를 지원하지 않아 무시한다 (%.2f)", temperature)
    elif temperature is not None:
        kwargs["temperature"] = temperature

    if response_format is not None:
        kwargs["response_format"] = {"type": "json_schema", "json_schema": response_format}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"

    return _get_client().chat.completions.create(**kwargs)


def parse(
    profile: Profile,
    *,
    model: type[T],
    schema_name: str,
    messages: list[dict[str, Any]],
    timeout: float = 60,
    temperature: float | None = None,
) -> tuple[T, Any]:
    """구조화 출력 한 번. `(파싱된 모델, 원본 응답)`을 돌려준다.

    원본 응답도 같이 주는 이유: 토큰·지연을 추적(AI-LAB)에 남기는 호출부가 있다.
    """
    resp = chat(
        profile,
        messages=messages,
        timeout=timeout,
        temperature=temperature,
        response_format=schema_of(model, schema_name),
    )
    content = resp.choices[0].message.content
    if not content:
        raise ValueError("LLM이 빈 응답을 돌려줬다(모델 거부 등)")
    return model.model_validate(json.loads(content)), resp
