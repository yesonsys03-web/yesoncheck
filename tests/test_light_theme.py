"""밝은 테마(T 키)에 어두운 테마가 섞이지 않음 (2026-11-12 — 사용자 보고 "화이트 테마 T 모드의 일관성이 없어. 블랙 테마가 섞여 있어").

섞여 있던 것 셋:
- **창 바탕이 검정**(Mac): 밝은 시트에서 `QMainWindow { background: #fafafa }` 뒤에 `QWidget { background: transparent }`가 와서
  창 자신(QMainWindow도 QWidget)의 바탕이 투명 — 창이 아무것도 칠하지 않음. raster 화면에서는 시스템 창 색이 비쳐 티가 안 났고,
  GL 뷰포트(Mac 기본)에서는 칠하지 않은 자리가 검게 나옴. 여기서는 창을 투명한 그림에 그려 바탕을 실제로 칠하는지 봄
  (화면 없는 시험에서는 GL 합성을 못 봄 — 실제 화면은 눈 확인).
- **접는 상자(ROI 설정·OCR 분석·결과 관리·수정 사항 주석)의 머리**가 어두운 색 고정(위젯에 직접 넣은 시트).
- **'OCR 분석 방식:'·패턴 라벨**의 글자색이 어두운 테마용(#e0e0e0) 고정 — 밝은 바탕에서 거의 안 보임.
어두운 테마의 모양은 그대로여야 함(색 값 고정).
"""

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor, QImage, QPalette
from PyQt5.QtWidgets import QLabel

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck.player_timeline import CollapsibleBox

LIGHT_WINDOW = "#fafafa"
DARK_WINDOW = "#232323"
LIGHT_TEXT = "#2c3e50"
DARK_TEXT = "#e0e0e0"
# 접는 상자 머리: (접힘 바탕, 펼침 바탕, 글자)
DARK_HEADER = ("#2d2d2d", "#3d3d3d", "#ffae00")
LIGHT_HEADER = ("#e9ecef", "#dee2e6", LIGHT_TEXT)


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


def boxes(player):
    found = player.findChildren(CollapsibleBox)
    assert len(found) == 4
    return found


def header_background(box):
    button = box.toggle_button
    return painted(button, QPoint(button.width() - 8, button.height() // 2))  # 글자는 왼쪽 정렬 — 오른쪽 끝은 바탕뿐


def header_text(box):
    box.toggle_button.ensurePolished()
    return box.toggle_button.palette().color(QPalette.ButtonText).name()


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


def test_collapsible_headers_are_light_in_the_light_theme(player):
    player.set_light_theme()
    collapsed, expanded, text = LIGHT_HEADER
    for box in boxes(player):
        assert (header_background(box), header_text(box)) == (opaque(collapsed), text)
        box.toggle_button.click()  # 펼침
        assert header_background(box) == opaque(expanded)


def test_collapsible_headers_keep_their_dark_look_in_the_dark_theme(player):
    collapsed, expanded, text = DARK_HEADER
    for box in boxes(player):
        assert (header_background(box), header_text(box)) == (opaque(collapsed), text)
        box.toggle_button.click()
        assert header_background(box) == opaque(expanded)


def test_collapsible_headers_follow_the_theme_back_to_dark(player):
    player.set_light_theme()
    player.set_dark_theme()
    assert {header_background(box) for box in boxes(player)} == {opaque(DARK_HEADER[0])}


def test_ocr_option_labels_use_the_theme_text_colour(player):
    assert {label_text(label) for label in ocr_option_labels(player)} == {DARK_TEXT}
    player.set_light_theme()
    assert {label_text(label) for label in ocr_option_labels(player)} == {LIGHT_TEXT}
