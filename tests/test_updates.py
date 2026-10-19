"""yesoncheck/updates.py 시험: NAS·GitHub의 latest.json을 읽고 더 새 버전을 고르는 핵심 (Qt 없음).

GitHub는 시험 안에서 http_server(conftest)로 127.0.0.1 임의 포트에 흉내 낸다. REST API는 쓰지 않는다.
"""

import json
import os

import pytest
import requests

from yesoncheck import updates
from yesoncheck.updates import (
    CheckResult,
    FileEntry,
    Manifest,
    ManifestError,
    Offer,
    SourceResult,
    Version,
    asset_location,
    check,
    choose_offer,
    github_base_url,
    parse_manifest,
    read_github,
    read_nas,
)

# ---- 시험 도우미 (브리핑의 컨트롤러 판단: 이 시험 모듈 안에만 둠) ----


def manifest_dict(version="1.1.0", commit="0" * 7, released="2026-10-19", notes="", files=None):
    """latest.json 하나를 딱 기본값으로 채운 dict. platform_key 기본은 "windows" 하나만 (다른 플랫폼은
    없는 채로 둬서 '이 컴퓨터용 항목 없음' 시험이 쉽게 되게)."""
    if files is None:
        files = {"windows": {"name": f"YesonCheck_Setup_{version}.exe", "size": 123, "sha256": "a" * 64}}
    return {"version": version, "commit": commit, "released": released, "notes": notes, "files": files}


def manifest_bytes(**kwargs):
    return json.dumps(manifest_dict(**kwargs), ensure_ascii=False).encode("utf-8")


def manifest(**kwargs):
    return parse_manifest(manifest_bytes(**kwargs))


def write_manifest(updates_dir, **kwargs):
    """updates_dir(NAS의 updates 폴더)을 만들고 그 안에 latest.json을 씀."""
    updates_dir = str(updates_dir)
    os.makedirs(updates_dir, exist_ok=True)
    with open(os.path.join(updates_dir, updates.MANIFEST_NAME), "wb") as fh:
        fh.write(manifest_bytes(**kwargs))


def nas_result(version, location="/fake/updates", **kwargs):
    return SourceResult("NAS", location, manifest(version=version, **kwargs), None, None)


def gh_result(version, base="https://example.test/releases", **kwargs):
    return SourceResult("GitHub", base, manifest(version=version, **kwargs), None, None)


def gh_result_with(m, base):
    return SourceResult("GitHub", base, m, None, None)


def error_result(source, message="시험용 오류"):
    return SourceResult(source, "", None, None, message)


# ---- Step 1: 브리핑의 시험 (그대로) ----


def test_version_compare_ignores_build():
    assert Version.parse("1.1.10") > Version.parse("1.1.9")
    assert Version.parse("1.1.0+0f4d3d7") == Version.parse("1.1.0")
    assert not Version.parse("1.1.0+0f4d3d7.dirty") < Version.parse("1.1.0")
    for bad in ["1.1", "v1.1.0", "1.1.0-rc1", "", "1.1.0+XYZ"]:
        with pytest.raises(ValueError):
            Version.parse(bad)


def test_parse_manifest_errors():
    with pytest.raises(ManifestError, match="sha256"):
        parse_manifest(manifest_bytes(files={"windows": {"name": "a.exe", "size": 1, "sha256": "짧음"}}))
    with pytest.raises(ManifestError):
        parse_manifest(b"{")


def test_read_nas_states(tmp_path):
    assert read_nas(None, "windows").expected_problem  # 공유 설정 폴더를 모름
    assert read_nas(str(tmp_path), "windows").expected_problem  # updates/ 없음 = 아직 배포 없음
    write_manifest(tmp_path / "updates", version="1.1.1")
    r = read_nas(str(tmp_path), "windows")
    assert r.manifest.version == Version.parse("1.1.1") and r.error is None
    assert read_nas(str(tmp_path), "mac-arm64").error  # 이 컴퓨터용 항목 없음 = 오류
    (tmp_path / "updates" / "latest.json").write_bytes(b"{")
    assert read_nas(str(tmp_path), "windows").error  # 형식 오류 = 오류


def test_read_github_unreachable_is_expected():
    r = read_github("http://127.0.0.1:9", "windows", timeout_s=2)  # 닫힌 포트
    assert r.expected_problem and r.error is None and r.manifest is None


def test_read_github_states(http_server):
    assert read_github(http_server.url, "windows").expected_problem  # 404 = 아직 배포 없음
    http_server.serve("/latest/download/latest.json", manifest_bytes(version="1.1.2"))
    assert read_github(http_server.url, "windows").manifest.version == Version.parse("1.1.2")
    http_server.serve("/latest/download/latest.json", b"oops", status=500)
    assert read_github(http_server.url, "windows").error  # 그 밖의 상태 = 오류
    assert read_github(None, "windows").expected_problem  # off


def test_choose_offer_rules():
    nas, gh = nas_result("1.1.1"), gh_result("1.1.1")
    assert choose_offer(Version.parse("1.1.0"), "windows", [gh, nas]).result.source == "NAS"  # 같으면 NAS
    assert choose_offer(
        Version.parse("1.1.0"), "windows", [nas_result("1.1.1"), gh_result("1.1.2")]
    ).manifest.version == Version.parse("1.1.2")
    assert choose_offer(Version.parse("1.1.1+abc1234"), "windows", [nas, gh]) is None
    assert choose_offer(Version.parse("1.1.0"), "windows", [error_result("NAS"), gh]).result.source == "GitHub"


def test_asset_location():
    m = manifest(version="1.1.1")
    assert asset_location(gh_result_with(m, base="https://example.test/r"), m, m.files["windows"]) == (
        "https://example.test/r/download/v1.1.1/YesonCheck_Setup_1.1.1.exe"
    )


# ---- 추가 시험: Version ----


def test_version_str_roundtrip():
    assert str(Version.parse("1.1.0+0f4d3d7.dirty")) == "1.1.0+0f4d3d7.dirty"
    assert str(Version.parse("1.1.0")) == "1.1.0"


def test_version_not_comparable_with_other_types():
    assert Version.parse("1.1.0") != "1.1.0"
    with pytest.raises(TypeError):
        Version.parse("1.1.0") < "1.1.0"


# ---- 추가 시험: parse_manifest ----


def test_parse_manifest_missing_field():
    data = manifest_dict()
    del data["commit"]
    with pytest.raises(ManifestError, match="commit"):
        parse_manifest(json.dumps(data).encode("utf-8"))


def test_parse_manifest_not_object():
    with pytest.raises(ManifestError, match="객체"):
        parse_manifest(b"[1, 2, 3]")


def test_parse_manifest_bad_version():
    data = manifest_dict(version="v1.1.0")
    with pytest.raises(ManifestError, match="version"):
        parse_manifest(json.dumps(data).encode("utf-8"))


def test_parse_manifest_bad_size():
    with pytest.raises(ManifestError, match="size"):
        parse_manifest(manifest_bytes(files={"windows": {"name": "a.exe", "size": 0, "sha256": "a" * 64}}))
    with pytest.raises(ManifestError, match="size"):
        parse_manifest(manifest_bytes(files={"windows": {"name": "a.exe", "size": -1, "sha256": "a" * 64}}))
    with pytest.raises(ManifestError, match="size"):
        parse_manifest(manifest_bytes(files={"windows": {"name": "a.exe", "size": "1", "sha256": "a" * 64}}))


def test_parse_manifest_files_not_object():
    data = manifest_dict()
    data["files"] = ["windows"]
    with pytest.raises(ManifestError, match="files"):
        parse_manifest(json.dumps(data).encode("utf-8"))


def test_manifest_is_frozen():
    m = manifest(version="1.1.1")
    assert isinstance(m, Manifest)
    with pytest.raises(Exception):
        m.version = Version.parse("2.0.0")


# ---- 추가 시험: SourceResult 불변식 ----


def test_source_result_requires_exactly_one_value():
    m = manifest(version="1.1.1")
    with pytest.raises(ValueError):
        SourceResult("NAS", "/x", None, None, None)  # 셋 다 없음
    with pytest.raises(ValueError):
        SourceResult("NAS", "/x", m, "문제", None)  # 둘 다 있음
    with pytest.raises(ValueError):
        SourceResult("NAS", "/x", m, None, "오류")


def test_source_result_rejects_unknown_source():
    with pytest.raises(ValueError):
        SourceResult("FTP", "/x", None, "문제", None)


# ---- 추가 시험: github_base_url ----


def test_github_base_url_default(monkeypatch):
    monkeypatch.delenv("YESONCHECK_UPDATE_URL", raising=False)
    assert github_base_url() == updates.GITHUB_RELEASES_URL


def test_github_base_url_off(monkeypatch):
    monkeypatch.setenv("YESONCHECK_UPDATE_URL", "off")
    assert github_base_url() is None


def test_github_base_url_override(monkeypatch, http_server):
    monkeypatch.setenv("YESONCHECK_UPDATE_URL", http_server.url)
    assert github_base_url() == http_server.url


# ---- 추가 시험: read_nas의 그 밖의 OSError ----


def test_read_nas_other_oserror_is_error(tmp_path):
    updates_dir = tmp_path / "updates"
    updates_dir.mkdir()
    # latest.json 자리에 폴더를 둬서 열 때 OSError(FileNotFoundError 아님)가 나게 함
    (updates_dir / updates.MANIFEST_NAME).mkdir()
    r = read_nas(str(tmp_path), "windows")
    assert r.error and r.manifest is None and r.expected_problem is None


# ---- 추가 시험: read_github의 분류 (requests.get을 흉내) ----


def test_read_github_ssl_error_is_error(monkeypatch):
    def fake_get(url, timeout):
        raise requests.exceptions.SSLError("인증서 문제(시험)")

    monkeypatch.setattr(requests, "get", fake_get)  # read_github가 처음 쓸 때 불러오는 그 모듈
    r = read_github("https://example.test", "windows")
    assert r.error and "SSL" in r.error or "보안" in r.error
    assert r.manifest is None and r.expected_problem is None


def test_read_github_unexpected_exception_has_traceback(monkeypatch):
    def fake_get(url, timeout):
        raise RuntimeError("예상 못 한 문제(시험)")

    monkeypatch.setattr(requests, "get", fake_get)
    r = read_github("https://example.test", "windows")
    assert r.error and "RuntimeError" in r.error and "Traceback" in r.error


# ---- 추가 시험: choose_offer의 플랫폼 항목 없음 ----


def test_choose_offer_ignores_missing_platform_entry():
    nas = nas_result("1.1.1")  # files에는 "windows"만 있음
    assert choose_offer(Version.parse("1.1.0"), "mac-arm64", [nas]) is None


# ---- 추가 시험: asset_location의 NAS 쪽 ----


def test_asset_location_nas():
    m = manifest(version="1.1.1")
    result = nas_result("1.1.1", location=os.path.join("fake", "updates"))
    assert asset_location(result, m, m.files["windows"]) == os.path.join("fake", "updates", "YesonCheck_Setup_1.1.1.exe")


# ---- 추가 시험: check()가 두 소스를 합쳐 더 새 버전을 고름 ----


def test_check_combines_nas_and_github(tmp_path, http_server):
    write_manifest(tmp_path / "updates", version="1.1.1")
    http_server.serve("/latest/download/latest.json", manifest_bytes(version="1.1.2"))
    result = check(Version.parse("1.1.0"), "windows", str(tmp_path), http_server.url)
    assert isinstance(result, CheckResult)
    assert len(result.results) == 2
    assert isinstance(result.offer, Offer)
    assert result.offer.manifest.version == Version.parse("1.1.2")
    assert result.offer.result.source == "GitHub"


def test_check_no_offer_when_up_to_date(tmp_path):
    write_manifest(tmp_path / "updates", version="1.1.1")
    result = check(Version.parse("1.1.1"), "windows", str(tmp_path), None)
    assert result.offer is None
    assert any(r.source == "GitHub" and r.expected_problem for r in result.results)


def test_file_entry_fields():
    entry = FileEntry(name="a.exe", size=1, sha256="a" * 64)
    assert entry.name == "a.exe" and entry.size == 1 and entry.sha256 == "a" * 64


# ---- 시작이 느려지지 않게: requests는 처음 쓸 때 불러옴 ----


_STARTUP_IMPORTS = r"""
import sys

sys.path.insert(0, sys.argv[1])
import yesoncheck.app
import yesoncheck.main_window
import yesoncheck.update_install
import yesoncheck.updates

print("REQUESTS_LOADED", "requests" in sys.modules)
"""


def test_startup_does_not_import_requests():
    """앱의 시작(main_window → player_update → update_install·updates)에서 requests(약 80 ms, 처음 켤 때 200 ms 넘게)를
    불러오지 않음 — GitHub 확인·URL 받기가 처음 쓸 때 불러옴. pytest 프로세스는 이미 불렀으므로 새 파이썬 프로세스에서."""
    import subprocess
    import sys

    from tests.conftest import ROOT

    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-c", _STARTUP_IMPORTS, ROOT], cwd=ROOT, env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=300)
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "REQUESTS_LOADED False" in result.stdout.splitlines(), result.stdout
