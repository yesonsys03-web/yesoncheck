"""(Mac) 이 Mac에서 공유가 붙은 곳(mac_mounts): 자동 연결(autofs) 설정·/etc/fstab 읽기, 경로 변환, 공유 설정 폴더,
작품 경로 관리, OCR 결과·주석 저장, 목록 다시 읽기(check_gone).

시험 자료 tests/mac_mounts_data:
- mac_b/: 공유를 auto_master의 간접 맵 auto_nfs로 /System/Volumes/Data/mnt 아래에 붙인 스튜디오 Mac(mac_b)의
  /etc/auto_master·auto_nfs·auto_nfs_back(모두 주석, auto_master가 가리키지 않음). 보고받은 내용 그대로이고, 보고에서
  "..."로 줄인 usadata5~usadata7·usadata4의 옵션과 usadata7의 서버는 같은 줄들의 모양을 따라 채움. mac_b에는 fstab이 없음.
- reference/: 기준 Mac(공유를 fstab과 /- -static으로 제자리에 붙인 Mac)의 /etc/auto_master·/etc/fstab.
- path_map.json: 공유 설정 폴더의 변환표 (2026-10-16 내용) — "mac" 항목이 공유 설정의 앞부분.

tmp 폴더를 root로 같은 모양을 만들어 시험한다. 실제 /etc는 읽기만 하는 시험 하나(test_real_config_changes_nothing_here)뿐.
"""

import errno
import hashlib
import json
import os
import shutil
import sys
from types import SimpleNamespace

import pytest

from yesoncheck import mac_mounts, paths, shared_config, video_list
from yesoncheck.paths import PathMap, PathMapError

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Mac 공유 위치 (POSIX 경로·심볼릭 링크) — Windows는 path_map.json")

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mac_mounts_data")
MAC_B_KEYS = ("USA_DB", "usadata2", "usadata3", "usadata1", "usadata5", "usadata6", "usadata7", "usadata4", "bgfinal")
with open(os.path.join(DATA, "path_map.json"), encoding="utf-8") as _fh:
    PATH_MAP = json.load(_fh)
PATH_MAP_ROOTS = [entry["mac"] for entry in PATH_MAP["shares"]]
# 공유 설정 work_paths.json (2026-10-16 내용)
WORK_PATHS = {
    "BB": "/usadata3/Bento_Project",
    "KOTH": "/usadata2/Disney/KOTH",
    "Big_Mouth": "/usadata2/Titmouse/Big_Mouth",
    "TGN": "/usadata3/Bento_Project2/Great_North",
    "MatingSeason": "/usadata2/Titmouse/MatingSeason",
    "The_Johnsons": "/usadata2/Titmouse/The_Johnsons",
    "BB_Animatic": "/Users/studio01/Desktop/usadata4/BentoBox_Data/BentoBox_data/BB_New/",
    "KOTH_Animatic": "/Volumes/colordata/KOTH",
    "BM_Animatic": "/Volumes/bgfinal/colordata/BIG_MOUTH",
    "TGN_Animatic": "/Users/studio01/Desktop/usadata4/BentoBox_Data/BentoBox_data/",
    "MS_Animatic": "/Volumes/bgfinal/colordata/MatingSeason",
    "TJS_Animatic": "/Volumes/bgfinal/colordata/The_Johnsons",
    "FL": "/usadata2/Titmouse/FLORIDA",
    "FL_Animatic": "/Volumes/colordata/FLORIDA",
    "Hazbin": "/usadata2/Princess_Bento/Hazbin_Hotel",
    "Hazbin_animatic": "/Volumes/colordata/Hazbin_Hotel/HH99_시즌_자료",
}
FL_JOB = "/usadata2/Titmouse/FLORIDA/FL_Season01/FL_904"
FL_VIDEO = FL_JOB + "/scene-A001/frames/FL_904_A001_TK1.mov"
USADATA4 = "/Users/studio01/Desktop/usadata4"
NO_SUCH_CONFIG = "/yc_no_such_share/test_jn/.yesoncheck"  # 이 Mac에도 없는 앞부분 (NAS를 읽지 않게)


def md5(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb"):
        pass
    return path


def write(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "w", encoding="utf-8") as fh:
        fh.write(text)


def enoent(path):
    return FileNotFoundError(errno.ENOENT, "No such file or directory", path)


def copy_data(kind, names, etc):
    os.makedirs(etc, exist_ok=True)
    for name in names:
        shutil.copy(os.path.join(DATA, kind, name), os.path.join(etc, name))


def write_config(config, work_paths=WORK_PATHS, path_map=True):
    os.makedirs(config, exist_ok=True)
    with open(os.path.join(config, "work_paths.json"), "w", encoding="utf-8") as fh:
        json.dump(work_paths, fh, ensure_ascii=False)
    if path_map:
        shutil.copy(os.path.join(DATA, "path_map.json"), os.path.join(config, "path_map.json"))


def make_mac_b(root, desktop_user="studio01"):
    """mac_b 모양: auto_nfs가 /System/Volumes/Data/mnt/<이름>에 붙임. /USA_DB·/usadata*·/mnt는 없음, ~/Desktop/usadata4는
    자동 연결 폴더로 가는 링크, /Volumes/colordata는 SMB(여기서는 폴더), /Volumes/bgfinal은 없음."""
    root = str(root)
    copy_data("mac_b", ("auto_master", "auto_nfs", "auto_nfs_back"), os.path.join(root, "etc"))
    mnt = os.path.join(root, "System", "Volumes", "Data", "mnt")
    for key in MAC_B_KEYS:
        os.makedirs(os.path.join(mnt, key))  # 붙지 않은 것은 빈 자동 연결 폴더 (dr-xr-xr-x)
    config = os.path.join(mnt, "USA_DB", "test_jn", ".yesoncheck")
    write_config(config)
    touch(mnt + FL_VIDEO)
    touch(mnt + FL_JOB + "/scene-A002/frames/FL_904_A002_TK1.mov")
    touch(mnt + "/usadata2/Titmouse/FLORIDA/FL_Season01/FL_905/scene-A001/frames/FL_905_A001_TK1.mov")
    touch(mnt + "/usadata4/BentoBox_Data/BentoBox_data/BB_New/a.mov")
    touch(mnt + "/bgfinal/bgfinal1/a.mov")
    desktop = os.path.join(root, "Users", desktop_user, "Desktop")
    os.makedirs(desktop)
    os.symlink(os.path.join(mnt, "usadata4"), os.path.join(desktop, "usadata4"))
    os.makedirs(os.path.join(root, "Volumes", "colordata", "KOTH"))
    return SimpleNamespace(root=root, mnt=mnt, config=config)


def make_reference(root):
    """기준 Mac 모양: /USA_DB·/usadata1~6·/bgfinal·/CH_PROPS는 Data 볼륨의 마운트 위치로 가는 링크, ~/Desktop/usadata4는
    마운트 위치 그대로, /Volumes/colordata는 SMB, /Volumes/bgfinal은 없음 (실제로도 없음)."""
    root = str(root)
    copy_data("reference", ("auto_master", "fstab"), os.path.join(root, "etc"))
    data = os.path.join(root, "System", "Volumes", "Data")
    for name in ("USA_DB", "usadata1", "usadata2", "usadata3", "usadata5", "usadata6", "bgfinal", "CH_PROPS"):
        os.makedirs(os.path.join(data, name))
        os.symlink(os.path.join(data, name), os.path.join(root, name))
    os.makedirs(os.path.join(root, "Users", "studio01", "Desktop", "usadata4"))
    os.makedirs(os.path.join(root, "Volumes", "colordata"))
    config = os.path.join(data, "USA_DB", "test_jn", ".yesoncheck")
    write_config(config)
    return SimpleNamespace(root=root, data=data, config=config)


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    monkeypatch.delenv(shared_config.CONFIG_DIR_ENV, raising=False)
    yield
    paths.activate_mount_map(None)


@pytest.fixture
def mac_b(tmp_path, mac):
    """mac_b 모양 + 공유 설정을 읽은 뒤의 맵 (path_map.json의 "mac"까지 봄)."""
    layout = make_mac_b(tmp_path / "mac_b")
    layout.startup = mac_mounts.read_mount_map(root=layout.root)
    layout.map = layout.startup.with_canonical_roots(PATH_MAP_ROOTS)
    paths.activate_mount_map(layout.map)
    return layout


def conversions(path):
    """경로 하나의 모든 변환 결과 (변환이 오류면 그 오류 문구)."""
    result = {}
    for name in ("to_native", "to_canonical", "to_storage", "from_storage", "thumbnail_key"):
        try:
            result[name] = getattr(paths, name)(path)
        except PathMapError as exc:
            result[name] = f"PathMapError: {exc}"
    return result


def assert_unchanged(mount_map, battery):
    """mount_map을 써도 battery의 모든 경로·변환이 맵이 없을 때(예전 Mac 동작)와 글자까지 같음."""
    paths.activate_mount_map(None)
    before = {path: conversions(path) for path in battery}
    paths.activate_mount_map(mount_map)
    try:
        after = {path: conversions(path) for path in battery}
    finally:
        paths.activate_mount_map(None)
    assert after == before


# ---- 읽기 (auto_master·간접 맵·fstab) ----

def test_mac_b_startup_map_only_resolves_config_root(tmp_path, mac):
    layout = make_mac_b(tmp_path)
    found = mac_mounts.read_mount_map(root=layout.root)
    mnt = layout.mnt
    assert [(m.path, m.names, m.source, m.displaced) for m in found.mounts] == [
        (f"{mnt}/{key}", (key,), "auto_nfs", True) for key in MAC_B_KEYS]
    assert found.mounts[0].remote == "nfs://203.0.113.3:/data/USA_DB"
    assert found.problems == [] and found.notes == []
    assert found.map_dirs == {mnt}  # auto_nfs_back은 auto_master가 가리키지 않아 읽지 않음
    # 시작할 때는 공유 설정 폴더의 앞부분만 (나머지는 공유 설정의 path_map.json을 읽은 뒤)
    assert {root: m.path for root, m in found.forward.items()} == {"/USA_DB": f"{mnt}/USA_DB"}
    assert found.reverse == []
    lines = found.report_lines()
    assert f"/USA_DB → {mnt}/USA_DB (auto_nfs)" in lines
    assert any("제자리가 아닌 공유 9개" in line and "path_map.json" in line for line in lines)


def test_mac_b_loaded_map_uses_path_map_roots(mac_b):
    mnt = mac_b.mnt
    assert {root: m.path for root, m in mac_b.map.forward.items()} == {
        "/USA_DB": f"{mnt}/USA_DB", "/usadata2": f"{mnt}/usadata2", "/usadata3": f"{mnt}/usadata3",
        "/usadata1": f"{mnt}/usadata1", "/usadata5": f"{mnt}/usadata5", "/usadata6": f"{mnt}/usadata6",
        "/usadata7": f"{mnt}/usadata7", "/bgfinal": f"{mnt}/bgfinal"}
    # 공유 설정의 앞부분이 아닌 /Volumes/<이름>은 바꾸지 않음, ~/Desktop/usadata4는 이 Mac에 있음(링크)
    assert "/Volumes/bgfinal" not in mac_b.map.forward and USADATA4 not in mac_b.map.forward
    roots = {mount.path: root for mount, root in mac_b.map.reverse_roots}
    assert roots[f"{mnt}/usadata4"] == USADATA4 and roots[f"{mnt}/bgfinal"] == "/bgfinal"
    lines = mac_b.map.mapping_lines()
    assert f"/usadata2 → {mnt}/usadata2 (auto_nfs)" in lines
    assert f"공유 설정에 적을 때: {mnt}/usadata4 → {USADATA4}" in lines


def test_special_auto_master_entries_are_skipped(tmp_path):
    write(tmp_path / "etc" / "auto_master",
          "#\n# Automounter master map\n#\n"
          "+auto_master\t\t# Use directory service\n"
          "/net\t\t\t-hosts\t\t-nobrowse,hidefromfinder,nosuid\n"
          "/home\t\t\tauto_home\t-nobrowse,hidefromfinder\n"
          "/home2 auto_home\n"
          "/Network/Servers\t-fstab\n"
          "/-\t\t\t-static\n"
          "/nothing -null\n"
          "/- auto_direct\n"
          "/mnt2   auto_x   -nobrowse   # 옵션과 주석\n")
    write(tmp_path / "etc" / "auto_home", "usadata2 server:/data/usadata2\n")  # 읽으면 안 됨
    write(tmp_path / "etc" / "auto_direct", "/usadata3 server:/data/usadata3\n")  # 직접 맵 — 읽지 않음
    write(tmp_path / "etc" / "auto_x",
          "# 주석\n"
          "usadata3 -fstype=nfs,rw \\\n"
          "    nfs://203.0.113.3:/data/usadata3\n"
          "\n"
          "usadata2 -fstype=nfs  server:/data/&\n"  # &는 항목 이름 (L1)
          "*  -fstype=nfs  server:/data/&\n"
          "+auto_more\n")
    found = mac_mounts.read_mount_map(root=str(tmp_path))
    assert [(m.path, m.names, m.source, m.remote) for m in found.mounts] == [
        (f"{tmp_path}/mnt2/usadata3", ("usadata3",), "auto_x", "nfs://203.0.113.3:/data/usadata3"),
        (f"{tmp_path}/mnt2/usadata2", ("usadata2",), "auto_x", "server:/data/usadata2")]
    assert found.problems == []
    assert found.map_dirs == {f"{tmp_path}/mnt2"}
    notes = "\n".join(found.notes)
    assert "/- auto_direct" in notes and "*" in notes and "+auto_more" in notes
    assert "/net" not in notes and "auto_home" not in notes and "-null" not in notes and "+auto_master" not in notes
    # L5: 와일드카드·실행 맵 아래의 이름은 공유 설정에 적을 경로를 정하지 못함 → 저장하지 않음
    loaded = found.with_canonical_roots(PATH_MAP_ROOTS)
    assert loaded.to_canonical(f"{tmp_path}/mnt2/usadata2/x") == "/usadata2/x"
    with pytest.raises(PathMapError, match="맵 폴더"):
        loaded.to_canonical(f"{tmp_path}/mnt2/anything/x")  # 와일드카드(*)로 붙는 이름
    os.chmod(tmp_path / "etc" / "auto_x", 0o755)
    executable = mac_mounts.read_mount_map(root=str(tmp_path)).with_canonical_roots(PATH_MAP_ROOTS)
    assert executable.mounts == [] and any("실행 맵" in note for note in executable.notes)
    with pytest.raises(PathMapError, match="맵 폴더"):
        executable.to_canonical(f"{tmp_path}/mnt2/usadata2/x")


def test_unreadable_config_is_reported(tmp_path):
    write(tmp_path / "etc" / "auto_master", "/System/Volumes/Data/mnt auto_nfs\n")  # auto_nfs가 없음
    found = mac_mounts.read_mount_map(root=str(tmp_path))
    assert found.mounts == []
    assert len(found.problems) == 1
    assert f"{tmp_path}/etc/auto_nfs" in found.problems[0] and "FileNotFoundError" in found.problems[0]
    assert any(found.problems[0] in line for line in found.report_lines())
    assert found.problems[0] in found.describe(shared_config.MAC_CONFIG_DIR)

    missing = mac_mounts.read_mount_map(root=str(tmp_path / "nothing"))
    assert missing.mounts == [] and "auto_master" in missing.problems[0]


def test_fstab_types_comments_passwords_and_bad_bytes(tmp_path):
    """L2: 모르는 네트워크 종류는 notes에. L3: fstab의 #은 줄 맨 앞만 주석, 비밀번호는 가림. L4: NUL은 문제로 (멈추지 않음)."""
    write(tmp_path / "etc" / "auto_master", "/-\t-static\n")
    write(tmp_path / "etc" / "fstab",
          "# 주석 //u:secret@host/x /Volumes/z smbfs rw\n"
          "LABEL=Backup none hfs rw,noauto\n"
          "UUID=1234-5678 /Volumes/Local apfs rw\n"
          "/dev/disk3s1 /Volumes/Data2 apfs rw\n"
          "//u:pa#ss@host/usadata2 /Volumes/x smbfs rw\n"
          "//u:pw@host/usadata2 /Volumes/x2 smb rw\n"
          "server:/data/usadata3 /Volumes/y nfs4 rw\n"
          "host:/dav /Volumes/d webdav rw\n"
          "https://h/dav /Volumes/d2 webdav rw\n"
          "s:/data/x /Vol\\000umes/x nfs rw\n")
    found = mac_mounts.read_mount_map(root=str(tmp_path))
    assert [(m.path, m.names, m.remote) for m in found.mounts] == [
        (f"{tmp_path}/Volumes/x", ("usadata2", "x"), "//u:***@host/usadata2"),
        (f"{tmp_path}/Volumes/d2", ("dav", "d2"), "https://h/dav")]
    notes = "\n".join(found.notes)
    assert "모르는 종류(smb)" in notes and "모르는 종류(nfs4)" in notes and "모르는 종류(webdav)" in notes
    assert "LABEL" not in notes and "apfs" not in notes and "주석" not in notes
    text = "\n".join(found.report_lines() + found.problems)
    assert "secret" not in text and "pa#ss" not in text and ":pw@" not in text
    assert any("NUL" in problem and "/Vol" in problem for problem in found.problems)

    write(tmp_path / "etc" / "auto_master", "/mn\x00t auto_x\n")
    write(tmp_path / "etc" / "auto_x", "a s:/a\n")
    nul = mac_mounts.read_mount_map(root=str(tmp_path))
    assert nul.mounts == [] and any("ValueError" in problem for problem in nul.problems)


def test_names_are_case_sensitive(tmp_path, mac):
    """L9: 맵 항목 USADATA2는 공유 설정의 /usadata2와 다른 이름 — 바꾸지 않고 describe가 그렇게 알림."""
    write(tmp_path / "etc" / "auto_master", "/mnt2 auto_x\n")
    write(tmp_path / "etc" / "auto_x", "USADATA2 s:/data/USADATA2\n")
    (tmp_path / "mnt2").mkdir()
    found = mac_mounts.read_mount_map(root=str(tmp_path)).with_canonical_roots(["/usadata2"])
    assert found.forward == {"/USADATA2": found.mounts[0]}
    assert found.to_native("/usadata2/x") == "/usadata2/x"
    assert "대소문자 구분" in found.describe("/usadata2/x")


def test_startup_reads_nothing_under_users(tmp_path, mac, monkeypatch):
    """시작할 때(load_mount_map, 스플래시 전 GUI 스레드)는 /Users 아래(~/Desktop 등)를 보지 않음 — 개인정보 보호 창이 시작을
    막지 않게. 기준 Mac(fstab에 ~/Desktop/usadata4)·mac_b(~/Desktop/usadata4 링크) 모두."""
    from yesoncheck import app

    touched = []
    for name in ("scandir", "listdir", "stat", "lstat", "readlink", "access"):
        real = getattr(os, name)

        def spy(path=".", *args, _real=real, _name=name, **kwargs):
            touched.append((_name, os.fspath(path) if not isinstance(path, int) else path))
            return _real(path, *args, **kwargs)

        monkeypatch.setattr(os, name, spy)
    for layout in (make_mac_b(tmp_path / "mac_b"), make_reference(tmp_path / "reference")):
        monkeypatch.setattr(mac_mounts, "DEFAULT_ROOT", layout.root)
        touched.clear()
        found = app.load_mount_map()
        assert found is paths.active_mount_map() and found.mounts
        users = os.path.join(layout.root, "Users")
        assert [t for t in touched if isinstance(t[1], str) and t[1].startswith(users)] == []
        assert touched  # 무엇인가는 봄 (/·/System/Volumes/Data 목록, 맵 폴더)


def test_windows_does_not_read_mount_map(tmp_path, monkeypatch):
    """Windows: load_mount_map은 아무것도 하지 않고 None, 경로 변환은 변환표 그대로 (Mac 맵이 있어도)."""
    from yesoncheck import app

    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda drive: {"Y:": "\\\\nas\\usadata2"}.get(drive))
    paths._cached_remote_name.cache_clear()
    assert app.load_mount_map() is None and paths.active_mount_map() is None
    layout = make_mac_b(tmp_path)
    paths.activate_mount_map(mac_mounts.read_mount_map(root=layout.root).with_canonical_roots(PATH_MAP_ROOTS))
    paths.activate(PathMap.from_dict({"version": 1, "shares": [{"mac": "/usadata2", "windows": ["\\\\nas\\usadata2"]}]}, "t"))
    try:
        assert paths.to_native("/usadata2/x") == "\\\\nas\\usadata2\\x"
        assert paths.to_canonical("Y:\\x") == "/usadata2/x"
        assert paths.to_storage("Y:\\x") == "/usadata2/x"
        assert paths.from_storage("/usadata2/x") == "\\\\nas\\usadata2\\x"
        assert paths.thumbnail_key("Y:\\x") == md5("/usadata2/x")
        assert paths.to_storage("C:\\local\\a.mov") == "C:\\local\\a.mov"
    finally:
        paths.activate(None)
        paths.activate_mount_map(None)
        paths._cached_remote_name.cache_clear()


# ---- 경로 변환 (mac_b) ----

def test_mac_b_conversions(mac_b):
    mnt = mac_b.mnt
    native = mnt + FL_VIDEO
    assert paths.to_native(FL_VIDEO) == native
    assert paths.from_storage(FL_VIDEO) == native
    assert paths.to_canonical(native) == FL_VIDEO
    assert paths.to_storage(native) == FL_VIDEO
    assert paths.thumbnail_key(native) == md5(FL_VIDEO)  # 다른 Mac·Windows가 만든 썸네일 이름
    assert paths.to_native(shared_config.MAC_CONFIG_DIR) == mac_b.config
    assert paths.to_native("/usadata2") == mnt + "/usadata2"
    assert paths.to_native("/usadata2/") == mnt + "/usadata2/"
    assert paths.to_canonical(mnt + "/usadata3/Bento_Project/") == "/usadata3/Bento_Project/"
    assert paths.to_native("/bgfinal/bgfinal1/a.mov") == mnt + "/bgfinal/bgfinal1/a.mov"
    assert paths.to_storage(mnt + "/bgfinal/bgfinal1/a.mov") == "/bgfinal/bgfinal1/a.mov"  # 기준 Mac과 같은 /bgfinal
    # 바꾸지 않는 경로는 예전 Mac 동작 그대로 (/Volumes/bgfinal은 공유 설정의 앞부분이 아님 — 기준 Mac에서도 열리지 않음)
    for path in ("/Volumes/colordata/KOTH/a.mov", "/Volumes/bgfinal/colordata/BIG_MOUTH/a.mov", "/tmp/a.mov",
                 "/System/Volumes/Data/usadata2/a.mov", "/usadata22/a.mov", USADATA4 + "/a.mov", "a.mov", ""):
        assert paths.to_native(path) == path
        assert paths.from_storage(path) == path
        assert paths.to_storage(path) == path
        assert paths.thumbnail_key(path) == md5(path)
    assert paths.to_canonical("/System/Volumes/Data/usadata2/a.mov") == "/usadata2/a.mov"  # 예전처럼 접두만 뺌


def test_firmlink_and_mnt_forms_map_back(tmp_path):
    """실제 모양의 경로: /System/Volumes/Data/mnt/<이름>과 그 접두를 뺀 /mnt/<이름>은 공유 설정의 앞부분으로 — 저장하는
    경로에 /mnt·/System/Volumes/Data/mnt가 남지 않음. usadata4는 path_map 항목(~/Desktop/usadata4)으로."""
    mounts = [mac_mounts.Mount(f"/System/Volumes/Data/mnt/{key}", f"/System/Volumes/Data/mnt/{key}", (key,), "auto_nfs",
                               f"nfs://203.0.113.3:/data/{key}", True) for key in ("usadata2", "usadata4", "bgfinal")]
    found = mac_mounts.MountMap(str(tmp_path), "auto_master", "fstab", mounts, ["/System/Volumes/Data/mnt"], [], [],
                                roots=["/USA_DB"], loaded=False).with_canonical_roots(PATH_MAP_ROOTS)
    for native, canonical in (("/System/Volumes/Data/mnt/usadata2/Titmouse", "/usadata2/Titmouse"),
                              ("/mnt/usadata2/Titmouse", "/usadata2/Titmouse"),
                              ("/System/Volumes/Data/mnt/usadata4/BentoBox_Data/a.mov", USADATA4 + "/BentoBox_Data/a.mov"),
                              ("/mnt/usadata4/BentoBox_Data/a.mov", USADATA4 + "/BentoBox_Data/a.mov"),
                              ("/mnt/bgfinal/bgfinal1/a.mov", "/bgfinal/bgfinal1/a.mov")):
        assert found.to_canonical(native) == canonical, native
    with pytest.raises(PathMapError, match="맵 폴더"):
        found.to_canonical("/mnt/usadata22/Titmouse")  # 맵에 없는 이름 → 정하지 못함 (저장하지 않음)
    assert found.to_canonical("/mnt2/usadata2/x") is None


def test_cross_layout_round_trip(tmp_path, mac):
    """mac_b의 파일 → 저장하는 경로가 기준 Mac과 글자까지 같고, 기준 Mac은 그 경로로 같은 파일을 열고, 썸네일 이름도 같음.
    mac_b도 그 경로로 같은 파일을 다시 엶."""
    m = make_mac_b(tmp_path / "mac_b")
    ref = make_reference(tmp_path / "reference")
    m_map = mac_mounts.read_mount_map(root=m.root).with_canonical_roots(PATH_MAP_ROOTS)
    ref_map = mac_mounts.read_mount_map(root=ref.root).with_canonical_roots(PATH_MAP_ROOTS)
    cases = [
        (FL_VIDEO, m.mnt + FL_VIDEO),
        ("/USA_DB/test_jn/.yesoncheck/work_paths.json", m.config + "/work_paths.json"),
        (USADATA4 + "/BentoBox_Data/BentoBox_data/BB_New/a.mov", m.mnt + "/usadata4/BentoBox_Data/BentoBox_data/BB_New/a.mov"),
        (USADATA4 + "/BentoBox_Data/BentoBox_data/BB_New/a.mov", USADATA4 + "/BentoBox_Data/BentoBox_data/BB_New/a.mov"),
        ("/bgfinal/bgfinal1/a.mov", m.mnt + "/bgfinal/bgfinal1/a.mov"),
    ]
    for canonical, m_native in cases:
        touch(ref.root + canonical)  # 기준 Mac: 공유 설정의 경로 그대로가 이 Mac의 경로
        paths.activate_mount_map(m_map)
        stored = paths.to_storage(m_native)
        m_key = paths.thumbnail_key(m_native)
        reopened = paths.from_storage(stored)
        paths.activate_mount_map(ref_map)
        assert stored == canonical == paths.to_storage(canonical), m_native
        assert m_key == paths.thumbnail_key(canonical) == md5(canonical), m_native
        assert paths.from_storage(stored) == canonical and os.path.exists(ref.root + canonical)
        # mac_b가 다시 여는 곳 = 그 파일 (링크로 여는 /Users/… 경로는 이 시험에서 root 아래로 옮겨 봄)
        m_file = m_native if m_native.startswith(m.root) else m.root + m_native
        opened = reopened if reopened.startswith(m.root) else m.root + reopened
        assert os.path.exists(opened) and os.path.realpath(opened) == os.path.realpath(m_file), m_native


def test_other_login_maps_usadata4_root(tmp_path, mac):
    """M1: ~/Desktop/usadata4가 없는 Mac(다른 로그인): path_map의 앞부분 /Users/studio01/Desktop/usadata4를 자동 연결 폴더로."""
    layout = make_mac_b(tmp_path, desktop_user="artist")
    found = mac_mounts.read_mount_map(root=layout.root).with_canonical_roots(PATH_MAP_ROOTS)
    paths.activate_mount_map(found)
    bb = WORK_PATHS["BB_Animatic"]
    assert paths.to_native(bb) == layout.mnt + "/usadata4" + bb[len(USADATA4):]
    assert paths.to_storage(layout.mnt + "/usadata4/x.mov") == USADATA4 + "/x.mov"
    description = found.describe(bb)
    assert f"{USADATA4} → {layout.mnt}/usadata4 (auto_nfs: nfs://203.0.113.14:/volume1/usadata4)" in description


def test_existing_link_to_autofs_folder(tmp_path, mac):
    """/usadata2가 자동 연결 폴더로 가는 링크(synthetic.conf 등)로 있으면 그대로 열고, 따라간 경로는 /usadata2로."""
    layout = make_mac_b(tmp_path)
    os.symlink(os.path.join(layout.mnt, "usadata2"), os.path.join(layout.root, "usadata2"))
    found = mac_mounts.read_mount_map(root=layout.root).with_canonical_roots(PATH_MAP_ROOTS)
    assert "/usadata2" not in found.forward
    paths.activate_mount_map(found)
    assert paths.to_native("/usadata2/Titmouse") == "/usadata2/Titmouse"
    assert paths.to_canonical(layout.mnt + "/usadata2/Titmouse") == "/usadata2/Titmouse"


# ---- fstab ----

def test_fstab_static_mount_under_other_volumes_name(tmp_path, mac):
    """fstab으로 /Volumes/NAS2에 붙인 203.0.113.3:/data/usadata2 — 서버 쪽 경로의 이름으로 path_map의 /usadata2와 맞춤."""
    write(tmp_path / "etc" / "auto_master", "/-\t\t\t-static\n")
    write(tmp_path / "etc" / "fstab", "203.0.113.3:/data/usadata2  /Volumes/NAS2  nfs  bg,intr,hard,resvport 0 0\n")
    (tmp_path / "Volumes" / "NAS2" / "Titmouse").mkdir(parents=True)
    startup = mac_mounts.read_mount_map(root=str(tmp_path))
    nas2 = f"{tmp_path}/Volumes/NAS2"
    assert [(m.path, m.names, m.displaced) for m in startup.mounts] == [(nas2, ("usadata2", "NAS2"), False)]
    assert startup.forward == {} and startup.to_canonical(nas2 + "/a.mov") is None
    found = startup.with_canonical_roots(PATH_MAP_ROOTS)
    assert {root: m.path for root, m in found.forward.items()} == {"/usadata2": nas2}  # /Volumes/usadata2는 앞부분 아님
    assert f"/usadata2 → {nas2} (fstab)" in found.mapping_lines()
    assert found.to_native("/usadata2/Titmouse/a.mov") == nas2 + "/Titmouse/a.mov"
    assert found.to_canonical(nas2 + "/Titmouse/a.mov") == "/usadata2/Titmouse/a.mov"  # 대신 여는 공유는 되돌림
    assert found.map_dirs == frozenset()


def test_fstab_net_entry_mounts_under_network_servers(tmp_path, mac):
    write(tmp_path / "etc" / "auto_master", "/Network/Servers\t-fstab\n/-\t\t\t-static\n")
    write(tmp_path / "etc" / "fstab", "203.0.113.3:/data/usadata2 /usadata2 nfs net,bg,intr\n")
    (tmp_path / "Network" / "Servers").mkdir(parents=True)
    found = mac_mounts.read_mount_map(root=str(tmp_path)).with_canonical_roots(PATH_MAP_ROOTS)
    servers = f"{tmp_path}/Network/Servers"
    net = f"{servers}/203.0.113.3/data/usadata2"
    assert [(m.path, m.source, m.displaced) for m in found.mounts] == [(net, "fstab", True)]
    assert found.forward["/usadata2"].path == net
    assert found.to_canonical(net + "/Titmouse/a.mov") == "/usadata2/Titmouse/a.mov"
    assert {servers, f"{servers}/203.0.113.3", f"{servers}/203.0.113.3/data"} <= found.map_dirs
    with pytest.raises(PathMapError):
        found.to_canonical(f"{servers}/203.0.113.3/data/other/a.mov")  # -fstab 맵 폴더 아래 모르는 곳
    assert found.problems == []

    # -fstab 맵이 없으면 net 항목은 붙지 않음 → 알리고 보지 않음
    write(tmp_path / "etc" / "auto_master", "/-\t\t\t-static\n")
    without = mac_mounts.read_mount_map(root=str(tmp_path))
    assert without.mounts == [] and any("net" in note and "-fstab" in note for note in without.notes)


def test_fstab_root_mount_only_under_data_volume(tmp_path, mac):
    """synthetic 링크 없이 /USA_DB가 /System/Volumes/Data/USA_DB에만 있는 Mac: 시작할 때 그 경로로 공유 설정 폴더를 찾음."""
    write(tmp_path / "etc" / "auto_master", "/-\t\t\t-static\n")
    write(tmp_path / "etc" / "fstab", "203.0.113.3:/data/USA_DB\t/USA_DB\t\tnfs\tbg,intr,hard\n")
    data_usa_db = f"{tmp_path}/System/Volumes/Data/USA_DB"
    write_config(data_usa_db + "/test_jn/.yesoncheck")
    found = mac_mounts.read_mount_map(root=str(tmp_path))
    assert [(m.path, m.displaced) for m in found.mounts] == [(data_usa_db, True)]
    assert f"/USA_DB → {data_usa_db} (fstab)" in found.report_lines()
    paths.activate_mount_map(found)
    assert shared_config.configured_config_dir() == data_usa_db + "/test_jn/.yesoncheck"
    paths.activate_mount_map(found.with_canonical_roots(PATH_MAP_ROOTS))
    assert paths.to_canonical(data_usa_db + "/test_jn/x") == "/USA_DB/test_jn/x"

    # 링크가 있으면 fstab 위치 그대로 (바꾸지 않음)
    os.symlink(data_usa_db, str(tmp_path / "USA_DB"))
    linked = mac_mounts.read_mount_map(root=str(tmp_path))
    assert [(m.path, m.displaced) for m in linked.mounts] == [(f"{tmp_path}/USA_DB", False)]
    assert linked.forward == {}


def test_two_shares_with_one_name_are_reported_not_picked(tmp_path, mac):
    """/usadata2에 맞는 공유가 둘(fstab /Volumes/NAS2와 auto_nfs의 usadata2)이면 고르지 않고 알림. 그 공유 아래는 저장도 못 함."""
    write(tmp_path / "etc" / "auto_master", "/-\t\t\t-static\n/System/Volumes/Data/mnt auto_nfs\n")
    write(tmp_path / "etc" / "auto_nfs",
          "usadata2 -fstype=nfs,rw nfs://203.0.113.3:/data/usadata2\n"
          "USA_DB -fstype=nfs,rw nfs://203.0.113.3:/data/USA_DB\n")
    write(tmp_path / "etc" / "fstab",
          "203.0.113.3:/data/usadata2  /Volumes/NAS2  nfs  bg,intr\n"
          "//guest@203.0.113.9/USA_DB  /Volumes/DB  smbfs  rw\n")
    (tmp_path / "Volumes" / "NAS2").mkdir(parents=True)
    (tmp_path / "Volumes" / "DB").mkdir(parents=True)
    mnt = f"{tmp_path}/System/Volumes/Data/mnt"
    os.makedirs(mnt + "/usadata2")
    startup = mac_mounts.read_mount_map(root=str(tmp_path))
    found = startup.with_canonical_roots(PATH_MAP_ROOTS)
    assert "/usadata2" not in found.forward
    assert [m.path for m in found.ambiguous["/usadata2"]] == [mnt + "/usadata2", f"{tmp_path}/Volumes/NAS2"]
    lines = "\n".join(found.mapping_lines())
    assert "/usadata2: 맞는 공유가 여럿" in lines and f"{tmp_path}/Volumes/NAS2" in lines and "썸네일" in lines
    paths.activate_mount_map(found)
    with pytest.raises(PathMapError, match="NAS2"):
        paths.to_native("/usadata2/Titmouse")
    with pytest.raises(PathMapError, match="여럿"):
        paths.to_storage(mnt + "/usadata2/a.mov")
    assert paths.thumbnail_key(mnt + "/usadata2/a.mov") == md5(mnt + "/usadata2/a.mov")
    # 공유 설정 폴더(/USA_DB)도 맞는 공유가 둘 → 공유 설정 오류에 후보가 보임
    from yesoncheck.player_sidebar import gather_shared_config

    paths.activate_mount_map(startup)
    state = gather_shared_config()
    assert state.config_dir is None
    assert "/Volumes/DB" in state.shared_config_problem and f"{mnt}/USA_DB" in state.shared_config_problem


# ---- 기준 Mac: 아무것도 바뀌지 않음 ----

REFERENCE_BATTERY = list(WORK_PATHS.values()) + [
    shared_config.MAC_CONFIG_DIR, FL_VIDEO, "/USA_DB/test_jn/.yesoncheck/work_paths.json",
    "/System/Volumes/Data/usadata2/Titmouse/a.mov", "/System/Volumes/Data/USA_DB/test_jn/x", "/bgfinal/colordata/a.mov",
    "/System/Volumes/Data/bgfinal/a.mov", USADATA4 + "/BentoBox_Data/a.mov", "/usadata4/x", "/usadata4/BentoBox_Data/a.mov",
    "/Volumes/usadata4/x.mov", "/Volumes/colordata/FLORIDA/a.mov", "/Volumes/bgfinal/colordata/BIG_MOUTH/a.mov",
    "/usadata1/a.mov", "/CH_PROPS/a.mov", "/mnt/usadata2/a.mov", "/System/Volumes/Data/mnt/usadata2/a.mov", "/tmp/a.mov",
    "a.mov", "", "/", "/Volumes", "/System/Volumes/Data",
]


def test_reference_layout_changes_nothing(tmp_path, mac, monkeypatch):
    """기준 Mac(실제 auto_master·fstab·path_map.json, 공유를 모두 제자리에 붙임): 작품 경로에 /usadata4/x·/bgfinal/x가
    있어도 경로·썸네일 이름·저장 경로가 글자까지 그대로."""
    from yesoncheck.player_sidebar import gather_shared_config

    layout = make_reference(tmp_path)
    write_config(layout.config, dict(WORK_PATHS, NEW4="/usadata4/x", NEWBG="/bgfinal/x"))
    startup = mac_mounts.read_mount_map(root=layout.root)
    assert startup.problems == []
    assert sorted(m.path for m in startup.mounts) == sorted(
        [f"{layout.root}/{name}" for name in ("USA_DB", "usadata2", "usadata3", "CH_PROPS", "usadata1", "usadata5",
                                              "usadata6", "bgfinal")] + [layout.root + USADATA4])
    assert all(m.source == "fstab" and not m.displaced for m in startup.mounts)
    monkeypatch.setenv(shared_config.CONFIG_DIR_ENV, layout.config)
    paths.activate_mount_map(startup)
    state = gather_shared_config()
    assert state.shared_config_problem is None and state.path_map_problem is None
    loaded = state.mount_map
    assert loaded.forward == {} and loaded.ambiguous == {} and loaded.reverse == [] and loaded.unmapped == []
    assert loaded.map_dirs == frozenset()  # 목록 다시 읽기(check_gone)도 그대로
    assert loaded.mapping_lines() == []
    battery = REFERENCE_BATTERY + [layout.root + path for path in REFERENCE_BATTERY if path.startswith("/")]
    assert_unchanged(startup, battery)
    assert_unchanged(loaded, battery)


def test_reference_without_path_map_only_logs(tmp_path, mac, monkeypatch, capsys):
    """공유를 모두 제자리에 붙인 Mac은 path_map.json이 없어도 바뀌는 것이 없음 → 로그만 (실행 시험의 공유 설정처럼)."""
    from yesoncheck.player_sidebar import gather_shared_config

    layout = make_reference(tmp_path)
    os.remove(os.path.join(layout.config, "path_map.json"))
    monkeypatch.setenv(shared_config.CONFIG_DIR_ENV, layout.config)
    paths.activate_mount_map(mac_mounts.read_mount_map(root=layout.root))
    state = gather_shared_config()
    assert state.shared_config_problem is None and state.path_map_problem is None
    assert "path_map.json을 읽지 못함" in capsys.readouterr().out


def test_real_config_changes_nothing_here(mac):
    """이 Mac의 실제 /etc/auto_master·/etc/fstab (읽기만): 이 Mac에 있는 공유 설정의 앞부분은 바뀌지 않음."""
    startup = mac_mounts.read_mount_map(root="/")
    found = startup.with_canonical_roots(PATH_MAP_ROOTS)
    for root in found.forward:
        assert not os.path.lexists(root), root  # 이 Mac에 있는 앞부분은 바꾸지 않음
    # 이 Mac에 없어서 바꾸는 앞부분(found.forward) 아래 경로는 뺌 — 예: 시험 자료 path_map.json의
    # /Users/studio01/Desktop/usadata4가 이 Mac에서는 다른 사용자의 Desktop에 붙어 있으면 바뀌는 것이 맞음
    here = [path for path in REFERENCE_BATTERY
            if path.startswith("/") and any(os.path.lexists(r) for r in (path, mac_mounts.first_root(path)) if r)
            and not any(m.displaced and path.startswith(m.path) for m in found.mounts)
            and not any(path == root or path.startswith(root + "/") for root in found.forward)]
    assert_unchanged(startup, here)
    assert_unchanged(found, here)


# ---- 공유 설정 폴더 ----

def test_mac_config_dir_found_through_mount_map(tmp_path, mac):
    from yesoncheck.player_sidebar import gather_shared_config

    layout = make_mac_b(tmp_path)
    paths.activate_mount_map(mac_mounts.read_mount_map(root=layout.root))  # 시작할 때의 맵
    assert shared_config.configured_config_dir() == layout.config
    state = gather_shared_config()
    assert state.shared_config_problem is None and state.path_map_problem is None
    assert state.config_dir == layout.config and state.work_paths == WORK_PATHS
    assert state.mount_map.loaded and state.mount_map.to_canonical(layout.mnt + "/usadata4/x") == USADATA4 + "/x"


def test_mac_config_dir_not_found_says_what_was_tried(mac_b, monkeypatch):
    from yesoncheck.player_sidebar import gather_shared_config

    # 자동 연결 설정에 그 이름의 공유가 없음
    monkeypatch.setattr(shared_config, "MAC_CONFIG_DIR", NO_SUCH_CONFIG)
    problem = gather_shared_config().shared_config_problem
    assert f"작품 경로 파일이 없습니다: {NO_SUCH_CONFIG}/work_paths.json" in problem
    assert "/yc_no_such_share: 이 Mac에 없음" in problem and f"{mac_b.root}/etc/auto_master" in problem
    assert "Traceback" in problem

    # 이름은 있지만 공유가 붙지 않음 (빈 자동 연결 폴더)
    monkeypatch.setattr(shared_config, "MAC_CONFIG_DIR", "/USA_DB/test_jn/.yesoncheck")
    shutil.rmtree(os.path.join(mac_b.mnt, "USA_DB", "test_jn"))
    problem = gather_shared_config().shared_config_problem
    assert f"작품 경로 파일이 없습니다: {mac_b.config}/work_paths.json" in problem
    assert f"/USA_DB → {mac_b.mnt}/USA_DB (auto_nfs" in problem


def test_mac_config_dir_lookup_reports_read_error(tmp_path, mac, monkeypatch):
    from yesoncheck.player_sidebar import gather_shared_config

    monkeypatch.setattr(shared_config, "MAC_CONFIG_DIR", NO_SUCH_CONFIG)
    paths.activate_mount_map(mac_mounts.read_mount_map(root=str(tmp_path)))  # auto_master가 없음
    problem = gather_shared_config().shared_config_problem
    assert "작품 경로 파일이 없습니다" in problem
    assert f"{tmp_path}/etc/auto_master" in problem and "FileNotFoundError" in problem


def test_mac_config_dir_lookup_without_mount_map(mac):
    paths.activate_mount_map(None)
    assert "읽지 않았습니다" in shared_config.mac_config_dir_lookup()


def test_mac_b_without_path_map_is_reported(tmp_path, mac, qapp, dialogs, monkeypatch):
    """제자리가 아닌 공유가 있는 Mac에서 path_map.json을 읽지 못하면 변환표 오류 창 (/<이름>으로만 정함)."""
    layout = make_mac_b(tmp_path)
    os.remove(os.path.join(layout.config, "path_map.json"))
    paths.activate_mount_map(mac_mounts.read_mount_map(root=layout.root))
    from yesoncheck.main_window import VideoPlayer

    player = VideoPlayer()
    try:
        assert "path_map.json" in player.path_map_problem and player.shared_config_problem is None
        assert player.windowTitle().endswith("— 변환표 오류")
        player.resolve_shared_config_problem()
        assert [(kind, title) for kind, title, _text in dialogs.errors()] == [("warning", "변환표 오류")]
        assert paths.to_storage(layout.mnt + "/usadata4/x") == "/usadata4/x"  # /<이름>으로만
    finally:
        player.close()


# ---- 창: 작품 목록·작품 경로 관리·OCR 결과·주석 (mac_b) ----

@pytest.fixture
def mac_b_player(tmp_path, mac, qapp, monkeypatch):
    layout = make_mac_b(tmp_path / "mac_b")
    paths.activate_mount_map(mac_mounts.read_mount_map(root=layout.root))  # 시작할 때의 맵 (공유 설정은 창이 읽음)
    from yesoncheck.main_window import VideoPlayer

    player = VideoPlayer()
    yield player, layout
    player.close()


def test_work_list_opens_mapped_share_and_shares_thumbnail_names(mac_b_player, dialogs):
    from PyQt5.QtCore import Qt

    from tests.conftest import write_test_video

    player, layout = mac_b_player
    for video in (FL_VIDEO, FL_JOB + "/scene-A002/frames/FL_904_A002_TK1.mov"):
        write_test_video(layout.mnt + video)  # 목록의 첫 영상을 열므로 실제 영상으로
    assert player.shared_config_problem is None and player.path_map_problem is None
    assert paths.active_mount_map().loaded
    assert player.get_work_path("FL") == layout.mnt + "/usadata2/Titmouse/FLORIDA"
    player.workComboBox.setCurrentText("FL")
    player.seasonComboBox.setCurrentText("FL_Season01")
    player.jobComboBox.setCurrentText("FL_904")
    listed = [player.sidebar.item(i).data(Qt.UserRole) for i in range(player.sidebar.count())]
    assert listed == [layout.mnt + FL_VIDEO, layout.mnt + FL_JOB + "/scene-A002/frames/FL_904_A002_TK1.mov"]
    assert paths.thumbnail_key(listed[0]) == md5(FL_VIDEO)
    assert dialogs.errors() == []


def test_unopenable_work_path_is_reported(mac_b_player, dialogs):
    """/Volumes/bgfinal/…은 공유 설정의 앞부분이 아님(기준 Mac에서도 없음) → 빈 목록이 아니라 창으로, 찾아본 내용과 함께."""
    player, _layout = mac_b_player
    assert player.get_work_path("BM_Animatic") == ""
    errors = dialogs.errors()
    assert len(errors) == 1 and errors[0][1] == "작품 경로 오류"
    assert "폴더를 열 수 없습니다" in errors[0][2] and "/Volumes/bgfinal: 이 Mac에 없음" in errors[0][2]


def test_work_path_management_stores_shared_config_paths(mac_b_player, dialogs):
    from PyQt5.QtWidgets import QDialog, QFileDialog, QListWidget

    player, layout = mac_b_player
    mnt = layout.mnt
    # 고른 폴더(이 Mac 경로) → 공유 설정에 적을 Mac 경로 (/System/Volumes/Data/mnt가 아니라)
    assert player._stored_work_path_or_warn(mnt + "/usadata2/Titmouse/NEW", None) == "/usadata2/Titmouse/NEW"
    assert player._stored_work_path_or_warn(mnt + "/usadata4/BentoBox_Data", None) == USADATA4 + "/BentoBox_Data"
    assert player._stored_work_path_or_warn(USADATA4 + "/BentoBox_Data", None) == USADATA4 + "/BentoBox_Data"
    assert player._stored_work_path_or_warn(mnt + "/bgfinal/colordata/X", None) == "/bgfinal/colordata/X"
    assert dialogs.errors() == []
    assert player._stored_work_path_or_warn(mnt + "/zzz/X", None) is None  # 맵에 없는 이름: 저장하지 않고 창
    assert "경로를 저장할 수 없음" in [title for _k, title, _t in dialogs.errors()]
    dialogs.messages.clear()

    table = QListWidget()
    player._refresh_work_path_table(table)
    rows = {table.item(i).data(0x0100): table.item(i).text() for i in range(table.count())}
    assert rows["FL"] == f"FL: /usadata2/Titmouse/FLORIDA\n    → {mnt}/usadata2/Titmouse/FLORIDA"
    assert rows["KOTH_Animatic"] == "KOTH_Animatic: /Volumes/colordata/KOTH"  # 바꾸지 않는 경로는 예전처럼 한 줄

    # 경로 수정: 선택 창은 이 Mac 경로에서 시작하고, 고른 폴더는 Mac 경로로 저장
    starts = []
    new_folder = mnt + "/usadata2/Titmouse/FLORIDA2"
    os.makedirs(new_folder)
    original = QFileDialog.getExistingDirectory
    QFileDialog.getExistingDirectory = lambda parent, caption, start="", *a, **k: starts.append(start) or new_folder
    try:
        table.setCurrentRow([table.item(i).data(0x0100) for i in range(table.count())].index("FL"))
        player.edit_work_path(table, QDialog())
    finally:
        QFileDialog.getExistingDirectory = original
    assert starts == [mnt + "/usadata2/Titmouse/FLORIDA"]
    with open(os.path.join(layout.config, "work_paths.json"), encoding="utf-8") as fh:
        assert json.load(fh)["FL"] == "/usadata2/Titmouse/FLORIDA2"
    assert dialogs.errors() == []


def test_ocr_result_and_annotations_use_shared_config_paths(mac_b_player, dialogs, monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QFileDialog

    from yesoncheck.frame_annotations import FrameAnnotationStore

    player, layout = mac_b_player
    store = FrameAnnotationStore()
    store.video_path = layout.mnt + FL_VIDEO
    assert store.to_dict()["video_path"] == FL_VIDEO

    stored = "/usadata2/Titmouse/FLORIDA/FL_Season01/FL_904/없음.mov"
    result = tmp_path / "ocr_result.json"
    result.write_text(json.dumps({"video_path": stored, "segments": []}), encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(result), "JSON Files (*.json)"))
    player.load_ocr_result()
    warnings = [m for m in dialogs.messages if m[1] == "동영상 파일 없음"]
    assert len(warnings) == 1, dialogs.messages
    assert f"저장된 경로: {stored}" in warnings[0][2]
    assert f"이 PC 경로: {layout.mnt}{stored}" in warnings[0][2]


def test_unmappable_video_is_not_saved_and_user_is_told(mac_b_player, dialogs, monkeypatch, tmp_path):
    """H3: 자동 연결 맵 폴더 아래의 모르는 이름(맵에 없음·와일드카드) → OCR 결과·주석을 저장하지 않고 창으로. /mnt… 경로를
    적지 않음. 썸네일은 이 Mac 경로 이름 (로그 한 번)."""
    from PyQt5.QtWidgets import QFileDialog

    player, layout = mac_b_player
    video = touch(layout.mnt + "/zzz/show/a.mov")
    with pytest.raises(PathMapError, match="맵 폴더"):
        paths.to_storage(video)
    assert paths.thumbnail_key(video) == md5(video)

    player.filename_a = video
    player.last_ocr_segments = [{"text": "SC_001", "start_frame": 0, "end_frame": 1}]
    target = tmp_path / "out" / "a_ocr_result.json"
    target.parent.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "JSON Files (*.json)"))
    player.save_ocr_result()
    errors = dialogs.errors()
    assert [(kind, title) for kind, title, _t in errors] == [("critical", "저장 실패")]
    assert video in errors[0][2] and "맵 폴더" in errors[0][2]
    assert os.listdir(target.parent) == []  # 결과 파일·이미지 폴더 모두 없음

    dialogs.messages.clear()
    player.annotation_store.video_path = video
    assert player.auto_save_annotations() is False
    assert player.auto_save_annotations() is False  # 자동 저장은 자주 불림 → 창은 한 번
    assert [(kind, title) for kind, title, _t in dialogs.errors()] == [("critical", "주석 저장 실패")]
    assert "주석 저장 실패" in player.annotationStorageLabel.text()
    assert not os.path.exists(os.path.join(os.path.dirname(video), ".yesoncheck", "a_annotations.json"))


def test_before_shared_config_is_read_nothing_is_stored(tmp_path, mac, capsys):
    """공유 설정(path_map.json)을 읽기 전(시작할 때의 맵)에는 제자리가 아닌 공유 아래 경로를 공유 설정에 적지 않음 —
    읽은 뒤와 다른 경로를 적지 않게. 썸네일은 이 Mac 경로 이름, 그곳마다 로그 한 번."""
    layout = make_mac_b(tmp_path)
    paths.activate_mount_map(mac_mounts.read_mount_map(root=layout.root))
    native = layout.mnt + "/usadata4/x.mov"
    with pytest.raises(PathMapError, match="아직 읽지 않아"):
        paths.to_storage(native)
    with pytest.raises(PathMapError, match="아직 읽지 않아"):
        paths.to_canonical(native)
    assert paths.thumbnail_key(native) == paths.thumbnail_key(native) == md5(native)
    out = capsys.readouterr().out
    assert out.count("나눠 쓰지 않음") == 1


# ---- 목록 다시 읽기: 끊긴 공유는 '없어짐'이 아님 (mac_b) ----

def test_unmounted_autofs_share_is_not_gone(mac_b):
    video = mac_b.mnt + "/usadata3/Bento_Project/BB_Season14/job/scene-A001/frames/a.mov"  # 빈 자동 연결 폴더
    gone, detail = video_list.check_gone(video, enoent(video))
    assert gone is False and "비어" in detail
    linked = mac_b.root + USADATA4 + "/x/a.mov"  # 링크 → 붙지 않은 자동 연결 폴더
    shutil.rmtree(mac_b.mnt + "/usadata4/BentoBox_Data")
    gone, detail = video_list.check_gone(linked, enoent(linked))
    assert gone is False


def test_walk_up_to_autofs_map_dir_is_not_gone(mac_b):
    """자동 연결 맵 폴더(/System/Volumes/Data/mnt)까지 올라가면 공유 밖 — 맵 폴더 목록에 공유 이름이 없어도
    (-nobrowse 맵은 붙은 것만 보임) 없어진 것으로 보지 않음."""
    shutil.rmtree(mac_b.mnt + "/usadata7")
    video = mac_b.mnt + "/usadata7/Show/S1/job/a.mov"
    gone, detail = video_list.check_gone(video, enoent(video))
    assert gone is False
    assert "자동 연결" in detail and mac_b.mnt in detail


def test_deleted_folders_on_live_mapped_share_are_gone(mac_b):
    mnt = mac_b.mnt
    for path in (mnt + FL_JOB + "/scene-Z007/frames/FL_904_Z007_TK1.mov",  # 지워진 scene 폴더
                 mnt + "/usadata2/Titmouse/FLORIDA/FL_Season01/FL_999",  # 지워진 job 폴더
                 mnt + FL_JOB + "/scene-A001/frames/FL_904_A001_TK2.mov",  # 지워진 파일
                 mnt + "/usadata2/Disney/KOTH"):  # 공유 바로 아래가 지워짐 (공유 맨 위에 다른 폴더가 있음)
        assert video_list.check_gone(path, enoent(path)) == (True, ""), path
