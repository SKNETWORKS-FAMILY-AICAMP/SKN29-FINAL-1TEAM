"""OpenAI 임베딩 인코더 — `embedding-strategy.md` §7.

문서와 질의를 **다르게** 태운다. 문서는 `Chunk.embedding_text()`(계층 헤더 + 본문),
질의는 `Q_ctx` 접두를 붙인다. 이 비대칭이 실측으로 값을 하는 유일한 조정이다
(📏 본문만 태우는 `A_content`는 전 모델에서 꼴찌 — 평균 MRR −0.050).
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from app.rag.embedding.config import DEFAULT, EmbeddingConfig


def _l2_normalize(vec: Sequence[float]) -> list[float]:
    """L2 정규화 — cosine = 내적 등식을 성립시킨다.

    **`dimensions`로 줄여 받은 벡터는 노름이 1이 아니다.** 재정규화하지 않으면 Chroma의
    cosine 계산이 어긋난다. 멱등이므로 API가 이미 정규화해 줬어도 안전하다.
    """
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:                      # 빈 문자열 등 — 0벡터는 그대로 둔다(검색에서 안 걸림)
        return list(vec)
    return [x / norm for x in vec]


class OpenAIEncoder:
    """배치 임베딩. 클라이언트는 주입 가능하게 둔다(테스트가 API를 부르지 않도록)."""

    def __init__(self, config: EmbeddingConfig = DEFAULT, client=None) -> None:
        self.config = config
        self._client = client
        self.billed_tokens = 0

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI          # 지연 import — 파싱·청킹 테스트가 안 끌게

            from app.config import settings

            if not settings.openai_api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY 가 비어 있다 — 임베딩을 부를 수 없다. "
                    "레포 루트 `.env`에 넣고 다시 실행할 것"
                )
            self._client = OpenAI(api_key=settings.openai_api_key)
        return self._client

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self.config.batch_size):
            batch = list(texts[start : start + self.config.batch_size])
            resp = self.client.embeddings.create(
                model=self.config.model,
                input=batch,
                dimensions=self.config.dimensions,
            )
            usage = getattr(resp, "usage", None)
            self.billed_tokens += getattr(usage, "prompt_tokens", 0) or 0
            # 응답 순서를 믿지 않는다 — index로 되돌린다
            for item in sorted(resp.data, key=lambda d: d.index):
                out.append(_l2_normalize(item.embedding))
        return out

    def encode_documents(self, chunks: Iterable) -> list[list[float]]:
        """`Chunk[]` → 벡터. 임베딩 입력은 저장 문서(`context_text()`)와 **다르다**."""
        return self._encode([c.embedding_text() for c in chunks])

    def encode_queries(self, queries: Sequence[str]) -> list[list[float]]:
        return self._encode([f"{self.config.query_prefix}{q}" for q in queries])

    def encode_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """원문 그대로 임베딩(문서 헤더 주입도, 질의 접두도 없음).

        운영 경로는 쓰지 않는다 — AI-LAB에서 "이 문장과 저 문장이 얼마나 닮았는지"를
        직접 재볼 때처럼, 비대칭 입력 규약 밖에서 벡터를 봐야 하는 실험용 통로다.
        """
        return self._encode(list(texts))
