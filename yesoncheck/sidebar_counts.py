"""사이드바 목록 아래 개수 줄의 글 (Qt 없음) — 지금 보는 탭의 개수.

  Mov  `12개`                                   꼬리가 있으면 `450개 — TK1 225 · HD 225`
  Seq  `시퀀스 3개`                              (프레임 수가 아니라 시퀀스 수 — 꼬리는 시퀀스 이름으로)
  All  `15개 — mov 10 · mp4 2 · tga 2 · exr 1`  꼬리가 있는 포맷은 `mov 450 (TK1 225 · HD 225)`

All의 포맷은 확장자(소문자) — 영상은 파일 확장자, 시퀀스는 프레임 확장자. 영상 포맷을 먼저, 그다음 시퀀스 포맷이고 각각 많은 순
(같으면 이름 순). 창에서 셀 때는 원본 Mov·Seq 목록에서 셈 (sidebar_all — All 목록은 보일 때만 미뤄서 다시 만들어짐).

**영문 꼬리마다 나눔**(사용자 요청 2026-11-06 — 같은 샷의 `_TK1.mov` 225개와 `_TK1_HD.mov` 225개가 450개로만 보였음; Hazbin의
`_OSAN_v02`·`_OSRO_v01`도 따로): 이름(확장자 뺀) 끝의 버전 꼬리(`_v01`·`_v002` — v + 숫자, 대소문자 무시)를 떼고, 마지막 `_` 뒤가 ASCII
영문자뿐이면(`_HD`·`_LR`·`_OSAN`·`_TX` …, 대문자로 보임) 그 꼬리로 따로 셈. 나머지 묶음의 이름은 (버전을 뗀) 꼬리가 모두 같으면 그
꼬리(`TK1`), 아니면 `기본`. 꼬리가 하나도 없으면 나누지 않음 — 버전을 떼도 앞이 숫자인 이름(KOTH `_004_v001`), 밑줄 없는 이름, 영문이
아닌 꼬리는 꼬리로 치지 않음. 차례는 나머지 묶음 먼저, 그다음 꼬리마다 많은 순(같으면 이름 순).
"""

import os
import re
from collections import Counter

TABS = ("mov", "seq", "all")
BASIC_LABEL = "기본"  # 꼬리 없는 묶음의 이름 — 그 묶음의 꼬리가 서로 다를 때
VERSION_TOKEN = re.compile(r"[vV]\d+")  # 끝의 버전 꼬리 (v01·v002·V3) — 떼고 그 앞 꼬리를 봄


def _breakdown(formats):
    """[(포맷, 개수)] — 많은 순, 같으면 이름 순."""
    return sorted(Counter(formats).items(), key=lambda pair: (-pair[1], pair[0]))


def _last_token(stem):
    """끝의 버전 꼬리를 뗀 이름의 마지막 `_` 뒤 (밑줄이 없으면 None)."""
    head, sep, tail = stem.rpartition("_")
    if sep and VERSION_TOKEN.fullmatch(tail):
        stem = head
    return stem.rsplit("_", 1)[1] if "_" in stem else None


def letter_suffix(stem):
    """이름(확장자 뺀)의 영문 꼬리(대문자) — 끝의 버전 꼬리를 뗀 뒤 마지막 `_` 뒤가 ASCII 영문자뿐일 때만, 아니면 None."""
    token = _last_token(stem)
    return token.upper() if token and token.isascii() and token.isalpha() else None


def suffix_split(stems):
    """[(묶음 이름, 개수)] — 꼬리 없는 묶음(이름: 공통 꼬리 또는 '기본') 먼저, 그다음 꼬리마다. 꼬리가 하나도 없으면 [] (나누지 않음)."""
    suffixes = [letter_suffix(stem) for stem in stems]
    if not any(suffixes):
        return []
    rest = [stem for stem, suffix in zip(stems, suffixes) if suffix is None]
    parts = []
    if rest:
        tokens = {(_last_token(stem) or "").upper() for stem in rest}
        label = next(iter(tokens)) if len(tokens) == 1 and "" not in tokens else BASIC_LABEL
        parts.append((label, len(rest)))
    return parts + _breakdown(suffix for suffix in suffixes if suffix)


def _split_text(stems):
    return " · ".join(f"{label} {count}" for label, count in suffix_split(stems))


def _stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def count_text(tab, movie_paths, sequences) -> str:
    """tab("mov"·"seq"·"all")의 개수 줄. movie_paths: Mov 목록의 영상 경로, sequences: Seq 목록의 시퀀스마다 (이름 base, 프레임 확장자)."""
    if tab == "mov":
        split = _split_text([_stem(path) for path in movie_paths])
        return f"{len(movie_paths)}개" + (f" — {split}" if split else "")
    if tab == "seq":
        split = _split_text([base for base, _ext in sequences])
        return f"시퀀스 {len(sequences)}개" + (f" — {split}" if split else "")
    if tab != "all":
        raise ValueError(f"tab은 {', '.join(TABS)} 중 하나여야 합니다: {tab!r}")
    total = len(movie_paths) + len(sequences)
    if total == 0:
        return "0개"
    movie_stems = {}
    for path in movie_paths:
        movie_stems.setdefault(os.path.splitext(path)[1].lstrip(".").lower(), []).append(_stem(path))
    seq_stems = {}
    for base, ext in sequences:
        seq_stems.setdefault(ext.lower(), []).append(base)
    parts = []
    for groups in (movie_stems, seq_stems):  # 영상 포맷 먼저, 그다음 시퀀스 포맷 — 각각 많은 순, 같으면 이름 순
        for name, stems in sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0])):
            split = _split_text(stems)
            parts.append(f"{name} {len(stems)}" + (f" ({split})" if split else ""))
    return f"{total}개 — {' · '.join(parts)}"
