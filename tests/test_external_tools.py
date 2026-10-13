import os
import subprocess
import sys

import pytest

from yesoncheck import external_tools, file_names


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


def test_concat_list_line_escapes_quote():
    assert external_tools.concat_list_line("/a/it's.mov") == "file '/a/it'\\''s.mov'\n"


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
    with pytest.raises(RuntimeError, match="ffmpeg 병합 실패"):
        external_tools.merge_videos_ffmpeg(external_tools.ffmpeg_path(), [str(tmp_path / "없음.mov")], str(tmp_path / "o.mov"))


def test_probe_korean_path(tmp_path, make_video):
    video = make_video(str(tmp_path / "한글 폴더" / "영상.mov"))
    result = subprocess.run(
        [external_tools.ffprobe_path(), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", video],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **external_tools.subprocess_kwargs())
    assert external_tools.decode_output(result.stdout).strip() == "h264"


def test_merge_registers_process_that_can_be_killed(tmp_path, make_video):
    """병합이 실행 중인 ffmpeg를 알려 줌 → 창을 닫을 때 끝낼 수 있음. 끝내면 실패로 올라옴."""
    a = make_video(str(tmp_path / "a.mov"))
    registered = []

    def kill_now(process):
        registered.append(process)
        process.kill()

    with pytest.raises(RuntimeError, match="ffmpeg 병합 실패"):
        external_tools.merge_videos_ffmpeg(external_tools.ffmpeg_path(), [a, a], str(tmp_path / "o.mov"),
                                           register_process=kill_now)
    assert len(registered) == 1 and registered[0].returncode not in (None, 0)
