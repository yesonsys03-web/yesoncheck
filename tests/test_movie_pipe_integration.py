"""ffmpeg 파이프를 열기 경로에 연결 (yesoncheck/movie_pipe_source.py 3부): maybe_pipe_capture의 판정·모드·예외 경계, open_any_capture와
VideoPlayer._open_movie_capture의 삽입 분기, app.launch의 모드 검증. 실제 ffprobe·ffmpeg로 클립 공장 클립을 연다.

사용자 최우선 제약 "기존 파일 재생 무회귀"의 시험: 게이트가 음성인 파일(H.264·mp4v·가변 프레임 레이트 등)은 어떤 모드에서도
FFmpegPipeCapture를 만들지 않고 기존 cv2.VideoCapture가 열린다 — FFmpegPipeCapture를 '만들면 실패'하는 센티널로 바꿔 증명.
바꿔치기는 그 이름을 읽는 모듈(movie_pipe_source)에서 한다 (CLAUDE.md 규칙). 창은 conftest의 dialogs가 가로챔.
"""

import dataclasses
import os
import re

import cv2
import pytest

from tests.conftest import write_test_video
from tests.prores_clips import frame_number, make_held, make_numbered_clip, make_rot, make_vfr_h264, run_ffmpeg
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import external_tools, movie_pipe_source
from yesoncheck.movie_pipe_source import (
    FFmpegPipeCapture, PipeCaptureError, ineligible_reason, maybe_pipe_capture, pipe_eligible, probe_movie,
)
from yesoncheck.sequence_source import open_any_capture

ENV = "YESONCHECK_MOVIE_SOURCE"
CREATE_MSG = "게이트가 음성인 파일에서 FFmpegPipeCapture가 만들어졌습니다"


# ---------------------------------------------------------------- 클립 (session: 인코딩 반복 방지)

@pytest.fixture(scope="session")
def prores_clip(tmp_path_factory):
    """4444 120장 24fps 번호 클립 (게이트 양성)."""
    path = str(tmp_path_factory.mktemp("integration_prores") / "numbered_4444.mov")
    make_numbered_clip(path, count=120, fps="24", profile="4", pix_fmt="yuv444p10le")
    return path


@pytest.fixture(scope="session")
def h264_clip(tmp_path_factory):
    """일정한 프레임 속도(CFR) H.264 48장 — 코덱 ①만 빼고 정확도 게이트(②~⑥)를 통과하는 파일."""
    path = str(tmp_path_factory.mktemp("integration_h264") / "cfr.mp4")
    run_ffmpeg(["-f", "lavfi", "-i", "testsrc=duration=2:size=320x180:rate=24", "-c:v", "libx264", "-bf", "0",
                "-pix_fmt", "yuv420p", path], "H.264 일정 프레임 속도 클립 인코드")
    return path


@pytest.fixture(scope="session")
def mp4v_clip(tmp_path_factory):
    """cv2.VideoWriter가 쓴 mp4v 24장 (다른 시험 파일들이 쓰는 평범한 시험 영상)."""
    return write_test_video(str(tmp_path_factory.mktemp("integration_mp4v") / "plain.mp4"))


@pytest.fixture(scope="session")
def vfr_h264_clip(tmp_path_factory):
    """가변 프레임 레이트 H.264 (코덱 ①도, 프레임 속도 ②도 음성)."""
    path = str(tmp_path_factory.mktemp("integration_vfr") / "vfr.mp4")
    make_vfr_h264(path)
    return path


@pytest.fixture(scope="session")
def held_clip(tmp_path_factory):
    """ProRes인데 한 프레임이 머무는 클립 (코덱 ①은 양성, 프레임 속도 ②가 음성)."""
    path = str(tmp_path_factory.mktemp("integration_held") / "held.mov")
    make_held(path)
    return path


@pytest.fixture(scope="session")
def rot_clip(tmp_path_factory):
    """ProRes인데 회전 메타가 있는 클립 (⑤가 음성)."""
    path = str(tmp_path_factory.mktemp("integration_rot") / "rot.mov")
    make_rot(path)
    return path


@pytest.fixture
def no_pipe(monkeypatch):
    """FFmpegPipeCapture를 '만들면 실패'하는 센티널로 — cv2 경로 시험 전용."""

    class Sentinel:
        def __init__(self, *args, **kwargs):
            raise AssertionError(CREATE_MSG)

    monkeypatch.setattr(movie_pipe_source, "FFmpegPipeCapture", Sentinel)


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


# ---------------------------------------------------------------- open_any_capture: 게이트 음성은 기존 cv2 그대로

def test_cv2_path_unchanged_for_h264(h264_clip, mp4v_clip, vfr_h264_clip, no_pipe, capsys):
    """H.264·mp4v·가변 H.264는 게이트 음성 — 파이프 캡처를 만들지 않고 열린 cv2.VideoCapture가 돌아옴. 음성 사유가 파일 이름과 함께 한 줄."""
    for path in (h264_clip, mp4v_clip, vfr_h264_clip):
        cap = open_any_capture(path)
        assert type(cap) is cv2.VideoCapture and cap.isOpened(), path
        assert cap.read()[0], path  # 기존 경로는 그대로 프레임을 읽음
        cap.release()
        out = capsys.readouterr().out
        lines = [line for line in out.splitlines() if line.startswith("[재생]")]
        assert len(lines) == 1 and os.path.basename(path) in lines[0] and "cv2" in lines[0] and "코덱" in lines[0], out


def test_gate_negative_reason_names_the_condition(held_clip, rot_clip, capsys):
    """ProRes라도 정확도 조건이 어긋나면 cv2로 가고, 로그 한 줄이 어느 조건인지 말함 (진단 추적 — 스펙 §5.7)."""
    for path, condition in ((held_clip, "②"), (rot_clip, "⑤")):
        cap = open_any_capture(path)
        assert type(cap) is cv2.VideoCapture, path
        cap.release()
        lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("[재생]")]
        assert len(lines) == 1 and condition in lines[0] and "cv2" in lines[0], (path, lines)


def test_gate_positive_returns_pipe(prores_clip, capsys):
    cap = open_any_capture(prores_clip)
    try:
        assert isinstance(cap, FFmpegPipeCapture) and cap.isOpened()
        out = capsys.readouterr().out
        lines = [line for line in out.splitlines() if "[재생] ffmpeg 파이프" in line]
        assert len(lines) == 1, out
        assert lines[0] == "[재생] ffmpeg 파이프: numbered_4444.mov (prores 320×180 24fps, 프레임 120)", lines[0]
        ok, frame = cap.read()
        assert ok and frame_number(frame) == 0
    finally:
        cap.release()


def test_mode_cv2_disables_gate(prores_clip, no_pipe, monkeypatch, capsys):
    """cv2 모드는 완전한 킬 스위치: probe도 하지 않고 로그도 없이 기존 cv2 경로 (ProRes여도)."""
    def no_probe(path):
        raise AssertionError("cv2 모드에서 probe_movie가 불렸습니다")

    monkeypatch.setattr(movie_pipe_source, "probe_movie", no_probe)
    for given in ("cv2", "CV2"):
        monkeypatch.setenv(ENV, given)
        cap = open_any_capture(prores_clip)
        assert type(cap) is cv2.VideoCapture and cap.isOpened()
        cap.release()
    assert capsys.readouterr().out == ""


def test_mode_pipe_forces_loud_failure(vfr_h264_clip, prores_clip, held_clip, monkeypatch):
    """pipe 모드는 코덱 ①만 면제 — 비 CFR 파일은 cv2로 조용히 틀지 않고 PipeCaptureError (파일·어느 조건인지 글에 있음)."""
    monkeypatch.setenv(ENV, "pipe")
    for path, condition in ((vfr_h264_clip, "②"), (held_clip, "②")):
        with pytest.raises(PipeCaptureError) as excinfo:
            open_any_capture(path)
        assert path in str(excinfo.value) and condition in str(excinfo.value), str(excinfo.value)
    cap = open_any_capture(prores_clip)  # 적격 파일은 모드와 상관없이 파이프
    try:
        assert isinstance(cap, FFmpegPipeCapture)
    finally:
        cap.release()


def test_mode_pipe_waives_only_the_codec(h264_clip, monkeypatch):
    """pipe 모드가 면제하는 건 ① 코덱뿐 — 일정한 프레임 속도의 H.264는 파이프로 열림 (auto에서는 cv2)."""
    probe = probe_movie(h264_clip)
    assert not pipe_eligible(probe) and pipe_eligible(probe, check_codec=False)
    assert ineligible_reason(probe).startswith("①") and ineligible_reason(probe, check_codec=False) is None
    monkeypatch.setenv(ENV, "pipe")
    cap = open_any_capture(h264_clip)
    try:
        assert isinstance(cap, FFmpegPipeCapture) and cap.read()[0]
    finally:
        cap.release()


def test_check_codec_waiver_keeps_the_accuracy_conditions(vfr_h264_clip, held_clip, rot_clip):
    """check_codec=False는 정확도 조건 ②~⑥을 하나도 풀지 않음 — 면제 뒤에도 비 CFR·회전 파일은 음성이고, 사유는 코덱이 아님."""
    for path, condition in ((vfr_h264_clip, "②"), (held_clip, "②"), (rot_clip, "⑤")):
        probe = probe_movie(path)
        assert not pipe_eligible(probe, check_codec=False), path
        assert ineligible_reason(probe, check_codec=False).startswith(condition), path


def test_pipe_eligible_is_the_reason_function(prores_clip):
    """pipe_eligible은 사유 함수의 겉 — 양성이면 사유 None, 조건마다 사유가 있음 (사유 함수 하나만 판정)."""
    probe = probe_movie(prores_clip)
    assert pipe_eligible(probe) and ineligible_reason(probe) is None
    broken = {
        "①": dataclasses.replace(probe, codec="h264"),
        "②": dataclasses.replace(probe, avg=None),
        "③": dataclasses.replace(probe, nb_frames=0),
        "④": dataclasses.replace(probe, duration_ts=probe.duration_ts + 1),
        "⑤": dataclasses.replace(probe, rotation=90),
        "⑥": dataclasses.replace(probe, video_start=float("nan")),
    }
    for condition, bad in broken.items():
        assert not pipe_eligible(bad) and ineligible_reason(bad).startswith(condition), condition


# ---------------------------------------------------------------- 예외 경계: ffprobe 실패만 cv2, 나머지는 위로

def test_probe_failure_falls_to_cv2_with_log(tmp_path, capsys):
    """ffprobe가 못 읽는 파일(깨진 파일)은 기존 cv2 경로 — 그 결과는 예전과 같고(열리지 않은 cv2), 트레이스·stderr 전문이 로그에 남음."""
    broken = tmp_path / "broken.mov"
    broken.write_bytes(b"this is not a movie" * 100)
    cap = open_any_capture(str(broken))
    assert type(cap) is cv2.VideoCapture and not cap.isOpened()
    captured = capsys.readouterr()
    assert "[재생]" in captured.out and "broken.mov" in captured.out and "cv2" in captured.out
    assert "Traceback" in captured.err and "ffprobe로 읽지 못했습니다" in captured.err and str(broken) in captured.err


def test_mode_pipe_probe_failure_is_loud(tmp_path, monkeypatch, capsys):
    """pipe 모드에서 ffprobe가 못 읽는 파일은 cv2로 조용히 가지 않고 PipeCaptureError (원인 RuntimeError 체인·ffprobe stderr 전문 유지)."""
    broken = tmp_path / "broken.mov"
    broken.write_bytes(b"this is not a movie" * 100)
    monkeypatch.setenv(ENV, "pipe")
    with pytest.raises(PipeCaptureError) as excinfo:
        open_any_capture(str(broken))
    assert isinstance(excinfo.value.__cause__, RuntimeError)
    assert str(broken) in str(excinfo.value) and "ffprobe로 읽지 못했습니다" in str(excinfo.value)
    assert "cv2 경로" not in capsys.readouterr().out  # cv2로 간다는 로그가 없음
    monkeypatch.setenv(ENV, "auto")  # 대조: auto는 같은 파일을 기존처럼 cv2로 (위 test_probe_failure_falls_to_cv2_with_log)
    assert type(open_any_capture(str(broken))) is cv2.VideoCapture


def test_tool_not_found_propagates(prores_clip, monkeypatch):
    """ffprobe 실행 파일이 없음(번들 깨짐)은 cv2로 보내지 않고 그대로 — 조용히 숨기면 안 됨."""
    monkeypatch.setenv("PATH", "")
    with pytest.raises(external_tools.ToolNotFoundError):
        maybe_pipe_capture(prores_clip)
    with pytest.raises(external_tools.ToolNotFoundError):
        open_any_capture(prores_clip)


def test_probe_interpretation_error_propagates(prores_clip, monkeypatch):
    """probe 결과 해석이 어긋난 예외(KeyError 등 — 코드 버그)도 그대로."""
    def broken_probe(path):
        raise KeyError("streams")

    monkeypatch.setattr(movie_pipe_source, "probe_movie", broken_probe)
    with pytest.raises(KeyError):
        open_any_capture(prores_clip)


def test_pipe_construction_error_propagates(prores_clip, monkeypatch):
    """게이트는 양성인데 파이프를 못 연 PipeCaptureError는 maybe_pipe_capture가 잡지 않음 — 부르는 쪽 몫."""
    class Failing:
        def __init__(self, path, probe):
            raise PipeCaptureError("시험용 실패", ["ffmpeg"], "boom")

    monkeypatch.setattr(movie_pipe_source, "FFmpegPipeCapture", Failing)
    with pytest.raises(PipeCaptureError, match="시험용 실패"):
        maybe_pipe_capture(prores_clip)


# ---------------------------------------------------------------- VideoPlayer._open_movie_capture

def test_open_movie_capture_pipe_error_dialog(player, dialogs, mp4v_clip, vfr_h264_clip, monkeypatch, capsys):
    """파이프를 열지 못하면(여기서는 pipe 모드의 비 CFR 파일) 오류 창 한 번(스택 트레이스째)·열기 실패 — 보던 영상은 그대로."""
    assert player.open_file("A", mp4v_clip) is True
    before = (player.cap_a, player.filename_a)
    assert isinstance(before[0], cv2.VideoCapture) and before[0].isOpened()

    monkeypatch.setenv(ENV, "pipe")
    assert player.open_file("A", vfr_h264_clip) is False

    assert len(dialogs.criticals) == 1 and dialogs.messages[-1][1] == "영상을 열 수 없음"
    text = dialogs.criticals[0]
    assert vfr_h264_clip in text and "PipeCaptureError" in text and "Traceback" in text
    assert "Traceback" in capsys.readouterr().err  # 로그에도 트레이스째
    assert (player.cap_a, player.filename_a) == before and before[0].isOpened()  # 보던 영상 그대로


def test_open_movie_capture_construction_failure_dialog(player, dialogs, mp4v_clip, prores_clip, monkeypatch):
    """게이트는 양성인데 ffmpeg가 못 열어 생성자가 PipeCaptureError를 올리면: 창에 ffmpeg stderr 전문이 있고, 보던 영상은 그대로."""
    class Failing:
        def __init__(self, path, probe):
            raise PipeCaptureError(f"영상을 ffmpeg 파이프로 열지 못했습니다 (시험): {path}", ["ffmpeg", "-i", path], "Invalid data found")

    assert player.open_file("A", mp4v_clip) is True
    before = (player.cap_a, player.filename_a)
    monkeypatch.setattr(movie_pipe_source, "FFmpegPipeCapture", Failing)

    assert player.open_file("A", prores_clip) is False

    assert len(dialogs.criticals) == 1
    assert "Invalid data found" in dialogs.criticals[0] and prores_clip in dialogs.criticals[0]
    assert (player.cap_a, player.filename_a) == before and before[0].isOpened()


def test_open_file_keeps_cv2_for_the_rest(player, dialogs, mp4v_clip, h264_clip, vfr_h264_clip, no_pipe):
    """창 수준 무회귀: mp4v·H.264·가변 H.264는 기존 cv2.VideoCapture로 열림 (센티널이 파이프 만들기를 막음), 안내 창 없음."""
    for path in (mp4v_clip, h264_clip, vfr_h264_clip):
        assert player.open_file("A", path) is True
        assert type(player.cap_a) is cv2.VideoCapture and player.cap_a.isOpened(), path
    assert dialogs.messages == []


def test_open_file_uses_pipe_for_prores(player, dialogs, prores_clip):
    """창 수준: 게이트 양성 ProRes는 파이프 캡처로 열리고 첫 화면이 그려짐 (A는 RGB 프레임)."""
    assert player.open_file("A", prores_clip) is True
    assert isinstance(player.cap_a, FFmpegPipeCapture) and player.cap_a.isOpened()
    assert player.frame_a is not None and player.frame_a.shape[:2] == (180, 320)
    assert dialogs.messages == []


def test_open_movie_capture_cv2_failure_text_unchanged(player, dialogs, tmp_path):
    """게이트 음성(ffprobe도 못 읽는 깨진 파일)에서 cv2가 못 열면 기존 오류 창 그대로 — 파이프 쪽 창이 아님."""
    broken = tmp_path / "broken.mov"
    broken.write_bytes(b"this is not a movie" * 100)
    assert player.open_file("A", str(broken)) is False
    assert len(dialogs.criticals) == 1 and "OpenCV가 읽지 못함" in dialogs.criticals[0]
    assert "Traceback" not in dialogs.criticals[0] and player.cap_a is None


# ---------------------------------------------------------------- app.launch: 모드 검증

def test_launch_rejects_a_bad_mode_before_the_window(qapp, monkeypatch):
    """YESONCHECK_MOVIE_SOURCE가 나쁜 값이면 시작 때 ValueError — 창·스플래시를 만들기 전에 크게 (뒤늦게 첫 영상에서 알게 되지 않음)."""
    from yesoncheck import app as app_module

    def no_window(**kwargs):
        raise AssertionError("나쁜 모드인데 창을 만들었습니다")

    monkeypatch.setattr(app_module, "VideoPlayer", no_window)
    monkeypatch.setenv(ENV, "pipes")
    with pytest.raises(ValueError, match=re.escape(repr("pipes"))):
        app_module.launch(["yesoncheck"])
