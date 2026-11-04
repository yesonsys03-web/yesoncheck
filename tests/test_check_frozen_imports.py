"""check_frozen_imports.py의 별칭 규칙: 같은 파일이 다른 이름으로도 등록된 TensorFlow 모듈
(tensorflow.compat.v1 ↔ 실제 파일 tensorflow/_api/v2/compat/v1/__init__.py)만, 실제 이름이 앱(PYZ)에 있을 때 통과.
이미지 시퀀스 프레임 디코딩 실행(exercise_sequence_decode): PIL의 지연 import 플러그인이 '실행에 쓰인 모듈'에 잡히는지.
cv2에 OpenEXR 코덱이 꺼진 환경(Windows 휠의 기본)에서는 EXR을 건너뛰고 TGA만 확인하며 그 사실을 결과에 적음.
소스 import 모음(source_imports): `from yesoncheck import X`의 X 모듈도 모아 함수 안에서만 부르는 모듈(mac_native_source)도 대조됨.
네이티브 디코드 실행(exercise_native_decode): Apple Silicon에서만 번들 ffmpeg로 만든 4K 4444 클립을 NativeVTCapture로 3장 읽어 네이티브
재생 길을 실제로 돌리고(그 밖의 플랫폼은 NATIVE_SKIPPED 한 줄), 틀린 프레임·게이트 음성·번들 ffmpeg 없음은 SystemExit. 가짜
arm64(platform.machine·sys.platform 바꿔치기) + 가짜 캡처·클립·probe로 PyObjC 없이 어느 플랫폼에서나 돌고, 진짜 디코드는 PyObjC가 있는
환경(p310_native·arm64 CI)에서."""

import glob
import os
import platform
import re
import subprocess
import sys
from fractions import Fraction

import numpy as np
import pytest

import check_frozen_imports as cfi
# sys.platform을 바꿔치기하는 시험보다 먼저 불러 둠: 모듈 수준에서 플랫폼을 읽는 것(external_tools.IS_WINDOWS 등)이 바뀐 값으로 굳지 않게
from yesoncheck import mac_native_gate, mac_native_source, movie_pipe_source
from yesoncheck.frame_handles import NativeHandle, wrap_native
from yesoncheck.sequence_source import exr_supported

SITE = sorted(cfi.SITE_DIRS)[0]


def site_path(*parts):
    return os.path.join(SITE, *parts)


def test_tensorflow_compat_alias_accepted_when_real_name_is_in_app():
    path = site_path("tensorflow", "_api", "v2", "compat", "v1", "__init__.py")
    modules = {"tensorflow._api.v2.compat.v1"}
    assert cfi.tensorflow_alias_of("tensorflow.compat.v1", path, modules) == "tensorflow._api.v2.compat.v1"


def test_tensorflow_alias_rejected_when_real_name_missing_from_app():
    path = site_path("tensorflow", "_api", "v2", "compat", "v1", "__init__.py")
    assert cfi.tensorflow_alias_of("tensorflow.compat.v1", path, set()) is None


def test_alias_rule_only_for_tensorflow_namespace():
    """tensorflow 밖의 모듈은 경로가 다른 실제 이름을 가리켜도 받아 주지 않음 (진짜 누락을 가리지 않게)."""
    path = site_path("urllib3", "__init__.py")
    assert cfi.tensorflow_alias_of("requests.packages.urllib3", path, {"urllib3"}) is None
    assert cfi.tensorflow_alias_of("tensorflow_io_gcs_filesystem", site_path("x", "__init__.py"), {"x"}) is None


def test_same_name_is_not_an_alias():
    path = site_path("tensorflow", "python", "__init__.py")
    assert cfi.tensorflow_alias_of("tensorflow.python", path, {"tensorflow.python"}) is None


def test_source_imports_name_submodules_of_package_imports(tmp_path, monkeypatch):
    """`from yesoncheck import X`에서 X가 이 패키지의 모듈 파일이면 X도 이름으로 모음 — 함수 안의 지연 import는 그 함수가 돌지 않으면 X를
    불러오지 않아 '실행에 쓰인 모듈'에 안 잡히고 앱에 빠져도 모름. 모듈이 아닌 이름(상수 등)은 넣지 않음 (import 실패로 건너뜀 목록이 늘지 않게)."""
    pkg = tmp_path / "yesoncheck"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "lazy.py").write_text("", encoding="utf-8")
    (pkg / "user.py").write_text("def open_it():\n    from yesoncheck import lazy, NOT_A_MODULE\n", encoding="utf-8")
    monkeypatch.setattr(cfi, "PROJECT_ROOT", str(tmp_path))
    assert cfi.source_imports() == ["yesoncheck", "yesoncheck.lazy"]


def test_source_imports_name_every_package_module():
    """yesoncheck/ 바로 아래 모든 모듈이 source_imports()에 이름으로 있음 → exercise_app이 하나하나 불러 앱 안에 있는지 대조함 (CLAUDE.md의
    '평면 모듈은 spec에 따로 적지 않아도 됨'의 근거). 위 규칙이 없으면 빠지는 것: mac_native_source (player_playback이 함수 안에서만
    `from yesoncheck import mac_native_source` — Intel·Windows 빌드 검사가 그 모듈이 앱에 있는지 보지 않았음)."""
    modules = {f"yesoncheck.{os.path.basename(path)[:-3]}" for path in glob.glob(os.path.join(cfi.PROJECT_ROOT, "yesoncheck", "*.py"))
               if os.path.basename(path) != "__init__.py"}
    assert "yesoncheck.mac_native_source" in modules
    assert modules - set(cfi.source_imports()) == set()


def test_sequence_decode_exercise_pulls_in_the_tga_plugin():
    """PIL 플러그인은 지연 import라, 디코딩을 실제로 실행해야 PIL.TgaImagePlugin이 '쓰인 모듈'에 올라 앱 안에 있는지 대조된다.
    새 인터프리터에서 실행 전에는 없고 실행 뒤에는 있어야 함 (이 프로세스는 다른 시험이 이미 불러왔을 수 있음)."""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {cfi.PROJECT_ROOT!r})\n"
        "import check_frozen_imports as cfi\n"
        "assert 'PIL.TgaImagePlugin' not in sys.modules\n"
        "decoded = cfi.exercise_sequence_decode()\n"
        "from yesoncheck import sequence_source\n"
        "print(sequence_source.exr_supported())\n"
        "print(sorted(decoded))\n"
        "print('PIL.TgaImagePlugin' in sys.modules)\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr
    supported, decoded, plugin_loaded = proc.stdout.strip().splitlines()
    if sys.platform == "darwin":
        assert supported == "True", "Mac의 cv2는 EXR을 다룰 수 있어야 함 (조용히 건너뛰지 않게)"
    # EXR을 다룰 수 있는 환경(Mac 등)은 둘 다, 코덱이 꺼진 환경은 TGA만 하고 건너뛴 사실을 적음
    assert decoded == str(sorted(["exr", "tga"] if supported == "True" else ["tga", cfi.EXR_SKIPPED]))
    assert plugin_loaded == "True"


def test_sequence_decode_exercise_skips_exr_when_the_codec_is_disabled(monkeypatch):
    """OpenEXR이 꺼진 cv2에서는 EXR을 건너뜀 (빌드를 실패시키지 않음) — 건너뛴 사실은 결과 목록에 남고 EXR 디코딩은 부르지 않는다."""
    import yesoncheck.sequence_source as sequence_source

    real, asked = sequence_source.decode_frame, []

    def spy(data, ext):
        asked.append(ext)
        return real(data, ext)

    monkeypatch.setattr(sequence_source, "exr_supported", lambda: False)
    monkeypatch.setattr(sequence_source, "decode_frame", spy)
    assert cfi.exercise_sequence_decode() == ["tga", cfi.EXR_SKIPPED]
    assert asked == ["tga"]
    assert "건너뜀" in cfi.EXR_SKIPPED and "OpenEXR" in cfi.EXR_SKIPPED


def test_sequence_decode_exercise_fails_loudly_on_a_wrong_decode(monkeypatch):
    """디코딩 결과가 기대와 다르면 검사를 실패로 끝냄 (조용히 넘기지 않음)."""
    import yesoncheck.sequence_source as sequence_source

    monkeypatch.setattr(sequence_source, "decode_frame", lambda data, ext: np.zeros((4, 8, 3), np.uint8))
    with pytest.raises(SystemExit) as exc:
        cfi.exercise_sequence_decode()
    assert "TGA" in str(exc.value)


@pytest.mark.skipif(not exr_supported(), reason="cv2 OpenEXR 비활성(이 플랫폼 휠)")
def test_sequence_decode_exercise_checks_the_exr_result_too(monkeypatch):
    """EXR 디코딩이 틀려도 실패 (TGA만 맞고 cv2의 EXR 경로가 깨진 환경)."""
    import yesoncheck.sequence_source as sequence_source

    real = sequence_source.decode_frame
    monkeypatch.setattr(sequence_source, "decode_frame",
                        lambda data, ext: real(data, ext) if ext == "tga" else np.zeros((4, 8, 3), np.uint8))
    with pytest.raises(SystemExit) as exc:
        cfi.exercise_sequence_decode()
    assert "EXR" in str(exc.value)


def test_sequence_decode_exercise_lets_a_decoder_error_through(monkeypatch):
    """TGA 플러그인이 없는 앱처럼 디코더가 오류를 내면 그 오류(스택 트레이스째)가 그대로 올라옴."""
    import yesoncheck.sequence_source as sequence_source

    def broken(data, ext):
        raise ValueError("이미지 프레임을 디코딩하지 못했습니다: cannot identify image file")

    monkeypatch.setattr(sequence_source, "decode_frame", broken)
    with pytest.raises(ValueError, match="디코딩하지 못했습니다"):
        cfi.exercise_sequence_decode()


# ---------------------------------------------------------------- 네이티브 디코드 (exercise_native_decode)

NATIVE_WIDTH, NATIVE_HEIGHT = cfi.NATIVE_CLIP_SIZE
REAL_FFMPEG_DIR = cfi.vendored_ffmpeg_dir()  # 이 기계의 번들 ffmpeg 폴더 — platform.machine()을 바꿔치기하기 전에 구함


def eligible_probe(**changes):
    """네이티브 게이트를 통과하는 4K ProRes 4444 bt709 6장 probe (실제 클립의 ffprobe 값 모양 — 번들 ffmpeg 9.0.2가 만든 것)."""
    values = dict(codec="prores", width=NATIVE_WIDTH, height=NATIVE_HEIGHT, r=Fraction(24), avg=Fraction(24),
                  nb_frames=cfi.NATIVE_CLIP_FRAMES, duration_ts=3072, time_base=Fraction(1, 12288), video_start=0.0,
                  format_start=0.0, rotation=0, sar_ok=True, pix_fmt="yuv444p12le", color_space="bt709", color_range="tv",
                  codec_tag="ap4h")
    values.update(changes)
    return movie_pipe_source.MovieProbe(**values)


def fake_native_frames(count, start=0, constant=False, width=NATIVE_WIDTH, height=NATIVE_HEIGHT):
    """가짜 NativeFrameArray count장 (PyObjC 없이): 진짜 frame_handles.wrap_native로 손잡이(번호 start부터)를 단 BGRX 뷰(기본 4K) — IOSurface처럼
    행 끝 패딩이 있는 읽기 전용 버퍼. 메모리를 아끼려고 모든 행이 한 행을 함께 씀(행 간격 0 — tests/native_fakes.spy_frames와 같은 수;
    모양·strides는 표면 전체 그대로라 whole_surface_handle이 통과). constant면 모든 픽셀이 같은 색(빈 프레임 — 채널마다 값은 다름)."""
    row_bytes = width * 4 + 64
    row = np.zeros(row_bytes, np.uint8)
    xs = np.arange(width)
    pixels = row[: width * 4].reshape(width, 4)
    pixels[:] = (40, 80, 120, 255) if constant else np.stack([xs % 256, (xs * 3) % 256, (xs * 7) % 256, np.full(width, 255)], axis=1)
    raw = np.lib.stride_tricks.as_strided(row, (height, row_bytes), (0, 1), writeable=False)
    return [wrap_native(raw, NativeHandle(iosurface=0x5EED0000 + i, width=width, height=height, index=start + i, keepalive=raw))
            for i in range(count)]


class FakeVTCapture:
    """NativeVTCapture 자리 (read·release·hardware_decode_supported만 — exercise_native_decode가 쓰는 낱말)."""

    def __init__(self, path, probe, results, hw):
        self.path, self.probe = path, probe
        self.results = list(results)
        self.hardware_decode_supported = hw
        self.reads = 0
        self.released = False

    def read(self):
        self.reads += 1
        return self.results.pop(0) if self.results else (False, None)

    def release(self):
        self.released = True


@pytest.fixture
def fake_arm64(monkeypatch, tmp_path):
    """가짜 Apple Silicon: sys.platform darwin·platform.machine arm64, 번들 ffmpeg 폴더는 빈 가짜 파일 둘, 클립 공장·ffprobe·캡처는 기록하는 가짜.
    rig.results(캡처의 read 결과 목록)·rig.hw·rig.probe를 바꾼 뒤 cfi.exercise_native_decode()를 부르면 됨."""
    folder = tmp_path / "vendor_ffmpeg"
    folder.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        (folder / name).write_bytes(b"")
    rig = type("Rig", (), {})()
    rig.folder = str(folder)
    rig.results = [(True, frame) for frame in fake_native_frames(cfi.NATIVE_READ_FRAMES)]
    rig.hw = False
    rig.probe = eligible_probe()
    rig.clips, rig.probed, rig.captures = [], [], []

    def make_clip(ffmpeg, path):
        rig.clips.append((ffmpeg, path, os.environ["PATH"].split(os.pathsep)[0]))
        with open(path, "wb") as fh:
            fh.write(b"clip")

    def probe(path):
        rig.probed.append(path)
        return rig.probe

    def capture(path, probe):
        cap = FakeVTCapture(path, probe, rig.results, rig.hw)
        rig.captures.append(cap)
        return cap

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(cfi, "vendored_ffmpeg_dir", lambda: rig.folder)
    monkeypatch.setattr(cfi, "make_native_clip", make_clip)
    # probe_movie가 읽는 이름은 movie_pipe_source에 있음 (CLAUDE.md 바꿔치기 규칙) — PATH 확인도 그 이름으로 함
    monkeypatch.setattr(movie_pipe_source, "ffprobe_path", lambda: os.path.join(rig.folder, "ffprobe"))
    monkeypatch.setattr(movie_pipe_source, "probe_movie", probe)
    monkeypatch.setattr(mac_native_source, "NativeVTCapture", capture)
    return rig


@pytest.mark.parametrize("system, machine", [("darwin", "x86_64"), ("win32", "AMD64"), ("win32", "ARM64"), ("linux", "aarch64")])
def test_frozen_check_skips_native_outside_arm64(monkeypatch, system, machine):
    """Apple Silicon Mac이 아니면(Intel Mac·Windows·Windows ARM·Linux ARM) 클립도 캡처도 만들지 않고 NATIVE_SKIPPED 한 줄을 돌려줌
    (main()이 결과 줄에 그대로 적음 — 건너뛴 사실이 보이게)."""
    def must_not_run(*args, **kwargs):
        raise AssertionError("Apple Silicon이 아닌데 네이티브 디코드를 시작했다")

    monkeypatch.setattr(sys, "platform", system)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    monkeypatch.setattr(cfi, "make_native_clip", must_not_run)
    monkeypatch.setattr(mac_native_source, "NativeVTCapture", must_not_run)
    assert cfi.exercise_native_decode() == cfi.NATIVE_SKIPPED
    assert cfi.NATIVE_SKIPPED == "네이티브 디코드 건너뜀 (Apple Silicon 아님)"


@pytest.mark.parametrize("hw, label", [(True, "yes"), (False, "no"), (None, "?")])
def test_frozen_check_runs_native_decode_on_arm64(fake_arm64, hw, label):
    """Apple Silicon: 번들 ffmpeg(PATH 맨 앞)로 임시 폴더에 클립 → 그 클립의 probe → 같은 probe 객체로 NativeVTCapture → 3장 읽고 release →
    결과 줄. PATH는 끝나면 되돌림."""
    fake_arm64.hw = hw
    path_before = os.environ["PATH"]
    result = cfi.exercise_native_decode()
    assert result == f"네이티브 디코드: VideoToolbox 3장 {NATIVE_WIDTH}×{NATIVE_HEIGHT} 32BGRA (hw={label})"
    assert os.environ["PATH"] == path_before
    [(ffmpeg, clip, path_head)] = fake_arm64.clips
    assert ffmpeg == os.path.join(fake_arm64.folder, "ffmpeg")
    assert path_head == fake_arm64.folder  # 클립을 만들고 probe하는 동안 번들 폴더가 PATH 맨 앞
    assert clip.endswith(".mov") and not os.path.exists(clip)  # 임시 폴더는 끝나면 지움
    assert fake_arm64.probed == [clip]
    [cap] = fake_arm64.captures
    assert (cap.path, cap.reads, cap.released) == (clip, cfi.NATIVE_READ_FRAMES, True)
    assert cap.probe is fake_arm64.probe


def wrong_frames():
    good = fake_native_frames(cfi.NATIVE_READ_FRAMES)
    return {
        "읽기 실패": [(True, good[0]), (False, None)],
        "모양(1080p 표면)": [(True, frame) for frame in fake_native_frames(cfi.NATIVE_READ_FRAMES, width=1920, height=1080)],
        "모양(3채널)": [(True, np.zeros((NATIVE_HEIGHT, NATIVE_WIDTH, 3), np.uint8))],
        "손잡이 없음(복사본)": [(True, np.array(good[0]))],
        "번호": [(True, frame) for frame in fake_native_frames(cfi.NATIVE_READ_FRAMES, start=1)],
        "한 색": [(True, frame) for frame in fake_native_frames(cfi.NATIVE_READ_FRAMES, constant=True)],
    }


@pytest.mark.parametrize("case", sorted(wrong_frames()))
def test_frozen_check_native_decode_fails_loudly_on_a_wrong_frame(fake_arm64, case):
    """프레임이 기대(4K (높이, 너비, 4) uint8 · 표면 전체의 IOSurface 손잡이 · 번호 0, 1, 2 · 한 색이 아님)와 다르면 검사 실패 (SystemExit —
    조용히 넘기지 않음). 실패해도 캡처는 release하고 PATH는 되돌림."""
    fake_arm64.results = wrong_frames()[case]
    path_before = os.environ["PATH"]
    with pytest.raises(SystemExit) as exc:
        cfi.exercise_native_decode()
    assert "네이티브 디코드" in str(exc.value)
    [cap] = fake_arm64.captures
    assert cap.released
    assert os.environ["PATH"] == path_before


def test_native_frame_problem_names_a_wrong_dtype():
    """모양은 4K BGRX인데 형이 uint8이 아니면 '모양·형' 사유에 그 형을 적음 — whole_surface_handle도 uint8만 받지만 그 사유('손잡이 없음')로
    넘기지 않음 (형 검사를 빼면 이 시험이 실패). 4K uint16 프레임은 broadcast_to로 메모리 없이."""
    frame = np.broadcast_to(np.zeros(4, np.uint16), (NATIVE_HEIGHT, NATIVE_WIDTH, 4))
    problem = cfi.native_frame_problem(True, frame, 0)
    assert problem == (f"0번째 프레임의 모양·형이 {frame.shape} uint16입니다 (기대 ({NATIVE_HEIGHT}, {NATIVE_WIDTH}, 4) uint8)")


def test_frozen_check_native_decode_fails_when_the_gate_rejects_the_clip(fake_arm64):
    """번들 ffmpeg가 만든 클립이 네이티브 게이트를 통과하지 못하면(예: 4:2:2) 캡처를 열지 않고 사유째 실패."""
    fake_arm64.probe = eligible_probe(pix_fmt="yuv422p10le")
    with pytest.raises(SystemExit, match="⑧ 4:4:4가 아님"):
        cfi.exercise_native_decode()
    assert fake_arm64.captures == []


def test_frozen_check_native_decode_lets_a_capture_error_through(fake_arm64, monkeypatch):
    """NativeVTCapture가 못 열면(NativeCaptureError — PyObjC 없음 등) 그 오류가 스택 트레이스째 그대로 올라옴 (검사 실패)."""
    def refuse(path, probe):
        raise mac_native_source.NativeCaptureError("AVFoundation으로 영상을 열지 못했습니다 — ModuleNotFoundError", path)

    monkeypatch.setattr(mac_native_source, "NativeVTCapture", refuse)
    with pytest.raises(mac_native_source.NativeCaptureError, match="AVFoundation"):
        cfi.exercise_native_decode()


@pytest.mark.parametrize("missing", ["ffmpeg", "ffprobe"])
def test_vendored_ffmpeg_missing_fails_loudly(fake_arm64, missing):
    """번들 ffmpeg·ffprobe가 없으면 그 경로를 든 SystemExit — PATH의 다른 ffmpeg로 조용히 대신하지 않음, PATH는 그대로."""
    os.remove(os.path.join(fake_arm64.folder, missing))
    path_before = os.environ["PATH"]
    with pytest.raises(SystemExit) as exc:
        cfi.exercise_native_decode()
    assert os.path.join(fake_arm64.folder, missing) in str(exc.value)
    assert fake_arm64.clips == [] and os.environ["PATH"] == path_before


def test_vendored_ffmpeg_must_be_the_one_the_app_finds(fake_arm64, monkeypatch):
    """PATH 맨 앞에 번들 폴더를 뒀는데도 앱 코드(movie_pipe_source.ffprobe_path)가 다른 ffprobe를 고르면 실패 (그 ffprobe로 probe하지 않음)."""
    monkeypatch.setattr(movie_pipe_source, "ffprobe_path", lambda: "/usr/local/bin/ffprobe")
    path_before = os.environ["PATH"]
    with pytest.raises(SystemExit, match="/usr/local/bin/ffprobe"):
        cfi.exercise_native_decode()
    assert fake_arm64.clips == [] and os.environ["PATH"] == path_before


def test_main_prints_the_native_result_in_the_summary_line(monkeypatch, capsys):
    """main()의 '앱 경로 실행:' 결과 줄에 네이티브 디코드 결과(실행했으면 그 줄, 아니면 건너뜀)가 시퀀스 디코딩 다음에 들어감."""
    monkeypatch.setattr(sys, "argv", ["check_frozen_imports.py", "dist/app"])
    monkeypatch.setattr(cfi, "exercise_app", lambda: (["Seq 02A"], [0, 30, 60], [], ["tga", "exr"], cfi.NATIVE_SKIPPED))
    monkeypatch.setattr(cfi, "frozen_contents", lambda bundle: (set(), set()))
    assert cfi.main() == 0
    summary = next(line for line in capsys.readouterr().out.splitlines() if line.startswith("앱 경로 실행:"))
    assert f"시퀀스 프레임 디코딩 ['tga', 'exr'], {cfi.NATIVE_SKIPPED}, 사용 모듈" in summary


@pytest.mark.skipif(sys.platform != "darwin", reason="번들 ffmpeg 폴더 vendor/ffmpeg/<machine>은 Mac 규칙 (Windows는 vendor/ffmpeg/windows)")
def test_native_clip_from_the_vendored_ffmpeg_passes_the_gate(tmp_path):
    """이 Mac의 진짜 번들 ffmpeg·ffprobe로: make_native_clip의 명령이 네이티브 게이트를 통과하는 4K 4444 6장 클립을 만들고, PATH를 바꾼 동안
    앱 코드가 그 ffprobe를 고름 (arm64 CI의 빌드 검사가 같은 명령을 씀)."""
    path = str(tmp_path / "native_4k_4444.mov")
    path_before = os.environ["PATH"]
    with cfi.vendored_ffmpeg_on_path() as ffmpeg:
        assert ffmpeg == os.path.join(REAL_FFMPEG_DIR, "ffmpeg")
        assert os.path.realpath(movie_pipe_source.ffprobe_path()) == os.path.realpath(os.path.join(REAL_FFMPEG_DIR, "ffprobe"))
        cfi.make_native_clip(ffmpeg, path)
        probe = movie_pipe_source.probe_movie(path)
    assert os.environ["PATH"] == path_before
    assert mac_native_gate.native_ineligible_reason(probe) is None, probe
    assert (probe.width, probe.height, probe.nb_frames, probe.codec_tag) == (NATIVE_WIDTH, NATIVE_HEIGHT, cfi.NATIVE_CLIP_FRAMES, "ap4h")


def test_native_decode_exercise_really_decodes(monkeypatch):
    """진짜 VideoToolbox(AVAssetReader) 디코드: 번들 ffmpeg 클립을 NativeVTCapture로 3장 — PyObjC가 있는 환경에서만(p310_native·arm64 CI).
    Intel Mac(p310_native)에서는 platform.machine만 arm64로 바꾸고 번들 폴더는 이 기계의 것을 씀 (VideoToolbox는 Intel에서도 ProRes를 디코드)."""
    pytest.importorskip("AVFoundation", reason="PyObjC 없음 — 진짜 네이티브 디코드는 p310_native·arm64 CI에서")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(cfi, "vendored_ffmpeg_dir", lambda: REAL_FFMPEG_DIR)
    result = cfi.exercise_native_decode()
    assert re.fullmatch(rf"네이티브 디코드: VideoToolbox 3장 {NATIVE_WIDTH}×{NATIVE_HEIGHT} 32BGRA \(hw=(yes|no|\?)\)", result), result
