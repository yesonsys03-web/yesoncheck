"""yesoncheck/media_info.py: 미디어 정보 창의 글 — ffprobe JSON(스트림·형식)을 사람이 읽는 줄로.

코덱은 이름만이 아니라 프로파일·태그(`Apple ProRes 4444 (prores · ap4h)`), 픽셀 형식의 뜻(`yuv444p12le` → 4:4:4 · 12비트 · 알파),
색 공간·범위, 비트레이트, 인코더, 음성 트랙, 컨테이너·파일 크기까지. 창은 HTML(굵은 라벨)이라 예전처럼 `**`가 글자로 보이지 않음.
"""

import json
import os

import pytest
from PyQt5.QtCore import Qt

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import media_info

PRORES_4K = {  # 실파일 FL_106_A001_TK1_HD.mov의 ffprobe 그대로 (2026-11-03) — 음성 트랙 없음
    "streams": [{
        "index": 0, "codec_type": "video", "codec_name": "prores", "codec_long_name": "Apple ProRes (iCodec Pro)",
        "profile": "4444", "codec_tag_string": "ap4h", "pix_fmt": "yuv444p12le", "bits_per_raw_sample": "12",
        "color_range": "tv", "color_space": "bt709", "field_order": "progressive", "sample_aspect_ratio": "1:1",
        "bit_rate": "1054922730", "nb_frames": "334", "r_frame_rate": "24/1", "avg_frame_rate": "24/1",
        "width": 3840, "height": 2160, "time_base": "1/24000", "duration": "13.916667",
        "tags": {"creation_time": "2026-10-16T03:00:53.000000Z", "encoder": "Apple ProRes 4444", "vendor_id": "appl"},
    }],
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "format_long_name": "QuickTime / MOV", "duration": "13.916667",
               "size": "1835129465", "bit_rate": "1054924697", "tags": {"major_brand": "qt  "}},
}

H264_AAC = {
    "streams": [
        {"index": 0, "codec_type": "video", "codec_name": "h264", "codec_long_name": "H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10",
         "profile": "High", "codec_tag_string": "avc1", "pix_fmt": "yuv420p", "color_range": "tv", "color_space": "bt709",
         "color_primaries": "bt709", "color_transfer": "bt709", "field_order": "progressive", "width": 1920, "height": 1080,
         "sample_aspect_ratio": "1:1", "r_frame_rate": "24000/1001", "avg_frame_rate": "24000/1001", "nb_frames": "480",
         "bit_rate": "8000000", "duration": "20.020000", "tags": {"encoder": "Lavc60"}},
        {"index": 1, "codec_type": "audio", "codec_name": "aac", "codec_long_name": "AAC (Advanced Audio Coding)", "profile": "LC",
         "codec_tag_string": "mp4a", "sample_rate": "48000", "channels": 2, "channel_layout": "stereo", "bit_rate": "128000"},
    ],
    "format": {"format_long_name": "QuickTime / MOV", "duration": "20.020000", "size": "20345678", "bit_rate": "8128000"},
}


def rows_dict(rows):
    return dict(rows)


def test_prores_rows_show_profile_tag_pixel_format_and_colour():
    rows = rows_dict(media_info.describe(PRORES_4K, "/x/FL_106_A001_TK1_HD.mov"))
    assert rows["코덱"] == "Apple ProRes 4444 (prores · ap4h) — Apple ProRes (iCodec Pro)"
    assert rows["픽셀 형식"] == "yuv444p12le (4:4:4 · 12비트 · 알파 없음)"
    assert rows["색"] == "bt709, 범위 tv (limited)"
    assert rows["해상도"] == "3840 × 2160"
    assert rows["프레임 속도"] == "24 fps"
    assert rows["프레임"] == "334"
    assert rows["길이"] == "00:00:13.917"
    assert rows["비트레이트"] == "1,055 Mb/s"
    assert rows["주사"] == "progressive"
    assert rows["인코더"] == "Apple ProRes 4444"
    assert rows["음성"] == "없음"
    assert rows["컨테이너"] == "QuickTime / MOV"
    assert rows["파일 크기"] == "1.84 GB (1,835,129,465 바이트)"
    assert rows["만든 때"] == "2026-10-16T03:00:53Z"
    assert rows["파일 경로"] == "/x/FL_106_A001_TK1_HD.mov"
    assert list(rows)[0] == "파일"  # 맨 위는 파일 이름


def test_bit_rate_from_the_container_is_labelled():
    info = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 10, "height": 10}],
            "format": {"bit_rate": "759000", "duration": "3.0"}}
    rows = rows_dict(media_info.describe(info, "/x/a.mkv"))
    assert rows["비트레이트"] == "759 kb/s (컨테이너 전체 — 음성 포함)"
    assert rows["길이"] == "00:00:03.000"


def test_codec_tag_is_trimmed_and_skipped_when_it_repeats_the_name():
    rows = rows_dict(media_info.describe({"streams": [{"codec_type": "video", "codec_name": "png", "codec_long_name": "PNG (Portable Network Graphics) image",
                                                     "codec_tag_string": "png ", "width": 1, "height": 1}], "format": {}}, "/x/a.mov"))
    assert rows["코덱"] == "PNG (png) — PNG (Portable Network Graphics) image"
    rows = rows_dict(media_info.describe({"streams": [{"codec_type": "video", "codec_name": "h264", "codec_tag_string": "H264", "width": 1, "height": 1}], "format": {}}, "/x/a.avi"))
    assert rows["코덱"] == "H.264 (h264)"


def test_variable_frame_rate_shows_the_average():
    info = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1, "height": 1, "r_frame_rate": "90000/1", "avg_frame_rate": "24000/1001"}], "format": {}}
    assert rows_dict(media_info.describe(info, "/x/a.mp4"))["프레임 속도"] == "23.976 fps (평균 — 가변 프레임 속도, r 90000/1)"


def test_h264_rows_include_audio_and_fractional_fps():
    rows = rows_dict(media_info.describe(H264_AAC, "/x/a.mov"))
    assert rows["코덱"] == "H.264 High (h264 · avc1) — H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10"
    assert rows["픽셀 형식"] == "yuv420p (4:2:0 · 8비트 · 알파 없음)"
    assert rows["색"] == "bt709 / 원색 bt709 / 전달 bt709, 범위 tv (limited)"
    assert rows["프레임 속도"] == "23.976 fps (24000/1001)"
    assert rows["비트레이트"] == "8.0 Mb/s"
    assert rows["음성"] == "AAC LC (aac · mp4a) — 48000 Hz, 2채널 (stereo), 128 kb/s"
    assert rows["파일 크기"] == "20.3 MB (20,345,678 바이트)"
    assert "만든 때" not in rows  # 태그 없음 — 줄 자체가 없음


@pytest.mark.parametrize("pix_fmt, text", [
    ("yuv444p12le", "yuv444p12le (4:4:4 · 12비트 · 알파 없음)"),
    ("yuva444p12le", "yuva444p12le (4:4:4 · 12비트 · 알파 있음)"),
    ("yuv422p10le", "yuv422p10le (4:2:2 · 10비트 · 알파 없음)"),
    ("yuv420p", "yuv420p (4:2:0 · 8비트 · 알파 없음)"),
    ("rgb24", "rgb24 (RGB · 8비트 · 알파 없음)"),
    ("rgba", "rgba (RGB · 8비트 · 알파 있음)"),
    ("gbrap12le", "gbrap12le (RGB · 12비트 · 알파 있음)"),
    ("gray", "gray (흑백 · 8비트 · 알파 없음)"),
    ("gray16le", "gray16le (흑백 · 16비트 · 알파 없음)"),
    ("rgb48le", "rgb48le (RGB · 16비트 · 알파 없음)"),
    ("rgba64le", "rgba64le (RGB · 16비트 · 알파 있음)"),
    ("rgb0", "rgb0 (RGB · 8비트 · 알파 없음)"),  # 끝 0은 채움 바이트 (Hap·화면 캡처)
    ("bgr0", "bgr0 (RGB · 8비트 · 알파 없음)"),
    ("rgb555le", "rgb555le"),  # 묶음 16비트 — 채널당 비트가 고르지 않아 이름만 (185비트로 보였던 것)
    ("rgb565be", "rgb565be"),
    ("rgb8", "rgb8"),
    ("rgbaf32le", "rgbaf32le"),  # 실수 형식은 이름만
    ("pal8", "pal8"),  # 모르는 모양은 이름만
    ("", "알 수 없음"),
    (None, "알 수 없음"),
])
def test_pixel_format_text(pix_fmt, text):
    assert media_info.pixel_format_text(pix_fmt) == text


def test_missing_values_are_shown_as_unknown_not_dropped():
    info = {"streams": [{"codec_type": "video", "codec_name": "foo", "width": 10, "height": 10}], "format": {}}
    rows = rows_dict(media_info.describe(info, "/x/f.mov"))
    assert rows["코덱"] == "foo"
    assert rows["픽셀 형식"] == "알 수 없음"
    assert rows["프레임 속도"] == "알 수 없음"
    assert rows["프레임"] == "알 수 없음"  # MKV·WebM·TS는 nb_frames가 없음 — "None"이 보였던 것
    assert rows["길이"] == "알 수 없음"
    assert rows["비트레이트"] == "알 수 없음"
    assert rows["컨테이너"] == "알 수 없음"


def test_no_video_track_is_an_error():
    with pytest.raises(ValueError, match="영상 트랙"):
        media_info.describe({"streams": [{"codec_type": "audio", "codec_name": "aac"}], "format": {}}, "/x/a.m4a")


def test_attached_picture_is_not_the_video_track():
    cover = {"codec_type": "video", "codec_name": "mjpeg", "width": 300, "height": 300, "disposition": {"attached_pic": 1}}
    video = dict(PRORES_4K["streams"][0])
    rows = rows_dict(media_info.describe({"streams": [cover, video], "format": PRORES_4K["format"]}, "/x/a.mov"))
    assert rows["해상도"] == "3840 × 2160"


def test_format_html_uses_bold_labels_and_escapes():
    html = media_info.format_html([("파일", "a<b>.mov"), ("코덱", "x & y")])
    assert html == "<b>파일:</b> a&lt;b&gt;.mov<br><b>코덱:</b> x &amp; y"
    assert "**" not in html


def test_media_info_html_reads_the_file_with_ffprobe(tmp_path):
    path = write_test_video(str(tmp_path / "clip.mov"))
    html, details = media_info.media_info_html(path)
    assert "<b>코덱:</b> MPEG-4 part 2 Simple Profile (mpeg4 · mp4v)" in html
    assert "<b>해상도:</b> 320 × 240" in html and "<b>프레임:</b> 24" in html
    assert "yuv420p (4:2:0 · 8비트 · 알파 없음)" in html
    assert json.loads(details)["streams"][0]["codec_name"] == "mpeg4"  # 자세히 = ffprobe 원본 JSON


def test_media_info_html_raises_on_unreadable_file(tmp_path):
    bad = tmp_path / "bad.mov"
    bad.write_bytes(b"not a movie")
    with pytest.raises(RuntimeError, match="ffprobe"):
        media_info.media_info_html(str(bad))


def test_dialog_shows_rich_text_without_markdown_stars(new_player, dialogs, tmp_path):
    player = new_player(make_config(str(tmp_path), {}))
    path = write_test_video(str(tmp_path / "clip.mov"))
    player.add_files_to_sidebar([path])
    assert player.sidebar.count() == 1
    player.show_video_info(player.sidebar.model().index(0, 0))
    [(kind, title, text)] = [m for m in dialogs.messages if m[1] == "미디어 정보"]
    assert "**" not in text
    assert "<b>코덱:</b> MPEG-4 part 2 Simple Profile (mpeg4 · mp4v)" in text
    assert "<b>파일 경로:</b> " + path in text
    assert '"codec_name": "mpeg4"' in text  # 자세히(ffprobe JSON)까지 기록됨


def test_dialog_reports_probe_failure_plainly(new_player, dialogs, tmp_path, capsys):
    """깨진 파일: 창은 평문(경로의 & 같은 글자를 이스케이프하지 않고 그대로 — 본문에 종류·사유, 자세히에 트레이스백), 기록에 `[미디어 정보] 실패` 줄 + 트레이스백.
    (파일 이름에 <를 쓰면 Windows에서 파일을 만들 수 없음 — Windows CI에서 잡힘.)"""
    player = new_player(make_config(str(tmp_path), {}))
    bad = tmp_path / "bad&b.mov"
    bad.write_bytes(b"not a movie")
    player.add_files_to_sidebar([str(bad)])
    assert player.sidebar.count() == 1
    capsys.readouterr()
    player.show_video_info(player.sidebar.model().index(0, 0))
    [(kind, title, text)] = [m for m in dialogs.messages if m[1] == "미디어 정보"]
    assert kind == "warning"
    assert text.startswith("미디어 정보를 가져오는 데 실패했습니다 (RuntimeError)") and "ffprobe" in text and "bad&b.mov" in text
    assert "Traceback" in text  # 자세히
    err = capsys.readouterr().err
    assert "[미디어 정보] 실패:" in err and "Traceback" in err
