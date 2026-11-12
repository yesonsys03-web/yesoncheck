"""테마를 바꾸면 색만 바뀜 — 위젯의 자리·크기·글꼴은 그대로 (2026-11-12).

사용자 보고: "테마 전환시 전체적으로 UI 사이즈 변경돼. 테마만 전환돼야 하는데"·"화이트 테마 전환시 버튼의 비율들이 바뀌는 거 같아".
원인은 두 테마 시트를 따로 써서 색이 아닌 속성까지 달랐던 것: 밝은 시트는 자식 위젯에 font-size 12px이 없어 시스템 글꼴 크기로 커졌고,
QPushButton·QComboBox에 min-height 20px, 목록 줄에 padding 6px, 스크롤바 폭 12px 등이 따로 있었음 — 테마를 바꾸면 보이는 위젯이 전부 움직였음.

지키는 것 둘:
- 시트(글): 두 시트의 규칙에서 **색이 아닌 속성**이 선택자마다 같음 (어두운 테마가 기준 — 켤 때의 테마이고 매뉴얼 그림의 테마).
- 창(결과): 테마를 바꿔도 보이는 위젯의 자리·크기, 목록 줄 높이, 글꼴 크기, 스크롤바 굵기가 그대로.
"""

import re

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QDialog, QLabel, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck.main_window_styles import DARK_STYLESHEET, LIGHT_STYLESHEET
from yesoncheck.player_timeline import CollapsibleBox

# 색만 정하는 속성 — 테마마다 달라도 됨
COLOR_PROPERTIES = {"background", "background-color", "color", "selection-background-color", "selection-color"}
# 크기와 무관한 꾸밈 — 밝은 테마의 체크 표시 그림(16×16 고정 상자 안)
DECORATION_PROPERTIES = {"image"}
COLOR_VALUE = re.compile(r"#[0-9a-fA-F]{3,8}|transparent|none")


def shape_rules(sheet):
    """선택자 → {속성: 색을 뺀 값} — 색만 정하는 속성과 꾸밈은 빼고, 값 안의 색(`1px solid #444`의 #444)도 뺌."""
    found = {}
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", sheet):
        for selector in match.group(1).split(","):
            shape = found.setdefault(" ".join(selector.split()), {})
            for declaration in match.group(2).split(";"):
                if ":" not in declaration:
                    continue
                name, value = (part.strip() for part in declaration.split(":", 1))
                if name in COLOR_PROPERTIES or name in DECORATION_PROPERTIES:
                    continue
                shape[name] = " ".join(part for part in value.split() if not COLOR_VALUE.fullmatch(part))
    return {selector: shape for selector, shape in found.items() if shape}


def test_theme_sheets_differ_only_in_colours():
    dark, light = shape_rules(DARK_STYLESHEET), shape_rules(LIGHT_STYLESHEET)
    differences = {selector: (dark.get(selector), light.get(selector))
                   for selector in sorted(set(dark) | set(light)) if dark.get(selector) != light.get(selector)}
    assert differences == {}


# ---------------------------------------------------------------- 창

@pytest.fixture
def player(new_player, dialogs, tmp_path, qapp):  # noqa: F811
    window = new_player(make_config(str(tmp_path), {}))
    window.resize(1280, 900)
    window.show()
    for name in [f"SH{n:03d}_TK{1 + n % 3}.mov" for n in range(60)]:  # 스크롤바가 생길 만큼
        item = QListWidgetItem(name)
        item.setData(Qt.UserRole, "/shots/" + name)
        item.setToolTip("/shots/" + name)
        window.sidebar.addItem(item)
    for box in window.findChildren(CollapsibleBox):
        box.toggle_button.click()  # 접는 상자를 모두 펼침 — 안의 단추·콤보·라벨도 봄
    settle(qapp)
    return window


def settle(qapp):
    for _ in range(6):
        qapp.processEvents()


def geometry(window):
    """보이는 위젯마다 (종류, 자리·크기) — 같은 위젯은 늘 같은 차례로 나옴."""
    found = {}
    for index, widget in enumerate(window.findChildren(QWidget)):
        if widget.isVisible():
            rect = widget.geometry()
            found[f"{index} {type(widget).__name__}"] = (rect.x(), rect.y(), rect.width(), rect.height())
    return found


def moved(before, after):
    return {key: (before.get(key), after.get(key)) for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)}


def test_switching_theme_keeps_every_widget_in_place(player, qapp):
    dark = geometry(player)
    assert len(dark) > 60
    player.set_light_theme()
    settle(qapp)
    assert moved(dark, geometry(player)) == {}
    player.set_dark_theme()
    settle(qapp)
    assert moved(dark, geometry(player)) == {}


def sizes(window, qapp):
    """줄 높이·스크롤바 굵기·글꼴 크기 — 위젯의 자리에는 안 잡히는 크기들."""
    dialog = QDialog(window)  # 딸린 창도 창의 시트를 물려받음
    layout = QVBoxLayout(dialog)
    label, button = QLabel("글자"), QPushButton("단추")
    layout.addWidget(label)
    layout.addWidget(button)
    dialog.show()
    settle(qapp)
    try:
        first = window.sidebar.item(0)
        return {
            "목록 줄 높이": window.sidebar.visualItemRect(first).height(),
            "목록 스크롤바 굵기": window.sidebar.verticalScrollBar().width(),
            "가운데 열 스크롤바 굵기": window.middleScrollArea.verticalScrollBar().sizeHint().width(),
            "메뉴 줄 글꼴": window.menuBar().fontInfo().pixelSize(),
            "목록 글꼴": window.sidebar.fontInfo().pixelSize(),
            "단추 글꼴": window.playPauseButton.fontInfo().pixelSize(),
            "콤보 글꼴": window.findChild(QComboBox).fontInfo().pixelSize(),
            "개수 줄 글꼴": window.sidebar_count_label.fontInfo().pixelSize(),
            "딸린 창 라벨 글꼴": label.fontInfo().pixelSize(),
            "딸린 창 단추 높이": button.height(),
        }
    finally:
        dialog.close()
        dialog.deleteLater()


def test_switching_theme_keeps_row_heights_scrollbars_and_fonts(player, qapp):
    dark = sizes(player, qapp)
    player.set_light_theme()
    settle(qapp)
    assert sizes(player, qapp) == dark
