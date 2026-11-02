"""북마크(~/.yeson_bookmarks.json: 폴더 경로 목록) 읽기·더하기·지우기 (Qt 없음).

북마크 파일은 이 PC의 사용자별 파일이라 여러 YesonCheck 창이 함께 쓴다. 창의 메모리 목록을 통째로 쓰면 그동안 다른
창이 더하거나 지운 것이 사라지므로, 더하기·지우기는 쓸 때마다 파일을 다시 읽어 고치고(user_files.update_json: 잠금 +
원자적 쓰기) 합친 목록을 돌려준다. 읽지 못한 파일(깨짐·형식 오류·권한)은 UserFileError — 빈 목록으로 치고 저장해
그 파일을 덮어 지우지 않는다.
"""

import os

from yesoncheck import paths, user_files
from yesoncheck.user_files import UserFileError


def default_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".yeson_bookmarks.json")


def _check(path: str, value) -> list:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise UserFileError(f"북마크 파일 형식이 올바르지 않습니다 (폴더 경로 목록이어야 함): {path}")
    return value


def load(path: str) -> list[str]:
    """북마크 목록 (파일이 없으면 빈 목록). 읽지 못하거나 형식이 틀리면 UserFileError."""
    return list(_check(path, user_files.read_json(path, [])))


def add(path: str, folder: str) -> list[str]:
    """folder를 북마크 파일에 더함 (이미 있으면 그대로 — 판정은 paths.contains_path). 합친 새 목록을 돌려줌."""

    def mutate(value):
        current = _check(path, value)
        return current if paths.contains_path(current, folder) else current + [folder]

    return user_files.update_json(path, mutate, [])


def remove(path: str, folder: str) -> list[str]:
    """folder를 북마크 파일에서 지움 (없으면 그대로). 다른 창이 그동안 더한 것은 남기고 합친 새 목록을 돌려줌."""
    key = paths.path_key(folder)

    def mutate(value):
        return [item for item in _check(path, value) if paths.path_key(item) != key]

    return user_files.update_json(path, mutate, [])


def replace(path: str, old: str, new: str) -> list[str]:
    """북마크 파일에서 old를 new로 고침 (관리 창에서 경로를 그 자리에서 고친 것). 합친 새 목록을 돌려줌.

    new는 old의 자리에 들어감. 그사이 다른 창이 old를 지웠으면 new를 끝에 더하고, new가 이미 (old 아닌 자리에) 있으면
    old만 지워 new가 한 번만 남음 (판정은 paths.path_key). old와 new가 같은 경로면 글자만 new로.
    """
    old_key, new_key = paths.path_key(old), paths.path_key(new)

    def mutate(value):
        current = _check(path, value)
        elsewhere = any(paths.path_key(item) == new_key for item in current if paths.path_key(item) != old_key)
        result, placed = [], False
        for item in current:
            if paths.path_key(item) != old_key:
                result.append(item)
            elif not placed and not elsewhere:
                result.append(new)
                placed = True
        if not placed and not elsewhere:
            result.append(new)
        return result

    return user_files.update_json(path, mutate, [])
