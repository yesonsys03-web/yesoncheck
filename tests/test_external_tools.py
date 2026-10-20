import itertools
import json
import os
import re
import subprocess
import sys
from fractions import Fraction
from types import SimpleNamespace

import pytest

from yesoncheck import external_tools, file_names


def make_media(path, seconds=1, size="320x240", rate=24, audio=True, audio_first=False, pix_fmt="yuv420p",
               audio_seconds=None):
    """lavfi로 시험 영상: H.264 + (PCM 스테레오 22050 Hz 사인파) + 타임코드 트랙. audio_first: 소리가 0번, 영상이 1번 트랙.
    audio_seconds: 소리 길이 (기본은 영상과 같게)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cmd = [external_tools.ffmpeg_path(), "-y", "-v", "error",
           "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={size}:rate={rate}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=duration={audio_seconds or seconds}:sample_rate=22050",
                "-map", "1:a" if audio_first else "0:v", "-map", "0:v" if audio_first else "1:a",
                "-c:a", "pcm_s16be", "-ac", "2"]
    cmd += ["-c:v", "libx264", "-pix_fmt", pix_fmt, "-timecode", "00:00:00:00", path]
    subprocess.run(cmd, check=True, **external_tools.subprocess_kwargs())
    return path


def ffmpeg(*args):
    """시험 미디어 만들기 (ffmpeg -y -v error …)."""
    subprocess.run([external_tools.ffmpeg_path(), "-y", "-v", "error", *args], check=True,
                   **external_tools.subprocess_kwargs())


def make_tone(path, seconds=1):
    """소리만 있는 파일 (PCM 스테레오 22050 Hz 사인파)."""
    ffmpeg("-f", "lavfi", "-i", f"sine=duration={seconds}:sample_rate=22050", "-c:a", "pcm_s16be", "-ac", "2", path)
    return path


def make_flat_cut(path, gray, frames, audio=False):
    """한 가지 회색(gray 0~255)의 24 fps 컷 frames프레임, audio면 그 길이의 사인파 소리도."""
    cmd = ["-f", "lavfi", "-i", f"color=c=0x{gray:02x}{gray:02x}{gray:02x}:size=320x240:rate=24"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=duration={frames / 24:.6f}:sample_rate=22050",
                "-c:a", "pcm_s16be", "-ac", "2"]
    ffmpeg(*cmd, "-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p", path)
    return path


def video_audio(path):
    """첫 영상·첫 소리 트랙 (ffprobe, 프레임은 디코딩해 셈 — nb_read_frames). 없으면 None."""
    result = subprocess.run(
        [external_tools.ffprobe_path(), "-v", "error", "-count_frames", "-show_streams", "-of", "json", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **external_tools.subprocess_kwargs())
    streams = json.loads(external_tools.decode_output(result.stdout))["streams"]
    video = next((s for s in streams if s["codec_type"] == "video"), None)
    audio = next((s for s in streams if s["codec_type"] == "audio"), None)
    return video, audio


def mean_volume(path, start, seconds):
    """path의 start초부터 seconds초 동안 소리의 평균 크기(dB, volumedetect)."""
    result = subprocess.run(
        [external_tools.ffmpeg_path(), "-v", "info", "-ss", str(start), "-t", str(seconds), "-i", path,
         "-vn", "-af", "volumedetect", "-f", "null", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **external_tools.subprocess_kwargs())
    log = external_tools.decode_output(result.stderr)
    found = re.search(r"mean_volume: (-?[\d.]+) dB", log)
    assert found, f"{start}초부터 소리가 없습니다:\n{log[-2000:]}"
    return float(found.group(1))


def silences(path):
    """소리의 무음 구간 [(시작, 끝)] (silencedetect: -60 dB 아래 0.05초 이상 — 끝까지 이어진 무음은 빠질 수 있음)."""
    result = subprocess.run(
        [external_tools.ffmpeg_path(), "-v", "info", "-i", path, "-vn", "-af", "silencedetect=n=-60dB:d=0.05",
         "-f", "null", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **external_tools.subprocess_kwargs())
    log = external_tools.decode_output(result.stderr)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", log)]
    return list(zip(starts, ends))


def frame_luma(path):
    """영상 프레임마다 (시각, 평균 밝기 Y) — signalstats."""
    result = subprocess.run(
        [external_tools.ffmpeg_path(), "-v", "error", "-i", path, "-map", "0:v",
         "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **external_tools.subprocess_kwargs())
    log = external_tools.decode_output(result.stdout)
    times = [float(x) for x in re.findall(r"pts_time:([\d.]+)", log)]
    levels = [float(x) for x in re.findall(r"YAVG=([\d.]+)", log)]
    assert len(times) == len(levels), log[-2000:]
    return list(zip(times, levels))


def top_rows_brightness(path, at, rows=20):
    """at초 프레임의 맨 위 rows줄의 가장 밝은 값 (회색 0~255)."""
    result = subprocess.run(
        [external_tools.ffmpeg_path(), "-v", "error", "-ss", str(at), "-i", path, "-frames:v", "1",
         "-vf", f"crop=iw:{rows}:0:0", "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **external_tools.subprocess_kwargs())
    assert result.stdout, external_tools.decode_output(result.stderr)
    return max(result.stdout)


def merge(paths, out):
    external_tools.merge_videos_ffmpeg(external_tools.ffmpeg_path(), paths, out)
    return video_audio(out)


def assert_length(video, audio, seconds, frames):
    """영상 길이·프레임 수가 예상과 같고, 소리가 있으면 영상과 길이가 같음."""
    assert abs(float(video["duration"]) - seconds) < 0.1, video["duration"]
    assert abs(int(video["nb_read_frames"]) - frames) <= 1, video["nb_read_frames"]
    if audio is not None:
        assert abs(float(audio["duration"]) - float(video["duration"])) < 0.1, (audio["duration"], video["duration"])


def test_encoder_args():
    assert external_tools.video_encoder_args("fast", "4000k", "darwin") == [
        "-c:v", "h264_videotoolbox", "-b:v", "4000k", "-allow_sw", "1"]
    assert external_tools.video_encoder_args("fast", "4000k", "win32") == [
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "4000k"]
    assert external_tools.video_encoder_args("quality", "4000k", "win32") == [
        "-c:v", "libx264", "-preset", "slower", "-crf", "18"]
    assert external_tools.video_encoder_args("balanced", "4000k", "darwin") == [
        "-c:v", "libx264", "-preset", "faster", "-crf", "20"]
    assert external_tools.fast_mode_label("darwin") == "고속 (VideoToolbox)"
    assert external_tools.fast_mode_label("win32") == "고속 (CPU)"


def test_tool_path_frozen(monkeypatch, tmp_path):
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    (tmp_path / exe).write_bytes(b"")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert external_tools.ffmpeg_path() == str(tmp_path / exe)
    with pytest.raises(external_tools.ToolNotFoundError, match="앱 안에"):
        external_tools.ffprobe_path()


def test_tool_path_missing_on_path(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(external_tools.ToolNotFoundError, match="PATH"):
        external_tools.ffmpeg_path()


def test_file_names():
    assert file_names.is_listed_video("A.MOV")
    assert file_names.is_listed_video("b.mp4")
    assert not file_names.is_listed_video("._b.mov")
    assert not file_names.is_listed_video("c.txt")
    assert file_names.with_extension("X.MOV", ".mov") == "X.MOV"
    assert file_names.with_extension("X", ".mov") == "X.mov"
    assert file_names.avoid_reserved_name("aux") == "aux_"
    assert file_names.avoid_reserved_name("COM1") == "COM1_"
    assert file_names.avoid_reserved_name("SC_001") == "SC_001"


def test_merge_korean_and_quote(tmp_path, make_video):
    folder = tmp_path / "병합 시험"
    a = make_video(str(folder / "컷 1.mov"))
    b = make_video(str(folder / "it's 2.mov"))
    out = str(folder / "합본.mov")
    progress = []
    external_tools.merge_videos_ffmpeg(external_tools.ffmpeg_path(), [a, b], out, progress.append)
    assert os.path.getsize(out) > 0 and progress[-1] == 100
    # 같은 이름으로 다시 병합해도 (-y) 멈추지 않음
    external_tools.merge_videos_ffmpeg(external_tools.ffmpeg_path(), [a, b], out)


def test_merge_failure_raises(tmp_path):
    missing = str(tmp_path / "없음.mov")
    with pytest.raises(RuntimeError, match="ffprobe로 읽지 못했습니다") as error:
        external_tools.merge_videos_ffmpeg(external_tools.ffmpeg_path(), [missing], str(tmp_path / "o.mov"))
    assert missing in str(error.value) and "No such file" in str(error.value)


@pytest.mark.parametrize("audio_first_leads", [True, False])
def test_merge_different_track_order(tmp_path, audio_first_leads):
    """트랙 순서가 다른 파일 (소리가 0번 ↔ 영상이 0번): 번호가 아니라 종류로 이어 붙임 (concat demuxer는 번호로 짝지어
    둘째 파일의 영상을 소리로 디코딩 — 결과 영상은 첫 파일에서 멈추고 둘째 부분 소리는 잡음)."""
    a = make_media(str(tmp_path / "A.mov"), seconds=1, audio_first=True)
    b = make_media(str(tmp_path / "B.mov"), seconds=2)
    paths = [a, b] if audio_first_leads else [b, a]
    out = str(tmp_path / "합본.mov")
    video, audio = merge(paths, out)
    assert_length(video, audio, 3.0, 72)
    assert audio is not None
    first = 1.0 if audio_first_leads else 2.0
    assert -30 < mean_volume(out, 0.1, first - 0.2) < -12  # 사인파(진폭 1/8 ≈ -21 dB), 잡음이면 -5 dB쯤
    assert -30 < mean_volume(out, first + 0.1, 3.0 - first - 0.2) < -12


@pytest.mark.parametrize("silent", [0, 1, 2])
def test_merge_one_file_without_audio(tmp_path, silent):
    """소리가 없는 파일(처음·가운데·끝)은 그 영상 길이만큼 무음 — 결과에 소리가 있고 뒤 파일의 소리가 밀리지 않음."""
    paths = [make_media(str(tmp_path / f"컷 {n}.mov"), audio=n != silent) for n in range(3)]
    out = str(tmp_path / "합본.mov")
    video, audio = merge(paths, out)
    assert audio is not None
    assert_length(video, audio, 3.0, 72)
    for n in range(3):
        level = mean_volume(out, n + 0.1, 0.8)
        if n == silent:
            assert level < -60, (n, level)
        else:
            assert -30 < level < -12, (n, level)


def test_merge_audio_longer_than_video_is_cut(tmp_path):
    """영상보다 긴 소리는 그 컷의 마지막 프레임에서 자름 — 뒤 컷이 밀리지 않음 (컷 경계가 프레임에 맞음)."""
    a = make_media(str(tmp_path / "A.mov"), seconds=1, audio_seconds=1.5)
    b = make_media(str(tmp_path / "B.mov"), seconds=1)
    out = str(tmp_path / "합본.mov")
    video, audio = merge([a, b], out)
    assert audio is not None
    assert_length(video, audio, 2.0, 48)
    assert -30 < mean_volume(out, 1.1, 0.8) < -12


def test_merge_short_audio_padded_at_end(tmp_path):
    """영상보다 짧은 소리는 무음으로 채움 — 마지막 컷이어도 (concat 필터는 마지막 컷을 채우지 않음)."""
    a = make_media(str(tmp_path / "A.mov"), seconds=1)
    b = make_media(str(tmp_path / "B.mov"), seconds=1, audio_seconds=0.5)
    out = str(tmp_path / "합본.mov")
    video, audio = merge([a, b], out)
    assert audio is not None
    assert_length(video, audio, 2.0, 48)
    assert -30 < mean_volume(out, 1.1, 0.3) < -12
    assert mean_volume(out, 1.6, 0.3) < -60


def test_merge_held_frames_first_file_keeps_24fps(tmp_path):
    """첫 파일이 멈춘 그림을 긴 프레임으로 저장했으면(r 24, avg 168/25) avg가 아니라 r — 다른 컷의 프레임을 버리지 않음."""
    held = str(tmp_path / "멈춤.mov")  # 8프레임마다 2프레임만 (나머지는 앞 그림이 7/24초 동안), 끝 두 프레임은 그대로
    ffmpeg("-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=24",
           "-vf", r"select='lt(mod(n\,8)\,2)+gte(n\,46)'", "-fps_mode", "passthrough",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", held)
    first = video_audio(held)[0]
    assert (first["r_frame_rate"], first["avg_frame_rate"], first["duration"]) == ("24/1", "168/25", "2.000000")
    b = make_media(str(tmp_path / "B.mov"))
    video, audio = merge([held, b], str(tmp_path / "합본.mov"))
    assert video["r_frame_rate"] == "24/1"
    assert_length(video, audio, 3.0, 72)


def test_merge_cut_ends_at_edit_list_end(tmp_path):
    """편집 목록이 마지막 프레임보다 먼저 끝나는 컷(마지막 프레임은 7/24초, 편집 목록은 1.75초에서 끝): 그 컷은
    1.75초(42프레임)에서 끝남 — 다음 컷이 밀리지 않음."""
    held = str(tmp_path / "멈춤.mov")
    ffmpeg("-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=24", "-vf", r"select='lt(mod(n\,8)\,2)'",
           "-fps_mode", "passthrough", "-c:v", "libx264", "-pix_fmt", "yuv420p", held)
    first = video_audio(held)[0]
    assert (first["r_frame_rate"], first["duration"], first["nb_frames"]) == ("24/1", "1.750000", "12")
    white = str(tmp_path / "흰 화면.mov")
    ffmpeg("-f", "lavfi", "-i", "color=c=white:size=320x240:rate=24:duration=1", "-f", "lavfi", "-i", "sine=duration=1",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", white)
    out = str(tmp_path / "합본.mov")
    video, audio = merge([held, white], out)
    assert int(video["nb_read_frames"]) == 66  # 42 + 24
    assert_length(video, audio, 2.75, 66)
    frames = frame_luma(out)
    assert frames[42][0] == pytest.approx(1.75) and frames[42][1] > 200, frames[40:44]  # 흰 컷의 첫 프레임
    assert frames[41][1] < 200, frames[40:44]


def test_merge_bframe_mp4_video_starting_late(tmp_path):
    """B 프레임 mp4를 편집 목록 없이 쓰면 영상이 0.083초에 시작 — 컷은 첫 그림부터 (컷마다 밀리지 않음)."""
    cut = str(tmp_path / "컷.mp4")
    ffmpeg("-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=24", "-f", "lavfi", "-i", "sine=duration=1",
           "-c:v", "libx264", "-bf", "2", "-pix_fmt", "yuv420p", "-c:a", "aac", "-use_editlist", "0", cut)
    assert float(video_audio(cut)[0]["start_time"]) > 0.05
    video, audio = merge([cut] * 4, str(tmp_path / "합본.mov"))
    assert int(video["nb_read_frames"]) == 96
    assert_length(video, audio, 4.0, 96)


def test_merge_late_audio_start_stays_in_sync(tmp_path):
    """소리가 0.28초 늦게 시작하는 컷(편집 목록): 그 0.28초는 무음, 소리는 원래 자리 (영상과 맞음)."""
    a = make_media(str(tmp_path / "A.mov"))
    picture = make_media(str(tmp_path / "그림.mov"), audio=False)
    tone = make_tone(str(tmp_path / "소리.mov"))
    b = str(tmp_path / "B.mov")
    ffmpeg("-i", picture, "-itsoffset", "0.28", "-i", tone, "-map", "0:v", "-map", "1:a", "-c", "copy", b)
    out = str(tmp_path / "합본.mov")
    video, audio = merge([a, b], out)
    assert_length(video, audio, 2.0, 48)
    gaps = silences(out)
    assert len(gaps) == 1 and abs(gaps[0][0] - 1.0) < 0.06 and abs(gaps[0][1] - 1.28) < 0.06, gaps


def test_merge_video_empty_edit_lead(tmp_path):
    """영상 앞에 빈 편집(0.5초)이 있는 컷: 컷은 첫 그림부터 — 길이는 영상 길이의 합, 그림 앞의 소리는 버림 (영상과 맞게)."""
    a = make_media(str(tmp_path / "A.mov"))
    picture = make_media(str(tmp_path / "그림.mov"), audio=False)
    tone = make_tone(str(tmp_path / "소리.mov"))
    b = str(tmp_path / "B.mov")
    ffmpeg("-itsoffset", "0.5", "-i", picture, "-i", tone, "-map", "0:v", "-map", "1:a", "-c", "copy", b)
    out = str(tmp_path / "합본.mov")
    video, audio = merge([a, b, a], out)
    assert_length(video, audio, 3.0, 72)
    assert -30 < mean_volume(out, 1.05, 0.4) < -12  # B의 소리 0.5~1.0초 (그림과 함께 나오던 부분)
    assert mean_volume(out, 1.55, 0.4) < -60  # 그 뒤는 소리가 없음 → 무음


def test_merge_truncated_middle_input_fails(tmp_path):
    """가운데 파일이 잘려 있으면(moov는 2초, 그림은 일부만) 프레임 수가 모자람 → 실패, 결과 파일은 지움."""
    paths = [make_media(str(tmp_path / f"컷 {n}.mov"), seconds=2) for n in range(3)]
    whole = str(tmp_path / "온전.mov")
    os.replace(paths[1], whole)
    ffmpeg("-i", whole, "-map", "0", "-c", "copy", "-movflags", "faststart", paths[1])
    with open(paths[1], "r+b") as fh:
        fh.truncate(os.path.getsize(paths[1]) * 45 // 100)
    out = str(tmp_path / "합본.mov")
    with pytest.raises(RuntimeError, match="프레임 수가") as error:
        external_tools.merge_videos_ffmpeg(external_tools.ffmpeg_path(), paths, out)
    assert "예상 142~146 프레임" in str(error.value)
    assert not os.path.exists(out)


def test_merge_rotated_first_file_gives_portrait(tmp_path):
    """첫 파일이 90도 돌려 보이는 영상(디스플레이 행렬)이면 세로 화면 — 돌린 그림이 화면을 채우고 둘째는 레터박스."""
    plain = make_media(str(tmp_path / "가로.mov"))
    rotated = str(tmp_path / "세로.mov")
    ffmpeg("-display_rotation:v:0", "90", "-i", plain, "-map", "0", "-c", "copy", rotated)
    out = str(tmp_path / "합본.mov")
    video, audio = merge([rotated, plain], out)
    assert (video["width"], video["height"]) == (240, 320)
    assert_length(video, audio, 2.0, 48)
    assert top_rows_brightness(out, 0.5) > 100
    assert top_rows_brightness(out, 1.5) < 30


def test_merge_non_square_pixels_first_file(tmp_path):
    """첫 파일의 화소가 정사각형이 아니면(SAR 4:3, 480x360 → 보이는 크기 640x360) 보이는 크기로."""
    wide = str(tmp_path / "A.mov")
    ffmpeg("-f", "lavfi", "-i", "testsrc=duration=1:size=480x360:rate=24", "-vf", "setsar=4/3",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", wide)
    b = make_media(str(tmp_path / "B.mov"), size="640x360")
    out = str(tmp_path / "합본.mov")
    video, audio = merge([wide, b], out)
    assert (video["width"], video["height"], video["sample_aspect_ratio"]) == (640, 360, "1:1")
    assert_length(video, audio, 2.0, 48)
    assert top_rows_brightness(out, 0.5) > 100 and top_rows_brightness(out, 1.5) > 100  # 둘 다 화면을 채움


def test_merge_bad_result_is_deleted(monkeypatch, tmp_path, make_video):
    """결과 확인에서 틀리면 결과 파일을 지우고, 지웠다고 알림 (ffmpeg 명령·로그도)."""
    a = make_video(str(tmp_path / "A.mov"))
    out = str(tmp_path / "합본.mov")
    existed = []

    def wrong(inputs, output_path, *args):
        existed.append(os.path.exists(output_path))
        raise RuntimeError("병합 결과가 잘못되었습니다 — 시험")

    monkeypatch.setattr(external_tools, "check_merged_output", wrong)
    with pytest.raises(RuntimeError, match="병합 결과가 잘못되었습니다 — 시험") as error:
        external_tools.merge_videos_ffmpeg(external_tools.ffmpeg_path(), [a, a], out)
    assert existed == [True] and not os.path.exists(out)
    message = str(error.value)
    assert f"잘못된 결과 파일은 지웠습니다: {out}" in message and "명령:" in message and "libx264" in message


def test_merge_bad_result_delete_failure_is_reported(monkeypatch, tmp_path, make_video):
    """잘못된 결과 파일을 지우지 못하면 그 오류도 같은 메시지에 (삼키지 않음)."""
    a = make_video(str(tmp_path / "A.mov"))
    out = str(tmp_path / "합본.mov")

    def wrong(*args):
        raise RuntimeError("병합 결과가 잘못되었습니다 — 시험")

    def locked(path):
        raise PermissionError(13, "잠겨 있음", path)

    monkeypatch.setattr(external_tools, "check_merged_output", wrong)
    monkeypatch.setattr(external_tools.os, "remove", locked)
    with pytest.raises(RuntimeError, match="병합 결과가 잘못되었습니다 — 시험") as error:
        external_tools.merge_videos_ffmpeg(external_tools.ffmpeg_path(), [a, a], out)
    assert f"잘못된 결과 파일을 지우지 못했습니다: {out} — " in str(error.value)
    assert "잠겨 있음" in str(error.value)
    assert os.path.exists(out)


@pytest.mark.parametrize("audio", [False, True])
@pytest.mark.parametrize("pattern", [(24, 1, 24, 1, 24), (24, 1, 1, 1, 1, 24)])
def test_merge_one_frame_cuts(tmp_path, pattern, audio):
    """1프레임 컷도 제자리에 — 소리가 없는 병합에서 concat이 영상만인 컷의 길이를 프레임 간격으로 짐작하면 1프레임 컷이
    0이 되어 다음 컷의 첫 프레임과 겹침. 컷마다 다른 회색으로 결과의 프레임이 어느 컷인지 봄."""
    paths = [make_flat_cut(str(tmp_path / f"컷 {n}.mov"), 0x10 + 0x28 * n, frames, audio)
             for n, frames in enumerate(pattern)]
    out = str(tmp_path / "합본.mov")
    video, merged_audio = merge(paths, out)
    assert (merged_audio is not None) == audio
    levels = [frame_luma(path)[0][1] for path in paths]
    frames = frame_luma(out)
    cuts = [min(range(len(levels)), key=lambda k: abs(levels[k] - luma)) for _time, luma in frames]
    runs = [(cut, len(list(group))) for cut, group in itertools.groupby(cuts)]
    assert runs == list(enumerate(pattern)), runs
    starts = [sum(pattern[:n]) for n in range(len(pattern))]
    assert [frames[i][0] for i in starts] == pytest.approx([i / 24 for i in starts])
    assert_length(video, merged_audio, sum(pattern) / 24, sum(pattern))


def test_merge_no_audio_anywhere(tmp_path):
    paths = [make_media(str(tmp_path / f"컷 {n}.mov"), audio=False) for n in range(2)]
    video, audio = merge(paths, str(tmp_path / "합본.mov"))
    assert audio is None
    assert_length(video, audio, 2.0, 48)


def test_merge_different_resolution(tmp_path):
    """크기가 다른 파일은 첫 파일 크기로 (가로세로 비율이 다르면 레터박스)."""
    a = make_media(str(tmp_path / "A.mov"), size="320x240")
    b = make_media(str(tmp_path / "B.mov"), size="640x360")
    out = str(tmp_path / "합본.mov")
    video, audio = merge([a, b], out)
    assert (video["width"], video["height"]) == (320, 240)
    assert_length(video, audio, 2.0, 48)
    # 16:9 → 4:3: 320x180으로 줄이고 위아래 30줄씩 검은 띠 (늘이지 않음)
    assert top_rows_brightness(out, 0.5) > 100
    assert top_rows_brightness(out, 1.5) < 30


def test_merge_odd_size_rounds_down_to_even(tmp_path):
    a = make_media(str(tmp_path / "A.mov"), size="321x241", pix_fmt="yuv444p")
    b = make_media(str(tmp_path / "B.mov"))
    video, audio = merge([a, b], str(tmp_path / "합본.mov"))
    assert (video["width"], video["height"], video["pix_fmt"]) == (320, 240, "yuv420p")
    assert_length(video, audio, 2.0, 48)


def test_merge_different_frame_rate(tmp_path):
    """프레임 속도가 다른 파일은 첫 파일의 속도로 (30 → 24: 1초는 그대로 1초)."""
    a = make_media(str(tmp_path / "A.mov"), rate=24)
    b = make_media(str(tmp_path / "B.mov"), rate=30)
    video, audio = merge([a, b], str(tmp_path / "합본.mov"))
    assert video["r_frame_rate"] == "24/1"
    assert_length(video, audio, 2.0, 48)


def test_merge_audio_only_input_raises(tmp_path, make_video):
    a = make_video(str(tmp_path / "A.mov"))
    sound = str(tmp_path / "소리.m4a")
    subprocess.run([external_tools.ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1",
                    "-c:a", "aac", sound], check=True, **external_tools.subprocess_kwargs())
    with pytest.raises(RuntimeError, match=r"영상\(그림\) 트랙이 없습니다") as error:
        external_tools.merge_videos_ffmpeg(external_tools.ffmpeg_path(), [a, sound], str(tmp_path / "o.mov"))
    assert sound in str(error.value)


def test_merge_windows_command_too_long(monkeypatch, tmp_path):
    """Windows 명령 줄 한도(약 32,000자)를 넘으면 ffprobe·ffmpeg를 띄우기 전에 알림."""
    monkeypatch.setattr(external_tools, "IS_WINDOWS", True)
    paths = [f"C:\\작품\\{'애니매틱 폴더 ' * 8}\\컷 {n}.mov" for n in range(400)]
    with pytest.raises(RuntimeError, match="한 번에 합칠 파일 수를 줄이세요"):
        external_tools.merge_videos_ffmpeg("ffmpeg.exe", paths, str(tmp_path / "o.mov"))


def fake_resource(soft, hard, cap=None, error=None):
    """resource 모듈 흉내 (열린 파일 한도). cap: setrlimit이 말없이 이 값까지만 올림, error: setrlimit이 이 예외."""
    fake = SimpleNamespace(RLIMIT_NOFILE=8, RLIM_INFINITY=2 ** 63 - 1, limit=(soft, hard), calls=[])

    def setrlimit(kind, limit):
        assert kind == fake.RLIMIT_NOFILE
        fake.calls.append(limit)
        if error:
            raise error
        fake.limit = (min(limit[0], cap or limit[0]), limit[1])

    fake.getrlimit = lambda kind: fake.limit
    fake.setrlimit = setrlimit
    return fake


def merge_with_open_file_limit(monkeypatch, tmp_path, fake, count):
    """(Mac·Linux 쪽 길) 없는 파일 count개를 합치려 함 — 한도를 확인한 뒤 첫 파일을 읽다가 실패해야 함."""
    ffmpeg_path = external_tools.ffmpeg_path()
    monkeypatch.setattr(external_tools, "IS_WINDOWS", False)
    monkeypatch.setitem(sys.modules, "resource", fake)
    paths = [str(tmp_path / f"없음 {n}.mov") for n in range(count)]
    with pytest.raises(RuntimeError) as error:
        external_tools.merge_videos_ffmpeg(ffmpeg_path, paths, str(tmp_path / "o.mov"))
    return str(error.value)


def test_merge_raises_open_file_limit(monkeypatch, tmp_path):
    """concat 필터는 입력을 한꺼번에 엶 → 한도(Finder로 켠 앱은 256)가 모자라면 이 프로세스의 한도를 올림 (ffmpeg가 물려받음)."""
    fake = fake_resource(256, 2 ** 63 - 1)
    message = merge_with_open_file_limit(monkeypatch, tmp_path, fake, 300)
    assert "ffprobe로 읽지 못했습니다" in message  # 한도를 올린 뒤 첫 파일 읽기에서
    assert fake.calls == [(300 + external_tools.MERGE_FD_HEADROOM, 2 ** 63 - 1)]
    small = fake_resource(256, 2 ** 63 - 1)
    merge_with_open_file_limit(monkeypatch, tmp_path, small, 3)
    assert small.calls == []  # 모자라지 않으면 건드리지 않음


@pytest.mark.parametrize("cap, error", [(None, ValueError("current limit exceeds maximum limit")), (280, None)])
def test_merge_open_file_limit_cannot_be_raised(monkeypatch, tmp_path, cap, error):
    """한도를 올리지 못하면(macOS: kern.maxfilesperproc 초과) ffprobe·ffmpeg를 띄우기 전에 나눠서 합치라고 알림."""
    message = merge_with_open_file_limit(monkeypatch, tmp_path, fake_resource(256, 2 ** 63 - 1, cap, error), 300)
    allowed = (cap or 256) - external_tools.MERGE_FD_HEADROOM
    assert f"한 번에 합칠 수 있는 파일 수({allowed}개)를 넘었습니다 — 나눠서 합치세요" in message, message
    assert "300개" in message and "ffprobe" not in message
    if error:
        assert "current limit exceeds maximum limit" in message


def merge_inputs(*durations, audio=True):
    return [external_tools.MergeInput(path=f"/작품/컷 {n}.mov", video_index=0, audio_index=1 if audio else None,
                                      width=320, height=240, rate=Fraction(24), duration=seconds, start=0.0,
                                      sample_rate=22050 if audio else None)
            for n, seconds in enumerate(durations, 1)]


def check(inputs, video_duration, audio_duration, frames=72):
    external_tools.check_merged_output(inputs, "/작품/합본.mov", video_duration, frames, audio_duration)


def test_merge_tolerance():
    """이음매마다 한 프레임 + 0.1초."""
    assert external_tools.merge_tolerance(2, 24) == pytest.approx(2 / 24 + 0.1)


def test_check_merged_output_within_tolerance():
    inputs = merge_inputs(1.0, 2.0)
    tolerance = external_tools.merge_tolerance(2, 24)
    check(inputs, 3.0 + tolerance - 0.01, 3.0 + tolerance - 0.01)
    check(inputs, 3.0 - tolerance + 0.01, 3.0)
    check(merge_inputs(1.0, 2.0, audio=False), 3.0, None)  # 소리가 없는 입력 → 결과에도 소리 없음


def test_check_merged_output_short_video():
    """예전 문제: 영상이 첫 파일 끝에서 멈춤 (소리는 더 김). 입력별 길이·예상 합계·결과를 모두 보임."""
    with pytest.raises(RuntimeError, match="병합 결과가 잘못되었습니다") as error:
        check(merge_inputs(1.0, 2.0), 1.0, 1.68, frames=24)
    message = str(error.value)
    for text in ("/작품/컷 1.mov", "/작품/컷 2.mov", "1.000초", "2.000초", "3.000초", "24 프레임", "1.680초",
                 "/작품/합본.mov"):
        assert text in message, text
    tolerance = external_tools.merge_tolerance(2, 24)
    with pytest.raises(RuntimeError, match="영상 길이"):
        check(merge_inputs(1.0, 2.0), 3.0 + tolerance + 0.01, 3.0)


def test_check_merged_output_frame_count():
    """프레임 수는 Σ floor(영상 길이 × 프레임 속도) - 2 ~ Σ ceil(…) + 2 (예전 같은 문제: 길이는 맞는데 그림이 멈춤)."""
    inputs = merge_inputs(1.0, 2.0)  # 24 + 48 프레임
    check(inputs, 3.0, 3.0, frames=74)
    check(inputs, 3.0, 3.0, frames=70)
    for frames in (69, 75):
        with pytest.raises(RuntimeError, match="프레임 수가") as error:
            check(inputs, 3.0, 3.0, frames=frames)
        assert f"{frames} 프레임" in str(error.value) and "예상 70~74 프레임" in str(error.value)
    with pytest.raises(RuntimeError, match="프레임 수"):
        check(inputs, 3.0, 3.0, frames=None)


def test_check_merged_output_frame_count_many_inputs():
    """입력이 많아도 범위는 ±2 프레임 (입력 수만큼 넓히지 않음 — 267컷에서 200프레임이 모자라면 실패)."""
    inputs = merge_inputs(*[1.0] * 267)  # 6408 프레임
    check(inputs, 267.0, 267.0, frames=6408)
    check(inputs, 267.0, 267.0, frames=6410)
    for frames in (6208, 6405, 6411):
        with pytest.raises(RuntimeError, match="프레임 수가") as error:
            check(inputs, 267.0, 267.0, frames=frames)
        assert "예상 6406~6410 프레임" in str(error.value)


def test_check_merged_output_frame_count_fractional():
    """길이가 프레임에 딱 맞지 않으면 (23.976 fps의 1.5초 = 35.96 프레임) 내림·올림 사이에서."""
    inputs = [external_tools.MergeInput(path="/작품/컷.mov", video_index=0, audio_index=None, width=320, height=240,
                                        rate=Fraction(24000, 1001), duration=1.5, start=0.0, sample_rate=None)] * 2
    check(inputs, 3.0, None, frames=72)
    with pytest.raises(RuntimeError, match="예상 68~74 프레임"):
        check(inputs, 3.0, None, frames=75)


def test_check_merged_output_audio_longer_than_video():
    with pytest.raises(RuntimeError, match="소리가 영상보다"):
        check(merge_inputs(1.0, 2.0), 3.0, 4.1)
    check(merge_inputs(1.0, 2.0), 3.0, 3.9)  # 1초까지는 괜찮음


def test_check_merged_output_missing_tracks():
    with pytest.raises(RuntimeError, match="소리 트랙이 없거나"):
        check(merge_inputs(1.0, 2.0), 3.0, None)
    with pytest.raises(RuntimeError, match="영상 트랙이 없거나"):
        check(merge_inputs(1.0, 2.0), None, 3.0)


@pytest.mark.parametrize("text, expected", [
    (None, None), ("", None), ("0/0", None), ("0/1", None), ("-24/1", None), ("241/1", None),
    ("24/1", Fraction(24)), ("240/1", Fraction(240)), ("24000/1001", Fraction(24000, 1001))])
def test_frame_rate_text(text, expected):
    assert external_tools._frame_rate(text) == expected


@pytest.mark.parametrize("text, expected", [(None, None), ("N/A", None), ("0", None), ("0.000000", None), ("1.5", 1.5)])
def test_seconds_text(text, expected):
    assert external_tools._seconds(text) == expected


@pytest.mark.parametrize("r, avg, expected", [
    ("0/0", "0/0", None),
    ("0/1", "0/1", None),
    ("90000/1", "24/1", Fraction(24)),  # r이 터무니없음 → avg
    ("24000/1001", "24000/1001", Fraction(24000, 1001)),
    ("48/1", "18000/601", Fraction(30000, 1001)),  # VFR 폰 영상: r은 48인데 실제로는 30쯤 → avg, 표준 속도로
    ("644490000/21527987", "644490000/21527987", Fraction(30000, 1001)),  # 큰 분수는 표준 속도로
    ("25/1", "0/0", Fraction(25)),
    ("30/1", "2997/100", Fraction(30)),  # 10% 안에서 다르면 r
    ("15/1", "15/1", Fraction(15)),
    ("24/1", "192/35", Fraction(24)),  # 멈춘 그림을 긴 프레임으로 저장 → avg는 표준 속도가 아님 → r
    ("24/1", "48/7", Fraction(24)),
    ("0/0", "1234567/98765", Fraction(1234567, 98765).limit_denominator(1001)),  # r을 못 쓰고 avg는 표준이 아님
])
def test_pick_frame_rate(r, avg, expected):
    assert external_tools.pick_frame_rate(r, avg) == expected


def test_pick_frame_rate_limits_denominator():
    """표준 속도가 아니면 분모를 1001까지로 (mov 시간 단위가 넘치지 않게)."""
    rate = external_tools.pick_frame_rate("1234567/98765", "1234567/98765")
    assert rate.denominator <= 1001 and abs(float(rate) - 1234567 / 98765) < 0.001


def probe_info(video, audio=None, format_info=None):
    streams = [{"index": 0, "codec_type": "video", "disposition": {"attached_pic": 1}, "width": 600, "height": 600,
                "r_frame_rate": "90000/1", "avg_frame_rate": "0/0"}]  # 앨범 아트
    if audio:
        streams.append(dict(audio, index=1, codec_type="audio"))
    streams.append(dict({"r_frame_rate": "24/1", "avg_frame_rate": "24/1", "width": 320, "height": 240,
                         "disposition": {"attached_pic": 0}}, **video, index=2, codec_type="video"))
    return {"streams": streams, "format": format_info or {}}


def test_probe_merge_input_picks_by_type(monkeypatch):
    """앨범 아트(attached_pic)는 영상으로 치지 않음, 영상에 길이가 없으면 형식의 길이,
    시작은 첫 그림 (ffmpeg가 빼는 형식 시작 기준)."""
    info = probe_info({"start_time": "0.5"}, {"sample_rate": "48000"}, {"duration": "2.5", "start_time": "0.25"})
    monkeypatch.setattr(external_tools, "_probe", lambda *args, **kwargs: info)
    item = external_tools.probe_merge_input("ffprobe", "/작품/컷.mkv")
    assert (item.video_index, item.audio_index, item.width, item.height) == (2, 1, 320, 240)
    assert (item.duration, item.start, item.rate, item.sample_rate) == (2.5, 0.25, Fraction(24), 48000)


@pytest.mark.parametrize("video, size", [
    ({"sample_aspect_ratio": "4:3", "width": 480, "height": 360}, (640, 360)),
    ({"sample_aspect_ratio": "0:1"}, (320, 240)),  # 모름 → 정사각형
    ({"side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]}, (240, 320)),
    ({"side_data_list": [{"side_data_type": "Display Matrix", "rotation": 180}]}, (320, 240)),
    ({"sample_aspect_ratio": "4:3", "width": 480, "height": 360,
      "side_data_list": [{"side_data_type": "Display Matrix", "rotation": 90}]}, (360, 640)),
])
def test_probe_merge_input_display_size(monkeypatch, video, size):
    """크기는 보이는 크기 (화소 비율 SAR을 곱하고, 90·270도 돌려 보이면 가로세로를 바꿈)."""
    info = probe_info(dict(video, duration="1.0"))
    monkeypatch.setattr(external_tools, "_probe", lambda *args, **kwargs: info)
    item = external_tools.probe_merge_input("ffprobe", "/작품/컷.mov")
    assert (item.width, item.height) == size


@pytest.mark.parametrize("video, audio, error", [
    ({}, {"sample_rate": "abc"}, ValueError),
    ({}, {"channels": 2}, KeyError),  # sample_rate 없음
    ({"r_frame_rate": "x/y"}, None, ValueError),
    ({"side_data_list": [{"rotation": "abc"}]}, None, ValueError),
    ({"width": "넓음"}, None, ValueError),
])
def test_probe_merge_input_unexpected_json(monkeypatch, video, audio, error):
    """ffprobe 결과가 예상과 다르면 맨 예외가 아니라 RuntimeError (파일 이름, 원래 예외, 스택 트레이스)."""
    info = probe_info(dict(video, duration="1.0"), audio)
    monkeypatch.setattr(external_tools, "_probe", lambda *args, **kwargs: info)
    with pytest.raises(RuntimeError, match="병합할 파일의 정보를 읽지 못했습니다") as caught:
        external_tools.probe_merge_input("ffprobe", "/작품/컷 1.mov")
    message = str(caught.value)
    assert "/작품/컷 1.mov" in message and f"{error.__name__}(" in message and "Traceback" in message
    assert isinstance(caught.value.__cause__, error)


def test_probe_korean_path(tmp_path, make_video):
    video = make_video(str(tmp_path / "한글 폴더" / "영상.mov"))
    result = subprocess.run(
        [external_tools.ffprobe_path(), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", video],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **external_tools.subprocess_kwargs())
    assert external_tools.decode_output(result.stdout).strip() == "h264"


def test_merge_registers_process_that_can_be_killed(tmp_path, make_video):
    """병합이 띄우는 ffprobe·ffmpeg를 모두 알려 줌 → 창을 닫을 때 끝낼 수 있음. 병합 ffmpeg를 끝내면 실패로 올라옴."""
    a = make_video(str(tmp_path / "a.mov"))
    ffmpeg_path = external_tools.ffmpeg_path()
    registered = []

    def kill_merge(process):
        registered.append(process)
        if process.args[0] == ffmpeg_path:
            process.kill()

    with pytest.raises(RuntimeError, match="ffmpeg 병합 실패"):
        external_tools.merge_videos_ffmpeg(ffmpeg_path, [a, a], str(tmp_path / "o.mov"), register_process=kill_merge)
    assert [p.args[0] for p in registered] == [external_tools.ffprobe_path()] * 2 + [ffmpeg_path]
    assert registered[-1].returncode not in (None, 0)


def test_merge_probe_can_be_killed(tmp_path, make_video):
    """파일을 읽는 ffprobe도 끝낼 수 있음 (느린 NAS) → 끝내면 거기서 멈추고 병합 ffmpeg는 띄우지 않음."""
    a = make_video(str(tmp_path / "a.mov"))
    out = str(tmp_path / "o.mov")
    registered = []

    def kill_now(process):
        registered.append(process)
        process.kill()

    with pytest.raises(RuntimeError, match="ffprobe로 읽지 못했습니다"):
        external_tools.merge_videos_ffmpeg(external_tools.ffmpeg_path(), [a, a], out, register_process=kill_now)
    assert len(registered) == 1 and registered[0].args[0] == external_tools.ffprobe_path()
    assert registered[0].returncode not in (None, 0) and not os.path.exists(out)
