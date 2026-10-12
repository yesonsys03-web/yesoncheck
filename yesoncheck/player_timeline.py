"""Main window implementation for the YesonCheck application."""

import copy
import os
import cv2
from PyQt5.QtCore import (
    QDateTime,
    QEvent,
    QObject,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QTimer,
    Qt,
    pyqtSlot,
    QItemSelectionModel,
)
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QBrush, QWheelEvent
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)
class CollapsibleBox(QWidget):
    """접을 수 있는 그룹박스 위젯"""
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        
        self.toggle_button = QPushButton(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(True)
        self.toggle_button.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 8px;
                background: #2d2d2d;
                border: 1px solid #444;
                color: #ffae00;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #3d3d3d;
            }
            QPushButton:checked {
                background: #3d3d3d;
            }
        """)
        self.toggle_button.clicked.connect(self.toggle)
        
        self.content_area = QWidget()
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(10, 8, 5, 8)
        self.content_layout.setSpacing(8)  # 위젯 간 간격 증가
        self.content_area.setLayout(self.content_layout)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 5)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.content_area)
        
        # 크기 정책 설정
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        
    def toggle(self):
        self.content_area.setVisible(self.toggle_button.isChecked())
        # 버튼 텍스트 업데이트 (▼/▶)
        if self.toggle_button.isChecked():
            text = self.toggle_button.text().replace("▶", "▼")
            if "▼" not in text:
                text = "▼ " + text
        else:
            text = self.toggle_button.text().replace("▼", "▶")
            if "▶" not in text:
                text = "▶ " + text.strip()
        self.toggle_button.setText(text)
        
        # 레이아웃 자동 조정 - 펼칠 때와 접을 때 모두
        self.updateGeometry()
        
        # 부모 위젯들의 레이아웃도 업데이트
        parent = self.parent()
        while parent:
            parent.updateGeometry()
            if parent.layout():
                parent.layout().update()
                parent.layout().activate()
            parent = parent.parent()
        
        # 약간의 지연 후 강제 업데이트 (접을 때 UI 축소)
        QTimer.singleShot(10, self._delayed_update)
    
    def _delayed_update(self):
        """레이아웃 업데이트를 지연 실행하여 UI가 제대로 축소되도록 함"""
        self.updateGeometry()
        if self.parent():
            self.parent().updateGeometry()
            if self.parent().layout():
                self.parent().layout().activate()
    
    def add_widget(self, widget):
        self.content_layout.addWidget(widget)
    
    def add_layout(self, layout):
        self.content_layout.addLayout(layout)


class OCRTimelineWidget(QWidget):
    """DaVinci Resolve-style horizontal timeline showing OCR-detected segments with thumbnails."""

    def __init__(self, total_frames, video_path=None, parent=None, ocr_mode='titmouse'):
        super().__init__(parent)
        self.total_frames = max(1, int(total_frames) if total_frames else 1)
        self.segments = []
        self.video_path = video_path
        self.ocr_mode = ocr_mode  # OCR 모드 저장 (PaddleOCR인지 확인용)
        self.thumbnail_width = 160  # 균일한 썸네일 너비
        self.thumbnail_height = 90  # 균일한 썸네일 높이
        self.thumbnail_spacing = 4  # 썸네일 간 간격
        self.label_height = 30  # 텍스트 라벨 높이 (씬 이름 표시용, 폰트 12px + 여백)
        self.frame_count_height = 25  # 프레임 카운트 높이
        # 전체 높이: 프레임 카운트(25) + 썸네일(90) + 씬 이름(30) + 여백(10)
        self.setMinimumHeight(self.frame_count_height + self.thumbnail_height + self.label_height + 10)
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
        self._thumbnail_cache = {}  # 프레임 번호 -> QPixmap 캐시
        self._thumbnail_widgets = []  # 썸네일 위젯들 저장
        self._parent_dialog = None  # OCRReviewDialog 참조
        self._selected_indices = set()
        self._selected_start_frames = set()
        self._selection_anchor = None
        
        # 레이아웃 설정
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(self.thumbnail_spacing, 5, self.thumbnail_spacing, 5)
        self.main_layout.setSpacing(self.thumbnail_spacing)
        self.main_layout.addStretch()  # 오른쪽 여백

    def set_parent_dialog(self, dialog):
        """OCRReviewDialog 참조 설정"""
        self._parent_dialog = dialog

    def set_video_path(self, video_path):
        """비디오 경로 설정"""
        self.video_path = video_path
        self._thumbnail_cache.clear()
        self._rebuild_thumbnails()

    def set_total_frames(self, total_frames):
        self.total_frames = max(1, int(total_frames) if total_frames else 1)
        self._rebuild_thumbnails()

    def set_segments(self, segments):
        """세그먼트 설정 및 타임라인 업데이트 (성능 최적화: 변경된 부분만 업데이트)"""
        new_segments = segments or []
        
        # 세그먼트가 실제로 변경되었는지 확인 (성능 최적화)
        if self.segments == new_segments:
            return  # 변경사항 없음
        
        # 세그먼트 개수나 시작 프레임이 변경되었는지 빠르게 확인
        if len(self.segments) != len(new_segments):
            # 개수가 다르면 전체 재빌드
            self.segments = new_segments
            self._rebuild_thumbnails()
        else:
            # 개수가 같으면 변경된 부분만 확인
            changed = False
            for i, (old_seg, new_seg) in enumerate(zip(self.segments, new_segments)):
                # 시작 프레임이나 텍스트가 변경되었는지 확인
                if (old_seg.get("start_frame") != new_seg.get("start_frame") or
                    old_seg.get("end_frame") != new_seg.get("end_frame") or
                    old_seg.get("edited_text") != new_seg.get("edited_text") or
                    old_seg.get("text") != new_seg.get("text")):
                    changed = True
                    break
            
            if changed:
                # 변경사항이 있으면 전체 재빌드
                self.segments = new_segments
                self._rebuild_thumbnails()
            else:
                # 변경사항이 없으면 업데이트 스킵
                self.segments = new_segments

    def _rebuild_thumbnails(self):
        """썸네일 위젯들을 다시 생성"""
        # 성능 최적화: 위젯 업데이트 중지 (320개 썸네일 생성 시 매우 느려짐)
        self.setUpdatesEnabled(False)
        
        # 기존 위젯들 제거
        for item in self._thumbnail_widgets:
            widget = item.get("container") if isinstance(item, dict) else item
            if widget:
                self.main_layout.removeWidget(widget)
                widget.deleteLater()
        self._thumbnail_widgets.clear()
        
        if not self.segments:
            self.setMinimumWidth(2000)
            self.setUpdatesEnabled(True)
            return
        
        # 각 세그먼트마다 썸네일 위젯 생성
        total_width = self.thumbnail_spacing * 2  # 양쪽 여백
        for index, segment in enumerate(self.segments):
            container, info = self._create_thumbnail_widget(segment, index)
            self.main_layout.insertWidget(index, container)
            self._thumbnail_widgets.append(info)
            # 실제 썸네일 너비를 사용하여 총 너비 계산
            thumb_width = info.get("thumbnail_width", self.thumbnail_width)
            total_width += thumb_width + self.thumbnail_spacing
        
        # 타임라인 너비 계산
        self.setMinimumWidth(max(2000, total_width))
        self.update()

        # 성능 최적화: 위젯 업데이트 재개 (모든 썸네일 생성 완료 후)
        self.setUpdatesEnabled(True)
        
        # 기존 선택 상태 복원
        if self._selected_start_frames:
            self.highlight_segments_by_frames(self._selected_start_frames)
        elif self._selected_indices:
            self._set_selected_indices(self._selected_indices)

    def get_segment_x_position(self, index):
        """주어진 인덱스의 세그먼트 x 좌표 반환 (오토 스크롤용)"""
        if 0 <= index < len(self._thumbnail_widgets):
            item = self._thumbnail_widgets[index]
            container = item.get("container")
            if container:
                return container.pos().x()
        return None

    def _create_thumbnail_widget(self, segment, index):
        """개별 썸네일 위젯 생성 (테이블과 동일한 기능)"""
        # 썸네일 이미지 생성
        # 성능 최적화: roi_image가 있으면 우선 사용 (비디오에서 추출하지 않음)
        start_frame = int(segment.get("start_frame", 0))
        detections = copy.deepcopy(segment.get("detections") or [])
        
        # 캐시 확인 (성능 최적화)
        if start_frame in self._thumbnail_cache:
            original_pixmap = self._thumbnail_cache[start_frame]
        else:
            original_pixmap = None
            
            # roi_image가 있으면 우선 사용 (OCR 저장 파일 로드 시 이미 있음)
            roi_bytes = segment.get("roi_image") or segment.get("roi_preview")
            if roi_bytes:
                original_pixmap = self._get_thumbnail_pixmap(segment)
                # 캐시에 저장 (성능 최적화)
                if original_pixmap and not original_pixmap.isNull():
                    self._thumbnail_cache[start_frame] = original_pixmap
            else:
                # roi_image가 없을 때만 비디오에서 첫 프레임 추출
                if self.video_path and os.path.exists(self.video_path):
                    try:
                        cap = cv2.VideoCapture(self.video_path)
                        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                        ret, frame = cap.read()
                        cap.release()
                        
                        if ret and frame is not None:
                            height, width, channel = frame.shape
                            bytes_per_line = 3 * width
                            q_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888).rgbSwapped()
                            original_pixmap = QPixmap.fromImage(q_image)
                            
                            # 캐시에 저장 (성능 최적화)
                            if original_pixmap and not original_pixmap.isNull():
                                self._thumbnail_cache[start_frame] = original_pixmap
                    except Exception as e:
                        print(f"[Timeline] 비디오에서 프레임 추출 실패: {e}")
                
                # 비디오에서 추출 실패 시 fallback
                if original_pixmap is None or original_pixmap.isNull():
                    original_pixmap = self._get_thumbnail_pixmap(segment)
        
        # PaddleOCR 분석 시 ROI 종횡비 유지 (테이블 ROI 샘플과 동일하게)
        # OCR 모드 판별 (대소문자 구분 없이, 공백 제거)
        ocr_mode_str = str(self.ocr_mode).lower().strip()
        is_ocr_mode = ocr_mode_str not in ['animatic', 'animatic2']
        
        roi_bytes = segment.get("roi_image") or segment.get("roi_preview")
        has_roi_image = roi_bytes is not None
        
        if not is_ocr_mode:
            # 애니매틱 모드: 기존 크기 사용 (100%)
            thumbnail_width = self.thumbnail_width
            thumbnail_height = self.thumbnail_height
        else:
            # OCR 모드 (King, Titmouse): 60% 축소
            target_height = int(self.thumbnail_height * 0.6)
            
            # ROI 이미지가 있으면 종횡비 유지
            if has_roi_image and original_pixmap and not original_pixmap.isNull():
                orig_width = original_pixmap.width()
                orig_height = original_pixmap.height()
                aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                target_width = int(target_height * aspect_ratio)
            else:
                # ROI 이미지가 없으면 60% 축소 (16:9 비율 유지)
                target_width = int(self.thumbnail_width * 0.6)
            
            thumbnail_width = target_width
            thumbnail_height = target_height
        
        container = QWidget()
        # 프레임 카운트를 위한 블랙 여백 공간 추가 (25px)
        frame_count_height = self.frame_count_height
        # 컨테이너 높이: 프레임 카운트(25) + 썸네일(90) + 씬 이름(25)
        container.setFixedSize(thumbnail_width, frame_count_height + thumbnail_height + self.label_height)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)  # 스페이싱을 0으로 설정하여 씬 이름이 잘리지 않도록
        
        # 썸네일 위젯 (재생 버튼 오버레이용)
        thumb_widget = QWidget()
        thumb_widget.setFixedSize(thumbnail_width, thumbnail_height)
        thumb_layout = QVBoxLayout(thumb_widget)
        thumb_layout.setContentsMargins(0, 0, 0, 0)
        thumb_layout.setSpacing(0)
        
        thumb_label = QLabel()
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setFixedSize(thumbnail_width, thumbnail_height)
        
        if original_pixmap:
            pixmap = original_pixmap.scaled(
                thumbnail_width,
                thumbnail_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            thumb_label.setPixmap(pixmap)
            thumb_label.setProperty('original_pixmap', original_pixmap)
        else:
            thumb_label.setText("No Image")
        
        # 툴팁 설정
        detection_lines = []
        if detections:
            for det in detections:
                if isinstance(det, dict) and det.get("text"):
                    detection_lines.append(det["text"])
        tooltip_text = "\n".join(detection_lines) if detection_lines else ""
        thumb_label.setToolTip(tooltip_text)
        
        # 썸네일 클릭 이벤트 (프리뷰 & 하이라이트)
        def on_thumbnail_clicked(event):
            if event.button() == Qt.LeftButton and self._parent_dialog:
                # QApplication.keyboardModifiers()를 사용하여 현재 키보드 상태 확인
                from PyQt5.QtWidgets import QApplication
                modifiers = QApplication.keyboardModifiers()

                # macOS에서 모든 modifier 상태 확인
                is_shift = bool(modifiers & Qt.ShiftModifier)
                is_ctrl = bool(modifiers & Qt.ControlModifier)
                is_alt = bool(modifiers & Qt.AltModifier)
                is_meta = bool(modifiers & Qt.MetaModifier)

                # 성능 최적화: 로그 출력 제거
                # print(f"[Timeline] 썸네일 클릭: index={index}, modifiers={int(modifiers)}, Shift={is_shift}, Ctrl={is_ctrl}, Alt={is_alt}, Meta={is_meta}")

                # macOS에서는 Command+클릭도 다중 선택으로 처리 (macOS 표준)
                is_alt_click = is_alt or is_meta or is_ctrl
                is_shift_click = is_shift

                # 선택 처리 (Alt/Shift 클릭은 다중 선택, 일반 클릭은 단일 선택)
                self._handle_selection_click(index, modifiers)
                
                # Alt + 클릭 시에는 테이블 선택 동기화만 하고 프리뷰는 업데이트하지 않음
                # (기존 선택 유지)
                if is_alt_click:
                    # _handle_selection_click에서 이미 _sync_table_selection_with_timeline() 호출됨
                    # 프리뷰는 업데이트하지 않음 (기존 선택 유지)
                    return
                
                # 일반 클릭 또는 Shift + 클릭 시에는 프리뷰 업데이트
                start_frame = int(segment.get("start_frame", 0))
                end_frame = int(segment.get("end_frame", start_frame))
                
                # 테이블 row 찾기 (인덱스와 동일)
                # O(N) 검색 제거하여 성능 최적화
                table_row = index
                
                if table_row is not None:
                    # Shift + 클릭이 아닐 때만 단일 행 선택 (Shift는 범위 선택이므로 동기화만)
                    if not is_shift_click:
                        # _handle_selection_click에서 이미 동기화했지만, 
                        # 단일 선택일 때는 명시적으로 selectRow 호출
                        if len(self._selected_indices) == 1:
                            self._parent_dialog.table.selectRow(table_row)
                    # 클릭 이벤트는 즉시 반응 (immediate=True) -> False로 변경하여 UI 반응성 향상
                    # 선택 하이라이트가 먼저 그려지고, 프리뷰 로딩은 약간 지연됨
                    self._parent_dialog.update_preview(table_row, immediate=False)
                elif hasattr(self._parent_dialog, '_play_preview_segment'):
                    self._parent_dialog._play_preview_segment(start_frame, end_frame, None)
        
        thumb_label.mousePressEvent = on_thumbnail_clicked
        thumb_label.setCursor(Qt.PointingHandCursor)  # 클릭 가능한 커서로 변경
        
        thumb_layout.addWidget(thumb_label)
        
        # 프레임 카운트 라벨 생성 (블랙 여백에 표시)
        start_frame = int(segment.get("start_frame", 0))
        end_frame = int(segment.get("end_frame", start_frame))
        frame_count = end_frame - start_frame + 1
        
        # 블랙 여백 영역 위젯 생성
        frame_count_area = QWidget()
        frame_count_area.setFixedHeight(frame_count_height)
        frame_count_area.setStyleSheet("QWidget { background: #000000; }")
        frame_count_area_layout = QVBoxLayout(frame_count_area)
        frame_count_area_layout.setContentsMargins(0, 0, 0, 0)
        frame_count_area_layout.setAlignment(Qt.AlignCenter)
        
        frame_count_label = QLabel(str(frame_count))
        frame_count_label.setAlignment(Qt.AlignCenter)
        frame_count_label.setStyleSheet("""
            QLabel {
                background: rgba(255, 20, 147, 255);
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
                padding: 2px 6px;
            }
        """)
        frame_count_label.setFixedSize(35, 20)
        frame_count_area_layout.addWidget(frame_count_label)
        
        # 블랙 여백 영역을 컨테이너 레이아웃의 맨 위에 추가
        container_layout.addWidget(frame_count_area)
        
        container_layout.addWidget(thumb_widget)
        
        # 텍스트 라벨 (씬 이름)
        label = segment.get("edited_text") or segment.get("text") or f"Scene {index + 1}"
        if label == "<미검출>":
            label = ""

        text_label = QLabel(label)
        text_label.setAlignment(Qt.AlignCenter)  # 수직 중앙 정렬
        # HTML 타임라인과 동일한 스타일: 흰색 텍스트, 약간의 패딩, 반투명 배경
        text_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                background: rgba(0, 0, 0, 180);
                font-size: 12px;
                font-weight: bold;
                padding: 4px 6px;
                border-radius: 3px;
            }
        """)
        text_label.setFixedHeight(self.label_height)
        text_label.setWordWrap(False)
        text_label.setContentsMargins(0, 0, 0, 0)

        # 텍스트가 너무 길면 잘라내기
        font_metrics = text_label.fontMetrics()
        elided_text = font_metrics.elidedText(label, Qt.ElideRight, thumbnail_width - 8)
        text_label.setText(elided_text)
        
        container_layout.addWidget(text_label)
        
        # 생성된 위젯 정보 저장
        segment_start_frame = int(segment.get("start_frame", 0))
        thumb_info = {
            "container": container,
            "thumb_label": thumb_label,
            "text_label": text_label,
            "frame_count_label": frame_count_label,
            "index": index,
            "start_frame": segment_start_frame,
            "thumbnail_width": thumbnail_width,  # 실제 썸네일 너비 저장
        }
        self._apply_label_style(thumb_label, index in self._selected_indices, container, text_label)

        return container, thumb_info

    def _apply_label_style(self, label, selected, container=None, text_label=None):
        border_color = "#ffae00" if selected else "#222222"
        border_width = 2 if selected else 1  # 선택 시 2px 테두리
        background = "#444444" if selected else "#050505"  # 선택 시 훨씬 더 밝은 배경
        text_color = "#ffff00" if selected else "#dddddd"  # 선택 시 노란색
        padding = 2 if selected else 0  # 선택 시 패딩 추가하여 테두리가 보이도록 (2px로 조정)

        # 썸네일 라벨 스타일 (padding 추가)
        label_stylesheet = (
            f"QLabel {{ "
            f"background: {background}; "
            f"border: {border_width}px solid {border_color}; "
            f"color: {text_color}; "
            f"border-radius: 6px; "
            f"padding: {padding}px; "  # 패딩으로 이미지와 테두리 사이 공간 확보
            f"}}"
        )
        label.setStyleSheet(label_stylesheet)

        # Container 위젯에도 배경색과 외곽선 적용
        if container:
            container_bg = "#555555" if selected else "transparent"
            container_border = f"{border_width}px solid {border_color}" if selected else "none"
            container_border_radius = "8px"
            # 선택 시 마진 추가하여 테두리가 명확히 보이도록 (1px로 조정)
            container_margin = 1 if selected else 0

            container.setStyleSheet(
                f"QWidget {{ "
                f"background: {container_bg}; "
                f"border: {container_border}; "
                f"border-radius: {container_border_radius}; "
                f"margin: {container_margin}px; "
                f"}}"
            )

            # 레이아웃 마진도 업데이트
            layout = container.layout()
            if layout:
                margin = 1 if selected else 0
                layout.setContentsMargins(margin, margin, margin, margin)

            container.update()
            container.repaint()

        # 텍스트 라벨 스타일 (씬 이름) - HTML 타임라인과 동일한 스타일 유지
        if text_label:
            # 선택 여부에 관계없이 일관된 스타일 유지
            text_label_color = "#ffff00" if selected else "#ffffff"
            text_label.setStyleSheet(f"""
                QLabel {{
                    color: {text_label_color};
                    background: rgba(0, 0, 0, 180);
                    font-size: 12px;
                    font-weight: bold;
                    padding: 4px 6px;
                    border-radius: 3px;
                }}
            """)
            text_label.setContentsMargins(0, 0, 0, 0)
            text_label.update()
            text_label.repaint()

        # 여러 방법으로 강제 업데이트
        label.update()
        label.repaint()

        # 성능 최적화: 로그 출력 제거 (326개 썸네일마다 출력하면 매우 느려짐)
        # print(f"[Timeline] _apply_label_style 적용: selected={selected}, border={border_width}px {border_color}, bg={background}, padding={padding}px, container_border={'yes' if selected and container else 'no'}")

    def _set_selected_index(self, index):
        self._selected_segment_index = index
        self._selected_start_frame = None
        self._selected_indices = set() if index is None else {index}
        self._selection_anchor = index
        self._update_selected_start_frames()
        self._update_selection_styles()

    def _update_selected_start_frames(self):
        self._selected_start_frames = {
            item.get("start_frame")
            for item in self._thumbnail_widgets
            if item.get("index") in self._selected_indices
        }

    def _update_selection_styles(self):
        # 성능 최적화: 로그 출력 제거 (326개 썸네일마다 출력하면 매우 느려짐)
        # print(f"[Timeline] _update_selection_styles 시작: 선택된 인덱스 = {sorted(self._selected_indices)}, 썸네일 수 = {len(self._thumbnail_widgets)}")
        updated_count = 0
        
        # 전체 업데이트 대신 변경된 항목만 업데이트
        # 하지만 현재 구조상 전체 순회가 불가피할 수 있음 (이전 선택 상태를 모르므로)
        # -> thumb_info에 'selected' 상태를 저장하여 최적화
        
        for item in self._thumbnail_widgets:
            label = item.get("thumb_label")
            if label is None:
                # print(f"[Timeline] 경고: 인덱스 {item.get('index')}의 thumb_label이 None")
                continue
            
            index = item.get("index")
            is_selected = index in self._selected_indices
            
            # 이전 상태와 같으면 건너뜀 (성능 최적화 핵심)
            if item.get("selected") == is_selected:
                continue
                
            # 상태 업데이트 및 저장
            item["selected"] = is_selected
            
            container = item.get("container")
            text_label = item.get("text_label")
            self._apply_label_style(label, is_selected, container, text_label)
            updated_count += 1
            
        # 타임라인 전체 업데이트하여 시각적 변경사항 즉시 반영
        # 변경된 항목이 있을 때만 update 호출
        if updated_count > 0:
            self.update()
            self.repaint()
        # print(f"[Timeline] _update_selection_styles 완료: {updated_count}개 썸네일 스타일 업데이트")

    def _set_selected_indices(self, indices, anchor=None):
        old_indices = self._selected_indices.copy() if hasattr(self, '_selected_indices') else set()
        self._selected_indices = set(idx for idx in indices if idx is not None)
        if anchor is not None:
            self._selection_anchor = anchor
        elif self._selected_indices:
            self._selection_anchor = min(self._selected_indices)
        else:
            self._selection_anchor = None
        # 성능 최적화: 로그 출력 제거
        # print(f"[Timeline] _set_selected_indices: {sorted(old_indices)} -> {sorted(self._selected_indices)}, anchor={self._selection_anchor}")
        self._update_selected_start_frames()
        self._update_selection_styles()

    def _handle_selection_click(self, index, modifiers):
        # macOS에서 모든 modifier 확인
        is_shift = bool(modifiers & Qt.ShiftModifier)
        is_ctrl = bool(modifiers & Qt.ControlModifier)
        is_alt = bool(modifiers & Qt.AltModifier)
        is_meta = bool(modifiers & Qt.MetaModifier)

        # macOS에서는 Command(Meta) 또는 Ctrl도 다중 선택으로 처리
        is_multi_select = is_alt or is_meta or is_ctrl

        # 성능 최적화: 로그 출력 제거
        # print(f"[Timeline] _handle_selection_click: index={index}, Shift={is_shift}, Ctrl={is_ctrl}, Alt={is_alt}, Meta={is_meta}, multi_select={is_multi_select}")

        if is_shift and self._selection_anchor is not None:
            anchor = self._selection_anchor if self._selection_anchor is not None else index
            start = min(anchor, index)
            end = max(anchor, index)
            new_indices = set(range(start, end + 1))
            # print(f"[Timeline] Shift+클릭: 범위 선택 {start}~{end}")
            self._set_selected_indices(new_indices, anchor=anchor)
        elif is_multi_select:
            new_indices = set(self._selected_indices)
            if index in new_indices:
                new_indices.remove(index)
                # print(f"[Timeline] 다중 선택 클릭: 인덱스 {index} 제거")
            else:
                new_indices.add(index)
                # print(f"[Timeline] 다중 선택 클릭: 인덱스 {index} 추가")
            anchor = self._selection_anchor
            if anchor is None or anchor not in new_indices:
                anchor = index if index in new_indices else (min(new_indices) if new_indices else None)
            self._set_selected_indices(new_indices, anchor=anchor)
        else:
            # print(f"[Timeline] 일반 클릭: 인덱스 {index}")
            self._set_selected_indices({index}, anchor=index)
        # print(f"[Timeline] 선택 처리 완료, 테이블 동기화 시작")
        self._sync_table_selection_with_timeline()

    def _sync_table_selection_with_timeline(self):
        if not self._parent_dialog or not hasattr(self._parent_dialog, 'table'):
            # 성능 최적화: 로그 출력 제거
            # print("[Timeline] _sync_table_selection_with_timeline: parent_dialog 또는 table 없음")
            return
        selection_model = self._parent_dialog.table.selectionModel()
        if selection_model is None:
            # print("[Timeline] _sync_table_selection_with_timeline: selection_model 없음")
            return

        # 성능 최적화: 로그 출력 제거
        # print(f"[Timeline] _sync_table_selection_with_timeline: 선택된 인덱스 = {sorted(self._selected_indices)}")

        # 순환 동기화 방지: 플래그 설정 + 시그널 연결 해제
        self._parent_dialog._timeline_updating = True

        # selectionChanged 시그널 임시 연결 해제
        try:
            selection_model.selectionChanged.disconnect(self._parent_dialog.on_selection_changed)
            signal_disconnected = True
            # print("[Timeline] selectionChanged 시그널 연결 해제 성공")
        except:
            signal_disconnected = False
            # print("[Timeline] selectionChanged 시그널 연결 해제 실패 (이미 연결되지 않음)")

        try:
            # QItemSelection 사용하여 한 번에 모든 행 선택
            from PyQt5.QtCore import QItemSelection
            selection = QItemSelection()
            model = self._parent_dialog.table.model()
            column_count = model.columnCount()
            selected_rows = []

            for idx in sorted(self._selected_indices):
                if idx < 0 or idx >= len(self.segments):
                    # print(f"[Timeline] 인덱스 {idx} 범위 초과 (세그먼트 수: {len(self.segments)})")
                    continue
                
                # 테이블 행 인덱스는 세그먼트 인덱스와 동일 (1:1 매핑)
                # O(N) 검색 제거하여 성능 최적화
                row = idx
                
                # print(f"[Timeline] 인덱스 {idx} -> 테이블 row {row} 선택")
                selected_rows.append(row)

                # QItemSelection에 행 전체 범위 추가
                top_left = model.index(row, 0)
                bottom_right = model.index(row, column_count - 1)
                selection.select(top_left, bottom_right)

            # 한 번에 모든 선택 적용 (ClearAndSelect로 이전 선택 지우고 새로운 선택 적용)
            selection_model.select(selection, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
            # print(f"[Timeline] 테이블에 선택된 행: {selected_rows}")
        finally:
            # 시그널 다시 연결
            if signal_disconnected:
                selection_model.selectionChanged.connect(self._parent_dialog.on_selection_changed)
                # print("[Timeline] selectionChanged 시그널 다시 연결")

            # 플래그 즉시 해제
            self._parent_dialog._timeline_updating = False

    def highlight_segment_by_frame(self, start_frame):
        if start_frame is None:
            self._set_selected_indices(set())
            return
        self.highlight_segments_by_frames([start_frame])

    def highlight_segments_by_indices(self, indices):
        """인덱스 리스트로 세그먼트 하이라이트 (O(1) 업데이트용)"""
        if indices is None:
            self._set_selected_indices(set())
            return
        
        new_indices = set(indices)
        # 현재 선택과 새 선택이 같으면 업데이트하지 않음 (불필요한 재랜더링 방지)
        if new_indices == self._selected_indices:
            return
            
        self._set_selected_indices(new_indices)

    def highlight_segments_by_frames(self, start_frames):
        # 성능 최적화: 로그 출력 제거
        # print(f"[Timeline] highlight_segments_by_frames 호출: start_frames={start_frames}")
        if start_frames is None:
            # print("[Timeline] start_frames가 None이므로 선택 해제")
            self._set_selected_indices(set())
            return
        frame_set = set(start_frames)
        indices = {
            item.get("index")
            for item in self._thumbnail_widgets
            if item.get("start_frame") in frame_set
        }
        # print(f"[Timeline] 프레임 {sorted(frame_set)} -> 인덱스 {sorted(indices)}")
        # 현재 선택과 새 선택이 같으면 업데이트하지 않음 (불필요한 재랜더링 방지)
        if indices == self._selected_indices:
            # print(f"[Timeline] 선택 상태 동일하므로 업데이트 건너뜀")
            return
        # print(f"[Timeline] 선택 상태 업데이트: {sorted(self._selected_indices)} -> {sorted(indices)}")
        self._set_selected_indices(indices)

    def _get_thumbnail_pixmap(self, segment):
        """세그먼트의 썸네일 이미지를 가져옴 (간단한 버전)"""
        start_frame = int(segment.get("start_frame", 0))
        
        # 캐시 확인
        if start_frame in self._thumbnail_cache:
            return self._thumbnail_cache[start_frame]
        
        # roi_image 또는 roi_preview에서 가져오기
        roi_bytes = segment.get("roi_image") or segment.get("roi_preview")
        pixmap = None
        
        if roi_bytes:
            try:
                import numpy as np
                nparr = np.frombuffer(roi_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is not None:
                    height, width, channel = img.shape
                    bytes_per_line = 3 * width
                    q_image = QImage(img.data, width, height, bytes_per_line, QImage.Format_RGB888).rgbSwapped()
                    pixmap = QPixmap.fromImage(q_image)
            except Exception as e:
                print(f"[Timeline] 썸네일 로드 실패: {e}")
        
        # 비디오에서 프레임 추출 (roi_image가 없을 때)
        if pixmap is None and self.video_path and os.path.exists(self.video_path):
            try:
                cap = cv2.VideoCapture(self.video_path)
                cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                ret, frame = cap.read()
                cap.release()
                
                if ret and frame is not None:
                    height, width, channel = frame.shape
                    bytes_per_line = 3 * width
                    q_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888).rgbSwapped()
                    pixmap = QPixmap.fromImage(q_image)
            except Exception as e:
                print(f"[Timeline] 비디오에서 프레임 추출 실패: {e}")
        
        if pixmap and not pixmap.isNull():
            self._thumbnail_cache[start_frame] = pixmap
            return pixmap
        
        return None

    def wheelEvent(self, event: QWheelEvent):
        """타임라인에서 마우스 휠을 좌우 스크롤로 변경"""
        # 부모 위젯(ScrollArea) 찾기
        parent = self.parent()
        while parent:
            if isinstance(parent, QScrollArea):
                # 수평 스크롤바 가져오기
                scroll_bar = parent.horizontalScrollBar()
                if scroll_bar:
                    # 휠 델타를 스크롤 값으로 변환
                    delta = event.angleDelta().y()
                    # 스크롤 방향: 위로 스크롤하면 왼쪽으로, 아래로 스크롤하면 오른쪽으로
                    scroll_bar.setValue(scroll_bar.value() - delta)
                    event.accept()
                    return
            parent = parent.parent()
        
        # ScrollArea를 찾지 못한 경우 기본 동작 (상하 스크롤)
        super().wheelEvent(event)
    
    def contextMenuEvent(self, event):
        """타임라인 우클릭 메뉴 표시"""
        if self._parent_dialog:
            self._parent_dialog._show_timeline_context_menu(event.pos())
        else:
            super().contextMenuEvent(event)
