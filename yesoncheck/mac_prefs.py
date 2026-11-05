"""(Mac) 사용자 설정 파일 prefs.json — 읽기와 한 키 고치기. Qt 없음.

위치: ~/Library/Application Support/YesonCheck/prefs.json (HOME을 부를 때마다 읽음). 키마다 쓰는 곳이 다르다:
  asked_default_video_app  동영상 기본 앱 질문에 답했는지 (default_app — 처음 켤 때 한 번 묻기)
  playback_decoder         재생 디코더 "videotoolbox" | "ffmpeg" (app.launch가 시작 때 한 번 읽어 mac_native_gate의 캐시에 두고,
                           Setting 메뉴가 update_pref로 고침 — 값의 뜻·검증은 mac_native_gate)
이 모듈은 파일만 다룬다: 어떤 키가 무슨 뜻인지, 값이 맞는지는 호출한 쪽이 판단한다 (다른 창·다음 버전이 쓴 모르는 키는 그대로 둠).

user_files의 규칙을 그대로 따른다: 파일이 없으면 빈 값, 읽지 못했거나 깨졌거나 JSON 객체가 아니면 UserFileError(경로와 원인) — 빈 값으로
치지 않아 다음 저장이 그 파일을 덮어 지우지 않는다. 고칠 때는 잠금 안에서 다시 읽고 그 키만 바꿔 원자적으로 쓴다 (두 창이 동시에 고쳐도
한쪽이 사라지지 않음). 잠금은 같은 PC의 프로세스 사이 전용.
"""

import os

from yesoncheck import user_files
from yesoncheck.user_files import UserFileError

PREFS_FILE_NAME = "prefs.json"


def prefs_path() -> str:
    """~/Library/Application Support/YesonCheck/prefs.json — HOME을 부를 때마다 읽음 (시험·업데이트 끝까지 시험은 HOME을 바꿈)."""
    return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "YesonCheck", PREFS_FILE_NAME)


def _as_prefs(value, path):
    if not isinstance(value, dict):
        raise UserFileError(f"설정 파일이 JSON 객체가 아닙니다: {path} ({type(value).__name__})")
    return value


def read_prefs(path=None) -> dict:
    """prefs.json의 값 (없으면 {}). 깨졌거나 객체가 아니면 UserFileError — 빈 값으로 치지 않음. path: 다른 위치(Windows — windows_display)."""
    path = path or prefs_path()
    return _as_prefs(user_files.read_json(path, {}), path)


def update_pref(key: str, value, path=None) -> None:
    """prefs.json의 key를 value로 (잠금 안에서 다시 읽고 그 키만 고침 — 다른 키는 그대로, 파일이 없으면 새로 만듦). 깨진 파일은 덮지 않고
    UserFileError, 잠금 시간 초과는 TimeoutError, 쓰기 실패는 OSError. path: 다른 위치(Windows — windows_display)."""
    path = path or prefs_path()

    def mutate(prefs):
        prefs = _as_prefs(prefs, path)
        prefs[key] = value
        return prefs

    user_files.update_json(path, mutate, {})
