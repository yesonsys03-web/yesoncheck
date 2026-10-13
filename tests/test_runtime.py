import glob
import os

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


def test_windows_logging_only_when_frozen_windows(monkeypatch, tmp_path):
    from yesoncheck import app
    monkeypatch.setattr(app.sys, "platform", "darwin")
    assert app.setup_windows_logging() is None
