"""폴더의 파일 이름에서 이미지 시퀀스를 찾아 묶는 규칙 (Qt 없음, 디스크를 읽지 않음).

`EX01_tk1-0001.tga … EX01_tk1-0306.tga`처럼 `<base>-<프레임 번호>.<확장자>`인 파일이 2장 이상이면 시퀀스 하나다.
프레임 번호 앞의 '-'는 이름의 마지막 '-'이므로 base 자체에 '-'가 있어도 된다 (`scene-09B_tk1-0001.tga` -> `scene-09B_tk1`).

사이드바 목록에는 시퀀스를 가상 경로 `<폴더>/<base>.seq`(SeqInfo.identity)로 넣는다 — 같은 폴더의 `<base>.mov`와
이름이 겹치지 않고, 진짜 파일이 아니라는 표시(is_sequence_path)로도 쓴다.
"""

import os
import re
from dataclasses import dataclass

# natural_key는 video_list가 아닌 중립 모듈(file_names)에 있음: video_list가 이 모듈을 쓰므로(스캔 때 시퀀스를 함께 찾음) 거기서 가져오면 순환 import
from yesoncheck.file_names import natural_key

# 시퀀스로 묶는 이미지 확장자 (점 없는 소문자; 비교는 소문자로)
SEQ_EXTENSIONS = {"tga", "png", "jpg", "jpeg", "tif", "tiff", "exr"}
# 시퀀스에서 뽑은 임시 프레임을 두는 폴더 이름: 부르는 쪽이 이 이름의 폴더는 그룹핑에서 뺀다
TEMP_FRAMES_DIR = "temp_frames"
SEQ_SUFFIX = ".seq"

# base는 마지막 '-' 앞까지 (탐욕 매칭), 프레임 번호는 2자리 이상 ASCII 숫자 ('\d'는 다른 문자 체계 숫자도 받아서 안 씀)
_FRAME_NAME = re.compile(r"(.+)-([0-9]{2,})\.([^.]+)")


@dataclass(frozen=True)
class SeqInfo:
    """이미지 시퀀스 하나: dir 폴더의 `base-NNNN.ext` 프레임들 (pad = 번호 자릿수, first~last = 스캔에서 본 번호 범위)."""

    dir: str
    base: str
    ext: str
    pad: int
    first: int
    last: int
    count: int  # 스캔에서 실제로 본 프레임 수

    @property
    def identity(self):
        """사이드바 목록에서 이 시퀀스를 가리키는 가상 경로 (`<dir>/<base>.seq`)."""
        return os.path.join(self.dir, self.base + SEQ_SUFFIX)

    def frame_name(self, n):
        """프레임 번호 n의 파일 이름 (`<base>-<0으로 채운 n>.<ext>`)."""
        return f"{self.base}-{n:0{self.pad}d}.{self.ext}"

    @property
    def missing(self):
        """first~last 사이에서 스캔에 없던 프레임 수."""
        return self.last - self.first + 1 - self.count


def is_sequence_path(path):
    """목록의 경로가 시퀀스의 가상 경로(`.seq`)인지."""
    return path.endswith(SEQ_SUFFIX)


def group_sequences(dir_path, names):
    """dir_path 폴더의 파일 이름들(names, 폴더 항목은 부르는 쪽이 뺌)에서 2장 이상인 시퀀스를 찾아 base 번호 순서로.

    (base, 확장자, 번호 자릿수)가 같은 파일이 한 시퀀스다: 테이크가 다르거나(tk1·tk2) 자릿수가 다르면(-001·-0001)
    별개. 확장자는 SEQ_EXTENSIONS만(대소문자 무시, SeqInfo.ext는 소문자), '.'으로 시작하는 숨김·._ 파일은 제외.
    """
    groups = {}  # (base, ext, pad) -> 본 프레임 번호 집합 (같은 이름이 또 와도 한 장)
    for name in names:
        if name.startswith("."):
            continue
        match = _FRAME_NAME.fullmatch(name)
        if match is None:
            continue
        base, digits, ext = match.groups()
        ext = ext.lower()
        if ext not in SEQ_EXTENSIONS:
            continue
        groups.setdefault((base, ext, len(digits)), set()).add(int(digits))

    sequences = [
        SeqInfo(dir_path, base, ext, pad, min(numbers), max(numbers), len(numbers))
        for (base, ext, pad), numbers in groups.items()
        if len(numbers) >= 2
    ]
    sequences.sort(key=lambda s: (natural_key(s.base), s.base, s.ext, s.pad))
    return sequences
