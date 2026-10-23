"""파일 이름 규칙: 목록에 넣을 영상, 확장자, Windows 예약 이름, 번호 순서 정렬 키."""

import os
import re

LISTED_VIDEO_EXTENSIONS = (".mov", ".mp4")
WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def is_listed_video(name):
    """작품 job 목록에 넣을 영상인지 (확장자 대소문자 무시, '.'으로 시작하는 숨김·._ 파일 제외)."""
    return not name.startswith(".") and name.lower().endswith(LISTED_VIDEO_EXTENSIONS)


def natural_key(file_path):
    """번호 순서 정렬 키: 파일 이름의 숫자는 숫자로 (clip2 < clip10), 나머지는 소문자로.

    video_list(영상 목록)와 sequence_scan(시퀀스 묶기)이 함께 쓰므로 둘 중 어느 쪽에도 속하지 않는 이 모듈에 둠 (서로 불러오면 순환).
    """
    filename = os.path.basename(file_path)
    # isdecimal: int()가 받는 글자만 숫자로 (isdigit은 '²'·'①'도 받아 int()가 ValueError)
    return [int(text) if text.isdecimal() else text.lower() for text in re.split('([0-9]+)', filename)]


def with_extension(path, ext):
    """확장자가 없으면 붙입니다 (대소문자 무시: X.MOV에 .mov를 또 붙이지 않음)."""
    return path if path.lower().endswith(ext.lower()) else path + ext


def avoid_reserved_name(stem):
    """Windows가 파일 이름으로 쓸 수 없는 이름(CON, AUX, COM1 등)이면 뒤에 _를 붙입니다."""
    return stem + "_" if stem.upper() in WINDOWS_RESERVED_NAMES else stem
