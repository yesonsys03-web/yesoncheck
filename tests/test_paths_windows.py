"""실제 Windows SMB 공유로 경로 변환 확인 (CI windows-build가 공유를 만들고 환경 변수를 줌)."""

import os
import sys

import pytest

from yesoncheck import paths
from yesoncheck.paths import PathMap, PathMapError

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용 (CI windows-build에서 실행)")


@pytest.fixture
def share():
    """CI 시험 공유. Windows에서 환경 변수가 없으면 건너뛰지 않고 실패한다."""
    missing = [k for k in ("YC_TEST_DRIVE", "YC_TEST_UNC", "YC_TEST_SHARE_ROOT") if not os.environ.get(k)]
    if missing:
        pytest.fail(f"CI 시험 공유 환경 변수가 없습니다: {missing} (ci/setup_test_share.ps1 참고)")
    paths._cached_remote_name.cache_clear()
    return os.environ["YC_TEST_DRIVE"], os.environ["YC_TEST_UNC"], os.environ["YC_TEST_SHARE_ROOT"]


def test_wnet_resolves_mapped_drive(share):
    drive, unc, _root = share
    assert paths._remote_name_of_drive(drive).casefold() == unc.casefold()


def test_local_drive_is_not_network(share):
    assert paths._remote_name_of_drive("C:") is None
    with pytest.raises(PathMapError, match="네트워크 드라이브가 아닙니다"):
        paths.drive_to_unc("C:\\Windows")


def test_korean_folder_round_trip(share):
    drive, unc, root = share
    folder = os.path.join(root, "작품_왕복", "시즌1")
    os.makedirs(folder, exist_ok=True)
    path_map = PathMap.from_dict({"version": 1, "shares": [{"mac": "/Volumes/yc_test", "windows": [unc]}]}, "ci")
    paths.activate(path_map)
    try:
        mac = path_map.windows_to_mac(paths.drive_to_unc(f"{drive}\\작품_왕복\\시즌1"))
        assert mac == "/Volumes/yc_test/작품_왕복/시즌1"
        native = paths.to_native(mac)
        assert native == f"{unc}\\작품_왕복\\시즌1"
        assert os.path.isdir(native)
        assert os.listdir(os.path.dirname(native)) == ["시즌1"]
    finally:
        paths.activate(None)


def test_path_key_same_for_drive_and_unc(share, monkeypatch):
    drive, unc, root = share
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    assert paths.path_key(f"{drive}/작품_왕복/A.mov") == paths.path_key(f"{unc}\\작품_왕복\\a.MOV")
    assert paths.thumbnail_key(f"{drive}\\x.mov") == paths.thumbnail_key(f"{unc}\\X.mov")


def test_auto_connect_on_real_share(share):
    """실제로 연결된 시험 드라이브로 공유 찾기·설정 폴더 찾기·변환표 짝 찾기."""
    import uuid

    from yesoncheck import path_map_setup

    drive, unc, root = share
    shares, problems = path_map_setup.connected_shares()
    mine = [s for s in shares if paths.unc_key(s.unc) == paths.unc_key(unc)]
    assert mine and drive.upper() in mine[0].drives, (shares, problems)

    sub = "자동연결_" + uuid.uuid4().hex[:6]
    os.makedirs(os.path.join(root, sub, ".yesoncheck"))
    with open(os.path.join(root, sub, ".yesoncheck", "work_paths.json"), "w", encoding="utf-8") as fh:
        fh.write("{}")
    os.makedirs(os.path.join(root, sub, "작품"))

    found = path_map_setup.find_config_dirs(mine, mac_config_dir=f"/USA_DB/{sub}/.yesoncheck")
    assert [paths.unc_key(f) for f in found] == [paths.unc_key(f"{unc}\\{sub}\\.yesoncheck")]

    proposal = path_map_setup.propose_mapping({"W": f"/Volumes/yc_test/{sub}/작품"}, mine)
    assert [(p.mac_prefix, paths.unc_key(p.candidates[0].unc)) for p in proposal.pairs] == [
        ("/Volumes/yc_test", paths.unc_key(unc))
    ]


def test_local_link_to_share_is_found(share, tmp_path):
    """시스템 드라이브의 Harmony용 링크(C:\\USA_DB → \\\\서버\\USA_DB)처럼 UNC를 가리키는 디렉터리 링크를 공유로 찾음."""
    import uuid

    from yesoncheck import path_map_setup

    _drive, unc, root = share
    sub = "link_target_" + uuid.uuid4().hex[:6]
    os.makedirs(os.path.join(root, sub))
    target = f"{unc}\\{sub}"
    links = tmp_path / "root"
    links.mkdir()
    (links / "plain").mkdir()  # 링크가 아닌 폴더는 건너뜀
    link = links / "USA_DB"
    try:
        os.symlink(target, str(link), target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:  # ERROR_PRIVILEGE_NOT_HELD (정션은 UNC를 가리킬 수 없어 대신 못 씀)
            pytest.skip(f"이 러너에서는 심볼릭 링크를 만들 권한이 없습니다: {exc}")
        raise
    shares, problems = path_map_setup.local_link_shares(root=str(links))
    assert problems == []
    assert [(paths.unc_key(s.unc), s.drives) for s in shares] == [(paths.unc_key(target), [str(link)])]
