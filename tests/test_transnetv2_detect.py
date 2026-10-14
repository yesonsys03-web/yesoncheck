"""애니매틱2(TransNetV2 + TensorFlow): 빌드 환경에서 실제로 컷을 찾는지, 그리고 앱 시작 경로가 TensorFlow를 불러오지 않는지.

TensorFlow와 가중치(vendor/transnetv2-weights)는 빌드 환경에 반드시 있어야 하므로 건너뛰지 않는다 (없으면 실패).
"""

import json
import os
import subprocess
import sys

import pytest

from tests.conftest import ROOT
from tests.test_work_paths_ui import make_config

from yesoncheck import transnetv2_detector
from yesoncheck.smoke_test import THREE_SHOT_STARTS, write_three_shot_clip


def test_build_environment_has_tensorflow_and_weights():
    assert transnetv2_detector.transnetv2_missing() == []
    assert transnetv2_detector.TRANSNETV2_AVAILABLE is True
    assert transnetv2_detector.transnetv2_weights_dir() == os.path.join(ROOT, "vendor", "transnetv2-weights")


def test_detects_three_shot_clip_and_reuses_model(tmp_path, capsys, monkeypatch):
    """합성 3샷 영상(30프레임씩)에서 앱과 같은 설정으로 씬 시작 [0, 30, 60]을 찾음 (실제 TensorFlow 추론, 약 10초).
    두 번째 실행은 이 프로세스에서 이미 불러온 모델을 다시 씀 (약 4초 걸리는 모델 불러오기를 건너뜀)."""
    monkeypatch.setattr(transnetv2_detector, "_MODELS", {})  # 다른 시험이 불러 둔 모델과 상관없이 '처음'부터
    weights_dir = transnetv2_detector.transnetv2_weights_dir()
    assert transnetv2_detector.transnetv2_model_loaded() is False
    clip = write_three_shot_clip(str(tmp_path / "three_shots.mp4"))
    settings = dict(threshold=0.3, min_scene_len=10, detect_gradual_transitions=True, post_process_histogram=True)

    segments = transnetv2_detector.detect_scene_cuts_transnetv2(clip, **settings)
    assert [s["start_frame"] for s in segments] == THREE_SHOT_STARTS
    assert [s["end_frame"] for s in segments] == [29, 59, 89]
    out = capsys.readouterr().out
    # 시간 기록: TensorFlow·모델을 불러오는 단계 앞뒤로 남김 (멈추면 마지막 줄이 그 단계를 가리킴)
    for message in ("TensorFlow 불러오는 중…", "TensorFlow 불러옴 (", "TransNetV2 모델 불러오는 중…", "TransNetV2 모델 불러옴 ("):
        assert message in out, out
    assert transnetv2_detector.transnetv2_model_loaded() is True
    model = transnetv2_detector._MODELS[weights_dir]

    segments = transnetv2_detector.detect_scene_cuts_transnetv2(clip, **settings)
    assert [s["start_frame"] for s in segments] == THREE_SHOT_STARTS
    out = capsys.readouterr().out
    assert "TransNetV2 모델 다시 씀" in out, out
    assert "TransNetV2 모델 불러오는 중…" not in out and "TensorFlow 불러오는 중…" not in out, out
    assert transnetv2_detector._MODELS == {weights_dir: model}  # 같은 모델 객체 하나만


_STARTUP_CODE = r"""
import json
import sys

sys.path.insert(0, sys.argv[1])
import yesoncheck.transnetv2_detector
import yesoncheck.workers
import yesoncheck.player_base

after_imports = "tensorflow" in sys.modules
from PyQt5.QtWidgets import QApplication

app = QApplication([])
from yesoncheck.main_window import VideoPlayer

player = VideoPlayer()
player.show()
app.processEvents()
print("REPORT " + json.dumps({
    "after_imports": after_imports,
    "after_window": "tensorflow" in sys.modules,
    "animatic2_index": player.ocrModeComboBox.findData("animatic2"),
}))
player.close()
"""


def test_startup_does_not_import_tensorflow(tmp_path):
    """workers·player_base를 불러오고 창(VideoPlayer)을 만들어도 TensorFlow는 불리지 않아야 함 (시작이 느려지지 않게).

    pytest 프로세스는 다른 시험이 이미 TensorFlow를 불렀을 수 있으므로 새 파이썬 프로세스에서 확인한다.
    """
    # PYTHONIOENCODING: 자식 프로세스의 한글 출력을 utf-8로 (Windows 기본 코드 페이지에서도 읽을 수 있게)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8",
               YESONCHECK_CONFIG_DIR=make_config(str(tmp_path), {}))
    result = subprocess.run([sys.executable, "-c", _STARTUP_CODE, ROOT], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    # 창을 닫을 때 다른 줄도 찍히므로 표시한 줄만 읽음
    lines = [line for line in result.stdout.splitlines() if line.startswith("REPORT ")]
    assert len(lines) == 1, result.stdout
    report = json.loads(lines[0][len("REPORT "):])
    assert report["after_imports"] is False, report
    assert report["after_window"] is False, report
    assert report["animatic2_index"] >= 0, report  # TensorFlow를 불러오지 않고도 항목은 보임


# ---------------------------------------------------------------------------
# x86 CPU에 AVX가 없으면 TensorFlow 2.15 x86 빌드는 import할 때 파이썬 예외 없이 죽음(SIGILL/abort)
# → TensorFlow를 불러오지 않고 numpy의 CPU 기능 표로 확인해 애니매틱2를 숨김
# ---------------------------------------------------------------------------

def test_x86_cpu_without_avx_is_reported_missing(monkeypatch):
    monkeypatch.setattr(transnetv2_detector.platform, "machine", lambda: "AMD64")  # Windows의 x86_64 표기
    monkeypatch.setattr(transnetv2_detector, "cpu_features", lambda: {"AVX": False, "SSE2": True})
    missing = transnetv2_detector.transnetv2_missing()
    assert len(missing) == 1 and "AVX" in missing[0], missing


def test_x86_cpu_with_avx_is_fine(monkeypatch):
    monkeypatch.setattr(transnetv2_detector.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(transnetv2_detector, "cpu_features", lambda: {"AVX": True})
    assert transnetv2_detector.transnetv2_missing() == []


def test_arm64_does_not_need_avx(monkeypatch):
    """arm64 TensorFlow는 AVX와 무관 (numpy 표에 AVX 항목이 없어도 확인하지 않음)."""
    monkeypatch.setattr(transnetv2_detector.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(transnetv2_detector, "cpu_features", lambda: {})
    assert transnetv2_detector.transnetv2_missing() == []


def test_detection_refuses_without_avx(tmp_path, monkeypatch):
    """감지 함수도 TensorFlow를 불러오기 전에 이유와 함께 실패 (조용히 죽지 않게)."""
    monkeypatch.setattr(transnetv2_detector.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(transnetv2_detector, "cpu_features", lambda: {"AVX": False})
    clip = write_three_shot_clip(str(tmp_path / "three_shots.mp4"))
    with pytest.raises(RuntimeError, match="AVX"):
        transnetv2_detector.detect_scene_cuts_transnetv2(clip)


def test_real_cpu_features_answer_avx_on_x86():
    """이 빌드 PC의 numpy가 CPU 기능 표를 주는지 (x86이면 AVX 항목이 있어야 함)."""
    features = transnetv2_detector.cpu_features()
    if transnetv2_detector.platform.machine().lower() in transnetv2_detector.X86_MACHINES:
        assert "AVX" in features, sorted(features)


def test_concurrent_first_loads_build_one_model(monkeypatch):
    """두 워커가 동시에 처음 불러도 모델은 한 번만 만듦 (잠금). TensorFlow 대신 느린 가짜 로더로 확인."""
    import threading
    import time
    import types

    built = []

    class SlowTransNetV2:
        def __init__(self, model_dir):
            time.sleep(0.3)
            built.append(model_dir)

    monkeypatch.setitem(sys.modules, "yesoncheck.transnetv2_model", types.SimpleNamespace(TransNetV2=SlowTransNetV2))
    monkeypatch.setattr(transnetv2_detector, "_MODELS", {})
    results, logs = [], []
    threads = [
        threading.Thread(target=lambda: results.append(transnetv2_detector.load_transnetv2_model("/w", logs.append)))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert built == ["/w"], built
    assert len(results) == 2 and results[0] is results[1]
    assert sum(line.startswith("TransNetV2 모델 다시 씀") for line in logs) == 1, logs
