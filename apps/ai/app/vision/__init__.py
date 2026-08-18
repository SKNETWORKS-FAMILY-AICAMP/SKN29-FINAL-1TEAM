"""비전 판독 — 이미지·PDF에서 정산 판정에 쓸 사실을 뽑는다.

두 도구로 나뉜다. 입력 형태가 아니라 **뽑는 대상**이 다르기 때문이다:

  · `receipt.read_receipt`            영수증 → 사용내역(가맹점·금액·일시·품목) + 판정 사실
  · `document.read_evidence_document` 증빙 문서 → 판정 사실만 (`Attachment.extracted` 계약)

영수증은 화면이 보여줄 "내역"이 결과물의 절반이고, 증빙 문서는 전부가 판정 사실이다.
둘 다 `mcp/tools.py`를 통해 노출되며(§5 tool 경유 원칙), 공통 호출부는 `client.py`에 있다.
"""
from app.vision.document import read_evidence_document
from app.vision.receipt import read_receipt

__all__ = ["read_receipt", "read_evidence_document"]
