"""사이드바 목록 아래 개수 줄의 글 (Qt 없음) — 지금 보는 탭의 개수.

  Mov  `12개`                                   나눌 것이 있으면 `450개 — 기본 225 (TK1 225) · HD 225 (TK1 225)`
  Seq  `시퀀스 3개`                              (프레임 수가 아니라 시퀀스 수 — 종류·버전은 시퀀스 이름으로)
  All  `15개 — mov 10 · mp4 2 · tga 2 · exr 1`  나눌 것이 있으면 둘째 줄에 종류(버전) — 괄호가 두 겹이 되지 않게

All의 포맷은 확장자(소문자) — 영상은 파일 확장자, 시퀀스는 프레임 확장자. 영상 포맷을 먼저, 그다음 시퀀스 포맷이고 각각 많은 순
(같으면 이름 순). 창에서 셀 때는 원본 Mov·Seq 목록에서 셈 (sidebar_all — All 목록은 보일 때만 미뤄서 다시 만들어짐).

**종류마다, 그 안에 버전·테이크 괄호**(사용자 요청 2026-11-06 — FL_106 job이 같은 샷의 `_TK1` 225 + `_TK1_HD` 225인데 450개로만 보였음;
이어서 Hazbin의 `_OSAN_v02`·`_OSRO_v01`, 그리고 TK1·TK2·v001·v002도 따로; 모양은 사용자 결정 '종류 안에 버전 괄호'). 이름(확장자 뺀)을
`_`로 나눠 **끝에서만** 봄(`kind_and_version`):
  - 끝이 버전·테이크(`TK` + 숫자, `v` + 숫자 — 대소문자 무시)면 그것이 버전, 그 바로 앞이 ASCII 영문자뿐이면 종류
  - 끝이 ASCII 영문자뿐이면 그것이 종류, 그 바로 앞이 버전·테이크면 버전
  - 종류·버전은 이름의 첫 토막이 될 수 없음(밑줄 앞의 한 토막은 샷 이름). 끝의 하나만 보므로 FL의 샷 코드 `V005`(`FL_106_V005_TK1`)를
    버전으로 세지 않음
종류가 없는 파일의 묶음은 `기본`. 차례는 `기본` 먼저, 그다음 종류마다 많은 순(같으면 이름 순); 괄호 안의 버전도 많은 순(같으면 이름 순),
종류 안에 버전이 없는 파일이 섞이면 `없음 n`(합이 맞게). 종류도 버전도 하나도 없으면 나누지 않음(밑줄 없는 이름, 영문이 아닌 꼬리,
끝이 `A001` 같은 이름). 버전은 `TK1`·`v01` 꼴로 보임(대문자 V는 v로).
"""

import os
import re
from collections import Counter, defaultdict

TABS = ("mov", "seq", "all")
BASIC_LABEL = "기본"  # 종류가 없는 파일의 묶음
NO_VERSION_LABEL = "없음"  # 버전이 있는 파일과 같은 종류에 섞인, 버전 없는 파일
VERSION_TOKEN = re.compile(r"(?i)(tk|v)(\d+)")


def _breakdown(items):
    """[(이름, 개수)] — 많은 순, 같으면 이름 순."""
    return sorted(Counter(items).items(), key=lambda pair: (-pair[1], pair[0]))


def _is_kind(token):
    return token.isascii() and token.isalpha()


def _version_label(token):
    match = VERSION_TOKEN.fullmatch(token)
    if match is None:
        return None
    prefix, digits = match.groups()
    return ("TK" if prefix.lower() == "tk" else "v") + digits


def kind_and_version(stem):
    """이름(확장자 뺀)의 (종류 또는 None, 버전 또는 None) — 모듈 설명의 규칙 (끝에서만, 첫 토막은 아님)."""
    tokens = stem.split("_")
    if len(tokens) < 2:
        return None, None
    version = _version_label(tokens[-1])
    if version is not None:
        before = tokens[-2] if len(tokens) >= 3 else None
        return (before.upper() if before and _is_kind(before) else None), version
    if _is_kind(tokens[-1]):
        version = _version_label(tokens[-2]) if len(tokens) >= 3 else None
        return tokens[-1].upper(), version
    return None, None


def kind_version_text(stems):
    """`기본 225 (TK1 225) · HD 225 (TK1 225)` — 종류도 버전도 하나도 없으면 ""."""
    parsed = [kind_and_version(stem) for stem in stems]
    if not any(kind or version for kind, version in parsed):
        return ""
    versions = defaultdict(list)
    for kind, version in parsed:
        versions[kind].append(version)
    order = ([None] if None in versions else []) + [kind for kind, _count in _breakdown(k for k, _v in parsed if k)]
    parts = []
    for kind in order:
        members = versions[kind]
        text = f"{kind or BASIC_LABEL} {len(members)}"
        if any(members):
            inner = _breakdown(version or NO_VERSION_LABEL for version in members)
            text += " (" + " · ".join(f"{name} {count}" for name, count in inner) + ")"
        parts.append(text)
    return " · ".join(parts)


def _stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def count_text(tab, movie_paths, sequences) -> str:
    """tab("mov"·"seq"·"all")의 개수 줄. movie_paths: Mov 목록의 영상 경로, sequences: Seq 목록의 시퀀스마다 (이름 base, 프레임 확장자)."""
    if tab == "mov":
        split = kind_version_text([_stem(path) for path in movie_paths])
        return f"{len(movie_paths)}개" + (f" — {split}" if split else "")
    if tab == "seq":
        split = kind_version_text([base for base, _ext in sequences])
        return f"시퀀스 {len(sequences)}개" + (f" — {split}" if split else "")
    if tab != "all":
        raise ValueError(f"tab은 {', '.join(TABS)} 중 하나여야 합니다: {tab!r}")
    total = len(movie_paths) + len(sequences)
    if total == 0:
        return "0개"
    movies = _breakdown(os.path.splitext(path)[1].lstrip(".").lower() for path in movie_paths)
    frames = _breakdown(ext.lower() for _base, ext in sequences)
    line = f"{total}개 — " + " · ".join(f"{name} {count}" for name, count in movies + frames)
    split = kind_version_text([_stem(path) for path in movie_paths] + [base for base, _ext in sequences])
    return line + (f"\n{split}" if split else "")
