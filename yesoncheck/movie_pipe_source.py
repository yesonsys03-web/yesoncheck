"""ffmpeg 파이프 프레임 소스: 판정(probe_movie·pipe_eligible)과 cv2.VideoCapture 자리에 꽂는 캡처(FFmpegPipeCapture).

판정: ffprobe 한 번으로 영상 파일의 모양을 읽고(probe_movie), ffmpeg 파이프로 읽어도 cv2와 같은 프레임이 같은 번호로 나올
파일인지 가른다(pipe_eligible). 게이트는 양성 증거로만 켜진다 — 한 조건이라도 확인하지 못하면(값이 없거나 맞지 않으면) 거짓이라
기존 cv2 경로로 간다. probe_movie는 오류를 삼키지 않는다: ffprobe가 파일을 못 읽으면(RuntimeError)도, 결과 해석이 어긋나도
(KeyError·ValueError·TypeError…) 그대로 올라간다 — cv2로 돌릴지는 부른 쪽이 정한다.

캡처: ffmpeg 프로세스 하나(세션)가 bgr24 원시 프레임을 stdout으로 내보내고, 읽기 스레드가 그것을 유한 큐에 미리 받아 둔다.
실패는 캡처 안에서 끝난다 (스펙 §5.5): 생성자만 PipeCaptureError를 올리고, 그 뒤의 read·get·set은 예외를 내지 않는다 — 도중에
끊기면 죽은 cv2 캡처와 같은 겉모습이 되고, 기록(stderr)에 한 번, 오류 창은 Qt 루프에서 한 번 알린다.
Qt(PyQt5)와 error_window는 알릴 때만 불러온다 — 판정은 Qt 없이도 쓴다.
"""

import collections
import math
import os
import subprocess
import sys
import threading
import traceback
import weakref
from dataclasses import dataclass
from fractions import Fraction

import cv2
import numpy as np

from yesoncheck.external_tools import (
    MAX_FRAME_RATE, _frame_rate, _probe, _start_seconds, decode_output, ffmpeg_path, ffprobe_path, subprocess_kwargs,
)

PIPE_CODECS = ("prores",)
SOURCE_MODE_ENV = "YESONCHECK_MOVIE_SOURCE"
SOURCE_MODES = ("auto", "pipe", "cv2")  # 환경 변수가 받는 값 (없거나 비어 있으면 "auto")
UNSPECIFIED_SAR = (None, "1:1", "0:1")  # ffprobe의 sample_aspect_ratio: 없음·정사각형·미지정(0:1)

READAHEAD_FRAMES = 6  # 캡처마다 미리 받아 두는 프레임 수 (4K bgr24 ≈ 24MB/장 → ~143MB) — 스펙 §5.3
READ_TIMEOUT_S = 30.0  # read()·생성자가 빈 큐를 기다리는 한도: 넘으면 멈춘 ffmpeg(NFS hard mount 등)로 보고 실패 처리
LOG_PREFIX = "[파이프]"
FAILURE_HEADLINE = "영상을 읽던 ffmpeg 파이프가 도중에 끊겨 이 영상을 더 읽을 수 없습니다"  # 도중 실패의 기록·오류 창 첫 줄


@dataclass(frozen=True)
class MovieProbe:
    """첫 영상 트랙(attached_pic 제외)의 ffprobe 값 중 게이트에 쓰는 것. 없는 값은 None·0·""(영상 트랙이 없으면 전부).

    width·height는 ffprobe가 준 그대로 — 화소 비율(SAR)을 곱하지도 회전으로 바꾸지도 않는다 (게이트가 둘 다 없는 파일만
    통과시키므로 cv2가 주는 크기와 같다)."""

    codec: str
    width: int
    height: int
    r: Fraction | None  # r_frame_rate (_frame_rate: 0/0·0 이하·MAX_FRAME_RATE 초과는 None)
    avg: Fraction | None  # avg_frame_rate (같은 규칙)
    nb_frames: int | None
    duration_ts: int | None  # time_base 단위
    time_base: Fraction | None
    video_start: float  # 영상 트랙 start_time (초, 음수도 있음)
    format_start: float  # 컨테이너 start_time (초)
    rotation: int  # 디스플레이 행렬의 회전 (도, 반올림)
    sar_ok: bool  # 화소 비율이 없거나 1:1


def _optional_int(value):
    """ffprobe 정수 글(nb_frames "120"·duration_ts 61440). 없거나 "N/A"면 None."""
    return None if value in (None, "N/A") else int(value)


def _rotation(video):
    """디스플레이 행렬의 회전 (external_tools._display_size가 읽는 자리와 같음). 없으면 0."""
    return round(float(next((d["rotation"] for d in video.get("side_data_list", []) if "rotation" in d), 0)))


def probe_movie(path):
    """path의 첫 영상 트랙을 ffprobe(1회)로 읽은 MovieProbe. 영상 트랙이 없으면 값이 모두 빈 probe (게이트는 거짓)."""
    info = _probe(ffprobe_path(), path)
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"
                  and s.get("disposition", {}).get("attached_pic") != 1), {})
    time_base = video.get("time_base")
    return MovieProbe(
        codec=video.get("codec_name", ""),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        r=_frame_rate(video.get("r_frame_rate")),
        avg=_frame_rate(video.get("avg_frame_rate")),
        nb_frames=_optional_int(video.get("nb_frames")),
        duration_ts=_optional_int(video.get("duration_ts")),
        time_base=Fraction(time_base) if time_base else None,
        video_start=_start_seconds(video.get("start_time")),
        format_start=_start_seconds(info.get("format", {}).get("start_time")),
        rotation=_rotation(video),
        sar_ok=video.get("sample_aspect_ratio") in UNSPECIFIED_SAR,
    )


def pipe_eligible(probe):
    """ffmpeg 파이프로 읽어도 되는 파일인가 (스펙 §5.2 ①~⑥ 전부)."""
    if probe.codec not in PIPE_CODECS:  # ①
        return False
    if probe.r is None or not 0 < probe.r <= MAX_FRAME_RATE or probe.avg != probe.r:  # ②
        return False
    if probe.nb_frames is None or probe.nb_frames < 1 or probe.width * probe.height < 1:  # ③
        return False
    # ④ 프레임 수·길이·속도 삼자 일치 — 편집 목록으로 잘린 파일(nb_frames 120인데 재생 118)과 한 프레임이 머무는 파일을 거름
    if probe.duration_ts is None or probe.time_base is None \
            or Fraction(probe.nb_frames, 1) / probe.r != probe.duration_ts * probe.time_base:
        return False
    if probe.rotation != 0 or not probe.sar_ok:  # ⑤
        return False
    return math.isfinite(probe.video_start) and math.isfinite(probe.format_start)  # ⑥ 오프셋은 탐색이 보정


def movie_source_mode():
    """환경 변수 YESONCHECK_MOVIE_SOURCE: 없거나 비면 "auto", "auto"·"pipe"·"cv2"(대소문자 무시)는 소문자로, 그 밖은 ValueError."""
    given = os.environ.get(SOURCE_MODE_ENV, "")
    mode = given.lower() or "auto"
    if mode not in SOURCE_MODES:
        raise ValueError(f"{SOURCE_MODE_ENV}는 {', '.join(SOURCE_MODES)} 중 하나여야 합니다 (비우면 auto): {given!r}")
    return mode


# ---------------------------------------------------------------- 캡처 (스펙 §5.3·§5.5·§5.6)

class PipeCaptureError(Exception):
    """ffmpeg 파이프로 영상을 열지 못했음 — FFmpegPipeCapture 생성자만 올린다 (스펙 §5.5). 글에 원인·파일·명령·stderr 전문이 다 있다.

    command: 실행한 명령(인자 리스트), stderr: ffmpeg가 stderr에 남긴 것 전부 (없으면 "")."""

    def __init__(self, reason, command, stderr):
        super().__init__(f"{reason}\n명령: {command}\nffmpeg stderr:\n{stderr.rstrip() or '(없음)'}")
        self.command = list(command)
        self.stderr = stderr


# _PipeSession.take의 결과 종류
_FRAME, _END, _FAILED, _STOPPED, _TIMEOUT = "frame", "end", "failed", "stopped", "timeout"


def _pipe_command(path):
    """처음부터 끝까지 bgr24 원시 프레임을 stdout으로 내는 ffmpeg 명령 (스펙 §5.3). -fps_mode passthrough: 없으면 rawvideo가
    CFR에 맞추려고 프레임을 복제해 섞음(§3b). -map 0:V:0: attached_pic을 뺀 첫 영상 트랙 — probe_movie가 고른 트랙과 같음.
    경로는 인자 그대로 (비ASCII 안전). ffmpeg가 없으면 ToolNotFoundError."""
    return [ffmpeg_path(), "-nostdin", "-v", "error", "-i", path, "-map", "0:V:0", "-fps_mode", "passthrough",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]


def _read_into(stream, view):
    """바이트 memoryview를 다 채울 때까지 stream에서 읽음 → 읽은 바이트 수 (EOF면 len(view)보다 적음)."""
    filled = 0
    while filled < len(view):
        count = stream.readinto(view[filled:])
        if not count:
            break
        filled += count
    return filled


class _PipeSession:
    """ffmpeg 프로세스 하나와 그 둘레 한 덩어리 — 읽기 스레드·stderr 스레드·유한 큐·실패 칸·정지 플래그 (스펙 §5.3).

    캡처는 세션을 통째로 버린다(stop) — 옛 프로세스의 프레임·실패가 다른 세션에 섞이지 않는다.
    - stdout은 읽기 스레드만 읽는다: 프레임 크기(height*width*3바이트)씩 새 배열에 바로 읽어(readinto — 따로 복사하지 않음) 큐에
      넣고, 큐가 차면(READAHEAD_FRAMES) _cond에서 기다린다. stop()이 그 기다림을 깨운다.
    - stderr는 전용 스레드가 늘 비운다 (안 비우면 파이프가 차서 ffmpeg가 멈춤) — 모아서 실패 글에 싣는다.
    - 읽기 스레드가 끝날 때 프로세스를 거두고(wait — 좀비 없음) stdout을 닫는다 (stderr는 그 스레드가 닫음). kill해도 안 죽는
      프로세스(NFS hard mount의 D 상태)면 이 데몬 스레드만 남아 기다리고, 부른 스레드(GUI)는 막히지 않는다.
    - 실패(프레임 중간에서 끊김·0이 아닌 종료 코드·읽기 오류)는 failure에 적어 두기만 한다 — 드러내는 것은 큐를 다 비운 read()의
      몫. stop()으로 일부러 끝낸 뒤의 끊김·종료 코드는 실패가 아니다 (정지 플래그).
    _cond가 지키는 것: _frames·_stopped·_finished·failure.
    """

    def __init__(self, command, height, width):
        self.command = command
        self._shape = (height, width, 3)
        self._cond = threading.Condition()
        self._frames = collections.deque()
        self._stopped = False  # 정지 플래그: stop()이 일부러 끝냄
        self._finished = False  # 읽기 스레드가 끝남: 더 올 프레임 없음, 프로세스는 거둬졌고 failure는 확정
        self.failure = None  # 읽기 스레드가 본 실패 원인 (정상 끝·정지면 None)
        self.eof_noted = False  # 정상 끝의 stderr를 기록했는지 (세션당 한 번 — 캡처의 _lock이 지킴)
        self._stderr_chunks = []
        self.proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     **subprocess_kwargs())
        self.stderr_reader = threading.Thread(target=self._drain_stderr, name="ffmpeg-pipe-stderr", daemon=True)
        self.reader = threading.Thread(target=self._read_frames, name="ffmpeg-pipe-read", daemon=True)
        self.stderr_reader.start()
        self.reader.start()

    def stderr_text(self):
        """지금까지 받은 stderr (읽기 스레드가 끝났으면 전부)."""
        return decode_output(b"".join(list(self._stderr_chunks)))

    def take(self, timeout, remove=True):
        """다음 프레임을 기다림 → (_FRAME, 배열) / (_END, None) 정상 끝 / (_FAILED, 원인) / (_STOPPED, None) / (_TIMEOUT, None).
        큐에 남은 프레임은 실패보다 먼저 준다. remove=False면 프레임을 큐에 둔 채 알리기만 함 (생성자의 첫 프레임 — 첫 read가 씀)."""
        with self._cond:
            if not self._cond.wait_for(lambda: self._frames or self._finished or self._stopped, timeout):
                return _TIMEOUT, None
            if self._stopped:
                return _STOPPED, None
            if self._frames:
                if not remove:
                    return _FRAME, self._frames[0]
                frame = self._frames.popleft()
                self._cond.notify_all()  # 자리가 남 — put을 기다리던 읽기 스레드를 깨움
                return _FRAME, frame
            return (_FAILED, self.failure) if self.failure else (_END, None)

    def unsurfaced_failure(self):
        """(stop 전에) 아직 드러나지 않은 실패 — 읽기 스레드가 적어 둔 것, 또는 큐가 차 있어 읽기 스레드가 아직 보지 못한 비정상
        종료(멈춰 둔 사이 죽은 ffmpeg). 없으면 None."""
        with self._cond:
            if self.failure:
                return self.failure
        returncode = self.proc.poll()
        return None if returncode in (None, 0) else f"ffmpeg가 이미 끝나 있었습니다 (종료 코드 {returncode})"

    def stop(self):
        """일부러 끝냄 (release·GC·실패 정리, 여러 번 불러도 됨): 정지 플래그 → put 대기를 깨우고 큐 비움 → kill.
        기다리지 않는다 — 거두기·파이프 닫기는 두 스레드가."""
        with self._cond:
            self._stopped = True
            self._frames.clear()
            self._cond.notify_all()
        self.proc.kill()  # 이미 끝난 프로세스면 아무것도 안 함

    def _drain_stderr(self):
        stream = self.proc.stderr
        try:
            for chunk in iter(lambda: stream.read1(65536), b""):
                self._stderr_chunks.append(chunk)
        finally:
            stream.close()

    def _read_frames(self):
        failure = None
        stdout = self.proc.stdout
        try:
            while True:
                frame = np.empty(self._shape, np.uint8)  # 프레임마다 새 배열 — read()가 그대로 호출자에게 줌 (재사용 금지)
                filled = _read_into(stdout, memoryview(frame).cast("B"))
                if filled < frame.nbytes:
                    if filled:
                        failure = f"프레임 중간에서 출력이 끊겼습니다 ({filled}/{frame.nbytes}바이트)"
                    break
                with self._cond:
                    while len(self._frames) >= READAHEAD_FRAMES and not self._stopped:
                        self._cond.wait()
                    if self._stopped:
                        break
                    self._frames.append(frame)
                    self._cond.notify_all()
        except Exception:  # 파이프 읽기 오류 — 삼키지 않고 실패 원인으로
            failure = f"ffmpeg 출력을 읽다 오류가 났습니다:\n{traceback.format_exc()}"
        finally:
            self._finish(failure, stdout)

    def _finish(self, failure, stdout):
        """읽기 스레드의 끝: stdout 닫기 → (실패면 kill) → 거두기 → stderr 다 받기 → 실패 확정(정지가 아니었을 때만)·알림."""
        stdout.close()
        if failure is not None:
            self.proc.kill()
        returncode = self.proc.wait()
        self.stderr_reader.join()
        with self._cond:
            if not self._stopped:
                if failure is not None:
                    failure = f"{failure} (ffmpeg 종료 코드 {returncode})"
                elif returncode != 0:
                    failure = f"ffmpeg가 비정상 종료했습니다 (종료 코드 {returncode})"
                self.failure = failure
            self._finished = True
            self._cond.notify_all()


class FFmpegPipeCapture:
    """ProRes류 영상을 ffmpeg 파이프로 읽어 cv2.VideoCapture 자리에 꽂는 캡처 — read·isOpened·release·get·set의 의미가 cv2와
    같다 (ImageSequenceCapture와 같은 계약). 게이트(pipe_eligible)를 통과한 파일의 probe와 함께 만든다.

    read()는 다음 프레임(호출자가 써도 되는 새 배열)을 주고 pos를 1 올림. 끝에서는 (False, None)이고 pos는 그대로 — 단 받은 수가
    nb_frames와 같을 때만 끝이다. get(CAP_PROP_POS_FRAMES)는 다음에 읽을 인덱스(set이 기록한 목표가 있으면 그 값), FPS는
    float(avg)(cv2와 같은 출처), FRAME_COUNT는 nb_frames, 크기는 probe 값, 그 밖의 속성은 0.0. release한 캡처·죽은 캡처는 cv2처럼
    isOpened False, read (False, None), get 0.0, set False.

    생성자가 ffmpeg를 띄우고 첫 프레임이 올 때까지 기다린다(eager) — 못 열면 PipeCaptureError(원인·명령·stderr 전문). 첫 프레임은
    큐에 남아 첫 read()가 씀 (두 번 디코드하지 않음). ffmpeg를 찾지 못하면(ToolNotFoundError — 빌드 깨짐) 감싸지 않고 그대로 올라간다.

    생성 뒤의 read·get·set은 예외를 내지 않는다 (스펙 §5.5). 도중 실패 — 프레임 중간에서 끊김, ffmpeg 비정상 종료, 끝났는데 받은 수가
    nb_frames와 다름(모자람·넘침), READ_TIMEOUT_S 동안 다음 프레임이 없음 — 는 큐에 남은 정상 프레임을 다 준 뒤에 드러나고, 그때
    캡처가 스스로: 세션 정리(kill — 거두기는 데몬 스레드) → 죽음 상태 → 기록에 한 번(원인·읽던 곳의 호출 스택·명령·stderr 전문) →
    오류 창을 Qt 루프에서 한 번 (_report_failure). 죽은 뒤의 read는 다시 알리지 않는다.

    스레드: 캡처의 상태(_session·_pos·_target)는 _lock이 지키고, read()는 프레임을 기다리는 동안 _lock을 잡지 않는다 — 다른 스레드의
    release가 기다림을 깨워 끝낼 수 있다(그 read는 (False, None), 실패 아님). 죽음 전이는 '_session이 아직 그 세션일 때 None으로
    바꾼 쪽'만 하므로 한 번뿐. release 없이 버려진 캡처의 ffmpeg는 weakref.finalize가 끝낸다 (인터프리터가 끝날 때도).
    """

    def __init__(self, path, probe):
        if probe.width < 1 or probe.height < 1 or (probe.nb_frames or 0) < 1 or probe.avg is None:
            raise ValueError(f"파이프로 열 수 없는 probe입니다 (pipe_eligible을 먼저 볼 것): {probe}")
        self._path = path
        self._count = probe.nb_frames
        self._fps = float(probe.avg)
        self._width = probe.width
        self._height = probe.height
        self._lock = threading.Lock()
        self._session = None  # 지금 세션. None = 닫힘(release)·죽음
        self._pos = 0  # 다음에 읽을 인덱스 (세션이 차례로 내준 프레임을 셈)
        self._target = None  # set()이 기록한 탐색 목표 (아직 실행하지 않음 — get(POS_FRAMES)만 반영)
        command = _pipe_command(path)
        try:
            session = _PipeSession(command, probe.height, probe.width)
        except OSError as exc:
            raise PipeCaptureError(f"ffmpeg를 실행하지 못했습니다 ({exc}): {path}", command, "") from exc
        self._finalizer = weakref.finalize(self, session.stop)  # 세션을 멈추는 단 하나의 길 (release·죽음·GC가 같이 씀)
        outcome, value = session.take(READ_TIMEOUT_S, remove=False)
        if outcome != _FRAME:
            self._finalizer()
            if outcome == _END:
                reason = "ffmpeg가 프레임을 하나도 주지 않고 끝났습니다"
            elif outcome == _FAILED:
                reason = value
            else:
                reason = f"ffmpeg가 {READ_TIMEOUT_S:g}초 안에 첫 프레임을 주지 않았습니다"
            raise PipeCaptureError(f"영상을 ffmpeg 파이프로 열지 못했습니다 — {reason}: {path}", command,
                                   session.stderr_text())
        self._session = session

    def isOpened(self):
        return self._session is not None

    def read(self):
        with self._lock:
            session = self._session
        if session is None:
            return False, None
        outcome, value = session.take(READ_TIMEOUT_S)
        with self._lock:
            if self._session is not session:  # 기다리는 사이 다른 스레드가 release함 (일부러 끝냄 — 실패 아님)
                return False, None
            if outcome == _FRAME and self._pos < self._count:
                self._pos += 1
                return True, value
            clean_end = outcome == _END and self._pos == self._count  # 정상 끝: cv2처럼 pos 그대로, 열린 채
            if clean_end:
                leftover = "" if session.eof_noted else session.stderr_text()  # 끝났으니 stderr는 전부 받음
                session.eof_noted = True
            else:
                reason = self._failure_reason(outcome, value)
                self._session = None  # 죽음 전이 — 이 줄에 닿는 것은 세션마다 한 번
        if clean_end:
            if leftover.strip():
                self._log_eof_stderr(session, leftover)
            return False, None
        self._die(session, reason)
        return False, None

    def get(self, prop):
        with self._lock:
            if self._session is None:
                return 0.0
            if prop == cv2.CAP_PROP_POS_FRAMES:
                return float(self._pos if self._target is None else self._target)
            values = {
                cv2.CAP_PROP_FPS: self._fps,
                cv2.CAP_PROP_FRAME_COUNT: self._count,
                cv2.CAP_PROP_FRAME_WIDTH: self._width,
                cv2.CAP_PROP_FRAME_HEIGHT: self._height,
            }
            return float(values.get(prop, 0.0))

    def set(self, prop, value):
        """CAP_PROP_POS_FRAMES의 목표를 기록하고 True (get(POS_FRAMES)가 그 값을 보임). 아직 이동은 하지 않음 — read는 차례대로
        읽는다. 닫힌·죽은 캡처, 다른 속성은 False. 숫자가 아닌 value는 cv2처럼 TypeError(부른 쪽의 버그)."""
        target = float(value)
        with self._lock:
            if self._session is None or prop != cv2.CAP_PROP_POS_FRAMES:
                return False
            self._target = target
            return True

    def release(self):
        """닫기 (여러 번 불러도 됨): 세션을 떼고 정지 플래그 → kill (거두기·파이프 닫기는 세션의 데몬 스레드 — 여기서 기다리지
        않음) → 큐 비움. 드러나기 전의 실패(멈춰 둔 사이 죽은 ffmpeg)가 있었으면 기록에만 한 번 남김 (닫는 영상이라 창은 없음)."""
        with self._lock:
            session, self._session = self._session, None
            self._pos, self._target = 0, None
        if session is None:
            return
        failure = session.unsurfaced_failure()
        self._finalizer()
        if failure is not None:
            error = PipeCaptureError(f"{failure}: {self._path}", session.command, session.stderr_text())
            print(f"{LOG_PREFIX} 닫기(release) 전에 드러나지 않은 파이프 실패 — 기록만 남깁니다: {error}",
                  file=sys.stderr, flush=True)

    def _failure_reason(self, outcome, value):
        """(_lock 안에서) read가 본 도중 실패의 원인 글."""
        if outcome == _FRAME:
            return f"ffmpeg가 파일의 프레임 수 {self._count}보다 많은 프레임을 줬습니다"
        if outcome == _END:
            return f"ffmpeg가 {self._pos}장을 주고 끝났습니다 (파일의 프레임 수 {self._count})"
        if outcome == _FAILED:
            return f"{value} — {self._pos}장을 받은 뒤"
        if outcome == _TIMEOUT:
            return f"ffmpeg가 {READ_TIMEOUT_S:g}초 동안 다음 프레임을 주지 않았습니다 ({self._pos}장을 받은 뒤)"
        return f"ffmpeg 세션이 멈춰 있습니다 ({self._pos}장을 받은 뒤)"

    def _log_eof_stderr(self, session, stderr):
        """정상 끝(종료 코드 0·받은 수 == nb_frames)인데 ffmpeg가 stderr에 남긴 글 — 기록에만 한 번 (창 없음, 상태 그대로).
        디코드 오류 글이면 그 프레임이 깨졌을 수 있다 (cv2는 같은 상황에 조용함). 예외를 내지 않음 (read 안)."""
        try:
            print(f"{LOG_PREFIX} 끝까지 읽었지만(프레임 {self._count}장, 종료 코드 0) ffmpeg가 stderr에 글을 남겼습니다 — "
                  f"프레임이 깨졌을 수 있습니다: {self._path}\n명령: {session.command}\nffmpeg stderr:\n{stderr.rstrip()}",
                  file=sys.stderr, flush=True)
        except Exception:
            _last_resort(f"ffmpeg stderr를 기록하지 못했습니다: {self._path}")

    def _die(self, session, reason):
        """죽음 전이 뒤의 뒤처리 (read가 _lock 밖에서 한 번): 세션 정리 → 기록 한 번 → 오류 창은 Qt 루프에서 한 번."""
        try:
            self._finalizer()  # session.stop: kill — 거두기는 세션의 읽기 스레드
        except Exception:
            _last_resort(f"ffmpeg를 끝내지 못했습니다: {self._path}")
        error = PipeCaptureError(f"{reason}: {self._path}", session.command, session.stderr_text())
        context = f"{FAILURE_HEADLINE}.\n파일: {self._path}\n원인: {reason}"
        details = "읽던 곳 (가장 최근 호출이 마지막):\n" + "".join(traceback.format_stack()) + f"{type(error).__name__}: {error}"
        _report_failure(context, details)


_RELAY = None  # 오류 창을 Qt 루프로 넘기는 QObject (처음 알릴 때 만들어 GUI 스레드로 옮김)
_RELAY_LOCK = threading.Lock()


def _report_failure(context, details):
    """도중 실패 알림 — 어느 스레드에서 불러도 되고 예외를 내지 않는다 (mac_app_events._report_error 선례).

    기록(stderr — 빌드 앱은 기록 파일)에는 지금 바로 한 번: context + details 전부. 오류 창은 QApplication이 있으면 GUI 스레드의
    Qt 루프로 미뤄 한 번: error_window.with_details(context, details) — context는 그대로, details는 끝 DETAILS_LIMIT 글자(stderr가
    끝에 오게 짜 둠). QApplication이 없으면(Qt 없는 쓰임) 기록만."""
    try:
        print(f"{LOG_PREFIX} {context}\n\n{details}", file=sys.stderr, flush=True)
        from PyQt5.QtCore import QCoreApplication

        if QCoreApplication.instance() is not None:
            from yesoncheck import error_window

            _window_relay().requested.emit(error_window.with_details(context, details))
    except Exception:
        _last_resort(context)


def _window_relay():
    """GUI 스레드에 사는 전달자 (처음 부를 때 만들고, 다른 스레드에서 만들었으면 QApplication의 스레드로 옮김)."""
    global _RELAY
    with _RELAY_LOCK:
        if _RELAY is None:
            from PyQt5.QtCore import QCoreApplication

            relay = _make_relay()
            relay.moveToThread(QCoreApplication.instance().thread())
            _RELAY = relay
        return _RELAY


def _make_relay():
    """전달자 QObject — PyQt5를 알릴 때만 불러오려고 클래스를 여기서 만든다 (_window_relay가 한 번만 부름)."""
    from PyQt5.QtCore import QObject, Qt, pyqtSignal, pyqtSlot

    class _WindowRelay(QObject):
        requested = pyqtSignal(str)

        def __init__(self):
            super().__init__()
            # 늘 큐드 연결: GUI 스레드에서 emit해도 지금(read 안 — 재생 타이머 슬롯일 수 있음) 모달 창을 열지 않고 Qt 루프로 미룸
            self.requested.connect(self._show, Qt.QueuedConnection)

        @pyqtSlot(str)
        def _show(self, text):
            try:
                from yesoncheck import error_window

                error_window.show_window(text)
            except Exception:  # Qt 루프 밖으로 내보내면 소스 실행의 PyQt5가 프로세스를 끝냄
                _last_resort(text)

    return _WindowRelay()


def _last_resort(message):
    """(except 블록 안에서) 알리다 또 실패함: 원래 stderr(sys.__stderr__ — 기록 파일로 바꾸기 전)에 message와 그 예외의 트레이스백.
    원래 stderr도 없으면(Windows 창 앱) 더 남길 곳이 없다 — 이 실패를 올리면 read()에서 예외가 나가므로(PyQt abort) 올리지 않는다."""
    stream = sys.__stderr__
    if stream is not None:
        stream.write(f"{LOG_PREFIX} 오류를 알리지 못했습니다 — {message}\n{traceback.format_exc()}\n")
        stream.flush()
