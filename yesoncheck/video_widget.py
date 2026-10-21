"""Video display widget with zoom, pan, and drag support."""

import math
import os

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QBrush,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
    QWheelEvent,
)

from PyQt5.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QLabel,
    QMessageBox,
)

from yesoncheck import paths

class CustomVideoWidget(QGraphicsView):
    wipePositionChanged = pyqtSignal()
    fitToWindowChanged = pyqtSignal(bool)
    roiSelectionFinished = pyqtSignal(tuple)  # (x, y, w, h) normalized to current frame
    annotationShapeFinished = pyqtSignal(dict)
    annotationTextRequested = pyqtSignal(float, float)
    annotationMovePressed = pyqtSignal(float, float)
    annotationMoveDragged = pyqtSignal(float, float)
    annotationMoveReleased = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.video_item = self.scene.addPixmap(QPixmap())

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

        self.zoom_label = QLabel(self)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setStyleSheet("background-color: rgba(255, 255, 255, 128); padding: 5px; border-radius: 3px;")
        self.zoom_label.hide()

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_zoom_label_position()
        if self.is_fit_to_window:
            self.fitInView(self.video_item, Qt.KeepAspectRatio)

    def update_zoom_label_position(self):
        self.zoom_label.move(10, 10)

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
            
            # URL들을 파일/폴더로 분류
            for url in urls:
                local_path = paths.normalize_native(url.toLocalFile())
                if os.path.isfile(local_path):
                    # 파일인 경우
                    if parent.is_video_file(local_path):
                        video_files.append(local_path)
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
                elif not read_failed:
                    QMessageBox.warning(parent, "경고", "폴더에 지원되는 비디오 파일이 없습니다.")
            else:
                # 개별 파일들만 있는 경우
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
        
        event.acceptProposedAction()

    def updateFrame(self, frame_a, frame_b):
        if frame_a is None:
            self.video_item.setPixmap(QPixmap())
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

        pixmap = QPixmap.fromImage(q_img)
        self.video_item.setPixmap(pixmap)

        scene_rect_changed = self.scene.sceneRect() != self.video_item.boundingRect()
        if self.initial_fit or scene_rect_changed:
            self.scene.setSceneRect(self.video_item.boundingRect())
            self.fit_to_window()
            self.initial_fit = False
        
        self.updateWipeLine()
        self._update_roi_item()
        self._update_edit_handle_items()

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
        else:
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
        """Legacy hook; annotations are burned onto frames at playback time."""
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
            if tool in ("line", "arrow"):
                return
            self.annotationTextRequested.emit(start_norm[0], start_norm[1])
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
