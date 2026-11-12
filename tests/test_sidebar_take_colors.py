"""사이드바 Mov 항목의 테이크·버전별 글자색 (2026-11-12 — 사용자 요청 "테이크 넘버가 다른 건 다른 컬러로 … 시퀀스가 푸른색이니까
이 색깔 피해서").

- 테이크·버전 번호는 개수 줄과 같은 규칙(sidebar_counts.kind_and_version — 이름 끝의 TK·v + 숫자)으로 읽음.
- 1번(TK1·v01·v001)과 번호 없는 이름은 테마 기본색(따로 칠하지 않음), 2번부터 번호마다 색 — 넷을 돌려 씀.
- 색은 이미 뜻이 있는 색을 피함: All 탭의 시퀀스(하늘색), 선택 재생 중인 항목(빨강), 어두운 테마의 선택 항목(주황).
- 창: 목록이 바뀌면·테마를 바꾸면 다시 칠하고, All 탭의 mov 사본도 같은 색(시퀀스는 하늘색 그대로), 선택 재생이 끝나도 테이크 색이 남음.
"""

import colorsys

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from tests.conftest import write_test_video
from tests.test_sequence_capture import make_seq
from tests.test_sidebar_all_tab import show_all_tab, wait_rebuild
from tests.test_thumbnails import drop_folder
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck.sidebar_all import ALL_SEQ_FG
from yesoncheck.sidebar_take_colors import TAKE_COLORS, take_color, take_number

RESERVED = {"dark": {"sequence": ALL_SEQ_FG["dark"], "playing": "#ff0000", "selected": "#ff9900"},
            "light": {"sequence": ALL_SEQ_FG["light"], "playing": "#ff0000"}}

# ---------------------------------------------------------------- 규칙 (Qt 없음)


@pytest.mark.parametrize("stem, number", [
    ("EP101_SC001_TK1", 1), ("EP101_SC001_TK2", 2), ("EP101_SC001_tk3", 3),
    ("KOTH_1604_010_v001", 1), ("KOTH_1604_010_v002", 2), ("HH_305_010_OSAN_v04", 4),
    ("FL_106_010_TK2_HD", 2),  # 종류가 뒤에 붙은 이름 — 버전은 그 앞
    ("FL_106_V005_TK1", 1),  # 샷 코드 V005는 버전이 아님 (끝의 TK1이 테이크)
    ("EP101_SC001", None), ("tk2", None), ("final", None),
])
def test_take_number_follows_the_count_line_rule(stem, number):
    assert take_number(stem) == number


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_first_take_and_unnumbered_names_keep_the_theme_colour(theme):
    for stem in ("EP101_SC001_TK1", "EP101_SC001_v001", "EP101_SC001", "EP101_SC001_v000"):
        assert take_color(stem, theme) is None


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_each_later_take_has_its_own_colour_and_the_colours_repeat(theme):
    colors = [take_color(f"EP101_SC001_TK{n}", theme) for n in range(2, 6)]
    assert colors == list(TAKE_COLORS[theme])
    assert len(set(colors)) == 4
    assert take_color("EP101_SC001_TK6", theme) == colors[0]  # 넷을 돌려 씀
    assert take_color("EP101_SC001_v02", theme) == colors[0]  # v도 TK와 같은 번호 색


def test_unknown_theme_is_an_error():
    with pytest.raises(KeyError):
        take_color("EP101_SC001_TK2", "sepia")


def hue(color):
    red, green, blue = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hsv(red, green, blue)[0] * 360


def hue_distance(a, b):
    diff = abs(hue(a) - hue(b)) % 360
    return min(diff, 360 - diff)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_take_colours_stay_away_from_colours_that_already_mean_something(theme):
    """시퀀스(하늘색)·재생 중(빨강)·선택(주황)과 색상(hue)이 25도 넘게 떨어져 있음 — 사용자 지시 '시퀀스 색을 피해서'."""
    for color in TAKE_COLORS[theme]:
        for meaning, reserved in RESERVED[theme].items():
            assert hue_distance(color, reserved) > 25, (theme, color, meaning)


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# 목록 줄의 바탕 (main_window_styles의 QListWidget 규칙): 어두운 테마, 밝은 테마의 보통 줄·마우스를 올린 줄
LIST_BACKGROUNDS = {"dark": ("#232323",), "light": ("#ffffff", "#f8f9fa")}


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_take_colours_are_readable_on_the_list_background(theme):
    """목록 바탕과의 명암 대비가 본문 글자 기준(WCAG AA 4.5:1) 이상 — 사용자 지시 "화이트 테마에서도 가독성 떨어지는지 체크"."""
    for color in TAKE_COLORS[theme]:
        for background in LIST_BACKGROUNDS[theme]:
            assert contrast(color, background) >= 4.5, (theme, color, background)


# ---------------------------------------------------------------- 창

@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def shots(tmp_path):
    """테이크가 섞인 영상 넷(번호 없음·TK1·TK2·v03)과 TK2 시퀀스 하나가 든 폴더."""
    folder = tmp_path / "shots"
    for name in ("SH010.mov", "SH010_TK1.mov", "SH010_TK2.mov", "SH020_v03.mov"):
        write_test_video(str(folder / name))
    make_seq(str(folder), "SH030_TK2", range(1, 4))
    return folder


def loaded(player, qapp, tmp_path):
    drop_folder(player, "video", shots(tmp_path))
    qapp.processEvents()
    return player


def color_of(item):
    """항목에 따로 칠한 글자색(없으면 None — 테마 시트의 기본색)."""
    brush = item.data(Qt.ForegroundRole)
    return None if brush is None else QColor(brush).name()


def mov_colors(player):
    return {player.sidebar.item(i).text(): color_of(player.sidebar.item(i)) for i in range(player.sidebar.count())}


def expected(theme):
    green, pink = TAKE_COLORS[theme][0], TAKE_COLORS[theme][1]
    return {"SH010.mov": None, "SH010_TK1.mov": None, "SH010_TK2.mov": green, "SH020_v03.mov": pink}


def test_mov_items_are_coloured_by_take(player, qapp, tmp_path):
    assert mov_colors(loaded(player, qapp, tmp_path)) == expected("dark")


def test_colours_follow_the_theme(player, qapp, tmp_path):
    loaded(player, qapp, tmp_path)
    player.set_light_theme()
    qapp.processEvents()
    assert mov_colors(player) == expected("light")
    player.set_dark_theme()
    qapp.processEvents()
    assert mov_colors(player) == expected("dark")


def test_all_tab_shows_take_colours_on_movies_and_keeps_sequences_sky_blue(player, qapp, tmp_path):
    loaded(player, qapp, tmp_path)
    show_all_tab(player, qapp)
    wait_rebuild(qapp)
    assert player.all_sidebar.count() == 5
    colors = {player.all_sidebar.item(i).text(): color_of(player.all_sidebar.item(i)) for i in range(player.all_sidebar.count())}
    sequence = [name for name in colors if name not in expected("dark")]
    assert len(sequence) == 1
    assert colors == {**expected("dark"), sequence[0]: ALL_SEQ_FG["dark"]}  # TK2 시퀀스도 테이크 색이 아니라 하늘색


def test_take_colours_survive_play_selected(player, qapp, tmp_path):
    """선택 재생이 끝나 강조를 되돌릴 때(reset_sidebar_colors) 테마 기본색으로 덮지 않음."""
    loaded(player, qapp, tmp_path)
    for i in range(player.sidebar.count()):
        player.sidebar.item(i).setForeground(QColor("red"))  # 재생 중 강조가 지나간 자리
    player.reset_sidebar_colors()
    assert mov_colors(player) == expected("dark")


def test_item_being_played_stays_red_when_the_list_is_repainted(player, qapp, tmp_path):
    """선택 재생 중인 항목(빨강)은 목록이 바뀌거나 테마를 바꿔 다시 칠할 때도 그대로."""
    loaded(player, qapp, tmp_path)
    playing = [player.sidebar.item(i) for i in range(player.sidebar.count()) if player.sidebar.item(i).text() == "SH010_TK2.mov"][0]
    player.playlist = [playing.toolTip()]
    player.current_playlist_index = 0
    player.is_playlist_playing = True
    playing.setForeground(QColor("red"))
    player.set_light_theme()
    qapp.processEvents()
    assert color_of(playing) == "#ff0000"
    assert mov_colors(player) == {**expected("light"), "SH010_TK2.mov": "#ff0000"}
