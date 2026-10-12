import hashlib
import json
import unicodedata

import pytest

from yesoncheck import paths
from yesoncheck.paths import PathMap, PathMapError

MAP = {
    "version": 1,
    "shares": [
        {"mac": "/Volumes/colordata", "windows": ["\\\\203.0.113.19\\colordata", "\\\\NAS19\\colordata"]},
        {"mac": "/usadata2", "windows": ["\\\\203.0.113.3\\usadata2"]},
        {"mac": "/usadata2/Disney", "windows": ["\\\\203.0.113.3\\disney"]},
        {"mac": "/Users/studio01/Desktop/usadata4", "windows": ["\\\\203.0.113.14\\usadata4"]},
    ],
}


@pytest.fixture
def path_map():
    return PathMap.from_dict(MAP, "test-map")


@pytest.fixture
def windows(monkeypatch, path_map):
    """Windows 동작을 흉내: Z:=colordata, Y:=usadata2, C:=로컬 디스크."""
    remotes = {"Z:": "\\\\203.0.113.19\\colordata", "Y:": "\\\\203.0.113.3\\usadata2"}
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda drive: remotes.get(drive))
    paths._cached_remote_name.cache_clear()
    paths.activate(path_map)
    yield remotes
    paths.activate(None)
    paths._cached_remote_name.cache_clear()


def test_mac_to_windows_uses_first_alias_and_backslashes(path_map):
    assert path_map.mac_to_windows("/Volumes/colordata/FLORIDA/FL902") == "\\\\203.0.113.19\\colordata\\FLORIDA\\FL902"


def test_mac_prefix_matches_whole_folders_only(path_map):
    with pytest.raises(PathMapError, match="변환표에 없는 경로"):
        path_map.mac_to_windows("/usadata22/x")


def test_longest_mac_prefix_wins(path_map):
    assert path_map.mac_to_windows("/usadata2/Disney/KOTH") == "\\\\203.0.113.3\\disney\\KOTH"
    assert path_map.mac_to_windows("/usadata2/Titmouse/FLORIDA") == "\\\\203.0.113.3\\usadata2\\Titmouse\\FLORIDA"


def test_share_root_itself(path_map):
    assert path_map.mac_to_windows("/Volumes/colordata") == "\\\\203.0.113.19\\colordata"


def test_trailing_slash_and_firmlink(path_map):
    expected = "\\\\203.0.113.14\\usadata4\\BentoBox_Data\\BB_New"
    assert path_map.mac_to_windows("/Users/studio01/Desktop/usadata4/BentoBox_Data/BB_New/") == expected
    assert path_map.mac_to_windows("/System/Volumes/Data/usadata2/KOTH") == "\\\\203.0.113.3\\usadata2\\KOTH"


def test_windows_to_mac_any_alias_case_and_slashes(path_map):
    assert path_map.windows_to_mac("\\\\nas19\\COLORDATA\\FLORIDA") == "/Volumes/colordata/FLORIDA"
    assert path_map.windows_to_mac("//203.0.113.19/colordata/FLORIDA/") == "/Volumes/colordata/FLORIDA"


def test_windows_longest_alias_wins(path_map):
    assert path_map.windows_to_mac("\\\\203.0.113.3\\disney\\KOTH") == "/usadata2/Disney/KOTH"


def test_windows_unknown_share(path_map):
    with pytest.raises(PathMapError, match="변환표에 없는 공유 폴더"):
        path_map.windows_to_mac("\\\\203.0.113.99\\other\\x")


def test_windows_path_normalization_with_dotdot(path_map):
    # .. 세그먼트 정규화 확인
    assert path_map.windows_to_mac("\\\\203.0.113.19\\colordata\\a\\..\\FLORIDA") == "/Volumes/colordata/FLORIDA"


def test_hangul_normalization(path_map):
    nfd = unicodedata.normalize("NFD", "HH99_시즌_자료")
    out = path_map.mac_to_windows(f"/Volumes/colordata/Hazbin_Hotel/{nfd}")
    assert out == "\\\\203.0.113.19\\colordata\\Hazbin_Hotel\\HH99_시즌_자료"
    assert path_map.windows_to_mac(f"\\\\203.0.113.19\\colordata\\{nfd}") == "/Volumes/colordata/HH99_시즌_자료"


@pytest.mark.parametrize(
    "data, message",
    [
        ([], "최상위가 객체"),
        ({"version": 2, "shares": []}, '"version"이 1'),
        ({"version": 1, "shares": []}, '"shares" 목록'),
        ({"version": 1, "shares": [{"mac": "/a/", "windows": ["\\\\s\\a"]}]}, "끝에 /가 없는"),
        ({"version": 1, "shares": [{"mac": "a", "windows": ["\\\\s\\a"]}]}, "끝에 /가 없는"),
        ({"version": 1, "shares": [{"mac": "/a", "windows": "\\\\s\\a"}]}, "UNC 경로 목록"),
        ({"version": 1, "shares": [{"mac": "/a", "windows": ["Z:\\a"]}]}, "UNC 경로"),
        ({"version": 1, "shares": [{"mac": "/a", "windows": ["\\\\s"]}]}, "서버와 공유 이름"),
        (
            {"version": 1, "shares": [{"mac": "/a", "windows": ["\\\\s\\a"]}, {"mac": "/a", "windows": ["\\\\s\\b"]}]},
            "겹칩니다",
        ),
    ],
)
def test_invalid_map(data, message):
    with pytest.raises(PathMapError, match=message):
        PathMap.from_dict(data, "bad-map")


def test_load_missing_and_broken(tmp_path):
    with pytest.raises(PathMapError, match="변환표 파일이 없습니다"):
        PathMap.load(str(tmp_path))
    (tmp_path / "path_map.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(PathMapError, match="변환표를 읽지 못했습니다"):
        PathMap.load(str(tmp_path))
    (tmp_path / "path_map.json").write_text(json.dumps(MAP), encoding="utf-8")
    assert PathMap.load(str(tmp_path)).mac_to_windows("/usadata2") == "\\\\203.0.113.3\\usadata2"


def test_drive_to_unc():
    remotes = {"Z:": "\\\\203.0.113.19\\colordata"}
    assert paths.drive_to_unc("z:/FLORIDA/FL902", remotes.get) == "\\\\203.0.113.19\\colordata\\FLORIDA\\FL902"
    assert paths.drive_to_unc("Z:\\", remotes.get) == "\\\\203.0.113.19\\colordata\\"
    assert paths.drive_to_unc("//nas/share/a", remotes.get) == "\\\\nas\\share\\a"
    with pytest.raises(PathMapError, match="네트워크 드라이브가 아닙니다"):
        paths.drive_to_unc("C:\\work", remotes.get)
    with pytest.raises(PathMapError, match="드라이브 문자나 UNC"):
        paths.drive_to_unc("relative\\x", remotes.get)


def test_mac_mode_is_identity(monkeypatch):
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    assert paths.to_native("/usadata2/x/") == "/usadata2/x/"
    assert paths.to_canonical("/System/Volumes/Data/usadata2/x") == "/usadata2/x"
    assert paths.to_storage("/a/b.mov") == "/a/b.mov"
    assert paths.from_storage("/a/b.mov") == "/a/b.mov"
    assert paths.path_key("/a/B.mov") == "/a/B.mov"
    assert paths.normalize_native("/a//b") == "/a//b"
    # 기존 썸네일 캐시 키와 같아야 함 (Mac 캐시 유지)
    assert paths.thumbnail_key("/a/한글.mov") == hashlib.md5("/a/한글.mov".encode("utf-8")).hexdigest()


def test_windows_conversions(windows):
    assert paths.to_native("/Volumes/colordata/FLORIDA") == "\\\\203.0.113.19\\colordata\\FLORIDA"
    assert paths.to_canonical("Z:/FLORIDA/시즌") == "/Volumes/colordata/FLORIDA/시즌"
    assert paths.to_canonical("\\\\nas19\\colordata\\FLORIDA") == "/Volumes/colordata/FLORIDA"
    with pytest.raises(PathMapError, match="네트워크 드라이브가 아닙니다"):
        paths.to_canonical("C:/local/work")


def test_storage_round_trip(windows):
    assert paths.to_storage("Z:\\FLORIDA\\a.mov") == "/Volumes/colordata/FLORIDA/a.mov"
    # 로컬 디스크 영상은 변환표 밖 → 원래 경로를 그대로 적음 (스펙 2-4)
    assert paths.to_storage("C:\\clips\\a.mov") == "C:\\clips\\a.mov"
    assert paths.from_storage("/Volumes/colordata/FLORIDA/a.mov") == "\\\\203.0.113.19\\colordata\\FLORIDA\\a.mov"
    assert paths.from_storage("C:\\clips\\a.mov") == "C:\\clips\\a.mov"
    with pytest.raises(PathMapError):
        paths.from_storage("/Volumes/unknown/a.mov")


def test_path_key_drive_letters_differ(windows):
    unc = "\\\\203.0.113.19\\colordata\\FLORIDA\\A.mov"
    assert paths.path_key("Z:/florida/a.MOV") == paths.path_key(unc)
    assert paths.thumbnail_key("Z:\\FLORIDA\\A.mov") == paths.thumbnail_key("//203.0.113.19/colordata/FLORIDA/A.mov")
    assert paths.same_path("Z:\\FLORIDA\\A.mov", unc)
    assert paths.contains_path(["C:\\x", unc], "z:/FLORIDA/a.mov")
    assert not paths.same_path("Z:\\FLORIDA\\A.mov", "Y:\\FLORIDA\\A.mov")


def test_active_map_required(monkeypatch):
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    paths.activate(None)
    with pytest.raises(PathMapError, match="로드되지 않았습니다"):
        paths.to_native("/usadata2/x")
