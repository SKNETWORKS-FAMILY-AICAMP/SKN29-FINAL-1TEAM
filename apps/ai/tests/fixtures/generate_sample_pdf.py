"""Generate a tiny, dependency-free, hand-built single-page PDF fixture for
docling parsing smoke tests: a title, two headed articles (paragraph text),
and a simple bordered 2x2 table. No reportlab/fpdf available in the env, so
this writes raw PDF objects + xref table directly.
"""
from __future__ import annotations

import pathlib


def _content_stream() -> bytes:
    lines = [
        "BT /F1 18 Tf 72 720 Td (Chapter 1 General Provisions) Tj ET",
        "BT /F1 12 Tf 72 690 Td (Article 1 Purpose) Tj ET",
        "BT /F2 10 Tf 72 670 Td (This document sets out sample provisions for testing.) Tj ET",
        "BT /F2 10 Tf 72 655 Td (It exists only to validate the PDF parsing pipeline.) Tj ET",
        "BT /F1 12 Tf 72 620 Td (Article 2 Definitions) Tj ET",
        "BT /F2 10 Tf 72 600 Td (Table 1 shows sample limits by category.) Tj ET",
        # table grid (3 horizontal + 3 vertical lines -> 2x2 grid)
        "72 580 m 400 580 l S",
        "72 560 m 400 560 l S",
        "72 540 m 400 540 l S",
        "72 580 m 72 540 l S",
        "236 580 m 236 540 l S",
        "400 580 m 400 540 l S",
        "BT /F1 10 Tf 80 565 Td (Category) Tj ET",
        "BT /F1 10 Tf 250 565 Td (Limit) Tj ET",
        "BT /F2 10 Tf 80 545 Td (Meal) Tj ET",
        "BT /F2 10 Tf 250 545 Td (50000) Tj ET",
    ]
    return ("\n".join(lines) + "\n").encode("latin-1")


def build_pdf() -> bytes:
    stream = _content_stream()
    objects: list[bytes] = []

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(
        ("<< /Length %d >>\nstream\n" % len(stream)).encode("latin-1")
        + stream
        + b"endstream"
    )

    out = bytearray()
    out += b"%PDF-1.4\n"
    offsets = [0]  # object 0 is free
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("latin-1")
        out += body
        out += b"\nendobj\n"

    xref_offset = len(out)
    n = len(objects) + 1
    out += f"xref\n0 {n}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += b"trailer\n"
    out += f"<< /Size {n} /Root 1 0 R >>\n".encode("latin-1")
    out += b"startxref\n"
    out += f"{xref_offset}\n".encode("latin-1")
    out += b"%%EOF"
    return bytes(out)


if __name__ == "__main__":
    target = pathlib.Path(__file__).parent / "sample_regulation.pdf"
    target.write_bytes(build_pdf())
    print("wrote", target, target.stat().st_size, "bytes")
