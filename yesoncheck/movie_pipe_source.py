"""ffmpeg 파이프 프레임 소스의 판정 부분: ffprobe 한 번으로 영상 파일의 모양을 읽고(probe_movie), ffmpeg 파이프로 읽어도
cv2와 같은 프레임이 같은 번호로 나올 파일인지 가른다(pipe_eligible). 순수 판정만 있고 파이프를 띄우지는 않는다.

게이트는 양성 증거로만 켜진다 — 한 조건이라도 확인하지 못하면(값이 없거나 맞지 않으면) 거짓이라 기존 cv2 경로로 간다.
probe_movie는 오류를 삼키지 않는다: ffprobe가 파일을 못 읽으면(RuntimeError)도, 결과 해석이 어긋나도(KeyError·ValueError·
TypeError…) 그대로 올라간다 — cv2로 돌릴지는 부른 쪽이 정한다.
"""

import math
import os
from dataclasses import dataclass
from fractions import Fraction

from yesoncheck.external_tools import MAX_FRAME_RATE, _frame_rate, _probe, _start_seconds, ffprobe_path

PIPE_CODECS = ("prores",)
SOURCE_MODE_ENV = "YESONCHECK_MOVIE_SOURCE"
SOURCE_MODES = ("pipe", "cv2")  # 환경 변수가 받는 값 (없으면 "auto")
UNSPECIFIED_SAR = (None, "1:1", "0:1")  # ffprobe의 sample_aspect_ratio: 없음·정사각형·미지정(0:1)


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
    """환경 변수 YESONCHECK_MOVIE_SOURCE: 없거나 비면 "auto", "pipe"·"cv2"(대소문자 무시)는 소문자로, 그 밖은 ValueError."""
    given = os.environ.get(SOURCE_MODE_ENV, "")
    mode = given.lower()
    if not mode:
        return "auto"
    if mode not in SOURCE_MODES:
        raise ValueError(f"{SOURCE_MODE_ENV}는 {' 또는 '.join(SOURCE_MODES)}이어야 합니다 (비우면 자동): {given!r}")
    return mode
