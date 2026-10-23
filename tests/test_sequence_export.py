"""시퀀스 → mov 일괄 내보내기 워커: 실제 ffmpeg로 mov를 만들어 프레임 수·프레임 내용·fps를 확인한다.

프레임은 번호마다 서로 다른 단색이다 (손실 없는 TGA) — 출력 mov는 h264(손실)라 색이 아니라 '어느 번호의 프레임인가'만 본다.
신호는 Qt.DirectConnection으로 받아 신호를 낸 스레드에서 바로 기록한다 (이벤트 루프 없이 결정적). 취소 시험은 진행 신호를 받은 워커 스레드를
`stop()`이 불릴 때까지 세워 두므로 sleep으로 맞추지 않는다.
"""

import json
import os
import stat
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import cv2
import pytest
from PyQt5.QtCore import Qt

from tests.test_sequence_capture import PALETTE, identify, make_frame, make_movie, make_seq
from yesoncheck import external_tools, sequence_export_worker
from yesoncheck.player_base import VideoPlayerBase
from yesoncheck.sequence_export_worker import PARTIAL_SUFFIX, SequenceExportWorker, validate_out_dir
from yesoncheck.sequence_scan import group_sequences
from yesoncheck.sequence_source import ImageSequenceCapture

WAIT_S = 60


def scan(folder):
    """폴더의 시퀀스들 (SeqInfo)."""
    return group_sequences(str(folder), sorted(os.listdir(folder)))


def probe(path):
    """출력 mov의 첫 영상 트랙 정보 (ffprobe). nb_read_packets: 컨테이너의 실제 패킷 수."""
    result = subprocess.run(
        [external_tools.ffprobe_path(), "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries",
         "stream=nb_read_packets,r_frame_rate,width,height,pix_fmt", "-of", "json", str(path)],
        check=True, capture_output=True)
    return json.loads(result.stdout)["streams"][0]


def frame_ids(path):
    """출력 mov의 프레임을 차례로 읽어 PALETTE 번호 목록으로."""
    cap = cv2.VideoCapture(str(path))
    ids = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        ids.append(identify(frame))
    cap.release()
    return ids


def expected_ids(numbers):
    return [n % len(PALETTE) for n in numbers]


class Recorder:
    """워커의 신호를 신호를 낸 스레드에서 바로 모은다."""

    def __init__(self, worker):
        self.started, self.progress, self.errors, self.finished = [], [], [], []
        worker.item_started.connect(lambda index, base: self.started.append((index, base)), Qt.DirectConnection)
        worker.progress.connect(lambda done, total: self.progress.append((done, total)), Qt.DirectConnection)
        worker.error.connect(self.errors.append, Qt.DirectConnection)
        worker.finished.connect(lambda: self.finished.append(True), Qt.DirectConnection)


def run_to_end(worker):
    recorder = Recorder(worker)
    worker.start()
    assert worker.wait(WAIT_S * 1000), "워커가 끝나지 않았습니다"
    return recorder


def make_worker(items, out_dir):
    return SequenceExportWorker(items, str(out_dir), external_tools.ffmpeg_path())


@pytest.fixture
def spawned(monkeypatch):
    """워커가 띄운 ffmpeg 프로세스를 모은다 (진짜 Popen을 그대로 부름)."""
    procs = []
    real_popen = subprocess.Popen

    def spy(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        procs.append(proc)
        return proc

    monkeypatch.setattr(sequence_export_worker.subprocess, "Popen", spy)
    return procs


def hold_at(worker, out_dir, frames):
    """진행이 `frames`장에 닿으면 워커 스레드를 stop()이 불릴 때까지 세운다 (그때 out_dir에 생긴 파일 이름을 기록).
    돌려주는 (reached, seen): reached는 세웠을 때 켜지는 Event, seen["files"]는 그때의 out_dir 목록."""
    reached = threading.Event()
    seen = {}

    def on_progress(done, _total):
        if done != frames:
            return
        wait_for_partial(out_dir)
        seen["files"] = sorted(os.listdir(out_dir))
        reached.set()
        assert worker._stopped.wait(30), "stop()이 불리지 않았습니다"

    worker.progress.connect(on_progress, Qt.DirectConnection)
    return reached, seen


# ---------------------------------------------------------------- 만들기


def test_export_single_sequence_frame_count_and_name(qapp, tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "EX01_tk1", range(1, 7))
    items = scan(src)

    worker = make_worker(items, out)
    rec = run_to_end(worker)

    assert rec.errors == []
    assert rec.finished == [True]
    assert sorted(os.listdir(out)) == ["EX01_tk1.mov"], "출력 폴더에는 <base>.mov만 남아야 합니다 (임시 파일 없음)"
    info = probe(out / "EX01_tk1.mov")
    assert int(info["nb_read_packets"]) == 6
    assert (info["width"], info["height"]) == (64, 48)
    assert info["pix_fmt"] == "yuv420p"
    assert info["r_frame_rate"] == "24/1", "짝 mov가 없으면 24fps"
    assert frame_ids(out / "EX01_tk1.mov") == expected_ids(range(1, 7))
    assert rec.started == [(0, "EX01_tk1")]
    assert rec.progress[0] == (0, 6) and rec.progress[-1] == (6, 6)
    assert os.listdir(src) != [], "원본 폴더는 그대로"


def test_export_fills_gaps_preserves_length(qapp, tmp_path):
    """0001·0003만 있는 시퀀스 -> 3프레임 mov (빠진 0002는 직전 프레임 유지) [Review Focus 5]."""
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "GAP_tk1", [1, 3])

    rec = run_to_end(make_worker(scan(src), out))

    assert rec.errors == [] and rec.finished == [True]
    assert int(probe(out / "GAP_tk1.mov")["nb_read_packets"]) == 3
    assert frame_ids(out / "GAP_tk1.mov") == expected_ids([1, 1, 3])
    assert rec.progress[-1] == (3, 3)


def test_export_nonstandard_start(qapp, tmp_path):
    """시작 번호가 0001이 아닌 시퀀스(0101…)도 프레임 수가 맞다 [Review Focus 1]."""
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "LATE_tk1", range(101, 106))

    rec = run_to_end(make_worker(scan(src), out))

    assert rec.errors == [] and rec.finished == [True]
    assert int(probe(out / "LATE_tk1.mov")["nb_read_packets"]) == 5
    assert frame_ids(out / "LATE_tk1.mov") == expected_ids(range(101, 106))


def test_export_odd_frame_size(qapp, tmp_path):
    """가로·세로가 홀수인 프레임: yuv420p는 짝수 크기만 되므로 검은 한 줄을 덧붙여 만든다 (프레임 수는 그대로)."""
    src, out = tmp_path / "src", tmp_path / "out"
    os.makedirs(src)
    for n in range(1, 4):
        make_frame(str(src / f"ODD_tk1-{n:04d}.tga"), PALETTE[n], size=(65, 49))

    rec = run_to_end(make_worker(scan(src), out))

    assert rec.errors == [] and rec.finished == [True]
    info = probe(out / "ODD_tk1.mov")
    assert int(info["nb_read_packets"]) == 3
    assert (info["width"], info["height"]) == (66, 50)


@pytest.mark.parametrize("paired_fps, expected_rate", [(30, "30/1"), ("24000/1001", "24000/1001")])
def test_fps_from_paired_mov(qapp, tmp_path, paired_fps, expected_rate):
    """짝 mov(<base>.mov)의 fps가 출력에 쓰인다 — 23.976처럼 분수인 속도도 정확한 분수(24000/1001)로."""
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "EX01_tk1", range(1, 5))
    make_movie(str(src / "EX01_tk1.mov"), paired_fps)

    rec = run_to_end(make_worker(scan(src), out))

    assert rec.errors == [] and rec.finished == [True]
    assert probe(out / "EX01_tk1.mov")["r_frame_rate"] == expected_rate


def test_export_overwrites_existing_output(qapp, tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "EX01_tk1", range(1, 4))
    os.makedirs(out)
    (out / "EX01_tk1.mov").write_bytes(b"old")

    rec = run_to_end(make_worker(scan(src), out))

    assert rec.errors == [] and rec.finished == [True]
    assert int(probe(out / "EX01_tk1.mov")["nb_read_packets"]) == 3


def test_batch_two_items_serial_progress(qapp, tmp_path):
    """항목은 차례로 처리: item_started가 항목마다 한 번, 진행은 두 항목의 프레임을 합산해 한 번도 줄지 않는다."""
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "A_tk1", range(1, 5))  # 4프레임
    make_seq(str(src), "B_tk1", range(1, 8))  # 7프레임
    items = scan(src)
    assert [s.base for s in items] == ["A_tk1", "B_tk1"]

    worker = make_worker(items, out)
    order = []  # 신호가 온 순서 (항목이 섞이지 않았는지)
    worker.item_started.connect(lambda index, base: order.append(("start", base)), Qt.DirectConnection)
    worker.progress.connect(lambda done, total: order.append(("progress", done)), Qt.DirectConnection)
    rec = run_to_end(worker)

    assert rec.errors == [] and rec.finished == [True]
    assert rec.started == [(0, "A_tk1"), (1, "B_tk1")]
    assert all(total == 11 for _done, total in rec.progress)
    dones = [done for done, _total in rec.progress]
    assert dones == sorted(dones) and dones[-1] == 11
    assert dones.count(4) >= 1, "첫 항목이 끝난 지점(4/11)을 지남"
    assert order.index(("start", "B_tk1")) > order.index(("progress", 4)), "둘째 항목은 첫 항목이 끝난 뒤에 시작"
    assert sorted(os.listdir(out)) == ["A_tk1.mov", "B_tk1.mov"]
    assert int(probe(out / "A_tk1.mov")["nb_read_packets"]) == 4
    assert int(probe(out / "B_tk1.mov")["nb_read_packets"]) == 7


# ---------------------------------------------------------------- 취소·오류: 부분 출력 삭제


def test_cancel_deletes_partial_output(qapp, tmp_path, spawned):
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "EX01_tk1", range(1, 41))
    worker = make_worker(scan(src), out)
    rec = Recorder(worker)
    reached, seen = hold_at(worker, str(out), 3)

    worker.start()
    assert reached.wait(WAIT_S), "진행 3장에 닿지 않았습니다"
    assert seen["files"] == ["EX01_tk1" + PARTIAL_SUFFIX], "취소 전에는 만드는 중인 파일이 있어야 합니다"
    proc = spawned[0]
    assert proc.poll() is None, "취소 전에는 ffmpeg가 돌고 있어야 합니다"
    worker.stop()
    assert worker.wait(WAIT_S * 1000), "stop() 뒤에도 워커가 끝나지 않았습니다"

    assert os.listdir(out) == [], "취소하면 부분 출력(과 임시 파일)이 남지 않아야 합니다"
    assert proc.returncode not in (None, 0), f"ffmpeg가 끝나지 않고 자연 완료된 것으로 보입니다 (returncode={proc.returncode})"
    assert rec.finished == [] and rec.errors == [], "취소는 완료도 오류도 아님"
    assert worker.cancelled


def test_cancel_keeps_finished_items_and_stops_batch(qapp, tmp_path):
    """둘째 항목을 만드는 중에 취소: 첫 항목의 mov는 남고 둘째의 부분 출력만 지워지며 셋째는 시작하지 않는다."""
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "A_tk1", range(1, 4))
    make_seq(str(src), "B_tk1", range(1, 41))
    make_seq(str(src), "C_tk1", range(1, 4))
    worker = make_worker(scan(src), out)
    rec = Recorder(worker)
    reached, seen = hold_at(worker, str(out), 3 + 3)  # A(3장) 다음 B의 3장째

    worker.start()
    assert reached.wait(WAIT_S)
    assert seen["files"] == ["A_tk1.mov", "B_tk1" + PARTIAL_SUFFIX]
    worker.stop()
    assert worker.wait(WAIT_S * 1000)

    assert os.listdir(out) == ["A_tk1.mov"]
    assert int(probe(out / "A_tk1.mov")["nb_read_packets"]) == 3
    assert [base for _index, base in rec.started] == ["A_tk1", "B_tk1"]
    assert rec.finished == [] and rec.errors == []


def test_stop_before_start_does_nothing(qapp, tmp_path, spawned):
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "EX01_tk1", range(1, 4))
    worker = make_worker(scan(src), out)
    rec = Recorder(worker)

    worker.stop()
    worker.start()
    assert worker.wait(WAIT_S * 1000)

    assert spawned == [] and rec.started == [] and rec.finished == [] and rec.errors == []
    assert not out.exists() or os.listdir(out) == []


def wait_for_partial(out_dir):
    """ffmpeg가 만드는 중인 출력 파일(.part)을 연 뒤까지 기다림 (실패·취소를 '파일이 있는 상태'에서 일으키려고)."""
    deadline = time.monotonic() + 30
    while not any(name.endswith(PARTIAL_SUFFIX) for name in os.listdir(out_dir)):
        assert time.monotonic() < deadline, "ffmpeg가 출력 파일을 만들지 않았습니다"
        time.sleep(0.01)


def failing_after(reads, out_dir, message="decode exploded"):
    """read()가 `reads`번째 부름에서 (ffmpeg가 출력 파일을 연 뒤) 예외를 올리는 캡처 — 그 앞은 진짜 프레임."""

    class FailingCapture(ImageSequenceCapture):
        def read(self):
            self.calls = getattr(self, "calls", 0) + 1
            if self.calls == reads:
                wait_for_partial(out_dir)
                raise RuntimeError(message)
            return super().read()

    return FailingCapture


def test_error_deletes_partial_output(qapp, tmp_path, monkeypatch, spawned):
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "EX01_tk1", range(1, 21))
    monkeypatch.setattr(sequence_export_worker, "ImageSequenceCapture", failing_after(4, str(out)))

    rec = run_to_end(make_worker(scan(src), out))

    assert os.listdir(out) == [], "오류가 나도 부분 출력이 남지 않아야 합니다"
    assert rec.finished == []
    assert len(rec.errors) == 1
    assert "EX01_tk1" in rec.errors[0] and "decode exploded" in rec.errors[0]
    assert "Traceback" in rec.errors[0], "예상 못 한 오류는 스택 트레이스째 보여야 합니다"
    assert spawned and all(proc.poll() is not None for proc in spawned), "ffmpeg가 남지 않아야 합니다"


def test_batch_continues_after_item_failure(qapp, tmp_path, monkeypatch):
    """한 항목이 실패해도 다음 항목은 만든다. 끝나면 실패 요약이 error로 오고 finished는 오지 않는다."""
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "A_tk1", range(1, 11))
    make_seq(str(src), "B_tk1", range(1, 5))
    make_seq(str(src), "C_tk1", range(1, 4))
    failing = failing_after(3, str(out), "A broke")
    monkeypatch.setattr(sequence_export_worker, "ImageSequenceCapture",
                        lambda identity: failing(identity) if identity.endswith("A_tk1.seq") else ImageSequenceCapture(identity))

    rec = run_to_end(make_worker(scan(src), out))

    assert [base for _index, base in rec.started] == ["A_tk1", "B_tk1", "C_tk1"]
    assert sorted(os.listdir(out)) == ["B_tk1.mov", "C_tk1.mov"]
    assert int(probe(out / "B_tk1.mov")["nb_read_packets"]) == 4
    assert rec.finished == []
    assert len(rec.errors) == 1
    summary = rec.errors[0]
    assert summary.splitlines()[0].startswith("3개 중 1개 실패"), summary
    assert "A_tk1" in summary and "A broke" in summary
    assert "B_tk1" not in summary and "C_tk1" not in summary
    assert rec.progress[-1] == (17, 17), "실패한 항목도 건너뛰어 전체 진행이 끝까지 감"


def test_unopenable_sequence_is_item_error(qapp, tmp_path):
    """스캔 뒤 프레임이 사라져 시퀀스를 열 수 없으면 그 항목만 오류 — 다음 항목은 만든다."""
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "A_tk1", range(1, 4))
    make_seq(str(src), "B_tk1", range(1, 4))
    items = scan(src)
    for n in range(1, 4):
        os.remove(src / f"A_tk1-{n:04d}.tga")

    rec = run_to_end(make_worker(items, out))

    assert os.listdir(out) == ["B_tk1.mov"]
    assert len(rec.errors) == 1 and "A_tk1" in rec.errors[0] and "열 수 없습니다" in rec.errors[0]


def test_locked_destination_is_item_error_and_batch_continues(qapp, tmp_path, monkeypatch):
    """(Windows) 덮어쓸 mov를 다른 프로그램이 열고 있으면(PermissionError) 그 항목만 오류. 있던 파일은 그대로, 임시 파일은 지움."""
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "A_tk1", range(1, 4))
    make_seq(str(src), "B_tk1", range(1, 4))
    os.makedirs(out)
    (out / "A_tk1.mov").write_bytes(b"old and locked")
    real_replace = os.replace

    def locked_replace(src_path, dst_path):
        if os.path.basename(dst_path) == "A_tk1.mov":
            raise PermissionError(13, "다른 프로세스가 파일을 사용 중이기 때문에 프로세스가 액세스 할 수 없습니다", dst_path)
        return real_replace(src_path, dst_path)

    monkeypatch.setattr(sequence_export_worker.os, "replace", locked_replace)

    rec = run_to_end(make_worker(scan(src), out))

    assert sorted(os.listdir(out)) == ["A_tk1.mov", "B_tk1.mov"]
    assert (out / "A_tk1.mov").read_bytes() == b"old and locked"
    assert int(probe(out / "B_tk1.mov")["nb_read_packets"]) == 3
    assert rec.finished == [] and len(rec.errors) == 1
    assert "A_tk1" in rec.errors[0] and "덮어쓸 수 없습니다" in rec.errors[0]


def test_same_output_name_in_one_batch_is_item_error(qapp, tmp_path):
    """다른 폴더의 같은 이름 시퀀스 둘: 둘째가 첫째의 mov를 말없이 덮어쓰지 않고 오류로 남는다."""
    src1, src2, out = tmp_path / "src1", tmp_path / "src2", tmp_path / "out"
    make_seq(str(src1), "EX01_tk1", range(1, 4))
    make_seq(str(src2), "EX01_tk1", range(1, 6))

    rec = run_to_end(make_worker(scan(src1) + scan(src2), out))

    assert os.listdir(out) == ["EX01_tk1.mov"]
    assert int(probe(out / "EX01_tk1.mov")["nb_read_packets"]) == 3, "첫 항목의 결과가 그대로"
    assert len(rec.errors) == 1 and "EX01_tk1.mov" in rec.errors[0] and "이미" in rec.errors[0]


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="실행 파일 스크립트(shebang)로 ffmpeg를 흉내 냄 — POSIX 전용")


def fake_ffmpeg(tmp_path, body):
    """`body`(파이썬 코드)를 도는 가짜 ffmpeg 실행 파일 — 워커가 ffmpeg에 넘기는 인자는 sys.argv[1:]."""
    fake = tmp_path / "fake_ffmpeg"
    fake.write_text(f"#!{sys.executable}\nimport sys\n{body}\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return str(fake)


def run_and_wait(worker, spawned, seconds=30):
    """워커를 돌려 `seconds` 안에 끝나는지 본다. 안 끝나면 띄운 프로세스를 끝내 정리하고 False."""
    worker.start()
    finished = worker.wait(seconds * 1000)
    if not finished:
        worker.stop()
        for proc in spawned:
            proc.kill()
        worker.wait(10 * 1000)
    return finished


@posix_only
def test_ffmpeg_stderr_is_drained(qapp, tmp_path, spawned):
    """ffmpeg가 stdin을 읽기 전에 stderr를 가득 채워도(파이프 용량 이상) 멈추지 않는다 — stderr를 리더 스레드로 비움."""
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "EX01_tk1", range(1, 41))
    fake = fake_ffmpeg(tmp_path, "sys.stderr.write('x' * 1000000)\nsys.stderr.flush()\nsys.stdin.buffer.read()")
    worker = SequenceExportWorker(scan(src), str(out), fake)
    rec = Recorder(worker)

    assert run_and_wait(worker, spawned), "ffmpeg의 stderr를 비우지 않아 워커가 멈췄습니다"

    assert len(rec.errors) == 1 and "만들지 않았습니다" in rec.errors[0], rec.errors
    assert not out.exists() or os.listdir(out) == []


@posix_only
def test_stop_unblocks_a_pipe_write_by_killing_ffmpeg(qapp, tmp_path, monkeypatch, spawned):
    """ffmpeg가 stdin을 읽지 않아 워커가 파이프에 쓰다 막혔을 때도 stop()이 ffmpeg를 끝내 워커를 풀어 준다."""
    src, out = tmp_path / "src", tmp_path / "out"
    os.makedirs(src)
    for n in range(1, 4):
        make_frame(str(src / f"BIG_tk1-{n:04d}.tga"), PALETTE[n], size=(640, 480))  # 한 프레임 약 900KB: 파이프 용량보다 훨씬 큼
    read_done = threading.Event()

    class SignalingCapture(ImageSequenceCapture):
        def read(self):
            result = super().read()
            read_done.set()  # 이 다음은 곧바로 ffmpeg 파이프에 쓰기 (stop 확인은 읽기 전에만 함)
            return result

    monkeypatch.setattr(sequence_export_worker, "ImageSequenceCapture", SignalingCapture)
    worker = SequenceExportWorker(scan(src), str(out), fake_ffmpeg(tmp_path, "import time\ntime.sleep(600)"))
    rec = Recorder(worker)

    worker.start()
    assert read_done.wait(WAIT_S)
    worker.stop()
    finished = worker.wait(15 * 1000)
    if not finished:  # stop()이 ffmpeg를 끝내지 않은 경우의 정리
        for proc in spawned:
            proc.kill()
        worker.wait(10 * 1000)

    assert finished, "stop()이 ffmpeg를 끝내지 않아 파이프에 쓰던 워커가 풀리지 않았습니다"
    assert rec.finished == [] and rec.errors == []
    assert not out.exists() or os.listdir(out) == []


@posix_only
def test_output_frame_count_mismatch_is_error_and_output_deleted(qapp, tmp_path, spawned):
    """ffmpeg가 0으로 끝나도 결과 프레임 수가 시퀀스와 다르면(여기서는 fps 필터로 절반이 사라짐) 오류 + 출력 삭제."""
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "EX01_tk1", range(1, 7))
    fake = fake_ffmpeg(tmp_path, f"import subprocess\n"
                                 f"sys.exit(subprocess.call([{external_tools.ffmpeg_path()!r}] + sys.argv[1:-1] + "
                                 f"['-vf', 'fps=12', sys.argv[-1]]))")
    worker = SequenceExportWorker(scan(src), str(out), fake)
    rec = Recorder(worker)

    assert run_and_wait(worker, spawned)

    assert os.listdir(out) == [], "틀린 결과는 남기지 않음"
    assert rec.finished == [] and len(rec.errors) == 1
    assert "프레임 수" in rec.errors[0] and "EX01_tk1" in rec.errors[0]


# ---------------------------------------------------------------- 원본 폴더 금지


def test_validate_out_dir_rejects_source_folder(tmp_path):
    src1, src2, other = tmp_path / "src1", tmp_path / "src2", tmp_path / "other"
    make_seq(str(src1), "A_tk1", range(1, 4))
    make_seq(str(src2), "B_tk1", range(1, 4))
    other.mkdir()
    items = scan(src1) + scan(src2)

    for same in (str(src1), str(src2), str(src1) + os.sep, os.path.join(str(src1), "..", "src1"), os.path.join(str(src2), ".")):
        reason = validate_out_dir(items, same)
        assert isinstance(reason, str) and reason, same
    assert validate_out_dir(items, str(other)) is None
    assert validate_out_dir(items, str(tmp_path / "not_created_yet")) is None
    assert validate_out_dir(items, str(src1 / "mov")) is None, "원본 폴더 안의 하위 폴더는 원본 폴더가 아님"
    assert validate_out_dir([], str(src1)) is None


def test_validate_out_dir_rejects_relative_and_symlink_alias(tmp_path, monkeypatch):
    src, alias_parent = tmp_path / "src", tmp_path / "links"
    make_seq(str(src), "A_tk1", range(1, 4))
    alias_parent.mkdir()
    try:
        os.symlink(str(src), str(alias_parent / "alias"), target_is_directory=True)
    except OSError as exc:  # Windows에서 권한이 없으면 심볼릭 링크를 못 만듦
        pytest.skip(f"심볼릭 링크를 만들 수 없음: {exc}")
    items = scan(src)

    assert validate_out_dir(items, str(alias_parent / "alias")), "같은 폴더를 가리키는 링크도 거부"
    monkeypatch.chdir(tmp_path)
    assert validate_out_dir(items, "src"), "상대 경로로 쓴 원본 폴더도 거부"


def test_worker_refuses_source_folder_without_encoding(qapp, tmp_path, spawned):
    """대화상자를 거치지 않아도 워커가 원본 폴더로는 만들지 않는다 (error 한 번, ffmpeg·파일 없음)."""
    src = tmp_path / "src"
    make_seq(str(src), "EX01_tk1", range(1, 4))
    before = sorted(os.listdir(src))

    rec = run_to_end(make_worker(scan(src), src))

    assert len(rec.errors) == 1 and rec.errors[0] == validate_out_dir(scan(src), str(src))
    assert rec.finished == [] and rec.started == [] and spawned == []
    assert sorted(os.listdir(src)) == before


# ---------------------------------------------------------------- 창 닫기 가드


def test_running_job_attrs_registers_sequence_export():
    assert ("시퀀스 MOV 만들기", "seq_export_worker") in VideoPlayerBase.RUNNING_JOB_ATTRS


def test_close_window_guard_stops_export_and_removes_partial(qapp, tmp_path, spawned):
    """창 닫기(stop_running_jobs)가 RUNNING_JOB_ATTRS를 따라 시퀀스 내보내기를 멈추고 부분 출력을 지운다."""
    src, out = tmp_path / "src", tmp_path / "out"
    make_seq(str(src), "EX01_tk1", range(1, 41))
    worker = make_worker(scan(src), out)
    reached, _seen = hold_at(worker, str(out), 3)
    player = SimpleNamespace(RUNNING_JOB_ATTRS=VideoPlayerBase.RUNNING_JOB_ATTRS, JOB_CLOSE_WAIT_MS=30000,
                             seq_export_worker=worker)
    player.running_jobs = lambda: VideoPlayerBase.running_jobs(player)

    worker.start()
    assert reached.wait(WAIT_S)
    assert player.running_jobs() == [("시퀀스 MOV 만들기", worker)]
    VideoPlayerBase.stop_running_jobs(player)

    assert not worker.isRunning()
    assert os.listdir(out) == []
    assert spawned[0].returncode not in (None, 0)
