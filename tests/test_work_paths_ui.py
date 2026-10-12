import json
import os

import pytest
from PyQt5.QtCore import Qt

from yesoncheck import paths
from yesoncheck.paths import PathMap
from tests.conftest import write_test_video


def make_config(base, work_paths, path_map=None, raw=None):
    config = os.path.join(base, ".yesoncheck")
    os.makedirs(config, exist_ok=True)
    with open(os.path.join(config, "work_paths.json"), "w", encoding="utf-8") as fh:
        fh.write(raw if raw is not None else json.dumps(work_paths, ensure_ascii=False))
    if path_map is not None:
        with open(os.path.join(config, "path_map.json"), "w", encoding="utf-8") as fh:
            json.dump(path_map, fh)
    return config


@pytest.fixture
def new_player(qapp, monkeypatch):
    created = []

    def make(config_dir):
        monkeypatch.setenv("YESONCHECK_CONFIG_DIR", config_dir)
        from yesoncheck.main_window import VideoPlayer

        player = VideoPlayer()
        created.append(player)
        return player

    yield make
    for player in created:
        player.close()
    paths.activate(None)


def combo_items(combo):
    return [combo.itemText(i) for i in range(combo.count())]


def test_work_list_and_playlist(new_player, dialogs, work_area):
    video = write_test_video(os.path.join(work_area.local, "S1", "job_01", "scene-001", "frames", "a.mov"))
    config = make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map)
    player = new_player(config)
    assert player.shared_config_problem is None
    assert combo_items(player.workComboBox) == ["작품선택", "SMOKE"]
    player.workComboBox.setCurrentText("SMOKE")
    player.seasonComboBox.setCurrentText("S1")
    player.jobComboBox.setCurrentText("job_01")
    assert player.sidebar.count() == 1
    # Mac: 만든 파일 경로 그대로. Windows: 시험 공유의 UNC 경로 (변환표로 바뀐 작품 경로 아래)
    expected = os.path.join(paths.to_native(work_area.stored), "S1", "job_01", "scene-001", "frames", "a.mov")
    assert os.path.exists(video)
    assert paths.same_path(player.sidebar.item(0).data(Qt.UserRole), expected)
    assert dialogs.errors() == []


def test_corrupt_work_paths_not_overwritten(new_player, dialogs, tmp_path):
    config = make_config(str(tmp_path), None, raw="{broken")
    player = new_player(config)
    assert "읽지 못했습니다" in player.shared_config_problem
    assert "Traceback" in player.shared_config_problem
    assert combo_items(player.workComboBox) == ["작품선택"]
    with open(os.path.join(config, "work_paths.json"), encoding="utf-8") as fh:
        assert fh.read() == "{broken"
    player.resolve_shared_config_problem()
    assert any(kind == "critical" and "work_paths.json" in text for kind, _t, text in dialogs.messages)


def test_missing_work_paths_file_not_created(new_player, dialogs, tmp_path):
    config = tmp_path / ".yesoncheck"
    config.mkdir()
    player = new_player(str(config))
    assert "파일이 없습니다" in player.shared_config_problem
    player.resolve_shared_config_problem()
    assert not (config / "work_paths.json").exists()
    assert dialogs.errors()


def test_manage_blocked_when_problem(new_player, dialogs, tmp_path):
    config = make_config(str(tmp_path), None, raw="{broken")
    player = new_player(config)
    player.manage_work_paths()  # 입력 창이 열리면 dialogs fixture가 실패시킴
    assert any(kind == "warning" and "관리할 수 없습니다" in text for kind, _t, text in dialogs.messages)


def test_unmapped_work_path_reports_error(new_player, dialogs, tmp_path, monkeypatch):
    config = make_config(str(tmp_path), {"FL": "/Volumes/colordata/FLORIDA"})
    player = new_player(config)
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    paths.activate(PathMap.from_dict({"version": 1, "shares": [{"mac": "/usadata2", "windows": ["\\\\nas\\usadata2"]}]}, "map"))
    assert player.get_work_path("FL") == ""
    assert any("변환표에 없는 경로" in text for _k, _t, text in dialogs.errors())


def test_save_rejects_local_folder(new_player, dialogs, tmp_path, monkeypatch):
    config = make_config(str(tmp_path), {})
    player = new_player(config)
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda drive: None)
    paths.activate(PathMap.from_dict({"version": 1, "shares": [{"mac": "/usadata2", "windows": ["\\\\nas\\usadata2"]}]}, "map"))
    assert player._stored_work_path_or_warn("C:/work", None) is None
    assert any("네트워크 드라이브가 아닙니다" in text for _k, _t, text in dialogs.errors())


def test_save_converts_drive_path(new_player, dialogs, tmp_path, monkeypatch):
    config = make_config(str(tmp_path), {})
    player = new_player(config)
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda drive: {"Z:": "\\\\nas\\colordata"}.get(drive))
    paths.activate(PathMap.from_dict({"version": 1, "shares": [{"mac": "/Volumes/colordata", "windows": ["\\\\nas\\colordata"]}]}, "map"))
    assert player._stored_work_path_or_warn("Z:/FLORIDA/시즌", None) == "/Volumes/colordata/FLORIDA/시즌"


def test_choose_shared_config_dir_handles_save_failure(new_player, dialogs, tmp_path, monkeypatch):
    config = make_config(str(tmp_path), {})
    player = new_player(config)
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(paths, "drive_to_unc", lambda p, resolver=None: p)

    # APPDATA\YesonCheck\settings.json이 깨져 있음 (시작할 때 이 흐름으로 들어오게 되는 바로 그 상황)
    appdata = tmp_path / "appdata"
    (appdata / "YesonCheck").mkdir(parents=True)
    (appdata / "YesonCheck" / "settings.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    # 고를 폴더는 공유 설정 폴더로서는 유효함 (work_paths.json 존재)
    valid_config = tmp_path / "valid_config"
    valid_config.mkdir()
    (valid_config / "work_paths.json").write_text("{}", encoding="utf-8")
    dialogs.folders.append(str(valid_config))

    result = player.choose_shared_config_dir()

    assert result is False
    assert any(kind == "critical" and "PC별 설정" in text for kind, _t, text in dialogs.messages)
