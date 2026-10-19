"""ci/update_e2e.py(업데이트 끝까지 시험 드라이버)의 판정 — 도우미 기록의 순서·이유, 전체 제한 시간.

도우미 줄은 update_helper_windows.ps1(Write-Log)·update_helper_mac.sh(log)가 쓰는 모양 그대로. 드라이버 전체(빌드된 앱·
설치 파일)는 CI의 '업데이트 끝까지 시험' 단계가 돌린다.
"""

import importlib.util
import os

import pytest

from tests.conftest import ROOT

_spec = importlib.util.spec_from_file_location("update_e2e", os.path.join(ROOT, "ci", "update_e2e.py"))
update_e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_e2e)

T = "2026-10-19T23:23:37 "
WIN_DIR = r"C:\yc_update\rollback\apps\YesonCheck"


def helper_log(*lines):
    """도우미 줄 + 그 사이의 앱 줄(도우미 줄이 아님 — 판정이 건너뛰어야 함)."""
    out = [T + "업데이트 99.0.0: 도우미를 띄움 (앱의 줄)"]
    for line in lines:
        out.append(T + "도우미: " + line)
        out.append("[시작 23:23:39.840] QApplication 만드는 중… (다시 켠 앱의 출력)")
    return "\n".join(out) + "\n"


WINDOWS_START = [
    f"시작: 대상 버전 99.0.0, 설치 폴더 {WIN_DIR}, 설치 파일 C:\\yc_update\\rollback\\user\\YesonCheck\\updates\\"
    "downloads\\YesonCheck_Setup_98.0.0.exe",
    "앱이 끝나기를 기다림 (pid 4100, 최대 300초)",
    "앱이 끝남 (pid 4100)",
    f"설치 폴더를 백업 이름으로 바꿈: {WIN_DIR} → {WIN_DIR}.update-backup",
]
WINDOWS_ROLLBACK_AFTER_TIMEOUT = [
    *WINDOWS_START,
    "설치 파일을 조용히 실행: … (설치 파일 기록: …, 최대 900초)",
    "설치 파일이 끝남 (종료 코드 0)",
    f"새 앱을 켬 (pid 5200): {WIN_DIR}\\YesonCheck_Autocut.exe",
    "새 앱의 '잘 켜짐' 표시를 기다림 (최대 60초): …\\update_ok.json",
    "업데이트 실패: 60초 안에 '잘 켜짐' 표시가 없음 (표시: 없음)",
    "되돌림 시작",
    "새 앱 프로세스를 끝냄: pid 5200",
    f"반쯤 깔린 설치 폴더를 치움: {WIN_DIR} → {WIN_DIR}.update-failed-3900",
    f"백업을 제자리로 되돌림: {WIN_DIR}.update-backup → {WIN_DIR}",
    f"치운 새 버전을 지움: {WIN_DIR}.update-failed-3900",
    "되돌림: 옛 앱을 다시 켬",
    f"옛 앱을 켬 (pid 5600): {WIN_DIR}\\YesonCheck_Autocut.exe",
]
MAC_APP = "/Users/runner/work/_temp/yc_update/rollback/yc_apps/YesonCheck_Autocut_Intel.app"
MAC_ROLLBACK_AFTER_EXIT = [
    f"시작: 대상 버전 99.0.0, 앱 {MAC_APP}, 준비한 새 앱 {os.path.dirname(MAC_APP)}/.YesonCheck_Autocut_Intel.app.update-99.0.0",
    "앱이 끝나기를 기다림 (pid 22393, 최대 300초)",
    "앱이 끝남 (pid 22393)",
    f"옛 앱을 백업 이름으로 옮김: {MAC_APP} → …/YesonCheck_Autocut_Intel.update-backup.app",
    f"새 앱을 앱 자리로 옮김: …/.YesonCheck_Autocut_Intel.app.update-99.0.0 → {MAC_APP}",
    f"새 앱을 켬 (직접 실행, pid 22714): {MAC_APP}",
    "새 앱의 '잘 켜짐' 표시를 기다림 (최대 60초): …/update_ok.json",
    "업데이트 실패: 새 앱이 '잘 켜짐' 표시 없이 끝남 (표시 버전: 없음)",
    "되돌림 시작",
    "새 앱 프로세스는 이미 끝나 있음",
    f"백업을 제자리로 되돌림: …/YesonCheck_Autocut_Intel.update-backup.app → {MAC_APP}",
    "되돌림: 옛 앱을 다시 켬",
    f"옛 앱을 켬 (직접 실행, pid 22755): {MAC_APP}",
]


def test_rollback_after_new_app_was_launched_passes():
    update_e2e.assert_helper_sequence(helper_log(*WINDOWS_ROLLBACK_AFTER_TIMEOUT), update_e2e.rollback_sequence(True))
    update_e2e.assert_helper_sequence(helper_log(*MAC_ROLLBACK_AFTER_EXIT), update_e2e.rollback_sequence(False))


@pytest.mark.parametrize("lines, missing", [
    # 설치 폴더의 이름을 바꾸지 못함 (파일이 잡혀 있음 — DLL 찾는 곳을 되돌리지 않으면 생길 수 있는 실패): 새 앱을 켜지 않음
    ([*WINDOWS_START[:3],
      "업데이트 실패: 설치 폴더의 이름을 바꾸지 못함 — 다른 YesonCheck 창이 켜져 있거나 파일이 잡혀 있음 (…): …",
      "되돌림 시작", f"설치 폴더는 바뀌지 않았음: {WIN_DIR}", "되돌림: 옛 앱을 다시 켬", "옛 앱을 켬 (pid 5600): …"],
     "설치 파일이 끝남 (종료 코드 0)"),
    # 설치 파일이 실패함
    ([*WINDOWS_START, "설치 파일 기록의 끝 20줄 (…):",
      "업데이트 실패: 설치 파일이 실패함 (종료 코드 1, 설치 파일 기록: …)", "되돌림 시작",
      f"백업을 제자리로 되돌림: {WIN_DIR}.update-backup → {WIN_DIR}", "되돌림: 옛 앱을 다시 켬", "옛 앱을 켬 (pid 5600): …"],
     "설치 파일이 끝남 (종료 코드 0)"),
    # 새 앱이 표시 없이 끝남 (죽음) — 이 시험이 만든 실패(98.0.0이 떠 있다 시간이 지남)가 아님
    ([*WINDOWS_ROLLBACK_AFTER_TIMEOUT[:7],
      "업데이트 실패: 새 앱이 '잘 켜짐' 표시 없이 끝남 (종료 코드 -1073740791, 표시: 없음)",
      *WINDOWS_ROLLBACK_AFTER_TIMEOUT[9:]],
     "업데이트 실패: 60초 안에 '잘 켜짐' 표시가 없음"),
])
def test_windows_rollback_for_another_reason_fails(lines, missing):
    with pytest.raises(AssertionError, match=missing.replace("(", r"\(").replace(")", r"\)")):
        update_e2e.assert_helper_sequence(helper_log(*lines), update_e2e.rollback_sequence(True))


def test_mac_rollback_before_launch_fails():
    lines = [*MAC_ROLLBACK_AFTER_EXIT[:3],
             "업데이트 실패: 옛 앱을 백업 이름으로 옮기지 못함: mv: …: Operation not permitted",
             "되돌림 시작", f"앱은 바뀌지 않았음: {MAC_APP}", "되돌림: 옛 앱을 다시 켬", f"옛 앱을 켬 (직접 실행, pid 1): {MAC_APP}"]
    with pytest.raises(AssertionError, match="새 앱을 켬"):
        update_e2e.assert_helper_sequence(helper_log(*lines), update_e2e.rollback_sequence(False))


def test_success_sequence_needs_the_order():
    windows = [*WINDOWS_START, "설치 파일이 끝남 (종료 코드 0)", f"새 앱을 켬 (pid 5200): {WIN_DIR}\\YesonCheck_Autocut.exe",
               "새 앱이 잘 켜짐 (버전 99.0.0)", f"백업을 지움: {WIN_DIR}.update-backup", "업데이트 끝: 99.0.0"]
    update_e2e.assert_helper_sequence(helper_log(*windows), update_e2e.success_sequence(True))
    mac = [*MAC_ROLLBACK_AFTER_EXIT[:6], "새 앱이 잘 켜짐 (버전 99.0.0)", "백업을 지움: …", "업데이트 끝: 99.0.0"]
    update_e2e.assert_helper_sequence(helper_log(*mac), update_e2e.success_sequence(False))
    # '업데이트 끝'이 새 앱을 켜기 전에 있으면 (순서가 다름) 통과가 아님
    with pytest.raises(AssertionError, match="새 앱이 잘 켜짐"):
        update_e2e.assert_helper_sequence(helper_log(*mac[:5], "업데이트 끝: 99.0.0", mac[5]),
                                          update_e2e.success_sequence(False))


def test_deadline_caps_waits_and_stops_after_the_limit(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(update_e2e.time, "monotonic", lambda: now[0])
    deadline = update_e2e.Deadline(2)  # 120초
    assert deadline.left(900) == 120
    assert deadline.left(30) == 30
    now[0] += 119
    assert deadline.left(900) == pytest.approx(1)
    now[0] += 1
    with pytest.raises(TimeoutError, match="전체 제한 시간 2분"):
        deadline.left(900)
