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
    """Windows 동작 + 가짜 네트워크 드라이브 Y: = NAS (공유 루트와 그 아래 '작품' 폴더만 열림).

    시스템 드라이브 바로 아래의 UNC 링크(C:\\USA_DB 같은)는 state.links (기본 없음). %SystemDrive%는 tmp 아래의
    없는 폴더 → Harmony식 설정 폴더(C:\\USA_DB\\test_jn\\.yesoncheck)도 이 PC의 실제 C:를 보지 않음.
    """
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("SystemDrive", str(tmp_path / "sysdrive"))
    state = SimpleNamespace(shares=[Share(NAS, ["Y:"])], folders={NAS.casefold(), f"{NAS}\\작품".casefold()},
                            answers=[], accept=True, shown=[], players=[], links=[])
    monkeypatch.setattr(path_map_setup, "connected_shares", lambda remote_of_drive=None: (state.shares, []))
    monkeypatch.setattr(path_map_setup, "local_link_shares", lambda *a, **k: (state.links, []))
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


# --- Harmony용 링크만 있는 PC: C:\USA_DB → \\서버\USA_DB (네트워크 드라이브에는 USA_DB 공유가 없음) ---

def harmony_mirror(tmp_path):
    """win의 %SystemDrive% 아래 Mac 공유 설정 경로 모양 (C:\\USA_DB\\test_jn\\.yesoncheck)."""
    return str(tmp_path / "sysdrive") + "\\USA_DB\\test_jn\\.yesoncheck"


def settings_of(tmp_path):
    with open(os.path.join(str(tmp_path / "appdata"), "YesonCheck", "settings.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_config_dir_found_through_harmony_link(win, dialogs, tmp_path, monkeypatch):
    mirror = harmony_mirror(tmp_path)
    real = "\\\\localhost\\yc_fake_usadb\\test_jn\\.yesoncheck"
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: p.casefold() == f"{mirror}\\work_paths.json".casefold())
    monkeypatch.setattr(path_map_setup, "_default_realpath", lambda p: {mirror: real}[p])
    player = win.player()
    assert settings_of(tmp_path) == {"config_dir": real}  # 링크의 실제 UNC를 저장 (다른 PC와 같은 주소)
    assert player.work_paths_config_dir == real
    assert player.config_dir_candidates == []


def test_harmony_link_and_drive_to_same_config_count_once(win, dialogs, tmp_path, monkeypatch):
    share = "\\\\localhost\\yc_fake_usadb"
    win.shares = [Share(share, ["U:"])]
    mirror = harmony_mirror(tmp_path)
    real = f"{share}\\test_jn\\.yesoncheck"
    files = {f"{mirror}\\work_paths.json".casefold(), f"{real}\\work_paths.json".casefold()}
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: p.casefold() in files)
    monkeypatch.setattr(path_map_setup, "_default_realpath", lambda p: {mirror: real.upper()}[p])
    player = win.player()
    assert player.config_dir_candidates == []  # 같은 폴더 → 후보 하나 → 바로 씀
    assert paths.unc_key(settings_of(tmp_path)["config_dir"]) == paths.unc_key(real)


def test_local_harmony_folder_is_not_used(win, dialogs, tmp_path, monkeypatch, capsys):
    """C:\\USA_DB\\test_jn\\.yesoncheck가 링크가 아닌 진짜 로컬 폴더 → 쓰지 않고(로그) 드라이브에서 찾은 폴더를 씀."""
    b = "\\\\localhost\\yc_fake_b"
    win.shares = [Share(b, ["B:"])]
    mirror = harmony_mirror(tmp_path)
    other = f"{b}\\test_jn\\.yesoncheck"
    files = {f"{mirror}\\work_paths.json".casefold(), f"{other}\\work_paths.json".casefold()}
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: p.casefold() in files)
    monkeypatch.setattr(path_map_setup, "_default_realpath", lambda p: p)  # 링크가 아닌 진짜 로컬 폴더
    player = win.player()
    assert player.config_dir_candidates == []
    assert settings_of(tmp_path) == {"config_dir": other}
    assert f"{mirror} 는 링크가 아니라 로컬 폴더 — 쓰지 않음" in capsys.readouterr().out


def test_harmony_link_realpath_error_continues_with_drives(win, dialogs, tmp_path, monkeypatch, capsys):
    b = "\\\\localhost\\yc_fake_b"
    win.shares = [Share(b, ["B:"])]
    mirror = harmony_mirror(tmp_path)
    other = f"{b}\\test_jn\\.yesoncheck"
    files = {f"{mirror}\\work_paths.json".casefold(), f"{other}\\work_paths.json".casefold()}
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: p.casefold() in files)

    def broken(path):
        raise OSError(53, "네트워크 경로를 찾을 수 없습니다 (가짜 재현)")

    monkeypatch.setattr(path_map_setup, "_default_realpath", broken)
    player = win.player()
    assert settings_of(tmp_path) == {"config_dir": other}  # 드라이브 후보로 계속
    assert player.work_paths_config_dir == other and player.config_dir_candidates == []
    assert "가짜 재현" in capsys.readouterr().out


def test_harmony_link_realpath_error_shown_when_nothing_found(win, dialogs, tmp_path, monkeypatch):
    win.shares = []
    mirror = harmony_mirror(tmp_path)
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: p.casefold() == f"{mirror}\\work_paths.json".casefold())

    def broken(path):
        raise OSError(53, "네트워크 경로를 찾을 수 없습니다 (가짜 재현)")

    monkeypatch.setattr(path_map_setup, "_default_realpath", broken)
    player = win.player()
    assert player.config_dir_search_failed and player.shared_config_problem
    player.resolve_shared_config_problem()  # 폴더 선택 안내에 확인하지 못한 곳이 보임 (dialogs.folders 비어 있음 → 취소)
    infos = [text for kind, title, text in dialogs.messages if kind == "information" and title == "공유 설정 폴더 선택"]
    assert len(infos) == 1 and mirror in infos[0] and "가짜 재현" in infos[0]


def test_choose_config_dir_on_link_uses_real_unc(win, dialogs, tmp_path, monkeypatch, capsys):
    """C:\\USA_DB 아래를 고르면 drive_to_unc는 실패(로컬 드라이브) → 링크의 실제 UNC로 확인·저장."""
    player = win.player(make_config(str(tmp_path), WORK, {"version": 1, "shares": [{"mac": "/Volumes/yc", "windows": [NAS]}]}))
    monkeypatch.delenv("YESONCHECK_CONFIG_DIR")  # 이제부터는 PC별 설정(고른 폴더)을 씀
    folder = "C:/USA_DB/test_jn/.yesoncheck"
    real = "\\\\localhost\\yc_fake_usadb\\test_jn\\.yesoncheck"
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda drive: None)  # C:는 네트워크 드라이브가 아님
    monkeypatch.setattr(path_map_setup, "_default_realpath", lambda p: {folder: real}[p])
    validated = []
    monkeypatch.setattr(shared_config, "validate_config_dir", validated.append)
    dialogs.folders.append(folder)
    capsys.readouterr()
    assert player.choose_shared_config_dir() is True
    assert validated[0] == real
    assert settings_of(tmp_path) == {"config_dir": real}
    assert not any(title == "다른 폴더를 고르세요" for _kind, title, _text in dialogs.messages)
    log = capsys.readouterr().out
    assert "네트워크 드라이브가 아닙니다" in log and f"→ 링크의 실제 위치 {real} 사용" in log  # 원래 오류도 남김


def test_choose_folder_on_unreadable_network_drive_keeps_warning(win, dialogs, tmp_path, monkeypatch):
    """드라이브 연결 정보를 읽지 못한 오류(로컬 드라이브라서가 아님)는 링크로 대신하지 않고 예전처럼 경고."""
    player = win.player(make_config(str(tmp_path), WORK, {"version": 1, "shares": [{"mac": "/Volumes/yc", "windows": [NAS]}]}))

    def unreadable(drive):
        raise paths.PathMapError(f"{drive} 드라이브의 연결 정보를 읽지 못했습니다 (WNetGetConnectionW 오류 1203)")

    monkeypatch.setattr(paths, "_remote_name_of_drive", unreadable)
    monkeypatch.setattr(path_map_setup, "_default_realpath", lambda p: pytest.fail(f"realpath를 불렀습니다: {p}"))
    dialogs.folders.append("Z:/USA_DB/test_jn/.yesoncheck")
    assert player.choose_shared_config_dir() is False
    warnings = [text for kind, title, text in dialogs.messages if kind == "warning" and title == "다른 폴더를 고르세요"]
    assert len(warnings) == 1 and "WNetGetConnectionW 오류 1203" in warnings[0]


def test_choose_plain_local_folder_still_warns(win, dialogs, tmp_path, monkeypatch):
    player = win.player(make_config(str(tmp_path), WORK, {"version": 1, "shares": [{"mac": "/Volumes/yc", "windows": [NAS]}]}))
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda drive: None)
    monkeypatch.setattr(path_map_setup, "_default_realpath", lambda p: p.replace("/", "\\"))  # 링크 아님 → 로컬 그대로
    dialogs.folders.append("C:/work")
    assert player.choose_shared_config_dir() is False
    warnings = [text for kind, title, text in dialogs.messages if kind == "warning" and title == "다른 폴더를 고르세요"]
    assert len(warnings) == 1 and "네트워크 드라이브가 아닙니다" in warnings[0]


def test_link_share_is_preferred_alias(win, dialogs, tmp_path):
    """USA_DB에 드라이브 문자 없이 링크로만 연결된 PC → 변환표에서 그 링크의 UNC를 먼저 씀 (작품이 열림)."""
    link, other = "\\\\localhost\\yc_fake_link", "\\\\localhost\\yc_fake_ip"
    win.shares = []
    win.links = [Share(link, ["C:\\yc"])]
    win.folders |= {link.casefold(), f"{link}\\작품".casefold()}
    config = make_config(str(tmp_path), WORK, {"version": 1, "shares": [{"mac": "/Volumes/yc", "windows": [other, link]}]})
    player = win.player(config)
    assert paths.to_native("/Volumes/yc/작품") == link + "\\작품"
    player.resolve_shared_config_problem()
    assert win.shown == [] and dialogs.messages == []


def test_auto_setup_finds_pair_through_link_share(win, dialogs, tmp_path):
    win.shares = []
    win.links = [Share(NAS, ["C:\\yc"])]
    config = make_config(str(tmp_path), WORK)
    win.answers.extend([("pw", True), ("pw", True)])
    player = win.player(config)
    player.resolve_shared_config_problem()
    assert len(win.shown) == 1
    (_check, combo, _pair), = win.shown[0]._rows
    assert "C:\\yc" in combo.itemText(0)  # 링크 이름이 드라이브 자리에 보임
    assert read_map(config)["shares"] == [{"mac": "/Volumes/yc", "windows": [NAS]}]


# --- 응답하지 않는 공유 (서버 주소가 바뀌어 남은 \\BGSERVER\bgfinal 같은): 정해진 시간까지만 기다리고 알림 ---

DEAD = "\\\\localhost\\yc_fake_dead"


@pytest.fixture
def short_timeout(monkeypatch):
    monkeypatch.setattr(path_map_setup, "SHARE_PROBE_TIMEOUT_S", 0.3)
    return 0.3


@pytest.fixture
def dead_share_hangs(win, monkeypatch):
    """DEAD 아래를 열어 보면 release까지 막힘 (시험이 끝나면 풀림)."""
    import threading

    release = threading.Event()
    is_dir, is_file = path_map_setup._default_is_dir, path_map_setup._default_is_file

    def hang_or(func):
        def probe(path):
            if path.casefold().startswith(DEAD.casefold()):
                release.wait(30)
                return False
            return func(path)
        return probe

    monkeypatch.setattr(path_map_setup, "_default_is_dir", hang_or(is_dir))
    monkeypatch.setattr(path_map_setup, "_default_is_file", hang_or(is_file))
    yield release
    release.set()


def label_texts(dialog):
    return "\n".join(label.text() for label in dialog.findChildren(QLabel))


def test_config_search_skips_share_that_never_answers(win, dialogs, short_timeout, dead_share_hangs):
    import time

    win.shares = [Share(DEAD, ["W:"])]
    started = time.monotonic()
    player = win.player()
    assert time.monotonic() - started < 3
    line = f"W: ({DEAD}) — 0.3초 안에 응답 없음 (서버가 꺼졌거나 느림)"
    assert player.config_dir_search_problems == [line] and player.config_dir_search_failed
    player.resolve_shared_config_problem()  # 폴더 선택 안내에 보임 (dialogs.folders 비어 있음 → 취소)
    infos = [text for kind, title, text in dialogs.messages if kind == "information" and title == "공유 설정 폴더 선택"]
    assert len(infos) == 1 and line in infos[0]


def test_configured_config_dir_that_never_answers(win, dialogs, short_timeout, tmp_path, monkeypatch):
    import threading
    import time

    slow = f"{DEAD}\\.yesoncheck"
    settings = tmp_path / "appdata" / "YesonCheck" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"config_dir": slow}), encoding="utf-8")
    release = threading.Event()
    real_valid = shared_config.is_valid_config_dir

    def valid(path):
        if path == slow:
            release.wait(30)
            return False
        return real_valid(path)

    monkeypatch.setattr(shared_config, "is_valid_config_dir", valid)
    monkeypatch.setattr(path_map_setup, "find_config_dirs", lambda *a, **k: pytest.fail("자동 찾기를 했습니다"))
    try:
        started = time.monotonic()
        player = win.player()
        assert time.monotonic() - started < 3
    finally:
        release.set()
    expected = f"공유 설정 폴더가 0.3초 안에 응답하지 않습니다: {slow} (서버가 꺼졌거나 느림)"
    assert player.shared_config_problem == expected
    assert player.work_paths_config_dir is None  # GUI 스레드의 resolve가 그 폴더를 다시 열어 보지 않게
    player.resolve_shared_config_problem()
    infos = [text for kind, title, text in dialogs.messages if kind == "information" and title == "공유 설정 폴더 선택"]
    assert len(infos) == 1 and expected in infos[0]


def test_works_check_skips_root_that_never_answers(win, dialogs, short_timeout, dead_share_hangs, monkeypatch):
    import time

    from yesoncheck import player_sidebar

    works = {"A": "/Volumes/dead/A", "B": "/Volumes/dead/B", "W": "/Volumes/yc/작품"}
    path_map = paths.PathMap.from_dict({"version": 1, "shares": [
        {"mac": "/Volumes/dead", "windows": [DEAD]}, {"mac": "/Volumes/yc", "windows": [NAS]},
    ]}, "시험")
    calls = []
    hanging = path_map_setup._default_is_dir

    def is_dir(path):
        calls.append(path.casefold())
        return hanging(path)

    monkeypatch.setattr(path_map_setup, "_default_is_dir", is_dir)
    started = time.monotonic()
    broken = player_sidebar.list_works_not_opening(works, path_map.mac_to_windows)
    assert time.monotonic() - started < 3
    assert [c for c in calls if c.startswith(DEAD.casefold())] == [DEAD.casefold()]  # 루트만 한 번
    assert len(broken) == 2
    assert broken[0].startswith("A: ") and f"공유 폴더 {DEAD}가 0.3초 안에 응답 없음" in broken[0]
    assert broken[1].startswith("B: ") and "응답 없음" in broken[1]


def test_auto_setup_skips_root_that_never_answers(win, dialogs, short_timeout, dead_share_hangs, tmp_path):
    import time

    win.shares = [Share(DEAD, ["W:"]), Share(NAS, ["Y:"])]
    config = make_config(str(tmp_path), WORK)
    win.accept = False
    player = win.player(config)
    started = time.monotonic()
    player.resolve_shared_config_problem()
    assert time.monotonic() - started < 3
    assert len(win.shown) == 1
    text = label_texts(win.shown[0])
    assert f"W: ({DEAD}) — 공유 폴더가 0.3초 안에 응답 없음 (서버가 꺼졌거나 느림)" in text
    assert win.shown[0].chosen() == [("/Volumes/yc", NAS)]  # 응답한 공유의 짝은 그대로


def test_auto_setup_cancel_while_waiting_for_root(win, dialogs, dead_share_hangs, tmp_path, monkeypatch):
    """GUI 스레드에서 루트를 기다리는 동안에도 진행 창을 처리하고 취소를 받음 (시간 제한보다 먼저 끝남)."""
    import time

    monkeypatch.setattr(path_map_setup, "SHARE_PROBE_TIMEOUT_S", 30)
    monkeypatch.setattr(QProgressDialog, "wasCanceled", lambda self: True)
    win.shares = [Share(DEAD, ["W:"])]
    config = make_config(str(tmp_path), WORK)
    player = win.player(config)
    started = time.monotonic()
    assert player.auto_setup_path_map(ask_password=False, startup=True) is False
    assert time.monotonic() - started < 3
    assert win.shown == []
    assert len(path_map_criticals(dialogs)) == 1  # 시작할 때의 변환표 문제는 한 번 알림 (취소한 경우도)
