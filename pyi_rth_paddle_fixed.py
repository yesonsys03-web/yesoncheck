# PyInstaller runtime hook for Paddle - Fixed Version
# 이 훅은 PaddlePaddle이 PyInstaller 환경에서 정상 작동하도록 경로를 설정합니다

import os
import sys
import site
import sysconfig
import platform

if getattr(sys, 'frozen', False):
    # PyInstaller로 빌드된 환경
    _MEIPASS = sys._MEIPASS

    # Paddle 패키지가 있는 경로를 sys.path 맨 앞에 추가
    paddle_path = os.path.join(_MEIPASS, 'paddle')
    if os.path.exists(paddle_path) and paddle_path not in sys.path:
        sys.path.insert(0, paddle_path)
        print(f"[Runtime Hook] Added paddle path to sys.path: {paddle_path}")

    # _MEIPASS 자체도 sys.path에 추가 (최우선)
    if _MEIPASS not in sys.path:
        sys.path.insert(0, _MEIPASS)
        print(f"[Runtime Hook] Added _MEIPASS to sys.path: {_MEIPASS}")

    # site.USER_SITE와 site.USER_BASE를 _MEIPASS로 설정
    # (paddle/base/core.py의 set_paddle_lib_path에서 사용됨)
    site.USER_SITE = _MEIPASS
    site.USER_BASE = _MEIPASS
    print(f"[Runtime Hook] Set site.USER_SITE and site.USER_BASE to: {_MEIPASS}")

    # site.getsitepackages도 패치
    original_getsitepackages = getattr(site, 'getsitepackages', None)

    def patched_getsitepackages():
        """Return PyInstaller temp directory as site-packages."""
        return [_MEIPASS]

    site.getsitepackages = patched_getsitepackages
    print(f"[Runtime Hook] Patched site.getsitepackages to return: {_MEIPASS}")

    # sysconfig.get_platform 패치 (setuptools/_distutils에서 사용됨)
    if not hasattr(sysconfig, 'get_platform'):
        def get_platform():
            """Return platform string for current system."""
            return platform.platform()

        sysconfig.get_platform = get_platform
        print(f"[Runtime Hook] Added sysconfig.get_platform()")
