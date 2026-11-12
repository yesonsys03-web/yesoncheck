"""사이드바 Mov 항목의 테이크·버전별 글자색 — 규칙만 (Qt 없음. 칠하는 일은 sidebar_all.SidebarAllMixin).

사용자 요청(2026-11-12): "테이크 넘버가 다른 건 다른 컬러로 표시하면 가독성이 좋을 거 같아 … 시퀀스가 푸른색이니까 이 색깔 피해서".

- 번호는 개수 줄과 **같은 규칙**(sidebar_counts.kind_and_version — 이름 끝의 TK·v + 숫자, 그 뒤에 종류가 붙어도 됨)으로 읽음:
  목록 아래의 `TK1 243 · TK2 6`과 목록의 색이 어긋나지 않게.
- 1번(TK1·v01·v001)·0번·번호 없는 이름은 None — 따로 칠하지 않고 테마 기본색. 대부분의 파일이 여기라 색이 든 줄이 곧 '다시 한 테이크'.
- 2번부터 번호마다 색, 넷을 돌려 씀(2 초록 · 3 분홍 · 4 보라 · 5 연두 · 6 초록 …). 이미 뜻이 있는 색은 피함: All 탭의 시퀀스(하늘색
  sidebar_all.ALL_SEQ_FG), 선택 재생 중인 항목(빨강), 어두운 테마의 선택 항목(주황 #ff9900) — 시험이 색상(hue) 거리로 지킴.
  밝은 테마의 색은 흰 목록 바탕에서 읽히게 어두운 쪽 — 두 테마 모두 목록 바탕(밝은 테마는 마우스를 올린 줄 포함)과의 명암 대비가
  4.5:1 이상(시험이 지킴; 실측 어두운 7.6~11.2:1, 밝은 5.1~6.5:1).
- 고른 줄은 테이크 색이 아니라 목록 시트의 선택 글자색(어두운 테마 주황·밝은 테마 기본색)으로 보임 — 시트의 ::item:selected가 우선.
"""

from yesoncheck.sidebar_counts import VERSION_TOKEN, kind_and_version

# 테마 → 2·3·4·5번째 테이크의 색 (그 뒤는 처음부터 다시)
TAKE_COLORS = {
    "dark": ("#7ee081", "#ff8fd0", "#c9a7ff", "#d7e35a"),
    "light": ("#187a35", "#c2187a", "#6f42c1", "#766c00"),
}


def take_number(stem):
    """이름(확장자 뺀)의 테이크·버전 번호 — 없으면 None."""
    _kind, version = kind_and_version(stem)
    if version is None:
        return None
    return int(VERSION_TOKEN.fullmatch(version).group(2))


def take_color(stem, theme):
    """이름의 테이크·버전 색("#rrggbb") — 1번 이하·번호 없음이면 None(테마 기본색). 모르는 테마는 KeyError."""
    colors = TAKE_COLORS[theme]
    number = take_number(stem)
    if number is None or number < 2:
        return None
    return colors[(number - 2) % len(colors)]
