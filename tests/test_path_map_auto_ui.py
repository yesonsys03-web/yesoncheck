"""Windows 자동 연결 흐름 (Mac·Windows 공통: Windows 동작과 네트워크 드라이브를 흉내 냄).

가짜 주소는 \\\\localhost\\yc_fake… 를 씀: Windows CI에서 실제로 열어 봐도 바로 실패해 시험이 느려지지 않음.
"""

import hashlib
import json
import os
from types import SimpleNamespace

import pytest
from PyQt5.QtCore import QCoreApplication, QEvent
from PyQt5.QtWidgets import QDialog, QInputDialog, QLabel, QProgressDialog

from yesoncheck import path_map_setup, paths, shared_config
from yesoncheck.path_map_setup import Share
from yesoncheck.path_map_setup_dialog import PathMapSetupDialog
from tests.test_work_paths_ui import make_config

NAS = "\\\\localhost\\yc_fake"
WORK = {"W": "/Volumes/yc/작품"}


@pytest.fixture
def win(qapp, dialogs, monkeypatch, tmp_path):
    """Windows 동작 + 가짜 네트워크 드라이브 Y: = NAS (공유 루트와 그 아래 '작품' 폴더만 열림)."""
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    state = SimpleNamespace(shares=[Share(NAS, ["Y:"])], folders={NAS.casefold(), f"{NAS}\\작품".casefold()},
                            answers=[], accept=True, shown=[], players=[])
    monkeypatch.setattr(path_map_setup, "connected_shares", lambda remote_of_drive=None: (state.shares, []))
    monkeypatch.setattr(path_map_setup, "_default_is_dir", lambda p: p.casefold() in state.folders)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: state.answers.pop(0))

    def fake_exec(self):
        state.shown.append(self)
        return QDialog.Accepted if state.accept else QDialog.Rejected

    monkeypatch.setattr(PathMapSetupDialog, "exec_", fake_exec)

    def player(config_dir=None):
        if config_dir is None:
            monkeypatch.delenv("YESONCHECK_CONFIG_DIR", raising=False)
        else:
            monkeypatch.setenv("YESONCHECK_CONFIG_DIR", config_dir)
        from yesoncheck.main_window import VideoPlayer

        p = VideoPlayer()
        state.players.append(p)
        return p

    state.player = player
    yield state
    for p in state.players:
        p.close()
    paths.activate(None)


def read_map(config):
    with open(os.path.join(config, "path_map.json"), encoding="utf-8") as fh:
        return json.load(fh)


def path_map_criticals(dialogs):
    return [text for kind, title, text in dialogs.messages if kind == "critical" and "변환표" in title]


def test_startup_auto_setup_writes_path_map(win, dialogs, tmp_path):
    config = make_config(str(tmp_path), WORK)
    win.answers.extend([("pw", True), ("pw", True)])  # 최초 비밀번호 설정 + 확인
    player = win.player(config)
    assert player.path_map_problem and player.shared_config_problem is None
    player.resolve_shared_config_problem()
    assert len(win.shown) == 1
    assert read_map(config)["shares"] == [{"mac": "/Volumes/yc", "windows": [NAS]}]
    assert player.path_map_problem is None
    assert os.path.exists(os.path.join(config, "work_paths_password.json"))


def test_cancel_writes_nothing(win, dialogs, tmp_path):
    config = make_config(str(tmp_path), WORK)
    win.accept = False
    player = win.player(config)
    player.resolve_shared_config_problem()
    assert not os.path.exists(os.path.join(config, "path_map.json"))
    assert len(path_map_criticals(dialogs)) == 1


def test_wrong_password_writes_nothing(win, dialogs, tmp_path):
    config = make_config(str(tmp_path), WORK)
    with open(os.path.join(config, "work_paths_password.json"), "w", encoding="utf-8") as fh:
        json.dump({"password_hash": hashlib.sha256("right".encode("utf-8")).hexdigest()}, fh)
    win.answers.append(("wrong", True))
    player = win.player(config)
    player.resolve_shared_config_problem()
    assert not os.path.exists(os.path.join(config, "path_map.json"))
    assert any("비밀번호가 올바르지 않습니다" in text for _k, _t, text in dialogs.messages)


def test_nothing_to_add_shows_no_dialog(win, dialogs, tmp_path):
    config = make_config(str(tmp_path), WORK)
    win.shares = []
    player = win.player(config)
    player.resolve_shared_config_problem()
    assert win.shown == []
    assert len(path_map_criticals(dialogs)) == 1


def test_unreadable_template_is_backed_up(win, dialogs, tmp_path):
    config = make_config(str(tmp_path), WORK)
    with open(os.path.join(config, "path_map.json"), "w", encoding="utf-8") as fh:
        fh.write('{"version": 1, "shares": [{"mac": "/Volumes/yc", "windows": ["여기에_붙여넣기"]}]}')
    win.answers.extend([("pw", True), ("pw", True)])
    player = win.player(config)
    player.resolve_shared_config_problem()
    backups = [n for n in os.listdir(config) if n.startswith("path_map.json.bak-")]
    assert len(backups) == 1
    assert "여기에_붙여넣기" in open(os.path.join(config, backups[0]), encoding="utf-8").read()
    assert read_map(config)["shares"] == [{"mac": "/Volumes/yc", "windows": [NAS]}]


def test_existing_entry_gets_alias(win, dialogs, tmp_path):
    old = "\\\\localhost\\yc_fake_old"
    config = make_config(str(tmp_path), WORK, {"version": 1, "shares": [{"mac": "/Volumes/yc", "windows": [old]}]})
    win.answers.extend([("pw", True), ("pw", True)])
    player = win.player(config)
    assert player.path_map_problem is None
    player.resolve_shared_config_problem()  # 변환표는 정상이지만 작품이 열리지 않음 → 자동 설정 제안
    assert read_map(config)["shares"] == [{"mac": "/Volumes/yc", "windows": [old, NAS]}]  # 첫 주소는 그대로
    # 이 PC는 연결된 드라이브(NAS)와 맞는 주소를 먼저 엶 → 저장 후 바로, 그리고 다음 시작에도 작품이 열림
    assert paths.to_native("/Volumes/yc/작품") == NAS + "\\작품"
    assert dialogs.errors() == []
    win.player(config)
    assert paths.to_native("/Volumes/yc/작품") == NAS + "\\작품"


def test_manage_opens_with_only_path_map_problem(win, dialogs, tmp_path, monkeypatch):
    config = make_config(str(tmp_path), WORK)
    win.answers.extend([("pw", True), ("pw", True)])
    monkeypatch.setattr(QDialog, "exec_", lambda self: QDialog.Rejected)
    player = win.player(config)
    assert player.path_map_problem and player.shared_config_problem is None
    player.manage_work_paths()
    assert not any("관리할 수 없습니다" in text for _k, _t, text in dialogs.messages)
    assert os.path.exists(os.path.join(config, "work_paths_password.json"))


def test_config_dir_auto_found_and_saved(win, dialogs, tmp_path, monkeypatch):
    share = "\\\\localhost\\yc_fake_cfg"
    win.shares = [Share(share, ["U:"])]
    target = f"{share}\\test_jn\\.yesoncheck"
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: p.casefold() == f"{target}\\work_paths.json".casefold())
    player = win.player()
    with open(os.path.join(str(tmp_path / "appdata"), "YesonCheck", "settings.json"), encoding="utf-8") as fh:
        assert json.load(fh) == {"config_dir": target}
    assert player.work_paths_config_dir == target


def test_multiple_config_dirs_pick_one(win, dialogs, tmp_path, monkeypatch):
    a, b = "\\\\localhost\\yc_fake_a", "\\\\localhost\\yc_fake_b"
    win.shares = [Share(a, ["A:"]), Share(b, ["B:"])]
    targets = [f"{a}\\test_jn\\.yesoncheck", f"{b}\\test_jn\\.yesoncheck"]
    files = {f"{t}\\work_paths.json".casefold() for t in targets}
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: p.casefold() in files)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: (targets[1], True))
    player = win.player()
    assert player.config_dir_candidates == targets
    player.resolve_shared_config_problem()
    with open(os.path.join(str(tmp_path / "appdata"), "YesonCheck", "settings.json"), encoding="utf-8") as fh:
        assert json.load(fh) == {"config_dir": targets[1]}


def test_no_config_dir_found_opens_folder_picker(win, dialogs, tmp_path, monkeypatch):
    win.shares = [Share("\\\\localhost\\yc_fake_none", ["N:"])]
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: False)
    player = win.player()
    assert player.config_dir_candidates == [] and player.shared_config_problem
    player.resolve_shared_config_problem()  # dialogs.folders가 비어 있음 → 폴더 선택 취소
    assert any(kind == "information" and "연결된 네트워크 드라이브에서 공유 설정 폴더를 찾지 못했습니다" in text
               for kind, _t, text in dialogs.messages)
    assert any(kind == "critical" and title == "공유 설정 오류" for kind, title, _text in dialogs.messages)
    assert not os.path.exists(os.path.join(str(tmp_path / "appdata"), "YesonCheck", "settings.json"))


def test_startup_progress_cancel_shows_one_critical(win, dialogs, tmp_path, monkeypatch):
    """Finding 1 ruling 1c: 진행 창 취소도 (다른 미저장 경로처럼) 변환표 오류를 한 번 알려야 함."""
    config = make_config(str(tmp_path), WORK)

    def cancelled(*args, **kwargs):
        raise path_map_setup.SetupCancelled()

    monkeypatch.setattr(path_map_setup, "propose_mapping", cancelled)
    player = win.player(config)
    assert player.path_map_problem
    player.resolve_shared_config_problem()
    assert not os.path.exists(os.path.join(config, "path_map.json"))
    assert len(path_map_criticals(dialogs)) == 1


def test_startup_password_cancelled_shows_one_critical(win, dialogs, tmp_path):
    """Finding 1 ruling 1c: 시작할 때 비밀번호를 취소해도 변환표 오류를 한 번 알려야 함."""
    config = make_config(str(tmp_path), WORK)
    win.answers.append(("", False))  # 최초 비밀번호 설정 창에서 취소
    player = win.player(config)
    assert player.path_map_problem
    player.resolve_shared_config_problem()
    assert not os.path.exists(os.path.join(config, "path_map.json"))
    assert len(path_map_criticals(dialogs)) == 1


def test_startup_with_both_problems_reports_both(win, dialogs, tmp_path):
    """Finding 1 ruling 1a/1b: 공유 설정·변환표 문제가 둘 다 있으면 제목·시작 오류가 둘 다 보여야 함."""
    config = make_config(str(tmp_path), None, raw="{broken")  # work_paths.json도 깨지고 path_map.json도 없음
    player = win.player(config)
    assert player.shared_config_problem and player.path_map_problem
    assert "공유 설정 오류" in player.windowTitle()
    assert "변환표 오류" in player.windowTitle()
    player.resolve_shared_config_problem()
    criticals = [text for kind, title, text in dialogs.messages if kind == "critical" and title == "공유 설정 오류"]
    assert len(criticals) == 1
    assert "읽지 못했습니다" in criticals[0]  # work_paths.json 오류
    assert "변환표 파일이 없습니다" in criticals[0]  # path_map.json 오류


def test_no_additions_and_no_path_map_problem_is_silent(win, dialogs, tmp_path):
    """Review Focus 5: 변환표는 정상이지만 더할 짝이 없으면(연결된 드라이브 없음) 아무 창도 띄우지 않음."""
    old = "\\\\localhost\\yc_fake_old"
    config = make_config(str(tmp_path), WORK, {"version": 1, "shares": [{"mac": "/Volumes/yc", "windows": [old]}]})
    win.shares = []
    player = win.player(config)
    assert player.path_map_problem is None
    player.resolve_shared_config_problem()
    assert win.shown == []
    assert not any(kind in ("critical", "warning") for kind, _title, _text in dialogs.messages)


def test_reread_failure_after_save_shows_shared_config_error(win, dialogs, tmp_path, monkeypatch):
    """Finding 2 ruling 2a: 저장 후 다시 읽기가 실패해도 저장은 된 것 — "변환표 저장됨"이 아니라 공유 설정 오류로 알림."""
    config = make_config(str(tmp_path), WORK)
    player = win.player(config)
    assert player.path_map_problem  # 아직 변환표 없음 → 저장할 것이 있음

    def boom(_path):
        raise shared_config.SharedConfigError("읽기 실패 (가짜 재현)")

    monkeypatch.setattr(shared_config, "read_work_paths", boom)
    result = player.auto_setup_path_map(ask_password=False)
    assert result is True
    assert read_map(config)["shares"] == [{"mac": "/Volumes/yc", "windows": [NAS]}]

    criticals = [text for kind, title, text in dialogs.messages if kind == "critical" and title == "공유 설정 오류"]
    assert len(criticals) == 1
    assert "변환표를 저장했습니다" in criticals[0]
    assert "읽기 실패 (가짜 재현)" in criticals[0]
    assert not any(kind == "information" and title == "변환표 저장됨" for kind, title, _text in dialogs.messages)


def test_one_share_under_two_mac_prefixes_asks_once(win, dialogs, tmp_path):
    """Final #2: Mac이 같은 공유를 /Volumes/yc와 /Volumes/yc-1로 연결해 둔 작품들 → 한 UNC가 두 앞부분에 맞음.

    작품이 더 많은 /Volumes/yc만 기본으로 넣고 /Volumes/yc-1 줄은 이유와 함께 꺼 둠. 다음 시작에는 창·오류 없음.
    """
    works = {"A": "/Volumes/yc/작품", "B": "/Volumes/yc/작품B", "C": "/Volumes/yc-1/작품C"}
    win.folders |= {f"{NAS}\\작품B".casefold(), f"{NAS}\\작품C".casefold()}
    config = make_config(str(tmp_path), works)
    win.answers.extend([("pw", True), ("pw", True)])
    player = win.player(config)
    player.resolve_shared_config_problem()
    assert len(win.shown) == 1
    dialog = win.shown[0]
    rows = {pair.mac_prefix: check for check, _combo, pair in dialog._rows}
    assert rows["/Volumes/yc"].isChecked() and not rows["/Volumes/yc-1"].isChecked()
    assert "/Volumes/yc-1" in "\n".join(label.text() for label in dialog.findChildren(QLabel))
    assert dialog.chosen() == [("/Volumes/yc", NAS)]
    assert read_map(config)["shares"] == [{"mac": "/Volumes/yc", "windows": [NAS]}]
    assert path_map_criticals(dialogs) == []

    before = len(dialogs.messages)
    second = win.player(config)
    assert second.path_map_problem is None
    second.resolve_shared_config_problem()
    assert len(win.shown) == 1  # 두 번째 시작: 창 없음
    assert [m for m in dialogs.messages[before:] if m[0] == "critical"] == []
    assert win.answers == []  # 비밀번호도 묻지 않음


def test_user_checked_unmergeable_row_fails_before_password(win, dialogs, tmp_path, monkeypatch):
    """Final #2: 꺼 둔 줄을 사용자가 켜서 저장하면 비밀번호를 묻기 전에 "변환표 저장 실패"로 알림."""
    works = {"A": "/Volumes/yc/작품", "B": "/Volumes/yc/작품B", "C": "/Volumes/yc-1/작품C"}
    win.folders |= {f"{NAS}\\작품B".casefold(), f"{NAS}\\작품C".casefold()}
    config = make_config(str(tmp_path), works)

    def check_all(self):
        win.shown.append(self)
        for check, _combo, _pair in self._rows:
            check.setChecked(True)
        return QDialog.Accepted

    monkeypatch.setattr(PathMapSetupDialog, "exec_", check_all)
    player = win.player(config)
    assert player.auto_setup_path_map(ask_password=True) is False  # win.answers가 비어 있음 → 비밀번호를 물으면 실패
    assert not os.path.exists(os.path.join(config, "path_map.json"))
    failures = [text for kind, title, text in dialogs.messages if kind == "critical" and title == "변환표 저장 실패"]
    assert len(failures) == 1
    assert "번째 항목에도 있습니다" in failures[0] and "Traceback" in failures[0]


def test_entry_written_by_another_pc_during_dialog_is_kept(win, dialogs, tmp_path, monkeypatch):
    """Final #3: 확인 창·비밀번호 사이에 다른 PC가 쓴 항목을 덮어쓰지 않음 (저장 직전에 다시 읽어 합침)."""
    config = make_config(str(tmp_path), WORK)
    other = {"mac": "/Volumes/other", "windows": ["\\\\localhost\\yc_fake_other"]}

    def other_pc_writes(self):
        win.shown.append(self)
        with open(os.path.join(config, "path_map.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "shares": [other]}, fh)
        return QDialog.Accepted

    monkeypatch.setattr(PathMapSetupDialog, "exec_", other_pc_writes)
    win.answers.extend([("pw", True), ("pw", True)])
    player = win.player(config)
    player.resolve_shared_config_problem()
    assert read_map(config)["shares"] == [other, {"mac": "/Volumes/yc", "windows": [NAS]}]
    assert [n for n in os.listdir(config) if n.startswith("path_map.json.bak-")] == []
    assert path_map_criticals(dialogs) == []


def test_cp949_path_map_is_backed_up_at_startup(win, dialogs, tmp_path):
    """Final #4: 메모장 ANSI(CP949)로 저장된 path_map.json → 오류 대신 백업 후 새로 만듦."""
    config = make_config(str(tmp_path), WORK)
    raw = '{"version": 1, "shares": [{"mac": "/Volumes/작품", "windows": ["여기에_붙여넣기"]}]}'.encode("cp949")
    with open(os.path.join(config, "path_map.json"), "wb") as fh:
        fh.write(raw)
    win.answers.extend([("pw", True), ("pw", True)])
    player = win.player(config)
    assert player.path_map_problem
    player.resolve_shared_config_problem()
    backups = [n for n in os.listdir(config) if n.startswith("path_map.json.bak-")]
    assert len(backups) == 1
    with open(os.path.join(config, backups[0]), "rb") as fh:
        assert fh.read() == raw
    assert read_map(config)["shares"] == [{"mac": "/Volumes/yc", "windows": [NAS]}]


def test_works_not_opening_probes_dead_share_root_once(win, dialogs, tmp_path, monkeypatch):
    """Final #5: 서버가 꺼진 공유의 작품들은 공유 루트를 한 번만 열어 보고 작품 폴더는 열어 보지 않음."""
    dead = "\\\\localhost\\yc_fake_dead"
    works = {"A": "/Volumes/dead/A", "B": "/Volumes/dead/B", "W": "/Volumes/yc/작품", "X": "/Volumes/yc/없음"}
    config = make_config(str(tmp_path), works, {"version": 1, "shares": [
        {"mac": "/Volumes/dead", "windows": [dead]}, {"mac": "/Volumes/yc", "windows": [NAS]},
    ]})
    player = win.player(config)
    calls = []

    def is_dir(path):
        calls.append(path.casefold())
        return path.casefold() in win.folders

    monkeypatch.setattr(path_map_setup, "_default_is_dir", is_dir)
    broken = player._works_not_opening()
    assert [c for c in calls if c.startswith(dead.casefold())] == [dead.casefold()]
    assert calls.count(NAS.casefold()) == 1
    assert len(broken) == 3
    assert broken[0].startswith("A: ") and dead in broken[0] and "공유 폴더" in broken[0]
    assert broken[1].startswith("B: ") and dead in broken[1]
    assert broken[2].startswith("X: ") and f"{NAS}\\없음" in broken[2]


def test_use_config_dir_reports_both_problems(win, dialogs, tmp_path, monkeypatch):
    """Minor: 공유 설정 폴더를 고른 뒤의 "공유 설정 오류"도 변환표 오류를 함께 보여 줌 (시작 오류와 같게)."""
    good = make_config(str(tmp_path / "good"), WORK, {"version": 1, "shares": [{"mac": "/Volumes/yc", "windows": [NAS]}]})
    player = win.player(good)
    monkeypatch.delenv("YESONCHECK_CONFIG_DIR")  # 이제부터는 PC별 설정(고른 폴더)을 씀
    broken = make_config(str(tmp_path / "broken"), None, raw="{broken")  # path_map.json도 없음
    assert player._use_config_dir(broken) is True
    criticals = [text for kind, title, text in dialogs.messages if kind == "critical" and title == "공유 설정 오류"]
    assert len(criticals) == 1
    assert "읽지 못했습니다" in criticals[0] and "변환표 파일이 없습니다" in criticals[0]


def test_progress_dialog_is_deleted(win, dialogs, tmp_path):
    """Minor: 진행 창은 닫은 뒤 deleteLater로 지움 (자동 설정을 여러 번 해도 창 객체가 쌓이지 않음)."""
    config = make_config(str(tmp_path), WORK)
    player = win.player(config)
    win.accept = False
    for _ in range(2):
        player.auto_setup_path_map(ask_password=False)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert player.findChildren(QProgressDialog) == []
