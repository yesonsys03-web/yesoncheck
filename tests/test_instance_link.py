"""창 사이 연결(instance_link): 다른 창(프로세스)이 이 창의 상태를 묻고 정상 종료를 요청 — 응답 없는 창은 정해진 시간에
InstanceLinkError(Review Focus 2). 서버는 이 시험 프로세스의 메인 스레드 이벤트 루프, 클라이언트는 다른 프로세스.
"""

import json
import os
import re
import subprocess
import sys
import time

import pytest
from PyQt5.QtCore import QTimer
from types import SimpleNamespace

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QDialog, QFileDialog, QListWidgetItem, QMessageBox, QProgressDialog

from tests.conftest import ROOT
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import instance_link, instances
from yesoncheck.instance_link import InstanceLinkError, InstanceServer

CLIENT = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from PyQt5.QtCore import QCoreApplication
from yesoncheck import instance_link
app = QCoreApplication([])
op, name = sys.argv[2], sys.argv[3]
try:
    if op == "status":
        result = instance_link.query_status(name)
    elif op == "close":
        result = instance_link.request_close(name)
    else:
        result = instance_link._request(name, {"op": op}, 3000)
    print(json.dumps({"result": result}, ensure_ascii=False))
except instance_link.InstanceLinkError as exc:
    print(json.dumps({"error": str(exc)}, ensure_ascii=False))
"""

# 듣기만 하고 답하지 않는 창: 서버를 연 뒤 이벤트 루프를 돌리지 않음 (GUI 스레드가 NAS에서 멈춘 창 흉내)
FROZEN_SERVER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from PyQt5.QtCore import QCoreApplication
from yesoncheck.instance_link import InstanceServer
app = QCoreApplication([])
server = InstanceServer(lambda: {"pid": 0}, lambda: None)
print(server.start(), flush=True)
time.sleep(60)
"""


def _child_env():
    return dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")


def _run_client(qapp, op, name, timeout_s=60):
    """다른 프로세스에서 op를 보내고, 끝날 때까지 이 프로세스의 이벤트 루프를 돌려 서버가 답하게 함 → 클라이언트가 찍은 JSON."""
    proc = subprocess.Popen([sys.executable, "-c", CLIENT, ROOT, op, name], cwd=ROOT, env=_child_env(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + timeout_s
    while proc.poll() is None:
        qapp.processEvents()
        if time.monotonic() > deadline:
            proc.kill()
            pytest.fail(f"클라이언트가 {timeout_s}초 안에 끝나지 않았습니다")
        time.sleep(0.005)
    out, err = proc.communicate()
    out, err = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    assert proc.returncode == 0, f"stdout:\n{out}\nstderr:\n{err}"
    return json.loads(out.strip().splitlines()[-1])


def _wait_until(qapp, condition, timeout_s=5):
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail("기다리는 일이 일어나지 않았습니다")
        qapp.processEvents()
        time.sleep(0.005)


def test_server_name_is_short_ascii():
    # Windows는 이름 있는 파이프(\\.\pipe\…) — 사용자 이름이 한글이어도 ASCII, 짧게
    name = instance_link.server_name()
    assert re.fullmatch(r"yesoncheck-[0-9a-z]+-%d" % os.getpid(), name), name
    assert len(name) <= 40


def test_status_round_trip(qapp):
    status = {"pid": os.getpid(), "title": "YesonCheck — FL_901.mov", "video": "/Volumes/작업/FL_901.mov",
              "jobs": ["OCR 분석·컷 감지", "영상 병합"], "unsaved_ocr": True}
    closed = []
    server = InstanceServer(lambda: status, lambda: closed.append("closed"))
    name = server.start()
    try:
        assert name.endswith(instance_link.server_name())  # 전체 이름 (Mac 소켓 파일 경로·Windows 파이프)
        assert _run_client(qapp, "status", name) == {"result": status}
        assert _run_client(qapp, "status", name) == {"result": status}  # 여러 번
        assert closed == []
    finally:
        server.close()


def test_close_request_runs_handler(qapp):
    closed = []
    server = InstanceServer(lambda: {}, lambda: closed.append("closed"))
    name = server.start()
    try:
        assert _run_client(qapp, "close", name) == {"result": None}
        _wait_until(qapp, lambda: closed == ["closed"])  # 답한 뒤 이벤트 루프에서
    finally:
        server.close()


def test_unknown_request_answered_with_error(qapp, capsys):
    server = InstanceServer(lambda: {}, lambda: pytest.fail("닫으면 안 됨"))
    name = server.start()
    try:
        reply = _run_client(qapp, "reboot", name)
        assert "알 수 없는 요청" in reply["error"] and "reboot" in reply["error"]
    finally:
        server.close()
    assert "알 수 없는 요청" in capsys.readouterr().out  # 서버 쪽 기록에도


# 상태·닫기 처리 중 오류가 나는 창 (excepthook을 바꾸지 않음 — 그대로면 PyQt가 abort()로 창을 끝냄, Mac 빌드처럼)
FAILING_SERVER = r"""
import sys
sys.path.insert(0, sys.argv[1])
from PyQt5.QtCore import QCoreApplication
from yesoncheck.instance_link import InstanceServer
app = QCoreApplication([])
calls = {"status": 0, "close": 0}

def status():
    calls["status"] += 1
    if calls["status"] == 1:
        raise RuntimeError("상태 오류 (시험)")
    return {"calls": dict(calls)}

def close():
    calls["close"] += 1
    if calls["close"] == 1:
        raise RuntimeError("닫기 오류 (시험)")
    app.quit()

server = InstanceServer(status, close)
print(server.start(), flush=True)
sys.exit(app.exec_())
"""


def test_handler_errors_answered_and_window_keeps_serving(qapp):
    """상태·닫기를 처리하다 난 오류: 창은 죽지 않고(작업을 잃지 않게) 트레이스백을 기록에 남기며, 상태 오류는 묻는 창에
    InstanceLinkError(오류 내용)로 — 그 뒤에도 계속 답함."""
    proc = subprocess.Popen([sys.executable, "-c", FAILING_SERVER, ROOT], cwd=ROOT, env=_child_env(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        name = proc.stdout.readline().strip()
        assert name, proc.stderr.read()
        with pytest.raises(InstanceLinkError, match=r"RuntimeError: 상태 오류 \(시험\)"):
            instance_link.query_status(name)
        assert instance_link.query_status(name) == {"calls": {"status": 2, "close": 0}}
        instance_link.request_close(name)  # 받았다고 답한 뒤 처리하다 오류 — 창은 그대로
        _wait_until(qapp, lambda: instance_link.query_status(name)["calls"]["close"] == 1)
        assert proc.poll() is None
        instance_link.request_close(name)  # 이번에는 닫힘
        assert proc.wait(timeout=30) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        err = proc.stderr.read()
        proc.stdout.close()
        proc.stderr.close()
    assert "Traceback" in err and "RuntimeError: 상태 오류 (시험)" in err and "RuntimeError: 닫기 오류 (시험)" in err, err


def test_query_unresponsive_server_times_out(qapp):
    proc = subprocess.Popen([sys.executable, "-c", FROZEN_SERVER, ROOT], cwd=ROOT, env=_child_env(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        name = proc.stdout.readline().strip()
        assert name, proc.stderr.read()
        started = time.monotonic()
        with pytest.raises(InstanceLinkError, match="답하지 않았습니다"):
            instance_link.query_status(name)  # 기본 3초
        elapsed = time.monotonic() - started
        assert 2.5 <= elapsed < 4.0, elapsed
        # 같은 창에 또 연결(닫기 요청)해도 정해진 시간에 끝남
        started = time.monotonic()
        with pytest.raises(InstanceLinkError, match="답하지 않았습니다"):
            instance_link.request_close(name, timeout_ms=1000)
        assert time.monotonic() - started < 2.0
    finally:
        proc.kill()
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()


def test_missing_server_fails_fast(qapp):
    started = time.monotonic()
    with pytest.raises(InstanceLinkError, match="연결하지 못했습니다"):
        instance_link.query_status("yesoncheck-test-no-such-window-1")
    assert time.monotonic() - started < 2.0


def test_start_twice_raises(qapp):
    server = InstanceServer(lambda: {}, lambda: None)
    server.start()
    try:
        with pytest.raises(RuntimeError, match="이미"):
            server.start()
    finally:
        server.close()


# ---- 창(VideoPlayer) ----


def test_window_registers_and_reports_status(qapp, new_player, dialogs, tmp_path):
    player = new_player(make_config(str(tmp_path), {}))
    player.start_instance_link()
    record_path = os.path.join(instances.registry_dir(), f"{os.getpid()}.json")
    with open(record_path, encoding="utf-8") as fh:
        record = json.load(fh)
    assert record["pid"] == os.getpid() and record["app_path"] == instances.current_app_path()
    status = {"pid": os.getpid(), "title": player.windowTitle(), "video": "", "jobs": [], "unsaved_ocr": False}
    assert player.instance_status() == status
    assert _run_client(qapp, "status", record["server_name"]) == {"result": status}

    player.close()  # 닫으면 기록을 지우고 서버를 닫음 (다른 창이 세지 않음)
    assert not os.path.exists(record_path)
    assert "연결하지 못했습니다" in _run_client(qapp, "status", record["server_name"])["error"]


def test_window_registers_even_when_server_fails(qapp, new_player, dialogs, tmp_path, monkeypatch):
    """서버를 열지 못해도 기록은 남김 (세어진 창에 닿지 못하면 그 업데이트는 멈춤 — 모르는 채 앱 파일을 바꾸지 않게) + 경고."""
    def failing_start(self):
        raise InstanceLinkError("창 사이 연결 서버를 열지 못했습니다 (시험)")

    monkeypatch.setattr(InstanceServer, "start", failing_start)
    player = new_player(make_config(str(tmp_path), {}))
    player.start_instance_link()
    record_path = os.path.join(instances.registry_dir(), f"{os.getpid()}.json")
    with open(record_path, encoding="utf-8") as fh:
        assert json.load(fh)["server_name"] == instance_link.server_name()
    assert len(dialogs.warnings) == 1 and "(시험)" in dialogs.warnings[0]
    with pytest.raises(InstanceLinkError, match="연결하지 못했습니다"):
        instance_link.query_status(instance_link.server_name(), timeout_ms=1000)
    player.close()
    assert not os.path.exists(record_path)


def test_close_for_update_rejects_open_dialog(qapp, new_player, dialogs, tmp_path):
    player = new_player(make_config(str(tmp_path), {}))
    player.show()
    player.start_instance_link()
    record_path = os.path.join(instances.registry_dir(), f"{os.getpid()}.json")
    assert os.path.exists(record_path)

    box = QMessageBox(QMessageBox.Question, "질문", "계속할까요?", QMessageBox.Yes | QMessageBox.No, player)
    box.open()  # 창 모달로 떠 있는 질문
    progress = QProgressDialog("작업 중…", "취소", 0, 10, player)  # 진행 창은 Esc처럼 '취소' (wasCanceled)
    progress.setWindowModality(Qt.WindowModal)
    progress.show()
    modeless = QDialog(player)  # 모달이 아닌 창(OCR 검토 창 같은)은 건드리지 않음 — 앱이 끝나면 함께 닫힘
    modeless.show()
    QTimer.singleShot(0, player.close_for_update)  # 아래 대화 상자의 이벤트 루프 안에서 닫기 요청이 옴
    try:
        result = QFileDialog(player, "저장").exec_()
        assert result == QDialog.Rejected
        assert not box.isVisible()
        assert progress.wasCanceled() and not progress.isVisible()
        assert modeless.isVisible()
        assert not player.isVisible()
        assert not os.path.exists(record_path)  # 평소 닫기(closeEvent)를 거침
    finally:
        modeless.close()
        QApplication.processEvents()


def test_close_for_update_stops_thumbnail_regeneration_loop(qapp, new_player, dialogs, tmp_path, monkeypatch):
    """진행 창의 이벤트 처리 안에서 닫기 요청이 옴: 진행 창을 '취소'해 반복이 멈추고, 끝난 뒤의 '완료' 창도 띄우지 않음."""
    player = new_player(make_config(str(tmp_path), {}))
    player.show()
    videos = []
    for i in range(5):
        path = tmp_path / f"FL_90{i}.mov"
        path.write_bytes(b"x")
        videos.append(str(path))
        item = QListWidgetItem(path.name)
        item.setToolTip(str(path))
        player.sidebar.addItem(item)
        item.setSelected(True)
    made = []

    def fake_generate(file_path, item=None):
        made.append(file_path)
        if len(made) == 1:
            QTimer.singleShot(0, player.close_for_update)  # 첫 썸네일 뒤에 다른 창의 업데이트가 닫기를 요청

    monkeypatch.setattr(player, "generate_thumbnail", fake_generate)
    monkeypatch.setattr(player, "delete_thumbnail_file", lambda file_path, item=None: None)
    player.regenerate_selected_thumbnails()
    assert made == videos[:1]
    assert not player.isVisible()
    assert dialogs.messages == []


@pytest.mark.parametrize("search_notices_cancel", [True, False], ids=["cancelled", "finished_anyway"])
def test_close_for_update_stops_path_map_search_without_follow_up_dialog(qapp, new_player, dialogs, tmp_path,
                                                                          monkeypatch, search_notices_cancel):
    """변환표 찾기(진행 창, 0.5초 뒤에 보임) 중 닫기 요청: 찾기를 취소하고, 그 뒤의 변환표 문제 창·확인 창을 열지 않음."""
    from yesoncheck import path_map_setup, player_sidebar

    player = new_player(make_config(str(tmp_path), {}))
    player.show()
    player.path_map_problem = "변환표 문제 (시험)"  # 시작할 때 찾기: 취소·짝 없음이면 이 문제를 알리는 창이 뜨는 경로
    monkeypatch.setattr(path_map_setup, "read_existing", lambda config_dir: (None, None))
    monkeypatch.setattr(path_map_setup, "available_shares", lambda: ([], []))
    answers = []

    def fake_propose(work_paths, shares, progress=None, on_wait=None, **kwargs):
        QTimer.singleShot(0, player.close_for_update)
        for done in range(1, 4):
            answers.append(progress(done, 3))  # 진행 창의 이벤트 처리 안에서 닫기 요청이 옴
            if not answers[-1] and search_notices_cancel:
                raise path_map_setup.SetupCancelled()
        return SimpleNamespace(pairs=[], share_problems=[])  # 취소를 보기 전에 끝난 찾기

    monkeypatch.setattr(path_map_setup, "propose_mapping", fake_propose)
    monkeypatch.setattr(player_sidebar, "PathMapSetupDialog",
                        lambda *a, **k: pytest.fail("닫는 중에 변환표 확인 창을 열면 안 됨"))
    assert player.auto_setup_path_map(ask_password=False, startup=True) is False
    assert answers[0] is False  # 첫 진행 보고에서 이미 취소됨
    assert dialogs.messages == []
    assert not player.isVisible()
