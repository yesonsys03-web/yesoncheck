"""썸네일 파일: Mac·Windows가 NAS의 같은 썸네일을 쓰고, 바뀐 영상만 새로 만들고, 저장 실패는 창으로 알림.

Windows 사용자 보고 (2026-10-15): 썸네일을 만든 작업으로 돌아와 썸네일 모드를 켜면 모두 처음부터 다시 만듦
(Windows는 Mac이 만든 썸네일 이름을 몰랐고, Mac이 만든 폴더에 쓰지 못한 저장 실패는 로그에만 남았음).
"""

import hashlib

import pytest

from yesoncheck import paths
from yesoncheck.paths import PathMap

# 실제 NAS의 영상: Mac에서 만든 썸네일 파일이 <job>/.yesoncheck_thumb/5588e0d6ba56606ffae36e54b8d5283f.jpg로 있음
MAC_VIDEO = "/usadata2/Titmouse/FLORIDA/FL_Season01/FL_902/scene-A001/frames/FL_902_A001_TK1.mov"
MAC_THUMB_KEY = "5588e0d6ba56606ffae36e54b8d5283f"
UNC_VIDEO = "\\\\Mainnas\\usadata2\\Titmouse\\FLORIDA\\FL_Season01\\FL_902\\scene-A001\\frames\\FL_902_A001_TK1.mov"
NAS_MAP = {"version": 1, "shares": [{"mac": "/usadata2", "windows": ["\\\\Mainnas\\usadata2"]}]}


def md5(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


@pytest.fixture
def windows(monkeypatch):
    """Windows 동작을 흉내: Y:=\\\\Mainnas\\usadata2, C:=로컬 디스크. 변환표는 시험마다 activate."""
    remotes = {"Y:": "\\\\Mainnas\\usadata2"}
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda drive: remotes.get(drive))
    paths._cached_remote_name.cache_clear()
    yield remotes
    paths.activate(None)
    paths._cached_remote_name.cache_clear()


def test_mac_key_unchanged(monkeypatch):
    """Mac은 기존 이름 그대로 (NAS에 이미 있는 Mac 썸네일이 계속 쓰여야 함)."""
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    assert paths.thumbnail_key(MAC_VIDEO) == MAC_THUMB_KEY


def test_windows_unc_uses_mac_thumbnail_name(windows):
    paths.activate(PathMap.from_dict(NAS_MAP, "t"))
    assert paths.thumbnail_key(UNC_VIDEO) == MAC_THUMB_KEY
    # 서버·공유 이름의 대소문자와 구분자는 상관없음 (그 아래는 NAS의 이름 그대로)
    assert paths.thumbnail_key(UNC_VIDEO.replace("\\\\Mainnas\\usadata2", "//MAINNAS/USADATA2")) == MAC_THUMB_KEY


def test_windows_drive_letter_uses_mac_thumbnail_name(windows):
    paths.activate(PathMap.from_dict(NAS_MAP, "t"))
    rest = "\\Titmouse\\FLORIDA\\FL_Season01\\FL_902\\scene-A001\\frames\\FL_902_A001_TK1.mov"
    assert paths.thumbnail_key("Y:" + rest) == MAC_THUMB_KEY
    assert paths.thumbnail_key("y:" + rest.replace("\\", "/")) == MAC_THUMB_KEY


def test_windows_outside_path_map_keeps_old_key(windows):
    """변환표 밖 공유·로컬 디스크는 예전 이름 (path_key의 md5)."""
    paths.activate(PathMap.from_dict(NAS_MAP, "t"))
    other = "\\\\other\\share\\A.mov"
    local = "C:\\clips\\A.mov"
    assert paths.thumbnail_key(other) == md5(paths.path_key(other)) == md5("\\\\other\\share\\a.mov")
    assert paths.thumbnail_key(local) == md5(paths.path_key(local)) == md5("c:\\clips\\a.mov")


def test_windows_without_path_map_keeps_old_key(windows):
    paths.activate(None)
    assert paths.thumbnail_key(UNC_VIDEO) == md5(paths.path_key(UNC_VIDEO))
    assert paths.thumbnail_key("Y:\\x.mov") == paths.thumbnail_key("\\\\mainnas\\USADATA2\\X.mov")

