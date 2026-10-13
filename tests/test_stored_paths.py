import json

import pytest

from yesoncheck import paths
from yesoncheck.frame_annotations import FrameAnnotationStore
from yesoncheck.paths import PathMap


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda d: {"Z:": "\\\\nas\\colordata"}.get(d))
    paths._cached_remote_name.cache_clear()
    paths.activate(PathMap.from_dict({"version": 1, "shares": [{"mac": "/Volumes/colordata", "windows": ["\\\\nas\\colordata"]}]}, "map"))
    yield
    paths.activate(None)
    paths._cached_remote_name.cache_clear()


def test_annotation_load_keeps_opened_path(tmp_path):
    sidecar = tmp_path / "a_annotations.json"
    sidecar.write_text(json.dumps({"video_path": "/somewhere/else.mov", "fps": 24, "annotations": {}}), encoding="utf-8")
    store = FrameAnnotationStore()
    store.video_path = str(tmp_path / "a.mov")
    assert store.load(str(sidecar))
    assert store.video_path == str(tmp_path / "a.mov")
    assert store.fps == 24.0


def test_annotation_saves_mac_path_on_windows(windows):
    store = FrameAnnotationStore()
    store.video_path = "Z:\\FLORIDA\\a.mov"
    assert store.to_dict()["video_path"] == "/Volumes/colordata/FLORIDA/a.mov"


def test_annotation_mac_unchanged(monkeypatch):
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    store = FrameAnnotationStore()
    store.video_path = "/Volumes/colordata/FLORIDA/a.mov"
    assert store.to_dict()["video_path"] == "/Volumes/colordata/FLORIDA/a.mov"


def _player_with_ocr_result(qapp, monkeypatch, tmp_path, video_path):
    from PyQt5.QtWidgets import QFileDialog

    config = tmp_path / ".yesoncheck"
    config.mkdir()
    (config / "work_paths.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", str(config))
    from yesoncheck.main_window import VideoPlayer

    player = VideoPlayer()
    result = tmp_path / "ocr_result.json"
    result.write_text(json.dumps({"video_path": video_path, "segments": []}), encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(result), "JSON Files (*.json)"))
    return player


def test_ocr_result_missing_video_shows_stored_and_converted_path(qapp, dialogs, monkeypatch, tmp_path):
    """스펙 2-4: 변환한 경로에 영상이 없으면 파일에 적힌 원래 경로도 함께 보여 줌."""
    player = _player_with_ocr_result(qapp, monkeypatch, tmp_path, "/Volumes/colordata/FLORIDA/없음.mov")
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    # 없는 공유: localhost라 Windows CI에서도 서버 이름 찾기로 오래 기다리지 않음
    unc = "\\\\localhost\\yc_no_such_share"
    paths.activate(PathMap.from_dict({"version": 1, "shares": [{"mac": "/Volumes/colordata", "windows": [unc]}]}, "map"))
    try:
        player.load_ocr_result()
    finally:
        paths.activate(None)
        player.close()
    warnings = [m for m in dialogs.messages if m[1] == "동영상 파일 없음"]
    assert len(warnings) == 1, dialogs.messages
    text = warnings[0][2]
    assert "저장된 경로: /Volumes/colordata/FLORIDA/없음.mov" in text
    assert f"이 PC 경로: {unc}\\FLORIDA\\없음.mov" in text


def test_ocr_result_missing_video_mac_message_unchanged(qapp, dialogs, monkeypatch, tmp_path):
    missing = str(tmp_path / "없음.mov")
    player = _player_with_ocr_result(qapp, monkeypatch, tmp_path, missing)
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    try:
        player.load_ocr_result()
    finally:
        player.close()
    warnings = [m for m in dialogs.messages if m[1] == "동영상 파일 없음"]
    assert [w[2] for w in warnings] == [
        f"저장된 동영상 파일을 찾을 수 없습니다:\n{missing}\n\n수동으로 동영상을 로드한 후 다시 시도하세요."
    ]
