"""공유 설정 폴더(.yesoncheck) 찾기와 작품 경로 파일(work_paths.json) 읽기·쓰기.

- Mac: /USA_DB/test_jn/.yesoncheck (고정, 기존과 같음). 이 Mac에 /USA_DB가 없고 그 공유를 다른 곳에 붙였으면 그곳
  (paths.to_native — 이 Mac의 자동 연결 설정·fstab, mac_mounts)
- Windows: PC별 설정 %APPDATA%\\YesonCheck\\settings.json 의 "config_dir"(UNC)
- 시험·실행 시험용: 환경 변수 YESONCHECK_CONFIG_DIR가 있으면 그 폴더
공유 파일을 읽다 실패해도 기본값으로 덮어쓰거나 폴더를 새로 만들지 않는다.
"""

import json
import os

from yesoncheck import paths

MAC_CONFIG_DIR = "/USA_DB/test_jn/.yesoncheck"
WORK_PATHS_FILENAME = "work_paths.json"
PASSWORD_FILENAME = "work_paths_password.json"
CONFIG_DIR_ENV = "YESONCHECK_CONFIG_DIR"


class SharedConfigError(Exception):
    """공유 설정 폴더나 작품 경로 파일, PC별 설정을 쓸 수 없을 때."""


def local_settings_path():
    """Windows PC별 설정 파일 위치."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SharedConfigError("APPDATA 환경 변수가 없어 PC별 설정 위치를 정할 수 없습니다.")
    return os.path.join(appdata, "YesonCheck", "settings.json")


def load_local_settings():
    path = local_settings_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise SharedConfigError(f"PC별 설정 파일을 읽지 못했습니다: {path}\n{exc}") from exc
    if not isinstance(data, dict):
        raise SharedConfigError(f"PC별 설정 파일 형식 오류 (객체가 아님): {path}")
    return data


def save_local_settings(updates):
    data = load_local_settings()
    data.update(updates)
    path = local_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)  # PC별 설정 폴더는 만들어도 됨 (공유 폴더 아님)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def configured_config_dir():
    """이 PC가 쓸 공유 설정 폴더. Windows에서 아직 정하지 않았으면 None.

    Mac: MAC_CONFIG_DIR를 이 Mac에서 여는 경로 (공유를 다른 곳에 붙인 Mac은 그곳). 맞는 공유가 여럿이라 정하지 못하면
    SharedConfigError (후보가 보임).
    """
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return override
    if not paths.IS_WINDOWS:
        try:
            return paths.to_native(MAC_CONFIG_DIR)
        except paths.PathMapError as exc:
            raise SharedConfigError(f"공유 설정 폴더를 이 Mac에서 찾지 못했습니다: {MAC_CONFIG_DIR}\n{exc}") from exc
    return load_local_settings().get("config_dir") or None


def mac_config_dir_lookup():
    """(Mac) 공유 설정 폴더(MAC_CONFIG_DIR)를 이 Mac에서 어디로 찾았는지 — 작품 경로 파일을 읽지 못했을 때 오류에 덧붙임
    (자동 연결 설정·fstab에서 찾은 것, 또는 그 파일들을 읽다 난 문제)."""
    return paths.describe_mac_path(MAC_CONFIG_DIR)


def validate_config_dir(config_dir):
    """공유 설정 폴더인지 확인합니다 (work_paths.json이 있어야 함)."""
    if not config_dir or not os.path.isdir(config_dir):
        raise SharedConfigError(f"공유 설정 폴더를 열 수 없습니다: {config_dir}")
    if not os.path.isfile(os.path.join(config_dir, WORK_PATHS_FILENAME)):
        raise SharedConfigError(f"이 폴더에 {WORK_PATHS_FILENAME}이 없습니다: {config_dir}")


def is_valid_config_dir(config_dir):
    try:
        validate_config_dir(config_dir)
    except SharedConfigError:
        return False
    return True


def read_work_paths(work_paths_file):
    """작품 경로 파일을 읽습니다: {작품 이름: Mac 경로}. 문제가 있으면 SharedConfigError (파일은 건드리지 않음)."""
    try:
        with open(work_paths_file, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise SharedConfigError(f"작품 경로 파일이 없습니다: {work_paths_file}\nNAS 연결을 확인하세요.") from exc
    except (OSError, ValueError) as exc:
        raise SharedConfigError(f"작품 경로 파일을 읽지 못했습니다: {work_paths_file}\n{exc}") from exc
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise SharedConfigError(f"작품 경로 파일 형식 오류 ({{작품 이름: 경로}} 형태가 아님): {work_paths_file}")
    return data


def write_work_paths(work_paths_file, work_paths):
    """작품 경로 파일에 씁니다. 폴더는 만들지 않습니다 (없으면 OSError)."""
    with open(work_paths_file, "w", encoding="utf-8") as fh:
        json.dump(work_paths, fh, ensure_ascii=False, indent=2)
