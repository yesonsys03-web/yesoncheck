"""재생 FPS 라벨(`labelPlaybackFPS`): 영상의 원래 fps 옆에 **실제로 그린 fps**를 함께 — 리얼타임 재생인지 보려고(4K).

예전에는 `update_playback_fps`가 1초마다 원래 fps(`cap_a.get(CAP_PROP_FPS)`)만 다시 써서 느리게 돌아도 24로 보였고, `update_frame`이
재생 중에 올리는 `playback_fps_counter`는 읽는 곳이 없었음. 이제 재생 틱(`next_frame_playback`)이 **진행한** 프레임을 세고(그리기를 건너뛰는
OCR 검토 창·탐색 그리기와 무관) 틱마다 그 수를 걸린 시간으로 나눠 `재생: 24 FPS · 실제 23.8`. 재생 중이 아니면 원래 fps만, 재생을 시작한 뒤
첫 틱(지난 틱과 이번 틱 사이에 시작)은 부분 구간이라 실제를 적지 않음(검토에서 잡은 '첫 값이 반으로' 문제).
"""

from types import SimpleNamespace

import cv2
import pytest

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def playing(player, monkeypatch):
    monkeypatch.setattr(player.timer, "isActive", lambda: True)


def test_no_video_shows_zero(player):
    player.update_playback_fps(now=100.0)
    assert player.labelPlaybackFPS.text() == "재생: 0 FPS"
    assert player.playback_fps_measured is None


def test_open_but_not_playing_shows_nominal_only(player, tmp_path):
    player.open_file("A", write_test_video(str(tmp_path / "a.mov")))
    player.playback_fps_counter = 7  # 탐색으로 그린 프레임이 있어도 실제 fps는 재생 중에만
    player.update_playback_fps(now=100.0)
    assert player.labelPlaybackFPS.text() == "재생: 24 FPS"
    assert player.playback_fps_measured is None
    assert player.playback_fps_counter == 0  # 틱마다 0으로


def test_playing_shows_measured_fps_from_frames_drawn(player, tmp_path, monkeypatch):
    player.open_file("A", write_test_video(str(tmp_path / "a.mov")))
    playing(player, monkeypatch)
    player.update_playback_fps(now=100.0)  # 기준 시각
    player.playback_fps_counter = 12
    player.update_playback_fps(now=100.5)  # 0.5초에 12장 → 24.0
    assert player.labelPlaybackFPS.text() == "재생: 24 FPS · 실제 24.0"
    assert player.playback_fps_measured == pytest.approx(24.0)
    player.playback_fps_counter = 19
    player.update_playback_fps(now=101.5)  # 1초에 19장 → 리얼타임 아님
    assert player.labelPlaybackFPS.text() == "재생: 24 FPS · 실제 19.0"
    assert player.playback_fps_measured == pytest.approx(19.0)


def test_fractional_nominal_fps_keeps_three_decimals(player, monkeypatch):
    player.cap_a = SimpleNamespace(get=lambda prop: 23.976 if prop == cv2.CAP_PROP_FPS else 0.0)
    playing(player, monkeypatch)
    player.update_playback_fps(now=10.0)
    player.playback_fps_counter = 24
    player.update_playback_fps(now=11.0)
    assert player.labelPlaybackFPS.text() == "재생: 23.976 FPS · 실제 24.0"


def test_frames_advanced_by_playback_ticks_are_counted(player, tmp_path, monkeypatch):
    player.open_file("A", write_test_video(str(tmp_path / "a.mov")))
    playing(player, monkeypatch)
    player.playback_fps_counter = 0
    player.next_frame_playback()
    player.next_frame_playback()
    assert player.playback_fps_counter == 2


def test_counting_does_not_depend_on_drawing(player, tmp_path, monkeypatch):
    """OCR 검토 창이 열려 있으면 update_frame이 홀수 틱의 그리기를 건너뜀 — 그래도 진행한 프레임은 다 셈(검토에서 잡은 '반으로 보임')."""
    player.open_file("A", write_test_video(str(tmp_path / "a.mov")))
    playing(player, monkeypatch)
    monkeypatch.setattr(player, "update_frame", lambda *a, **k: None)
    player.playback_fps_counter = 0
    player.next_frame_playback()
    player.next_frame_playback()
    assert player.playback_fps_counter == 2


def test_seeks_during_playback_are_not_counted(player, tmp_path, monkeypatch):
    player.open_file("A", write_test_video(str(tmp_path / "a.mov")))
    playing(player, monkeypatch)
    player.playback_fps_counter = 0
    player.seek_to_frame(5)
    player.update_frame()
    assert player.playback_fps_counter == 0


def test_first_tick_after_play_shows_nominal_only(player, tmp_path, monkeypatch):
    """재생을 시작한 뒤 첫 틱은 지난 틱부터의 부분 구간이라 실제를 적지 않음 — 다음 틱부터."""
    player.open_file("A", write_test_video(str(tmp_path / "a.mov")))
    player.update_playback_fps(now=10.0)  # 멈춘 채
    playing(player, monkeypatch)  # 10.9에 재생 시작했다고 치고
    player.playback_fps_counter = 2
    player.update_playback_fps(now=11.0)
    assert player.labelPlaybackFPS.text() == "재생: 24 FPS" and player.playback_fps_measured is None
    player.playback_fps_counter = 24
    player.update_playback_fps(now=12.0)
    assert player.labelPlaybackFPS.text() == "재생: 24 FPS · 실제 24.0"


def test_dead_capture_shows_zero_and_no_measured(player, monkeypatch):
    player.cap_a = SimpleNamespace(get=lambda prop: 0.0)  # 죽은 파이프 캡처의 겉모습
    playing(player, monkeypatch)
    player.update_playback_fps(now=1.0)
    player.playback_fps_counter = 10
    player.update_playback_fps(now=2.0)
    assert player.labelPlaybackFPS.text() == "재생: 0 FPS" and player.playback_fps_measured is None


def test_nan_fps_does_not_raise(player, monkeypatch):
    player.cap_a = SimpleNamespace(get=lambda prop: float("nan"))
    player.update_playback_fps(now=1.0)
    assert player.labelPlaybackFPS.text() == "재생: 0 FPS"


def test_label_shows_the_whole_measured_text_in_a_roomy_window(player, qapp):
    """넉넉한 창에서 '재생: 23.976 FPS · 실제 23.9'가 …로 잘리지 않고 다 보임 (keep_text·fit_text를 긴 글로 넓힌 효과)."""
    from PyQt5.QtCore import QSize

    text = "재생: 23.976 FPS · 실제 23.9"
    player.labelPlaybackFPS.setText(text)
    player.resize(player.sizeHint().expandedTo(QSize(1400, 800)))
    player.show()
    qapp.processEvents()
    assert player.labelPlaybackFPS.displayed_text() == text
