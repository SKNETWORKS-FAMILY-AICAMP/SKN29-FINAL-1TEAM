"""업로드 파일 경로 해석 — core가 저장한 media 볼륨을 ai가 읽는 유일한 통로.

Django가 파일의 SoR이고 ai는 **읽기만** 한다(compose가 `media:/data/media:ro`). 넘어오는 건
`Receipt.file_ref`·`Attachment.file_ref`·`PolicyDoc.file.name` 같은 **볼륨 기준 상대경로**다.

경로 계산을 모듈마다 따로 하면 컨테이너에서만 조용히 어긋난다(실제로 Chroma 호스트 설정에서
그랬다). 그래서 여기 한 곳에 둔다.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ROOT = "/data/media"


def media_root() -> Path:
    return Path(os.environ.get("RAG_MEDIA_ROOT", "").strip() or DEFAULT_ROOT)


class UnsafeMediaPath(ValueError):
    """미디어 루트를 벗어나는 경로 — 열지 않고 거부한다."""


def resolve(relative: str) -> Path:
    """볼륨 기준 상대경로 → 실제 파일 경로. **루트 밖이면 거부한다.**

    `file_ref`는 DB에서 오지만 그 값은 결국 업로드에서 비롯되고, 어딘가 한 곳만 검증을
    빠뜨려도 `../../etc/passwd`가 그대로 열린다. 파일을 여는 지점에서 막는 게 가장
    확실하다 — 호출부가 늘어나도 이 함수를 지나야 한다.

    **절대경로와 `..`는 잘라내지 않고 거부한다.** `/etc/passwd`에서 앞 슬래시만 떼면
    루트 안(`<root>/etc/passwd`)을 가리켜 "안전"해지지만, 그건 요청과 다른 파일을 조용히
    열어주는 것이다. 그런 입력은 공격이거나 호출부 버그이니 사실대로 실패시킨다.
    """
    text = str(relative or "").strip()
    if not text:
        raise UnsafeMediaPath("빈 경로입니다.")
    if text.startswith(("/", "\\")) or (len(text) > 1 and text[1] == ":"):
        raise UnsafeMediaPath(f"절대경로는 받지 않습니다(볼륨 기준 상대경로여야 함): {relative!r}")
    if ".." in Path(text).parts:
        raise UnsafeMediaPath(f"상위 경로 참조는 받지 않습니다: {relative!r}")

    root = media_root().resolve()
    target = (root / text).resolve()
    # 심볼릭 링크로 우회할 수 있으므로 최종 경로가 루트 아래인지 한 번 더 본다.
    if target != root and root not in target.parents:
        raise UnsafeMediaPath(f"미디어 루트를 벗어나는 경로입니다: {relative!r}")
    return target
