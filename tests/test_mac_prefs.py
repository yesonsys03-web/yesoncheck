"""Mac 설정 파일 (yesoncheck/mac_prefs.py): ~/Library/Application Support/YesonCheck/prefs.json 읽기·한 키 고치기.

default_app(동영상 기본 앱 질문의 답)과 재생 디코더 설정이 함께 쓰는 모듈 — 읽기·쓰기 규칙(없으면 빈 값, 깨진 파일은 덮지 않음, 잠금 안에서
다시 읽고 그 키만 고침)은 tests/test_default_app.py가 default_app 쪽에서 이미 시험하므로 여기서는 모듈 자체의 계약과 default_app이 이 모듈을
쓰는지만 본다.
"""

import json
import os

import pytest

from yesoncheck import default_app, mac_prefs
from yesoncheck.user_files import UserFileError


@pytest.fixture
def home(monkeypatch, tmp_path):
    """prefs.json은 시험마다 새 HOME 아래에 (사용자의 ~/Library/Application Support를 건드리지 않음). Windows의 expanduser는
    USERPROFILE을 봄 — 둘 다. (tests/test_default_app.py의 home과 같은 모양)"""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    return path


def write_prefs_file(text):
    path = mac_prefs.prefs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def prefs_on_disk():
    with open(mac_prefs.prefs_path(), encoding="utf-8") as fh:
        return json.load(fh)


def test_prefs_path_is_under_the_current_home(home):
    assert mac_prefs.prefs_path() == os.path.join(str(home), "Library", "Application Support", "YesonCheck", "prefs.json")


def test_read_prefs_missing_is_empty(home):
    assert mac_prefs.read_prefs() == {}
    assert not os.path.exists(mac_prefs.prefs_path())  # 읽기만으로 파일을 만들지 않음


def test_update_pref_creates_the_file_with_that_key(home):
    mac_prefs.update_pref("playback_decoder", "ffmpeg")
    assert prefs_on_disk() == {"playback_decoder": "ffmpeg"}
    assert mac_prefs.read_prefs() == {"playback_decoder": "ffmpeg"}


def test_update_pref_keeps_other_keys(home):
    write_prefs_file(json.dumps({"asked_default_video_app": True, "future_key": [1, 2]}))
    mac_prefs.update_pref("playback_decoder", "ffmpeg")
    assert prefs_on_disk() == {"asked_default_video_app": True, "future_key": [1, 2], "playback_decoder": "ffmpeg"}
    mac_prefs.update_pref("playback_decoder", "videotoolbox")  # 같은 키는 덮어씀, 나머지는 그대로
    assert prefs_on_disk() == {"asked_default_video_app": True, "future_key": [1, 2], "playback_decoder": "videotoolbox"}


@pytest.mark.parametrize("broken", ["not json", "{not json", "[1, 2]"])
def test_update_pref_refuses_broken_file(home, broken):
    """깨진 파일·JSON 객체가 아닌 파일은 빈 값으로 치지 않고 UserFileError — 파일은 그대로 (설정을 덮어 지우지 않음)."""
    path = write_prefs_file(broken)
    with pytest.raises(UserFileError, match="prefs.json"):
        mac_prefs.update_pref("playback_decoder", "ffmpeg")
    with pytest.raises(UserFileError, match="prefs.json"):
        mac_prefs.read_prefs()
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == broken


def test_default_app_uses_mac_prefs(home):
    """default_app의 기록은 이 모듈의 한 함수로 — record_asked가 같은 파일에 asked 키를 쓰고, default_app의 옛 이름(prefs_path·read_prefs)은
    이 모듈의 것 그대로."""
    write_prefs_file(json.dumps({"playback_decoder": "ffmpeg"}))
    default_app.record_asked()
    assert mac_prefs.read_prefs()["asked_default_video_app"] is True
    assert mac_prefs.read_prefs()["playback_decoder"] == "ffmpeg"  # 다른 키는 그대로
    assert default_app.ASKED_KEY == "asked_default_video_app"
    assert default_app.prefs_path is mac_prefs.prefs_path
    assert default_app.read_prefs is mac_prefs.read_prefs
