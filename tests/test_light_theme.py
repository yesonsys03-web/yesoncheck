"""밝은 테마(T 키)에 어두운 테마가 섞이지 않음 (2026-11-12 — 사용자 보고 "화이트 테마 T 모드의 일관성이 없어. 블랙 테마가 섞여 있어").

섞여 있던 것 셋:
- **창 바탕이 검정**(Mac): 밝은 시트에서 `QMainWindow { background: #fafafa }` 뒤에 `QWidget { background: transparent }`가 와서
  창 자신(QMainWindow도 QWidget)의 바탕이 투명 — 창이 아무것도 칠하지 않음. raster 화면에서는 시스템 창 색이 비쳐 티가 안 났고,
  GL 뷰포트(Mac 기본)에서는 칠하지 않은 자리가 검게 나옴. 여기서는 창을 투명한 그림에 그려 바탕을 실제로 칠하는지 봄
  (화면 없는 시험에서는 GL 합성을 못 봄 — 실제 화면은 눈 확인).
- **접는 상자(ROI 설정·OCR 분석·결과 관리·수정 사항 주석)의 머리**가 어두운 색 고정(위젯에 직접 넣은 시트).
  2026-11-16 UI 개편에서 접는 상자는 없어지고 도구 패널(뷰어 오른쪽)이 됨 — 같은 뜻을 새 위젯으로 봄: 패널의 머리·
  사이드바의 작은 단추·선택 재생 단추가 테마를 따르고(색을 위젯에 직접 넣지 않음), 패널의 몸은 창 바탕색.
- **'OCR 분석 방식:'·패턴 라벨**의 글자색이 어두운 테마용(#e0e0e0) 고정 — 밝은 바탕에서 거의 안 보임.
어두운 테마의 모양은 그대로여야 함(색 값 고정).
"""

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor, QImage, QPalette
from PyQt5.QtWidgets import QApplication, QLabel, QWidget

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

LIGHT_WINDOW = "#fafafa"
DARK_WINDOW = "#232323"
LIGHT_TEXT = "#2c3e50"
DARK_TEXT = "#e0e0e0"
# 도구 패널의 머리: (바탕, 제목 글자)
DARK_PANEL_HEADER = ("#2b2b2b", "#e0e0e0")
LIGHT_PANEL_HEADER = ("#f0f0f0", LIGHT_TEXT)
# 사이드바의 작은 단추·선택 재생 단추: (바탕, 글자, 켜진 단추의 바탕)
DARK_TOOL = ("#2d2d2d", "#e0e0e0", "#4a4a4a")
LIGHT_TOOL = ("#ffffff", LIGHT_TEXT, "#d0d4d8")


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    window = new_player(make_config(str(tmp_path), {}))
    window.resize(1200, 800)
    window.show()
    return window


def painted(widget, point):
    """위젯을 투명한 그림에 그렸을 때 그 점의 색 — 칠하지 않은 자리는 투명(#00000000)으로 남음."""
    image = QImage(widget.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    widget.render(image)
    return image.pixelColor(point).name(QColor.HexArgb)


def opaque(color):
    return QColor(color).name(QColor.HexArgb)


def bare_window_point(player):
    """창에서 자식이 아무것도 칠하지 않는 자리 — 사이드바 개수 줄('0개')의 글자 없는 오른쪽 끝."""
    label = player.sidebar_count_label
    return label.mapTo(player, QPoint(label.width() - 4, label.height() // 2))


def settle():
    for _ in range(4):
        QApplication.processEvents()


def panel_header_look(player):
    """도구 패널 머리의 (바탕, 제목 글자색). 바탕은 제목 라벨 아래의 점에서 — 라벨이 제 바탕을 칠하면(어두운 시트의
    QWidget 규칙) 머리의 색이 가려짐."""
    header = player.toolPanel.findChild(QWidget, "toolPanelHeader")
    title = player.toolPanel.findChild(QLabel, "toolPanelTitle")
    title.ensurePolished()
    background = painted(header, QPoint(header.width() // 2, header.height() - 5))
    return background, title.palette().color(QPalette.WindowText).name()


def tool_look(button):
    """단추의 (바탕, 글자색) — 바탕은 글자가 없는 왼쪽 끝 안쪽에서."""
    button.ensurePolished()
    return painted(button, QPoint(4, button.height() // 2)), button.palette().color(QPalette.ButtonText).name()


def sidebar_tools(player):
    return [player.openFolderButton, player.bookmarkMenuButton, player.refreshListButton, player.thumbnailModeButton,
            player.playlistButton]


def ocr_option_labels(player):
    labels = [label for label in player.findChildren(QLabel) if label.text() == "OCR 분석 방식:"]
    assert len(labels) == 1
    return [labels[0], player.ocrPatternLabel]


def label_text(label):
    label.ensurePolished()
    return label.palette().color(QPalette.WindowText).name()


def test_light_theme_window_paints_its_own_background(player):
    player.set_light_theme()
    assert painted(player, bare_window_point(player)) == opaque(LIGHT_WINDOW)


def test_dark_theme_window_background_is_unchanged(player):
    assert painted(player, bare_window_point(player)) == opaque(DARK_WINDOW)


def test_switching_back_to_dark_restores_the_dark_window(player):
    player.set_light_theme()
    player.set_dark_theme()
    assert painted(player, bare_window_point(player)) == opaque(DARK_WINDOW)


def test_tool_panel_header_follows_the_theme(player):
    player.show_tool_panel("ocr")
    settle()
    dark = (opaque(DARK_PANEL_HEADER[0]), DARK_PANEL_HEADER[1])
    assert panel_header_look(player) == dark
    player.set_light_theme()
    settle()
    assert panel_header_look(player) == (opaque(LIGHT_PANEL_HEADER[0]), LIGHT_PANEL_HEADER[1])
    player.set_dark_theme()
    settle()
    assert panel_header_look(player) == dark


@pytest.mark.parametrize("page", ["annotation", "ocr"])
def test_tool_panel_body_is_the_window_colour_in_both_themes(player, page):
    """패널의 몸은 창 바탕색 — 어두운 색 조각이 밝은 테마에 남지 않음 (쪽의 오른쪽 아래 구석: 위젯이 없는 자리)."""
    player.show_tool_panel(page)
    settle()
    panel = player.toolPanel
    corner = panel.mapTo(player, QPoint(panel.width() - 6, panel.height() - 6))
    assert painted(player, corner) == opaque(DARK_WINDOW)
    player.set_light_theme()
    settle()
    assert painted(player, corner) == opaque(LIGHT_WINDOW)


def test_sidebar_tools_follow_the_theme(player):
    settle()
    background, text, _checked = DARK_TOOL
    for button in sidebar_tools(player):
        assert tool_look(button) == (opaque(background), text), button.objectName()
        assert button.styleSheet() == ""  # 색을 위젯에 직접 넣지 않음 — 넣으면 테마를 바꿔도 남음
    player.set_light_theme()
    settle()
    background, text, _checked = LIGHT_TOOL
    for button in sidebar_tools(player):
        assert tool_look(button) == (opaque(background), text), button.objectName()
    player.set_dark_theme()
    settle()
    assert tool_look(player.openFolderButton) == (opaque(DARK_TOOL[0]), DARK_TOOL[1])


def test_chosen_view_mode_button_is_marked_in_both_themes(player):
    """목록 | 썸네일 가운데 고른 쪽은 바탕이 다름 — 두 테마 모두 (예전에는 초록·보라 색 단추)."""
    settle()
    assert player.listModeButton.isChecked() and not player.thumbnailModeButton.isChecked()
    assert tool_look(player.listModeButton)[0] == opaque(DARK_TOOL[2])
    assert tool_look(player.thumbnailModeButton)[0] == opaque(DARK_TOOL[0])
    player.set_light_theme()
    settle()
    assert tool_look(player.listModeButton)[0] == opaque(LIGHT_TOOL[2])
    assert tool_look(player.thumbnailModeButton)[0] == opaque(LIGHT_TOOL[0])


def test_transport_toggles_follow_the_theme(player):
    """재생 줄의 토글(와이프·주석·OCR): 켜진 토글의 바탕이 테마마다 그 테마의 색."""
    player.show_tool_panel("annotation")
    settle()
    toggle = player.transportBar.annotationButton
    assert toggle.isChecked()
    assert painted(toggle, QPoint(3, toggle.height() // 2)) == opaque("#4a4a4a")
    player.set_light_theme()
    settle()
    assert painted(toggle, QPoint(3, toggle.height() // 2)) == opaque("#d0d4d8")


def test_ocr_option_labels_use_the_theme_text_colour(player):
    assert {label_text(label) for label in ocr_option_labels(player)} == {DARK_TEXT}
    player.set_light_theme()
    assert {label_text(label) for label in ocr_option_labels(player)} == {LIGHT_TEXT}
