"""ffmpeg·ffprobe 위치와 실행 옵션, 인코더 설정, 영상 병합 (Mac/Windows 공통)."""

import os
import shutil
import subprocess
import sys
import tempfile

IS_WINDOWS = sys.platform == "win32"


class ToolNotFoundError(Exception):
    """ffmpeg·ffprobe 실행 파일을 찾지 못했을 때."""


def tool_path(name):
    """빌드 앱: 앱 안의 실행 파일(Windows는 .exe). 개발 환경: PATH에서 찾음."""
    filename = name + (".exe" if IS_WINDOWS else "")
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = os.path.join(meipass, filename)
        if os.path.isfile(candidate):
            return candidate
        raise ToolNotFoundError(f"앱 안에 {filename}이(가) 없습니다: {candidate}")
    found = shutil.which(name)
    if found:
        return found
    raise ToolNotFoundError(f"{name}을(를) PATH에서 찾지 못했습니다. ffmpeg를 설치했는지, PATH에 있는지 확인하세요.")


def ffmpeg_path():
    return tool_path("ffmpeg")


def ffprobe_path():
    return tool_path("ffprobe")


def subprocess_kwargs():
    """모든 ffmpeg·ffprobe 실행에 넘길 옵션. Windows: 실행할 때마다 콘솔 창이 뜨지 않게."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def decode_output(data):
    """ffmpeg 출력(UTF-8)을 문자열로. 한글 Windows의 기본 인코딩(cp949)으로 읽지 않음."""
    return data.decode("utf-8", errors="replace") if data else ""


def video_encoder_args(export_mode, bitrate, platform=sys.platform):
    """내보내기 모드별 영상 인코더 인자. 고속: Mac은 VideoToolbox, 그 외는 libx264 veryfast + 비트레이트."""
    if export_mode == "fast":
        if platform == "darwin":
            return ["-c:v", "h264_videotoolbox", "-b:v", bitrate, "-allow_sw", "1"]
        return ["-c:v", "libx264", "-preset", "veryfast", "-b:v", bitrate]
    if export_mode == "quality":
        return ["-c:v", "libx264", "-preset", "slower", "-crf", "18"]
    return ["-c:v", "libx264", "-preset", "faster", "-crf", "20"]


def fast_mode_label(platform=sys.platform):
    return "고속 (VideoToolbox)" if platform == "darwin" else "고속 (CPU)"


def concat_list_line(file_path):
    """ffmpeg concat 목록 한 줄. 작은따옴표는 '\\'' 로 이스케이프."""
    return "file '" + file_path.replace("'", "'\\''") + "'\n"


def merge_videos_ffmpeg(ffmpeg, file_paths, output_path, on_progress=None, register_process=None):
    """여러 영상을 하나로 합칩니다 (블랙 프레임 검사 필터 + libx264). 실패하면 RuntimeError(stderr 포함).

    register_process(proc): ffmpeg를 띄운 직후 불림 → 부른 쪽이 proc.kill()로 병합을 멈출 수 있음 (창 닫기).
    """
    temp_dir = tempfile.mkdtemp(prefix="yesoncheck_merge_")
    try:
        list_path = os.path.join(temp_dir, "video_list.txt")
        with open(list_path, "w", encoding="utf-8") as fh:
            for path in file_paths:
                fh.write(concat_list_line(path))
        if on_progress:
            on_progress(50)
        cmd = [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-vf", "blackdetect=d=0.1:pix_th=0.1,blackframe=0:32",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
            "-movflags", "faststart", "-f", "mov", output_path,
        ]
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **subprocess_kwargs())
        try:
            if register_process:
                register_process(process)
            _, stderr = process.communicate()
        finally:
            if process.poll() is None:  # 여기서 예외가 나도 ffmpeg가 남지 않게
                process.kill()
                process.wait()
        if process.returncode != 0:
            raise RuntimeError(
                f"ffmpeg 병합 실패 (종료 코드 {process.returncode})\n명령: {' '.join(cmd)}\n"
                f"{decode_output(stderr)[-4000:]}"
            )
        if on_progress:
            on_progress(100)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
