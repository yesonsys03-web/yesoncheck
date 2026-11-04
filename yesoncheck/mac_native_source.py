"""네이티브(VideoToolbox) 프레임 소스: AVAssetReader가 ProRes를 IOSurface가 받친 32BGRA CVPixelBuffer로 디코드하고, 그 메모리 위의
배열을 cv2.VideoCapture 자리에 꽂는 캡처(NativeVTCapture — movie_pipe_source.FFmpegPipeCapture와 같은 계약)로 내준다. CPU 픽셀 일이
없다: 읽기 스레드는 copyNextSampleBuffer → 읽기 잠금 → 배열 씌우기 → 큐에 넣기만 하고, read()는 큐·링에서 꺼내 그대로 준다(복사·색
변환·tobytes 없음). 프레임은 frame_handles.NativeFrameArray — (높이, 너비, 4) uint8 BGRX 읽기 전용 뷰([..., :3]이 BGR, 넷째 채널은
알파로 읽지 말 것), .native가 NativeHandle(IOSurface 포인터·크기·프레임 번호·keepalive)이고 whole_surface_handle(frame)이 그 손잡이를
돌려준다(GPU 쪽이 표면을 복사 없이 질감으로 씀).

판정은 하지 않는다: 어느 파일을 이 캡처로 열지는 mac_native_gate(토글·Apple Silicon·4K ProRes 4:4:4·색 태그)를 본 플레이어가 정한다
(시험은 게이트 없이 아무 크기의 클립이나 직접 연다). PyObjC는 함수 안(_pyobjc — 잠금 아래 한 번)에서만 불러온다: 이 모듈은 PyObjC가
없는 Intel Mac·Windows에서도 import된다(빌드의 모듈 검사·플레이어의 지연 분기). 두 스레드가 처음으로 동시에 PyObjC 프레임워크를
import하면 멈춘 일이 있어(Stage 0 디코드만 측정의 두 리더) 잠금 아래에서 부른다.

계약 (cv2와 같음 — FFmpegPipeCapture 설명과 같은 낱말): read()는 다음 프레임을 주고 pos를 1 올림. 끝에서는 (False, None)이고 pos는
그대로 — 단 받은 수가 nb_frames와 맞을 때만 끝이다. get(CAP_PROP_POS_FRAMES)는 다음에 읽을 번호(set이 기록한 목표가 있으면 그 값),
FPS는 float(avg)(cv2·파이프와 같은 출처 — AVFoundation의 nominalFrameRate가 아님), FRAME_COUNT는 nb_frames, 크기는 probe 값, 그 밖의
속성은 0.0. release한 캡처·죽은 캡처는 isOpened False, read (False, None), get 0.0, set False. 파이프와 달리 내주는 프레임은 새 복사본이
아니라 읽기 전용 원본이다 — 링에서 다시 내줄 때도 같은 객체(쓰기는 ValueError라 호출자가 고칠 수 없음).

번호: 프레임 번호는 받은 순서가 아니라 PTS에서 — round((PTS − 트랙 시작) × r), r은 probe의 정확한 분수 r_frame_rate이고 뺄셈·곱셈은
CMTime의 value/timescale을 Fraction으로 그대로(_frame_index — 프레임마다 따로 계산하므로 쌓이는 오차가 없고, 시간 단위가 600처럼 PTS를
반올림해 둔 파일도 ±0.5틱이 반올림 안에 듦). 리더가 주는 번호는 시작 번호부터 +1씩 빈틈 없이 이어져야 하고 어긋나면(빠짐·겹침·넘침)
죽음 — 번호를 믿을 수 없는 프레임을 내주지 않는다. EOF 불변식: 정상 끝은 '받은 장 수 == nb_frames'에서 리더가 끝났을 때뿐이다 — 일찍
끝나면(파일이 probe보다 짧음·잘림) 조용한 EOF가 아니라 죽음 + 기록, 넘쳐도 죽음 (재시작한 리더는 시작 번호부터 세므로 기준이 저절로 맞음).

탐색은 지연(lazy): set은 목표만 기록하고(0~count로 자르고 소수 버림, NaN·무한은 0), 다음 read()가 목표 n으로 — 스트림 우선(파이프와
같은 순서): ① n == 스트림 위치(리더가 다음에 줄 번호) → 리더에서 꺼내 내줌 ② 링(최근 리더에서 꺼낸 NATIVE_KEEP_BEHIND장)에 있음 → 그
프레임 ③ 스트림 위치 < n ≤ 스트림 위치 + NATIVE_SEEK_FORWARD_MAX → 큐·리더에서 꺼내 버린 뒤 ①(버린 것도 링에) ④ 그 밖 → 리더 재시작:
그 프레임 시각부터 timeRange로 새 AVAssetReader. 재시작 시작 번호 = n − K — 앞으로(n > 스트림 위치)는 K = 0(목표에서 바로 — 앞으로
끄는 슬라이더가 느려지지 않게), 뒤로(n < 스트림 위치)는 K = min(NATIVE_KEEP_BEHIND, n)(파이프의 '뒤로 재시작 미리 채우기'와 같은 규칙,
Ruling 11 ①): 목표 8장 앞에서 띄워 그 장들을 꺼내 버리며 링에 보관하므로 이어지는 ←가 링에서 나온다 — 링은 8장 FIFO라 착지 뒤 링은
n − 7..n이고 ←는 8번에 한 번만 재시작(스파이크는 ←마다 재시작이었음, M1 4K 43~75ms). 재시작은 링을 비운다(링은 늘 리더에서 최근 꺼낸
연속 구간). set(count)처럼 끝 자리로의 먼 탐색은 리더를 띄우지 않고 곧바로 끝(False, None)이다. 재시작 비용(Ruling 8): 이 Mac·M1 정상
상태 ≈24ms(프로세스의 첫 재시작만 ≈190ms) — 그래서 링 8장만 두고 파일 전체 보관은 하지 않는다.

리더 churn (Ruling 11 ②): 재시작은 옛 리더를 먼저 멈추고 — 옛 읽기 스레드가 하던 한 장을 마친 뒤 스스로 cancelReading하고 리더 참조를
놓고 끝나기를 기다린 '뒤에'(보통 한 장 디코드 이하) — 새 리더를 만든다: 같은 애셋의 리더 둘이 겹쳐 돌지 않는다. 리더는 만든 뒤 읽기
스레드만 만진다 — 다른 스레드가 cancelReading하면 그때 copyNextSampleBuffer 안에 있던 읽기 스레드가 AVFoundation 안에서 죽는다(이 Mac
실측 SIGSEGV: 재시작 연타 2,000번에서 확률적으로 — faulthandler로 copyNextSampleBuffer 안). M1 1회차에서는 23번째 재시작 뒤 재생 중
AVAssetReader가 status failed -11821 "Cannot Decode"(NSOSStatus -12137)로 죽었는데(내부 records/2026-11-03-mac-native-playback/m1-logs/
yesoncheck_20261104_13175.log), 이 Intel Mac에서는 재현되지 않았다 — 이 캡처로 320×180 60장에서 먼 점프 2,000번·1초에 10번 뒤로 한 칸
100번·처음부터 끝까지 5번(재시작 1,894번), 실파일 4K 4444(FL_106_A001, 334장)에서 먼 점프 300번·1초에 10번 뒤로 120번·끝까지 3번(재시작
319번); 스파이크 캡처 그대로(누수 있음·←마다 재시작)도 M1 순서(재생 → ← 연타 → 처음으로 → 재생)로 4K·작은 4444 둘 다 통과. 그래서
재시도 없이 죽음(B 방식)으로 둔다 — M1의 실패는 그날 함께 돈 샘플 버퍼 누수(아래 — 16GB 기계에서 83GB)로 VideoToolbox 쪽 메모리·IOSurface가
바닥난 것과 겹쳐 있었다; 고친 뒤 M1에서 다시 보면 확실해진다.

샘플 버퍼 누수 (Ruling 13 — M1 83GB): AVAssetReaderOutput.copyNextSampleBuffer는 Copy 규칙(+1)으로 CMSampleBuffer를 돌려주는데 PyObjC
12.2.2의 메타데이터에 이 셀렉터의 already_cfretained가 없어 PyObjC가 +1을 갚지 않았다 → 샘플마다 참조 하나가 영원히 남아 CVPixelBuffer →
IOSurface를 붙잡고, VT 풀이 표면을 돌려받지 못해 장마다 새 표면을 만듦(320×180 300장에서 서로 다른 표면 300개, 4K 한 장 33.2MB). 고침은
_pyobjc()가 첫 리더 전에 한 번 거는 registerMetaDataForSelector 한 줄(기반 클래스 AVAssetReaderOutput — AVAssetReaderTrackOutput에도
적용). 호출처마다 CFRelease를 더하지 말 것: 호출처가 하나라도 빠지면 다시 새고, 나중 PyObjC가 메타데이터를 넣으면 이중 해제(크래시)가
된다 — 메타데이터 등록은 같은 값을 다시 넣는 것이라 그때도 무해. 고친 뒤에는 손잡이가 죽는 즉시 버퍼가 VT 풀로 돌아가 다음 프레임에
다시 쓰인다 — 손잡이 없이 이 메모리를 가리키는 것(원시 memoryview·포인터)을 밖에 내주면 누수 대신 엉뚱한 픽셀이 된다. 그래서 바탕
memoryview는 wrap_native에만 넘기고(뷰의 .base 사슬이 손잡이 → keepalive를 붙듦), GL은 묶은 표면의 손잡이를 다 쓸 때까지 쥘 것.

keepalive와 수명: 손잡이의 keepalive는 _LockedBuffer(CVPixelBuffer 하나의 읽기 잠금 주인) — 이 객체가 사라질 때(참조 계수만으로, gc
없이) CVPixelBufferUnlockBaseAddress(ReadOnly) 뒤 버퍼 참조를 놓는다. 배열은 쥐지 않는다(배열 → _SurfaceBuffer → 손잡이 → 주인 → 버퍼,
한 방향 — 순환 없음). 캡처의 메모리(4K BGRA 33.2MB/장 — 모두 VideoToolbox의 IOSurface, 앱 RSS에는 0으로 잡힘): 선읽기 큐
NATIVE_READAHEAD 4장 + 링 8장 + 읽기 스레드가 손에 든 1장 ≈ 13장 ≈ 430MB, 호출자가 쥔 프레임(플레이어의 frame_a 등)은 따로.

실패 처리 (B 방식 — 스펙 §5.3, 파이프와 같은 모양): NativeCaptureError(원인·파일)는 열 때만(생성자·open_native_capture) — AVFoundation이
못 읽는 파일, 크기가 probe와 다름, 리더를 시작하지 못함, 첫 프레임이 NATIVE_READ_TIMEOUT_S 안에 안 옴·번호가 0이 아님, PyObjC 없음.
그 뒤의 read·get·set은 예외를 내지 않는다 — 도중 실패(리더 status failed·읽기 스레드 예외, 번호 어긋남, NATIVE_READ_TIMEOUT_S 동안
프레임 없음, 일찍 끝남·넘침, 재시작할 때 옛 리더가 그 한도 안에 멈추지 않음·새 리더를 시작하지 못함)는 큐에 남은 정상 프레임을 다 준 뒤 드러나고, 그때 캡처가 스스로 '죽음':
(죽은 cv2 캡처의 겉모습 — read (False, None)·isOpened False·get 0.0·set False, is_dead True) 링·큐를 비우고 리더를 멈춤(읽기 스레드가 cancelReading) →
기록(stderr)에 즉시 한 번(원인 — 읽기 스레드의 트레이스백이 있으면 그 전문 — 과 읽던 곳의 호출 스택) → 오류 창은 Qt 루프에서 한 번
(movie_pipe_source의 전달자 _window_relay를 같이 씀 — 큐드 연결이라 재생 타이머 슬롯 안에서 모달을 열지 않음; QApplication이 없으면
기록만). 창 글의 끝 줄은 탈출구 안내(NATIVE_ESCAPE_HINT — YESONCHECK_MAC_NATIVE=off). 죽은 뒤의 read는 다시 알리지 않는다.

스레드: read()는 한 번에 한 스레드만 부른다(GUI — 파이프와 같은 계약). get·set·release는 다른 스레드에서 불러도 된다: 캡처의 상태
(_session·_finalizer·_pos·_stream_pos·_ring·_target)는 _lock이 지키고, read()는 프레임을 기다리는 동안과 리더를 띄우는 동안 _lock을
잡지 않는다 — 다른 스레드의 release가 기다림을 깨워 끝낼 수 있다(그 read는 (False, None), 실패 아님). 죽음 전이는 '_session이 아직 그
세션일 때 None으로 바꾼 쪽'만 하므로 한 번뿐. 읽기 스레드는 데몬이고 캡처를 붙잡지 않는다(세션만 — 리더·출력·영상 정보·큐). release
없이 버려진 캡처의 리더는 weakref.finalize가 멈춘다(재시작하면 새 세션으로 다시 등록하고 옛 것은 불러서 끝냄).
"""

import collections
import ctypes
import math
import os
import sys
import threading
import time
import traceback
import weakref
from fractions import Fraction

import cv2

from yesoncheck.frame_handles import NativeHandle, wrap_native
from yesoncheck.mac_native_gate import NATIVE_MODE_ENV
from yesoncheck.movie_pipe_source import PLAY_LOG_PREFIX

NATIVE_READAHEAD = 4  # 읽기 스레드가 미리 받아 두는 프레임 수 (4K BGRA 33.2MB/장 — 캡처당 총량은 모듈 설명)
NATIVE_KEEP_BEHIND = 8  # 링: 리더에서 최근 꺼낸 프레임 보관 수 = 뒤로 재시작이 미리 채우는 장수 (Ruling 8·11 ①)
NATIVE_SEEK_FORWARD_MAX = 24  # 앞으로 이만큼까지는 큐·리더에서 꺼내 버림 (그보다 멀면 재시작)
NATIVE_READ_TIMEOUT_S = 30.0  # read()·생성자가 빈 큐를 기다리는 한도: 넘으면 멈춘 리더(NAS hard mount 등)로 보고 실패 처리
NATIVE_LOG_PREFIX = f"{PLAY_LOG_PREFIX} 네이티브(VideoToolbox):"  # 열기 기록 줄·도중 실패 기록의 머리 — 기록에 이 줄이 있으면 네이티브 경로
NATIVE_FAILURE_HEADLINE = "VideoToolbox로 영상을 읽다가 도중에 실패해 이 영상을 더 읽을 수 없습니다"  # 도중 실패의 기록·오류 창 첫 줄
NATIVE_ESCAPE_HINT = f"탈출구(네이티브 재생을 끄고 ffmpeg 파이프로 엶): {NATIVE_MODE_ENV}=off"  # 오류 창 글의 끝 줄
NATIVE_READER_THREAD = "native-vt-reader"  # 읽기 스레드 이름의 머리 (뒤에 리더 시작 번호)
READER_STATUS = {0: "unknown", 1: "reading", 2: "completed", 3: "failed", 4: "cancelled"}  # AVAssetReaderStatus
_STACK_HEADER = "읽던 곳 (가장 최근 호출이 마지막):\n"

# 세션에서 꺼낸 결과 (take·peek)
_FRAME = "frame"  # 프레임 (값: NativeFrameArray)
_END = "end"  # 리더가 정상으로 끝남 (status completed) — 캡처가 받은 수로 EOF 불변식을 봄
_FAILED = "failed"  # 리더 실패·읽기 스레드 예외 (값: 사유 글)
_TIMEOUT = "timeout"  # 한도 동안 아무것도 오지 않음
_STOPPED = "stopped"  # 세션을 멈춤 (release·죽음·재시작)

_IMPORT_LOCK = threading.Lock()
_FRAMEWORKS = None  # _pyobjc()가 처음 부를 때 채움

VIDEOTOOLBOX_FRAMEWORK = "/System/Library/Frameworks/VideoToolbox.framework/VideoToolbox"  # VTIsHardwareDecodeSupported를 ctypes로 (Ruling 15)
_HW_PROBE_LOCK = threading.Lock()
_HW_PROBE = None  # ctypes로 묶은 VTIsHardwareDecodeSupported (_ctypes_hw_probe가 처음 부를 때)
_HW_PROBE_FAILURE = None  # 묶지 못한 사유 — 기록에 한 번 찍은 뒤 다시 열어 보지 않음
HW_LABELS = {True: "yes", False: "no", None: "?"}  # hardware_decode_supported → hw= 낱말 (열기 기록 줄·check_frozen_imports 결과 줄이 함께 씀)


class NativeCaptureError(Exception):
    """네이티브 캡처를 열지 못함 (생성자·open_native_capture만 올림 — 그 뒤의 실패는 캡처 안에서 끝남). reason: 원인, path: 파일."""

    def __init__(self, reason, path):
        super().__init__(f"{reason}: {path}")
        self.reason = reason
        self.path = path


class _Frameworks:
    """_pyobjc()가 불러온 PyObjC 모듈 묶음. VideoToolbox는 PyObjC 래퍼(pyobjc-framework-VideoToolbox)가 없으면 None (의존성을 더하지
    않음 — 빌드에는 넣지 않으므로 _hardware_decode_supported가 ctypes로 프레임워크를 직접 부름)."""

    def __init__(self, objc, AVFoundation, CoreMedia, Foundation, Quartz, VideoToolbox):  # noqa: N803 (모듈 이름 그대로)
        self.objc = objc
        self.AVFoundation = AVFoundation
        self.CoreMedia = CoreMedia
        self.Foundation = Foundation
        self.Quartz = Quartz
        self.VideoToolbox = VideoToolbox


def _pyobjc():
    """PyObjC 모듈 묶음 — 처음 부를 때 잠금 아래에서 불러오고, 첫 리더보다 먼저 copyNextSampleBuffer의 소유 규칙(+1, Copy 규칙)을
    PyObjC에 알린다 (모듈 설명의 '샘플 버퍼 누수' — 한 번, 이 자리에서만). PyObjC가 없으면 ModuleNotFoundError 그대로 (생성자가
    NativeCaptureError로 감쌈)."""
    global _FRAMEWORKS
    with _IMPORT_LOCK:
        if _FRAMEWORKS is None:
            import objc
            import AVFoundation
            import CoreMedia
            import Foundation
            import Quartz

            objc.registerMetaDataForSelector(
                b"AVAssetReaderOutput", b"copyNextSampleBuffer", {"retval": {"already_cfretained": True}})
            try:
                import VideoToolbox
            except ModuleNotFoundError as exc:
                if exc.name != "VideoToolbox":  # 래퍼는 있는데 그 안의 import가 깨짐 — 감추지 않음
                    raise
                VideoToolbox = None
            _FRAMEWORKS = _Frameworks(objc, AVFoundation, CoreMedia, Foundation, Quartz, VideoToolbox)
        return _FRAMEWORKS


def _frame_index(value, timescale, start, rate):
    """PTS(value/timescale초) → 프레임 번호 = round((PTS − 트랙 시작 start초) × r) — 전부 정확한 분수(Fraction)라 프레임마다 따로
    계산해도 오차가 쌓이지 않는다 (23.976fps·시간 단위 600에서 1만 장 시험). 반올림은 0.5에서 위로 (파일이 반올림해 둔 PTS는 ±0.5틱
    — 1프레임의 1/50 안팎이라 경계에 닿지 않음)."""
    return math.floor((Fraction(value, timescale) - start) * rate + Fraction(1, 2))


def _valid_time(CM, t):  # noqa: N803
    """유효하고 유한한 CMTime인가 (무한·불확정·잘못된 값은 아님)."""
    invalid = CM.kCMTimeFlags_PositiveInfinity | CM.kCMTimeFlags_NegativeInfinity | CM.kCMTimeFlags_Indefinite
    return bool(t.flags & CM.kCMTimeFlags_Valid) and not t.flags & invalid and t.timescale > 0


class _Movie:
    """AVURLAsset의 첫 영상 트랙과 번호·시각 계산 값. rate: probe의 r_frame_rate (정확한 분수 — 탐색 시각과 PTS → 번호 둘 다)."""

    def __init__(self, fw, path, rate):
        AVF, CM = fw.AVFoundation, fw.CoreMedia  # noqa: N806
        if rate.numerator > 0x7FFFFFFF:  # 프레임 시각 index/r의 분모가 CMTime 시간 단위(int32)에 들어가야 함
            raise RuntimeError(f"프레임 속도 {rate}의 분자가 CMTime 시간 단위(32비트)를 넘습니다")
        self.rate = rate
        self._CM = CM
        with fw.objc.autorelease_pool():
            url = fw.Foundation.NSURL.fileURLWithPath_(path)
            self.asset = AVF.AVURLAsset.URLAssetWithURL_options_(url, {AVF.AVURLAssetPreferPreciseDurationAndTimingKey: True})
            tracks = self.asset.tracksWithMediaType_(AVF.AVMediaTypeVideo)
            if tracks is None or len(tracks) == 0:
                raise RuntimeError("AVFoundation이 영상 트랙을 찾지 못했습니다 (깨진 파일이거나 AVFoundation이 못 읽는 형식)")
            self.track = tracks[0]
            size = self.track.naturalSize()
            self.width, self.height = int(size.width), int(size.height)
            start = self.track.timeRange().start
            if not _valid_time(CM, start):
                raise RuntimeError(f"영상 트랙의 시작 시각이 유효하지 않습니다: {start}")
            self.start_time = start  # CMTime — 탐색 시각의 바탕
            self.start = Fraction(start.value, start.timescale)  # 초 — 번호 계산의 바탕
            descriptions = self.track.formatDescriptions()
            if not descriptions:
                raise RuntimeError("영상 트랙에 형식 설명(format description)이 없습니다")
            self.codec_type = int(CM.CMFormatDescriptionGetMediaSubType(descriptions[0]))  # 'ap4h'·'apch' … (FourCharCode)

    def index_of(self, pts):
        """샘플 PTS(CMTime) → 프레임 번호 (_frame_index). 유효하지 않은 PTS는 RuntimeError (읽기 스레드 실패 → 죽음)."""
        if not _valid_time(self._CM, pts):
            raise RuntimeError(f"샘플 PTS가 유효하지 않습니다: {pts}")
        return _frame_index(pts.value, pts.timescale, self.start, self.rate)

    def time_of(self, index):
        """index번 프레임의 시각 = 트랙 시작 + index / r (CMTime — index/r은 분모가 r의 분자인 정확한 분수)."""
        offset = Fraction(index) / self.rate
        return self._CM.CMTimeAdd(self.start_time, self._CM.CMTimeMake(offset.numerator, offset.denominator))


def _start_reader(fw, movie, start_index):
    """새 AVAssetReader + 트랙 출력(32BGRA, IOSurface, alwaysCopiesSampleData=False — 리더가 버퍼를 복사하지 않음) → (리더, 출력).
    start_index > 0이면 그 프레임 시각부터 끝까지(timeRange). 만들지 못하면 RuntimeError (리더 상태·오류 글 그대로)."""
    AVF, CM, Q = fw.AVFoundation, fw.CoreMedia, fw.Quartz  # noqa: N806
    with fw.objc.autorelease_pool():
        reader, error = AVF.AVAssetReader.assetReaderWithAsset_error_(movie.asset, None)
        if reader is None:
            raise RuntimeError(f"AVAssetReader를 만들지 못했습니다: {error}")
        settings = {Q.kCVPixelBufferPixelFormatTypeKey: Q.kCVPixelFormatType_32BGRA, Q.kCVPixelBufferIOSurfacePropertiesKey: {}}
        output = AVF.AVAssetReaderTrackOutput.assetReaderTrackOutputWithTrack_outputSettings_(movie.track, settings)
        output.setAlwaysCopiesSampleData_(False)
        if not reader.canAddOutput_(output):
            raise RuntimeError("AVAssetReader가 트랙 출력을 받지 않습니다")
        reader.addOutput_(output)
        if start_index > 0:
            reader.setTimeRange_(CM.CMTimeRangeMake(movie.time_of(start_index), CM.kCMTimePositiveInfinity))
        if not reader.startReading():
            raise RuntimeError(f"AVAssetReader startReading 실패 ({start_index}번 프레임부터): {_reader_state(reader)}")
    return reader, output


def _reader_state(reader):
    """리더 상태 글 — status 이름과 오류(도메인·코드·설명 전문)."""
    status = reader.status()
    return f"status={READER_STATUS.get(status, status)} error={reader.error()}"


def _copy_next_sample(output):
    """다음 샘플 (리더가 끝나거나 멈췄으면 None). 소유 규칙은 _pyobjc()의 메타데이터가 맞춤 — 여기서 CFRelease를 더하지 말 것.
    읽기 스레드가 부르는 단 한 자리 (멈춤 시험이 이 이름을 바꿔치기함). PyObjC는 이 호출 동안 GIL을 놓는다."""
    return output.copyNextSampleBuffer()


class _LockedBuffer:
    """CVPixelBuffer 하나의 읽기 잠금 주인 — NativeHandle.keepalive. 이 객체가 사라지면(마지막 뷰·손잡이가 놓일 때, 참조 계수만으로)
    잠금을 풀고 버퍼 참조를 놓는다 → 버퍼가 VideoToolbox 풀로 돌아감. 배열·캡처는 쥐지 않는다 (순환 없음 — 모듈 설명).
    잠금 해제가 실패하면(CVReturn ≠ 0) 예외를 올림 — 소멸자라 'Exception ignored in …'과 트레이스백으로 stderr에 드러남(삼키지 않음)."""

    def __init__(self, buffer, unlock, flags):
        self._buffer = buffer
        self._unlock = unlock
        self._flags = flags

    def __del__(self):
        buffer, self._buffer = self._buffer, None
        status = self._unlock(buffer, self._flags)
        if status != 0:
            raise RuntimeError(f"CVPixelBufferUnlockBaseAddress 실패 (CVReturn {status})")


def _wrap_sample(fw, movie, sample):
    """(읽기 스레드) 샘플 → NativeFrameArray: IOSurface·32BGRA·크기 확인, PTS → 번호, 바탕 주소 읽기 잠금(주인 _LockedBuffer가 풂),
    (높이, bytesPerRow) 읽기 전용 memoryview를 wrap_native로 (높이, 너비, 4) 뷰에 씌움. 픽셀은 건드리지 않는다. 어긋나면 RuntimeError."""
    CM, Q = fw.CoreMedia, fw.Quartz  # noqa: N806
    buffer = CM.CMSampleBufferGetImageBuffer(sample)
    if buffer is None:
        raise RuntimeError("CMSampleBufferGetImageBuffer가 None입니다 (영상 버퍼 없는 샘플)")
    surface = Q.CVPixelBufferGetIOSurface(buffer)
    if surface is None:
        raise RuntimeError("CVPixelBufferGetIOSurface가 None입니다 (IOSurface가 받치지 않은 버퍼)")
    pixel_format = Q.CVPixelBufferGetPixelFormatType(buffer)
    if pixel_format != Q.kCVPixelFormatType_32BGRA:
        raise RuntimeError(f"픽셀 형식이 32BGRA가 아닙니다: {pixel_format:#x}")
    width, height = Q.CVPixelBufferGetWidth(buffer), Q.CVPixelBufferGetHeight(buffer)
    if (width, height) != (movie.width, movie.height):
        raise RuntimeError(f"버퍼 크기 {width}×{height}가 트랙 {movie.width}×{movie.height}와 다릅니다")
    index = movie.index_of(CM.CMSampleBufferGetPresentationTimeStamp(sample))
    status = Q.CVPixelBufferLockBaseAddress(buffer, Q.kCVPixelBufferLock_ReadOnly)
    if status != 0:
        raise RuntimeError(f"CVPixelBufferLockBaseAddress 실패 (CVReturn {status})")
    owner = _LockedBuffer(buffer, Q.CVPixelBufferUnlockBaseAddress, Q.kCVPixelBufferLock_ReadOnly)  # 이제부터 잠금은 주인의 몫
    row = Q.CVPixelBufferGetBytesPerRow(buffer)
    # as_buffer는 바탕 주소 위의 memoryview(복사 없음, 버퍼를 쥐지 않음) — 수명은 wrap_native의 .base 사슬 → 손잡이 → 주인이 지킴
    memory = Q.CVPixelBufferGetBaseAddress(buffer).as_buffer(height * row).cast("B", (height, row)).toreadonly()
    handle = NativeHandle(iosurface=fw.objc.pyobjc_id(surface), width=width, height=height, index=index, keepalive=owner)
    return wrap_native(memory, handle)


def _reader_outcome(fw, reader):
    """(읽기 스레드) copyNextSampleBuffer가 None을 준 뒤: 정상 끝(status completed)이면 (_END, None), 아니면 (_FAILED, 상태 글)."""
    if reader.status() == fw.AVFoundation.AVAssetReaderStatusCompleted:
        return _END, None
    return _FAILED, f"AVAssetReader가 정상 끝이 아닙니다: {_reader_state(reader)}"


class _ReaderSession:
    """AVAssetReader 하나 + 읽기 스레드(데몬) + 선읽기 큐(최대 NATIVE_READAHEAD장, Condition). start번 프레임부터 끝까지 차례로.
    읽기 스레드는 copyNextSampleBuffer → _wrap_sample → 큐에 넣기만 한다(번호 검사·EOF 불변식은 캡처가 꺼낼 때). 캡처를 붙잡지 않는다.

    리더(AVAssetReader·출력)는 만든 뒤 읽기 스레드만 만진다 — 다른 스레드가 cancelReading하면 그때 copyNextSampleBuffer 안에 있던 읽기
    스레드가 AVFoundation 안에서 죽는다(이 Mac 실측: 재시작 연타에서 SIGSEGV, faulthandler로 copyNextSampleBuffer 안). 그래서 stop()은
    정지 표지만 세우고, 읽기 스레드가 지금 하던 한 장을 마친 뒤(큐 자리를 기다리던 중이면 곧바로) 스스로 cancelReading하고 리더 참조를
    놓고 끝난다 — closed가 그때 선다. 세션은 리더 참조를 따로 두지 않는다(스레드 인자뿐 — 스레드가 끝나면 놓임)."""

    def __init__(self, fw, movie, start):
        self.start = start
        self.cond = threading.Condition()
        self.frames = collections.deque()  # 선읽기 큐 (읽기 스레드가 넣고 캡처가 꺼냄)
        self.stopped = False
        self.finished = None  # 읽기 스레드가 끝난 까닭: (_END, None) / (_FAILED, 사유 글) — 큐를 다 꺼낸 뒤에 드러남
        self.closed = threading.Event()  # 읽기 스레드가 (멈췄으면 cancelReading까지 하고) 리더 참조를 다 놓고 끝남
        reader, output = _start_reader(fw, movie, start)
        # 리더는 이 칸으로 넘기고 읽기 스레드가 꺼내 감 — 스레드 인자로 넘기면 threading.Thread가 _run이 끝난 뒤(closed 뒤)까지 쥔다
        self._handoff = (reader, output)
        thread = threading.Thread(target=self._run, args=(fw, movie), name=f"{NATIVE_READER_THREAD}-{start}", daemon=True)
        try:
            thread.start()
        except BaseException:
            self._handoff = None
            reader.cancelReading()  # 스레드를 못 띄움 — 시작한 리더는 여기서 멈춤 (아직 아무도 읽지 않음)
            raise

    def _run(self, fw, movie):
        """(읽기 스레드) 큐에 자리가 나면 한 장씩. 정지 표지를 보면 리더를 cancelReading하고 끝남 — 리더를 만지는 단 하나의 스레드."""
        reader, output = self._handoff
        self._handoff = None
        try:
            self._read_loop(fw, movie, reader, output)
        except BaseException as exc:  # 캡처가 큐를 다 꺼낸 뒤 사유로 드러냄 (트레이스백 그대로 — 삼키지 않음)
            text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            with self.cond:
                self.finished = (_FAILED, f"읽기 스레드에서 예외가 났습니다:\n{text.rstrip()}")
                self.cond.notify_all()
        finally:
            try:
                if reader.status() == fw.AVFoundation.AVAssetReaderStatusReading:  # 멈춤·예외로 중간에 나감 (끝·실패한 리더는 그대로)
                    reader.cancelReading()
            finally:
                del reader, output
                self.closed.set()

    def _read_loop(self, fw, movie, reader, output):
        while True:
            with self.cond:
                while len(self.frames) >= NATIVE_READAHEAD and not self.stopped:
                    self.cond.wait()
                if self.stopped:
                    return
            with fw.objc.autorelease_pool():  # 이 스레드에는 Cocoa 런루프의 풀이 없음
                sample = _copy_next_sample(output)
                frame = None if sample is None else _wrap_sample(fw, movie, sample)
                del sample  # 샘플을 다음 반복까지 끌지 않음 (버퍼는 frame의 주인이 쥠)
            if frame is None:
                if self.stopped:
                    return
                outcome = _reader_outcome(fw, reader)
                with self.cond:
                    self.finished = outcome
                    self.cond.notify_all()
                return
            with self.cond:
                if self.stopped:
                    return
                self.frames.append(frame)
                self.cond.notify_all()
            del frame  # 큐 자리를 기다리는 동안 한 장을 더 쥐지 않음

    def take(self, timeout, remove=True):
        """다음 결과 — (_FRAME, 프레임) · 큐가 비었고 읽기 스레드가 끝났으면 그 까닭 (_END·_FAILED) · (_STOPPED, None) · 한도 동안 아무것도
        없으면 (_TIMEOUT, None). remove=False면 프레임을 큐에 둔 채 봄 (생성자의 첫 프레임)."""
        deadline = time.monotonic() + timeout
        with self.cond:
            while not self.frames and self.finished is None and not self.stopped:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return _TIMEOUT, None
                self.cond.wait(remaining)
            if self.stopped:
                return _STOPPED, None
            if self.frames:
                if not remove:
                    return _FRAME, self.frames[0]
                frame = self.frames.popleft()
                self.cond.notify_all()
                return _FRAME, frame
            return self.finished

    def stop(self):
        """멈춤 (여러 번 불러도 됨, 기다리지 않음): 정지 표지 → 큐 비움(잠긴 버퍼를 놓음) → 읽기 스레드를 깨움. cancelReading과 리더 참조
        놓기는 읽기 스레드가 지금 하던 한 장을 마친 뒤 스스로 한다(클래스 설명) — 끝났는지는 closed."""
        with self.cond:
            if self.stopped:
                return
            self.stopped = True
            self.frames.clear()
            self.cond.notify_all()


def _ctypes_hw_probe():
    """VideoToolbox.framework의 VTIsHardwareDecodeSupported를 ctypes로 묶은 함수 (C 서명 Boolean(CMVideoCodecType) → c_bool(c_uint32);
    처음 부를 때 잠금 아래 한 번 묶고 다시 씀). 프레임워크를 열지 못하거나(OSError) 함수가 없으면(AttributeError) None — 그 사유를 기록에
    한 줄로 한 번만 찍고 다시 열어 보지 않음(조용한 hw=? 금지, 열 때마다 같은 줄이 쌓이지 않게). 그 밖의 예외는 그대로 올림.
    macOS(네이티브 캡처를 연 뒤 — 생성자가 PyObjC를 먼저 부름)에서만 불린다."""
    global _HW_PROBE, _HW_PROBE_FAILURE
    with _HW_PROBE_LOCK:
        if _HW_PROBE is None and _HW_PROBE_FAILURE is None:
            try:
                function = ctypes.CDLL(VIDEOTOOLBOX_FRAMEWORK).VTIsHardwareDecodeSupported
            except (OSError, AttributeError) as exc:
                _HW_PROBE_FAILURE = f"{type(exc).__name__}: {exc}"
                print(f"{NATIVE_LOG_PREFIX} 하드웨어 디코드 여부를 알 수 없음(hw=?) — {VIDEOTOOLBOX_FRAMEWORK}의 "
                      f"VTIsHardwareDecodeSupported를 열지 못했습니다: {_HW_PROBE_FAILURE}", flush=True)
            else:
                function.restype = ctypes.c_bool
                function.argtypes = [ctypes.c_uint32]
                _HW_PROBE = function
        return _HW_PROBE


def _hardware_decode_supported(fw, codec_type):
    """VTIsHardwareDecodeSupported(코덱 FourCharCode 정수 — 'ap4h'·'apch' …) → bool (기록 hw=yes|no). PyObjC VideoToolbox 래퍼가 있으면
    그것을, 없으면(빌드에는 넣지 않음 — Ruling 15) ctypes로 프레임워크를 직접(_ctypes_hw_probe). 프레임워크를 열지 못하면 None (기록 hw=?
    — 사유는 _ctypes_hw_probe가 한 번 찍음)."""
    if fw.VideoToolbox is not None:
        return bool(fw.VideoToolbox.VTIsHardwareDecodeSupported(codec_type))
    function = _ctypes_hw_probe()
    if function is None:
        return None
    return bool(function(codec_type))


class NativeVTCapture:
    """VideoToolbox(AVAssetReader) 32BGRA IOSurface 캡처 — cv2.VideoCapture 계약 (모듈 설명: 계약·번호·탐색·실패·스레드). probe:
    movie_pipe_source.MovieProbe (프레임 수·fps·크기를 파이프·cv2와 같은 출처로).

    생성자가 리더를 띄우고 첫 프레임이 올 때까지 기다린다(eager) — 못 열면 NativeCaptureError. 첫 프레임은 큐에 남아 첫 read()가 씀.
    시험용: restart_count(열기 뒤 리더를 새로 띄운 횟수 — 탐색 ④), is_dead(도중 실패로 죽음 — release는 아님),
    hardware_decode_supported(이 코덱의 하드웨어 디코드 여부, 알 수 없으면 None)."""

    def __init__(self, path, probe):
        if probe.width < 1 or probe.height < 1 or (probe.nb_frames or 0) < 1 or probe.avg is None or probe.r is None:
            raise NativeCaptureError(f"네이티브로 열 수 없는 probe입니다 (크기·프레임 수·프레임 속도가 있어야 함): {probe}", path)
        self._path = path
        self._count = probe.nb_frames
        self._fps = float(probe.avg)
        self._width = probe.width
        self._height = probe.height
        self._lock = threading.Lock()
        self._session = None  # 지금 세션. None = 닫힘(release)·죽음
        self._pos = 0  # 다음에 내줄 프레임 번호
        self._stream_pos = 0  # 스트림 위치: 리더가 다음에 줄 번호 (재시작에서 시작 번호, 꺼낼 때마다 +1)
        self._ring = collections.OrderedDict()  # 번호 → 프레임: 리더에서 최근 꺼낸 NATIVE_KEEP_BEHIND장 (연속 구간, 재시작에서 비움)
        self._target = None  # set()이 기록한 탐색 목표 (다음 read()가 실행)
        self.restart_count = 0
        self.is_dead = False
        try:
            fw = _pyobjc()
            movie = _Movie(fw, path, probe.r)
        except Exception as exc:  # PyObjC 없음·AVFoundation이 못 읽음 — 원인 사슬을 이어 올림
            raise NativeCaptureError(f"AVFoundation으로 영상을 열지 못했습니다 — {type(exc).__name__}: {exc}", path) from exc
        if (movie.width, movie.height) != (probe.width, probe.height):
            raise NativeCaptureError(f"AVFoundation의 크기 {movie.width}×{movie.height}가 ffprobe의 {probe.width}×{probe.height}와 "
                                     "다릅니다", path)
        self._fw = fw
        self._movie = movie
        self.hardware_decode_supported = _hardware_decode_supported(fw, movie.codec_type)
        try:
            session = _ReaderSession(fw, movie, 0)
        except Exception as exc:
            raise NativeCaptureError(f"AVAssetReader로 읽기를 시작하지 못했습니다 — {type(exc).__name__}: {exc}", path) from exc
        self._finalizer = weakref.finalize(self, session.stop)  # 세션을 멈추는 단 하나의 길 (release·죽음·GC·재시작이 같이 씀)
        timeout = NATIVE_READ_TIMEOUT_S
        outcome, value = session.take(timeout, remove=False)
        if outcome != _FRAME or value.native.index != 0:
            self._finalizer()
            if outcome == _FRAME:
                reason = f"첫 프레임의 번호가 0이 아니라 {value.native.index}입니다 (트랙 시작·PTS가 어긋남)"
            elif outcome == _END:
                reason = "리더가 프레임을 하나도 주지 않고 끝났습니다"
            elif outcome == _FAILED:
                reason = value
            else:
                reason = f"리더가 {timeout:g}초 안에 첫 프레임을 주지 않았습니다"
            raise NativeCaptureError(f"VideoToolbox로 첫 프레임을 받지 못했습니다 — {reason}", path)
        self._session = session

    def isOpened(self):  # noqa: N802 (cv2 이름)
        return self._session is not None

    def read(self):
        with self._lock:
            session, target = self._session, self._target
            if session is None:
                return False, None
            n = self._pos if target is None else target  # 이번에 내줄 번호 (지연 탐색의 목표가 있으면 그것)
            ahead = n - self._stream_pos
            if ahead == 0:  # ① 스트림 위치 — 아래에서 꺼내 내줌
                self._arrive(n, target)
            elif n in self._ring:  # ② 링 — 그 프레임 그대로 (읽기 전용이라 복사 없음)
                frame = self._ring[n]
                self._arrive(n + 1, target)
                return True, frame
            restart = not 0 < ahead <= NATIVE_SEEK_FORWARD_MAX
            if ahead and restart and n >= self._count:  # 끝 자리로의 먼 탐색: 리더를 띄우지 않고 끝 (cv2처럼 pos = count)
                self._arrive(n, target)
                return False, None
        if ahead:  # ③ 앞으로 버리기 / ④ 재시작(ahead < 0이면 뒤로 — 미리 채움) — 끝나면 스트림 위치 == n (①)
            session = self._seek(session, n, target, restart, backward=ahead < 0)
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
        """CAP_PROP_POS_FRAMES의 목표를 기록하고 True — cv2·파이프처럼 0~count로 자르고 소수는 버림(NaN·무한은 0). get(POS_FRAMES)는
        곧바로 그 값, 실제 이동은 다음 read()가 한다 (지연). 닫힌·죽은 캡처, 다른 속성은 False. 숫자가 아니면 TypeError(부른 쪽 버그)."""
        number = float(value)
        target = min(max(int(number), 0), self._count) if math.isfinite(number) else 0
        with self._lock:
            if self._session is None or prop != cv2.CAP_PROP_POS_FRAMES:
                return False
            self._target = target
            return True

    def release(self):
        """닫기 (여러 번 불러도 됨): 세션을 떼고 링을 비운 뒤 세션 stop(정지 표지·큐 비움 — 읽기 스레드가 스스로 cancelReading하고
        끝남, 기다리지 않음). 호출자가 쥔 프레임은 그대로 읽힌다(자기 keepalive가 버퍼를 쥠)."""
        with self._lock:
            session, self._session = self._session, None
            self._pos, self._target, self._stream_pos = 0, None, 0
            self._ring.clear()
            finalizer = self._finalizer
        if session is not None:
            finalizer()

    # ------------------------------------------------------------ 안

    def _arrive(self, pos, target):
        """(_lock 안) 이동을 마침: pos를 정하고 이번 read가 실행한 목표를 지움 (그사이 다른 목표가 기록됐으면 그것은 다음 read의 몫)."""
        self._pos = pos
        if target is not None and self._target == target:
            self._target = None

    def _seek(self, session, n, target, restart, backward):
        """(read 안, _lock 밖) 스트림을 n번으로: restart면 ④ 재시작(_restart — 뒤로면 n − K부터) 뒤, 스트림 위치가 n이 될 때까지 꺼내
        버림(③·미리 채우기 — 버린 것도 링에). → 이동을 마친 세션, 또는 None (그사이 release / 죽음 — 알림까지 끝냄)."""
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
            if not self._pull(session, deliver=False)[0]:  # 버리기 — 목표 앞의 끝은 도중 실패
                return None

    def _restart(self, old, target, backward):
        """(read 안, _lock 밖) 리더 재시작 (모듈 설명의 '리더 churn'): 옛 세션을 먼저 멈추고 그 읽기 스레드가 cancelReading하고 리더를
        놓고 끝나기를 기다린 뒤(보통 한 장 디코드 이하 — NATIVE_READ_TIMEOUT_S를 넘으면 멈춘 저장소로 보고 죽음) start = target − K부터 새
        세션 → 캡처의 세션·GC 안전망을 바꾸고 링을 비우고 스트림 위치를 start로(pos는 목표 그대로 — 미리 채우는 동안 다른 스레드의
        get(POS_FRAMES)가 목표 앞 번호를 보지 않게). → 새 세션, 또는 None (옛 리더가 멈추지 않음·새 리더를 시작하지 못해 죽음 — 알림까지
        끝냄 / 그사이 release됨). read 밖으로 예외를 내지 않는다 (B 방식)."""
        start = target - min(NATIVE_KEEP_BEHIND if backward else 0, target)
        old.stop()
        timeout = NATIVE_READ_TIMEOUT_S
        if not old.closed.wait(timeout):
            self._die_unless_released(old, f"{target}번 프레임으로 탐색하려는데 옛 리더({old.start}번부터)가 {timeout:g}초 안에 멈추지 "
                                           "않았습니다 (copyNextSampleBuffer가 돌아오지 않음 — 저장소가 멈췄을 수 있음)")
            return None
        try:
            new = _ReaderSession(self._fw, self._movie, start)
        except Exception as error:
            headline = f"{target}번 프레임으로 탐색하려고 AVAssetReader를 {start}번부터 다시 시작하지 못했습니다"
            try:
                reason = f"{headline}:\n{traceback.format_exc().rstrip()}"
            except Exception:  # 사유 글을 만들다 실패해도 read 밖으로 내지 않음
                reason = f"{headline} ({type(error).__name__})"
            self._die_unless_released(old, reason)
            return None
        with self._lock:
            swapped = self._session is old
            if swapped:
                self._session = new
                old_finalizer, self._finalizer = self._finalizer, weakref.finalize(self, new.stop)
                self._ring.clear()
                self._stream_pos, self._pos = start, target
                self.restart_count += 1
        if not swapped:  # 띄우는 사이 다른 스레드가 release함
            new.stop()
            return None
        old_finalizer()  # 옛 세션의 GC 안전망을 뺌 (stop은 이미 했으므로 다시 불려도 무해)
        return new

    def _die_unless_released(self, session, reason):
        """(read 안, _lock 밖) session이 아직 캡처의 세션이면 죽음 전이와 뒤처리(_die) — 그사이 release됐으면 아무것도 안 함."""
        with self._lock:
            dying = self._session is session
            if dying:
                self._session = None  # 죽음 전이
                self.is_dead = True
        if dying:
            self._die(reason)

    def _pull(self, session, deliver):
        """(read 안) 세션에서 다음 프레임 하나를 꺼내(기다리는 동안 _lock 없음) 번호를 확인하고(스트림 위치와 같아야 하고 count 앞이어야
        함) 링에 보관, 스트림 위치 +1 — deliver면 호출자에게(pos도 전진), 아니면 버리기. → (True, 프레임) · 버리기면 (True, None) /
        (False, None): 정상 끝(스트림 위치 == count에서 리더가 끝남) · 그사이 release · 도중 실패(여기서 죽음 전이와 알림까지)."""
        outcome, value = session.take(NATIVE_READ_TIMEOUT_S)
        with self._lock:
            if self._session is not session:  # 기다리는 사이 다른 스레드가 release함 (일부러 끝냄 — 실패 아님)
                return False, None
            expected = self._stream_pos
            if outcome == _FRAME and expected < self._count and value.native.index == expected:
                self._ring[expected] = value
                while len(self._ring) > NATIVE_KEEP_BEHIND:
                    self._ring.popitem(last=False)
                self._stream_pos = expected + 1
                if not deliver:
                    return True, None
                self._pos = expected + 1
                return True, value
            if outcome == _END and expected == self._count:  # 정상 끝: cv2처럼 pos 그대로, 열린 채
                return False, None
            reason = self._failure_reason(session, outcome, value)
            self._session = None  # 죽음 전이 — 이 줄에 닿는 것은 세션마다 한 번
            self.is_dead = True
        del value
        self._die(reason)
        return False, None

    def _failure_reason(self, session, outcome, value):
        """(_lock 안) 세션에서 꺼내다 본 도중 실패의 원인 글 — 리더 시작 번호와 그 리더가 준 장 수로 말한다."""
        expected = self._stream_pos
        got = f"{session.start}번 프레임부터 연 리더가 {expected - session.start}장을 준 뒤"
        if outcome == _FRAME:
            if expected >= self._count:
                return f"리더가 파일의 프레임 수 {self._count}보다 많은 프레임을 줬습니다 ({got} — 넘침)"
            return (f"PTS에서 계산한 번호 {value.native.index}가 기대 번호 {expected}와 다릅니다 — 빠지거나 겹친 프레임 ({got})")
        if outcome == _END:
            return (f"리더가 {expected}번 프레임 앞에서 끝났습니다 — 받은 장 수가 파일의 프레임 수 {self._count}보다 적음 ({got}: "
                    "파일이 probe보다 짧거나 잘림)")
        if outcome == _FAILED:
            return f"{value}\n({got})"
        if outcome == _TIMEOUT:
            return f"리더가 {NATIVE_READ_TIMEOUT_S:g}초 동안 다음 프레임을 주지 않았습니다 ({got})"
        return f"리더 세션이 멈춰 있습니다 ({got})"

    def _die(self, reason):
        """죽음 전이 뒤의 뒤처리 (read가 _lock 밖에서 한 번): 링 비움 → 세션 stop(큐 비움 — 읽기 스레드가 cancelReading) → 기록 한 번 → 오류 창은 Qt
        루프에서 한 번. _lock을 스스로 잡으므로 _lock을 쥔 채 부르면 안 된다. 예외를 내지 않음 (read 안 — B 방식)."""
        with self._lock:
            self._ring.clear()  # 죽은 캡처는 더 읽지 않음 — 잠긴 버퍼(4K 8장 ~266MB)를 붙들지 않게
            self._target = None
            finalizer = self._finalizer
        try:
            finalizer()
        except Exception:
            _last_resort(f"AVAssetReader를 멈추지 못했습니다: {self._path}")
        try:
            context = f"{NATIVE_FAILURE_HEADLINE}.\n파일: {self._path}\n원인: {reason}"
            details = _STACK_HEADER + "".join(traceback.format_stack()).rstrip()
        except Exception:
            _last_resort(f"{NATIVE_FAILURE_HEADLINE} — 알릴 글을 만들지 못했습니다: {self._path}\n원인: {reason}")
            return
        _report_failure(context, details)


def _report_failure(context, details):
    """도중 실패 알림 — 어느 스레드에서 불러도 되고 예외를 내지 않는다 (movie_pipe_source._report_failure와 같은 모양, 머리만 다름).
    기록(stderr — 빌드 앱은 기록 파일)에는 지금 바로 한 번: context + details 전부. 오류 창은 QApplication이 있으면 GUI 스레드의 Qt
    루프로 미뤄 한 번(파이프의 전달자 _window_relay — 프로세스에 하나): error_window.with_details(context, details) + 끝 줄 탈출구 안내.
    QApplication이 없으면(Qt 없는 쓰임) 기록만."""
    try:
        print(f"{NATIVE_LOG_PREFIX} {context}\n\n{details}", file=sys.stderr, flush=True)
        from PyQt5.QtCore import QCoreApplication

        if QCoreApplication.instance() is not None:
            from yesoncheck import error_window, movie_pipe_source

            text = f"{error_window.with_details(context, details)}\n\n{NATIVE_ESCAPE_HINT}"
            movie_pipe_source._window_relay().requested.emit(text)
    except Exception:
        _last_resort(context)


def _last_resort(message):
    """(except 블록 안에서) 알리다 또 실패함: 원래 stderr(sys.__stderr__)에 message와 그 예외의 트레이스백. 원래 stderr가 없거나 거기
    쓰는 것마저 실패하면 더 남길 곳이 없다 — 올리면 read()에서 예외가 나가므로(B 방식) 올리지 않는다. 알림 사슬의 끝."""
    stream = sys.__stderr__
    if stream is None:
        return
    try:
        stream.write(f"{NATIVE_LOG_PREFIX} 오류를 알리지 못했습니다 — {message}\n{traceback.format_exc()}\n")
        stream.flush()
    except Exception:  # 남길 곳이 없음 (위 docstring)
        pass


def open_native_capture(path, probe):
    """path를 네이티브 캡처로 열고 기록 한 줄을 남김 — `[재생] 네이티브(VideoToolbox): <이름> (prores 3840×2160 24fps, 프레임 334,
    32BGRA, hw=yes|no|?)` (기록에 이 줄이 있으면 네이티브 경로). 게이트는 부른 쪽 몫. 못 열면 NativeCaptureError (기록 줄 없음)."""
    capture = NativeVTCapture(path, probe)
    hw = HW_LABELS[capture.hardware_decode_supported]
    print(f"{NATIVE_LOG_PREFIX} {os.path.basename(path)} ({probe.codec} {probe.width}×{probe.height} {float(probe.avg):g}fps, "
          f"프레임 {probe.nb_frames}, 32BGRA, hw={hw})")
    return capture
