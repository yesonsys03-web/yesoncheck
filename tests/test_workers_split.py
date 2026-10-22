"""workers.py를 워커별 모듈로 나눈 뒤에도 지켜야 할 것: 앱 시작 때의 import 시점, 평면 구조.

- 앱 시작 때 불리는 player_sidebar가 (sidebar_thumbnails를 거쳐) yesoncheck.workers를 부르면, 다시 내보내기만 하는 workers가 scene_workers까지 바로
  불러 scenedetect(auto_trim)·transnetv2_detector가 나누기 전처럼 시작 때 불려야 함 (늦게 불리게 바뀌면 그 import 오류가
  첫 애니매틱 분석 때에야 드러남). TensorFlow는 여전히 시작 때 불리지 않아야 함 (첫 애니매틱2 분석 때만).
- 새 모듈은 yesoncheck/ 바로 아래(평면)에 있어야 함: check_frozen_imports.py·tests/test_runtime.py의 비재귀 glob은
  하위 패키지 안의 모듈을 보지 못해 검사 범위가 말없이 좁아짐.
"""

import glob
import json
import os
import subprocess
import sys

from tests.conftest import ROOT

NEW_MODULES = ["ffmpeg_worker", "thumbnail_workers", "ocr_worker", "ocr_export_worker", "scene_workers"]

_STARTUP_CODE = r"""
import json
import sys

sys.path.insert(0, sys.argv[1])
import yesoncheck.player_sidebar

names = ["yesoncheck.workers", "yesoncheck.scene_workers", "scenedetect", "yesoncheck.transnetv2_detector", "tensorflow"]
print("REPORT " + json.dumps({name: name in sys.modules for name in names}))
"""


def test_startup_imports_unchanged():
    """pytest 프로세스는 다른 시험이 이미 불렀을 수 있으므로 새 파이썬 프로세스에서 player_sidebar만 불러 확인한다."""
    # PYTHONIOENCODING: 자식 프로세스의 출력을 utf-8로 (Windows 기본 코드 페이지에서도 읽을 수 있게)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-c", _STARTUP_CODE, ROOT], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    lines = [line for line in result.stdout.splitlines() if line.startswith("REPORT ")]
    assert len(lines) == 1, result.stdout
    loaded = json.loads(lines[0][len("REPORT "):])
    assert loaded == {
        "yesoncheck.workers": True,
        "yesoncheck.scene_workers": True,
        "scenedetect": True,
        "yesoncheck.transnetv2_detector": True,
        "tensorflow": False,
    }, loaded


def test_new_modules_visible_to_flat_glob():
    """check_frozen_imports.py·tests/test_runtime.py와 같은 비재귀 glob(yesoncheck/*.py)에 새 모듈 5개가 모두 보임."""
    found = {os.path.splitext(os.path.basename(path))[0] for path in glob.glob(os.path.join(ROOT, "yesoncheck", "*.py"))}
    missing = [name for name in NEW_MODULES if name not in found]
    assert missing == [], missing
