"""사이드바 Mov 항목의 테이크·버전별 글자색 — 규칙만 (Qt 없음. 칠하는 일은 sidebar_all.SidebarAllMixin).

사용자 요청(2026-11-12): "테이크 넘버가 다른 건 다른 컬러로 표시하면 가독성이 좋을 거 같아 … 시퀀스가 푸른색이니까 이 색깔 피해서".

- 번호는 개수 줄과 **같은 규칙**(sidebar_counts.kind_and_version — 이름 끝의 TK·v + 숫자, 그 뒤에 종류가 붙어도 됨)으로 읽음:
  목록 아래의 `TK1 243 · TK2 6`과 목록의 색이 어긋나지 않게.
- 1번(TK1·v01·v001)·0번·번호 없는 이름은 None — 따로 칠하지 않고 테마 기본색. 대부분의 파일이 여기라 색이 든 줄이 곧 '다시 한 테이크'.
- 2번부터 번호마다 색, 넷을 돌려 씀(2 초록 · 3 분홍 · 4 보라 · 5 연두 · 6 초록 …). 이미 뜻이 있는 색은 피함: All 탭의 시퀀스(하늘색
  sidebar_all.ALL_SEQ_FG), 선택 재생 중인 항목(빨강), 어두운 테마의 선택 항목(주황 #ff9900) — 시험이 색상(hue) 거리로 지킴.
  밝은 테마의 색은 흰 목록 바탕에서 읽히게 어두운 쪽 — 두 테마 모두 목록 바탕과의 명암 대비가 4.5:1 이상
  (시험이 지킴; 실측 어두운 7.6~11.2:1, 밝은 5.4~6.5:1).
- 고른 줄은 테이크 색이 아니라 목록 시트의 선택 글자색(어두운 테마 주황·밝은 테마 기본색)으로 보임 — 시트의 ::item:selected가 우선.
- **개수 줄**(목록 아래 `638개 — OSAN 615 (v01 397 · v02 176 …)`)의 버전·테이크 토막도 같은 색(`count_line_html`) — 줄이 곧 범례.
  사용자 지시 "여기에도 일관성있게 적용돼야지". 버전·테이크는 늘 괄호 안이라 괄호 안의 토막만 칠함(괄호 밖 포맷 이름이 `v2`처럼
  생겨도 그대로). 칠할 토막이 없으면 None — 부른 쪽이 예전처럼 평문으로 보임.
"""

import html
import re

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


def number_color(number, theme):
    """테이크·버전 번호의 색("#rrggbb") — 1번 이하·None이면 None(테마 기본색). 모르는 테마는 KeyError."""
    colors = TAKE_COLORS[theme]
    if number is None or number < 2:
        return None
    return colors[(number - 2) % len(colors)]


def take_color(stem, theme):
    """이름의 테이크·버전 색("#rrggbb") — 1번 이하·번호 없음이면 None(테마 기본색). 모르는 테마는 KeyError."""
    return number_color(take_number(stem), theme)


_PARENTHESES = re.compile(r"\(([^()]*)\)")  # 종류마다의 버전·테이크 묶음 `(v01 397 · v02 176)`
_VERSION_COUNT = re.compile(r"(?<![0-9A-Za-z_])(?:TK|v)(\d+) \d+")  # 묶음 안의 토막 `v02 176` — sidebar_counts가 내는 모양(TK·v + 숫자, 개수)


def count_line_html(line, theme):
    """개수 줄 글(sidebar_counts.count_text)에서 2번 이상의 버전·테이크 토막을 목록과 같은 색으로 감싼 HTML.
    칠할 토막이 하나도 없으면 None (평문 그대로 보이면 됨). 줄 바꿈(All 탭의 둘째 줄)은 <br>, 나머지 글은 escape."""
    painted = []

    def paint(token):
        color = number_color(int(token.group(1)), theme)
        if color is None:
            return token.group(0)
        painted.append(token.group(0))
        return f'<span style="color:{color}">{token.group(0)}</span>'

    marked = _PARENTHESES.sub(lambda group: "(" + _VERSION_COUNT.sub(paint, group.group(1)) + ")", html.escape(line, quote=False))
    return marked.replace("\n", "<br>") if painted else None
