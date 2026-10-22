#!/usr/bin/env python3
"""화면 픽셀 비교 검사: 코드를 나누거나 옮긴 뒤에도 앱 화면이 픽셀까지 같은지 확인한다.

사용:
  screenshot_check.py capture --out DIR [--scene NAME ...] [--root DIR]
  screenshot_check.py compare --baseline DIR --current DIR [--scene NAME ...] [--max-diff N]

- capture: 장면마다 자식 프로세스를 하나씩 띄워(같은 프로세스에서 이어 찍으면 앞 장면이 뒷 장면을 오염시킴) 진짜
  VideoPlayer·OCRReviewDialog를 만들고, 정착한 화면을 widget.grab()으로 DIR/<장면>.png 에, 위젯 트리 덤프(클래스·objectName·
  geometry·보임·글자·styleSheet sha256)를 DIR/<장면>.tree.json 에 저장한다. 찍은 환경·정착 정보는 DIR/<장면>.meta.json,
  자식의 출력은 DIR/<장면>.log. --scene을 여러 번 주면 그 장면만(기본: 전부). --root: 이 검사를 돌리는 저장소가 아닌 다른
  체크아웃(예: 리팩토링 전 커밋의 worktree)의 yesoncheck를 찍을 때. 장면이 끝까지 성공해야만(자식이 창을 닫고 뒤 스레드까지
  정리하고 종료 코드 0) meta.json에 완료 표시와 PNG·트리의 sha256을 적는다 — 실패한 장면의 PNG·트리·meta는 지우고 로그만 남긴다.
- compare: 두 폴더의 장면마다 PNG 바이트와 트리 JSON이 모두 같으면 종료 0, 다르면 종료 1 + 어느 장면이 어디서 다른지
  (다른 픽셀의 바운딩 박스, 트리의 바뀐 위젯과 값, 대화 상자 차이)를 출력한다. --scene을 안 주면 고정된 장면 전부가 두 폴더
  모두에 있어야 하고(없으면 차이 — 양쪽에서 같이 빠져도), 디스크에 있는 그 밖의 PNG도 함께 비교한다. 장면의 meta.json에 완료
  표시가 없거나 PNG·트리가 meta의 sha256과 다르면(찍기가 끝까지 가지 못했거나 찍은 뒤 바뀐 파일) 그 장면은 차이다. 폴더가
  없거나 장면 이름이 틀리면 종료 2.

같은 기계·같은 플랫폼에서 전/후를 찍어 비교하는 도구다 (글꼴·DPI·스타일이 플랫폼마다 달라 플랫폼 사이 비교는 뜻이 없음).
전/후를 같은 러너가 찍어야 하고, Qt·글꼴·화면이 다르게 찍힌 폴더끼리 비교하면 [주의]로 알린다.

격리 (자식 프로세스의 환경): QT_QPA_PLATFORM=offscreen, HOME·USERPROFILE·YESONCHECK_CONFIG_DIR(빈 work_paths.json)·창 기록
(YESONCHECK_INSTANCES_DIR)을 장면마다 새 임시 폴더로 (북마크·오버레이 설정·주석 내보내기 폴더는 HOME 아래라 함께 격리) →
사용자 파일을 읽지도 쓰지도 않고 NAS도 필요 없다. 글자 커서 깜박임은 끔(QApplication.setCursorFlashTime(0)). 진짜 QMessageBox·
QFileDialog는 띄우지 않고 기록만 한다 (offscreen에서 진짜 창을 띄우면 멈추거나 죽음) — 경고·오류 창이 뜨면 그 장면은 실패.
영상은 저장소 ffmpeg로 만든 합성 영상을 임시 폴더에 두고 쓴다 (실제 NAS·작품의 영상은 쓰지 않음).

정착 (settle): 타이머로 글자가 바뀌는 곳이 있다(재생 FPS 표시의 1초 타이머, 검토 창의 지연 갱신). 그래서 뒤 스레드가 끝나기를
기다린 뒤, 이벤트를 FIXED_WAIT_S초 돌리고, 연속 두 번 찍은 그림(GAP_S초 간격)이 바이트까지 같을 때까지 되풀이한다 —
SETTLE_MAX_S초 안에 같아지지 않으면 그 장면은 실패로 크게 알린다.

한계: 마우스·키보드 조작은 없다 (정해진 함수 호출로 장면을 만듦). 영상 프레임은 이 기계의 디코더 결과라 기계 사이는 비교하지
않는다. 이벤트 루프를 돌리며 바뀌는 값(시계·무작위 포트·토큰)이 화면에 나오는 장면은 정착하지 않아 실패로 드러난다.
"""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import namedtuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.abspath(__file__)

FIXED_WAIT_S = 1.5  # 정착: 먼저 이벤트를 이만큼 돌림
GAP_S = 0.5  # 정착: 연속 두 번 찍는 사이 (이벤트를 돌리며 기다림)
SETTLE_MAX_S = 10.0  # 정착: 고정 대기 뒤 연속 두 번이 같아질 때까지의 최대 시간
BACKGROUND_MAX_S = 10.0  # 뒤 스레드가 끝나기를 기다리는 최대 시간 (장면을 만든 뒤, 창을 닫은 뒤)
SCENE_TIMEOUT_S = 300  # 자식 프로세스 하나의 최대 시간

MAIN_SIZE = (1200, 800)  # offscreen 화면은 800x600이라 장면마다 창 크기를 명시
REVIEW_SIZE = (1400, 900)

# 합성 영상: 파일 이름 → ffmpeg lavfi 입력. 장면마다 다른 내용이 보이게 소스를 다르게 함
MEDIA_SOURCES = {"clip_a.mp4": "testsrc", "clip_b.mp4": "testsrc2", "clip_c.mp4": "smptebars"}
MEDIA_SECONDS = 2

# 환경 변수 중 그림을 바꾸는 것은 자식에게 물려주지 않음 (그 밖의 것은 그대로 — Python·Qt를 찾는 데 필요)
INHERITED_ENV_DROPPED = (
    "QT_SCALE_FACTOR", "QT_AUTO_SCREEN_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS", "QT_FONT_DPI", "QT_STYLE_OVERRIDE",
    "QT_ENABLE_HIGHDPI_SCALING", "QT_DEVICE_PIXEL_RATIO", "QT_QPA_PLATFORMTHEME", "QT_QPA_FONTDIR",
)

OUTPUT_SUFFIXES = ("png", "tree.json", "meta.json")
TREE_FIELDS = ("class", "meta_class", "name", "geometry", "visible", "enabled", "text", "values", "style_sha256")
ENVIRONMENT_KEYS = ("python", "qt", "pyqt", "platform", "machine", "style", "font", "screen")
DEFAULT_MAX_DIFF = 40  # 장면마다 보여 줄 트리 차이의 최대 줄 수
REGION_MERGE_PX = 7  # 이만큼 가까운 다른 픽셀은 한 영역으로 묶음
MAX_REGIONS_SHOWN = 12


# ---------------------------------------------------------------- 장면 (자식 프로세스 안에서 돎)
#
# 장면 = 창을 만들어 정해진 상태로 만든 뒤 그 창을 돌려주는 함수. 정착·찍기·저장은 공통 코드가 한다.
# 함수가 하는 일은 앱의 함수를 부르는 것뿐이다 (마우스·키보드 이벤트를 흉내 내지 않음).

Scene = namedtuple("Scene", "build media description")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class SceneContext:
    """장면 함수에 건네는 도구: 합성 영상 경로, 이벤트 돌리기, 메인 창 만들기, 정리 목록."""

    def __init__(self, app, work):
        self.app = app
        self.work = work
        self.cleanups = []  # 찍은 뒤 거꾸로 부름

    def media(self, name):
        return os.path.join(self.work, "media", name)

    def pump(self, seconds):
        pump(self.app, seconds)

    def new_player(self):
        from yesoncheck.main_window import VideoPlayer

        player = VideoPlayer()
        player.resize(*MAIN_SIZE)
        player.show()
        self.cleanups.append(player.close)
        return player

    def open_video(self, player, kind, name):
        require(player.open_file(kind, self.media(name)), f"영상을 열지 못함: {kind} {name}")


def collapsible_boxes(player):
    # CollapsibleBox 클래스를 import하지 않고 이름으로 찾음 (모듈 위치가 바뀌어도 이 검사는 그대로)
    from PyQt5.QtWidgets import QWidget

    return [w for w in player.findChildren(QWidget) if type(w).__name__ == "CollapsibleBox"]


def expand(box):
    if not box.toggle_button.isChecked():
        box.toggle_button.click()
    require(box.content_area.isVisibleTo(box), f"접는 상자가 펼쳐지지 않음: {box.toggle_button.text()}")


def scene_main_window(ctx):
    return ctx.new_player()


def scene_light_theme(ctx):
    player = ctx.new_player()
    player.toggle_theme()
    require(player.current_theme == "light", f"밝은 테마가 되지 않음: {player.current_theme}")
    return player


def scene_video_a_open(ctx):
    player = ctx.new_player()
    ctx.open_video(player, "A", "clip_a.mp4")
    return player


def scene_wipe_ab(ctx):
    player = ctx.new_player()
    ctx.open_video(player, "A", "clip_a.mp4")
    ctx.open_video(player, "B", "clip_b.mp4")
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)
    player.wipeYButton.setChecked(True)
    require(player.videoWidget.wipe_enabled_x and player.videoWidget.wipe_enabled_y, "와이프가 켜지지 않음")
    return player


def scene_thumbnail_mode(ctx):
    player = ctx.new_player()
    player.add_files_to_sidebar([ctx.media(name) for name in sorted(MEDIA_SOURCES)])
    player.switch_to_thumbnail_mode()
    return player


def check_thumbnails_shown(player):
    # 썸네일은 뒤 스레드가 만들어 넘김 — 뒤 스레드를 기다린 다음에 부름
    require(player.sidebar.count() == len(MEDIA_SOURCES), f"사이드바 항목 수가 다름: {player.sidebar.count()}")
    empty = [player.sidebar.item(i).text() for i in range(player.sidebar.count()) if player.sidebar.item(i).icon().isNull()]
    require(not empty, f"썸네일이 붙지 않은 항목: {empty}")


def scene_boxes_expanded(ctx):
    player = ctx.new_player()
    boxes = collapsible_boxes(player)
    require(len(boxes) == 4, f"접는 상자가 4개(ROI·OCR 분석·결과 관리·주석)가 아님: {len(boxes)}")
    for box in boxes:
        expand(box)
    return player


def scene_overlay_visible(ctx):
    player = ctx.new_player()
    ctx.open_video(player, "A", "clip_a.mp4")
    player.show_overlay_controls()
    require(player.overlayFrame.isVisible(), "오버레이 컨트롤이 보이지 않음")
    return player


def scene_annotation_mode(ctx):
    player = ctx.new_player()
    ctx.open_video(player, "A", "clip_a.mp4")
    boxes = [box for box in collapsible_boxes(player) if "수정 사항 주석" in box.toggle_button.text()]
    require(len(boxes) == 1, f"주석 접는 상자를 하나 찾아야 함: {len(boxes)}")
    expand(boxes[0])
    player.annotationModeButton.setChecked(True)  # 영상 A가 없으면 도로 꺼짐
    require(player.annotationModeButton.isChecked(), "주석 모드가 켜지지 않음")
    return player


REVIEW_SEGMENTS = [
    {"start_frame": 0, "end_frame": 11, "start_time": 0.0, "end_time": 0.5, "duration": 0.5,
     "text": "A", "edited_text": "A", "roi_preview": None, "detections": []},
    {"start_frame": 12, "end_frame": 23, "start_time": 0.5, "end_time": 1.0, "duration": 0.5,
     "text": "B", "edited_text": "B", "roi_preview": None, "detections": []},
]


def scene_ocr_review(ctx):
    from PyQt5 import sip
    from yesoncheck.player_review import OCRReviewDialog

    dialog = OCRReviewDialog(None, [dict(s) for s in REVIEW_SEGMENTS], fps=24, total_frames=24, ocr_mode="titmouse")
    dialog.resize(*REVIEW_SIZE)
    dialog.show()

    def delete():
        dialog.close()
        sip.delete(dialog)  # deleteLater()로 미루면 뒤의 스타일 바꾸기에서 죽음 — 바로 지움

    ctx.cleanups.append(delete)
    return dialog


# 장면 이름(고정) → 장면 정의. media: 이 장면이 쓰는 합성 영상 (capture가 장면 폴더에 복사해 줌)
SCENES = {
    "main_window": Scene(scene_main_window, (), "처음 켠 메인 창 (어두운 테마)"),
    "light_theme": Scene(scene_light_theme, (), "밝은 테마로 바꾼 메인 창"),
    "video_a_open": Scene(scene_video_a_open, ("clip_a.mp4",), "영상 A를 연 뒤"),
    "wipe_ab": Scene(scene_wipe_ab, ("clip_a.mp4", "clip_b.mp4"), "영상 A·B와 X·Y 와이프"),
    "thumbnail_mode": Scene(scene_thumbnail_mode, tuple(sorted(MEDIA_SOURCES)), "사이드바 썸네일 모드 (영상 3개)"),
    "boxes_expanded": Scene(scene_boxes_expanded, (), "접는 상자 4개(ROI·OCR 분석·결과 관리·주석) 펼침"),
    "overlay_visible": Scene(scene_overlay_visible, ("clip_a.mp4",), "오버레이 컨트롤 보임"),
    "annotation_mode": Scene(scene_annotation_mode, ("clip_a.mp4",), "주석 상자를 펼치고 주석 모드 켬"),
    "ocr_review": Scene(scene_ocr_review, (), "OCR 검토 창 (구간 2개, 24fps, titmouse)"),
}
AFTER_BACKGROUND_CHECKS = {"thumbnail_mode": check_thumbnails_shown}


# ---------------------------------------------------------------- 자식: 격리·정착·찍기·덤프


def pump(app, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def running_threads():
    """프로세스 안에서 돌고 있는 QThread 전부 (워커를 어디에 붙잡아 두었든)."""
    import gc

    from PyQt5.QtCore import QThread

    running = []
    for obj in gc.get_objects():
        if isinstance(obj, QThread):
            try:
                if obj.isRunning():
                    running.append(obj)
            except RuntimeError:  # C++ 객체가 이미 지워진 스레드는 돌고 있지 않음
                continue
    return running


def wait_for_background(app, what):
    """뒤 QThread(썸네일·공유 설정·목록 읽기 등)가 모두 끝나기를 기다림 → 걸린 초. 시간 안에 안 끝나면 실패."""
    from yesoncheck import player_base

    started = time.monotonic()
    while True:
        app.processEvents()
        busy = running_threads()
        if not busy:
            break
        if time.monotonic() - started > BACKGROUND_MAX_S:
            raise RuntimeError(f"{what}: 뒤 스레드가 {BACKGROUND_MAX_S:g}초 안에 끝나지 않음: "
                               f"{[type(t).__name__ for t in busy]}")
        time.sleep(0.02)
    still_running = player_base.wait_for_released_workers(BACKGROUND_MAX_S)
    require(not still_running, f"{what}: 붙잡아 둔 작업이 끝나지 않음: {still_running}")
    return time.monotonic() - started


def image_bytes(image):
    pointer = image.constBits()
    pointer.setsize(image.byteCount())
    return bytes(pointer)


def changed_box(first, second):
    """같은 크기의 두 그림이 다른 곳의 바운딩 박스 문구 (정착하지 않을 때 어디가 계속 바뀌는지 알리는 용도)."""
    import numpy as np

    if first.size() != second.size():
        return f"크기가 다름 ({first.width()}x{first.height()} → {second.width()}x{second.height()})"

    def pixels(image):
        return np.frombuffer(image_bytes(image), np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)

    ys, xs = np.nonzero(np.any(pixels(first) != pixels(second), axis=2))
    return box_text(int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()))


def settle(app, widget):
    """이벤트를 FIXED_WAIT_S초 돌린 뒤, 연속 두 번 grab()이 바이트까지 같아질 때까지 → (그림, 정착 정보)."""
    started = time.monotonic()
    pump(app, FIXED_WAIT_S)
    previous = widget.grab().toImage()
    rounds = 0
    deadline = time.monotonic() + SETTLE_MAX_S
    while True:
        pump(app, GAP_S)
        current = widget.grab().toImage()
        rounds += 1
        if current.size() == previous.size() and image_bytes(current) == image_bytes(previous):
            info = {"fixed_wait_s": FIXED_WAIT_S, "gap_s": GAP_S, "rounds": rounds, "consecutive_identical": 2,
                    "settle_s": round(time.monotonic() - started, 2)}
            return current, info
        if time.monotonic() > deadline:
            raise RuntimeError(f"{SETTLE_MAX_S:g}초 안에 그림이 정착하지 않음 (연속 두 번이 계속 다름, {rounds}번 찍음, "
                               f"마지막 두 장이 다른 곳 {changed_box(previous, current)})")
        previous = current


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def tmp_roots(work):
    roots = {work, os.path.realpath(work)}
    return sorted(roots, key=len, reverse=True)


def normalizer(work):
    """덤프에 들어가는 글에서 임시 폴더 경로와 장면마다 달라지는 값(동기화 서버의 포트·토큰)을 고정 문자열로."""
    roots = tmp_roots(work)
    token_url = re.compile(r"(ws://127\.0\.0\.1):\d+(/\?token=)[^\s\"'<>)]+")

    def normalize(value):
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if not isinstance(value, str):
            return value
        for root in roots:
            value = value.replace(root, "<TMP>")
        return token_url.sub(r"\1:<PORT>\2<TOKEN>", value)

    return normalize


def describe_widget(widget):
    """위젯의 글자(text)와 그 밖의 보이는 값(values: 항목·값·확인 상태 등)."""
    from PyQt5 import QtWidgets as W

    text, values = "", {}
    if isinstance(widget, W.QLabel):
        text = widget.text()
    elif isinstance(widget, W.QAbstractButton):
        text = widget.text()
        if widget.isCheckable():
            values["checked"] = widget.isChecked()
    elif isinstance(widget, W.QGroupBox):
        text = widget.title()
    elif isinstance(widget, W.QComboBox):
        text = widget.currentText()
        values["index"] = widget.currentIndex()
        values["items"] = [widget.itemText(i) for i in range(widget.count())]
    elif isinstance(widget, W.QLineEdit):
        text = widget.text()
        values["placeholder"] = widget.placeholderText()
    elif isinstance(widget, (W.QTextEdit, W.QPlainTextEdit)):
        text = widget.toPlainText()
    elif isinstance(widget, W.QProgressBar):
        text = widget.text()
        values.update(value=widget.value(), minimum=widget.minimum(), maximum=widget.maximum())
    elif isinstance(widget, W.QAbstractSlider):
        values.update(value=widget.value(), minimum=widget.minimum(), maximum=widget.maximum())
    elif isinstance(widget, W.QAbstractSpinBox):
        text = widget.text()
    elif isinstance(widget, W.QListWidget):
        items = [widget.item(i) for i in range(widget.count())]
        values["items"] = [item.text() for item in items]
        values["has_icon"] = [not item.icon().isNull() for item in items]
    elif isinstance(widget, W.QTableWidget):
        rows, columns = widget.rowCount(), widget.columnCount()
        cells = [[widget.item(r, c).text() if widget.item(r, c) is not None else None for c in range(columns)]
                 for r in range(rows)]
        headers = [widget.horizontalHeaderItem(c).text() if widget.horizontalHeaderItem(c) is not None else None
                   for c in range(columns)]
        values.update(rows=rows, columns=columns, headers=headers, cells=cells)
    elif isinstance(widget, (W.QMenuBar, W.QMenu)):
        values["actions"] = [action.text() for action in widget.actions()]
    if widget.isWindow():
        values["window_title"] = widget.windowTitle()
    return text, values


def dump_widget(widget, normalize):
    """위젯 하나와 그 아래 위젯 트리. 형제는 (위치·크기·클래스·이름·글자)로 정렬 → 만든 차례가 달라져도 같은 덤프."""
    text, values = describe_widget(widget)
    rect = widget.geometry()
    sheet = widget.styleSheet()
    node = {
        "class": type(widget).__name__,
        "meta_class": widget.metaObject().className(),
        "name": widget.objectName(),
        "geometry": [rect.x(), rect.y(), rect.width(), rect.height()],
        "visible": widget.isVisible(),
        "enabled": widget.isEnabled(),
        "text": normalize(text),
        "values": normalize(values),
        "style_sha256": sha256_hex(sheet.encode("utf-8")) if sheet else "",
    }
    children = [dump_widget(child, normalize) for child in widget.children() if child.isWidgetType()]
    children.sort(key=lambda n: (n["geometry"][1], n["geometry"][0], n["geometry"][2], n["geometry"][3], n["class"],
                                 n["name"], n["text"]))
    node["children"] = children
    return node


def check_isolated_environment(work):
    """부모가 정한 격리 환경이 그대로인지 확인 (사용자의 홈·공유 설정을 읽고 있으면 바로 실패)."""
    expected = {
        "QT_QPA_PLATFORM": "offscreen",
        "HOME": os.path.join(work, "home"),
        "USERPROFILE": os.path.join(work, "home"),
        "YESONCHECK_CONFIG_DIR": os.path.join(work, "share", ".yesoncheck"),
        "YESONCHECK_INSTANCES_DIR": os.path.join(work, "instances"),
    }
    for key, value in expected.items():
        require(os.environ.get(key) == value, f"격리 환경 변수가 다름: {key}={os.environ.get(key)!r} (기대 {value!r})")
    require(os.path.expanduser("~") == expected["HOME"], f"~가 임시 홈이 아님: {os.path.expanduser('~')}")


def install_dialog_guards():
    """진짜 대화 상자를 띄우지 않고 기록만 (tests/conftest.py의 dialogs 픽스처와 같은 방식). 기록 목록을 돌려줌."""
    from PyQt5.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox

    recorded = []

    def recorder(kind, answer):
        def fake(parent, title, text, *args, **kwargs):
            recorded.append({"kind": kind, "title": title, "text": text})
            return answer

        return fake

    def refuse(*args, **kwargs):
        raise AssertionError(f"장면이 진짜 대화 상자·파일 선택 창을 열려 함: {args[1:3]}")

    box_kinds = {QMessageBox.Critical: "critical", QMessageBox.Warning: "warning",
                 QMessageBox.Information: "information", QMessageBox.Question: "question"}

    def box_exec(box):
        kind = box_kinds.get(box.icon(), "other")
        details = box.detailedText()
        text = f"{box.text()}\n\n{details}" if details else box.text()
        recorded.append({"kind": kind, "title": box.windowTitle() or box.property("ycTitle") or "", "text": text})
        return QMessageBox.Yes if kind == "question" else QMessageBox.Ok

    QDialog.exec_ = refuse
    QDialog.exec = refuse
    QMessageBox.critical = recorder("critical", QMessageBox.Ok)
    QMessageBox.warning = recorder("warning", QMessageBox.Ok)
    QMessageBox.information = recorder("information", QMessageBox.Ok)
    QMessageBox.question = recorder("question", QMessageBox.Yes)
    QMessageBox.exec_ = box_exec
    QMessageBox.exec = box_exec
    for name in ("getExistingDirectory", "getOpenFileName", "getOpenFileNames", "getSaveFileName"):
        setattr(QFileDialog, name, refuse)
    QInputDialog.getText = refuse
    return recorded


def describe_environment(app):
    from PyQt5.QtCore import PYQT_VERSION_STR, qVersion

    screen = app.primaryScreen()
    font = app.font()
    return {
        "python": platform.python_version(),
        "qt": qVersion(),
        "pyqt": PYQT_VERSION_STR,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "style": app.style().objectName(),
        "font": f"{font.family()} {font.pointSizeF():g}",
        "screen": [screen.geometry().width(), screen.geometry().height(), screen.devicePixelRatio(),
                   round(screen.logicalDotsPerInch(), 2)],
    }


def child_main(args):
    """capture가 장면마다 띄우는 자식의 진입점. 어떤 예외든 스택 트레이스를 그대로 출력하고 종료 코드 1로 끝낸다 (살아 있는
    창을 둔 채 파이썬이 정리하다 죽어 종료 코드가 가려지지 않게 바로 끝냄)."""
    try:
        run_scene(args)
    except BaseException:
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)


def run_scene(args):
    work = os.path.abspath(args.work)
    root = os.path.abspath(args.root)
    sys.path.insert(0, root)
    check_isolated_environment(work)
    started = time.monotonic()

    from PyQt5.QtWidgets import QApplication

    app = QApplication(["screenshot_check"])
    app.setCursorFlashTime(0)  # 글자 커서 깜박임이 그림을 바꾸지 않게
    import yesoncheck

    require(os.path.realpath(yesoncheck.__file__).startswith(os.path.realpath(root) + os.sep),
            f"다른 곳의 yesoncheck를 불러옴: {yesoncheck.__file__} (기대: {root} 아래)")
    dialogs = install_dialog_guards()
    scene = SCENES[args.scene]

    ctx = SceneContext(app, work)
    widget = scene.build(ctx)
    background_s = wait_for_background(app, "장면을 만든 뒤")
    if args.scene in AFTER_BACKGROUND_CHECKS:
        AFTER_BACKGROUND_CHECKS[args.scene](widget)
    image, settle_info = settle(app, widget)
    settle_info["background_wait_s"] = round(background_s, 2)

    bad = [d for d in dialogs if d["kind"] in ("critical", "warning")]
    require(not bad, f"장면 중에 경고·오류 창이 뜸: {bad}")

    normalize = normalizer(work)
    out = os.path.abspath(args.out)
    png_path = os.path.join(out, f"{args.scene}.png")
    require(image.save(png_path, "PNG"), f"PNG를 저장하지 못함: {png_path}")
    pixels = image_bytes(image)
    document = {
        "scene": args.scene,
        "dialogs": normalize(dialogs),
        "tree": dump_widget(widget, normalize),
    }
    with open(os.path.join(out, f"{args.scene}.tree.json"), "w", encoding="utf-8") as fh:
        json.dump(document, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    meta = {
        "scene": args.scene,
        "size": [image.width(), image.height()],
        "device_pixel_ratio": image.devicePixelRatio(),
        "pixels_sha256": sha256_hex(pixels),
        "settle": settle_info,
        "environment": describe_environment(app),
    }
    with open(os.path.join(out, f"{args.scene}.meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")

    # 정리: 창을 닫고 뒤 스레드가 끝나기를 기다림 (실행 중인 QThread가 있는 채로 끝나면 프로세스가 죽음)
    for cleanup in reversed(ctx.cleanups):
        cleanup()
    pump(app, 0.2)
    wait_for_background(app, "창을 닫은 뒤")
    print(f"scene {args.scene}: 완료 ({time.monotonic() - started:.1f}초)", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)  # 파이썬이 끝나며 Qt 객체를 정리하는 순서에 기대지 않음 (찍은 뒤라 잃을 것이 없음)


# ---------------------------------------------------------------- capture (부모)


def ffmpeg_path(root):
    """저장소의 정적 ffmpeg(vendor/ffmpeg/<아키텍처>), 없으면 PATH의 ffmpeg."""
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    vendored = os.path.join(root, "vendor", "ffmpeg", "windows" if sys.platform == "win32" else platform.machine(), exe)
    if os.path.isfile(vendored):
        return vendored
    found = shutil.which("ffmpeg")
    if found is None:
        raise SystemExit(f"ffmpeg를 찾지 못함: {vendored} 도 PATH도 없음 (fetch_ffmpeg.sh)")
    return found


def make_media(root, folder, names):
    """합성 영상(영상 + 소리, H.264)을 만듦 → {이름: sha256}. 같은 입력이면 같은 파일이 나오게 스레드·태그를 고정."""
    os.makedirs(folder)
    ffmpeg = ffmpeg_path(root)
    hashes = {}
    for name in sorted(names):
        path = os.path.join(folder, name)
        subprocess.run(
            [ffmpeg, "-y", "-v", "error",
             "-f", "lavfi", "-i", f"{MEDIA_SOURCES[name]}=duration={MEDIA_SECONDS}:size=320x240:rate=24",
             "-f", "lavfi", "-i", f"sine=duration={MEDIA_SECONDS}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "1", "-c:a", "aac", "-shortest",
             "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact", path],
            check=True,
        )
        with open(path, "rb") as fh:
            hashes[name] = sha256_hex(fh.read())
    return hashes


def git_info(root):
    """찍은 yesoncheck 소스가 어느 것인지: yesoncheck/ 폴더의 git 트리 해시와 커밋 안 된 변경 여부."""
    try:
        tree = subprocess.run(["git", "-C", root, "rev-parse", "HEAD:yesoncheck"], capture_output=True, text=True)
        status = subprocess.run(["git", "-C", root, "status", "--porcelain", "--", "yesoncheck"],
                                capture_output=True, text=True)
    except OSError as exc:
        return {"error": f"git을 실행하지 못함: {exc}"}
    if tree.returncode or status.returncode:
        return {"error": (tree.stderr + status.stderr).strip()}
    return {"yesoncheck_tree": tree.stdout.strip(), "yesoncheck_dirty": bool(status.stdout.strip())}


def child_environment(work, root):
    env = {k: v for k, v in os.environ.items() if k not in INHERITED_ENV_DROPPED and not k.startswith("YESONCHECK_")}
    home = os.path.join(work, "home")
    env.update({
        "QT_QPA_PLATFORM": "offscreen",
        "HOME": home,
        "USERPROFILE": home,
        "LOCALAPPDATA": os.path.join(home, "AppData", "Local"),
        "YESONCHECK_CONFIG_DIR": os.path.join(work, "share", ".yesoncheck"),
        "YESONCHECK_INSTANCES_DIR": os.path.join(work, "instances"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    vendored = os.path.join(root, "vendor", "ffmpeg", "windows" if sys.platform == "win32" else platform.machine())
    if os.path.isdir(vendored):
        env["PATH"] = vendored + os.pathsep + env.get("PATH", "")
    return env


def prepare_scene_folder(work, media_dir, names):
    """장면 하나의 임시 작업 폴더: 홈, 빈 work_paths.json이 든 설정 폴더, 창 기록 폴더, 합성 영상 사본."""
    config = os.path.join(work, "share", ".yesoncheck")
    for folder in (os.path.join(work, "home"), config, os.path.join(work, "instances"), os.path.join(work, "media")):
        os.makedirs(folder)
    with open(os.path.join(config, "work_paths.json"), "w", encoding="utf-8") as fh:
        fh.write("{}")
    for name in names:
        shutil.copy2(os.path.join(media_dir, name), os.path.join(work, "media", name))


def tail(text, lines=40):
    rows = text.rstrip().splitlines()
    return "\n".join(rows[-lines:])


def remove_outputs(out, name, include_log=False):
    """장면의 산출물(PNG·트리·meta)을 지움. 로그는 include_log일 때만 (실패 원인을 볼 수 있게 남김)."""
    suffixes = OUTPUT_SUFFIXES + ("meta.json.tmp",) + (("log",) if include_log else ())
    for suffix in suffixes:
        path = os.path.join(out, f"{name}.{suffix}")
        if os.path.exists(path):
            os.remove(path)


def file_sha256(path):
    with open(path, "rb") as fh:
        return sha256_hex(fh.read())


def capture_scene(name, out, root, work, media_dir, media_hashes, git):
    """장면 하나를 자식 프로세스로 찍음 → 성공이면 True. 실패는 이유(종료 코드·자식의 마지막 출력)를 크게 출력하고, 실패한
    (예외로 끝난 것 포함) 장면의 PNG·트리·meta는 남기지 않음 — 자식은 정리(창 닫기·뒤 스레드 기다림)보다 먼저 산출물을 쓰므로
    정리에서 실패하면 정상처럼 보이는 파일이 남기 때문. 완료 표시는 맨 마지막에 부모가 적음."""
    remove_outputs(out, name, include_log=True)  # 이전 결과가 섞이지 않게
    succeeded = False
    try:
        succeeded = run_scene_child(name, out, root, work, media_dir, media_hashes, git)
    finally:
        if not succeeded:
            remove_outputs(out, name)
    return succeeded


def run_scene_child(name, out, root, work, media_dir, media_hashes, git):
    scene = SCENES[name]
    prepare_scene_folder(work, media_dir, scene.media)
    command = [sys.executable, SCRIPT, "_scene", name, "--out", out, "--work", work, "--root", root]
    started = time.monotonic()
    try:
        proc = subprocess.run(command, env=child_environment(work, root), cwd=root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=SCENE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        partial = exc.stderr or exc.stdout or ""
        print(f"[실패] {name}: 자식 프로세스가 {SCENE_TIMEOUT_S}초 안에 끝나지 않음", file=sys.stderr)
        print(tail(partial.decode("utf-8", "replace") if isinstance(partial, bytes) else partial), file=sys.stderr)
        return False
    with open(os.path.join(out, f"{name}.log"), "w", encoding="utf-8") as fh:
        fh.write(proc.stdout + "\n--- stderr ---\n" + proc.stderr)
    elapsed = time.monotonic() - started
    produced = [os.path.join(out, f"{name}.{suffix}") for suffix in OUTPUT_SUFFIXES]
    if proc.returncode != 0 or not all(os.path.exists(p) for p in produced):
        print(f"[실패] {name}: 종료 코드 {proc.returncode} ({elapsed:.1f}초) — 전체 출력: {os.path.join(out, name + '.log')}",
              file=sys.stderr)
        print(tail(proc.stderr) or tail(proc.stdout), file=sys.stderr)
        return False
    meta_path = os.path.join(out, f"{name}.meta.json")
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    meta["png_sha256"] = file_sha256(os.path.join(out, f"{name}.png"))
    meta["tree_sha256"] = file_sha256(os.path.join(out, f"{name}.tree.json"))
    meta["media_sha256"] = {n: media_hashes[n] for n in scene.media}
    meta["git"] = git
    meta["elapsed_s"] = round(elapsed, 1)
    meta["complete"] = True  # 성공 경로의 맨 끝에서만 적는 완료 표시 — compare가 요구함
    tmp_path = meta_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp_path, meta_path)  # 반쯤 쓴 meta가 남지 않게
    settle_info = meta["settle"]
    print(f"{name}: 정착 {settle_info['fixed_wait_s']:g}초 + 연속 두 번 같음 (확인 {settle_info['rounds']}번째, "
          f"정착까지 {settle_info['settle_s']}초), 뒤 스레드 기다림 {settle_info['background_wait_s']}초, "
          f"{meta['size'][0]}x{meta['size'][1]}, PNG sha256 {meta['png_sha256'][:12]}, 전체 {elapsed:.1f}초")
    return True


def cmd_capture(args):
    scenes = list(dict.fromkeys(args.scene or SCENES))  # 같은 장면을 여러 번 줘도 한 번만
    out = os.path.abspath(args.out)
    root = os.path.abspath(args.root)
    os.makedirs(out, exist_ok=True)
    git = git_info(root)
    needed = sorted({name for scene in scenes for name in SCENES[scene].media})
    failed = []
    with tempfile.TemporaryDirectory(prefix="yc_shots_") as tmp:
        media_dir = os.path.join(tmp, "media")
        media_hashes = make_media(root, media_dir, needed) if needed else {}
        for name in scenes:
            if not capture_scene(name, out, root, os.path.join(tmp, name), media_dir, media_hashes, git):
                failed.append(name)
    if failed:
        print(f"찍기 실패: {len(failed)}/{len(scenes)} 장면 ({', '.join(failed)})", file=sys.stderr)
        return 1
    print(f"찍기 완료: {len(scenes)}개 장면 → {out}")
    return 0


# ---------------------------------------------------------------- compare (부모)


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_pixels(path):
    """PNG를 RGBA 배열(높이, 너비, 4)로. 읽지 못하면 RuntimeError."""
    import numpy as np
    from PyQt5.QtGui import QImage

    image = QImage(path)
    if image.isNull():
        raise RuntimeError(f"PNG를 읽지 못함: {path}")
    image = image.convertToFormat(QImage.Format_RGBA8888)
    pointer = image.constBits()
    pointer.setsize(image.byteCount())
    array = np.frombuffer(pointer, np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)
    return array[:, : image.width()].copy()  # 복사: 배열이 QImage의 메모리를 가리킨 채 함수를 나가면 안 됨


def diff_regions(changed):
    """다른 픽셀 마스크 → [(x0, x1, y0, y1, 픽셀 수)] 가까운 것끼리 묶고 큰 순서로."""
    import cv2
    import numpy as np

    mask = changed.astype(np.uint8)
    size = 2 * REGION_MERGE_PX + 1
    merged = cv2.dilate(mask, np.ones((size, size), np.uint8))
    count, labels = cv2.connectedComponents(merged)
    regions = []
    for label in range(1, count):
        ys, xs = np.nonzero(changed & (labels == label))
        if len(xs):
            regions.append((int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()), int(len(xs))))
    regions.sort(key=lambda r: -r[4])
    return regions


def box_text(x0, x1, y0, y1):
    return f"x={x0}..{x1} y={y0}..{y1}"


def compare_pixels(baseline_png, current_png):
    """PNG 바이트가 다를 때 어디가 어떻게 다른지 → 설명 줄 목록."""
    import numpy as np

    try:
        before, after = load_pixels(baseline_png), load_pixels(current_png)
    except RuntimeError as exc:
        return [f"픽셀: {exc}"]
    if before.shape != after.shape:
        return [f"픽셀: 크기가 다름 (기준 {before.shape[1]}x{before.shape[0]}, 현재 {after.shape[1]}x{after.shape[0]})"]
    changed = np.any(before != after, axis=2)
    total = int(changed.sum())
    if total == 0:
        return ["픽셀: 모든 픽셀이 같음 (PNG 인코딩만 다름)"]
    regions = diff_regions(changed)
    ys, xs = np.nonzero(changed)
    percent = 100.0 * total / changed.size
    lines = [f"픽셀: {total:,}개 다름 (전체 {changed.size:,}개의 {percent:.2f}%), "
             f"전체 {box_text(int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()))}, 영역 {len(regions)}곳"]
    for x0, x1, y0, y1, pixels in regions[:MAX_REGIONS_SHOWN]:
        lines.append(f"  {box_text(x0, x1, y0, y1)} ({x1 - x0 + 1}x{y1 - y0 + 1}, {pixels:,}개)")
    if len(regions) > MAX_REGIONS_SHOWN:
        lines.append(f"  … 외 {len(regions) - MAX_REGIONS_SHOWN}곳")
    return lines


def flatten_tree(root):
    """트리 → {경로: 위젯 정보(children 제외)}. 경로 = 클래스(#objectName)[같은 이름 형제 중 차례]를 /로 이음."""
    flat = {}

    def visit(node, path):
        flat[path] = {field: node[field] for field in TREE_FIELDS}
        seen = {}
        for child in node["children"]:
            key = child["class"] + (f"#{child['name']}" if child["name"] else "")
            index = seen.get(key, 0)
            seen[key] = index + 1
            visit(child, f"{path}/{key}[{index}]")

    visit(root, root["class"] + (f"#{root['name']}" if root["name"] else ""))
    return flat


def short(value, limit=120):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def compare_trees(baseline, current):
    """위젯 트리 차이 → 설명 줄 목록 (-: 기준에만, +: 현재에만, ~: 값이 바뀜)."""
    before, after = flatten_tree(baseline), flatten_tree(current)
    lines = []
    for path in before:
        if path not in after:
            lines.append(f"- {path} (현재에 없음)")
    for path in after:
        if path not in before:
            lines.append(f"+ {path} (기준에 없음)")
    for path in before:
        if path in after:
            for field in TREE_FIELDS:
                if before[path][field] != after[path][field]:
                    lines.append(f"~ {path} {field}: {short(before[path][field])} → {short(after[path][field])}")
    return lines


def compare_dialogs(baseline, current):
    lines = []
    if baseline == current:
        return lines
    lines.append(f"대화 상자 기록이 다름 (기준 {len(baseline)}개, 현재 {len(current)}개)")
    for index in range(max(len(baseline), len(current))):
        before = baseline[index] if index < len(baseline) else None
        after = current[index] if index < len(current) else None
        if before != after:
            lines.append(f"  [{index}] {short(before)} → {short(after)}")
    return lines


def environment_notes(baseline_dir, current_dir, scene):
    """두 폴더가 같은 환경에서 찍힌 것인지 (meta.json이 있을 때만) → [주의] 줄 목록. 결과(종료 코드)에는 영향 없음."""
    notes = []
    paths = [os.path.join(d, f"{scene}.meta.json") for d in (baseline_dir, current_dir)]
    if not all(os.path.exists(p) for p in paths):
        return notes
    before, after = (load_json(p) for p in paths)
    changed = [key for key in ENVIRONMENT_KEYS if before["environment"].get(key) != after["environment"].get(key)]
    if changed:
        details = ", ".join(f"{k} {short(before['environment'].get(k))} → {short(after['environment'].get(k))}"
                            for k in changed)
        notes.append(f"[주의] {scene}: 찍은 환경이 다름 — 픽셀 차이가 코드 때문이 아닐 수 있음 ({details})")
    if before.get("media_sha256") != after.get("media_sha256"):
        notes.append(f"[주의] {scene}: 합성 영상 파일이 다름 — 영상이 있는 장면의 차이가 영상 때문일 수 있음")
    return notes


def completion_problems(folder, label, scene):
    """폴더의 장면이 찍기가 끝까지 성공한 것인지 → 문제 줄 목록 (없으면 빈 목록). 끝까지 성공한 장면에만 부모가 meta.json에
    완료 표시와 PNG·트리의 sha256을 적으므로, 표시가 없거나 파일이 그 해시와 다르면 중간에 실패했거나 찍은 뒤 바뀐 것."""
    meta_path = os.path.join(folder, f"{scene}.meta.json")
    if not os.path.exists(meta_path):
        return [f"{scene}.meta.json이(가) {label} 폴더에 없음 — 찍기가 끝까지 성공하지 않았거나 옛 형식"]
    meta = load_json(meta_path)
    if meta.get("complete") is not True:
        return [f"{label} 폴더의 {scene}.meta.json에 완료 표시가 없음 — 찍기가 끝까지 성공하지 않았거나 옛 형식"]
    problems = []
    for key, filename in (("png_sha256", f"{scene}.png"), ("tree_sha256", f"{scene}.tree.json")):
        path = os.path.join(folder, filename)
        if os.path.exists(path) and file_sha256(path) != meta.get(key):
            problems.append(f"{label} 폴더의 {filename}이(가) meta에 적힌 {key}와 다름 — 찍은 뒤 바뀐 파일")
    return problems


def compare_scene(scene, baseline_dir, current_dir, max_diff):
    """장면 하나 비교 → (같은가, 설명 줄 목록)."""
    png_name, tree_name = f"{scene}.png", f"{scene}.tree.json"
    sides = (("기준", baseline_dir), ("현재", current_dir))
    missing = [f"{filename}이(가) {label} 폴더에 없음"
               for label, folder in sides for filename in (png_name, tree_name)
               if not os.path.exists(os.path.join(folder, filename))]
    problems = [line for label, folder in sides for line in completion_problems(folder, label, scene)]
    if missing:
        return False, missing + problems

    same = not problems
    lines = list(problems)
    baseline_png, current_png = os.path.join(baseline_dir, png_name), os.path.join(current_dir, png_name)
    with open(baseline_png, "rb") as fh:
        before_bytes = fh.read()
    with open(current_png, "rb") as fh:
        after_bytes = fh.read()
    if before_bytes == after_bytes:
        lines.append("PNG 동일 (바이트까지)")
    else:
        same = False
        lines.append(f"PNG 바이트가 다름 (기준 {len(before_bytes):,}B sha256 {sha256_hex(before_bytes)[:12]}, "
                     f"현재 {len(after_bytes):,}B sha256 {sha256_hex(after_bytes)[:12]})")
        lines.extend(compare_pixels(baseline_png, current_png))

    before_doc, after_doc = (load_json(os.path.join(d, tree_name)) for d in (baseline_dir, current_dir))
    dialog_lines = compare_dialogs(before_doc["dialogs"], after_doc["dialogs"])
    tree_lines = compare_trees(before_doc["tree"], after_doc["tree"])
    if dialog_lines or tree_lines:
        same = False
    lines.extend(dialog_lines)
    if tree_lines:
        lines.append(f"트리: {len(tree_lines)}곳 다름")
        lines.extend(f"  {line}" for line in tree_lines[:max_diff])
        if len(tree_lines) > max_diff:
            lines.append(f"  … 외 {len(tree_lines) - max_diff}곳 (--max-diff로 더 봄)")
    else:
        lines.append("트리 동일")
    return same, lines


def scenes_in(folder):
    return {name[: -len(".png")] for name in os.listdir(folder) if name.endswith(".png")}


def cmd_compare(args):
    # 기본: 고정된 장면 전부(두 폴더 모두에 있어야 함 — 양쪽에서 같이 빠져도 차이) + 디스크에 있는 그 밖의 PNG
    scenes = list(dict.fromkeys(args.scene)) if args.scene else sorted(set(SCENES) | scenes_in(args.baseline) | scenes_in(args.current))
    notes = sorted({note for scene in scenes for note in environment_notes(args.baseline, args.current, scene)})
    for note in notes:
        print(note)
    different = []
    for scene in scenes:
        same, lines = compare_scene(scene, args.baseline, args.current, args.max_diff)
        print(f"== {scene}: {'같음' if same else '다름'}")
        for line in lines:
            print(f"   {line}")
        if not same:
            different.append(scene)
    if different:
        print(f"차이 있음: {len(different)}/{len(scenes)} 장면 ({', '.join(different)})")
        return 1
    print(f"차이 없음: {len(scenes)}개 장면 (PNG 바이트·트리 동일)")
    return 0


# ---------------------------------------------------------------- 진입점


def positive_int(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("1 이상이어야 함")
    return value


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    scene_help = "찍거나 비교할 장면 (여러 번 줄 수 있음, 기본: 전부): " + ", ".join(SCENES)
    cap = sub.add_parser("capture", help="장면마다 자식 프로세스로 화면을 찍어 PNG·트리 JSON을 저장")
    cap.add_argument("--out", required=True, help="저장할 폴더")
    cap.add_argument("--scene", action="append", choices=list(SCENES), help=scene_help)
    cap.add_argument("--root", default=ROOT, help="찍을 yesoncheck가 든 저장소 (기본: 이 검사가 든 저장소)")
    cap.set_defaults(func=cmd_capture)

    cmp_ = sub.add_parser("compare", help="두 폴더의 장면을 PNG 바이트·트리 JSON으로 비교 (다르면 종료 1)")
    cmp_.add_argument("--baseline", required=True, help="기준(리팩토링 전)을 찍은 폴더")
    cmp_.add_argument("--current", required=True, help="지금을 찍은 폴더")
    cmp_.add_argument("--scene", action="append", choices=list(SCENES), help=scene_help)
    cmp_.add_argument("--max-diff", type=positive_int, default=DEFAULT_MAX_DIFF, help="장면마다 보여 줄 트리 차이 줄 수")
    cmp_.set_defaults(func=cmd_compare)

    child = sub.add_parser("_scene", help=argparse.SUPPRESS)  # capture가 장면마다 띄우는 자식 (직접 부르지 않음)
    child.add_argument("scene", choices=list(SCENES))
    child.add_argument("--out", required=True)
    child.add_argument("--work", required=True)
    child.add_argument("--root", required=True)
    child.set_defaults(func=child_main)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "compare":
        for label, folder in (("--baseline", args.baseline), ("--current", args.current)):
            if not os.path.isdir(folder):
                parser.error(f"{label} 폴더가 없음: {folder}")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
