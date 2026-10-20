"""ffmpeg·ffprobe 위치와 실행 옵션, 인코더 설정, 영상 병합 (Mac/Windows 공통)."""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass
from fractions import Fraction

IS_WINDOWS = sys.platform == "win32"
MAX_FRAME_RATE = 240  # r_frame_rate가 이보다 크면(VFR 파일의 90000/1 등) avg_frame_rate를 씀
MERGE_SLACK_SECONDS = 0.1  # 병합 결과 길이 검사의 여유 (이음매마다 한 프레임에 더함)
MERGE_FRAME_SLACK = 2  # 병합 결과 프레임 수 범위의 여유 (Σ 내림 - 2 ~ Σ 올림 + 2)
AUDIO_OVERRUN_LIMIT = 1.0  # 병합 결과의 소리가 영상보다 이만큼(초) 넘게 길면 잘못된 병합
WINDOWS_COMMAND_LIMIT = 32000  # Windows 명령 줄 한도(32,767자)보다 조금 작게
MERGE_FD_HEADROOM = 64  # 병합 ffmpeg가 입력 말고 여는 파일(라이브러리·출력·파이프 등)의 여유
STANDARD_FRAME_RATES = tuple(Fraction(r) for r in ("24000/1001", "24", "25", "30000/1001", "30", "48", "50",
                                                    "60000/1001", "60"))


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


@dataclass(frozen=True)
class MergeInput:
    """병합할 파일 하나 (ffprobe). 트랙 번호는 파일 안의 절대 번호 — 트랙 순서가 파일마다 달라도 종류로 고름."""

    path: str
    video_index: int  # 첫 영상 트랙 (앨범 아트 같은 attached_pic 제외)
    audio_index: int | None  # 첫 소리 트랙
    width: int  # 보이는 크기 (화소 비율 SAR을 곱하고, 90·270도 돌려 보이면 가로세로를 바꿈)
    height: int
    rate: Fraction  # 프레임 속도 (pick_frame_rate)
    duration: float  # 영상 길이(초)
    start: float  # 컷의 시작 = 첫 그림 (ffmpeg가 형식의 시작을 뺀 뒤의 시각, 초)
    sample_rate: int | None


def _communicate(cmd, register_process, stdout=subprocess.PIPE):
    """cmd를 띄우고 끝날 때까지 기다림 → (종료 코드, stdout, stderr). register_process(proc): 띄운 직후 불림 →
    부른 쪽이 proc.kill()로 멈출 수 있음 (창 닫기)."""
    process = subprocess.Popen(cmd, stdout=stdout, stderr=subprocess.PIPE, **subprocess_kwargs())
    try:
        if register_process:
            register_process(process)
        out, err = process.communicate()
    finally:
        if process.poll() is None:  # 여기서 예외가 나도 프로세스가 남지 않게
            process.kill()
            process.wait()
    return process.returncode, out, err


def _probe(ffprobe, path, register_process=None):
    """ffprobe JSON (스트림·형식). 실패하면(끝냈을 때도) RuntimeError (파일·stderr 전부)."""
    code, out, err = _communicate(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path], register_process)
    if code != 0:
        raise RuntimeError(f"ffprobe로 읽지 못했습니다 (종료 코드 {code}): {path}\n{decode_output(err)}")
    return json.loads(decode_output(out))


def _seconds(text):
    """ffprobe 길이 글(초). 없거나 0 이하면 None."""
    if text in (None, "N/A"):
        return None
    seconds = float(text)
    return seconds if seconds > 0 else None


def _start_seconds(text):
    """ffprobe 시작 시각 글(초, 음수도 있음). 없으면 0."""
    return 0.0 if text in (None, "N/A") else float(text)


def _frame_rate(text):
    """ffprobe 프레임 속도 글("24/1", "24000/1001")을 Fraction으로. 0/0·0 이하·MAX_FRAME_RATE 초과면 None."""
    if not text or text.endswith("/0"):
        return None
    rate = Fraction(text)
    return rate if 0 < rate <= MAX_FRAME_RATE else None


def _standard_rate(rate):
    """rate와 0.5% 안의 표준 속도(STANDARD_FRAME_RATES 중 가장 가까운 것). 없으면 None."""
    nearest = min(STANDARD_FRAME_RATES, key=lambda standard: abs(standard - rate))
    return nearest if abs(nearest - rate) <= nearest / 200 else None


def pick_frame_rate(r_frame_rate, avg_frame_rate):
    """병합에 쓸 프레임 속도. 보통 r_frame_rate. avg_frame_rate는 표준 속도에 맞고, r을 쓸 수 없거나 r과 10% 넘게
    다를 때만 (VFR 폰 영상: r 48, 실제 30쯤) — 멈춘 그림을 긴 프레임으로 저장한 파일(r 24, avg 5.49)의 avg는 쓰지
    않음. 표준 속도와 0.5% 안이면 그 속도, 아니면 분모를 1001까지로 (fps 필터에 큰 분수를 넣으면 mov 시간 단위가
    넘침). 둘 다 쓸 수 없으면 None."""
    r, avg = _frame_rate(r_frame_rate), _frame_rate(avg_frame_rate)
    if avg is not None and _standard_rate(avg) and (r is None or abs(r - avg) > avg / 10):
        return _standard_rate(avg)
    rate = r if r is not None else avg
    if rate is None:
        return None
    return _standard_rate(rate) or rate.limit_denominator(1001)


def _display_size(video):
    """영상 트랙의 보이는 크기 (가로, 세로): 화소 비율(SAR, 모르면 1)을 곱한 가로, 90·270도 돌려 보이면
    (디스플레이 행렬) 가로세로를 바꿈 — ffmpeg는 디코딩할 때 돌려 줌."""
    num, _, den = str(video.get("sample_aspect_ratio", "")).partition(":")
    sar = Fraction(int(num), int(den)) if num.isdigit() and den.isdigit() and int(num) and int(den) else Fraction(1)
    width, height = int(int(video["width"]) * sar), int(video["height"])
    rotation = next((d["rotation"] for d in video.get("side_data_list", []) if "rotation" in d), 0)
    return (height, width) if round(float(rotation)) % 180 == 90 else (width, height)


def probe_merge_input(ffprobe, path, register_process=None):
    """병합할 파일의 MergeInput. 영상 트랙이 없거나 크기·길이·프레임 속도를 알 수 없으면 RuntimeError (파일 이름).
    ffprobe 결과가 예상과 다르면(값의 형식·빠진 값) 원래 예외와 스택 트레이스를 붙인 RuntimeError."""
    try:
        return _merge_input_from_probe(path, _probe(ffprobe, path, register_process))
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
        raise RuntimeError(f"병합할 파일의 정보를 읽지 못했습니다 (ffprobe 결과가 예상과 다름): {path}\n{exc!r}\n"
                           f"{traceback.format_exc()}") from exc


def _merge_input_from_probe(path, info):
    """ffprobe JSON → MergeInput (probe_merge_input)."""
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and s.get("disposition", {}).get("attached_pic") != 1), None)
    if video is None:
        raise RuntimeError(f"병합할 수 없는 파일 — 영상(그림) 트랙이 없습니다: {path}")
    if not video.get("width") or not video.get("height"):
        raise RuntimeError(f"병합할 수 없는 파일 — 영상 크기를 알 수 없습니다: {path}")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = _seconds(video.get("duration")) or _seconds(info.get("format", {}).get("duration"))
    if duration is None:
        raise RuntimeError(f"병합할 수 없는 파일 — 영상 길이를 알 수 없습니다: {path}")
    rate = pick_frame_rate(video.get("r_frame_rate"), video.get("avg_frame_rate"))
    if rate is None:
        raise RuntimeError(f"병합할 수 없는 파일 — 프레임 속도를 알 수 없습니다 (r_frame_rate "
                           f"{video.get('r_frame_rate')}, avg_frame_rate {video.get('avg_frame_rate')}): {path}")
    width, height = _display_size(video)
    # ffmpeg는 파일마다 형식의 시작(가장 이른 트랙)을 빼고 읽음 → 첫 그림의 시각도 그 기준으로
    start = _start_seconds(video.get("start_time")) - _start_seconds(info.get("format", {}).get("start_time"))
    return MergeInput(path=path, video_index=video["index"], audio_index=audio["index"] if audio else None,
                      width=width, height=height, rate=rate, duration=duration, start=start,
                      sample_rate=int(audio["sample_rate"]) if audio else None)


def merge_filter_graph(inputs):
    """병합 필터 그래프. 크기·프레임 속도는 첫 파일(크기는 보이는 크기를 짝수로 내림), 소리는 소리가 있는 첫 파일의
    샘플레이트·스테레오. 크기가 다르면 비율을 지켜 줄이고 남는 곳은 검은 띠, 화소 비율은 정사각형으로.
    컷은 첫 그림부터 (영상 시작을 0으로, 소리도 같은 만큼 옮겨 컷 안의 싱크를 지킴 — 늦게 시작하는 소리는 앞을 무음,
    그림 앞의 소리는 버림). 영상은 그 길이에서 자름 (편집 목록이 마지막 프레임보다 먼저 끝나는 파일), 소리는 파일마다
    그 영상 길이로 (짧으면 무음으로 채우고 길면 자름 — 컷 경계가 프레임에 맞게), 소리가 없는 파일은 그 영상 길이만큼
    무음. 어느 파일에도 소리가 없어도 컷마다 무음을 두고 버림 ([a]anullsink — 영상만인 컷은 concat이 길이를 프레임
    간격으로 짐작해 1프레임 컷이 0이 됨). 영상·소리만 이음 (타임코드·데이터 트랙은 버림)."""
    width, height = inputs[0].width // 2 * 2, inputs[0].height // 2 * 2
    rate = inputs[0].rate
    sample_rate = next((i.sample_rate for i in inputs if i.audio_index is not None), None)
    silent_rate = sample_rate or 48000  # 소리가 없는 병합: 내보내지 않는 무음
    chains, pads = [], []
    for n, item in enumerate(inputs):
        chains.append(f"[{n}:{item.video_index}]setpts=PTS-STARTPTS,scale=trunc(iw*sar/2)*2:ih,setsar=1,"
                      f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                      f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                      f"fps={rate.numerator}/{rate.denominator},format=yuv420p,trim=end={item.duration:.6f}[v{n}]")
        pads.append(f"[v{n}]")
        if item.audio_index is not None:
            chains.append(f"[{n}:{item.audio_index}]asetpts=PTS-({item.start:.6f})/TB,aresample=async=1:first_pts=0,"
                          f"aformat=sample_fmts=fltp:sample_rates={sample_rate}:channel_layouts=stereo,"
                          f"apad,atrim=end={item.duration:.6f}[a{n}]")
        else:
            chains.append(f"anullsrc=r={silent_rate}:cl=stereo,atrim=duration={item.duration:.6f}[a{n}]")
        pads.append(f"[a{n}]")
    chains.append(f"{''.join(pads)}concat=n={len(inputs)}:v=1:a=1[v][a]")
    if sample_rate is None:
        chains.append("[a]anullsink")
    return ";\n".join(chains)


def _merge_command(ffmpeg, file_paths, graph_path, output_path, with_audio):
    """병합 ffmpeg 명령. 필터 그래프는 파일로 넘김 (명령 줄은 -i 경로만큼만 길어짐)."""
    cmd = [ffmpeg, "-y"]
    for path in file_paths:
        cmd += ["-i", path]
    cmd += ["-/filter_complex", graph_path, "-map", "[v]"]
    if with_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    return cmd + ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
                  "-movflags", "faststart", "-f", "mov", output_path]


def _ensure_open_file_limit(input_count):
    """(Mac·Linux) concat 필터는 입력을 한꺼번에 엶 → 열린 파일 한도(Finder로 켠 Mac 앱은 256)가 모자라면 이 프로세스의
    한도를 올림 (병합 ffmpeg가 물려받음 — 스레드가 많은 앱이라 preexec_fn은 쓰지 않음). 올리지 못하면 RuntimeError."""
    import resource  # Windows에는 없음

    needed = input_count + MERGE_FD_HEADROOM
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft == resource.RLIM_INFINITY or soft >= needed:
        return
    failure = ""
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE,
                           (needed if hard == resource.RLIM_INFINITY else min(hard, needed), hard))
    except (ValueError, OSError) as exc:  # macOS: kern.maxfilesperproc보다 크면 거절
        failure = f" — 한도를 올리지 못했습니다: {exc}"
    soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    if soft < needed:
        raise RuntimeError(
            f"한 번에 합칠 수 있는 파일 수({max(soft - MERGE_FD_HEADROOM, 0)}개)를 넘었습니다 — 나눠서 합치세요 "
            f"(합칠 파일 {input_count}개, 열린 파일 한도 {soft}개, 필요 {needed}개){failure}")


def merge_tolerance(input_count, fps):
    """병합 결과 영상 길이의 허용 오차(초): 이음매마다 한 프레임 + MERGE_SLACK_SECONDS."""
    return input_count / fps + MERGE_SLACK_SECONDS


def check_merged_output(inputs, output_path, video_duration, frames, audio_duration):
    """병합 결과가 입력과 맞는지 (subprocess 없음). 영상 길이 = 입력 영상 길이의 합 (± merge_tolerance),
    프레임 수 = Σ floor(영상 길이 × 프레임 속도) - MERGE_FRAME_SLACK ~ Σ ceil(…) + MERGE_FRAME_SLACK
    (길이는 맞는데 그림이 멈춘 결과도 잡음),
    입력에 소리가 있으면 결과에도 소리가 있고 영상보다 AUDIO_OVERRUN_LIMIT초 넘게 길지 않음.
    틀리면 RuntimeError (입력별 길이, 예상 합계, 결과의 영상 길이·프레임 수·소리 길이)."""
    expected = sum(i.duration for i in inputs)
    fps = float(inputs[0].rate)
    tolerance = merge_tolerance(len(inputs), fps)
    # 1e-3: 23.976 fps처럼 길이 × 속도가 정수에서 아주 조금 어긋나는 것 (부동소수점)
    lowest = sum(math.floor(i.duration * fps + 1e-3) for i in inputs) - MERGE_FRAME_SLACK
    highest = sum(math.ceil(i.duration * fps - 1e-3) for i in inputs) + MERGE_FRAME_SLACK
    with_audio = any(i.audio_index is not None for i in inputs)
    if video_duration is None:
        problem = "결과에 영상 트랙이 없거나 길이를 알 수 없습니다"
    elif abs(video_duration - expected) > tolerance:
        problem = f"영상 길이가 입력 영상 길이의 합과 다릅니다 (허용 ±{tolerance:.3f}초)"
    elif frames is None:
        problem = "결과의 프레임 수를 알 수 없습니다"
    elif not lowest <= frames <= highest:
        problem = f"프레임 수가 예상 범위({lowest}~{highest})를 벗어났습니다"
    elif with_audio and audio_duration is None:
        problem = "결과에 소리 트랙이 없거나 길이를 알 수 없습니다"
    elif with_audio and audio_duration > video_duration + AUDIO_OVERRUN_LIMIT:
        problem = f"소리가 영상보다 {AUDIO_OVERRUN_LIMIT:g}초 넘게 깁니다"
    else:
        return

    def seconds(value):
        return "없음" if value is None else f"{value:.3f}초"

    listing = "\n".join(f"  {seconds(i.duration)}  {i.path}" for i in inputs)
    raise RuntimeError(
        f"병합 결과가 잘못되었습니다 — {problem}\n출력: {output_path}\n"
        f"입력 {len(inputs)}개 (영상 길이):\n{listing}\n예상 합계: {seconds(expected)}\n"
        f"결과: 영상 {seconds(video_duration)} ({'?' if frames is None else frames} 프레임, "
        f"예상 {lowest}~{highest} 프레임), 소리 {seconds(audio_duration)}"
    )


def merge_videos_ffmpeg(ffmpeg, file_paths, output_path, on_progress=None, register_process=None):
    """여러 영상을 하나로 합칩니다 (concat 필터 + libx264). 트랙은 번호가 아니라 종류로 이음 (파일마다 트랙 순서가
    달라도 됨), 크기·프레임 속도·소리 형식은 첫 파일에 맞춤. 합친 뒤 결과 길이·프레임 수를 확인하고, 틀리면 결과
    파일을 지움. 실패하면 RuntimeError (stderr 포함).

    register_process(proc): ffprobe·ffmpeg를 띄울 때마다 불림 → 부른 쪽이 proc.kill()로 병합을 멈출 수 있음 (창 닫기).
    """
    temp_dir = tempfile.mkdtemp(prefix="yesoncheck_merge_")
    try:
        graph_path = os.path.join(temp_dir, "filter_graph.txt")
        if IS_WINDOWS:  # 파일을 하나씩 읽기 전에 (소리가 있는 긴 쪽 명령으로)
            length = len(subprocess.list2cmdline(_merge_command(ffmpeg, file_paths, graph_path, output_path, True)))
            if length > WINDOWS_COMMAND_LIMIT:
                raise RuntimeError(
                    f"합칠 파일이 너무 많습니다 ({len(file_paths)}개) — ffmpeg 명령 줄이 {length}자로 Windows 한도"
                    f"(약 {WINDOWS_COMMAND_LIMIT:,}자)를 넘습니다. 한 번에 합칠 파일 수를 줄이세요.")
        else:
            _ensure_open_file_limit(len(file_paths))
        ffprobe = ffprobe_path()
        inputs = [probe_merge_input(ffprobe, path, register_process) for path in file_paths]
        with open(graph_path, "w", encoding="utf-8") as fh:
            fh.write(merge_filter_graph(inputs))
        with_audio = any(i.audio_index is not None for i in inputs)
        if on_progress:
            on_progress(50)
        cmd = _merge_command(ffmpeg, file_paths, graph_path, output_path, with_audio)
        code, _, stderr = _communicate(cmd, register_process, stdout=subprocess.DEVNULL)
        if code != 0:
            raise RuntimeError(
                f"ffmpeg 병합 실패 (종료 코드 {code})\n명령: {' '.join(cmd)}\n{decode_output(stderr)[-4000:]}"
            )
        # ffmpeg가 0으로 끝나도 결과가 틀릴 수 있음 (예전: 트랙 순서가 다른 파일 → 영상이 첫 파일에서 멈춤)
        streams = _probe(ffprobe, output_path, register_process).get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        try:
            check_merged_output(
                inputs, output_path,
                _seconds(video.get("duration")) if video else None,
                int(video["nb_frames"]) if video and str(video.get("nb_frames", "")).isdigit() else None,
                _seconds(audio.get("duration")) if audio else None,
            )
        except RuntimeError as exc:  # 틀린 것이 확실한 파일은 남기지 않음 (지우지 못하면 그 오류도 알림)
            try:
                os.remove(output_path)
                removed = f"잘못된 결과 파일은 지웠습니다: {output_path}"
            except OSError as remove_error:
                removed = f"잘못된 결과 파일을 지우지 못했습니다: {output_path} — {remove_error}"
            raise RuntimeError(
                f"{exc}\n{removed}\n명령: {' '.join(cmd)}\n{decode_output(stderr)[-4000:]}"
            ) from exc
        if on_progress:
            on_progress(100)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
