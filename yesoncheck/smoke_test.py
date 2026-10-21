"""실행 시험: YesonCheck_Autocut --smoke-test <작업 폴더>

화면 없이(QT_QPA_PLATFORM=offscreen) 실제 앱 코드로 공유 설정·작품 목록·영상 열기·OCR·내보내기·병합을
실행하고 결과를 <작업 폴더>/smoke_result.json에 쓴 뒤 종료 코드(0 성공, 1 실패)로 알린다.
작업 폴더의 smoke_config.json(ci/make_test_data.py가 만듦)에 고를 작품·시즌·job과 기대 파일 수가 있다
(빌드된 앱 시험이면 기대 버전 expect_version도 — 앱이 읽은 build_info.json의 버전과 창 제목을 확인).
대화상자는 띄우지 않고 기록하며, 오류·경고 대화상자가 하나라도 나오면 실패로 본다.
시나리오(smoke_config의 scenario): 없음(기본), "auto_connect"(공유 설정·변환표 자동 설정), "update"(빌드된 앱이 NAS 흉내
폴더의 새 버전을 받아 업데이트 도우미에 넘김 — ci/update_e2e.py가 그 뒤 도우미·새 앱을 확인. close_others면 같은 설치의 다른
창이 켜진 채 — '다른 창도 닫고 업데이트' 확인 창에 [모두 닫고 업데이트]로 답하고 결과의 answered에 남김, box_answer).
"""

import dataclasses
import json
import os
import re
import sys
import threading
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


def app_version(expected, window_title):
    """빌드된 앱이 읽은 빌드 정보(build_info.json)의 버전이 expected이고 창 제목에 보이는지 → 빌드 정보 (dict)."""
    import dataclasses

    from yesoncheck import build_info

    info = build_info.current()
    assert info is not None, "소스 실행에는 빌드 정보(build_info.json)가 없습니다 (기대 버전은 빌드된 앱에서만 확인)"
    assert info.version == expected, f"앱 버전 {info.version} (기대 {expected})"
    assert window_title.split(" — ")[0] == build_info.title_base(), \
        f"창 제목 {window_title!r}에 버전이 없습니다 (기대 {build_info.title_base()!r})"
    return dataclasses.asdict(info)


# 애니매틱2 시험 영상(write_three_shot_clip)에서 TransNetV2가 찾아야 할 씬 시작 프레임
THREE_SHOT_STARTS = [0, 30, 60]
# 애니매틱2 실행 시험의 최대 시간 (빌드된 앱의 첫 TensorFlow·모델 불러오기는 약 12초)
ANIMATIC2_TIMEOUT_S = 300
# 업데이트 시나리오: 자동 업데이트 확인(NAS 흉내 폴더 읽기)과, '업데이트'부터 도우미에 넘길 때까지(받기 + Mac은 dmg에서
# 새 앱 준비 — 약 2 GB를 ditto)의 최대 시간
UPDATE_CHECK_TIMEOUT_S = 120
UPDATE_HANDOFF_TIMEOUT_S = 600


def write_three_shot_clip(path):
    """애니매틱2(TransNetV2) 시험용 합성 영상: 30프레임짜리 샷 3개 (샷마다 다른 단색 배경 + 움직이는 흰 원),
    cv2.VideoWriter mp4v 24fps. 씬 시작 프레임은 THREE_SHOT_STARTS. check_frozen_imports.py·pytest도 같이 씀.
    (Windows의 cv2.VideoWriter는 한글 경로를 못 쓰므로 ASCII 경로로)"""
    import cv2
    import numpy as np

    width, height = 320, 180
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 24, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"VideoWriter를 열 수 없습니다: {path}")
    for background in [(40, 40, 200), (40, 170, 40), (190, 110, 30)]:  # BGR
        for i in range(30):
            frame = np.full((height, width, 3), background, np.uint8)
            cv2.circle(frame, (40 + i * 8, height // 2), 24, (255, 255, 255), -1)
            writer.write(frame)
    writer.release()
    return path


def box_answer(config, title):
    """실행 시험이 exec_로 띄운 창(QMessageBox)에 누를 단추 — 없으면 None (기록하고 Ok): update 시나리오의 close_others(다른
    창이 켜진 채 업데이트 — ci/update_e2e.py의 다른 창 경로)면 '다른 창도 닫고 업데이트' 확인 창에 [모두 닫고 업데이트](Yes)."""
    from PyQt5.QtWidgets import QMessageBox

    from yesoncheck.player_update import UPDATE_OTHERS_TITLE

    if config.get("scenario") == "update" and config.get("close_others") and title == UPDATE_OTHERS_TITLE:
        return QMessageBox.Yes
    return None


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


def wait_released_workers(report, timeout_s):
    """창을 닫으며 붙잡아 둔 작업(release_worker — 업데이트 확인, 시간 안에 끝나지 않은 애니매틱2 등)이 끝나기를
    timeout_s초까지 기다림 → 끝나지 않은 작업 이름 목록 (남으면 report에 실패 항목으로 남김).

    app.launch는 이벤트 루프가 끝난 뒤 finish_released_workers로 기다리지만 실행 시험은 run()에서 바로 끝남: 실행 중인
    QThread가 남은 채 파이썬이 끝나면 파괴되며 프로세스가 죽음 ("QThread: Destroyed while thread is still running",
    Windows 0xC0000409)."""
    from yesoncheck.player_base import wait_for_released_workers

    still_running = wait_for_released_workers(timeout_s)
    if still_running:
        report["checks"].append({"name": "창을 닫은 뒤 남은 작업", "ok": False,
                                 "detail": f"{timeout_s:g}초 안에 끝나지 않음: {', '.join(still_running)}"})
    return still_running


def run(workdir):
    import cv2
    import numpy as np
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

    from yesoncheck import external_tools

    # 업데이트 확인(공유 설정을 불러온 뒤 자동)이 실제 GitHub에 닿지 않게: 실행 시험 결과가 GitHub의 상태(5xx·SSL
    # 오류면 경고 창 → 실패)에 따라 바뀌지 않도록. 업데이트를 시험하는 쪽이 주소(시험 서버)를 정했으면 그대로 둠
    os.environ.setdefault("YESONCHECK_UPDATE_URL", "off")
    with open(os.path.join(workdir, "smoke_config.json"), encoding="utf-8") as fh:
        config = json.load(fh)
    out_dir = os.path.join(workdir, "out")
    os.makedirs(out_dir, exist_ok=True)
    report = {"checks": [], "dialogs": [], "answered": []}  # answered: box_answer로 답한 창

    def record(kind, answer):
        def fake(parent, title, text, *args, **kwargs):
            report["dialogs"].append({"kind": kind, "title": title, "text": text})
            return answer
        return fake

    QMessageBox.critical = record("critical", QMessageBox.Ok)
    QMessageBox.warning = record("warning", QMessageBox.Ok)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
    # QMessageBox를 만들어 exec_()로 띄우는 창(업데이트 실패 창 — 자세한 글 setDetailedText)도 띄우지 않고 기록
    box_kinds = {QMessageBox.Critical: "critical", QMessageBox.Warning: "warning"}

    def record_box(box):
        details = box.detailedText()
        title = box.windowTitle() or box.property("ycTitle") or ""  # macOS의 QMessageBox는 창 제목을 버림
        text = f"{box.text()}\n\n{details}" if details else box.text()
        answer = box_answer(config, title)
        if answer is not None:
            button = box.button(answer)
            report["answered"].append({"title": title, "text": text,
                                       "answer": button.text() if button is not None else f"(단추 없음: {answer})"})
            return answer
        report["dialogs"].append({"kind": box_kinds.get(box.icon(), "information"), "title": title, "text": text})
        return QMessageBox.Ok

    QMessageBox.exec_ = record_box

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

    from yesoncheck.app import EXIT_WAIT_S, create_application, load_mount_map

    # app.launch와 같은 고해상도 설정 (Windows: 배율 반올림 없이)으로 만듦
    app = QApplication.instance() or create_application([sys.argv[0]])
    # app.launch처럼 (Mac) 이 Mac에서 공유가 붙은 곳을 읽어 경로 변환에 씀 — 빌드된 앱에서도 같은 코드가 돌게
    load_mount_map()
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

    def finish(passed, close_player=True):
        if player is not None and close_player:
            player.close()
        app.processEvents()
        # 창을 닫으며 놓은 작업이 끝나기를 앱처럼 EXIT_WAIT_S초까지 기다림 (남으면 실패 항목)
        still_running = wait_released_workers(report, EXIT_WAIT_S)
        bad_dialogs = [d for d in report["dialogs"] if d["kind"] in ("critical", "warning")]
        ok = all(c["ok"] for c in report["checks"]) and not bad_dialogs and passed
        report["ok"] = ok
        with open(os.path.join(workdir, "smoke_result.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        code = 0 if ok else 1
        if still_running:
            # 결과는 위에 씀 — 남은 QThread가 파이썬이 끝나며 파괴되어 죽지 않게 바로 끝냄 (app.finish_released_workers처럼)
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(code)
        return code

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

    if config.get("scenario") == "update":
        # 업데이트 끝까지 시험(ci/update_e2e.py)의 옛 앱: 앱처럼 열고 공유 설정을 불러오면 자동 업데이트 확인이 이어서
        # 돎 → NAS 흉내 폴더(<공유 설정>/updates)의 새 버전(expect_offer)을 알리는지 → '업데이트' → 받기(Mac은 새 앱 준비까지)
        # → 도우미에 넘김 → 도우미가 시작 기록을 남기면 창이 닫힘. 도우미(이 앱이 끝나기를 기다렸다 바꾸고 다시 켬)가 끝나기는
        # 기다리지 않음 — 결과를 쓰고 끝냄
        from yesoncheck import update_install

        handed = []  # 도우미에 넘긴 인자 — 진짜 도우미를 띄운 뒤에 남김

        def recording(launch):
            def launch_and_record(*args):
                proc = launch(*args)
                handed.append(list(args))
                return proc  # 앱이 이것으로 도우미가 살아 있는지 봄 (_hand_off)
            return launch_and_record

        update_install.launch_helper_mac = recording(update_install.launch_helper_mac)
        update_install.launch_helper_windows = recording(update_install.launch_helper_windows)

        def update_log_tail():
            try:
                with open(update_install.log_path(), encoding="utf-8") as fh:
                    return "".join(fh.readlines()[-40:])
            except FileNotFoundError:
                return "(업데이트 기록 없음)"

        def window_shown():
            nonlocal player
            player, shown_s = show_like_launch(VideoPlayer, app)
            return {"construct_show_s": round(shown_s, 3)}

        def shared_config_load():
            load_s = wait_shared_config_load(player, app, timeout_s=120)
            return {"load_s": round(load_s, 3), "config_dir": shared_config_ok()}

        def update_offer():
            # 공유 설정을 불러온 뒤 앱이 부른 자동 확인(start_update_check(manual=False))이 끝나기를 기다림
            started = time.perf_counter()
            while player.update_check_running:
                if time.perf_counter() - started > UPDATE_CHECK_TIMEOUT_S:
                    raise TimeoutError(f"업데이트 확인이 {UPDATE_CHECK_TIMEOUT_S}초 안에 끝나지 않았습니다")
                app.processEvents()
                time.sleep(0.01)
            offer = player.update_offer
            assert offer is not None, f"새 버전을 알리지 않았습니다 — 업데이트 기록:\n{update_log_tail()}"
            assert str(offer.manifest.version) == config["expect_offer"], \
                f"알린 버전 {offer.manifest.version} (기대 {config['expect_offer']})"
            assert offer.result.source == "NAS", offer.result
            assert player.update_banner.mode() == "offer", player.update_banner.mode()
            return {"version": str(offer.manifest.version), "source": offer.result.source,
                    "file": offer.entry.name, "size": offer.entry.size, "check_s": round(time.perf_counter() - started, 3)}

        def hand_off():
            # 띠의 '업데이트'와 같은 일 → 받기·준비는 뒤 스레드, 다 되면 업데이트 기록·도우미, 도우미가 시작 기록을 남기면
            # 창 닫기 (_hand_off). 실패하면 띠가 다시 알림으로 (실패 창은 report["dialogs"]에)
            started = time.perf_counter()
            player.start_update()
            while player.isVisible():
                if player.update_banner.mode() != "progress":
                    raise AssertionError(f"도우미에 넘기지 못했습니다 (띠: {player.update_banner.mode()}) — 대화상자 "
                                         f"{report['dialogs']}\n업데이트 기록:\n{update_log_tail()}")
                if time.perf_counter() - started > UPDATE_HANDOFF_TIMEOUT_S:
                    raise TimeoutError(f"{UPDATE_HANDOFF_TIMEOUT_S}초 안에 도우미에 넘기지 못했습니다 — 업데이트 기록:\n"
                                       f"{update_log_tail()}")
                app.processEvents()
                time.sleep(0.01)
            assert handed, "도우미를 띄우지 않았는데 창이 닫혔습니다"
            pending = update_install.read_pending()
            assert pending is not None and pending.target == config["expect_offer"], pending
            return {"helper": handed[0], "pending": dataclasses.asdict(pending),
                    "seconds": round(time.perf_counter() - started, 2)}

        passed = (check("창 바로 표시", window_shown)
                  and check("공유 설정 불러오기 (백그라운드)", shared_config_load)
                  and check("새 버전 알림 (자동 업데이트 확인)", update_offer)
                  and check("업데이트 → 도우미에 넘김", hand_off))
        # 넘겼으면 창은 앱이 닫았음 (다시 닫지 않음) — 도우미가 시작하지 못했으면 창이 그대로 있음
        return finish(bool(passed), close_player=player is not None and player.isVisible())

    player = VideoPlayer()  # 기존 실행 시험: 동기 생성자(공유 설정을 여기서 읽음)
    if "expect_version" in config:  # make_test_data.py --expect-version (빌드된 앱)
        check("앱 버전", lambda: app_version(config["expect_version"], player.windowTitle()))
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

    def animatic2():
        """애니매틱2(TransNetV2): 콤보박스에 항목이 있고, 앱과 같은 설정의 워커가 앱처럼 워커 스레드에서
        합성 3샷 영상의 컷을 찾는지 (빌드된 앱에서 TensorFlow를 워커 스레드로 처음 불러오는 경로까지)."""
        from yesoncheck.player_base import release_worker
        from yesoncheck.transnetv2_detector import transnetv2_weights_dir
        from yesoncheck.workers import TransNetV2Worker

        assert player is not None and player.ocrModeComboBox.findData("animatic2") >= 0, \
            "분석 방식 목록에 '애니매틱2 (TransNetV2)'가 없습니다 (TensorFlow 또는 가중치가 빌드에 없음)"
        # TransNetV2 MIT 라이선스 고지가 가중치 옆에 함께 들어 있어야 함 (spec)
        license_path = os.path.join(transnetv2_weights_dir(), "LICENSE")
        assert os.path.isfile(license_path), f"TransNetV2 라이선스 고지(LICENSE)가 없습니다: {license_path}"
        with open(license_path, encoding="utf-8") as fh:
            assert "MIT License" in fh.read(), f"LICENSE 내용이 MIT 고지가 아닙니다: {license_path}"
        # 시작·OCR 경로는 TensorFlow를 불러오지 않아야 함 (애니매틱2 감지를 시작할 때 처음 불러옴)
        assert "tensorflow" not in sys.modules, "애니매틱2 감지 전에 TensorFlow가 이미 불려 있습니다"
        path = write_three_shot_clip(os.path.join(workdir, "animatic2_three_shots.mp4"))
        result = {}
        # 앱(player_base의 애니매틱2 분석)과 같은 설정
        worker = TransNetV2Worker(path, threshold=0.3, min_scene_len=10,
                                  detect_gradual_transitions=True, post_process_histogram=True)
        worker.completed.connect(lambda r: result.update(r))
        worker.error.connect(lambda m: result.update(error=m))
        # 상태 신호를 보낸 스레드 (DirectConnection: 보낸 스레드에서 바로 실행) — 앱처럼 워커 스레드에서 돌았는지
        threads = set()
        worker.status.connect(lambda _message: threads.add(threading.get_ident()), type=Qt.DirectConnection)
        # 앱처럼 QThread.start()로 워커 스레드에서 돌리고(TensorFlow도 그 스레드에서 처음 불러옴), 끝날 때까지
        # 이벤트를 처리하며 기다림 → 워커가 보낸 completed·error(대기열 신호)를 받음
        started = time.perf_counter()
        worker.start()
        deadline = started + ANIMATIC2_TIMEOUT_S
        while not worker.isFinished():
            if time.perf_counter() > deadline:
                worker.stop()
                # 실행 중인 QThread를 놓으면 파괴되며 앱이 죽어 결과 파일도 못 씀 → 끝날 때까지 붙잡아 둠
                release_worker(worker, "애니매틱2 실행 시험")
                raise TimeoutError(f"애니매틱2 컷 감지가 {ANIMATIC2_TIMEOUT_S}초 안에 끝나지 않았습니다")
            app.processEvents()
            time.sleep(0.01)
        assert worker.wait(10000), "TransNetV2Worker 스레드가 끝나지 않았습니다"
        app.processEvents()  # 끝나기 직전에 보낸 신호까지 처리
        assert threads and threading.get_ident() not in threads, \
            "TransNetV2Worker가 메인 스레드에서 돌았습니다 (앱은 QThread.start()로 워커 스레드에서 돌림)"
        assert "error" not in result, result.get("error")
        starts = [s["start_frame"] for s in result.get("segments", [])]
        assert starts == THREE_SHOT_STARTS, f"씬 시작 프레임 {starts} (기대 {THREE_SHOT_STARTS})"
        return {"cuts": starts, "seconds": round(time.perf_counter() - started, 2), "thread": "worker",
                "license": license_path}

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
    check("애니매틱2 (TransNetV2)", animatic2)
    check("OCR 모델 폴더", ocr_model_dir)
    check("긴 경로 허용", long_path_aware)

    return finish(video is not None)
