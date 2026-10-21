import hashlib
import json
import os
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
    with pytest.raises(PathMapError, match="로드되지 않았습니다.*변환표 오류"):
        paths.to_native("/usadata2/x")


@pytest.fixture
def drives(monkeypatch):
    """GetDriveTypeW·WNetGetConnectionW를 흉내. types: 드라이브 → 종류, wnet: 드라이브 → (반환값, 원격 이름)."""
    fake = type("FakeDrives", (), {})()
    fake.types = {}
    fake.wnet = {}
    fake.wnet_calls = []

    def wnet(drive):
        fake.wnet_calls.append(drive)
        return fake.wnet[drive]

    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(paths, "_drive_type", lambda drive: fake.types[drive])
    monkeypatch.setattr(paths, "_wnet_get_connection", wnet)
    paths._cached_remote_name.cache_clear()
    yield fake
    paths._cached_remote_name.cache_clear()


def test_local_drive_does_not_ask_network(drives):
    """네트워크 공급자가 여럿인 PC에서는 로컬 디스크에도 WNet이 1203·1222 등을 돌려줌 → 로컬은 아예 묻지 않음."""
    drives.types["C:"] = paths._DRIVE_FIXED
    drives.wnet["C:"] = (1222, "")  # ERROR_NO_NETWORK
    assert paths.path_key("C:\\Clips\\A.mov") == "c:\\clips\\a.mov"
    assert paths.same_path("c:/clips/a.MOV", "C:\\Clips\\A.mov")
    with pytest.raises(PathMapError, match="네트워크 드라이브가 아닙니다"):
        paths.drive_to_unc("C:\\Clips")
    assert drives.wnet_calls == []


def test_network_drive_codes(drives):
    drives.types["Z:"] = paths._DRIVE_REMOTE
    drives.wnet["Z:"] = (0, "\\\\nas\\share")
    assert paths.drive_to_unc("Z:\\a") == "\\\\nas\\share\\a"
    drives.wnet["Z:"] = (1201, "\\\\nas\\share")  # 기억된 연결, 지금은 끊김
    assert paths._remote_name_of_drive("Z:") == "\\\\nas\\share"
    drives.wnet["Z:"] = (2250, "")
    assert paths._remote_name_of_drive("Z:") is None
    drives.wnet["Z:"] = (1203, "")  # 네트워크 드라이브인데 연결 정보를 못 읽음 → 오류로 알림
    with pytest.raises(PathMapError, match="WNetGetConnectionW 오류 1203"):
        paths._remote_name_of_drive("Z:")


def test_absent_drive_letter(drives):
    """지금 없는 드라이브 문자: 기억된(끊긴) 네트워크 연결이면 원격 이름, 아니면 None (오류 아님)."""
    drives.types["X:"] = paths._DRIVE_NO_ROOT_DIR
    drives.wnet["X:"] = (1201, "\\\\nas\\old")
    assert paths._remote_name_of_drive("X:") == "\\\\nas\\old"
    drives.wnet["X:"] = (1203, "")
    assert paths._remote_name_of_drive("X:") is None
    assert paths.path_key("X:\\A.mov") == "x:\\a.mov"


def test_load_accepts_notepad_bom(tmp_path):
    """메모장이 저장한 UTF-8 BOM 파일도 읽음."""
    (tmp_path / "path_map.json").write_text(json.dumps(MAP, ensure_ascii=False), encoding="utf-8-sig")
    assert PathMap.load(str(tmp_path)).mac_to_windows("/usadata2") == "\\\\203.0.113.3\\usadata2"


@pytest.mark.parametrize(
    "alias_a, alias_b",
    [
        ("\\\\nas\\공유", "\\\\nas\\공유"),
        ("\\\\NAS\\Share", "//nas/share"),  # 대소문자·슬래시만 다름
        ("\\\\nas\\" + unicodedata.normalize("NFC", "공유"), "\\\\nas\\" + unicodedata.normalize("NFD", "공유")),
    ],
)
def test_same_unc_alias_under_two_mac_entries_rejected(alias_a, alias_b):
    data = {"version": 1, "shares": [{"mac": "/a", "windows": [alias_a]}, {"mac": "/b", "windows": [alias_b]}]}
    with pytest.raises(PathMapError, match="변환표 형식 오류.*shares의 2번째 항목.*1번째 항목"):
        PathMap.from_dict(data, "bad-map")


def test_same_unc_alias_within_one_entry_allowed():
    data = {"version": 1, "shares": [{"mac": "/a", "windows": ["\\\\nas\\a", "\\\\NAS\\A"]}]}
    assert PathMap.from_dict(data, "ok").windows_to_mac("\\\\nas\\a\\x") == "/a/x"


def _alias_lists(path_map):
    return [["\\\\" + "\\".join(alias) for alias in uncs] for _mac, uncs in path_map.shares]


def test_with_preferred_aliases_puts_connected_share_first():
    """각 PC는 자기 드라이브가 연결된 주소를 먼저 엶 (서버·공유 이름이 같으면, 대소문자 무시·더 깊은 별칭 포함)."""
    data = {
        "version": 1,
        "shares": [
            {"mac": "/Volumes/colordata",
             "windows": ["\\\\203.0.113.19\\colordata", "\\\\NAS\\Data\\sub", "\\\\nas19\\colordata"]},
            {"mac": "/usadata2", "windows": ["\\\\203.0.113.3\\usadata2", "\\\\NAS3\\usadata2"]},
        ],
    }
    original = PathMap.from_dict(data, "test-map")
    before = _alias_lists(original)
    preferred = original.with_preferred_aliases(["\\\\nas\\DATA", "\\\\NAS19\\ColorData\\"])
    assert preferred is not original and preferred.source == "test-map"
    assert _alias_lists(preferred) == [
        ["\\\\NAS\\Data\\sub", "\\\\nas19\\colordata", "\\\\203.0.113.19\\colordata"],  # 맞는 것끼리는 원래 순서
        ["\\\\203.0.113.3\\usadata2", "\\\\NAS3\\usadata2"],  # 맞는 것이 없으면 그대로
    ]
    assert _alias_lists(original) == before  # 원래 표는 그대로
    assert preferred.mac_to_windows("/Volumes/colordata/FL") == "\\\\NAS\\Data\\sub\\FL"
    assert original.mac_to_windows("/Volumes/colordata/FL") == "\\\\203.0.113.19\\colordata\\FL"
    for entry in data["shares"]:
        for alias in entry["windows"]:  # Windows → Mac은 모든 별칭이 그대로
            assert preferred.windows_to_mac(alias + "\\x") == entry["mac"] + "/x"
    assert _alias_lists(original.with_preferred_aliases([])) == before


# ---- 이름의 정규화(NFC·NFD)만 다른 실제 경로 (find_unicode_variant) ----


class ByteExactFS:
    """이름을 바이트 그대로 비교하는 파일 시스템(NFS 공유) 대역 — 넣은 경로와 그 위 폴더들만 있음. 부른 차례는 calls."""

    def __init__(self, *paths_):
        self.entries = {os.sep}
        self.calls = []
        self.unreadable = set()
        for path in paths_:
            while path not in self.entries:
                self.entries.add(path)
                path = os.path.dirname(path)

    def lexists(self, path):
        self.calls.append(("lexists", path))
        return path in self.entries

    def listdir(self, folder):
        self.calls.append(("listdir", folder))
        if folder in self.unreadable:
            raise PermissionError(13, "Permission denied", folder)
        if folder not in self.entries:
            raise FileNotFoundError(2, "No such file or directory", folder)
        return sorted(os.path.basename(e) for e in self.entries if e != folder and os.path.dirname(e) == folder)


def _nfd(text):
    return unicodedata.normalize("NFD", text)


def _nfc(text):
    return unicodedata.normalize("NFC", text)


def test_find_unicode_variant_on_byte_exact_share():
    """Mac이 넘긴 경로(NFD — argv_emulation의 CFStringGetFileSystemRepresentation)가 NFS 공유에서 이름이 NFC로 저장된 폴더를
    지나면 그대로는 없음 → 이름마다 위 폴더 목록에서 NFC가 같은 것을 찾아 실제 경로로 (NFC·NFD 이름이 섞여 있어도)."""
    share = os.path.join(os.sep, "nas", "Mainnas")
    folder_nfc = _nfc("FL_901 컷 모음")  # Windows·NAS에서 만든 폴더 — NFC로 저장됨
    video_nfd = _nfd("장면 #3.mov")  # Mac에서 넣은 파일 — NFD로 저장됨
    real = os.path.join(share, folder_nfc, video_nfd)
    fs = ByteExactFS(real)
    handed = _nfd(real)  # Mac이 넘긴 경로: 모두 NFD
    assert handed != real and not fs.lexists(handed)
    assert paths.find_unicode_variant(handed, lexists=fs.lexists, listdir=fs.listdir) == real
    # 모두 NFC로 넘겨도 (open --args로 받은 경로 등)
    assert paths.find_unicode_variant(_nfc(real), lexists=fs.lexists, listdir=fs.listdir) == real


def test_find_unicode_variant_returns_none_when_nothing_to_find():
    share = os.path.join(os.sep, "nas", "Mainnas")
    real = os.path.join(share, _nfc("가나"), "a.mov")
    fs = ByteExactFS(real)
    # 있는 경로는 그대로 쓰면 됨 → None
    assert paths.find_unicode_variant(real, lexists=fs.lexists, listdir=fs.listdir) is None
    # 정규화로 달라질 글자가 없으면 디스크를 보지 않고 None
    fs.calls.clear()
    assert paths.find_unicode_variant(os.path.join(share, "gone", "a.mov"), lexists=fs.lexists,
                                      listdir=fs.listdir) is None
    assert fs.calls == []
    # 정말 없는 파일 (이름의 정규화를 바꿔도 없음)
    assert paths.find_unicode_variant(os.path.join(share, _nfd("가나"), "b.mov"), lexists=fs.lexists,
                                      listdir=fs.listdir) is None
    assert paths.find_unicode_variant(os.path.join(share, _nfd("다라"), "a.mov"), lexists=fs.lexists,
                                      listdir=fs.listdir) is None


def test_find_unicode_variant_ambiguous_or_unreadable_is_none(capsys):
    """NFC가 같은 이름이 둘 이상(NFC·NFD로 따로 저장된 두 폴더)이면 고르지 않음, 폴더를 읽지 못하면 None — 둘 다 기록에 까닭."""
    share = os.path.join(os.sep, "nas", "Mainnas")
    both = ByteExactFS(os.path.join(share, _nfc("가각"), "a.mov"), os.path.join(share, _nfd("가각"), "a.mov"))
    mixed = "가" + _nfd("각")  # 앞 글자는 NFC, 뒤 글자는 NFD — 어느 쪽과도 바이트가 다름
    assert paths.find_unicode_variant(os.path.join(share, mixed, "a.mov"), lexists=both.lexists,
                                      listdir=both.listdir) is None
    assert "2개" in capsys.readouterr().out

    fs = ByteExactFS(os.path.join(share, _nfc("가나"), "a.mov"))
    fs.unreadable.add(share)
    assert paths.find_unicode_variant(os.path.join(share, _nfd("가나"), "a.mov"), lexists=fs.lexists,
                                      listdir=fs.listdir) is None
    out = capsys.readouterr().out
    assert share in out and "PermissionError" in out
