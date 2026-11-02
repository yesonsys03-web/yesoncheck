"""미디어 정보 창의 글 (Qt 없음): ffprobe JSON(스트림·형식)을 사람이 읽는 (라벨, 값) 줄로 — 사이드바 우클릭 → 미디어 정보.

예전 창은 cv2로 해상도·프레임만 읽고 코덱은 ffprobe의 `codec_name`(`prores`)만 보여 줬음. 이제 ffprobe 한 번(`-show_streams -show_format`)으로
코덱의 프로파일·태그(`Apple ProRes 4444 (prores · ap4h)`), 픽셀 형식의 뜻(`yuv444p12le` → 4:4:4 · 12비트 · 알파), 색 공간·범위, 해상도(화소 비율),
프레임 속도(분수까지, 가변이면 평균), 프레임 수, 길이(영상 트랙 길이, 없으면 컨테이너 — 예전 창은 cv2로 마지막 프레임 시각 `(n−1)/fps`를 보여 줬음),
비트레이트(영상 트랙, 없으면 컨테이너 전체라고 적음), 주사, 인코더, 음성 트랙(첫 트랙), 컨테이너, 파일 크기, 만든 때, 경로. 없는 값은 "알 수 없음"(있을 때만 적는 줄:
주사·인코더·만든 때). 창은 `format_html`의 HTML(굵은 라벨)이고 '자세히'에는 ffprobe JSON 원본. 읽지 못하면 예외 그대로(깨진 파일·ffprobe 실패는 RuntimeError,
ffprobe 없음은 ToolNotFoundError, 영상 트랙 없음은 ValueError, JSON 오류는 json의 것) — 창이 그 사유를 평문으로 보임.
"""

import html
import json
import os
import re
from fractions import Fraction

from yesoncheck import external_tools

UNKNOWN = "알 수 없음"

# 코덱 이름 → 사람이 부르는 이름 (없으면 ffprobe의 codec_long_name, 그것도 없으면 codec_name)
FRIENDLY = {
    "prores": "Apple ProRes", "h264": "H.264", "hevc": "H.265/HEVC", "mpeg4": "MPEG-4 part 2", "mpeg2video": "MPEG-2",
    "dnxhd": "DNxHD/HR", "mjpeg": "Motion JPEG", "vp9": "VP9", "av1": "AV1", "png": "PNG", "qtrle": "QuickTime Animation",
    "aac": "AAC", "mp3": "MP3", "pcm_s16le": "PCM 16비트", "pcm_s24le": "PCM 24비트", "pcm_s32le": "PCM 32비트", "alac": "Apple Lossless",
}
_RANGES = {"tv": "tv (limited)", "pc": "pc (full)"}
_PIX_RE = re.compile(r"^(?P<fam>yuva|yuvj|yuv|gbrap|gbrp|rgba|rgb|bgra|bgr|graya|gray|ya)(?P<rest>.*)$")
_SUBSAMPLING = {"444": "4:4:4", "422": "4:2:2", "420": "4:2:0", "411": "4:1:1", "410": "4:1:0", "440": "4:4:0"}


def media_info_html(path):
    """path를 ffprobe로 읽어 (창에 보일 HTML, '자세히'에 넣을 ffprobe JSON 글). 읽지 못하면 RuntimeError·ToolNotFoundError 그대로."""
    info = external_tools.probe_json(path)
    return format_html(describe(info, path)), json.dumps(info, ensure_ascii=False, indent=2)


def describe(info, path):
    """ffprobe JSON → [(라벨, 값)] (창에 보이는 순서). 영상 트랙(attached_pic 제외)이 없으면 ValueError."""
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
    if video is None:
        raise ValueError(f"영상 트랙이 없습니다: {path}")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = info.get("format") or {}
    tags = video.get("tags") or {}
    rows = [
        ("파일", os.path.basename(path)),
        ("코덱", codec_label(video, with_long=True)),
        ("픽셀 형식", pixel_format_text(video.get("pix_fmt"))),
        ("색", colour_text(video)),
        ("해상도", resolution_text(video)),
        ("프레임 속도", frame_rate_text(video)),
        ("프레임", _present(video.get("nb_frames")) or UNKNOWN),  # MKV·WebM·TS는 없음
        ("길이", duration_text(_present(video.get("duration")) or _present(fmt.get("duration")))),
        ("비트레이트", bit_rate_text(_present(video.get("bit_rate"))) if _present(video.get("bit_rate"))
         else (bit_rate_text(fmt.get("bit_rate")) + " (컨테이너 전체 — 음성 포함)" if _present(fmt.get("bit_rate")) else UNKNOWN)),
    ]
    if _present(video.get("field_order")):
        rows.append(("주사", video["field_order"]))
    if _present(tags.get("encoder")):
        rows.append(("인코더", tags["encoder"]))
    rows += [
        ("음성", audio_text(audio)),
        ("컨테이너", _present(fmt.get("format_long_name")) or UNKNOWN),
        ("파일 크기", size_text(_present(fmt.get("size")))),
    ]
    created = _present(tags.get("creation_time")) or _present((fmt.get("tags") or {}).get("creation_time"))
    if created:
        rows.append(("만든 때", re.sub(r"\.\d+", "", created)))
    rows.append(("파일 경로", path))
    return rows


def codec_label(stream, with_long):
    """`Apple ProRes 4444 (prores · ap4h) — Apple ProRes (iCodec Pro)`: 부르는 이름 + 프로파일 + (codec_name · 태그) + (with_long이면) 긴 이름."""
    name = _present(stream.get("codec_name")) or UNKNOWN
    long_name = _present(stream.get("codec_long_name"))
    head = FRIENDLY.get(name) or long_name or name
    label = head
    profile = _present(stream.get("profile"))
    if profile and profile.lower() != "unknown":
        label += f" {profile}"
    ids = [name] if head != name else []
    tag = (_present(stream.get("codec_tag_string")) or "").strip()
    if tag and "[" not in tag and tag.lower() != name.lower():
        ids.append(tag)
    if ids:
        label += f" ({' · '.join(ids)})"
    if with_long and long_name and long_name != head:
        label += f" — {long_name}"
    return label


def pixel_format_text(pix_fmt):
    """`yuv444p12le` → `yuv444p12le (4:4:4 · 12비트 · 알파 없음)`. 모르는 모양은 이름만, 없으면 "알 수 없음"."""
    if not pix_fmt:
        return UNKNOWN
    m = _PIX_RE.match(pix_fmt)
    if not m:
        return pix_fmt
    fam, rest = m.group("fam"), m.group("rest")
    alpha = fam in ("yuva", "gbrap", "rgba", "bgra", "graya", "ya")
    if fam.startswith("yuv"):
        kind = _SUBSAMPLING.get(rest[:3])
        if kind is None:
            return pix_fmt
        digits = re.search(r"(\d+)", rest[3:])
        bits = int(digits.group(1)) if digits else 8
    elif fam.startswith("gray") or fam == "ya":
        kind = "흑백"
        digits = re.search(r"(\d+)", rest)
        bits = int(digits.group(1)) if digits else 8
    elif fam.startswith("gbr"):  # 평면 RGB — 숫자는 채널당 비트 (실수 f32 등은 이름만)
        kind = "RGB"
        m2 = re.fullmatch(r"(\d+)?(le|be)?", rest)
        if m2 is None:
            return pix_fmt
        bits = int(m2.group(1)) if m2.group(1) else 8
    else:  # 묶음 RGB(rgb24·rgba64le) — 숫자는 화소 전체 비트. rgb0·bgr0은 8비트 + 채움 바이트, 채널 비트가 고르지 않은 rgb555·rgb565·rgb8과 실수 형식은 이름만
        kind = "RGB"
        if rest == "0":
            return f"{pix_fmt} (RGB · 8비트 · 알파 없음)"
        m2 = re.fullmatch(r"(\d+)?(le|be)?", rest)
        if m2 is None:
            return pix_fmt
        channels = 4 if alpha else 3
        total = int(m2.group(1)) if m2.group(1) else 8 * channels
        if total not in {8 * channels, 16 * channels}:
            return pix_fmt
        bits = total // channels
    return f"{pix_fmt} ({kind} · {bits}비트 · 알파 {'있음' if alpha else '없음'})"


def colour_text(stream):
    parts = []
    space = _present(stream.get("color_space"))
    if space and space != "unknown":
        parts.append(space)
    primaries = _present(stream.get("color_primaries"))
    if primaries and primaries != "unknown":
        parts.append(f"원색 {primaries}")
    transfer = _present(stream.get("color_transfer"))
    if transfer and transfer != "unknown":
        parts.append(f"전달 {transfer}")
    text = " / ".join(parts)
    rng = _present(stream.get("color_range"))
    if rng and rng != "unknown":
        text = (text + ", " if text else "") + f"범위 {_RANGES.get(rng, rng)}"
    return text or UNKNOWN


def resolution_text(stream):
    width, height = stream.get("width"), stream.get("height")
    if not width or not height:
        return UNKNOWN
    text = f"{width} × {height}"
    sar = _present(stream.get("sample_aspect_ratio"))
    if sar and sar not in ("1:1", "0:1"):
        text += f" (화소 비율 {sar})"
    return text


def frame_rate_text(stream):
    r = _fraction(stream.get("r_frame_rate"))
    avg = _fraction(stream.get("avg_frame_rate"))
    if r is None:
        return UNKNOWN
    if r > external_tools.MAX_FRAME_RATE and avg is not None:  # 가변 프레임 속도 — r은 타임베이스(90000 등)
        return f"{float(avg):.3f} fps (평균 — 가변 프레임 속도, r {r.numerator}/{r.denominator})"
    text = f"{r.numerator} fps" if r.denominator == 1 else f"{float(r):.3f} fps ({r.numerator}/{r.denominator})"
    if avg is not None and avg != r:
        text += f", 평균 {float(avg):.3f}"
    return text


def duration_text(seconds_text):
    if not seconds_text:
        return UNKNOWN
    total_ms = int(round(float(seconds_text) * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"


def bit_rate_text(bps_text):
    if not bps_text:
        return UNKNOWN
    bps = int(bps_text)
    if bps >= 100_000_000:
        return f"{bps / 1_000_000:,.0f} Mb/s"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f} Mb/s"
    return f"{bps / 1000:.0f} kb/s"


def audio_text(stream):
    if stream is None:
        return "없음"
    parts = []
    rate = _present(stream.get("sample_rate"))
    if rate:
        parts.append(f"{rate} Hz")
    channels = stream.get("channels")
    if channels:
        layout = _present(stream.get("channel_layout"))
        parts.append(f"{channels}채널" + (f" ({layout})" if layout else ""))
    bit_rate = _present(stream.get("bit_rate"))
    if bit_rate:
        parts.append(f"{int(bit_rate) / 1000:.0f} kb/s")
    label = codec_label(stream, with_long=False)
    return label + (f" — {', '.join(parts)}" if parts else "")


def size_text(size_text_):
    if not size_text_:
        return UNKNOWN
    size = int(size_text_)
    human = f"{size / 1e9:.2f} GB" if size >= 1e9 else f"{size / 1e6:.1f} MB" if size >= 1e6 else f"{size / 1e3:.0f} kB"
    return f"{human} ({size:,} 바이트)"


def format_html(rows):
    """(라벨, 값) 줄 → `<b>라벨:</b> 값<br>…` (값은 HTML 이스케이프)."""
    return "<br>".join(f"<b>{html.escape(label)}:</b> {html.escape(str(value))}" for label, value in rows)


def _present(value):
    """ffprobe 값: 없음·"N/A"·빈 글은 None."""
    return None if value in (None, "N/A", "") else value


def _fraction(text):
    text = _present(text)
    if not text:
        return None
    try:
        value = Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None
