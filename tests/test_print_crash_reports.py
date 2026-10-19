"""ci/print_crash_reports.py: Mac CI가 실패했을 때 macOS 충돌 보고서(.ips)에서 죽은 스레드의 스택을 출력 (진단용 도구)."""

import importlib.util
import json
import os

from tests.conftest import ROOT

TOOL = os.path.join(ROOT, "ci", "print_crash_reports.py")
JOB_START = 1_800_000_000


def load_tool():
    """ci/print_crash_reports.py를 모듈로 불러옴 (ci는 패키지가 아니므로 파일 경로로)."""
    spec = importlib.util.spec_from_file_location("print_crash_reports", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_report(folder, name, header, body, mtime=JOB_START + 60):
    path = folder / name
    path.write_text(json.dumps(header) + "\n" + (json.dumps(body) if body is not None else ""), encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


CRASH = {
    "procName": "python3.10", "procPath": "/Users/*/python3.10", "captureTime": "2026-10-20 10:00:00 +0900",
    "exception": {"type": "EXC_BAD_ACCESS", "signal": "SIGSEGV", "subtype": "KERN_INVALID_ADDRESS at 0x10"},
    "termination": {"indicator": "Segmentation fault: 11"},
    "faultingThread": 1,
    "threads": [{"frames": []}, {"name": "OCRWorker", "frames": [
        {"imageIndex": 0, "symbol": "sgemm_itcopy", "symbolLocation": 12, "imageOffset": 4096},
        {"imageIndex": 1, "imageOffset": 255},
    ]}],
    "usedImages": [{"name": "libphi.dylib"}, {"name": "libpaddle.so"}],
}


def run(tool, capsys, *args):
    tool.main(list(args))
    return capsys.readouterr().out


def test_prints_faulting_thread_frames(tmp_path, capsys):
    write_report(tmp_path, "python3.10-1.ips", {"app_name": "python3.10", "bug_type": "309"}, CRASH)
    out = run(load_tool(), capsys, str(tmp_path))
    assert "EXC_BAD_ACCESS SIGSEGV KERN_INVALID_ADDRESS at 0x10" in out
    assert "죽은 스레드 1 (이름 'OCRWorker'" in out
    assert "libphi.dylib" in out and "sgemm_itcopy + 12" in out
    assert "libpaddle.so" in out and "+255" in out
    assert "충돌 보고서 1개 출력" in out


def test_missing_parts_and_unreadable_reports_do_not_stop_the_rest(tmp_path, capsys):
    """CI 러너의 coreaudiod 보고서처럼 usedImages·threads가 없어도, JSON이 깨져도 멈추지 않고 있는 것만 출력."""
    partial = {k: v for k, v in CRASH.items() if k != "usedImages"}
    write_report(tmp_path, "a.ips", {"app_name": "python3.10"}, partial, mtime=JOB_START + 1)
    write_report(tmp_path, "b.ips", {"app_name": "python3.10"}, {"procName": "python3.10"}, mtime=JOB_START + 2)
    (tmp_path / "c.ips").write_text("{not json", encoding="utf-8")
    os.utime(tmp_path / "c.ips", (JOB_START + 3, JOB_START + 3))
    write_report(tmp_path, "d.ips", {"app_name": "YesonCheck_Autocut"}, CRASH, mtime=JOB_START + 4)
    out = run(load_tool(), capsys, str(tmp_path))
    assert "?                              sgemm_itcopy + 12" in out  # 라이브러리 이름 없이 함수는 보임
    assert "죽은 스레드 정보 없음" in out
    assert "c.ips\n이 보고서를 읽지 못함:" in out and "JSONDecodeError" in out
    assert out.count("libphi.dylib") == 1  # d.ips까지 출력됨
    assert "충돌 보고서 4개 출력" in out


def test_only_reports_of_this_job_and_our_processes(tmp_path, capsys):
    """러너 이미지에 원래 있던 오래된 보고서와 다른 프로그램(coreaudiod 등)의 보고서는 건너뛰고 몇 개인지만 알림."""
    write_report(tmp_path, "python3.10-old.ips", {"app_name": "python3.10"}, CRASH, mtime=JOB_START - 3600)
    write_report(tmp_path, "coreaudiod-1.ips", {"app_name": "coreaudiod"}, dict(CRASH, procName="coreaudiod"))
    write_report(tmp_path, "YesonCheck_Autocut-1.ips", {"app_name": "YesonCheck_Autocut"},
                 dict(CRASH, procName="YesonCheck_Autocut"))
    write_report(tmp_path, "python3.10-new.ips", {"app_name": "python3.10"}, CRASH)
    out = run(load_tool(), capsys, "--since", str(JOB_START), "--process", "python3", "--process", "YesonCheck_Autocut",
              str(tmp_path))
    assert "YesonCheck_Autocut-1.ips" in out and "python3.10-new.ips" in out
    assert "python3.10-old.ips" not in out and "coreaudiod-1.ips" not in out
    assert "충돌 보고서 2개 출력" in out and "--since 이전 1개" in out and "다른 프로세스 1개 ['coreaudiod']" in out


def test_no_reports(tmp_path, capsys):
    out = run(load_tool(), capsys, str(tmp_path / "없는 폴더"))
    assert "충돌 보고서 0개 출력" in out
