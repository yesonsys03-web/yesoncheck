"""파일 이름 규칙: 목록에 넣을 영상, 확장자, Windows 예약 이름."""

LISTED_VIDEO_EXTENSIONS = (".mov", ".mp4")
WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def is_listed_video(name):
    """작품 job 목록에 넣을 영상인지 (확장자 대소문자 무시, '.'으로 시작하는 숨김·._ 파일 제외)."""
    return not name.startswith(".") and name.lower().endswith(LISTED_VIDEO_EXTENSIONS)


def with_extension(path, ext):
    """확장자가 없으면 붙입니다 (대소문자 무시: X.MOV에 .mov를 또 붙이지 않음)."""
    return path if path.lower().endswith(ext.lower()) else path + ext


def avoid_reserved_name(stem):
    """Windows가 파일 이름으로 쓸 수 없는 이름(CON, AUX, COM1 등)이면 뒤에 _를 붙입니다."""
    return stem + "_" if stem.upper() in WINDOWS_RESERVED_NAMES else stem
