"""한글 등 비ASCII 경로에서도 되는 이미지 읽기·쓰기.

cv2.imread/imwrite는 Windows에서 비ASCII 경로를 열지 못하고 실패해도 예외 없이 None/False만 돌려준다.
"""

import os

import cv2
import numpy as np


def imread(path, flags=cv2.IMREAD_COLOR):
    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, flags)
    if image is None:
        raise ValueError(f"이미지를 읽지 못했습니다: {path}")
    return image


def imwrite(path, image, params=None):
    ext = os.path.splitext(path)[1] or ".jpg"
    ok, buffer = cv2.imencode(ext, image, params or [])
    if not ok:
        raise ValueError(f"이미지를 인코딩하지 못했습니다 ({ext}): {path}")
    buffer.tofile(path)
