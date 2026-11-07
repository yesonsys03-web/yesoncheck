"""영상 열기의 단계별 시간 기록 (사용자 요청 2026-11-07 — 선택 재생의 전환 약 1초 중 '열기' 0.93초가 무엇에 드는지 재고 나서 '다음 파일 미리
열기'를 설계하려고). open_file이 끝날 때 한 줄:

  [측정] 열기 0.93초 — ffprobe 0.12 · ffmpeg 시작 0.05 · 첫 프레임 0.40 · 옛 캡처 놓기 0.01 · 소리 0.08 · 첫 화면 0.20 · 주석 0.03 · 그 밖 0.04 — <파일>

캡처 단계는 파이프 캡처면 ffprobe·ffmpeg 시작·첫 프레임으로 나누고(maybe_pipe_capture·FFmpegPipeCapture가 적어 둔 open_steps), 그 밖의
캡처(cv2·시퀀스·네이티브)는 '캡처 열기' 하나. 시간 숫자 자체는 단언하지 않음 — 이름·차례·합이 총합을 넘지 않음만.
"""

import re

from tests.conftest import write_test_video
from tests.test_pipe_player import pipe_log, player, prores_clip  # noqa: F401 (픽스처)
from tests.test_work_paths_ui import new_player  # noqa: F401 (픽스처 — player가 씀)
from yesoncheck.player_playback import open_timing_line

LINE = re.compile(r"^\[측정\] 열기 ([\d.]+)초 — (.+) — (.+)$")


def parse(out):
    lines = [line for line in out.splitlines() if line.startswith("[측정] 열기")]
    assert len(lines) == 1, lines
    match = LINE.match(lines[0])
    assert match, lines[0]
    total, parts, name = match.groups()
    steps = [(label, float(seconds)) for label, seconds in (part.rsplit(" ", 1) for part in parts.split(" · "))]
    return float(total), steps, name


def test_open_timing_line_format():
    assert open_timing_line(0.93, [("ffprobe", 0.12), ("첫 프레임", 0.4)], "A001.mov") == \
        "[측정] 열기 0.93초 — ffprobe 0.12 · 첫 프레임 0.40 · 그 밖 0.41 — A001.mov"


def test_open_timing_line_never_shows_a_negative_rest():
    """반올림 탓에 단계 합이 총합을 조금 넘어도 '그 밖'을 음수로 적지 않음."""
    assert open_timing_line(0.5, [("ffprobe", 0.3), ("첫 프레임", 0.2004)], "x.mov").endswith("그 밖 0.00 — x.mov")


def test_pipe_open_logs_ffprobe_ffmpeg_and_first_frame(player, prores_clip, capsys):  # noqa: F811
    capsys.readouterr()
    assert player.open_file("A", prores_clip) is True
    total, steps, name = parse(capsys.readouterr().out)
    labels = [label for label, _seconds in steps]
    assert labels[:3] == ["ffprobe", "ffmpeg 시작", "첫 프레임"]
    assert {"멈추기", "옛 캡처 놓기", "소리", "첫 화면", "주석", "그 밖"} <= set(labels)
    assert name == "numbered_4444.mov"
    assert sum(seconds for label, seconds in steps if label != "그 밖") <= total + 0.01 * len(steps)


def test_cv2_open_logs_one_capture_step(player, tmp_path, capsys):  # noqa: F811
    clip = write_test_video(str(tmp_path / "clip.mp4"), frames=6)
    capsys.readouterr()
    assert player.open_file("A", clip) is True
    _total, steps, name = parse(capsys.readouterr().out)
    labels = [label for label, _seconds in steps]
    assert labels[0] == "캡처 열기" and "ffprobe" not in labels
    assert name == "clip.mp4"


def test_failed_open_logs_no_timing_line(player, tmp_path, capsys, dialogs):  # noqa: F811
    capsys.readouterr()
    assert player.open_file("A", str(tmp_path / "missing.mov")) is False
    assert "[측정] 열기" not in capsys.readouterr().out
