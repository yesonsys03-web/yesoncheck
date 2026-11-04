"""영상 열기 경로의 네이티브(VideoToolbox) 분기 (Apple Silicon 네이티브 재생 — 계획 Task 14·B9, 스펙 §5.3·§5.8).

VideoPlayer._open_movie_capture는 os.stat 확인 뒤 _native_or_pipe_capture로 캡처를 고른다: YESONCHECK_MOVIE_SOURCE=cv2면 네이티브 토글도 보지
않고 probe도 없이 기존 cv2 줄, native_wanted()가 아니면(Windows·YESONCHECK_MAC_NATIVE=off) 예전 파이프 게이트 줄 그대로, 원하면 ffprobe
한 번(movie_pipe_source.probe_for_open — ffprobe가 못 읽을 때의 규칙은 파이프와 같음)으로 네이티브 게이트(mac_native_gate.native_ineligible_reason)를
보고 — 양성이면 네이티브 캡처, 못 열면 기록·오류 창(끝 줄 NATIVE_ESCAPE_HINT) 뒤 같은 probe로 파이프, 음성이면 사유 한 줄 뒤 같은 probe로 파이프.

PyObjC·VideoToolbox·플랫폼(sys.platform)이 어떻든 어느 OS에서나 돌도록 하드웨어에 기대지 않는다: native_wanted·maybe_pipe_capture는 그 이름을 읽는
player_playback에서, probe_movie는 probe_for_open·maybe_pipe_capture가 읽는 movie_pipe_source에서, open_native_capture·_pyobjc는 플레이어가
지연 import하는 mac_native_source에서 바꿔치기한다 (CLAUDE.md 규칙 — 다른 모듈에 다시 내보낸 이름을 바꾸면 닿지 않음). 4K probe는 실제
ffprobe로 읽은 1080p ProRes 4444(bt709) 공장 클립의 probe를 dataclasses.replace로 3840×2160으로 바꾼 것(게이트는 probe 값만 봄). 창은 conftest의
dialogs. 예전 파이프·cv2 줄 자체의 무회귀는 tests/test_movie_pipe_integration.py·test_pipe_player.py의 무수정 통과가 지킨다.
"""

import dataclasses
import os
import subprocess
import sys
from types import SimpleNamespace

import cv2
import pytest

from tests.conftest import write_test_video
from tests.native_fakes import FakeNativeCapture, spy_frames
from tests.prores_clips import make_numbered_clip
from tests.test_movie_pipe_integration import KILL_SWITCH_HINT
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import mac_native_source, movie_pipe_source, player_playback
from yesoncheck.frame_handles import native_surface_of
from yesoncheck.gl_video_item import VIDEO_ITEM_ENV
from yesoncheck.mac_native_gate import native_ineligible_reason
from yesoncheck.mac_native_source import NATIVE_ESCAPE_HINT, NativeCaptureError
from yesoncheck.movie_pipe_source import FFmpegPipeCapture, PipeCaptureError, maybe_pipe_capture, probe_movie
from yesoncheck.video_widget import VIEWPORT_ENV

ENV = "YESONCHECK_MOVIE_SOURCE"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NATIVE_WINDOW_TITLE = "영상을 열 수 없음(네이티브)"
REAL_OPEN_NATIVE = mac_native_source.open_native_capture  # 바꿔치기 전의 진짜 (모듈을 불러올 때 잡아 둠)


# ---------------------------------------------------------------- 클립·probe (module: 인코딩 반복 방지)

@pytest.fixture(scope="module")
def clip_1080(tmp_path_factory):
    """1920×1080 ProRes 4444(bt709) 12장 — 파이프 게이트·네이티브 게이트 둘 다 양성 (크기 조건 없음). 네이티브 음성을 겨누는 시험은 이
    probe에 HDR 태그를 붙여 쓴다 (파이프 게이트는 색 태그를 보지 않으므로 진짜 파이프가 그대로 열림)."""
    path = str(tmp_path_factory.mktemp("native_open_1080") / "clip_1080.mov")
    make_numbered_clip(path, count=12, fps="24", profile="4", pix_fmt="yuv444p10le", width=1920, height=1080, color="bt709")
    return path


@pytest.fixture(scope="module")
def probe_1080(clip_1080):
    return probe_movie(clip_1080)


@pytest.fixture(scope="module")
def probe_4k(probe_1080):
    """clip_1080의 실제 probe를 3840×2160으로 — 네이티브 게이트 양성 (전제를 단언)."""
    probe = dataclasses.replace(probe_1080, width=3840, height=2160)
    assert native_ineligible_reason(probe) is None, native_ineligible_reason(probe)
    return probe


@pytest.fixture(scope="module")
def mp4v_clip(tmp_path_factory):
    """cv2.VideoWriter가 쓴 mp4v 24장 — 파이프·네이티브 게이트 둘 다 음성 (① 코덱)."""
    return write_test_video(str(tmp_path_factory.mktemp("native_open_mp4v") / "plain.mp4"))


@pytest.fixture
def broken_file(tmp_path):
    """ffprobe도 cv2도 못 읽는 파일 (os.stat은 됨)."""
    path = tmp_path / "broken.mov"
    path.write_bytes(b"this is not a movie" * 100)
    return str(path)


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


# ---------------------------------------------------------------- 바꿔치기 묶음

class SentinelCapture:
    """cv2 계약(isOpened·read·get·set·release)만 갖춘 표지 캡처 — 무엇이 돌아왔는지 가르는 데만 씀."""

    def __init__(self, label):
        self.label = label

    def isOpened(self):  # noqa: N802 (cv2 이름)
        return True

    def read(self):
        return False, None

    def get(self, prop):
        return 0.0

    def set(self, prop, value):
        return False

    def release(self):
        pass


def _answer(spec, *args, **kwargs):
    """바꿔치기한 함수의 대답: 예외면 올리고, 부를 수 있으면 그 결과, 아니면 그 값 그대로."""
    if isinstance(spec, BaseException):
        raise spec
    if callable(spec):
        return spec(*args, **kwargs)
    return spec


def _refuse_native(path, probe):
    raise AssertionError(f"네이티브 캡처를 열면 안 되는데 open_native_capture가 불렸다: {path}")


@pytest.fixture
def rig(monkeypatch):
    """열기 경로의 네 이름을 기록하며 바꿔치기 → SimpleNamespace. 각 '대답'은 값·예외·함수(_answer):
    wanted(native_wanted — 기본 True; wanted_calls), probe(movie_pipe_source.probe_movie — 기본 진짜; probes는 받은 경로, probed는 돌려준 probe),
    native(mac_native_source.open_native_capture — 기본 '부르면 실패'; opens는 (경로, probe)), pipe(player_playback.maybe_pipe_capture — 기본 진짜;
    pipes는 (args, kwargs))."""
    state = SimpleNamespace(wanted=True, wanted_calls=0, probe=probe_movie, probes=[], probed=[], native=_refuse_native, opens=[],
                            pipe=maybe_pipe_capture, pipes=[])

    def wanted():
        state.wanted_calls += 1
        return _answer(state.wanted)

    def probe(path):
        state.probes.append(path)
        result = _answer(state.probe, path)
        state.probed.append(result)
        return result

    def open_native(path, probe):
        state.opens.append((path, probe))
        return _answer(state.native, path, probe)

    def pipe(*args, **kwargs):
        state.pipes.append((args, kwargs))
        return _answer(state.pipe, *args, **kwargs)

    monkeypatch.setattr(player_playback, "native_wanted", wanted)
    monkeypatch.setattr(movie_pipe_source, "probe_movie", probe)
    monkeypatch.setattr(mac_native_source, "open_native_capture", open_native)
    monkeypatch.setattr(player_playback, "maybe_pipe_capture", pipe)
    return state


def play_lines(text):
    return [line for line in text.splitlines() if line.startswith("[재생]")]


def assert_native_failure_window(dialogs, path, *must_contain):
    """네이티브 열기 실패 창이 정확히 하나 — 첫 줄은 '파이프로 계속', 사유(예외 이름째)·트레이스백, 끝 줄은 탈출구 안내."""
    assert len(dialogs.criticals) == 1, dialogs.messages
    kind, title, text = dialogs.messages[-1]
    assert (kind, title) == ("critical", NATIVE_WINDOW_TITLE), dialogs.messages
    assert text.splitlines()[0] == f"VideoToolbox(네이티브)로 영상을 열지 못해 ffmpeg 파이프로 계속합니다: {path}", text
    assert "이유: NativeCaptureError: " in text and "Traceback" in text, text
    for part in must_contain:
        assert part in text, (part, text)
    assert text.endswith("\n" + NATIVE_ESCAPE_HINT), text


# ---------------------------------------------------------------- 양성: 네이티브

def test_native_wanted_and_eligible_opens_native_not_pipe(player, dialogs, rig, clip_1080, probe_4k, capsys):
    """원함 + 4K 4444 bt709 → open_native_capture가 준 캡처가 그대로 돌아오고 파이프는 부르지 않음, ffprobe 한 번, 그 probe 그대로 넘김.

    깨지는 변경: 네이티브 분기를 파이프 게이트 뒤에 두면(파이프가 이김) maybe_pipe_capture의 AssertionError; 분기를 빼면 opens가 빔;
    probe를 두 번 돌리면 probes가 둘."""
    native_cap = SentinelCapture("native")
    rig.probe, rig.native, rig.pipe = probe_4k, native_cap, AssertionError("파이프가 불렸다")
    capsys.readouterr()

    assert player._open_movie_capture(clip_1080) is native_cap

    assert rig.probes == [clip_1080]
    assert len(rig.opens) == 1 and rig.opens[0][0] == clip_1080 and rig.opens[0][1] is probe_4k
    assert rig.pipes == []
    assert dialogs.messages == []
    assert play_lines(capsys.readouterr().out) == []  # 양성 기록 줄은 open_native_capture 몫 (여기선 바꿔치기라 없음 — 중복 없음)


def test_pipe_mode_still_prefers_native_when_eligible(player, dialogs, rig, clip_1080, probe_4k, monkeypatch):
    """YESONCHECK_MOVIE_SOURCE=pipe는 네이티브 음성일 때의 강제일 뿐(스펙 §5.8) — 네이티브 양성 파일은 pipe 모드에서도 네이티브로 열림.

    깨지는 변경: pipe 모드도 네이티브를 건너뛰게 하면(예: 분기 조건을 `mode != "auto"`로) 파이프 대역의 AssertionError."""
    monkeypatch.setenv(ENV, "pipe")
    native_cap = SentinelCapture("native")
    rig.probe, rig.native, rig.pipe = probe_4k, native_cap, AssertionError("파이프가 불렸다")
    assert player._open_movie_capture(clip_1080) is native_cap
    assert dialogs.messages == []


def test_open_file_shows_the_native_capture(new_player, dialogs, rig, tmp_path, probe_4k, monkeypatch):  # noqa: F811
    """창 수준: open_file이 이 분기로 연 네이티브 캡처가 cap_a가 되고 첫 프레임이 복사·변환 없이 GL 스트림 아이템의 표면으로 감, 창 없음.
    (가짜 네이티브 캡처 — tests/native_fakes; 소리 재생기용으로 진짜 영상 파일 경로를 엶)

    깨지는 변경: _open_movie_capture가 네이티브 캡처를 감싸거나 버리면 cap_a 단언; 이 분기가 열기 길에 안 붙으면 opens가 빔."""
    monkeypatch.setenv(VIEWPORT_ENV, "gl")
    monkeypatch.delenv(VIDEO_ITEM_ENV, raising=False)
    reads = []
    fake = FakeNativeCapture(spy_frames(8, reads))
    rig.probe, rig.native, rig.pipe = probe_4k, fake, AssertionError("파이프가 불렸다")
    player = new_player(make_config(str(tmp_path), {}))
    path = write_test_video(str(tmp_path / "clip_a.mov"))

    assert player.open_file("A", path) is True

    assert player.cap_a is fake and rig.probes == [path] and [p for p, _ in rig.opens] == [path]
    assert player.frame_a is fake.frames[0] and native_surface_of(player.frame_a) is not None
    assert player.videoWidget.video_item.surface_handle() is fake.frames[0].native
    assert reads == []  # 연 뒤 첫 그림까지 네이티브 프레임의 픽셀을 파이썬이 읽지 않음
    assert dialogs.messages == []


# ---------------------------------------------------------------- 네이티브 실패: 알린 뒤 파이프로

def test_native_failure_shows_window_then_pipe(player, dialogs, rig, clip_1080, probe_4k, capsys):
    """open_native_capture가 NativeCaptureError → 오류 창 한 번(경로·예외 이름·트레이스백, 끝 줄 YESONCHECK_MAC_NATIVE=off 안내) 뒤 같은 probe로
    파이프 — 그 캡처가 결과. 기록: 트레이스백(stderr) + 한 줄 '열지 못해 ffmpeg 파이프로 계속'.

    깨지는 변경: 창을 빼면 criticals 0; 창 뒤 return None이면 결과·pipes; probe를 넘기지 않으면(두 번 probe) kwargs의 probe;
    창을 파이프 뒤에 띄우면 창 수 단언(파이프를 부를 때 이미 1); 탈출구 안내를 빼면 끝 줄; 기록 줄·print_exc를 빼면 stdout/stderr 단언."""
    pipe_cap = SentinelCapture("pipe")
    windows_at_pipe = []

    def pipe(*args, **kwargs):
        windows_at_pipe.append(len(dialogs.criticals))
        return pipe_cap

    rig.probe, rig.native, rig.pipe = probe_4k, NativeCaptureError("AVAssetReader 시작 실패", clip_1080), pipe
    capsys.readouterr()

    assert player._open_movie_capture(clip_1080) is pipe_cap

    assert_native_failure_window(dialogs, clip_1080, f"NativeCaptureError: AVAssetReader 시작 실패: {clip_1080}")
    assert rig.probes == [clip_1080] and len(rig.opens) == 1
    assert len(rig.pipes) == 1 and rig.pipes[0][0] == (clip_1080,)
    assert rig.pipes[0][1]["full_cache"] is True and rig.pipes[0][1]["probe"] is probe_4k
    assert windows_at_pipe == [1]  # 알린 '뒤'에 파이프로
    captured = capsys.readouterr()
    assert play_lines(captured.out) == ["[재생] 네이티브(VideoToolbox): 열지 못해 ffmpeg 파이프로 계속: clip_1080.mov"]
    assert "Traceback" in captured.err and "NativeCaptureError: AVAssetReader 시작 실패" in captured.err


def test_pyobjc_missing_is_a_failure_window_not_a_crash(player, dialogs, rig, clip_1080, probe_4k, monkeypatch):
    """PyObjC가 없음(ModuleNotFoundError — Intel Mac의 YESONCHECK_MAC_NATIVE=on, 빠진 번들): 진짜 open_native_capture·NativeVTCapture가
    NativeCaptureError로 감싸 올리므로(_pyobjc의 ModuleNotFoundError는 생성자의 except가 받음 — 밖으로 새지 않음) 같은 창 + 파이프로 계속.
    어느 기계에서나 같게 _pyobjc를 'objc 없음'으로 바꿔치기 (p310_native·arm64에는 PyObjC가 있음).

    깨지는 변경: 생성자가 ModuleNotFoundError를 감싸지 않으면(또는 분기가 NativeCaptureError만 받는데 다른 것이 새면) 예외가 열기 밖으로 —
    앱이 그 파일을 못 엶; 창을 빼면 창 단언."""
    def no_pyobjc():
        raise ModuleNotFoundError("No module named 'objc'", name="objc")

    monkeypatch.setattr(mac_native_source, "_pyobjc", no_pyobjc)
    pipe_cap = SentinelCapture("pipe")
    rig.probe, rig.native, rig.pipe = probe_4k, REAL_OPEN_NATIVE, pipe_cap

    assert player._open_movie_capture(clip_1080) is pipe_cap

    assert_native_failure_window(dialogs, clip_1080, "ModuleNotFoundError: No module named 'objc'")
    assert len(rig.pipes) == 1 and rig.pipes[0][1]["probe"] is probe_4k


def test_native_then_pipe_failure_shows_both_windows(player, dialogs, rig, clip_1080, probe_4k):
    """네이티브도 파이프도 못 열면 창 둘이 차례로 — 네이티브 실패 창(끝 줄 YESONCHECK_MAC_NATIVE=off), 그다음 기존 파이프 오류 창(끝 줄
    YESONCHECK_MOVIE_SOURCE=cv2) — 결과 None(보던 영상은 그대로), ffprobe 한 번(같은 probe가 파이프로).

    깨지는 변경: 파이프 호출을 네이티브 except 안으로 옮기거나 그 PipeCaptureError를 다른 길로 보내면 둘째 창이 없거나 다름;
    네이티브 창을 빼면 첫 창 단언."""
    rig.probe = probe_4k
    rig.native = NativeCaptureError("AVAssetReader 시작 실패", clip_1080)
    rig.pipe = PipeCaptureError(f"영상을 ffmpeg 파이프로 열지 못했습니다 (시험): {clip_1080}", ["ffmpeg", "-i", clip_1080], "Invalid data found")

    assert player._open_movie_capture(clip_1080) is None

    assert [(kind, title) for kind, title, _ in dialogs.messages] == [("critical", NATIVE_WINDOW_TITLE), ("critical", "영상을 열 수 없음")]
    assert dialogs.criticals[0].endswith("\n" + NATIVE_ESCAPE_HINT), dialogs.criticals[0]
    assert "Invalid data found" in dialogs.criticals[1] and dialogs.criticals[1].endswith("\n" + KILL_SWITCH_HINT), dialogs.criticals[1]
    assert rig.probes == [clip_1080] and len(rig.pipes) == 1 and rig.pipes[0][1]["probe"] is probe_4k


def test_unexpected_native_error_propagates(player, dialogs, rig, clip_1080, probe_4k):
    """NativeCaptureError가 아닌 예외(코드 버그 — AttributeError 등)는 받지 않고 그대로 — 창도 파이프도 없음 (조용히 숨기지 않음).

    깨지는 변경: 분기가 except Exception처럼 넓게 받으면 파이프로 넘어가 AssertionError 대신 결과가 나오거나 창이 뜸."""
    rig.probe, rig.native, rig.pipe = probe_4k, AttributeError("시험용 코드 버그"), AssertionError("파이프가 불렸다")

    with pytest.raises(AttributeError, match="시험용 코드 버그"):
        player._open_movie_capture(clip_1080)

    assert dialogs.messages == [] and rig.pipes == []


# ---------------------------------------------------------------- 음성: 사유 한 줄 뒤 파이프

def test_small_hd_prores_opens_native_now(player, dialogs, rig, clip_1080, probe_1080, capsys):
    """1080p ProRes 4444(실제 ffprobe, 크기를 키우지 않음)도 네이티브 양성 — 4K 조건이 없어진 뒤 (옛 ⑥½ 음성 시험을 뒤집음): open_native_capture가
    준 캡처가 그대로 돌아오고 파이프는 부르지 않음, ffprobe 한 번, 그 probe 그대로 넘김.

    깨지는 변경: 크기 조건이 되살아나면 파이프 대역의 AssertionError."""
    native_cap = SentinelCapture("native")
    rig.probe, rig.native, rig.pipe = probe_1080, native_cap, AssertionError("파이프가 불렸다")
    capsys.readouterr()

    assert player._open_movie_capture(clip_1080) is native_cap

    assert rig.probes == [clip_1080]
    assert len(rig.opens) == 1 and rig.opens[0][1] is probe_1080
    assert rig.pipes == [] and dialogs.messages == []
    assert play_lines(capsys.readouterr().out) == []


def test_ineligible_logs_and_uses_pipe(player, dialogs, rig, clip_1080, capsys):
    """HDR 태그(전달 함수 smpte2084)를 단 1080p ProRes 4444(실제 ffprobe + 태그만 바꾼 probe) → 네이티브 음성 사유 한 줄
    `… 아님 — ⑨ HDR(smpte2084): <이름>` 뒤 진짜 파이프가 같은 probe로 열림 — ffprobe 한 번, 창 없음, open_native_capture는 불리지 않음.

    깨지는 변경: 음성 기록 줄을 빼면 줄 단언; probe를 파이프에 넘기지 않으면 maybe_pipe_capture가 다시 probe해 probes가 둘;
    게이트를 보지 않고 늘 네이티브를 열면 _refuse_native."""
    rig.probe = lambda path: dataclasses.replace(probe_movie(path), color_transfer="smpte2084")
    capsys.readouterr()

    cap = player._open_movie_capture(clip_1080)
    try:
        assert isinstance(cap, FFmpegPipeCapture) and cap.isOpened()
    finally:
        cap.release()

    assert rig.probes == [clip_1080] and rig.opens == []
    assert len(rig.pipes) == 1 and rig.pipes[0][1]["probe"] is rig.probed[0]
    assert play_lines(capsys.readouterr().out) == [
        "[재생] 네이티브(VideoToolbox): 아님 — ⑨ HDR(smpte2084): clip_1080.mov",
        "[재생] ffmpeg 파이프: clip_1080.mov (prores 1920×1080 24fps, 프레임 12)",
    ]
    assert dialogs.messages == []


# ---------------------------------------------------------------- 순서: cv2 킬 스위치가 먼저, 원하지 않으면 예전 줄

def test_cv2_kill_switch_skips_native(player, dialogs, rig, clip_1080, monkeypatch, capsys):
    """YESONCHECK_MOVIE_SOURCE=cv2 + 네이티브 원함 → 네이티브 토글도 보지 않고(먼저 판정 — 토글 값이 잘못돼도 탈출구가 막히지 않음)
    probe 0·네이티브 0, 진짜 maybe_pipe_capture가 None이라 ProRes여도 cv2.VideoCapture, 기록 줄 없음.

    깨지는 변경: 분기 조건에서 cv2 검사를 빼면 probe_movie의 AssertionError; native_wanted를 cv2 검사보다 먼저 보면 wanted_calls."""
    monkeypatch.setenv(ENV, "cv2")
    rig.probe = AssertionError("cv2 모드에서 probe_movie가 불렸다")
    capsys.readouterr()

    cap = player._open_movie_capture(clip_1080)
    try:
        assert type(cap) is cv2.VideoCapture and cap.isOpened()
    finally:
        cap.release()

    assert rig.probes == [] and rig.opens == [] and rig.wanted_calls == 0
    assert play_lines(capsys.readouterr().out) == []
    assert dialogs.messages == []


def test_not_wanted_leaves_existing_path_untouched(player, dialogs, rig, mp4v_clip, capsys):
    """native_wanted()가 거짓(Intel·Windows·YESONCHECK_MAC_NATIVE=off) → 이 분기는 probe하지 않고 예전 줄 `maybe_pipe_capture(path, full_cache=True)`
    (probe 인자 없음) 하나만 — 여기서는 대역이 None을 줘서 기존 cv2.VideoCapture까지. 네이티브 기록 줄 없음.
    (진짜 파이프·cv2 줄의 무회귀는 test_movie_pipe_integration·test_pipe_player의 무수정 통과)

    깨지는 변경: 원하지 않아도 probe하면 probes; 원함 검사를 빼면 _refuse_native 또는 probes; 파이프 호출에 probe를 늘 넘기면 kwargs 단언."""
    rig.wanted, rig.pipe = False, None
    capsys.readouterr()

    cap = player._open_movie_capture(mp4v_clip)
    try:
        assert type(cap) is cv2.VideoCapture and cap.isOpened()
    finally:
        cap.release()

    assert rig.wanted_calls == 1 and rig.probes == [] and rig.opens == []
    assert rig.pipes == [((mp4v_clip,), {"full_cache": True})]
    assert not any("네이티브" in line for line in play_lines(capsys.readouterr().out))
    assert dialogs.messages == []


def test_player_does_not_import_native_source_unless_wanted():
    """플레이어는 mac_native_source를 맨 위에서 불러오지 않고, 원하지 않을 때(native_wanted 거짓) 영상 열기 전체(_open_movie_capture — os.stat
    확인부터 캡처를 돌려줄 때까지)에서도 불러오지 않음 — 원할 때만 분기 안에서 지연 import (스펙 §5.8·§5.9: Intel·Windows 앱은 이 모듈을 import하지
    않음). 새 프로세스에서 player_playback을 불러 sys.modules를 보고(이 프로세스는 다른 시험이 이미 불러옴), 원하지 않음·표지를 주는 파이프 대역으로
    진짜 _open_movie_capture를 있는 파일(그 모듈 파일 자체)에 한 번 돌린 뒤 다시 봄 — 창·QApplication 없이(os.stat이 되고 대역이 cv2 앞에서 돌려줌).
    자식 출력은 utf-8로 (tests/test_workers_split 선례).

    깨지는 변경: player_playback 맨 위에 `from yesoncheck import mac_native_source`(또는 그 이름들의 import)를 두면 첫 값이, 지연 import를
    native_wanted 검사 앞으로 옮기거나 _open_movie_capture 안(분기 밖)에 두면 둘째 값이 True."""
    code = (
        "import sys\n"
        "from yesoncheck import player_playback\n"
        "print('yesoncheck.mac_native_source' in sys.modules)\n"
        "player_playback.native_wanted = lambda: False\n"
        "sentinel = object()\n"
        "player_playback.maybe_pipe_capture = lambda *args, **kwargs: sentinel\n"
        "assert player_playback.PlayerPlaybackMixin()._open_movie_capture(player_playback.__file__) is sentinel\n"
        "print('yesoncheck.mac_native_source' in sys.modules)\n"
    )
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
                          timeout=300, check=False)
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert proc.stdout.strip().splitlines()[-2:] == ["False", "False"], proc.stdout


# ---------------------------------------------------------------- ffprobe가 못 읽음: 파이프와 같은 규칙

def test_probe_failure_in_native_branch_matches_pipe_rule(player, dialogs, rig, broken_file, monkeypatch, capsys):
    """원함 + ffprobe가 못 읽는 파일(실제 ffprobe의 RuntimeError): maybe_pipe_capture와 같은 규칙 —
    auto는 같은 기록 줄 한 번 + 트레이스백 뒤 기존 cv2 줄(여기서는 cv2도 못 열어 기존 'OpenCV가 읽지 못함' 창), ffprobe는 한 번;
    pipe는 PipeCaptureError가 기존 파이프 오류 창으로(끝 줄 YESONCHECK_MOVIE_SOURCE=cv2 안내), cv2로 조용히 가지 않음.

    깨지는 변경: 분기가 probe_movie를 직접 불러 RuntimeError를 안 받으면 열기 밖으로 예외; 받아서 probe 없이 파이프를 다시 부르면 probes가 둘·줄이 둘;
    pipe 모드에서 cv2로 보내면 창 단언."""
    capsys.readouterr()
    assert player._open_movie_capture(broken_file) is None
    captured = capsys.readouterr()
    assert play_lines(captured.out) == ["[재생] ffprobe가 파일을 읽지 못해 기존 cv2 경로로 엽니다: broken.mov"]
    assert "Traceback" in captured.err and "ffprobe로 읽지 못했습니다" in captured.err
    assert rig.probes == [broken_file] and rig.opens == []
    assert len(dialogs.criticals) == 1 and "OpenCV가 읽지 못함" in dialogs.criticals[0]

    monkeypatch.setenv(ENV, "pipe")
    rig.probes.clear()
    assert player._open_movie_capture(broken_file) is None
    assert rig.probes == [broken_file] and rig.opens == []
    assert len(dialogs.criticals) == 2 and dialogs.messages[-1][1] == "영상을 열 수 없음"
    text = dialogs.criticals[1]
    assert "PipeCaptureError" in text and "ffprobe가 파일을 읽지 못했습니다" in text and broken_file in text, text
    assert text.endswith("\n" + KILL_SWITCH_HINT), text
    assert "cv2 경로로 엽니다" not in capsys.readouterr().out


# ---------------------------------------------------------------- maybe_pipe_capture(probe=…)

def test_maybe_pipe_capture_accepts_probe(clip_1080, mp4v_clip, monkeypatch, capsys):
    """maybe_pipe_capture(path, probe=probe)는 probe_movie를 부르지 않고 스스로 probe한 것과 같은 판정·같은 기록 줄 — 그 밖의 규칙도 그대로:
    pipe 모드의 게이트 불통과는 PipeCaptureError, cv2 모드는 None (기록 없음).

    깨지는 변경: probe를 받고도 다시 probe하면 AssertionError; probe를 받을 때 게이트·모드를 건너뛰면 pipe/cv2 단언."""
    given = {path: probe_movie(path) for path in (clip_1080, mp4v_clip)}
    expected = {}
    capsys.readouterr()
    for path in given:  # 대조: 스스로 probe
        cap = maybe_pipe_capture(path, full_cache=True)
        expected[path] = (type(cap), play_lines(capsys.readouterr().out))
        if cap is not None:
            cap.release()

    def no_probe(path):
        raise AssertionError(f"probe를 받았는데 probe_movie가 불렸다: {path}")

    monkeypatch.setattr(movie_pipe_source, "probe_movie", no_probe)
    for path, probe in given.items():
        cap = maybe_pipe_capture(path, full_cache=True, probe=probe)
        try:
            assert (type(cap), play_lines(capsys.readouterr().out)) == expected[path], path
        finally:
            if cap is not None:
                cap.release()
    assert expected[clip_1080][0] is FFmpegPipeCapture and expected[mp4v_clip][0] is type(None)

    monkeypatch.setenv(ENV, "pipe")
    with pytest.raises(PipeCaptureError, match="②"):
        maybe_pipe_capture(clip_1080, probe=dataclasses.replace(given[clip_1080], avg=None))
    monkeypatch.setenv(ENV, "cv2")
    assert maybe_pipe_capture(clip_1080, probe=given[clip_1080]) is None
    assert capsys.readouterr().out == ""
