"""Application entry helpers."""

import os
import sys

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtWidgets import QApplication, QSplashScreen, QLabel

if __package__ in (None, ""):
    # Allow running the file directly (python yesoncheck/app.py)
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from yesoncheck.main_window import VideoPlayer  # type: ignore  # pylint: disable=import-error
else:
    from .main_window import VideoPlayer


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
    """CLI entrypoint."""
    return launch(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
