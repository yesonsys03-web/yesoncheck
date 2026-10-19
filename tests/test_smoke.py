import json
import os
import subprocess
import sys

import pytest

from tests.conftest import ROOT


@pytest.mark.skipif(sys.platform == "win32", reason="Windows는 CI가 빌드된 exe로 실행 (ci/run_smoke_test.ps1)")
def test_smoke_from_source(tmp_path):
    share = tmp_path / "share"
    workdir = tmp_path / "work"
    subprocess.run([sys.executable, os.path.join(ROOT, "ci", "make_test_data.py"),
                    "--share-root", str(share), "--mac-root", str(share), "--workdir", str(workdir)], check=True)
    env = dict(os.environ, YESONCHECK_CONFIG_DIR=str(share / ".yesoncheck"), QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable, "-m", "yesoncheck.app", "--smoke-test", str(workdir)],
                            cwd=ROOT, env=env, timeout=900)
    report = json.loads((workdir / "smoke_result.json").read_text(encoding="utf-8"))
    failed = [c for c in report["checks"] if not c["ok"]]
    assert result.returncode == 0 and not failed and not report["dialogs"], json.dumps(report, ensure_ascii=False, indent=2)


def test_manifest_long_path_aware_needs_true():
    from yesoncheck.smoke_test import manifest_long_path_aware

    ns = b'xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings"'
    assert manifest_long_path_aware(b"<windowsSettings><longPathAware " + ns + b">true</longPathAware></windowsSettings>")
    assert manifest_long_path_aware(b"<ws2:longPathAware " + ns + b">\r\n  true\r\n</ws2:longPathAware>")
    assert not manifest_long_path_aware(b"<longPathAware " + ns + b">false</longPathAware>")
    assert not manifest_long_path_aware(b"... longPathAware ...")


def test_ocr_model_files(tmp_path):
    from yesoncheck.smoke_test import ocr_model_files

    with pytest.raises(AssertionError, match="OCR 모델 폴더가 없습니다"):
        ocr_model_files(str(tmp_path))
    (tmp_path / "whl" / "det" / "en").mkdir(parents=True)
    with pytest.raises(AssertionError, match="OCR 모델 폴더가 비어 있습니다"):
        ocr_model_files(str(tmp_path))
    (tmp_path / "whl" / "det" / "en" / "inference.pdmodel").write_bytes(b"x")
    assert ocr_model_files(str(tmp_path)) == [os.path.join("whl", "det", "en", "inference.pdmodel")]


def test_app_version_check(monkeypatch):
    """실행 시험의 '앱 버전': 빌드된 앱이 읽은 버전(build_info.json)이 기대 버전이고 창 제목에 보이는지."""
    from yesoncheck import build_info
    from yesoncheck.smoke_test import app_version

    with pytest.raises(AssertionError, match="소스 실행"):
        app_version("1.1.0", "Yeson Checker")
    monkeypatch.setattr(build_info, "current",
                        lambda: build_info.BuildInfo("1.1.0+0f4d3d7", "0f4d3d7" + "0" * 33, "2026-10-20T10:00:00+09:00", "windows"))
    assert app_version("1.1.0+0f4d3d7", "Yeson Checker 1.1.0+0f4d3d7")["version"] == "1.1.0+0f4d3d7"
    with pytest.raises(AssertionError, match="기대 1.1.0"):
        app_version("1.1.0", "Yeson Checker 1.1.0+0f4d3d7")
    with pytest.raises(AssertionError, match="창 제목"):
        app_version("1.1.0+0f4d3d7", "Yeson Checker")


@pytest.mark.parametrize("extra", [["--auto-connect", "--expect-version", "1.1.0"], ["--expect-version", ""]])
def test_make_test_data_rejects_unused_expect_version(tmp_path, extra):
    """기대 버전은 기본 시나리오만 확인 → 자동 연결 시험이나 빈 값이면 조용히 무시하지 않고 멈춤."""
    result = subprocess.run([sys.executable, os.path.join(ROOT, "ci", "make_test_data.py"), "--share-root", str(tmp_path),
                             "--mac-root", str(tmp_path), "--workdir", str(tmp_path / "work"), *extra],
                            capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert result.returncode == 2 and "--expect-version" in result.stderr, result.stderr
    assert not (tmp_path / "work").exists()
