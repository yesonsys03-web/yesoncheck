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
