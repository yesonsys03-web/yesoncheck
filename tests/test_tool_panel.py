"""도구 패널 위젯(`tool_panel`) — 뷰어 오른쪽 칸: 머리(이름 + 닫기) 아래에 쪽 하나(주석 또는 OCR).

플레이어 없이 위젯만 본다. 무엇을 쪽으로 넣고 언제 여닫는지는 플레이어 몫(`player_tools` — test_tool_panel_player).
"""

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QCheckBox, QLabel, QLineEdit, QToolButton, QVBoxLayout, QWidget

from yesoncheck import tool_panel, transport_icons, ui_text
from yesoncheck.tool_panel import ToolPanel, section_title


@pytest.fixture(autouse=True)
def _default_language():
    yield
    ui_text.set_language(ui_text.DEFAULT_LANGUAGE)


def make_page(minimum_width=0):
    page = QWidget()
    layout = QVBoxLayout(page)
    page.check = QCheckBox("켜기")
    page.line = QLineEdit()
    layout.addWidget(page.check)
    layout.addWidget(page.line)
    if minimum_width:
        page.setMinimumWidth(minimum_width)
    return page


@pytest.fixture
def panel(qapp):
    widget = ToolPanel()
    widget.annotation = make_page()
    widget.ocr = make_page()
    widget.add_page("annotation", "panel.annotation", widget.annotation)
    widget.add_page("ocr", "panel.ocr", widget.ocr)
    widget.resize(tool_panel.PANEL_WIDTH, 600)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()


def title_of(panel):
    return panel.findChild(QLabel, "toolPanelTitle")


def close_button(panel):
    return panel.findChild(QToolButton, "toolPanelClose")


def icon_pixels(button):
    image = button.icon().pixmap(18, 18).toImage().convertToFormat(QImage.Format_ARGB32)
    return bytes(image.bits().asarray(image.byteCount()))


def test_panel_wants_the_starting_width(panel):
    assert tool_panel.PANEL_WIDTH == 340
    assert panel.objectName() == "toolPanel"
    assert panel.sizeHint().width() == 340
    assert panel.minimumSizeHint().width() <= 340


def test_header_has_the_title_and_a_close_button(panel):
    assert title_of(panel) is not None and title_of(panel).text() == "수정 사항 주석"
    button = close_button(panel)
    assert button is not None and button.focusPolicy() == Qt.NoFocus
    assert button.toolTip() == "패널 닫기 (N)" and not button.icon().isNull() and button.text() == ""
    # 머리가 위, 쪽이 그 아래
    assert title_of(panel).mapTo(panel, title_of(panel).rect().bottomLeft()).y() < panel.annotation.mapTo(
        panel, panel.annotation.rect().topLeft()).y()


def test_first_page_shows_and_show_page_switches(panel, qapp):
    assert panel.keys() == ("annotation", "ocr")
    assert panel.current() == "annotation"
    assert panel.annotation.isVisible() and not panel.ocr.isVisible()
    panel.show_page("ocr")
    qapp.processEvents()
    assert panel.current() == "ocr" and title_of(panel).text() == "OCR"
    assert panel.ocr.isVisible() and not panel.annotation.isVisible()
    panel.show_page("ocr")  # 같은 쪽 — 그대로
    assert panel.current() == "ocr"
    panel.show_page("annotation")
    assert panel.current() == "annotation" and title_of(panel).text() == "수정 사항 주석"


def test_unknown_page_raises_before_changing_anything(panel):
    panel.show_page("ocr")
    with pytest.raises(KeyError):
        panel.show_page("settings")
    assert panel.current() == "ocr" and title_of(panel).text() == "OCR"


def test_same_key_twice_is_refused(panel):
    with pytest.raises(ValueError):
        panel.add_page("ocr", "panel.ocr", QWidget())
    assert panel.keys() == ("annotation", "ocr")


def test_unknown_title_key_is_refused_before_adding(panel):
    with pytest.raises(KeyError):
        panel.add_page("extra", "panel.no_such_title", QWidget())
    assert panel.keys() == ("annotation", "ocr")


def test_empty_panel_has_no_current_page(qapp):
    panel = ToolPanel()
    assert panel.current() is None and panel.keys() == ()
    assert title_of(panel).text() == ""
    with pytest.raises(KeyError):
        panel.show_page("annotation")
    panel.deleteLater()


def test_close_button_asks_once_per_click(panel):
    asked = []
    panel.closeRequested.connect(lambda: asked.append(1))
    QTest.mouseClick(close_button(panel), Qt.LeftButton)
    assert asked == [1]
    assert panel.isVisible() and panel.current() == "annotation"  # 숨기는 것은 받는 쪽(플레이어)이 함
    QTest.mouseClick(close_button(panel), Qt.LeftButton)
    assert asked == [1, 1]


def test_pages_keep_their_state_while_another_is_shown(panel):
    panel.annotation.check.setChecked(True)
    panel.annotation.line.setText("3번 컷 색 확인")
    panel.show_page("ocr")
    panel.ocr.check.setChecked(True)
    panel.show_page("annotation")
    assert panel.annotation.check.isChecked() and panel.annotation.line.text() == "3번 컷 색 확인"
    panel.show_page("ocr")
    assert panel.ocr.check.isChecked()
    panel.hide()
    panel.show()
    assert panel.current() == "ocr" and panel.ocr.check.isChecked()


def test_minimum_width_covers_the_widest_page_whichever_is_shown(qapp):
    panel = ToolPanel()
    panel.add_page("annotation", "panel.annotation", make_page())
    panel.add_page("ocr", "panel.ocr", make_page(minimum_width=420))
    assert panel.current() == "annotation"
    assert panel.minimumSizeHint().width() >= 420  # 보이지 않는 쪽의 최소 너비도 — 쪽을 바꿔도 칸 너비가 튀지 않게
    assert panel.sizeHint().width() == panel.minimumSizeHint().width()  # 원하는 너비는 최소 너비 밑으로 안 감
    panel.deleteLater()


def test_section_title_reads_the_text_table(qapp):
    label = section_title("ocr.section.roi")
    assert isinstance(label, QLabel) and label.objectName() == "toolPanelSection"
    assert label.text() == "ROI 설정"
    with pytest.raises(KeyError):
        section_title("ocr.section.none")
    label.deleteLater()


def test_retranslate_rereads_the_title_tooltip_and_sections(panel):
    section = section_title("ocr.section.analysis")
    panel.ocr.layout().addWidget(section)
    ui_text.set_language("en")
    panel.retranslate()
    assert title_of(panel).text() == "Annotations"
    assert close_button(panel).toolTip() == "Close panel (N)"
    assert section.text() == "OCR analysis"
    panel.show_page("ocr")
    assert title_of(panel).text() == "OCR"
    ui_text.set_language("ko")
    panel.retranslate()
    assert section.text() == "OCR 분석" and close_button(panel).toolTip() == "패널 닫기 (N)"


def test_apply_theme_recolours_the_close_icon(panel):
    panel.apply_theme("light")
    expected = transport_icons.icon("close", QColor("#333333")).pixmap(18, 18).toImage().convertToFormat(
        QImage.Format_ARGB32)
    assert icon_pixels(close_button(panel)) == bytes(expected.bits().asarray(expected.byteCount()))
    with pytest.raises(KeyError):
        panel.apply_theme("sepia")
    panel.apply_theme("dark")
    dark = transport_icons.icon("close", QColor("#d0d0d0")).pixmap(18, 18).toImage().convertToFormat(QImage.Format_ARGB32)
    assert icon_pixels(close_button(panel)) == bytes(dark.bits().asarray(dark.byteCount()))
