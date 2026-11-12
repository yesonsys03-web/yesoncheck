"""사이드바 목록 정렬 — 이름(기본, 예전 순서)·종류·버전 (2026-11-12).

사용자 요청: "사이드바 리스트에 소트 기능 필요해. 사용자 선택해서 소팅할 수 있게 … 지금은 OSAN - OSRO - OSAN 섞여 있잖아. 이러면 사용자가 OSAN만
재생하고 싶을 때 힘들잖아." 종류(이름 끝의 OSAN·OSRO·HD …)나 버전(v01·TK2 …)끼리 묶고, 묶음 안에서는 예전의 이름 순서 그대로.
기본(이름)은 목록을 건드리지 않음 — 고르지 않으면 예전과 같음.

규칙(Qt 없음)과 진짜 창의 Mov·Seq·All 목록을 함께 봄. 영상 파일은 빈 파일(목록은 이름만 봄), 이름은 지어낸 것.
"""

import os

import pytest
from PyQt5.QtCore import QItemSelectionModel, Qt
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QListWidgetItem

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import sidebar_sort, sidebar_sorting, video_list
from yesoncheck.sidebar_items import ALL_KIND_ROLE

NAMES = [
    "EP01_010_0010_OSAN_v01.mov", "EP01_010_0020_OSRO_v01.mov", "EP01_010_0030_OSAN_v02.mov", "EP01_010_0040_PBRO_v01.mov",
    "EP01_010_0050_OSRO_v03.mov", "EP01_010_0060_OSAN_v01.mov", "EP01_010_0070.mov", "EP01_010_0080_OSRO_v02.mov",
]
BY_KIND = [
    "EP01_010_0070.mov",  # 종류 없는 것 먼저 (개수 줄의 '기본')
    "EP01_010_0010_OSAN_v01.mov", "EP01_010_0030_OSAN_v02.mov", "EP01_010_0060_OSAN_v01.mov",
    "EP01_010_0020_OSRO_v01.mov", "EP01_010_0050_OSRO_v03.mov", "EP01_010_0080_OSRO_v02.mov",
    "EP01_010_0040_PBRO_v01.mov",
]
BY_VERSION = [
    "EP01_010_0070.mov",  # 버전 없는 것 먼저
    "EP01_010_0010_OSAN_v01.mov", "EP01_010_0020_OSRO_v01.mov", "EP01_010_0040_PBRO_v01.mov", "EP01_010_0060_OSAN_v01.mov",
    "EP01_010_0030_OSAN_v02.mov", "EP01_010_0080_OSRO_v02.mov",
    "EP01_010_0050_OSRO_v03.mov",
]


def stems(names):
    return [os.path.splitext(name)[0] for name in names]


# ---------------------------------------------------------------- 규칙 (Qt 없음)


def test_modes_and_labels():
    assert sidebar_sort.MODES == ("name", "kind", "version", "time") and sidebar_sort.DEFAULT_MODE == "name"
    assert [sidebar_sort.LABELS[mode] for mode in sidebar_sort.MODES] == ["이름", "종류", "버전", "시간"]
    assert sidebar_sort.button_text("kind") == "정렬: 종류 ▾"
    assert sidebar_sort.button_texts("kind") == ("정렬: 종류 ▾", "종류 ▾", "↕")  # 탭 줄 폭에 맞춰 긴 것부터


def test_name_mode_keeps_the_given_order():
    """이름(기본)은 받은 순서 그대로 — 목록을 읽은 쪽이 이미 이름 순서로 줌."""
    assert sidebar_sort.ordered(stems(NAMES), "name") == stems(NAMES)
    assert sidebar_sort.ordered(list(reversed(stems(NAMES))), "name") == list(reversed(stems(NAMES)))


def test_kind_mode_groups_kinds_and_keeps_the_order_inside():
    assert sidebar_sort.ordered(stems(NAMES), "kind") == stems(BY_KIND)


def test_version_mode_groups_versions_and_keeps_the_order_inside():
    assert sidebar_sort.ordered(stems(NAMES), "version") == stems(BY_VERSION)


def test_versions_sort_by_number_not_by_text():
    names = ["A_010_v10", "A_020_v2", "A_030_v1", "A_040_TK2", "A_050_TK10", "A_060_v002"]
    assert sidebar_sort.ordered(names, "version") == ["A_030_v1", "A_020_v2", "A_040_TK2", "A_060_v002", "A_010_v10", "A_050_TK10"]


def test_kind_is_read_like_the_count_line():
    """개수 줄(sidebar_counts)과 같은 규칙 — 끝에서만 읽음: `_TK1_HD`의 종류는 HD, 샷 코드 V005는 버전이 아님, 대소문자 무시."""
    names = ["FL_106_V005_TK1", "FL_106_A001_TK1_HD", "FL_106_A002_TK1", "fl_106_a003_tk2_hd"]
    assert sidebar_sort.ordered(names, "kind") == ["FL_106_V005_TK1", "FL_106_A002_TK1", "FL_106_A001_TK1_HD", "fl_106_a003_tk2_hd"]
    assert sidebar_sort.ordered(names, "version") == ["FL_106_V005_TK1", "FL_106_A001_TK1_HD", "FL_106_A002_TK1", "fl_106_a003_tk2_hd"]


def test_ordered_takes_a_key_function_for_other_things_than_names():
    pairs = [("x", "S_010_OSRO_v01"), ("y", "S_020_OSAN_v01")]
    assert sidebar_sort.ordered(pairs, "kind", stem_of=lambda pair: pair[1]) == [pairs[1], pairs[0]]


def test_time_mode_puts_the_most_recently_modified_first():
    """시간: 고친 시각이 최근인 것부터, 같은 시각이면 받은 순서, 시각을 모르는 것(None)은 맨 뒤."""
    times = {"a": 100.0, "b": 300.0, "c": None, "d": 300.0, "e": 200.0}
    assert sidebar_sort.ordered(list("abcde"), "time", time_of=times.get) == ["b", "d", "e", "a", "c"]


def test_time_mode_needs_the_times():
    """시각 없이 시간 정렬을 부르면 이름으로 대신 정렬하지 않고 실패."""
    with pytest.raises(ValueError, match="time_of"):
        sidebar_sort.ordered(["a", "b"], "time")


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="정렬"):
        sidebar_sort.ordered(["a"], "date")
    with pytest.raises(ValueError, match="정렬"):
        sidebar_sort.button_text("date")


# ---------------------------------------------------------------- 창: Mov 목록


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def make_folder(tmp_path, names, folder="shots"):
    root = tmp_path / folder
    root.mkdir(exist_ok=True)
    for name in names:
        (root / name).write_bytes(b"")
    return root


def load(player, tmp_path, names=NAMES):
    """폴더의 영상을 Mov 목록에 넣음 (폴더를 불러온 것과 같은 길 — 출처를 기억해 다시 읽기가 됨)."""
    root = make_folder(tmp_path, names)
    source = player._register_sidebar_source(video_list.ListSource("folder", str(root)))
    player._add_sidebar_videos([(name, path, source) for name, path in video_list.scan_folder(str(root)).videos])
    return root


def mov_names(player):
    return [player.sidebar.item(i).text() for i in range(player.sidebar.count())]


def shown_mode(player):
    """단추가 알리는 지금 기준 — 툴팁 첫 줄(늘 긴 글; 단추의 글은 탭 줄 폭에 따라 줄어듦)."""
    assert player.sidebar_sort_button.text() in sidebar_sort.button_texts(player.sidebar_sort_mode)
    return player.sidebar_sort_button.toolTip().splitlines()[0]


def test_the_sort_button_sits_in_the_tab_row_next_to_the_all_tab(player):
    """사용자 지시 "정렬버튼을 All 탭 옆으로" — 탭 위젯의 오른쪽 모서리."""
    button = player.sidebar_sort_button
    assert button.parentWidget() is player.sidebar_tabs  # 탭 줄 안 — 자리는 아래 tab_row 시험들이 봄 (All 탭 바로 옆)
    assert player.sidebar_tabs.cornerWidget(Qt.TopRightCorner) is None  # 모서리 위젯이 아님 — 탭 위젯의 크기 계산에 끼지 않음
    assert shown_mode(player) == "정렬: 이름 ▾"
    assert [action.text() for action in button.menu().actions()] == ["이름", "종류", "버전", "시간"]
    assert [action.isChecked() for action in button.menu().actions()] == [True, False, False, False]


def tab_row(player, qapp, sidebar_width):
    """사이드바 열을 sidebar_width로 맞춘 창을 보인 뒤의 (단추 글, 탭 막대가 다 보이는가, 단추가 All 탭 바로 옆인가 — 겹치지 않고 틈 0~8px,
    단추가 탭 줄 안에 다 들어오는가)."""
    player.resize(1400, 860)
    player.show()
    qapp.processEvents()
    player._resize_sidebar_column(sidebar_width)
    for _ in range(5):
        qapp.processEvents()
    tabs, bar, button = player.sidebar_tabs, player.sidebar_tabs.tabBar(), player.sidebar_sort_button
    all_right = bar.mapTo(tabs, bar.tabRect(2).topRight()).x()
    left = button.mapTo(tabs, button.rect().topLeft()).x()
    beside = 0 <= left - all_right <= 8 and left + button.width() <= tabs.width()
    return button.text(), bar.width() >= bar.sizeHint().width(), beside


def test_in_the_default_narrow_sidebar_the_button_shrinks_instead_of_covering_the_all_tab(player, qapp):
    """기본 폭(약 180px)에서는 탭 막대만으로 줄이 거의 참 — 긴 글의 단추를 두면 Qt가 탭 막대를 줄여 All 탭이 가려졌음. 단추 글이 줄어들어 세 탭이 다 보임."""
    text, tabs_whole, beside = tab_row(player, qapp, player.default_sidebar_width or 176)
    assert text == sidebar_sort.COMPACT_BUTTON_TEXT and tabs_whole and beside
    assert shown_mode(player) == "정렬: 이름 ▾"  # 기준은 툴팁에


def test_in_a_wide_sidebar_the_button_shows_the_full_text_right_beside_the_all_tab(player, qapp):
    """넓어도 줄의 오른쪽 끝이 아니라 All 탭 바로 옆 (모서리 위젯만 두면 Qt가 오른쪽 끝에 붙임 — 실제 Mac 화면에서 75px 떨어졌음)."""
    text, tabs_whole, beside = tab_row(player, qapp, 380)
    assert text == "정렬: 이름 ▾" and tabs_whole and beside
    player.set_sidebar_sort("version")
    assert player.sidebar_sort_button.text() == "정렬: 버전 ▾"


def test_the_button_text_follows_the_sidebar_width(player, qapp):
    """사이드바를 넓히고 좁히면 단추 글도 따라 바뀜 — 가운데 폭에서는 `이름 ▾`."""
    seen = [tab_row(player, qapp, width) for width in (380, 215, 176, 380)]
    assert [text for text, _whole, _apart in seen] == ["정렬: 이름 ▾", "이름 ▾", sidebar_sort.COMPACT_BUTTON_TEXT, "정렬: 이름 ▾"]
    assert all(whole and beside for _text, whole, beside in seen)


def test_default_mode_leaves_the_list_alone(player, tmp_path):
    load(player, tmp_path)
    assert mov_names(player) == NAMES and player.sidebar_sort_mode == "name"


def test_choosing_kind_groups_the_mov_list(player, tmp_path):
    load(player, tmp_path)
    player.sidebar_sort_button.menu().actions()[1].trigger()
    assert mov_names(player) == BY_KIND
    assert shown_mode(player) == "정렬: 종류 ▾"
    assert [action.isChecked() for action in player.sidebar_sort_button.menu().actions()] == [False, True, False, False]


def test_choosing_version_then_name_restores_the_original_order(player, tmp_path):
    load(player, tmp_path)
    player.set_sidebar_sort("version")
    assert mov_names(player) == BY_VERSION
    player.set_sidebar_sort("kind")
    assert mov_names(player) == BY_KIND
    player.set_sidebar_sort("name")
    assert mov_names(player) == NAMES


def test_choosing_the_checked_mode_keeps_it_checked(player, tmp_path):
    load(player, tmp_path)
    player.sidebar_sort_button.menu().actions()[0].trigger()  # 체크된 '이름'을 다시 누름 — Qt가 체크를 끔
    assert [action.isChecked() for action in player.sidebar_sort_button.menu().actions()] == [True, False, False, False]
    assert mov_names(player) == NAMES


def test_items_keep_their_identity_selection_and_current_item(player, tmp_path):
    """줄을 옮길 뿐 — 항목 객체(썸네일 아이콘·색·썸네일 자리)는 그대로, 고른 것·현재 항목도 같은 영상에."""
    load(player, tmp_path)
    items = {player.sidebar.item(i).text(): player.sidebar.item(i) for i in range(player.sidebar.count())}
    player.sidebar.item(1).setSelected(True)  # 0020 OSRO
    player.sidebar.item(4).setSelected(True)  # 0050 OSRO
    player.sidebar.setCurrentItem(player.sidebar.item(4), QItemSelectionModel.NoUpdate)
    player.set_sidebar_sort("kind")
    assert all(player.sidebar.item(i) is items[player.sidebar.item(i).text()] for i in range(player.sidebar.count()))
    assert sorted(item.text() for item in player.sidebar.selectedItems()) == ["EP01_010_0020_OSRO_v01.mov", "EP01_010_0050_OSRO_v03.mov"]
    assert player.sidebar.currentItem().text() == "EP01_010_0050_OSRO_v03.mov"


def test_sorting_does_not_open_or_reload_anything(player, tmp_path, monkeypatch):
    """정렬은 목록의 줄만 옮김 — 영상을 열거나(open_file) 목록을 비우지(모델 초기화 → 출처·Seq 목록을 잊음) 않음."""
    load(player, tmp_path)
    opened, resets = [], []
    monkeypatch.setattr(player, "open_file", lambda *args, **kwargs: opened.append(args))
    player.sidebar.model().modelReset.connect(lambda: resets.append(1))
    sources = dict(player._sidebar_sources)
    player.set_sidebar_sort("kind")
    player.set_sidebar_sort("name")
    assert opened == [] and resets == [] and player._sidebar_sources == sources


def test_the_button_leaves_the_keyboard_focus_with_the_list(player):
    """단추가 포커스를 가져가면 목록의 ↑↓·전역 단축키(프레임 이동)가 끊김."""
    assert player.sidebar_sort_button.focusPolicy() == Qt.NoFocus


def test_the_button_looks_the_same_size_in_both_themes(player, qapp):
    """테마를 바꿔도 크기·자리가 그대로 — 단추의 시트는 색을 정하지 않음(글자색은 테마 시트를 따름)."""
    player.show()
    qapp.processEvents()
    button = player.sidebar_sort_button
    before = (button.geometry(), button.font().pixelSize())
    player.toggle_theme()
    qapp.processEvents()
    assert (button.geometry(), button.font().pixelSize()) == before
    assert "color: #" not in button.styleSheet()


def test_sorting_waits_while_the_list_is_in_use(player, tmp_path):
    """목록을 쓰는 중(썸네일 반복·우클릭 메뉴가 줄 번호를 쥠 — _hold_sidebar_refresh)에는 줄을 옮기지 않고 끝난 뒤에. 단추·기준은 바로 바뀜."""
    load(player, tmp_path)
    with player._hold_sidebar_refresh():
        player.set_sidebar_sort("kind")
        assert mov_names(player) == NAMES and shown_mode(player) == "정렬: 종류 ▾"
        assert player._sidebar_sort_timer.isActive()
    QTest.qWait(sidebar_sorting.SORT_RETRY_MS + 150)
    assert mov_names(player) == BY_KIND


def test_changing_the_mode_twice_while_the_list_is_in_use_keeps_the_name_order(player, tmp_path):
    """종류로 정렬해 둔 목록을 쓰는 중에 이름 → 버전으로 연달아 바꿈: 이름으로 되돌리기가 아직 미뤄진 채(줄은 종류 순서)라도 그 줄 순서를 이름 순서로
    잘못 적지 않음 — 끝난 뒤 버전 순서가 되고, 이름으로 돌아가면 처음 순서."""
    load(player, tmp_path)
    player.set_sidebar_sort("kind")
    with player._hold_sidebar_refresh():
        player.set_sidebar_sort("name")
        assert mov_names(player) == BY_KIND  # 아직 옮기지 못함
        player.set_sidebar_sort("version")
    QTest.qWait(sidebar_sorting.SORT_RETRY_MS + 150)
    assert mov_names(player) == BY_VERSION
    player.set_sidebar_sort("name")
    assert mov_names(player) == NAMES


def test_a_refresh_before_a_postponed_return_to_name_still_uses_the_name_order(player, tmp_path, qapp):
    """이름으로 되돌리기가 미뤄진 사이(줄은 아직 종류 순서) 목록 다시 읽기가 먼저 와도 계획은 이름 순서로 — 새 영상이 이름 순서의 제자리에."""
    root = load(player, tmp_path)
    player.set_sidebar_sort("kind")
    with player._hold_sidebar_refresh():
        player.set_sidebar_sort("name")
    assert mov_names(player) == BY_KIND and player.sidebar_sort_mode == "name"  # 미룬 정렬(타이머)이 아직 안 돎
    (root / "EP01_010_0035_OSRO_v01.mov").write_bytes(b"")
    player._apply_sidebar_read(video_list.read_sources(tuple(player._sidebar_sources), []), 0.0)
    QTest.qWait(sidebar_sorting.SORT_RETRY_MS + 150)
    assert mov_names(player) == sorted(NAMES + ["EP01_010_0035_OSRO_v01.mov"])


def test_take_colors_and_icons_travel_with_the_rows(player, tmp_path, qapp):
    """줄을 옮겨도 항목에 칠한 테이크 색(v02 초록)·썸네일 아이콘은 그 영상에 그대로."""
    load(player, tmp_path)
    qapp.processEvents()  # 테이크 색 (0ms 미룸)
    colors = {player.sidebar.item(i).text(): player.sidebar.item(i).data(Qt.ForegroundRole) for i in range(player.sidebar.count())}
    assert colors["EP01_010_0030_OSAN_v02.mov"] is not None and colors["EP01_010_0010_OSAN_v01.mov"] is None
    player.sidebar.item(2).setIcon(QIcon(QPixmap(8, 8)))
    player.set_sidebar_sort("version")
    qapp.processEvents()
    after = {player.sidebar.item(i).text(): player.sidebar.item(i) for i in range(player.sidebar.count())}
    assert {name: item.data(Qt.ForegroundRole) for name, item in after.items()} == colors
    assert not after["EP01_010_0030_OSAN_v02.mov"].icon().isNull() and after["EP01_010_0010_OSAN_v01.mov"].icon().isNull()


def test_unknown_mode_is_refused_and_nothing_changes(player, tmp_path):
    load(player, tmp_path)
    with pytest.raises(ValueError, match="정렬"):
        player.set_sidebar_sort("date")
    assert mov_names(player) == NAMES and player.sidebar_sort_mode == "name"


def test_files_added_later_join_their_group(player, tmp_path, qapp):
    """정렬해 둔 목록에 영상을 더 넣으면(끌어다 놓기 — 목록 끝에 붙음) 그 묶음 자리로 감. 이름으로 돌아가면 넣은 차례(끝)에."""
    load(player, tmp_path)
    player.set_sidebar_sort("kind")
    extra = make_folder(tmp_path, ["EP01_020_0010_OSAN_v01.mov"], folder="more")
    player._add_sidebar_videos([("EP01_020_0010_OSAN_v01.mov", str(extra / "EP01_020_0010_OSAN_v01.mov"), None)])
    qapp.processEvents()  # 미룬 정렬 (0ms)
    assert mov_names(player) == BY_KIND[:4] + ["EP01_020_0010_OSAN_v01.mov"] + BY_KIND[4:]
    player.set_sidebar_sort("name")
    assert mov_names(player) == NAMES + ["EP01_020_0010_OSAN_v01.mov"]


def test_refreshing_a_sorted_list_puts_new_and_gone_videos_right(player, tmp_path, qapp):
    """정렬한 채 목록을 다시 읽음: 없어진 영상은 빠지고 새 영상은 그 묶음에 — 이름으로 돌아가면 처음 불러온 것과 같은 이름 순서."""
    root = load(player, tmp_path)
    player.set_sidebar_sort("kind")
    (root / "EP01_010_0020_OSRO_v01.mov").unlink()
    (root / "EP01_010_0035_OSRO_v01.mov").write_bytes(b"")
    player._apply_sidebar_read(video_list.read_sources(tuple(player._sidebar_sources), []), 0.0)
    qapp.processEvents()
    assert mov_names(player) == [
        "EP01_010_0070.mov",
        "EP01_010_0010_OSAN_v01.mov", "EP01_010_0030_OSAN_v02.mov", "EP01_010_0060_OSAN_v01.mov",
        "EP01_010_0035_OSRO_v01.mov", "EP01_010_0050_OSRO_v03.mov", "EP01_010_0080_OSRO_v02.mov",
        "EP01_010_0040_PBRO_v01.mov",
    ]
    player.set_sidebar_sort("name")
    assert mov_names(player) == [name for name in sorted(NAMES + ["EP01_010_0035_OSRO_v01.mov"]) if name != "EP01_010_0020_OSRO_v01.mov"]


def test_a_refresh_with_nothing_new_keeps_the_sorted_list_untouched(player, tmp_path, qapp):
    load(player, tmp_path)
    player.set_sidebar_sort("kind")
    items = [player.sidebar.item(i) for i in range(player.sidebar.count())]
    moved = []
    player.sidebar.model().rowsRemoved.connect(lambda *args: moved.append(args))
    player._apply_sidebar_read(video_list.read_sources(tuple(player._sidebar_sources), []), 0.0)
    qapp.processEvents()
    assert [player.sidebar.item(i) for i in range(player.sidebar.count())] == items and moved == []


def test_a_new_list_is_sorted_the_same_way(player, tmp_path, qapp):
    """정렬은 창이 떠 있는 동안 유지 — 목록을 비우고 다른 폴더를 불러와도 고른 정렬대로."""
    load(player, tmp_path)
    player.set_sidebar_sort("kind")
    player.sidebar.clear()
    load(player, tmp_path)
    qapp.processEvents()
    assert mov_names(player) == BY_KIND and shown_mode(player) == "정렬: 종류 ▾"
    player.set_sidebar_sort("name")
    assert mov_names(player) == NAMES


def test_plain_items_without_a_path_do_not_break_sorting(player):
    """경로 없이 넣은 항목(시험·옛 코드)도 이름으로 묶임 — 정렬이 예외를 내지 않음."""
    for name in ("B_010_OSRO_v01.mov", "B_020_OSAN_v01.mov"):
        player.sidebar.addItem(QListWidgetItem(name))
    player.set_sidebar_sort("kind")
    assert mov_names(player) == ["B_020_OSAN_v01.mov", "B_010_OSRO_v01.mov"]


# ---------------------------------------------------------------- 시간 (파일을 고친 시각)

NOON = 1_700_000_000  # 시험용 기준 시각 (초)


def set_times(root, minutes):
    """{파일 이름: 기준 시각 뒤 몇 분에 고쳤는지} — os.utime으로 고친 시각을 정함."""
    for name, minute in minutes.items():
        os.utime(root / name, (NOON + minute * 60, NOON + minute * 60))


# 고친 차례(분): 0070이 가장 최근, 0010이 가장 오래됨 — 이름 순서와 섞이게
MINUTES = {
    "EP01_010_0010_OSAN_v01.mov": 1, "EP01_010_0020_OSRO_v01.mov": 50, "EP01_010_0030_OSAN_v02.mov": 20, "EP01_010_0040_PBRO_v01.mov": 70,
    "EP01_010_0050_OSRO_v03.mov": 30, "EP01_010_0060_OSAN_v01.mov": 60, "EP01_010_0070.mov": 80, "EP01_010_0080_OSRO_v02.mov": 40,
}
BY_TIME = [name for name, _minute in sorted(MINUTES.items(), key=lambda pair: -pair[1])]


def test_choosing_time_puts_recently_modified_videos_first(player, tmp_path, capsys):
    root = load(player, tmp_path)
    set_times(root, MINUTES)
    player.sidebar_sort_button.menu().actions()[3].trigger()
    assert mov_names(player) == BY_TIME and BY_TIME[0] == "EP01_010_0070.mov"
    assert shown_mode(player) == "정렬: 시간 ▾"
    assert f"[정렬] 고친 시각 읽음: {len(NAMES)}개" in capsys.readouterr().out
    player.set_sidebar_sort("name")
    assert mov_names(player) == NAMES


def test_times_are_read_again_only_when_time_is_picked_again(player, tmp_path, qapp):
    """다시 렌더한 영상(고친 시각이 새로워짐)은 '시간'을 다시 고를 때 위로 — 그 전에는(저절로 도는 다시 읽기 포함) 파일마다 다시 묻지 않음."""
    root = load(player, tmp_path)
    set_times(root, MINUTES)
    player.set_sidebar_sort("time")
    set_times(root, {"EP01_010_0010_OSAN_v01.mov": 999})  # 가장 오래된 것을 다시 렌더
    player._apply_sidebar_read(video_list.read_sources(tuple(player._sidebar_sources), []), 0.0)
    qapp.processEvents()
    assert mov_names(player) == BY_TIME
    player.sidebar_sort_button.menu().actions()[3].trigger()  # 체크된 '시간'을 다시 고름
    assert mov_names(player) == ["EP01_010_0010_OSAN_v01.mov"] + BY_TIME[:-1]
    assert [action.isChecked() for action in player.sidebar_sort_button.menu().actions()] == [False, False, False, True]


def test_videos_whose_time_cannot_be_read_go_last_and_are_logged(player, tmp_path, capsys):
    root = load(player, tmp_path)
    set_times(root, MINUTES)
    (root / "EP01_010_0070.mov").unlink()  # 가장 최근 것이 그사이 지워짐
    player.set_sidebar_sort("time")
    assert mov_names(player) == BY_TIME[1:] + ["EP01_010_0070.mov"]
    out = capsys.readouterr().out
    assert "읽지 못한 1개는 맨 뒤에" in out and "EP01_010_0070.mov" in out and "FileNotFoundError" in out


def test_new_videos_in_time_mode_are_placed_by_their_time(player, tmp_path, qapp, capsys):
    """시간으로 정렬해 둔 목록에 들어온 새 영상은 그것만 시각을 읽어 제자리에."""
    root = load(player, tmp_path)
    set_times(root, MINUTES)
    player.set_sidebar_sort("time")
    capsys.readouterr()
    (root / "EP01_010_0035_OSRO_v01.mov").write_bytes(b"")
    set_times(root, {"EP01_010_0035_OSRO_v01.mov": 45})  # 0020(50분)과 0080(40분) 사이
    player._apply_sidebar_read(video_list.read_sources(tuple(player._sidebar_sources), []), 0.0)
    qapp.processEvents()
    names = mov_names(player)
    assert names.index("EP01_010_0035_OSRO_v01.mov") == names.index("EP01_010_0020_OSRO_v01.mov") + 1
    assert names == BY_TIME[:4] + ["EP01_010_0035_OSRO_v01.mov"] + BY_TIME[4:]
    assert "[정렬] 고친 시각 읽음: 1개" in capsys.readouterr().out
    player.set_sidebar_sort("name")
    assert mov_names(player) == sorted(NAMES + ["EP01_010_0035_OSRO_v01.mov"])


def test_sorting_by_time_waits_while_the_list_is_in_use(player, tmp_path, capsys):
    """목록을 쓰는 중에는 디스크도 읽지 않음 — 끝난 뒤 한 번."""
    root = load(player, tmp_path)
    set_times(root, MINUTES)
    with player._hold_sidebar_refresh():
        player.set_sidebar_sort("time")
        assert mov_names(player) == NAMES and "고친 시각 읽음" not in capsys.readouterr().out
    QTest.qWait(sidebar_sorting.SORT_RETRY_MS + 150)
    assert mov_names(player) == BY_TIME


def test_seq_and_all_lists_follow_the_time_sort(player, tmp_path):
    """시퀀스는 첫 프레임 파일을 고친 시각 — Seq·All 탭도 최근 것부터."""
    bases = ["S_010_OSRO_v01", "S_020_OSAN_v01", "S_030_OSRO_v02"]
    frames = seq_frames(tmp_path, bases)
    for base, minute in zip(bases, (10, 90, 55)):
        os.utime(frames / f"{base}-0001.tga", (NOON + minute * 60, NOON + minute * 60))
    root = load(player, tmp_path)
    set_times(root, MINUTES)
    player._set_seq_items(video_list.scan_folder(str(frames)).sequences)
    player.set_sidebar_sort("time")
    assert seq_names(player) == ["S_020_OSAN_v01", "S_030_OSRO_v02", "S_010_OSRO_v01"]
    player.sidebar_tabs.setCurrentWidget(player.all_sidebar)
    player._rebuild_all_list()
    all_stems = [all_stem(player.all_sidebar.item(i)) for i in range(player.all_sidebar.count())]
    minutes = {os.path.splitext(name)[0]: minute for name, minute in MINUTES.items()} | dict(zip(bases, (10, 90, 55)))
    assert all_stems == sorted(minutes, key=lambda stem: -minutes[stem])
    player.set_sidebar_sort("name")
    assert seq_names(player) == bases


# ---------------------------------------------------------------- 선택 재생·All·Seq


def test_play_selected_follows_the_visible_order(player, tmp_path):
    """종류로 정렬하고 OSAN 묶음을 골라 재생 — 보이는 차례대로."""
    load(player, tmp_path)
    player.set_sidebar_sort("kind")
    for i in (1, 2, 3):
        player.sidebar.item(i).setSelected(True)
    assert [item.text() for item in player._playlist_selection()] == BY_KIND[1:4]


def seq_frames(tmp_path, bases, folder="frames"):
    root = tmp_path / folder
    root.mkdir(exist_ok=True)
    for base in bases:
        for number in (1, 2):
            (root / f"{base}-{number:04d}.tga").write_bytes(b"")
    return root


def all_stem(item):
    """All 항목의 이름(확장자 뺀) — 시퀀스는 base, 영상은 파일 이름."""
    if item.data(ALL_KIND_ROLE) == "seq":
        return item.data(Qt.UserRole).base
    return os.path.splitext(item.text())[0]


def seq_names(player):
    return [player.seq_sidebar.item(i).data(Qt.UserRole).base for i in range(player.seq_sidebar.count())]


def test_seq_and_all_lists_follow_the_same_sort(player, tmp_path):
    bases = ["S_010_OSRO_v01", "S_020_OSAN_v01", "S_030_OSRO_v02", "S_040_OSAN_v02"]
    root = seq_frames(tmp_path, bases)
    load(player, tmp_path)
    player._set_seq_items(video_list.scan_folder(str(root)).sequences)
    assert seq_names(player) == bases
    player.set_sidebar_sort("kind")
    assert seq_names(player) == ["S_020_OSAN_v01", "S_040_OSAN_v02", "S_010_OSRO_v01", "S_030_OSRO_v02"]
    player.sidebar_tabs.setCurrentWidget(player.all_sidebar)
    player._rebuild_all_list()
    all_stems = [all_stem(player.all_sidebar.item(i)) for i in range(player.all_sidebar.count())]
    assert all_stems == [
        "EP01_010_0070",  # 종류 없는 것
        "EP01_010_0010_OSAN_v01", "EP01_010_0030_OSAN_v02", "EP01_010_0060_OSAN_v01", "S_020_OSAN_v01", "S_040_OSAN_v02",  # 영상·시퀀스가 이름 순서로
        "EP01_010_0020_OSRO_v01", "EP01_010_0050_OSRO_v03", "EP01_010_0080_OSRO_v02", "S_010_OSRO_v01", "S_030_OSRO_v02",
        "EP01_010_0040_PBRO_v01",
    ]
    player.set_sidebar_sort("version")
    player._rebuild_all_list()
    numbers = [sidebar_sort.group_key(all_stem(player.all_sidebar.item(i)), "version") for i in range(player.all_sidebar.count())]
    assert numbers == sorted(numbers) and len(numbers) == len(NAMES) + len(bases)
    player.set_sidebar_sort("name")
    assert seq_names(player) == bases


def test_sequences_set_later_are_sorted_too(player, tmp_path):
    bases = ["S_010_OSRO_v01", "S_020_OSAN_v01"]
    root = seq_frames(tmp_path, bases)
    player.set_sidebar_sort("kind")
    player._set_seq_items(video_list.scan_folder(str(root)).sequences)
    assert seq_names(player) == ["S_020_OSAN_v01", "S_010_OSRO_v01"]


def test_sorting_an_empty_window_does_nothing(player):
    player.set_sidebar_sort("version")
    assert player.sidebar.count() == 0 and shown_mode(player) == "정렬: 버전 ▾"
