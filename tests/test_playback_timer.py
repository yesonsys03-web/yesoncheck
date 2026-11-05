"""재생 타이머가 시계를 따르는가 — 진짜 VideoPlayer와 진짜 QTimer (사용자 보고 2026-11-05: 24fps가 `실제 25`). 프레임 번호·장 수는 타이머와 상관없어야 함."""

import time

import cv2
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

FRAMES = 96
FPS = 24


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    player = new_player(make_config(str(tmp_path), {}))
    assert player.open_file("A", write_test_video(str(tmp_path / "clip.mp4"), frames=FRAMES)) is True
    QTest.qWait(30)
    return player


def play_to_end(player, limit_s=30):
    start = time.perf_counter()
    while player.timer.isActive() and time.perf_counter() - start < limit_s:
        QApplication.processEvents()
        time.sleep(0.0005)
    assert not player.timer.isActive(), "재생이 끝나지 않음"


def test_timer_is_precise(player):
    """기본(Coarse) 타이머는 5% 안에서 간격을 바꿈 — 41ms가 40ms로 돌았음."""
    assert player.timer.timerType() == Qt.PreciseTimer


def test_playback_is_not_faster_than_the_video(player):
    """시간을 재는 유일한 시험: 시각표를 따르면 부하가 있어도 빨라지지 않음 (느려지는 것은 기계 탓이라 재지 않음). int(1000/fps) + 기본 타이머면 3.80초로 실패."""
    start = time.perf_counter()
    player.play_video()
    play_to_end(player)
    elapsed = time.perf_counter() - start
    assert elapsed >= FRAMES / FPS - 0.02  # 끝은 FRAMES번째 틱에서 앎 (정밀 타이머 41ms 고정도 여기서 걸림)


def test_every_frame_is_shown_in_order(player, monkeypatch):
    """사용자 질문 '타이머를 바꿔도 프레임 카운트는 괜찮나': 시계는 틱 시각만 정함 — 모든 프레임을 차례로 읽고 건너뛰지 않음."""
    player.seek_to_frame(1)  # 0번을 보임 — 재생은 그다음부터
    shown = []
    real_update = player.update_frame

    def update_frame(*args, **kwargs):
        shown.append(int(player.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1)
        return real_update(*args, **kwargs)

    monkeypatch.setattr(player, "update_frame", update_frame)
    player.play_video()
    play_to_end(player)
    assert shown == list(range(1, FRAMES)) + [0]  # 끝나면 처음으로 돌아가 0번을 그림 (stop_video)


def test_late_ticks_do_not_skip_frames(player, monkeypatch):
    """틱이 시각표보다 크게 늦어도(무거운 프레임) 장 수는 그대로."""
    player.seek_to_frame(FRAMES - 21)  # FRAMES - 22번을 보임
    shown = []
    real_update = player.update_frame

    def slow_update(*args, **kwargs):
        shown.append(int(player.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1)
        time.sleep(0.05)
        return real_update(*args, **kwargs)

    monkeypatch.setattr(player, "update_frame", slow_update)
    player.play_video()
    play_to_end(player)
    assert shown == list(range(FRAMES - 21, FRAMES)) + [0]


def test_every_play_starts_a_new_schedule(player):
    """멈춘 동안의 시간을 밀린 것으로 치면 안 됨 — Play마다 그 시각부터 새 시각표. 옛 시각표를 이으면 다음 틱이 바로(1ms)."""
    player.play_video()
    QTest.qWait(100)
    player.pause_video()
    QTest.qWait(50)
    before_play = time.perf_counter()
    player.play_video()
    player.timer.stop()  # 저절로 울리지 않게 — 시각표만 봄
    assert player._playback_clock.next_delay_ms(before_play) >= 2 * 1000 / FPS - 1


def test_timer_stays_active_during_a_tick(player, monkeypatch):
    """재생 중인지를 timer.isActive()로 보는 코드가 틱 안에도 있음 — 다음 시각을 거는 동안 꺼지면 안 됨."""
    seen = []
    real_update = player.update_frame

    def update_frame(*args, **kwargs):
        seen.append(player.timer.isActive())
        return real_update(*args, **kwargs)

    monkeypatch.setattr(player, "update_frame", update_frame)
    player.play_video()
    QTest.qWait(150)
    active_after = player.timer.isActive()
    player.pause_video()
    assert seen and all(seen) and active_after


def test_tick_that_stops_playback_does_not_restart_the_timer(player):
    """끝에 닿아 멈춘 틱이 다음 시각을 걸어 타이머를 되살리면 안 됨 (play_to_end가 끝나지 않음)."""
    player.seek_to_frame(FRAMES - 2)
    player.play_video()
    play_to_end(player)
    QTest.qWait(100)
    assert not player.timer.isActive()


def test_loop_restart_uses_its_own_schedule(player):
    """반복 재생: 끝에 닿은 틱 안에서 play_video가 새 시각표로 켬 — 옛 시각표가 다음 시각을 덮어쓰면 그 긴 시각(끝난 뒤의 번호)이나 잘못된 간격이 걸림."""
    player.loopEnabled = True
    player.seek_to_frame(FRAMES - 3)
    player.play_video()
    first = player._playback_clock
    start = time.perf_counter()
    while player._playback_clock is first and time.perf_counter() - start < 10:
        QApplication.processEvents()
        time.sleep(0.001)
    assert player._playback_clock is not first, "반복 재생이 새 시각표를 만들지 않음"
    assert player.timer.isActive()
    assert player.timer.interval() == player._playback_clock.first_delay_ms()
    at = int(player.cap_a.get(cv2.CAP_PROP_POS_FRAMES))
    QTest.qWait(300)
    player.loopEnabled = False
    player.pause_video()
    assert int(player.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) > at


def test_tick_arms_the_timer_with_the_clocks_delay(player):
    """틱마다 시계가 준 시간을 타이머에 걺 — 첫 간격을 그대로 두면(42ms 고정) 소수만큼 느려짐. 시간을 재는 시험은 '빠르지 않음'만 보므로 여기서 고정."""
    player.play_video()
    player._playback_clock.next_delay_ms = lambda now: 7
    player.next_frame_playback()
    assert player.timer.interval() == 7
    player.pause_video()


def test_timer_started_without_play_is_left_alone(player):
    """시험·다른 길이 play_video 없이 켠 타이머는 시계가 없음 — 틱이 간격을 바꾸지 않음."""
    player.timer.start(600000)
    player.next_frame_playback()
    assert player.timer.interval() == 600000
    player.timer.stop()
