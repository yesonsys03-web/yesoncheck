# -*- coding: utf-8 -*-
"""슬라이더 호버 썸네일의 키프레임 거친 띠 — 키프레임 목록 읽기(ffprobe)·만들지의 판단·장수 줄이기·거친 띠 저장소. Qt 없음.

왜 (스펙 2026-11-11 §3): 긴 파일(500장 넘음 — 띠의 간격 step > 1)의 정확한 띠는 ffmpeg가 파일 전체를 디코드해야 해서 오래 걸린다 (22.6분 720p
H.264 애니매틱 32,553장: 스레드를 풀어도 18.8초). 키프레임만 디코드하면(-skip_frame nokey) 같은 파일이 10.2초에 558장 — 그래서 워커는 먼저
키프레임만의 거친 띠를 채워 호버에 보이고, 그 뒤 지금과 같은 정확한 띠로 덧씌운다(정확한 띠가 끝나면 거친 띠는 버림). '즉시'는 아니다 — 바닥은
파일 전체를 demux·파싱하는 약 10초.

언제 만드나 (coarse_wanted): 간격 > 1이고 키프레임이 전체의 1/KEYFRAME_RATIO(4) 이하일 때만 — all-intra(ProRes 등 모든 장이 키프레임)는
키프레임만 디코드해도 전부 디코드하는 꼴이라 건너뜀. 키프레임이 MAX_COARSE(1000)장을 넘으면 m = ceil(K / 1000)마다 하나만(subsample — 두
시간짜리도 1000장 ≤ 173MB·16:9): ffmpeg에는 select=not(mod(n,m))(n은 디코드된 장 — -skip_frame nokey 뒤라 키프레임만 셈)을 넣고 목록도 같은 규칙
frames[::m]으로 줄여, j번째 출력 = 목록의 j번째.

키프레임 번호 (scan_keyframes): ffprobe 한 번으로 영상 트랙(V:0 — attached_pic 제외)의 패킷 pts·플래그와 스트림의 시작·속도를 JSON으로 받아,
K 플래그 패킷의 pts를 프레임 번호 round((pts − start_time) × r)로 바꿔 정렬하고 [0, 패킷 수 − 1]로 자른다 (r은 r_frame_rate 분수 그대로,
start_time이 없으면 0). 정확도는 ±1장이면 충분하다(거친 띠의 어긋남이 GOP/2라서). 번호를 정할 수 없으면(영상 트랙 없음·속도를 모름·키프레임
패킷에 pts 없음) 지어내지 않고 RuntimeError — 부른 쪽은 거친 띠만 건너뛰고 기록한다(정확한 띠는 계속). FL106 실측: K 패킷 558개 =
-skip_frame nokey 출력 558장, 순서도 같음 — 그래도 수가 다르면 워커가 거친 띠를 버린다(번호를 믿을 수 없음).

프로세스: scan_keyframes는 run(명령) → (종료 코드, stdout 바이트, stderr 글)을 받는다 — 워커는 자기 프로세스 수명(정지·재개·stop의 kill)을 지키는
run을 넘기고, 기본은 셸 없는 subprocess.run(시험·도구용).

거친 띠 저장소 KeyframeStrip: hover_strip.ImageRows(띠 저장소와 같은 행 규칙 — 다 복사한 뒤 표시) + 정렬된 키프레임 번호 frames(생성 뒤 바뀌지
않는 튜플) + nearest(frame)(가장 가까운 키프레임 — 같은 거리면 앞쪽). 워커가 목록·표시 배열을 다 만든 뒤 속성 하나로 공개하고 GUI는 그 참조만
읽는다. 상수(MAX_COARSE·KEYFRAME_RATIO)는 부를 때마다 모듈 값으로 읽는다(시험의 monkeypatch가 닿게).
"""

import bisect
import json
import subprocess
from fractions import Fraction

from yesoncheck.external_tools import MAX_FRAME_RATE, decode_output, subprocess_kwargs
from yesoncheck.hover_strip import ImageRows

MAX_COARSE = 1000  # 거친 띠의 최대 장수 — 키프레임이 더 많으면 m장마다 하나 (subsample)
KEYFRAME_RATIO = 4  # 키프레임이 전체의 1/이 값 이하일 때만 거친 띠를 만듦 (coarse_wanted)
_PROBE_ENTRIES = "stream=start_time,r_frame_rate:packet=pts_time,flags"


def probe_command(ffprobe: str, path: str) -> list[str]:
    """키프레임 목록을 읽는 ffprobe 명령 (인자 리스트 그대로 — 셸 없음)."""
    return [ffprobe, "-v", "error", "-select_streams", "V:0", "-show_entries", _PROBE_ENTRIES, "-of", "json", path]


def _run(command: list[str]) -> tuple[int, bytes, str]:
    """기본 run — 셸 없이 끝날 때까지 (stdin 없음) → (종료 코드, stdout 바이트, stderr 글)."""
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            **subprocess_kwargs())
    return result.returncode, result.stdout, decode_output(result.stderr)


def _seconds(value) -> Fraction | None:
    """ffprobe 시각 글(초) → Fraction, 없거나 N/A면 None."""
    return None if value in (None, "N/A") else Fraction(value)


def keyframes_from_probe(info: dict) -> tuple[list[int], int]:
    """ffprobe JSON(probe_command의 출력) → (정렬한 키프레임 번호 — [0, 패킷 수 − 1]로 자름, 영상 패킷 수). 번호를 정할 수 없으면 RuntimeError."""
    streams = info.get("streams") or []
    if not streams:
        raise RuntimeError("영상 트랙이 없습니다 (ffprobe의 streams가 비었음)")
    stream = streams[0]
    text = stream.get("r_frame_rate") or ""
    rate = None if text.endswith("/0") or not text else Fraction(text)
    if rate is None or not 0 < rate <= MAX_FRAME_RATE:
        raise RuntimeError(f"프레임 속도를 알 수 없어 키프레임 번호를 정하지 못했습니다 (r_frame_rate {text or '없음'})")
    start = _seconds(stream.get("start_time")) or Fraction(0)
    packets = info.get("packets") or []
    last = len(packets) - 1
    frames = []
    for index, packet in enumerate(packets):
        if "K" not in packet.get("flags", ""):
            continue
        pts = _seconds(packet.get("pts_time"))
        if pts is None:  # 이 장을 빼면 ffmpeg 출력과 장수가 어긋남 — 지어내지 않음
            raise RuntimeError(f"키프레임 패킷에 pts가 없습니다 (영상 패킷 {index}번째 — {packet})")
        frames.append(min(max(round((pts - start) * rate), 0), last))
    return sorted(frames), len(packets)


def scan_keyframes(ffprobe: str, path: str, run=None) -> tuple[list[int], int]:
    """path의 (정렬한 키프레임 번호, 영상 패킷 수). run(명령) → (종료 코드, stdout 바이트, stderr 글) — 없으면 셸 없는 subprocess.run.
    ffprobe가 0이 아닌 코드로 끝나면 RuntimeError (파일·명령·종료 코드·stderr 전문), 번호를 정할 수 없어도 RuntimeError (keyframes_from_probe).
    JSON이 깨졌으면 json의 ValueError 그대로."""
    command = probe_command(ffprobe, path)
    returncode, out, err = (run or _run)(command)
    if returncode != 0:
        raise RuntimeError(f"ffprobe로 키프레임을 읽지 못했습니다 (종료 코드 {returncode}): {path}\n명령: {' '.join(command)}\n"
                           f"stderr:\n{err.rstrip() or '(없음)'}")
    return keyframes_from_probe(json.loads(decode_output(out)))


def coarse_wanted(total: int, step: int, keyframes: int | None = None) -> str | None:
    """거친 띠를 만들지 않는 이유 글, 만들면 None (모듈 설명). total: 전체 장수, step: 정확한 띠의 간격, keyframes: 키프레임 수 — 주지 않으면
    간격만 봄(스캔 전: 간격 1이면 스캔할 까닭도 없음)."""
    if step <= 1:
        return f"간격 1 — 정확한 띠가 프레임마다 (전체 {total}장)"
    if keyframes is None:
        return None
    if keyframes == 0:
        return "키프레임 없음"
    if keyframes * KEYFRAME_RATIO > total:
        return (f"키프레임 {keyframes}장 × {KEYFRAME_RATIO} > 전체 {total}장 — 키프레임만 디코드해도 거의 전부 디코드하는 꼴 "
                f"(all-intra 등)")
    return None


def subsample(frames: list[int], max_count: int) -> tuple[list[int], int]:
    """키프레임 목록을 max_count장 이하로 → (frames[::m], m), m = ceil(K / max_count) (1 이상). ffmpeg의 select=not(mod(n,m))와 같은 규칙."""
    every = max(1, -(-len(frames) // max_count))
    return frames[::every], every


class KeyframeStrip(ImageRows):
    """거친 띠 저장소 — 행 j = 키프레임 frames[j]의 그림 (모듈 설명). frames: 정렬한 원본 프레임 번호(비었거나 정렬이 아니면 ValueError —
    번호가 같은 것은 허용: 출력의 j번째와 짝이므로)."""

    ROW_NAME = "키프레임"

    def __init__(self, frames, width: int, height: int):
        frames = tuple(frames)
        if not frames or any(a > b for a, b in zip(frames, frames[1:])):
            raise ValueError(f"키프레임 번호는 비어 있지 않고 정렬돼 있어야 합니다: {frames[:10]}…({len(frames)}개)")
        super().__init__(len(frames), width, height)
        self.frames = frames

    def nearest(self, frame: int) -> int:
        """원본 프레임 frame(0-based)에 가장 가까운 키프레임의 행 번호 — 같은 거리면 앞쪽, 같은 번호가 여럿이면 그 첫 번째."""
        frames = self.frames
        i = bisect.bisect_left(frames, frame)  # frames[i]는 frame 이상인 첫 값 — 같은 번호들의 첫 번째
        if i == 0:
            return 0
        if i == len(frames) or frame - frames[i - 1] <= frames[i] - frame:
            return bisect.bisect_left(frames, frames[i - 1])  # 앞쪽 값의 첫 번째
        return i
