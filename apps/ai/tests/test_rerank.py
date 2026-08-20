"""LLM 재선별(`rag/retrieval/rerank.py`) 회귀 — 실 OpenAI 호출 없이 `_get_client`만 대체한다.

핵심 계약: "LLM이 관련 없다고 답한 것"과 "rerank 호출 자체가 실패한 것"을 구분해야
한다 — 전자는 빈 배열이 진짜 결과고, 후자는 원본 top_n으로 fail-open해야 하류가
"근거가 원래 없었다"로 잘못 수렴하지 않는다.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

# `app.rag.retrieval.__init__`가 `from .rerank import rerank`로 패키지 속성 `rerank`를
# 함수로 덮어써서(정본 export 계약), `import app.rag.retrieval.rerank as x`처럼 dotted
# import는 그 속성 체인을 타 함수를 돌려준다 — 실제 서브모듈을 얻으려면 sys.modules 기반의
# importlib.import_module을 써야 한다.
rerank_mod = importlib.import_module("app.rag.retrieval.rerank")


def _hit(chunk_id: str, text: str = "본문") -> dict:
    return {"chunk_id": chunk_id, "citation": chunk_id, "text": text, "score": 0.5}


def _fake_client(relevant_chunk_ids: list[str] | None, *, raises: bool = False):
    def _parse(**_kw):
        if raises:
            raise RuntimeError("모델 거부")
        parsed = None if relevant_chunk_ids is None else rerank_mod.RerankVerdict(
            relevant_chunk_ids=relevant_chunk_ids
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))])

    completions = SimpleNamespace(parse=_parse)
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(beta=SimpleNamespace(chat=chat))


def test_empty_hits_short_circuits_without_calling_llm(monkeypatch):
    def _fail_if_called():
        raise AssertionError("빈 후보인데 LLM이 호출됨")

    monkeypatch.setattr(rerank_mod, "_get_client", _fail_if_called)
    assert rerank_mod.rerank("질의", [], top_n=6) == []


def test_selects_and_reorders_by_llm_verdict(monkeypatch):
    hits = [_hit("a"), _hit("b"), _hit("c")]
    monkeypatch.setattr(rerank_mod, "_get_client", lambda: _fake_client(["c", "a"]))

    result = rerank_mod.rerank("질의", hits, top_n=6)

    assert [h["chunk_id"] for h in result] == ["c", "a"]


def test_unknown_chunk_id_from_llm_is_dropped(monkeypatch):
    hits = [_hit("a")]
    monkeypatch.setattr(rerank_mod, "_get_client", lambda: _fake_client(["a", "지어낸id"]))

    result = rerank_mod.rerank("질의", hits, top_n=6)

    assert [h["chunk_id"] for h in result] == ["a"]


def test_result_capped_at_top_n(monkeypatch):
    hits = [_hit("a"), _hit("b"), _hit("c")]
    monkeypatch.setattr(rerank_mod, "_get_client", lambda: _fake_client(["a", "b", "c"]))

    result = rerank_mod.rerank("질의", hits, top_n=2)

    assert len(result) == 2


def test_llm_says_none_relevant_returns_empty_not_fallback(monkeypatch):
    """LLM이 명시적으로 '관련 없음'이라 답한 것은 진짜 빈 결과 — 원본으로 폴백하면 안 된다."""
    hits = [_hit("a"), _hit("b")]
    monkeypatch.setattr(rerank_mod, "_get_client", lambda: _fake_client([]))

    assert rerank_mod.rerank("질의", hits, top_n=6) == []


def test_llm_call_failure_falls_back_to_original_top_n(monkeypatch):
    """호출 자체가 실패하면(타임아웃 등) '근거 없음'이 아니라 원본을 그대로 돌려준다."""
    hits = [_hit("a"), _hit("b"), _hit("c")]
    monkeypatch.setattr(rerank_mod, "_get_client", lambda: _fake_client(None, raises=True))

    result = rerank_mod.rerank("질의", hits, top_n=2)

    assert [h["chunk_id"] for h in result] == ["a", "b"]


def test_unparsed_response_falls_back_to_original_top_n(monkeypatch):
    hits = [_hit("a"), _hit("b")]
    monkeypatch.setattr(rerank_mod, "_get_client", lambda: _fake_client(None))

    result = rerank_mod.rerank("질의", hits, top_n=1)

    assert [h["chunk_id"] for h in result] == ["a"]
