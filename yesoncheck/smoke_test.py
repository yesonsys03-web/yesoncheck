"""실행 시험: YesonCheck_Autocut --smoke-test <작업 폴더>

화면 없이(QT_QPA_PLATFORM=offscreen) 실제 앱 코드로 공유 설정·작품 목록·영상 열기·OCR·내보내기·병합을
실행하고 결과를 <작업 폴더>/smoke_result.json에 쓴 뒤 종료 코드(0 성공, 1 실패)로 알린다.
작업 폴더의 smoke_config.json(ci/make_test_data.py가 만듦)에 고를 작품·시즌·job과 기대 파일 수가 있다.
대화상자는 띄우지 않고 기록하며, 오류·경고 대화상자가 하나라도 나오면 실패로 본다.
"""

import json
import os
import re
import sys
import traceback

# exe manifest의 <longPathAware ...>true</longPathAware> (이름공간 접두사 허용, 값은 true여야 함)
_LONG_PATH_AWARE = re.compile(rb"<(?:[\w.-]+:)?longPathAware\b[^>]*>\s*true\s*</(?:[\w.-]+:)?longPathAware\s*>")


def manifest_long_path_aware(data):
    """exe 바이트(안의 manifest)에 longPathAware가 true로 켜져 있는지."""
    return _LONG_PATH_AWARE.search(data) is not None


def ocr_model_files(base_dir):
    """OCR 모델이 base_dir의 whl 폴더 아래로 내려받아졌는지 확인하고 파일 목록(base_dir 기준)을 돌려줌."""
    whl = os.path.join(base_dir, "whl")
    assert os.path.isdir(whl), f"OCR 모델 폴더가 없습니다: {whl}"
    files = sorted(
        os.path.relpath(os.path.join(root, name), base_dir) for root, _dirs, names in os.walk(whl) for name in names
    )
    assert files, f"OCR 모델 폴더가 비어 있습니다: {whl}"
    return files


def run(workdir):
    import cv2
    import numpy as np
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from yesoncheck import external_tools

    with open(os.path.join(workdir, "smoke_config.json"), encoding="utf-8") as fh:
        config = json.load(fh)
    out_dir = os.path.join(workdir, "out")
    os.makedirs(out_dir, exist_ok=True)
    report = {"checks": [], "dialogs": []}

    def record(kind, answer):
        def fake(parent, title, text, *args, **kwargs):
            report["dialogs"].append({"kind": kind, "title": title, "text": text})
            return answer
        return fake

    QMessageBox.critical = record("critical", QMessageBox.Ok)
    QMessageBox.warning = record("warning", QMessageBox.Ok)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)

    def check(name, func):
        try:
            detail = func()
            report["checks"].append({"name": name, "ok": True, "detail": detail})
            return detail
        except Exception:
            report["checks"].append({"name": name, "ok": False, "detail": traceback.format_exc()})
            return None

    app = QApplication.instance() or QApplication([sys.argv[0]])
    from yesoncheck.main_window import VideoPlayer

    player = VideoPlayer()

    def shared_config_ok():
        assert player.shared_config_problem is None, player.shared_config_problem
        return player.work_paths_config_dir

    def work_listing():
        player.workComboBox.setCurrentText(config["work"])
        player.seasonComboBox.setCurrentText(config["season"])
        player.jobComboBox.setCurrentText(config["job"])
        files = [player.sidebar.item(i).data(Qt.UserRole) for i in range(player.sidebar.count())]
        assert len(files) == config["expected_files"], files
        return files

    files = check("공유 설정", shared_config_ok) and check("작품 목록", work_listing)
    video = files[0] if files else None

    def probe():
        codec = player.get_video_codec(video)
        assert codec == "h264", codec
        return codec

    def opencv_open():
        cap = cv2.VideoCapture(video)
        try:
            assert cap.isOpened(), f"열 수 없음: {video}"
            ok, frame = cap.read()
            assert ok and frame is not None
            return list(frame.shape)
        finally:
            cap.release()

    def ocr():
        from yesoncheck.workers import OCRWorker

        path = os.path.join(workdir, "ocr_text.mp4")
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 24, (640, 160))
        for _ in range(24):
            image = np.full((160, 640, 3), 255, np.uint8)
            cv2.putText(image, "SC_001", (40, 110), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (0, 0, 0), 6)
            writer.write(image)
        writer.release()
        result = {}
        worker = OCRWorker(path, (0.0, 0.0, 1.0, 1.0), start_frame=0, end_frame=23, ocr_mode="titmouse")
        worker.completed.connect(lambda r: result.update(r))
        worker.error.connect(lambda m: result.update(error=m))
        worker.run()
        assert "error" not in result, result.get("error")
        texts = [s.get("text") for s in result.get("segments", [])]
        assert any("SC" in (t or "") and "001" in (t or "") for t in texts), texts
        return texts

    def export(mode):
        from yesoncheck.workers import OCRExportWorker

        segment = {"text": f"SMOKE_{mode}", "edited_text": f"SMOKE_{mode}", "start_frame": 0, "end_frame": 23,
                   "start_time": 0.0, "end_time": 1.0, "duration": 1.0}
        result = {}
        worker = OCRExportWorker(video, [segment], out_dir, external_tools.ffmpeg_path(),
                                 include_audio=True, export_mode=mode, bitrate="2000k", max_workers=1)
        worker.completed.connect(lambda r: result.update(r))
        worker.error.connect(lambda m: result.update(error=m))
        worker.run()
        assert "error" not in result, result.get("error")
        output = os.path.join(out_dir, f"SMOKE_{mode}.mp4")
        assert os.path.getsize(output) > 0
        return output

    def merge():
        outputs = [os.path.join(out_dir, f"SMOKE_{m}.mp4") for m in ("fast", "balanced")]
        merged = os.path.join(out_dir, "합본.mov")
        external_tools.merge_videos_ffmpeg(external_tools.ffmpeg_path(), outputs, merged)
        assert os.path.getsize(merged) > 0
        return merged

    def annotation_export():
        from yesoncheck.annotation_export import AnnotationExportWorker

        output = os.path.join(out_dir, "주석.mp4")
        result = {}
        worker = AnnotationExportWorker(video, {}, output, external_tools.ffmpeg_path())
        worker.completed.connect(lambda p: result.update(done=p))
        worker.error.connect(lambda m: result.update(error=m))
        worker.run()
        assert result.get("done") == output, result.get("error")
        return output

    def long_path_aware():
        if not (sys.platform == "win32" and getattr(sys, "frozen", False)):
            return "Windows 빌드 앱에서만 확인"
        with open(sys.executable, "rb") as fh:
            assert manifest_long_path_aware(fh.read()), "exe manifest에 longPathAware(true)가 없습니다"
        return "true"

    def ocr_model_dir():
        """OCR 모델이 ASCII 폴더(%ProgramData%\\YesonCheck\\paddleocr)로 내려받아졌는지 (OCR 실행 뒤)."""
        if not (sys.platform == "win32" and getattr(sys, "frozen", False)):
            return "Windows 빌드 앱에서만 확인"
        from yesoncheck.workers import paddleocr_base_dir

        return ocr_model_files(paddleocr_base_dir())

    if video:
        check("ffprobe", probe)
        check("OpenCV 열기", opencv_open)
        check("고속 내보내기", lambda: export("fast"))
        check("균형 내보내기", lambda: export("balanced"))
        check("병합", merge)
        check("주석 내보내기", annotation_export)
    check("OCR", ocr)
    check("OCR 모델 폴더", ocr_model_dir)
    check("긴 경로 허용", long_path_aware)

    player.close()
    app.processEvents()
    bad_dialogs = [d for d in report["dialogs"] if d["kind"] in ("critical", "warning")]
    ok = all(c["ok"] for c in report["checks"]) and not bad_dialogs and video is not None
    report["ok"] = ok
    with open(os.path.join(workdir, "smoke_result.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1
