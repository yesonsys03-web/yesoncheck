"""Application entry helpers."""

import datetime
import os
import sys
import traceback

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QMessageBox, QSplashScreen

if __package__ in (None, ""):
    # Allow running the file directly (python yesoncheck/app.py)
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from yesoncheck.main_window import VideoPlayer  # type: ignore  # pylint: disable=import-error
else:
    from .main_window import VideoPlayer


def setup_windows_logging():
    """Windows 빌드 앱(창 모드): stdout·stderr가 없으므로 로그 파일로 보내고, 잡히지 않은 예외를 로그+오류 창으로.

    로그: %LOCALAPPDATA%\\YesonCheck\\logs\\yesoncheck_<날짜>.log. 그 외 환경에서는 아무것도 안 하고 None.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    log_dir = os.path.join(os.environ["LOCALAPPDATA"], "YesonCheck", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"yesoncheck_{datetime.date.today():%Y%m%d}.log")
    stream = open(log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = stream
    sys.stderr = stream
    print(f"===== YesonCheck 시작 {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====")

    def excepthook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        print(text, file=sys.stderr)
        if QApplication.instance() is not None:
            QMessageBox.critical(None, "YesonCheck 오류", f"{text[-3000:]}\n\n로그: {log_path}")

    sys.excepthook = excepthook
    return log_path


def launch(argv=None):
    """Create and run the QApplication event loop."""
    argv = list(sys.argv if argv is None else argv)

    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        # 고해상도 디스플레이 지원 (QApplication 생성 전에 설정해야 함)
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        app = QApplication(argv)

    # 스플래시 스크린 생성 (즉시 표시)
    pixmap = QPixmap(500, 300)
    pixmap.fill(Qt.black)
    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint | Qt.SplashScreen)
    splash.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.SplashScreen)
    
    # 스플래시 메시지 표시
    splash.showMessage("Yeson Checker\n로딩 중...", Qt.AlignCenter | Qt.AlignBottom, Qt.white)
    splash.show()
    app.processEvents()  # 즉시 화면 표시
    
    # 메인 윈도우 생성
    player = VideoPlayer()
    
    if len(argv) > 1:
        file_path = argv[1]
        print(f"Opening file: {file_path}")
        if os.path.isfile(file_path):
            player.open_file("A", file_path)
        else:
            print(f"File does not exist: {file_path}")
    
    # 메인 윈도우 표시 후 스플래시 닫기
    player.show()
    splash.finish(player)
    # 공유 설정 문제(설정 폴더·작품 경로·변환표)는 스플래시가 닫힌 뒤에 알림 (스플래시가 대화상자를 가리지 않게)
    QTimer.singleShot(0, player.resolve_shared_config_problem)

    if owns_app:
        return app.exec_()
    return 0


def main():
    """CLI entrypoint. --smoke-test <작업 폴더>: 실행 시험 (yesoncheck/smoke_test.py)."""
    setup_windows_logging()
    if len(sys.argv) >= 3 and sys.argv[1] == "--smoke-test":
        from yesoncheck.smoke_test import run

        return run(sys.argv[2])
    return launch(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
