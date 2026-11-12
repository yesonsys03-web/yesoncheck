"""ci/print_crash_reports.py: Mac CI가 실패했을 때 macOS 충돌 보고서(.ips)에서 죽은 스레드의 스택을 출력 (진단용 도구)."""

import importlib.util
import json
import os

import pytest

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


# ---------------------------------------------------------------- --wait: macOS가 보고서를 쓸 때까지 기다림


STEP_START = JOB_START + 600  # '충돌 보고서' 단계가 시작된 시각 — job을 시작한 지 10분 뒤
EARLIER = JOB_START + 60  # 그보다 9분 전: 시험이 일부러 죽인 파이썬의 보고서가 쓰인 때


class FakeTime:
    """가짜 시계와 sleep — sleep할 때마다 시각을 그만큼 보내고, 정해 둔 시각에 일(보고서가 생김)을 일으킴.
    clock은 기다림을 재는 시계, time은 보고서 파일의 고친 시각과 견줄 벽시계(단계가 시작될 때 STEP_START)."""

    def __init__(self, happenings=()):
        self.now = 1000.0
        self.sleeps = []
        self.happenings = sorted(happenings, key=lambda pair: pair[0])  # [(몇 초 뒤, 할 일)]

    def clock(self):
        return self.now

    def time(self):
        return STEP_START + (self.now - 1000.0)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
        while self.happenings and self.now - 1000.0 >= self.happenings[0][0]:
            self.happenings.pop(0)[1]()


def run_waiting(tool, capsys, fake, *args, settle="0"):
    """가짜 시계로 도구를 돌림. settle: 방금 쓰인 보고서를 본 뒤 더 지켜보는 시간(--settle) — 기다림 자체를 보는 시험은 0으로 두고 sleep 차례를
    정확히 단언, None이면 도구의 기본값."""
    extra = [] if settle is None else ["--settle", settle]
    tool.main(extra + list(args), sleep=fake.sleep, clock=fake.clock, now=fake.time)
    return capsys.readouterr().out


def crash_now(fake, folder, name="python3.10-1.ips", app="python3.10"):
    """지금(가짜 벽시계) 쓰인 보고서 — 방금 죽은 프로세스의 것."""
    return lambda: write_report(folder, name, {"app_name": app}, dict(CRASH, procName=app), mtime=fake.time())


def test_without_wait_it_never_sleeps(tmp_path, capsys):
    fake = FakeTime()
    out = run_waiting(load_tool(), capsys, fake, str(tmp_path))
    assert "충돌 보고서 0개 출력" in out and fake.sleeps == [] and "기다림" not in out


def test_waits_until_the_report_is_written(tmp_path, capsys):
    """pytest가 세그폴트로 죽은 직후에는 보고서가 아직 없음 — 생길 때까지 기다렸다가 스택을 출력."""
    fake = FakeTime()
    fake.happenings = [(7, crash_now(fake, tmp_path))]
    out = run_waiting(load_tool(), capsys, fake, "--since", str(JOB_START), "--process", "python3", "--wait", "120", str(tmp_path))
    assert "sgemm_itcopy + 12" in out and "충돌 보고서 1개 출력" in out
    assert fake.sleeps == [2.0, 2.0, 2.0, 2.0] and "기다림 8초(최대 120초)" in out


def test_gives_up_at_the_deadline(tmp_path, capsys):
    fake = FakeTime()
    out = run_waiting(load_tool(), capsys, fake, "--wait", "5", "--poll", "2", str(tmp_path))
    assert "충돌 보고서 0개 출력" in out and "기다림 5초(최대 5초)" in out
    assert fake.sleeps == [2.0, 2.0, 1.0]  # 기한을 넘겨 자지 않음


def test_a_report_still_being_written_does_not_end_the_wait(tmp_path, capsys):
    """쓰는 중이라 JSON이 덜 된 보고서는 '아직 없음' — 다 써지면 그 스택을 출력 (읽지 못함으로 끝내지 않음)."""
    def start_writing():
        (tmp_path / "python3.10-1.ips").write_text('{"app_name": "python3.10"}\n{"procName": "pyth', encoding="utf-8")
        os.utime(tmp_path / "python3.10-1.ips", (fake.time(), fake.time()))

    fake = FakeTime()
    fake.happenings = [(2, start_writing), (6, crash_now(fake, tmp_path))]
    out = run_waiting(load_tool(), capsys, fake, "--since", str(JOB_START), "--process", "python3", "--wait", "60", str(tmp_path))
    assert "sgemm_itcopy + 12" in out and "읽지 못함" not in out and len(fake.sleeps) == 3


def test_an_unreadable_report_is_still_reported_at_the_deadline(tmp_path, capsys):
    (tmp_path / "broken.ips").write_text("{not json", encoding="utf-8")
    fake = FakeTime()
    out = run_waiting(load_tool(), capsys, fake, "--wait", "4", str(tmp_path))
    assert "broken.ips\n이 보고서를 읽지 못함:" in out and "충돌 보고서 1개 출력" in out and fake.sleeps == [2.0, 2.0]


def test_another_programs_report_does_not_end_the_wait(tmp_path, capsys):
    """러너의 다른 프로그램(coreaudiod 등)이 그사이 죽어도 우리 프로세스의 보고서를 계속 기다림."""
    write_report(tmp_path, "coreaudiod-1.ips", {"app_name": "coreaudiod"}, dict(CRASH, procName="coreaudiod"), mtime=STEP_START - 1)
    fake = FakeTime()
    fake.happenings = [(4, crash_now(fake, tmp_path))]
    out = run_waiting(load_tool(), capsys, fake, "--since", str(JOB_START), "--process", "python3", "--wait", "60", str(tmp_path))
    assert "python3.10-1.ips" in out and "coreaudiod-1.ips" not in out and "다른 프로세스 1개 ['coreaudiod']" in out
    assert fake.sleeps == [2.0, 2.0]


def test_an_earlier_report_of_ours_does_not_end_the_wait(tmp_path, capsys):
    """시험이 일부러 죽인 파이썬(test_smoke)·앞서 죽은 자식의 보고서는 같은 python3.10이고 몇 분 전에 이미 있음 — 그것을 보고 기다림을 끝내면
    방금 죽은 pytest의 보고서를 놓침(2026-11-12 CI: 일부러 죽인 것 둘이 있어 '기다림 0초'). 방금 쓰인 보고서가 올 때까지 기다리고 둘 다 출력."""
    write_report(tmp_path, "python3.10-deliberate.ips", {"app_name": "python3.10"}, CRASH, mtime=EARLIER)
    fake = FakeTime()
    fake.happenings = [(6, crash_now(fake, tmp_path, "python3.10-real.ips"))]
    out = run_waiting(load_tool(), capsys, fake, "--since", str(JOB_START), "--process", "python3", "--wait", "120", str(tmp_path))
    assert fake.sleeps == [2.0, 2.0, 2.0]
    assert "python3.10-deliberate.ips" in out and "python3.10-real.ips" in out and "충돌 보고서 2개 출력" in out
    assert "기다림 6초(최대 120초)" in out and "방금" not in out


def test_with_only_earlier_reports_it_waits_to_the_deadline_and_says_so(tmp_path, capsys):
    """크래시가 아닌 실패: 앞서 쓰인 보고서만 있음 — 기한까지 기다린 뒤 있는 것을 출력하고, 방금 쓰인 것은 없었다고 적음."""
    write_report(tmp_path, "python3.10-deliberate.ips", {"app_name": "python3.10"}, CRASH, mtime=EARLIER)
    fake = FakeTime()
    out = run_waiting(load_tool(), capsys, fake, "--since", str(JOB_START), "--process", "python3", "--wait", "6", str(tmp_path))
    assert fake.sleeps == [2.0, 2.0, 2.0] and "python3.10-deliberate.ips" in out and "충돌 보고서 1개 출력" in out
    assert "기다림 6초(최대 6초) — 방금(이 단계 직전 30초 안) 다 쓰인 보고서는 없음" in out


def test_a_report_written_just_before_the_step_ends_the_wait_at_once(tmp_path, capsys):
    """프로세스가 죽고 이 단계가 돌기까지 몇 초 — 그사이 이미 다 쓰인 보고서는 방금 것: 기다리지 않음. --fresh로 그 폭을 정함."""
    write_report(tmp_path, "python3.10-1.ips", {"app_name": "python3.10"}, CRASH, mtime=STEP_START - 10)
    fake = FakeTime()
    out = run_waiting(load_tool(), capsys, fake, "--since", str(JOB_START), "--process", "python3", "--wait", "120", str(tmp_path))
    assert fake.sleeps == [] and "sgemm_itcopy + 12" in out and "기다림 0초(최대 120초)" in out and "방금" not in out
    fake = FakeTime()
    out = run_waiting(load_tool(), capsys, fake, "--since", str(JOB_START), "--process", "python3", "--wait", "4", "--fresh", "5", str(tmp_path))
    assert fake.sleeps == [2.0, 2.0] and "방금(이 단계 직전 5초 안) 다 쓰인 보고서는 없음" in out


# ---------------------------------------------------------------- 리뷰에서 잡은 것


def header_only_now(fake, folder, name="python3.10-1.ips"):
    """머리 줄만 쓰이고 본문은 아직인 보고서 (지금 쓰는 중)."""
    def write():
        (folder / name).write_text('{"app_name": "python3.10"}\n', encoding="utf-8")
        os.utime(folder / name, (fake.time(), fake.time()))
    return write


def test_a_report_with_only_its_header_line_does_not_end_the_wait(tmp_path, capsys):
    """머리 줄만 쓰이고 본문이 아직인 순간에도 파일은 읽힘(본문 빈 dict) — 그것으로 끝내면 '죽은 스레드 정보 없음'만 찍힘. 본문이 올 때까지 기다림."""
    fake = FakeTime()
    fake.happenings = [(2, header_only_now(fake, tmp_path)), (6, crash_now(fake, tmp_path))]
    out = run_waiting(load_tool(), capsys, fake, "--since", str(JOB_START), "--process", "python3", "--wait", "60", str(tmp_path))
    assert "sgemm_itcopy + 12" in out and "죽은 스레드 정보 없음" not in out and fake.sleeps == [2.0, 2.0, 2.0]


def test_a_header_only_report_is_still_printed_at_the_deadline(tmp_path, capsys):
    fake = FakeTime()
    fake.happenings = [(2, header_only_now(fake, tmp_path))]
    out = run_waiting(load_tool(), capsys, fake, "--since", str(JOB_START), "--process", "python3", "--wait", "4", str(tmp_path))
    assert "python3.10-1.ips" in out and "죽은 스레드 정보 없음" in out and "충돌 보고서 1개 출력" in out
    assert fake.sleeps == [2.0, 2.0] and "다 쓰인 보고서는 없음" in out


def test_after_a_fresh_report_it_keeps_looking_for_a_while(tmp_path, capsys):
    """자식이 죽고 곧이어 pytest 본체도 죽으면 보고서가 둘 — 첫 보고서를 보자마자 끝내면 둘째(본체의 것)를 놓침. 기본 20초(--settle) 더 지켜봄."""
    fake = FakeTime()
    fake.happenings = [(4, crash_now(fake, tmp_path, "python3.10-child.ips")), (14, crash_now(fake, tmp_path, "python3.10-pytest.ips"))]
    out = run_waiting(load_tool(), capsys, fake, "--since", str(JOB_START), "--process", "python3", "--wait", "120", str(tmp_path),
                      settle=None)
    assert "python3.10-child.ips" in out and "python3.10-pytest.ips" in out and "충돌 보고서 2개 출력" in out
    assert sum(fake.sleeps) == 24.0 and "기다림 24초(최대 120초)" in out and "없음" not in out


def test_looking_on_never_passes_the_deadline(tmp_path, capsys):
    fake = FakeTime()
    fake.happenings = [(4, crash_now(fake, tmp_path))]
    out = run_waiting(load_tool(), capsys, fake, "--since", str(JOB_START), "--process", "python3", "--wait", "10", str(tmp_path),
                      settle="20")
    assert sum(fake.sleeps) == 10.0 and "sgemm_itcopy + 12" in out and "기다림 10초(최대 10초)" in out


def test_a_report_that_vanishes_during_the_scan_is_skipped_and_counted(tmp_path, capsys, monkeypatch):
    """폴더를 훑는 사이 보고서가 사라져도(macOS가 옮김·임시 이름) 도구가 트레이스백으로 죽지 않음 — 그 파일만 건너뛰고 끝 줄에 적음."""
    write_report(tmp_path, "python3.10-1.ips", {"app_name": "python3.10"}, CRASH)
    write_report(tmp_path, "python3.10-gone.ips", {"app_name": "python3.10"}, CRASH)
    tool = load_tool()
    real_getmtime = os.path.getmtime

    def getmtime(path):
        if str(path).endswith("gone.ips"):
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real_getmtime(path)

    monkeypatch.setattr(tool.os.path, "getmtime", getmtime)
    out = run(tool, capsys, str(tmp_path))
    assert "===== " + str(tmp_path / "python3.10-1.ips") in out and "===== " + str(tmp_path / "python3.10-gone.ips") not in out
    assert "충돌 보고서 1개 출력" in out and "훑는 사이 사라진 파일 1개" in out


def test_without_vanished_files_the_last_line_does_not_mention_them(tmp_path, capsys):
    write_report(tmp_path, "python3.10-1.ips", {"app_name": "python3.10"}, CRASH)
    assert "사라진" not in run(load_tool(), capsys, str(tmp_path))


@pytest.mark.parametrize("poll", ["0", "-1"])
def test_poll_must_be_positive(tmp_path, capsys, poll):
    """--poll 0이면 기한까지 쉬지 않고 폴더를 훑고, 음수면 sleep이 ValueError — 인자에서 막음."""
    with pytest.raises(SystemExit):
        load_tool().main(["--wait", "5", "--poll", poll, str(tmp_path)], sleep=lambda _seconds: None)
    assert "--poll" in capsys.readouterr().err
