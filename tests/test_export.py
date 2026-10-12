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
    video = make_video(str(tmp_path / "긴영상.mov"), seconds=60)
    out_dir = tmp_path / "out"
    worker = OCRExportWorker(video, [segment("LONG", 0, 60 * 24 - 1)], str(out_dir), external_tools.ffmpeg_path(),
                             export_mode="quality", max_workers=1)
    thread = threading.Thread(target=worker.run)
    thread.start()
    deadline = time.time() + 30
    while not worker._procs and time.time() < deadline:
        time.sleep(0.05)
    assert worker._procs, "ffmpeg가 시작되지 않았습니다"
    worker.stop()
    thread.join(timeout=30)
    assert not thread.is_alive(), "취소 후에도 내보내기가 끝나지 않았습니다"
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
