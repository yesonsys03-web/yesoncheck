"""(시험 도우미 — 시험 아님) 메인 창의 화면 글자를 영역별로 모은다 (UI 개편 PR 3 '언어 고르기').

두 가지에 쓴다:
- **한국어 화면이 그대로인지** — 글자를 글자 표(`ui_text`)로 옮기기 전에 모은 것을 `tests/data/main_window_texts_ko.json`에 적어 두고,
  옮기는 동안 같은지 견준다(`tests/test_ui_texts_baseline.py`).
- **English 화면에 한글이 남지 않는지** — 언어를 바꾼 뒤 모은 것에서 `hangul()`로 한글이 든 글을 찾는다.

`stage(player, tmp_path)`가 정해진 상태(합성 영상 A·B, 이미지 시퀀스, 사각형 주석, 정렬 '종류')를 만들고, `collect(player)`가
영역 → 글자 목록(순서 고정)을 돌려준다. 한 번에 한 모양만 보이는 것(알림 띠의 세 모양, fps 칸의 상태 글, 썸네일 진행 막대의 글,
창 제목의 꼬리, 우클릭 메뉴)은 `collect`가 그 모양을 차례로 만들어 가며 모으고 끝에 되돌린다.
임시 폴더 경로는 `<tmp>`, 버전이 든 창 제목의 머리는 `<title>`로 바꿔 적는다 — 기계·날짜에 따라 달라지지 않게.
"""

import os
import re

from PyQt5.QtCore import QPoint
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QGroupBox, QLabel, QLineEdit, QListWidget, QMenu, QProgressBar,
    QTabBar, QWidget,
)

from tests.conftest import write_test_video
from tests.test_sidebar_seq_tab import shot
from tests.test_thumbnails import drop_folder
from yesoncheck import build_info, player_update

AREAS = ("menubar", "transport", "sidebar", "sidebar_menus", "annotation", "ocr", "viewer", "overlay", "banner", "title")
RECT = {"type": "rect", "norm_x1": 0.25, "norm_y1": 0.25, "norm_x2": 0.75, "norm_y2": 0.75, "color": "#ff3333", "stroke_width": 3}
FPS_PROTOCOL_TEXTS = ("재생: 대기", "재생: 정지", "재생: 일시정지", "재생: 0 FPS", "재생: 24 FPS · 실제 23.8")
_HANGUL = re.compile("[가-힣ㄱ-ㅎㅏ-ㅣ]")


def hangul(texts):
    """한글이 든 글만 (받은 순서)."""
    return [text for text in texts if _HANGUL.search(text)]


# ---------------------------------------------------------------- 상태 만들기

def stage(player, tmp_path):
    """정해진 상태를 만든다 (파일 이름은 ASCII). 재생은 하지 않는다 — 프레임 번호·시간이 실행마다 같게."""
    folder = shot(tmp_path)  # tk1.mov + 시퀀스 tk1(6장)·tk2(5장, 하나 빠짐)
    write_test_video(str(folder / "tk2.mov"))
    player.resize(1400, 860)
    player.show()
    QTest.qWait(250)
    drop_folder(player, "video", folder)  # 목록에 넣고 첫 영상을 A로
    QApplication.processEvents()
    player.open_file("A", str(folder / "tk1.mov"))
    player.open_file("B", str(folder / "tk2.mov"))
    player.annotation_store.add(0, dict(RECT))
    player.refresh_annotation_ui()
    player.set_sidebar_sort("kind")
    player.sidebar_tabs.setCurrentWidget(player.all_sidebar)  # All 목록을 만들게 (보일 때만 미뤄서 만듦)
    QTest.qWait(250)
    player.sidebar_tabs.setCurrentWidget(player.sidebar)
    player.show_tool_panel("ocr")
    player.show_tool_panel("annotation")
    player._ui_texts_tmp = (str(tmp_path), os.path.realpath(str(tmp_path)))
    QApplication.processEvents()
    player.update_playback_fps()  # fps 칸: 1초 타이머가 나중에 넣을 글('대기' → 영상의 fps)을 지금 넣어 둠 — 모으는 때에 따라 달라지지 않게


# ---------------------------------------------------------------- 모으기

def _normalizer(player):
    roots = sorted(set(getattr(player, "_ui_texts_tmp", ())), key=len, reverse=True)
    title = build_info.title_base()

    def normalize(text):
        for root in roots:
            text = text.replace(root, "<tmp>")
        return text.replace(title, "<title>") if title else text

    return normalize


def _widget_texts(widget):
    """위젯 하나의 화면 글자: 글·자리표시 글·콤보 항목·목록 항목(글·툴팁)·진행 막대의 글·숫자 칸의 앞뒤 글·툴팁."""
    found = []
    if isinstance(widget, (QAbstractButton, QLabel)):
        found.append(widget.text())
    if isinstance(widget, QLineEdit):
        found.append(widget.placeholderText())
    if isinstance(widget, QGroupBox):
        found.append(widget.title())
    if isinstance(widget, QComboBox):
        found.extend(widget.itemText(index) for index in range(widget.count()))
    if isinstance(widget, QListWidget):
        for row in range(widget.count()):
            found.extend((widget.item(row).text(), widget.item(row).toolTip()))
    if isinstance(widget, QProgressBar):
        found.append(widget.format())
    if isinstance(widget, QTabBar):
        found.extend(widget.tabText(index) for index in range(widget.count()))
    if isinstance(widget, QAbstractSpinBox) and hasattr(widget, "suffix"):
        found.extend((widget.prefix(), widget.suffix()))
    found.append(widget.toolTip())
    return found


def _tree_texts(root, skip=()):
    """root와 그 자손 위젯의 글자 (만들어진 차례). skip의 위젯과 그 자손은 뺀다."""
    found = []
    for widget in [root] + root.findChildren(QWidget):
        if any(widget is other or other.isAncestorOf(widget) for other in skip):
            continue
        found.extend(_widget_texts(widget))
    return found


def _menu_texts(menu):
    """메뉴의 항목 글과(글과 다른) 툴팁 — 하위 메뉴까지. 메뉴를 여는 것처럼 aboutToShow를 먼저 보낸다(체크·켜짐·상태 글을 맞춤)."""
    menu.aboutToShow.emit()
    found = []
    for action in menu.actions():
        if action.isSeparator():
            continue
        found.append(action.text())
        if action.toolTip() and action.toolTip() != action.text().replace("&", ""):
            found.append(action.toolTip())
        if action.menu() is not None:
            found.extend(_menu_texts(action.menu()))
    return found


def menubar_texts(player):
    found = []
    for action in player.menuBar().actions():
        found.append(action.text())
        if action.menu() is not None:
            found.extend(_menu_texts(action.menu()))
    return found


def _context_menu_texts(player):
    """Mov·Seq·All 목록의 우클릭 메뉴(띄우지 않고 띄우려던 메뉴를 적음)와 북마크·정렬 단추의 메뉴."""
    captured = []
    real_exec = QMenu.exec_
    QMenu.exec_ = lambda menu, *args: captured.extend(_menu_texts(menu))
    try:
        for widget, show in ((player.sidebar, player.show_sidebar_context_menu), (player.seq_sidebar, player.show_seq_context_menu),
                             (player.all_sidebar, player.show_all_context_menu)):
            player.sidebar_tabs.setCurrentWidget(widget)
            QApplication.processEvents()
            show(widget.visualItemRect(widget.item(0)).center())
        player.show_all_context_menu(QPoint(5, player.all_sidebar.viewport().height() - 5))  # 항목 밖 — 맨 위 항목만
    finally:
        QMenu.exec_ = real_exec
        player.sidebar_tabs.setCurrentWidget(player.sidebar)
        QApplication.processEvents()
    captured.extend(_menu_texts(player.bookmarkMenuButton.menu()))
    captured.extend(_menu_texts(player.sidebar_sort_button.menu()))
    return captured


def _fps_texts(player):
    """fps 칸의 상태 글 — 재생 코드가 넣는 규약 글을 어댑터에 넣어 보고, 화면에 나온 글을 적는다 (끝에 되돌림)."""
    slot, label = player.labelPlaybackFPS, player.transportBar.fpsLabel
    before = slot.text()
    found = []
    for raw in FPS_PROTOCOL_TEXTS:
        slot.setText(raw)
        found.append(label.text())
    slot.setText(before)
    return found


def _thumbnail_bar_texts(player):
    """썸네일 진행 막대의 글 — 진짜 반복(`_make_thumbnails`)을 워커 없이 돌려 가며 적는다."""
    bar = player.thumbnailProgressBar
    state = player._thumbnail_pass_state()
    found = []
    real_generate = player.generate_thumbnail
    player.generate_thumbnail = lambda *args, **kwargs: found.append(bar.format()) or False  # 만드는 중의 글
    was_closed, shown_format = player._sidebar_scan_closed, bar.format()
    try:
        player._make_thumbnails([], state)  # 만들 것이 없음
        found.append(bar.format())
        player._make_thumbnails([("x.mov", None)], state)  # 끝까지
        found.append(bar.format())
        player._make_thumbnails([("x.mov", None)], (state[0] - 1, state[1]))  # 목록이 바뀜
        found.append(bar.format())
        assert not player.is_thumbnail_mode  # 목록 모드에서 모음 — 썸네일 모드에서 시작한 반복이면 '목록 모드로 바꿈'
        player._make_thumbnails([("x.mov", None)], (state[0], True))
        found.append(bar.format())
        player._sidebar_scan_closed = True
        player._make_thumbnails([("x.mov", None)], state)  # 창을 닫음
        found.append(bar.format())
    finally:
        player._sidebar_scan_closed = was_closed
        del player.generate_thumbnail
        assert player.generate_thumbnail == real_generate
        player._thumbnail_bar_timer.stop()
        bar.setVisible(False)
        bar.setFormat(shown_format)
    return found


def banner_shapes(player):
    """알림 띠의 모양들 — (이름, 그 모양으로 보이는 함수). 띠의 글을 넣는 방식이 바뀌면 여기만 고친다."""
    banner = player.update_banner
    megabyte = 1_000_000
    return (
        ("offer", lambda: banner.show_offer("9.9.9", "1.0.0")),
        ("download", lambda: banner.show_progress(megabyte, 2 * megabyte, player_update.download_text("9.9.9", "NAS", megabyte, 2 * megabyte))),
        ("staging", lambda: banner.show_progress(0, 0, player_update.STAGING_TEXT)),
        ("checking", lambda: banner.show_progress(0, 0, player_update.CHECKING_OTHERS_TEXT, cancellable=False)),
        ("closing", lambda: banner.show_progress(0, 0, player_update.CLOSING_OTHERS_TEXT, cancellable=False)),
        ("cancelling", lambda: banner.show_progress(0, 0, player_update.CANCELLING_TEXT)),
        ("helper", lambda: banner.show_progress(0, 0, player_update.HELPER_STARTING_TEXT, cancellable=False)),
        ("updated", lambda: banner.show_message(player_update.updated_message("9.9.9"))),
    )


def _banner_texts(player):
    banner = player.update_banner
    found = []
    for _name, show in banner_shapes(player):
        show()
        found.append(banner.text_label.text())
        found.extend(button.text() for button in (banner.notes_button, banner.update_button, banner.later_button, banner.cancel_button)
                     if not button.isHidden())
    banner.hide_banner()
    return found


def _title_texts(player):
    """창 제목 — 보통·불러오는 중·공유 설정 문제(제목에 적지 않음 — 보통과 같음)·변환표 오류 (끝에 되돌림)."""
    saved = (getattr(player, "shared_config_loading", False), player.shared_config_problem, getattr(player, "path_map_problem", None))
    found = []
    try:
        for loading, problem, map_problem in ((False, None, None), (True, None, None), (False, "x", None), (False, None, "y"),
                                              (False, "x", "y")):
            player.shared_config_loading, player.shared_config_problem, player.path_map_problem = loading, problem, map_problem
            player._update_shared_config_title()
            found.append(player.windowTitle())
    finally:
        player.shared_config_loading, player.shared_config_problem, player.path_map_problem = saved
        player._update_shared_config_title()
    return found


def collect(player):
    """영역(`AREAS`) → 화면 글자 목록. 빈 글은 빼고, 임시 폴더·창 제목의 머리는 바꿔 적는다."""
    pages = player.toolPanel._pages
    raw = {
        "menubar": menubar_texts(player),
        "transport": _tree_texts(player.transportBar) + _fps_texts(player),
        "sidebar": _tree_texts(player.mainSplitter.widget(0)) + _thumbnail_bar_texts(player),
        "sidebar_menus": _context_menu_texts(player),
        "annotation": _tree_texts(pages["annotation"]),
        "ocr": _tree_texts(pages["ocr"]),
        "viewer": _tree_texts(player.videoWidget, skip=(player.overlayFrame,)),
        "overlay": _tree_texts(player.overlayFrame),
        "banner": _banner_texts(player),
        "title": _title_texts(player),
    }
    normalize = _normalizer(player)
    return {area: [normalize(text) for text in raw[area] if isinstance(text, str) and text.strip()] for area in AREAS}
