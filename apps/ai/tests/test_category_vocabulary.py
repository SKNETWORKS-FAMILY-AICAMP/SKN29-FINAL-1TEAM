"""비용분류 어휘는 core가 정본 — ai는 런타임에 받아 쓴다.

## 왜 이 파일이 생겼나

ai에는 같은 6개 목록이 세 벌 있었다: `schemas.Category` Literal(구조화 출력 enum),
Draft Agent 프롬프트 문장("다음 6개 중 하나만"), `rule_agent_v0/api.Scope` Literal.
core가 분류를 늘려도 이 셋은 따라오지 않으므로 **모델이 새 분류를 고를 방법 자체가
없었다**(스키마가 enum을 강제하므로 조용히 옛 목록으로 수렴한다).

고정하는 계약:
  ① 구조화 출력 enum은 **core 목록 + 빈 문자열**로 매 호출 시점에 만들어진다.
  ② 프롬프트 지시문도 같은 목록을 본다(스키마만 바꾸면 모델은 "고를 수 있지만 고르면
     안 되는 값"으로 취급한다).
  ③ core 조회가 실패하면 정적 미러로 떨어진다 — 초안 작성 전체가 core 가용성에 묶이지
     않는다(값이 사라지는 변경은 없으므로 낡은 목록은 안전한 방향).
  ④ 빈 문자열은 「아직 못 정했다」 — 모델이 판단할 수 없을 때 아무거나 찍지 않을 자리.
"""
from __future__ import annotations

from typing import get_args

import pytest

from app.agents import draft_agent
from app.clients import core_client
from app.schemas import Category as CategoryMirror

SERVER_VOCAB = ["회식", "회의", "식대", "출장", "접대", "비품", "기타", "신설분류"]


@pytest.fixture(autouse=True)
def _reset_cache():
    core_client._categories_cache = None
    draft_agent._with_categories.cache_clear()
    yield
    core_client._categories_cache = None
    draft_agent._with_categories.cache_clear()


def _serve(monkeypatch, values):
    monkeypatch.setattr(
        core_client, "_get",
        lambda path, timeout=10: {"categories": [{"value": v, "label": v} for v in values]},
    )


# ① 구조화 출력 enum이 서버 목록을 따른다
def test_출력_스키마가_서버_어휘로_만들어진다(monkeypatch):
    _serve(monkeypatch, SERVER_VOCAB)
    model = draft_agent._draft_output_model()
    allowed = set(get_args(model.model_fields["category"].annotation))
    assert "신설분류" in allowed, "core가 늘린 분류를 모델이 고를 수 없다"
    assert allowed == {"", *SERVER_VOCAB}


def test_수정_모드도_같은_어휘를_쓴다(monkeypatch):
    _serve(monkeypatch, SERVER_VOCAB)
    allowed = set(get_args(draft_agent._revise_output_model().model_fields["category"].annotation))
    assert allowed == {"", *SERVER_VOCAB}


# ② 프롬프트도 같은 목록을 본다
def test_프롬프트에_서버_어휘가_들어간다(monkeypatch):
    _serve(monkeypatch, SERVER_VOCAB)
    prompt = draft_agent._system_prompt(draft_agent.SYSTEM_PROMPT_CREATE)
    assert "신설분류" in prompt
    assert "{categories}" not in prompt          # 치환이 실제로 일어났다
    assert "6개" not in prompt                    # 개수를 문장에 박아 두지 않는다


# ③ core가 죽어도 초안 경로는 산다
def test_조회_실패시_정적_미러로_떨어진다(monkeypatch):
    def _boom(path, timeout=10):
        raise RuntimeError("core down")

    monkeypatch.setattr(core_client, "_get", _boom)
    assert core_client.get_categories() == list(get_args(CategoryMirror))


def test_미러에_기타가_들어_있다():
    """폴백 목록에서 `기타`가 빠지면 core가 죽은 동안만 그 분류를 못 고르게 된다."""
    assert "기타" in get_args(CategoryMirror)


# ④ 미분류 자리
def test_빈_문자열이_enum에_포함된다(monkeypatch):
    _serve(monkeypatch, SERVER_VOCAB)
    allowed = get_args(draft_agent._draft_output_model().model_fields["category"].annotation)
    assert "" in allowed


def test_LLM_실패_폴백은_분류를_지어내지_않는다():
    """예전엔 "비품"으로 채웠다 — 사용자에겐 AI가 판단한 값과 구분되지 않았다."""
    assert draft_agent.UNSET_CATEGORY == ""


# 캐시 — 어휘는 배포 단위로만 바뀐다
def test_어휘_조회는_한_번만_나간다(monkeypatch):
    calls = []

    def _counted(path, timeout=10):
        calls.append(path)
        return {"categories": [{"value": v, "label": v} for v in SERVER_VOCAB]}

    monkeypatch.setattr(core_client, "_get", _counted)
    core_client.get_categories()
    core_client.get_categories()
    assert len(calls) == 1
