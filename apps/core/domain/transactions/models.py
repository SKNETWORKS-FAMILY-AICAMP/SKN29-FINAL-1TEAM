"""거래/증빙 (기술명세서 §3.1).

테이블:
- transactions(merchant, amount, ts, card_id, raw_payload JSONB)
- receipts(file_ref, ocr_text, matched_tx_id, status)
  ※ 영수증은 별도 OCR 없이 OpenAI 비전이 판독(FastAPI). Django는 파일·매칭결과만 보관.
TODO: 모델 구현.
"""
from django.db import models  # noqa: F401
