import glob
import os
import sys

from tests.conftest import ROOT


def test_no_dev_debug_log_left():
    hits = []
    for path in glob.glob(os.path.join(ROOT, "yesoncheck", "*.py")):
        with open(path, encoding="utf-8") as fh:
            if ".cursor/debug.log" in fh.read():
                hits.append(path)
    assert hits == []


def test_paddleocr_dir():
    from yesoncheck import workers
    assert workers.paddleocr_base_dir("darwin", {}) is None
    assert workers.paddleocr_base_dir("win32", {"ProgramData": "C:\\ProgramData"}) == "C:\\ProgramData\\YesonCheck\\paddleocr\\"


def test_use_ascii_paddleocr_dir_patches_actual_module(monkeypatch, tmp_path):
    """BASE_DIR은 PaddleOCR.__module__로 찾아야 한다 (빌드된 Windows 앱에서는 paddleocr가
    패키지가 아니라 paddleocr.py 모듈 자체로 풀리므로 paddleocr.paddleocr로 고정하면 안 됨)."""
    from paddleocr import PaddleOCR

    from yesoncheck import workers

    target_module = sys.modules[PaddleOCR.__module__]
    fake_dir = str(tmp_path) + os.sep
    monkeypatch.setattr(workers, "paddleocr_base_dir", lambda: fake_dir)
    monkeypatch.setattr(target_module, "BASE_DIR", target_module.BASE_DIR)  # 원래 값 저장 → 자동 복원

    workers.use_ascii_paddleocr_dir()

    assert sys.modules[PaddleOCR.__module__].BASE_DIR == fake_dir


def test_windows_logging_only_when_frozen_windows(monkeypatch, tmp_path):
    from yesoncheck import app
    monkeypatch.setattr(app.sys, "platform", "darwin")
    assert app.setup_windows_logging() is None
