"""사이드바 목록 정렬의 규칙 (Qt 없음) — 이름(기본)·종류·버전·시간.

사용자 요청(2026-11-12): "사이드바 리스트에 소트 기능 필요해. 사용자 선택해서 소팅할 수 있게 … 지금은 OSAN - OSRO - OSAN 섞여 있잖아. 이러면
사용자가 OSAN만 재생하고 싶을 때 힘들잖아."

  이름  목록을 읽은 순서 그대로 (예전과 같음 — 읽는 쪽 video_list가 이미 이름 순서로 줌). 아무것도 옮기지 않음
  종류  이름 끝의 종류(OSAN·OSRO·HD …)끼리 묶음 — 종류 없는 것 먼저, 그다음 종류 이름 순
  버전  버전·테이크 번호(v01·TK2 …)끼리 묶음 — 번호 없는 것 먼저, 그다음 번호 순 (TK2와 v02는 같은 묶음 — 테이크 색과 같음)
  시간  파일을 고친 시각이 최근인 것부터 (사용자 요청 "정렬에 시간도 추가할 수 있어?" — 다시 렌더한 영상이 위로). 시각을 읽지 못한 것은 맨 뒤.
        이름이 아니라 디스크의 시각이라 부르는 쪽이 항목마다 시각을 줌(time_of) — 읽는 일은 sidebar_sorting

묶음 안에서는(시간은 같은 시각이면) 받은 순서(= 이름 순서) 그대로 — 안정 정렬. 종류·버전을 이름에서 읽는 규칙은 목록 아래 개수 줄과 같음(sidebar_counts.kind_and_version —
끝에서만 읽어 샷 코드 V005를 버전으로 세지 않음): 개수 줄의 `OSAN 320 · OSRO 190`과 목록의 묶음이 같은 것을 가리킴.
창에 잇는 일(단추·목록 옮기기)은 sidebar_sorting.SidebarSortMixin.
"""

from yesoncheck import ui_text
from yesoncheck.sidebar_take_colors import take_number
from yesoncheck.sidebar_counts import kind_and_version

MODES = ("name", "kind", "version", "time")
DEFAULT_MODE = "name"
TIME_MODE = "time"
# 화면의 글은 글자 표(ui_text)에서 — 기준의 이름 `sort.<기준>`(이름·종류·버전·시간 / Name·Kind·Version·Time), 그 툴팁
# `sort.<기준>.tip`, 단추 글 `sort.button`(`정렬: 종류 ▾` / `Sort: Kind ▾`)·`sort.button.short`, 단추 툴팁 `sort.button.tip`
LABEL_KEYS = {mode: f"sort.{mode}" for mode in MODES}
UNKNOWN_TIME = 0.0  # 고친 시각을 읽지 못한(또는 아직 읽지 않은) 항목의 정렬 값 — 가장 오래된 것으로 쳐 맨 뒤에 (화면에 보이는 값이 아니라 차례만 정함)


def _checked(mode):
    if mode not in MODES:
        raise ValueError(f"정렬 기준은 {', '.join(MODES)} 중 하나여야 합니다: {mode!r}")
    return mode


def label(mode) -> str:
    """기준의 이름(지금 언어) — 메뉴 항목의 글."""
    return ui_text.text(LABEL_KEYS[_checked(mode)])


def tip(mode) -> str:
    """기준의 설명(지금 언어) — 메뉴 항목의 툴팁."""
    return ui_text.text(LABEL_KEYS[_checked(mode)] + ".tip")


def button_tip() -> str:
    """정렬 단추의 툴팁(지금 언어 — 첫 줄 아래에 붙는 설명)."""
    return ui_text.text("sort.button.tip")


def log_label(mode) -> str:
    """기록 줄에 적는 기준의 이름 — 언어와 무관하게 한글."""
    return ui_text.korean(LABEL_KEYS[_checked(mode)])


def button_text(mode) -> str:
    """정렬 단추의 글 — `정렬: 종류 ▾` (끝의 세모는 누르면 고르는 목록이 뜬다는 표시)."""
    return ui_text.text("sort.button", label=label(mode))


COMPACT_BUTTON_TEXT = "↕"  # 자리가 가장 모자랄 때의 단추 글 (기준은 툴팁에)


def button_texts(mode) -> tuple:
    """정렬 단추의 글 후보 — 긴 것부터: `정렬: 종류 ▾` · `종류 ▾` · `↕`. 단추는 탭 줄(All 탭 옆)에 있어 사이드바가 좁으면 탭을 가리므로
    자리에 들어가는 가장 긴 것을 씀 (sidebar_sorting._fit_sidebar_sort_button)."""
    return button_text(mode), ui_text.text("sort.button.short", label=label(mode)), COMPACT_BUTTON_TEXT


def group_key(stem, mode, mtime=None) -> tuple:
    """이름(확장자 뺀)이 mode에서 속하는 묶음의 정렬 열쇠 — 같은 묶음이면 같은 값, 묶음의 차례대로 커짐. 이름(기본)은 모두 한 묶음(()).
    시간은 이름을 보지 않고 mtime(고친 시각 — 초, 모르면 None)만: 최근일수록 작은 값, 모르면 UNKNOWN_TIME(맨 뒤)."""
    _checked(mode)
    if mode == TIME_MODE:
        return (-(UNKNOWN_TIME if mtime is None else mtime),)
    if mode == "kind":
        kind, _version = kind_and_version(stem)
        return (0, "") if kind is None else (1, kind)
    if mode == "version":
        number = take_number(stem)
        return (0, 0) if number is None else (1, number)
    return ()


def ordered(entries, mode, stem_of=None, time_of=None) -> list:
    """entries를 mode의 묶음 차례로 — 묶음 안에서는 받은 순서 그대로(안정 정렬). stem_of: 항목 → 이름(확장자 뺀), 없으면 항목이 이름.
    time_of: 항목 → 고친 시각(초, 모르면 None) — 시간 정렬에만 쓰고 그때는 꼭 줘야 함(없으면 ValueError — 이름으로 대신 정렬하지 않음).
    이름(기본)은 받은 순서 그대로이고 stem_of·time_of를 부르지 않음."""
    _checked(mode)
    entries = list(entries)
    if mode == DEFAULT_MODE:
        return entries
    if mode == TIME_MODE:
        if time_of is None:
            raise ValueError("시간 정렬에는 항목마다 고친 시각을 주는 time_of가 필요합니다")
        return sorted(entries, key=lambda entry: group_key(None, mode, time_of(entry)))
    stem_of = stem_of or (lambda entry: entry)
    return sorted(entries, key=lambda entry: group_key(stem_of(entry), mode))
