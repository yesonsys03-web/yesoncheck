"""YesonCheck application package."""

import os

# EXR 시퀀스 프레임용: Windows cv2 휠은 OpenEXR 코덱이 기본으로 꺼져 있고, 이 값은 cv2가 이미지 코덱을 처음 쓰기 전에
# 정해져 있어야 한다. 앱이 cv2를 불러오는 모든 길(python -m yesoncheck.app, 동결된 앱의 app.py)이 이 패키지를 먼저 불러오므로
# 여기가 가장 이른 자리 (sequence_source에도 같은 줄이 있어 이 패키지를 거치지 않는 쓰임의 예비)
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

__all__ = ["launch"]


def launch(argv=None):
    """앱 실행. PyQt5 등 무거운 모듈은 호출할 때 불러옵니다."""
    from .app import launch as _launch

    return _launch(argv)
