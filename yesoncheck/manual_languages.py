"""사용법 매뉴얼의 언어 — 한글(기준)과 영문의 글·화면 글자, 그리고 두 글의 모양이 같은지 보는 검사 (Qt 없음).

매뉴얼 HTML 한 파일에 두 언어가 함께 들어가고 목차 위의 단추로 전환함(`manual_html`). 언어마다 글은 모듈 둘:
쪽 글(`manual_content`·`manual_content_en` — PAGES·GROUPS·RELEASES_TITLE·RELEASES_GROUP·RELEASES_LEAD)과
버전별 바뀐 점(`release_notes`·`release_notes_en` — RELEASES). 쪽 이름(key)·절의 닻·그림 이름은 언어와 무관해
주소(`#쪽--닻`)가 두 언어에서 같음 — 전환해도 보던 쪽에 머묾.

**글을 고칠 때는 두 언어를 함께**: 영문은 한글을 블록 하나하나 그대로 옮긴 것이라 쪽·블록·줄·항목의 수와 차례가 같아야 함.
`parity_problems`가 어긋난 곳을 글로 돌려주고 시험(`tests/test_manual_languages.py`)이 그것이 비었는지 봄 — 한쪽만 고치면 시험이 실패.
배포 노트(GitHub Release·업데이트 알림의 '바뀐 점')는 예전처럼 한글 `release_notes`에서만 뽑음.
"""
import re
from dataclasses import dataclass

from yesoncheck import manual_content, manual_content_en, release_notes, release_notes_en

LINK_RE = re.compile(r"\[\[([a-z_]+(?:/[a-z0-9_.]+)?)(?:\|[^\]]+)?\]\]")
KEY_RE = re.compile(r"\{([^{}]+)\}")
HANGUL_RE = re.compile(r"[ㄱ-ㆎ가-힣]")


@dataclass(frozen=True)
class Language:
    code: str  # html의 lang 값·브라우저에 저장하는 값
    name: str  # 전환 단추의 글 (그 언어로)
    content: object  # 쪽 글 모듈
    notes: object  # 버전별 바뀐 점 모듈
    ui: dict  # 화면 글자 (manual_html이 씀)


KOREAN = Language("ko", "한국어", manual_content, release_notes, {
    "manual": "사용법",
    "version": "버전",
    "search": "찾기",
    "theme": "밝게 / 어둡게",
    "current": "지금 버전",
    "callouts": {"note": "참고", "tip": "팁", "warn": "주의"},
    "found": "{n}개 쪽에서 찾음 — Enter로 이동",
    "none": "찾는 글이 없습니다",
})
ENGLISH = Language("en", "English", manual_content_en, release_notes_en, {
    "manual": "Manual",
    "version": "Version",
    "search": "Search",
    "theme": "Light / dark",
    "current": "Current version",
    "callouts": {"note": "Note", "tip": "Tip", "warn": "Caution"},
    "found": "Found on {n} page(s) — press Enter to go",
    "none": "No matches",
})
LANGUAGES = (KOREAN, ENGLISH)  # 첫째가 기준: 요소 id에 앞말이 없고 그림을 품음 (스크립트가 꺼진 브라우저에서 보이는 언어)


def _tokens(text):
    """글 안의 링크 대상과 키 — 번역해도 같아야 하는 것 (키의 한글 자판 표시 "F (ㄹ)"도 그대로)."""
    return sorted(LINK_RE.findall(text)), sorted(KEY_RE.findall(text))


def _same_tokens(where, base_text, other_text, problems, keys=True):
    base_links, base_keys = _tokens(base_text)
    other_links, other_keys = _tokens(other_text)
    if base_links != other_links:
        problems.append(f"{where}: 링크가 다름 {base_links} ≠ {other_links}")
    if keys and base_keys != other_keys:
        problems.append(f"{where}: 키 표시가 다름 {base_keys} ≠ {other_keys}")


def _key_specs(spec):
    return (spec,) if isinstance(spec, str) else tuple(spec)


def _translated_key_differs(base_spec, other_spec):
    """한글 낱말이 든 키("Ctrl+휠" → "Ctrl+Wheel")의 번역이 어긋났는지: `+`로 나눈 조각의 수가 같고 한글이 없는 조각(Ctrl)은 그대로여야 함."""
    base_parts, other_parts = base_spec.split("+"), other_spec.split("+")
    if len(base_parts) != len(other_parts):
        return True
    return any(not HANGUL_RE.search(base) and base != other for base, other in zip(base_parts, other_parts))


def _block_problems(where, base, other, problems):
    kind = base[0]
    if kind == "h":
        if base[2] != other[2]:
            problems.append(f"{where}: 닻이 다름 {base[2]!r} ≠ {other[2]!r}")
        _same_tokens(where, base[1], other[1], problems)
    elif kind == "fig":
        if base[1] != other[1]:
            problems.append(f"{where}: 그림이 다름 {base[1]!r} ≠ {other[1]!r}")
        if len(base[3]) != len(other[3]):
            problems.append(f"{where}: 그림 설명의 수가 다름 {len(base[3])} ≠ {len(other[3])}")
        _same_tokens(where, base[2], other[2], problems)
        for index, (base_item, other_item) in enumerate(zip(base[3], other[3]), 1):
            _same_tokens(f"{where} 설명 {index}", base_item, other_item, problems)
    elif kind == "keys":
        if len(base[1]) != len(other[1]):
            problems.append(f"{where}: 단축키 줄의 수가 다름 {len(base[1])} ≠ {len(other[1])}")
        for index, ((base_spec, base_text), (other_spec, other_text)) in enumerate(zip(base[1], other[1]), 1):
            base_specs, other_specs = _key_specs(base_spec), _key_specs(other_spec)
            if len(base_specs) != len(other_specs):
                problems.append(f"{where} 줄 {index}: 키의 수가 다름 {base_specs} ≠ {other_specs}")
            for base_one, other_one in zip(base_specs, other_specs):
                korean_word = HANGUL_RE.search(re.sub(r" \(.\)$", "", base_one))  # "마우스 휠"은 번역, "F (ㄹ)"은 그대로
                if not korean_word and base_one != other_one:
                    problems.append(f"{where} 줄 {index}: 키가 다름 {base_one!r} ≠ {other_one!r}")
                elif korean_word and _translated_key_differs(base_one, other_one):
                    problems.append(f"{where} 줄 {index}: 키가 다름 {base_one!r} ≠ {other_one!r}")
            _same_tokens(f"{where} 줄 {index}", base_text, other_text, problems)
    elif kind == "table":
        base_head, other_head = base[1], other[1]
        if (base_head is None) != (other_head is None) or (base_head is not None and len(base_head) != len(other_head)):
            problems.append(f"{where}: 표 머리의 모양이 다름")
        for cell, (base_cell, other_cell) in enumerate(zip(base_head or (), other_head or ()), 1):
            _same_tokens(f"{where} 머리 칸 {cell}", base_cell, other_cell, problems)
        if [len(row) for row in base[2]] != [len(row) for row in other[2]]:
            problems.append(f"{where}: 표의 줄·칸 수가 다름 {[len(r) for r in base[2]]} ≠ {[len(r) for r in other[2]]}")
        for row, (base_row, other_row) in enumerate(zip(base[2], other[2]), 1):
            for cell, (base_cell, other_cell) in enumerate(zip(base_row, other_row), 1):
                _same_tokens(f"{where} 줄 {row} 칸 {cell}", base_cell, other_cell, problems)
    elif kind in ("steps", "list"):
        if len(base[1]) != len(other[1]):
            problems.append(f"{where}: 항목의 수가 다름 {len(base[1])} ≠ {len(other[1])}")
        for index, (base_item, other_item) in enumerate(zip(base[1], other[1]), 1):
            _same_tokens(f"{where} 항목 {index}", base_item, other_item, problems)
    else:  # p·note·tip·warn
        _same_tokens(where, base[1], other[1], problems)


def content_problems(base, other):
    """쪽 글 모듈 둘(기준·번역)의 모양이 어긋난 곳 — 글 목록 (비었으면 같음)."""
    problems = []
    if len(base.GROUPS) != len(other.GROUPS):
        problems.append(f"목차 묶음의 수가 다름 {len(base.GROUPS)} ≠ {len(other.GROUPS)}")
    if [page.key for page in base.PAGES] != [page.key for page in other.PAGES]:
        problems.append(f"쪽 이름·차례가 다름 {[p.key for p in base.PAGES]} ≠ {[p.key for p in other.PAGES]}")
        return problems
    if base.RELEASES_GROUP in base.GROUPS and other.RELEASES_GROUP in other.GROUPS \
            and base.GROUPS.index(base.RELEASES_GROUP) != other.GROUPS.index(other.RELEASES_GROUP):
        problems.append("업데이트 내역 쪽의 묶음 자리가 다름")
    for base_page, other_page in zip(base.PAGES, other.PAGES):
        where = f"쪽 {base_page.key}"
        if base_page.group in base.GROUPS and other_page.group in other.GROUPS \
                and base.GROUPS.index(base_page.group) != other.GROUPS.index(other_page.group):
            problems.append(f"{where}: 목차 묶음의 자리가 다름 {base_page.group!r} ≠ {other_page.group!r}")
        _same_tokens(f"{where} 소개", base_page.lead, other_page.lead, problems)
        base_kinds, other_kinds = [b[0] for b in base_page.blocks], [b[0] for b in other_page.blocks]
        if base_kinds != other_kinds:
            problems.append(f"{where}: 블록의 종류·차례가 다름 {base_kinds} ≠ {other_kinds}")
            continue
        for index, (base_block, other_block) in enumerate(zip(base_page.blocks, other_page.blocks), 1):
            _block_problems(f"{where} 블록 {index}({base_block[0]})", base_block, other_block, problems)
    return problems


def notes_problems(base, other):
    """버전별 바뀐 점 모듈 둘(기준·번역)의 모양이 어긋난 곳 — 글 목록 (비었으면 같음)."""
    problems = []
    base_versions = [(release.version, release.date) for release in base.RELEASES]
    other_versions = [(release.version, release.date) for release in other.RELEASES]
    if base_versions != other_versions:
        missing = [v for v in base_versions if v not in other_versions]
        extra = [v for v in other_versions if v not in base_versions]
        problems.append(f"버전·날짜가 다름 — 번역에 없는 것 {missing}, 번역에만 있는 것 {extra}")
        return problems
    for base_release, other_release in zip(base.RELEASES, other.RELEASES):
        where = f"버전 {base_release.version}"
        _same_tokens(f"{where} 요약", base_release.summary, other_release.summary, problems, keys=False)
        base_shape = [(bool(title), len(items)) for title, items in base_release.groups]
        other_shape = [(bool(title), len(items)) for title, items in other_release.groups]
        if base_shape != other_shape:
            problems.append(f"{where}: 묶음·항목의 수가 다름 {base_shape} ≠ {other_shape}")
            continue
        for group, ((_t, base_items), (_u, other_items)) in enumerate(zip(base_release.groups, other_release.groups), 1):
            for index, (base_item, other_item) in enumerate(zip(base_items, other_items), 1):
                _same_tokens(f"{where} 묶음 {group} 항목 {index}", base_item, other_item, problems, keys=False)
    return problems


def parity_problems(base=KOREAN, other=ENGLISH):
    """기준 언어와 번역의 글 모양이 어긋난 곳 (쪽 글 + 버전별 바뀐 점) — 비었으면 같음."""
    return content_problems(base.content, other.content) + notes_problems(base.notes, other.notes)
