"""드래그 표지(is_dragging) 회귀 시험: 메인 시간 슬라이더를 놓을 때 표지가 풀려야 함 (사용자 보고 — 와이프 드래그 뒤 B가 검게 남음).

원인: VideoPlayer.is_dragging은 on_slider_moved(드래그 미리보기)가 True로 두고 on_slider_value_changed(valueChanged)만 False로 되돌린다.
그런데 드래그 미리보기(_update_ui_fast·_ultra_fast_ui_update)가 슬라이더 값을 blockSignals로 먼저 써 두므로, Qt가 뒤이어 setValue(position)을 해도
값이 이미 같아 valueChanged가 오지 않는다. 메인 슬라이더의 sliderReleased 처리(sync_audio_on_release)는 표지를 건드리지 않았으므로 놓은 뒤에도 True로 남아,
다음 클릭·휠까지 _update_ui_after_seek가 와이프 B를 숨기고(이 시험의 B 단언), OCR 검토 창이 열려 있으면 update_frame이 최소 갱신만 하고,
optimize_for_4k(자동 모드)가 GPU 길을 건너뜀. 오버레이 슬라이더는 on_overlay_slider_released에서 이미 되돌림 — 같은 처리를 메인 슬라이더에도.

시험은 실제 offscreen VideoPlayer에 mp4 두 개(A·B)를 열고 와이프를 켠 뒤, test_slider_click의 드래그 방식(누름 → 직접 만든 MouseMove → 놓음)으로 끈다.
표지가 풀리지 않는 상태는 이 하니스에서 진짜 드래그가 저절로 만든다(놓기 직전 True를 단언) — 일부러 써 넣지 않음. 단 sync_audio_on_release 단독 시험만 직접 True를 씀.

B 단언은 놓는 길이 둘:
- 놓을 때 정확한 위치로 옮기는 이동(_precise_seek)이 도는 드래그 — 마지막 움직임이 프레임 캐시에 맞아 캡처가 5장 넘게 떨어진 채 놓음(test_drag_release_seek와 같은 길).
- 이동이 안 도는 드래그(캐시 미적중 — 캡처가 이미 목표에 있음): 드래그 미리보기가 B 동기화를 통째로 건너뛰어 frame_b가 None인 채라, 표지를 풀어도 B가 검게 남음.
  놓을 때 B를 A의 장에 맞춰 다시 그려야 함(sync_audio_on_release의 elif) — 이 길의 시험은 A·B에 같은 클립을 열어 두 프레임의 밝기가 같음(같은 장)으로 가름.
  와이프면 정밀 이동의 허용 오차가 0(캡처와 1~5장 차이로 놓아도 이동 — 슬라이더·라벨·A/B 캡처가 함께 목표로), B가 이미 그 자리면(평범한 클릭·오버레이 슬라이더 놓기) elif도 다시 읽지 않음.
"""

import os

import cv2
import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from tests.conftest import write_test_video
from tests.test_drag_release_seek import CountingCapture
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

FRAMES = 48
SEEK_THRESHOLD = 5  # sync_audio_on_release가 캡처와 목표가 이보다 멀면 _precise_seek로 옮김


def send_drag_move(slider, pos):
    """왼쪽 버튼을 누른 채로 pos로 움직이는 MouseMove를 직접 보냄 (QTest.mouseMove는 이 하니스에서 버튼 상태를 못 들고 감 — test_slider_click과 같음)."""
    event = QMouseEvent(
        QMouseEvent.MouseMove, pos, slider.mapToGlobal(pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    QApplication.sendEvent(slider, event)
    QApplication.processEvents()


@pytest.fixture
def wipe_player(new_player, dialogs, tmp_path):  # noqa: F811
    """A·B를 연 실제 플레이어 + 와이프 켬 (체크 + X 와이프 — _update_ui_after_seek는 wipe_enabled_x/y를 봄)."""
    player = new_player(make_config(str(tmp_path), {}))
    player.resize(1200, 800)
    player.show()
    QTest.qWaitForWindowExposed(player)
    QApplication.processEvents()

    a = write_test_video(os.path.join(str(tmp_path), "v", "a.mp4"), frames=FRAMES)
    b = write_test_video(os.path.join(str(tmp_path), "v", "b.mp4"), frames=FRAMES)
    assert player.open_file("A", a) is True
    assert player.open_file("B", b) is True
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)
    player.drag_update_interval = 0  # 시험은 움직임을 잇달아 보냄 — 30ms 빈도 제한이 미리보기를 걸러 내지 않게
    QApplication.processEvents()
    assert player.videoWidget.wipeEnabled and player.videoWidget.wipe_enabled_x
    return player


def drag_off_the_capture(player):
    """메인 슬라이더를 20% 자리에서 눌러 60% → 80% → 60%로 끌고 놓지 않은 채 멈춤; 놓을 자리(QPoint) 반환.

    60%를 두 번 지나므로 마지막 움직임은 프레임 캐시에 맞아(캡처는 80%의 장에 남고 슬라이더·그림만 60%의 장) 놓을 때 정확한 위치로 옮기는 이동이 돎."""
    slider = player.positionScroll
    y = slider.height() // 2
    QTest.mousePress(slider, Qt.LeftButton, Qt.NoModifier, QPoint(int(slider.width() * 0.2), y))
    QApplication.processEvents()
    assert slider.isSliderDown() is True
    for fraction in (0.6, 0.8, 0.6):
        send_drag_move(slider, QPoint(int(slider.width() * fraction), y))
    capture_index = int(player.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
    assert player.cache_hits == 1  # 전제: 마지막 움직임이 캐시에 맞음
    assert abs(capture_index - slider.value()) > SEEK_THRESHOLD  # 전제: 놓을 때 이동이 돎
    return QPoint(int(slider.width() * 0.6), y)


def release(player, pos):
    QTest.mouseRelease(player.positionScroll, Qt.LeftButton, Qt.NoModifier, pos)
    QApplication.processEvents()


def test_release_resets_drag_flag_after_main_slider_drag(wipe_player):
    """끌고 놓으면 is_dragging이 False — 놓기 직전엔 True(미리보기가 값을 먼저 써 valueChanged가 안 온 진짜 드래그의 상태)."""
    player = wipe_player
    pos = drag_off_the_capture(player)
    assert player.is_dragging is True  # 놓기 전: 끌고 있음 (valueChanged가 안 풀었음)
    assert player.positionScroll.isSliderDown() is True

    release(player, pos)

    assert player.positionScroll.isSliderDown() is False
    assert player.is_dragging is False


def test_b_frame_is_drawn_again_after_release_in_wipe_mode(wipe_player, monkeypatch):
    """놓은 뒤의 그림 어디에도 B가 빠지지 않음 — 표지가 True로 남으면 놓을 때의 이동(_update_ui_after_seek)이 B를 None으로 그림(와이프 B 숨김).
    이어 update_frame이 B를 다시 그리므로 '마지막 그림'만 보면 옛 코드도 통과함 — 그래서 놓은 뒤의 모든 그림을 봄."""
    player = wipe_player
    calls = []
    original = player.videoWidget.updateFrame

    def recording_update_frame(frame_a, frame_b=None, *args, **kwargs):
        calls.append((frame_a is not None, frame_b is not None))
        return original(frame_a, frame_b, *args, **kwargs)

    monkeypatch.setattr(player.videoWidget, "updateFrame", recording_update_frame)

    pos = drag_off_the_capture(player)
    assert player.is_dragging is True
    calls.clear()  # 드래그 중의 그림(B 없음이 정상)은 보지 않음 — 놓은 뒤만

    release(player, pos)

    assert calls, "놓은 뒤 한 번도 그리지 않음 — 놓을 때 이동이 안 돌았음"
    assert calls[-1] == (True, True), f"놓은 뒤 마지막 그림에 B가 없음: {calls}"
    assert all(has_b for _has_a, has_b in calls), f"놓은 뒤 B를 뺀 그림이 있음(표지가 True로 남아 B를 숨김): {calls}"
    assert player.is_dragging is False


def test_sync_audio_on_release_alone_clears_the_drag_flag(wipe_player):
    """sliderReleased의 슬롯(sync_audio_on_release)을 직접 불러도 표지가 풀림 — 신호 배선과 무관한 고침 지점의 고정."""
    player = wipe_player
    player.is_dragging = True

    player.sync_audio_on_release()

    assert player.is_dragging is False


def drag_to_an_uncached_frame(player):
    """메인 슬라이더를 20% 자리에서 눌러 60%로 한 번만 끌고 놓지 않은 채 멈춤; 놓을 자리(QPoint) 반환.

    60%의 장은 캐시에 없어(미적중) 미리보기가 캡처를 그 장으로 옮기고(캡처 = 슬라이더의 장 — 놓을 때 정확한 위치로 옮기는 이동이 안 돎)
    B 동기화는 통째로 건너뛰어 frame_b를 None으로 둠 — 와이프 B가 검게 남는 흐름."""
    slider = player.positionScroll
    y = slider.height() // 2
    QTest.mousePress(slider, Qt.LeftButton, Qt.NoModifier, QPoint(int(slider.width() * 0.2), y))
    QApplication.processEvents()
    assert slider.isSliderDown() is True
    send_drag_move(slider, QPoint(int(slider.width() * 0.6), y))
    capture_index = int(player.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
    assert player.cache_hits == 0  # 전제: 캐시 미적중
    assert abs(capture_index - slider.value()) <= SEEK_THRESHOLD  # 전제: 놓을 때 정확한 위치로 옮기는 이동이 안 돎
    assert player.frame_b is None  # 전제: 미리보기가 B를 비워 둠
    return QPoint(int(slider.width() * 0.6), y)


def test_b_is_resynced_on_release_without_precise_seek(wipe_player, monkeypatch):
    """캐시 미적중 드래그를 놓으면(정확한 위치로 옮기는 이동이 안 돎) B를 A가 보여 주는 장에 맞춰 다시 그림 — 안 맞추면 frame_b가 None인 채 B 칸이 검게 남음.
    A·B가 같은 클립이라 같은 장이면 두 프레임의 밝기가 같음(write_test_video는 i번 장이 (i * 10) % 255 — 이웃 장과 10 차이)."""
    player = wipe_player
    calls = []
    original = player.videoWidget.updateFrame

    def recording_update_frame(frame_a, frame_b=None, *args, **kwargs):
        calls.append((frame_a is not None, frame_b is not None))
        return original(frame_a, frame_b, *args, **kwargs)

    monkeypatch.setattr(player.videoWidget, "updateFrame", recording_update_frame)

    pos = drag_to_an_uncached_frame(player)
    assert player.is_dragging is True
    calls.clear()

    release(player, pos)

    assert calls, "놓은 뒤 한 번도 그리지 않음 — B가 검게 남음"
    assert calls[-1] == (True, True), f"놓은 뒤 마지막 그림에 B가 없음: {calls}"
    assert player.frame_b is not None
    assert player.frame_b.mean() == pytest.approx(player.frame_a.mean(), abs=2)  # 같은 장 (이웃 장이면 10 차이)
    assert player.is_dragging is False


def position(cap):
    return int(cap.get(cv2.CAP_PROP_POS_FRAMES))


def test_narrow_wipe_drag_back_onto_a_cached_frame_keeps_slider_label_and_captures_aligned(wipe_player):
    """와이프 + 캐시 적중 + 캡처와 5장 차이로 놓기(짧은 클립에서 20 → 25 → 20처럼 좁게 왔다갔다 끌기): 정밀 이동이 도는 허용 오차는 와이프면 0.
    5장 안이라고 B만 목표에 맞추면 update_frame의 update_position_info가 캡처(25) 기준으로 슬라이더·Current를 25로 되돌려 그림(20)과 어긋나 튀고,
    A 캡처(25)·B 캡처(20)가 갈려 이어지는 와이프 재생이 5장 어긋남. 정밀 이동은 A 캡처·B·슬라이더·라벨을 함께 20으로 맞춤."""
    player = wipe_player
    bar = player.positionScroll
    bar.setSliderDown(True)
    for value in (20, 25, 20):  # 20·25는 미적중(캐시에 담김), 마지막 20은 적중 — 캡처는 25에 남고 슬라이더·그림만 20
        bar.setSliderPosition(value)
    assert player.cache_hits == 1
    assert position(player.cap_a) - 1 == 25 and bar.value() == 20  # 전제: 캡처와 5장 차이 — 옛 5장 허용 오차면 이동이 안 도는 놓기

    bar.setSliderDown(False)
    QApplication.processEvents()

    assert bar.value() == 20
    assert player.overlaySlider.value() == 20
    assert player.labelFrameCount.text() == "Current: 21"
    assert position(player.cap_a) - 1 == 20
    assert position(player.cap_b) - 1 == 20  # A·B 캡처 정렬 — 이어지는 와이프 재생이 어긋나지 않음
    assert player.frame_b is not None and player.frame_b.mean() == pytest.approx(player.frame_a.mean(), abs=2)


def test_plain_click_release_does_not_reread_or_redraw_b(wipe_player, monkeypatch):
    """평범한 클릭(누름·놓음만): 누를 때 valueChanged → 정밀 이동이 A·B를 목표에 맞췄으므로 놓을 때 B를 다시 읽지도 그리지도 않음(자리가 같으면 건너뜀)."""
    player = wipe_player
    player.cap_b = CountingCapture(player.cap_b)
    draws = []
    original = player.videoWidget.updateFrame

    def recording_update_frame(*args, **kwargs):
        draws.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(player.videoWidget, "updateFrame", recording_update_frame)
    slider = player.positionScroll
    y = slider.height() // 2

    QTest.mousePress(slider, Qt.LeftButton, Qt.NoModifier, QPoint(int(slider.width() * 0.6), y))
    QApplication.processEvents()
    assert position(player.cap_b) - 1 == slider.value()  # 전제: 누를 때 이미 B가 그 자리
    player.cap_b.reset()
    draws.clear()
    QTest.mouseRelease(slider, Qt.LeftButton, Qt.NoModifier, QPoint(int(slider.width() * 0.6), y))
    QApplication.processEvents()

    assert (player.cap_b.reads, player.cap_b.sets) == (0, 0)
    assert draws == []


def test_overlay_slider_release_reads_b_only_once(wipe_player):
    """오버레이 슬라이더 놓기: _overlay_slider_final_seek가 B를 맞춘 뒤 sync_audio_on_release를 또 부르는데, B가 이미 그 자리라 한 번 더 읽지 않음(읽기·set 각 1번)."""
    player = wipe_player
    player.cap_b = CountingCapture(player.cap_b)
    player.overlaySlider.blockSignals(True)
    player.overlaySlider.setValue(30)
    player.overlaySlider.blockSignals(False)

    player.on_overlay_slider_released()
    QApplication.processEvents()

    assert (player.cap_b.reads, player.cap_b.sets) == (1, 1)
    assert position(player.cap_b) - 1 == 30
