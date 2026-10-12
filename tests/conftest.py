"""pytest 공통 설정: 프로젝트 루트를 import 경로에, Qt는 화면 없이, ffmpeg는 저장소의 정적 빌드."""

import os
import platform
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# fetch_ffmpeg.sh / fetch_ffmpeg_windows.ps1로 받은 정적 ffmpeg를 PATH 맨 앞에 둠
_FFMPEG_DIR = os.path.join(
    ROOT, "vendor", "ffmpeg", "windows" if sys.platform == "win32" else platform.machine()
)
if os.path.isdir(_FFMPEG_DIR):
    os.environ["PATH"] = _FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

import uuid
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialogs(monkeypatch):
    """QMessageBox·폴더 선택 창을 띄우지 않고 기록한다. folders에 넣어 둔 경로를 차례로 '고른다'."""
    from PyQt5.QtWidgets import QFileDialog, QInputDialog, QMessageBox

    rec = SimpleNamespace(messages=[], folders=[])

    def recorder(kind, answer):
        def fake(parent, title, text, *args, **kwargs):
            rec.messages.append((kind, title, text))
            return answer

        return fake

    monkeypatch.setattr(QMessageBox, "critical", recorder("critical", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "warning", recorder("warning", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "information", recorder("information", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", recorder("question", QMessageBox.Yes))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: rec.folders.pop(0) if rec.folders else "")

    def no_input(*args, **kwargs):
        raise AssertionError(f"시험 중 입력 창이 열렸습니다: {args[1:3]}")

    monkeypatch.setattr(QInputDialog, "getText", no_input)
    rec.errors = lambda: [m for m in rec.messages if m[0] in ("critical", "warning")]
    return rec


@pytest.fixture
def work_area(tmp_path):
    """작품 폴더를 만들 곳(local)과 그 폴더의 공유 설정용 경로(stored).

    Mac: tmp 폴더 그대로. Windows: CI 시험 공유(YC_TEST_SHARE_ROOT ↔ YC_TEST_UNC, Mac 경로 /Volumes/yc_test).
    """
    if sys.platform != "win32":
        return SimpleNamespace(local=str(tmp_path), stored=str(tmp_path), path_map=None)
    missing = [k for k in ("YC_TEST_SHARE_ROOT", "YC_TEST_UNC") if not os.environ.get(k)]
    if missing:
        pytest.fail(f"CI 시험 공유 환경 변수가 없습니다: {missing}")
    sub = "pytest_" + uuid.uuid4().hex[:8]
    local = os.path.join(os.environ["YC_TEST_SHARE_ROOT"], sub)
    os.makedirs(local)
    path_map = {"version": 1, "shares": [{"mac": "/Volumes/yc_test", "windows": [os.environ["YC_TEST_UNC"]]}]}
    return SimpleNamespace(local=local, stored=f"/Volumes/yc_test/{sub}", path_map=path_map)


def write_test_video(path, frames=24, size=(320, 240)):
    """OpenCV로 짧은 시험 영상 (ASCII 경로 전용: Windows의 cv2.VideoWriter는 한글 경로를 못 씀)."""
    import cv2
    import numpy as np

    os.makedirs(os.path.dirname(path), exist_ok=True)
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 24, size)
    assert writer.isOpened(), f"VideoWriter를 열 수 없습니다: {path}"
    for i in range(frames):
        writer.write(np.full((size[1], size[0], 3), (i * 10) % 255, np.uint8))
    writer.release()
    return path
