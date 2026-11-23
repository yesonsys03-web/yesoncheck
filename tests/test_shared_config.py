import json
import os

import pytest

from yesoncheck import paths, shared_config
from yesoncheck.shared_config import SharedConfigError


def test_mac_config_dir_is_fixed(monkeypatch):
    monkeypatch.delenv("YESONCHECK_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    assert shared_config.configured_config_dir() == "/USA_DB/test_jn/.yesoncheck"


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", str(tmp_path))
    assert shared_config.configured_config_dir() == str(tmp_path)


def test_windows_local_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("YESONCHECK_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert shared_config.configured_config_dir() is None
    shared_config.save_local_settings({"config_dir": "\\\\nas\\USA_DB\\test_jn\\.yesoncheck"})
    saved = json.loads((tmp_path / "YesonCheck" / "settings.json").read_text(encoding="utf-8"))
    assert saved == {"config_dir": "\\\\nas\\USA_DB\\test_jn\\.yesoncheck"}
    assert shared_config.configured_config_dir() == "\\\\nas\\USA_DB\\test_jn\\.yesoncheck"


def test_windows_local_settings_broken(monkeypatch, tmp_path):
    monkeypatch.delenv("YESONCHECK_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "YesonCheck").mkdir()
    (tmp_path / "YesonCheck" / "settings.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(SharedConfigError, match="PC별 설정 파일을 읽지 못했습니다"):
        shared_config.configured_config_dir()


def test_validate_config_dir(tmp_path):
    with pytest.raises(SharedConfigError, match="열 수 없습니다"):
        shared_config.validate_config_dir(str(tmp_path / "none"))
    with pytest.raises(SharedConfigError, match="work_paths.json이 없습니다"):
        shared_config.validate_config_dir(str(tmp_path))
    (tmp_path / "work_paths.json").write_text("{}", encoding="utf-8")
    shared_config.validate_config_dir(str(tmp_path))
    assert shared_config.is_valid_config_dir(str(tmp_path))
    assert not shared_config.is_valid_config_dir(None)


def test_read_work_paths(tmp_path):
    f = tmp_path / "work_paths.json"
    with pytest.raises(SharedConfigError, match="파일이 없습니다"):
        shared_config.read_work_paths(str(f))
    f.write_text("{broken", encoding="utf-8")
    with pytest.raises(SharedConfigError, match="읽지 못했습니다"):
        shared_config.read_work_paths(str(f))
    f.write_text('["a"]', encoding="utf-8")
    with pytest.raises(SharedConfigError, match="형식 오류"):
        shared_config.read_work_paths(str(f))
    f.write_text(json.dumps({"FL": "/Volumes/colordata/FLORIDA", "HH": "/a/시즌"}, ensure_ascii=False), encoding="utf-8")
    assert shared_config.read_work_paths(str(f)) == {"FL": "/Volumes/colordata/FLORIDA", "HH": "/a/시즌"}


def test_write_work_paths_does_not_create_folders(tmp_path):
    with pytest.raises(OSError):
        shared_config.write_work_paths(str(tmp_path / "missing" / "work_paths.json"), {"A": "/a"})
    assert not (tmp_path / "missing").exists()
    target = tmp_path / "work_paths.json"
    shared_config.write_work_paths(str(target), {"HH": "/a/시즌"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"HH": "/a/시즌"}
    assert "시즌" in target.read_text(encoding="utf-8")  # ensure_ascii=False 유지
