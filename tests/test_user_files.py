"""yesoncheck/user_files.py 시험: 원자적 JSON 쓰기·읽기·프로세스 사이 잠금·읽고-고치고-쓰기 (Qt 없음).

Windows 전용 갈래(os.replace의 PermissionError 다시 시도, msvcrt 잠금)는 플랫폼·os.replace·msvcrt를 주입해 모든
플랫폼에서 시험한다. 실제 잠금(FileLock)·여러 프로세스 시험은 돌고 있는 플랫폼의 진짜 잠금을 쓴다.
"""

import errno
import json
import multiprocessing
import os
import stat
import sys
import types

import pytest

from yesoncheck import user_files
from yesoncheck.user_files import FileLock, UserFileError, read_json, update_json, write_json_atomic


def _list_dir(folder):
    return sorted(os.listdir(folder))


# ---------- write_json_atomic ----------


def test_write_json_atomic_writes_json_and_makes_folder(tmp_path):
    path = str(tmp_path / "새 폴더" / "data.json")
    write_json_atomic(path, {"이름": ["가", 1]})
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert json.loads(text) == {"이름": ["가", 1]}
    assert "가" in text  # ensure_ascii=False
    assert _list_dir(os.path.dirname(path)) == ["data.json"]


def test_write_json_atomic_indent_default_is_2_and_none_is_compact(tmp_path):
    path = str(tmp_path / "data.json")
    write_json_atomic(path, {"a": 1})
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == '{\n  "a": 1\n}'
    write_json_atomic(path, {"a": 1}, indent=None)
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == '{"a": 1}'


def test_write_json_atomic_keeps_old_file_when_dump_fails(tmp_path, monkeypatch):
    path = str(tmp_path / "data.json")
    write_json_atomic(path, {"old": True})

    def failing_dump(data, fh, **kwargs):
        fh.write('{"half": ')  # 반쯤 쓰다 실패
        raise RuntimeError("dump 중간 실패")

    monkeypatch.setattr(user_files.json, "dump", failing_dump)
    with pytest.raises(RuntimeError, match="dump 중간 실패"):
        write_json_atomic(path, {"new": True})
    monkeypatch.undo()

    assert read_json(path, None) == {"old": True}
    assert _list_dir(tmp_path) == ["data.json"]  # 임시 파일이 남지 않음


def test_write_json_atomic_unserializable_data_keeps_old_file(tmp_path):
    path = str(tmp_path / "data.json")
    write_json_atomic(path, [1])
    with pytest.raises(TypeError):
        write_json_atomic(path, {"x": object()})
    assert read_json(path, None) == [1]
    assert _list_dir(tmp_path) == ["data.json"]


def _fake_replace_failing(times, counter):
    """처음 times번은 PermissionError, 그 뒤는 진짜 os.replace."""

    def replace(src, dst):
        counter.append(1)
        if len(counter) <= times:
            raise PermissionError(errno.EACCES, "다른 프로세스가 열어 두고 있음", dst)
        os.replace(src, dst)

    return replace


def test_write_json_atomic_retries_permission_error_on_windows(tmp_path, monkeypatch):
    path = str(tmp_path / "data.json")
    write_json_atomic(path, {"old": True})
    calls, sleeps = [], []
    monkeypatch.setattr(user_files, "_IS_WINDOWS", True)
    monkeypatch.setattr(user_files, "_replace", _fake_replace_failing(3, calls))
    monkeypatch.setattr(user_files, "_sleep", sleeps.append)

    write_json_atomic(path, {"new": True})

    assert len(calls) == 4
    assert sleeps == [0.1, 0.1, 0.1]
    assert read_json(path, None) == {"new": True}
    assert _list_dir(tmp_path) == ["data.json"]


def test_write_json_atomic_gives_up_after_20_retries_on_windows(tmp_path, monkeypatch):
    path = str(tmp_path / "data.json")
    write_json_atomic(path, {"old": True})
    calls, sleeps = [], []
    monkeypatch.setattr(user_files, "_IS_WINDOWS", True)
    monkeypatch.setattr(user_files, "_replace", _fake_replace_failing(10**6, calls))
    monkeypatch.setattr(user_files, "_sleep", sleeps.append)

    with pytest.raises(PermissionError) as info:  # 감싸지 않고 그대로
        write_json_atomic(path, {"new": True})

    assert info.value.filename == path  # str()은 filename을 repr로 보여 Windows 경로의 \가 두 배가 됨
    assert len(calls) == 21  # 처음 한 번 + 다시 20번
    assert sleeps == [0.1] * 20
    assert read_json(path, None) == {"old": True}
    assert _list_dir(tmp_path) == ["data.json"]


def test_write_json_atomic_does_not_retry_permission_error_off_windows(tmp_path, monkeypatch):
    path = str(tmp_path / "data.json")
    calls, sleeps = [], []
    monkeypatch.setattr(user_files, "_IS_WINDOWS", False)
    monkeypatch.setattr(user_files, "_replace", _fake_replace_failing(10**6, calls))
    monkeypatch.setattr(user_files, "_sleep", sleeps.append)

    with pytest.raises(PermissionError):
        write_json_atomic(path, {"new": True})

    assert len(calls) == 1
    assert sleeps == []
    assert _list_dir(tmp_path) == []


def test_write_json_atomic_does_not_retry_other_errors_on_windows(tmp_path, monkeypatch):
    path = str(tmp_path / "data.json")
    calls, sleeps = [], []

    def replace(src, dst):
        calls.append(1)
        raise OSError(errno.ENOSPC, "디스크가 가득 참", dst)

    monkeypatch.setattr(user_files, "_IS_WINDOWS", True)
    monkeypatch.setattr(user_files, "_replace", replace)
    monkeypatch.setattr(user_files, "_sleep", sleeps.append)

    with pytest.raises(OSError) as info:
        write_json_atomic(path, {"new": True})

    assert info.value.errno == errno.ENOSPC
    assert len(calls) == 1
    assert sleeps == []
    assert _list_dir(tmp_path) == []


# ---------- write_json_atomic: 파일 권한 ----------
# mkstemp는 0600으로 만들므로 그대로 os.replace하면 NAS를 함께 쓰는 다른 계정이 못 읽음 — 권한을 맞춰 둔다.
# Windows의 os.chmod는 읽기 전용 표시만 바꾸므로 권한 비트 시험은 Mac에서만 한다.

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="Windows의 chmod는 읽기 전용 표시만 바꿈")


def _umask():
    old = os.umask(0)
    os.umask(old)
    return old


@posix_only
@pytest.mark.parametrize("mode", [0o664, 0o666, 0o600])
def test_write_json_atomic_keeps_mode_of_existing_file(tmp_path, mode):
    path = str(tmp_path / "data.json")
    write_json_atomic(path, {"old": True})
    os.chmod(path, mode)

    write_json_atomic(path, {"new": True})

    assert stat.S_IMODE(os.stat(path).st_mode) == mode
    assert read_json(path, None) == {"new": True}


@posix_only
def test_write_json_atomic_new_file_gets_default_open_mode(tmp_path):
    path = str(tmp_path / "새 폴더" / "data.json")
    write_json_atomic(path, {"a": 1})
    expected = 0o666 & ~_umask()
    assert stat.S_IMODE(os.stat(path).st_mode) == expected
    # open()으로 만든 파일과 같음
    plain = str(tmp_path / "plain.json")
    with open(plain, "w", encoding="utf-8") as fh:
        fh.write("{}")
    assert stat.S_IMODE(os.stat(path).st_mode) == stat.S_IMODE(os.stat(plain).st_mode)


@posix_only
def test_write_json_atomic_failed_write_keeps_mode_and_content_of_existing_file(tmp_path):
    path = str(tmp_path / "data.json")
    write_json_atomic(path, {"old": True})
    os.chmod(path, 0o664)
    with pytest.raises(TypeError):
        write_json_atomic(path, {"x": object()})
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o664
    assert read_json(path, None) == {"old": True}


@posix_only
def test_update_json_keeps_mode_of_existing_file(tmp_path):
    path = str(tmp_path / "list.json")
    update_json(path, lambda value: value + ["a"], [])
    os.chmod(path, 0o664)
    update_json(path, lambda value: value + ["b"], [])
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o664


# ---------- read_json ----------


def test_read_json_missing_returns_default(tmp_path):
    path = str(tmp_path / "없는 폴더" / "data.json")
    assert read_json(path, []) == []
    assert read_json(path, None) is None
    sentinel = object()
    assert read_json(path, sentinel) is sentinel
    assert not os.path.exists(os.path.dirname(path))  # 읽기만 함: 폴더를 만들지 않음


def test_read_json_reads_utf8(tmp_path):
    path = str(tmp_path / "data.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('{"씬": "가나다"}')
    assert read_json(path, None) == {"씬": "가나다"}


@pytest.mark.parametrize("content", [b"", b'{"half": ', b"\xff\xfe\x00 not utf8"])
def test_read_json_corrupt_raises_with_path(tmp_path, content):
    path = str(tmp_path / "data.json")
    with open(path, "wb") as fh:
        fh.write(content)
    with pytest.raises(UserFileError) as info:
        read_json(path, [])
    assert path in str(info.value)
    assert isinstance(info.value.__cause__, ValueError)  # JSONDecodeError·UnicodeDecodeError 모두 ValueError
    assert type(info.value.__cause__).__name__ in str(info.value)  # 원인도 메시지에


def test_read_json_os_error_raises_with_path(tmp_path):
    path = str(tmp_path / "folder.json")
    os.mkdir(path)  # 파일이 아니라 폴더
    with pytest.raises(UserFileError) as info:
        read_json(path, [])
    assert path in str(info.value)
    assert isinstance(info.value.__cause__, OSError)


# ---------- FileLock ----------


def test_filelock_timeout_names_path(tmp_path):
    path = str(tmp_path / "data.json.lock")
    with FileLock(path):
        with pytest.raises(TimeoutError) as info:
            with FileLock(path, timeout_s=0.2):
                pytest.fail("잠긴 파일을 또 잠그면 안 됨")
    assert path in str(info.value)


def test_filelock_can_be_taken_again_after_release(tmp_path):
    path = str(tmp_path / "x.lock")
    with FileLock(path):
        pass
    with FileLock(path, timeout_s=0.2):
        pass


def test_filelock_released_when_body_raises(tmp_path):
    path = str(tmp_path / "x.lock")
    with pytest.raises(RuntimeError):
        with FileLock(path):
            raise RuntimeError("본문 실패")
    with FileLock(path, timeout_s=0.2):
        pass


def test_filelock_makes_folder(tmp_path):
    path = str(tmp_path / "새" / "폴더" / "x.lock")
    with FileLock(path):
        assert os.path.exists(path)


def _fake_msvcrt(locking):
    return types.SimpleNamespace(LK_UNLCK=0, LK_LOCK=1, LK_NBLCK=2, locking=locking)


def test_filelock_windows_uses_nonblocking_msvcrt_lock_and_unlocks(tmp_path, monkeypatch):
    path = str(tmp_path / "x.lock")
    calls = []

    def locking(fd, mode, nbytes):
        calls.append((mode, nbytes, os.lseek(fd, 0, os.SEEK_CUR)))
        if mode == 2 and len([c for c in calls if c[0] == 2]) <= 2:
            raise PermissionError(errno.EACCES, "잠겨 있음")  # 다른 프로세스가 잡고 있는 것처럼

    monkeypatch.setattr(user_files, "_IS_WINDOWS", True)
    monkeypatch.setitem(sys.modules, "msvcrt", _fake_msvcrt(locking))
    monkeypatch.setattr(user_files, "_sleep", lambda s: None)

    with FileLock(path):
        assert [c[0] for c in calls] == [2, 2, 2]  # LK_NBLCK 세 번째에 잡음
    assert [c[0] for c in calls] == [2, 2, 2, 0]  # 나갈 때 LK_UNLCK
    assert all(c[1] == 1 and c[2] == 0 for c in calls)  # 파일 맨 앞 1바이트


def test_filelock_windows_timeout_names_path(tmp_path, monkeypatch):
    path = str(tmp_path / "x.lock")

    def locking(fd, mode, nbytes):
        raise PermissionError(errno.EACCES, "잠겨 있음")

    monkeypatch.setattr(user_files, "_IS_WINDOWS", True)
    monkeypatch.setitem(sys.modules, "msvcrt", _fake_msvcrt(locking))

    with pytest.raises(TimeoutError) as info:
        with FileLock(path, timeout_s=0.2):
            pytest.fail("잠기면 안 됨")
    assert path in str(info.value)


def test_filelock_windows_other_os_error_raises_user_file_error_with_path(tmp_path, monkeypatch):
    path = str(tmp_path / "x.lock")

    def locking(fd, mode, nbytes):
        raise OSError(errno.EBADF, "잘못된 파일")

    monkeypatch.setattr(user_files, "_IS_WINDOWS", True)
    monkeypatch.setitem(sys.modules, "msvcrt", _fake_msvcrt(locking))

    with pytest.raises(UserFileError) as info:
        with FileLock(path):
            pytest.fail("잠기면 안 됨")
    assert path in str(info.value)
    assert isinstance(info.value.__cause__, OSError)


# ---------- update_json ----------


def test_update_json_reads_mutates_writes_and_returns_new_value(tmp_path):
    path = str(tmp_path / "list.json")
    assert update_json(path, lambda value: value + ["a"], []) == ["a"]
    assert update_json(path, lambda value: value + ["b"], []) == ["a", "b"]
    assert read_json(path, None) == ["a", "b"]
    assert _list_dir(tmp_path) == ["list.json", "list.json.lock"]


def test_update_json_mutate_error_keeps_file_and_releases_lock(tmp_path):
    path = str(tmp_path / "list.json")
    update_json(path, lambda value: value + ["a"], [])

    def broken(value):
        raise RuntimeError("고치다 실패")

    with pytest.raises(RuntimeError, match="고치다 실패"):
        update_json(path, broken, [])
    assert read_json(path, None) == ["a"]
    with FileLock(path + ".lock", timeout_s=0.2):  # 잠금이 풀려 있음
        pass


def test_update_json_corrupt_file_raises_and_is_not_overwritten(tmp_path):
    path = str(tmp_path / "list.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{깨진")
    with pytest.raises(UserFileError) as info:
        update_json(path, lambda value: value + ["a"], [])
    assert path in str(info.value)
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == "{깨진"  # 빈 목록으로 덮지 않음


def _append_many(path, worker, count):
    """자식 프로세스: 리스트 파일에 count번 덧붙임 (시험 모듈에 있어야 spawn으로 부를 수 있음)."""
    for n in range(count):
        update_json(path, lambda value, item=f"{worker}-{n}": value + [item], [])


def test_update_json_no_lost_update_across_processes(tmp_path):
    path = str(tmp_path / "list.json")
    context = multiprocessing.get_context("spawn")  # Mac·Windows 기본과 같게
    processes = [context.Process(target=_append_many, args=(path, worker, 25)) for worker in range(4)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=120)
    assert [process.exitcode for process in processes] == [0, 0, 0, 0]

    items = read_json(path, None)
    assert len(items) == 100
    assert len(set(items)) == 100  # 하나도 덮어써서 사라지거나 겹치지 않음
