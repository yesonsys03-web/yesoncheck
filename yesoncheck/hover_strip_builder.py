# -*- coding: utf-8 -*-
"""슬라이더 호버 썸네일의 띠를 만드는 워커 (HoverStripBuilder — QThread 하나와 차례로 띄우는 프로세스들). 화면(위젯) 없음.

번들 ffmpeg가 파일 전체를 띠 크기(hover_strip.StripPlan)의 rgb24 원시 프레임으로 줄여 stdout으로 내보내고, 이 워커가 한 장씩 받아 띠 저장소
(hover_strip.HoverStrip)에 넣는다. 재생 캡처(cap_a)는 건드리지 않는다 — 따로 띄운 프로세스가 파일을 따로 연다. 띄우는 때·멈추는 때는 부르는
쪽(플레이어의 쉬는 때 판정)이 정하고, 워커는 띄워진 뒤 paused 표지만 본다.

패스 둘 (스펙 2026-11-11 §3): 한 run 안에서 차례로 ① 키프레임 거친 띠 — 긴 파일(간격 step > 1)이면 헤더 ffprobe(hover_keyframes.probe_header —
패킷 없이 코덱·속도만)로 all-intra 코덱·모르는 속도를 먼저 거르고(건너뜀 한 줄), 그 밖이면 패킷 ffprobe로 키프레임 번호를 읽어
(hover_keyframes.scan_keyframes — 버림(D) 패킷 제외) 키프레임이 드물면(hover_keyframes.coarse_wanted — 전체의 1/4 이하) -skip_frame nokey로
키프레임만 디코드해 거친 띠(hover_keyframes.KeyframeStrip)를 채움 ② 정확한 띠 — 지금 그대로. 거친 띠는 정확한 띠보다 훨씬 빨리 차므로(22.6분 720p H.264
애니매틱: 키프레임만 10.2초 대 전부 18.8초 — 이 Mac 실측) 그동안 호버가 거친 그림을 보이고, 정확한 띠가 끝나면 버린다(coarse_strip = None을
done 앞에). 공개: coarse_strip은 목록·표시 배열을 다 만든 저장소를 속성 하나로 한 번 대입(그 전·버린 뒤·정확한 띠 완성 뒤·stop 뒤 None — GUI는
조회마다 그 참조만 읽음; 정확한 띠가 실패(failed)하면 그대로 둠 — 이미 채운 장처럼 계속 보임), 다 채우면 coarse_done(채운 장수, 띄운 때부터 초). 거친 띠는 보조라 어느 실패(ffprobe 실패·찾지 못함, 거친 ffmpeg의
종료 코드 ≠ 0·한 장 도중 끊김·출력 장수 ≠ 목록 장수·예상 못 한 예외)도 failed(창)를 내지 않고 기록(stderr) 'LOG_PREFIX 거친 띠를 만들지
못했습니다(정확한 띠는 계속) — 파일' 한 줄과 사유 전문만 남긴 뒤 거친 띠를 버리고 정확한 띠로 넘어간다 — 장수가 다르면 j번째 출력이 목록의 j번째라는
짝을 믿을 수 없어서. 간격 1(500장 이하)이면 거친 띠를 생각하지 않는다(ffprobe도 기록 줄도 없음 — 정확한 띠가 곧 모든 장). paused·stop()·
_suspendable·stderr 비우기는 패스와 상관없이 지금 도는 프로세스(_process — ffprobe도)에 그대로 적용된다(_run_pass가 패스마다 바꿈).

왜 stdout 파이프로 충분한가 (스펙 §5.3): 전송은 stdout 파이프로 충분하다 — 장당 173KB(320×180×3; 어떤 비율이든 320×320 상자 안이라 최대
307KB)이고 쉴 때만 읽는다. 파이프 소스(movie_pipe_source)가 소켓으로 옮긴 까닭은 4K 한 장 25MB가 64KB씩 수백 번의 read로 들어오며 재생 중인
GUI 스레드와 GIL을 다투던 것(공급 기아)인데, 여기는 장당 read가 몇 번뿐이고 재생 중에는 읽지 않으므로 해당 없다 — 소켓·전송 계층 없이
Popen(stdout=PIPE) 하나다.

왜 멈춤이 psutil 프로세스 정지인가 (스펙 §5.3): 파이프를 읽지 않는 것만으로는 ffmpeg가 바로 멈추지 않는다 — 프레임 스레드들이 이미 디코드
중인 장(스레드 수만큼 — 4K 4444면 8코어로 수백 ms)을 마저 디코드해 재생의 첫 틱들과 겹친다. 그래서 paused가 참이 되면
psutil.Process(pid).suspend()(POSIX SIGSTOP·Windows NtSuspendProcess), 거짓이 되면 resume() — CPU가 즉시 0이 된다. 정지된 프로세스에도 kill은
그대로 먹는다(SIGKILL·TerminateProcess) — stop()은 정지 여부와 상관없이 kill한다. 정지·재개가 실패하면(psutil.Error 전부 — NoSuchProcess·
AccessDenied 등 — 와 OSError: Windows에서 끝나 가는 프로세스의 NtSuspendProcess는 psutil이 감싸지 않은 OSError로 올 수 있음) 기록 한 줄을
남기고 읽기만 멈추는(또는 잇는) 방식으로 둔다 — 조용히 넘기지 않고, GUI 틱 슬롯(paused setter)이나 워커 스레드로 올려 실패로 만들지도 않는다.
1080p보다 큰 원본(4K 등)·720p보다 크고 허용 목록(h264) 밖 코덱(1080p ProRes 등)·코덱을 모르는 720p보다 큰 원본의 띠 ffmpeg는 디코드·축소를 1코어로 묶는다(스펙
§5.3 — 쉴 때만 돌므로 느려도 됨, 이 Mac 4K 334장 쉴 때 약 38초(이 Mac 실측 — 쉴 때만)): 디코더 스레드 FFMPEG_THREADS(-threads 1 — 입력 옵션,
-i 앞)와 필터 스레드 FFMPEG_FILTER_THREADS(-filter_threads 1 — 전역 옵션, -i 앞). 720p 이하 원본, 그리고 1080p 이하이고 헤더로 안 코덱이
허용 목록(hover_strip.LONG_GOP_FULL_THREADS_CODECS — h264, 재생 게이트를 잰 코덱만)에 있는 원본은 두 옵션을 넣지 않는다(ffmpeg 기본 —
hover_strip.thread_limits, Ruling 24·25·26: 재생 게이트 — 720p·1080p H.264 통과, 1080p ProRes 불통과; 긴 720p 애니매틱 67.0초 → 18.8초, 긴 1080p H.264 애니매틱 82.2초 → 24.6초 실측). 코덱은 긴 파일(간격 > 1)이면 run이 헤더
ffprobe로 늘 알아내고(codec — 거친 띠를 만들든 말든) 정확한 띠 명령(command)을 그 코덱으로 다시 정한다; 짧은 파일은 헤더를 읽지 않아 코덱을
모름(1080p ProRes·4K 명령은 글자 그대로).
-threads는 **디코더** 스레드만 묶는다 — -vf scale(4K → 320 축소 + rgb24 변환)은 따로 CPU 수만큼 slice 스레드를 쓰므로(이 Mac 16코어,
번들 ffmpeg 9.0.2 실측: 프로세스 스레드 기본 68개, -threads 2만이면 54개, -filter_threads 1 -threads 2면 24개, 둘 다 1이면 22개 — 나머지는
ffmpeg 자신의 구성 요소 스레드(미확인)) 필터 쪽 손잡이가 -filter_threads다. 까닭(측정 — CLAUDE.md 2026-11-10): 띠 워커를 띄운 지 0.5초 안에 4K
재생을 시작하면 Play 뒤 첫 1~2초(때로 중간)에 끊김이 났고(정지는 그때 이미 걸려 있음), 기본 스레딩(16)과 -threads 2 모두 켬이 끔의 범위를
넘었다 — Play 직전에 여러 코어로 4K 장을 한꺼번에 디코드·축소하는 버스트가 원인으로 의심되어(미확인) 1코어로 묶는다.

수명: 생성자는 띄우지 않는다 — start()가 run에서 프로세스마다 Popen(stdout=PIPE, stderr=PIPE)하고(_run_pass), 띄운 직후 잠금 안에서 paused면
바로 정지한다. stderr는 데몬 스레드가 끝까지 모은다(안 비우면 파이프가 차서 ffmpeg가 멈춤 — movie_pipe_source._PipeSession과 같은 모양).
정확한 띠의 끝은 셋 중 하나다 (거친 띠의 끝은 위 '패스 둘').
- done(채운 장수, 띄운 때부터 초 — 멈춘 시간 포함): 종료 코드 0이고 장 경계에서 EOF(0바이트에서 끝남)일 때. 계획보다 적게 와도(잘린 파일·
  VFR) done이고 남은 샘플은 빈 채로, 많이 오면 남는 장은 읽어 버리고 done(기록에 '넘침 n장' 한 줄). 이때 stderr에 글이 있어도 done이다 —
  잘린 파일(복사·렌더가 진행 중인 NAS 파일)이면 번들 ffmpeg가 오류 수준 글('partial file'·'wrong picture data size'·'Decoding error')을
  찍고도 종료 코드 0으로 끝나므로, 그 글은 삼키지 않고 기록(stderr)에 'LOG_PREFIX ffmpeg 경고 (종료 코드 0, n장 채움) — 파일' 한 줄과 전문을
  남기되 창은 띄우지 않는다(스펙 §5.3·§5.7 ② — 처음 글의 'stderr에 글이면 failed'는 그런 파일을 열 때마다 실패 창을 띄웠음).
- failed(글): 띄우지 못함·한 장 도중 끊김·종료 코드 ≠ 0·예상 못 한 예외(읽기·넣기 오류 포함)만. 글은 파일·명령·종료 코드·stderr 전문
  (·트레이스백). 이미 넣은 장은 그대로 둔다(그 구간은 보임). 한 장 도중 끊김(몇 바이트만 오고 EOF)은 브리프의 '짧게 끝나면 EOF'보다
  보수적으로 failed로 본다 — 스펙 §5.3의 실패 목록('한 장 도중 EOF')을 따름. 0바이트에서의 EOF만 정상 끝이다.
- stop(): 표지를 둔 뒤의 끊김(kill의 종료 코드·끊긴 읽기)은 신호도 기록도 내지 않는다 — done·failed는 잠금 안에서 표지를 보고 내므로
  stop()이 표지를 둔 뒤에는 나가지 않는다. 단 트레이스백이 있는 문제(예상 못 한 예외 — 정리 단계·put의 버그 등)는 stop 뒤라도 신호 없이
  기록(stderr)에 LOG_PREFIX 머리 한 줄과 트레이스백을 남긴다(조용히 사라지지 않게). 끝 신호 두 개를 직접 연결(Qt.DirectConnection)로 받아
  그 안에서 paused·stop을 부르면 안 된다(잠금을 다시 잡음) — 플레이어는 GUI 스레드의 대기열 연결로 받는다. progress는 잠금 밖에서 낸다(묶음
  알림일 뿐 — stop 직후 하나가 더 올 수 있음).
샘플 i(ffmpeg가 낸 i번째 장 — select면 원본 i×step)는 한 번만 put한다 (HoverStrip.put은 행을 다 쓴 뒤 표시하므로, 같은 행을 다시 쓰면 GUI가
덮어쓰는 중인 행을 읽을 수 있음).

잠금(_lock)이 지키는 것: _paused·_stopped·_process·_suspendable·pids, 그리고 coarse_strip의 대입(GUI는 잠금 없이 참조만 읽음). _suspendable은 프로세스를 정지·재개해도 되는 동안(띄운 직후부터 읽기가
끝날 때까지)만 참이다 — 읽기가 끝난 뒤(EOF·실패·stop)에는 정지·재개하지 않아, 끝나 가는 프로세스를 정지해 거두기(wait)가 막히거나 거둔 뒤
다른 프로세스가 물려받은 PID를 건드리지 않는다. 정상 EOF인데 멈춤 표지가 서 있으면(마지막 장을 받는 사이 정지됨) 거두기 전에 재개한다.
"""

import subprocess
import sys
import threading
import time
import traceback

import psutil
from PyQt5.QtCore import QThread, pyqtSignal

from yesoncheck import hover_keyframes
from yesoncheck.external_tools import ToolNotFoundError, decode_output, ffmpeg_path, ffprobe_path, subprocess_kwargs
from yesoncheck.hover_strip import LOG_PREFIX, HoverStrip, ImageRows, StripPlan, thread_limits

POLL_S = 0.05  # 멈춘 동안 표지를 다시 보는 간격 (초)
BATCH_S = 0.05  # progress 묶음 간격 (초) — 또는 BATCH_FRAMES장마다, 먼저 오는 쪽 (GUI 신호 폭주 방지)
BATCH_FRAMES = 10
STOP_WAIT_MS = 2000  # stop()이 kill한 프로세스를 거두고, 스레드 끝을 기다리는 최대 시간 (각각)
_STDERR_CHUNK = 65536
# 묶을 때의 띠 ffmpeg 스레드 (모듈 설명 — 묶을지는 hover_strip.thread_limits가 원본 크기·코덱으로 고름; 묶지 않거나 None이면 그 옵션을 넣지
# 않아 ffmpeg 기본: 이 Mac은 디코더·필터 모두 CPU 수만큼)
FFMPEG_THREADS: int | None = 1  # 디코더 스레드 (-threads — 입력 옵션이라 -i 바로 앞). 필터(-vf scale)는 묶지 않음
FFMPEG_FILTER_THREADS: int | None = 1  # 필터 스레드 (-filter_threads — 전역 옵션, -i 앞). -vf scale의 slice 스레드를 묶음


def build_command(ffmpeg: str, path: str, plan: StripPlan, codec: str | None = None) -> list[str]:
    """띠 하나를 만드는 ffmpeg 명령 (인자 리스트 그대로 — 셸 없음). -map 0:V:0(대문자 — attached_pic 제외)·-fps_mode passthrough(복제
    금지)는 파이프 소스와 같은 이유. 간격이 1이면 scale만, 아니면 select로 step장마다 하나 — 쉼표 앞의 역슬래시는 select 식의 쉼표가 필터
    구분자로 읽히지 않게 하는 필터 파서용 (셸 따옴표 아님). 스레드 옵션은 원본 크기·codec(헤더의 codec_name — 모르면 None)으로
    hover_strip.thread_limits가 고르고(720p 이하·1080p 이하 h264면 없음),
    값은 두 상수를 호출 때 읽음(시험의 monkeypatch가 닿게): 필터 스레드(-filter_threads, 전역)를 앞에, 디코더 스레드(-threads, 입력 옵션)를
    -i 바로 앞에 — -threads는 디코더만 묶음(모듈 설명)."""
    return _strip_command(ffmpeg, path, plan, plan.step, (), codec)


def build_coarse_command(ffmpeg: str, path: str, plan: StripPlan, codec: str | None = None) -> list[str]:
    """키프레임만의 거친 띠 명령 — build_command와 같은 모양에 -skip_frame nokey(디코더 옵션이라 -i 앞 — 디코더 스레드 바로 앞)를 더하고 select는
    넣지 않음: 키프레임 전부(K장)를 내고, 워커가 m장마다 하나만 거친 띠에 넣음(_read_frames의 every — 목록은 hover_keyframes.subsample이 같은 규칙
    frames[::m]으로 줄임; 스펙 §3.2의 select와 다름 — 디코드 비용은 같고 파이프 전송만 K장, 장수 검사가 받은 수 == K로 정확해짐). 스레드 규칙도
    같음 (hover_strip.thread_limits)."""
    return _strip_command(ffmpeg, path, plan, 1, ("-skip_frame", "nokey"), codec)


def _strip_command(ffmpeg: str, path: str, plan: StripPlan, every: int, input_options, codec: str | None) -> list[str]:
    """두 명령의 공통 모양: [필터 스레드] [입력 옵션] [디코더 스레드] -i 파일 … -vf [select,]scale … rgb24 pipe:1 (select는 every > 1일 때 —
    정확한 띠의 간격)."""
    scale = f"scale={plan.width}:{plan.height}"
    vf = scale if every == 1 else f"select=not(mod(n\\,{every})),{scale}"
    decoder, filters = thread_limits(plan, FFMPEG_THREADS, FFMPEG_FILTER_THREADS, codec)
    filter_threads = [] if filters is None else ["-filter_threads", str(filters)]
    threads = [] if decoder is None else ["-threads", str(decoder)]
    return [ffmpeg, "-nostdin", "-v", "error", *filter_threads, *input_options, *threads, "-i", path, "-map", "0:V:0",
            "-fps_mode", "passthrough", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]


def _read_full(stream, view: memoryview) -> int:
    """view를 다 채울 때까지 stream에서 읽음 → 읽은 바이트 수 (EOF면 len(view)보다 적음)."""
    filled = 0
    while filled < len(view):
        count = stream.readinto(view[filled:])
        if not count:
            break
        filled += count
    return filled


def _drain(stream, chunks: list) -> None:
    """stderr를 EOF까지 chunks에 모으고 닫음 (데몬 스레드 — 안 비우면 파이프가 차서 ffmpeg가 멈춤)."""
    try:
        for chunk in iter(lambda: stream.read1(_STDERR_CHUNK), b""):
            chunks.append(chunk)
    finally:
        stream.close()


class _Stopped(Exception):
    """거친 패스에서 stop()을 본 뒤 조용히 빠져나옴 (RuntimeError 등 '실패'와 섞이지 않게 따로 — hover_keyframes를 지나 _coarse_pass까지)."""


class HoverStripBuilder(QThread):
    """띠 저장소를 채우는 워커 (거친 띠 → 정확한 띠 — 모듈 설명). 생성·start·paused·stop은 GUI 스레드, run은 워커 스레드.

    path: 영상 파일, strip: 채울 저장소(계획은 strip.plan), ffmpeg: 실행 파일(None이면 external_tools.ffmpeg_path() — 없으면 생성자가
    ToolNotFoundError), ffprobe: 키프레임 스캔의 실행 파일(None이면 거친 패스 때 external_tools.ffprobe_path() — 없으면 거친 띠만 건너뜀).
    coarse_strip: 지금 보일 거친 띠(GUI가 조회마다 읽음 — 모듈 설명), coarse_count: 거친 띠의 장수(공개한 뒤 그대로 — 기록용).
    command(정확한 띠)·coarse_command(거친 띠 — 만들 때만)·pid(지금·마지막 프로세스)·pids(띄운 차례대로 모든 프로세스)는 기록·시험용."""

    progress = pyqtSignal(int)  # 정확한 띠의 채운 장수 (BATCH_S마다 또는 BATCH_FRAMES장마다)
    done = pyqtSignal(int, float)  # 채운 장수, 띄운 때부터 초
    failed = pyqtSignal(str)  # 파일·명령·종료 코드·stderr 전문·트레이스백
    coarse_done = pyqtSignal(int, float)  # 거친 띠를 다 채움: 채운 장수(= coarse_count), 띄운 때부터 초

    def __init__(self, path: str, strip: HoverStrip, ffmpeg: str | None = None, parent=None, ffprobe: str | None = None):
        super().__init__(parent)
        self.path = path
        self.strip = strip
        self._ffmpeg = ffmpeg if ffmpeg is not None else ffmpeg_path()
        self._ffprobe = ffprobe
        self.command = build_command(self._ffmpeg, path, strip.plan)  # 코덱을 모를 때의 명령 — 긴 파일은 run이 헤더를 읽은 뒤 다시 정함
        self.codec: str | None = None  # 헤더 ffprobe의 codec_name (긴 파일만 읽음 — 모르면 None; 스레드 규칙)
        self.coarse_command: list[str] | None = None
        self.coarse_strip: hover_keyframes.KeyframeStrip | None = None
        self.coarse_count = 0
        self.pid: int | None = None
        self.pids: list[int] = []
        self._lock = threading.Lock()
        self._paused = False
        self._stopped = False
        self._process: subprocess.Popen | None = None
        self._suspendable = False

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        """멈춤 표지. 값이 바뀔 때만 잠금을 잡고 — 프로세스가 돌고 있으면 바로 정지·재개. 같은 값이면 아무것도 하지 않음(잠금도 psutil도):
        플레이어가 재생 중 틱마다 True를 넣어도 SIGSTOP을 다시 보내지 않고 워커 스레드(잠금 안에서 psutil·기록을 부름)와 잠금을 다투지
        않는다. 잠금 밖의 비교가 안전한 까닭: _paused를 쓰는 곳은 이 setter뿐이라 부르는 쪽이 마지막에 쓴 값을 본다 — 잠금 안에서 한 번 더
        봐서 두 스레드가 불러도 신호를 두 번 보내지 않음."""
        if value == self._paused:
            return
        with self._lock:
            if value == self._paused:
                return
            self._paused = value
            if self._suspendable:
                self._signal_process(value)

    def stop(self) -> None:
        """일부러 끝냄 (GUI 스레드, 여러 번 불러도 됨): 표지 → kill(정지돼 있어도 먹힘) → 거두기 → 스레드 끝 대기.

        거두기와 스레드 끝은 각각 STOP_WAIT_MS까지만 기다린다 — 넘으면 기록을 남기고 돌아간다(GUI를 막지 않음; 워커 스레드가 프로세스를
        끝까지 기다려 거두고, 부른 쪽은 worker_lifecycle.release_worker로 붙잡아 둔다). stdout은 여기서 닫지 않고 워커 스레드가 닫는다(브리프의
        'stdout 닫기'와 다름): 프로세스가 죽으면 읽기는 EOF로 바로 끝나므로 닫을 까닭이 없고, 여기서 닫으면 ① 읽기 스레드가 readinto 안에
        있을 때 닫기가 그 읽기를 기다리고 ② 표지 검사와 readinto 사이에 닫히면 정상 중단이 ValueError 트레이스백이 되어 '예상 못 한 오류'
        기록으로 섞인다. 표지를 둔 뒤로는 done·failed·coarse_done을 내지 않는다(그 전에 낸 신호가 GUI의 대기열에 남아 있을 수는 있음 — 부른 쪽
        몫). 거친 띠도 놓는다(coarse_strip = None — 워커는 표지를 본 뒤로 다시 대입하지 않음). 어느 패스든 지금 프로세스를 끝내고, 그 뒤의 패스는
        띄우지 않는다(run·거친 패스가 띄우기 전에 표지를 봄 — 그 검사와 띄우기 사이에 온 stop이면 _attach가 바로 kill)."""
        with self._lock:
            self._stopped = True
            self._suspendable = False
            self.coarse_strip = None
            process = self._process
        if process is not None:
            process.kill()  # 이미 거둔 프로세스면 아무것도 안 함
            try:
                process.wait(STOP_WAIT_MS / 1000)
            except subprocess.TimeoutExpired:
                print(f"{LOG_PREFIX} kill한 ffmpeg가 {STOP_WAIT_MS}ms 안에 끝나지 않았습니다 (pid {process.pid}) — 워커 스레드가 끝까지 "
                      f"기다려 거둡니다: {self.path}", file=sys.stderr, flush=True)
                return  # 안 죽는 프로세스면 읽기 스레드도 막혀 있음 — 스레드를 더 기다리지 않음
        if not self.wait(STOP_WAIT_MS):
            print(f"{LOG_PREFIX} 띠 워커 스레드가 {STOP_WAIT_MS}ms 안에 끝나지 않았습니다: {self.path}", file=sys.stderr, flush=True)

    def run(self) -> None:
        """워커 스레드 본문 — ① 거친 띠(조건이 맞을 때) ② 정확한 띠. 예외를 밖으로 내지 않는다(QThread.run에서 새면 PyQt5가 프로세스를
        끝냄) — 거친 패스는 스스로 기록하고, 나머지는 모두 failed의 글로."""
        started = time.monotonic()
        try:
            self._coarse_pass(started)
            if self._stopped:  # stop 뒤에는 정확한 패스를 띄우지 않음 (stop() 설명)
                return
            if self.codec is not None:  # 헤더로 코덱을 알았으면 스레드 규칙을 다시 (Ruling 25 — hover_strip.thread_limits)
                self.command = build_command(self._ffmpeg, self.path, self.strip.plan, self.codec)
            self._build(started)
        except Exception:  # 정리 단계의 예상 못 한 오류 (_run_pass가 프로세스는 이미 거둠) — 삼키지 않고 failed로 (stop 뒤면 기록으로)
            self._report("띠 워커가 예외로 끝났습니다.", None, "", 0, started, trace=traceback.format_exc())

    def _build(self, started: float) -> None:
        """② 정확한 띠 — 끝 신호 하나(_report). stop() 뒤면 run이 부르지 않음 — run의 검사와 띄우기 사이에 온 stop이면 _attach가 바로 kill하고
        조용히 끝남."""
        try:
            problem, returncode, stderr, received, trace = self._run_pass(
                self.command, lambda stdout: self._read_frames(stdout, self.strip, progress=True), "ffmpeg")
        except OSError:
            self._report("ffmpeg를 띄우지 못했습니다.", None, "", 0, started, trace=traceback.format_exc())
            return
        self._report(problem, returncode, stderr, received or 0, started, trace=trace)

    def _coarse_pass(self, started: float) -> None:
        """① 키프레임 거친 띠 (모듈 설명 '패스 둘'). 간격 1이면 아무것도 안 함. 실패는 창 없이 기록(stderr) 한 줄 + 사유 전문 뒤 거친 띠를
        버리고 돌아감 — 예외를 내지 않음(예상 못 한 예외는 트레이스백째 기록, stop 뒤라도)."""
        plan = self.strip.plan
        if hover_keyframes.coarse_wanted(plan.total, plan.step) is not None:
            return  # 간격 1 — 정확한 띠가 곧 모든 장이라 생각하지 않음 (ffprobe·기록 없음)
        try:
            problem = self._build_coarse(started, plan)
        except _Stopped:  # stop()이 표지를 둠 — 조용히 (트레이스백이 있는 문제는 빠져나오기 전에 기록함)
            return
        except Exception:  # 예상 못 한 예외 (깨진 ffprobe JSON·put의 버그 등)
            problem = f"거친 띠 패스가 예외로 끝났습니다.\n{traceback.format_exc().rstrip()}"
            if self._stopped:  # stop 뒤라도 트레이스백은 남김 — 정확한 띠와 같은 머리, 신호 없음
                self._log_after_stop(problem)
                return
        if problem is None:
            return
        with self._lock:
            self.coarse_strip = None  # 덜 찼거나 번호를 믿을 수 없는 거친 띠는 버림
        print(f"{LOG_PREFIX} 거친 띠를 만들지 못했습니다(정확한 띠는 계속) — {self.path}\n{problem}", file=sys.stderr, flush=True)

    def _build_coarse(self, started: float, plan: StripPlan) -> str | None:
        """거친 패스 본문 → 기록할 문제 글(사유 전문), 또는 None(다 채워 coarse_done을 냄·건너뜀(기록 한 줄)·stop으로 멈춤). 헤더를 먼저 읽어
        all-intra 코덱·모르는 속도면 패킷 스캔(파일 전체 읽기) 없이 건너뜀 (hover_keyframes 설명)."""
        frames = None
        if self._stopped:  # stop 뒤에는 ffprobe도 띄우지 않음
            return None
        try:
            ffprobe = self._ffprobe if self._ffprobe is not None else ffprobe_path()
            header = hover_keyframes.probe_header(ffprobe, self.path, run=self._run_probe)
            self.codec = header.codec or None  # 거친 띠를 만들든 말든 — 정확한 띠의 스레드 규칙에도 씀 (run)
            reason = hover_keyframes.header_skip_reason(header)
            if reason is None and not self._stopped:
                frames, _packets = hover_keyframes.scan_keyframes(ffprobe, self.path, header, run=self._run_probe)
        except (ToolNotFoundError, OSError, RuntimeError) as exc:  # ffprobe 없음·못 띄움·실패(kill 포함)·번호를 정할 수 없음
            return None if self._stopped else f"헤더·키프레임 목록을 읽지 못했습니다 — {type(exc).__name__}: {exc}"
        if self._stopped:
            return None
        if reason is None:
            reason = hover_keyframes.coarse_wanted(plan.total, plan.step, len(frames))
        if reason is not None:
            print(f"{LOG_PREFIX} 거친 띠 건너뜀: {reason} — {self.path}", flush=True)
            return None
        keyframes = len(frames)  # ffmpeg가 낼 장수 K (줄이기 전 — 장수 검사의 기준)
        rows, every = hover_keyframes.subsample(frames, hover_keyframes.MAX_COARSE)
        strip = hover_keyframes.KeyframeStrip(rows, plan.width, plan.height)
        command = build_coarse_command(self._ffmpeg, self.path, plan, self.codec)
        with self._lock:  # 목록·표시 배열을 다 만든 뒤 한 번에 공개 (stop 뒤면 공개하지 않음)
            if self._stopped:
                return None
            self.coarse_command, self.coarse_count, self.coarse_strip = command, strip.count, strip
        print(f"{LOG_PREFIX} 거친 띠 먼저: 키프레임 {keyframes}장 → {strip.count}장(간격 {every}, 전체 {plan.total}장) — {self.path}",
              flush=True)
        try:
            problem, returncode, stderr, received, trace = self._run_pass(
                command, lambda stdout: self._read_frames(stdout, strip, progress=False, every=every, limit=keyframes), "ffmpeg")
        except OSError:
            return f"거친 띠 ffmpeg를 띄우지 못했습니다.\n명령: {' '.join(command)}\n{traceback.format_exc().rstrip()}"
        if self._stopped:  # 일부러 멈춤 — 조용히 (트레이스백이 있는 문제만 정확한 띠와 같은 머리로 기록)
            if trace is not None:
                self._log_after_stop(f"{problem}\n{trace.rstrip()}")
            return None
        if problem is None and returncode == 0 and received == keyframes:
            if stderr.strip():  # 삼키지 않음 (정확한 띠의 경고와 같은 규칙 — 창 없음)
                print(f"{LOG_PREFIX} 거친 띠 ffmpeg 경고 (종료 코드 0, {strip.filled_count}장 채움) — {self.path}\n{stderr.rstrip()}",
                      file=sys.stderr, flush=True)
            with self._lock:
                if not self._stopped:
                    self.coarse_done.emit(strip.filled_count, time.monotonic() - started)
            return None
        if problem is None:
            problem = (f"ffmpeg가 비정상 종료했습니다 (종료 코드 {returncode}, 출력 {received}장 / 키프레임 목록 {keyframes}장)"
                       if returncode != 0 else
                       f"출력 {received}장 ≠ 키프레임 목록 {keyframes}장 — j번째 출력이 목록의 j번째라는 짝을 믿을 수 없어 채운 것을 버림")
        if trace is not None:
            problem = f"{problem}\n{trace.rstrip()}"
        return f"{problem}\n명령: {' '.join(command)}\n종료 코드: {returncode}\nstderr:\n{stderr.rstrip() or '(없음)'}"

    def _run_probe(self, command: list[str]) -> tuple[int, bytes, str]:
        """probe_header·scan_keyframes의 run — ffprobe도 지금 프로세스로(_run_pass — 멈춤·stop이 먹게) 띄워 stdout을 끝까지 읽음 → (종료 코드,
        stdout, stderr 글). stop() 뒤면 _Stopped로 빠져나옴 — stop이 읽기를 멈춰 반쪽만 받은 JSON을 해석해 '예상 못 한 예외'로 거짓 기록하지
        않게(트레이스백이 있는 문제는 먼저 정확한 띠와 같은 머리로 기록). 읽다 예외가 나면 트레이스백째 RuntimeError (거친 띠만 건너뜀)."""
        problem, returncode, stderr, out, trace = self._run_pass(command, self._read_all, "ffprobe")
        if self._stopped:
            if trace is not None:
                self._log_after_stop(f"{problem}\n{trace.rstrip()}")
            raise _Stopped
        if problem is not None:
            raise RuntimeError(f"{problem}\n{(trace or '').rstrip()}")
        return returncode, out, stderr

    def _run_pass(self, command: list[str], consume, tool: str):
        """프로세스 하나를 띄워(지금 프로세스 — 멈춤·stop이 먹음) stdout을 consume(stdout) → (값, 문제 글|None)으로 읽고 거둠 →
        (문제 글|None, 종료 코드, stderr 글, 값|None, 트레이스백|None). 못 띄우면 Popen의 OSError 그대로. 문제가 있으면 남은 출력을 기다리지 않고
        kill(정지돼 있어도 먹힘 — stop()이면 stop()·_attach가 이미 kill). tool: 문제 글의 이름."""
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   **subprocess_kwargs())
        stderr_chunks = []
        stderr_reader = threading.Thread(target=_drain, args=(process.stderr, stderr_chunks), name="hover-strip-stderr",
                                         daemon=True)
        value, problem, trace = None, None, None
        try:
            stderr_reader.start()
            self._attach(process)
            value, problem = consume(process.stdout)
        except Exception:  # 읽기·넣기 오류 (예상 못 한 예외 — stop 뒤라도 기록에 남음)
            problem, trace = f"{tool} 출력을 읽다 오류가 났습니다.", traceback.format_exc()
        try:
            self._end_reading(clean=problem is None)
        except Exception:  # 재개 중 예상 못 한 오류 — 정지된 채 거두기를 기다리지 않게 아래에서 kill
            problem, trace = f"{tool}를 재개하지 못했습니다.", traceback.format_exc()
        finally:
            if problem is not None:
                process.kill()
            process.stdout.close()
            process.wait()
            stderr_reader.join()
        return problem, process.returncode, decode_output(b"".join(stderr_chunks)), value, trace

    def _attach(self, process: subprocess.Popen) -> None:
        """띄운 직후 (잠금 안): 지금 프로세스로 붙임. 이미 stop()이 불렸으면 바로 kill, 멈춤 표지가 서 있으면 바로 정지."""
        with self._lock:
            self._process = process
            self.pid = process.pid
            self.pids.append(process.pid)
            if self._stopped:
                process.kill()
                return
            self._suspendable = True
            if self._paused:
                self._signal_process(True)

    def _read_frames(self, stdout, store: ImageRows, progress: bool, every: int = 1,
                     limit: int | None = None) -> tuple[int, str | None]:
        """EOF까지 한 장(store.frame_bytes)씩 읽어 받은 i번째 장 중 i % every == 0인 장을 행 i // every에 넣음 → (ffmpeg가 낸 장수, 문제 글 또는
        None). 저장소 장수를 넘는 장은 읽어 버림. limit: 이 장수를 넘는 장이 오면 그 자리에서 문제로 끊음(거친 띠 — 번호를 믿을 수 없으니 EOF까지
        디코드하지 않음; 부른 쪽이 kill). 멈춤 표지가 서 있는 동안은 읽지 않음(POLL_S마다 다시 봄), stop()이면 바로 끝. progress: 정확한 띠면
        progress 신호를 냄."""
        frame_bytes = store.frame_bytes
        view = memoryview(bytearray(frame_bytes))
        received = 0
        reported, reported_at = 0, time.monotonic()
        while not self._stopped:
            if self._paused:
                time.sleep(POLL_S)
                continue
            got = _read_full(stdout, view)
            if got < frame_bytes:
                if got:
                    return received, f"한 장 도중에 출력이 끊겼습니다 ({got}/{frame_bytes}바이트 — {received}장을 받은 뒤)"
                return received, None
            if limit is not None and received >= limit:
                return received + 1, (f"출력이 키프레임 목록 {limit}장을 넘었습니다 ({received + 1}장째에서 끊음) — j번째 출력이 목록의 j번째라는 "
                                      f"짝을 믿을 수 없어 채운 것을 버림")
            if received % every == 0 and received // every < store.count:
                store.put(received // every, view)
            received += 1
            if not progress:
                continue
            filled = min(received, store.count)
            now = time.monotonic()
            if filled > reported and (filled - reported >= BATCH_FRAMES or now - reported_at >= BATCH_S):
                self.progress.emit(filled)
                reported, reported_at = filled, now
        return received, None

    def _read_all(self, stdout) -> tuple[bytes, None]:
        """(ffprobe) EOF까지 stdout을 모음 → (바이트, None). 멈춤 표지가 서 있는 동안은 읽지 않음, stop()이면 바로 끝 (모은 데까지)."""
        chunks = []
        while not self._stopped:
            if self._paused:
                time.sleep(POLL_S)
                continue
            chunk = stdout.read1(_STDERR_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), None

    def _end_reading(self, clean: bool) -> None:
        """읽기 끝 (잠금 안): 이제부터 정지·재개하지 않음. 정상 EOF인데 멈춤 표지가 서 있으면 재개 — 마지막 장을 받는 사이 정지된 ffmpeg가
        정지된 채 남아 거두기(wait)가 막히지 않게."""
        with self._lock:
            resume = clean and self._suspendable and self._paused
            self._suspendable = False
            if resume:
                self._signal_process(False)

    def _signal_process(self, pause: bool) -> None:
        """(잠금 안, _suspendable일 때만) 프로세스를 정지(pause) 또는 재개. psutil이 못 하면 기록 한 줄 — 표지는 그대로라 읽기만 멈추거나 이어짐."""
        pid = self._process.pid
        try:
            process = psutil.Process(pid)
            if pause:
                process.suspend()
            else:
                process.resume()
        except (psutil.Error, OSError) as exc:  # NoSuchProcess·AccessDenied 등 + Windows의 감싸지 않은 OSError (모듈 설명)
            action, fallback = ("정지", "읽기만 멈춤") if pause else ("재개", "읽기를 이어 감")
            print(f"{LOG_PREFIX} 정지/재개 실패 — {action}, pid {pid}: {type(exc).__name__}: {exc} ({fallback}): {self.path}",
                  file=sys.stderr, flush=True)

    def _log_after_stop(self, text: str) -> None:
        """stop() 뒤의 트레이스백이 있는 문제 — 신호 없이 기록(stderr)에 머리 한 줄과 글 전문 (조용히 사라지지 않게; 모든 패스가 같은 머리)."""
        print(f"{LOG_PREFIX} 멈춘 띠 워커에서 예상 못 한 오류가 났습니다 (stop 뒤라 신호 없음) — {self.path}\n{text}", file=sys.stderr, flush=True)

    def _report(self, problem: str | None, returncode: int | None, stderr: str, received: int, started: float,
                trace: str | None = None) -> None:
        """끝 신호 하나 (잠금 안). 문제 글이 없고(장 경계의 EOF) 종료 코드 0이면 done — stderr에 글이 있으면 경고 기록(stderr, 창 없음)을
        남김(모듈 설명: 잘린 파일). 아니면 failed. trace: 예상 못 한 예외의 트레이스백.
        stop()이 표지를 둔 뒤면 신호를 내지 않는다 — 정상 중단(kill로 끊긴 읽기·종료 코드)은 조용히, trace가 있는 문제는 기록(stderr)에 남김."""
        plan = self.strip.plan
        if trace is not None:
            problem = f"{problem}\n{trace.rstrip()}"
        with self._lock:
            if self._stopped:
                if trace is not None:
                    self._log_after_stop(problem)
                return
            if problem is None and returncode == 0:
                filled = self.strip.filled_count
                if stderr.strip():  # 삼키지 않음 — 잘린 파일이면 ffmpeg가 오류 줄을 찍고도 0으로 끝남
                    print(f"{LOG_PREFIX} ffmpeg 경고 (종료 코드 0, {filled}장 채움) — {self.path}\n{stderr.rstrip()}",
                          file=sys.stderr, flush=True)
                if received > plan.count:
                    print(f"{LOG_PREFIX} 계획보다 많은 장을 받아 버림: 넘침 {received - plan.count}장 (계획 {plan.count}장) — {self.path}",
                          flush=True)
                self.coarse_strip = None  # 정확한 띠가 다 참 — 거친 띠는 버림 (done을 내기 전에)
                self.done.emit(filled, time.monotonic() - started)
                return
            if problem is None:
                problem = f"ffmpeg가 비정상 종료했습니다 (종료 코드 {returncode})"
            code = "없음" if returncode is None else str(returncode)
            self.failed.emit(f"{problem}\n파일: {self.path}\n명령: {' '.join(self.command)}\n종료 코드: {code}\n"
                             f"stderr:\n{stderr.rstrip() or '(없음)'}")
