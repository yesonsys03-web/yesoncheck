"""다른 영상으로 넘어갈 때 떠나는 영상을 되감지 않음 (2026-11-12).

예전에는 새 영상을 열 때 `_stop_playback_for_open` → `stop_video`가 **떠나는** 캡처를 1번 프레임으로 되감았음(디코드·그리기·소리 위치) —
그 결과는 바로 뒤 `display_first_frame`이 새 캡처에 같은 일을 하며 전부 덮어씀. 남는 것은 비용뿐이었음:
- 떠나는 파일이 그사이 바뀌었으면(같은 이름으로 다시 렌더됨) 그 되감기가 실패해 오류 창이 뜸 — 사용자 보고(1.9.0, Mac 네이티브):
  "VideoToolbox로 영상을 읽다가 도중에 실패해 … 리더가 0번 프레임 앞에서 끝났습니다" (어차피 닫을 영상).
- ffmpeg 파이프(Windows의 4K ProRes)는 그 되감기에 ffmpeg를 한 번 더 띄움(길면 약 0.5초).
선택 재생(Play Selected)은 전부터 되감지 않고 넘어갔음 — 같은 방식.

여기서는 캡처를 감싸 read·set 횟수를 셈(tests/test_drag_release_seek.CountingCapture — 시간이 아니라 '건드렸는가').
Stop 단추는 그대로 처음으로 되감음.
"""

import cv2
import pytest

from tests.conftest import write_test_video
from tests.test_drag_release_seek import CountingCapture
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


@pytest.fixture
def clips(tmp_path):
    return [write_test_video(str(tmp_path / f"clip{n}.mp4"), frames=60) for n in (1, 2, 3)]


def watched(player, side):
    """그 쪽 캡처를 세는 것으로 감싸 돌려줌."""
    counting = CountingCapture(player.cap_a if side == "A" else player.cap_b)
    if side == "A":
        player.cap_a = counting
    else:
        player.cap_b = counting
    return counting


def position(cap):
    return int(cap.get(cv2.CAP_PROP_POS_FRAMES))


def test_switching_to_another_file_does_not_touch_the_leaving_capture(player, clips):
    assert player.open_file("A", clips[0]) is True
    leaving = watched(player, "A")
    player.seek_to_frame(30)
    leaving.reset()

    assert player.open_file("A", clips[1]) is True

    assert (leaving.reads, leaving.sets) == (0, 0)
    assert player.filename_a == clips[1]
    assert position(player.cap_a) == 1  # 새 영상은 1번 프레임을 읽은 자리
    assert player.positionScroll.value() == 0
    assert player.labelFrameCount.text() == "Current: 1"


def test_switching_while_playing_stops_playback_without_touching_the_leaving_capture(player, clips):
    assert player.open_file("A", clips[0]) is True
    player.play_video()
    assert player.timer.isActive()
    leaving = watched(player, "A")

    assert player.open_file("A", clips[1]) is True

    assert (leaving.reads, leaving.sets) == (0, 0)
    assert not player.timer.isActive()
    assert player.playPauseButton.text() == "Play"


def test_opening_b_reads_a_once_for_the_first_frame(player, clips):
    """B를 열 때 A는 떠나지 않음 — 첫 화면(display_first_frame)이 A를 1번으로 맞추는 한 번만 읽음 (예전에는 멈추기가 한 번 더)."""
    assert player.open_file("A", clips[0]) is True
    a = watched(player, "A")
    player.seek_to_frame(1)
    one_seek = (a.reads, a.sets)  # 1번 프레임으로 한 번 맞추는 데 드는 횟수
    player.seek_to_frame(30)
    a.reset()

    assert player.open_file("B", clips[1]) is True

    assert (a.reads, a.sets) == one_seek
    assert position(a) == 1


def test_new_a_still_brings_wipe_b_back_to_the_first_frame(player, clips):
    """와이프의 B는 예전처럼 새 A와 함께 1번 프레임으로 — 새 영상의 첫 화면이 맞춤(떠나는 영상의 되감기에 기대지 않음)."""
    assert player.open_file("A", clips[0]) is True
    assert player.open_file("B", clips[1]) is True
    player.wipeCheckBox.setChecked(True)
    player.seek_to_frame(30)
    assert position(player.cap_b) == 30

    assert player.open_file("A", clips[2]) is True

    assert (position(player.cap_a), position(player.cap_b)) == (1, 1)


def test_stop_button_still_rewinds_to_the_first_frame(player, clips):
    assert player.open_file("A", clips[0]) is True
    player.seek_to_frame(30)
    assert position(player.cap_a) == 30

    player.stop_video()

    assert position(player.cap_a) == 1
    assert player.labelFrameCount.text() == "Current: 1"
    assert player.playPauseButton.text() == "Play"
