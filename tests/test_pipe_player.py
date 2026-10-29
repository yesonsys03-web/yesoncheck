"""플레이어 수준 시험 — 실제 VideoPlayer를 offscreen으로 띄워, ffmpeg 파이프 캡처(FFmpegPipeCapture)가 cap_a/cap_b에 꽂힌 채로
재생 기능 전체가 도는지 본다 (열기·화살표/휠 한 칸·슬라이더 탐색·A/B 와이프·주석 내보내기·재생 도중 ffmpeg 사망).

번호 클립(tests/prores_clips)의 프레임 번호(frame_number)로 어느 프레임이 화면에 갔는지 판별 — 픽셀 추측 없음. 와이프의 B는
번호가 거꾸로 가는 클립(B의 k번 프레임 = 번호 B_COUNT-1-k)이라 A·B가 뒤바뀌거나 한쪽이 다른 쪽을 끌고 가면 번호로 드러난다.
각 시험은 시작에서 cap이 진짜 파이프인지 단언한다 (게이트가 실수로 cv2를 주면 시험 전체가 무의미해지므로). pipe_log 픽스처가 앱이
만든 캡처·세션을 전부 기록해, 시험이 끝나 창이 닫힌 뒤 ffmpeg 프로세스·스레드가 하나도 남지 않았는지 늘 확인한다.

플레이어 API 참고: seek_to_frame은 1-based(seek_to_frame(k + 1)이 k번 프레임, 0-based 인덱스 k). 방향키 한 칸은 mov도 A만 움직이는 기존
동작이라(test_sequence_open 주석) 와이프 시험은 탐색·재생 틱으로만 B를 본다.
오류 창은 conftest의 dialogs가 가로채고, 파이프의 도중 실패 알림은 error_window.show_window를 바꿔치기해 기록한다
(movie_pipe_source가 error_window 모듈에서 그 이름을 읽으므로 그 모듈에서 바꿈 — CLAUDE.md 규칙).
"""

import random
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QImage, QWheelEvent
from PyQt5.QtTest import QTest

from tests.prores_clips import frame_number, make_numbered_clip, read_all_frames, run_ffmpeg
from tests.test_movie_pipe_capture import assert_session_gone, wait_for
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import error_window, external_tools, movie_pipe_source
from yesoncheck.annotation_export import AnnotationExportWorker
from yesoncheck.movie_pipe_source import (
    FAILURE_HEADLINE, KEEP_BEHIND, READAHEAD_FRAMES, FFmpegPipeCapture, pipe_eligible, probe_movie,
)

A_COUNT = 120
B_COUNT = 90  # A보다 짧음 — 와이프에서 B가 먼저 끝나도 A는 계속 가야 함
POS = cv2.CAP_PROP_POS_FRAMES
SEED = 20261029  # 무작위 탐색 지점의 시드 (실패하면 메시지에 지점이 찍힘)
EXPORT_TIMEOUT_S = 60


# ---------------------------------------------------------------- 클립 (session: 인코딩 반복 방지)

@pytest.fixture(scope="session")
def prores_clip(tmp_path_factory):
    """A용: 4444 120장 24fps 번호 클립 (프레임 i의 번호 i)."""
    path = str(tmp_path_factory.mktemp("player_a") / "numbered_4444.mov")
    make_numbered_clip(path, count=A_COUNT, fps="24", profile="4", pix_fmt="yuv444p10le")
    return path


@pytest.fixture(scope="session")
def reversed_clip(tmp_path_factory):
    """B용: 4444 90장 24fps — 번호가 거꾸로 (k번 프레임의 번호 B_COUNT-1-k). 같은 인덱스에서 A와 번호가 절대 같지 않아서
    A·B가 뒤섞이면 드러난다. 번호 클립을 reverse 필터로 다시 인코드해 만들고, 번호 순서와 게이트 양성을 만든 자리에서 검증."""
    folder = tmp_path_factory.mktemp("player_b")
    forward, path = str(folder / "forward.mov"), str(folder / "reversed_4444.mov")
    make_numbered_clip(forward, count=B_COUNT, fps="24", profile="4", pix_fmt="yuv444p10le")
    run_ffmpeg(["-i", forward, "-vf", "reverse", "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuv444p10le", path],
               "번호 클립 거꾸로 다시 인코드")
    numbers = [frame_number(f) for f in read_all_frames(path)]
    assert numbers == list(range(B_COUNT - 1, -1, -1)), numbers
    probe = probe_movie(path)
    assert pipe_eligible(probe) and probe.nb_frames == B_COUNT, probe
    return path


# ---------------------------------------------------------------- 픽스처

@pytest.fixture
def pipe_log(monkeypatch):
    """앱이 만든 FFmpegPipeCapture·세션(ffmpeg 프로세스 하나)을 전부 기록 (movie_pipe_source에서 하위 클래스로 바꿔치기 — 그 모듈이
    두 이름을 읽음). 이 픽스처는 new_player보다 먼저 만들어져 나중에 정리된다: 창이 닫힌 뒤에 모든 캡처가 닫혔고 모든 세션의
    프로세스·파이프·스레드가 끝났는지 단언 (재시작으로 버려진 옛 세션도 포함)."""
    log = SimpleNamespace(captures=[], sessions=[])

    class RecordingSession(movie_pipe_source._PipeSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            log.sessions.append(self)

    class RecordingCapture(FFmpegPipeCapture):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            log.captures.append(self)

    monkeypatch.setattr(movie_pipe_source, "_PipeSession", RecordingSession)
    monkeypatch.setattr(movie_pipe_source, "FFmpegPipeCapture", RecordingCapture)
    yield log
    for capture in log.captures:
        assert not capture.isOpened(), "시험이 끝났는데 캡처가 열려 있습니다 (창 닫기가 놓지 않음)"
    for session in log.sessions:
        assert_session_gone(session)


@pytest.fixture
def windows(monkeypatch, qapp):
    """오류 창(error_window.show_window)을 띄우지 않고 글을 기록. 끝날 때 남은 Qt 이벤트를 비워 (바꿔치기가 살아 있는 동안)
    다른 시험에서 진짜 창이 뜨지 않게."""
    shown = []
    monkeypatch.setattr(error_window, "show_window", shown.append)
    yield shown
    qapp.processEvents()


@pytest.fixture
def player(pipe_log, new_player, dialogs, tmp_path, qapp):  # noqa: F811 (pipe_log가 맨 먼저 — new_player 정리 뒤에 확인)
    return new_player(make_config(str(tmp_path), {}))


# ---------------------------------------------------------------- 도구

def open_pipe(player, side, path, pipe_log):
    """영상을 side(A/B)로 열고 그 cap이 앱의 열기 경로가 만든 진짜 파이프 캡처임을 단언 → cap."""
    assert player.open_file(side, path) is True
    cap = player.cap_a if side == "A" else player.cap_b
    assert isinstance(cap, FFmpegPipeCapture) and cap.isOpened(), type(cap)
    assert cap in pipe_log.captures  # 기록된 클래스로 만들어졌음 = movie_pipe_source.maybe_pipe_capture를 거쳤음
    return cap


def screen_image(player):
    """화면(videoWidget)에 그려진 그림 — RGB 배열 (손실 없음)."""
    image = player.videoWidget.video_item.pixmap().toImage().convertToFormat(QImage.Format_RGB888)
    height, width, stride = image.height(), image.width(), image.bytesPerLine()
    pointer = image.constBits()
    pointer.setsize(stride * height)
    return np.frombuffer(pointer, np.uint8).reshape(height, stride)[:, :width * 3].reshape(height, width, 3).copy()


def assert_showing(player, index, note=""):
    """A가 index번 프레임을 보이고 있음 — 플레이어가 든 프레임, 화면에 그려진 그림, 라벨, 두 슬라이더가 모두. note: 실패 메시지에 덧붙임."""
    assert frame_number(player.frame_a) == index, note
    assert frame_number(screen_image(player)) == index, note
    assert player.labelFrameCount.text() == f"Current: {index + 1}", note
    assert player.positionScroll.value() == index, note
    assert player.overlaySlider.value() == index, note


def assert_wipe_showing(player, index):
    """와이프 중: A는 index번, B는 거꾸로 번호(B_COUNT-1-index) 프레임 — B가 끝났으면(index >= B_COUNT) frame_b None.
    화면은 와이프 선 오른쪽이 B(없으면 검정)인 합성 그림 그대로."""
    assert frame_number(player.frame_a) == index
    if index < B_COUNT:
        assert frame_number(player.frame_b) == B_COUNT - 1 - index
    else:
        assert player.frame_b is None
    right = np.zeros_like(player.frame_a) if player.frame_b is None else player.frame_b
    expected = player.frame_a.copy()
    wipe_x = int(expected.shape[1] * player.videoWidget.wipe_position_x)
    expected[:, wipe_x:] = right[:, wipe_x:]
    np.testing.assert_array_equal(screen_image(player), expected)


def wheel(player, delta):
    """휠 한 칸 (delta > 0 위 = 다음 프레임, < 0 아래 = 이전)."""
    player.wheelEvent(QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                                  Qt.NoScrollPhase, False))


def key(player, qapp, which):
    """실제 키 입력 경로 (창이 자기 자신에 건 eventFilter가 받음)."""
    QTest.keyClick(player, which)
    qapp.processEvents()


def tick(player, count=1):
    """재생 타이머 틱을 직접 부름 (이벤트를 처리하지 않으니 진짜 타이머가 끼어들지 않음 — play_video로 타이머는 켜 둬야 함)."""
    for _ in range(count):
        player.next_frame_playback()


# ---------------------------------------------------------------- 열기

def test_open_file_pipe_sets_ui(player, pipe_log, prores_clip, dialogs):
    cap = open_pipe(player, "A", prores_clip, pipe_log)

    assert len(pipe_log.captures) == 1 and len(pipe_log.sessions) == 1  # 열면서 ffmpeg가 하나
    assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == A_COUNT
    assert player.positionScroll.maximum() == A_COUNT - 1
    assert player.frameRateComboBox.currentText() == "24"  # detect_fps
    assert player.labelTotalFrames.text().startswith(f"Total: {A_COUNT}")
    assert player.timeLabel.text().endswith(player.format_time((A_COUNT - 1) / 24))
    assert player.filenameLabel.text() == "A: numbered_4444.mov"
    assert_showing(player, 0)  # 첫 화면 = 0번 프레임 (open_file의 display_first_frame)
    assert dialogs.messages == []


# ---------------------------------------------------------------- 화살표·휠 한 칸

def test_arrow_and_wheel_steps(player, pipe_log, prores_clip, qapp):
    """오른쪽/왼쪽 화살표와 휠로 한 칸씩 — 화면에 간 프레임 번호가 늘 정확. 링 버퍼 안의 뒤로 가기는 ffmpeg를 다시 띄우지 않고
    (세션·pid 불변), 링 밖으로 나가면 다시 띄우지만 그래도 정확."""
    cap = open_pipe(player, "A", prores_clip, pipe_log)
    session, pid = cap._session, cap._session.proc.pid

    def step(how, expected):
        {"right": lambda: key(player, qapp, Qt.Key_Right), "left": lambda: key(player, qapp, Qt.Key_Left),
         "wheel_up": lambda: wheel(player, 120), "wheel_down": lambda: wheel(player, -120)}[how]()
        assert_showing(player, expected)

    def assert_no_restart():
        assert cap._session is session and cap._session.proc.pid == pid and len(pipe_log.sessions) == 1

    # 앞으로: 화살표 3칸, 휠 위로 링 안쪽 한계까지 넘기도록 (KEEP_BEHIND + 4)
    top = KEEP_BEHIND + 4
    for index in range(1, 4):
        step("right", index)
    for index in range(4, top + 1):
        step("wheel_up", index)
    assert_no_restart()

    # 뒤로 가기 — 링 버퍼 (최근 꺼낸 KEEP_BEHIND장)의 가장 오래된 장까지: 화살표와 휠을 번갈아, ffmpeg는 그대로
    oldest = top - (KEEP_BEHIND - 1)
    for index in range(top - 1, oldest - 1, -1):
        step("left" if index % 2 else "wheel_down", index)
    assert_no_restart()
    for index in range(oldest + 1, top + 1):  # 다시 앞으로 — 링의 나머지를 지나 스트림 현재 위치까지 이어짐
        step("right" if index % 2 else "wheel_up", index)
    assert_no_restart()
    for index in range(top - 1, oldest - 1, -1):
        step("left", index)
    assert_no_restart()

    # 링 밖 한 칸 뒤: 재시작(새 ffmpeg, 옛것은 끝남)하지만 착지는 정확하고 이어서 앞으로도 정확
    step("left", oldest - 1)
    assert cap._session is not session and len(pipe_log.sessions) == 2
    assert_session_gone(session)
    step("right", oldest)
    step("wheel_up", oldest + 1)

    # 끝: 마지막 프레임에서 더 앞으로 가지 않음
    player.seek_to_frame(A_COUNT)
    assert_showing(player, A_COUNT - 1)
    step("right", A_COUNT - 1)
    step("wheel_up", A_COUNT - 1)
    step("left", A_COUNT - 2)


# ---------------------------------------------------------------- 슬라이더 탐색

def test_slider_seek(player, pipe_log, prores_clip):
    cap = open_pipe(player, "A", prores_clip, pipe_log)
    rng = random.Random(SEED)

    # seek_to_frame (휠·재생이 쓰는 탐색) — 무작위 5곳, 순서도 무작위라 앞뒤로 뛴다
    targets = rng.sample(range(A_COUNT), 5)
    for index in targets:
        player.seek_to_frame(index + 1)
        assert_showing(player, index, f"seek_to_frame 지점 {targets}, 지금 {index}")

    # 진짜 슬라이더 (positionScroll 값 변경 → on_slider_value_changed → _precise_seek) — 처음·끝 근처·무작위
    slider_targets = [0, A_COUNT - 1] + rng.sample(range(1, A_COUNT - 6), 4)
    for index in slider_targets:
        player.positionScroll.setValue(index)
        note = f"슬라이더 지점 {slider_targets}, 지금 {index}"
        assert frame_number(player.frame_a) == index, note
        assert frame_number(screen_image(player)) == index, note
        assert player.labelFrameCount.text() == f"Current: {index + 1}", note
    assert cap.isOpened() and len(pipe_log.sessions) >= 2  # 먼 지점들은 재시작으로 갔음 (이 시험이 탐색 경로를 실제로 탔다)


# ---------------------------------------------------------------- A/B 와이프

def test_wipe_ab_pipe(player, pipe_log, prores_clip, reversed_clip, windows, qapp):
    cap_a = open_pipe(player, "A", prores_clip, pipe_log)
    cap_b = open_pipe(player, "B", reversed_clip, pipe_log)
    assert cap_a is not cap_b and cap_a._session.proc.pid != cap_b._session.proc.pid  # ffmpeg가 따로
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)
    assert player.videoWidget.wipeEnabled and player.videoWidget.wipe_enabled_x

    # 탐색은 A·B를 같이 맞춤 — 앞뒤로 뛰고, 인접 인덱스·B의 마지막 장도
    for index in (0, 1, 2, 40, 41, B_COUNT - 1, 30, 3):
        player.seek_to_frame(index + 1)
        assert_wipe_showing(player, index)

    # B가 끝난 뒤(A가 더 긴 클립): B는 비고 A는 정확, B는 죽지 않음 — 되돌아가면 B도 다시 정확
    for index in (B_COUNT, A_COUNT - 1, B_COUNT + 5):
        player.seek_to_frame(index + 1)
        assert_wipe_showing(player, index)
    assert cap_b.isOpened()
    for index in (50, 7):
        player.seek_to_frame(index + 1)
        assert_wipe_showing(player, index)

    # 재생 틱 — 둘을 같이 앞으로, 도중에 B가 끝나도 A는 계속
    player.seek_to_frame(50 + 1)
    player.play_video()
    for index in (51, 52, 53):
        tick(player)
        assert_wipe_showing(player, index)
    player.seek_to_frame(B_COUNT - 3 + 1)
    for index in range(B_COUNT - 2, B_COUNT + 4):  # B의 마지막 장(B_COUNT - 1)을 지나 끝난 뒤까지
        tick(player)
        assert_wipe_showing(player, index)
    player.pause_video()
    assert cap_a.isOpened() and cap_b.isOpened()

    qapp.processEvents()
    assert windows == []  # 어느 쪽도 도중 실패로 알려지지 않음 (B의 정상 끝은 실패가 아님)


# ---------------------------------------------------------------- 주석 내보내기

def run_export(qapp, worker):
    """실제 QThread로 돌려 끝날 때까지 이벤트를 처리 (앱이 쓰는 방식 — 읽기는 일꾼 스레드에서) → 신호로 받은 결과."""
    result = {}
    worker.completed.connect(lambda path: result.update(done=path))
    worker.error.connect(lambda message: result.update(error=message))
    worker.status.connect(lambda message: result.setdefault("status", []).append(message))
    worker.start()
    deadline = time.monotonic() + EXPORT_TIMEOUT_S
    while not worker.wait(20):
        qapp.processEvents()
        if time.monotonic() > deadline:
            worker.stop()
            worker.wait()
            pytest.fail(f"주석 내보내기가 {EXPORT_TIMEOUT_S}초 안에 끝나지 않았습니다: {result}")
    qapp.processEvents()  # 끝날 때 올라온 마지막 신호까지
    return result


def test_annotation_export_pipe(prores_clip, pipe_log, tmp_path, qapp):
    """주석 0개로도 전 장 내보내기가 파이프 캡처로 돔 — 출력 장수 == A_COUNT, 순서도 그대로 (번호열)."""
    out = str(tmp_path / "out" / "annotated.mov")
    worker = AnnotationExportWorker(prores_clip, {}, out, external_tools.ffmpeg_path(), include_audio=True,
                                    export_mode="balanced")

    result = run_export(qapp, worker)

    assert "error" not in result, result.get("error")
    assert result["done"] == out
    assert len(pipe_log.captures) == 1 and isinstance(pipe_log.captures[0], FFmpegPipeCapture)  # 파이프로 읽었음 (cv2 아님)
    assert not pipe_log.captures[0].isOpened()  # 워커가 끝나며 놓음
    frames = read_all_frames(out)
    assert len(frames) == A_COUNT
    assert [frame_number(f) for f in frames] == list(range(A_COUNT))  # 한 장도 빠지거나 밀리지 않음 (h264 손실에도 번호는 복호됨)
    assert result["status"][-1] == f"완료: {A_COUNT}프레임 처리, 0프레임에 주석 적용"


# ---------------------------------------------------------------- 재생 끝·재생 도중 사망

def test_playback_to_the_end_is_not_a_failure(player, pipe_log, prores_clip, windows, qapp, capsys):
    """대조군: 끝까지 재생하면 정상 끝(handle_video_end → 처음으로) — 오류 창도 기록도 없음. 아래 사망 시험과 가르는 선."""
    cap = open_pipe(player, "A", prores_clip, pipe_log)
    player.seek_to_frame(A_COUNT - 1)  # 인덱스 A_COUNT - 2 (뒤에 1장 남음)
    player.play_video()
    tick(player)
    assert frame_number(player.frame_a) == A_COUNT - 1
    assert player.timer.isActive()

    tick(player)  # 읽을 장이 없음 → 끝
    assert not player.timer.isActive() and player.playPauseButton.text() == "Play"
    # stop_video가 처음으로 되돌림. (프레임 라벨은 보지 않음: 끝에서 처음으로 돌아올 때 update_position_info가 옛 슬라이더 값으로
    # 라벨을 정해 "Current: 120"이 한 번 남는 기존 동작이 cv2 캡처에서도 똑같음 — 파이프와 무관)
    assert frame_number(player.frame_a) == 0 and frame_number(screen_image(player)) == 0
    assert player.positionScroll.value() == 0 and player.overlaySlider.value() == 0
    assert cap.isOpened()
    qapp.processEvents()
    assert windows == [] and FAILURE_HEADLINE not in capsys.readouterr().err


def test_player_survives_mid_death(player, pipe_log, prores_clip, windows, dialogs, qapp, capsys):
    """재생 중 ffmpeg를 밖에서 죽이면: 앱(플레이어)은 죽지 않고, 알림은 기록·오류 창 모두 한 번, 재생은 끝난 모습."""
    cap = open_pipe(player, "A", prores_clip, pipe_log)
    player.play_video()
    assert player.timer.isActive()
    tick(player, 5)
    assert frame_number(player.frame_a) == 5
    session = cap._session
    assert wait_for(lambda: len(session._frames) == READAHEAD_FRAMES)  # 선읽기 큐가 참 → ffmpeg는 아직 한참 남은 중간
    capsys.readouterr()  # 지금까지의 출력은 버림 (죽은 뒤의 기록만 센다)

    session.proc.kill()
    assert wait_for(lambda: session.proc.poll() is not None)

    # 재생 틱이 몇 번 도는 동안 앱은 죽지 않음: 큐에 남은 정상 프레임(큐 READAHEAD_FRAMES장 + 읽기 스레드가 손에 든 1장까지)은
    # 끊김 없이 이어 보이고(5 다음 번호부터), 그 뒤 끊김을 만나 재생이 끝남 (예외 없이). 영상 끝으로 위장하지 않으려고 번호 연속성을 본다.
    max_ticks = READAHEAD_FRAMES + 6
    shown = []
    for _ in range(max_ticks):
        tick(player)
        if not player.timer.isActive():
            break
        shown.append(frame_number(player.frame_a))
    assert not player.timer.isActive(), f"사망 뒤 {max_ticks}틱 안에 재생이 끝나지 않았습니다 (본 번호 {shown})"
    assert shown == list(range(6, 6 + len(shown)))
    assert len(shown) >= READAHEAD_FRAMES - 1  # 큐에 남은 정상 프레임을 다 보여 준 뒤에야 끝남

    # 끝난 모습: 재생 단추 Play, 죽은 cv2 캡처와 같은 겉모습 (read가 (False, None))
    assert player.playPauseButton.text() == "Play"
    assert not cap.isOpened() and cap._session is None
    assert cap.read() == (False, None)
    assert cap.get(POS) == 0.0 and cap.set(POS, 0) is False

    # 알림은 기록 한 번 + 오류 창 한 번 (Qt 루프에서)
    qapp.processEvents()
    assert len(windows) == 1
    assert FAILURE_HEADLINE in windows[0] and prores_clip in windows[0]
    assert capsys.readouterr().err.count(FAILURE_HEADLINE) == 1

    # 죽은 뒤에 사용자가 아무 조작을 해도 예외 없이 지나가고 알림이 되풀이되지 않음 (재생 단추의 글자는 보지 않음: 죽은 캡처에서
    # Play를 누르면 play_video가 fps 0이라 타이머를 켜지 않은 채 단추만 'Pause'로 바꾸는 플레이어 쪽 동작이 있음)
    tick(player)
    player.next_frame()
    player.prev_frame()
    player.seek_to_frame(10)
    player.positionScroll.setValue(50)
    key(player, qapp, Qt.Key_Right)
    wheel(player, -120)
    player.play_video()
    tick(player)
    player.pause_video()
    qapp.processEvents()
    assert len(windows) == 1 and FAILURE_HEADLINE not in capsys.readouterr().err
    assert dialogs.errors() == []  # 오류 창 경로 말고 따로 뜬 창도 없음
    assert_session_gone(session)

    # 앱은 살아 있음: 같은 영상을 다시 열면 새 파이프로 정상 재생
    reopened = open_pipe(player, "A", prores_clip, pipe_log)
    assert reopened is not cap
    assert_showing(player, 0)
    key(player, qapp, Qt.Key_Right)
    assert_showing(player, 1)
    assert len(windows) == 1
