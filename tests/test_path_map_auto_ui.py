"""Windows 자동 연결 흐름 (Mac·Windows 공통: Windows 동작과 네트워크 드라이브를 흉내 냄).

가짜 주소는 \\\\localhost\\yc_fake… 를 씀: Windows CI에서 실제로 열어 봐도 바로 실패해 시험이 느려지지 않음.
"""

import hashlib
import json
import os
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QDialog, QInputDialog

from yesoncheck import path_map_setup, paths
from yesoncheck.path_map_setup import Share
from yesoncheck.path_map_setup_dialog import PathMapSetupDialog
from tests.test_work_paths_ui import make_config

NAS = "\\\\localhost\\yc_fake"
WORK = {"W": "/Volumes/yc/작품"}


@pytest.fixture
def win(qapp, dialogs, monkeypatch, tmp_path):
    """Windows 동작 + 가짜 네트워크 드라이브 Y: = NAS (그 아래 '작품' 폴더만 열림)."""
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    state = SimpleNamespace(shares=[Share(NAS, ["Y:"])], folders={f"{NAS}\\작품".casefold()},
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
    assert any(kind == "critical" and "변환표" in title for kind, title, _text in dialogs.messages)


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
    assert any(kind == "critical" and "변환표" in title for kind, title, _text in dialogs.messages)


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
    assert read_map(config)["shares"] == [{"mac": "/Volumes/yc", "windows": [old, NAS]}]


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
