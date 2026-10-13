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
