"""Application entry helpers."""

import datetime
import os
import sys
import time
import traceback

from PyQt5.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont, QGuiApplication, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QMessageBox, QSplashScreen

if __package__ in (None, ""):
    # Allow running the file directly (python yesoncheck/app.py)
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from yesoncheck.main_window import VideoPlayer  # type: ignore  # pylint: disable=import-error
    from yesoncheck import mac_mounts, paths, timing_log  # type: ignore  # pylint: disable=import-error
    from yesoncheck.player_base import wait_for_released_workers  # type: ignore  # pylint: disable=import-error
else:
    from .main_window import VideoPlayer
    from . import mac_mounts, paths, timing_log
    from .player_base import wait_for_released_workers


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

    sys.excepthook = make_excepthook(log_path)
    return log_path


class _ErrorDialog(QObject):
    """잡히지 않은 예외의 오류 창. GUI 스레드에서만, 한 번에 하나만 띄운다.

    GUI 스레드에서 만들어야 함 (다른 스레드에서 보낸 requested가 GUI 스레드에서 처리되도록).
    """

    requested = pyqtSignal(str)

    def __init__(self, log_path):
        super().__init__()
        self.log_path = log_path
        self.is_open = False
        self.requested.connect(self.show_error)

    @pyqtSlot(str)
    def show_error(self, text):
        if self.is_open:
            # 창 안의 이벤트 루프에서 같은 오류가 또 나면(타이머 등) 창이 겹겹이 쌓이다 스택이 넘침 → 로그에만
            print("(오류 창이 이미 열려 있어 위 예외는 로그에만 남깁니다)", file=sys.stderr)
            return
        self.is_open = True
        try:
            QMessageBox.critical(None, "YesonCheck 오류", f"{text[-3000:]}\n\n로그: {self.log_path}")
        finally:
            self.is_open = False


def make_excepthook(log_path):
    """sys.excepthook: 예외는 항상 스택 트레이스째 로그(stderr)에 남기고, 오류 창은 GUI 스레드에서 하나씩.

    GUI 스레드가 아닌 곳(QThread 등)의 예외는 거기서 창을 만들지 않고(위젯은 GUI 스레드 전용) GUI 스레드로 넘겨 띄운다.
    """
    dialog = _ErrorDialog(log_path)

    def excepthook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        print(text, file=sys.stderr)
        app = QApplication.instance()
        if app is None:
            return
        if QThread.currentThread() is app.thread():
            dialog.show_error(text)
        else:
            dialog.requested.emit(text)  # GUI 스레드의 이벤트 루프에서 show_error 실행

    excepthook.dialog = dialog  # 시험·GC 방지용 참조
    return excepthook


def apply_high_dpi_rounding_policy():
    """Windows: 화면 배율을 반올림하지 않고 그대로(PassThrough) — QApplication을 만들기 전에 불러야 함.

    Qt 5.15 기본값(Round)은 125%를 1배, 150%를 2배로 그려서 앱이 다른 앱보다 20% 작거나 33% 컸다
    (150%에서는 최소 창이 실제 픽셀로 화면보다 커서 줄일 수 없었음). Mac은 배율이 정수라 바꾸지 않는다.
    """
    if sys.platform != "win32":
        return
    if not hasattr(QApplication, "setHighDpiScaleFactorRoundingPolicy"):
        raise RuntimeError(
            "이 PyQt5에는 QApplication.setHighDpiScaleFactorRoundingPolicy가 없습니다 (Qt 5.14 이상 필요) — "
            "Windows 125%·150% 배율이 1배·2배로 반올림됩니다"
        )
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)


def create_application(argv):
    """QApplication을 만들기 전에 정해야 하는 설정(고해상도)을 하고 만든다 — app.launch와 실행 시험(smoke_test)이 같은 설정."""
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    apply_high_dpi_rounding_policy()
    return QApplication(argv)


def load_mount_map():
    """(Mac) 이 Mac에서 공유가 붙은 곳(자동 연결 설정·/etc/fstab)을 읽어 경로 변환에 씀 — 공유 설정을 읽기 전에 한 번.

    launch와 실행 시험(smoke_test)이 같이 씀. 바꾸는 경로마다 한 줄([공유] /usadata2 → … (auto_nfs))과 설정 파일 문제를
    로그에. 공유(NAS) 자체는 열어 보지 않음 (mac_mounts). Windows는 아무것도 안 하고 None.
    """
    if paths.IS_WINDOWS:
        return None
    started = time.perf_counter()
    mount_map = mac_mounts.read_mount_map()
    for line in mount_map.report_lines():
        print(f"[공유] {line}", flush=True)
    paths.activate_mount_map(mount_map)
    timing_log.startup(f"이 Mac에서 공유가 붙은 곳 읽음 ({timing_log.since(started)})")
    return mount_map


def screen_report(screen):
    """시작 로그용 한 줄: 화면의 논리 크기·작업 영역·devicePixelRatio·논리 DPI·Qt 배율 반올림 정책
    (Windows 150%가 2배로 반올림되는지 등을 사용자 로그로 알 수 있게)."""
    geometry = screen.geometry()
    available = screen.availableGeometry()
    policy = QGuiApplication.highDpiScaleFactorRoundingPolicy()
    return (
        f"화면: 논리 {geometry.width()}×{geometry.height()} (위치 {geometry.x()},{geometry.y()}), "
        f"작업 영역 {available.width()}×{available.height()} (위치 {available.x()},{available.y()}), "
        f"devicePixelRatio {screen.devicePixelRatio():g}, 논리 DPI {screen.logicalDotsPerInch():g}, "
        f"배율 반올림 {getattr(policy, 'name', policy)}"
    )


def open_startup_file(player, file_path):
    """명령줄로 받은 파일을 영상 A로 엶 (없으면 로그만)."""
    print(f"Opening file: {file_path}")
    if os.path.isfile(file_path):
        player.open_file("A", file_path)
    else:
        print(f"File does not exist: {file_path}")


# 창을 닫은 뒤 끝나지 않은 작업(예: TensorFlow 추론 중인 애니매틱2)을 기다리는 최대 시간 (초).
# 넘으면 로그를 남기고 프로세스를 강제로 끝냄 (finish_released_workers)
EXIT_WAIT_S = 30


def finish_released_workers(timeout_s):
    """창을 닫을 때 붙잡아 둔 작업을 timeout_s초까지 기다리고, 그래도 안 끝나면 로그를 남긴 뒤 os._exit(0).

    실행 중인 QThread가 남은 채 파이썬이 끝나면 모듈 정리 중에 파괴돼 오류로 죽음(Windows 0xC0000409)
    → 창 없이 오래 남지도, 오류로 죽지도 않게 정해진 시간 뒤에는 드러나게(로그) 강제 종료."""
    still_running = wait_for_released_workers(timeout_s)
    if not still_running:
        return
    print(f"[닫기] 작업 {len(still_running)}개가 {timeout_s:g}초 안에 끝나지 않아 강제로 종료합니다: "
          f"{', '.join(still_running)}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()  # Windows 빌드 앱은 stdout·stderr가 로그 파일 (setup_windows_logging)
    os._exit(0)


def launch(argv=None):
    """Create and run the QApplication event loop."""
    argv = list(sys.argv if argv is None else argv)

    # 시작 시간 기록: 느릴 수 있는 단계마다 앞뒤로 찍음 → 멈추면 로그의 마지막 줄이 그 단계 (timing_log)
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        # 고해상도 디스플레이 지원 (QApplication 생성 전에 설정해야 함, Windows는 배율 반올림 없이)
        timing_log.startup("QApplication 만드는 중…")
        app = create_application(argv)
    timing_log.startup("QApplication 준비")
    timing_log.startup(screen_report(app.primaryScreen()))
    # (Mac) 공유를 다른 곳에 붙인 Mac: 공유 설정 폴더·작품 경로를 열기 전에 이 Mac에서 공유가 붙은 곳을 읽음
    # (스플래시 전에 — 예상 못 한 오류 창이 항상 위인 스플래시에 가려지지 않게)
    load_mount_map()

    # 스플래시 스크린 생성 (즉시 표시)
    pixmap = QPixmap(500, 300)
    pixmap.fill(Qt.black)
    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint | Qt.SplashScreen)
    splash.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.SplashScreen)
    
    # 스플래시 메시지 표시
    splash.showMessage("Yeson Checker\n로딩 중...", Qt.AlignCenter | Qt.AlignBottom, Qt.white)
    splash.show()
    app.processEvents()  # 즉시 화면 표시
    timing_log.startup("스플래시 표시")
    
    # 메인 윈도우 생성: 공유 설정(NAS)은 읽지 않고 바로 — 창을 보인 뒤 백그라운드에서 읽음
    timing_log.startup("창 만드는 중…")
    started = time.perf_counter()
    try:
        player = VideoPlayer(load_shared_config=False)
    except BaseException:
        # 오류 창(excepthook)이 스플래시(항상 위)에 가려져 '로딩 중'에서 멈춘 것처럼 보이지 않게 먼저 닫음
        splash.close()
        raise
    timing_log.startup(f"창 만듦 ({timing_log.since(started)})")
    
    # 메인 윈도우 표시 후 스플래시 닫기
    player.show()
    splash.finish(player)
    timing_log.startup("창 표시")
    # 지난 업데이트의 결과(이 컴퓨터의 기록 파일만 — NAS·인터넷 없음): 창을 보인 뒤 맨 먼저 — 새 버전이면 "잘 켜짐" 표시를
    # 바로 남겨 업데이트 도우미가 기다림을 끝냄
    QTimer.singleShot(0, player.handle_update_startup)
    # 공유 설정(설정 폴더·작품 경로·변환표)은 창을 보인 뒤 백그라운드에서 읽고, 끝나면 문제를 알림
    # (스플래시가 닫힌 뒤라 대화상자가 가려지지 않음)
    QTimer.singleShot(0, player.start_shared_config_load)
    if len(argv) > 1:
        # 명령줄로 받은 파일도 창을 보인 뒤에 엶: 여는 중 소리 재생기를 만들고(처음에는 수 초), 오류 창이
        # 스플래시에 가려지지 않게. 공유 설정 불러오기를 먼저 시작해 두어 그동안 백그라운드에서 읽음
        file_path = argv[1]
        QTimer.singleShot(0, lambda: open_startup_file(player, file_path))

    if owns_app:
        code = app.exec_()
        # 창을 닫을 때 끝나지 않아 붙잡아 둔 작업(예: TensorFlow 추론 중인 애니매틱2)을 EXIT_WAIT_S초까지 기다림
        # (넘으면 로그를 남기고 강제 종료 — 실행 중인 QThread가 파이썬 종료 중에 파괴되면 앱이 오류로 죽음)
        finish_released_workers(EXIT_WAIT_S)
        return code
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
