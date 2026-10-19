"""yesoncheck/update_install.py 시험: 받기(다운로드+sha256 검사)·Mac dmg 준비·업데이트 기록 (Qt 없음).

NAS는 그냥 파일 복사를 흉내 내고(tmp_path), GitHub는 http_server(conftest)로 127.0.0.1 임의 포트에 흉내 낸다.
Mac 전용(hdiutil·xattr) 시험은 darwin이 아니면 건너뛴다.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests

from yesoncheck import build_info, update_install
from yesoncheck.update_install import (
    NEEDED_BYTES,
    Cancelled,
    Pending,
    UpdateError,
    check_free_space,
    clear_pending,
    download,
    log,
    log_path,
    log_tail_since,
    ok_marker_path,
    read_pending,
    refuse_reason_mac,
    running_app_location,
    stage_mac,
    startup_result,
    state_dir,
    timestamp,
    write_ok_marker,
    write_pending,
)
from yesoncheck.updates import FileEntry

# ---- 시험 도우미 (이 시험 모듈 안에만 둠) ----


def make_file(path, size):
    """size 바이트짜리 시험 파일 (내용은 반복되는 숫자 — 다를 필요 없이 매번 같게 만들 수만 있으면 됨)."""
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = (b"0123456789" * (size // 10 + 1))[:size]
    with open(path, "wb") as fh:
        fh.write(data)
    return Path(path)


def entry_for(path):
    """path의 실제 크기·sha256으로 FileEntry를 만듦 (다운로드 검사가 통과하도록)."""
    data = open(path, "rb").read()
    return FileEntry(name=os.path.basename(str(path)), size=len(data), sha256=hashlib.sha256(data).hexdigest())


# ---- Step 1: 브리핑의 시험 (그대로) ----


def test_download_nas_verifies_and_reports_progress(tmp_path):
    src = make_file(tmp_path / "nas" / "YesonCheck_Setup_1.1.1.exe", 3 * 1024 * 1024 + 5)
    seen = []
    out = download(str(src), entry_for(src), str(tmp_path / "dl"), lambda d, t: seen.append((d, t)), lambda: False)
    assert open(out, "rb").read() == src.read_bytes() and seen[-1] == (src.stat().st_size, src.stat().st_size)


def test_download_sha_mismatch_removes_part(tmp_path):
    src = make_file(tmp_path / "a.exe", 10)
    with pytest.raises(UpdateError, match="sha256"):
        download(str(src), FileEntry("a.exe", 10, "0" * 64), str(tmp_path / "dl"), lambda d, t: None, lambda: False)
    assert not list((tmp_path / "dl").iterdir())


def test_download_cancel_removes_part(tmp_path):
    src = make_file(tmp_path / "a.exe", 5 * 1024 * 1024)
    with pytest.raises(Cancelled):
        download(str(src), entry_for(src), str(tmp_path / "dl"), lambda d, t: None, lambda: True)
    assert not list((tmp_path / "dl").iterdir())


def test_download_http(http_server, tmp_path):
    src = make_file(tmp_path / "a.exe", 2 * 1024 * 1024 + 7)
    served = http_server.serve_file("/a.exe", src)
    seen = []
    out = download(
        http_server.url + "/a.exe", entry_for(served), str(tmp_path / "dl"),
        lambda d, t: seen.append((d, t)), lambda: False,
    )
    assert open(out, "rb").read() == src.read_bytes()
    assert seen[-1] == (src.stat().st_size, src.stat().st_size)


def test_download_http_404_leaves_no_part(http_server, tmp_path):
    """등록 안 된 경로(404)는 requests가 HTTPError를 올리고, download()는 그걸 그대로 다시 올리며(삼키지
    않음) .part를 남기지 않음."""
    with pytest.raises(requests.exceptions.HTTPError):
        download(
            http_server.url + "/missing.exe", FileEntry("missing.exe", 10, "0" * 64),
            str(tmp_path / "dl"), lambda d, t: None, lambda: False,
        )
    assert not list((tmp_path / "dl").iterdir())


def test_download_nas_stops_early_when_source_larger_than_expected(tmp_path):
    """소스가 entry.size보다 훨씬 크면 끝까지 받지 않고 바로 멈춤 (디스크·시간 낭비 방지)."""
    src = make_file(tmp_path / "big.exe", 5 * 1024 * 1024)
    entry = FileEntry("big.exe", 1000, hashlib.sha256(b"x").hexdigest())  # 실제보다 훨씬 작은 크기
    with pytest.raises(UpdateError, match="많습니다"):
        download(str(src), entry, str(tmp_path / "dl"), lambda d, t: None, lambda: False)
    assert not list((tmp_path / "dl").iterdir())


def test_refuse_reason_mac():
    assert refuse_reason_mac("/private/var/folders/x/T/AppTranslocation/ABC/d/YesonCheck_Autocut_Intel.app")
    assert refuse_reason_mac("/Volumes/YesonCheck_Autocut_Intel/YesonCheck_Autocut_Intel.app")
    assert refuse_reason_mac("/Applications/YesonCheck_Autocut_Intel.app") is None


def test_startup_result_paths(tmp_state_dir):
    write_pending(Pending("1.1.1", "1.1.0", "windows", "2026-10-20T10:00:00"))
    assert startup_result("1.1.2") is None and read_pending()  # 다른 버전: 그대로 둠
    assert startup_result("1.1.1")[0] == "ok" and read_pending() is None
    assert json.load(open(ok_marker_path()))["version"] == "1.1.1"
    write_pending(Pending("1.1.1", "1.1.0", "windows", "2026-10-20T10:00:00"))
    assert startup_result("1.1.0")[0] == "failed" and read_pending() is None


@pytest.mark.skipif(sys.platform != "darwin", reason="Mac 다운로드 격리 표시")
def test_downloaded_file_has_no_quarantine(http_server, tmp_path):  # 설계 5-4 "만드는 사람이 확인"
    served = http_server.serve_file("/a.dmg", make_file(tmp_path / "a.dmg", 1000))
    out = download(http_server.url + "/a.dmg", entry_for(served), str(tmp_path / "dl"), lambda d, t: None, lambda: False)
    assert subprocess.run(["xattr", "-p", "com.apple.quarantine", out], capture_output=True).returncode != 0


def test_check_free_space_raises(tmp_path):
    with pytest.raises(UpdateError, match="여유 공간"):
        check_free_space(str(tmp_path), 10 ** 18)


def _make_fake_app(base_dir, app_name="YesonCheck_Autocut_Intel.app", version="1.2.3"):
    """build_info.json이 든 작은 가짜 .app (hdiutil create의 소스로 씀)."""
    app_dir = os.path.join(base_dir, app_name)
    os.makedirs(os.path.join(app_dir, "Contents", "MacOS"))
    os.makedirs(os.path.join(app_dir, "Contents", "Resources"))
    with open(os.path.join(app_dir, "Contents", "MacOS", "YesonCheck_Autocut"), "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\necho 시험용 가짜 실행 파일\n")
    info = {
        "version": version, "commit": "d" * 40,
        "built": "2026-10-20T10:00:00+09:00", "platform_key": "mac-arm64",
    }
    with open(os.path.join(app_dir, "Contents", "Resources", build_info.FILE_NAME), "w", encoding="utf-8") as fh:
        json.dump(info, fh)
    return app_dir


def _make_dmg(tmp_path, src_parent, dmg_name="test.dmg"):
    dmg_path = os.path.join(str(tmp_path), dmg_name)
    subprocess.run(
        ["hdiutil", "create", "-volname", "YesonTest", "-srcfolder", src_parent, "-ov", "-format", "UDZO", dmg_path],
        check=True, capture_output=True, text=True,
    )
    return dmg_path


def _dmg_is_mounted(dmg_path):
    info = subprocess.run(["hdiutil", "info"], capture_output=True, text=True, check=True).stdout
    return os.path.realpath(dmg_path) in info or dmg_path in info


@pytest.mark.skipif(sys.platform != "darwin", reason="hdiutil")
def test_stage_mac_from_dmg(tmp_path):  # 작은 가짜 .app(build_info.json 포함)으로 hdiutil create → stage
    src_parent = os.path.join(str(tmp_path), "src")
    os.makedirs(src_parent)
    _make_fake_app(src_parent, version="1.2.3")
    dmg_path = _make_dmg(tmp_path, src_parent)

    install_dir = os.path.join(str(tmp_path), "install_dir")
    os.makedirs(install_dir)
    app_path = os.path.join(install_dir, "YesonCheck_Autocut_Intel.app")

    # 버전이 맞으면: 경로가 앱 옆 숨김 이름, dmg는 떼어져 있음
    staged = stage_mac(dmg_path, app_path, "1.2.3")
    assert staged == os.path.join(install_dir, ".YesonCheck_Autocut_Intel.app.update-1.2.3")
    assert os.path.isfile(os.path.join(staged, "Contents", "MacOS", "YesonCheck_Autocut"))
    assert not _dmg_is_mounted(dmg_path)

    # 버전이 다르면: UpdateError, 준비 폴더가 남지 않음, dmg는 떼어져 있음
    with pytest.raises(UpdateError):
        stage_mac(dmg_path, app_path, "9.9.9")
    mismatched = os.path.join(install_dir, ".YesonCheck_Autocut_Intel.app.update-9.9.9")
    assert not os.path.exists(mismatched)
    assert not _dmg_is_mounted(dmg_path)


@pytest.mark.skipif(sys.platform != "darwin", reason="hdiutil")
def test_stage_mac_falls_back_to_state_dir_when_parent_not_writable(tmp_path, tmp_state_dir, monkeypatch):
    src_parent = os.path.join(str(tmp_path), "src")
    os.makedirs(src_parent)
    _make_fake_app(src_parent, version="2.0.0")
    dmg_path = _make_dmg(tmp_path, src_parent, dmg_name="test2.dmg")

    install_dir = os.path.join(str(tmp_path), "readonly_install")
    os.makedirs(install_dir)
    app_path = os.path.join(install_dir, "YesonCheck_Autocut_Intel.app")

    monkeypatch.setattr(update_install.os, "access", lambda path, mode: False)
    staged = stage_mac(dmg_path, app_path, "2.0.0")
    assert staged == os.path.join(tmp_state_dir, ".YesonCheck_Autocut_Intel.app.update-2.0.0")
    assert os.path.isfile(os.path.join(staged, "Contents", "MacOS", "YesonCheck_Autocut"))


def test_verify_staged_app_appends_cleanup_failure_without_masking_main_error(tmp_path, monkeypatch):
    """_verify_staged_app: 검사 실패 → 지우려다 실패한 것이 있으면, 그 실패를 삼키지 않고 원래(검사 실패)
    메시지에 덧붙여 올림 (Mac이 아니어도 플랫폼과 상관없는 순수 로직이라 hdiutil 없이 시험)."""
    dest_path = str(tmp_path / "staged.app")
    os.makedirs(dest_path)  # 실행 파일이 없어 검사가 실패하도록

    def fake_rmtree(path, onerror=None):
        if onerror is not None:
            onerror(os.remove, path, (OSError, OSError("시험용 지우기 실패"), None))

    monkeypatch.setattr(update_install.shutil, "rmtree", fake_rmtree)
    with pytest.raises(UpdateError) as exc_info:
        update_install._verify_staged_app(dest_path, "1.0.0")
    message = str(exc_info.value)
    assert "실행 파일이 없습니다" in message  # 원래 오류는 그대로
    assert "지우지 못함" in message and "시험용 지우기 실패" in message  # 덧붙은 정리 실패


def test_stage_mac_combines_copy_and_detach_errors(tmp_path, monkeypatch):
    """복사도 떼어내기도 둘 다 실패하면 — 흔치 않지만 — 어느 쪽도 가려지지 않고 둘 다 사용자에게 보임.
    hdiutil 없이 _hdiutil_attach·_copy_app_from_mount·_hdiutil_detach를 모두 흉내 내 플랫폼과 상관없이 시험."""
    def fake_copy(mp, dest_path):
        raise UpdateError("복사 실패(시험)")

    def fake_detach(mp):
        raise UpdateError("떼어내기 실패(시험)")

    mount_point = str(tmp_path / "mount")
    os.makedirs(mount_point)
    monkeypatch.setattr(update_install.tempfile, "mkdtemp", lambda prefix=None: mount_point)
    monkeypatch.setattr(update_install, "_hdiutil_attach", lambda dmg_path, mp: None)
    monkeypatch.setattr(update_install, "_copy_app_from_mount", fake_copy)
    monkeypatch.setattr(update_install, "_hdiutil_detach", fake_detach)

    install_dir = str(tmp_path / "install_dir")
    os.makedirs(install_dir)
    app_path = os.path.join(install_dir, "YesonCheck_Autocut_Intel.app")

    with pytest.raises(UpdateError) as exc_info:
        stage_mac("fake.dmg", app_path, "1.0.0")
    message = str(exc_info.value)
    assert "복사 실패(시험)" in message and "떼어내기 실패(시험)" in message

    assert os.path.isdir(mount_point)  # 떼어내기가 (흉내로) 실패했으니 안 지워짐
    os.rmdir(mount_point)  # 시험 뒤 정리


# ---- 추가 시험: state_dir / log_path ----


def test_state_dir_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(update_install.paths, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    d = state_dir()
    assert d == os.path.join(str(tmp_path), "YesonCheck", "updates")
    assert os.path.isdir(d)


def test_state_dir_mac(monkeypatch, tmp_path):
    monkeypatch.setattr(update_install.paths, "IS_WINDOWS", False)
    monkeypatch.setenv("HOME", str(tmp_path))
    # ntpath.expanduser(실제 Windows에서 돌 때)는 HOME을 보지 않고 USERPROFILE을 먼저 봄 — 이 시험이
    # Mac 쪽 분기를 흉내 내느라 실제 사용자 폴더를 건드리지 않도록 둘 다 돌려 둠
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    d = state_dir()
    assert d == os.path.join(str(tmp_path), "Library", "Caches", "YesonCheck", "updates")
    assert os.path.isdir(d)


def test_log_path_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(update_install.paths, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    p = log_path()
    assert p == os.path.join(str(tmp_path), "YesonCheck", "logs", "update.log")
    assert os.path.isdir(os.path.dirname(p))


def test_log_path_mac(monkeypatch, tmp_path):
    monkeypatch.setattr(update_install.paths, "IS_WINDOWS", False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # test_state_dir_mac과 같은 이유
    p = log_path()
    assert p == os.path.join(str(tmp_path), "Library", "Logs", "YesonCheck", "update.log")
    assert os.path.isdir(os.path.dirname(p))


# ---- 추가 시험: log / log_tail_since ----


def test_log_appends_with_timestamp_and_prints(tmp_state_dir, capsys):
    log("시험 줄 1")
    log("시험 줄 2")
    with open(log_path(), encoding="utf-8") as fh:
        lines = fh.readlines()
    assert len(lines) == 2
    assert lines[0].endswith("시험 줄 1\n") and lines[1].endswith("시험 줄 2\n")
    ts = lines[0].split(" ", 1)[0]
    assert len(ts) == 19 and ts[4] == "-" and ts[13] == ":"  # ISO 8601 (초 단위)
    out = capsys.readouterr().out
    assert "시험 줄 1" in out and "시험 줄 2" in out


def test_log_tail_since_missing_file_is_empty(tmp_state_dir):
    assert log_tail_since("2026-10-19T10:00:00") == ""


def test_log_tail_since_filters_and_limits(tmp_state_dir):
    path = log_path()
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("2026-10-19T09:00:00 이전 줄\n")
        fh.write("2026-10-19T10:00:00 기준 줄\n")
        fh.write("2026-10-19T10:00:01 이후 줄1\n")
        fh.write("2026-10-19T10:00:02 이후 줄2\n")

    tail = log_tail_since("2026-10-19T10:00:00", max_lines=80)
    assert "이전 줄" not in tail
    assert "기준 줄" in tail and "이후 줄1" in tail and "이후 줄2" in tail

    tail2 = log_tail_since("2026-10-19T10:00:00", max_lines=2)
    assert "기준 줄" not in tail2 and "이후 줄1" in tail2 and "이후 줄2" in tail2


def test_timestamp_matches_log_format(tmp_state_dir):
    """timestamp()는 log()가 줄 앞에 쓰는 것과 같은 형식 — Task 6이 Pending.started에 쓸 값."""
    ts = timestamp()
    assert len(ts) == 19 and ts[4] == "-" and ts[13] == ":"
    log("시험 줄")
    with open(log_path(), encoding="utf-8") as fh:
        logged_ts = fh.readline().split(" ", 1)[0]
    assert len(logged_ts) == len(ts)


def test_log_tail_since_keeps_traceback_lines_and_drops_stale_run(tmp_state_dir):
    """실패 로그(트레이스백)는 "업데이트 실패" 창에 통째로 보여야 함 — 시각 없는 줄(들여쓴 트레이스백 줄)도
    버려지지 않고, 이전 실행의 오래된 트레이스백은 포함되지 않아야 함."""
    with open(log_path(), "a", encoding="utf-8") as fh:
        fh.write("2026-10-19T09:00:00 이전 실행 시작\n")
        fh.write("2026-10-19T09:00:01 오류\n")
        fh.write("Traceback (most recent call last):\n")
        fh.write('  File "x.py", line 1, in <module>\n')
        fh.write('    raise RuntimeError("예전 오류")\n')
        fh.write("RuntimeError: 예전 오류\n")
        fh.write("2026-10-19T10:00:00 기준 실행 시작\n")
        fh.write("2026-10-19T10:00:01 오류\n")
        fh.write("Traceback (most recent call last):\n")
        fh.write('  File "y.py", line 2, in <module>\n')
        fh.write('    raise RuntimeError("새 오류")\n')
        fh.write("RuntimeError: 새 오류\n")

    tail = log_tail_since("2026-10-19T10:00:00")
    assert "이전 실행" not in tail and "예전 오류" not in tail
    assert "기준 실행 시작" in tail
    assert 'File "y.py"' in tail and "새 오류" in tail
    assert tail.count("\n") == 6  # 시작·오류·Traceback·File·raise·RuntimeError (들여쓴 줄도 모두 남음)


def test_log_tail_since_truncates_started_to_second_precision(tmp_state_dir):
    """started에 초보다 더 정밀한 값(마이크로초)이 들어와도 같은 초의 줄을 빼먹지 않음."""
    with open(log_path(), "a", encoding="utf-8") as fh:
        fh.write("2026-10-19T10:00:00 같은 초\n")
    tail = log_tail_since("2026-10-19T10:00:00.123456")
    assert "같은 초" in tail


# ---- 추가 시험: Pending / ok 표시 ----


def test_pending_roundtrip_and_clear(tmp_state_dir):
    assert read_pending() is None
    p = Pending("1.1.1", "1.1.0", "windows", "2026-10-19T10:00:00")
    write_pending(p)
    assert read_pending() == p
    clear_pending()
    assert read_pending() is None
    clear_pending()  # 두 번째도 조용히 (이미 없음)


def test_read_pending_corrupted_raises(tmp_state_dir):
    with open(os.path.join(tmp_state_dir, "pending_update.json"), "w", encoding="utf-8") as fh:
        fh.write("{")
    with pytest.raises(UpdateError):
        read_pending()


def test_write_ok_marker(tmp_state_dir):
    write_ok_marker("1.2.3")
    assert ok_marker_path() == os.path.join(tmp_state_dir, "update_ok.json")
    with open(ok_marker_path(), encoding="utf-8") as fh:
        assert json.load(fh) == {"version": "1.2.3"}


# ---- 추가 시험: NEEDED_BYTES ----


def test_needed_bytes_has_all_platform_keys():
    assert NEEDED_BYTES == {
        "windows": 1_500_000_000, "mac-x86_64": 3_000_000_000, "mac-arm64": 3_000_000_000,
    }


# ---- 추가 시험: running_app_location ----


def test_running_app_location_source_run_raises(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    with pytest.raises(UpdateError):
        running_app_location()


def test_running_app_location_windows(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(update_install.paths, "IS_WINDOWS", True)
    monkeypatch.setattr(sys, "executable", "/fake/install/YesonCheck.exe", raising=False)
    assert running_app_location() == "/fake/install"


def test_running_app_location_mac(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(update_install.paths, "IS_WINDOWS", False)
    monkeypatch.setattr(
        sys, "executable", "/Applications/YesonCheck.app/Contents/MacOS/YesonCheck_Autocut", raising=False
    )
    assert running_app_location() == "/Applications/YesonCheck.app"


def test_refuse_reason_mac_mentions_applications_folder():
    msg = refuse_reason_mac("/Volumes/YesonCheck_Autocut_Intel/YesonCheck_Autocut_Intel.app")
    assert "응용 프로그램 폴더" in msg


# ---- 도우미 출력 (update_helper_console.txt): 기록에 없는 줄 ----


def test_helper_console_extra_without_file_is_empty(tmp_state_dir):
    assert update_install.helper_console_extra() == ""


def test_helper_console_extra_keeps_only_lines_missing_from_log(tmp_state_dir):
    """도우미는 기록의 줄을 stdout에도 씀 → 그 줄은 빼고, 기록을 쓰기 전의 실패(PowerShell 오류 등)만 남김."""
    log("도우미: 시작: 대상 버전 1.1.1")
    with open(log_path(), encoding="utf-8") as fh:
        logged = fh.read().splitlines()[0]
    error = "New-Object : The 'New-Object' command was found in the module 'Microsoft.PowerShell.Utility', but the module could not be loaded."
    with open(update_install.helper_console_path(), "wb") as fh:
        fh.write(f"{logged}\r\n\r\n{error}\r\n    + FullyQualifiedErrorId : CouldNotAutoloadMatchingModule\r\n".encode("utf-8"))
    extra = update_install.helper_console_extra()
    assert extra == f"{error}\n    + FullyQualifiedErrorId : CouldNotAutoloadMatchingModule\n"
    # 모두 기록에 있는 줄이면 빈 글자 (성공한 도우미의 출력)
    with open(update_install.helper_console_path(), "wb") as fh:
        fh.write(f"{logged}\n".encode("utf-8"))
    assert update_install.helper_console_extra() == ""


def test_helper_console_extra_reads_non_utf8_with_this_computers_encoding(tmp_state_dir, monkeypatch):
    """Windows PowerShell 5.1이 파일로 보낸 출력은 이 컴퓨터의 코드 페이지 — UTF-8로 읽히지 않으면 그 인코딩으로, 어떻게
    읽었는지 적어서."""
    monkeypatch.setattr(update_install.locale, "getpreferredencoding", lambda do_setlocale=True: "cp949")
    with open(update_install.helper_console_path(), "wb") as fh:
        fh.write("모듈을 불러오지 못했습니다\r\n".encode("cp949"))
    assert update_install.helper_console_extra() == "(UTF-8이 아니어서 cp949로 읽음)\n모듈을 불러오지 못했습니다\n"
