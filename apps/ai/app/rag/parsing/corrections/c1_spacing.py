"""C1. 자간·어절 재결합 — `pdf_parsing_strategy.md` §5 C1. [전 프로파일]

CJK 양끝맞춤 조판 때문에 어절 내부에 공백이 들어간다("발 급한다", "타 이 거 주 식 회 사").
실측 399라인 + 표 셀 161건.

⚠️ 어절 내/간 간격이 조판상 동일해 **원리적으로 완전 복원이 불가능**하다. 그래서 외부 사전
대신 **문서 내부 어휘**를 쓴다 — 같은 낱말이 문서 어딘가에는 온전히 등장한다는 성질에 기댄다.
문서 어휘에 없으면 **원문을 그대로 둔다. 추측 병합은 하지 않는다.**
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from app.rag.parsing.model import Element

_INVISIBLE = dict.fromkeys(map(ord, "​‌‍﻿⁠"), None)
# NFKC가 뭉개면 안 되는 기호 — 원문자 항(①②③)은 법령의 항 번호 그 자체다
_PROTECTED = re.compile(r"[①-⑮㈀-㈜㉠-㉻]")
_CJK = re.compile(r"[가-힣]")
_TRIM = re.compile(r"^[\s\"'“”‘’(){}\[\]「」『』·,.:;]+|[\s\"'“”‘’(){}\[\]「」『』·,.:;]+$")

_MIN_VOCAB_LEN = 2          # 어휘로 인정할 최소 길이
_MAX_FRAGMENT_LEN = 2       # 앞 조각이 이보다 길면 줄바꿈 파편으로 보지 않는다
_RUN_MIN_HEADING = 3        # 헤딩: 짧은 토큰 3연속부터 자간으로 본다
_RUN_MIN_BODY = 4           # 본문: 오적용을 피해 한 칸 더 보수적으로


def normalize(text: str) -> str:
    """보이지 않는 문자 제거 + NFKC. 원문자는 보호 후 복원한다."""
    saved: list[str] = []

    def _stash(m: re.Match) -> str:
        saved.append(m.group(0))
        return f"\x00{len(saved) - 1}\x00"

    text = _PROTECTED.sub(_stash, text.translate(_INVISIBLE))
    text = unicodedata.normalize("NFKC", text).replace("\xa0", " ")
    for i, ch in enumerate(saved):
        text = text.replace(f"\x00{i}\x00", ch)
    return re.sub(r"[ \t]+", " ", text).strip()


def build_vocabulary(elements: list[Element]) -> Counter[str]:
    """문서 전체에서 온전한 낱말 사전을 만든다. 표 셀도 포함한다."""
    vocab: Counter[str] = Counter()
    for el in elements:
        for token in normalize(el.text).split():
            word = _TRIM.sub("", token)
            if len(word) >= _MIN_VOCAB_LEN and _CJK.search(word):
                vocab[word] += 1
        for row in el.attrs.get("grid") or []:
            for cell in row:
                for token in normalize(str(cell)).split():
                    word = _TRIM.sub("", token)
                    if len(word) >= _MIN_VOCAB_LEN and _CJK.search(word):
                        vocab[word] += 1
    return vocab


def _rejoin_words(text: str, vocab: Counter[str]) -> str:
    """어절 내 줄바꿈 복원: 짧은 앞조각 + 뒷조각이 문서 어휘에 있으면 붙인다."""
    tokens = text.split(" ")
    out: list[str] = []
    i = 0
    while i < len(tokens):
        cur = tokens[i]
        if i + 1 < len(tokens):
            head, tail = _TRIM.sub("", cur), _TRIM.sub("", tokens[i + 1])
            merged = head + tail
            # 줄바꿈은 어절의 앞·뒤 어느 쪽이든 끊어 놓는다("발 급한다" / "건 을").
            # 어느 경우든 근거는 같다 — **붙인 형태가 문서 어휘에 있고, 끊긴 조각은
            # 그 자체로 낱말이 아닐 것.** 둘 중 하나라도 아니면 원문을 그대로 둔다.
            broken_head = len(head) <= _MAX_FRAGMENT_LEN and head not in vocab
            broken_tail = len(tail) <= _MAX_FRAGMENT_LEN and tail not in vocab
            if (
                head
                and tail
                and _CJK.search(head)
                and merged in vocab
                and (broken_head or broken_tail)
            ):
                out.append(cur + tokens[i + 1])
                i += 2
                continue
        out.append(cur)
        i += 1
    return " ".join(out)


def _segment(word: str, vocab: Counter[str]) -> str:
    """붙여쓴 덩어리를 문서 어휘로 다시 띄운다(최장 일치). 전부 못 나누면 원형 유지."""
    parts: list[str] = []
    i = 0
    while i < len(word):
        for j in range(len(word), i + 1, -1):
            if word[i:j] in vocab:
                parts.append(word[i:j])
                i = j
                break
        else:
            return word
    return " ".join(parts)


def _collapse_runs(text: str, vocab: Counter[str], run_min: int) -> str:
    """자간 벌린 구간(짧은 토큰 연속)을 붙인 뒤 어휘로 재분절한다."""
    tokens = text.split(" ")
    out: list[str] = []
    i = 0
    while i < len(tokens):
        j = i
        while j < len(tokens) and 0 < len(tokens[j]) <= 2:
            j += 1
        run = tokens[i:j]
        # 실제 자간 결함은 1글자 토큰이 다수다. 2글자 낱말의 정상 나열과 구분한다.
        if len(run) >= run_min and sum(1 for t in run if len(t) == 1) >= len(run) - 1:
            joined = "".join(run)
            out.append(_segment(joined, vocab) if _CJK.search(joined) else joined)
            i = j
            continue
        out.append(tokens[i])
        i += 1
    return " ".join(out)


def apply(elements: list[Element]) -> int:
    """자간·어절 교정. 반환값은 변경된 요소 수."""
    vocab = build_vocabulary(elements)
    changed = 0
    for el in elements:
        original = el.text
        text = normalize(original)
        if el.type != "code_block":     # 들여쓰기가 곧 조직 계층인 ASCII 도해는 예외
            run_min = _RUN_MIN_HEADING if el.type in ("heading", "title") else _RUN_MIN_BODY
            text = _collapse_runs(text, vocab, run_min)
            text = _rejoin_words(text, vocab)
        if text != original:
            el.text = text
            el.mark("C1")
            changed += 1

        grid = el.attrs.get("grid")
        if grid:
            el.attrs["grid"] = [[normalize(str(c)) for c in row] for row in grid]
            if el.attrs.get("header_row"):
                el.attrs["header_row"] = [normalize(str(c)) for c in el.attrs["header_row"]]
    return changed
