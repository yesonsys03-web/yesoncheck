"""슬라이더를 놓을 때의 멈춤 회귀 시험 (사용자 보고 2026-11-05 — Windows·Intel·Apple Silicon, 1.6.1에서도 같음).

증상: 긴 영상(25분 h264, 36781장)에서 핸들을 좌우로 빠르게 끈 뒤 놓으면 앱이 분 단위로 멈췄다가 풀림 — 짧은 영상에서는 보이지 않음.
원인: 드래그가 프레임 캐시에 맞으면(같은 슬라이더 값으로 돌아옴 — 마우스는 픽셀 단위라 흔함) 그림만 바꾸고 캡처는 옮기지 않으므로(그래서 즉시 반응함)
캡처가 먼 곳에 남는다. 놓을 때 sync_audio_on_release가 그 차이를 보고 0번부터 목표까지 한 장씩 읽었다 — 멈춤이 목표 번호에 비례(실측 30000번 119초).
직접 이동은 같은 파일 전체를 순차로 읽은 프레임과 같은 곳에 닿음을 잼(직접 이동 37곳·끝 근처 80곳 전부 일치, 실측 30000번 0.08초).

드래그 쪽은 그대로여야 함(사용자 요구: 드래그·스크럽은 지금처럼 즉시 반응) — 캐시에 맞는 드래그는 캡처를 건드리지 않고, 캡처가 제자리면 놓을 때 아무것도 읽지 않음.
시험 영상은 프레임마다 밝기가 달라(write_test_video) 어느 프레임이 보이는지 밝기로 가른다. 드래그 신호는 setSliderDown·setSliderPosition — 진짜 마우스 드래그가 거치는 길과 같음.
"""

import time

import cv2
import numpy as np
import pytest
from PyQt5.QtCore import QDateTime
from PyQt5.QtWidgets import QApplication

from tests.conftest import write_test_video
from tests.test_pipe_player import screen_image
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

FRAMES = 120
FAR, NEAR = 100, 20  # 밝기 (i * 10) % 255 가 서로 멀고(235, 200) 끝 프레임 특별 처리(최대값 - 1 이상)에 닿지 않는 번호
NEAR_END = FRAMES - 3  # _precise_seek가 _seek_conservative로 보내는 끝 근처 번호 (밝기 150)
CONSERVATIVE_READS = 11  # 끝 근처는 목표 10장 앞부터 읽어 목표까지 — 뒤로 가는 갈래가 쓰던 폭
NEIGHBOUR_MARGIN = 4.9  # 이웃 프레임과 밝기 10 차이라 5 미만이면 가름 — 코덱·러너의 밝기 쏠림(이 Mac −2.7)을 견딤


class CountingCapture:
    """cv2 캡처를 감싸 read·set 횟수를 셈 — 시간이 아니라 '몇 장을 읽었나'로 멈춤을 잼 (짧은 시험 영상에서도 결정적)."""

    def __init__(self, cap):
        self._cap = cap
        self.reads = 0
        self.sets = 0

    def read(self):
        self.reads += 1
        return self._cap.read()

    def grab(self):
        self.reads += 1  # 디코드는 read와 같음 — grab으로 처음부터 넘기는 회귀도 잡음
        return self._cap.grab()

    def set(self, prop, value):
        self.sets += 1
        return self._cap.set(prop, value)

    def reset(self):
        self.reads = self.sets = 0

    def __getattr__(self, name):
        return getattr(self._cap, name)


@pytest.fixture
def rig(new_player, dialogs, tmp_path):  # noqa: F811
    player = new_player(make_config(str(tmp_path), {}))
    path = write_test_video(str(tmp_path / "clip.mp4"), frames=FRAMES)
    assert player.open_file("A", path) is True
    player.cap_a = CountingCapture(player.cap_a)
    player.drag_update_interval = 0  # 시험은 움직임을 즉시 잇달아 보냄 — 30ms 빈도 제한이 걸러 내지 않게
    return player, player.cap_a, player.positionScroll


def drag_through(bar, *values):
    bar.setSliderDown(True)
    for value in values:
        bar.setSliderPosition(value)


def position(cap):
    return int(cap.get(cv2.CAP_PROP_POS_FRAMES))


def brightness(index, frames=None):
    """frames를 주면 거꾸로 번호(write_reversed_video)."""
    return ((frames - 1 - index if frames else index) * 10) % 255


def shows_frame(player, index):
    return player.frame_a.mean() == pytest.approx(brightness(index), abs=NEIGHBOUR_MARGIN)


def blank_picture(player):
    """캐시에 맞은 드래그는 이미 같은 프레임을 보이고 있어, 지우지 않으면 놓는 일이 그림을 가져와 그렸는지 가릴 수 없음."""
    player.frame_a = np.zeros_like(player.frame_a)
    player.videoWidget.updateFrame(player.frame_a, None)


def assert_settled(player, cap, index):
    """놓은 뒤 플레이어 전체가 index번에 맞음 — 캡처, 든 프레임, 화면, 라벨, 두 슬라이더."""
    assert position(cap) == index + 1
    assert shows_frame(player, index)
    assert screen_image(player).mean() == pytest.approx(brightness(index), abs=NEIGHBOUR_MARGIN)
    assert player.labelFrameCount.text() == f"Current: {index + 1}"
    assert player.positionScroll.value() == index
    assert player.overlaySlider.value() == index


def open_b_in_wipe(player, tmp_path):
    assert player.open_file("B", write_reversed_video(str(tmp_path / "b.mp4"))) is True
    player.cap_b = CountingCapture(player.cap_b)
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)
    return player.cap_b


def write_reversed_video(path, frames=FRAMES, size=(320, 240)):
    """B용 — write_test_video의 거꾸로라 A와 밝기가 달라 화면에서 두 쪽을 가름."""
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 24, size)
    assert writer.isOpened(), f"VideoWriter를 열 수 없습니다: {path}"
    for i in range(frames):
        writer.write(np.full((size[1], size[0], 3), brightness(i, frames), np.uint8))
    writer.release()
    return path


def test_release_on_a_cached_frame_does_not_decode_from_the_start(rig):
    """놓을 때 0번부터 순차로 읽으면(옛 sync_audio_on_release → _seek_sequential) read가 FAR + 1번 — 긴 영상의 멈춤 그 자체. 직접 이동이면 1번."""
    player, cap, bar = rig
    drag_through(bar, FAR, NEAR, FAR)
    assert position(cap) == NEAR + 1 and player.cache_hits == 1  # 전제: 마지막 움직임이 캐시에 맞아 캡처가 NEAR에 남음
    blank_picture(player)
    cap.reset()

    bar.setSliderDown(False)

    assert cap.reads == 1
    assert_settled(player, cap, FAR)  # 캡처가 보이는 프레임으로 돌아옴 — 뒤따르는 화살표·재생의 기준


def test_arrow_keys_continue_from_the_released_frame(rig):
    """사용자 조작 그대로: 끌고 놓은 뒤 좌우 화살표 왕복 — 놓은 프레임 바로 옆으로 움직임. 놓을 때 캡처를 옮기지 않으면 NEAR 근처로 튀어 실패."""
    player, cap, bar = rig
    drag_through(bar, FAR, NEAR, FAR)
    bar.setSliderDown(False)

    player.next_frame()
    assert position(cap) == FAR + 2 and shows_frame(player, FAR + 1)
    player.prev_frame()
    assert position(cap) == FAR + 1 and shows_frame(player, FAR)


def test_drag_back_onto_a_cached_frame_touches_no_capture(rig):
    """사용자 요구 '드래그·스크럽은 즉시 반응'의 고정: 캐시에 맞는 드래그는 읽지도 옮기지도 않음. 드래그 중 캡처를 맞추게 바꾸면 실패."""
    player, cap, bar = rig
    drag_through(bar, FAR, NEAR)
    cap.reset()

    bar.setSliderPosition(FAR)

    assert (cap.reads, cap.sets) == (0, 0)
    assert shows_frame(player, FAR)


def test_release_with_the_capture_in_place_reads_nothing(rig):
    """캡처가 이미 제자리면 놓는 일에 디코드 비용이 없음. 놓을 때마다 무조건 다시 이동하게 바꾸면 실패."""
    _player, cap, bar = rig
    drag_through(bar, NEAR, FAR)
    assert position(cap) == FAR + 1
    cap.reset()

    bar.setSliderDown(False)

    assert (cap.reads, cap.sets) == (0, 0)


@pytest.mark.parametrize("target", [NEAR_END, FRAMES - 4, FRAMES - 5], ids=["conservative", "direct_near_end_4", "direct_near_end_5"])
def test_release_just_before_the_end_does_not_read_every_frame_between(rig, target):
    """끝 근처에서 놓을 때: _seek_conservative(끝 3장)·_seek_direct의 끝 갈래(끝 5장)가 현재 위치부터 목표까지 한 장씩 읽으면 read가 거리만큼(실파일 30648장 92초). 목표 바로 앞에서 시작해야 함."""
    player, cap, bar = rig
    drag_through(bar, target, NEAR, target)
    assert position(cap) == NEAR + 1 and player.cache_hits == 1
    blank_picture(player)
    cap.reset()

    bar.setSliderDown(False)

    assert cap.reads <= CONSERVATIVE_READS
    assert_settled(player, cap, target)


def test_rate_limited_move_near_the_end_does_not_read_every_frame_between(rig):
    """드래그 중 빈도 제한에 걸린 움직임은 valueChanged → _precise_seek로 감 — 놓지 않아도 끝 근처면 같은 길. 거리만큼 읽으면 드래그 중에 멈춤."""
    player, cap, bar = rig
    player.seek_to_frame(NEAR + 1)
    bar.setSliderDown(True)
    player.drag_update_interval = 10 ** 9
    player.last_drag_update = QDateTime.currentMSecsSinceEpoch()  # on_slider_moved가 빈도 제한으로 바로 돌아감
    cap.reset()

    bar.setSliderPosition(NEAR_END)

    assert cap.reads <= CONSERVATIVE_READS
    assert position(cap) == NEAR_END + 1
    assert shows_frame(player, NEAR_END)


def test_conservative_seek_from_close_by_just_reads_forward(rig):
    """목표가 10장 안이면 예전처럼 옮기지 않고 앞으로 읽음(옮기면 키프레임부터 다시 디코드). 항상 set하게 바꾸면 실패."""
    player, cap, _bar = rig
    player.seek_to_frame(NEAR_END - 4)
    assert position(cap) == NEAR_END - 4
    cap.reset()

    assert player._seek_conservative(NEAR_END, FRAMES) is True

    assert (cap.sets, cap.reads) == (0, 5)
    assert position(cap) == NEAR_END + 1
    assert shows_frame(player, NEAR_END)


@pytest.mark.parametrize("target", [FAR, NEAR_END], ids=["mid_file", "near_end"])
def test_release_in_wipe_brings_b_to_the_released_frame(rig, tmp_path, target):
    """와이프 중에 놓으면 B도 같은 번호로 — 예전 순차 읽기가 하던 일. 끝 근처 길(_seek_conservative)이 B를 맞추지 않으면 B 쪽이 검게 남고 재생이 어긋난 B에서 이어짐."""
    player, _cap, bar = rig
    cap_b = open_b_in_wipe(player, tmp_path)
    drag_through(bar, target, NEAR, target)
    assert player.cache_hits == 1

    bar.setSliderDown(False)

    assert position(cap_b) == target + 1
    assert cap_b.reads <= 2 * CONSERVATIVE_READS  # 앞 움직임(캐시에 안 맞음)은 B를 읽지 않음 — 놓을 때 읽은 것뿐
    assert player.frame_b is not None and player.frame_b.mean() == pytest.approx(brightness(target, FRAMES), abs=NEIGHBOUR_MARGIN)
    screen = screen_image(player)
    wipe_x = int(screen.shape[1] * player.videoWidget.wipe_position_x)
    assert screen[:, :wipe_x].mean() == pytest.approx(brightness(target), abs=NEIGHBOUR_MARGIN)
    assert screen[:, wipe_x:].mean() == pytest.approx(brightness(target, FRAMES), abs=NEIGHBOUR_MARGIN)


def test_rate_limited_move_near_the_end_brings_b_along(rig, tmp_path):
    """드래그 중 끝 근처 길도 와이프면 B를 맞추되 A와 같은 한도로 — 드래그 즉시 반응이 B 때문에 느려지지 않게."""
    player, _cap, bar = rig
    cap_b = open_b_in_wipe(player, tmp_path)
    player.seek_to_frame(NEAR + 1)
    bar.setSliderDown(True)
    player.drag_update_interval = 10 ** 9
    player.last_drag_update = QDateTime.currentMSecsSinceEpoch()
    cap_b.reset()

    bar.setSliderPosition(NEAR_END)

    assert cap_b.reads <= CONSERVATIVE_READS
    assert position(cap_b) == NEAR_END + 1
    assert player.frame_b.mean() == pytest.approx(brightness(NEAR_END, FRAMES), abs=NEIGHBOUR_MARGIN)


def test_conservative_seek_from_close_by_reads_forward_on_b_too(rig, tmp_path):
    """B도 가까우면 옮기지 않음 — 옮기면 키프레임부터 다시 디코드하고 끝 근처 드래그마다 11장을 읽음."""
    player, cap, _bar = rig
    cap_b = open_b_in_wipe(player, tmp_path)
    player.seek_to_frame(NEAR_END - 4)
    assert position(cap_b) == NEAR_END - 4
    cap.reset()
    cap_b.reset()

    assert player._seek_conservative(NEAR_END, FRAMES) is True

    assert (cap_b.sets, cap_b.reads) == (0, 5)
    assert position(cap_b) == NEAR_END + 1


def test_release_moves_the_sound_with_the_picture(rig):
    """소리 위치는 놓은 뒤의 캡처 위치에서 계산함 — 캡처를 옮기지 않거나 소리 맞춤을 빼면 NEAR 쪽 소리가 남음.
    값이 올 때까지 기다림: 정해진 시간만 돌면 가상 머신이 대기 중 잠을 길게 자 5ms 타이머를 놓침(Mac CI에서 빈 목록). 파일을 열 때 예약된 0ms도 함께 올 수 있어 순서는 보지 않음(Windows CI에서 [4137, 0])."""
    player, _cap, bar = rig
    drag_through(bar, FAR, NEAR, FAR)
    heard = []
    player.set_media_position = heard.append

    bar.setSliderDown(False)

    far_ms, near_ms = FAR / 24 * 1000, NEAR / 24 * 1000
    deadline = time.perf_counter() + 3
    while not any(abs(ms - far_ms) < abs(ms - near_ms) for ms in heard) and time.perf_counter() < deadline:
        QApplication.processEvents()
        time.sleep(0.001)
    assert any(abs(ms - far_ms) < abs(ms - near_ms) for ms in heard), heard


def test_conservative_seek_does_not_swallow_errors(rig, monkeypatch):
    """놓는 길이 이 함수를 지나므로 안에서 난 오류를 말없이 False로 삼키면 그림만 안 바뀌고 원인이 사라짐(예전 순차 읽기는 올렸음) — 그대로 올려 예외 창으로."""
    player, _cap, _bar = rig

    def broken(*_args):
        raise RuntimeError("그리다 실패")

    monkeypatch.setattr(player, "_update_ui_after_seek", broken)

    with pytest.raises(RuntimeError, match="그리다 실패"):
        player._seek_conservative(NEAR_END, FRAMES)
