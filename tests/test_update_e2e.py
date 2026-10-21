"""ci/update_e2e.py(업데이트 끝까지 시험 드라이버)의 판정 — 도우미 기록의 순서·이유, 전체 제한 시간.

도우미 줄은 update_helper_windows.ps1(Write-Log)·update_helper_mac.sh(log)가 쓰는 모양 그대로. 드라이버 전체(빌드된 앱·
설치 파일)는 CI의 '업데이트 끝까지 시험' 단계가 돌린다.
"""

import importlib.util
import os
from types import SimpleNamespace

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
    "다음 로그인에서 되살리도록 등록함 (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce 의 "
    "YesonCheckUpdateRecover, 160자): …",
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
    "다음 로그인의 되살림 등록을 지움",
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
    ([*WINDOWS_ROLLBACK_AFTER_TIMEOUT[:8],
      "업데이트 실패: 새 앱이 '잘 켜짐' 표시 없이 끝남 (종료 코드 -1073740791, 표시: 없음)",
      *WINDOWS_ROLLBACK_AFTER_TIMEOUT[10:]],
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
               "새 앱이 잘 켜짐 (버전 99.0.0)", f"백업을 지움: {WIN_DIR}.update-backup", "다음 로그인의 되살림 등록을 지움",
               "업데이트 끝: 99.0.0"]
    update_e2e.assert_helper_sequence(helper_log(*windows), update_e2e.success_sequence(True))
    # 되살림을 등록하지 않았거나(이름을 바꾸기 전) 지우지 않았으면 통과가 아님
    for missing in ("다음 로그인에서 되살리도록 등록함", "다음 로그인의 되살림 등록을 지움"):
        with pytest.raises(AssertionError, match=missing):
            update_e2e.assert_helper_sequence(helper_log(*[line for line in windows if not line.startswith(missing)]),
                                              update_e2e.success_sequence(True))
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


# ---- 켜진 앱: 정확히 하나, 계속 떠 있음 ----


CASE = SimpleNamespace(app="C:\\yc_update\\rollback\\apps\\YesonCheck")


def _app(pid, ppid=1):
    exe = "C:\\yc_update\\rollback\\apps\\YesonCheck\\YesonCheck_Autocut.exe"
    return update_e2e.Proc(pid, exe, f'"{exe}"', ppid, "2026-10-19T17:15:37.500")


@pytest.fixture
def fast_clock(monkeypatch):
    """one_app_process의 기다림을 시험 시간 없이: sleep은 시계를 1초 움직이기만."""
    now = [0.0]
    monkeypatch.setattr(update_e2e.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(update_e2e.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    monkeypatch.setattr(update_e2e, "DEADLINE", update_e2e.Deadline(60))
    helper = update_e2e.Proc(4000, "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
                             "powershell.exe -File update_helper_windows.ps1", 1, "")
    monkeypatch.setattr(update_e2e, "list_processes", lambda: [helper])
    return now


def test_one_app_process_needs_the_same_single_process_to_stay(monkeypatch, fast_clock):
    monkeypatch.setattr(update_e2e, "app_processes", lambda case: [_app(7528, 4000)])
    assert [p.pid for p in update_e2e.one_app_process(CASE, "되돌린 옛 앱")] == [7528]
    assert fast_clock[0] >= update_e2e.STAYS_RUNNING_S


def test_one_app_process_shows_parents_of_two_processes(monkeypatch, fast_clock):
    monkeypatch.setattr(update_e2e, "app_processes", lambda case: [_app(7528, 4000), _app(7964, 7528)])
    with pytest.raises(AssertionError) as info:
        update_e2e.one_app_process(CASE, "되돌린 옛 앱")
    text = str(info.value)
    assert "하나가 아닙니다 (2개)" in text
    assert "pid 7528 (부모 4000 powershell.exe -File update_helper_windows.ps1)" in text
    assert "pid 7964 (부모 7528 (이미 끝남))" in text and "만든 시각 2026-10-19T17:15:37.500" in text


def test_one_app_process_fails_when_the_app_dies_after_starting(monkeypatch, fast_clock):
    """켜진 뒤 몇 초 안에 죽는 앱(예: 메시지 창에서 죽음)은 '떠 있음'이 아님."""
    seen = iter([[_app(7528, 4000)], [_app(7528, 4000)], []])
    monkeypatch.setattr(update_e2e, "app_processes", lambda case: next(seen))
    with pytest.raises(AssertionError, match=r"pid 7528\)가 10초 동안 혼자 떠 있지 않았습니다 — 지금: 없음"):
        update_e2e.one_app_process(CASE, "되돌린 옛 앱")


# ---- 다른 창 경로 (같은 설치의 다른 창이 켜진 채 업데이트) ----


def test_close_others_texts_match_the_app():
    """드라이버가 확인하는 확인 창·기록의 글이 앱(player_update)의 것과 같음 (드라이버는 Qt를 불러오지 않아 따로 둠)."""
    from yesoncheck import player_update

    assert update_e2e.CLOSE_OTHERS_TITLE == player_update.UPDATE_OTHERS_TITLE
    assert update_e2e.CLOSE_OTHERS_COUNT == player_update.OTHERS_COUNT.format(n=1)
    assert update_e2e.CLOSE_ALL_BUTTON == player_update.CLOSE_ALL_BUTTON


@pytest.mark.parametrize("windows", [True, False])
def test_other_window_case_shares_the_success_package(monkeypatch, tmp_path, windows):
    """경우 셋: success·other_window는 같은 꾸러미(99.0.0, 잘 켜짐)를 하나만 만들어 복사, rollback은 따로."""
    monkeypatch.setattr(update_e2e, "WINDOWS", windows)
    args = SimpleNamespace(share_root=str(tmp_path / "share"), unc=r"\\localhost\yc_test\yc_update",
                           app_dist="/x/dist/YesonCheck_Autocut_Intel.app")
    cases = update_e2e.make_cases(args, str(tmp_path / "work"))
    assert [(c.name, c.other_window, c.broken) for c in cases] == [
        ("success", False, False), ("other_window", True, False), ("rollback", False, True)]
    groups = update_e2e.package_groups(cases)
    assert [[c.name for c in group] for group in groups] == [["success", "other_window"], ["rollback"]]
    success, other = groups[0]
    os.makedirs(success.package_dir)
    with open(os.path.join(success.package_dir, "YesonCheck_Setup_99.0.0.exe"), "wb") as fh:
        fh.write(b"MZ setup")
    assert update_e2e.share_package(groups[0]) == ["other_window"]
    with open(os.path.join(other.package_dir, "YesonCheck_Setup_99.0.0.exe"), "rb") as fh:
        assert fh.read() == b"MZ setup"
    assert os.listdir(success.package_dir) == ["YesonCheck_Setup_99.0.0.exe"]  # 복사 (원본은 그대로)


def app_log(*lines):
    """업데이트 기록: 앱의 줄(update_install.log — "<시각> [pid N] …")과 도우미의 줄("<시각> 도우미: …")."""
    return "".join(T + (line if line.startswith("도우미: ") else "[pid 4100] " + line) + "\n" for line in lines)


CLOSE_OTHERS_LOG = [
    "업데이트 99.0.0: 다른 창 확인 (받기 전, 앱 자리 C:\\yc_update\\other_window\\apps\\YesonCheck)",
    "업데이트 99.0.0: 다른 창 확인 끝 — 다른 사용자의 프로세스 0개, 다른 창 1개",
    "업데이트 99.0.0: 다른 창도 닫고 업데이트할지 물음",
    "업데이트 99.0.0: → 모두 닫고 업데이트",
    "업데이트 99.0.0: 받기 시작 → C:\\yc_update\\other_window\\user\\YesonCheck\\updates\\downloads",
    "업데이트 99.0.0: 다른 창 확인 (넘기기 전, 앱 자리 …)",
    "업데이트 99.0.0: 다른 창 1개에 닫기를 요청하고 프로세스가 끝나기를 기다림 (요청의 답을 받은 뒤 최대 90초): Yeson Checker (pid 5300)",
    "업데이트 99.0.0: 다른 창이 끝남 — Yeson Checker (pid 5300)",
    "업데이트 99.0.0: 닫기 요청의 답",
    "업데이트 99.0.0: 다른 창 1개가 모두 끝남 — 도우미에 넘김",
    "업데이트 99.0.0: 도우미를 띄움",
    "도우미: 시작: 대상 버전 99.0.0, 설치 폴더 …",
]


def test_close_others_sequence_needs_close_request_before_hand_off():
    update_e2e.assert_log_sequence(app_log(*CLOSE_OTHERS_LOG), update_e2e.close_others_sequence())
    # 닫기를 요청하지 않고(다른 창이 저절로 끝남) 넘겼거나, 도우미가 다른 창이 끝나기 전에 시작했으면 통과가 아님
    without_request = [line for line in CLOSE_OTHERS_LOG if "닫기를 요청" not in line]
    with pytest.raises(AssertionError, match="닫기를 요청"):
        update_e2e.assert_log_sequence(app_log(*without_request), update_e2e.close_others_sequence())
    helper_first = [CLOSE_OTHERS_LOG[-1], *CLOSE_OTHERS_LOG[:-1]]
    with pytest.raises(AssertionError, match="도우미: 시작"):
        update_e2e.assert_log_sequence(app_log(*helper_first), update_e2e.close_others_sequence())


ANSWERED = {"title": "다른 창도 닫고 업데이트", "text": "다른 YesonCheck 창 1개도 닫힙니다.", "answer": "모두 닫고 업데이트"}


@pytest.mark.parametrize("other_window, answered, error", [
    (True, [ANSWERED], None),
    (True, [ANSWERED, ANSWERED], None),  # 받은 뒤 다시 물음
    (True, [], "확인 창이 뜨지 않았습니다"),
    (True, [dict(ANSWERED, text="다른 YesonCheck 창 2개도 닫힙니다.")], "1개를 알리지 않았습니다"),
    (True, [dict(ANSWERED, answer="(단추 없음: 16384)")], "다른 확인 창에 답함"),
    (False, [], None),
    (False, [ANSWERED], "다른 창이 없는데"),
])
def test_check_close_others_answer(other_window, answered, error):
    case = SimpleNamespace(other_window=other_window)
    report = {"checks": [], "dialogs": [], "answered": answered}
    if error is None:
        assert update_e2e.check_close_others_answer(case, report) == answered
    else:
        with pytest.raises(AssertionError, match=error):
            update_e2e.check_close_others_answer(case, report)


def test_check_second_window_closed_needs_a_clean_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(update_e2e, "instance_record_path", lambda case, pid: str(tmp_path / f"{pid}.json"))
    log = app_log(*CLOSE_OTHERS_LOG)
    second = SimpleNamespace(pid=5300, poll=lambda: 0)
    assert update_e2e.check_second_window_closed(None, second, log) == 0
    for code, message in ((None, "아직 돕니다"), (1, "종료 코드 1")):
        with pytest.raises(AssertionError, match=message):
            update_e2e.check_second_window_closed(None, SimpleNamespace(pid=5300, poll=lambda c=code: c), log)
    (tmp_path / "5300.json").write_text("{}", encoding="utf-8")  # 정상 종료면 창 기록을 지움
    with pytest.raises(AssertionError, match="창 기록이 남아"):
        update_e2e.check_second_window_closed(None, second, log)
