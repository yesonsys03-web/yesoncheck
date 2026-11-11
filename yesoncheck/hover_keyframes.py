# -*- coding: utf-8 -*-
"""슬라이더 호버 썸네일의 키프레임 거친 띠 — 헤더 읽기·키프레임 목록 읽기(ffprobe)·만들지의 판단·장수 줄이기·거친 띠 저장소. Qt 없음.

왜 (스펙 2026-11-11 §3): 긴 파일(500장 넘음 — 띠의 간격 step > 1)의 정확한 띠는 ffmpeg가 파일 전체를 디코드해야 해서 오래 걸린다 (22.6분 720p
H.264 애니매틱 32,553장: 스레드를 풀어도 18.8초). 키프레임만 디코드하면(-skip_frame nokey) 같은 파일이 10.2초에 558장 — 그래서 워커는 먼저
키프레임만의 거친 띠를 채워 호버에 보이고, 그 뒤 지금과 같은 정확한 띠로 덧씌운다(정확한 띠가 끝나면 거친 띠는 버림). '즉시'는 아니다 — 바닥은
파일 전체를 demux·파싱하는 약 10초.

읽는 차례 (워커가 부름): ① 헤더(probe_header — 영상 트랙 V:0의 코덱·속도·시작만, 패킷 없음이라 파일을 다 읽지 않음) → header_skip_reason이 사유를
주면 패킷 스캔 없이 건너뜀: all-intra 코덱(ALL_INTRA_CODECS — 모든 장이 키프레임이라 키프레임만 디코드해도 전부 디코드하는 꼴; 예전에는 패킷
스캔이 파일 전체를 읽은 뒤에야 알았음)·속도를 모르거나 MAX_FRAME_RATE(240)를 넘음(VFR의 90000/1 — 번호를 정할 수 없음) ② 키프레임 목록
(scan_keyframes — 패킷 pts·플래그; 파일 전체를 읽음) → coarse_wanted(간격 > 1이고 키프레임이 전체의 1/KEYFRAME_RATIO(4) 이하일 때만).

키프레임 번호: K 플래그 패킷의 pts를 프레임 번호 round((pts − start_time) × r)로 바꿔 정렬하고 [0, 버리지 않는 패킷 수 − 1]로 자른다(r·start_time은
헤더 — r은 분수 그대로, start_time이 없으면 0). 정확도는 ±1장이면 충분하다(거친 띠의 어긋남이 GOP/2라서). 둘째 플래그가 D(버림 — 편집 목록으로 앞이
잘린 mp4의 'KD_')인 패킷은 뺀다: -skip_frame nokey가 그 장을 내지 않으므로(리뷰 실측: K 10개 중 KD_ 1 → 출력 9장). 키프레임 패킷에 pts가 없으면
지어내지 않고 RuntimeError — 부른 쪽은 거친 띠만 건너뛰고 기록한다(정확한 띠는 계속). FL106 실측: K 패킷 558개 = -skip_frame nokey 출력 558장,
순서도 같음 — 그래도 수가 다르면 워커가 거친 띠를 버린다(번호를 믿을 수 없음).

장수 줄이기 (subsample): 키프레임이 MAX_COARSE(1000)장을 넘으면 m = ceil(K / 1000)마다 하나만 — 목록은 frames[::m]. 워커는 ffmpeg에 select를
넣지 않고 키프레임 전부를 받아 i번째 장 중 i % m == 0만 넣는다(스펙 §3.2의 select와 다름 — 디코드 비용은 같고 파이프 전송만 K장; 장수 검사가 받은
수 == K로 정확해짐).

프로세스: probe_header·scan_keyframes는 run(명령) → (종료 코드, stdout 바이트, stderr 글)을 받는다 — 워커는 자기 프로세스 수명(정지·재개·stop의
kill)을 지키는 run을 넘기고, 기본은 셸 없는 subprocess.run(시험·도구용).

거친 띠 저장소 KeyframeStrip: hover_strip.ImageRows(띠 저장소와 같은 행 규칙 — 다 복사한 뒤 표시) + 정렬된 키프레임 번호 frames(생성 뒤 바뀌지
않는 튜플) + nearest(frame)(가장 가까운 키프레임 — 같은 거리면 앞쪽). 워커가 목록·표시 배열을 다 만든 뒤 속성 하나로 공개하고 GUI는 그 참조만
읽는다. 상수(MAX_COARSE·KEYFRAME_RATIO)는 부를 때마다 모듈 값으로 읽는다(시험의 monkeypatch가 닿게).
"""

import bisect
import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction

from yesoncheck.external_tools import MAX_FRAME_RATE, decode_output, subprocess_kwargs
from yesoncheck.hover_strip import ALL_INTRA_CODECS, ImageRows  # ALL_INTRA_CODECS — 스레드 규칙(hover_strip.thread_limits)과 같은 상수 하나

MAX_COARSE = 1000  # 거친 띠의 최대 장수 — 키프레임이 더 많으면 m장마다 하나 (subsample)
KEYFRAME_RATIO = 4  # 키프레임이 전체의 1/이 값 이하일 때만 거친 띠를 만듦 (coarse_wanted)
_HEADER_ENTRIES = "stream=codec_name,r_frame_rate,start_time"
_PACKET_ENTRIES = "packet=pts_time,flags"


@dataclass(frozen=True)
class StreamHeader:
    """영상 트랙의 헤더. codec: codec_name(없으면 ""), rate_text: r_frame_rate 글 그대로, rate: 0 < r ≤ MAX_FRAME_RATE일 때의 분수(아니면 None),
    start: start_time(없으면 0)."""
    codec: str
    rate_text: str
    rate: Fraction | None
    start: Fraction


def header_command(ffprobe: str, path: str) -> list[str]:
    """헤더만 읽는 ffprobe 명령 (패킷 없음 — 파일을 다 읽지 않음; 인자 리스트 그대로 — 셸 없음)."""
    return [ffprobe, "-v", "error", "-select_streams", "V:0", "-show_entries", _HEADER_ENTRIES, "-of", "json", path]


def packets_command(ffprobe: str, path: str) -> list[str]:
    """키프레임 목록을 읽는 ffprobe 명령 — 영상 트랙의 패킷 pts·플래그 (파일 전체를 읽음)."""
    return [ffprobe, "-v", "error", "-select_streams", "V:0", "-show_entries", _PACKET_ENTRIES, "-of", "json", path]


def _run(command: list[str]) -> tuple[int, bytes, str]:
    """기본 run — 셸 없이 끝날 때까지 (stdin 없음) → (종료 코드, stdout 바이트, stderr 글)."""
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            **subprocess_kwargs())
    return result.returncode, result.stdout, decode_output(result.stderr)


def _probe(command: list[str], path: str, what: str, run) -> dict:
    """ffprobe를 run으로 돌려 JSON → dict. 0이 아닌 코드는 RuntimeError(파일·명령·종료 코드·stderr 전문), 깨진 JSON은 json의 ValueError 그대로."""
    returncode, out, err = (run or _run)(command)
    if returncode != 0:
        raise RuntimeError(f"ffprobe로 {what}을 읽지 못했습니다 (종료 코드 {returncode}): {path}\n명령: {' '.join(command)}\n"
                           f"stderr:\n{err.rstrip() or '(없음)'}")
    return json.loads(decode_output(out))


def _seconds(value) -> Fraction | None:
    """ffprobe 시각 글(초) → Fraction, 없거나 N/A면 None."""
    return None if value in (None, "N/A") else Fraction(value)


def header_from_probe(info: dict) -> StreamHeader:
    """헤더 ffprobe JSON → StreamHeader. 영상 트랙이 없으면 RuntimeError."""
    streams = info.get("streams") or []
    if not streams:
        raise RuntimeError("영상 트랙이 없습니다 (ffprobe의 streams가 비었음)")
    stream = streams[0]
    text = stream.get("r_frame_rate") or ""
    rate = None if not text or text.endswith("/0") else Fraction(text)
    if rate is not None and not 0 < rate <= MAX_FRAME_RATE:
        rate = None
    return StreamHeader(codec=stream.get("codec_name") or "", rate_text=text, rate=rate,
                        start=_seconds(stream.get("start_time")) or Fraction(0))


def probe_header(ffprobe: str, path: str, run=None) -> StreamHeader:
    """path의 헤더 (header_command 한 번 — 파일을 다 읽지 않음). 실패는 _probe의 RuntimeError·ValueError, 영상 트랙 없음도 RuntimeError."""
    return header_from_probe(_probe(header_command(ffprobe, path), path, "헤더", run))


def header_skip_reason(header: StreamHeader) -> str | None:
    """헤더만으로 거친 띠를 건너뛸 사유 글 (실패가 아님 — 기록 한 줄 뒤 정확한 띠만), 없으면 None (모듈 설명)."""
    if header.codec in ALL_INTRA_CODECS:
        return f"all-intra 코덱 {header.codec} — 모든 장이 키프레임이라 키프레임만 디코드해도 전부 디코드하는 꼴"
    if header.rate is None:
        return (f"가변 프레임 레이트이거나 속도를 알 수 없음 (r_frame_rate {header.rate_text or '없음'}) — 키프레임 번호를 정할 수 없음")
    return None


def keyframes_from_packets(info: dict, header: StreamHeader) -> tuple[list[int], int]:
    """패킷 ffprobe JSON → (정렬한 키프레임 번호 — [0, 버리지 않는 패킷 수 − 1]로 자름, 버리지 않는 영상 패킷 수). 버림(D) 패킷은 뺌.
    키프레임 패킷에 pts가 없으면 RuntimeError, 헤더의 속도가 없으면(header_skip_reason을 보지 않은 부른 쪽의 버그) ValueError."""
    if header.rate is None:
        raise ValueError(f"속도를 모르는 헤더로는 키프레임 번호를 정할 수 없습니다 (r_frame_rate {header.rate_text or '없음'})")
    kept = [packet for packet in info.get("packets") or [] if packet.get("flags", "")[1:2] != "D"]
    last = len(kept) - 1
    frames = []
    for index, packet in enumerate(kept):
        if "K" not in packet.get("flags", ""):
            continue
        pts = _seconds(packet.get("pts_time"))
        if pts is None:  # 이 장을 빼면 ffmpeg 출력과 장수가 어긋남 — 지어내지 않음
            raise RuntimeError(f"키프레임 패킷에 pts가 없습니다 (버리지 않는 영상 패킷 {index}번째 — {packet})")
        frames.append(min(max(round((pts - header.start) * header.rate), 0), last))
    return sorted(frames), len(kept)


def scan_keyframes(ffprobe: str, path: str, header: StreamHeader, run=None) -> tuple[list[int], int]:
    """path의 (정렬한 키프레임 번호, 버리지 않는 영상 패킷 수) — packets_command 한 번(파일 전체를 읽음), 번호는 header의 속도·시작으로.
    실패는 _probe의 RuntimeError·ValueError, 번호를 정할 수 없으면 keyframes_from_packets의 RuntimeError."""
    return keyframes_from_packets(_probe(packets_command(ffprobe, path), path, "키프레임", run), header)


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
        return f"키프레임 {keyframes}장 × {KEYFRAME_RATIO} > 전체 {total}장 — 키프레임만 디코드해도 거의 전부 디코드하는 꼴"
    return None


def subsample(frames: list[int], max_count: int) -> tuple[list[int], int]:
    """키프레임 목록을 max_count장 이하로 → (frames[::m], m), m = ceil(K / max_count) (1 이상). 워커가 받은 i번째 장 중 i % m == 0만 넣는 규칙과 짝."""
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
