#!/usr/bin/env python3
"""사용법 매뉴얼(Help → 사용법)의 스크린샷 만들기 — 개발 도구 (앱에 들어가지 않음).

사용: ~/coding/p310_tf/bin/python tools/make_manual_screenshots.py [--out yesoncheck/manual_images] [--shot 이름 ...]

- 진짜 VideoPlayer를 화면 없이(offscreen, 2배 배율) 띄워 정해진 상태를 만들고 widget.grab()으로 찍음. 샷마다 자식 프로세스
  하나(앞 샷의 상태가 뒤 샷에 섞이지 않게). 화면이 바뀌면(단추·메뉴·모양) 이 도구를 다시 돌려 그림을 새로 만듦.
- **그림에 실제 작품이 들어가지 않게**: HOME·공유 설정·창 기록을 샷마다 임시 폴더로 격리(ci/screenshot_check.py와 같은 환경 —
  북마크·작품 경로·NAS를 읽지 않음)하고, 영상은 tools/manual_media.py가 직접 그린 합성 그림만 씀(저장소가 공개).
- 번호 표지는 위젯 자리에서 계산해 그림 위에 그림 — 번호의 뜻은 yesoncheck/manual_content.py의 그림 설명과 짝(번호를 바꾸면
  그쪽도 함께).
- 메뉴·호버 창·대화 상자처럼 창 밖에 뜨는 것은 따로 찍어 창 그림 위에 얹음(화면 없이는 한 장에 함께 찍히지 않음).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections import namedtuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.abspath(__file__)
sys.path.insert(0, os.path.join(ROOT, "ci"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import manual_media  # noqa: E402
import screenshot_check as sc  # noqa: E402 — 격리 환경·정착·뒤 스레드 기다림을 그대로 씀

SCALE = 2  # 2배로 찍음 (레티나에서 또렷하게) — 그림의 논리 크기는 창 크기 그대로
WINDOW = (1360, 880)
BADGE_COLOR = "#ff2d6f"
BADGE_RADIUS = 12
GUTTER_COLOR = "#232323"  # 어두운 테마의 창 배경 (main_window_styles)
GUTTER = 40
MEDIA_LINK = "/tmp/MyShow"  # 창에 보이는 경로(미디어 정보·주석 저장 자리)가 임시 폴더 이름 없이 /tmp/MyShow/… 가 되게 거는 링크
SHOT_TIMEOUT_S = 300

Callout = namedtuple("Callout", "number rect anchor outline", defaults=("l", False))


# ---------------------------------------------------------------- 그림 도구 (자식)


def widget_rect(window, widget):
    from PyQt5.QtCore import QPoint, QRect

    return QRect(widget.mapTo(window, QPoint(0, 0)), widget.size())


def union(window, *widgets):
    rect = widget_rect(window, widgets[0])
    for widget in widgets[1:]:
        rect = rect.united(widget_rect(window, widget))
    return rect


def ancestor(widget, cls):
    parent = widget.parentWidget()
    while parent is not None and not isinstance(parent, cls):
        parent = parent.parentWidget()
    sc.require(parent is not None, f"{cls.__name__} 조상을 찾지 못함: {widget}")
    return parent


def button(window, text):
    from PyQt5.QtWidgets import QAbstractButton

    found = [b for b in window.findChildren(QAbstractButton) if b.text() == text and b.isVisibleTo(window)]
    sc.require(len(found) == 1, f"단추 {text!r}가 하나가 아님: {len(found)}")
    return found[0]


def box(window, title):
    found = [b for b in sc.collapsible_boxes(window) if title in b.toggle_button.text()]
    sc.require(len(found) == 1, f"접는 상자 {title!r}가 하나가 아님: {len(found)}")
    return found[0]


def logical_size(image):
    ratio = image.devicePixelRatio()
    return image.width() / ratio, image.height() / ratio


def anchor_point(rect, anchor):
    points = {
        "tl": (rect.left(), rect.top()), "tr": (rect.right(), rect.top()), "t": (rect.center().x(), rect.top()),
        "l": (rect.left(), rect.center().y()), "r": (rect.right(), rect.center().y()),
        "c": (rect.center().x(), rect.center().y()), "bl": (rect.left(), rect.bottom()),
        "b": (rect.center().x(), rect.bottom()), "br": (rect.right(), rect.bottom()),
        "lo": (rect.left() - BADGE_RADIUS - 3, rect.center().y()),  # 왼쪽 바깥
        "ro": (rect.right() + BADGE_RADIUS + 4, rect.center().y()),  # 오른쪽 바깥
    }
    return points[anchor]


def draw_callouts(image, callouts, gutter=0):
    """번호 표지를 그림. anchor "g"는 왼쪽 여백(gutter) 가운데에 두고 위젯 왼쪽 끝까지 가는 선을 그음."""
    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import QColor, QFont, QPainter, QPen

    width, height = logical_size(image)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    font = QFont("Helvetica Neue")
    font.setPixelSize(15)
    font.setBold(True)
    painter.setFont(font)
    for callout in callouts:
        rect = QRectF(callout.rect)
        if callout.outline:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(BADGE_COLOR), 2))
            painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 6, 6)
    for callout in callouts:  # 표지는 테두리 위에
        if callout.anchor == "g":
            sc.require(gutter > 0, "anchor 'g'는 여백(gutter)이 있어야 함")
            x, y = gutter / 2, QRectF(callout.rect).center().y()
            painter.setPen(QPen(QColor(BADGE_COLOR), 1.5))
            painter.drawLine(QPointF(x, y), QPointF(callout.rect.left() + 3, y))
        else:
            x, y = anchor_point(QRectF(callout.rect), callout.anchor)
        x = min(max(x, BADGE_RADIUS + 2), width - BADGE_RADIUS - 2)
        y = min(max(y, BADGE_RADIUS + 2), height - BADGE_RADIUS - 2)
        painter.setPen(QPen(QColor("white"), 2))
        painter.setBrush(QColor(BADGE_COLOR))
        painter.drawEllipse(QPointF(x, y), BADGE_RADIUS, BADGE_RADIUS)
        painter.setPen(QColor("white"))
        painter.drawText(QRectF(x - BADGE_RADIUS, y - BADGE_RADIUS, 2 * BADGE_RADIUS, 2 * BADGE_RADIUS),
                         Qt.AlignCenter, str(callout.number))
    painter.end()


def paste(image, overlay, x, y, shadow=True):
    """overlay(따로 찍은 메뉴·호버 창)를 image의 논리 좌표 (x, y)에 얹음."""
    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import QColor, QPainter

    width, height = logical_size(overlay)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    if shadow:
        painter.setPen(Qt.NoPen)
        for spread, alpha in ((10, 18), (6, 30), (3, 46)):
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(QRectF(x - spread, y - spread + 4, width + 2 * spread, height + 2 * spread), 8, 8)
    painter.drawImage(QPointF(x, y), overlay)
    painter.end()


def draw_cursor(image, x, y):
    """마우스 화살표 (화면 없이 찍으면 커서가 없어서 그려 넣음)."""
    from PyQt5.QtCore import QPointF
    from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF

    shape = [(0, 0), (0, 17), (4.5, 13), (7.5, 20), (10, 19), (7, 12), (12.5, 12)]
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("white"), 1.4))
    painter.setBrush(QColor("black"))
    painter.drawPolygon(QPolygonF([QPointF(x + dx, y + dy) for dx, dy in shape]))
    painter.end()


def crop(image, rect, pad=12):
    from PyQt5.QtCore import QRect

    ratio = image.devicePixelRatio()
    width, height = logical_size(image)
    left, top = max(0, rect.left() - pad), max(0, rect.top() - pad)
    right, bottom = min(width, rect.right() + 1 + pad), min(height, rect.bottom() + 1 + pad)
    cut = image.copy(QRect(int(left * ratio), int(top * ratio), int((right - left) * ratio), int((bottom - top) * ratio)))
    cut.setDevicePixelRatio(ratio)
    return cut, (left, top)


def add_gutter(image, gutter):
    """왼쪽에 번호 표지를 둘 빈 여백(창 배경색)을 붙임."""
    from PyQt5.QtCore import QPointF
    from PyQt5.QtGui import QColor, QImage, QPainter

    ratio = image.devicePixelRatio()
    wide = QImage(image.width() + int(gutter * ratio), image.height(), QImage.Format_ARGB32_Premultiplied)
    wide.setDevicePixelRatio(ratio)
    wide.fill(QColor(GUTTER_COLOR))
    painter = QPainter(wide)
    painter.drawImage(QPointF(gutter, 0), image)
    painter.end()
    return wide


def left_inset(rect, dx):
    """넓은 단추의 글자를 가리지 않게: 왼쪽 끝에서 dx만큼 들어온 자리의 작은 사각형 (anchor "c"와 함께)."""
    from PyQt5.QtCore import QRect

    return QRect(rect.left() + dx - 1, rect.center().y() - 1, 2, 2)


class Stage:
    """샷 함수에 건네는 도구: 합성 영상 경로, 창 만들기, 정착한 그림 찍기, 저장."""

    def __init__(self, app, work, out):
        self.app = app
        self.work = work
        self.out = out
        self.cleanups = []
        self.saved = []

    def media(self, *parts):
        return os.path.join(MEDIA_LINK, *parts)

    def pump(self, seconds=0.3):
        sc.pump(self.app, seconds)

    def player(self, size=WINDOW):
        from yesoncheck.main_window import VideoPlayer

        player = VideoPlayer()
        player.resize(*size)
        player.show()
        self.cleanups.append(player.close)
        self.pump()
        return player

    def open_job(self, player, row=0, frame=18):
        """EP101 폴더를 불러와(영상 7개 + 시퀀스 3개) row번째 영상을 A에 열고 frame번째 장으로."""
        player.load_videos_from_folder(self.media("EP101"))
        player.sidebar.clearSelection()
        item = player.sidebar.item(row)
        player.sidebar.setCurrentItem(item)
        sc.require(player.open_file("A", item.toolTip()), f"영상을 열지 못함: {item.text()}")
        player.seek_to_frame(frame)
        self.pump()

    def grab(self, widget):
        sc.wait_for_background(self.app, "샷을 만든 뒤")
        image, _info = sc.settle(self.app, widget)
        return image

    def save(self, name, image, callouts=(), crop_to=None, pad=12, gutter=0):
        left = top = 0
        if crop_to is not None:
            image, (left, top) = crop(image, crop_to, pad)
        if gutter:
            image = add_gutter(image, gutter)
            left -= gutter
        draw_callouts(image, [c._replace(rect=c.rect.translated(-int(left), -int(top))) for c in callouts], gutter)
        path = os.path.join(self.out, f"{name}.png")
        sc.require(image.save(path, "PNG"), f"PNG를 저장하지 못함: {path}")
        self.saved.append({"name": name, "size": [image.width(), image.height()]})

    def capture_menu(self, trigger):
        """trigger()가 띄우는 QMenu를 진짜로 띄우지 않고 찍음 → (그림, 화면 좌표의 자리)."""
        from PyQt5.QtGui import QCursor
        from PyQt5.QtWidgets import QMenu

        captured = {}
        original = QMenu.exec_

        def fake_exec(menu, *args):
            menu.popup(args[0] if args else QCursor.pos())
            self.pump(0.4)
            captured["image"] = menu.grab().toImage()
            captured["pos"] = menu.pos()
            menu.close()
            return None

        QMenu.exec_ = fake_exec
        try:
            trigger()
        finally:
            QMenu.exec_ = original
        sc.require("image" in captured, "메뉴가 뜨지 않음")
        return captured["image"], captured["pos"]

    def capture_dialog(self, cls, trigger, size=None):
        """trigger()가 exec_()로 띄우는 대화 상자(cls)를 띄우지 않고 찍음 → 그림."""
        captured = {}
        original = cls.exec_

        def fake_exec(dialog, *args):
            if size is not None:
                dialog.resize(*size)
            dialog.show()
            self.pump(0.6)
            captured["image"] = dialog.grab().toImage()
            dialog.close()
            return 0

        cls.exec_ = fake_exec
        try:
            trigger()
        finally:
            cls.exec_ = original
        sc.require("image" in captured, f"{cls.__name__}이 뜨지 않음")
        return captured["image"]


# ---------------------------------------------------------------- 샷


def sidebar_column(player):
    """사이드바 열 전체 (맨 위 단추부터 개수 줄까지)."""
    return union(player, button(player, "Select Folder"), player.sidebar_tabs, player.sidebar_count_label)


def middle_panel(player):
    from PyQt5.QtWidgets import QScrollArea

    return ancestor(button(player, "Open Video A"), QScrollArea)


def info_row(player):
    return union(player, player.filenameLabel, player.timeLabel)


def menu_titles_rect(player):
    """메뉴 줄에서 글자가 있는 부분만 (Settings·Help)."""
    bar = player.menuBar()
    rect = bar.actionGeometry(bar.actions()[0])
    for action in bar.actions()[1:]:
        rect = rect.united(bar.actionGeometry(action))
    from PyQt5.QtCore import QRect

    return QRect(bar.mapTo(player, rect.topLeft()), rect.size())


def video_point(player, norm_x, norm_y):
    """영상 그림 위의 정규화 좌표 → 창 좌표."""
    from PyQt5.QtCore import QPointF

    view = player.videoWidget
    scene_rect = view.video_item.sceneBoundingRect()
    point = view.mapFromScene(QPointF(scene_rect.left() + norm_x * scene_rect.width(),
                                      scene_rect.top() + norm_y * scene_rect.height()))
    return view.viewport().mapTo(player, point)


def point_rect(point, half=1):
    from PyQt5.QtCore import QRect

    return QRect(point.x() - half, point.y() - half, 2 * half, 2 * half)


def shot_overview(st):
    player = st.player()
    st.open_job(player)
    image = st.grab(player)
    st.save("overview", image, [
        Callout(1, menu_titles_rect(player), "r", False),
        Callout(2, sidebar_column(player), "tl", True),
        Callout(3, widget_rect(player, middle_panel(player)), "tl", True),
        Callout(4, widget_rect(player, player.videoWidget), "tl", True),
        Callout(5, info_row(player), "tl", True),
        Callout(6, widget_rect(player, player.positionScroll), "tl", True),
        Callout(7, union(player, player.playPauseButton, button(player, "Stop")), "tl", True),
    ])


def shot_sidebar(st):
    player = st.player()
    st.open_job(player)
    image = st.grab(player)
    from PyQt5.QtCore import QRect

    rows = widget_rect(player, player.sidebar)
    st.save("sidebar", image, [
        Callout(1, widget_rect(player, button(player, "Select Folder")), "g"),
        Callout(2, widget_rect(player, button(player, "Add Bookmark")), "g"),
        Callout(3, widget_rect(player, button(player, "Bookmarks")), "g"),
        Callout(4, widget_rect(player, button(player, "작품 경로 관리")), "g"),
        Callout(5, union(player, player.listModeButton, player.refreshListButton), "g"),
        Callout(6, widget_rect(player, player.sidebar_tabs.tabBar()), "g"),
        Callout(7, QRect(rows.left(), rows.top(), rows.width(), 110), "g"),
        Callout(8, widget_rect(player, player.sidebar_count_label), "g"),
    ], crop_to=sidebar_column(player), pad=6, gutter=GUTTER)


def shot_thumbnails(st):
    player = st.player()
    st.open_job(player)
    player.switch_to_thumbnail_mode()
    image = st.grab(player)
    st.save("thumbnails", image, crop_to=sidebar_column(player), pad=6)


def shot_mov_menu(st):
    player = st.player()
    st.open_job(player)
    for row in (0, 1, 2):
        player.sidebar.item(row).setSelected(True)
    image = st.grab(player)
    item_rect = player.sidebar.visualItemRect(player.sidebar.item(1))
    click = item_rect.center()
    click.setX(item_rect.left() + 150)
    from PyQt5.QtGui import QCursor

    QCursor.setPos(player.sidebar.viewport().mapToGlobal(click))
    menu, _pos = st.capture_menu(lambda: player.show_sidebar_context_menu(click))
    at = player.sidebar.viewport().mapTo(player, click)
    paste(image, menu, at.x(), at.y())
    draw_cursor(image, at.x() - 2, at.y() - 2)
    from PyQt5.QtCore import QRect

    width, height = logical_size(menu)
    st.save("mov_menu", image, crop_to=sidebar_column(player).united(QRect(at.x(), at.y(), int(width) + 14, int(height))), pad=6)


def shot_controls(st):
    player = st.player()
    st.open_job(player)
    image = st.grab(player)
    st.save("controls", image, [
        Callout(1, union(player, button(player, "Open Video A"), button(player, "Open Video B")), "g"),
        Callout(2, union(player, box(player, "ROI 설정"), box(player, "결과 관리")), "g"),
        Callout(3, widget_rect(player, box(player, "수정 사항 주석")), "g"),
        Callout(4, widget_rect(player, player.loopCheckBox), "g"),
        Callout(5, widget_rect(player, player.volumeSlider), "g"),
        Callout(6, widget_rect(player, player.frameRateComboBox), "g"),
        Callout(7, union(player, player.wipeCheckBox, player.wipeYButton), "g"),
        Callout(8, union(player, player.playSelectedButton, player.playSelectedPauseButton), "g"),
        Callout(9, union(player, player.workComboBox, player.jobComboBox), "g"),
    ], crop_to=widget_rect(player, middle_panel(player)), pad=0, gutter=GUTTER)


def shot_playbar(st):
    player = st.player()
    st.open_job(player)
    image = st.grab(player)
    stop = button(player, "Stop")
    st.save("playbar", image, [
        Callout(1, widget_rect(player, player.filenameLabel), "t"),
        Callout(2, widget_rect(player, player.labelFrameCount), "t"),
        Callout(3, widget_rect(player, player.labelTotalFrames), "t"),
        Callout(4, widget_rect(player, player.labelPlaybackFPS), "t"),
        Callout(5, widget_rect(player, player.timeLabel), "t"),
        Callout(6, left_inset(widget_rect(player, player.positionScroll), int(WINDOW[0] * 0.8)), "c"),
        Callout(7, left_inset(widget_rect(player, player.playPauseButton), 560), "c"),
        Callout(8, left_inset(widget_rect(player, stop), 560), "c"),
    ], crop_to=info_row(player).united(widget_rect(player, stop)), pad=16)


def shot_hover(st):
    from PyQt5.QtCore import QEvent, QPointF, QRect, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication

    player = st.player()
    st.open_job(player, row=0, frame=6)
    deadline = time.monotonic() + 40
    while True:  # 띠는 쉬는 동안 뒤에서 만들어짐 — 다 찰 때까지
        st.pump(0.2)
        strip, plan = player._hover_strip, player._hover_plan
        if strip is not None and plan is not None and strip.filled_count == plan.count:
            break
        sc.require(time.monotonic() < deadline, "호버 띠가 40초 안에 다 차지 않음")
    image = st.grab(player)
    slider = player.positionScroll
    x = int(slider.width() * 0.62)
    QApplication.sendEvent(slider, QMouseEvent(QEvent.MouseMove, QPointF(x, slider.height() / 2), Qt.NoButton,
                                               Qt.NoButton, Qt.NoModifier))
    st.pump(0.3)
    popup = player._hover_popup
    sc.require(popup.isVisible(), "호버 창이 뜨지 않음")
    shot = popup.grab().toImage()
    popup.hide()
    width, height = logical_size(shot)
    # 화면 없이는 화면 크기(800×600) 안으로 밀려 뜨므로, 진짜 화면에서의 자리(커서 위 가운데, 슬라이더 위 8px)에 얹음
    cursor = slider.mapTo(player, QPointF(x, slider.height() / 2).toPoint())
    left = int(cursor.x() - width / 2)
    top = int(widget_rect(player, slider).top() - 8 - height)
    paste(image, shot, left, top)
    draw_cursor(image, cursor.x(), cursor.y() - 2)
    area = QRect(left - 330, top - 14, int(width) + 660, int(height) + 14 + 8 + slider.height() + 26)
    st.save("hover", image, [
        Callout(1, QRect(left, top, int(width), int(height)), "tr"),
        Callout(2, point_rect(cursor, 6), "lo"),
    ], crop_to=area, pad=10)


def shot_wipe(st):
    player = st.player()
    st.open_job(player, row=0, frame=30)
    sc.require(player.open_file("B", st.media("EP101", "EP101_SC001_TK2.mov")), "B를 열지 못함")
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)
    player.seek_to_frame(30)
    sc.require(player.videoWidget.wipe_enabled_x, "와이프가 켜지지 않음")
    image = st.grab(player)
    line = player.videoWidget.wipe_line_x.line()
    view = player.videoWidget
    top = view.viewport().mapTo(player, view.mapFromScene(line.p1()))
    bottom = view.viewport().mapTo(player, view.mapFromScene(line.p2()))
    from PyQt5.QtCore import QPoint

    middle = QPoint(top.x(), (top.y() + bottom.y()) // 2)
    st.save("wipe", image, [
        Callout(1, widget_rect(player, player.wipeCheckBox), "lo"),
        Callout(2, union(player, player.wipeXButton, player.wipeYButton), "lo"),
        Callout(3, point_rect(middle), "c"),
        Callout(4, widget_rect(player, player.filenameLabel), "t"),
    ])


def shot_seq_tab(st):
    player = st.player()
    st.open_job(player)
    player.sidebar_tabs.setCurrentIndex(1)
    item = player.seq_sidebar.item(1)
    player.seq_sidebar.setCurrentItem(item)
    player.on_seq_item_clicked(item)
    st.pump()
    player.seek_to_frame(7)
    image = st.grab(player)
    st.save("seq_tab", image, [
        Callout(1, widget_rect(player, player.sidebar_tabs.tabBar()), "ro"),
        Callout(2, widget_rect(player, player.seq_sidebar), "r"),
        Callout(3, widget_rect(player, player.sidebar_count_label), "r"),
        Callout(4, widget_rect(player, player.filenameLabel), "t"),
    ])


def shot_all_tab(st):
    player = st.player()
    st.open_job(player)
    player.sidebar_tabs.setCurrentIndex(2)
    st.pump(0.5)
    image = st.grab(player)
    st.save("all_tab", image, crop_to=sidebar_column(player), pad=6)


def shot_seq_menu(st):
    from PyQt5.QtCore import QRect
    from PyQt5.QtGui import QCursor

    player = st.player()
    st.open_job(player)
    player.sidebar_tabs.setCurrentIndex(1)
    for row in (0, 1):
        player.seq_sidebar.item(row).setSelected(True)
    image = st.grab(player)
    item_rect = player.seq_sidebar.visualItemRect(player.seq_sidebar.item(1))
    click = item_rect.center()
    click.setX(item_rect.left() + 150)
    QCursor.setPos(player.seq_sidebar.viewport().mapToGlobal(click))
    menu, _pos = st.capture_menu(lambda: player.show_seq_context_menu(click))
    at = player.seq_sidebar.viewport().mapTo(player, click)
    paste(image, menu, at.x(), at.y())
    draw_cursor(image, at.x() - 2, at.y() - 2)
    width, height = logical_size(menu)
    st.save("seq_menu", image, crop_to=sidebar_column(player).united(QRect(at.x(), at.y(), int(width) + 14, int(height))), pad=6)


ANNOTATION_FRAME = 10  # 주석을 더하면 그 주석의 시작 프레임으로 가므로 처음부터 이 장에 맞춤


def annotation_player(st):
    """주석 칸을 펼치고 주석 셋(타원·글자·화살표)을 그린 창. 가운데 열은 스플리터로 넓힘(기본 폭에서는 칸 오른쪽이 잘림)."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QSplitter

    player = st.player((WINDOW[0], 1260))  # 주석 칸(최대 300px)이 다 펼쳐지는 높이
    main = [sp for sp in player.findChildren(QSplitter) if sp.orientation() == Qt.Horizontal and sp.count() == 3]
    sc.require(len(main) == 1, f"가로 스플리터가 하나가 아님: {len(main)}")
    main[0].setSizes([200, 300, WINDOW[0] - 500])
    st.open_job(player, row=0, frame=ANNOTATION_FRAME)
    sc.expand(box(player, "수정 사항 주석"))
    player.annotationModeButton.setChecked(True)
    sc.require(player.annotationModeButton.isChecked(), "주석 모드가 켜지지 않음")
    player.annotationRangeStartSpin.setValue(ANNOTATION_FRAME)
    player.annotationRangeEndSpin.setValue(30)
    sun_x = 260 + 520 * (ANNOTATION_FRAME - 1) / manual_media.SHOT_FRAMES  # manual_media.scene_hills의 해
    player.on_annotation_shape_finished({
        "type": "ellipse", "norm_x1": (sun_x - 86) / manual_media.WIDTH, "norm_y1": (170 - 86) / manual_media.HEIGHT,
        "norm_x2": (sun_x + 86) / manual_media.WIDTH, "norm_y2": (170 + 86) / manual_media.HEIGHT, "color": "#ff3333"})
    start, end = player._get_annotation_range_0based()
    player.annotation_store.add(player.get_current_frame_index(), {
        "type": "text", "norm_x1": 0.47, "norm_y1": 0.27, "norm_x2": 0.47, "norm_y2": 0.27,
        "text": "지붕 색 확인", "color": "#ffcc00", "font_size": player.annotationFontSizeSpin.value(),
    }, start_frame=start, end_frame=end)
    player.on_annotation_shape_finished(
        {"type": "arrow", "norm_x1": 0.585, "norm_y1": 0.37, "norm_x2": 0.685, "norm_y2": 0.475, "color": "#ffcc00"})
    player.auto_save_annotations()
    player.refresh_annotation_ui(redraw=True)
    st.pump()
    sc.require(player.get_current_frame_index() + 1 == ANNOTATION_FRAME, f"프레임이 다름: {player.get_current_frame_index() + 1}")
    return player, sun_x


def annotation_scroll(player):
    from PyQt5.QtWidgets import QScrollArea

    return ancestor(player.annotationToolCombo, QScrollArea)


def shot_annotation(st):
    from PyQt5.QtCore import QRect
    from PyQt5.QtWidgets import QLabel

    player, sun_x = annotation_player(st)
    image = st.grab(player)
    inner = widget_rect(player, annotation_scroll(player).viewport())

    def seen(number, *widgets):
        rect = union(player, *widgets).intersected(inner)
        sc.require(rect.height() > 12, f"표지 {number}의 위젯이 칸 안에 보이지 않음")
        return Callout(number, rect, "lo")

    badges = [w for w in player.videoWidget.findChildren(QLabel) if w.text() == "주석 모드" and w.isVisible()]
    sc.require(len(badges) == 1, f"'주석 모드' 배지가 하나가 아님: {len(badges)}")
    mark = video_point(player, (sun_x + 86) / manual_media.WIDTH, 100 / manual_media.HEIGHT)
    st.save("annotation", image, [
        seen(1, player.annotationModeButton),
        seen(2, player.annotationToolCombo, player.annotationColorCombo),
        seen(3, player.annotationFontSizeSpin, player.annotationRangeEndSpin),
        seen(4, player.annotationListWidget),
        Callout(5, QRect(mark.x() + 14, mark.y(), 2, 2), "c"),
        Callout(6, widget_rect(player, badges[0]), "lo"),
    ])


def shot_annotation_export(st):
    player, _sun_x = annotation_player(st)
    scroll = annotation_scroll(player)
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    st.pump()
    image = st.grab(player)
    inner = widget_rect(player, scroll.viewport())

    def seen(number, *widgets):
        rect = union(player, *widgets).intersected(inner)
        sc.require(rect.height() > 12, f"표지 {number}의 위젯이 칸 안에 보이지 않음")
        return Callout(number, rect, "g")

    st.save("annotation_export", image, [
        seen(1, player.annotationDeleteButton, player.annotationClearFrameButton),
        seen(2, player.annotationExportDirButton),
        seen(3, player.annotationExportButton),
    ], crop_to=widget_rect(player, box(player, "수정 사항 주석")), pad=4, gutter=GUTTER)


def shot_ocr(st):
    from PyQt5.QtCore import QRect

    player = st.player()
    sc.require(player.open_file("A", st.media("ANIMATIC", manual_media.ANIMATIC_NAME)), "애니매틱을 열지 못함")
    player.seek_to_frame(70)
    for title in ("ROI 설정", "OCR 분석", "결과 관리"):
        sc.expand(box(player, title))
    x1, y1, x2, y2 = manual_media.slate_box(manual_media.SLATES[2])
    roi = ((x1 - 10) / manual_media.WIDTH, (y1 - 10) / manual_media.HEIGHT,
           (x2 - x1 + 20) / manual_media.WIDTH, (y2 - y1 + 20) / manual_media.HEIGHT)
    player.on_roi_selected(roi)
    st.pump()
    image = st.grab(player)
    corner = video_point(player, roi[0] + roi[2], roi[1])
    st.save("ocr", image, [
        Callout(1, widget_rect(player, player.ocrSelectRoiButton), "lo"),
        Callout(2, union(player, player.ocrClearRoiButton, player.ocrTrackingCheckBox), "lo"),
        Callout(3, widget_rect(player, player.ocrModeComboBox), "lo"),
        Callout(4, union(player, player.ocrAnalyzeButton, player.ocrAnalyzeRangeButton), "lo"),
        Callout(5, union(player, player.ocrReopenResultButton, player.ocrLoadResultButton), "lo"),
        Callout(6, QRect(corner.x(), corner.y(), 2, 2), "c"),
    ])


def shot_review(st):
    import cv2
    from PyQt5 import sip
    from yesoncheck.player_review import OCRReviewDialog

    player = st.player()
    path = st.media("ANIMATIC", manual_media.ANIMATIC_NAME)
    sc.require(player.open_file("A", path), "애니매틱을 열지 못함")
    frames = manual_media.ANIMATIC_SCENE_FRAMES
    segments = []
    for index, slate in enumerate(manual_media.SLATES):
        x1, y1, x2, y2 = manual_media.slate_box(slate)
        ok, encoded = cv2.imencode(".png", manual_media.frame(index, 0.0)[y1 - 8:y2 + 8, x1 - 8:x2 + 8])
        sc.require(ok, "ROI 그림을 만들지 못함")
        start, end = index * frames, (index + 1) * frames - 1
        segments.append({"start_frame": start, "end_frame": end, "start_time": start / manual_media.FPS,
                         "end_time": (end + 1) / manual_media.FPS, "duration": frames / manual_media.FPS,
                         "text": slate, "edited_text": slate, "roi_preview": encoded.tobytes(), "detections": []})
    dialog = OCRReviewDialog(player, segments, fps=manual_media.FPS, total_frames=frames * len(segments), ocr_mode="titmouse")
    dialog.resize(1400, 900)
    dialog.show()

    def delete():
        dialog.close()
        sip.delete(dialog)

    st.cleanups.append(delete)
    st.pump(1.0)
    image = st.grab(dialog)

    def label(text):
        from PyQt5.QtWidgets import QLabel

        found = [w for w in dialog.findChildren(QLabel) if w.text() == text and w.isVisibleTo(dialog)]
        sc.require(len(found) == 1, f"검토 창의 {text!r} 글자가 하나가 아님: {len(found)}")
        fitted = widget_rect(dialog, found[0])
        fitted.setWidth(found[0].fontMetrics().horizontalAdvance(text) + 14)  # 글자 바로 오른쪽에 표지
        return fitted

    from PyQt5.QtWidgets import QTableWidget

    tables = [w for w in dialog.findChildren(QTableWidget) if w.isVisibleTo(dialog)]
    sc.require(len(tables) == 1, f"검토 창의 표가 하나가 아님: {len(tables)}")
    st.save("review", image, [
        Callout(1, label("씬 리스트"), "ro"),
        Callout(2, label("프리뷰 영상"), "ro"),
        Callout(3, label("타임라인"), "ro"),
        Callout(4, widget_rect(dialog, tables[0]), "tl"),
        Callout(5, union(dialog, dialog.mergeButton, dialog.redoButton), "tr"),
        Callout(6, union(dialog, dialog.exportSelectedButton, dialog.exportModeComboBox), "r"),
    ])


def shot_bookmarks(st):
    from yesoncheck import bookmarks
    from yesoncheck.sidebar_bookmarks import BookmarkDialog

    for folder in ("/Volumes/Project/MyShow/EP101/animatic", "/Volumes/Project/MyShow/EP101/scene-01A_S03/frames",
                   "/Volumes/Project/MyShow/EP102/layout", "/Volumes/Project/MyShow/EP102/color"):
        bookmarks.add(bookmarks.default_path(), folder)
    player = st.player()

    def prepare_and_show():
        player.show_bookmarks()

    original_exec = BookmarkDialog.exec_
    captured = {}

    def fake_exec(dialog, *args):
        dialog.resize(640, 320)
        dialog.show()
        dialog.list_widget.setCurrentRow(1)
        st.pump(0.6)
        captured["image"] = dialog.grab().toImage()
        dialog.close()
        return 0

    BookmarkDialog.exec_ = fake_exec
    try:
        prepare_and_show()
    finally:
        BookmarkDialog.exec_ = original_exec
    sc.require("image" in captured, "북마크 창이 뜨지 않음")
    st.save("bookmarks", captured["image"])


def shot_media_info(st):
    from PyQt5.QtWidgets import QMessageBox

    player = st.player()
    st.open_job(player)
    index = player.sidebar.model().index(0, 0)
    image = st.capture_dialog(QMessageBox, lambda: player.show_video_info(index))
    st.save("media_info", image)


def menu_shot(st, name, menu_index):
    from PyQt5.QtCore import QPoint, QRect

    player = st.player()
    st.open_job(player)
    image = st.grab(player)
    bar = player.menuBar()
    action = bar.actions()[menu_index]
    title = bar.actionGeometry(action)
    menu = action.menu()
    menu.popup(bar.mapToGlobal(QPoint(title.left(), title.bottom() + 1)))
    st.pump(0.4)
    shot = menu.grab().toImage()
    menu.close()
    at = bar.mapTo(player, QPoint(title.left(), title.bottom() + 1))
    paste(image, shot, at.x(), at.y())
    width, height = logical_size(shot)
    st.save(name, image, crop_to=QRect(0, 0, max(at.x() + int(width) + 40, 520), at.y() + int(height) + 10), pad=14)


def shot_settings_menu(st):
    menu_shot(st, "settings_menu", 0)


def shot_help_menu(st):
    menu_shot(st, "help_menu", 1)


def shot_update_banner(st):
    from PyQt5.QtCore import QRect

    player = st.player()
    st.open_job(player)
    player.update_banner.show_offer("1.9.0", "1.8.1")
    st.pump()
    image = st.grab(player)
    banner = widget_rect(player, player.update_banner)
    st.save("update_banner", image, crop_to=QRect(0, 0, WINDOW[0], banner.bottom() + 150), pad=0)


def shot_overlay_text(st):
    from PyQt5.QtCore import QRect

    player = st.player()
    st.open_job(player, row=3, frame=24)
    player.show_overlay = True
    player.update_frame()
    image = st.grab(player)
    top_left = video_point(player, 0.0, 0.58)
    bottom_right = video_point(player, 0.78, 1.0)
    st.save("overlay_text", image, crop_to=QRect(top_left, bottom_right), pad=0)


def shot_v_mode(st):
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest

    player = st.player()
    st.open_job(player, row=4, frame=20)
    QTest.keyClick(player, Qt.Key_V)
    st.pump(0.6)
    sc.require(not player.controls_visible and player.overlayFrame.isVisible(), "V 모드가 되지 않음")
    image = st.grab(player)
    st.save("v_mode", image, [Callout(1, widget_rect(player, player.overlayFrame), "tl", True)])


SHOTS = {
    "overview": shot_overview,
    "sidebar": shot_sidebar,
    "thumbnails": shot_thumbnails,
    "mov_menu": shot_mov_menu,
    "controls": shot_controls,
    "playbar": shot_playbar,
    "hover": shot_hover,
    "wipe": shot_wipe,
    "seq_tab": shot_seq_tab,
    "all_tab": shot_all_tab,
    "seq_menu": shot_seq_menu,
    "annotation": shot_annotation,
    "annotation_export": shot_annotation_export,
    "ocr": shot_ocr,
    "review": shot_review,
    "bookmarks": shot_bookmarks,
    "media_info": shot_media_info,
    "settings_menu": shot_settings_menu,
    "help_menu": shot_help_menu,
    "update_banner": shot_update_banner,
    "overlay_text": shot_overlay_text,
    "v_mode": shot_v_mode,
}


# ---------------------------------------------------------------- 자식·부모


def child_main(args):
    try:
        run_shot(args)
    except BaseException:
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)


def run_shot(args):
    work = os.path.abspath(args.work)
    sys.path.insert(0, ROOT)
    sc.check_isolated_environment(work)
    sc.require(os.environ.get("QT_SCALE_FACTOR") == str(SCALE), "QT_SCALE_FACTOR가 정해지지 않음")
    sc.require(os.path.realpath(MEDIA_LINK) == os.path.realpath(os.path.join(work, "MyShow")),
               f"{MEDIA_LINK}가 이 샷의 합성 영상 폴더를 가리키지 않음: {os.path.realpath(MEDIA_LINK)}")

    from PyQt5.QtWidgets import QApplication

    app = QApplication(["manual_screenshots"])
    app.setCursorFlashTime(0)
    import yesoncheck

    sc.require(os.path.realpath(yesoncheck.__file__).startswith(os.path.realpath(ROOT) + os.sep),
               f"다른 곳의 yesoncheck를 불러옴: {yesoncheck.__file__}")
    dialogs = sc.install_dialog_guards()
    stage = Stage(app, work, os.path.abspath(args.out))
    SHOTS[args.child](stage)
    bad = [d for d in dialogs if d["kind"] in ("critical", "warning")]
    sc.require(not bad, f"샷 중에 경고·오류 창이 뜸: {bad}")
    for cleanup in reversed(stage.cleanups):
        cleanup()
    sc.pump(app, 0.2)
    sc.wait_for_background(app, "창을 닫은 뒤")
    print("saved " + json.dumps(stage.saved, ensure_ascii=False), flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def prepare_work(work, media_root):
    config = os.path.join(work, "share", ".yesoncheck")
    for folder in (os.path.join(work, "home"), config, os.path.join(work, "instances")):
        os.makedirs(folder)
    with open(os.path.join(config, "work_paths.json"), "w", encoding="utf-8") as fh:
        fh.write("{}")
    shutil.copytree(media_root, os.path.join(work, "MyShow"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="사용법 매뉴얼 스크린샷 만들기")
    parser.add_argument("--out", default=os.path.join(ROOT, "yesoncheck", "manual_images"))
    parser.add_argument("--shot", action="append", choices=sorted(SHOTS), help="이 샷만 (여러 번 줄 수 있음, 기본: 전부)")
    parser.add_argument("--child", choices=sorted(SHOTS), help=argparse.SUPPRESS)
    parser.add_argument("--work", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        child_main(args)
        return 0

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    names = args.shot or list(SHOTS)
    if os.path.lexists(MEDIA_LINK) and not os.path.islink(MEDIA_LINK):
        raise SystemExit(f"{MEDIA_LINK}가 이미 있고 링크가 아님 — 옮기거나 지운 뒤 다시 돌릴 것")
    base = tempfile.mkdtemp(prefix="yc_manual_", dir="/tmp")
    failed = []
    try:
        media_root = os.path.join(base, "_media")
        started = time.monotonic()
        manual_media.make_media(media_root, sc.ffmpeg_path(ROOT))
        print(f"합성 영상 {time.monotonic() - started:.1f}초", flush=True)
        for name in names:
            work = os.path.join(base, name)
            prepare_work(work, media_root)
            if os.path.islink(MEDIA_LINK):
                os.remove(MEDIA_LINK)
            os.symlink(os.path.join(work, "MyShow"), MEDIA_LINK)
            env = sc.child_environment(work, ROOT)
            env["QT_SCALE_FACTOR"] = str(SCALE)
            started = time.monotonic()
            proc = subprocess.run([sys.executable, SCRIPT, "--child", name, "--work", work, "--out", out],
                                  env=env, capture_output=True, text=True, timeout=SHOT_TIMEOUT_S)
            saved = [line for line in proc.stdout.splitlines() if line.startswith("saved ")]
            if proc.returncode != 0 or not saved:
                failed.append(name)
                print(f"[실패] {name} (종료 코드 {proc.returncode})\n{sc.tail(proc.stdout + proc.stderr, 30)}", flush=True)
                continue
            print(f"{name}: {saved[-1][6:]} {time.monotonic() - started:.1f}초", flush=True)
    finally:
        if os.path.islink(MEDIA_LINK):
            os.remove(MEDIA_LINK)
        shutil.rmtree(base, ignore_errors=True)
    if failed:
        print(f"실패한 샷: {failed}")
        return 1
    print(f"스크린샷 {len(names)}개 샷 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
