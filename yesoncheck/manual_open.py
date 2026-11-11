"""사용법 매뉴얼 열기 (Help → 사용법 · F1) — Qt 없음.

앱에 든 그림(`manual_images/`)과 글로 HTML 한 파일을 만들어 이 사용자의 폴더에 쓰고, 그 파일을 이 PC의 기본 프로그램
(보통 웹 브라우저)으로 엶. 앱 묶음 안에는 쓰지 않음(서명한 Mac 앱·Program Files는 쓸 수 없음) — 열 때마다 새로 써서
업데이트한 뒤에도 늘 지금 버전의 글이 열림.

  그림 폴더: 빌드한 앱 `sys._MEIPASS/manual_images`(spec의 datas), 소스 실행 `yesoncheck/manual_images`
  쓰는 자리: Mac `~/Library/Caches/YesonCheck/manual`, Windows `%LOCALAPPDATA%\\YesonCheck\\manual`

실패(그림 없음·쓸 수 없음·열지 못함)는 예외 그대로 — 부른 쪽(`player_base.show_help`)이 오류 창으로 알림.
"""
import os
import subprocess
import sys
import tempfile

from yesoncheck import build_info, manual_html

IMAGES_FOLDER = "manual_images"
FILE_NAME = "YesonCheck_manual.html"
OPEN_TIMEOUT_S = 30  # (Mac) open 명령이 돌아오기를 기다리는 한도 — new_window·open_with와 같음
LOG_PREFIX = "[사용법]"
OPEN_FAILED_TEXT = "사용법(매뉴얼)을 열지 못했습니다."


def images_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, IMAGES_FOLDER)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), IMAGES_FOLDER)


def load_image(name, folder=None):
    """그림 `<이름>.png`의 바이트. 없으면 FileNotFoundError 그대로 (빌드에서 빠졌다는 뜻 — 지어내지 않음)."""
    with open(os.path.join(images_dir() if folder is None else folder, name + ".png"), "rb") as fh:
        return fh.read()


def output_dir(platform=None):
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return os.path.join(os.environ["LOCALAPPDATA"], "YesonCheck", "manual")
    if platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Caches", "YesonCheck", "manual")
    return os.path.join(os.path.expanduser("~"), ".cache", "YesonCheck", "manual")


def build():
    """지금 앱의 매뉴얼 HTML. 배포한 버전이면 '업데이트 내역'의 그 버전에 '지금 버전' 표시."""
    info = build_info.current()
    current = info.version if info is not None and info.is_release else None
    return manual_html.build(load_image, version_text=build_info.display_version(), current_version=current)


def write(folder=None):
    """매뉴얼을 `folder`(기본 `output_dir()`)에 씀 → 파일 경로. 같은 폴더의 임시 파일에 쓴 뒤 바꿔 끼움 —
    여러 창이 함께 써도, 브라우저가 읽는 중에도 반쪽 파일이 보이지 않음."""
    folder = output_dir() if folder is None else folder
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, FILE_NAME)
    text = build()
    handle, tmp_path = tempfile.mkstemp(prefix=".manual_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return path


def open_file(path, platform=None):
    """파일을 이 PC의 기본 프로그램으로 엶. 열지 못하면 예외 (Mac: 명령과 출력이 든 RuntimeError, Windows: OSError)."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        os.startfile(path)  # noqa: S606 — 우리가 방금 쓴 파일
        return
    command = ["/usr/bin/open", path] if platform == "darwin" else ["xdg-open", path]
    done = subprocess.run(command, capture_output=True, text=True, timeout=OPEN_TIMEOUT_S)
    if done.returncode != 0:
        raise RuntimeError(f"매뉴얼 파일을 열지 못했습니다 (종료 코드 {done.returncode})\n명령: {command}\n"
                           f"출력: {(done.stdout + done.stderr).strip()}")


def open_manual():
    """매뉴얼을 쓰고 엶 → 쓴 파일 경로."""
    path = write()
    open_file(path)
    return path
