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
from PyQt5.QtWidgets import QLabel

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

LIGHT_WINDOW = "#fafafa"
DARK_WINDOW = "#232323"
LIGHT_TEXT = "#2c3e50"
DARK_TEXT = "#e0e0e0"


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


def test_ocr_option_labels_use_the_theme_text_colour(player):
    assert {label_text(label) for label in ocr_option_labels(player)} == {DARK_TEXT}
    player.set_light_theme()
    assert {label_text(label) for label in ocr_option_labels(player)} == {LIGHT_TEXT}
