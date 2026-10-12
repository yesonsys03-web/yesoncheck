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
