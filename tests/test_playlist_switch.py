"""선택 재생의 파일 전환 (사용자 보고 2026-11-06 — Windows 4K, 파일 하나는 딜레이 없이 반복하지만 여러 파일 재생은 넘어갈 때 딜레이).

① 앞 파일보다 짧은 파일을 열면 슬라이더 최대값이 줄며 Qt가 값을 새 끝으로 끌어내림 → valueChanged가 사용자가 끈 것처럼 새 파일의
마지막 프레임으로 탐색했다가(_precise_seek → _seek_to_last_frame) 처음으로 되돌아옴 — 파이프 4K에서 ffmpeg 재시작 두 번. 고침: 최대값을
바꾸는 동안 신호를 막음(다른 곳의 setValue와 같은 방법). ② 전환마다 기록 한 줄 `[측정] 전환 <초>초 (열기 <초>초) — <앞> → <다음>`.
진짜 VideoPlayer·QTimer·cv2 시험 영상.
"""

import re
import time

import pytest
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck.sidebar_playlist import switch_line


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def wait_until(predicate, limit_s=30):
    start = time.perf_counter()
    while not predicate() and time.perf_counter() - start < limit_s:
        QApplication.processEvents()
        time.sleep(0.0005)
    assert predicate(), "기다린 일이 일어나지 않음"


# ---------------------------------------------------------------- ① 짧은 파일을 열 때


def test_opening_a_shorter_file_does_not_seek_to_its_end(player, tmp_path, monkeypatch):
    """선택 재생 중에만 생김: 그때는 열기 전에 stop_video(슬라이더를 0으로)를 부르지 않아(_stop_playback_for_open — 타이머만 멈춤)
    슬라이더가 앞 파일의 끝에 남은 채 최대값이 줄어듦."""
    long_clip = write_test_video(str(tmp_path / "long.mp4"), frames=48)
    short_clip = write_test_video(str(tmp_path / "short.mp4"), frames=12)
    assert player.open_file("A", long_clip) is True
    player.positionScroll.setValue(player.positionScroll.maximum())  # 앞 파일을 끝까지 봄 (재생이 끝난 자리)
    QTest.qWait(20)
    seeks = []
    monkeypatch.setattr(player, "_precise_seek", lambda *args: seeks.append(args))
    monkeypatch.setattr(player, "_seek_to_last_frame", lambda *args: seeks.append(("last",) + args))
    player.is_playlist_playing = True  # 선택 재생이 다음 파일을 엶 (play_current_playlist_item과 같은 상태)

    assert player.open_file("A", short_clip) is True
    player.is_playlist_playing = False

    assert seeks == []  # 끝으로 갔다가 되돌아오지 않음
    assert player.positionScroll.maximum() == 11
    assert player.positionScroll.value() == 0
    assert player.labelFrameCount.text() == "Current: 1"


def test_dragging_the_slider_still_seeks(player, tmp_path, monkeypatch):
    """막는 것은 최대값을 바꾸는 동안뿐 — 손으로 옮긴 값은 예전처럼 탐색."""
    assert player.open_file("A", write_test_video(str(tmp_path / "clip.mp4"), frames=24)) is True
    seeks = []
    monkeypatch.setattr(player, "_precise_seek", lambda *args: seeks.append(args))
    player.positionScroll.setValue(10)
    assert seeks == [(10, 24)]


# ---------------------------------------------------------------- ② 전환 기록 줄


def test_switch_line_format():
    assert switch_line(0.84, 0.62, "A001.mov", "A002.mov") == "[측정] 전환 0.84초 (열기 0.62초) — A001.mov → A002.mov"


def test_play_selected_logs_one_switch_line_per_transition(player, tmp_path, capsys, dialogs):
    clips = [write_test_video(str(tmp_path / f"c{i}.mp4"), frames=6) for i in range(3)]
    player.add_files_to_sidebar(clips)
    player.sidebar.selectAll()
    capsys.readouterr()

    player.play_selected_files()
    wait_until(lambda: not player.is_playlist_playing)

    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.startswith("[측정] 전환")]
    assert [line.split(" — ")[1] for line in lines] == ["c0.mp4 → c1.mp4", "c1.mp4 → c2.mp4"]
    for line in lines:
        gap, open_s = (float(x) for x in re.match(r"\[측정\] 전환 ([\d.]+)초 \(열기 ([\d.]+)초\)", line).groups())
        assert 0 <= open_s <= gap
    assert out.count("[측정] 5장") == 3  # 파일마다 재생 줄은 그대로


def test_first_playlist_item_has_no_switch_line_even_after_a_full_play(player, tmp_path, capsys):
    """선택 재생 밖에서 끝까지 본 영상의 [측정] 시각은 선택 재생 첫 차례의 '전환'이 아님 (낡은 시각으로 재지 않음)."""
    first = write_test_video(str(tmp_path / "a.mp4"), frames=6)
    second = write_test_video(str(tmp_path / "b.mp4"), frames=6)
    assert player.open_file("A", first) is True
    player.play_video()
    wait_until(lambda: not player.timer.isActive())
    assert player._last_measure_end is not None  # a.mp4를 끝까지 봐 [측정] 줄을 찍음
    player.add_files_to_sidebar([second])
    player.sidebar.clearSelection()
    player.sidebar.item(player.sidebar.count() - 1).setSelected(True)
    capsys.readouterr()

    player.play_selected_files()
    wait_until(lambda: not player.is_playlist_playing)
    assert "[측정] 전환" not in capsys.readouterr().out
