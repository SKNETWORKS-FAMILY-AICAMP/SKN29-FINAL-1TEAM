"""임베딩 고정 계약 — `llm_wiki/_context/embedding-strategy.md` §1·§8.

**여기 있는 값은 실측으로 고른 것이지 취향이 아니다.** 근거는 평가 노트북
(`docling_eval/docling_embedding_strategy.ipynb` → `output/embedding/`)에 있고,
바꿀 때는 같은 정답셋으로 다시 재고 전략 문서와 함께 갱신한다.

상수로 박지 않고 이 한 곳에 모으는 이유: 모델·차원은 언제든 뒤집힐 수 있다.
후보 1·2위의 ΔMRR은 부트스트랩 CI가 0을 포함해 **통계적으로 구분되지 않고**,
점수 1위는 아예 후보 밖 기준선(`bge-m3`)이었다. 재임베딩은 799청크 30만 토큰이라
싸다 — 코드가 그 전제로 짜여 있을 때만.
"""
from __future__ import annotations

from dataclasses import dataclass

# 문서 유형 → Chroma 컬렉션. DIAGRAM(조직도·직급체계 등)은 `org_docs`로 **분리**한다.
# 규정과 같은 컬렉션에 두면 "내부참고문서" 같은 보일러플레이트 청크가 규정 검색에 섞이고,
# 조직도가 정산 판정 근거로 인용될 수 있다. 결재선의 SoR은 Django(users·teams)이지
# 문서가 아니며, 문서 자신도 "금액 기준은 「법인카드 사용 규정」 별표1에서 관리한다"고
# 선을 긋는다. 판정 경로는 `org_docs`를 검색하지 않는다.
COLLECTION_OF: dict[str, str] = {
    "REGULATION": "policy_docs",
    "LAW": "tax_refs",
    "DIAGRAM": "org_docs",
    "GENERIC": "policy_docs",
}

# 정산 판정(룰·Risk Review)이 근거로 인용해도 되는 컬렉션.
JUDGEMENT_COLLECTIONS = ("policy_docs", "case_history", "tax_refs")

ALL_COLLECTIONS = ("policy_docs", "case_history", "tax_refs", "org_docs")


@dataclass(frozen=True)
class EmbeddingConfig:
    """📏 근거는 전부 `output/embedding/results/`."""

    model: str = "text-embedding-3-large"
    # 네이티브 3072 대비 ΔMRR −0.006(CI가 0 포함 = 잡음)인데 저장은 9.8→3.3MB(−67%).
    # 256은 ΔMRR −0.091(CI가 0 제외)로 **실제 손실** — 여기가 하한이다.
    dimensions: int = 1024
    query_prefix: str = "사내 규정 조문 검색: "     # Q_ctx. ΔMRR +0.014 > TIE_EPS(0.01)
    batch_size: int = 128
    doc_input: str = "B_heading"                  # = Chunk.embedding_text() (헤더+본문)

    @property
    def version(self) -> str:
        """벡터에 새기는 신원. 이 값이 다르면 같은 컬렉션에 섞으면 안 된다."""
        return f"openai/{self.model}@{self.dimensions}/{self.doc_input}"


DEFAULT = EmbeddingConfig()
