# PyInstaller hook for PaddleOCR
# PaddleOCR의 동적 import를 위한 hiddenimports

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# PaddleOCR의 모든 서브모듈 수집
hiddenimports = collect_submodules('paddleocr')

# PaddleOCR tools 모듈 명시적 추가
hiddenimports += [
    'paddleocr.tools',
    'paddleocr.tools.infer',
    'paddleocr.tools.infer.utility',
    'paddleocr.tools.infer.predict_det',
    'paddleocr.tools.infer.predict_rec',
    'paddleocr.tools.infer.predict_cls',
    'paddleocr.tools.infer.predict_system',
]

# PaddleOCR 데이터 파일 수집 (Python 파일 포함)
datas = collect_data_files('paddleocr', include_py_files=True)

print(f"[hook-paddleocr] Collected {len(hiddenimports)} hiddenimports and {len(datas)} datas")
