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
import time
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


def show_like_launch(VideoPlayer, app):
    """app.launch처럼 공유 설정을 읽지 않고 창을 만들어 보임 → (player, 만들어 보이기까지 걸린 초)."""
    started = time.perf_counter()
    player = VideoPlayer(load_shared_config=False)
    player.show()
    app.processEvents()
    return player, time.perf_counter() - started


def wait_shared_config_load(player, app, timeout_s):
    """공유 설정을 백그라운드로 불러오고(끝나면 resolve까지 실행됨) 끝날 때까지 이벤트를 처리하며 기다림 → 걸린 초."""
    started = time.perf_counter()
    player.start_shared_config_load()
    while player.shared_config_loading:
        if time.perf_counter() - started > timeout_s:
            raise TimeoutError(f"공유 설정 불러오기가 {timeout_s}초 안에 끝나지 않았습니다")
        app.processEvents()
        time.sleep(0.01)
    return time.perf_counter() - started


def open_like_launch(VideoPlayer, app, timeout_s=120):
    """창을 launch처럼 바로 보이고 공유 설정을 백그라운드로 불러와 기다림 → (player, 창 표시 초, 불러오기 초)."""
    player, shown_s = show_like_launch(VideoPlayer, app)
    load_s = wait_shared_config_load(player, app, timeout_s)
    return player, shown_s, load_s


def run(workdir):
    import cv2
    import numpy as np
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

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

    # 화면이 없으므로 변환표 자동 설정 확인 창은 기본 선택 그대로 승인, 비밀번호 입력에는 시험용 비밀번호
    from yesoncheck.path_map_setup_dialog import PathMapSetupDialog

    PathMapSetupDialog.exec_ = lambda self: QDialog.Accepted
    QInputDialog.getText = staticmethod(lambda *a, **k: ("smoke-password", True))

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

    player = None

    def shared_config_ok():
        assert player.shared_config_problem is None, player.shared_config_problem
        assert player.path_map_problem is None, player.path_map_problem
        return player.work_paths_config_dir

    def work_listing():
        player.workComboBox.setCurrentText(config["work"])
        player.seasonComboBox.setCurrentText(config["season"])
        player.jobComboBox.setCurrentText(config["job"])
        files = [player.sidebar.item(i).data(Qt.UserRole) for i in range(player.sidebar.count())]
        assert len(files) == config["expected_files"], files
        return files

    def finish(passed):
        if player is not None:
            player.close()
        app.processEvents()
        bad_dialogs = [d for d in report["dialogs"] if d["kind"] in ("critical", "warning")]
        ok = all(c["ok"] for c in report["checks"]) and not bad_dialogs and passed
        report["ok"] = ok
        with open(os.path.join(workdir, "smoke_result.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    if config.get("scenario") == "auto_connect":
        # 앱처럼 연다: 창을 먼저 보이고(공유 설정 없이) 공유 설정은 백그라운드에서 — 끝나면 resolve가 자동 설정까지 함
        from yesoncheck import shared_config

        startup = {}  # resolve가 불릴 때(백그라운드 읽기 직후)의 상태
        share_problems = []  # 변환표 자동 설정 확인 창에 보인 공유 문제
        original_dialog_init = PathMapSetupDialog.__init__

        def recording_dialog_init(self, proposal, *args, **kwargs):
            share_problems.extend(proposal.share_problems)
            original_dialog_init(self, proposal, *args, **kwargs)

        PathMapSetupDialog.__init__ = recording_dialog_init

        def window_shown():
            nonlocal player
            player, shown_s = show_like_launch(VideoPlayer, app)
            original_resolve = player.resolve_shared_config_problem

            def recording_resolve(*args, **kwargs):
                startup.update(path_map_problem=player.path_map_problem,
                               shared_config_problem=player.shared_config_problem)
                return original_resolve(*args, **kwargs)

            player.resolve_shared_config_problem = recording_resolve
            # 이 시간은 미리 데워진 러너에서 잼 (앞의 단계들이 Qt·모듈을 이미 불러옴) — 진짜 확인은 아래
            # "시작할 때 소리 재생기 없음"(창을 만들고 공유 설정을 불러올 때까지 QMediaPlayer를 만들지 않음)
            assert shown_s < 3, f"창을 만들어 보이는 데 {shown_s:.2f}초 걸렸습니다 (3초 미만이어야 함)"
            return {"construct_show_s": round(shown_s, 3)}

        def shared_config_load():
            from yesoncheck import path_map_setup

            load_s = wait_shared_config_load(player, app, timeout_s=120)
            assert startup, "공유 설정 불러오기가 끝났는데 resolve_shared_config_problem이 불리지 않았습니다"
            gather_s = player.shared_config_load_seconds
            # 끊긴 기억된 드라이브(W:)가 있어도 공유 확인은 정해진 시간까지만 기다림 (예전에는 ~21초, 무한히 걸릴 수도)
            bound_s = path_map_setup.SHARE_PROBE_TIMEOUT_S + 5
            assert gather_s < bound_s, f"백그라운드 불러오기 {gather_s:.1f}초 (응답 없는 공유를 {bound_s}초 안에 건너뛰어야 함)"
            return {"load_with_resolve_s": round(load_s, 3), "background_gather_s": round(gather_s, 3),
                    "background_gather_bound_s": bound_s}

        def no_media_player_at_startup():
            # 시작할 때 멀티미디어를 만들지 않는다는 구조적 확인 (창 생성·표시·공유 설정 불러오기·자동 설정까지).
            # 작품 목록 확인에서 job을 고르면 첫 영상이 열려(setMedia) 그때 만들어지므로 그 전에 확인
            from PyQt5.QtMultimedia import QMediaPlayer

            assert player.findChildren(QMediaPlayer) == [], "시작할 때 소리 재생기(QMediaPlayer)가 이미 만들어졌습니다"
            return "QMediaPlayer 없음"

        def auto_config_dir():
            assert startup["shared_config_problem"] is None, startup["shared_config_problem"]
            found = player.work_paths_config_dir or ""
            assert found.replace("/", "\\").lower().endswith("\\test_jn\\.yesoncheck"), found
            assert shared_config.load_local_settings().get("config_dir") == found
            return found

        def auto_path_map():
            assert startup["path_map_problem"], "변환표가 없는데 문제로 잡히지 않았습니다"
            assert player.path_map_problem is None, player.path_map_problem
            config_dir = player.work_paths_config_dir
            with open(os.path.join(config_dir, "path_map.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            assert [entry["mac"] for entry in data["shares"]] == [config["mac_prefix"]], data
            # 시험 데이터의 기본 파일('여기에_붙여넣기')은 SMB 공유 위에서 백업된 뒤 바꿔치기돼야 함
            backups = sorted(name for name in os.listdir(config_dir) if name.startswith("path_map.json.bak-"))
            assert len(backups) == 1, backups
            with open(os.path.join(config_dir, backups[0]), encoding="utf-8") as fh:
                backup_text = fh.read()
            assert "여기에_붙여넣기" in backup_text, backup_text
            return {"path_map": data, "backup": backups[0]}

        def dead_share_reported():
            # 서버가 없는 기억된 드라이브(CI가 등록): 실패가 아니라 확인 창의 공유 문제로만 보여야 함
            dead = config["dead_share"].lower()
            reported = [problem for problem in share_problems if dead in problem.lower()]
            assert reported, f"끊긴 공유 {config['dead_share']}가 공유 문제로 보이지 않았습니다: {share_problems}"
            return reported

        def media_player():
            # 기록만: 이미 만들어졌는지(작품 목록에서 첫 영상을 열면 만들어짐)와 만드는 데 걸린 시간 (없으면 여기서 만듦)
            from PyQt5.QtMultimedia import QMediaPlayer

            already = bool(player.findChildren(QMediaPlayer))
            media = player.mediaPlayer
            assert player.findChildren(QMediaPlayer) == [media]
            return {"created_before_this_check": already,
                    "media_player_create_s": round(player.media_player_create_seconds, 3)}

        listed = (check("창 바로 표시", window_shown)
                  and check("공유 설정 불러오기 (백그라운드)", shared_config_load)
                  and check("시작할 때 소리 재생기 없음", no_media_player_at_startup)
                  and check("공유 설정 자동 찾기", auto_config_dir)
                  and check("변환표 자동 설정", auto_path_map)
                  and check("작품 목록", work_listing))
        if listed and config.get("dead_share"):
            listed = check("끊긴 공유는 문제로 알림", dead_share_reported)
        if player is not None:
            check("소리 재생기 (처음 쓸 때 만든 시간)", media_player)
        return finish(bool(listed))

    player = VideoPlayer()  # 기존 실행 시험: 동기 생성자(공유 설정을 여기서 읽음)
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

    return finish(video is not None)
