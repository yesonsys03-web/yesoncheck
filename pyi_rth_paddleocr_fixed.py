# PyInstaller runtime hook for PaddleOCR - Fixed Version
# 이 훅은 PaddleOCR이 PyInstaller 환경에서 정상 작동하도록 경로를 설정합니다

import os
import sys

if getattr(sys, 'frozen', False):
    # PyInstaller로 빌드된 환경
    _MEIPASS = sys._MEIPASS

    # apted 모듈 경로 추가 (PaddleOCR이 사용하는 fallback 구현)
    apted_path = os.path.join(_MEIPASS, 'apted')
    apted_parent = os.path.dirname(apted_path)
    print(f"[Runtime Hook] Checking apted: path={apted_path}, exists={os.path.exists(apted_path)}")
    if os.path.exists(apted_path):
        if apted_parent not in sys.path:
            sys.path.insert(0, apted_parent)
            print(f"[Runtime Hook] Added apted parent path to sys.path: {apted_parent}")
        else:
            print(f"[Runtime Hook] apted parent path already in sys.path: {apted_parent}")
        if os.path.exists(os.path.join(apted_path, '__init__.py')):
            print(f"[Runtime Hook] apted module found at: {apted_path}")
        else:
            print(f"[Runtime Hook] WARNING: apted __init__.py NOT found")
    else:
        print(f"[Runtime Hook] WARNING: apted directory NOT found at: {apted_path}")
        print(f"[Runtime Hook] Contents of _MEIPASS: {os.listdir(_MEIPASS)[:20]}")

    # PaddleOCR 패키지가 있는 경로를 sys.path 맨 앞에 추가
    paddleocr_path = os.path.join(_MEIPASS, 'paddleocr')
    if os.path.exists(paddleocr_path) and paddleocr_path not in sys.path:
        sys.path.insert(0, paddleocr_path)
        print(f"[Runtime Hook] Added paddleocr path to sys.path: {paddleocr_path}")

    # PaddleOCR이 있는지 확인
    paddleocr_init = os.path.join(paddleocr_path, '__init__.py')
    if os.path.exists(paddleocr_init):
        print(f"[Runtime Hook] PaddleOCR __init__.py found at: {paddleocr_init}")

        # paddleocr 서브디렉토리들도 확인
        for subdir in ['ppocr', 'ppstructure', 'tools']:
            subdir_path = os.path.join(paddleocr_path, subdir)
            if os.path.exists(subdir_path):
                print(f"[Runtime Hook] PaddleOCR subdir found: {subdir}")
    else:
        print(f"[Runtime Hook] WARNING: PaddleOCR __init__.py NOT found at: {paddleocr_init}")
        print(f"[Runtime Hook] Contents of _MEIPASS: {os.listdir(_MEIPASS)[:20]}")
