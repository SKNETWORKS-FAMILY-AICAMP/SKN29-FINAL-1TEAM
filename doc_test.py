from pathlib import Path
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend

pipeline_options = PdfPipelineOptions()
pipeline_options.do_ocr = False  # 전자 PDF 확정이므로 OCR 비활성화

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=pipeline_options,
            backend=PyPdfiumDocumentBackend,
        )
    }
)

pdf_path = "/Users/kyoungchan/SKN29-FINAL-1TEAM/SKN29-FINAL-1TEAM/tiger_inc/pdf/법인카드_사용규정_타이거.pdf"
result = converter.convert(pdf_path)
markdown_text = result.document.export_to_markdown()

# md로 저장
out_path = Path(pdf_path).with_suffix(".docling.md")
out_path.write_text(markdown_text, encoding="utf-8")
print(f"저장 완료: {out_path}")

import re
import difflib
from pathlib import Path

def normalize(text: str) -> str:
    """마크다운 문법·공백 차이를 제거하고 순수 텍스트만 남김"""
    text = re.sub(r"[#*`_>\-|]", " ", text)      # 마크다운 특수문자 제거
    text = re.sub(r"\s+", " ", text).strip()      # 공백 정규화
    return text

def word_set(text: str) -> set:
    return set(re.findall(r"[가-힣A-Za-z0-9]+", text))

def compare(original_path: str, docling_path: str):
    original = Path(original_path).read_text(encoding="utf-8")
    docling  = Path(docling_path).read_text(encoding="utf-8")

    norm_orig = normalize(original)
    norm_doc  = normalize(docling)

    # 1) 문자 단위 유사도 (전체적인 순서·표현 일치도)
    char_ratio = difflib.SequenceMatcher(None, norm_orig, norm_doc).ratio()

    # 2) 단어 단위 Jaccard 유사도 (순서 무관, 누락/추가 단어 감지에 강함)
    orig_words = word_set(original)
    doc_words  = word_set(docling)
    jaccard = len(orig_words & doc_words) / len(orig_words | doc_words)

    # 3) 원본에는 있는데 Docling 결과에 없는 단어 (누락 탐지)
    missing = orig_words - doc_words
    extra   = doc_words - orig_words

    print("=" * 50)
    print(f"문자 단위 유사도(SequenceMatcher): {char_ratio:.4f}")
    print(f"단어 단위 유사도(Jaccard):         {jaccard:.4f}")
    print(f"원본 단어 수: {len(orig_words)} / Docling 단어 수: {len(doc_words)}")
    print(f"누락된 단어 수: {len(missing)}")
    print(f"추가된 단어 수: {len(extra)}")
    print("=" * 50)

    if missing:
        print("\n[누락 의심 단어] (상위 30개)")
        print(sorted(missing)[:30])
    if extra:
        print("\n[추가 의심 단어] (상위 30개)")
        print(sorted(extra)[:30])

    # 4) 상세 diff 리포트 파일로 저장 (줄 단위)
    diff = difflib.unified_diff(
        original.splitlines(),
        docling.splitlines(),
        fromfile="원본(source).md",
        tofile="docling_출력.md",
        lineterm="",
    )
    diff_path = Path(docling_path).with_suffix(".diff.txt")
    diff_path.write_text("\n".join(diff), encoding="utf-8")
    print(f"\n상세 diff 저장: {diff_path}")

    return {"char_ratio": char_ratio, "jaccard": jaccard,
            "missing": missing, "extra": extra}


# 사용 예시 — 원본 소스 md 경로를 실제 위치로 맞춰주세요
ORIGINAL_MD = "/Users/kyoungchan/SKN29-FINAL-1TEAM/SKN29-FINAL-1TEAM/tiger_inc/md/법인카드_사용규정_타이거.md"
DOCLING_MD  = "/Users/kyoungchan/SKN29-FINAL-1TEAM/SKN29-FINAL-1TEAM/tiger_inc/pdf/법인카드_사용규정_타이거.docling.md"

compare(ORIGINAL_MD, DOCLING_MD)