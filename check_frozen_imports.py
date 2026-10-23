"""빌드된 앱에 실행 중 필요한 파이썬 모듈이 모두 들어 있는지 검사합니다.

빌드 환경(소스)에서 앱이 쓰는 경로를 실제로 실행해 불러온 모듈을 모은 뒤,
빌드된 앱 안에 같은 모듈이 있는지 대조합니다. PyInstaller가 정적 분석으로 놓친 모듈
(예: setuptools 내부의 jaraco.collections)이 있으면 앱이 실행 중에 "No module named ..."로
실패하므로 빌드 단계에서 잡습니다.

실행하는 경로:
- yesoncheck 소스에 있는 모든 import (함수 안의 지연 import 포함)
- PaddleOCR 생성 + 인식 (앱의 King 모드 설정, 모델이 없으면 ~/.paddleocr에 내려받음)
- paddle 3.0 입력 크기 변화 버그 회피(yesoncheck.workers.guard_paddle_buffer_growth)가 통하는지
- PySceneDetect 씬 감지 (임시 합성 영상)
- 애니매틱2: TensorFlow + TransNetV2 씬 감지 (합성 3샷 영상, 씬 시작 [0, 30, 60]이어야 함).
  TensorFlow나 가중치(vendor/transnetv2-weights)가 빌드 환경에 없으면 검사 실패
- 이미지 시퀀스: TGA(RLE)·EXR 프레임 한 장씩 디코딩 (yesoncheck.sequence_source.decode_frame, 메모리에서 만든 작은 프레임).
  PIL 이미지 플러그인(PIL.TgaImagePlugin 등)은 지연 import라 소스 import만으로는 쓰인 모듈에 안 잡히므로, 실제로 디코딩해서 앱에 있는지 대조함

사용법: python check_frozen_imports.py <앱 번들(.app) 또는 Windows 앱 폴더(dist\\YesonCheck_Autocut)>
누락이 하나라도 있으면 목록을 출력하고 종료 코드 1로 끝납니다.
"""

import ast
import glob
import importlib
import os
import plistlib
import sys
import sysconfig
import tempfile
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

SITE_DIRS = {os.path.realpath(sysconfig.get_paths()[k]) for k in ("purelib", "platlib")}
STDLIB_DIR = os.path.realpath(sysconfig.get_paths()["stdlib"])

# 앱에 없어도 되는 모듈: 불러오는 쪽이 ImportError를 처리함 (이유를 반드시 적을 것)
OPTIONAL_MODULES = {
    "Cython._shared": "setuptools/command/build_ext.py가 Cython을 try/except로 시도, 없으면 distutils판 사용",
    "_shared": "Cython._shared와 같은 파일 (위와 동일)",
}


def spec_excludes():
    """YesonCheck_Autocut.spec의 Analysis(excludes=[...]) 목록을 읽습니다."""
    with open(os.path.join(PROJECT_ROOT, "YesonCheck_Autocut.spec"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Analysis":
            for kw in node.keywords:
                if kw.arg == "excludes":
                    return set(ast.literal_eval(kw.value))
    raise SystemExit("spec에서 Analysis(excludes=...)를 찾지 못했습니다")


class BlockExcluded:
    """spec에서 제외한 모듈은 빌드된 앱처럼 소스 실행에서도 import 실패로 만듭니다."""

    def __init__(self, names):
        self.names = names

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in self.names:
            raise ModuleNotFoundError(f"No module named '{fullname}' (spec excludes)", name=fullname)
        return None


def source_imports():
    """yesoncheck 패키지 소스의 모든 절대 import 모듈 이름을 모읍니다."""
    names = set()
    for path in glob.glob(os.path.join(PROJECT_ROOT, "yesoncheck", "*.py")):
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module)
    return sorted(names)


def exercise_sequence_decode():
    """이미지 시퀀스 프레임을 TGA·EXR 한 장씩 앱의 디코더(sequence_source.decode_frame)로 읽어 봅니다. 읽은 확장자 목록을 돌려줌.

    PIL은 이미지 플러그인(TgaImagePlugin 등)을 처음 쓸 때 지연 import하므로, 실제로 디코딩하지 않으면 그 모듈이
    '실행에 쓰인 모듈'에 안 잡혀 빌드된 앱에 빠져도 모른다. 여기서 읽으면 쓰인 모듈에 올라 main()이 앱 안에 있는지 대조한다.
    EXR은 cv2의 EXR 인코더·디코더가 이 환경의 cv2에 있는지 확인 (cv2는 앱에 같은 휠로 들어감).
    디코더가 내는 오류는 잡지 않고 그대로 올림 (스택 트레이스째 검사 실패). 부르기 전에 PROJECT_ROOT가 sys.path에 있어야 함.
    """
    import io

    import cv2
    import numpy as np
    from PIL import Image

    # sequence_source를 먼저 불러야 함: OPENCV_IO_ENABLE_OPENEXR을 cv2의 첫 EXR 인코딩·디코딩 전에 정함
    from yesoncheck import sequence_source

    decoded = []
    tga = io.BytesIO()
    Image.new("RGB", (8, 4), (10, 200, 30)).save(tga, format="TGA", compression="tga_rle")  # 앱의 시퀀스 TGA처럼 RLE
    frame = sequence_source.decode_frame(tga.getvalue(), "tga")
    if frame.shape != (4, 8, 3) or tuple(frame[0, 0]) != (30, 200, 10):  # BGR
        raise SystemExit(f"TGA 프레임 디코딩 결과가 다릅니다: 모양 {frame.shape}, 첫 픽셀 {tuple(frame[0, 0])} (기대 (4, 8, 3), (30, 200, 10))")
    decoded.append("tga")

    ok, exr = cv2.imencode(".exr", np.full((4, 8, 3), (0.0, 1.0, 2.0), np.float32))
    if not ok:
        raise SystemExit("이 환경의 cv2가 EXR을 인코딩하지 못합니다 (OpenEXR 지원 확인 필요)")
    frame = sequence_source.decode_frame(exr.tobytes(), "exr")
    if frame.shape != (4, 8, 3) or tuple(frame[0, 0]) != (0, 255, 255):  # 0~1 밖의 값은 잘라내기만 함
        raise SystemExit(f"EXR 프레임 디코딩 결과가 다릅니다: 모양 {frame.shape}, 첫 픽셀 {tuple(frame[0, 0])} (기대 (4, 8, 3), (0, 255, 255))")
    decoded.append("exr")
    return decoded


def exercise_app():
    """앱이 실행 중에 거치는 경로를 소스 환경에서 실행합니다."""
    sys.path.insert(0, PROJECT_ROOT)
    sys.meta_path.insert(0, BlockExcluded(spec_excludes()))
    skipped = []
    for name in source_imports():
        try:
            importlib.import_module(name)
        except ImportError as exc:
            # 앱이 부르지 않는 함수 안의 선택 import(transnetv2_model.predict_video의 ffmpeg 등)는 건너뜀 (목록은 출력함).
            # TensorFlow는 여기서 건너뛰어도 아래 애니매틱2 실행에서 다시 불러 실패가 드러남
            skipped.append(f"{name} ({exc})")

    frame_formats = exercise_sequence_decode()  # 가볍고 PIL 플러그인 누락을 바로 잡으므로 느린 OCR 앞에서

    import cv2
    import numpy as np
    from paddleocr import PaddleOCR

    image = np.full((120, 700, 3), 255, np.uint8)
    cv2.putText(image, "Seq 02A_S09 - Panel 6", (15, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3)
    engine = PaddleOCR(
        use_angle_cls=True, lang="en", show_log=False, use_gpu=False, use_mp=True, total_process_num=2,
        det_db_thresh=0.3, det_db_box_thresh=0.5, rec_batch_num=16, use_space_char=True,
    )
    result = engine.ocr(image, cls=True)
    texts = [line[1][0] for line in (result[0] or [])]
    if not texts:
        raise SystemExit("OCR 실행 결과가 비어 있습니다 (빌드 환경의 PaddleOCR 확인 필요)")

    # 앱의 paddle 3.0 버그 회피(guard_paddle_buffer_growth)가 이 Mac의 paddle에서 통하는지 확인:
    # 새 엔진에 입력 크기(배치·폭)가 여러 번 커지는 순서를 넣음 (회피가 없으면 paddle 3.0.0은 4번째에서 실패)
    from yesoncheck.workers import guard_paddle_buffer_growth

    fresh = PaddleOCR(use_angle_cls=False, lang="en", show_log=False, use_gpu=False, rec_batch_num=16, use_space_char=True)
    guard_paddle_buffer_growth(fresh)
    rec = fresh.text_recognizer
    for batch, width in [(1, 320), (2, 320), (1, 320), (3, 320), (1, 640), (1, 320), (1, 960), (4, 960), (2, 1280)]:
        rec.input_tensor.copy_from_cpu(np.random.rand(batch, 3, 48, width).astype("float32"))
        try:
            rec.predictor.run()
        except RuntimeError as exc:
            raise SystemExit(f"paddle 입력 크기 변화 회피 실패 (배치 {batch}, 폭 {width}): {exc}") from exc
        for output in rec.output_tensors:  # 앱(paddleocr)처럼 실행 후 출력을 읽음
            output.copy_to_cpu()

    from yesoncheck.auto_trim import detect_scene_cuts

    with tempfile.TemporaryDirectory() as tmp:
        video = os.path.join(tmp, "cuts.mp4")
        writer = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"mp4v"), 24, (320, 180))
        for i in range(72):
            writer.write(np.full((180, 320, 3), 0 if i < 36 else 255, np.uint8))
        writer.release()
        detect_scene_cuts(video, min_scene_len=5)

    # 애니매틱2(TransNetV2): 앱에 반드시 들어가야 하므로 빌드 환경에 없으면 검사를 실패로 끝냄
    from yesoncheck.smoke_test import THREE_SHOT_STARTS, write_three_shot_clip
    from yesoncheck.transnetv2_detector import detect_scene_cuts_transnetv2, transnetv2_missing

    missing = transnetv2_missing()
    if missing:
        raise SystemExit(f"애니매틱2(TransNetV2)에 필요한 것이 빌드 환경에 없습니다: {missing}")
    with tempfile.TemporaryDirectory() as tmp:
        clip = write_three_shot_clip(os.path.join(tmp, "three_shots.mp4"))
        # 앱(player_base의 애니매틱2 분석)과 같은 설정
        segments = detect_scene_cuts_transnetv2(clip, threshold=0.3, min_scene_len=10,
                                                detect_gradual_transitions=True, post_process_histogram=True)
    cuts = [segment["start_frame"] for segment in segments]
    if cuts != THREE_SHOT_STARTS:
        raise SystemExit(f"TransNetV2 씬 감지 결과가 다릅니다: 씬 시작 {cuts} (기대 {THREE_SHOT_STARTS})")
    return texts, cuts, skipped, frame_formats


def frozen_contents(bundle):
    """빌드된 앱의 PYZ·base_library.zip 모듈 이름과 라이브러리 폴더 파일 경로를 모읍니다.

    Mac: <앱>.app (Contents/MacOS/<실행 파일>, Contents/Frameworks)
    Windows: dist\\YesonCheck_Autocut 폴더 (YesonCheck_Autocut.exe, _internal)
    """
    from PyInstaller.archive.readers import CArchiveReader

    if sys.platform == "win32":
        exe = os.path.join(bundle, "YesonCheck_Autocut.exe")
        lib_dir = os.path.join(bundle, "_internal")
    else:
        with open(os.path.join(bundle, "Contents", "Info.plist"), "rb") as fh:
            exe_name = plistlib.load(fh)["CFBundleExecutable"]
        exe = os.path.join(bundle, "Contents", "MacOS", exe_name)
        lib_dir = os.path.join(bundle, "Contents", "Frameworks")
    pkg = CArchiveReader(exe)
    pyz_name = next(n for n in pkg.toc if n.endswith(".pyz"))
    modules = set(pkg.open_embedded_archive(pyz_name).toc)

    with zipfile.ZipFile(os.path.join(lib_dir, "base_library.zip")) as zf:
        for entry in zf.namelist():
            if entry.endswith(".pyc"):
                name = entry[:-4].replace("/", ".")
                modules.add(name[: -len(".__init__")] if name.endswith(".__init__") else name)

    files = set()
    # Mac: 데이터 폴더는 Contents/Resources에 있고 Frameworks에서 심볼릭 링크로 연결됨 → 링크를 따라감
    for root, _dirs, names in os.walk(lib_dir, followlinks=True):
        for name in names:
            files.add(os.path.normcase(os.path.relpath(os.path.join(root, name), lib_dir)))
    return modules, files


_WIN_EXT_DIR_CACHE = []


def win_stdlib_ext_dir():
    """Windows 표준 확장 모듈(.pyd, 예: _ctypes·_socket)이 실제로 있는 폴더.

    `sys.base_prefix\\DLLs`라고 가정하지 않는다: uv 매니지드 파이썬의 venv는
    sys.base_prefix가 실제 설치 경로와 다르게(혹은 다른 표기로) 잡힐 수 있어
    (CI에서 _ctypes 등 13개 표준 확장 모듈이 모두 이 가정으로 위치 계산 실패) 빗나갈 수 있다.
    대신 항상 내장되는 표준 확장 모듈(_socket)의 __file__을 realpath해 그 폴더를 역산한다.
    다른 모듈 경로를 realpath하는 방식과 같은 방법이라 root 비교가 어긋나지 않는다.
    """
    if not _WIN_EXT_DIR_CACHE:
        import _socket
        _WIN_EXT_DIR_CACHE.append(os.path.dirname(os.path.realpath(_socket.__file__)))
    return _WIN_EXT_DIR_CACHE[0]


def module_name_from_path(path):
    """site-packages 아래 모듈 파일 경로 → 그 파일의 실제 모듈 이름 (계산할 수 없으면 None).

    예: …/site-packages/tensorflow/_api/v2/compat/v1/__init__.py → tensorflow._api.v2.compat.v1
    """
    path = os.path.realpath(path)
    for site in SITE_DIRS:
        if path.startswith(site + os.sep):
            stem, ext = os.path.splitext(os.path.relpath(path, site))
            if ext not in (".py", ".pyc"):
                return None
            parts = stem.split(os.sep)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            return ".".join(parts)
    return None


def tensorflow_alias_of(name, file_attr, modules):
    """TensorFlow가 같은 파일을 다른 이름으로도 등록한 모듈이면 앱(PYZ)에 있는 실제 이름, 아니면 None.

    예: tensorflow.compat.v1 → 파일 tensorflow/_api/v2/compat/v1/__init__.py → tensorflow._api.v2.compat.v1.
    tensorflow. 이름공간에만 적용 (다른 패키지의 진짜 누락을 별칭으로 가리지 않게).
    """
    if not name.startswith("tensorflow."):
        return None
    real_name = module_name_from_path(file_attr)
    if real_name and real_name != name and real_name in modules:
        return real_name
    return None


def frozen_location(name, path, is_package_dir=False, debug=None):
    """소스 환경의 모듈 위치를 빌드된 앱 Contents/Frameworks 기준 상대 경로로 바꿉니다.

    경로는 모듈 이름에서 계산합니다 (ppocr.utils.network → <루트>/ppocr/utils/network.py).
    루트가 site-packages 아래면 앱에서도 같은 상대 위치(paddleocr 등)에 있어야 합니다.
    계산할 수 없으면 None.

    debug: None 또는 dict. 계산에 실패했을 때(None 반환) 진단 정보(root, base_prefix,
    win_stdlib_ext_dir 등)를 채워 넣습니다 (호출부가 오류 메시지에 포함시킴).
    """
    path = os.path.realpath(path)
    parts = name.split(".")
    base = os.path.basename(path)
    if is_package_dir:
        rel = os.path.join(*parts)
    elif base.startswith("__init__."):
        rel = os.path.join(*parts, base)
    else:
        rel = os.path.join(*parts[:-1], base)
    if not os.path.normcase(path).endswith(os.path.normcase(os.sep + rel)):
        return None
    root = path[: -len(os.sep + rel)]
    if debug is not None:
        debug["root"] = root
        debug["base_prefix"] = getattr(sys, "base_prefix", None)
    for site in SITE_DIRS:
        if root == site or root.startswith(site + os.sep):
            return os.path.normcase(os.path.normpath(os.path.join(os.path.relpath(root, site), rel)))
    if sys.platform == "win32":
        ext_dir = win_stdlib_ext_dir()
        if debug is not None:
            debug["win_stdlib_ext_dir"] = ext_dir
        if os.path.normcase(root) == os.path.normcase(ext_dir):
            return os.path.normcase(rel)
    if root == os.path.join(STDLIB_DIR, "lib-dynload"):
        return os.path.normcase(os.path.join("lib-dynload", rel))
    if root in (STDLIB_DIR, PROJECT_ROOT):
        return os.path.normcase(rel)
    return None


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    bundle = sys.argv[1]

    baseline = set(sys.modules)  # 인터프리터 시작 시 모듈(.pth 포함)은 앱과 무관
    texts, cuts, skipped, frame_formats = exercise_app()
    used = {name: mod for name, mod in sys.modules.items() if name not in baseline and mod is not None}

    modules, files = frozen_contents(bundle)
    missing = []
    aliases = []  # (이름, 앱에 있는 실제 이름) — 별칭으로 통과시킨 모듈은 모두 출력함
    for name, mod in sorted(used.items()):
        # 별칭 등록(requests.packages.urllib3 → urllib3 등)은 같은 객체가 실제 이름으로 검사되므로 건너뜀
        # (paddle._C_ops처럼 __name__만 바뀐 실제 모듈은 객체가 달라 계속 검사됨)
        real_name = getattr(mod, "__name__", name)
        if real_name != name and used.get(real_name) is mod:
            continue
        if name in sys.builtin_module_names or name in modules or name in OPTIONAL_MODULES or name == "__mp_main__":
            continue
        # distutils는 앱에서 setuptools의 내장판(setuptools._distutils)으로 연결됨
        if name.split(".")[0] == "distutils" and "setuptools._distutils" + name[len("distutils"):] in modules:
            continue
        file_attr = getattr(mod, "__file__", None)
        if file_attr is None:
            pkg_paths = list(getattr(mod, "__path__", None) or [])
            if not pkg_paths:
                # 파일 없이 실행 중 만들어지는 모듈(cv2.aruco, _cython_3_x, six.moves 등) → 부모가 제공
                continue
            # 네임스페이스 패키지: 하위 모듈이 PYZ에 있거나 같은 폴더가 앱에 있으면 충분
            if any(m.startswith(name + ".") for m in modules):
                continue
            rel_dirs = [frozen_location(name, p, is_package_dir=True) for p in pkg_paths]
            if any(r and any(f.startswith(r + os.sep) for f in files) for r in rel_dirs):
                continue
            missing.append(f"{name} (네임스페이스 패키지 {pkg_paths})")
            continue
        debug = {}
        rel = frozen_location(name, file_attr, debug=debug)
        if rel is None or rel not in files:
            # 같은 파일이 다른 이름으로도 등록된 TensorFlow 모듈 (tensorflow.compat.v1 ↔ 실제 파일
            # tensorflow/_api/v2/compat/v1/__init__.py): 파일 경로가 가리키는 실제 이름이 앱(PYZ)에 있으면 됨
            alias_of = tensorflow_alias_of(name, file_attr, modules)
            if alias_of:
                aliases.append((name, alias_of))
                continue
        if rel is None:
            detail = ", ".join(f"{k}={v}" for k, v in debug.items())
            missing.append(f"{name} (앱 안 위치를 계산할 수 없음: {file_attr} [{detail}])")
        elif rel not in files:
            missing.append(f"{name} (앱에 {rel} 없음)")

    print(f"앱 경로 실행: OCR 결과 {texts}, 애니매틱2(TransNetV2) 씬 시작 {cuts}, 시퀀스 프레임 디코딩 {frame_formats}, 사용 모듈 {len(used)}개")
    if aliases:
        print(f"TensorFlow 별칭 모듈 {len(aliases)}개 (같은 파일이 앱에는 실제 이름으로 들어 있어 통과):")
        for name, real_name in aliases:
            print(f"  {name} → {real_name}")
    if skipped:
        print(f"소스 환경에도 없어 건너뛴 선택 모듈 {len(skipped)}개:")
        for line in skipped:
            print(f"  {line}")
    if missing:
        print(f"빌드된 앱에 없는 모듈 {len(missing)}개 (실행 중 'No module named' 오류 가능):")
        for line in missing:
            print(f"  {line}")
        return 1
    print("통과: 실행에 쓰인 모듈이 모두 앱에 들어 있습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
