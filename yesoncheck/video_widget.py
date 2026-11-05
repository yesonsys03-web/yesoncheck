"""Video display widget with zoom, pan, and drag support."""

import math
import os
import traceback

import cv2
import numpy as np
from PyQt5 import sip
from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QBrush,
    QFont,
    QFontMetricsF,
    QImage,
    QOpenGLContext,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QSurfaceFormat,
    QTransform,
    QWheelEvent,
)

from PyQt5.QtWidgets import (
    QApplication,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QLabel,
    QMessageBox,
    QOpenGLWidget,
)

from yesoncheck import gl_bindings, paths, windows_display
from yesoncheck.annotation_overlay import AnnotationOverlay
from yesoncheck.frame_handles import native_surface_of, whole_surface_handle
from yesoncheck.gl_video_item import LOG_PREFIX, VIDEO_ITEM_ENV, VideoFrameItem, use_stream_item, video_item_mode
from yesoncheck.overlay_text_layout import overlay_layout

VIEWPORT_ENV = "YESONCHECK_VIEWPORT"
VIEWPORT_MODES = ("gl", "raster")

# 영상 주변 여백 색 — main_window_styles의 테마 배경과 짝 (어두운: QWidget #232323, 밝은: QMainWindow #fafafa).
# GL 뷰포트는 스타일시트 배경 칠을 받지 않아(WA_OpaquePaintEvent) backgroundBrush로 GPU가 칠함.
# 시트는 해시로 얼어 있어(tests/test_stylesheet_freeze.py) 값이 어긋날 일 없음.
VIDEO_BG = {"dark": "#232323", "light": "#fafafa"}

# B 키 오버레이 아이템(네이티브 프레임 — set_overlay_text): 쌓임은 ROI(10) 위, 주석 미리보기(14)·편집 핸들(16) 아래
OVERLAY_ITEM_Z = 13
# 주석 층(네이티브 프레임 — annotation_overlay): B 키 상자 위(굽는 길도 B 글자를 먼저, 주석을 그 위에 구움 — Ruling 18), 주석 미리보기(14) 아래
ANNOTATION_OVERLAY_Z = 13.5
OVERLAY_FONT_REF_PX = 100  # 글꼴 크기를 정할 때 대문자 높이를 재는 기준 픽셀 크기 (overlay_font)


def viewport_mode(platform_name, env, windows_renderer=windows_display.DEFAULT_RENDERER):
    """뷰포트 종류를 정함 — "gl" 또는 "raster".

    풀스크린 재생 FPS 저하는 Mac 레티나의 CPU 확대 블릿이 원인이라 cocoa에서만 GL이 기본
    (풀스크린 13.5→24.8fps, 창 모드는 동일 — 2026-10-28 실측). Windows는 기본 raster이고 Settings 메뉴에서 GPU를 고르면(windows_renderer —
    windows_display) GL — 4K 끊김이 줄어듦(사용자 확인 2026-11-05). offscreen(시험·CI)은 QOpenGLWidget을 지원하지 않음(컨텍스트 생성 실패).
    YESONCHECK_VIEWPORT=gl|raster로 명시해서 바꿀 수 있고(메뉴보다 우선), 그 밖의 값은 ValueError — 조용한 폴백 금지.
    """
    forced = env.get(VIEWPORT_ENV)
    if forced is not None:
        if forced not in VIEWPORT_MODES:
            raise ValueError(
                f"{VIEWPORT_ENV}는 {' 또는 '.join(VIEWPORT_MODES)}여야 합니다: {forced!r}"
            )
        return forced
    if platform_name == "cocoa" or (platform_name == "windows" and windows_renderer == "gpu"):
        return "gl"
    return "raster"


def viewport_forced(env):
    """토글(YESONCHECK_VIEWPORT)로 명시했는지 — 강제한 GL은 컨텍스트 확인 없이 말 그대로 강제."""
    return env.get(VIEWPORT_ENV) is not None


def gl_context_available():
    """OpenGL 컨텍스트를 실제로 만들 수 있는지 — cocoa에서도 드물게 실패할 수 있음(원격 세션·드라이버 문제)."""
    return QOpenGLContext().create()


def windows_gl_problem():
    """(Windows) 이 PC의 GL을 그리기 코드가 쓸 수 없는 이유, 쓸 수 있으면 None. 확인이 실패해도 창은 열려야 함 — GPU를 고른 PC가 앱을 못 켜면 메뉴로 되돌릴 수도
    없으므로 트레이스백을 기록하고 '쓸 수 없음'으로 돌려줌 (부른 쪽이 창으로 알림)."""
    try:
        return windows_display.gl_problem(gl_bindings.context_info())
    except Exception as exc:
        traceback.print_exc()
        return f"OpenGL을 확인하지 못했습니다: {exc}"


def overlay_font(text, layout):
    """B 키 오버레이 아이템의 글꼴 — 앱 기본 글꼴을 굽는 길(cv2 Hershey)의 글자 크기에 맞춤(모양은 다름 — 사용자 결정 "같아 보이면 OK").

    크기: 대문자 높이(QFontMetricsF.capHeight)가 cv2 글자 높이(layout.text_height — 기준선 위 높이, 대문자 높이에 획 반 굵기를 더한 값)와 같게 —
    OVERLAY_FONT_REF_PX에서 잰 대문자 높이로 비례 계산(대문자 높이는 픽셀 크기에 비례). 그래도 Qt 글자가 들어갈 너비(layout.room)보다 넓으면
    (글꼴마다 폭이 다름) 들어갈 때까지 더 줄임(1px까지). 굵기: cv2 획이 3px 이상(1080p 3·4K 8 — overlay_metrics)이면 Bold, 그보다 가늘면(720p 이하 2) 보통.
    굽는 길이 4K 획을 √(k/1.5)만큼 더 굵게 하는 것(줄여 볼 때 획 가장자리가 섞여 가늘어 보임)은 아이템에는 필요 없음 — Qt 글자는 화면 해상도로
    그려져 줄여 봐도 가늘어지지 않음. 대문자 높이를 잴 수 없는 글꼴(0 이하)이면 ValueError — 크기를 지어내지 않음."""
    font = QFont()
    font.setBold(layout.thickness >= 3)
    font.setPixelSize(OVERLAY_FONT_REF_PX)
    cap = QFontMetricsF(font).capHeight()
    if not cap > 0:
        raise ValueError(f"글꼴 {font.family()!r}의 대문자 높이를 잴 수 없습니다(capHeight {cap}, 픽셀 크기 {OVERLAY_FONT_REF_PX}, "
                         f"Qt 플랫폼 {QApplication.platformName()!r}) — B 키 오버레이 글자 크기를 정할 수 없음")
    font.setPixelSize(max(1, round(layout.text_height * OVERLAY_FONT_REF_PX / cap)))
    advance = QFontMetricsF(font).horizontalAdvance(text)
    while advance > layout.room and font.pixelSize() > 1:  # 작은 크기에서는 폭이 크기에 비례하지 않아(글꼴의 작은 크기용 자간) 다시 잼
        font.setPixelSize(max(1, min(font.pixelSize() - 1, math.floor(font.pixelSize() * layout.room / advance))))
        advance = QFontMetricsF(font).horizontalAdvance(text)
    return font


class CustomVideoWidget(QGraphicsView):
    wipePositionChanged = pyqtSignal()
    fitToWindowChanged = pyqtSignal(bool)
    roiSelectionFinished = pyqtSignal(tuple)  # (x, y, w, h) normalized to current frame
    annotationShapeFinished = pyqtSignal(dict)
    annotationTextRequested = pyqtSignal(float, float)
    annotationMovePressed = pyqtSignal(float, float)
    annotationMoveDragged = pyqtSignal(float, float)
    annotationMoveReleased = pyqtSignal(float, float)
    # 스트림 아이템(VideoFrameItem)이 그리기에 실패해 알릴 때(걸쇠 사이마다 첫 실패 — Qt 루프에서) — 값: 그리던 그림에 네이티브(IOSurface) 면이 있었는가.
    # 플레이어가 받아 Mac의 네이티브 면 실패면 이 창만 ffmpeg로 바꿈 (스펙 2026-11-04 §5.8). 기록·오류 창은 아이템이 이미 냄
    streamPaintFailed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # 뷰포트 종류(GL 여부)를 영상 아이템보다 먼저 정함: GL 뷰포트면 아이템이 VideoFrameItem(stream — 프레임을 GL 텍스처로
        # 바로 올림)이라 만들기 전에 알아야 하고, 아이템은 와이프 선·ROI보다 먼저 장면에 넣어야 쌓임 맨 아래(Z 순서)에 남음.
        # 아이템 선택(use_stream_item)이 토글을 검사하므로 YESONCHECK_VIDEO_ITEM=gl을 raster 뷰포트에 주면 여기서 ValueError.
        # setViewport 등 GL 적용 자체는 자리 조건(아래 주석) 때문에 그 자리에 그대로 둠.
        self.viewport_fallback_reason = None  # GL을 쓰려다 못 쓴 사유 — show_viewport_fallback(스플래시 뒤)이 창으로 알림
        platform_name = QApplication.platformName()
        mode = viewport_mode(platform_name, os.environ, windows_display.preferred())
        forced = viewport_forced(os.environ)
        gl_ok = mode == "gl" and (forced or gl_context_available())
        windows_problem = None
        if gl_ok and not forced and platform_name == "windows":  # 고른 GPU가 그리기 코드와 맞는가 — 맞지 않으면 그릴 때 실패하거나 오류 없이 느림 (windows_display)
            windows_problem = windows_gl_problem()
            gl_ok = windows_problem is None
        if mode == "gl" and not gl_ok:
            # 조용한 폴백 금지: 기록에 바로 남기고, 창은 여기서 띄우지 않음 — 위젯 생성 중 모달은
            # splash.finish의 processEvents 안에서 열려 시작 순서를 멈춤(업데이트 '잘 켜짐' 표시까지 늦어짐 — 검토 실측).
            # 사유를 남겨 두면 app.launch가 스플래시를 닫은 뒤 show_viewport_fallback으로 알림.
            if platform_name == "windows":
                windows_problem = windows_problem or windows_display.gl_problem(None)
                print(f"[뷰포트] GPU 화면 그리기를 쓸 수 없음 — raster로 계속: {windows_problem}")
                self.viewport_fallback_reason = windows_display.fallback_text(windows_problem)
            else:
                print("[뷰포트] OpenGL 컨텍스트 생성 실패 — raster로 계속 (풀스크린 재생이 느릴 수 있음)")
                self.viewport_fallback_reason = (
                    "OpenGL을 쓸 수 없어 기본 화면 그리기로 계속합니다 — 풀스크린 재생이 느릴 수 있습니다."
                )
        self.video_item_stream = use_stream_item(gl_ok, video_item_mode(os.environ))
        if self.video_item_stream:
            self.video_item = VideoFrameItem(stream=True)
            self.video_item.set_failure_callback(self._on_stream_failure)  # → streamPaintFailed
            self.scene.addItem(self.video_item)
        else:
            self.video_item = self.scene.addPixmap(QPixmap())
        self._pixmap_backing = None  # 픽스맵 길에 그린 네이티브 프레임 — RGB32 픽스맵이 그 메모리를 함께 쓰므로 다음 그림까지 쥠 (_show_native_frames)
        self._overlay_provider = None  # B 키 글자 공급자 () -> str | None — 플레이어가 등록(set_overlay_provider), updateFrame의 네이티브 분기가 부름
        self._annotation_provider = None  # 주석 공급자 () -> list[dict] — 보이는 프레임의 주석, 플레이어가 등록(set_annotation_provider)

        self.wipe_position_x = 0.5
        self.wipe_position_y = 0.5
        self.wipe_line_x = QGraphicsLineItem()
        self.wipe_line_y = QGraphicsLineItem()
        self.scene.addItem(self.wipe_line_x)
        self.scene.addItem(self.wipe_line_y)
        self.wipe_enabled_x = False
        self.wipe_enabled_y = False

        self.setMouseTracking(True)
        self.aspect_ratio = 16 / 9
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.wipeEnabled = False
        self.setAcceptDrops(True)
        self.zoom_level = 1.0
        self.base_line_width = 8
        self.initial_fit = True
        self.setDragMode(QGraphicsView.NoDrag)
        self.is_panning = False
        self.last_pan_point = QPointF()
        self.is_fit_to_window = False
        self.is_original_size = False
        self.zoom_changed = False
        
        # 키보드 이벤트가 메인 윈도우로 전달되도록 포커스 정책 설정
        self.setFocusPolicy(Qt.NoFocus)

        # Mac(cocoa) 풀스크린 재생: 라스터 페인트의 CPU 확대 블릿이 병목이라 GL 뷰포트로 확대를 GPU에 맡김.
        # 자리 조건 둘: setAcceptDrops(True) 뒤(새 뷰포트가 드롭 수락을 물려받음), 아래 라벨들을 만들기 전 —
        # setViewport()는 새 뷰포트를 자식 맨 끝(쌓임 맨 위)에 두므로 라벨을 그 뒤에 만들어야 GL 위에 보임
        # (아래로 깔린 형제는 hole punch로 지워짐 — 쌓임 순서는 test_gl_viewport가 지킴). GL을 쓸지(gl_ok)는 맨 위에서 정함.
        if gl_ok:
            gl_viewport = QOpenGLWidget()
            msaa = QSurfaceFormat(gl_viewport.format())
            msaa.setSamples(4)  # GL2 페인트 엔진의 안티앨리어싱은 MSAA뿐 — 와이프 선·ROI·주석 미리보기 계단 방지
            gl_viewport.setFormat(msaa)
            self.setViewport(gl_viewport)
            self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)  # GL은 부분 갱신이 안 됨
            self.viewport().setMouseTracking(True)  # setViewport()가 꺼 둠 — 와이프 선 커서 등
            # FullViewportUpdate라 매 페인트가 뷰포트 전체를 덮음 — 불투명 선언. 없으면 창 전체 스타일시트
            # 폴리시 뒤 뷰포트가 불투명으로 인정되지 않아 풀스크린 FPS가 24.8→16으로 떨어짐 (2026-10-28 실측)
            self.viewport().setAttribute(Qt.WA_OpaquePaintEvent, True)
            self.apply_theme_background("dark")  # 안전 기본값 — 창을 만드는 쪽과 테마 전환이 다시 맞춰 줌
            print("[뷰포트] GL(QOpenGLWidget) 사용 — 풀스크린 재생 확대를 GPU로")
            if self.video_item_stream:
                print(f"{LOG_PREFIX} GL 텍스처 스트리밍(VideoFrameItem)")
            else:
                print(f"{LOG_PREFIX} QPixmap 경로(토글 {VIDEO_ITEM_ENV}=pixmap)")

        self.zoom_label = QLabel(self)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setStyleSheet("background-color: rgba(255, 255, 255, 128); padding: 5px; border-radius: 3px;")
        self.zoom_label.hide()

        # 주석 모드 배지 — 접힌 주석 패널 밖에서도 모드가 켜진 것을 알 수 있게 (enable_annotation_mode가 보임/숨김)
        self.annotation_mode_label = QLabel("주석 모드", self)
        self.annotation_mode_label.setAlignment(Qt.AlignCenter)
        self.annotation_mode_label.setStyleSheet(
            "background-color: rgba(200, 30, 30, 230); color: white; font-weight: bold; padding: 5px; border-radius: 3px;"
        )
        # 배지 아래의 클릭·휠이 비디오 영역에 그대로 닿게 (없으면 배지가 그 구석의 그리기·줌을 말없이 삼킴)
        self.annotation_mode_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.annotation_mode_label.hide()

        # ROI overlay for OCR detection
        self.roi_selection_enabled = False
        self.roi_start_view_pos = None
        self.roi_normalized_rect = None  # (x, y, w, h) normalized to video frame
        self.roi_rect_item = QGraphicsRectItem()
        roi_pen = QPen(QColor(255, 165, 0, 180))
        roi_pen.setWidthF(2.0)
        self.roi_rect_item.setPen(roi_pen)
        self.roi_rect_item.setBrush(QColor(255, 165, 0, 60))
        self.roi_rect_item.setVisible(False)
        self.roi_rect_item.setZValue(10)
        self.scene.addItem(self.roi_rect_item)

        # B 키 오버레이 아이템(네이티브 프레임 — 읽기 전용이라 굽지 않음): 흰 상자 + 검정 글자, 영상 아이템 좌표(= 프레임 픽셀)라
        # 줌·맞춤에 따라 구운 글자처럼 함께 커짐. 영상 아이템보다 뒤에 넣고 z OVERLAY_ITEM_Z (주석 층이 13과 14 사이에 끼므로 쌓임 약속).
        # 글자는 상자의 자식 — 자식은 늘 부모 위에 그려지므로 z·넣은 차례와 상관없이 글자가 상자 위, 보임/숨김도 상자 하나로 (set_overlay_text).
        # 상자는 원점(0, 0)에 두고 사각형을 프레임 좌표로 잡으므로 상자 좌표 = 프레임 좌표
        self.overlay_box_item = QGraphicsRectItem()
        self.overlay_box_item.setPen(QPen(Qt.NoPen))
        self.overlay_box_item.setBrush(QColor(255, 255, 255))
        self.overlay_box_item.setZValue(OVERLAY_ITEM_Z)
        self.overlay_box_item.setVisible(False)
        self.overlay_text_item = QGraphicsSimpleTextItem(self.overlay_box_item)
        self.overlay_text_item.setBrush(QColor(0, 0, 0))
        self.scene.addItem(self.overlay_box_item)

        # 주석 층(네이티브 프레임 — 읽기 전용이라 주석을 굽지 않음): 프레임 사각형 하나가 주석마다 자식 아이템(annotation_overlay). 영상 아이템보다 뒤에
        # 넣고 원점·프레임 좌표라 B 키 상자처럼 줌·맞춤에 따라 구운 주석처럼 커짐; z ANNOTATION_OVERLAY_Z. 갱신은 updateFrame(_refresh_native_annotations)
        self.annotation_overlay = AnnotationOverlay()
        self.annotation_overlay.setZValue(ANNOTATION_OVERLAY_Z)
        self.scene.addItem(self.annotation_overlay)

        # Frame annotation overlay
        self.annotation_mode_enabled = False
        self.annotation_tool = "rect"
        self.annotation_color = "#ff3333"
        self.annotation_font_size = 28
        self.annotation_stroke_width = 3
        self.annotation_start_view_pos = None
        self.annotation_preview_item = None
        self.annotation_edit_target = None
        self.annotation_edit_handle_items = []
        self.annotation_edit_interaction = False

    def apply_theme_background(self, theme):
        """영상 주변 여백을 테마 배경색으로 — GL 뷰포트에서만 (raster는 스타일시트가 칠하므로 그대로 둠)."""
        if theme not in VIDEO_BG:
            raise ValueError(f"테마는 {' 또는 '.join(VIDEO_BG)}여야 합니다: {theme!r}")
        if isinstance(self.viewport(), QOpenGLWidget):
            self.setBackgroundBrush(QColor(VIDEO_BG[theme]))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_zoom_label_position()
        self.update_annotation_mode_label_position()
        if self.is_fit_to_window:
            self.fitInView(self.video_item, Qt.KeepAspectRatio)

    def update_zoom_label_position(self):
        self.zoom_label.move(10, 10)

    def update_annotation_mode_label_position(self):
        self.annotation_mode_label.adjustSize()
        self.annotation_mode_label.move(
            max(10, self.width() - self.annotation_mode_label.width() - 10), 10
        )

    def wheelEvent(self, event: QWheelEvent):
        """전역 휠 이벤트 처리 - 사이드바를 제외한 모든 영역에서 프레임 이동 또는 줌"""
        # 부모 위젯을 찾아서 비디오 상태 확인
        parent = self.parent()
        while parent and not hasattr(parent, 'cap_a'):
            parent = parent.parent()
        
        # 비디오가 로드되지 않은 경우 무시
        if not parent or not parent.cap_a:
            event.ignore()
            return
            
        delta = event.angleDelta().y()
        
        # Ctrl 키를 누른 상태에서 휠을 사용하면 줌인/줌아웃
        if event.modifiers() == Qt.ControlModifier:
            # 마우스 커서 위치를 비디오 위젯 좌표로 변환
            cursor_pos = self.mapFromGlobal(self.cursor().pos())
            
            if delta > 0:  # 휠 업 (줌인)
                self.zoom_in(cursor_pos)
            else:  # 휠 다운 (줌아웃)
                self.zoom_out(cursor_pos)
            event.accept()
            return
        
        # Ctrl 키가 아닌 경우 기존 프레임 이동 로직
        frame_step = 1  # 3에서 1로 변경
        
        # CAP_PROP_POS_FRAMES는 다음 읽을 프레임의 0-based 인덱스
        current_frame_idx = int(parent.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        if current_frame_idx < 0:
            current_frame_idx = 0
        
        if delta < 0:  # 휠 다운 (이전)
            target_frame_idx = max(0, current_frame_idx - frame_step)
        else:  # 휠 업 (다음)
            total_frames = int(parent.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
            target_frame_idx = min(total_frames - 1, current_frame_idx + frame_step)
        
        # 프레임 이동
        parent.seek_to_frame(target_frame_idx + 1)  # seek_to_frame은 1-based
        event.accept()

    def show_original_size(self):
        if self.video_item.pixmap():
            self.is_original_size = True
            self.is_fit_to_window = False
            self.setTransform(QTransform())
            self.setRenderHint(QPainter.SmoothPixmapTransform, True)  # 안티앨리어싱 적용
            self.setRenderHint(QPainter.Antialiasing, True)  # 추가 안티앨리어싱
            self.video_item.setTransformationMode(Qt.SmoothTransformation)  # 부드러운 변환 모드
            self.centerOn(self.video_item.boundingRect().center())
            self.updateWipeLine()
            self._update_roi_item()
            self.fitToWindowChanged.emit(False)
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.hide_zoom_label()

    def fit_to_window(self):
        if self.video_item.pixmap():
            self.setTransform(QTransform())
            self.fitInView(self.video_item, Qt.KeepAspectRatio)
            self.setRenderHint(QPainter.SmoothPixmapTransform, True)  # 안티앨리어싱 적용
            self.setRenderHint(QPainter.Antialiasing, True)  # 추가 안티앨리어싱
            self.video_item.setTransformationMode(Qt.SmoothTransformation)  # 부드러운 변환 모드
            self.is_fit_to_window = True
            self.is_original_size = False
            self.updateWipeLine()
            self._update_roi_item()
            self.fitToWindowChanged.emit(True)
            self.setDragMode(QGraphicsView.NoDrag)
            self.hide_zoom_label()

    def zoom_in(self, mouse_pos=None):
        print(f"zoom_in called - current scale: {self.transform().m11()}")  # 디버깅 출력
        self.is_fit_to_window = False
        self.is_original_size = False
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        
        # 마우스 위치를 중심으로 줌인
        if mouse_pos is None:
            # 마우스 위치가 제공되지 않으면 뷰포트 중심 사용
            mouse_pos = self.mapFromGlobal(self.cursor().pos())
        
        # 현재 마우스 위치를 씬 좌표로 변환
        scene_pos = self.mapToScene(mouse_pos)
        
        # 줌 전 현재 뷰포트의 중심점 저장
        old_center = self.mapToScene(self.viewport().rect().center())
        
        # 스케일 적용
        scale_factor = 1.1
        self.scale(scale_factor, scale_factor)
        
        # 줌 후 새로운 뷰포트의 중심점 계산
        new_center = self.mapToScene(self.viewport().rect().center())
        
        # 마우스 위치가 뷰포트 중심에 오도록 뷰포트 이동
        delta = scene_pos - new_center
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + int(delta.x()))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + int(delta.y()))
        
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)  # 안티앨리어싱 적용
        self.setRenderHint(QPainter.Antialiasing, True)  # 추가 안티앨리어싱
        self.video_item.setTransformationMode(Qt.SmoothTransformation)  # 부드러운 변환 모드
        new_scale = self.transform().m11()
        print(f"zoom_in - new scale: {new_scale}")  # 디버깅 출력
        self.updateWipeLine()
        self._update_roi_item()
        self._update_edit_handle_items()
        self.show_zoom_label()

    def zoom_out(self, mouse_pos=None):
        print(f"zoom_out called - current scale: {self.transform().m11()}")  # 디버깅 출력
        self.is_fit_to_window = False
        self.is_original_size = False
        
        # 마우스 위치를 중심으로 줌아웃
        if mouse_pos is None:
            # 마우스 위치가 제공되지 않으면 뷰포트 중심 사용
            mouse_pos = self.mapFromGlobal(self.cursor().pos())
        
        # 현재 마우스 위치를 씬 좌표로 변환
        scene_pos = self.mapToScene(mouse_pos)
        
        # 줌 전 현재 뷰포트의 중심점 저장
        old_center = self.mapToScene(self.viewport().rect().center())
        
        # 스케일 적용
        scale_factor = 1 / 1.1
        self.scale(scale_factor, scale_factor)
        
        # 줌 후 새로운 뷰포트의 중심점 계산
        new_center = self.mapToScene(self.viewport().rect().center())
        
        # 마우스 위치가 뷰포트 중심에 오도록 뷰포트 이동
        delta = scene_pos - new_center
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + int(delta.x()))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + int(delta.y()))
        
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)  # 안티앨리어싱 적용
        self.setRenderHint(QPainter.Antialiasing, True)  # 추가 안티앨리어싱
        self.video_item.setTransformationMode(Qt.SmoothTransformation)  # 부드러운 변환 모드
        new_scale = self.transform().m11()
        print(f"zoom_out - new scale: {new_scale}")  # 디버깅 출력
        if new_scale < 0.1:  # 매우 작은 최소값으로 설정
            self.fit_to_window()
        self.updateWipeLine()
        self._update_roi_item()
        self._update_edit_handle_items()
        self.show_zoom_label()

    def reset_view(self):
        self.fit_to_window()
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)  # 안티앨리어싱 적용
        self.setRenderHint(QPainter.Antialiasing, True)  # 추가 안티앨리어싱
        self.video_item.setTransformationMode(Qt.SmoothTransformation)  # 부드러운 변환 모드
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        # 부모 위젯을 찾아서 VideoPlayer 인스턴스를 찾기
        parent = self.parent()
        while parent and not hasattr(parent, 'open_file'):
            parent = parent.parent()
        
        if parent and hasattr(parent, 'open_file'):
            video_files = []
            has_folder = False
            read_failed = False  # 읽지 못한 폴더가 있음 (창으로 알림 — '지원되는 비디오 파일이 없습니다'는 띄우지 않음)
            folder_paths = []  # 폴더 경로들을 저장할 리스트
            frame_files = []  # 영상이 아닌 파일 — 이미지 시퀀스 프레임이면 그 시퀀스를 엶 (parent._dropped_frames가 이름을 봄)
            
            # URL들을 파일/폴더로 분류
            for url in urls:
                local_path = paths.normalize_native(url.toLocalFile())
                if os.path.isfile(local_path):
                    # 파일인 경우
                    if parent.is_video_file(local_path):
                        video_files.append(local_path)
                    else:
                        frame_files.append(local_path)
                elif os.path.isdir(local_path):
                    # 폴더인 경우 - 재귀적으로 비디오 파일 찾기
                    has_folder = True
                    folder_paths.append(local_path)  # 폴더 경로 저장
                    folder_files = parent.get_video_files_from_folder(local_path)
                    if folder_files is None:
                        read_failed = True
                        parent._register_unread_folder(local_path)  # 연결이 돌아오면 새로고침(F5)으로 들어옴
                        continue
                    folder_files.sort()  # 이름 순서대로 정렬
                    video_files.extend(folder_files)
            
            # 폴더가 포함된 경우 북마크에 자동 추가
            if folder_paths:
                parent.add_dropped_folders_to_bookmarks(folder_paths)
            
            # 이미지 시퀀스 프레임 파일 (한 장뿐인 프레임·프레임이 아닌 파일은 빠짐 — 예전처럼 무시)
            frames = parent._dropped_frames(frame_files)
            
            # 비디오 파일 처리
            if has_folder:
                # 폴더가 포함된 경우: 기존 사이드바 초기화 후 모든 파일을 사이드바에 추가하고 첫 번째 파일을 Video A에 로드
                if video_files:
                    # 첫 폴더의 썸네일 폴더를 씀 (전에 고른 job·폴더가 아니라)
                    parent._use_dropped_folder_for_thumbnails(folder_paths[0])
                    # 기존 사이드바 리스트 초기화
                    parent.sidebar.clear()
                    parent.add_files_to_sidebar(video_files, folder_paths)
                    # 첫 번째 파일을 Video A에 로드
                    parent.open_file('A', video_files[0])
                    # 백그라운드 로딩 스케줄링
                    parent.schedule_background_thumbnail_loading()
                    QMessageBox.information(parent, "폴더 로드 완료", f"{len(video_files)}개의 비디오 파일이 사이드바에 추가되었습니다.\n첫 번째 파일이 Video A에 로드되었습니다.")
                elif parent._dropped_folders_have_sequences(folder_paths):
                    # 시퀀스만 든 폴더: 영상 폴더를 놓을 때처럼 목록을 새로 채우되 Seq 탭을 보여 줌 ('영상이 없습니다' 경고 없음)
                    parent.sidebar.clear()
                    parent._show_dropped_sequence_folders(folder_paths)
                elif not read_failed:
                    QMessageBox.warning(parent, "경고", "폴더에 지원되는 비디오 파일이 없습니다.")
            else:
                # 개별 파일들만 있는 경우
                if frames:
                    # 프레임: 영상 파일이 함께 없으면 영상 파일을 놓을 때처럼 그 시퀀스를 열고 Seq 탭을 보여 줌. 영상이 함께 있으면 영상은 아래에서 예전대로,
                    # 시퀀스는 Seq 목록에만 더함
                    parent._add_dropped_frames(frames, show_tab=not video_files, open_them=not video_files)
                if len(video_files) == 1:
                    parent.open_file('A', video_files[0])
                elif len(video_files) == 2:
                    # 두 개 파일: Video A와 B에 각각 로드
                    parent.open_file('A', video_files[0])
                    parent.open_file('B', video_files[1])
                elif len(video_files) > 2:
                    # 여러 파일: 첫 번째는 Video A에, 나머지는 사이드바에 추가
                    parent.open_file('A', video_files[0])
                    remaining_files = video_files[1:]
                    parent.add_files_to_sidebar(remaining_files)
                    if remaining_files:
                        QMessageBox.information(parent, "파일 로드 완료", f"첫 번째 파일이 Video A에 로드되고, {len(remaining_files)}개의 파일이 사이드바에 추가되었습니다.")
            
            # 폴더와 함께 놓은 프레임의 시퀀스는 Seq 목록에만 더함 (폴더 처리는 위에서 예전대로)
            if has_folder and frames:
                parent._add_dropped_frames(frames)
        
        event.acceptProposedAction()

    def updateFrame(self, frame_a, frame_b):
        if frame_a is None:
            self.video_item.setPixmap(QPixmap())
            self._pixmap_backing = None  # 빈 픽스맵을 건 뒤에 놓음 — 픽스맵 길이 앞 네이티브 프레임의 표면(4K 33MB)을 더 쥐지 않게
            self.set_overlay_text(None, 0, 0)  # 비운 화면에 앞 네이티브 프레임의 B 키 글자가 남지 않게
            self.annotation_overlay.clear()  # 주석 층도
            return

        if native_surface_of(frame_a) is not None or native_surface_of(frame_b) is not None:
            self._show_native_frames(frame_a, frame_b)  # 네이티브(IOSurface) 프레임 — RGB 변환·numpy 합성 없음
            self._refresh_native_overlay(frame_a)
            self._refresh_native_annotations(frame_a)
            self._after_frame_shown()
            return

        height, width = frame_a.shape[:2]
        bytes_per_line = 3 * width
        
        q_img = None
        if self.wipe_enabled_x or self.wipe_enabled_y:
            if frame_b is None or frame_b.shape != frame_a.shape:
                frame_b = np.zeros_like(frame_a)
            result = frame_a.copy()
            if self.wipe_enabled_x:
                wipe_x = int(width * self.wipe_position_x)
                result[:, wipe_x:] = frame_b[:, wipe_x:]
            if self.wipe_enabled_y:
                wipe_y = int(height * self.wipe_position_y)
                result[wipe_y:, :] = frame_b[wipe_y:, :]
            q_img = QImage(result.data, width, height, bytes_per_line, QImage.Format_RGB888)
        else:
            q_img = QImage(frame_a.data, width, height, bytes_per_line, QImage.Format_RGB888)

        if self.video_item_stream:  # GL 텍스처 스트리밍: QPixmap 변환 없이 배열 그대로 (와이프면 위에서 합성한 result)
            self.video_item.set_frame(result if self.wipe_enabled_x or self.wipe_enabled_y else frame_a)
        else:
            pixmap = QPixmap.fromImage(q_img)
            self.video_item.setPixmap(pixmap)

        self._pixmap_backing = None  # RGB 그림을 건 뒤에 놓음 — 픽스맵 길이 앞 네이티브 프레임의 표면을 더 쥐지 않게(스트림 길에선 늘 None)
        self.set_overlay_text(None, width, height)  # RGB 프레임의 B 키 글자는 프레임에 구움 — 앞 네이티브 프레임의 아이템이 남지 않게(숨어 있으면 할 일 없음)
        self.annotation_overlay.clear()  # 주석도 프레임에 구움(prepare_frame_for_display) — 앞 네이티브 프레임의 주석 층을 비움(비어 있으면 할 일 없음)
        self._after_frame_shown()

    def _show_native_frames(self, frame_a, frame_b):
        """A 또는 B가 네이티브 프레임(frame_handles — IOSurface 위 BGRX 뷰)일 때 그리기 — CPU로 픽셀을 읽거나 합성하지 않는다.

        스트림 아이템(GL): 두 면을 그대로 set_sides — 네이티브 면은 아이템이 IOSurface를 텍스처로 묶고, 아닌 면(h264 등 RGB)은 아이템이 올림.
        와이프는 numpy 합성 대신 axis·ratio(GL scissor): X만 → ("x", wipe_position_x), Y만 → ("y", wipe_position_y), 둘 다 → ("xy", (rx, ry)),
        꺼짐 → (None, 0.0)이고 그때 B는 넘기지 않음.
        픽스맵 아이템(킬 스위치 YESONCHECK_VIDEO_ITEM=pixmap·raster 뷰포트 — 느려도 되는 끄는 길): **A만** 그림(와이프 합성은 GL 길의 몫 — 와이프 선은
        그대로 보이지만 B는 그리지 않음). 네이티브 A는 QImage Format_RGB32(리틀 엔디언 B·G·R·X 바이트 = BGRX)로 표면 메모리를 복사 없이 가리키고
        행 간격은 strides[0](bytesPerRow); RGB32 픽스맵은 그 메모리를 함께 쓸 수 있어 배열을 _pixmap_backing에 다음 그림까지 쥔다(배열이 손잡이로
        IOSurface를 살림). 표면 전체가 아닌 네이티브 뷰(조각·뒤집힌 뷰)는 바이트 배치가 달라 ValueError. A가 RGB(B만 네이티브)면 RGB888."""
        wipe_x, wipe_y = self.wipe_enabled_x, self.wipe_enabled_y
        if self.video_item_stream:
            if wipe_x and wipe_y:
                axis, ratio = "xy", (self.wipe_position_x, self.wipe_position_y)
            elif wipe_x:
                axis, ratio = "x", self.wipe_position_x
            elif wipe_y:
                axis, ratio = "y", self.wipe_position_y
            else:
                axis, ratio = None, 0.0
            self.video_item.set_sides(frame_a, frame_b if axis else None, axis, ratio)
            return
        height, width = frame_a.shape[:2]
        if native_surface_of(frame_a) is None:
            q_img = QImage(frame_a.data, width, height, 3 * width, QImage.Format_RGB888)
        else:
            if whole_surface_handle(frame_a) is None:
                raise ValueError(f"A 면이 네이티브 프레임의 표면 전체가 아닙니다(조각·상하 반전·채널 역순 뷰 — shape {frame_a.shape}, "
                                 f"strides {frame_a.strides}) — RGB32 픽스맵으로 가리킬 수 없습니다")
            q_img = QImage(sip.voidptr(frame_a.ctypes.data), width, height, frame_a.strides[0], QImage.Format_RGB32)
        self.video_item.setPixmap(QPixmap.fromImage(q_img))
        self._pixmap_backing = frame_a  # 새 픽스맵을 건 뒤에 바꿈 — 옛 픽스맵이 걸려 있는 동안 옛 배열을 놓지 않게

    def _on_stream_failure(self, native):
        """(Qt 루프 — 스트림 아이템의 _fail이 미뤄 부름) 아이템의 그리기 실패를 streamPaintFailed(native)로 넘김."""
        self.streamPaintFailed.emit(native)

    def set_overlay_provider(self, provider):
        """B 키 글자 공급자 등록 — provider() -> str | None(None이면 숨김). 플레이어가 창을 만들 때 한 번(_overlay_text_for_native);
        updateFrame의 네이티브 분기가 프레임마다 불러 아이템을 갱신(공급자가 없으면 아이템을 숨김)."""
        if not callable(provider):
            raise TypeError(f"B 키 글자 공급자는 호출할 수 있어야 합니다: {provider!r}")
        self._overlay_provider = provider

    def _refresh_native_overlay(self, frame_a):
        """네이티브 분기의 B 키 아이템 갱신 — updateFrame이 한 곳에서: prepare_frame_for_display를 거치지 않고 updateFrame을 바로 부르는 길
        (_minimal_preview_seek 등)에서도 새 프레임 번호. A가 네이티브일 때만 보임 — A가 RGB(B만 네이티브)면 B 키 글자는 굽는 길의 몫이라
        아이템은 숨김(prepare_frame_for_display가 A에 이미 구웠으면 두 번 그리지 않게, 굽지 않는 미리보기 길은 예전 RGB 길처럼 글자 없음).
        기하는 A의 크기(frame_a.shape — 픽셀은 읽지 않음)."""
        height, width = frame_a.shape[:2]
        if self._overlay_provider is None or native_surface_of(frame_a) is None:
            self.set_overlay_text(None, width, height)
            return
        self.set_overlay_text(self._overlay_provider(), width, height)

    def set_annotation_provider(self, provider):
        """주석 공급자 등록 — provider() -> list[dict](보이는 프레임의 주석 — 플레이어의 annotation_store). 플레이어가 창을 만들 때 한 번
        (_annotations_for_native); updateFrame의 네이티브 분기가 프레임마다 불러 주석 층을 갱신(공급자가 없으면 층을 비움)."""
        if not callable(provider):
            raise TypeError(f"주석 공급자는 호출할 수 있어야 합니다: {provider!r}")
        self._annotation_provider = provider

    def _refresh_native_annotations(self, frame_a):
        """네이티브 분기의 주석 층 갱신 — B 키 아이템(_refresh_native_overlay)과 같은 약속: updateFrame 한 곳에서라 prepare_frame_for_display를
        거치지 않는 길(_minimal_preview_seek 등)과 편집 뒤 다시 그리기(_redraw_frame_with_annotations)도 보이는 프레임의 주석. A가 네이티브일 때만 채움 —
        A가 RGB(B만 네이티브)면 주석은 prepare_frame_for_display가 A에 이미 구웠으므로 층을 비움(두 번 그리지 않게). 기하는 A의 크기(frame_a.shape —
        픽셀은 읽지 않음)."""
        height, width = frame_a.shape[:2]
        if self._annotation_provider is None or native_surface_of(frame_a) is None:
            self.annotation_overlay.clear()
            return
        self.annotation_overlay.set_annotations(self._annotation_provider(), width, height)

    def set_overlay_text(self, text, width, height):
        """B 키 오버레이 아이템(흰 상자 + 검정 글자 — 네이티브 프레임용, 굽지 않음)을 width×height 프레임의 text로. None이면 둘 다 숨김
        (이미 숨었으면 할 일 없음).

        굽는 길(player_playback.overlay_text)과 같은 규칙(overlay_layout — overlay_metrics의 크기·여백, 너비를 넘치면 줄임): 기준선은
        (margin_x, 높이 − margin_y), 상자는 글자 상자를 pad만큼 넓힌 것 — 왼쪽 margin_x − pad, 위 기준선 − cv2 글자 높이 − pad(구운 상자와 같은
        픽셀), 아래 기준선 + max(pad, cv2 꼬리, Qt 꼬리)(Qt 글꼴의 g·p·_ 꼬리도 상자 안), 오른쪽 Qt 글자 끝 + pad. cv2.rectangle처럼 끝 픽셀까지
        칠하도록 너비·높이에 1을 더함. 글꼴은 overlay_font(대문자 높이 = cv2 글자 높이). 글자 아이템은 상자의 자식이라 자리는 상자 좌표 — 상자가
        원점에 있어 프레임 좌표와 같음 — 이고 보임/숨김은 상자를 따름."""
        if text is None:
            if self.overlay_box_item.isVisible():
                self.overlay_box_item.setVisible(False)  # 자식인 글자도 함께 숨음
            return
        layout = overlay_layout(text, width, height)
        font = overlay_font(text, layout)
        metrics = QFontMetricsF(font)
        x, y = layout.margin_x, height - layout.margin_y  # 기준선 왼쪽 끝
        pad = layout.pad
        below = max(pad, layout.baseline, math.ceil(metrics.descent()))
        self.overlay_text_item.setFont(font)
        self.overlay_text_item.setText(text)
        self.overlay_text_item.setPos(x, y - metrics.ascent())  # 상자 좌표(= 프레임 좌표). 글자 아이템의 원점은 글줄 위 — 기준선이 y에 오게
        self.overlay_box_item.setRect(QRectF(x - pad, y - layout.text_height - pad,
                                             metrics.horizontalAdvance(text) + 2 * pad + 1, layout.text_height + pad + below + 1))
        self.overlay_box_item.setVisible(True)  # 자식인 글자도 함께 보임

    def _after_frame_shown(self):
        """updateFrame의 꼬리(두 그리기 길이 함께 씀): 새 그림 크기에 장면·맞춤을 맞추고 와이프 선·ROI·편집 핸들을 다시 놓음."""
        scene_rect_changed = self.scene.sceneRect() != self.video_item.boundingRect()
        if self.initial_fit or scene_rect_changed:
            self.scene.setSceneRect(self.video_item.boundingRect())
            self.fit_to_window()
            self.initial_fit = False
        
        self.updateWipeLine()
        self._update_roi_item()
        self._update_edit_handle_items()

    def display_path(self):
        """프레임을 화면에 그리는 길 — "gl"(GL 뷰포트 + 스트림 아이템), "pixmap"(GL 뷰포트 + 픽스맵 아이템 — 킬 스위치
        YESONCHECK_VIDEO_ITEM=pixmap), "raster"(라스터 뷰포트). [측정] 줄의 표시= 값."""
        if self.video_item_stream:
            return "gl"
        return "pixmap" if isinstance(self.viewport(), QOpenGLWidget) else "raster"

    def toggleWipeEffect(self, enabled):
        self.wipeEnabled = enabled
        self.updateWipeLine()

    def updateWipeLine(self):
        if not self.video_item.pixmap() or self.video_item.pixmap().isNull():
            return
            
        current_scale = self.transform().m11()

        if self.wipe_enabled_x:
            self.wipe_line_x.show()
            pen = QPen(QColor(255, 0, 0, 80))
            pen.setWidthF(self.base_line_width / current_scale)
            self.wipe_line_x.setPen(pen)
            brect = self.video_item.boundingRect()
            scene_x = brect.x() + brect.width() * self.wipe_position_x
            self.wipe_line_x.setLine(scene_x, brect.y(), scene_x, brect.y() + brect.height())
        else:
            self.wipe_line_x.hide()

        if self.wipe_enabled_y:
            self.wipe_line_y.show()
            pen = QPen(QColor(255, 0, 0, 80))
            pen.setWidthF(self.base_line_width / current_scale)
            self.wipe_line_y.setPen(pen)
            brect = self.video_item.boundingRect()
            scene_y = brect.y() + brect.height() * self.wipe_position_y
            self.wipe_line_y.setLine(brect.x(), scene_y, brect.x() + brect.width(), scene_y)
        else:
            self.wipe_line_y.hide()

    def enable_roi_selection(self, enabled=True):
        """Enable or disable ROI selection mode."""
        self.roi_selection_enabled = enabled
        self.roi_start_view_pos = None
        if enabled:
            self.setCursor(Qt.CrossCursor)
            self.setDragMode(QGraphicsView.NoDrag)
        else:
            self.unsetCursor()
            if self.is_fit_to_window:
                self.setDragMode(QGraphicsView.NoDrag)
            else:
                self.setDragMode(QGraphicsView.ScrollHandDrag)

    def set_roi_normalized_rect(self, normalized_rect):
        """Update stored ROI and refresh overlay."""
        self.roi_normalized_rect = normalized_rect
        self._update_roi_item()

    def clear_roi(self):
        """Clear stored ROI and hide overlay."""
        self.roi_normalized_rect = None
        self.roi_rect_item.setVisible(False)

    def _update_roi_item(self):
        """Refresh overlay rectangle to match current pixmap geometry."""
        if (
            self.roi_normalized_rect
            and self.video_item.pixmap()
            and not self.video_item.pixmap().isNull()
        ):
            # scene 좌표계로 ROI 사각형 계산 (item 로컬 좌표가 아닌)
            scene_rect = self.video_item.sceneBoundingRect()
            if scene_rect.width() <= 0 or scene_rect.height() <= 0:
                self.roi_rect_item.setVisible(False)
                return
            norm_x, norm_y, norm_w, norm_h = self.roi_normalized_rect
            rect = QRectF(
                scene_rect.left() + norm_x * scene_rect.width(),
                scene_rect.top() + norm_y * scene_rect.height(),
                norm_w * scene_rect.width(),
                norm_h * scene_rect.height(),
            ).normalized()
            pen = self.roi_rect_item.pen()
            current_scale = max(self.transform().m11(), 0.0001)
            pen.setWidthF(2.0 / current_scale)
            self.roi_rect_item.setPen(pen)
            self.roi_rect_item.setRect(rect)
            self.roi_rect_item.setVisible(True)
        else:
            self.roi_rect_item.setVisible(False)

    def _clamp_to_video_rect(self, scene_pos):
        """Clamp a scene coordinate to the visible video area."""
        # scene 좌표계를 사용해야 하므로 sceneBoundingRect() 사용
        brect = self.video_item.sceneBoundingRect()
        if brect.width() <= 0 or brect.height() <= 0:
            return scene_pos
        clamped_x = max(brect.left(), min(scene_pos.x(), brect.right()))
        clamped_y = max(brect.top(), min(scene_pos.y(), brect.bottom()))
        return QPointF(clamped_x, clamped_y)

    def enable_annotation_mode(self, enabled=True, tool=None, color=None):
        """Enable drawing annotations on the current frame."""
        self.annotation_mode_enabled = enabled
        if tool:
            self.annotation_tool = tool
        if color:
            self.annotation_color = color
        self.annotation_start_view_pos = None
        self._clear_annotation_preview()
        self.set_annotation_edit_target(None)
        self.annotation_edit_interaction = False
        if enabled:
            self.setCursor(Qt.CrossCursor)
            self.setDragMode(QGraphicsView.NoDrag)
            self.update_annotation_mode_label_position()
            self.annotation_mode_label.show()
            self.annotation_mode_label.raise_()
        else:
            self.annotation_mode_label.hide()
            self.unsetCursor()
            if self.is_fit_to_window:
                self.setDragMode(QGraphicsView.NoDrag)
            elif not self.roi_selection_enabled:
                self.setDragMode(QGraphicsView.ScrollHandDrag)

    def set_annotation_edit_target(self, annotation):
        """Show resize/move handles for the selected annotation (edit tool)."""
        self.annotation_edit_target = dict(annotation) if annotation else None
        self._update_edit_handle_items()

    def _clear_edit_handle_items(self):
        for item in self.annotation_edit_handle_items:
            self.scene.removeItem(item)
        self.annotation_edit_handle_items = []

    def _edit_handle_norm_positions(self, annotation):
        if not annotation:
            return []
        ann_type = annotation.get("type")
        x1 = annotation.get("norm_x1", 0.0)
        y1 = annotation.get("norm_y1", 0.0)
        x2 = annotation.get("norm_x2", x1)
        y2 = annotation.get("norm_y2", y1)
        if ann_type in ("line", "arrow"):
            return [(x1, y1), (x2, y2)]
        if ann_type in ("rect", "ellipse"):
            left = min(x1, x2)
            top = min(y1, y2)
            right = max(x1, x2)
            bottom = max(y1, y2)
            return [(left, top), (right, top), (left, bottom), (right, bottom)]
        if ann_type == "text":
            return [(x1, y1)]
        return []

    def _update_edit_handle_items(self):
        self._clear_edit_handle_items()
        if not self.annotation_edit_target or not self.video_item.pixmap() or self.video_item.pixmap().isNull():
            return

        current_scale = max(self.transform().m11(), 0.0001)
        radius = max(5.0, 7.0 / current_scale)
        for norm_x, norm_y in self._edit_handle_norm_positions(self.annotation_edit_target):
            center = self._normalized_point_to_scene(norm_x, norm_y)
            handle = QGraphicsEllipseItem(-radius, -radius, radius * 2, radius * 2)
            handle.setPos(center)
            handle.setBrush(QBrush(QColor(255, 204, 0, 220)))
            handle.setPen(QPen(QColor(0, 0, 0, 180), 1.5 / current_scale))
            handle.setZValue(16)
            self.scene.addItem(handle)
            self.annotation_edit_handle_items.append(handle)

    def set_display_annotations(self, annotations):
        """Legacy hook (부르는 곳 없음) — 주석은 RGB 프레임에는 재생 때 굽고(prepare_frame_for_display), 네이티브 프레임에는 주석 층(set_annotation_provider)."""
        _ = annotations

    def _annotation_pen(self, color_hex, scale=None, stroke_width=None):
        pen = QPen(QColor(color_hex))
        current_scale = scale if scale is not None else max(self.transform().m11(), 0.0001)
        width = stroke_width if stroke_width is not None else self.annotation_stroke_width
        pen.setWidthF(float(width) / current_scale)
        pen.setCosmetic(False)
        return pen

    def _arrow_head_length(self, stroke_width=None):
        width = stroke_width if stroke_width is not None else self.annotation_stroke_width
        return max(12.0 / max(self.transform().m11(), 0.0001), 6.0 + width * 1.5)

    def _clear_annotation_preview(self):
        if self.annotation_preview_item is not None:
            self.scene.removeItem(self.annotation_preview_item)
            self.annotation_preview_item = None

    def _view_pos_to_normalized(self, view_pos):
        """Convert a view coordinate to normalized video coordinates."""
        pixmap = self.video_item.pixmap()
        if not pixmap or pixmap.isNull():
            return None

        video_scene_rect = self.video_item.sceneBoundingRect()
        video_viewport_tl = self.mapFromScene(video_scene_rect.topLeft())
        video_viewport_br = self.mapFromScene(video_scene_rect.bottomRight())
        video_viewport_rect = QRectF(video_viewport_tl, video_viewport_br).normalized()

        if video_viewport_rect.width() <= 0 or video_viewport_rect.height() <= 0:
            return None

        rel_x = (view_pos.x() - video_viewport_rect.left()) / video_viewport_rect.width()
        rel_y = (view_pos.y() - video_viewport_rect.top()) / video_viewport_rect.height()
        return (
            max(0.0, min(1.0, rel_x)),
            max(0.0, min(1.0, rel_y)),
        )

    def _normalized_point_to_scene(self, norm_x, norm_y):
        scene_rect = self.video_item.sceneBoundingRect()
        return QPointF(
            scene_rect.left() + norm_x * scene_rect.width(),
            scene_rect.top() + norm_y * scene_rect.height(),
        )

    def _normalized_rect_to_scene(self, norm_x1, norm_y1, norm_x2, norm_y2):
        p1 = self._normalized_point_to_scene(norm_x1, norm_y1)
        p2 = self._normalized_point_to_scene(norm_x2, norm_y2)
        return QRectF(p1, p2).normalized()

    def _create_arrow_item(self, x1, y1, x2, y2, color_hex, stroke_width=None):
        path = QPainterPath(QPointF(x1, y1))
        path.lineTo(x2, y2)
        angle = math.atan2(y2 - y1, x2 - x1)
        head_len = self._arrow_head_length(stroke_width)
        left = QPointF(
            x2 - head_len * math.cos(angle - math.pi / 6),
            y2 - head_len * math.sin(angle - math.pi / 6),
        )
        right = QPointF(
            x2 - head_len * math.cos(angle + math.pi / 6),
            y2 - head_len * math.sin(angle + math.pi / 6),
        )
        path.moveTo(x2, y2)
        path.lineTo(left)
        path.moveTo(x2, y2)
        path.lineTo(right)
        item = QGraphicsPathItem(path)
        item.setPen(self._annotation_pen(color_hex, stroke_width=stroke_width))
        item.setBrush(QBrush(Qt.NoBrush))
        return item

    def _update_annotation_preview(self, start_view_pos, end_view_pos):
        start_scene = self.mapToScene(start_view_pos)
        end_scene = self.mapToScene(end_view_pos)
        self._clear_annotation_preview()

        tool = self.annotation_tool
        color = self.annotation_color
        stroke = self.annotation_stroke_width
        if tool in ("rect", "ellipse"):
            rect = QRectF(start_scene, end_scene).normalized()
            if tool == "rect":
                self.annotation_preview_item = QGraphicsRectItem(rect)
            else:
                self.annotation_preview_item = QGraphicsEllipseItem(rect)
            self.annotation_preview_item.setPen(self._annotation_pen(color, stroke_width=stroke))
            self.annotation_preview_item.setBrush(QBrush(QColor(color + "44")))
        elif tool in ("line", "arrow"):
            if tool == "line":
                self.annotation_preview_item = QGraphicsLineItem(
                    start_scene.x(), start_scene.y(), end_scene.x(), end_scene.y()
                )
                self.annotation_preview_item.setPen(self._annotation_pen(color, stroke_width=stroke))
            else:
                self.annotation_preview_item = self._create_arrow_item(
                    start_scene.x(), start_scene.y(), end_scene.x(), end_scene.y(), color, stroke
                )
        else:
            return

        self.annotation_preview_item.setZValue(14)
        self.scene.addItem(self.annotation_preview_item)

    def _finish_annotation_draw(self, start_view_pos, end_view_pos):
        start_norm = self._view_pos_to_normalized(start_view_pos)
        end_norm = self._view_pos_to_normalized(end_view_pos)
        if not start_norm or not end_norm:
            return

        tool = self.annotation_tool
        if tool == "text":
            self.annotationTextRequested.emit(start_norm[0], start_norm[1])
            return

        dx = abs(end_norm[0] - start_norm[0])
        dy = abs(end_norm[1] - start_norm[1])
        if dx < 0.005 and dy < 0.005:
            # 드래그 없는 클릭 — 텍스트 입력은 '텍스트' 도구에서만 (도형 도구의 클릭은 아무것도 만들지 않음)
            return

        payload = {
            "type": tool,
            "norm_x1": start_norm[0],
            "norm_y1": start_norm[1],
            "norm_x2": end_norm[0],
            "norm_y2": end_norm[1],
            "color": self.annotation_color,
            "stroke_width": self.annotation_stroke_width,
        }
        self.annotationShapeFinished.emit(payload)

    def mousePressEvent(self, event):
        if self.annotation_mode_enabled and event.button() == Qt.LeftButton:
            if not self.video_item.pixmap() or self.video_item.pixmap().isNull():
                return
            norm = self._view_pos_to_normalized(event.pos())
            if norm:
                self.annotation_edit_interaction = False
                self.annotationMovePressed.emit(norm[0], norm[1])
                if self.annotation_edit_interaction:
                    return
            self.annotation_start_view_pos = event.pos()
            return

        if self.roi_selection_enabled and event.button() == Qt.LeftButton:
            if not self.video_item.pixmap() or self.video_item.pixmap().isNull():
                return
            # View 좌표를 직접 저장
            self.roi_start_view_pos = event.pos()
            return

        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            is_on_wipe_x = self.wipe_enabled_x and self.wipe_line_x.shape().contains(scene_pos)
            is_on_wipe_y = self.wipe_enabled_y and self.wipe_line_y.shape().contains(scene_pos)
            
            if is_on_wipe_x or is_on_wipe_y:
                 self.setDragMode(QGraphicsView.NoDrag)
                 if is_on_wipe_x: self.setCursor(Qt.SizeHorCursor)
                 if is_on_wipe_y: self.setCursor(Qt.SizeVerCursor)
            else:
                 if not self.is_fit_to_window:
                     self.setDragMode(QGraphicsView.ScrollHandDrag)
                 super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self.annotation_mode_enabled
            and self.annotation_edit_interaction
            and event.buttons() & Qt.LeftButton
        ):
            norm = self._view_pos_to_normalized(event.pos())
            if norm:
                self.annotationMoveDragged.emit(norm[0], norm[1])
            return

        if (
            self.annotation_mode_enabled
            and self.annotation_start_view_pos is not None
            and self.annotation_tool != "text"
        ):
            self._update_annotation_preview(self.annotation_start_view_pos, event.pos())
            return

        if self.roi_selection_enabled and hasattr(self, 'roi_start_view_pos') and self.roi_start_view_pos is not None:
            # View 좌표로 scene 사각형 표시 (임시, 최종은 release에서)
            start_scene = self.mapToScene(self.roi_start_view_pos)
            end_scene = self.mapToScene(event.pos())
            rect = QRectF(start_scene, end_scene).normalized()
            self.roi_rect_item.setRect(rect)
            self.roi_rect_item.setVisible(True)
            return

        if self.cursor().shape() in [Qt.SizeHorCursor, Qt.SizeVerCursor]:
            scene_pos = self.mapToScene(event.pos())
            brect = self.video_item.boundingRect()
            if self.cursor().shape() == Qt.SizeHorCursor and brect.width() > 0:
                self.wipe_position_x = max(0, min(1, (scene_pos.x() - brect.x()) / brect.width()))
            elif self.cursor().shape() == Qt.SizeVerCursor and brect.height() > 0:
                self.wipe_position_y = max(0, min(1, (scene_pos.y() - brect.y()) / brect.height()))
            self.updateWipeLine()
            self.wipePositionChanged.emit()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.annotation_mode_enabled and event.button() == Qt.LeftButton:
            if self.annotation_edit_interaction:
                norm = self._view_pos_to_normalized(event.pos())
                if norm:
                    self.annotationMoveReleased.emit(norm[0], norm[1])
                self.annotation_edit_interaction = False
                return
            if self.annotation_start_view_pos is not None:
                self._finish_annotation_draw(self.annotation_start_view_pos, event.pos())
                self.annotation_start_view_pos = None
                self._clear_annotation_preview()
            return

        if self.roi_selection_enabled and event.button() == Qt.LeftButton:
            if hasattr(self, 'roi_start_view_pos') and self.roi_start_view_pos is not None:
                end_view_pos = event.pos()
                
                pixmap = self.video_item.pixmap()
                if not pixmap or pixmap.isNull():
                    self.roi_start_view_pos = None
                    return
                
                # video_item의 viewport 좌표 얻기
                video_scene_rect = self.video_item.sceneBoundingRect()
                video_viewport_tl = self.mapFromScene(video_scene_rect.topLeft())
                video_viewport_br = self.mapFromScene(video_scene_rect.bottomRight())
                video_viewport_rect = QRectF(video_viewport_tl, video_viewport_br).normalized()
                
                # Viewport 좌표를 pixmap 좌표로 변환
                pixmap_width = pixmap.width()
                pixmap_height = pixmap.height()
                
                if video_viewport_rect.width() <= 0 or video_viewport_rect.height() <= 0:
                    self.roi_start_view_pos = None
                    self.roi_rect_item.setVisible(False)
                    return
                
                # View 좌표를 video viewport 내의 상대 좌표로 변환
                start_view_x = self.roi_start_view_pos.x()
                start_view_y = self.roi_start_view_pos.y()
                end_view_x = end_view_pos.x()
                end_view_y = end_view_pos.y()
                
                # roi_start_view_pos 사용 완료 후 초기화
                self.roi_start_view_pos = None
                
                rel_x1 = (start_view_x - video_viewport_rect.left()) / video_viewport_rect.width()
                rel_y1 = (start_view_y - video_viewport_rect.top()) / video_viewport_rect.height()
                rel_x2 = (end_view_x - video_viewport_rect.left()) / video_viewport_rect.width()
                rel_y2 = (end_view_y - video_viewport_rect.top()) / video_viewport_rect.height()
                
                # 정규화 (0~1 범위로 클램프)
                norm_x = max(0.0, min(1.0, min(rel_x1, rel_x2)))
                norm_y = max(0.0, min(1.0, min(rel_y1, rel_y2)))
                norm_w = max(0.0, min(1.0, abs(rel_x2 - rel_x1)))
                norm_h = max(0.0, min(1.0, abs(rel_y2 - rel_y1)))
                
                # 끝점이 범위를 벗어나면 클램프
                if norm_x + norm_w > 1.0:
                    norm_w = 1.0 - norm_x
                if norm_y + norm_h > 1.0:
                    norm_h = 1.0 - norm_y
                
                norm_rect = (norm_x, norm_y, norm_w, norm_h)
                
                if norm_w > 0.005 and norm_h > 0.005:  # 최소 크기 체크
                    self.roi_normalized_rect = norm_rect
                    self._update_roi_item()
                    self.roiSelectionFinished.emit(norm_rect)
                else:
                    self.roi_rect_item.setVisible(False)
            return

        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.ArrowCursor)
            if not self.is_fit_to_window:
                self.setDragMode(QGraphicsView.ScrollHandDrag)
        super().mouseReleaseEvent(event)

    def show_zoom_label(self):
        self.update_zoom_label()
        self.zoom_label.show()
        QTimer.singleShot(1000, self.hide_zoom_label)

    def hide_zoom_label(self):
         self.zoom_label.hide()

    def update_zoom_label(self):
        zoom_percent = int(self.transform().m11() * 100)
        self.zoom_label.setText(f"Zoom: {zoom_percent}%")
        self.update_zoom_label_position()

    def keyPressEvent(self, event):
        # 모든 키보드 이벤트를 부모 위젯으로 전달
        event.ignore()
