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
    """QMessageBox·폴더 선택 창을 띄우지 않고 기록한다. folders에 넣어 둔 경로를 차례로 '고른다'.

    messages: 모든 창의 (종류, 제목, 글). questions·warnings·criticals: 그 종류의 글만 차례로.
    question 창의 대답은 기본 Yes — answer_question(QMessageBox.No)로 그 뒤의 대답을 바꿈.
    QMessageBox를 만들어 exec_()로 띄운 창(자세한 글 setDetailedText이 있는 창 등)도 같은 목록에 — 글은 "본문\n\n자세한 글",
    본문과 자세한 글을 따로 보려면 boxes (종류·제목·본문·자세한 글·단추 글자). 그런 창 중 question 아이콘의 창도 대답은
    answer_question으로 정한 값 (나머지는 Ok).
    """
    from PyQt5.QtWidgets import QFileDialog, QInputDialog, QMessageBox

    rec = SimpleNamespace(messages=[], folders=[], questions=[], warnings=[], criticals=[], boxes=[])
    answers = {"question": QMessageBox.Yes}
    texts = {"question": rec.questions, "warning": rec.warnings, "critical": rec.criticals}

    def recorder(kind, answer):
        def fake(parent, title, text, *args, **kwargs):
            rec.messages.append((kind, title, text))
            if kind in texts:
                texts[kind].append(text)
            return answers.get(kind, answer)

        return fake

    def answer_question(answer):
        answers["question"] = answer

    rec.answer_question = answer_question
    monkeypatch.setattr(QMessageBox, "critical", recorder("critical", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "warning", recorder("warning", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "information", recorder("information", QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", recorder("question", QMessageBox.Yes))
    box_kinds = {QMessageBox.Critical: "critical", QMessageBox.Warning: "warning",
                 QMessageBox.Information: "information", QMessageBox.Question: "question"}

    def box_exec(box):
        kind = box_kinds.get(box.icon(), "other")
        title = box.windowTitle() or box.property("ycTitle") or ""  # macOS의 QMessageBox는 창 제목을 버림
        details = box.detailedText()
        text = f"{box.text()}\n\n{details}" if details else box.text()
        rec.messages.append((kind, title, text))
        rec.boxes.append(SimpleNamespace(kind=kind, title=title, text=box.text(), details=details,
                                         buttons=[button.text() for button in box.buttons()]))
        if kind in texts:
            texts[kind].append(text)
        return answers["question"] if kind == "question" else QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "exec_", box_exec)
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


import subprocess


@pytest.fixture
def make_video():
    """ffmpeg로 시험 영상(영상+소리, H.264) 생성. 한글 경로 가능."""
    from yesoncheck import external_tools

    ffmpeg = external_tools.ffmpeg_path()

    def make(path, seconds=2):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(
            [ffmpeg, "-y", "-v", "error",
             "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x240:rate=24",
             "-f", "lavfi", "-i", f"sine=duration={seconds}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path],
            check=True, **external_tools.subprocess_kwargs(),
        )
        return path

    return make


@pytest.fixture(autouse=True)
def _no_mac_mount_map(monkeypatch):
    """(Mac) 이 Mac에서 공유가 붙은 곳(mac_mounts)은 시험마다 비움: launch·실행 시험이 이 Mac의 /etc를 읽지 않게(없는 폴더를
    기준으로) 하고, 시험에서 정한 맵이 다른 시험에 남지 않게."""
    from yesoncheck import mac_mounts, paths

    monkeypatch.setattr(mac_mounts, "DEFAULT_ROOT", os.path.join(ROOT, "tests", "no_such_mac_root"))
    yield
    paths.activate_mount_map(None)


@pytest.fixture(autouse=True)
def _bookmarks_file_in_tmp(monkeypatch, tmp_path_factory):
    """창이 북마크를 사용자의 ~/.yeson_bookmarks.json이 아니라 시험마다 새 임시 파일에서 읽고 쓰게 (끌어다 놓은 폴더가
    진짜 북마크에 남지 않게). 한 시험 안의 여러 창은 같은 파일을 씀."""
    from yesoncheck import bookmarks

    path = str(tmp_path_factory.mktemp("bookmarks") / ".yeson_bookmarks.json")
    monkeypatch.setattr(bookmarks, "default_path", lambda: path)


@pytest.fixture(autouse=True)
def _instances_in_tmp(monkeypatch, tmp_path_factory):
    """창 기록(instances)은 시험마다 새 임시 폴더에 — 사용자의 기록 폴더(~/Library/Caches/YesonCheck/instances,
    %LOCALAPPDATA%\\YesonCheck\\instances)를 건드리지 않게. 환경 변수로 돌리므로 시험이 띄우는 자식 프로세스(app.launch
    등)도 같은 임시 폴더를 씀. 시험이 남긴 이 프로세스의 등록은 지움."""
    from yesoncheck import instances

    monkeypatch.setenv(instances.REGISTRY_DIR_ENV, str(tmp_path_factory.mktemp("instances") / "instances"))
    yield
    instances.unregister()


@pytest.fixture(autouse=True)
def _fresh_shortcut_cache():
    """바로 가기 대상 캐시는 프로세스 전체에 하나 → 시험마다 비움 (가짜 경로가 다른 시험의 결과를 쓰지 않게)."""
    from yesoncheck import path_map_setup

    if hasattr(path_map_setup, "clear_shortcut_cache"):
        path_map_setup.clear_shortcut_cache()
    yield


import http.server
import threading


class _TestHTTPServer:
    """GitHub 대신 127.0.0.1 임의 포트에서 응답을 흉내 내는 시험용 HTTP 서버 (http_server 픽스처)."""

    def __init__(self):
        self._routes = {}  # 경로 → (status, body)
        handler = self._make_handler()
        self._httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self):
        """서버의 바탕 주소 (끝에 "/" 없음)."""
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def serve(self, path, body, status=200):
        """path로 들어오는 요청에 status·body(bytes)로 응답하게 등록."""
        self._routes[path] = (status, body)

    def serve_file(self, path, file_path):
        """file_path의 내용을 path 요청에 그대로 응답하게 등록. file_path를 그대로 돌려준다."""
        with open(file_path, "rb") as fh:
            data = fh.read()
        self.serve(path, data)
        return file_path

    def shutdown(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join()

    def _make_handler(self):
        routes = self._routes

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler가 정한 이름)
                entry = routes.get(self.path)
                if entry is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                status, body = entry
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):  # noqa: A002 (부모 시그니처)
                pass  # 시험 중 요청마다 stderr에 찍지 않음

        return Handler


@pytest.fixture
def http_server():
    """등록 안 된 경로는 404. 등록은 .serve(path, body, status=200)·.serve_file(path, file_path). 시험이 끝나면 멈춤."""
    server = _TestHTTPServer()
    yield server
    server.shutdown()


@pytest.fixture
def tmp_state_dir(monkeypatch, tmp_path):
    """update_install.state_dir()/log_path()가 읽는 환경 변수(LOCALAPPDATA·HOME·USERPROFILE)를 모두
    tmp_path로 돌림 — 시험마다 깨끗한 업데이트 상태 폴더를 씀.

    실제 플랫폼과 상관없이 셋 다 돌려 둔다: Windows의 ntpath.expanduser는 HOME을 보지 않고
    USERPROFILE(또는 HOMEDRIVE+HOMEPATH)을 보므로, 이 fixture 아래서 paths.IS_WINDOWS를 Mac으로
    바꿔 끼우는 시험(Mac 쪽 state_dir()/log_path() 분기를 Windows CI에서 시험)도 실제 사용자 폴더를
    건드리지 않고 안전하게 돈다. 돌려주는 값은 그 결과인 state_dir() 경로.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from yesoncheck import update_install

    return update_install.state_dir()
