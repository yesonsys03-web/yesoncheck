# -*- mode: python ; coding: utf-8 -*-

# YesonCheck PyInstaller Spec - PaddleOCR with apted support
# apted 폴더 포함 및 collect-all을 사용한 완전한 라이브러리 수집

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules
import hashlib
import os
import platform
import sys
import sysconfig

IS_WINDOWS = sys.platform == 'win32'

# 빌드에 사용 중인 가상환경(p310)의 site-packages
p310_site_packages = sysconfig.get_paths()['purelib']

# 프로젝트 루트 경로 (spec 파일이 있는 디렉토리)
project_root = SPECPATH

# 지원 최소 macOS (몬터레이 12.3). build_app.sh가 빌드 후 번들 내 모든 바이너리를 이 버전으로 검사함
# 12.3인 이유: Intel용 paddle 3.0.0 라이브러리가 12.3을 요구 (requirements-build.txt 참고)
MIN_MACOS = '12.3'

# 정적 ffmpeg/ffprobe: Mac은 아키텍처별(vendor/ffmpeg/x86_64·arm64, fetch_ffmpeg.sh),
# Windows는 vendor/ffmpeg/windows(fetch_ffmpeg_windows.ps1). Homebrew ffmpeg는 빌드한 macOS 이상에서만 돌아 쓰지 않음
if IS_WINDOWS:
    ffmpeg_dir = os.path.join(project_root, 'vendor', 'ffmpeg', 'windows')
    ffmpeg_files = ('ffmpeg.exe', 'ffprobe.exe')
else:
    ffmpeg_dir = os.path.join(project_root, 'vendor', 'ffmpeg', platform.machine())
    ffmpeg_files = ('ffmpeg', 'ffprobe')
for _tool in ffmpeg_files:
    if not os.path.isfile(os.path.join(ffmpeg_dir, _tool)):
        raise SystemExit(f"[spec] 정적 {_tool}가 없습니다: {ffmpeg_dir} (BUILD.md 참고)")

# 애니매틱2(TransNetV2) 가중치: 저장소의 vendor/transnetv2-weights (출처·sha256은 그 폴더의 README.md).
# 없거나 sha256이 다르면 빌드를 멈춤 (예전에는 collect_all 실패를 경고만 하고 넘어가 TransNetV2 없이 배포됨)
TRANSNETV2_WEIGHTS_DIR = os.path.join(project_root, 'vendor', 'transnetv2-weights')
TRANSNETV2_WEIGHTS_SHA256 = {
    'saved_model.pb': '8ac2a52c5719690d512805b6eaf5ce12097c1d8860b3d9de245dcbbc3100f554',
    'variables/variables.data-00000-of-00001': 'b8c9dc3eb807583e6215cabee9ca61737b3eb1bceff68418b43bf71459669367',
    'variables/variables.index': '8b99e28b4ad11372d9a1ad9703298c2e370df14859da4245fdbe818e92dd403f',
}
transnet_datas = []
for _rel, _expected in TRANSNETV2_WEIGHTS_SHA256.items():
    _path = os.path.join(TRANSNETV2_WEIGHTS_DIR, *_rel.split('/'))
    if not os.path.isfile(_path):
        raise SystemExit(f"[spec] TransNetV2 가중치 파일이 없습니다: {_path} (vendor/transnetv2-weights/README.md 참고)")
    with open(_path, 'rb') as _fh:
        _actual = hashlib.sha256(_fh.read()).hexdigest()
    if _actual != _expected:
        raise SystemExit(f"[spec] TransNetV2 가중치 sha256이 다릅니다: {_path}\n  기대 {_expected}\n  실제 {_actual}"
                         " (Git LFS 포인터 파일이거나 손상됨, vendor/transnetv2-weights/README.md 참고)")
    transnet_datas.append((_path, os.path.dirname('transnetv2-weights/' + _rel)))
print(f"[spec] TransNetV2 가중치 sha256 확인: {len(transnet_datas)}개 파일 ({TRANSNETV2_WEIGHTS_DIR})")

# 기본 라이브러리 수집 (collect_all 사용)
cv2_binaries, cv2_datas, cv2_hiddenimports = [], [], []
scenedetect_binaries, scenedetect_datas, scenedetect_hiddenimports = [], [], []
paddleocr_binaries, paddleocr_datas, paddleocr_hiddenimports = [], [], []
paddle_binaries, paddle_datas, paddle_hiddenimports = [], [], []
skimage_binaries, skimage_datas, skimage_hiddenimports = [], [], []
cython_datas = []

# OpenCV 수집
try:
    _b, _d, _h = collect_all("cv2")
    cv2_binaries.extend(_b)
    cv2_datas.extend(_d)
    cv2_hiddenimports.extend(_h)
    print(f"[spec] Collected cv2 assets: {len(_b)} binaries, {len(_d)} datas, {len(_h)} hiddenimports")
except Exception as exc:
    print(f"[spec] Warning: cv2 collect_all failed ({exc})")

# PySceneDetect 수집
try:
    _b, _d, _h = collect_all("scenedetect")
    scenedetect_binaries.extend(_b)
    scenedetect_datas.extend(_d)
    scenedetect_hiddenimports.extend(_h)
    print(f"[spec] Collected PySceneDetect: {len(_b)} binaries, {len(_d)} datas, {len(_h)} hiddenimports")
except Exception as exc:
    print(f"[spec] Warning: scenedetect collect_all failed ({exc})")

# PaddleOCR collect_all 시도
try:
    _b, _d, _h = collect_all("paddleocr")
    paddleocr_binaries.extend(_b)
    paddleocr_datas.extend(_d)
    paddleocr_hiddenimports.extend(_h)
    print(f"[spec] Collected PaddleOCR assets: {len(_b)} binaries, {len(_d)} datas, {len(_h)} hiddenimports")
except Exception as exc:
    print(f"[spec] Warning: paddleocr collect_all failed ({exc})")

# Paddle collect_all 시도
try:
    _b, _d, _h = collect_all("paddle")
    paddle_binaries.extend(_b)
    paddle_datas.extend(_d)
    paddle_hiddenimports.extend(_h)
    print(f"[spec] Collected Paddle assets: {len(_b)} binaries, {len(_d)} datas, {len(_h)} hiddenimports")
except Exception as exc:
    print(f"[spec] Warning: paddle collect_all failed ({exc})")

# scikit-image 수집
try:
    _b, _d, _h = collect_all("skimage")
    skimage_binaries.extend(_b)
    skimage_datas.extend(_d)
    skimage_hiddenimports.extend(_h)
    print(f"[spec] Collected skimage assets: {len(_b)} binaries, {len(_d)} datas, {len(_h)} hiddenimports")
except Exception as exc:
    print(f"[spec] Warning: skimage collect_all failed ({exc})")

# PaddleOCR 서브모듈 수집 (추가 보완)
try:
    paddleocr_submodules = collect_submodules('paddleocr')
    paddleocr_hiddenimports.extend(paddleocr_submodules)
    print(f"[spec] Collected PaddleOCR submodules: {len(paddleocr_submodules)} modules")
except Exception as exc:
    print(f"[spec] Warning: paddleocr submodules collection failed ({exc})")

# PaddleOCR 의존성 모듈 수집
paddleocr_deps = ['imgaug', 'lmdb', 'tqdm', 'numpy', 'opencv-python', 'pillow', 'scipy', 'imageio']
imageio_binaries, imageio_datas, imageio_hiddenimports = [], [], []

for dep in paddleocr_deps:
    try:
        dep_submodules = collect_submodules(dep)
        paddleocr_hiddenimports.extend(dep_submodules)
        print(f"[spec] Collected {dep} submodules: {len(dep_submodules)} modules")
    except Exception as exc:
        print(f"[spec] Warning: {dep} submodules collection failed ({exc})")

# imageio collect_all (메타데이터 포함)
try:
    _b, _d, _h = collect_all("imageio")
    imageio_binaries.extend(_b)
    imageio_datas.extend(_d)
    imageio_hiddenimports.extend(_h)
    print(f"[spec] Collected imageio assets: {len(_b)} binaries, {len(_d)} datas, {len(_h)} hiddenimports")
except Exception as exc:
    print(f"[spec] Warning: imageio collect_all failed ({exc})")

# Paddle 서브모듈 수집 (추가 보완)
try:
    paddle_submodules = collect_submodules('paddle')
    paddle_hiddenimports.extend(paddle_submodules)
    print(f"[spec] Collected Paddle submodules: {len(paddle_submodules)} modules")
except Exception as exc:
    print(f"[spec] Warning: paddle submodules collection failed ({exc})")

# Cython 데이터 파일 수집
try:
    cython_datas = collect_data_files("Cython", include_py_files=True)
    print(f"[spec] Collected Cython data files: {len(cython_datas)} files")
except Exception as exc:
    print(f"[spec] Warning: Cython data collection failed ({exc})")

a = Analysis(
    ['yesoncheck/app.py'],
    pathex=[],
    binaries=[
        (os.path.join(ffmpeg_dir, _tool), '.') for _tool in ffmpeg_files
    ] + cv2_binaries + scenedetect_binaries + paddleocr_binaries + paddle_binaries + skimage_binaries + imageio_binaries,
    datas=[
        # PaddleOCR 전체 패키지를 Tree로 추가
        (os.path.join(p310_site_packages, 'paddleocr'), 'paddleocr'),
        # Paddle 전체 패키지를 Tree로 추가
        (os.path.join(p310_site_packages, 'paddle'), 'paddle'),
        # apted 모듈 추가 (PaddleOCR 분석에 필수)
        (os.path.join(project_root, 'apted'), 'apted'),
    ] + cv2_datas + transnet_datas + scenedetect_datas + paddleocr_datas + paddle_datas + skimage_datas + imageio_datas + cython_datas + ([] if IS_WINDOWS else [('Info.plist', '.')]),
    hiddenimports=[
        # apted 모듈 (PaddleOCR이 사용하는 fallback 구현)
        'apted',
        'apted.core',
        'apted.helpers',
        # Python 표준 라이브러리 (PaddleOCR이 사용)
        'imghdr',
        # scikit-image (PaddleOCR이 사용)
        'skimage',
        'skimage.morphology',
        'skimage.morphology._skeletonize',
        # PaddleOCR 의존성 모듈
        'imgaug',
        'imgaug.augmenters',
        'imageio',
        'imageio.plugins',
        'lmdb',
        'tqdm',
        # Paddle 핵심 모듈
        'paddle',
        'paddle.fluid',
        'paddle.fluid.core',
        'paddle.inference',
        'paddle.base',
        'paddle.base.core',
        'paddle.base.framework',
        # PaddleOCR 핵심 모듈
        'paddleocr',
        'paddleocr.paddleocr',
        'paddleocr.ppocr',
        'paddleocr.ppocr.data',
        'paddleocr.ppocr.postprocess',
        'paddleocr.ppocr.utils',
        'paddleocr.ppstructure',
        'paddleocr.tools',
        'paddleocr.tools.infer',
        'paddleocr.tools.infer.utility',
        'paddleocr.tools.infer.predict_det',
        'paddleocr.tools.infer.predict_rec',
        'paddleocr.tools.infer.predict_cls',
        'paddleocr.tools.infer.predict_system',
        # PyQt5
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtMultimedia',
        'PyQt5.QtMultimediaWidgets',
        'PyQt5.QtWebSockets',
        # OpenCV
        'cv2',
        # 애니매틱2: TransNetV2 로더(저장소에 복사한 코드)와 TensorFlow — 감지를 시작할 때만 import해 정적 분석에 안 잡힘
        # (TensorFlow 수집은 pyinstaller-hooks-contrib의 hook-tensorflow·pyi_rth_tensorflow가 함)
        'yesoncheck.transnetv2_model',
        'tensorflow',
        # TensorFlow import가 끌어오는 pandas의 C 확장(pandas._libs.tslibs)이 zoneinfo를 불러와 정적 분석에서 빠짐
        'zoneinfo',
        # PySceneDetect
        'scenedetect',
        'scenedetect.video_manager',
        'scenedetect.scene_manager',
        'scenedetect.detectors',
        'scenedetect.detectors.content_detector',
        'scenedetect.detectors.threshold_detector',
        'scenedetect.frame_timecode',
        'scenedetect.video_stream',
        'scenedetect.platform',
        # YesonCheck modules
        'yesoncheck.player_timeline',
        'yesoncheck.player_review',
        # paddleocr 내부 모듈이 서로를 'ppocr.…' 이름으로 불러와 분석에서 빠짐
        # (ppocr/utils/network.py의 requests는 `from paddleocr import PaddleOCR` 시점에 필요)
        'requests',
    ] + cv2_hiddenimports + scenedetect_hiddenimports + paddleocr_hiddenimports + paddle_hiddenimports + skimage_hiddenimports + imageio_hiddenimports,
    hookspath=[project_root],
    hooksconfig={},
    runtime_hooks=[
        os.path.join(project_root, 'pyi_rth_paddle_fixed.py'),
        os.path.join(project_root, 'pyi_rth_paddleocr_fixed.py'),
    ],
    excludes=[
        'torch', 'transformers', 'sklearn',
        'matplotlib', 'sympy',
        'nltk', 'librosa', 'pygame',
        'lightning', 'datasets', 'pyarrow',
        # TensorFlow가 끌어오지만 앱은 쓰지 않음: tf.summary용 tensorboard(없으면 TF가 경고만 함),
        # GCS 파일 시스템 플러그인(TF_USE_MODULAR_FILESYSTEM일 때만 불러옴, Mac 휠의 .so가 macOS 13 이상 요구).
        # keras·h5py는 빼지 말 것 — TF 2.15 import가 깨짐
        'tensorboard', 'tensorflow_io_gcs_filesystem',
    ],
    noarchive=False,
    optimize=0,
)

# arm64용 paddle 2.6.2 휠에는 x86_64 전용 dylib(libblas.3, liblapack.3, libgfortran.5 등)가 섞여 있음.
# paddle 본체가 링크하지 않고(liblapack만 LAPACK 연산 때 dlopen) 이 아키텍처에서는 어차피 못 쓰므로 제외
# (paddle 폴더를 datas로도 통째로 넣으므로 binaries와 datas 양쪽에서 거름)
if sys.platform == 'darwin':
    from PyInstaller.utils.osx import get_binary_architectures

    def _lacks_target_arch(entry):
        dest, src = entry[0], entry[1]
        return (dest.startswith('paddle/libs/') and dest.endswith('.dylib')
                and platform.machine() not in get_binary_architectures(src)[1])

    _dropped = sorted({e[0] for e in list(a.binaries) + list(a.datas) if _lacks_target_arch(e)})
    if _dropped:
        print(f"[spec] {platform.machine()} 슬라이스가 없는 paddle 라이브러리 제외: {_dropped}")
        a.binaries = [e for e in a.binaries if e[0] not in _dropped]
        a.datas = [e for e in a.datas if e[0] not in _dropped]

# Windows: TensorFlow가 import할 때(self_check.preload_check) msvcp140.dll·msvcp140_1.dll을 이름으로 불러봄.
# VC++ 재배포 패키지가 없는 PC에서도 되도록 _internal 맨 위에 두 DLL이 있게 함
# (PyInstaller가 의존성으로 이미 넣었으면 그대로, 아니면 이 빌드 PC의 System32 것을 넣음, 둘 다 없으면 빌드 실패)
if IS_WINDOWS:
    _collected = {e[0].lower() for e in a.binaries}
    for _dll in ('msvcp140.dll', 'msvcp140_1.dll'):
        if _dll in _collected:
            print(f"[spec] {_dll}: PyInstaller가 이미 넣음")
            continue
        _src = os.path.join(os.environ['SystemRoot'], 'System32', _dll)
        if not os.path.isfile(_src):
            raise SystemExit(f"[spec] {_dll}을 찾을 수 없습니다: {_src} (Visual C++ 2015-2022 재배포 패키지 필요)")
        a.binaries.append((_dll, _src, 'BINARY'))
        print(f"[spec] {_dll}: 의존성 분석에 없어 직접 추가 ({_src})")

pyz = PYZ(a.pure)

# onedir 모드: 라이브러리를 실행 파일에 넣지 않고 COLLECT로 Contents/Frameworks에 펼침
# (onefile은 실행할 때마다 임시 폴더에 압축을 풀고, 번들 바이너리 검사도 할 수 없음)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='YesonCheck_Autocut',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=not IS_WINDOWS,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico' if IS_WINDOWS else None,
    version='windows_version_info.txt' if IS_WINDOWS else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='YesonCheck_Autocut',
)

if not IS_WINDOWS:
    app = BUNDLE(
        coll,
        name='YesonCheck_Autocut.app',
        icon='icon.icns',
        bundle_identifier='com.yeson.check',
        # BUNDLE은 dict만 병합함 (파일 경로 문자열은 무시됨)
        info_plist={'LSMinimumSystemVersion': MIN_MACOS},
    )

