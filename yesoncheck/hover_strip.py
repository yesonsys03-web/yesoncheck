# -*- coding: utf-8 -*-
"""슬라이더 호버 썸네일의 순수 규칙 — 띠 계획·띠 저장소·파일 크기 상한·켬/끔 설정. Qt·cv2 없음.

왜: 슬라이더 위에 커서를 올리면 그 자리의 프레임 그림을 보여 주려면 재생 캡처와 무관한 별도 출처가 필요하다 (재생 캡처로 꺼내면 본화면이
튀고 스트림·링이 깨짐). 그래서 쉴 때 ffmpeg가 파일 전체를 작게 줄여 RAM에 '띠'로 깔아 두고(hover_strip_builder), 호버는 꺼내 보이기만 한다.
이 모듈은 그 띠의 크기·장수를 정하고(StripPlan), 만든 그림을 담고(HoverStrip), 만들지 말아야 할 파일을 가르고(skip_reason), 기능을 켜고 끄는
선택을 prefs.json에 두는(read_enabled·save_enabled) 규칙만 가진다 — 프로세스·스레드·화면은 다른 모듈의 몫이라 Qt 없이 시험한다. 이 기능의
글 상수(메뉴 글 MENU_TEXT·기록 머리 LOG_PREFIX·설정 창 제목 SETTINGS_TITLE)도 여기 한 곳에 둔다 — Qt 없는 모듈이라 app·믹스인·화면 쪽이 모두
순환 없이 가져다 씀.

크기 (스펙 §5.2): 그림은 THUMB_WIDTH(320) × THUMB_WIDTH 상자 안에 맞춘다 — THUMB_WIDTH는 이름과 달리 '긴 변의 길이'다. 가로로 긴 영상(W ≥ H)은 폭 320에
짝수 높이, 세로로 긴 영상(W < H)은 높이 320에 짝수 폭이고, 짧은 변은 비율을 지켜 짝수로 맞춘다. ffmpeg의 scale에는 폭·높이 **둘 다 명시**해 넘긴다 —
`-2`(ffmpeg가 짝수 변을 알아서 고름)에 맡기면 ffmpeg가 정한 크기와 이쪽 버퍼 크기(frame_bytes)가 어긋날 수 있어서다. 한 장의 바이트 수는
이 모듈이 정하고 ffmpeg가 그대로 따른다. 장수는 MAX_THUMBS(500) 이하: 전체 장수가 그 이하면 프레임마다, 넘으면 step 간격으로 띄엄띄엄
(샘플 i = 원본 i × step).

메모리: 320×180×3 = 172,800B(173KB)/장이라 16:9에서 500장이 86.4MB로 멈춘다 (파일 하나 분 — 바꾸면 버리고 디스크에 쓰지 않음). 어떤 비율이든 한 장은
320×320 상자 안이라 최대 307,200B/장 — 500장 153.6MB(정사각형)가 상한이다 (세로 9:16은 180×320 = 172,800B/장으로 16:9와 같음).

파일 크기 상한 (스펙 §5.2): 띄엄띄엄 골라도 ffmpeg의 select는 디코드한 뒤 버리므로 파일 **전체**를 읽고 전부 디코드한다. 그래서 장수 상한만으로는
수십 GB짜리 긴 ProRes가 NAS에서 통째로 다시 읽히는 것을 막지 못한다 — os.stat 크기가 MAX_FILE_BYTES(사용자 결정 "크기 상한", 숫자는 제 결정)를
넘으면 띠를 만들지 않는다 (실패가 아니라 규칙 — 번호 + 빈 상자만 보임).

띠 ffmpeg의 스레드 (thread_limits — 스펙 2026-11-11 §2, 규칙은 Ruling 24·25): 1코어(hover_strip_builder의 두 상수)는 4K ProRes 4444에서 Play
직전 여러 코어로 4K 장을 한꺼번에 디코드·축소하는 버스트를 막으려고 측정 뒤 넣은 것이다(2026-11-10 1·2차 게이트 실패 → Ruling 14). 그 뒤 재생
게이트(켬이 끔의 범위 안인지 — 이 Mac)로 나눈 규칙: ① 원본 화소 ≤ SINGLE_THREAD_ABOVE_PIXELS(1280×720)면 어느 코덱이든 옵션 없음(ffmpeg 기본 —
이 Mac은 CPU 수만큼; 720p H.264 721장 켬·끔 각 3판: 켬 45·67·76ms가 끔 44~91ms 안 — 통과) ② ≤ INTER_CODEC_FULL_THREADS_MAX_PIXELS(1920×1080)이고
코덱이 허용 목록 LONG_GOP_FULL_THREADS_CODECS(h264 — 재생 게이트를 잰 코덱만; 프로젝트 원칙 '양성 증거로만 켬', Ruling 26)에 있으면 옵션 없음(1080p
H.264 — KOTH 애니매틱 30초 클립 켬·끔 각 3판: 켬 62·65·48ms가 끔 50~84ms 안 — 통과) ③ 그 밖은 1코어 — 목록 밖 코덱이 720p보다 크면(hevc·vp9·
av1은 안 잼; all-intra는 1080p ProRes 422 HQ 334장 켬·끔 각 9판: 끔 최대간격 44~62ms·끊김 0/9, 켬은 2판이 89·124ms로 끔의
범위 밖 — 불통과; 그때 ffmpeg는 이미 정지돼 CPU 0; 막는 목록이던 때는 ALL_INTRA_CODECS 밖의 all-intra가 1080p에서 기본 스레드로 갔음), 코덱을 모르면(짧은 파일은 헤더를 읽지 않음 — 짧은 1080p ProRes 샷이 바로 그 불통과 파일),
1080p보다 크면(4K 측정값 그대로). 얻는 것: 긴 720p 애니매틱(22.6분 32,553장) 띠 67.0초 → 18.8초, 긴 1080p H.264 애니매틱(KOTH 35,693장) 82.2초 →
24.6초(이 Mac 실측). 1080p ProRes·4K 명령은 글자 그대로라 측정된 설정이 바뀌지 않는다. 그래서 계획은 그림 크기와 함께 원본 크기
(source_width·source_height)도 들고, 코덱은 부른 쪽(워커 — 헤더 ffprobe)이 넘긴다.

상수는 시험이 monkeypatch로 바꿔 끼울 수 있게 함수가 부를 때마다 모듈 값으로 읽는다 (기본 인자로 굳히지 않음). 설정 키 slider_thumbnails는
Mac은 mac_prefs, Windows는 windows_display의 위치에 두며(prefs_path), 읽기·쓰기 규칙은 mac_prefs의 것을 그대로 쓴다: 없으면 기본 켬, 깨진
파일은 UserFileError(빈 값으로 치지 않아 다음 저장이 덮지 않음), 불리언이 아닌 값은 ValueError(값을 지어내지 않음).
"""

import os
import sys
from dataclasses import dataclass

import numpy as np

from yesoncheck import mac_prefs, windows_display
from yesoncheck.frame_cache_budget import gb

THUMB_WIDTH = 320  # 그림의 긴 변 (논리 px — 가로 영상은 폭, 세로 영상은 높이) — 키우면 메모리가 제곱으로 늘어남
MAX_THUMBS = 500  # 띠의 최대 장수
MAX_FILE_BYTES = 4 * 10**9  # 이보다 큰 파일은 띠를 만들지 않음 (os.stat 크기)
SINGLE_THREAD_ABOVE_PIXELS = 1280 * 720  # 원본 화소가 이 이하면 띠 ffmpeg의 스레드를 묶지 않음 — 어느 코덱이든 (thread_limits — 모듈 설명)
INTER_CODEC_FULL_THREADS_MAX_PIXELS = 1920 * 1080  # 이 이하이고 코덱이 LONG_GOP_FULL_THREADS_CODECS에 있으면 묶지 않음 (Ruling 25·26)
LONG_GOP_FULL_THREADS_CODECS = frozenset({"h264"})  # 허용 목록 — 1080p 재생 게이트를 잰 코덱만 (양성 증거로만 켬, Ruling 26)
ALL_INTRA_CODECS = frozenset({"prores", "dnxhd", "mjpeg", "rawvideo"})  # 모든 장이 키프레임인 코덱 — 거친 띠 건너뜀(hover_keyframes)
PREF_KEY = "slider_thumbnails"
MENU_TEXT = "슬라이더 썸네일"
LOG_PREFIX = "[슬라이더 썸네일]"
SETTINGS_TITLE = "슬라이더 썸네일 설정"  # 설정 창 제목 하나 — 시작 때 읽기 실패(app.load_slider_thumbnails)·메뉴의 저장 실패(player_hover_thumbs)

_enabled = True  # 프로세스 캐시 — app.load_slider_thumbnails가 시작 때 정하고 Settings 메뉴가 바꿈 (windows_display._preferred와 같은 모양)


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def thumb_size(width: int, height: int) -> tuple[int, int]:
    """원본 width×height의 그림 (폭, 높이) — THUMB_WIDTH(긴 변) 상자 안에 비율을 지켜 맞춤. 짧은 변은 짝수·최소 2.
    가로로 긴 영상(width ≥ height)은 (THUMB_WIDTH, 짝수 높이), 세로로 긴 영상은 (짝수 폭, THUMB_WIDTH)."""
    if width >= height:
        return THUMB_WIDTH, max(2, round(height * THUMB_WIDTH / width / 2) * 2)
    return max(2, round(width * THUMB_WIDTH / height / 2) * 2), THUMB_WIDTH


@dataclass(frozen=True)
class StripPlan:
    """띠 계획. total: 원본 전체 장수, step: 샘플 간격(원본 프레임), count: 띠의 장수, width·height: 그림 크기,
    source_width·source_height: 원본 크기 (스레드 규칙 thread_limits가 봄)."""
    total: int
    step: int
    count: int
    width: int
    height: int
    source_width: int
    source_height: int

    def source_frame(self, i: int) -> int:
        """샘플 i의 원본 프레임 번호 (0-based)."""
        return i * self.step

    def sample_for(self, frame: int) -> int:
        """원본 프레임(0-based)에 가장 가까운 샘플 번호 — [0, count-1]로 자름."""
        return min(max(round(frame / self.step), 0), self.count - 1)

    @property
    def frame_bytes(self) -> int:
        """그림 한 장의 바이트 (rgb24 — ffmpeg rawvideo의 한 장과 같은 크기)."""
        return self.width * self.height * 3


def plan_for(total: int, width: int, height: int) -> StripPlan:
    """전체 장수 total, 원본 크기 width×height의 띠 계획. total ≤ MAX_THUMBS면 프레임마다, 아니면 간격을 띄움. 값이 1 미만이면 ValueError."""
    if total < 1 or width < 1 or height < 1:
        raise ValueError(f"띠 계획의 장수·폭·높이는 1 이상이어야 합니다: total={total} width={width} height={height}")
    step = _ceil_div(total, MAX_THUMBS)  # total ≤ MAX_THUMBS면 1
    thumb_width, thumb_height = thumb_size(width, height)
    return StripPlan(total=total, step=step, count=_ceil_div(total, step), width=thumb_width, height=thumb_height,
                     source_width=width, source_height=height)


def thread_limits(plan: StripPlan, decoder: int | None, filters: int | None,
                  codec: str | None = None) -> tuple[int | None, int | None]:
    """띠 ffmpeg의 (디코더 스레드, 필터 스레드) — (None, None)이면 옵션을 넣지 않음(ffmpeg 기본), 아니면 부른 쪽의 값(큰 파일의 값) 그대로.
    원본 화소 ≤ SINGLE_THREAD_ABOVE_PIXELS면 (None, None); ≤ INTER_CODEC_FULL_THREADS_MAX_PIXELS이고 codec(헤더의 codec_name — 모르면 None)이
    LONG_GOP_FULL_THREADS_CODECS(허용 목록)에 있으면 (None, None); 그 밖은 부른 쪽의 값. 문턱·목록은 부를 때마다 모듈 값으로 읽음 (모듈 설명)."""
    pixels = plan.source_width * plan.source_height
    if pixels <= SINGLE_THREAD_ABOVE_PIXELS:
        return None, None
    if pixels <= INTER_CODEC_FULL_THREADS_MAX_PIXELS and codec in LONG_GOP_FULL_THREADS_CODECS:
        return None, None
    return decoder, filters


def skip_reason(path: str) -> str | None:
    """파일이 MAX_FILE_BYTES보다 크면 띠를 만들지 않는 이유 글, 아니면 None. os.stat의 OSError는 그대로 올림."""
    size = os.stat(path).st_size
    if size > MAX_FILE_BYTES:
        return f"파일 {gb(size)} > 상한 {gb(MAX_FILE_BYTES)}"
    return None


class ImageRows:
    """그림 행 저장소 — (count, h, w, 3) uint8 배열 하나(연속)와 행마다 채움 표시. 쓰는 쪽은 워커 스레드, 읽는 쪽은 GUI 스레드.
    띠(HoverStrip — 행 i = 샘플 i)와 키프레임 거친 띠(hover_keyframes.KeyframeStrip — 행 j = 키프레임 j)가 함께 씀.

    행 단위로만 쓰므로 잠금은 없다. 단 채움 표시는 행에 바이트를 다 복사한 **뒤**에 둔다 — GUI가 반쯤 쓴 행을 보지 않게. 같은 행은 한 번만
    put한다(다시 쓰면 GUI가 덮어쓰는 중인 행을 읽을 수 있음 — 워커가 지킴). ROW_NAME: 오류 글의 행 이름."""

    ROW_NAME = "샘플"

    def __init__(self, count: int, width: int, height: int):
        self.count = count
        self.width = width
        self.height = height
        self._frames = np.empty((count, height, width, 3), dtype=np.uint8)
        self._filled = bytearray(count)

    @property
    def frame_bytes(self) -> int:
        """그림 한 장의 바이트 (rgb24 — ffmpeg rawvideo의 한 장과 같은 크기)."""
        return self.width * self.height * 3

    def put(self, i: int, data) -> None:
        """행 i의 그림을 복사해 넣음. 길이가 frame_bytes와 다르면 ValueError (채움 표시 없음)."""
        view = memoryview(data)
        if view.nbytes != self.frame_bytes:
            raise ValueError(f"그림 한 장은 {self.frame_bytes}바이트여야 합니다: {view.nbytes}바이트 ({self.ROW_NAME} {i})")
        self._frames[i] = np.frombuffer(view, dtype=np.uint8).reshape(self.height, self.width, 3)
        self._filled[i] = 1

    def has(self, i: int) -> bool:
        return bool(self._filled[i])

    def image(self, i: int) -> np.ndarray:
        """행 i의 (h, w, 3) 뷰 (복사 아님). 아직 채우지 않았으면 LookupError."""
        if not self._filled[i]:
            raise LookupError(f"{self.ROW_NAME} {i}는 아직 채우지 않았습니다 ({self.filled_count}/{self.count}장)")
        return self._frames[i]

    @property
    def filled_count(self) -> int:
        return self._filled.count(1)

    @property
    def nbytes(self) -> int:
        return self._frames.nbytes


class HoverStrip(ImageRows):
    """띠 저장소 — 계획(plan)의 장수·그림 크기의 그림 행 (행 i = 샘플 i = 원본 plan.source_frame(i))."""

    def __init__(self, plan: StripPlan):
        super().__init__(plan.count, plan.width, plan.height)
        self.plan = plan


def prefs_path() -> str:
    """이 PC의 prefs.json — Windows는 windows_display(%LOCALAPPDATA%), 그 밖에는 mac_prefs(~/Library/Application Support)."""
    if sys.platform == "win32":
        return windows_display.prefs_path()
    return mac_prefs.prefs_path()


def read_enabled(path: str | None = None) -> bool:
    """저장된 켬/끔 (키가 없으면 True). 불리언이 아니면 ValueError, 깨진 파일은 UserFileError 그대로 — 값을 지어내지 않음."""
    value = mac_prefs.read_prefs(path or prefs_path()).get(PREF_KEY, True)
    if not isinstance(value, bool):
        raise ValueError(f"{PREF_KEY}는 true 또는 false여야 합니다: {value!r}")
    return value


def save_enabled(value: bool, path: str | None = None) -> None:
    """파일에 저장 (그 키만 고침 — 다른 키는 그대로). 불리언이 아니면 TypeError — read_enabled가 거부할 값을 파일에 쓰지 않음(파일은 그대로).
    깨진 파일은 덮지 않고 UserFileError."""
    if not isinstance(value, bool):
        raise TypeError(f"{PREF_KEY}는 bool이어야 합니다: {value!r}")
    mac_prefs.update_pref(PREF_KEY, value, path or prefs_path())


def set_enabled(value: bool) -> None:
    """프로세스 캐시를 바꿈. 불리언이 아니면 TypeError — 조용히 참·거짓으로 바꾸지 않으며 캐시는 그대로."""
    global _enabled
    if not isinstance(value, bool):
        raise TypeError(f"{PREF_KEY}는 bool이어야 합니다: {value!r}")
    _enabled = value


def enabled() -> bool:
    return _enabled
