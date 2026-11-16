"""앱을 끝낼 때의 정리 순서(`app.launch`): QApplication의 파이썬 래퍼가 풀리기 전에 앱 전체 이벤트 필터를 떼고 창을 먼저 지움.

왜: `launch`가 돌아가면 지역 변수 `app`이 풀리고, PyQt는 그때(`dealloc_QApplication`) 살아 있는 래퍼를 모두 돌며
(`sipVisitWrappers`) 파이썬이 가진 부모 없는 QObject를 지운다. 창이 그 안에서 지워지면 자식 수백 개의 소멸 이벤트가 파이썬
이벤트 필터(Mac의 앱 전체 필터 `FileOpenRouter` 등)를 부름 — 그렇게 파이썬 코드가 불린 판에서만 종료 세그폴트가 났음
(충돌 스택 `dealloc_QApplication → sip_api_visit_wrappers → cleanup_qobject → sip_api_get_address`, 2026-11-16 실측).

세그폴트 자체는 간헐이라(어느 장면에서 나는지도 코드가 바뀌면 옮겨 감) 시험은 그 조건을 본다: launch가 돌아가는 순간 창이
이미 지워져 있고, 그 뒤(프레임이 풀리며 QApplication이 정리되는 동안)에는 앱의 파이썬 코드가 불리지 않음.
"""

import os
import subprocess
import sys

import pytest

from tests.conftest import ROOT

RETURN_LINE = "CHILD: launch가 돌아갈 때 창 지워짐"
LATE_CALL_LINE = "CHILD: launch 뒤에 불린 앱 코드"

CHILD = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
scenario = sys.argv[2]
from PyQt5 import sip
from PyQt5.QtCore import QPoint, QTimer
from PyQt5.QtWidgets import QApplication
from yesoncheck import app as app_module

LAUNCH_FILE = os.path.abspath(app_module.__file__)
PACKAGE = os.path.dirname(LAUNCH_FILE) + os.sep
created = []
state = {"returned": False}
real_player = app_module.VideoPlayer
real_finish = app_module.finish_released_workers


def close_popup():
    popup = QApplication.activePopupWidget()
    print("CHILD: 팝업", type(popup).__name__ if popup is not None else None, flush=True)
    if popup is not None:
        popup.close()


def player_factory(**kwargs):
    player = real_player(**kwargs)
    created.append(player)

    def use_menu(times):
        if times == 0:
            QTimer.singleShot(300, player.close)
            return
        QTimer.singleShot(150, close_popup)
        player.show_video_context_menu(QPoint(40, 40))  # exec_ — close_popup이 닫으면 돌아옴
        QTimer.singleShot(50, lambda: use_menu(times - 1))

    QTimer.singleShot(800, lambda: use_menu(3 if scenario == "menu" else 0))
    return player


def profiler(frame, event, arg):
    code = frame.f_code
    path = os.path.abspath(code.co_filename)
    if event == "return" and code.co_name == "launch" and path == LAUNCH_FILE:
        state["returned"] = True
        print("CHILD: launch가 돌아갈 때 창 지워짐", sip.isdeleted(created[0]), flush=True)
    elif event == "call" and state["returned"] and path.startswith(PACKAGE):
        print("CHILD: launch 뒤에 불린 앱 코드", os.path.basename(path), code.co_name, flush=True)


def finish_then_watch(timeout):
    real_finish(timeout)
    sys.setprofile(profiler)  # 여기서부터: launch의 나머지와, 돌아간 뒤 프레임이 풀리는 동안


app_module.VideoPlayer = player_factory
app_module.finish_released_workers = finish_then_watch
code = app_module.launch([sys.argv[0]])
sys.setprofile(None)
print(f"CHILD: launch 끝 {code}", flush=True)
sys.exit(code)
'''


def run_child(tmp_path, scenario):
    script = tmp_path / "exit_child.py"
    script.write_text(CHILD, encoding="utf-8")
    home = tmp_path / "home"
    config = tmp_path / "share" / ".yesoncheck"
    instances = tmp_path / "instances"
    for folder in (home, config, instances):
        folder.mkdir(parents=True)
    (config / "work_paths.json").write_text("{}", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("YESONCHECK_")}
    env.update(QT_QPA_PLATFORM="offscreen", HOME=str(home), USERPROFILE=str(home),
               LOCALAPPDATA=str(home / "AppData" / "Local"), YESONCHECK_CONFIG_DIR=str(config),
               YESONCHECK_INSTANCES_DIR=str(instances), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, str(script), ROOT, scenario], cwd=ROOT, env=env, capture_output=True,
                          timeout=120)
    out = done.stdout.decode("utf-8", "replace")
    err = done.stderr.decode("utf-8", "replace")
    return done.returncode, out, f"종료 코드 {done.returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"


@pytest.mark.parametrize("scenario", ["plain", "menu"])
def test_window_is_gone_before_the_application_and_no_app_code_runs_after_launch(tmp_path, scenario):
    """창을 닫아 끝낼 때(그냥 닫기 · 영상 영역의 우클릭 메뉴를 세 번 쓴 뒤 닫기): launch가 돌아가는 순간 창이 이미 지워져
    있고, 그 뒤 QApplication이 정리되는 동안 앱의 파이썬 코드(이벤트 필터 등)가 불리지 않으며, 정상 종료."""
    code, out, report = run_child(tmp_path, scenario)
    if scenario == "menu":
        assert out.count("CHILD: 팝업 QMenu") == 3, report
    assert f"{RETURN_LINE} True" in out, report
    late = [line for line in out.splitlines() if line.startswith(LATE_CALL_LINE)]
    assert late == [], report
    assert "CHILD: launch 끝 0" in out, report
    assert code == 0, report
