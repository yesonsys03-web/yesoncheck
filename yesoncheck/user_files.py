"""사용자 파일(JSON)을 여러 창(프로세스)이 함께 써도 안전하게 읽고 쓰는 도구 (Qt 없음).

- write_json_atomic: 같은 폴더의 임시 파일에 쓴 뒤 os.replace — 쓰는 중에 읽는 쪽이 반쪽짜리 파일을 보지 않고,
  쓰다 실패해도 원래 파일이 그대로다. Windows에서는 대상 파일을 다른 프로세스가 열어 두고 있으면 os.replace가
  PermissionError를 내므로 0.1초 간격으로 20번까지 다시 시도하고, 그래도 안 되면 그 PermissionError를 그대로 올린다.
- read_json: 파일이 없으면 부른 쪽이 정한 값(missing), 읽기·형식 오류는 경로와 원인을 담은 UserFileError —
  깨진 파일을 빈 값으로 치지 않는다 (다음 저장이 그 파일을 덮어 지우지 않게).
- FileLock: 같은 PC 안의 프로세스 사이 잠금 (Mac fcntl.flock · Windows msvcrt.locking). NAS 위의 파일에는 쓰지
  않는다 — NAS의 파일 잠금은 믿을 수 없으므로 NAS에 있는 파일은 원자적 쓰기와 합치기로 지킨다. 잠금 파일은 지우지
  않고 남긴다 (지우면 지우는 사이에 다른 프로세스가 다른 파일을 잠그는 경쟁이 생김). 같은 프로세스 안에서도
  다시 들어갈 수 없다 (두 번째 잠금은 풀릴 때까지 기다리다 시간 초과).
- update_json: 잠금 안에서 읽기 → 고치기 → 쓰기를 한 번에 해서 두 창이 동시에 고쳐도 한쪽이 사라지지 않게 한다.

예상 못 한 예외는 삼키지 않는다. 오류는 경로와 원래 예외를 담아 올린다.
"""

import errno
import json
import os
import stat
import sys
import tempfile
import time
from collections.abc import Callable

# 테스트가 바꿔 끼울 수 있게 모듈 값으로 둠 (Windows 갈래를 Mac에서도 시험)
_IS_WINDOWS = sys.platform == "win32"
_replace = os.replace
_sleep = time.sleep

_REPLACE_RETRIES = 20  # Windows에서 대상이 열려 있어 PermissionError일 때 다시 시도하는 횟수
_REPLACE_RETRY_INTERVAL_S = 0.1
_LOCK_POLL_INTERVAL_S = 0.05


def _read_umask():
    """프로세스의 umask. 읽기만 하는 방법이 없어 0으로 바꿨다가 되돌린다 — 그 사이에 다른 스레드가 만드는 파일의
    권한이 틀어질 수 있으므로 모듈을 불러올 때 한 번만 부른다 (앱 시작 때 스레드가 늘기 전)."""
    old = os.umask(0)
    os.umask(old)
    return old


# open()이 새 파일에 주는 권한 (mkstemp는 0600이라 그대로 두면 다른 계정이 NAS의 파일을 못 읽음)
_NEW_FILE_MODE = 0o666 & ~_read_umask()


class UserFileError(Exception):
    """사용자 파일을 읽거나 잠그지 못함 — 메시지에 경로와 원인 (원래 예외는 __cause__)."""


def _replace_with_retry(tmp_path, path):
    """tmp_path를 path 자리로 옮김. Windows의 PermissionError(대상이 열려 있음)만 다시 시도, 끝내 안 되면 그대로 올림."""
    retries_left = _REPLACE_RETRIES
    while True:
        try:
            _replace(tmp_path, path)
            return
        except PermissionError:
            if not _IS_WINDOWS or retries_left == 0:
                raise
            retries_left -= 1
            _sleep(_REPLACE_RETRY_INTERVAL_S)


def _match_target_mode(tmp_path, path):
    """임시 파일(mkstemp는 0600)의 권한을 바꿔 둘 파일의 권한으로: path가 있으면 그 권한, 없으면 새 파일의 보통 권한.

    NAS의 파일은 Mac(NFS uid)·Windows(SMB 계정) 등 여러 계정이 함께 쓰므로 쓸 때마다 권한이 좁아지면 안 된다.
    Windows의 os.chmod는 읽기 전용 표시만 바꾸므로 해가 없다.
    """
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode) & 0o777
    except FileNotFoundError:
        mode = _NEW_FILE_MODE
    os.chmod(tmp_path, mode)


def write_json_atomic(path: str, data, indent: int | None = 2) -> None:
    """data를 JSON으로 path에 씀: 같은 폴더의 임시 파일 + os.replace (폴더가 없으면 만듦).

    쓰다 실패하면 임시 파일을 지우고 원래 예외를 그대로 올린다 (원래 파일은 그대로). indent=None이면 한 줄.
    파일 권한은 이미 있는 파일이면 그 권한을, 새 파일이면 open()과 같은 0o666 & ~umask를 준다 (좁아지지 않음).
    """
    folder = os.path.dirname(os.path.abspath(path))  # 폴더 없이 파일 이름만 줘도 됨
    os.makedirs(folder, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=indent)
        _match_target_mode(tmp_path, path)
        _replace_with_retry(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        raise


def read_json(path: str, missing):
    """path의 JSON 값. 파일이 없으면 missing(그 객체 그대로 — 고칠 값이면 부를 때마다 새로 만들어 넘길 것).

    읽지 못했거나(OSError) UTF-8·JSON 형식이 깨졌으면 UserFileError (경로와 원인).
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return missing
    except (OSError, ValueError) as exc:  # ValueError: JSONDecodeError·UnicodeDecodeError
        raise UserFileError(f"파일을 읽지 못했습니다: {path}\n{type(exc).__name__}: {exc}") from exc


class FileLock:
    """프로세스 사이 잠금 파일 path를 잡는 컨텍스트 매니저 (`with FileLock(path): ...`).

    timeout_s 안에 잡지 못하면 TimeoutError(경로 포함). 잠금 파일을 열거나 잠그지 못하면 UserFileError.
    같은 PC의 프로세스 사이 전용 — NAS 위에는 두지 않는다.
    """

    def __init__(self, path: str, timeout_s: float = 10.0):
        self.path = path
        self.timeout_s = timeout_s
        self._fd = None

    def __enter__(self):
        folder = os.path.dirname(os.path.abspath(self.path))
        try:
            os.makedirs(folder, exist_ok=True)
            self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o666)
        except OSError as exc:
            raise UserFileError(f"잠금 파일을 열지 못했습니다: {self.path}\n{type(exc).__name__}: {exc}") from exc
        try:
            self._acquire()
        except BaseException:
            os.close(self._fd)
            self._fd = None
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        fd, self._fd = self._fd, None
        try:
            self._unlock(fd)
        finally:
            os.close(fd)

    def _acquire(self):
        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                if self._try_lock(self._fd):
                    return
            except OSError as exc:
                raise UserFileError(f"파일을 잠그지 못했습니다: {self.path}\n{type(exc).__name__}: {exc}") from exc
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"다른 YesonCheck 창이 잠그고 있어 {self.timeout_s:g}초 안에 잠그지 못했습니다: {self.path}"
                )
            _sleep(_LOCK_POLL_INTERVAL_S)

    @staticmethod
    def _try_lock(fd) -> bool:
        """기다리지 않고 한 번 잠가 봄: 잡았으면 True, 다른 프로세스가 잡고 있으면 False, 그 밖의 오류는 OSError."""
        if _IS_WINDOWS:
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)  # msvcrt.locking은 지금 위치부터 잠금
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EDEADLK):  # 다른 프로세스가 잡고 있음
                    return False
                raise
            return True
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:  # 다른 프로세스가 잡고 있음
            return False
        return True

    @staticmethod
    def _unlock(fd) -> None:
        if _IS_WINDOWS:
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def update_json(path: str, mutate: Callable[[object], object], missing) -> object:
    """path + ".lock"을 잡고 읽기 → mutate(값) → write_json_atomic → 새 값을 돌려줌.

    mutate는 새 값을 돌려줘야 한다 (제자리에서 고치더라도 그 값을 돌려줄 것 — None을 돌려주면 null이 저장됨).
    파일이 없으면 mutate에 missing을 넘긴다. mutate가 예외를 내거나 읽기가 UserFileError면 파일을 건드리지 않는다.
    같은 PC의 프로세스 사이에서만 안전 (NAS 위의 파일에는 쓰지 않음 — FileLock 설명). 잠금 시간 초과는 TimeoutError.
    """
    with FileLock(path + ".lock"):
        new_value = mutate(read_json(path, missing))
        write_json_atomic(path, new_value)
        return new_value
