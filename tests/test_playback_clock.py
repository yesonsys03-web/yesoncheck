"""재생 틱 시계 (사용자 보고 2026-11-05: 24fps 영상이 `실제 25`로 재생 — int(1000/fps) = 41ms를 Qt 기본 타이머가 40ms로 돌려 4% 빨랐음).

정수 ms 타이머로 소수 간격을 내려면 간격을 고정하지 않고 틱마다 다음 프레임 시각까지 남은 시간을 계산해야 오차가 쌓이지 않음. 시계는 Qt 없이 시각만 받음."""

import pytest

from yesoncheck.playback_clock import BEHIND_LIMIT_FRAMES, PlaybackClock


def simulate(fps, ticks, work_s=0.0):
    """타이머가 약속한 ms 뒤에 정확히 울리고 틱마다 work_s가 걸린다고 치고, 마지막 틱의 시각을 돌려줌."""
    clock = PlaybackClock(fps, now=100.0)
    now = 100.0 + clock.first_delay_ms() / 1000
    for _ in range(ticks - 1):
        now += work_s
        now += clock.next_delay_ms(now) / 1000
    return now - 100.0


@pytest.mark.parametrize("fps", [24000 / 1001, 24, 25, 30000 / 1001, 30, 50, 60000 / 1001, 60])
def test_long_playback_stays_on_the_clock(fps):
    """25분(36000장)을 넘게 돌아도 원래 길이에서 벗어나지 않음. 간격을 고정(int·round)하면 소수만큼 쌓여 이 Mac에서 4% 빨랐음."""
    ticks = 40000
    assert simulate(fps, ticks) == pytest.approx(ticks / fps, abs=0.002)


def test_24fps_alternates_41_and_42_ms():
    clock = PlaybackClock(24, now=0.0)
    now = clock.first_delay_ms() / 1000
    delays = [clock.first_delay_ms()]
    for _ in range(11):
        delay = clock.next_delay_ms(now)
        delays.append(delay)
        now += delay / 1000
    assert set(delays) == {41, 42}
    assert sum(delays) == pytest.approx(12 * 1000 / 24, abs=1)


def test_frame_work_comes_out_of_the_wait():
    """틱에 30ms가 걸렸으면 나머지만 기다림 — 처리 시간이 간격에 더해지면 느려짐."""
    assert simulate(24, 1000, work_s=0.030) == pytest.approx(1000 / 24, abs=0.002)


def test_late_tick_fires_as_soon_as_possible_without_skipping():
    """시각을 넘겼으면 바로 다음 틱(0이면 이벤트가 돌 틈이 없으니 1ms). 시계는 프레임을 세기만 하고 건너뛰게 하지 않음."""
    clock = PlaybackClock(24, now=0.0)
    assert clock.next_delay_ms(0.100) == 1


def test_tiny_lag_stays_on_the_schedule():
    """프레임 2장 안의 흔들림은 시각표를 유지해 따라잡음 — 소리와 벌어지지 않게. 한 장 늦으면 틱 하나를 바로 보내고 원래 시각표로 돌아감."""
    clock = PlaybackClock(24, now=0.0)
    now = 2 / 24 + 1 / 24
    delays = []
    for _ in range(3):
        delay = clock.next_delay_ms(now)
        delays.append(delay)
        now += delay / 1000
    assert delays[:2] == [1, 1]
    assert delays[2] == pytest.approx(1000 / 24 - 2, abs=1)


@pytest.mark.parametrize("stall_s", [0.1, 0.2, 0.3, 2.0])
@pytest.mark.parametrize("fps", [24, 60])
def test_stall_does_not_replay_missed_frames_at_full_speed(fps, stall_s):
    """멈춘 뒤(탐색·창 끌기·NAS 끊김) 밀린 프레임을 1ms 간격으로 몰아 보이면 화면이 순간 빨라짐 — 예전에는 없던 일. 틱 하나만 바로, 그다음부터 원래 간격."""
    clock = PlaybackClock(fps, now=0.0)
    now = 2 / fps + stall_s  # 첫 틱을 마친 때: 다음 틱 시각을 stall_s 넘김
    delays = []
    for _ in range(6):
        delay = clock.next_delay_ms(now)
        delays.append(delay)
        now += delay / 1000
    assert delays[0] == 1
    assert all(d >= int(1000 / fps) for d in delays[1:])


def test_machine_that_cannot_keep_up_gets_no_extra_wait():
    """처리가 늘 늦는 기계(4K 와이프 등): 시각표를 옮길 때 한 프레임을 쉬면 안 그래도 느린 재생이 더 느려짐 — 언제나 바로 다음 틱."""
    clock = PlaybackClock(24, now=0.0)
    now = 0.0
    delays = []
    for _ in range(200):
        now += 0.060
        delay = clock.next_delay_ms(now)
        delays.append(delay)
        now += delay / 1000
    assert set(delays[3:]) == {1}  # 처음 몇 틱은 시각표보다 앞서 시작함


@pytest.mark.parametrize("fps", [0, -24, float("nan")])
def test_bad_fps_raises(fps):
    with pytest.raises(ValueError):
        PlaybackClock(fps, now=0.0)
