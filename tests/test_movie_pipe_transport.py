"""ffmpeg 파이프 캡처의 전송 계층 (yesoncheck/movie_pipe_source.py, Task 3b): ffmpeg 출력을 파이프가 아니라 소켓으로 받아 프레임
한 장을 recv_into(MSG_WAITALL) 한 번 — GIL을 한 번 놓고 한 번 다시 잡음 — 으로 받는다. 파이프(64KB씩 수백 번 read, 호출마다 GIL
재획득)였을 때 GUI 스레드가 파이썬을 실행하는 동안 읽기 스레드가 멈춰 4K 재생이 실시간을 밑돌던 원인(15fps)의 회귀 방지.

- 프레임당 recv 1회 — 세션의 recv_calls 카운터로 구조 단언 (결정적).
- 메인 스레드가 GIL을 쥐고 있어도 읽기 스레드가 프레임을 받아 둠 — 시간 단언 (근거 수치는 그 시험의 docstring).
- 막힌 recv를 다른 스레드의 release가 깨움 — hang 보호(take(READ_TIMEOUT_S) → stop()의 shutdown+close)의 증명.
- Windows 경로(TCP 리스너: accept·peer 확인·EOF·정리·접속 실패)를 이 플랫폼에서 sys.platform 바꿔치기로 (Windows 실기는 CI).
  peer가 127.0.0.1이 아닌 경우는 한 대의 기계에서 만들 수 없어(리스너가 127.0.0.1에만 묶임) 시험하지 않는다.
"""

import re
import statistics
import sys
import threading
import time
from fractions import Fraction

import cv2
import pytest

from tests.prores_clips import frame_number, make_numbered_clip
from tests.test_movie_pipe_capture import (  # noqa: F401 (windows: fixture)
    WAIT_S, assert_dead, assert_session_gone, open_capture, read_until_false, stand_in_command, use_tcp, wait_for, windows,
)
from yesoncheck import external_tools, movie_pipe_source
from yesoncheck.movie_pipe_source import (
    FAILURE_HEADLINE, KEEP_BEHIND, READAHEAD_FRAMES, FFmpegPipeCapture, MovieProbe, PipeCaptureError, probe_movie,
)

COUNT = 120
UHD_WIDTH, UHD_HEIGHT = 3840, 2160
GIL_HOLD_MS = 50  # 메인 스레드가 GIL을 쥐는 시간 (4K 재생 틱의 GUI 파이썬 몫 ~22ms보다 넉넉히 — 40ms가 아닌 근거는 그 시험)
GIL_ROUNDS = 24  # 정상 상태에서 재는 회차
WARM_FRAMES = KEEP_BEHIND + READAHEAD_FRAMES + 2  # 읽기 스레드가 이만큼 받으면 보관본 풀이 한 바퀴 — 새 할당이 끝난 정상 상태
WARMUP_ROUNDS_MAX = 40  # 이 안에 큐가 한 번도 차지 않으면(정상 상태에 닿지 못하면) 실패 — 파이프면 여기서 떨어짐
UHD_COUNT = WARMUP_ROUNDS_MAX + GIL_ROUNDS + READAHEAD_FRAMES + 2  # 기동이 한도까지 걸려도 재는 동안 끝에 닿지 않게
QUEUED_MEAN_MIN = READAHEAD_FRAMES - 1  # 근거: test_reader_keeps_up_while_main_thread_holds_gil
TCP_OUTPUT = re.compile(r"tcp://127\.0\.0\.1:\d+\?send_buffer_size=" + str(movie_pipe_source.SOCKET_BUFFER_BYTES // 2))


# ---------------------------------------------------------------- 클립 (session: 인코딩 반복 방지)

@pytest.fixture(scope="session")
def prores_clip(tmp_path_factory):
    """4444 120장 24fps 번호 클립 (320×180)."""
    path = str(tmp_path_factory.mktemp("transport_4444") / "numbered_4444.mov")
    make_numbered_clip(path, count=COUNT, fps="24", profile="4", pix_fmt="yuv444p10le")
    return path


# ---------------------------------------------------------------- 도구

def stand_in_probe(count, width=4, height=2):
    """대역 프로세스용 probe (bgr24 width×height, 24fps, count장)."""
    return MovieProbe(codec="prores", width=width, height=height, r=Fraction(24), avg=Fraction(24), nb_frames=count,
                      duration_ts=count * 512, time_base=Fraction(1, 12288), video_start=0.0, format_start=0.0,
                      rotation=0, sar_ok=True)


def in_recv(thread):
    """thread가 지금 _PipeSession._recv_into 안(소켓 recv에서 기다림)인가 — 그 스레드의 스택을 들여다봄."""
    code = movie_pipe_source._PipeSession._recv_into.__code__
    frame = sys._current_frames().get(thread.ident)
    while frame is not None:
        if frame.f_code is code:
            return True
        frame = frame.f_back
    return False


def hold_gil(ms):
    """ms 동안 순수 파이썬 루프 — GIL을 쥔 채 (GUI 스레드가 process_frame·update_frame 같은 파이썬 코드를 도는 모습)."""
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        pass


@pytest.fixture
def sessions(monkeypatch):
    """캡처가 띄운 세션을 차례로 기록 (실패한 생성자의 세션까지 — 정리 단언용)."""
    created = []

    class RecordingSession(movie_pipe_source._PipeSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(movie_pipe_source, "_PipeSession", RecordingSession)
    return created


# ---------------------------------------------------------------- 프레임당 recv 1회

def test_one_recv_per_frame(prores_clip):
    """순차로 끝까지 읽으면 세션의 recv_calls(프레임 바이트를 받은 recv 호출 수) == 프레임 수 — 파이프였으면 한 장(172.8KB)에
    read 여러 번. 정상 EOF까지 온 것 자체가 자식에게 넘긴 소켓 끝을 부모가 닫았다는 증거 (안 닫으면 EOF가 오지 않아 시간 초과)."""
    cap = open_capture(prores_clip)
    try:
        session = cap._session
        assert session.proc.stdout is None  # ffmpeg 출력은 파이프가 아님
        assert [frame_number(f) for f in read_until_false(cap)] == list(range(COUNT))
        assert cap.isOpened()  # 정상 EOF
        assert session.recv_calls == session.frames_received == COUNT
    finally:
        cap.release()
    assert_session_gone(session)


def color_source_command(path, output, seek_seconds=None):
    """_pipe_command 자리: 진짜 ffmpeg가 진짜 전송(output)으로 4K bgr24를 내되 입력은 lavfi 단색(bgr24 그대로 — 디코드·변환 없음).
    전송만 재려고 디코드 속도(러너마다 다름)를 뺀다. path는 쓰지 않음."""
    return [external_tools.ffmpeg_path(), "-nostdin", "-v", "error", "-f", "lavfi",
            "-i", f"color=c=gray:size={UHD_WIDTH}x{UHD_HEIGHT}:rate=24,format=bgr24", "-frames:v", str(UHD_COUNT),
            "-f", "rawvideo", "-pix_fmt", "bgr24", output]


def queue_under_gil(cap, hold_ms):
    """[GIL을 hold_ms 쥠 → 큐 길이 기록 → read()]를 돌림 → (기동 회차 수 또는 None, 기동 중 큐, 정상 상태 GIL_ROUNDS회의 큐).

    기동: 큐가 한 번이라도 가득(READAHEAD_FRAMES)이 됐고 읽기 스레드가 WARM_FRAMES장 이상 받을 때까지 — 보관본 풀이 한 바퀴 돌아
    새 4K 할당·첫 페이지 폴트가 끝난 정상 상태. WARMUP_ROUNDS_MAX회 안에 닿지 못하면 None (큐가 끝내 한 번도 안 참 — 실패).
    그 뒤 GIL_ROUNDS회를 잰다. test_reader_keeps_up_while_main_thread_holds_gil과 그 재측정 하니스가 같이 쓴다."""
    session = cap._session
    warm, full_seen = [], False
    while not (full_seen and session.frames_received >= WARM_FRAMES):
        if len(warm) == WARMUP_ROUNDS_MAX:
            return None, warm, []
        hold_gil(hold_ms)
        warm.append(len(session._frames))
        full_seen = full_seen or warm[-1] >= READAHEAD_FRAMES
        ok, frame = cap.read()
        assert ok and frame.shape == (UHD_HEIGHT, UHD_WIDTH, 3), len(warm)
    queued = []
    for i in range(GIL_ROUNDS):
        hold_gil(hold_ms)
        queued.append(len(session._frames))  # 메인이 GIL을 쥔 동안 읽기 스레드가 받아 둔 결과
        ok, frame = cap.read()
        assert ok and frame.shape == (UHD_HEIGHT, UHD_WIDTH, 3), i
    return len(warm), warm, queued


def test_reader_keeps_up_while_main_thread_holds_gil(monkeypatch, tmp_path):
    """이 전송 교체의 존재 이유: 메인 스레드가 GIL을 GIL_HOLD_MS(50ms) 쥘 때마다(4K 재생 틱의 GUI 파이썬 몫) 읽기 스레드는 그동안
    프레임을 받아 둔다. 4K bgr24(24.9MB/장)를 디코드 없는 단색 입력으로(color_source_command) [GIL 50ms 쥠 → read()]를 돌려
    (queue_under_gil): ① 큐가 WARMUP_ROUNDS_MAX회 안에 한 번은 가득 차고 보관본 풀이 한 바퀴 돎(정상 상태에 닿음) ② 그 뒤 24회의
    read() 직전 큐 평균 ≥ 5 (READAHEAD_FRAMES − 1 — 거의 늘 가득).

    겹침이 되면(소켓 + MSG_WAITALL: 한 장을 GIL을 놓은 채 syscall 한 번으로 받음) 큐는 늘 가득이다. 파이프면 한 장이 read 수백 번이고
    호출마다 GIL을 다시 잡아야 해서 메인이 쥔 동안 진척이 느려 큐가 비어 간다 — 큐가 끝내 차지 않아 ①에서 떨어진다. 정상 상태만 재는
    까닭: 읽기 스레드가 링 보관본도 만들게 된 뒤(한 장에 GIL을 recv 뒤·복사 뒤 두 번 다시 잡음) 기동 구간 — 보관본 풀이 새 4K 버퍼
    ~16개를 할당하며 첫 페이지 폴트를 치르는 동안 — 만 느려, 부하 아래 처음 8~15회차 큐가 1~2에 머물다 6으로 올라 머무는 모양으로
    흔들렸다(기동 4회만 빼던 옛 지표: 부하 6~16에서 50ms로도 12/40 실패). 정상 상태는 그와 무관하게 가득이다.
    측정 (2026-10-29 Mac x86_64, 이 지표 그대로 — /tmp 재측정 하니스가 queue_under_gil을 불러 판을 번갈아 돌림. "GUI 복사"는
    보관본 복사를 GUI 스레드에서 하던 판의 흉내, "파이프"는 교체 전 모듈):
    - 50ms(채택): 지금 코드 실패 0/64 — 부하 17~35에서 24회(기동 10~21회, 정상 상태 평균 최소 6.00), 바쁜 프로세스 8개를 더한
      부하 17~30에서 20회(기동 10~16, 최소 5.67·중앙 5.94), 16개를 더한 부하 ~110에서 20회(기동 10~12, 6.00). GUI 복사 판 0/64(기동
      10~12). 파이프는 4/4 실패 — 40회 내내 큐 0~1.
    - 40ms: 지금 코드 2/24 실패(부하 12 — 큐가 다섯~여섯 회차마다 한 장씩만 차올라 40회 안에 가득에 못 닿음, 기동 16~36, 정상 상태
      최소 5.33), 바쁜 프로세스 8개를 더하면 0/20이지만 정상 상태 최소 5.21. 읽기 스레드가 한 장에 GIL을 recv 뒤·복사 뒤 두 번 다시
      잡느라 40ms 쥠 아래 공급이 소비를 겨우 넘어서라, 50ms로 둔다(GUI 복사 판은 40ms에서도 기동 10회·6.00). 파이프는 40ms에서도 0~1.
    프레임당 여러 번 읽는 전송으로 돌아가는 회귀는 결정적인 test_one_recv_per_frame이 먼저 잡는다. 1080p는 macOS 파이프(커지는
    버퍼)로도 흔들려 가르지 못했고, 실제 ProRes 클립은 러너의 디코드 속도가 섞여 단색 입력을 쓴다.

    read()의 대기 시간은 단언하지 않는다: 큐 상태·링 처리·깨어난 읽기 스레드와의 GIL 주고받기가 섞여 전송을 바로 보지 못한다
    (1080p ProRes 측정: 파이프 3.6~7.3ms, 소켓 4.4~16.1ms — 거꾸로이기도). 받아 둔 장 수는 전송이 GIL에 막히는지를 바로 보는 값이다.
    재시도·다수결 같은 완화는 쓰지 않는다 (실패하면 진짜 회귀이거나 러너가 한도 밖으로 느린 것 — 메시지의 회차별 큐로 가린다;
    Windows는 TCP 전송의 처리량도 함께 본다)."""
    monkeypatch.setattr(movie_pipe_source, "_pipe_command", color_source_command)
    cap = FFmpegPipeCapture(str(tmp_path / "color.mov"), stand_in_probe(UHD_COUNT, UHD_WIDTH, UHD_HEIGHT))
    try:
        session = cap._session
        warm_rounds, warm, queued = queue_under_gil(cap, GIL_HOLD_MS)
    finally:
        cap.release()
    assert warm_rounds is not None, (f"GIL을 {GIL_HOLD_MS}ms 쥐는 동안 큐가 {WARMUP_ROUNDS_MAX}회 안에 한 번도 차지 않았습니다 "
                                     f"(받은 장 {session.frames_received}) — 기동 중 큐 {warm}")
    mean = statistics.fmean(queued)
    assert mean >= QUEUED_MEAN_MIN, (f"GIL을 {GIL_HOLD_MS}ms 쥔 뒤(정상 상태 — 기동 {warm_rounds}회 뒤) 큐에 받아 둔 장 수 평균 "
                                     f"{mean:.2f} < {QUEUED_MEAN_MIN} — 회차별 큐 {queued}, 기동 중 큐 {warm}")
    # 4K 한 장(24.9MB)도 MSG_WAITALL로 recv 한 번 — release가 받던 장을 끊었으면 그 덜 받은 한 번이 더 (+1)
    session.reader.join(WAIT_S)
    assert not session.reader.is_alive()
    assert session.frames_received >= GIL_ROUNDS and session.recv_calls <= session.frames_received + 1, \
        (session.recv_calls, session.frames_received)


# ---------------------------------------------------------------- 막힌 recv 깨우기 (hang 보호)

@pytest.mark.parametrize("transport", ["native", "tcp"])
def test_stop_wakes_blocked_recv(transport, monkeypatch, tmp_path, capsys):
    """recv에서 막힌 읽기 스레드(대역이 한 장만 주고 소켓을 쥔 채 잠듦)와 큐에서 기다리는 read(): 다른 스레드의 release가 1초
    안에 돌아오고, read는 (False, None), 읽기 스레드는 1초 안에 recv를 벗어남. stop()의 kill은 막아 둬서(대역은 살아서 소켓을
    쥔 채) 깨운 것이 프로세스 종료가 아니라 shutdown+close임을 가른다. 이것이 소켓 수준 타임아웃 없이도 멈춘 ffmpeg에 막히지 않는
    근거다 (read의 READ_TIMEOUT_S 실패 → stop → 같은 깨우기)."""
    script = ("out = open_output(sys.argv[1]); out.write(bytes(4 * 2 * 3)); out.flush()\n"
              "import time; time.sleep(60)\n")
    monkeypatch.setattr(movie_pipe_source, "_pipe_command", stand_in_command(script))
    if transport == "tcp":
        use_tcp(monkeypatch)
    cap = FFmpegPipeCapture(str(tmp_path / "stand_in.mov"), stand_in_probe(count=3))
    session = cap._session
    real_kill = session.proc.kill
    session.proc.kill = lambda: None  # stop()의 kill을 막음 — 깨우는 길은 shutdown+close뿐
    try:
        assert cap.read()[0]
        result = {}
        worker = threading.Thread(target=lambda: result.update(read=cap.read()))
        worker.start()
        assert wait_for(lambda: in_recv(session.reader)), "읽기 스레드가 recv에서 기다리는 상태가 되지 않았습니다"
        time.sleep(0.1)  # 일꾼의 read()가 빈 큐에서 기다리게
        assert worker.is_alive()
        started = time.monotonic()
        cap.release()
        assert time.monotonic() - started < 1
        worker.join(1)
        assert not worker.is_alive() and result["read"] == (False, None)
        assert wait_for(lambda: not in_recv(session.reader), timeout=1), "release가 막힌 recv를 1초 안에 깨우지 않았습니다"
        assert session.proc.poll() is None  # 대역은 아직 살아 소켓을 쥐고 있음 — 깨운 것은 shutdown+close
    finally:
        del session.proc.kill
        real_kill()
    assert_session_gone(session)
    assert session.failure is None  # 일부러 끝낸 세션 — 실패 아님
    assert FAILURE_HEADLINE not in capsys.readouterr().err


# ---------------------------------------------------------------- Windows 경로 (TCP 리스너)

def test_tcp_transport_reads_to_eof(prores_clip, monkeypatch, capsys):
    """TCP 경로: 출력 대상 tcp://127.0.0.1:<포트>, 접속 하나 받기(peer 127.0.0.1 확인 통과), 프레임당 recv 1회, 번호 순서 그대로
    정상 EOF, release 뒤 리스너·접속 소켓·프로세스·스레드 정리."""
    probe = probe_movie(prores_clip)
    use_tcp(monkeypatch)
    cap = FFmpegPipeCapture(prores_clip, probe)
    try:
        session = cap._session
        assert TCP_OUTPUT.fullmatch(session.command[-1]), session.command
        assert session.proc.stdout is None
        assert [frame_number(f) for f in read_until_false(cap)] == list(range(COUNT))
        assert cap.isOpened() and session.recv_calls == COUNT
    finally:
        cap.release()
    assert_session_gone(session)
    assert FAILURE_HEADLINE not in capsys.readouterr().err


def test_tcp_ffmpeg_exits_without_connecting(tmp_path, monkeypatch, sessions):
    """TCP 경로에서 ffmpeg가 접속도 못 하고 끝남(깨진 파일): 생성자가 CONNECT_TIMEOUT_S를 다 기다리지 않고 PipeCaptureError —
    원인(접속하지 않고 끝남·종료 코드)·명령·stderr 전문. 리스너·프로세스·스레드 정리."""
    broken = tmp_path / "broken.mov"
    broken.write_bytes(b"this is not a movie" * 100)
    use_tcp(monkeypatch)
    started = time.monotonic()
    with pytest.raises(PipeCaptureError) as raised:
        FFmpegPipeCapture(str(broken), stand_in_probe(count=120, width=320, height=180))
    assert time.monotonic() - started < movie_pipe_source.CONNECT_TIMEOUT_S / 2
    error = raised.value
    assert "접속하지 않고 끝났습니다" in str(error) and "종료 코드" in str(error)
    assert TCP_OUTPUT.fullmatch(error.command[-1]) and "Invalid data" in error.stderr
    assert len(sessions) == 1
    assert_session_gone(sessions[0])


def test_tcp_connect_timeout(tmp_path, monkeypatch, sessions):
    """TCP 경로에서 ffmpeg가 CONNECT_TIMEOUT_S 안에 접속하지 않음(대역이 stderr에 글만 쓰고 잠듦): 생성자가 PipeCaptureError —
    원인(시간 초과)·stderr 전문. 잠든 대역은 kill돼 거둬지고 리스너·스레드 정리."""
    monkeypatch.setattr(movie_pipe_source, "CONNECT_TIMEOUT_S", 0.5)
    script = "sys.stderr.write('stand-in never connects\\n'); sys.stderr.flush()\nimport time; time.sleep(60)\n"
    monkeypatch.setattr(movie_pipe_source, "_pipe_command", stand_in_command(script))
    use_tcp(monkeypatch)
    with pytest.raises(PipeCaptureError) as raised:
        FFmpegPipeCapture(str(tmp_path / "stand_in.mov"), stand_in_probe(count=3))
    error = raised.value
    assert "0.5초 안에 출력 소켓" in str(error) and "stand-in never connects" in error.stderr
    assert len(sessions) == 1
    assert_session_gone(sessions[0])


def test_tcp_restart_connect_failure_dies_without_raising(prores_clip, monkeypatch, sessions, qapp, windows, capsys):
    """TCP 경로의 탐색 재시작에서 새 ffmpeg가 접속하지 않고 끝남: read는 예외 없이 (False, None) — 죽은 cv2 캡처 겉모습, 기록
    1회(원인·stderr 전문), 오류 창 1회(Qt 루프). 접속 실패도 다른 도중 실패와 같은 길(§5.5)로 흡수된다."""
    probe = probe_movie(prores_clip)
    use_tcp(monkeypatch)
    cap = FFmpegPipeCapture(prores_clip, probe)
    try:
        assert frame_number(cap.read()[1]) == 0
        script = "sys.stderr.write('restart stand-in gives up\\n'); sys.stderr.flush(); sys.exit(3)\n"
        monkeypatch.setattr(movie_pipe_source, "_pipe_command", stand_in_command(script))
        assert cap.set(cv2.CAP_PROP_POS_FRAMES, 100) is True
        assert cap.read() == (False, None)
        assert_dead(cap)
        log = capsys.readouterr().err
        assert log.count(FAILURE_HEADLINE) == 1, log
        assert "접속하지 않고 끝났습니다" in log and "종료 코드 3" in log and "restart stand-in gives up" in log
        qapp.processEvents()
        assert len(windows) == 1 and prores_clip in windows[0].text
    finally:
        cap.release()
    assert len(sessions) == 2
    for session in sessions:
        assert_session_gone(session)
