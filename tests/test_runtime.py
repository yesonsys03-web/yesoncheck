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


def _raise(message):
    try:
        raise RuntimeError(message)
    except RuntimeError:
        return sys.exc_info()


def test_excepthook_one_dialog_at_a_time(qapp, monkeypatch, capsys):
    """오류 창이 열려 있는 동안 난 예외(창 안의 이벤트 루프에서 또 던짐)는 창을 겹쳐 띄우지 않고 로그에만."""
    from PyQt5.QtWidgets import QMessageBox

    from yesoncheck import app

    hook = app.make_excepthook("C:\\logs\\yesoncheck.log")
    shown = []

    def fake_critical(parent, title, text, *args, **kwargs):
        shown.append(text)
        if len(shown) == 1:
            hook(*_raise("두번째 오류"))  # 창이 떠 있는 동안 같은 스레드에서 또 예외
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "critical", fake_critical)
    hook(*_raise("첫번째 오류"))
    assert len(shown) == 1
    assert "첫번째 오류" in shown[0] and "C:\\logs\\yesoncheck.log" in shown[0]
    logged = capsys.readouterr().err
    assert "첫번째 오류" in logged and "두번째 오류" in logged and "Traceback" in logged
    # 창이 닫힌 뒤의 예외는 다시 창으로
    hook(*_raise("세번째 오류"))
    assert len(shown) == 2 and "세번째 오류" in shown[1]


def test_excepthook_from_other_thread_shows_dialog_on_gui_thread(qapp, monkeypatch, capsys):
    """GUI 스레드가 아닌 곳의 예외: 그 스레드에서는 창을 만들지 않고, GUI 스레드에서 띄운다."""
    import threading

    from PyQt5.QtCore import QThread
    from PyQt5.QtWidgets import QMessageBox

    from yesoncheck import app

    hook = app.make_excepthook("log.txt")
    shown = []

    def fake_critical(parent, title, text, *args, **kwargs):
        shown.append((text, QThread.currentThread() is qapp.thread()))
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "critical", fake_critical)
    worker = threading.Thread(target=lambda: hook(*_raise("작업 스레드 오류")))
    worker.start()
    worker.join()
    assert shown == []  # 작업 스레드에서는 창을 띄우지 않음
    assert "작업 스레드 오류" in capsys.readouterr().err
    qapp.processEvents()
    assert len(shown) == 1
    text, on_gui_thread = shown[0]
    assert "작업 스레드 오류" in text and on_gui_thread
