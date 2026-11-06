"""ffmpeg 파이프 프레임 소스: 판정(probe_movie·pipe_eligible)과 cv2.VideoCapture 자리에 꽂는 캡처(FFmpegPipeCapture).

판정: ffprobe 한 번으로 영상 파일의 모양을 읽고(probe_movie), ffmpeg 파이프로 읽어도 cv2와 같은 프레임이 같은 번호로 나올
파일인지 가른다(pipe_eligible). 게이트는 양성 증거로만 켜진다 — 한 조건이라도 확인하지 못하면(값이 없거나 맞지 않으면) 거짓이라
기존 cv2 경로로 간다. probe_movie는 오류를 삼키지 않는다: ffprobe가 파일을 못 읽으면(RuntimeError)도, 결과 해석이 어긋나도
(KeyError·ValueError·TypeError…) 그대로 올라간다 — cv2로 돌릴지는 부른 쪽이 정한다.

캡처: ffmpeg 프로세스 하나(세션)가 bgr24 원시 프레임을 소켓으로 내보내고, 읽기 스레드가 그것을 유한 큐에 미리 받아 둔다.
탐색은 지연 실행 (스펙 §5.4): set은 목표만 적고 다음 read가 링 버퍼(전체 모드는 채움기가 채운 전체 저장소도)·앞으로 버리기·-ss 재시작
중 하나로 옮긴다. 뒤로 가는 재시작은 목표 KEEP_BEHIND(8)장 앞에서 띄워 그 8장을 링에 보관한다 — 4K에서 링 밖의 ←가 매번 재시작(~0.5초)이던
것이 8번에 한 번(약 0.6초 — 디코드 8장 ≈0.16초가 더해짐)이 되고, 앞으로 먼 점프는 그대로 목표에서 띄운다.

전송 (Task 3b — 왜 파이프가 아니라 소켓이고 왜 플랫폼별로 다른가): stdout 파이프였을 때는 4K 한 장(24.9MB)이 64KB씩 ~467번의
read로 들어왔고, 호출마다 읽기 스레드가 GIL을 다시 잡아야 해서 GUI 스레드가 파이썬을 실행하는 동안(재생 틱의 process_frame·
update_frame) 한 번에 switch interval(5ms)씩 기다렸다 — 메인이 GIL을 쥔 실험에서 공급 28fps → 0.4fps, 실제 재생 15fps(334장 22초).
소켓에서 recv_into(MSG_WAITALL)는 커널이 한 장을 다 채울 때까지 GIL을 놓은 채 syscall 한 번이라(프레임당 recv 1회) 메인이 GIL을
쥐고 있어도 공급이 유지된다. POSIX는 socketpair(AF_UNIX)의 한 끝을 ffmpeg의 stdout으로 넘긴다(명령의 출력 대상은 pipe:1 그대로) —
macOS 로컬 소켓의 기본 버퍼는 8KB(net.local.stream.sendspace)라 ffmpeg가 직접 여는 unix:// 소켓은 키울 길이 없는데(ffmpeg unix
프로토콜에 버퍼 옵션 없음) socketpair는 양 끝을 우리가 만들어 버퍼를 정한다. 측정(2026-10-29 Mac x86_64, 4K ProRes 정상 상태 60장,
메인 idle/40ms GIL 쥠): unix:// 리스너 12~22fps, TCP 루프백 21~33fps, socketpair 30~43fps — 가장 빠르고 리스너·임시 폴더·경로 길이·
접속 상대 확인이 아예 없다. Windows는 socketpair 끝을 자식 stdout으로 넘길 수 없어(소켓 핸들은 CRT fd가 아님) 127.0.0.1 임시 포트
TCP 리스너(tcp://127.0.0.1:<포트>)에 ffmpeg가 접속한다 — 접속은 하나만, 상대가 127.0.0.1인지 확인. 소켓은 blocking이다: 소켓
타임아웃(settimeout)은 CPython이 내부적으로 non-blocking으로 바꾸는데 Windows는 non-blocking 소켓의 MSG_WAITALL을 WSAEOPNOTSUPP로
거절한다. 멈춘 ffmpeg에 대한 보호는 read의 READ_TIMEOUT_S 실패 → stop()의 shutdown+close가 막힌 recv를 깨우는 길로.

메모리 (4K bgr24 24.9MB/장): 캡처 하나가 선읽기 큐 6장 ~149MB + 링 8장(세션이 준 배열 8개 그대로) ~199MB + 읽기 스레드가 손에
든 1장 ~25MB ≈ ~373MB, A/B 와이프의 두 캡처면 ~750MB (호출자가 쥔 프레임 — 플레이어의 frame_a 등 — 은 따로). 전체 모드는 여기에
채움기의 세션(선읽기 큐·손에 든 1장 ~175MB — 띄운 뒤 다 채울 때까지)과 전체 저장소(채운 만큼, 파일 전체면 4K 334장 ≈8.3GB)가 더해진다.
보관은 세션이 준 배열 그대로(읽기 스레드가 프레임마다 새로 할당하므로 안전)이고 호출자는 복사본을 받는다 — 복사는 내주는 프레임마다
한 번, read()가 GUI 스레드에서 한다. 복사를 읽기 스레드로 옮겨 본 판은 캡처당 약 174MB(쌍 7장분)가 늘고 메모리 대역 경합 아래 공급이
무너져 되돌렸다 (Task 3b fix round 3).
전체 프레임 캐시 (스펙 §6·§6.5): 플레이어 A/B만 opt-in(maybe_pipe_capture(path, full_cache=True))하고 첫 read가 예산으로 판정한다 — 전체면
읽는 동안은 링만 두고(재생 중 내준 프레임을 다 붙잡으면 4K 첫 재생이 장당 GUI ~8ms 느려져 실시간을 잃음 — 16.0 vs 13.7초 실측),
이 프로세스의 어느 파이프 캡처도 IDLE_FILL_DELAY_S(0.3초) 동안 read하지 않을 때만 채움기(_Filler — 따로 띄운 ffmpeg, 처음부터)가 전체
저장소를 파일 장수까지 채운다 (이 Mac 4K 334장 약 7초 — 배치 부하 없을 때; 그동안 read가 오면 다음 장부터 멈추고, A/B에서 한쪽만
재생해도 다른 쪽은 채우지 않음). 다 차면 파일 어디로의 되감기·탐색에도 재시작이 없다. 채움기 실패는 캡처의 죽음이 아니라 기록 한 번
(캡처는 링으로 그대로, 예산 몫은 채운 만큼으로 줄임). 이 프로세스의 모든 캡처의 전체 보관 합은 물리 RAM의 20%(frame_cache_budget —
장부 _LEDGER)를 넘지 않고, 넘으면 링으로 열고 그 사유를 기록에 한 줄 남긴다.
장부는 프로세스마다 하나이고 창 하나 = 프로세스 하나라(Finder로 여러 파일을 열면 창이 여럿) 20%는 창마다다 — 여러 창은 서로의 몫을
보지 못한다: 판정 때의 사용 가능 메모리 검사에 다른 창이 이미 채운 만큼은 잡히지만 아직 채우지 않은 몫은 잡히지 않는다.
실패는 캡처 안에서 끝난다 (스펙 §5.5): 생성자만 PipeCaptureError를 올리고, 그 뒤의 read·get·set은 예외를 내지 않는다 — 도중에
끊기면 죽은 cv2 캡처와 같은 겉모습이 되고, 기록(stderr)에 한 번, 오류 창은 Qt 루프에서 한 번 알린다.
Qt(PyQt5)와 error_window는 알릴 때만 불러온다 — 판정은 Qt 없이도 쓴다.

열기 경로 연결 (스펙 §5.2): maybe_pipe_capture(path)가 모드(YESONCHECK_MOVIE_SOURCE)·판정·캡처 생성을 한 함수로 묶어, open_any_capture와
VideoPlayer._open_movie_capture의 삽입 분기가 같이 부른다 — 양성이면 캡처, 음성이면 None(부른 쪽의 기존 cv2 줄이 그대로 돎).
"""

import collections
import errno
import math
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import weakref
from dataclasses import dataclass
from fractions import Fraction

import cv2
import numpy as np

from yesoncheck import frame_cache_budget
from yesoncheck.external_tools import (
    MAX_FRAME_RATE, _frame_rate, _probe, _start_seconds, decode_output, ffmpeg_path, ffprobe_path, subprocess_kwargs,
)

PIPE_CODECS = ("prores",)
SOURCE_MODE_ENV = "YESONCHECK_MOVIE_SOURCE"
SOURCE_MODES = ("auto", "pipe", "cv2")  # 환경 변수가 받는 값 (없거나 비어 있으면 "auto")
FRAME_CACHE_ENV = "YESONCHECK_FRAME_CACHE"
FRAME_CACHE_MODES = ("auto", "ring")  # 환경 변수가 받는 값 (없거나 비어 있으면 "auto") — ring은 전체 보관을 끄고 링만
# 프레임 캐시 판정이 실패해 죽을 때 사유 끝에 붙이는 안내 (기록·오류 창) — ring이면 _settle_cache가 메모리(psutil)를 읽기 전에 끝남
FRAME_CACHE_ESCAPE_HINT = f"탈출구: {FRAME_CACHE_ENV}=ring (psutil을 부르지 않음)"
UNSPECIFIED_SAR = (None, "1:1", "0:1")  # ffprobe의 sample_aspect_ratio: 없음·정사각형·미지정(0:1)

READAHEAD_FRAMES = 6  # 캡처마다 미리 받아 두는 프레임 수 (4K bgr24 24.9MB/장 → ~149MB; 캡처당 총량은 모듈 docstring) — 스펙 §5.3
READ_TIMEOUT_S = 30.0  # read()·생성자가 빈 큐를 기다리는 한도: 넘으면 멈춘 ffmpeg(NFS hard mount 등)로 보고 실패 처리
# 전송 소켓 버퍼 (Task 3b): POSIX socketpair는 양 끝 SO_SNDBUF·SO_RCVBUF를 이 값으로, Windows TCP는 우리 SO_RCVBUF와 ffmpeg
# send_buffer_size를 절반씩. 근거는 처리량뿐 — "키우면 빨라지겠지"로 바꾸지 말 것: 4K 공급은 8KB(macOS 기본) 26~29fps → 32KB부터
# 꺾여 34~39fps이고, 64KB·128KB·4MB는 서로 잡음 수준(35~39fps)이라 더 키워도 빨라지지 않는다 (2026-10-29 Mac x86_64, socketpair,
# 정상 상태 60장, 메인 idle/GIL 40ms 쥠). Windows TCP의 절반씩(32K+32K)은 재 보지 않은 값이다 — 이 기계에서는 Windows 실기를 잴 수
# 없어 POSIX와 같은 총량으로 맞춰 둔 것뿐 (Windows 4K 처리량은 CI의 test_reader_keeps_up_while_main_thread_holds_gil이 함께 본다).
SOCKET_BUFFER_BYTES = 64 * 1024
# (Windows TCP) ffmpeg가 출력 소켓에 접속하기를 기다리는 한도 — ffmpeg는 입력을 연 뒤에 접속하므로 첫 프레임 한도와 같게 둔다
# (따로 짧으면 느린 SMB·NAS에서 열기·재시작이 Windows에서만 실패). 넘으면 실패 (생성자면 PipeCaptureError)
CONNECT_TIMEOUT_S = READ_TIMEOUT_S
ACCEPT_SLICE_S = 0.05  # (Windows TCP) accept 대기를 이 간격으로 끊어 ffmpeg 종료·세션 정지를 봄
LOOPBACK = "127.0.0.1"
# 탐색 (스펙 §5.4 — 값은 Task 1 스파이크가 CI 세 플랫폼에서 단언으로 확정)
KEEP_BEHIND = 8  # 링 버퍼: 최근 스트림에서 꺼낸 프레임 보관 수 (뒤로 한 칸이 재시작 없이 — 4K ≈ 199MB/캡처)
SEEK_FORWARD_MAX = 24  # 앞으로 이만큼까지는 큐·스트림에서 꺼내 버림 (그보다 멀면 재시작 — 4K 재시작 ≈ 24장 디코드)
SEEK_BACK_K = 0  # 재시작 -ss를 목표보다 몇 장 앞에 겨눌지 (0: 목표 시각을 직접 — K=0·K=2 모두 40/40 정확 착지) — 앞으로 가는 재시작
# 뒤로 가는 재시작(목표 < 스트림 위치)은 따로 상수를 두지 않고 KEEP_BEHIND장 앞에서 띄운다 (_restart — 링 깊이만큼 미리 채움): 그 장들을
# 꺼내 버리며 보관하므로 이어지는 ←가 링에서 나온다. 사용자 보고(2026-11-02, 4K ProRes): 링 밖으로 뒤로 가면 새 세션이 목표에서
# 시작해 그 앞이 하나도 없어 ←마다 재시작(~0.5초)이었음 → 8번에 한 번(디코드 8장 ≈ 0.16초가 더해져 약 0.6초). 링을 끄면(KEEP_BEHIND 0)
# 미리 채우기도 꺼진다.
# 전체 모드의 쉬는 시간 채움 (스펙 §6.5 — 방식 B, 2026-11-02 사용자 결정): 재생 중 내준 프레임을 모두 붙잡으면(장마다 24.9MB를 새 메모리에)
# 4K 첫 재생이 16.0~16.2초로 링만일 때(13.7~14.6초)보다 장당 GUI ~8ms 느려짐(메모리 대역·VM — read 자체는 두 모드 모두 3~4ms, 미리 페이지를
# 확보한 버퍼 풀도 효과 없음) → 읽는 동안은 링만 두고, read가 이만큼 없을 때만 채움기(_Filler)가 따로 띄운 ffmpeg로 전체 저장소를 채운다
IDLE_FILL_DELAY_S = 0.3  # read()가 이 시간 동안 없어야 쉬는 때 (재생 24fps는 42ms 간격·드래그 미리보기도 촘촘해 그동안은 채우지 않음)
FILL_POLL_S = 0.05  # 채움기가 쉬는 때를 다시 보는 간격 — 그동안 꺼내지 않으면 ffmpeg는 소켓에서 저절로 멈춤 (CPU 0)
LOG_PREFIX = "[파이프]"
FAILURE_HEADLINE = "영상을 읽던 ffmpeg 파이프가 도중에 끊겨 이 영상을 더 읽을 수 없습니다"  # 도중 실패의 기록·오류 창 첫 줄
FILL_FAILURE_HEADLINE = "프레임 캐시 채움을 멈췄습니다"  # 채움기 실패의 기록 첫머리 (캡처는 그대로, 오류 창 없음 — 스펙 §7-19)


@dataclass(frozen=True)
class MovieProbe:
    """첫 영상 트랙(attached_pic 제외)의 ffprobe 값 중 게이트에 쓰는 것. 없는 값은 None·0·""(영상 트랙이 없으면 전부).

    width·height는 ffprobe가 준 그대로 — 화소 비율(SAR)을 곱하지도 회전으로 바꾸지도 않는다 (게이트가 둘 다 없는 파일만
    통과시키므로 cv2가 주는 크기와 같다).

    pix_fmt부터 codec_tag까지는 게이트(pipe_eligible)가 보지 않는 값으로, 뒤 작업이 읽는다: ffprobe가 준 글 그대로(정규화 없음 —
    "unknown"도 그대로), 없으면 "". 그래서 기본값이 있다 (dataclasses.replace로 일부만 바꿔 쓰는 곳이 그대로 동작)."""

    codec: str
    width: int
    height: int
    r: Fraction | None  # r_frame_rate (_frame_rate: 0/0·0 이하·MAX_FRAME_RATE 초과는 None)
    avg: Fraction | None  # avg_frame_rate (같은 규칙)
    nb_frames: int | None
    duration_ts: int | None  # time_base 단위
    time_base: Fraction | None  # (_time_base: 없음·분모 0은 None)
    video_start: float  # 영상 트랙 start_time (초, 음수도 있음)
    format_start: float  # 컨테이너 start_time (초)
    rotation: int  # 디스플레이 행렬의 회전 (도, 반올림)
    sar_ok: bool  # 화소 비율이 없거나 1:1
    pix_fmt: str = ""  # 예: "yuv422p10le"·"yuva444p12le" (4444는 디코더 쪽 값이라 인코더 입력보다 비트가 큼)
    color_space: str = ""  # 행렬 계수 ("bt709"·"bt470bg"·…), 태그가 없으면 ""
    color_range: str = ""  # "tv"·"pc"
    color_transfer: str = ""
    color_primaries: str = ""
    codec_tag: str = ""  # codec_tag_string — "apch"(HQ)·"apcn"(422)·"ap4h"(4444)·…


def _optional_int(value):
    """ffprobe 정수 글(nb_frames "120"·duration_ts 61440). 없거나 "N/A"면 None."""
    return None if value in (None, "N/A") else int(value)


def _time_base(text):
    """ffprobe time_base 글("1/12288"). 없거나 비었거나 분모가 0("1/0"·"0/0")이면 None — Fraction이 ZeroDivisionError를 내지 않게
    (external_tools._frame_rate와 같은 규칙). None이면 게이트 ④가 거짓이라 기존 cv2 경로로 간다."""
    return None if not text or text.endswith("/0") else Fraction(text)


def _rotation(video):
    """디스플레이 행렬의 회전 (external_tools._display_size가 읽는 자리와 같음). 없으면 0."""
    return round(float(next((d["rotation"] for d in video.get("side_data_list", []) if "rotation" in d), 0)))


def probe_movie(path):
    """path의 첫 영상 트랙을 ffprobe(1회)로 읽은 MovieProbe. 영상 트랙이 없으면 값이 모두 빈 probe (게이트는 거짓)."""
    info = _probe(ffprobe_path(), path)
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"
                  and s.get("disposition", {}).get("attached_pic") != 1), {})
    return MovieProbe(
        codec=video.get("codec_name", ""),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        r=_frame_rate(video.get("r_frame_rate")),
        avg=_frame_rate(video.get("avg_frame_rate")),
        nb_frames=_optional_int(video.get("nb_frames")),
        duration_ts=_optional_int(video.get("duration_ts")),
        time_base=_time_base(video.get("time_base")),
        video_start=_start_seconds(video.get("start_time")),
        format_start=_start_seconds(info.get("format", {}).get("start_time")),
        rotation=_rotation(video),
        sar_ok=video.get("sample_aspect_ratio") in UNSPECIFIED_SAR,
        pix_fmt=video.get("pix_fmt", ""),
        color_space=video.get("color_space", ""),
        color_range=video.get("color_range", ""),
        color_transfer=video.get("color_transfer", ""),
        color_primaries=video.get("color_primaries", ""),
        codec_tag=video.get("codec_tag_string", ""),
    )


def ineligible_reason(probe, check_codec=True):
    """ffmpeg 파이프로 읽으면 안 되는 이유 한 줄 (스펙 §5.2 ①~⑥ 중 처음 어긋난 조건, 앞에 조건 번호) — 모두 통과하면 None.
    check_codec=False면 ① 코덱을 보지 않음 (pipe 모드: 정확도 조건 ②~⑥만 요구)."""
    if check_codec and probe.codec not in PIPE_CODECS:  # ①
        return f"① 코덱 {probe.codec or '(영상 트랙 없음)'}은(는) 파이프 대상({', '.join(PIPE_CODECS)})이 아님"
    if probe.r is None or not 0 < probe.r <= MAX_FRAME_RATE or probe.avg != probe.r:  # ②
        return f"② 프레임 속도가 일정하지 않음 (r_frame_rate {probe.r}, avg_frame_rate {probe.avg})"
    if probe.nb_frames is None or probe.nb_frames < 1 or probe.width * probe.height < 1:  # ③
        return f"③ 프레임 수·크기를 알 수 없음 (nb_frames {probe.nb_frames}, 크기 {probe.width}×{probe.height})"
    # ④ 프레임 수·길이·속도 삼자 일치 — 편집 목록으로 잘린 파일(nb_frames 120인데 재생 118)과 한 프레임이 머무는 파일을 거름
    if probe.duration_ts is None or probe.time_base is None \
            or Fraction(probe.nb_frames, 1) / probe.r != probe.duration_ts * probe.time_base:
        return (f"④ 프레임 수·길이·속도가 맞지 않음 (nb_frames {probe.nb_frames}, r {probe.r}, "
                f"duration_ts {probe.duration_ts}, time_base {probe.time_base})")
    if probe.rotation != 0 or not probe.sar_ok:  # ⑤
        return f"⑤ 회전({probe.rotation}°) 또는 1:1이 아닌 화소 비율"
    if not (math.isfinite(probe.video_start) and math.isfinite(probe.format_start)):  # ⑥ 오프셋은 탐색이 보정
        return f"⑥ 시작 시각을 알 수 없음 (영상 {probe.video_start}, 컨테이너 {probe.format_start})"
    return None


def pipe_eligible(probe, check_codec=True):
    """ffmpeg 파이프로 읽어도 되는 파일인가 (스펙 §5.2 ①~⑥ 전부, check_codec=False면 ① 코덱만 면제) — ineligible_reason이 None."""
    return ineligible_reason(probe, check_codec) is None


def movie_source_mode():
    """환경 변수 YESONCHECK_MOVIE_SOURCE: 없거나 비면 "auto", "auto"·"pipe"·"cv2"(대소문자 무시)는 소문자로, 그 밖은 ValueError."""
    given = os.environ.get(SOURCE_MODE_ENV, "")
    mode = given.lower() or "auto"
    if mode not in SOURCE_MODES:
        raise ValueError(f"{SOURCE_MODE_ENV}는 {', '.join(SOURCE_MODES)} 중 하나여야 합니다 (비우면 auto): {given!r}")
    return mode


def frame_cache_mode():
    """환경 변수 YESONCHECK_FRAME_CACHE: 없거나 비면 "auto", "auto"·"ring"(대소문자 무시)은 소문자로, 그 밖은 ValueError."""
    given = os.environ.get(FRAME_CACHE_ENV, "")
    mode = given.lower() or "auto"
    if mode not in FRAME_CACHE_MODES:
        raise ValueError(f"{FRAME_CACHE_ENV}는 {', '.join(FRAME_CACHE_MODES)} 중 하나여야 합니다 (비우면 auto): {given!r}")
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


def _pipe_command(path, output, seek_seconds=None):
    """bgr24 원시 프레임을 끝까지 output으로 내는 ffmpeg 명령 (스펙 §5.3) — seek_seconds가 있으면 그 시각(-ss, 입력 앞 = 컨테이너
    start 기준 시각, 소수 6자리)부터, 없으면 처음부터. output: 출력 대상 = _Transport.output — POSIX "pipe:1"(ffmpeg의 stdout이
    socketpair의 한 끝), Windows "tcp://127.0.0.1:<포트>?send_buffer_size=…"(우리 리스너). 플랫폼별로 다른 까닭은 모듈 docstring의
    '전송' 단락. -fps_mode passthrough: 없으면 rawvideo가 CFR에 맞추려고 프레임을 복제해 섞음(§3b). -map 0:V:0: attached_pic을 뺀
    첫 영상 트랙 — probe_movie가 고른 트랙과 같음. 경로는 인자 그대로 (비ASCII 안전). ffmpeg가 없으면 ToolNotFoundError."""
    seek = [] if seek_seconds is None else ["-ss", f"{seek_seconds:.6f}"]
    return [ffmpeg_path(), "-nostdin", "-v", "error", *seek, "-i", path, "-map", "0:V:0", "-fps_mode", "passthrough",
            "-f", "rawvideo", "-pix_fmt", "bgr24", output]


class _TransportError(Exception):
    """(Windows TCP) ffmpeg가 출력 소켓에 제대로 접속하지 않음 — 시간 초과·접속 전에 끝남·127.0.0.1이 아닌 상대. 읽기 스레드가
    세션의 실패 원인으로 적는다 (그 뒤는 다른 도중 실패와 같은 길 — 생성자면 PipeCaptureError, 그 뒤면 죽음 전이·알림)."""


class _Transport:
    """ffmpeg 출력이 들어오는 소켓 한 벌 — ffmpeg를 띄우기(Popen) 전에 만들고, 세션이 넘겨받는다 (모듈 docstring '전송' 단락).

    - POSIX: socketpair(AF_UNIX) — 한 끝(conn)은 우리 것, 다른 끝은 ffmpeg의 stdout(child_stdout)으로 넘기고 Popen 직후 부모에서
      닫는다(spawned — 안 닫으면 ffmpeg가 끝나도 EOF가 오지 않음). 출력 대상 "pipe:1". 두 끝은 non-inheritable(파이썬 기본)이라
      다른 자식 프로세스로 새지 않고, Popen이 ffmpeg의 fd 1로 dup2한 것만 넘어간다.
    - Windows: 127.0.0.1 임시 포트 TCP 리스너, 출력 대상 "tcp://127.0.0.1:<포트>?send_buffer_size=…", stdout은 DEVNULL. 읽기
      스레드가 accept로 접속 하나만 받고(connect) 리스너를 닫는다.
    conn은 blocking이다 (모듈 docstring — Windows의 MSG_WAITALL). 버퍼는 SOCKET_BUFFER_BYTES (근거는 그 상수의 주석).
    _lock이 지키는 것: 소켓을 닫는 일과 _woken — wake()(다른 스레드)와 connect·close(읽기 스레드)가 엇갈려도 막힌 recv를 놓치지
    않고 닫힌 소켓을 다시 만지지 않게. RLock: _lock을 쥔 읽기 스레드에서 GC가 캡처의 weakref.finalize(→ stop → wake)를 돌려도
    스스로 막히지 않게.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._woken = False  # wake()가 불림 — 그 뒤에 받은 접속은 쓰지 않고 닫음
        self.conn = None  # 우리 끝 (읽기 스레드만 recv)
        self._listener = None
        self._child_end = None
        if sys.platform == "win32":
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._listener = listener
            try:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows 파이썬에만 있음 (시험이 sys.platform만 바꾼 Mac에는 없음)
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # 같은 포트에 남이 끼어 묶지 못하게
                # 보내는 쪽(ffmpeg send_buffer_size)과 절반씩. Windows는 받은 접속이 리스너의 옵션을 물려받는다(listen 전에 정함) —
                # macOS는 물려받지 않음 (실측: 받은 소켓 SO_RCVBUF 326,640 — 이 플랫폼 흉내에서는 이 줄이 효과 없음)
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCKET_BUFFER_BYTES // 2)
                listener.bind((LOOPBACK, 0))
                listener.listen(1)
                listener.settimeout(ACCEPT_SLICE_S)
            except BaseException:
                listener.close()
                raise
            self.output = f"tcp://{LOOPBACK}:{listener.getsockname()[1]}?send_buffer_size={SOCKET_BUFFER_BYTES // 2}"
            self.child_stdout = subprocess.DEVNULL
        else:
            self.conn, self._child_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                self.conn.setblocking(True)  # socket.setdefaulttimeout가 어디서 불렸어도 blocking으로 (모듈 docstring '전송')
                self.conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCKET_BUFFER_BYTES)
                self._child_end.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SOCKET_BUFFER_BYTES)
            except BaseException:
                self.close()
                raise
            self.output = "pipe:1"
            self.child_stdout = self._child_end.fileno()

    @property
    def closed(self):
        """만든 소켓(우리 끝·리스너·자식에게 넘긴 끝)이 모두 닫혔는가 — 수명 확인용."""
        return all(sock is None or sock.fileno() == -1 for sock in (self.conn, self._listener, self._child_end))

    def spawned(self):
        """(Popen 직후 — 성공·실패 모두) 자식에게 넘긴 끝을 부모에서 닫음. 안 닫으면 ffmpeg가 끝나도 그 끝이 열려 있어 EOF가 오지 않는다."""
        with self._lock:
            if self._child_end is not None:
                self._child_end.close()

    def connect(self, proc, stopped):
        """(읽기 스레드) 우리 끝을 돌려줌 — socketpair는 이미 있고, TCP는 접속 하나를 받는다: ACCEPT_SLICE_S씩 끊어 기다리며
        ffmpeg 종료(proc.poll)·세션 정지(stopped())·CONNECT_TIMEOUT_S를 본다. → conn, 정지(wake)됐으면 None. 접속 실패는
        _TransportError. 받은 접속은 blocking으로, 상대가 127.0.0.1인지 확인, 리스너는 닫는다 (접속은 하나만)."""
        if self._listener is None:
            with self._lock:
                return None if self._woken else self.conn
        deadline = time.monotonic() + CONNECT_TIMEOUT_S
        exited = False
        while True:
            try:
                conn, peer = self._listener.accept()
                break
            except socket.timeout:
                pass
            if stopped():
                return None
            if exited:  # 끝난 뒤 한 번 더 받아 봤는데도 없음 (끝나기 전에 한 접속은 큐에 남아 있어 위 accept가 받음)
                raise _TransportError(f"ffmpeg가 출력 소켓({self.output})에 접속하지 않고 끝났습니다")
            if time.monotonic() > deadline:
                raise _TransportError(f"ffmpeg가 {CONNECT_TIMEOUT_S:g}초 안에 출력 소켓({self.output})에 접속하지 않았습니다")
            exited = proc.poll() is not None
        conn.setblocking(True)  # 리스너의 타임아웃을 물려받지 않게 — non-blocking이면 Windows MSG_WAITALL이 WSAEOPNOTSUPP
        with self._lock:
            self._listener.close()
            if self._woken:
                conn.close()
                return None
            self.conn = conn
        if peer[0] != LOOPBACK:
            raise _TransportError(f"출력 소켓에 {LOOPBACK}이 아닌 상대({peer[0]}:{peer[1]})가 접속했습니다 — 받지 않고 끊습니다")
        return conn

    def wake(self):
        """(stop — 다른 스레드에서) recv에서 막힌 읽기 스레드를 깨움: shutdown(SHUT_RDWR) 뒤 close. macOS는 close만으로는 막힌 recv가
        깨지 않을 수 있고, Windows는 closesocket이 막힌 호출을 취소한다 — 둘 다 한다. 상대가 이미 끊었으면 shutdown이
        ENOTCONN·ECONNRESET(깨울 recv가 없음 — EOF가 이미 와 있음)이라 넘어간다. 그 밖의 shutdown 오류와 close 오류는 뜻밖이라
        기록(트레이스백)에 남기되 올리지 않는다 — stop은 read(탐색 재시작)·release·GC 안에서 불리고(§5.5: read 밖으로 예외 없음), 뒤의
        kill이 어차피 recv를 끝낸다. close는 늘 시도한다."""
        with self._lock:
            self._woken = True
            conn = self.conn
            if conn is None or conn.fileno() == -1:
                return
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError as exc:
                if exc.errno not in (errno.ENOTCONN, errno.ECONNRESET):
                    _log_wake_error("shutdown")
            try:
                conn.close()
            except OSError:
                _log_wake_error("close")

    def close(self):
        """만든 소켓을 모두 닫음 (읽기 스레드의 끝·세션을 세우지 못한 쪽, 여러 번 불러도 됨)."""
        with self._lock:
            for sock in (self.conn, self._listener, self._child_end):
                if sock is not None:
                    sock.close()


def _log_wake_error(step):
    """(except 블록 안에서) wake의 shutdown·close가 뜻밖의 오류로 실패함 — 기록에 트레이스백째 남기고 올리지 않음 (stop은 read·release·
    GC 안). 기록마저 실패하면 _last_resort."""
    try:
        print(f"{LOG_PREFIX} 막힌 recv를 깨우려던 {step}이(가) 뜻밖의 오류로 실패했습니다 — kill로 이어 갑니다:\n{traceback.format_exc()}",
              file=sys.stderr, flush=True)
    except Exception:
        _last_resort(f"전송 소켓 {step} 실패를 기록하지 못했습니다")


class _PipeSession:
    """ffmpeg 프로세스 하나와 그 둘레 한 덩어리 — 전송 소켓·읽기 스레드·stderr 스레드·유한 큐·실패 칸·정지 플래그 (스펙 §5.3).

    캡처는 세션을 통째로 버린다(stop) — 옛 프로세스의 프레임·실패가 다른 세션에 섞이지 않는다.
    - 전송 소켓(transport — _Transport)은 읽기 스레드만 recv한다: 프레임 크기(height*width*3바이트)씩 새 배열에 바로 받아
      (recv_into(MSG_WAITALL) — 정상이면 한 장에 recv 한 번, 따로 복사하지 않음) 큐에 넣고, 큐가 차면(READAHEAD_FRAMES) _cond에서
      기다린다. stop()이 그 기다림과 막힌 recv(transport.wake)를 깨운다. recv_calls·frames_received: 프레임 바이트를 받은 recv 호출
      수·다 받은 프레임 수 (시험용).
    - stderr는 전용 스레드가 늘 비운다 (안 비우면 파이프가 차서 ffmpeg가 멈춤) — 모아서 실패 글에 싣는다.
    - 읽기 스레드가 끝날 때 전송 소켓을 닫고 프로세스를 거둔다(wait — 좀비 없음) (stderr는 그 스레드가 닫음). kill해도 안 죽는
      프로세스(NFS hard mount의 D 상태)면 이 데몬 스레드만 남아 기다리고, 부른 스레드(GUI)는 막히지 않는다.
    - 실패(프레임 중간에서 끊김·0이 아닌 종료 코드·읽기 오류·접속 실패)는 failure에 적어 두기만 한다 — 드러내는 것은 큐를 다
      비운 read()의 몫. stop()으로 일부러 끝낸 뒤의 끊김·종료 코드는 실패가 아니다 (정지 플래그).
    _cond가 지키는 것: _frames·_stopped·_finished·failure.
    start: 이 세션이 내줄 첫 프레임의 번호 (처음 연 세션 0, 탐색 재시작은 -ss로 겨눈 번호).
    is_filler: 전체 모드 채움기(_Filler)의 세션인가 — 동작은 주 세션과 같고, 시험이 재시작 횟수(주 세션)와 따로 세는 표지·스레드 이름에만 쓴다.
    transport는 만든 쪽이 넘기고, 이 생성자가 성공하면 세션 것이다 (실패하면 만든 쪽이 닫는다 — 캡처의 생성자·_restart·채움기).
    """

    def __init__(self, command, transport, height, width, start=0, is_filler=False):
        self.command = command
        self.transport = transport
        self.start = start
        self.is_filler = is_filler
        self._shape = (height, width, 3)
        self._cond = threading.Condition()
        self._frames = collections.deque()
        self._stopped = False  # 정지 플래그: stop()이 일부러 끝냄
        self._finished = False  # 읽기 스레드가 끝남: 더 올 프레임 없음, 프로세스는 거둬졌고 failure는 확정
        self.failure = None  # 읽기 스레드가 본 실패 원인 (정상 끝·정지면 None)
        self.eof_noted = False  # 정상 끝의 stderr를 기록했는지 (세션당 한 번 — 캡처의 _lock이 지킴)
        self.recv_calls = 0  # 프레임 바이트를 받은 recv 호출 수 (읽기 스레드만 셈 — 정상이면 프레임당 1)
        self.frames_received = 0  # 다 받은 프레임 수 (읽기 스레드만 셈 — recv_calls와 견주는 시험용)
        self._stderr_chunks = []
        try:
            self.proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=transport.child_stdout,
                                         stderr=subprocess.PIPE, **subprocess_kwargs())
        finally:
            transport.spawned()
        kind = "ffmpeg-pipe-fill" if is_filler else "ffmpeg-pipe"
        self.stderr_reader = threading.Thread(target=self._drain_stderr, name=f"{kind}-stderr", daemon=True)
        self.reader = threading.Thread(target=self._read_frames, name=f"{kind}-read", daemon=True)
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
        """일부러 끝냄 (release·GC·실패 정리, 여러 번 불러도 됨): 정지 플래그 → put 대기를 깨우고 큐 비움 → 막힌 recv 깨우기
        (transport.wake: shutdown+close) → kill. 기다리지 않는다 — 거두기·남은 소켓·파이프 닫기는 두 스레드가."""
        with self._cond:
            self._stopped = True
            self._frames.clear()
            self._cond.notify_all()
        try:
            self.transport.wake()
        finally:
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
        try:
            conn = self.transport.connect(self.proc, lambda: self._stopped)
            while conn is not None:
                frame = np.empty(self._shape, np.uint8)  # 프레임마다 새 배열 — 캡처가 그대로 보관함 (재사용 금지)
                filled = self._recv_into(conn, memoryview(frame).cast("B"))
                if filled < frame.nbytes:
                    if filled:
                        failure = f"프레임 중간에서 출력이 끊겼습니다 ({filled}/{frame.nbytes}바이트)"
                    break
                self.frames_received += 1
                with self._cond:
                    while len(self._frames) >= READAHEAD_FRAMES and not self._stopped:
                        self._cond.wait()
                    if self._stopped:
                        break
                    self._frames.append(frame)
                    self._cond.notify_all()
        except _TransportError as exc:  # 출력 소켓 접속 실패 (Windows TCP)
            failure = str(exc)
        except Exception:  # 소켓 읽기 오류 — 삼키지 않고 실패 원인으로
            failure = f"ffmpeg 출력을 읽다 오류가 났습니다:\n{traceback.format_exc()}"
        finally:
            self._finish(failure)

    def _recv_into(self, conn, view):
        """바이트 memoryview를 다 채울 때까지 conn에서 받음 → 받은 바이트 수 (EOF면 len(view)보다 적음). MSG_WAITALL: 커널이 다
        채울 때까지 GIL을 놓은 채 기다려 정상이면 한 장에 recv 한 번 (shutdown·EOF·신호면 덜 채우고 돌아옴 — 이어 받거나 끝)."""
        filled = 0
        while filled < len(view):
            count = conn.recv_into(view[filled:], len(view) - filled, socket.MSG_WAITALL)
            if not count:
                break
            self.recv_calls += 1
            filled += count
        return filled

    def _finish(self, failure):
        """읽기 스레드의 끝: 전송 소켓 닫기 → (실패면 kill) → 거두기 → stderr 다 받기 → 실패 확정(정지가 아니었을 때만)·알림."""
        self.transport.close()
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


class _FrameStore:
    """번호 → 보관 프레임 (스펙 §5.4·§6.5 — 탐색을 재시작 없이). 캡처가 둘을 쓴다:
    - 링(_ring — max_frames KEEP_BEHIND, keep_across_restart 거짓): 주 세션에서 꺼낸 프레임은 내주든 버리든 그 번호로 여기를 지나고(모드와
      무관 — 전체 모드도 읽는 동안은 링만), 세션 재시작에서 비운다 — 그러면 보관 번호는 늘 최근 꺼낸 것들의 연속 구간 [스트림 위치 − 보관
      수, 스트림 위치)라 1.5.1의 링과 같다 (단 뒤로 재시작은 목표 KEEP_BEHIND장 앞에서 띄워 그 장들을 꺼내 버리므로 착지 뒤 링에 목표 앞
      장들이 들어 있음 — 1.5.1은 목표 하나).
    - 전체 저장소(_full — 전체 모드면 max_frames 파일 장수, keep_across_restart 참, 링 모드면 0장이라 아무것도 넣지 않음): 채움기(_Filler)만
      쓰고 재시작을 건너 남는다 (release·죽음에서 비움).
    보관 수는 max_frames를 넘지 않는다 — 가득 차면 가장 오래 전에 넣은 번호부터 내보내고(FIFO), 같은 번호를 다시 넣으면 교체하며
    순서는 새로.

    보관은 세션이 준 배열 그대로다 (읽기 스레드가 프레임마다 새 배열을 할당하고 아무도 고치지 않음). 밖으로는 늘 새 복사본(copy_of)만
    나가므로 호출자가 받은 배열을 무엇으로 고쳐도 보관본은 그대로다. 캡처의 _lock 안에서만 쓴다.
    """

    def __init__(self, max_frames, keep_across_restart):
        self._max_frames = max_frames
        self._keep_across_restart = keep_across_restart
        self._frames = collections.OrderedDict()  # 번호 → 배열, 넣은 순서

    def keep(self, index, frame):
        """index번으로 frame(배열 그대로)을 보관. 가득 차면 가장 오래 전에 넣은 번호부터 내보냄 (max_frames ≤ 0이면 보관 없음)."""
        self._frames.pop(index, None)  # 같은 번호는 교체 — 순서는 새로
        if self._max_frames <= 0:
            return
        while len(self._frames) >= self._max_frames:
            self._frames.popitem(last=False)
        self._frames[index] = frame

    def has(self, index):
        return index in self._frames

    def copy_of(self, index):
        """index번 보관본의 새 복사본 (보관 배열은 밖으로 나가지 않음)."""
        return self._frames[index].copy()

    def clear(self):
        self._frames.clear()

    def on_restart(self):
        """세션 재시작: 링 모드(keep_across_restart 거짓)면 비움."""
        if not self._keep_across_restart:
            self.clear()

    def indices(self):
        """보관한 번호들, 넣은 순서로."""
        return list(self._frames)

    def __len__(self):
        return len(self._frames)

    @property
    def bytes(self):
        """보관 배열 크기의 합."""
        return sum(frame.nbytes for frame in self._frames.values())


class _Ledger:
    """전체 보관(full)을 잡은 살아 있는 캡처들의 바이트 장부 — 모듈에 하나(_LEDGER), A/B 와이프의 두 캡처가 같은 예산을 나눈다
    (프로세스 — 창 — 마다 하나라 다른 창의 캡처는 모름; 모듈 docstring).
    키는 캡처(id): 첫 read의 판정이 add, release·죽음·GC(캡처의 weakref.finalize)가 release — 없는 키는 무시라 여러 번 불러도 된다.
    잠금 안에서는 GC가 추적하는 객체를 만들지 않는다(합계를 따로 셈) — 잠금을 쥔 스레드에서 GC가 다른 캡처의 finalize(→ release)를
    돌려도 같은 잠금을 다시 잡으려다 막히지 않게."""

    def __init__(self):
        self._lock = threading.Lock()
        self._bytes = {}  # 키 → 잡은 바이트
        self._total = 0  # _bytes 값의 합

    def add(self, key, total):
        with self._lock:
            self._total += total - self._bytes.get(key, 0)
            self._bytes[key] = total

    def release(self, key):
        with self._lock:
            self._total -= self._bytes.pop(key, 0)

    def shrink(self, key, total):
        """있는 키의 몫을 total로 줄임 (채움기 실패 — 남은 몫은 다른 캡처가 씀). 없는 키(이미 반환됨)거나 이미 그보다 작으면 아무것도 안 함 —
        release와 엇갈려도 반환된 키를 되살리지 않음."""
        with self._lock:
            held = self._bytes.get(key)
            if held is not None and total < held:
                self._total -= held - total
                self._bytes[key] = total

    def committed(self):
        """살아 있는 전체 보관 캡처들이 잡은 바이트의 합."""
        with self._lock:
            return self._total


_LEDGER = _Ledger()


class _ReadClock:
    """read() 활동 시계 — 채움기가 '쉬는 때'를 보는 곳 (스펙 §6.5). 둘을 쓴다: 캡처마다 하나(_reads — 그 캡처의 read)와 프로세스에 하나
    (_PROCESS_READS — 이 프로세스의 모든 파이프 캡처의 read). 채움기는 **둘 다** IDLE_FILL_DELAY_S 동안 쉬어야 꺼낸다 — A/B를 열고 와이프를
    끈 채 A만 재생할 때(플레이어는 와이프가 켜져 있을 때만 B를 read) B의 채움기가 쉬는 줄 알고 8스레드로 디코드해 A의 재생과 다투지 않게
    (최종 검토 Ruling 11). 주석 내보내기 워커처럼 링 모드 캡처의 read도 프로세스 시계를 움직인다(그동안 채움은 쉼 — 디코드를 다투지 않음).
    캡처 대신 이것만 채움기에 넘겨 채움기가 캡처를 붙잡지 않게 한다(release 없이 버려진 캡처의 GC — 채움기 정지가 든 weakref.finalize — 가
    늘 돌게). enter()·leave(): read가 들어올 때·나갈 때 — last_read_at(time.monotonic)을 적고 busy(지금 read 중인 수 — 프로세스 시계는 여러
    스레드의 캡처가 함께 셈)를 올리고 내림. read 안의 재시작(4K ~0.5초)이 길어도 쉬는 때로 보지 않게. 잠금은 값 몇 개를 바꾸는 동안만
    (GC가 추적하는 객체를 만들지 않음)."""

    __slots__ = ("_lock", "busy", "last_read_at")

    def __init__(self):
        self._lock = threading.Lock()
        self.busy = 0
        self.last_read_at = time.monotonic()

    def enter(self):
        with self._lock:
            self.busy += 1
            self.last_read_at = time.monotonic()

    def leave(self):
        with self._lock:
            self.busy -= 1
            self.last_read_at = time.monotonic()

    def idle_for(self):
        """마지막 read가 끝난 뒤 지난 초 — 누가 read 중이면 0."""
        with self._lock:
            return 0.0 if self.busy else time.monotonic() - self.last_read_at


_PROCESS_READS = _ReadClock()  # 이 프로세스의 모든 파이프 캡처의 read — 채움기의 쉬는 때는 자기 캡처와 이것 둘 다로 봄


class _Filler:
    """전체 모드의 쉬는 시간 채움기 (스펙 §6.5 — 방식 B): 캡처의 read()도, 이 프로세스의 다른 파이프 캡처의 read()도 IDLE_FILL_DELAY_S 동안 없을 때만, 자기 ffmpeg 세션(채움 세션 —
    주 세션과 같은 명령·전송 코드, -ss 없이 처음부터)에서 프레임을 차례로 꺼내 캡처의 전체 저장소(_full)에 그 번호로 넣는다. 캡처당
    하나(전체 모드 판정 때 만듦 — FFmpegPipeCapture._settle_cache), 데몬 스레드 하나. 전체 저장소는 이 채움기만 쓴다 — read가 내준
    프레임은 링에만 (재생 중 보관 비용을 없애려는 것 — IDLE_FILL_DELAY_S 주석).

    - 쉬는 때 = 자기 캡처의 시계(clock)와 프로세스 시계(_PROCESS_READS)가 둘 다 IDLE_FILL_DELAY_S 동안 read 없음 — A/B에서 와이프를 끄고
      A만 재생해도 B는 채우지 않음(_ReadClock). 쉬는 때가 아니면 꺼내지 않고 FILL_POLL_S마다 다시 볼 뿐이다: 소켓을 읽지 않으면 ffmpeg는 저절로 멈춘다(CPU 0 — 읽기 스레드가 선읽기
      큐 READAHEAD_FRAMES장까지는 받아 둠, 4K ~150MB). 채움 세션은 처음 쉬는 때 띄운다(판정 직후 띄우면 첫 재생과 디코드를 다툼). 꺼내는
      도중에 read가 오면 그 장을 넣고 다음 장 앞에서 멈춘다.
    - 캡처를 붙잡지 않는다(약한 참조도 없음): 캡처의 잠금(lock)·전체 저장소(store)·read 시계(clock — _ReadClock)만 받는다. 넣기는 그
      잠금 안에서 짧게(사전 한 칸)이고, 소켓을 기다리는 동안(take)은 어떤 잠금도 쥐지 않는다.
    - 끝: 파일 장수를 다 넣고 정상 끝(EOF — 넘침 검사, 주 세션의 EOF 불변식과 같은 뜻)을 확인하면 done, 세션 정리, 기록 한 줄
      ("[파이프] 프레임 캐시 채움 끝: 334장 8.3GB (7.0초) — <파일>" — 초는 채움 세션을 띄운 때부터, 그사이 재생·탐색으로 쉰 시간 포함).
    - 실패(세션 실패·이른 끝·넘침·READ_TIMEOUT_S 동안 프레임 없음·세션이나 스레드를 띄우지 못함·뜻밖의 예외)는 캡처의 죽음이 아니다(보조
      기능): 기록에 한 번(FILL_FAILURE_HEADLINE — 채운 장수·사유(트레이스백이 있으면 함께)·파일·명령·stderr) + failed에 사유, 세션 정리,
      채움 끝 — 캡처는 링·스트림·재시작으로 그대로 읽고 오류 창은 없다(스펙 §7-19). 넘침이면 번호를 믿을 수 없어 채운 것을 비우고, 그 밖의
      실패는 이미 넣은 장을 둔다(처음부터 차례로 받은 것이라 번호가 정확). 다시 채우지 않는다. 실패하면 예산 장부의 몫을 이미 넣은 만큼으로
      곧바로 줄인다(_LEDGER.shrink — 채우지 못한 몫은 다른 캡처가 쓸 수 있음; 넣은 장과 그 몫은 release까지 남음). 어떤 실패도 이 스레드 밖으로 내지 않는다.
    - 멈춤: halt()는 캡처의 잠금 안에서(release·죽음이 저장소를 비우는 바로 그 자리) 플래그만 — 그 뒤로는 넣지 않으므로 닫은 캡처에 한
      장이 새어 들어가지 않는다. stop()은 release·죽음·GC(캡처 단위 weakref.finalize)에서 플래그 + 채움 세션 정지(kill — 거두기는 세션의
      데몬 스레드), 기다리지 않음. 멈춘 뒤의 끊김은 실패가 아니다. release는 그 전에 드러나지 않은 채움 실패(쉬는 사이 죽은 ffmpeg)를
      기록에 한 번 남긴다(report_unsurfaced — 주 세션의 _log_unsurfaced와 같은 규칙).
    _lock이 지키는 것: _live(정지할 채움 세션)·session·started_at·done·failed — stop()과 세션 띄우기·끝내기·실패 알림이 엇갈려도 세션을
    놓치거나 실패를 두 번 알리지 않게. RLock: _lock을 쥔 채움 스레드에서 GC가 (순환 참조로 버려진) 캡처의 weakref.finalize(→ stop)를
    돌려도 스스로 막히지 않게 (_Transport의 잠금과 같은 까닭). index(다음에 넣을 번호 = 넣은 장수)는 캡처의 잠금 안에서 채움 스레드만 바꾼다.
    """

    def __init__(self, lock, store, clock, path, count, height, width, frame_bytes, ledger_key=None):
        self._capture_lock = lock
        self._store = store
        self._clock = clock
        self._path = path
        self._count = count
        self._height = height
        self._width = width
        self._frame_bytes = frame_bytes
        self._ledger_key = ledger_key  # 캡처의 장부 키 — 실패하면 몫을 넣은 만큼으로 줄임 (_LEDGER.shrink)
        self._lock = threading.RLock()
        self._wake = threading.Event()  # stop()이 쉬는 때 기다림을 깨움
        self._stopped = False  # 정지 플래그: halt·stop
        self._live = None  # 정지할 채움 세션 (띄운 뒤 끝내기 전까지)
        self.session = None  # 띄운 채움 세션 (끝낸 뒤에도 남김 — 시험·기록용)
        self.started_at = None  # 채움 세션을 띄운 때 (time.monotonic)
        self.index = 0  # 다음에 넣을 번호 = 넣은 장수
        self.done = False  # 파일 장수를 다 넣고 정상 끝을 확인함
        self.failed = None  # 채움 실패 사유 (없으면 None)
        self.thread = threading.Thread(target=self._run, name="ffmpeg-pipe-filler", daemon=True)

    def start(self):
        """채움 스레드를 띄움 — 띄우지 못해도(스레드 한도 등) 예외를 내지 않고 채움 실패로 기록 (판정하는 read 안에서 부름)."""
        try:
            self.thread.start()
        except Exception:
            self._fail(self._traced("채움 스레드를 띄우지 못했습니다"))

    def halt(self):
        """(캡처의 _lock 안에서 — release·죽음이 저장소를 비우는 자리) 더는 넣지 않게 플래그만. 세션 정지는 stop()."""
        self._stopped = True

    def stop(self):
        """정지 (release·죽음·GC — 여러 번 불러도 됨): 플래그 → 쉬는 때 기다림 깨우기 → 채움 세션 정지 (기다리지 않음)."""
        self._stopped = True
        self._wake.set()
        self._end_session()

    def report_unsurfaced(self, when):
        """(release — halt 뒤·stop 전) 채움 세션의 아직 드러나지 않은 실패(쉬는 사이 죽은 ffmpeg 등)가 있으면 failed에 적고 기록에 한 번.
        채움 스레드가 이미 알렸거나 끝냈으면 아무것도 안 함. 멈추기 전에 봐야 함 (멈춘 뒤에는 kill의 종료 코드가 실패처럼 보임)."""
        with self._lock:
            session = self._live if self.failed is None and not self.done else None
        failure = None if session is None else session.unsurfaced_failure()
        if failure is None:
            return
        with self._lock:
            if self.failed is not None:  # 그사이 채움 스레드가 먼저 알림
                return
            self.failed = failure
        self._log_failure(f"{when} 전에 드러나지 않은 실패 — {failure}", session)

    def _run(self):
        try:
            self._fill()
        except Exception:  # 이 스레드 밖으로 내지 않음 — 뜻밖의 오류도 채움 실패로 (캡처는 그대로)
            self._fail(self._traced("채움기가 뜻밖의 오류로 멈췄습니다"), self.session)
        finally:
            self._end_session()

    def _fill(self):
        """채움 본체: 쉬는 때마다 한 장씩 꺼내 넣음 → 다 넣으면 정상 끝 확인. 멈춤(stop·halt)이면 조용히 끝."""
        session = None
        while self.index < self._count:
            if not self._wait_idle():
                return
            if session is None:
                session = self._spawn()
                if session is None:
                    return
            outcome, value = session.take(READ_TIMEOUT_S)
            if outcome == _FRAME:
                if not self._keep(value):
                    return
                continue
            if outcome != _STOPPED:
                self._fail(self._session_failure(outcome, value), session)
            return
        outcome, value = session.take(READ_TIMEOUT_S)  # 다 넣음 — 이제 정상 끝(EOF)이어야 함 (더 오면 번호가 어긋난 것)
        if outcome == _END:
            self._finish()
        elif outcome != _STOPPED:
            self._fail(self._session_failure(outcome, value), session, clear=outcome == _FRAME)

    def _wait_idle(self):
        """쉬는 때(자기 캡처와 프로세스 전체 모두 read가 IDLE_FILL_DELAY_S 동안 없음)까지 FILL_POLL_S씩 기다림 → 참, 그사이
        멈춤(stop·halt)이면 거짓. IDLE_FILL_DELAY_S는 볼 때마다 모듈에서 읽는다 (시험이 바꿔 채움기를 붙잡아 둠)."""
        while not self._stopped:
            if min(self._clock.idle_for(), _PROCESS_READS.idle_for()) >= IDLE_FILL_DELAY_S:
                return True
            self._wake.wait(FILL_POLL_S)
        return False

    def _spawn(self):
        """채움 세션을 띄움 (주 세션과 같은 명령·전송 — 처음부터) → 세션, 또는 None (멈춤 / 띄우지 못해 실패로 기록)."""
        command, transport = (), None
        try:
            transport = _Transport()
            command = _pipe_command(self._path, transport.output)
            if self._stopped:  # Popen 바로 앞: 쉬는 때를 본 뒤 release·죽음이 세웠으면 쓸모없는 ffmpeg를 띄우지 않음 (남는 좁은 틈은 아래에서 곧바로 멈춤)
                transport.close()
                return None
            session = _PipeSession(command, transport, self._height, self._width, is_filler=True)
        except Exception:  # 소켓·실행 파일 없음(OSError·ToolNotFoundError)·스레드 시작 실패 — 캡처는 그대로
            if transport is not None:
                transport.close()  # 세션이 서지 못함 — 만든 소켓은 여기서
            self._fail(self._traced("채움 ffmpeg를 띄우지 못했습니다"), command=command)
            return None
        with self._lock:
            if not self._stopped:
                self.session = self._live = session
                self.started_at = time.monotonic()
                return session
        session.stop()  # 띄우는 사이 멈춤 (release·죽음·GC)
        return None

    def _keep(self, frame):
        """(채움 스레드) index번으로 frame(세션이 준 배열 그대로)을 전체 저장소에 넣음 — 캡처의 잠금 안에서 짧게.
        → 넣었으면 참, 멈춤(halt — 닫힘·죽음)이면 거짓."""
        with self._capture_lock:
            if self._stopped:
                return False
            self._store.keep(self.index, frame)
            self.index += 1
        return True

    def _session_failure(self, outcome, value):
        """채움 세션에서 꺼내다 본 실패의 사유 글."""
        got = f"{self.index}장을 넣은 뒤"
        if outcome == _FRAME:
            return f"ffmpeg가 파일의 프레임 수 {self._count}보다 많은 프레임을 줬습니다 — 번호를 믿을 수 없어 채운 것을 비웁니다"
        if outcome == _END:
            return f"ffmpeg가 {self.index}장을 주고 끝났습니다 (파일의 프레임 수 {self._count})"
        if outcome == _FAILED:
            return f"{value} — {got}"
        return f"ffmpeg가 {READ_TIMEOUT_S:g}초 동안 다음 프레임을 주지 않았습니다 ({got})"

    def _finish(self):
        """다 채움: done → 세션 정리 → 기록 한 줄 (멈춘 뒤면 아무것도 안 함)."""
        with self._lock:
            if self._stopped:
                return
            self.done = True
            elapsed = time.monotonic() - self.started_at
        self._end_session()
        try:
            print(f"{LOG_PREFIX} 프레임 캐시 채움 끝: {self._count}장 {frame_cache_budget.gb(self._frame_bytes * self._count)} "
                  f"({elapsed:.1f}초) — {os.path.basename(self._path)}")
        except Exception:
            _last_resort(f"프레임 캐시 채움 끝을 기록하지 못했습니다: {self._path}")

    def _fail(self, reason, session=None, command=(), clear=False):
        """채움 실패 (처음 한 번만): failed에 사유 → (clear — 넘침 — 면 채운 것을 비움) → 세션 정리 → 장부 몫을 넣은 만큼으로 줄임
        (_LEDGER.shrink — 이미 반환됐으면 아무것도 안 함) → 기록 한 번. 멈춘 뒤면(release·죽음·GC — 실패가 아님) 아무것도 안 함. 예외를 내지 않음."""
        with self._lock:
            if self._stopped or self.failed is not None:
                return
            self.failed = reason
        if clear:
            with self._capture_lock:
                if not self._stopped:
                    self._store.clear()
                    self.index = 0
        self._end_session()
        _LEDGER.shrink(self._ledger_key, self.index * self._frame_bytes)
        self._log_failure(reason, session, command)

    def _log_failure(self, reason, session, command=()):
        """기록(stderr)에 한 번: FILL_FAILURE_HEADLINE — 채운 장수·사유·파일·명령·stderr. 예외를 내지 않음 (기록마저 실패하면 _last_resort)."""
        try:
            if session is not None:
                command, stderr = session.command, session.stderr_text()
            else:
                stderr = ""
            error = PipeCaptureError(f"{reason}: {self._path}", command, stderr)
            print(f"{LOG_PREFIX} {FILL_FAILURE_HEADLINE} — 재생·탐색은 그대로입니다 (채운 {self.index}/{self._count}장, 나머지는 "
                  f"링·재시작으로 읽음; 예산 몫은 채움 실패면 채운 만큼 {frame_cache_budget.gb(self.index * self._frame_bytes)}으로 줄이고 "
                  f"닫기(release)면 모두 돌려줌): {error}",
                  file=sys.stderr, flush=True)
        except Exception:
            _last_resort(f"{FILL_FAILURE_HEADLINE} — 기록하지 못했습니다 ({reason}): {self._path}")

    def _end_session(self):
        """채움 세션 정지 (끝·실패·stop — 한 번만 돎, 기다리지 않음)."""
        with self._lock:
            session, self._live = self._live, None
        if session is not None:
            session.stop()

    @staticmethod
    def _traced(headline):
        """(except 블록 안에서) 사유 글: headline + 트레이스백 — 만들다 실패하면 고정 글 + 원래 예외 한 줄 (_fallback_reason)."""
        error = sys.exc_info()[1]
        try:
            return f"{headline}:\n{traceback.format_exc()}"
        except Exception:
            return _fallback_reason(f"{headline} (원인 글을 만들지 못했습니다)", error)


class FFmpegPipeCapture:
    """ProRes류 영상을 ffmpeg 파이프로 읽어 cv2.VideoCapture 자리에 꽂는 캡처 — read·isOpened·release·get·set의 의미가 cv2와
    같다 (ImageSequenceCapture와 같은 계약). 게이트(pipe_eligible)를 통과한 파일의 probe와 함께 만든다.

    read()는 다음 프레임(호출자가 써도 되는 새 배열)을 주고 pos를 1 올림. 끝에서는 (False, None)이고 pos는 그대로 — 단 받은 수가
    nb_frames와 맞을 때만 끝이다. get(CAP_PROP_POS_FRAMES)는 다음에 읽을 인덱스(set이 기록한 목표가 있으면 그 값), FPS는
    float(avg)(cv2와 같은 출처), FRAME_COUNT는 nb_frames, 크기는 probe 값, 그 밖의 속성은 0.0. release한 캡처·죽은 캡처는 cv2처럼
    isOpened False, read (False, None), get 0.0, set False.

    탐색 (스펙 §5.4): set(CAP_PROP_POS_FRAMES, n)은 목표만 기록한다(지연 — 연속 set은 이동 한 번, 곧 release될 캡처의 set은 공짜).
    이동은 다음 read()가 목표 n(기록된 목표, 없으면 pos)으로: ① n == 스트림 위치 → 스트림에서 꺼내 내줌 ② 보관본(_FrameStore — 링
    _ring: 주 세션에서 최근 꺼낸 KEEP_BEHIND장을 먼저, 그다음 전체 저장소 _full: 전체 모드의 채움기가 채운 번호)에 있음 → 그 복사본(재시작
    없음; 전체 저장소에서 내주면 스트림을 보관본 끝으로 미리 옮겨 둠 — _store_frontier, 이미 그 구간 안이면 그대로, 링은 비우지 않음) ③ 스트림 위치 < n ≤ 스트림 위치 + SEEK_FORWARD_MAX → 큐·스트림에서 꺼내 버린 뒤 ①(버린 프레임도 링에 보관) ④ 그 밖 → 세션
    재시작: -ss (n − K)/r + (영상 트랙 start − 컨테이너 start), 그 뒤 K장 버리고(링에 보관됨) ①. K는 방향에 따라: 앞으로(n > 스트림 위치)
    K = min(SEEK_BACK_K, n) = 0 — 목표에서 바로; 뒤로(n < 스트림 위치) K = min(max(SEEK_BACK_K, KEEP_BEHIND), n) = min(8, n) — 목표 8장
    앞에서 띄워 그 8장을 보관하므로 이어지는 ←가 링에서 나온다 (링 밖의 ←가 매번 재시작이던 것이 8번에 한 번 — 4K에서 재시작 ~0.5초에
    디코드 8장 ≈0.16초가 더해짐; 링은 8장 FIFO라 n을 넣을 때 n − 8이 밀려나 착지 뒤 링은 n − 7..n — 전체 모드도 같음, 미리 채우기는
    링에만 씀). 재시작은 새 세션을 띄워 캡처의 세션·GC 안전망을 넘긴 뒤 옛 세션을 멈춘다(정지 플래그 — 옛 프로세스의 끊김은 실패가 아님).

    위치 장부 — pos: 다음에 내줄 번호. 스트림 위치(_stream_pos): 세션이 다음에 줄 번호 = 세션 시작 번호 + 그 세션에서 꺼낸 수.
    링(_ring): 주 세션에서 꺼낸 프레임(내주든 버리든)을 그 번호로 — 재시작에서 비우므로 늘 최근 것들의 연속 구간 [링 start, 스트림
    위치). 전체 저장소를 빼고 보면(링 모드, 또는 채움 전) 열려 있는 동안 늘 링 start ≤ pos ≤ 스트림 위치 (탐색 도중만 예외 — 끝나면
    pos = 목표 = 스트림 위치): pos < 스트림 위치면 다음 read는 링에서(복사본), 같으면 스트림에서 꺼낸다 — 그래서 링으로 뒤로 간 뒤의
    순차 read는 링의 나머지 → 스트림 현재 위치로 이어진다 (전체 저장소에서 내주는 동안은 pos가 그 구간 어디든 될 수 있고, 스트림 위치에
    닿으면 ①로 스트림을 다시 따라감). 세션에서 꺼낼 때마다 스트림 위치 < nb_frames여야 하고(아니면 넘침), 정상 끝은 스트림
    위치 == nb_frames에서의 EOF뿐이다 (EOF 불변식: 재시작 세션은 시작 번호부터 세므로 '그 세션이 줄 수 = nb_frames − 시작'으로
    기준이 저절로 바뀜 — 끝까지 재생해도 가짜 실패 없음).

    프레임 캐시 (스펙 §6·§6.5): full_cache=True(플레이어 A/B만)인 캡처는 첫 read 머리에서 한 번(_decide_cache) 예산을 보고 전체 모드면
    파일 장수 크기·재시작을 건너 남는 전체 저장소(_full)와 쉬는 시간 채움기(_Filler)를 만든다 — "전체"는 '읽는 동안은 링 + 쉬는 때
    채움'이라는 뜻: read가 내준 프레임은 전체 모드도 링에만 두고(재생 중 보관 비용 — IDLE_FILL_DELAY_S 주석), read가 IDLE_FILL_DELAY_S
    동안 없을 때(이 캡처도, 이 프로세스의 다른 파이프 캡처도 — A/B에서 한쪽만 재생해도 다른 쪽은 채우지 않음) 채움기가 따로 띄운 ffmpeg로
    처음부터 채운다. 채움기가 채운 번호로의 탐색은 재시작이 없고, 규칙 ①이 먼저라 보관 구간을
    지나는 순차 재생은 스트림을 그대로 따라간다(스트림 우선 — 보관 구간을 벗어날 때 재시작은 많아야 한 번). 채움 진행은
    fill_done·fill_index·fill_failed·fill_session과 wait_fill(timeout)으로 본다(시험용). 채움기 실패는 기록 한 번이고 캡처는 그대로(죽지
    않음, 오류 창 없음 — 스펙 §7-19), 예산 장부의 몫은 채운 만큼으로 곧바로 줄어듦. opt-in하지 않았거나, 킬 스위치(YESONCHECK_FRAME_CACHE=ring)거나, 예산이 모자라면 링 모드
    (cache_mode: None·"ring"·"full") — 채움기 없음.

    생성자가 ffmpeg를 띄우고 첫 프레임이 올 때까지 기다린다(eager) — 못 열면 PipeCaptureError(원인·명령·stderr 전문). 첫 프레임은
    큐에 남아 첫 read()가 씀 (두 번 디코드하지 않음). ffmpeg를 찾지 못하면(ToolNotFoundError — 빌드 깨짐) 감싸지 않고 그대로 올라간다.
    탐색 재시작은 첫 프레임을 기다리지 않는다 (그 뒤의 꺼내기가 READ_TIMEOUT_S까지 기다림).

    생성 뒤의 read·get·set은 예외를 내지 않는다 (스펙 §5.5 — 탐색 실행 중도, 첫 read의 캐시 판정도). 도중 실패 — 프레임 중간에서
    끊김, ffmpeg 비정상 종료, 끝났는데 받은 수가 nb_frames와 다름(모자람·넘침 — 재시작 착지가 어긋난 경우도 여기서 걸림),
    READ_TIMEOUT_S 동안 다음 프레임이 없음, 재시작할 ffmpeg를 띄우지 못함, 첫 read에서 프레임 캐시 예산을 정하지 못함(psutil 오류
    등 — 이것은 그 read에서 바로) — 은 큐에 남은 정상 프레임을 다 준 뒤에 드러나고, 그때 캡처가 스스로: 세션
    정리(kill — 거두기는 데몬 스레드) → 죽음 상태 → 기록에 한 번(원인·읽던 곳의 호출 스택·명령·stderr 전문) → 오류 창을 Qt 루프에서
    한 번 (_report_failure). 죽은 뒤의 read는 다시 알리지 않는다. 드러나기 전의 실패를 품은 세션을 버릴 때(release·탐색 재시작)는
    기록에만 한 번 남긴다.

    스레드: read()는 한 번에 한 스레드만 부른다 — 같은 캡처를 여러 스레드가 동시에 read하는 것은 지원하지 않는다 (위치 장부·탐색이
    read 한 호출 안에서 이어지는 일이라; 지금 앱의 소비자는 모두 한 스레드에서 read). get·set·release는 다른 스레드에서 불러도
    된다: 캡처의 상태(_session·_finalizer·_ledger_finalizer·_fill_finalizer·_filler·_pos·_stream_pos·_ring·_full·_target)는 _lock이 지키고
    (채움기도 전체 저장소에 넣을 때 이 잠금을 짧게 잡음 — 소켓을 기다리는 동안은 아님; read 활동 시계 _reads·_PROCESS_READS는 제 잠금), read()는 프레임을 기다리는 동안과
    ffmpeg를 띄우는 동안 _lock을 잡지 않는다 — 다른 스레드의 release가 기다림을 깨워 끝낼 수 있다(그 read는 (False, None), 실패
    아님). 죽음 전이는 '_session이 아직 그 세션일 때 None으로 바꾼 쪽'만 하므로 한 번뿐. release 없이 버려진 캡처의 ffmpeg는
    weakref.finalize가 끝낸다 (인터프리터가 끝날 때도) — 재시작하면 새 세션으로 다시 등록하고 옛 것은 불러서 끝낸다. 전체 보관의
    장부와 채움기 정지(채움 ffmpeg)는 따로 캡처에 등록한 weakref.finalize가 맡는다 (release·죽음은 그것을 불러서 — 한 번만; 채움기는
    캡처를 붙잡지 않으므로 버려진 캡처의 GC가 늘 돎).
    """

    def __init__(self, path, probe, full_cache=False):
        if probe.width < 1 or probe.height < 1 or (probe.nb_frames or 0) < 1 or probe.avg is None or probe.r is None:
            raise ValueError(f"파이프로 열 수 없는 probe입니다 (pipe_eligible을 먼저 볼 것): {probe}")
        self._path = path
        self._count = probe.nb_frames
        self._fps = float(probe.avg)
        self._rate = probe.r  # 탐색 시각은 정확한 분수 r로 (get(FPS)의 float(avg)와 따로 — 스펙 §4)
        self._start_offset = probe.video_start - probe.format_start  # 재시작 -ss의 트랙 시작 오프셋 보정 (스펙 §5.4)
        self._width = probe.width
        self._height = probe.height
        self._lock = threading.Lock()
        self._session = None  # 지금 세션. None = 닫힘(release)·죽음
        self._pos = 0  # 다음에 내줄 프레임 번호
        self._stream_pos = 0  # 스트림 위치: 세션이 다음에 줄 프레임 번호 (재시작에서 시작 번호, 꺼낼 때마다 +1)
        self._ring = _FrameStore(KEEP_BEHIND, keep_across_restart=False)  # 주 세션에서 꺼낸 프레임의 보관 — 최근 KEEP_BEHIND장 (두 모드 모두)
        # 전체 저장소: 링 모드는 0장(아무것도 넣지 않음), 전체 모드면 판정이 파일 장수로 바꾸고 채움기(_Filler)만 씀 (스펙 §6.5)
        self._full = _FrameStore(0, keep_across_restart=True)
        self._reads = _ReadClock()  # 이 캡처의 read() 활동 — 채움기가 쉬는 때를 봄 (프로세스 시계 _PROCESS_READS와 함께; 캡처 대신 이것만 넘김)
        self._filler = None  # 전체 모드의 쉬는 시간 채움기 (판정이 만듦)
        self._fill_finalizer = None  # 전체 모드면 채움기 정지 (캡처의 weakref.finalize — release·죽음·GC가 같이 쓰고 한 번만 돎)
        self._target = None  # set()이 기록한 탐색 목표 (0~count 정수, 다음 read()가 실행 — get(POS_FRAMES)는 이것을 보임)
        self._full_cache_wanted = full_cache  # 부른 쪽이 전체 보관을 원함 (플레이어 A/B만) — 판정은 첫 read(_decide_cache)
        self._cache_mode = None  # 프레임 캐시 판정: None(첫 read 전)·"ring"·"full"
        self._frame_bytes = probe.width * probe.height * 3  # bgr24 한 장
        self._ledger_key = None  # 전체 보관이면 장부(_LEDGER)의 키
        self._ledger_finalizer = None  # 전체 보관이면 장부 반환 (캡처의 weakref.finalize — release·죽음·GC가 같이 쓰고 한 번만 돎)
        try:
            transport = _Transport()  # ffmpeg 출력을 받을 소켓 — Popen 전에
        except OSError as exc:
            raise PipeCaptureError(f"ffmpeg 출력을 받을 소켓을 만들지 못했습니다 ({exc}): {path}", (), "") from exc
        command = ()
        try:
            command = _pipe_command(path, transport.output)  # ffmpeg가 없으면 ToolNotFoundError — 아래에서 소켓만 닫고 그대로
            session = _PipeSession(command, transport, probe.height, probe.width)
        except OSError as exc:
            transport.close()
            raise PipeCaptureError(f"ffmpeg를 실행하지 못했습니다 ({exc}): {path}", command, "") from exc
        except BaseException:
            transport.close()
            raise
        self._finalizer = weakref.finalize(self, session.stop)  # 세션을 멈추는 단 하나의 길 (release·죽음·GC·재시작이 같이 씀)
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

    @property
    def cache_mode(self):
        """프레임 캐시 판정 — None(첫 read 전)·"ring"·"full" (시험·기록용)."""
        return self._cache_mode

    @property
    def fill_done(self):
        """전체 저장소가 파일의 모든 프레임을 다 채웠는가 (시험·도구용) — 링 모드는 채울 것이 없어 참, 판정 전(첫 read 전)·닫힘·죽음은 거짓."""
        if self._session is None or self._cache_mode is None:
            return False
        return self._cache_mode == "ring" or (self._filler is not None and self._filler.done)

    @property
    def fill_index(self):
        """채움기가 다음에 넣을 번호 = 전체 저장소에 넣은 장수 (채움기가 없으면 0)."""
        return 0 if self._filler is None else self._filler.index

    @property
    def fill_failed(self):
        """채움 실패 사유 (없으면 None) — 기록에 한 번 남기고 캡처는 그대로 (스펙 §7-19)."""
        return None if self._filler is None else self._filler.failed

    @property
    def fill_session(self):
        """채움기가 띄운 채움 세션 (_PipeSession, is_filler 참 — 아직 안 띄웠거나 채움기가 없으면 None, 끝낸 뒤에도 남김 — 시험용)."""
        return None if self._filler is None else self._filler.session

    def wait_fill(self, timeout):
        """(시험·도구용) 전체 저장소가 다 찰 때까지 최대 timeout초 기다림 → fill_done. 링 모드는 곧바로 참, 채움이 실패했거나 캡처가
        닫혔·죽었으면 기다리지 않고 거짓. read 활동이 아니라 채움을 막지 않음 (GUI 스레드에서 불러도 Qt 이벤트는 돌리지 않음 — 채움에는
        Qt가 필요 없음)."""
        deadline = time.monotonic() + timeout
        while not self.fill_done:
            if self.fill_failed is not None or self._session is None or time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def read(self):
        reads = self._reads  # 채움기가 보는 read 활동: 이 캡처의 시계와 프로세스 시계 둘 다 (_ReadClock — 들어올 때·나갈 때 시각, 그 사이 busy)
        reads.enter()
        _PROCESS_READS.enter()
        try:
            return self._read()
        finally:
            _PROCESS_READS.leave()
            reads.leave()

    def _read(self):
        if self._cache_mode is None:  # 첫 read: 프레임 캐시 판정을 한 번 (_lock 밖 — 메모리를 읽음)
            self._decide_cache()
        served = park = None
        with self._lock:
            session, target = self._session, self._target
            if session is None:
                return False, None
            n = self._pos if target is None else target  # 이번에 내줄 번호 (지연 탐색의 목표가 있으면 그것)
            ahead = n - self._stream_pos
            if ahead == 0:  # ① 스트림 위치 — 아래에서 꺼내 내줌
                self._arrive(n, target)
            elif self._ring.has(n) or self._full.has(n):  # ② 보관본의 복사본 (세션 그대로) — 링을 먼저, 그다음 채움기가 채운 전체 저장소
                from_ring = self._ring.has(n)
                served = (self._ring if from_ring else self._full).copy_of(n)
                self._arrive(n + 1, target)
                if not from_ring:
                    park = self._store_frontier(n)
        if served is not None:
            if park is not None:  # 보관본이 끝나는 곳으로 스트림을 미리 옮겨 둠 — 실패면 _restart가 죽음까지 알림(이 프레임은 그대로 내줌)
                self._restart(session, park, backward=False, park=True)
            return True, served
        if ahead:  # ③ 앞으로 버리기 / ④ 재시작(ahead < 0이면 뒤로 — 미리 채움) — 끝나면 스트림 위치 == n (①)
            session = self._seek(session, n, target, restart=not 0 < ahead <= SEEK_FORWARD_MAX, backward=ahead < 0)
            if session is None:
                return False, None
        return self._pull(session, deliver=True)

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
        """CAP_PROP_POS_FRAMES의 목표를 기록하고 True — cv2처럼 0~count로 자르고 소수는 버림 (-3 → 0, count+5 → count,
        119.7 → 119; NaN·무한은 0 — x86 cv2와 같음). get(POS_FRAMES)는 곧바로 그 값, 실제 이동은 다음 read()가 한다 (지연).
        닫힌·죽은 캡처, 다른 속성은 False. 숫자가 아닌 value는 cv2처럼 TypeError(부른 쪽의 버그)."""
        number = float(value)
        target = min(max(int(number), 0), self._count) if math.isfinite(number) else 0
        with self._lock:
            if self._session is None or prop != cv2.CAP_PROP_POS_FRAMES:
                return False
            self._target = target
            return True

    def release(self):
        """닫기 (여러 번 불러도 됨): 세션을 떼고 두 보관본(링·전체 저장소)을 비우고 채움기를 세움(halt — 그 뒤로 넣지 않음) → 전체
        보관이면 장부 반환 → 채움기 정지(드러나지 않은 채움 실패가 있었으면 기록 한 번, 채움 세션 kill) → 세션 stop(정지 플래그·큐 비움·
        막힌 recv 깨우기·kill — 거두기와 남은 소켓·파이프 닫기는 세션의 데몬 스레드, 여기서 기다리지 않음). 드러나기 전의 실패(멈춰 둔
        사이 죽은 ffmpeg)가 있었으면 기록에만 한 번 남김 (닫는 영상이라 창은 없음)."""
        with self._lock:
            session, self._session = self._session, None
            self._pos, self._target, self._stream_pos = 0, None, 0
            filler = self._clear_stores()
            finalizer, ledger, fill_stop = self._finalizer, self._ledger_finalizer, self._fill_finalizer
        if ledger is not None:
            ledger()  # 장부 반환 — weakref.finalize라 한 번만 돌고 GC 안전망에서도 빠짐
        self._stop_filler(filler, fill_stop, "닫기(release)")
        if session is None:
            return
        failure = session.unsurfaced_failure()
        finalizer()
        if failure is not None:
            self._log_unsurfaced("닫기(release)", session, failure)

    def _clear_stores(self):
        """(_lock 안 — release·죽음) 두 보관본을 비우고 채움기를 세움(halt — 같은 잠금 안이라 그 뒤 채움기는 한 장도 넣지 못함) → 채움기 (없으면 None)."""
        self._ring.clear()
        self._full.clear()
        if self._filler is not None:
            self._filler.halt()
        return self._filler

    def _stop_filler(self, filler, stop, when=None):
        """(release·죽음 — _lock 밖) 채움기 정지: when이 있으면(release) 드러나지 않은 채움 실패를 먼저 기록 → 채움 세션 정지(캡처의
        weakref.finalize라 한 번만 돌고 GC 안전망에서도 빠짐). 예외를 내지 않음 (죽음은 read 안 — §5.5; 보조 기능이 닫기를 막지 않게)."""
        if filler is None:
            return
        try:
            if when is not None:
                filler.report_unsurfaced(when)
            stop()
        except Exception:
            _last_resort(f"프레임 캐시 채움기를 멈추지 못했습니다: {self._path}")

    def _decide_cache(self):
        """(첫 read 머리, _lock 밖에서 한 번) 프레임 캐시 판정 → _cache_mode "ring"·"full" (스펙 §6·§6.5).

        opt-in하지 않은 캡처(full_cache 거짓 — open_any_capture 등)와 킬 스위치(YESONCHECK_FRAME_CACHE=ring)는 링이고 기록 없음 —
        1.5.1과 같은 경로. 아니면 지금 메모리(frame_cache_budget.memory_snapshot)와 다른 캡처가 잡은 바이트(_LEDGER)로
        full_cache_decision: 전체면 파일 장수만큼의 전체 저장소(재시작을 건너 남음 — 채움기만 씀)와 쉬는 시간 채움기(_Filler)를 만들고
        장부에 올린다 — 반환은 release·죽음·GC(캡처의 weakref.finalize — 세션의 finalize는 재시작마다 바뀌므로 따로; 채움기 정지도
        같은 식으로 캡처에 따로 등록). 읽는 동안 내준 프레임은 전체 모드도 링에만 둔다. 판정했으면 전체든 링이든 기록 한 줄
        ("[파이프] 프레임 캐시: 전체 …" / "… 링 8장 — 파일 …"). 생성자가 아니라 첫 read에서 정하는 까닭: 플레이어의 open_file은 새
        캡처를 연 뒤 옛 캡처를 놓고 첫 프레임을 읽는다 — 옛 캡처가 놓은 예산을 새 캡처가 쓰게.
        판정하다 난 예외(psutil 오류, 토글의 나쁜 값 — 앱은 시작 때 검증 — 등)는 read 밖으로 내지 않는다 (§5.5 — 재생 타이머 슬롯에는
        try가 없어 PyQt5가 프로세스를 끝냄): 도중 실패(B)와 같이 죽음 전이 → _die(기록 한 번·트레이스백째, 오류 창 한 번)이고 그 read는
        (False, None) — 그 사유 글(트레이스백)을 만들다 실패해도 고정 사유(+ 원래 예외 한 줄, _fallback_reason)로 같은 길. 사유 끝에는
        늘 탈출구 안내(FRAME_CACHE_ESCAPE_HINT — 킬 스위치면 psutil을 부르지 않음)를 붙인다. 판정 기록을 남기다 난 실패는 다른 기록
        실패처럼 _last_resort로 (캡처는 그대로)."""
        try:
            decision = self._settle_cache()
        except Exception as error:
            try:  # 트레이스백(끝에 줄바꿈) 다음 줄에 탈출구 안내 — 기록과 오류 창(사유는 창에 그대로 실림)에 함께
                reason = f"프레임 캐시 예산을 정하지 못했습니다:\n{traceback.format_exc()}{FRAME_CACHE_ESCAPE_HINT}"
            except Exception:  # 사유 글을 만들다 실패(메모리 부족 등)해도 read 밖으로 내지 않음 — _die가 알릴 글을 지키는 것과 같이
                reason = _fallback_reason("프레임 캐시 예산을 정하지 못했습니다 (원인 글을 만들지 못했습니다)",
                                          error) + "\n" + FRAME_CACHE_ESCAPE_HINT
            self._cache_mode = "ring"  # 다시 판정하지 않음 (죽은 캡처 — 보관본은 _die가 비움)
            with self._lock:
                session, self._session = self._session, None  # 죽음 전이 — 세션이 아직 있을 때만 (이미 닫혔으면 알릴 것 없음)
            if session is not None:
                self._die(reason, session=session)
            return
        if decision is None:  # 기록 없는 링 (opt-in 안 함·킬 스위치·그사이 닫힘)
            return
        reason = decision.reason if decision.full else decision.reason.replace("링", f"링 {KEEP_BEHIND}장", 1)
        try:
            print(f"{LOG_PREFIX} 프레임 캐시: {reason} — {os.path.basename(self._path)}")
        except Exception:
            _last_resort(f"프레임 캐시 판정을 기록하지 못했습니다 ({reason}): {self._path}")

    def _settle_cache(self):
        """(_decide_cache 안) 판정을 정해 캡처에 반영 → 기록할 CacheDecision, 기록 없는 링이면 None. 예외는 부른 쪽(_decide_cache)이 받는다."""
        if not self._full_cache_wanted or frame_cache_mode() == "ring":
            self._cache_mode = "ring"
            return None
        ram_total, available = frame_cache_budget.memory_snapshot()
        decision = frame_cache_budget.full_cache_decision(
            self._frame_bytes, self._count, ram_total, available, _LEDGER.committed())
        filler = None
        with self._lock:
            if self._session is None:  # 판정 전·도중에 닫힘(다른 스레드의 release) — 보관도 장부도 잡지 않음
                self._cache_mode = "ring"
                return None
            if decision.full:
                self._full = _FrameStore(self._count, keep_across_restart=True)  # 채움기만 씀 — read가 내준 프레임은 링에만 (스펙 §6.5)
                self._ledger_key = id(self)
                # 반환 길을 먼저 걸고 장부에 올림 — 그 사이 무엇이 실패해도 장부가 새지 않게 (없는 키의 release는 무시)
                self._ledger_finalizer = weakref.finalize(self, _LEDGER.release, self._ledger_key)
                _LEDGER.add(self._ledger_key, decision.total_bytes)
                filler = _Filler(self._lock, self._full, self._reads, self._path, self._count, self._height, self._width,
                                 self._frame_bytes, self._ledger_key)
                self._filler = filler
                # release 없이 버려진 캡처도 채움 ffmpeg를 남기지 않게 — 채움기는 캡처를 붙잡지 않으므로 GC가 늘 돎
                self._fill_finalizer = weakref.finalize(self, filler.stop)
            self._cache_mode = "full" if decision.full else "ring"
        if filler is not None:
            filler.start()  # 쉬는 때를 기다리는 스레드 — 채움 세션은 처음 쉬는 때 띄움 (start는 예외를 내지 않음)
        return decision

    def _arrive(self, pos, target):
        """(_lock 안) 이동을 마침: pos를 정하고 이번 read가 실행한 목표를 지움 (그사이 다른 목표가 기록됐으면 그것은 다음 read의 몫)."""
        self._pos = pos
        if target is not None and self._target == target:
            self._target = None

    def _seek(self, session, n, target, restart, backward):
        """(read 안, _lock 밖) 스트림을 n번으로 옮김 (스펙 §5.4): restart면 ④ 세션 재시작(시작 번호 n − K, backward — n < 스트림 위치 —
        면 K가 KEEP_BEHIND: _restart) 뒤, 스트림 위치가 n이 될 때까지 꺼내 버림 (③ 앞으로 버리기·재시작 뒤 K장 — 버린 프레임도
        보관됨: 뒤로 재시작의 미리 채우기가 이것). 닿으면 pos = n = 스트림 위치이고 목표를 지움.
        → 이동을 마친 세션, 또는 None (그사이 release됨 / 죽음 — 알림까지 끝냄)."""
        if restart:
            session = self._restart(session, n, backward)
            if session is None:
                return None
        while True:
            with self._lock:
                if self._session is not session:
                    return None
                if self._stream_pos == n:
                    self._arrive(n, target)
                    return session
            if not self._pull(session, deliver=False)[0]:  # 버리기 — 목표 앞(< count)의 끝은 도중 실패
                return None

    def _store_frontier(self, n):
        """(_lock 안) 전체 저장소에서 n을 내준 뒤 스트림을 옮겨 둘 번호 — n 다음으로 전체 저장소에 없는 첫 번호, 옮길 필요가 없으면 None
        (파일 끝까지 다 있음·스트림이 이미 그 구간 안(n < 스트림 위치 ≤ 끝)이라 재생이 스트림에 닿을 때까지 보관본). 왜: 채움기가 앞부분만 채운 채 처음으로 돌아가면(반복 재생) 보관본을 내주는 동안 스트림은
        멀리(파일 끝) 서 있다가 보관본이 끝나는 곳에서야 재시작해 재생 도중에 멈췄음(Windows 4K 0.75~0.84초 — 사용자 기록 2026-11-06, ring이면
        없음). 보관본을 내주기 시작할 때 옮겨 두면 ffmpeg가 그동안 준비해 끝에 닿을 때 ①로 이어짐. 채움기는 0부터 차례로 채우므로 보관본은
        앞에서부터 이어진 구간."""
        frontier = n + 1
        while frontier < self._count and self._full.has(frontier):
            frontier += 1
        if frontier >= self._count or n < self._stream_pos <= frontier:
            return None  # 끝까지 다 있음, 또는 스트림이 이미 그 구간 안 — 재생이 스트림에 닿을 때까지 보관본 (리뷰: 멈춘 동안 보관본이 늘어 끝이 움직여도 다시 옮기지 않게)
        return frontier

    def _restart(self, old, target, backward, park=False):
        """(read 안, _lock 밖) 세션 재시작: 목표 K장 앞(start)을 -ss로 겨눈 새 ffmpeg → 캡처의 세션·GC 안전망을 새 세션으로 바꾸고
        스트림 위치를 start로(링은 on_restart로 비움 — 전체 저장소는 그대로; pos는 목표로) → 옛 세션 정지. → 새 세션, 또는 None (띄우지 못해
        죽음 — 알림까지 끝냄 / 띄우는 사이 release됨). 띄우지 못한 사유 글(트레이스백)을 만들다 실패해도 고정 사유(+ 원래 예외 한 줄)로
        죽음 — read 밖으로 예외를 내지 않음 (§5.5).
        K: 앞으로(backward 거짓) SEEK_BACK_K(0 — 목표에서 바로, 슬라이더를 앞으로 끄는 점프가 느려지지 않게), 뒤로(backward — 목표 <
        스트림 위치) KEEP_BEHIND — 0에서 자름. 뒤로는 start..목표−1을 _seek가 꺼내 버리며 보관해(on_restart로 비운 뒤라 남음) 이어지는 ←가
        재시작 없이 나온다: 4K에서 링 밖의 ←가 매번 재시작(~0.5초)이던 것이 8번에 한 번(디코드 8장 ≈0.16초가 더해져 약 0.6초).
        park: 보관본 끝으로 미리 옮겨 둠(_store_frontier) — 내줄 번호(pos)도 링도 그대로, 스트림 위치만 target으로."""
        back = max(SEEK_BACK_K, KEEP_BEHIND) if backward else SEEK_BACK_K
        start = target - min(back, target)
        command, transport = (), None
        try:
            transport = _Transport()
            command = _pipe_command(self._path, transport.output, self._seek_seconds(start))
            new = _PipeSession(command, transport, self._height, self._width, start)
        except Exception as error:  # §5.5: read 밖으로 내보내지 않음 — 소켓·실행 파일 없음(OSError·ToolNotFoundError)·스레드 시작 실패
            headline = (f"보관본 끝({target}번)으로 스트림을 미리 옮기려고 ffmpeg를 다시 띄우지 못했습니다" if park
                        else f"{target}번 프레임으로 탐색하려고 ffmpeg를 다시 띄우지 못했습니다")
            try:
                reason = f"{headline}:\n{traceback.format_exc()}"
            except Exception:  # 사유 글을 만들다 실패해도 read 밖으로 내지 않음 (_decide_cache와 같음)
                reason = _fallback_reason(f"{headline} (원인 글을 만들지 못했습니다)", error)
            if transport is not None:
                transport.close()  # 세션이 서지 못함 — 만든 소켓은 여기서
            with self._lock:
                dying = self._session is old
                if dying:
                    self._session = None  # 죽음 전이
            if dying:
                self._die(reason, command=command)
            return None
        unsurfaced = old.unsurfaced_failure()  # 멈추기 전에 (멈춘 뒤에는 kill의 종료 코드가 실패처럼 보임)
        with self._lock:
            swapped = self._session is old
            if swapped:
                self._session = new
                old_finalizer, self._finalizer = self._finalizer, weakref.finalize(self, new.stop)
                if not park:  # 링만 비움 — 전체 저장소는 채움기 것이라 그대로. 옮겨 두기는 링도 그대로(보던 자리로 돌아갈 때 재시작이 없게 — 리뷰;
                    self._ring.on_restart()  # 링은 번호로 찾으므로 옛 장이 남아도 번호는 맞고, 새로 꺼낸 장이 들어오면 FIFO로 밀려남)
                # pos는 목표 그대로 — 미리 채우는 동안(start..목표−1을 버리는 중) 다른 스레드의 get(POS_FRAMES)가 목표 앞 번호를 보지 않게
                self._stream_pos = start
                if not park:  # 옮겨 두기는 지금 내주는 자리(pos)를 바꾸지 않음
                    self._pos = target
        if not swapped:  # 띄우는 사이 다른 스레드가 release함
            new.stop()
            return None
        old_finalizer()  # 옛 세션 정지 — 한 번만 불리고 GC 안전망에서도 빠짐
        if unsurfaced is not None:
            self._log_unsurfaced("보관본 끝으로 미리 옮기기" if park else "탐색 재시작", old, unsurfaced)
        return new

    def _seek_seconds(self, index):
        """index번 프레임의 -ss 시각(초): index / r (정확한 분수) + 영상 트랙 start − 컨테이너 start. -ss는 컨테이너 start 기준이라
        트랙 오프셋을 더하지 않으면 영상 start 0.5s 파일에서 12프레임 앞에 착지한다 (스펙 §3b·§5.4, external_tools 선례)."""
        return float(Fraction(index) / self._rate) + self._start_offset

    def _pull(self, session, deliver):
        """(read 안) 세션에서 다음 프레임 하나를 꺼내(기다리는 동안 _lock 없음) 스트림 위치 번호로 링에 보관하고(세션이 준 배열 그대로)
        스트림 위치를 1 올림 — deliver면 호출자에게 내주는 것(pos도 전진, 내주는 것은 보관본과 독립인 복사본), 아니면 버리기.
        → (True, 복사본) · 버리기면 (True, None) / (False, None): 정상 끝(스트림 위치 == count) · 그사이 release · 도중 실패(여기서
        죽음 전이와 알림까지)."""
        outcome, value = session.take(READ_TIMEOUT_S)
        with self._lock:
            if self._session is not session:  # 기다리는 사이 다른 스레드가 release함 (일부러 끝냄 — 실패 아님)
                return False, None
            if outcome == _FRAME and self._stream_pos < self._count:
                self._ring.keep(self._stream_pos, value)  # 링에만 — 전체 모드도 읽는 동안은 붙잡지 않음 (스펙 §6.5)
                self._stream_pos += 1
                if not deliver:
                    return True, None
                self._pos += 1
                return True, value.copy()  # 복사는 내주는 프레임마다 한 번 (보관본은 원본)
            clean_end = outcome == _END and self._stream_pos == self._count  # 정상 끝: cv2처럼 pos 그대로, 열린 채
            if clean_end:
                leftover = "" if session.eof_noted else session.stderr_text()  # 끝났으니 stderr는 전부 받음
                session.eof_noted = True
            else:
                reason = self._failure_reason(session, outcome, value)
                self._session = None  # 죽음 전이 — 이 줄에 닿는 것은 세션마다 한 번
        if clean_end:
            if leftover.strip():
                self._log_eof_stderr(session, leftover)
            return False, None
        self._die(reason, session=session)
        return False, None

    def _failure_reason(self, session, outcome, value):
        """(_lock 안에서) 세션에서 꺼내다 본 도중 실패의 원인 글. 재시작한 세션이면 시작 번호와 그 세션이 준 수로 말한다."""
        received = self._stream_pos - session.start
        if session.start:
            got = f"{session.start}번 프레임에서 다시 연 세션이 {received}장을 준 뒤"
        else:
            got = f"{received}장을 받은 뒤"
        if outcome == _FRAME:
            hint = " — 탐색 착지가 목표보다 앞이었을 수 있음" if session.start else ""
            return f"ffmpeg가 파일의 프레임 수 {self._count}보다 많은 프레임을 줬습니다 ({got}{hint})"
        if outcome == _END:
            if session.start:
                return (f"ffmpeg가 {session.start}번 프레임에서 다시 연 세션에서 {received}장을 주고 끝났습니다 "
                        f"(파일의 프레임 수 {self._count} — {self._count - session.start}장이어야 함: 탐색 착지가 목표보다 "
                        "뒤였거나 파일이 잘림)")
            return f"ffmpeg가 {received}장을 주고 끝났습니다 (파일의 프레임 수 {self._count})"
        if outcome == _FAILED:
            return f"{value} — {got}"
        if outcome == _TIMEOUT:
            return f"ffmpeg가 {READ_TIMEOUT_S:g}초 동안 다음 프레임을 주지 않았습니다 ({got})"
        return f"ffmpeg 세션이 멈춰 있습니다 ({got})"

    def _log_eof_stderr(self, session, stderr):
        """정상 끝(종료 코드 0·받은 수 == nb_frames)인데 ffmpeg가 stderr에 남긴 글 — 기록에만 한 번 (창 없음, 상태 그대로).
        디코드 오류 글이면 그 프레임이 깨졌을 수 있다 (cv2는 같은 상황에 조용함). 예외를 내지 않음 (read 안)."""
        try:
            print(f"{LOG_PREFIX} 끝까지 읽었지만(프레임 {self._count}장, 종료 코드 0) ffmpeg가 stderr에 글을 남겼습니다 — "
                  f"프레임이 깨졌을 수 있습니다: {self._path}\n명령: {session.command}\nffmpeg stderr:\n{stderr.rstrip()}",
                  file=sys.stderr, flush=True)
        except Exception:
            _last_resort(f"ffmpeg stderr를 기록하지 못했습니다: {self._path}")

    def _log_unsurfaced(self, when, session, failure):
        """드러나기 전의 실패를 품은 세션을 버림(release·탐색 재시작) — 기록에만 한 번 (그 세션은 더 읽지 않으니 창은 없음).
        예외를 내지 않음 (탐색 재시작은 read 안)."""
        try:
            error = PipeCaptureError(f"{failure}: {self._path}", session.command, session.stderr_text())
            print(f"{LOG_PREFIX} {when} 전에 드러나지 않은 파이프 실패 — 기록만 남깁니다: {error}", file=sys.stderr, flush=True)
        except Exception:
            _last_resort(f"드러나지 않은 파이프 실패를 기록하지 못했습니다: {self._path}")

    def _die(self, reason, session=None, command=()):
        """죽음 전이 뒤의 뒤처리 (read가 _lock 밖에서 한 번): 두 보관본 비움·채움기 세움 → 장부 반환 → 채움기 정지(채움 세션 kill — 채움
        실패로 알리지 않음, 죽음 하나만 알림) → 세션 정리 → 기록 한 번 → 오류 창은 Qt 루프에서 한 번.
        _lock을 스스로 잡으므로 _lock을 쥔 채 부르면 안 된다 (threading.Lock — 교착).
        session: 실패한 세션(그 명령·stderr를 실음). 세션을 띄우지 못한 실패는 session 없이 시도한 command만. 예외를 내지 않음 (read
        안 — §5.5): 알릴 글(stderr·호출 스택)을 만들다 실패하면(메모리 부족 등) 원인 한 줄을 _last_resort로."""
        with self._lock:
            filler = self._clear_stores()  # 죽은 캡처는 더 읽지 않음 — 보관본(4K 링 8장 ~199MB, 전체 저장소는 파일 전체)을 붙들지 않게
            ledger, fill_stop = self._ledger_finalizer, self._fill_finalizer
        if ledger is not None:
            ledger()  # 장부 반환 (한 번만 돎)
        self._stop_filler(filler, fill_stop)
        try:
            self._finalizer()  # 지금 세션의 stop: kill — 거두기는 세션의 읽기 스레드
        except Exception:
            _last_resort(f"ffmpeg를 끝내지 못했습니다: {self._path}")
        try:
            if session is not None:
                command, stderr = session.command, session.stderr_text()
            else:
                stderr = ""
            error = PipeCaptureError(f"{reason}: {self._path}", command, stderr)
            context = f"{FAILURE_HEADLINE}.\n파일: {self._path}\n원인: {reason}"
            details = "읽던 곳 (가장 최근 호출이 마지막):\n" + "".join(traceback.format_stack()) + f"{type(error).__name__}: {error}"
        except Exception:
            _last_resort(f"{FAILURE_HEADLINE} — 알릴 글을 만들지 못했습니다: {self._path}\n원인: {reason}")
            return
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


def _fallback_reason(fixed, error):
    """(except 블록 안에서) 사유 글(트레이스백)을 만들지 못했을 때의 사유: 고정 글 + 원래 예외 한 줄 "<형>: <글>" — 그 한 줄마저
    만들지 못하면(예외의 __str__이 실패 등) 고정 글만. 예외를 내지 않음 (read 안 — §5.5)."""
    try:
        return f"{fixed}\n{type(error).__name__}: {error}"
    except Exception:  # 고정 글은 그대로 알림 — 삼키는 것은 덧붙일 한 줄뿐
        return fixed


def _last_resort(message):
    """(except 블록 안에서) 알리다 또 실패함: 원래 stderr(sys.__stderr__ — 기록 파일로 바꾸기 전)에 message와 그 예외의 트레이스백.
    원래 stderr가 없거나(Windows 창 앱) 거기 쓰는 것마저 실패하면(닫힌 콘솔·꽉 찬 디스크) 더 남길 곳이 없다 — 이 실패를 올리면
    read()에서 예외가 나가므로(§5.5, PyQt abort) 올리지 않는다. 이 함수가 알림 사슬의 끝이다."""
    stream = sys.__stderr__
    if stream is None:
        return
    try:
        stream.write(f"{LOG_PREFIX} 오류를 알리지 못했습니다 — {message}\n{traceback.format_exc()}\n")
        stream.flush()
    except Exception:  # 남길 곳이 없음 (위 docstring)
        pass


# ---------------------------------------------------------------- 열기 경로 연결 (스펙 §5.2·§5.7)

PLAY_LOG_PREFIX = "[재생]"


def probe_for_open(path, mode):
    """열기 경로의 ffprobe 한 번(probe_movie) → MovieProbe, 또는 None — ffprobe가 파일을 못 읽었을 때(RuntimeError — 깨진 파일·확인 불가,
    파일 쪽 문제)의 규칙을 한 곳에 둔다: maybe_pipe_capture와 플레이어의 네이티브 분기(VideoPlayer._native_or_pipe_capture — 게이트를 본
    probe를 파이프 판정에 그대로 넘김)가 같이 부름. mode: movie_source_mode()의 "auto"·"pipe" ("cv2"면 부르는 쪽이 probe하지 않음).
    - "auto": 기록 한 줄과 스택 트레이스·stderr 전문을 남기고 None — 부른 쪽은 기존 cv2 줄로 (cv2도 못 열면 기존 오류 창).
    - "pipe": PipeCaptureError로 감싸 올림 (원인 체인 유지 — 강제 모드는 cv2로 조용히 돌리지 않음).
    ffprobe 실행 파일이 없음(ToolNotFoundError — 빌드 깨짐)·probe 결과 해석 오류(KeyError·ValueError… — 코드 버그)는 잡지 않고 그대로."""
    try:
        return probe_movie(path)
    except RuntimeError as exc:  # ffprobe 종료 코드 ≠ 0 — 파일 쪽 문제 (ToolNotFoundError는 RuntimeError가 아님)
        if mode == "pipe":  # 강제 모드는 cv2로 조용히 돌리지 않음 — 사용자는 파이프로 재생 중이라고 믿게 됨
            raise PipeCaptureError(f"{SOURCE_MODE_ENV}=pipe지만 ffprobe가 파일을 읽지 못했습니다: {path}\n{exc}", [], "") from exc
        print(f"{PLAY_LOG_PREFIX} ffprobe가 파일을 읽지 못해 기존 cv2 경로로 엽니다: {os.path.basename(path)}")
        traceback.print_exc()
        return None


def maybe_pipe_capture(path, full_cache=False, probe=None):
    """영상 파일 path를 ffmpeg 파이프로 읽어야 하면 FFmpegPipeCapture, 아니면 None (부른 쪽이 기존 cv2.VideoCapture로 엶).

    full_cache: 캡처가 전체 프레임 캐시를 원하는가 — 플레이어 A/B만 True (VideoPlayer._open_movie_capture). 판정은 캡처의 첫 read
    (예산·킬 스위치 YESONCHECK_FRAME_CACHE=ring — FFmpegPipeCapture._decide_cache), 그 밖(open_any_capture — 주석 내보내기)은 링.

    probe: 부른 쪽이 이미 읽은 MovieProbe — 플레이어의 네이티브 분기(VideoPlayer._native_or_pipe_capture)가 네이티브 게이트를 본 probe를 넘겨
    ffprobe를 한 번만 돌림. 주면 probe_movie를 다시 부르지 않고 그 값으로 판정(모드·게이트·기록 줄은 그대로), None(기본)이면 여기서 probe_for_open.

    open_any_capture(annotation_export)와 VideoPlayer._open_movie_capture의 삽입 분기가 같은 이 함수를 부른다 — 판정 중복 없음.
    게이트는 양성 증거로만 켜진다(opt-in). 모드(YESONCHECK_MOVIE_SOURCE, movie_source_mode):
    - "cv2": probe도 하지 않고 None — 1.5.0 동작으로 돌리는 킬 스위치.
    - "auto": probe_movie → pipe_eligible이면 캡처(로그 한 줄), 아니면 None(어느 조건이 어긋났는지 로그 한 줄).
    - "pipe": ① 코덱만 면제하고 정확도 조건 ②~⑥을 요구 — 어긋나면 PipeCaptureError (비 CFR 파일을 조용히 틀어 주지 않음).
    예외의 경계: ffprobe가 파일을 못 읽음(RuntimeError — 깨진 파일·확인 불가, 파일 쪽 문제)은 probe_for_open의 규칙 — auto에서만 스택
    트레이스·stderr 전문을 로그에 남기고 None(cv2도 못 열면 기존 오류 창), pipe 모드는 PipeCaptureError로 감싸 올림(원인 체인 유지, cv2로 조용히 가지 않음).
    ffprobe 실행 파일이 없음(ToolNotFoundError — 빌드 깨짐)·probe 결과 해석 오류
    (KeyError·ValueError… — 코드 버그)·캡처 생성의 PipeCaptureError는 잡지 않고 그대로 올린다 (조용히 숨기면 안 됨).
    """
    mode = movie_source_mode()
    if mode == "cv2":
        return None
    name = os.path.basename(path)
    if probe is None:
        probe = probe_for_open(path, mode)
        if probe is None:  # auto에서 ffprobe가 못 읽음 — probe_for_open이 기록을 남겼고, 기존 cv2 경로로
            return None
    reason = ineligible_reason(probe, check_codec=mode != "pipe")
    if reason is not None:
        if mode == "pipe":
            raise PipeCaptureError(f"{SOURCE_MODE_ENV}=pipe지만 이 파일은 파이프로 읽을 수 없습니다 — {reason}: {path}", [], "")
        print(f"{PLAY_LOG_PREFIX} cv2: {name} (파이프 아님 — {reason})")
        return None
    capture = FFmpegPipeCapture(path, probe, full_cache=full_cache)
    print(f"{PLAY_LOG_PREFIX} ffmpeg 파이프: {name} ({probe.codec} {probe.width}×{probe.height} {float(probe.avg):g}fps, "
          f"프레임 {probe.nb_frames})")
    return capture
