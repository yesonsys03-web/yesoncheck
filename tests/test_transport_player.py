"""재생 줄을 단 창 — 진짜 VideoPlayer(화면 없이)에서 재생 줄의 단추·프레임 칸·키가 지금의 재생·탐색 코드를 부르는지.

2026-11-16 UI 개편 PR 1: 창 전체 폭의 큰 Play·Stop 막대와 정보 줄을 없애고 슬라이더 아래 재생 줄 하나로.
동작은 그대로 — 단추는 예전 처리기(`toggle_play_pause`·`prev_frame`·`next_frame`·`stop_video`)를 부른다.
다른 것 하나(사용자 결정): 선택 재생 중의 '처음'은 지금 영상의 처음으로만 가고 선택 재생을 유지,
선택 재생을 끝내는 길은 사이드바의 '끝내기' 단추(예전 Stop이 하던 일).
"""

import time

import cv2
import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QColor, QImage, QKeyEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPushButton, QStyle, QStyleOptionFrame, QWidget

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import transport_icons
from yesoncheck.transport_bar import PlayStateSlot, TextSlot, TransportBar


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


@pytest.fixture
def shown(player, qapp):
    player.show()
    QApplication.setActiveWindow(player)
    QTest.qWait(250)  # show()가 걸어 둔 일(100ms 뒤 force_focus — 창이 포커스를 가져감, 200ms 뒤 사이드바 폭)이 지난 뒤부터
    return player


def clip(tmp_path, name="a.mp4", frames=48):
    return write_test_video(str(tmp_path / name), frames=frames)


def press(player, key, text=""):
    player.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text))


def current(player):
    return int(player.labelFrameCount.text().removeprefix("Current: "))


def wait_until(predicate, limit_s=30):
    start = time.perf_counter()
    while not predicate() and time.perf_counter() - start < limit_s:
        QApplication.processEvents()
        time.sleep(0.0005)
    assert predicate(), "기다린 일이 일어나지 않음"


def start_playlist(player, tmp_path, frames=(48, 6)):
    clips = [clip(tmp_path, f"c{i}.mp4", count) for i, count in enumerate(frames)]
    player.add_files_to_sidebar(clips)
    player.sidebar.selectAll()
    player.play_selected_files()
    assert player.is_playlist_playing and player.timer.isActive()
    return clips


def type_frame(player, qapp, text, key=Qt.Key_Return):
    field = player.transportBar.frameField
    QTest.mouseClick(field, Qt.LeftButton)
    qapp.processEvents()
    assert field.hasFocus()
    QTest.keyClicks(field, text)
    QTest.keyClick(field, key)
    qapp.processEvents()


# ---------------------------------------------------------------- 창 구조

def test_window_has_the_transport_bar_instead_of_the_big_buttons(player):
    bar = player.transportBar
    assert isinstance(bar, TransportBar)
    texts = {button.text() for button in player.findChildren(QPushButton)}
    assert "Stop" not in texts and "Play" not in texts and "Pause" not in texts
    for gone in ("frameRateComboBox", "frameRateLabel", "volumePercentLabel", "detect_fps"):
        assert not hasattr(player, gone), gone
    # 옛 이름은 재생 줄의 위젯이나 그 어댑터
    assert player.filenameLabel is bar.filenameLabel and player.timeLabel is bar.timeLabel
    assert player.volumeSlider is bar.volumeSlider and player.loopCheckBox is bar.loopButton
    assert isinstance(player.labelFrameCount, TextSlot) and isinstance(player.labelTotalFrames, TextSlot)
    assert isinstance(player.labelPlaybackFPS, TextSlot) and isinstance(player.playPauseButton, PlayStateSlot)
    assert player.labelPlaybackFPS.text() == "재생: 대기" and bar.fpsLabel.text() == "대기"
    assert player.playPauseButton.text() == "Play"
    assert bar in player.control_widgets and player.endPlaylistButton not in player.control_widgets


def test_bar_sits_right_under_the_slider_across_the_window(shown):
    bar, slider, central = shown.transportBar, shown.positionScroll, shown.centralWidget()
    assert bar.height() == 44
    assert bar.width() == central.width() and bar.mapTo(central, bar.rect().topLeft()).x() == 0
    slider_bottom = slider.mapTo(central, slider.rect().topLeft()).y() + slider.height()
    bar_top = bar.mapTo(central, bar.rect().topLeft()).y()
    assert 0 <= bar_top - slider_bottom <= 6
    assert bar_top + bar.height() == central.height()  # 창의 맨 아래 줄


def test_bar_does_not_move_when_panels_lists_and_files_change(shown, qapp, tmp_path):
    shown.open_file("A", clip(tmp_path, "a.mp4"))
    qapp.processEvents()
    bar = shown.transportBar
    central = shown.centralWidget()

    def spots():
        widgets = [bar, bar.firstButton, bar.prevButton, bar.playButton, bar.nextButton, bar.lastButton,
                   bar.loopButton, bar.frameField]
        return [(w.mapTo(central, w.rect().topLeft()).x(), w.mapTo(central, w.rect().topLeft()).y(), w.width(),
                 w.height()) for w in widgets]

    before = spots()
    shown.show_tool_panel("ocr")  # 도구 패널을 열고 쪽을 바꿈 (예전에는 가운데 열의 접는 상자를 모두 펼침)
    shown.show_tool_panel("annotation")
    shown.add_files_to_sidebar([clip(tmp_path, f"list{i:02d}.mp4", 2) for i in range(30)])
    shown.open_file("A", clip(tmp_path, "EP101_SC001_a_very_long_file_name_for_the_transport_bar_TK2.mp4", 12))
    shown.play_video()
    wait_until(lambda: current(shown) >= 3)
    shown.pause_video()
    qapp.processEvents()
    assert spots() == before


# ---------------------------------------------------------------- 단추 = 예전 처리기

def test_play_button_toggles_playback(player, tmp_path):
    player.open_file("A", clip(tmp_path))
    bar = player.transportBar
    bar.playButton.click()
    assert player.timer.isActive() and player.playPauseButton.text() == "Pause"
    assert bar.playButton.toolTip() == "일시정지 (Space)"
    bar.playButton.click()
    assert not player.timer.isActive() and player.playPauseButton.text() == "Play"
    assert bar.playButton.toolTip() == "재생 (Space)"


def test_step_buttons_do_what_the_arrow_keys_do(player, tmp_path):
    player.open_file("A", clip(tmp_path))
    bar = player.transportBar
    bar.nextButton.click()
    bar.nextButton.click()
    assert current(player) == 3 and bar.frameField.text() == "3"
    bar.prevButton.click()
    assert current(player) == 2
    press(player, Qt.Key_Right)
    assert current(player) == 3
    press(player, Qt.Key_Left)
    assert current(player) == 2


def test_loop_button_sets_loop_playback(player):
    bar = player.transportBar
    assert not player.loopEnabled
    bar.loopButton.click()
    assert player.loopEnabled and bar.loopButton.isChecked()
    bar.loopButton.click()
    assert not player.loopEnabled
    player.loopCheckBox.setChecked(True)  # 옛 이름으로도
    assert player.loopEnabled


def test_volume_slider_reaches_the_player(player):
    player.transportBar.volumeSlider.setValue(30)
    assert player._media_volume == 30


def test_volume_slider_starts_at_the_actual_volume(player, tmp_path):
    """처음 볼륨은 50 — 슬라이더·툴팁과 실제 소리 크기가 같음. 예전에는 슬라이더만 50에서 시작하고 재생기는 100이라
    (슬라이더를 건드려야 맞춰짐) 표시가 틀렸음 — 사용자 결정 2026-11-16 "처음에 소리를 50으로": 소리를 표시(50)에 맞춤."""
    from yesoncheck import player_base

    assert player_base.START_VOLUME == 50
    slider = player.transportBar.volumeSlider
    assert slider.value() == player.media_volume() == 50
    assert slider.toolTip() == "볼륨 50%"
    player.open_file("A", clip(tmp_path))  # 재생기를 만듦 — 그때 정해 둔 볼륨을 받음
    assert player._media_player.volume() == 50 == slider.value()
    assert player.overlayVolume.value() == 50  # V 모드의 오버레이 볼륨도 같은 값에서


def test_volume_slider_follows_a_change_made_in_the_overlay(player, tmp_path):
    """V 모드의 오버레이 볼륨으로 바꾸면 재생 줄의 슬라이더·툴팁도 그 값 (돌아왔을 때 옛 값을 보이지 않게)."""
    slider = player.transportBar.volumeSlider
    player.overlayVolume.setValue(30)  # 영상을 열기 전(재생기 없음)에도
    assert player.media_volume() == 30
    assert slider.value() == 30 and slider.toolTip() == "볼륨 30%"
    player.open_file("A", clip(tmp_path))
    assert player._media_player.volume() == 30 == slider.value()
    player.overlayVolume.setValue(45)
    assert player._media_player.volume() == 45 == slider.value() and slider.toolTip() == "볼륨 45%"
    slider.setValue(70)  # 재생 줄에서 바꾸면 오버레이는 다음에 갱신될 때 맞춤 (update_overlay_controls — 예전 그대로)
    assert player._media_player.volume() == 70
    player.update_overlay_controls()
    assert player.overlayVolume.value() == 70


def test_first_button_is_the_old_stop_outside_a_playlist(player, tmp_path):
    player.open_file("A", clip(tmp_path))
    player.play_video()
    wait_until(lambda: current(player) >= 4)
    player.transportBar.firstButton.click()
    assert not player.timer.isActive() and current(player) == 1
    assert player.positionScroll.value() == 0 and player.playPauseButton.text() == "Play"
    assert player.labelPlaybackFPS.text() == "재생: 정지"  # stop_video가 남기는 글 그대로


def test_home_key_is_the_first_button(player, tmp_path):
    player.open_file("A", clip(tmp_path))
    player.seek_to_frame(20)
    press(player, Qt.Key_Home)
    assert current(player) == 1


def test_last_button_goes_to_the_last_frame_and_pauses(player, tmp_path):
    player.open_file("A", clip(tmp_path, frames=48))
    player.play_video()
    wait_until(lambda: current(player) >= 3)
    player.transportBar.lastButton.click()
    assert not player.timer.isActive()
    assert current(player) == 48 and player.positionScroll.value() == player.positionScroll.maximum()
    player.transportBar.lastButton.click()  # 이미 끝 — 그대로
    assert current(player) == 48


def test_end_key_is_the_last_button(player, tmp_path):
    player.open_file("A", clip(tmp_path, frames=48))
    press(player, Qt.Key_End)
    assert current(player) == 48
    press(player, Qt.Key_Home)
    assert current(player) == 1


def test_home_and_end_work_while_a_list_has_focus(player, tmp_path):
    player.add_files_to_sidebar([clip(tmp_path, "a.mp4", 48), clip(tmp_path, "b.mp4", 6)])
    player.sidebar.setCurrentRow(1)
    player.open_file("A", player.sidebar.item(0).toolTip())
    for source in (player.sidebar, player.seq_sidebar, player.all_sidebar):
        assert player.eventFilter(source, QKeyEvent(QEvent.KeyPress, Qt.Key_End, Qt.NoModifier)) is True
        assert current(player) == 48
        assert player.eventFilter(source, QKeyEvent(QEvent.KeyPress, Qt.Key_Home, Qt.NoModifier)) is True
        assert current(player) == 1
    assert player.sidebar.currentRow() == 1  # 목록의 고른 줄은 그대로


def test_controls_do_nothing_without_a_video(shown, qapp):
    bar = shown.transportBar
    for button in (bar.firstButton, bar.prevButton, bar.playButton, bar.nextButton, bar.lastButton):
        button.click()
    press(shown, Qt.Key_Home)
    press(shown, Qt.Key_End)
    shown.go_to_frame_number(5)
    type_frame(shown, qapp, "7")
    assert not shown.timer.isActive() and shown.cap_a is None
    assert bar.frameField.text() == "0" and shown.playPauseButton.text() == "Play"


# ---------------------------------------------------------------- 프레임 칸

def test_frame_field_goes_to_the_typed_frame(shown, qapp, tmp_path):
    shown.open_file("A", clip(tmp_path, frames=48))
    type_frame(shown, qapp, "12")
    assert current(shown) == 12 and shown.transportBar.frameField.text() == "12"
    assert shown.positionScroll.value() == round(11 / 47 * shown.positionScroll.maximum())
    type_frame(shown, qapp, "0")  # 범위 밖은 가장 가까운 끝으로
    assert current(shown) == 1
    type_frame(shown, qapp, "99999")
    assert current(shown) == 48 and shown.transportBar.frameField.text() == "48"
    assert shown.positionScroll.value() == shown.positionScroll.maximum()


def test_typing_a_frame_after_the_end_shows_that_frame(shown, qapp, tmp_path):
    """'끝'(또는 슬라이더 오른쪽 끝)에 있다가 번호를 쳐서 가면 번호·시간·슬라이더가 모두 그 프레임 (리뷰에서 잡음 —
    슬라이더가 끝에 남은 채 이동하면 update_position_info가 Current를 전체 장수로 적어, 영상은 10번인데 번호는 48)."""
    shown.open_file("A", clip(tmp_path, frames=48))
    shown.transportBar.lastButton.click()
    assert current(shown) == 48
    type_frame(shown, qapp, "10")
    assert current(shown) == 10 and shown.transportBar.frameField.text() == "10"
    assert int(shown.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) == 10
    assert shown.positionScroll.value() == round(9 / 47 * shown.positionScroll.maximum())
    assert shown.timeLabel.text().startswith(shown.format_time(9 / 24) + " /")
    shown.positionScroll.setValue(shown.positionScroll.maximum())  # 슬라이더 오른쪽 끝을 누른 뒤에도
    assert current(shown) == 48
    type_frame(shown, qapp, "5")
    assert current(shown) == 5 and shown.transportBar.frameField.text() == "5"
    assert shown.timeLabel.text().startswith(shown.format_time(4 / 24) + " /")


def test_typing_the_next_frame_near_the_end_moves_there(shown, qapp, tmp_path):
    """끝에서 셋째 장 안에서 바로 다음 번호 (리뷰에서 잡음 — 그 구간의 이동 _seek_conservative는 '목표 == 캡처가 다음에 읽을 자리'면
    이미 거기 있다고 보고 아무것도 안 함: 45번에서 46을 치면 45 그대로였음)."""
    shown.open_file("A", clip(tmp_path, frames=48))
    for number in (44, 45, 46, 47, 48, 47, 46, 45, 46, 44):
        type_frame(shown, qapp, str(number))
        assert current(shown) == number, number
        assert shown.transportBar.frameField.text() == str(number), number
        assert int(shown.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) == number, number  # 캡처도 그 프레임을 막 읽은 자리


def test_coming_back_from_another_app_while_typing_leaves_the_shortcuts_working(shown, qapp, tmp_path):
    """번호를 치다 말고 다른 창으로 갔다 오면 치던 글은 버리고 포커스는 창으로 — 칸에 남으면 돌아온 뒤 Space·← →가 먹지 않음."""
    shown.open_file("A", clip(tmp_path, frames=48))
    field = shown.transportBar.frameField
    QTest.mouseClick(field, Qt.LeftButton)
    qapp.processEvents()
    QTest.keyClicks(field, "3")
    other = QWidget()
    other.show()
    try:
        QApplication.setActiveWindow(other)
        qapp.processEvents()
        assert field.text() == str(current(shown))
        QApplication.setActiveWindow(shown)
        qapp.processEvents()
        assert shown.hasFocus() and not field.hasFocus()
        QTest.keyClick(shown, Qt.Key_Space)
        assert shown.timer.isActive()
        shown.pause_video()
    finally:
        other.close()
        other.deleteLater()


def test_frame_field_fits_six_digits_under_the_theme_sheet(shown, qapp):
    """프레임 칸의 글자 자리(테두리·안쪽 여백을 뺀 곳)에 숫자 여섯 자리가 들어감 — 두 테마에서 (text()는 칸이 좁아도 전체 글이라 '보인다'의 증거가 아님)."""
    field = shown.transportBar.frameField

    def room():
        option = QStyleOptionFrame()
        field.initStyleOption(option)
        inside = field.style().subElementRect(QStyle.SE_LineEditContents, option, field)
        widest = max("0123456789", key=field.fontMetrics().horizontalAdvance)
        return inside.width() - (field.fontMetrics().horizontalAdvance(widest * 6) + 4)  # QLineEdit는 글자 양옆에 2px씩 둠

    assert room() >= 0
    shown.set_light_theme()
    qapp.processEvents()
    assert room() >= 0
    shown.set_dark_theme()


def test_after_typing_a_frame_the_shortcuts_work_again(shown, qapp, tmp_path):
    shown.open_file("A", clip(tmp_path, frames=48))
    type_frame(shown, qapp, "12")
    assert shown.hasFocus() and not shown.transportBar.frameField.hasFocus()
    QTest.keyClick(shown, Qt.Key_Space)
    assert shown.timer.isActive()
    shown.pause_video()
    type_frame(shown, qapp, "30", key=Qt.Key_Escape)  # Esc — 가지 않고 편집만 끝냄
    assert shown.hasFocus() and shown.transportBar.frameField.text() == str(current(shown)) != "30"
    QTest.keyClick(shown, Qt.Key_Right)
    assert shown.transportBar.frameField.text() == str(current(shown))


def test_typing_while_playing_is_not_overwritten_and_enter_keeps_playing(shown, qapp, tmp_path):
    shown.loopCheckBox.setChecked(True)  # 짧은 시험 영상이 끝나 멈추지 않게
    shown.open_file("A", clip(tmp_path, frames=48))
    shown.play_video()
    field = shown.transportBar.frameField
    QTest.mouseClick(field, Qt.LeftButton)
    qapp.processEvents()
    QTest.keyClicks(field, "3")
    seen = current(shown)
    wait_until(lambda: current(shown) != seen)  # 재생 틱이 번호를 바꿔도
    assert field.text() == "3" and shown.timer.isActive()  # 치던 글자는 그대로, 재생도 그대로
    QTest.keyClicks(field, "0")
    QTest.keyClick(field, Qt.Key_Return)
    assert shown.timer.isActive()  # 재생은 멈추지 않음
    assert 30 <= current(shown) <= 34 and field.text() == str(current(shown))
    shown.pause_video()


# ---------------------------------------------------------------- 선택 재생

def test_end_playlist_button_shows_only_during_a_playlist(player, tmp_path):
    button = player.endPlaylistButton
    assert button.isHidden() and button.text() == "이어 재생 끝내기" and button.focusPolicy() == Qt.NoFocus
    start_playlist(player, tmp_path)
    assert not button.isHidden()
    button.click()  # 예전 Stop이 하던 일
    assert button.isHidden() and not player.is_playlist_playing
    assert not player.timer.isActive() and current(player) == 1
    player.on_sidebar_item_clicked(player.sidebar.item(1))  # 목록 클릭이 다시 영상을 엶
    assert player.filenameLabel.text() == "A: c1.mp4"


def test_first_button_keeps_the_playlist_and_rewinds_only_the_current_video(player, tmp_path, dialogs):
    start_playlist(player, tmp_path, frames=(48, 6))
    wait_until(lambda: current(player) >= 5)
    player.transportBar.firstButton.click()
    assert not player.timer.isActive() and current(player) == 1
    assert player.is_playlist_playing and player.current_playlist_index == 0
    assert player.filenameLabel.text() == "A: c0.mp4" and not player.endPlaylistButton.isHidden()
    player.on_sidebar_item_clicked(player.sidebar.item(1))  # 선택 재생 중이라 목록 클릭은 여전히 무시
    assert player.filenameLabel.text() == "A: c0.mp4"

    player.transportBar.playButton.click()  # 그 영상부터 이어 재생 → 끝나면 다음 영상으로
    wait_until(lambda: player.current_playlist_index == 1)
    wait_until(lambda: not player.is_playlist_playing)
    assert player.endPlaylistButton.isHidden()
    assert any(title == "Playlist Complete" for _kind, title, _text in dialogs.messages)


def test_home_key_in_a_playlist_is_the_first_button(player, tmp_path):
    start_playlist(player, tmp_path)
    wait_until(lambda: current(player) >= 4)
    press(player, Qt.Key_Home)
    assert not player.timer.isActive() and current(player) == 1 and player.is_playlist_playing
    player.end_playlist()
    assert not player.is_playlist_playing


def test_end_playlist_button_hides_however_the_playlist_ends(player, tmp_path):
    start_playlist(player, tmp_path)
    player._end_playlist_mode()  # 영상을 확인하지 못해 선택 재생만 끝남 (보던 영상은 그대로)
    assert player.endPlaylistButton.isHidden()
    player.pause_video()
    player.is_playlist_playing = True  # 다른 길로 켜져도 단추가 따라옴
    assert not player.endPlaylistButton.isHidden()
    player.is_playlist_playing = False
    assert player.endPlaylistButton.isHidden()


def test_hiding_and_restoring_controls_does_not_reveal_the_end_button(player, tmp_path):
    bar = player.transportBar
    press(player, Qt.Key_V, "v")
    assert bar.isHidden()
    press(player, Qt.Key_V, "v")
    assert not bar.isHidden() and player.endPlaylistButton.isHidden()
    player.hide_all_ui_elements()  # 영상만 전체 화면
    assert bar.isHidden()
    player.restore_ui_elements()
    assert not bar.isHidden() and player.endPlaylistButton.isHidden()


# ---------------------------------------------------------------- 테마

def test_theme_switch_recolours_the_bar_icons(player):
    def first_icon():
        image = player.transportBar.firstButton.icon().pixmap(18, 18).toImage().convertToFormat(QImage.Format_ARGB32)
        return bytes(image.bits().asarray(image.byteCount()))

    def drawn(colour):
        image = transport_icons.icon("first", QColor(colour)).pixmap(18, 18).toImage().convertToFormat(QImage.Format_ARGB32)
        return bytes(image.bits().asarray(image.byteCount()))

    assert first_icon() == drawn("#d0d0d0")
    player.set_light_theme()
    assert first_icon() == drawn("#333333")
    player.set_dark_theme()
    assert first_icon() == drawn("#d0d0d0")


# ---------------------------------------------------------------- 파일 이름: B는 와이프가 켜진 동안만 (사용자 보고 2026-11-17)

def test_file_name_shows_b_only_while_the_wipe_is_on(player, tmp_path):
    """와이프를 끈 뒤에도 'A: …, B: …'가 남던 것 — 화면에 B가 보일 때(와이프가 켜진 동안)만 B 이름 (사용자 결정 2026-11-17)."""
    assert player.open_file("A", clip(tmp_path, "a.mp4")) and player.open_file("B", clip(tmp_path, "b.mp4"))
    assert player.filenameLabel.text() == "A: a.mp4"  # B를 열기만 함 — 와이프는 꺼져 있음
    player.wipeCheckBox.setChecked(True)
    assert player.filenameLabel.text() == "A: a.mp4, B: b.mp4"
    player.wipeCheckBox.setChecked(False)
    assert player.filenameLabel.text() == "A: a.mp4"
    player.wipeCheckBox.setChecked(True)
    assert player.filenameLabel.text() == "A: a.mp4"  # 와이프를 끄면 B를 닫음 (2026-11-18 — 아래 시험)
    assert player.open_file("B", clip(tmp_path, "c.mp4"))  # 와이프가 켜진 채 B를 엶
    assert player.filenameLabel.text() == "A: a.mp4, B: c.mp4"
    player._release_side("B")
    assert player.filenameLabel.text() == "A: a.mp4"


# ---------------------------------------------------------------- 와이프를 끄면 B를 닫음 (사용자 결정 2026-11-18)

def test_turning_the_wipe_off_closes_b(player, tmp_path, monkeypatch):
    """와이프를 끄면 B 영상을 닫음 — 다시 켜면 새 B를 열 때까지 B 자리는 검정 (사용자 결정 2026-11-18: 1.9.4·2.0.0은 B가 열린 채
    남아, 다시 켜고 X·Y를 누르면 같은 B 그림이 다시 보였음 — 시험으로 확인)."""
    assert player.open_file("A", clip(tmp_path, "a.mp4")) and player.open_file("B", clip(tmp_path, "b.mp4"))
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)
    player.seek_to_frame(10)  # 와이프면 B도 읽음 (← → 한 장 이동은 A만)
    assert player.frame_b is not None
    old_b = player.cap_b
    assert old_b.isOpened()

    player.wipeCheckBox.setChecked(False)
    assert not old_b.isOpened()  # 놓음 — 메모리·파일이 돌아옴
    assert player.cap_b is None and player.frame_b is None and player.filename_b == ""
    assert player.filenameLabel.text() == "A: a.mp4"

    drawn = []
    real = player.videoWidget.updateFrame
    monkeypatch.setattr(player.videoWidget, "updateFrame", lambda a, b: (drawn.append(b), real(a, b)))
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)
    player.seek_to_frame(20)
    assert drawn and all(b is None for b in drawn)  # B 자리는 검정 — 같은 B가 다시 나오지 않음

    assert player.open_file("B", clip(tmp_path, "c.mp4"))  # 새 B를 채우면 다시 보임
    player.seek_to_frame(30)
    assert drawn[-1] is not None and player.filenameLabel.text() == "A: a.mp4, B: c.mp4"


def test_turning_the_wipe_off_without_b_does_nothing_more(player, tmp_path):
    assert player.open_file("A", clip(tmp_path, "a.mp4"))
    player.wipeCheckBox.setChecked(True)
    player.wipeCheckBox.setChecked(False)
    assert player.cap_b is None and player.cap_a is not None and player.filenameLabel.text() == "A: a.mp4"


def test_turning_the_wipe_off_during_playback_keeps_playing_a(player, tmp_path):
    """재생 중에 와이프를 꺼도 재생은 A로 이어짐 — 닫은 B를 읽지 않음(리뷰가 짚은 빈틈: 틱의 B 읽기는 wipeEnabled가 막음)."""
    assert player.open_file("A", clip(tmp_path, "a.mp4")) and player.open_file("B", clip(tmp_path, "b.mp4"))
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)
    player.seek_to_frame(5)
    player.play_video()
    try:
        assert player.timer.isActive()
        player.next_frame_playback()
        player.wipeCheckBox.setChecked(False)
        start = player.get_current_frame_index()
        for _ in range(3):
            player.next_frame_playback()
        assert player.cap_b is None and player.frame_b is None
        assert player.get_current_frame_index() == start + 3
    finally:
        player.pause_video()
