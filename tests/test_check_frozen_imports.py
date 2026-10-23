"""check_frozen_imports.py의 별칭 규칙: 같은 파일이 다른 이름으로도 등록된 TensorFlow 모듈
(tensorflow.compat.v1 ↔ 실제 파일 tensorflow/_api/v2/compat/v1/__init__.py)만, 실제 이름이 앱(PYZ)에 있을 때 통과.
이미지 시퀀스 프레임 디코딩 실행(exercise_sequence_decode): PIL의 지연 import 플러그인이 '실행에 쓰인 모듈'에 잡히는지."""

import os
import subprocess
import sys

import numpy as np
import pytest

import check_frozen_imports as cfi

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


def test_sequence_decode_exercise_pulls_in_the_tga_plugin():
    """PIL 플러그인은 지연 import라, 디코딩을 실제로 실행해야 PIL.TgaImagePlugin이 '쓰인 모듈'에 올라 앱 안에 있는지 대조된다.
    새 인터프리터에서 실행 전에는 없고 실행 뒤에는 있어야 함 (이 프로세스는 다른 시험이 이미 불러왔을 수 있음)."""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {cfi.PROJECT_ROOT!r})\n"
        "import check_frozen_imports as cfi\n"
        "assert 'PIL.TgaImagePlugin' not in sys.modules\n"
        "decoded = cfi.exercise_sequence_decode()\n"
        "print(sorted(decoded), 'PIL.TgaImagePlugin' in sys.modules)\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "['exr', 'tga'] True"


def test_sequence_decode_exercise_fails_loudly_on_a_wrong_decode(monkeypatch):
    """디코딩 결과가 기대와 다르면 검사를 실패로 끝냄 (조용히 넘기지 않음)."""
    import yesoncheck.sequence_source as sequence_source

    monkeypatch.setattr(sequence_source, "decode_frame", lambda data, ext: np.zeros((4, 8, 3), np.uint8))
    with pytest.raises(SystemExit) as exc:
        cfi.exercise_sequence_decode()
    assert "TGA" in str(exc.value)


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
