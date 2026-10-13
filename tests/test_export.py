import os
import threading
import time

from yesoncheck import external_tools
from yesoncheck.annotation_export import AnnotationExportWorker
from yesoncheck.workers import OCRExportWorker


def segment(text, start, end, fps=24.0):
    return {"text": text, "edited_text": text, "start_frame": start, "end_frame": end,
            "start_time": start / fps, "end_time": (end + 1) / fps, "duration": (end - start + 1) / fps}


def run_export(video, segments, out_dir, mode):
    worker = OCRExportWorker(video, segments, out_dir, external_tools.ffmpeg_path(),
                             include_audio=True, export_mode=mode, bitrate="2000k", max_workers=2)
    result = {}
    worker.completed.connect(lambda r: result.update(r))
    worker.error.connect(lambda m: result.update(error=m))
    worker.run()
    return result


def test_export_modes_and_reserved_name(qapp, tmp_path, make_video):
    video = make_video(str(tmp_path / "원본 폴더" / "컷.mov"), seconds=3)
    for mode in ("fast", "balanced"):
        out_dir = str(tmp_path / f"출력_{mode}")
        result = run_export(video, [segment("SC_001", 0, 23), segment("AUX", 24, 47)], out_dir, mode)
        assert "error" not in result, result.get("error")
        names = sorted(os.listdir(out_dir))
        assert names == ["AUX_.mp4", "SC_001.mp4"], names
        assert all(os.path.getsize(os.path.join(out_dir, n)) > 0 for n in names)


def test_cancel_kills_ffmpeg_and_removes_partial(qapp, tmp_path, make_video):
    # quality 모드로 자연 완료하면 이 길이의 영상은 (측정상) 약 26초가 걸린다 — 아래 10초
    # join 예산보다 훨씬 길어서, stop()이 실제로 ffmpeg를 끝내지 않으면 반드시 타임아웃으로
    # 드러난다 (returncode가 자연 종료인 0으로 남는 것도 함께 확인한다).
    seconds = 600
    video = make_video(str(tmp_path / "긴영상.mov"), seconds=seconds)
    out_dir = tmp_path / "out"
    worker = OCRExportWorker(video, [segment("LONG", 0, seconds * 24 - 1)], str(out_dir), external_tools.ffmpeg_path(),
                             export_mode="quality", max_workers=1)
    thread = threading.Thread(target=worker.run)
    thread.start()
    deadline = time.time() + 30
    while not worker._procs and time.time() < deadline:
        time.sleep(0.05)
    assert worker._procs, "ffmpeg가 시작되지 않았습니다"
    proc = next(iter(worker._procs))  # stop() 전에 잡아 둬야 종료 코드로 '실제로 죽었는지' 확인 가능
    worker.stop()
    thread.join(timeout=10)
    assert not thread.is_alive(), "취소 후에도 내보내기가 끝나지 않았습니다"
    assert proc.returncode not in (None, 0), (
        f"ffmpeg가 종료되지 않고 자연 완료된 것으로 보입니다 (returncode={proc.returncode})"
    )
    assert not (out_dir / "LONG.mp4").exists()


def test_annotation_export_long_video_does_not_hang(qapp, tmp_path, make_video):
    video = make_video(str(tmp_path / "주석 원본.mov"), seconds=20)
    out = str(tmp_path / "주석 결과.mp4")
    worker = AnnotationExportWorker(video, {}, out, external_tools.ffmpeg_path(), include_audio=True, export_mode="balanced")
    result = {}
    worker.completed.connect(lambda p: result.update(done=p))
    worker.error.connect(lambda m: result.update(error=m))
    thread = threading.Thread(target=worker.run)
    thread.start()
    # worker.run()을 별도 스레드에서 직접 호출하므로(QThread.start() 아님) completed/error
    # 시그널은 메인 스레드로 큐에 쌓인다. qapp.processEvents()로 펌프하지 않으면
    # thread.join()이 끝나도 result가 채워지지 않는다(PyQt 크로스스레드 큐드 커넥션).
    deadline = time.time() + 180
    while thread.is_alive() and time.time() < deadline:
        qapp.processEvents()
        thread.join(timeout=0.05)
    qapp.processEvents()  # 완료 시점에 올라온 마지막 시그널까지 처리
    assert not thread.is_alive(), "주석 내보내기가 멈췄습니다 (stderr 파이프)"
    assert result.get("done") == out, result.get("error")
    assert os.path.getsize(out) > 0


def test_annotation_export_reports_ffmpeg_stderr_on_failure(qapp, tmp_path, make_video):
    """ffmpeg가 출력 파일을 열지 못해 죽으면(stdin BrokenPipeError), 사용자는 ffmpeg의
    실제 이유를 봐야 한다 — "[Errno 32] Broken pipe"만 보면 안 된다.

    출력 경로를 이미 존재하는 폴더로 만들어서 ffmpeg가 그 경로를 출력 파일로 열지 못하게
    한다 (Mac: "Is a directory", Windows: "Permission denied" — 둘 다 플랫폼에 의존하지
    않는 chmod 권한 트릭 없이, Mac/Windows 모두에서 똑같이 실패를 일으킨다).
    """
    video = make_video(str(tmp_path / "주석 실패 원본.mov"), seconds=3)
    out = str(tmp_path / "out.mp4")
    os.mkdir(out)  # 출력 경로가 폴더 → ffmpeg가 출력 파일을 열지 못하고 바로 종료

    worker = AnnotationExportWorker(video, {}, out, external_tools.ffmpeg_path(),
                                    include_audio=True, export_mode="balanced")
    result = {}
    worker.completed.connect(lambda p: result.update(done=p))
    worker.error.connect(lambda m: result.update(error=m))
    thread = threading.Thread(target=worker.run)
    thread.start()
    deadline = time.time() + 30
    while thread.is_alive() and time.time() < deadline:
        qapp.processEvents()
        thread.join(timeout=0.05)
    qapp.processEvents()
    assert not thread.is_alive(), "ffmpeg 실패 후에도 내보내기가 멈췄습니다"
    assert "done" not in result, result
    error = result.get("error", "")
    assert "Error opening output" in error, error


def test_merge_worker_stop_kills_process_and_removes_partial(qapp, tmp_path):
    """FFmpegWorker.stop(): 등록된 ffmpeg를 끝내고, 끊긴 출력 파일을 지우고, 오류 창(error)은 내지 않음."""
    import subprocess
    import sys

    from PyQt5.QtCore import Qt

    from yesoncheck.workers import FFmpegWorker

    partial = tmp_path / "합본.mov"
    started = []

    def fake_merge(worker):
        partial.write_bytes(b"partial")
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        started.append(proc)
        worker.register_process(proc)
        proc.wait()
        raise RuntimeError(f"ffmpeg 병합 실패 (종료 코드 {proc.returncode})")

    worker = FFmpegWorker(fake_merge, partial_output=str(partial))
    errors = []
    worker.error.connect(errors.append, Qt.DirectConnection)
    worker.start()
    deadline = time.time() + 10
    while not started and time.time() < deadline:
        time.sleep(0.05)
    assert started, "병합 프로세스가 시작되지 않았습니다"
    worker.stop()
    assert worker.wait(10000), "중지 후에도 병합 스레드가 끝나지 않았습니다"
    assert started[0].returncode not in (None, 0)
    assert errors == []
    assert not partial.exists()


def test_merge_worker_stop_before_process_starts(qapp):
    """stop()이 ffmpeg 시작 전에 불려도 등록되는 즉시 끝냄."""
    import subprocess
    import sys

    from yesoncheck.workers import FFmpegWorker

    worker = FFmpegWorker(lambda w: None)
    worker.stop()
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    worker.register_process(proc)
    assert proc.wait(10) not in (None, 0)


def test_close_window_stops_exports_and_merge(qapp, dialogs, monkeypatch, tmp_path, capsys):
    """창을 닫으면 실행 중인 OCR 구간 내보내기·주석 내보내기·병합을 멈추고 기다림 (ffmpeg가 남지 않게)."""
    config = tmp_path / ".yesoncheck"
    config.mkdir()
    (config / "work_paths.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", str(config))
    from yesoncheck.main_window import VideoPlayer

    player = VideoPlayer()
    calls = []

    class Job:
        def __init__(self, name, finishes=True):
            self.name, self.finishes, self.running = name, finishes, True

        def isRunning(self):
            return self.running

        def blockSignals(self, block):
            calls.append((self.name, "blockSignals", block))

        def stop(self):
            calls.append((self.name, "stop"))

        def wait(self, ms):
            calls.append((self.name, "wait", ms))
            self.running = not self.finishes
            return self.finishes

    player.ocr_export_worker = Job("ocr")
    player.annotation_export_worker = Job("annotation")
    player.merge_worker = Job("merge", finishes=False)
    player.close()
    assert calls == [
        ("ocr", "blockSignals", True), ("ocr", "stop"), ("ocr", "wait", 10000),
        ("annotation", "blockSignals", True), ("annotation", "stop"), ("annotation", "wait", 10000),
        ("merge", "blockSignals", True), ("merge", "stop"), ("merge", "wait", 10000),
    ]
    assert "영상 병합이(가) 10초 안에 끝나지 않았습니다" in capsys.readouterr().out
