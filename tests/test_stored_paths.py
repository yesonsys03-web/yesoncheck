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
