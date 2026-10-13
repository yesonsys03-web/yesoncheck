import os
from pathlib import Path

import numpy as np

from yesoncheck import image_io, web_info
from tests.conftest import write_test_video


def test_image_roundtrip_korean_path(tmp_path):
    path = str(tmp_path / "한글 폴더" / "구간_0001.jpg")
    os.makedirs(os.path.dirname(path))
    image = np.zeros((20, 30, 3), np.uint8)
    image[:, :, 2] = 200
    import cv2
    image_io.imwrite(path, image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    loaded = image_io.imread(path)
    assert loaded.shape == (20, 30, 3)


def test_imread_missing_raises(tmp_path):
    import pytest
    with pytest.raises((OSError, ValueError)):
        image_io.imread(str(tmp_path / "없음.jpg"))


def test_playlist_lists_uppercase_extension(qapp, dialogs, monkeypatch, tmp_path):
    import json
    from yesoncheck.main_window import VideoPlayer
    if os.name == "nt":
        import pytest
        pytest.skip("Windows 목록 시험은 test_work_paths_ui와 실행 시험(smoke)에서 확인")
    frames = tmp_path / "work" / "S1" / "job" / "scene-001" / "frames"
    write_test_video(str(frames / "A.MOV"))
    write_test_video(str(frames / "b.mov"))
    (frames / "._b.mov").write_bytes(b"")
    config = tmp_path / ".yesoncheck"
    config.mkdir()
    (config / "work_paths.json").write_text(json.dumps({"W": str(tmp_path / "work")}), encoding="utf-8")
    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", str(config))
    player = VideoPlayer()
    player.workComboBox.setCurrentText("W")
    player.seasonComboBox.setCurrentText("S1")
    player.jobComboBox.setCurrentText("job")
    names = sorted(player.sidebar.item(i).text() for i in range(player.sidebar.count()))
    assert names == ["A.MOV", "b.mov"]
    player.close()


def test_web_report_uses_file_uri(tmp_path):
    video = str(tmp_path / "한글 영상 #1.mov")
    html = web_info._generate_html([], "v", 24.0, 10, "titmouse", video)
    assert Path(video).as_uri() in html
