"""재생 줄(`transport_bar`) — 위젯 단위 시험 (플레이어 없이 막대만 띄움).

재생 줄은 슬라이더 아래 한 줄: [파일 이름] [처음·한 장 뒤·재생·한 장 앞·끝·반복]
[프레임 칸 / 전체 · 시간 · fps · 도구 토글(와이프 X Y · 주석 · OCR) · 볼륨].
지키는 것: 높이·단추 자리가 글자와 상관없이 고정, 좁아져도 단추와 프레임 숫자는 다 보임, 재생 코드가 옛 이름으로
넣는 글자(`Current: 12`·`Total: …`·`재생: …`·`Play`/`Pause`)를 어댑터가 받아 재생 줄의 모양으로 보임.
좁아질 때의 차례: 도구 토글의 글자(아이콘만 남김) → 파일 이름 → fps → 시간 → 볼륨 슬라이더 → 도구 토글.
"""

import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QColor, QFocusEvent, QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QStyle, QStyleOptionFrame, QToolButton, QWidget

from yesoncheck import transport_bar, transport_icons, ui_text
from yesoncheck.transport_bar import (FrameField, PlayStateSlot, TextSlot, ToolToggle, TransportBar, shown_current,
                                      shown_fps, shown_total)

LONG_NAME = "A: " + "EP101_SC001_아주_긴_파일_이름_" * 8 + ".mov"
WIPE_TOTAL = "Total A: 12345 (771F 09f), B: 12345 (771F 09f)"


# ---------------------------------------------------------------- 어댑터

def test_text_slot_shows_only_when_the_text_changes():
    shown = []
    slot = TextSlot("Current: 0", shown.append)
    assert slot.text() == "Current: 0" and shown == []
    slot.setText("Current: 0")  # 같은 글 — 재생 틱마다 불려도 아무것도 안 함
    assert shown == []
    slot.setText("Current: 7")
    slot.setText("Current: 7")
    assert shown == ["Current: 7"] and slot.text() == "Current: 7"


def test_play_state_slot_maps_the_old_button_texts():
    states = []
    slot = PlayStateSlot(states.append)
    assert slot.text() == "Play"
    slot.setText("Pause")
    slot.setStyleSheet("background-color: yellow;")  # 옛 코드의 호출 — 받기만 함
    slot.setText("Play")
    slot.setStyleSheet("")
    assert states == [True, False] and slot.text() == "Play"
    with pytest.raises(ValueError):
        slot.setText("Stop")
    assert slot.text() == "Play"


@pytest.mark.parametrize("raw,shown", [
    ("Current: 12", "12"),
    ("Current: 0", "0"),
    ("Current: 12345", "12345"),
    ("현재 12", "현재 12"),  # 모르는 꼴은 그대로 보임 (지어내지 않음)
    ("", ""),
])
def test_shown_current(raw, shown):
    assert shown_current(raw) == shown


@pytest.mark.parametrize("raw,shown", [
    ("Total: 334 (20F 14f)", "/ 334 (20F 14f)"),
    ("Total: 0", "/ 0"),
    (WIPE_TOTAL, "/ A: 12345 (771F 09f), B: 12345 (771F 09f)"),
    ("334", "334"),
])
def test_shown_total(raw, shown):
    assert shown_total(raw) == shown


@pytest.mark.parametrize("raw,shown", [
    ("재생: 24 FPS", "24 fps"),
    ("재생: 23.976 FPS · 실제 23.9", "23.976 fps · 실제 23.9"),
    ("재생: 0 FPS", "0 fps"),
    ("재생: 대기", "대기"),
    ("재생: 일시정지", "일시정지"),
    ("재생: 정지", "정지"),
    ("24", "24"),
])
def test_shown_fps(raw, shown):
    assert shown_fps(raw) == shown


# ---------------------------------------------------------------- 프레임 칸

@pytest.fixture
def field(qapp):
    # 창 안의 자식으로 띄움 — 혼자 창이면 창이 활성화될 때 포커스를 저절로 가져 '편집 중'이 됨 (앱에서는 메인 창이 포커스를 가짐)
    host = QWidget()
    layout = QHBoxLayout(host)
    widget = FrameField()
    layout.addWidget(widget)
    host.show()
    QApplication.setActiveWindow(host)
    qapp.processEvents()
    assert not widget.hasFocus()
    yield widget
    host.close()
    host.deleteLater()


def focus(widget, qapp):
    widget.setFocus(Qt.TabFocusReason)
    qapp.processEvents()
    assert widget.hasFocus()


def test_frame_field_shows_the_number(field):
    assert field.text() == "0"
    field.show_number("12")
    assert field.text() == "12"
    assert field.objectName() == "frameField" and field.focusPolicy() == Qt.ClickFocus
    assert field.alignment() & Qt.AlignRight


def test_frame_field_width_does_not_follow_the_text(field, qapp):
    width = field.sizeHint().width()
    field.show_number("123456")
    assert field.sizeHint().width() == width == field.minimumSizeHint().width()
    assert field.fontMetrics().horizontalAdvance("000000") < width  # 여섯 자리가 들어감


def test_frame_field_keeps_what_is_being_typed_while_ticks_arrive(field, qapp):
    field.show_number("10")
    focus(field, qapp)
    assert field.selectedText() == "10"  # 포커스를 얻으면 전체 선택 — 치면 바뀜
    QTest.keyClicks(field, "3")
    field.show_number("11")  # 재생 틱 — 치던 글자를 덮지 않음
    field.show_number("12")
    assert field.text() == "3"
    QTest.keyClick(field, Qt.Key_Escape)
    assert field.text() == "12" and not field.hasFocus()  # 편집이 끝나면 가장 새 값


def test_frame_field_enter_emits_the_number_once_and_ends_editing(field, qapp):
    entered, ended = [], []
    field.frameEntered.connect(entered.append)
    field.editingEnded.connect(lambda: ended.append(1))
    field.show_number("5")
    focus(field, qapp)
    QTest.keyClicks(field, "34")
    QTest.keyClick(field, Qt.Key_Return)
    assert entered == [34] and ended == [1]
    assert not field.hasFocus() and field.text() == "5"  # 새 번호는 이동한 쪽이 show_number로 알려 줌


def test_frame_field_empty_enter_reverts_without_signal(field, qapp):
    entered = []
    field.frameEntered.connect(entered.append)
    field.show_number("5")
    focus(field, qapp)
    QTest.keyClick(field, Qt.Key_Backspace)
    assert field.text() == ""
    QTest.keyClick(field, Qt.Key_Enter)
    assert entered == [] and field.text() == "5" and not field.hasFocus()


def test_frame_field_escape_reverts_and_reports_the_end(field, qapp):
    entered, ended = [], []
    field.frameEntered.connect(entered.append)
    field.editingEnded.connect(lambda: ended.append(1))
    field.show_number("5")
    focus(field, qapp)
    QTest.keyClicks(field, "99")
    QTest.keyClick(field, Qt.Key_Escape)
    assert entered == [] and ended == [1] and field.text() == "5"


def test_frame_field_losing_focus_reverts_without_claiming_focus_back(field, qapp):
    ended = []
    field.editingEnded.connect(lambda: ended.append(1))
    field.show_number("5")
    focus(field, qapp)
    QTest.keyClicks(field, "99")
    field.clearFocus()  # 다른 곳을 눌러 포커스가 떠남 — 그 위젯의 포커스를 도로 뺏지 않게 신호 없음
    qapp.processEvents()
    assert field.text() == "5" and ended == []


def test_frame_field_ends_editing_when_its_window_is_deactivated(field, qapp):
    """다른 앱·창으로 가서 창이 비활성이 되면 편집을 끝냄(끝 신호) — 그냥 되돌리기만 하면 돌아왔을 때 포커스가 칸에 남음."""
    ended = []
    field.editingEnded.connect(lambda: ended.append(1))
    field.show_number("5")
    focus(field, qapp)
    QTest.keyClicks(field, "99")
    QApplication.sendEvent(field, QFocusEvent(QEvent.FocusOut, Qt.ActiveWindowFocusReason))
    assert field.text() == "5" and ended == [1]


def test_frame_field_has_room_for_six_digits(field):
    option = QStyleOptionFrame()
    field.initStyleOption(option)
    inside = field.style().subElementRect(QStyle.SE_LineEditContents, option, field)
    widest = max("0123456789", key=field.fontMetrics().horizontalAdvance)
    assert field.fontMetrics().horizontalAdvance(widest * 6) + 4 <= inside.width()  # QLineEdit는 글자 양옆에 2px씩 둠


def test_frame_field_takes_digits_only(field, qapp):
    field.show_number("5")
    focus(field, qapp)
    QTest.keyClicks(field, "v1n-2 ")
    assert field.text() == "12"


def test_frame_field_shows_unexpected_text_as_it_is(field):
    field.show_number("현재 12")  # 재생 코드의 글 꼴이 바뀌면 숨기지 않고 그대로 보임
    assert field.text() == "현재 12"


# ---------------------------------------------------------------- 재생 줄

@pytest.fixture
def bar(qapp):
    widget = TransportBar()
    widget.resize(1400, transport_bar.BAR_HEIGHT)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()


def buttons(bar):
    return [bar.firstButton, bar.prevButton, bar.playButton, bar.nextButton, bar.lastButton, bar.loopButton]


def spots(bar):
    """단추 여섯과 프레임 칸의 막대 안 자리."""
    return [(w.mapTo(bar, w.rect().topLeft()).x(), w.mapTo(bar, w.rect().topLeft()).y(), w.width(), w.height())
            for w in buttons(bar) + [bar.frameField]]


def set_width(bar, width, qapp):
    bar.resize(width, bar.height())
    qapp.processEvents()


def icon_pixels(button):
    image = button.icon().pixmap(18, 18).toImage().convertToFormat(QImage.Format_ARGB32)
    return bytes(image.bits().asarray(image.byteCount()))


def test_bar_has_the_fixed_height_and_name(bar, qapp):
    assert transport_bar.BAR_HEIGHT == 44
    assert bar.objectName() == "transportBar"
    for width in (1400, 700, bar.minimumSizeHint().width()):
        set_width(bar, width, qapp)
        assert bar.height() == 44 and bar.minimumHeight() == bar.maximumHeight() == 44


def test_buttons_are_six_in_order_without_focus(bar):
    xs = [b.mapTo(bar, b.rect().topLeft()).x() for b in buttons(bar)]
    assert xs == sorted(xs) and len(set(xs)) == 6
    for button in buttons(bar):
        assert isinstance(button, QToolButton) and button.focusPolicy() == Qt.NoFocus
        assert button.objectName() == "transportButton" and (button.width(), button.height()) == (30, 30)
        assert not button.icon().isNull() and button.text() == ""
    assert bar.loopButton.isCheckable() and not bar.playButton.isCheckable()
    assert bar.prevButton.autoRepeat() and bar.nextButton.autoRepeat() and not bar.playButton.autoRepeat()
    assert bar.volumeSlider.focusPolicy() == Qt.NoFocus


def test_tooltips_come_from_the_text_table(bar):
    assert bar.firstButton.toolTip() == "처음으로 (Home)"
    assert bar.prevButton.toolTip() == "한 장 뒤로 (←)"
    assert bar.playButton.toolTip() == "재생 (Space)"
    assert bar.nextButton.toolTip() == "한 장 앞으로 (→)"
    assert bar.lastButton.toolTip() == "끝으로 (End)"
    assert bar.loopButton.toolTip() == "반복 재생"
    assert bar.frameField.toolTip() == "프레임 번호 — 숫자를 치고 Enter"
    ui_text.set_language("en")
    try:
        bar.retranslate()
        assert bar.playButton.toolTip() == "Play (Space)" and bar.loopButton.toolTip() == "Loop playback"
    finally:
        ui_text.set_language("ko")
        bar.retranslate()
    assert bar.playButton.toolTip() == "재생 (Space)"


def group_edges(bar):
    left = bar.firstButton.mapTo(bar, bar.firstButton.rect().topLeft()).x()
    right = bar.loopButton.mapTo(bar, bar.loopButton.rect().topLeft()).x() + bar.loopButton.width()
    return left, right


def test_transport_buttons_sit_in_the_middle_when_there_is_room(bar, qapp):
    right_zone = bar.volumeSlider.parentWidget()
    wide = 2 * (right_zone.sizeHint().width() + transport_bar.ZONE_GAP + transport_bar.SIDE_MARGIN) + 400
    set_width(bar, wide, qapp)
    left, right = group_edges(bar)
    assert abs((left + right) / 2 - bar.width() / 2) <= 2
    volume_right = bar.volumeSlider.mapTo(bar, bar.volumeSlider.rect().topLeft()).x() + bar.volumeSlider.width()
    assert volume_right == bar.width() - transport_bar.SIDE_MARGIN  # 오른쪽 구역은 오른쪽 끝에
    assert bar.volumeSlider.width() == 90 and right_zone.width() == right_zone.sizeHint().width()
    name_left = bar.filenameLabel.mapTo(bar, bar.filenameLabel.rect().topLeft()).x()
    assert name_left == transport_bar.SIDE_MARGIN  # 파일 이름은 왼쪽 끝부터 단추 앞까지
    assert name_left + bar.filenameLabel.width() == left - transport_bar.ZONE_GAP


def test_transport_buttons_move_left_of_the_middle_rather_than_overlap_the_right_side(bar, qapp):
    right_zone = bar.volumeSlider.parentWidget()
    narrow = bar.sizeHint().width() + 20  # 모두 원하는 너비로 들어가지만, 한가운데에 두면 오른쪽 구역과 겹치는 너비
    assert narrow < 2 * right_zone.sizeHint().width()
    set_width(bar, narrow, qapp)
    left, right = group_edges(bar)
    zone_left = right_zone.mapTo(bar, right_zone.rect().topLeft()).x()
    assert right + transport_bar.ZONE_GAP == zone_left  # 오른쪽 구역 바로 앞에 붙음
    assert (left + right) / 2 < bar.width() / 2
    assert right_zone.width() == right_zone.sizeHint().width()  # 오른쪽 구역은 아직 줄지 않음
    assert left >= transport_bar.SIDE_MARGIN


@pytest.mark.parametrize("width", [1400, 900, 600])
def test_buttons_and_frame_field_do_not_move_when_the_texts_change(bar, qapp, width):
    set_width(bar, width, qapp)
    bar.filenameLabel.setText("A: a.mov")
    bar.show_total("Total: 5 (0F 05f)")
    bar.show_fps("재생: 정지")
    bar.show_current("Current: 1")
    bar.timeLabel.setText("00:00:00.000 / 00:00:00.167")
    qapp.processEvents()
    before = spots(bar)
    bar.filenameLabel.setText(LONG_NAME)
    bar.show_total(WIPE_TOTAL)
    bar.show_fps("재생: 23.976 FPS · 실제 23.9")
    bar.show_current("Current: 12345")
    bar.timeLabel.setText("00:08:34.375 / 00:08:34.375")
    qapp.processEvents()
    assert spots(bar) == before


def test_at_minimum_width_buttons_and_the_frame_numbers_are_whole(bar, qapp):
    bar.filenameLabel.setText(LONG_NAME)
    bar.show_current("Current: 12345")
    bar.show_total("Total: 12345 (771F 09f)")
    bar.show_fps("재생: 23.976 FPS · 실제 23.9")
    field_width = bar.frameField.width()
    set_width(bar, bar.minimumSizeHint().width(), qapp)
    rects = [(x, x + w) for x, _y, w, _h in spots(bar)]
    for (_l1, r1), (l2, _r2) in zip(rects, rects[1:]):
        assert r1 <= l2  # 겹치지 않음
    assert rects[0][0] >= 0 and rects[-1][1] <= bar.width()
    for button in buttons(bar):
        assert (button.width(), button.height()) == (30, 30)
    assert bar.frameField.width() == field_width and bar.frameField.text() == "12345"
    assert bar.totalLabel.displayed_text().startswith("/ 12345")
    assert bar.totalLabel.mapTo(bar, bar.totalLabel.rect().topRight()).x() <= bar.width()


def test_minimum_width_does_not_follow_the_texts(bar, qapp):
    before = bar.minimumSizeHint().width()
    bar.filenameLabel.setText(LONG_NAME)
    bar.show_total(WIPE_TOTAL)
    bar.show_fps("재생: 23.976 FPS · 실제 23.9")
    qapp.processEvents()
    assert bar.minimumSizeHint().width() == before
    # 최소 너비에 드는 것은 단추 묶음 + 프레임 칸 + '/ 00000' + 볼륨 아이콘뿐
    # (파일 이름·fps·시간·도구 토글·볼륨 슬라이더는 0까지 접힘 — 접힌 항목도 사이 간격은 차지: 항목 7개 → 간격 6).
    # 픽셀 값은 글꼴마다 다름(이 Mac 387, 글꼴 없는 Windows CI 527) — 그래서 관계로 봄
    right_zone = bar.volumeSlider.parentWidget()
    left, right = group_edges(bar)
    assert before == 2 * transport_bar.SIDE_MARGIN + (right - left) + transport_bar.ZONE_GAP + right_zone.minimumSizeHint().width()
    assert right_zone.minimumSizeHint().width() == (bar.frameField.sizeHint().width() + bar.totalLabel.floor_width()
                                                    + transport_bar.ICON_SIZE + 6 * transport_bar.INFO_SPACING)


def compact_right_width(bar):
    """도구 토글이 아이콘만일 때 오른쪽 구역이 원하는 너비 (글자와 무관 — 토글의 글자는 언어가 정함)."""
    return bar.volumeSlider.parentWidget().sizeHint().width() - bar.toolGroup.text_saving()


def test_the_file_name_gives_way_before_the_rest_of_the_right_side(bar, qapp):
    """토글의 글자가 아이콘으로 준 뒤: 파일 이름이 먼저 줄어 사라지고, 그다음에야 오른쪽 구역(fps·시간 …)이 줆."""
    bar.filenameLabel.setText(LONG_NAME)
    bar.show_total("Total: 12345 (771F 09f)")
    bar.show_fps("재생: 23.976 FPS · 실제 23.9")
    qapp.processEvents()
    right_zone = bar.volumeSlider.parentWidget()
    compact = compact_right_width(bar)
    width = bar.sizeHint().width() - bar.toolGroup.text_saving()  # 토글이 막 아이콘만 된 너비 — 파일 이름 몫은 그대로
    set_width(bar, width, qapp)
    assert right_zone.width() == compact and bar.filenameLabel.width() == transport_bar.NAME_HINT
    name_widths = []
    while right_zone.width() == compact and width > bar.minimumSizeHint().width():
        name_widths.append(bar.filenameLabel.width())
        width -= 40
        set_width(bar, width, qapp)
    assert name_widths[0] > 100 and name_widths == sorted(name_widths, reverse=True)
    assert name_widths[-1] < name_widths[0]  # 오른쪽 구역이 줄기 전에 파일 이름이 먼저 줄었음
    assert bar.filenameLabel.width() == 0  # 오른쪽 구역이 줄기 시작할 때 파일 이름은 이미 접힘
    assert right_zone.width() < compact


def test_file_name_is_dropped_rather_than_squeezed_below_what_it_can_show(bar, qapp):
    """파일 이름 자리가 줄인 이름('A: E….mov')도 못 그릴 만큼 좁으면 통째로 접음 — 몇 픽셀짜리 조각을 남기지 않음."""
    bar.filenameLabel.setText(LONG_NAME)
    qapp.processEvents()
    right_zone = bar.volumeSlider.parentWidget()
    left, right = group_edges(bar)
    floor = bar.filenameLabel.floor_width()
    assert floor > 10
    compact = compact_right_width(bar)
    packed = 2 * transport_bar.SIDE_MARGIN + compact + 2 * transport_bar.ZONE_GAP + (right - left)
    set_width(bar, packed + floor - 5, qapp)  # 파일 이름 자리 = 최소 너비보다 5px 모자람
    assert bar.filenameLabel.width() == 0
    assert right_zone.width() == compact  # 오른쪽 구역은 (토글의 글자 말고는) 아직 그대로
    set_width(bar, packed + floor + 20, qapp)
    assert bar.filenameLabel.width() == floor + 20
    shown = bar.filenameLabel.displayed_text()
    assert "…" in shown and shown.startswith("A: E") and shown.endswith(".mov")


def test_long_total_is_elided_with_the_number_kept(bar, qapp):
    bar.show_total(WIPE_TOTAL)
    qapp.processEvents()
    assert bar.totalLabel.text() == "/ A: 12345 (771F 09f), B: 12345 (771F 09f)"
    assert bar.totalLabel.displayed_text() != bar.totalLabel.text()  # 고정 너비라 줄여 그림 — 전체 글은 툴팁
    assert bar.totalLabel.tooltip_text() == bar.totalLabel.text()


def test_show_playing_swaps_the_icon_and_tooltip(bar):
    play_icon = icon_pixels(bar.playButton)
    bar.show_playing(True)
    assert bar.playButton.toolTip() == "일시정지 (Space)"
    assert icon_pixels(bar.playButton) != play_icon
    bar.show_playing(False)
    assert bar.playButton.toolTip() == "재생 (Space)" and icon_pixels(bar.playButton) == play_icon


def test_apply_theme_recolours_the_icons_and_keeps_the_layout(bar, qapp):
    assert transport_bar.ICON_COLORS == {"dark": "#d0d0d0", "light": "#333333"}
    before = spots(bar)
    bar.show_playing(True)
    bar.apply_theme("light")
    qapp.processEvents()
    for button, kind in zip(buttons(bar), ("first", "prev", "pause", "next", "last", "loop")):
        expected = transport_icons.icon(kind, QColor("#333333")).pixmap(18, 18).toImage().convertToFormat(QImage.Format_ARGB32)
        assert icon_pixels(button) == bytes(expected.bits().asarray(expected.byteCount())), kind
    assert spots(bar) == before
    with pytest.raises(KeyError):
        bar.apply_theme("sepia")
    bar.apply_theme("dark")


def test_volume_tooltip_follows_the_value(bar):
    assert (bar.volumeSlider.minimum(), bar.volumeSlider.maximum(), bar.volumeSlider.value()) == (0, 100, 50)
    assert bar.volumeSlider.toolTip() == "볼륨 50%"  # 막대 혼자의 처음 값 — 창에서는 플레이어가 실제 볼륨으로 맞춤
    bar.volumeSlider.setValue(73)
    assert bar.volumeSlider.toolTip() == "볼륨 73%"


def test_show_methods_feed_the_widgets(bar):
    bar.show_current("Current: 21")
    bar.show_total("Total: 334 (20F 14f)")
    bar.show_fps("재생: 24 FPS · 실제 23.8")
    assert bar.frameField.text() == "21"
    assert bar.totalLabel.text() == "/ 334 (20F 14f)"
    assert bar.fpsLabel.text() == "24 fps · 실제 23.8"


def test_labels_take_no_focus_and_only_the_field_takes_clicks(bar):
    for widget in (bar.filenameLabel, bar.totalLabel, bar.timeLabel, bar.fpsLabel):
        assert widget.focusPolicy() == Qt.NoFocus
    assert bar.frameField.focusPolicy() == Qt.ClickFocus


def test_clicking_the_field_selects_the_number(bar, qapp):
    QApplication.setActiveWindow(bar)
    bar.show_current("Current: 120")
    QTest.mouseClick(bar.frameField, Qt.LeftButton)
    qapp.processEvents()
    assert bar.frameField.hasFocus() and bar.frameField.selectedText() == "120"
    QTest.keyClicks(bar.frameField, "7")
    assert bar.frameField.text() == "7"
    bar.frameField.clearFocus()


def test_language_change_event_is_not_needed_for_plain_use(bar):
    # 재생 줄은 QEvent.LanguageChange에 기대지 않음 — 글은 retranslate()가 글자 표에서 다시 읽음
    QApplication.sendEvent(bar, QEvent(QEvent.LanguageChange))
    assert bar.playButton.toolTip() == "재생 (Space)"


# ---------------------------------------------------------------- 도구 토글 (와이프 X Y · 주석 · OCR)

def toggles(bar):
    return [bar.wipeButton, bar.annotationButton, bar.ocrButton]


def left_of(bar, widget):
    return widget.mapTo(bar, widget.rect().topLeft()).x()


def test_tool_toggle_full_width_is_what_qt_wants_for_text_beside_icon(qapp):
    toggle = ToolToggle()
    toggle.setText("A|B 와이프")
    toggle.setIcon(transport_icons.icon("wipe", QColor("#d0d0d0")))
    assert toggle.toolButtonStyle() == Qt.ToolButtonTextBesideIcon and not toggle.is_compact()
    wanted = QToolButton.sizeHint(toggle).width()
    assert toggle.full_width() == wanted == toggle.sizeHint().width() > transport_bar.BUTTON_SIZE
    toggle.set_compact(True)
    assert toggle.toolButtonStyle() == Qt.ToolButtonIconOnly and toggle.is_compact()
    assert toggle.sizeHint().width() == transport_bar.BUTTON_SIZE
    assert toggle.full_width() == wanted  # 지금 모양과 무관 — 글자까지 보일 때의 너비
    toggle.setText("OCR")
    assert toggle.full_width() < wanted
    toggle.set_compact(False)
    assert toggle.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
    toggle.deleteLater()


def test_tool_toggles_are_checkable_and_read_the_text_table(bar):
    expected = ((bar.wipeButton, "A|B 와이프", "A와 B를 와이프로 견줍니다"),
                (bar.annotationButton, "주석", "수정 사항 주석 패널을 열고 닫습니다"),
                (bar.ocrButton, "OCR", "OCR 패널을 열고 닫습니다"))
    for button, label, tip in expected:
        assert isinstance(button, ToolToggle) and button.isCheckable() and not button.isChecked()
        assert button.objectName() == "transportToggle" and button.focusPolicy() == Qt.NoFocus
        assert button.text() == label and button.toolTip() == tip and not button.icon().isNull()
    for button, label, tip in ((bar.wipeXButton, "X", "좌우로 나눔 (X축)"), (bar.wipeYButton, "Y", "위아래로 나눔 (Y축)")):
        assert isinstance(button, QToolButton) and button.isCheckable() and not button.isChecked()
        assert button.objectName() == "transportToggle" and button.focusPolicy() == Qt.NoFocus
        assert button.text() == label and button.toolTip() == tip
        assert not button.isEnabled()  # 와이프를 켜야 켜짐 (플레이어가 맡음)
    ui_text.set_language("en")
    try:
        bar.retranslate()
        assert bar.wipeButton.text() == "A|B Wipe" and bar.annotationButton.text() == "Annotate"
        assert bar.ocrButton.toolTip() == "Opens and closes the OCR panel"
    finally:
        ui_text.set_language("ko")
        bar.retranslate()
    assert bar.annotationButton.text() == "주석"


def test_tool_toggles_sit_between_the_fps_and_the_volume_in_order(bar, qapp):
    set_width(bar, bar.sizeHint().width() + 40, qapp)
    row = [bar.fpsLabel, bar.wipeButton, bar.wipeXButton, bar.wipeYButton, bar.annotationButton, bar.ocrButton,
           bar.volumeIcon, bar.volumeSlider]
    xs = [left_of(bar, widget) for widget in row]
    assert xs == sorted(xs) and len(set(xs)) == len(xs)
    for widget, following in zip(row, row[1:]):
        assert left_of(bar, widget) + widget.width() <= left_of(bar, following)  # 겹치지 않음
    for toggle in toggles(bar):
        assert toggle.isVisible() and toggle.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
        assert toggle.width() == toggle.full_width() and toggle.height() == transport_bar.BUTTON_SIZE
    assert bar.toolGroup.width() == bar.toolGroup.sizeHint().width()
    # 와이프 묶음(와이프·X·Y)과 패널 토글(주석·OCR) 사이는 묶음 안 간격보다 넓음
    inner = left_of(bar, bar.wipeYButton) - (left_of(bar, bar.wipeXButton) + bar.wipeXButton.width())
    between = left_of(bar, bar.annotationButton) - (left_of(bar, bar.wipeYButton) + bar.wipeYButton.width())
    assert between > inner >= 0


def test_toggle_texts_give_way_first_while_everything_else_stays(bar, qapp):
    """막대가 모든 것을 원하는 너비로 못 담게 되면 맨 먼저 토글의 글자가 빠짐(아이콘만) — 그 몫만큼 줄어드는 동안
    파일 이름 몫·재생 단추와 프레임 칸의 자리·라벨과 볼륨의 너비는 그대로."""
    bar.filenameLabel.setText(LONG_NAME)
    saving = bar.toolGroup.text_saving()
    assert saving > 0 and bar.toolGroup.compact_width() == bar.toolGroup.sizeHint().width() - saving
    full = bar.sizeHint().width()
    set_width(bar, full, qapp)
    assert all(t.toolButtonStyle() == Qt.ToolButtonTextBesideIcon for t in toggles(bar))
    assert bar.filenameLabel.width() == transport_bar.NAME_HINT
    before = spots(bar)
    others = [bar.totalLabel.width(), bar.timeLabel.width(), bar.fpsLabel.width(), bar.volumeSlider.width()]
    volume_x = left_of(bar, bar.volumeIcon) - bar.width()

    set_width(bar, full - 1, qapp)
    assert all(t.toolButtonStyle() == Qt.ToolButtonIconOnly and t.isVisible() for t in toggles(bar))
    assert all(t.width() == transport_bar.BUTTON_SIZE for t in toggles(bar))
    assert bar.wipeXButton.isVisible() and bar.wipeYButton.isVisible()
    assert all(not t.icon().isNull() for t in toggles(bar))
    icon_spots = [left_of(bar, w) - bar.width() for w in toggles(bar) + [bar.wipeXButton, bar.wipeYButton]]

    for width in (full - saving // 2, full - saving):
        set_width(bar, width, qapp)
        assert bar.filenameLabel.width() == transport_bar.NAME_HINT
        assert spots(bar) == before
        assert [bar.totalLabel.width(), bar.timeLabel.width(), bar.fpsLabel.width(), bar.volumeSlider.width()] == others
        assert left_of(bar, bar.volumeIcon) - bar.width() == volume_x
        # 아이콘만일 때 토글은 묶음의 오른쪽에 붙음 — 막대의 오른쪽 끝에서 잰 자리가 그대로
        assert [left_of(bar, w) - bar.width() for w in toggles(bar) + [bar.wipeXButton, bar.wipeYButton]] == icon_spots
    assert bar.toolGroup.width() == bar.toolGroup.compact_width()

    set_width(bar, full - saving - 30, qapp)  # 그보다 좁아지면 파일 이름이 줄기 시작
    assert bar.filenameLabel.width() == transport_bar.NAME_HINT - 30
    assert bar.toolGroup.width() == bar.toolGroup.compact_width()
    assert [bar.totalLabel.width(), bar.timeLabel.width(), bar.fpsLabel.width(), bar.volumeSlider.width()] == others

    set_width(bar, full, qapp)  # 다시 넓히면 글자가 돌아옴
    assert all(t.toolButtonStyle() == Qt.ToolButtonTextBesideIcon for t in toggles(bar))
    assert spots(bar) == before


def test_toggles_go_last_after_the_labels_and_the_volume_slider(bar, qapp):
    """아주 좁아지면: fps·시간이 접히고 볼륨 슬라이더가 사라진 뒤에야 토글 묶음이 사라짐 — 잘린 단추는 보이지 않음."""
    group, compact = bar.toolGroup, bar.toolGroup.compact_width()
    width = bar.sizeHint().width()
    whole_while_volume_shrinks = hidden_steps = 0
    while width >= bar.minimumSizeHint().width():
        set_width(bar, width, qapp)
        shown = [w.isVisible() for w in toggles(bar) + [bar.wipeXButton, bar.wipeYButton]]
        if group.width() >= compact:
            assert all(shown), width
            if bar.volumeSlider.width() < transport_bar.VOLUME_WIDTH // 2:
                whole_while_volume_shrinks += 1  # 볼륨 슬라이더가 절반 넘게 줄었는데도 토글은 온전
        else:  # 묶음이 줄기 시작함 — 다른 것은 이미 다 접혔고, 토글은 통째로 숨음
            assert not any(shown), width
            assert bar.volumeSlider.width() == 0 and bar.fpsLabel.width() == 0 and bar.timeLabel.width() == 0, width
            hidden_steps += 1
        width -= 9
    assert whole_while_volume_shrinks >= 2 and hidden_steps >= 2
    set_width(bar, bar.minimumSizeHint().width(), qapp)
    assert group.width() == 0 and not bar.wipeButton.isVisible()
    for button in buttons(bar):
        assert (button.width(), button.height()) == (30, 30)
    set_width(bar, bar.sizeHint().width(), qapp)
    assert all(w.isVisible() for w in toggles(bar) + [bar.wipeXButton, bar.wipeYButton])


def test_toggle_group_width_does_not_follow_the_checked_state(bar, qapp):
    set_width(bar, bar.sizeHint().width(), qapp)
    before = spots(bar), bar.toolGroup.sizeHint().width(), bar.minimumSizeHint().width()
    bar.wipeXButton.setEnabled(True)
    for button in toggles(bar) + [bar.wipeXButton, bar.wipeYButton]:
        button.setChecked(True)
    qapp.processEvents()
    assert (spots(bar), bar.toolGroup.sizeHint().width(), bar.minimumSizeHint().width()) == before


def test_theme_recolours_the_toggle_icons(bar, qapp):
    bar.apply_theme("light")
    for button, kind in ((bar.wipeButton, "wipe"), (bar.annotationButton, "annotate"), (bar.ocrButton, "ocr")):
        expected = transport_icons.icon(kind, QColor("#333333")).pixmap(18, 18).toImage().convertToFormat(QImage.Format_ARGB32)
        assert icon_pixels(button) == bytes(expected.bits().asarray(expected.byteCount())), kind
    bar.apply_theme("dark")
