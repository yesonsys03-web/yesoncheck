"""Main window implementation for the YesonCheck application."""

import copy
import os
import re
import sys
import cv2
from yesoncheck import external_tools, web_info
from PyQt5.QtCore import (
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
    QUrl,
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import QBrush, QColor, QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QWheelEvent, QCursor
from PyQt5.QtWebSockets import QWebSocketServer, QWebSocket
from PyQt5.QtNetwork import QHostAddress
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QShortcut,
    QSizePolicy,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
)
from yesoncheck.player_timeline import OCRTimelineWidget
from yesoncheck.slider_style import jump_to_click
class OCRReviewDialog(QDialog):
    """Dialog for reviewing and editing OCR-detected segments before export."""
    
    def _sort_segments(self, segments):
        """프레임 순서대로 세그먼트 정렬 (원래 동영상 순서)"""
        def sort_key(seg):
            start_frame = seg.get('start_frame', 0)
            # edited_text가 있으면 사용, 없으면 text 사용
            text = seg.get('edited_text', seg.get('text', '')).strip()
            
            # 텍스트를 정규화하여 정렬
            normalized_text = text.replace(' ', '_').replace('-', '_').upper()
            # 자연 정렬을 위한 키 생성: 숫자는 정수로 변환하여 비교
            def natural_key(norm_text):
                return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', norm_text)]
            
            # 프레임 순서 우선, 같은 프레임이면 텍스트로 정렬
            return (start_frame, natural_key(normalized_text), text)
        
        return sorted(segments, key=sort_key)

    def __init__(self, parent, segments, fps, total_frames, ocr_mode='titmouse'):
        super().__init__(parent)
        self.setWindowTitle("OCR 분석 결과 검토")
        self.setWindowModality(Qt.NonModal)  # Non-modal로 설정하여 메인 플레이어 제어 허용
        self.resize(1400, 1000)  # 크기 확대
        self.fps = fps or 24.0
        self.total_frames = max(1, int(total_frames) if total_frames else 1)
        self._updating = False
        self._timeline_updating = False  # 타임라인-테이블 순환 동기화 방지 플래그
        self._result_segments = None
        self._include_audio = True  # 기본값: 사운드 포함
        
        # OCR 모드 저장 (애니매틱인지 확인용)
        self.ocr_mode = ocr_mode
        
        # 비디오 경로 저장 (썸네일 생성용)
        # 사이드바에서 선택한 동영상이 있으면 그것을, 없으면 Video A를 사용
        if parent:
            pass
            # get_current_video_path 메서드가 있으면 사용 (사이드바 지원)
            if hasattr(parent, 'get_current_video_path'):
                self.video_path = parent.get_current_video_path()
            else:
                self.video_path = getattr(parent, 'filename_a', None)
        else:
            self.video_path = None

        # 비디오 파일 존재 여부 확인 및 로그
        if self.video_path:
            if os.path.exists(self.video_path):
                pass
                # print(f"[OCR Review] 비디오 파일 확인: {self.video_path}")
                pass
            else:
                pass
                # print(f"[OCR Review] 경고: 비디오 파일을 찾을 수 없음: {self.video_path}")
                # print(f"[OCR Review] 썸네일을 비디오에서 추출할 수 없습니다.")
                pass
        else:
            pass
            # print(f"[OCR Review] 경고: 비디오 경로가 설정되지 않았습니다.")
            pass
        
        # 미리보기 업데이트 debounce를 위한 타이머
        self._preview_update_timer = QTimer(self)
        self._preview_update_timer.setSingleShot(True)
        self._preview_update_timer.timeout.connect(self._do_update_preview)
        self._pending_preview_row = None
        
        # WebSocket 브로드캐스트 debounce를 위한 타이머 (편집 시 과도한 전송 방지)
        self._broadcast_timer = QTimer(self)
        self._broadcast_timer.setSingleShot(True)
        self._broadcast_timer.timeout.connect(self.broadcast_segments_change)
        
        # 이미지 캐시 (스케일링된 이미지 저장)
        self._preview_cache = {}
        # 프레임 추출 캐시 (비디오에서 추출한 원본 프레임 bytes)
        self._preview_frame_cache = {}
        
        # 프리뷰 비디오 재생 관련 변수
        self._preview_video_cap = None
        self._preview_play_timer = QTimer(self)
        self._preview_play_timer.timeout.connect(self._update_preview_video_frame)
        self._preview_playing = False
        self._preview_current_frame = 0
        self._preview_start_frame = 0
        self._preview_end_frame = 0
        self._preview_playing_row = None  # 현재 재생 중인 row 저장
        self._preview_current_display_frame = 0  # 현재 표시 중인 프레임 (프레임 단위 이동용)
        self._preview_current_segment_start = 0  # 현재 선택된 씬의 시작 프레임
        self._preview_current_segment_end = 0  # 현재 선택된 씬의 종료 프레임
        self._slider_dragging = False  # 슬라이더 드래그 중 플래그
        self._preview_sync_counter = 0  # 오디오 싱크 체크 카운터 (메인 플레이어와 동일)

        # 프리뷰 오디오 재생을 위한 QMediaPlayer
        self._preview_media_player = QMediaPlayer(self)
        self._preview_media_player.setVolume(50)  # 기본 볼륨 50%
        
        # Undo/Redo 히스토리 스택
        self.undo_stack = []  # 이전 상태 저장
        self.redo_stack = []  # redo를 위한 스택
        self.max_history = 50  # 최대 히스토리 개수

        # 오디오 싱크를 위한 총 프레임 수 저장
        self._total_video_frames = total_frames
        
        # 초기 segments 정렬 (프레임 순서)
        segments = self._sort_segments(segments)

        layout = QVBoxLayout(self)

        # 상단 안내 문구
        instruction_label = QLabel(
            "검출된 구간을 검토하여 필요하면 텍스트와 시작/종료 프레임을 수정하세요. "
            "내보내기를 누르면 해당 범위로 클립이 생성됩니다."
        )
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)

        # 메인 레이아웃: 왼쪽(3단) + 오른쪽(프리뷰 영상)
        main_horizontal_layout = QHBoxLayout()
        
        # 왼쪽 영역: 3단 구조
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 왼쪽 1단: 씬 리스트
        scene_list_label = QLabel("씬 리스트")
        scene_list_label.setStyleSheet("QLabel { color: #ffae00; font-weight: bold; padding: 4px; }")
        left_layout.addWidget(scene_list_label)
        
        self.sceneListWidget = QListWidget()
        self.sceneListWidget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.sceneListWidget.itemClicked.connect(self.on_scene_list_item_clicked)
        self.sceneListWidget.setStyleSheet("""
            QListWidget {
                background: #000000;
                color: #f0f0f0;
                border: 1px solid #222;
            }
            QListWidget::item {
                padding: 4px;
                border-bottom: 1px solid #111;
            }
            QListWidget::item:selected {
                background: #333333;
                color: #ffea9f;
            }
        """)
        left_layout.addWidget(self.sceneListWidget)
        
        # 왼쪽 2단: 선택된 씬 상세 정보
        scene_detail_label = QLabel("선택된 씬 상세 정보")
        scene_detail_label.setStyleSheet("QLabel { color: #ffae00; font-weight: bold; padding: 4px; }")
        left_layout.addWidget(scene_detail_label)
        
        self.previewText = QPlainTextEdit()
        self.previewText.setReadOnly(True)
        self.previewText.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.previewText.setStyleSheet("QPlainTextEdit { color: #ffae00; background: #000000; padding: 8px; border: 1px solid #222; }")
        left_layout.addWidget(self.previewText)
        
        # 로그 영역 (요약, 시퀀스) - populate_table에서 사용되므로 먼저 생성
        log_content_widget = QWidget()
        log_content_layout = QVBoxLayout(log_content_widget)
        log_content_layout.setContentsMargins(0, 0, 0, 0)
        
        # 요약 레이블
        self.summaryLabel = QLabel()
        self.summaryLabel.setStyleSheet("QLabel { color: #ffd27f; background: #000000; padding: 6px; }")
        log_content_layout.addWidget(self.summaryLabel)
        
        # 시퀀스 편집
        self.sequenceEdit = QPlainTextEdit()
        self.sequenceEdit.setReadOnly(True)
        self.sequenceEdit.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.sequenceEdit.setStyleSheet(
            "QPlainTextEdit { background: #050505; color: #f0f0f0; border: 1px solid #222; font-family: 'Roboto Mono', 'Menlo', Consolas, monospace; }"
        )
        log_content_layout.addWidget(self.sequenceEdit)
        
        # 왼쪽 영역을 QSplitter로 크기 조정 가능하게
        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(self.sceneListWidget)
        left_splitter.addWidget(self.previewText)
        left_splitter.addWidget(log_content_widget)
        left_splitter.setStretchFactor(0, 2)  # 씬 리스트: 2배
        left_splitter.setStretchFactor(1, 1)  # 상세 정보: 1배
        left_splitter.setStretchFactor(2, 1)  # 로그: 1배
        left_splitter.setSizes([400, 200, 200])  # 초기 크기
        
        # 왼쪽 영역을 감싸는 위젯
        left_container = QWidget()
        left_container_layout = QVBoxLayout(left_container)
        left_container_layout.setContentsMargins(0, 0, 0, 0)
        left_container_layout.addWidget(scene_list_label)
        left_container_layout.addWidget(left_splitter)
        
        # 로그 레이블을 왼쪽 컨테이너에 추가 (left_splitter 아래, 로그 위)
        log_label = QLabel("로그")
        log_label.setStyleSheet("QLabel { color: #ffae00; font-weight: bold; padding: 4px; }")
        left_container_layout.addWidget(log_label)
        
        # 오른쪽 영역: 프리뷰 영상
        right_widget = QWidget()
        right_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        preview_label_title = QLabel("프리뷰 영상")
        preview_label_title.setMaximumHeight(30)  # 타이틀 높이 제한
        preview_label_title.setStyleSheet("QLabel { color: #ffae00; font-weight: bold; padding: 4px; }")
        right_layout.addWidget(preview_label_title, 0)  # stretch: 0 (고정 높이)
        
        # 프리뷰 영상 컨테이너 (오버레이를 위한 QWidget)
        preview_container = QWidget()
        preview_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview_container_layout = QVBoxLayout(preview_container)
        preview_container_layout.setContentsMargins(0, 0, 0, 0)
        preview_container_layout.setSpacing(0)
        
        # 프리뷰 영상 레이블 (오버레이를 위한 부모 위젯)
        preview_widget = QWidget()
        preview_widget.setMinimumSize(400, 300)
        preview_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview_widget.setStyleSheet("QWidget { background: #050505; border: 2px solid #ff00ff; }")
        preview_widget_layout = QVBoxLayout(preview_widget)
        preview_widget_layout.setContentsMargins(0, 0, 0, 0)
        preview_widget_layout.setSpacing(0)

        self.previewLabel = QLabel("프리뷰 영상")
        self.previewLabel.setAlignment(Qt.AlignCenter)
        self.previewLabel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.previewLabel.setStyleSheet("QLabel { background: transparent; color: #555; }")
        preview_widget_layout.addWidget(self.previewLabel)
        
        # 프리뷰 영상 휠 이벤트 핸들러 추가
        def preview_wheel_event(event: QWheelEvent):
            """프리뷰 영상에서 휠로 프레임 이동"""
            if not hasattr(self, '_preview_current_display_frame'):
                event.ignore()
                return
            
            # 현재 세그먼트 정보 확인
            if not hasattr(self, '_preview_current_segment_start') or not hasattr(self, '_preview_current_segment_end'):
                event.ignore()
                return
            
            start_frame = self._preview_current_segment_start
            end_frame = self._preview_current_segment_end
            
            if start_frame is None or end_frame is None:
                event.ignore()
                return
            
            delta = event.angleDelta().y()
            frame_step = 1
            
            current_frame = self._preview_current_display_frame
            
            if delta < 0:  # 휠 다운 (이전 프레임)
                target_frame = max(start_frame, current_frame - frame_step)
            else:  # 휠 업 (다음 프레임)
                target_frame = min(end_frame, current_frame + frame_step)
            
            # 프레임 이동 및 이미지 업데이트
            self._preview_current_display_frame = target_frame
            self._update_preview_frame(target_frame)
            self._update_frame_display()
            
            event.accept()
        
        self.previewLabel.wheelEvent = preview_wheel_event

        # 프리뷰 위젯 참조 저장 (크기 계산에 사용)
        self.preview_widget = preview_widget
        
        # 프리뷰 위젯이 최대한 공간을 차지하도록 stretch 설정
        preview_container_layout.addWidget(preview_widget, 1)  # stretch factor: 1 (최대한 확장)
        
        # 프레임 번호 오버레이 (우하단에 표시) - preview_container의 자식으로 생성하여 항상 위에 표시
        self.frame_overlay = QLabel("Frame: 0", preview_container)
        self.frame_overlay.setAlignment(Qt.AlignBottom | Qt.AlignRight)
        self.frame_overlay.setStyleSheet("""
            QLabel {
                background: rgba(255, 174, 0, 220);
                color: #000000;
                font-size: 18px;
                font-weight: bold;
                padding: 10px 15px;
                border: 2px solid #ffae00;
                border-radius: 4px;
            }
        """)
        # 오버레이가 항상 위에 표시되도록 설정
        self.frame_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # 마우스 이벤트 통과
        self.frame_overlay.setAttribute(Qt.WA_ShowWithoutActivating, True)  # 활성화 없이 표시
        self.frame_overlay.adjustSize()  # 크기 자동 조정
        self.frame_overlay.raise_()  # 위로 올리기
        self.frame_overlay.show()
        
        # 오버레이 위치를 우하단으로 설정 (위젯 크기가 결정된 후)
        def setup_overlay():
            if hasattr(self, 'frame_overlay') and hasattr(self, 'preview_widget'):
                pass
                # preview_widget의 크기와 위치를 고려하여 우하단 위치 계산
                preview_size = self.preview_widget.size()
                preview_pos = self.preview_widget.pos()  # preview_container 기준 위치
                overlay_size = self.frame_overlay.size()
                # 우하단 위치: preview_widget의 우하단 기준으로 계산
                x = preview_pos.x() + preview_size.width() - overlay_size.width() - 10
                y = preview_pos.y() + preview_size.height() - overlay_size.height() - 10
                self.frame_overlay.move(x, y)
                # 다시 raise하여 확실히 위에 표시
                self.frame_overlay.raise_()
                # 초기 프레임 표시 설정 (씬 내 상대 프레임 번호)
                if hasattr(self, '_preview_current_display_frame') and self._preview_current_display_frame is not None:
                    current_frame = self._preview_current_display_frame
                else:
                    current_frame = 0
                
                # 씬 내 상대 프레임 번호 계산
                start_frame = getattr(self, '_preview_current_segment_start', None)
                if start_frame is not None:
                    relative_frame = current_frame - start_frame + 1  # 씬 내에서 1부터 시작
                else:
                    relative_frame = current_frame + 1  # start_frame이 없으면 절대 프레임 번호 사용
                
                self.frame_overlay.setText(f"Frame: {relative_frame}")
                self.frame_overlay.show()  # 명시적으로 표시
        QTimer.singleShot(100, setup_overlay)
        
        # preview_widget의 크기 변경 시 오버레이 위치를 우하단으로 조정
        class PreviewWidgetEventFilter(QObject):
            def __init__(self, dialog):
                super().__init__()
                self.dialog = dialog
            
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Resize and obj == preview_widget:
                    if hasattr(self.dialog, 'frame_overlay') and hasattr(self.dialog, 'preview_widget'):
                        pass
                        # 우하단 위치 계산 (preview_container 기준)
                        preview_size = self.dialog.preview_widget.size()
                        preview_pos = self.dialog.preview_widget.pos()
                        overlay_size = self.dialog.frame_overlay.size()
                        x = preview_pos.x() + preview_size.width() - overlay_size.width() - 10
                        y = preview_pos.y() + preview_size.height() - overlay_size.height() - 10
                        self.dialog.frame_overlay.move(x, y)
                        self.dialog.frame_overlay.raise_()
                        self.dialog.frame_overlay.show()
                return False
        
        preview_widget.installEventFilter(PreviewWidgetEventFilter(self))

        # 재생 컨트롤
        controls_widget = QWidget()
        controls_widget.setMinimumHeight(40)  # 최소 높이 설정
        controls_widget.setMaximumHeight(80)  # 컨트롤 높이 제한 (50 → 80으로 증가)
        controls_layout = QHBoxLayout(controls_widget)
        controls_layout.setContentsMargins(5, 5, 5, 5)
        controls_layout.setSpacing(3)  # 간격 축소 (5 → 3)
        
        # 이전 프레임 버튼
        self.prev_frame_button = QPushButton("◀◀")
        self.prev_frame_button.setToolTip("이전 프레임")
        self.prev_frame_button.setFixedSize(40, 30)
        self.prev_frame_button.setAutoDefault(False)  # Enter 키에 반응하지 않도록 설정
        self.prev_frame_button.setDefault(False)
        self.prev_frame_button.clicked.connect(self._prev_frame)
        controls_layout.addWidget(self.prev_frame_button)

        # 재생/일시정지 버튼
        self.preview_play_button = QPushButton("▶")
        self.preview_play_button.setToolTip("재생/일시정지")
        self.preview_play_button.setFixedSize(40, 30)
        self.preview_play_button.setAutoDefault(False)  # Enter 키에 반응하지 않도록 설정
        self.preview_play_button.setDefault(False)
        self.preview_play_button.clicked.connect(self._toggle_preview_playback)
        controls_layout.addWidget(self.preview_play_button)

        # 다음 프레임 버튼
        self.next_frame_button = QPushButton("▶▶")
        self.next_frame_button.setToolTip("다음 프레임")
        self.next_frame_button.setFixedSize(40, 30)
        self.next_frame_button.setAutoDefault(False)  # Enter 키에 반응하지 않도록 설정
        self.next_frame_button.setDefault(False)
        self.next_frame_button.clicked.connect(self._next_frame)
        controls_layout.addWidget(self.next_frame_button)
        
        # 현재 프레임 번호 표시 (간결하게)
        self.current_frame_label = QLabel("0/0")
        self.current_frame_label.setStyleSheet("QLabel { color: #ffae00; font-weight: bold; padding: 2px; font-size: 11px; }")
        self.current_frame_label.setToolTip("현재 프레임 / 전체 프레임")
        self.current_frame_label.setFixedWidth(70)
        controls_layout.addWidget(self.current_frame_label)
        
        # 재생 슬라이더 추가 (너비 축소)
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(100)
        self.frame_slider.setValue(0)
        self.frame_slider.setToolTip("프레임 이동 슬라이더")
        self.frame_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #555;
                height: 6px;
                background: #333;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffae00;
                border: 1px solid #ffae00;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffc850;
                border: 1px solid #ffc850;
            }
            QSlider::sub-page:horizontal {
                background: #ffae00;
                border-radius: 3px;
            }
        """)
        self.frame_slider.setFixedWidth(150)  # 200 → 150으로 축소
        # Windows(Fusion 포함)에서도 Mac처럼 왼쪽 클릭으로 그 위치로 바로 이동 + 드래그 계속되게
        jump_to_click(self.frame_slider)
        self.frame_slider.sliderPressed.connect(self._on_slider_pressed)
        self.frame_slider.sliderMoved.connect(self._on_slider_moved)
        self.frame_slider.sliderReleased.connect(self._on_slider_released)
        controls_layout.addWidget(self.frame_slider)
        
        # 프레임 번호 입력 필드 (슬라이더 옆에 배치) - 너비 축소
        self.frame_input = QLineEdit()
        self.frame_input.setPlaceholderText("프레임")
        self.frame_input.setFixedWidth(60)  # 80 → 60으로 축소
        self.frame_input.setToolTip("프레임 번호를 입력하고 Enter를 누르면 해당 프레임으로 이동합니다 (예: 30)")
        self.frame_input.setStyleSheet("""
            QLineEdit {
                background: #222;
                color: #ffae00;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 3px;
                font-weight: bold;
                font-size: 11px;
            }
            QLineEdit:focus {
                border: 2px solid #ffae00;
                background: #333;
            }
        """)
        # Enter 키 입력 시 프레임 이동
        self.frame_input.returnPressed.connect(self._on_frame_input_entered)
        
        # 프레임 입력 필드에 이벤트 필터 설치 (키 이벤트가 다른 곳으로 전달되지 않도록)
        class FrameInputEventFilter(QObject):
            def __init__(self, frame_input):
                super().__init__()
                self.frame_input = frame_input

            def eventFilter(self, obj, event):
                if obj == self.frame_input and event.type() == QEvent.KeyPress:
                    pass
                    # Enter 키는 완전히 차단 (returnPressed 시그널만 처리)
                    if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                        pass
                        return True  # 이벤트를 차단하여 상위로 전파되지 않도록 함
                    # 다른 키는 정상 처리
                    return False
                return False

        self.frame_input.installEventFilter(FrameInputEventFilter(self.frame_input))
        controls_layout.addWidget(self.frame_input)

        # 구간 길이 표시 레이블 (간격 절약을 위해 간단히 표시)
        self.segment_length_label = QLabel("-f")
        self.segment_length_label.setStyleSheet("QLabel { color: #ffae00; font-weight: bold; padding: 2px; font-size: 11px; }")
        self.segment_length_label.setToolTip("구간 길이")
        controls_layout.addWidget(self.segment_length_label)
        
        # 볼륨 레이블
        volume_label = QLabel("🔊")
        volume_label.setStyleSheet("QLabel { color: #ffae00; padding: 5px; }")
        controls_layout.addWidget(volume_label)

        # 볼륨 슬라이더
        self.preview_volume_slider = QSlider(Qt.Horizontal)
        self.preview_volume_slider.setRange(0, 100)
        self.preview_volume_slider.setValue(50)
        self.preview_volume_slider.setFixedWidth(100)
        self.preview_volume_slider.setToolTip("오디오 볼륨")
        self.preview_volume_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #555;
                height: 6px;
                background: #333;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffae00;
                border: 1px solid #ffae00;
                width: 14px;
                height: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffc850;
                border: 1px solid #ffc850;
            }
            QSlider::sub-page:horizontal {
                background: #ffae00;
                border-radius: 3px;
            }
        """)
        self.preview_volume_slider.valueChanged.connect(self._on_volume_changed)
        controls_layout.addWidget(self.preview_volume_slider)

        # 볼륨 퍼센트 레이블
        self.volume_percent_label = QLabel("50%")
        self.volume_percent_label.setStyleSheet("QLabel { color: #ffae00; font-weight: bold; padding: 5px; }")
        self.volume_percent_label.setFixedWidth(40)
        controls_layout.addWidget(self.volume_percent_label)

        # 초기 표시값 설정
        self._update_segment_info_display()

        controls_layout.addStretch()

        # 편집 텍스트 표시 레이블 (툴팁으로만 제공하고 UI에서 제거하여 공간 확보)
        self.edit_text_label = QLabel("-")
        self.edit_text_label.setStyleSheet("QLabel { color: #ffae00; padding: 2px; font-size: 10px; }")
        self.edit_text_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.edit_text_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.edit_text_label.setWordWrap(False)
        self.edit_text_label.setMaximumWidth(100)  # 200 → 100으로 축소
        # 편집 텍스트 레이블은 공간이 충분할 때만 표시 (일단 숨김)
        self.edit_text_label.hide()

        # 컨트롤 위젯은 stretch 없이 추가 (고정 높이 유지)
        preview_container_layout.addWidget(controls_widget, 0)

        # 프리뷰 컨테이너가 오른쪽 레이아웃에서 최대한 공간을 차지하도록 설정
        right_layout.addWidget(preview_container, 1)  # stretch factor: 1 (최대한 확장)
        
        # 메인 수평 레이아웃을 QSplitter로 크기 조정 가능하게
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(left_container)
        main_splitter.addWidget(right_widget)
        main_splitter.setStretchFactor(0, 1)  # 왼쪽: 1배
        main_splitter.setStretchFactor(1, 2)  # 오른쪽 (프리뷰): 2배
        main_splitter.setSizes([400, 800])  # 초기 크기 (프리뷰 영역 더 크게)
        
        # 하단 테이블 영역을 위한 위젯
        table_widget = QWidget()
        table_layout = QVBoxLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)

        # 썸네일 크기 조절 슬라이더 추가
        thumbnail_control_layout = QHBoxLayout()
        thumbnail_control_layout.setContentsMargins(5, 5, 5, 5)

        thumbnail_size_label = QLabel("썸네일 크기:")
        thumbnail_size_label.setStyleSheet("QLabel { color: #ffae00; font-weight: bold; }")
        thumbnail_control_layout.addWidget(thumbnail_size_label)

        # 슬라이더 (1~4 범위, 기본값 2)
        self.thumbnail_size_slider = QSlider(Qt.Horizontal)
        self.thumbnail_size_slider.setMinimum(1)
        self.thumbnail_size_slider.setMaximum(4)
        self.thumbnail_size_slider.setValue(2)  # 기본값: 2배 (192x108)
        self.thumbnail_size_slider.setTickPosition(QSlider.TicksBelow)
        self.thumbnail_size_slider.setTickInterval(1)
        self.thumbnail_size_slider.setFixedWidth(200)

        # OCR 모드에 따라 툴팁 설정
        is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']
        if is_ocr_mode:
            self.thumbnail_size_slider.setToolTip("썸네일 높이: 40 ~ 160 (가로는 종횡비에 맞게 자동 조절)")
        else:
            self.thumbnail_size_slider.setToolTip("썸네일 크기: 96×54 ~ 384×216")
        self.thumbnail_size_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #555;
                height: 6px;
                background: #333;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffae00;
                border: 1px solid #ffae00;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffc850;
                border: 1px solid #ffc850;
            }
            QSlider::sub-page:horizontal {
                background: #ffae00;
                border-radius: 3px;
            }
        """)
        self.thumbnail_size_slider.valueChanged.connect(self._on_thumbnail_size_changed)
        thumbnail_control_layout.addWidget(self.thumbnail_size_slider)

        # 크기 표시 레이블
        self.thumbnail_size_value_label = QLabel("192×108")
        self.thumbnail_size_value_label.setStyleSheet("QLabel { color: #ffae00; min-width: 80px; }")
        thumbnail_control_layout.addWidget(self.thumbnail_size_value_label)

        thumbnail_control_layout.addStretch()

        table_layout.addLayout(thumbnail_control_layout)

        self.table = QTableWidget(len(segments), 9, self)
        self.table.setHorizontalHeaderLabels(
            ["#", "ROI 샘플", "ROI 텍스트", "편집 텍스트", "시작 프레임", "종료 프레임", "시작 시간(s)", "종료 시간(s)", "구간 길이(프레임)"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)  # 다중 선택 허용 (Ctrl/Cmd + 클릭, Shift + 클릭)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked | QAbstractItemView.EditKeyPressed)
        # 모든 컬럼을 사용자가 조절 가능하도록 Interactive 모드로 설정
        self.table.horizontalHeader().setStretchLastSection(False)
        for column in range(9):  # 총 9개 컬럼 (0~8)
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Interactive)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            """
            QTableWidget {
                background: #000000;
                alternate-background-color: #0b0b0b;
                color: #f0f0f0;
                gridline-color: #222;
            }
            QTableWidget::item:selected {
                background: #333333;
                color: #ffea9f;
            }
            QHeaderView::section {
                background: #111111;
                color: #ffae00;
                padding: 6px;
                border: 0px;
            }
            """
        )
        table_layout.addWidget(self.table)
        
        # ROI 샘플 컬럼(인덱스 1) 너비를 썸네일 크기에 맞게 설정 (16:9 비율, 40% 작게)
        # OCR 모드에 따라 썸네일 크기 결정 (초기값은 애니매틱 모드 기준)
        self.table.setColumnWidth(1, 202)  # 192x108 썸네일 + 여백 (애니매틱 모드)

        self.segment_images = []
        self.segment_detections = []

        # Lazy loading을 위한 캐시: row -> (loaded, thumb_widget)
        self._thumbnail_cache = {}
        self._thumbnail_load_in_progress = set()  # 현재 로딩 중인 행
        self._background_loading_paused = False  # 백그라운드 로딩 일시 중지 플래그

        # 타임라인을 먼저 생성 (populate_table에서 사용되므로)
        # 타임라인을 전체 너비로 확장 (가로 스크롤 가능)
        timeline_container = QWidget()
        timeline_container_layout = QVBoxLayout(timeline_container)
        timeline_container_layout.setContentsMargins(0, 0, 0, 0)
        
        timeline_label = QLabel("타임라인")
        timeline_label.setStyleSheet("QLabel { color: #ffae00; font-weight: bold; padding: 4px; }")
        timeline_label.setMaximumHeight(30)
        timeline_container_layout.addWidget(timeline_label)
        
        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidgetResizable(False)  # 위젯 크기 조정 비활성화
        self.timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 프레임 카운트(25) + 썸네일(90) + 씬 이름(30) + 여백(25) = 170px
        self.timeline_scroll.setMinimumHeight(170)
        self.timeline_scroll.setMaximumHeight(170)
        self.timeline_scroll.setStyleSheet("""
            QScrollArea {
                background: #000000;
                border: 1px solid #222;
            }
            QScrollBar:horizontal {
                background: #111111;
                height: 12px;
                border: none;
            }
            QScrollBar::handle:horizontal {
                background: #ffae00;
                min-width: 20px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #ffc850;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
        
        # 타임라인 위젯 생성 (비디오 경로 및 OCR 모드 전달)
        self.timeline = OCRTimelineWidget(total_frames=self.total_frames, video_path=self.video_path, ocr_mode=self.ocr_mode)
        self.timeline.set_parent_dialog(self)  # OCRReviewDialog 참조 설정
        # 타임라인 우클릭 메뉴는 contextMenuEvent로 처리됨
        self.timeline_scroll.setWidget(self.timeline)
        timeline_container_layout.addWidget(self.timeline_scroll)
        
        # 타임라인 스크롤 영역의 키 이벤트 오버라이드 (좌우 화살표 키 가로채기)
        original_keyPressEvent = self.timeline_scroll.keyPressEvent
        def timeline_scroll_keyPressEvent(event):
            # 프레임 입력 필드에 포커스가 있으면 기본 동작 허용 (모든 키)
            focus_widget = self.focusWidget()
            if isinstance(focus_widget, QLineEdit) and focus_widget == getattr(self, 'frame_input', None):
                original_keyPressEvent(event)
                return
            
            key = event.key()
            # 좌우 화살표 키이고 프리뷰 영상이 활성화되어 있으면 가로채기
            if key == Qt.Key_Left or key == Qt.Key_Right:
                if (hasattr(self, '_preview_current_display_frame') and 
                    hasattr(self, '_preview_current_segment_start') and 
                    hasattr(self, '_preview_current_segment_end') and
                    self._preview_current_segment_start is not None and
                    self._preview_current_segment_end is not None):
                    # 다이얼로그의 keyPressEvent로 이벤트 전달
                    self.keyPressEvent(event)
                    event.accept()
                    return
            # 그 외의 경우는 기본 동작 수행
            original_keyPressEvent(event)
        
        self.timeline_scroll.keyPressEvent = timeline_scroll_keyPressEvent
        
        # 타임라인 위젯의 키 이벤트도 오버라이드
        if hasattr(self.timeline, 'keyPressEvent'):
            original_timeline_keyPressEvent = self.timeline.keyPressEvent
            def timeline_keyPressEvent(event):
                # 프레임 입력 필드에 포커스가 있으면 기본 동작 허용 (모든 키)
                focus_widget = self.focusWidget()
                if isinstance(focus_widget, QLineEdit) and focus_widget == getattr(self, 'frame_input', None):
                    original_timeline_keyPressEvent(event)
                    return
                
                key = event.key()
                # 좌우 화살표 키이고 프리뷰 영상이 활성화되어 있으면 가로채기
                if key == Qt.Key_Left or key == Qt.Key_Right:
                    if (hasattr(self, '_preview_current_display_frame') and 
                        hasattr(self, '_preview_current_segment_start') and 
                        hasattr(self, '_preview_current_segment_end') and
                        self._preview_current_segment_start is not None and
                        self._preview_current_segment_end is not None):
                        # 다이얼로그의 keyPressEvent로 이벤트 전달
                        self.keyPressEvent(event)
                        event.accept()
                        return
                # 그 외의 경우는 기본 동작 수행
                original_timeline_keyPressEvent(event)
            
            self.timeline.keyPressEvent = timeline_keyPressEvent
        
        # 이제 populate_table 호출 (타임라인과 로그 영역이 이미 생성됨)
        self.populate_table(segments)
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.selectionModel().selectionChanged.connect(self.on_selection_changed)
        
        # 우클릭 메뉴 활성화
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)

        # 스크롤 이벤트에 연결 - lazy loading을 위해
        self.table.verticalScrollBar().valueChanged.connect(self._on_table_scrolled)
        if self.table.rowCount() > 0:
            self.table.selectRow(0)
            # 씬 리스트도 첫 번째 아이템 선택
            if hasattr(self, 'sceneListWidget') and self.sceneListWidget.count() > 0:
                self.sceneListWidget.setCurrentRow(0)
            self.update_preview(0)

            # 초기 로드: 처음 INITIAL_LOAD_COUNT개는 이미 로드됨, 캐시에 추가
            INITIAL_LOAD_COUNT = 30  # populate_table과 동일한 값
            for row in range(min(INITIAL_LOAD_COUNT, self.table.rowCount())):
                self._thumbnail_cache[row] = True

            # 보이는 행의 나머지 썸네일 로드 (INITIAL_LOAD_COUNT 이후)
            QTimer.singleShot(100, self._on_table_scrolled)
        else:
            self.update_preview(-1)

        # QSplitter로 메인 영역, 타임라인, 테이블 분리 (크기 조정 가능)
        # 로그는 왼쪽 패널에 있으므로 여기서는 제외
        main_vertical_splitter = QSplitter(Qt.Vertical)
        main_vertical_splitter.addWidget(main_splitter)
        main_vertical_splitter.addWidget(timeline_container)  # 타임라인 (전체 너비)
        main_vertical_splitter.addWidget(table_widget)
        main_vertical_splitter.setStretchFactor(0, 3)  # 메인 영역 (프리뷰 포함): 3배
        main_vertical_splitter.setStretchFactor(1, 0)  # 타임라인: 고정 높이
        main_vertical_splitter.setStretchFactor(2, 1)  # 테이블: 1배
        main_vertical_splitter.setSizes([600, 130, 250])  # 초기 크기 (타임라인 높이 조정)
        layout.addWidget(main_vertical_splitter)

        controls_layout = QHBoxLayout()
        self.mergeButton = QPushButton("선택한 구간 병합")
        self.mergeButton.clicked.connect(self.merge_selected_rows)
        self.mergeButton.setToolTip("선택한 여러 구간을 하나로 병합합니다 (Ctrl/Cmd + 클릭 또는 Shift + 클릭으로 다중 선택, 연속되지 않은 구간도 병합 가능)\n단축키: D")
        controls_layout.addWidget(self.mergeButton)
        
        self.smartMergeButton = QPushButton("스마트 병합")
        self.smartMergeButton.clicked.connect(self.smart_merge_by_scene)
        self.smartMergeButton.setToolTip("Scene 번호가 같은 연속된 항목들을 자동으로 병합합니다\n예: 'Scene 8 - Panel A', 'Scene 8 - Panel B' → 자동 병합")
        controls_layout.addWidget(self.smartMergeButton)
        
        # 병합 단축키 D(ㅇ) - 한글 자판에서도 작동
        # 영문 자판: D
        merge_shortcut_d = QShortcut(QKeySequence("D"), self)
        merge_shortcut_d.activated.connect(self.merge_selected_rows)
        # 한글 자판: ㅇ (D 키를 누르면 생성되는 문자)
        merge_shortcut_kr = QShortcut(QKeySequence("ㅇ"), self)
        merge_shortcut_kr.activated.connect(self.merge_selected_rows)
        # 컨텍스트를 ApplicationShortcut으로 설정하여 더 넓은 범위에서 작동
        merge_shortcut_d.setContext(Qt.ApplicationShortcut)
        merge_shortcut_kr.setContext(Qt.ApplicationShortcut)
        self.removeButton = QPushButton("선택 구간 삭제")
        self.removeButton.clicked.connect(self.remove_selected_rows)
        self.removeButton.setToolTip("선택한 구간을 삭제합니다\n단축키: X")
        controls_layout.addWidget(self.removeButton)
        
        # 선택 구간 삭제 단축키 X(ㅌ) - 한글 자판에서도 작동
        # 영문 자판: X
        remove_shortcut_x = QShortcut(QKeySequence("X"), self)
        remove_shortcut_x.activated.connect(self.remove_selected_rows)
        # 한글 자판: ㅌ (X 키를 누르면 생성되는 문자)
        remove_shortcut_kr = QShortcut(QKeySequence("ㅌ"), self)
        remove_shortcut_kr.activated.connect(self.remove_selected_rows)
        # 컨텍스트를 ApplicationShortcut으로 설정하여 더 넓은 범위에서 작동
        remove_shortcut_x.setContext(Qt.ApplicationShortcut)
        remove_shortcut_kr.setContext(Qt.ApplicationShortcut)
        
        # 씬 분할 버튼
        self.splitButton = QPushButton("씬 분할")
        self.splitButton.clicked.connect(self.split_selected_row)
        self.splitButton.setToolTip("선택한 씬을 지정한 프레임 위치에서 두 개의 씬으로 분할합니다")
        controls_layout.addWidget(self.splitButton)
        
        # 리네임 버튼
        self.renameButton = QPushButton("일괄 리네임")
        self.renameButton.clicked.connect(self.batch_rename_segments)
        self.renameButton.setToolTip("편집 텍스트를 패턴 매칭으로 일괄 변경합니다\n예: ' - Panel A' → '' (제거)")
        controls_layout.addWidget(self.renameButton)
        
        # Undo/Redo 버튼
        self.undoButton = QPushButton("↶ 실행 취소")
        self.undoButton.clicked.connect(self.undo_action)
        self.undoButton.setToolTip("마지막 병합 또는 삭제를 취소합니다 (Ctrl/Cmd+Z)")
        self.undoButton.setEnabled(False)  # 초기 상태는 비활성화
        controls_layout.addWidget(self.undoButton)
        
        self.redoButton = QPushButton("↷ 다시 실행")
        self.redoButton.clicked.connect(self.redo_action)
        self.redoButton.setToolTip("취소한 작업을 다시 실행합니다 (Ctrl/Cmd+Shift+Z)")
        self.redoButton.setEnabled(False)  # 초기 상태는 비활성화
        controls_layout.addWidget(self.redoButton)
        
        # Undo/Redo 단축키
        undo_shortcut = QShortcut(QKeySequence.Undo, self)  # Ctrl+Z (Cmd+Z on Mac)
        undo_shortcut.activated.connect(self.undo_action)
        redo_shortcut = QShortcut(QKeySequence.Redo, self)  # Ctrl+Shift+Z (Cmd+Shift+Z on Mac)
        redo_shortcut.activated.connect(self.redo_action)
        
        controls_layout.addStretch(1)
        
        # 웹분석 버튼
        self.webAnalysisButton = QPushButton("웹분석")
        self.webAnalysisButton.clicked.connect(self.export_to_web)
        self.webAnalysisButton.setToolTip("OCR 분석 결과를 웹 페이지로 내보냅니다")
        self.webAnalysisButton.setFixedWidth(150)  # 고정 너비로 정렬
        self.webAnalysisButton.setStyleSheet("""
            QPushButton {
                background: #1a4d1a;
                color: #88ee88;
                border: 1px solid #88ee88;
                padding: 6px 12px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #2a6d2a;
                border-color: #aaff88;
            }
            QPushButton:pressed {
                background: #0a3d0a;
            }
        """)
        controls_layout.addWidget(self.webAnalysisButton)
        
        layout.addLayout(controls_layout)

        export_controls_layout = QHBoxLayout()
        self.exportSelectedButton = QPushButton("선택한 항목만 내보내기")
        self.exportSelectedButton.clicked.connect(self.export_selected_only)
        self.exportSelectedButton.setToolTip("선택된 구간만 내보냅니다 (Ctrl/Cmd + 클릭 또는 Shift + 클릭으로 다중 선택)")
        export_controls_layout.addWidget(self.exportSelectedButton)
        
        # 사운드 on/off 체크박스
        self.includeAudioCheckBox = QCheckBox("사운드 포함")
        self.includeAudioCheckBox.setChecked(True)  # 기본값: 사운드 포함
        self.includeAudioCheckBox.setToolTip("체크하면 사운드가 포함되고, 해제하면 사운드 없이 내보냅니다")
        export_controls_layout.addWidget(self.includeAudioCheckBox)
        
        # 내보내기 모드 선택
        export_mode_label = QLabel("내보내기 모드:")
        export_controls_layout.addWidget(export_mode_label)
        
        self.exportModeComboBox = QComboBox()
        self.exportModeComboBox.addItem("균형 (빠르고 정확)", "balanced")  # 기본값
        self.exportModeComboBox.addItem(external_tools.fast_mode_label(), "fast")
        self.exportModeComboBox.addItem("고품질 (최고 화질)", "quality")
        self.exportModeComboBox.setCurrentIndex(0)  # 균형 모드가 기본값
        self.exportModeComboBox.setToolTip(
            "균형: libx264 faster (속도와 품질의 균형, 추천)\n"
            + ("고속: VideoToolbox 하드웨어 가속 (5-10배 빠름)\n" if sys.platform == "darwin"
               else "고속: libx264 veryfast + 선택한 비트레이트 (CPU)\n")
            + "고품질: libx264 slower (느리지만 최고 화질)"
        )
        export_controls_layout.addWidget(self.exportModeComboBox)
        
        # 비트레이트 선택 (fast 모드일 때만 표시)
        self.bitrate_label = QLabel("비트레이트:")
        self.bitrate_label.setVisible(False)
        export_controls_layout.addWidget(self.bitrate_label)
        
        self.bitrateComboBox = QComboBox()
        self.bitrateComboBox.addItem("8000k (8 Mbit/s) - 높은 품질", "8000k")
        self.bitrateComboBox.addItem("4000k (4 Mbit/s) - 일반 품질", "4000k")
        self.bitrateComboBox.addItem("3000k (3 Mbit/s) - 약간 낮은 품질", "3000k")
        self.bitrateComboBox.addItem("2000k (2 Mbit/s) - 낮은 품질", "2000k")
        self.bitrateComboBox.addItem("1000k (1 Mbit/s) - 매우 낮은 품질", "1000k")
        self.bitrateComboBox.setCurrentIndex(0)  # 기본값: 8000k
        self.bitrateComboBox.setVisible(False)
        self.bitrateComboBox.setToolTip(
            "비트레이트가 낮을수록 파일 크기는 작아지지만 품질이 낮아집니다.\n"
            "고속 모드에서만 사용됩니다."
        )
        export_controls_layout.addWidget(self.bitrateComboBox)
        
        # exportModeComboBox 변경 시 비트레이트 ComboBox 표시/숨김
        self.exportModeComboBox.currentTextChanged.connect(self._on_export_mode_changed)
        # 초기 상태 설정
        self._on_export_mode_changed()
        
        export_controls_layout.addStretch(1)

        # 재분석 버튼 (고정 너비로 정렬)
        self.reanalyzeButton = QPushButton("재분석")
        self.reanalyzeButton.clicked.connect(self.reject)
        self.reanalyzeButton.setFixedWidth(120)  # 고정 너비
        export_controls_layout.addWidget(self.reanalyzeButton)

        # 전체 내보내기 버튼 (고정 너비로 정렬)
        self.exportAllButton = QPushButton("전체 내보내기")
        self.exportAllButton.clicked.connect(self.export_all)
        self.exportAllButton.setToolTip("전체 내보내기\n단축키: R")
        self.exportAllButton.setFixedWidth(150)  # 고정 너비
        export_controls_layout.addWidget(self.exportAllButton)

        layout.addLayout(export_controls_layout)
        
        # 전체 내보내기 단축키 R(ㄱ) - 한글 자판에서도 작동
        # 영문 자판: R
        export_all_shortcut_r = QShortcut(QKeySequence("R"), self)
        export_all_shortcut_r.activated.connect(self.export_all)
        # 한글 자판: ㄱ (R 키를 누르면 생성되는 문자)
        export_all_shortcut_kr = QShortcut(QKeySequence("ㄱ"), self)
        export_all_shortcut_kr.activated.connect(self.export_all)
        # 컨텍스트를 ApplicationShortcut으로 설정하여 더 넓은 범위에서 작동
        export_all_shortcut_r.setContext(Qt.ApplicationShortcut)
        export_all_shortcut_kr.setContext(Qt.ApplicationShortcut)

        segments = self.collect_segments()
        self.timeline.set_segments(segments)
        self.update_summary()

        # WebSocket 서버 초기화 (실시간 동기화용)
        self.websocket_server = None
        self.websocket_clients = []
        self.setup_websocket_server()
        self.update_sequence()

        # 다이얼로그가 표시된 직후 나머지 썸네일을 백그라운드에서 로드
        # (populate_table에서 모든 썸네일을 즉시 로드했으면 건너뛰기)
        # 이미 segment_images에 썸네일이 있는 행은 캐시에 추가
        total_rows = self.table.rowCount()
        for row in range(total_rows):
            if row not in self._thumbnail_cache:
                pass
                # 이미 segment_images에 썸네일이 있으면 캐시에 추가
                if row < len(self.segment_images) and self.segment_images[row]:
                    self._thumbnail_cache[row] = True
        
        cached_count = len(self._thumbnail_cache)
        # segment_images에 썸네일이 없는 행만 백그라운드에서 로드
        needs_loading = False
        for row in range(total_rows):
            if row not in self._thumbnail_cache:
                pass
                # 애니매틱 모드이고 비디오 경로가 있고, segment_images에 썸네일이 없는 경우만 로드 필요
                if (row >= len(self.segment_images) or not self.segment_images[row]) and \
                   getattr(self, 'ocr_mode', 'titmouse') in ['animatic', 'animatic2'] and \
                   self.video_path and os.path.exists(self.video_path):
                    needs_loading = True
                    break
        
        if needs_loading:
            pass
            # print(f"[Init] 백그라운드 썸네일 로딩 시작 (캐시: {cached_count}/{total_rows})")
            QTimer.singleShot(100, self._load_remaining_thumbnails)
        else:
            pass
            # print(f"[Init] 모든 썸네일 이미 로드됨 → 백그라운드 로딩 건너뛰기 (캐시: {cached_count}/{total_rows})")
    
    def keyPressEvent(self, event):
        """키보드 이벤트 처리 - 한글 자판에서도 작동하도록 물리적 키 코드 확인"""
        # 텍스트 입력 위젯에 포커스가 있으면 단축키 무시
        focus_widget = self.focusWidget()
        if isinstance(focus_widget, (QLineEdit, QPlainTextEdit)):
            pass
            # 프레임 입력 필드에 포커스가 있으면 모든 키 입력을 허용
            if focus_widget == getattr(self, 'frame_input', None):
                pass
                # 기본 키 이벤트 처리로 전달하여 입력 필드가 정상적으로 작동하도록 함
                super().keyPressEvent(event)
                return
            super().keyPressEvent(event)
            return
        
        # 물리적 키 코드 확인 (한글 입력 모드와 무관)
        key = event.key()
        text = event.text()

        # Enter/Return 키는 무시 (프레임 입력 후 의도하지 않은 동작 방지)
        if key in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return

        # D 키 (한글 자판에서 ㅇ) - 선택구간 병합
        # key == Qt.Key_D: 영문 자판에서 D 키
        # text == "ㅇ": 한글 자판에서 D 키를 누르면 생성되는 문자
        if key == Qt.Key_D or text == "ㅇ":
            self.merge_selected_rows()
            event.accept()
            return
        
        # X 키 (한글 자판에서 ㅌ) - 선택구간 삭제
        if key == Qt.Key_X or text == "ㅌ":
            self.remove_selected_rows()
            event.accept()
            return
        
        # R 키 (한글 자판에서 ㄱ) - 전체 내보내기
        # key == Qt.Key_R: 영문 자판에서 R 키
        # text == "ㄱ": 한글 자판에서 R 키를 누르면 생성되는 문자
        if key == Qt.Key_R or text == "ㄱ":
            self.export_all()
            event.accept()
            return
        
        # 스페이스바 - 프리뷰 재생/일시정지 토글
        if key == Qt.Key_Space:
            pass
            # 프리뷰 영상이 활성화되어 있는지 확인
            if (hasattr(self, '_preview_current_segment_start') and
                hasattr(self, '_preview_current_segment_end') and
                self._preview_current_segment_start is not None and
                self._preview_current_segment_end is not None):

                self._toggle_preview_playback()
                event.accept()
                return

        # 좌우 화살표 키 - 프리뷰 영상 이전/다음 프레임 이동
        if key == Qt.Key_Left or key == Qt.Key_Right:
            pass
            # 프리뷰 영상이 활성화되어 있는지 확인
            if (hasattr(self, '_preview_current_display_frame') and
                hasattr(self, '_preview_current_segment_start') and
                hasattr(self, '_preview_current_segment_end') and
                self._preview_current_segment_start is not None and
                self._preview_current_segment_end is not None):

                # 프리뷰 영상이 활성화되어 있으면 프레임 이동 처리
                if key == Qt.Key_Left:
                    pass
                    # 이전 프레임으로 이동
                    self._prev_frame()
                else:
                    pass
                    # 다음 프레임으로 이동
                    self._next_frame()

                event.accept()
                return

        # 기본 키 이벤트 처리
        super().keyPressEvent(event)

    def populate_table(self, segments):
        self._updating = True
        self.segment_images = []
        self.segment_detections = []

        # 성능 최적화: 테이블 업데이트 중지 (320개 행 처리 시 매우 느려짐)
        self.table.setUpdatesEnabled(False)

        # 씬 리스트 초기화 및 채우기
        if hasattr(self, 'sceneListWidget'):
            self.sceneListWidget.clear()

        # 타임라인 업데이트 (기존 데이터 제거 및 새 데이터 설정)
        if hasattr(self, 'timeline'):
            self.timeline.set_segments(segments)

        # 성능 최적화: 테이블 행 수를 미리 설정 (한 번에)
        self.table.setRowCount(len(segments))

        # OCR 모드에 따라 테이블 열 너비 설정 (한 번만)
        # OCR 모드는 실제 이미지 비율에 맞게 동적 조정되므로 여기서는 기본값만 설정
        is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']
        if is_ocr_mode:
            pass
            # OCR 모드: 기본값 (실제로는 첫 번째 이미지 로드 시 동적 조정)
            self.table.setColumnWidth(1, 400)  # 넉넉하게 기본값 설정
        else:
            pass
            # 애니매틱/애니매틱2 모드: 기존 크기 (192x108)
            self.table.setColumnWidth(1, 202)  # 192 + 여백

        # Lazy loading 여부 판단: 모든 segment에 roi_image가 있으면 lazy loading 불필요
        # OCR 분석 완료 직후에는 모든 썸네일이 이미 있으므로 즉시 전부 표시
        # JSON 파일 로드 시에는 base64 문자열이므로 lazy loading 필요
        has_all_thumbnails = all(
            segment.get("roi_image") is not None and
            isinstance(segment.get("roi_image"), bytes)  # bytes면 OCR 분석 완료 직후
            for segment in segments
        )

        if has_all_thumbnails:
            pass
            # print(f"[Populate Table] 모든 썸네일이 이미 메모리에 있음 → Lazy loading 건너뛰기 (즉시 전부 표시)")
            INITIAL_LOAD_COUNT = len(segments)  # 모두 즉시 로드
        else:
            pass
            # print(f"[Populate Table] 썸네일 일부 또는 전부 없음 → Lazy loading 사용")
            INITIAL_LOAD_COUNT = 30  # 처음 30개만 즉시 로드

        for row, segment in enumerate(segments):
            pass
            # 씬 리스트에 아이템 추가
            if hasattr(self, 'sceneListWidget'):
                start_frame = int(segment.get("start_frame", 0))
                end_frame = int(segment.get("end_frame", start_frame))
                start_time = segment.get("start_time", start_frame / self.fps if self.fps else 0.0)
                end_time = segment.get("end_time", (end_frame + 1) / self.fps if self.fps else 0.0)
                text = segment.get("edited_text", segment.get("text", ""))

                # 테이블과 동일하게 1-based로 표시 (VFX 업계 표준)
                scene_text = f"{row+1:02d}. {text} | 프레임 {start_frame + 1} → {end_frame + 1} | {start_time:.3f}s → {end_time:.3f}s"
                list_item = QListWidgetItem(scene_text)
                list_item.setData(Qt.UserRole, row)  # 테이블 행 인덱스 저장
                self.sceneListWidget.addItem(list_item)
            index_item = QTableWidgetItem(str(row + 1))
            index_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(row, 0, index_item)

            # Lazy loading: 처음 INITIAL_LOAD_COUNT개만 즉시 로드
            should_load_thumbnail = row < INITIAL_LOAD_COUNT

            roi_bytes = segment.get("roi_image") or segment.get("roi_preview")
            detections = copy.deepcopy(segment.get("detections") or [])

            # Lazy loading: 즉시 로드하는 경우에만 비디오에서 프레임 추출
            # 애니매틱/애니매틱2 모드일 때만 roi_image가 없으면 비디오에서 프레임 추출
            # OCR 모드일 때는 roi_image를 우선 사용 (ROI 지정한 영역 이미지)
            if should_load_thumbnail and not roi_bytes and getattr(self, 'ocr_mode', 'titmouse') in ['animatic', 'animatic2'] and self.video_path and os.path.exists(self.video_path):
                start_frame = int(segment.get("start_frame", 0))
                extracted_bytes = self._extract_frame_thumbnail(self.video_path, start_frame)
                if extracted_bytes:
                    roi_bytes = extracted_bytes
                    # print(f"[Lazy Load] Row {row}: 비디오에서 프레임 {start_frame} 추출 완료")

            self.segment_images.append(roi_bytes)
            self.segment_detections.append(detections)
            detection_lines = self._format_detection_lines(detections)
            tooltip_text = "\n".join(detection_lines)
            # detections에서 추출한 텍스트 (fallback용)
            roi_text_from_detections = "\n".join(
                det.get("text") for det in detections if isinstance(det, dict) and det.get("text")
            )
            if not roi_text_from_detections:
                roi_text_from_detections = "<미검출>"

            start_frame = int(segment.get("start_frame", 0))
            end_frame = int(segment.get("end_frame", start_frame))

            # 썸네일을 담을 위젯 (재생 버튼 오버레이용)
            thumb_widget = QWidget()
            thumb_layout = QVBoxLayout(thumb_widget)
            thumb_layout.setContentsMargins(0, 0, 0, 0)
            thumb_layout.setSpacing(0)

            thumb_label = QLabel()
            thumb_label.setAlignment(Qt.AlignCenter)
            thumb_label.setStyleSheet("QLabel { background: #050505; border: 1px solid #222; color: #555; }")

            # OCR 모드에 따라 썸네일 크기 결정
            is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']

            # Lazy loading: 즉시 로드하는 경우에만 pixmap 생성
            if should_load_thumbnail:
                pass
                # 원본 pixmap 생성 (슬라이더 성능 최적화용)
                original_pixmap = self._pixmap_with_boxes(roi_bytes, detections, None)
            else:
                pass
                # Lazy loading: placeholder만 표시 (스크롤할 때 로드됨)
                original_pixmap = None

            if is_ocr_mode:
                pass
                # OCR 모드: 실제 이미지 종횡비에 맞게 조정
                if original_pixmap:
                    pass
                    # 원본 이미지 크기 확인
                    orig_width = original_pixmap.width()
                    orig_height = original_pixmap.height()

                    # 높이를 80px로 고정하고 종횡비에 맞게 가로 크기 계산
                    target_height = 80
                    aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                    target_width = int(target_height * aspect_ratio)

                    thumbnail_size = QSize(target_width, target_height)

                    # 행 높이 조정 (높이 + 여백)
                    self.table.setRowHeight(row, target_height + 10)

                    # 컬럼 너비 동적 조정 (첫 번째 행일 때만)
                    if row == 0:
                        self.table.setColumnWidth(1, target_width + 10)

                    # 원본을 스케일링
                    pixmap = original_pixmap.scaled(
                        thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                else:
                    pixmap = None
                    thumbnail_size = QSize(240, 80)
                    self.table.setRowHeight(row, 90)
            else:
                pass
                # 애니매틱 모드: 기존 방식 유지 (원본 비율 유지하면서 스케일)
                thumbnail_size = QSize(192, 108)
                self.table.setRowHeight(row, 118)  # 108 + 여백

                # 애니매틱 모드: 원본을 스케일링
                if original_pixmap:
                    pixmap = original_pixmap.scaled(
                        thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                else:
                    pixmap = None

            if pixmap:
                thumb_label.setPixmap(pixmap)
                # 원본 pixmap 저장 (슬라이더 성능 최적화용)
                thumb_label.setProperty('original_pixmap', original_pixmap)
            else:
                pass
                # Lazy loading: placeholder 텍스트 표시
                if should_load_thumbnail:
                    thumb_label.setText("이미지 없음")
                else:
                    thumb_label.setText("⋯")  # 로딩 대기 중 표시
            thumb_label.setToolTip(tooltip_text)
            thumb_layout.addWidget(thumb_label)

            # 썸네일을 로드했으면 캐시에 추가
            # 이미 roi_bytes가 있으면 (씬 감지 완료 후 추출된 썸네일 또는 저장된 썸네일) 캐시에 추가
            if should_load_thumbnail or roi_bytes:
                self._thumbnail_cache[row] = True
            
            
            self.table.setCellWidget(row, 1, thumb_widget)
            
            # 행 높이를 썸네일 크기에 맞게 설정 (108px 썸네일 + 여백)
            self.table.setRowHeight(row, 118)

            # 2번 컬럼 (ROI 텍스트): segment["text"]를 우선 사용 (실제 병합된 OCR 결과)
            # edited_text가 있으면 그것을 사용, 없으면 text, 둘 다 없으면 detections에서 추출
            roi_text_value = segment.get("edited_text") or segment.get("text") or roi_text_from_detections
            roi_text_item = QTableWidgetItem(roi_text_value)
            roi_text_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            roi_text_item.setTextAlignment(Qt.AlignLeft | Qt.AlignTop)
            roi_text_item.setToolTip(tooltip_text)
            self.table.setItem(row, 2, roi_text_item)

            # 3번 컬럼 (편집된 텍스트): 2번 컬럼과 동일하게 시작
            display_text = roi_text_value
            text_item = QTableWidgetItem(display_text)
            text_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            text_item.setToolTip(tooltip_text)
            self.table.setItem(row, 3, text_item)

            # start_frame과 end_frame은 이미 위에서 정의됨 (4682-4683줄)

            # 사용자에게는 1-based로 표시 (VFX 업계 표준)
            start_item = QTableWidgetItem(str(start_frame + 1))
            start_item.setData(Qt.UserRole, start_frame)  # 내부적으로는 0-based 유지
            self.table.setItem(row, 4, start_item)

            end_item = QTableWidgetItem(str(end_frame + 1))
            end_item.setData(Qt.UserRole, end_frame)  # 내부적으로는 0-based 유지
            self.table.setItem(row, 5, end_item)

            start_time_item = QTableWidgetItem()
            start_time_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(row, 6, start_time_item)

            end_time_item = QTableWidgetItem()
            end_time_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(row, 7, end_time_item)

            duration_item = QTableWidgetItem()
            duration_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(row, 8, duration_item)

            self.update_row_times(row)
        
        # 성능 최적화: 테이블 업데이트 재개 (모든 행 추가 완료 후)
        self.table.setUpdatesEnabled(True)
        self._updating = False
        
        # 병합이 필요한 행들을 하이라이트 (지연 실행으로 성능 향상)
        QTimer.singleShot(100, self._highlight_mergeable_rows)
        
        # 타임라인과 요약은 마지막에 한 번만 업데이트 (성능 최적화)
        segments = self.collect_segments()
        QTimer.singleShot(0, lambda: self._update_ui_after_merge(segments))

    def add_segments_to_table(self, segments):
        """기존 테이블에 새 세그먼트들을 추가합니다 (프레임 순서대로 정렬)"""
        # print(f"[add_segments_to_table] 호출됨. 추가할 세그먼트: {len(segments)}개")
        
        if not segments:
            print("[add_segments_to_table] 세그먼트가 없어서 종료")
            return
        
        # 기존 세그먼트 수집 (collect_segments 호출 전에는 _updating을 False로 설정)
        self._updating = False
        existing_segments = self.collect_segments()
        # print(f"[add_segments_to_table] 기존 세그먼트: {len(existing_segments)}개")

        # 새 세그먼트와 겹치는 기존 세그먼트 제거 (선택 구간 재분석 시 중복 방지)
        if existing_segments:
            new_range_start = min(int(seg.get('start_frame', 0) or 0) for seg in segments)
            new_range_end = max(
                int(seg.get('end_frame', seg.get('start_frame', 0) or 0) or 0)
                for seg in segments
            )

            filtered_existing = []
            removed_count = 0
            for seg in existing_segments:
                seg_start = int(seg.get('start_frame', 0) or 0)
                seg_end = int(seg.get('end_frame', seg_start) or seg_start)

                overlaps = not (seg_end < new_range_start or seg_start > new_range_end)
                if overlaps:
                    removed_count += 1
                    continue
                filtered_existing.append(seg)

            if removed_count:
                print(
                    f"[add_segments_to_table] 신규 범위 {new_range_start}-{new_range_end}와 "
                    f"겹치는 기존 세그먼트 {removed_count}개 제거"
                )
            existing_segments = filtered_existing
        
        # 이제 테이블 업데이트 시작
        self._updating = True
        
        # 새 세그먼트 추가
        all_segments = existing_segments + segments
        # print(f"[add_segments_to_table] 병합 후 총 세그먼트: {len(all_segments)}개")
        
        # 정렬 전 샘플 출력 (처음 5개)
        # print(f"[add_segments_to_table] 정렬 전 샘플 (처음 5개):")
        for i, seg in enumerate(all_segments[:5]):
            text = seg.get('edited_text', seg.get('text', ''))[:30]
            print(f"  [{i}] frame={seg.get('start_frame', 0)}, text='{text}'")
        
        # 프레임 순서대로 정렬
        all_segments = self._sort_segments(all_segments)
        
        # 정렬 후 샘플 출력 (처음 10개)
        # print(f"[add_segments_to_table] 정렬 후 샘플 (처음 10개):")
        for i, seg in enumerate(all_segments[:10]):
            text = seg.get('edited_text', seg.get('text', ''))[:30]
            print(f"  [{i}] frame={seg.get('start_frame', 0)}, text='{text}'")
        
        # 테이블 다시 채우기
        # print(f"[add_segments_to_table] 테이블 업데이트 시작: {len(all_segments)}행")
        old_row_count = self.table.rowCount()
        self.table.setRowCount(0)  # 기존 행 모두 제거
        self.segment_images = []
        self.segment_detections = []
        
        # OCR 모드에 따라 테이블 열 너비 설정 (한 번만)
        # OCR 모드는 실제 이미지 비율에 맞게 동적 조정되므로 여기서는 기본값만 설정
        is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']
        if is_ocr_mode:
            pass
            # OCR 모드: 기본값 (실제로는 첫 번째 이미지 로드 시 동적 조정)
            self.table.setColumnWidth(1, 400)  # 넉넉하게 기본값 설정
        else:
            pass
            # 애니매틱/애니매틱2 모드: 기존 크기 (192x108)
            self.table.setColumnWidth(1, 202)  # 192 + 여백
        
        for row, segment in enumerate(all_segments):
            self.table.insertRow(row)
            
            index_item = QTableWidgetItem(str(row + 1))
            index_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(row, 0, index_item)

            roi_bytes = segment.get("roi_image") or segment.get("roi_preview")
            detections = copy.deepcopy(segment.get("detections") or [])
            
            # 애니매틱/애니매틱2 모드일 때만 roi_image가 없으면 비디오에서 프레임 추출
            # OCR 모드일 때는 roi_image를 우선 사용 (ROI 지정한 영역 이미지)
            if not roi_bytes and getattr(self, 'ocr_mode', 'titmouse') in ['animatic', 'animatic2'] and self.video_path and os.path.exists(self.video_path):
                start_frame = int(segment.get("start_frame", 0))
                roi_bytes = self._extract_frame_thumbnail(self.video_path, start_frame)
            
            self.segment_images.append(roi_bytes)
            self.segment_detections.append(detections)
            detection_lines = self._format_detection_lines(detections)
            tooltip_text = "\n".join(detection_lines)
            # detections에서 추출한 텍스트 (fallback용)
            roi_text_from_detections = "\n".join(
                det.get("text") for det in detections if isinstance(det, dict) and det.get("text")
            )
            if not roi_text_from_detections:
                roi_text_from_detections = "<미검출>"
            
            start_frame = int(segment.get("start_frame", 0))
            end_frame = int(segment.get("end_frame", start_frame))
            
            # 썸네일을 담을 위젯 (재생 버튼 오버레이용)
            thumb_widget = QWidget()
            thumb_layout = QVBoxLayout(thumb_widget)
            thumb_layout.setContentsMargins(0, 0, 0, 0)
            thumb_layout.setSpacing(0)
            
            thumb_label = QLabel()
            thumb_label.setAlignment(Qt.AlignCenter)
            thumb_label.setStyleSheet("QLabel { background: #050505; border: 1px solid #222; color: #555; }")
            
            # OCR 모드에 따라 썸네일 크기 결정
            is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']

            # 원본 pixmap 생성 (슬라이더 성능 최적화용)
            original_pixmap = self._pixmap_with_boxes(roi_bytes, detections, None)

            if is_ocr_mode:
                pass
                # OCR 모드: 실제 이미지 종횡비에 맞게 조정
                if original_pixmap:
                    pass
                    # 원본 이미지 크기 확인
                    orig_width = original_pixmap.width()
                    orig_height = original_pixmap.height()

                    # 높이를 80px로 고정하고 종횡비에 맞게 가로 크기 계산
                    target_height = 80
                    aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                    target_width = int(target_height * aspect_ratio)

                    thumbnail_size = QSize(target_width, target_height)

                    # 행 높이 조정 (높이 + 여백)
                    self.table.setRowHeight(row, target_height + 10)

                    # 컬럼 너비 동적 조정 (첫 번째 행일 때만)
                    if row == 0:
                        self.table.setColumnWidth(1, target_width + 10)

                    # 원본을 스케일링
                    pixmap = original_pixmap.scaled(
                        thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                else:
                    pixmap = None
                    thumbnail_size = QSize(240, 80)
                    self.table.setRowHeight(row, 90)
            else:
                pass
                # 애니매틱 모드: 기존 방식 유지 (원본 비율 유지하면서 스케일)
                thumbnail_size = QSize(192, 108)
                self.table.setRowHeight(row, 118)  # 108 + 여백

                # 애니매틱 모드: 원본을 스케일링
                if original_pixmap:
                    pixmap = original_pixmap.scaled(
                        thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                else:
                    pixmap = None

            if pixmap:
                thumb_label.setPixmap(pixmap)
                # 원본 pixmap 저장 (슬라이더 성능 최적화용)
                thumb_label.setProperty('original_pixmap', original_pixmap)
            else:
                thumb_label.setText("이미지 없음")
            thumb_label.setToolTip(tooltip_text)
            thumb_layout.addWidget(thumb_label)
            
            # 재생 버튼 오버레이
            play_button = QPushButton("▶")
            play_button.setFixedSize(30, 30)
            play_button.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 165, 0, 100);
                    color: white;
                    border: 2px solid rgba(255, 255, 255, 100);
                    border-radius: 15px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: rgba(255, 165, 0, 180);
                    border: 2px solid rgba(255, 255, 255, 150);
                }
                QPushButton:pressed {
                    background: rgba(255, 140, 0, 200);
                }
            """)
            play_button.setCursor(Qt.PointingHandCursor)
            
            # 재생 버튼에 row 정보 직접 저장 (클로저 문제 완전 해결)
            play_button.setProperty("table_row", row)
            
            # 재생 버튼을 썸네일 위에 오버레이로 배치
            play_button.setParent(thumb_label)
            play_button.raise_()
            play_button.show()
            
            # 썸네일 크기에 맞춰 버튼 위치 조정 (중앙)
            def update_button_position():
                if thumb_label.pixmap():
                    label_width = thumb_label.width()
                    label_height = thumb_label.height()
                    # 썸네일이 중앙에 배치되므로, 버튼도 중앙에 배치
                    x = (label_width - play_button.width()) // 2
                    y = (label_height - play_button.height()) // 2
                    play_button.move(x, y)
            
            # 레이아웃이 변경될 때마다 버튼 위치 업데이트
            original_resize_event = thumb_label.resizeEvent
            def resize_event_wrapper(e):
                if original_resize_event:
                    original_resize_event(e)
                update_button_position()
            thumb_label.resizeEvent = resize_event_wrapper
            
            # 재생 버튼 클릭 이벤트 - lambda로 row를 직접 캡처 (클로저 문제 완전 해결)
            play_button.clicked.connect(lambda checked, r=row: self._on_play_button_clicked(r))
            
            # 초기 버튼 위치 설정
            QTimer.singleShot(0, update_button_position)
            
            self.table.setCellWidget(row, 1, thumb_widget)
            
            # 행 높이를 썸네일 크기에 맞게 설정 (108px 썸네일 + 여백)
            self.table.setRowHeight(row, 118)

            # 2번 컬럼 (ROI 텍스트): segment["text"]를 우선 사용 (실제 병합된 OCR 결과)
            # edited_text가 있으면 그것을 사용, 없으면 text, 둘 다 없으면 detections에서 추출
            roi_text_value = segment.get("edited_text") or segment.get("text") or roi_text_from_detections
            roi_text_item = QTableWidgetItem(roi_text_value)
            roi_text_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            roi_text_item.setTextAlignment(Qt.AlignLeft | Qt.AlignTop)
            roi_text_item.setToolTip(tooltip_text)
            self.table.setItem(row, 2, roi_text_item)

            # 3번 컬럼 (편집된 텍스트): 2번 컬럼과 동일하게 시작
            display_text = roi_text_value
            text_item = QTableWidgetItem(display_text)
            text_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            text_item.setToolTip(tooltip_text)
            self.table.setItem(row, 3, text_item)

            # start_frame과 end_frame은 이미 위에서 정의됨 (4884-4885줄)
            
            # 사용자에게는 1-based로 표시 (VFX 업계 표준)
            start_item = QTableWidgetItem(str(start_frame + 1))
            start_item.setData(Qt.UserRole, start_frame)  # 내부적으로는 0-based 유지
            self.table.setItem(row, 4, start_item)

            end_item = QTableWidgetItem(str(end_frame + 1))
            end_item.setData(Qt.UserRole, end_frame)  # 내부적으로는 0-based 유지
            self.table.setItem(row, 5, end_item)

            start_time_item = QTableWidgetItem()
            start_time_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(row, 6, start_time_item)

            end_time_item = QTableWidgetItem()
            end_time_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(row, 7, end_time_item)

            duration_item = QTableWidgetItem()
            duration_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(row, 8, duration_item)

            self.update_row_times(row)
        
        # print(f"[add_segments_to_table] 테이블 업데이트 완료: {self.table.rowCount()}행")
        self._updating = False
        
        # 이미 segment_images에 썸네일이 있는 행은 캐시에 추가 (백그라운드 로딩 건너뛰기)
        for row in range(self.table.rowCount()):
            if row < len(self.segment_images) and self.segment_images[row]:
                self._thumbnail_cache[row] = True
        
        # 병합이 필요한 행들을 하이라이트 (초기 로드 시에만)
        # 행 수가 많을 때 성능 문제가 있으므로 타이머로 지연 실행
        if self.table.rowCount() > 50:
            pass
            # 많은 행이 있으면 하이라이트를 건너뜀
            pass
        else:
            self._highlight_mergeable_rows()
        
        # 타임라인, 요약, 시퀀스 업데이트
        updated_segments = self.collect_segments()
        self.timeline.set_segments(updated_segments)
        self.update_summary()
        self.update_sequence()
        
        # print(f"[add_segments_to_table] 타임라인, 요약, 시퀀스 업데이트 완료")
        
        # 부모 VideoPlayer의 saved_edited_segments 업데이트 (저장 시 최신 상태 반영)
        parent = self.parent()
        if parent and hasattr(parent, 'saved_edited_segments'):
            parent.saved_edited_segments = updated_segments
            # print(f"[add_segments_to_table] 부모의 saved_edited_segments 업데이트 완료")

    def _is_similar_text(self, text1, text2, threshold=0.85):
        """
        두 텍스트가 유사한지 판단.
        숫자와 문자 패턴이 모두 정확히 일치하고, 구분자(공백, _, -)만 다른 경우에만 유사하다고 판단합니다.
        OCR 오류로 인한 O(문자)와 0(숫자) 혼동을 처리합니다.

        예:
        - "MS105_Q002"와 "MS105_R002" → False (Q ≠ R)
        - "MS105_A001"와 "MS105_A002" → False (숫자 1 ≠ 2)
        - "MS105_A001"와 "MS105 A001" → True (숫자와 문자가 같고, 구분자만 다름)
        - "MS105_DO08"와 "MS105_D008" → True (O를 0으로 정규화 후 D0와 D0가 일치)
        - "Q002_MS105"와 "_Q002_MS105" → True (문자와 숫자가 같고, _만 추가됨)
        """
        if text1 == text2:
            pass
            return True

        # 빈 문자열이나 <미검출>은 정확히 일치해야 함
        if not text1 or not text2 or text1 == "<미검출>" or text2 == "<미검출>":
            pass
            return text1 == text2

        import re

        # OCR 오류 처리: O와 0을 통일 (모두 0으로 변환)
        normalized_text1 = text1.upper().replace('O', '0')
        normalized_text2 = text2.upper().replace('O', '0')

        # 숫자와 문자를 분리하여 패턴 추출
        # 예: "MS105_Q002" → 문자패턴 "MSQ", 숫자 ["105", "2"]
        nums1_raw = re.findall(r'\d+', normalized_text1)
        nums2_raw = re.findall(r'\d+', normalized_text2)

        # 숫자 정규화: 앞의 0 제거 (08 → 8, 008 → 8)
        nums1 = [str(int(n)) for n in nums1_raw]
        nums2 = [str(int(n)) for n in nums2_raw]

        # 문자 패턴 추출 (숫자와 구분자 제거)
        # O를 0으로 변환했으므로 실제 문자만 남음
        letters1 = re.sub(r'[\d\s_\-\.]+', '', normalized_text1)
        letters2 = re.sub(r'[\d\s_\-\.]+', '', normalized_text2)

        # 숫자가 정규화 후에도 일치하지 않으면 병합 불가
        if nums1 != nums2:
            pass
            return False

        # 문자 패턴도 정확히 일치해야 함
        if letters1 != letters2:
            pass
            return False

        # 숫자와 문자 패턴이 모두 일치하면 유사하다고 판단
        # (구분자만 다른 경우: "MS105_A001" vs "MS105 A001")
        return True

    def _safe_copy_detections(self, detections):
        """detections를 안전하게 복사 (순환 참조 방지)"""
        if not detections:
            pass
            return []
        
        try:
            pass
            # 먼저 일반 deepcopy 시도
            return copy.deepcopy(detections)
        except (RecursionError, RuntimeError):
            pass
            # 순환 참조가 있으면 수동으로 복사
            result = []
            for det in detections:
                if isinstance(det, dict):
                    new_det = {}
                    for key, value in det.items():
                        if isinstance(value, (str, int, float, bool, type(None))):
                            new_det[key] = value
                        elif isinstance(value, list):
                            pass
                            # 리스트는 재귀적으로 복사하되 깊이 제한
                            new_det[key] = [item if not isinstance(item, (dict, list)) else str(item) for item in value]
                        elif isinstance(value, dict):
                            pass
                            # 딕셔너리는 얕은 복사만
                            new_det[key] = dict(value)
                        else:
                            pass
                            # 기타 객체는 문자열로 변환
                            new_det[key] = str(value)
                    result.append(new_det)
                else:
                    result.append(det)
            return result

    def _highlight_mergeable_rows(self):
        """병합이 필요한 행들을 노란색/녹색 계열로 하이라이트"""
        # 재귀 호출 방지
        if self._updating:
            pass
            return

        # _updating 플래그로 itemChanged 시그널로 인한 재귀 호출 방지
        self._updating = True
        try:
            pass
            # 먼저 모든 행의 배경을 초기화 (기본 색상으로)
            default_color = QColor(0, 0, 0, 0)  # 투명 (기본 배경 사용)
            default_brush = QBrush(default_color)
            for row in range(self.table.rowCount()):
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item:
                        item.setBackground(default_brush)

            # 모든 행의 편집된 텍스트 수집 (3번 컬럼)
            row_texts = {}
            for row in range(self.table.rowCount()):
                text_item = self.table.item(row, 3)
                if text_item:
                    text = text_item.text().strip()
                    if text:
                        if text not in row_texts:
                            row_texts[text] = []
                        row_texts[text].append(row)

            # 모든 행의 ROI 텍스트 수집 (2번 컬럼)
            row_roi_texts = {}
            for row in range(self.table.rowCount()):
                roi_text_item = self.table.item(row, 2)
                if roi_text_item:
                    roi_text = roi_text_item.text().strip()
                    if roi_text and roi_text != "<미검출>":
                        if roi_text not in row_roi_texts:
                            row_roi_texts[roi_text] = []
                        row_roi_texts[roi_text].append(row)

            # 유사한 텍스트가 있는 행들 찾기
            mergeable_rows = set()  # 노란색 (편집된 텍스트 기준)
            roi_mergeable_rows = set()  # 녹색 (ROI 텍스트 기준)

            # 1. 편집된 텍스트 - 정확히 같은 텍스트가 2개 이상 있는 경우
            for text, rows in row_texts.items():
                if len(rows) >= 2:
                    mergeable_rows.update(rows)

            # 2. 편집된 텍스트 - 유사한 텍스트가 있는 경우 (OCR 오류 고려)
            texts_list = list(row_texts.keys())
            for i, text1 in enumerate(texts_list):
                for text2 in texts_list[i+1:]:
                    if self._is_similar_text(text1, text2):
                        mergeable_rows.update(row_texts[text1])
                        mergeable_rows.update(row_texts[text2])

            # 3. ROI 텍스트 - 정확히 같은 텍스트가 2개 이상 있는 경우
            for roi_text, rows in row_roi_texts.items():
                if len(rows) >= 2:
                    roi_mergeable_rows.update(rows)

            # 4. ROI 텍스트 - 유사한 텍스트가 있는 경우
            roi_texts_list = list(row_roi_texts.keys())
            for i, roi_text1 in enumerate(roi_texts_list):
                for roi_text2 in roi_texts_list[i+1:]:
                    is_similar = self._is_similar_text(roi_text1, roi_text2)
                    if is_similar:
                        roi_mergeable_rows.update(row_roi_texts[roi_text1])
                        roi_mergeable_rows.update(row_roi_texts[roi_text2])

            # 우선순위: ROI 텍스트 유사도가 편집된 텍스트보다 우선 (녹색이 노란색보다 우선)
            # 노란색: 편집된 텍스트만 유사한 경우
            yellow_only_rows = mergeable_rows - roi_mergeable_rows

            # 병합 가능한 행들을 노란색 계열로 하이라이트 (편집된 텍스트만 유사)
            merge_color = QColor(150, 150, 0, 120)  # 노란색 계열 (밝은 노란색, 반투명)
            merge_brush = QBrush(merge_color)

            for row in yellow_only_rows:
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item:
                        item.setBackground(merge_brush)

            # ROI 텍스트가 유사한 행들을 녹색 계열로 하이라이트
            roi_merge_color = QColor(0, 150, 0, 100)  # 녹색 계열 (반투명)
            roi_merge_brush = QBrush(roi_merge_color)

            for row in roi_mergeable_rows:
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item:
                        item.setBackground(roi_merge_brush)
        finally:
            self._updating = False

    def collect_segments(self, skip_detections_copy=False):
        # 재귀 호출 방지
        if self._updating:
            pass
            return []
        
        segments = []
        for row in range(self.table.rowCount()):
            text_item = self.table.item(row, 3)
            start_item = self.table.item(row, 4)
            end_item = self.table.item(row, 5)
            
            # None 체크
            if not text_item or not start_item or not end_item:
                pass
                continue
            
            # 편집된 텍스트를 가져옴 (3번 컬럼)
            edited_text = text_item.text() if text_item else ""
            
            # ROI 텍스트 (원본 OCR 결과, 2번 컬럼)
            roi_text_item = self.table.item(row, 2)
            roi_text = roi_text_item.text() if roi_text_item else ""
            
            start_frame = self._safe_int(start_item)
            end_frame = self._safe_int(end_item)
            
            start_frame = max(0, min(self.total_frames - 1, start_frame))
            end_frame = max(start_frame, min(self.total_frames - 1, end_frame))
            start_time = start_frame / self.fps if self.fps else 0.0
            # end_time은 다음 프레임의 시작 시점 (표시용)
            end_time = (end_frame + 1) / self.fps if self.fps else 0.0
            # duration: end_frame까지만 포함 (다음 프레임 미포함)
            num_frames = end_frame - start_frame + 1
            duration = num_frames / self.fps if self.fps else 0.0
            
            # detections 복사는 선택적 (병합 후 UI 업데이트에서는 불필요)
            if skip_detections_copy:
                detections = self.segment_detections[row] if row < len(self.segment_detections) else []
            else:
                detections = self._safe_copy_detections(self.segment_detections[row]) if row < len(self.segment_detections) else []
            
            segment_dict = {
                "text": roi_text,  # 원본 OCR 결과 (ROI 텍스트)
                "edited_text": edited_text,  # 사용자가 편집한 텍스트
                "start_frame": start_frame,
                "end_frame": end_frame,
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration,
                "roi_image": self.segment_images[row] if row < len(self.segment_images) else None,
                "detections": detections,
            }
            
            segments.append(segment_dict)
        
        return segments

    def get_segments(self):
        if self._result_segments is not None:
            pass
            return self._result_segments
        return self.collect_segments()
    
    def export_selected_only(self):
        """선택된 구간만 내보내기"""
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not selected_rows:
            QMessageBox.information(self, "선택 없음", "내보낼 구간을 먼저 선택하세요.")
            return
        
        # 확인 메시지
        reply = QMessageBox.question(
            self,
            "선택 항목 내보내기 확인",
            f"선택된 {len(selected_rows)}개 구간을 내보내시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            pass
            return
        
        # 선택된 행들의 segments만 수집
        # collect_segments를 사용하지 않고 직접 수집 (선택된 행만 필요하므로)
        selected_segments = []
        for row in selected_rows:
            pass
            # 편집된 텍스트 (3번 컬럼)
            edited_text = self.table.item(row, 3).text() if self.table.item(row, 3) else ""
            # 원본 ROI 텍스트 (2번 컬럼)
            roi_text = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
            
            start_frame = self._safe_int(self.table.item(row, 4))
            end_frame = self._safe_int(self.table.item(row, 5))
            start_frame = max(0, min(self.total_frames - 1, start_frame))
            end_frame = max(start_frame, min(self.total_frames - 1, end_frame))
            start_time = start_frame / self.fps if self.fps else 0.0
            # end_time은 다음 프레임의 시작 시점 (표시용)
            end_time = (end_frame + 1) / self.fps if self.fps else 0.0
            # duration: end_frame까지만 포함 (다음 프레임 미포함)
            num_frames = end_frame - start_frame + 1
            duration = num_frames / self.fps if self.fps else 0.0
            selected_segments.append(
                {
                    "text": roi_text,  # 원본 OCR 결과
                    "edited_text": edited_text,  # 편집된 텍스트 (파일명으로 사용)
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "roi_image": self.segment_images[row] if row < len(self.segment_images) else None,
                    "detections": copy.deepcopy(self.segment_detections[row]) if row < len(self.segment_detections) else [],
                }
            )
        
        # 선택된 segments를 저장하고 다이얼로그 종료
        self._result_segments = selected_segments
        # 사운드 옵션 저장
        self._include_audio = self.includeAudioCheckBox.isChecked()
        # 내보내기 모드 저장
        self._export_mode = self.exportModeComboBox.currentData()
        # 비트레이트 저장 (fast 모드일 때만)
        if self._export_mode == 'fast':
            self._bitrate = self.bitrateComboBox.currentData()
        else:
            self._bitrate = None
        self.accept()
    
    def _on_export_mode_changed(self):
        """내보내기 모드 변경 시 비트레이트 선택 표시/숨김"""
        export_mode = self.exportModeComboBox.currentData()
        is_fast_mode = (export_mode == 'fast')
        self.bitrate_label.setVisible(is_fast_mode)
        self.bitrateComboBox.setVisible(is_fast_mode)

    def _safe_int(self, item):
        """
        테이블 아이템에서 정수 값을 안전하게 읽음.
        화면에 표시되는 값은 1-based이므로 -1하여 0-based로 변환.
        """
        if item is None:
            pass
            return 0
        
        # 항상 text()에서 변환 (1-based 표시값 -> 0-based 내부값)
        # UserRole은 신뢰할 수 없음 (update_row_times 등에서 덮어씌워질 수 있음)
        try:
            text = item.text().strip()
            if text:
                pass
                # 화면에 표시되는 값은 1-based이므로 -1 해야 0-based로 변환됨
                return max(0, int(text) - 1)
        except (TypeError, ValueError):
            pass
        return 0

    def update_row_times(self, row):
        # 행이 유효한지 확인
        if row < 0 or row >= self.table.rowCount():
            pass
            return
        
        # 시작/종료 프레임 아이템 확인
        start_item = self.table.item(row, 4)
        end_item = self.table.item(row, 5)
        
        if start_item is None or end_item is None:
            pass
            # 아이템이 없으면 생성
            if start_item is None:
                start_item = QTableWidgetItem("0")
                start_item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, 4, start_item)
            if end_item is None:
                end_item = QTableWidgetItem("0")
                end_item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, 5, end_item)
        
        # UserRole에 저장된 0-based 값을 우선 사용 (이미 설정된 값 보존)
        original_start_frame = start_item.data(Qt.UserRole)
        original_end_frame = end_item.data(Qt.UserRole)
        
        start_frame = original_start_frame
        if start_frame is None:
            pass
            # UserRole이 없으면 텍스트에서 읽기 (1-based이므로 -1)
            start_frame = self._safe_int(start_item) - 1
        
        end_frame = original_end_frame
        if end_frame is None:
            pass
            # UserRole이 없으면 텍스트에서 읽기 (1-based이므로 -1)
            end_frame = self._safe_int(end_item) - 1
        
        start_frame = max(0, min(self.total_frames - 1, start_frame))
        end_frame = max(start_frame, min(self.total_frames - 1, end_frame))
        start_time = start_frame / self.fps if self.fps else 0.0
        end_time = (end_frame + 1) / self.fps if self.fps else 0.0
        num_frames = end_frame - start_frame + 1  # 구간 길이(프레임)

        for column, value in zip(
            [6, 7, 8],
            [f"{start_time:.3f}", f"{end_time:.3f}", str(num_frames)],
        ):
            item = self.table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.table.setItem(row, column, item)
            item.setText(value)

        # UserRole 데이터 설정 (아이템이 존재하는지 다시 확인)
        # 중요: 이미 UserRole이 설정되어 있으면 절대 덮어쓰지 않음 (populate_table_row에서 설정한 값 보존)
        start_item = self.table.item(row, 4)
        end_item = self.table.item(row, 5)
        if start_item is not None:
            pass
            # 원본 UserRole 값이 있으면 그것을 유지, 없을 때만 새로 설정
            if original_start_frame is not None:
                pass
                # 원본 값이 있으면 복원 (계산된 값으로 덮어쓰지 않음)
                start_item.setData(Qt.UserRole, original_start_frame)
            elif start_item.data(Qt.UserRole) is None:
                pass
                # UserRole이 없을 때만 설정
                start_item.setData(Qt.UserRole, start_frame)
        if end_item is not None:
            pass
            # 원본 UserRole 값이 있으면 그것을 유지, 없을 때만 새로 설정
            if original_end_frame is not None:
                pass
                # 원본 값이 있으면 복원 (계산된 값으로 덮어쓰지 않음)
                end_item.setData(Qt.UserRole, original_end_frame)
            elif end_item.data(Qt.UserRole) is None:
                pass
                # UserRole이 없을 때만 설정
                end_item.setData(Qt.UserRole, end_frame)

    def on_item_changed(self, item):
        if self._updating:
            pass
            return
        row = item.row()
        column = item.column()
        
        # 텍스트가 변경되면 하이라이트 업데이트 (성능을 위해 비활성화)
        # 필요 시 사용자가 수동으로 "하이라이트 새로고침" 버튼을 추가할 수 있음
        # if column == 3:
        #     self._highlight_mergeable_rows()

        if column in (4, 5):
            other_column = 5 if column == 4 else 4
            # 사용자 입력은 1-based이므로 text()에서 직접 읽어 0-based로 변환
            try:
                value_display = int(item.text())
            except (TypeError, ValueError):
                value_display = 1  # 기본값 1-based
            value = value_display - 1  # 내부 0-based
            
            # 다른 컬럼은 UserRole에서 0-based 값을 읽음
            other_value = self._safe_int(self.table.item(row, other_column))

            value = max(0, min(self.total_frames - 1, value))
            if column == 4 and value > other_value:
                value = other_value
            elif column == 5 and value < other_value:
                value = other_value

            self._updating = True
            item.setText(str(value + 1))  # 1-based로 표시
            item.setData(Qt.UserRole, value)  # 0-based로 저장
            self._updating = False
            self.update_row_times(row)

        # collect_segments를 한 번만 호출하여 재사용 (재귀 호출 방지)
        segments = self.collect_segments()
        if segments:  # segments가 있을 때만 업데이트
            # _updating 플래그로 재귀 호출 방지
            self._updating = True
            try:
                self.timeline.set_segments(segments)
                self.update_summary_with_segments(segments)
                self.update_sequence_with_segments(segments)
                
                # 부모 VideoPlayer의 saved_edited_segments 업데이트 (저장 시 최신 상태 반영)
                parent = self.parent()
                if parent and hasattr(parent, 'saved_edited_segments'):
                    parent.saved_edited_segments = segments
            finally:
                self._updating = False
        
        self.update_preview(row)
        
        # WebSocket 동기화 (디바운싱 적용: 50ms 후 전송하여 즉각적인 반응 속도 보장)
        self._broadcast_timer.stop()  # 기존 타이머 취소
        self._broadcast_timer.start(50)  # 50ms 후 전송

    def save_history(self):
        """현재 상태를 히스토리에 저장"""
        try:
            pass
            # 현재 테이블 상태를 깊은 복사로 저장
            current_state = {
                'segments': self.collect_segments(skip_detections_copy=False),
                'images': list(self.segment_images),
                'detections': [copy.deepcopy(d) for d in self.segment_detections],
                'thumbnail_slider_value': self.thumbnail_size_slider.value() if hasattr(self, 'thumbnail_size_slider') else 2
            }
            self.undo_stack.append(current_state)
            # 최대 히스토리 개수 유지
            if len(self.undo_stack) > self.max_history:
                self.undo_stack.pop(0)
            # redo 스택 초기화 (새 작업이 수행되면 redo 불가)
            self.redo_stack.clear()
            # 버튼 상태 업데이트
            self.update_undo_redo_buttons()
        except Exception as e:
            print(f"히스토리 저장 실패: {e}")
    
    def undo_action(self):
        """실행 취소"""
        if not self.undo_stack:
            pass
            return

        try:
            pass
            # 현재 상태를 redo 스택에 저장 (빠른 복사 사용)
            current_state = {
                'segments': self.collect_segments(skip_detections_copy=True),  # 이미 복사된 detections 사용
                'images': list(self.segment_images),
                'detections': [copy.deepcopy(d) for d in self.segment_detections],
                'thumbnail_slider_value': self.thumbnail_size_slider.value() if hasattr(self, 'thumbnail_size_slider') else 2
            }
            self.redo_stack.append(current_state)
            
            # 이전 상태 복원
            previous_state = self.undo_stack.pop()
            self.restore_state(previous_state)
            
            # 버튼 상태 업데이트
            self.update_undo_redo_buttons()
            
            # 웹 UI에 변경사항 브로드캐스트 (비동기로 실행하여 UI 반응성 향상)
            QTimer.singleShot(0, self.broadcast_segments_change)
        except Exception as e:
            QMessageBox.warning(self, "실행 취소 실패", f"실행 취소 중 오류가 발생했습니다:\n{e}")
    
    def redo_action(self):
        """다시 실행"""
        if not self.redo_stack:
            pass
            return

        try:
            pass
            # 현재 상태를 undo 스택에 저장 (빠른 복사 사용)
            current_state = {
                'segments': self.collect_segments(skip_detections_copy=True),  # 이미 복사된 detections 사용
                'images': list(self.segment_images),
                'detections': [copy.deepcopy(d) for d in self.segment_detections],
                'thumbnail_slider_value': self.thumbnail_size_slider.value() if hasattr(self, 'thumbnail_size_slider') else 2
            }
            self.undo_stack.append(current_state)
            
            # 다음 상태 복원
            next_state = self.redo_stack.pop()
            self.restore_state(next_state)
            
            # 버튼 상태 업데이트
            self.update_undo_redo_buttons()
            
            # 웹 UI에 변경사항 브로드캐스트 (비동기로 실행하여 UI 반응성 향상)
            QTimer.singleShot(0, self.broadcast_segments_change)
        except Exception as e:
            QMessageBox.warning(self, "다시 실행 실패", f"다시 실행 중 오류가 발생했습니다:\n{e}")
    
    def restore_state(self, state):
        """저장된 상태를 테이블에 복원"""
        self._updating = True
        self.table.setUpdatesEnabled(False)
        
        try:
            pass
            # 테이블 초기화
            self.table.clearContents()
            self.table.setRowCount(0)
            
            # 이미지 및 detections 복원
            self.segment_images = state['images']
            self.segment_detections = state['detections']

            # 썸네일 슬라이더 값 복원 (테이블 행 추가 전에 설정)
            saved_slider_value = state.get('thumbnail_slider_value', 2)
            if hasattr(self, 'thumbnail_size_slider'):
                pass
                # valueChanged 시그널을 일시적으로 차단하여 중복 업데이트 방지
                self.thumbnail_size_slider.blockSignals(True)
                self.thumbnail_size_slider.setValue(saved_slider_value)
                self.thumbnail_size_slider.blockSignals(False)
                # 슬라이더 라벨도 업데이트
                if hasattr(self, 'thumbnail_size_value_label'):
                    is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']
                    if is_ocr_mode:
                        pass
                        # OCR 모드: 동적 계산 (첫 이미지에서 결정됨)
                        self.thumbnail_size_value_label.setText(f"{saved_slider_value}x")
                    else:
                        pass
                        # 애니매틱 모드: 고정 비율
                        base_width = 96
                        base_height = 54
                        thumbnail_width = base_width * saved_slider_value
                        thumbnail_height = base_height * saved_slider_value
                        self.thumbnail_size_value_label.setText(f"{thumbnail_width}×{thumbnail_height}")

            # 세그먼트 복원
            segments = state['segments']
            self.table.setRowCount(len(segments))

            # 모든 행을 한 번에 처리 (성능 최적화)
            for row, segment in enumerate(segments):
                self.populate_table_row(row, segment)
            
            # 씬 리스트 업데이트
            self._update_scene_list()
            
            # UI 업데이트 (한 번에 처리)
            self.timeline.set_segments(segments)
            self.update_summary_with_segments(segments)
            self.update_sequence_with_segments(segments)
            
            # 부모의 saved_edited_segments 업데이트
            parent = self.parent()
            if parent and hasattr(parent, 'saved_edited_segments'):
                parent.saved_edited_segments = segments
        
        finally:
            self._updating = False
            self.table.setUpdatesEnabled(True)
            # viewport 업데이트는 한 번만 수행
            self.table.viewport().update()
    
    def populate_table_row(self, row, segment):
        """단일 행에 세그먼트 데이터를 채움 (restore_state용)"""
        # 행 번호
        index_item = QTableWidgetItem(str(row + 1))
        index_item.setFlags(index_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 0, index_item)
        
        # ROI 샘플 (이미지) - add_segments_to_table과 동일한 로직 사용
        roi_bytes = self.segment_images[row] if row < len(self.segment_images) else None
        detections = self.segment_detections[row] if row < len(self.segment_detections) else []
        
        # 썸네일을 담을 위젯 (재생 버튼 오버레이용)
        thumb_widget = QWidget()
        thumb_layout = QVBoxLayout(thumb_widget)
        thumb_layout.setContentsMargins(0, 0, 0, 0)
        thumb_layout.setSpacing(0)
        
        thumb_label = QLabel()
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setStyleSheet("QLabel { background: #050505; border: 1px solid #222; color: #555; }")

        # OCR 모드에 따라 썸네일 크기 결정
        is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']

        # 슬라이더 값 가져오기
        slider_value = self.thumbnail_size_slider.value() if hasattr(self, 'thumbnail_size_slider') else 2

        # 원본 pixmap 생성 (슬라이더 성능 최적화용)
        original_pixmap = self._pixmap_with_boxes(roi_bytes, detections, None)

        if is_ocr_mode:
            pass
            # OCR 모드: 실제 이미지 종횡비에 맞게 조정 (슬라이더 값 반영)
            if original_pixmap:
                orig_width = original_pixmap.width()
                orig_height = original_pixmap.height()
                base_height = 40
                target_height = base_height * slider_value
                aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                target_width = int(target_height * aspect_ratio)
                thumbnail_size = QSize(target_width, target_height)
                self.table.setRowHeight(row, target_height + 10)
                if row == 0:
                    self.table.setColumnWidth(1, target_width + 10)
                pixmap = original_pixmap.scaled(
                    thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            else:
                pixmap = None
        else:
            pass
            # 애니매틱 모드: 슬라이더 값 반영
            base_width = 96
            base_height = 54
            thumbnail_width = base_width * slider_value
            thumbnail_height = base_height * slider_value
            thumbnail_size = QSize(thumbnail_width, thumbnail_height)
            row_height = thumbnail_height + 10
            column_width = thumbnail_width + 10
            self.table.setRowHeight(row, row_height)
            if row == 0:
                self.table.setColumnWidth(1, column_width)
            if original_pixmap:
                pixmap = original_pixmap.scaled(
                    thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            else:
                pixmap = None

        if pixmap:
            thumb_label.setPixmap(pixmap)
            # 원본 pixmap 캐싱 (슬라이더 성능 최적화용)
            thumb_label.setProperty('original_pixmap', original_pixmap)
        else:
            thumb_label.setText("이미지 없음")
        
        # tooltip 생성
        start_frame = segment.get("start_frame", 0)
        end_frame = segment.get("end_frame", 0)
        tooltip_text = f"프레임: {start_frame + 1} → {end_frame + 1}"
        thumb_label.setToolTip(tooltip_text)
        thumb_layout.addWidget(thumb_label)
        
        self.table.setCellWidget(row, 1, thumb_widget)
        
        # ROI 텍스트 (원본 OCR)
        roi_text_value = segment.get("edited_text") or segment.get("text") or ""
        if not roi_text_value or roi_text_value == "<미검출>":
            if segment.get("detections"):
                roi_text_value = " ".join([d.get("text", "") for d in segment["detections"]]).strip() or "<미검출>"
        roi_text_item = QTableWidgetItem(roi_text_value)
        roi_text_item.setFlags(roi_text_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 2, roi_text_item)
        
        # 편집 텍스트
        display_text = segment.get("edited_text") or segment.get("text") or ""
        if not display_text or display_text == "<미검출>":
            if segment.get("detections"):
                display_text = " ".join([d.get("text", "") for d in segment["detections"]]).strip() or "<미검출>"
        edit_text_item = QTableWidgetItem(display_text)
        self.table.setItem(row, 3, edit_text_item)
        
        # 프레임 및 시간 정보
        start_frame = segment.get("start_frame", 0)
        end_frame = segment.get("end_frame", 0)
        
        # 디버깅: segment에서 프레임 정보 확인
        if "start_frame" not in segment:
            pass
            # print(f"[populate_table_row] 경고: segment에 'start_frame' 키가 없음. segment.keys()={list(segment.keys())}")
        
        # 프레임 값 확인 및 변환
        start_frame_int = int(start_frame) if start_frame is not None else 0
        end_frame_int = int(end_frame) if end_frame is not None else 0
        
        # 디버깅 로그는 성능 최적화를 위해 제거 (필요시 DEBUG 플래그로 활성화 가능)
        # DEBUG_POPULATE = False  # 디버깅이 필요할 때만 True로 설정
        
        start_frame_item = QTableWidgetItem(str(start_frame_int + 1))  # 1-based 표시
        start_frame_item.setData(Qt.UserRole, start_frame_int)  # 내부적으로는 0-based 유지
        end_frame_item = QTableWidgetItem(str(end_frame_int + 1))  # 1-based 표시
        end_frame_item.setData(Qt.UserRole, end_frame_int)  # 내부적으로는 0-based 유지
        
        self.table.setItem(row, 4, start_frame_item)
        self.table.setItem(row, 5, end_frame_item)
        
        # setItem 후 값이 바뀌었다면 다시 설정 (안전장치)
        stored_start_after_setitem = self.table.item(row, 4).data(Qt.UserRole)
        stored_end_after_setitem = self.table.item(row, 5).data(Qt.UserRole)
        if stored_start_after_setitem != start_frame_int:
            self.table.item(row, 4).setData(Qt.UserRole, start_frame_int)
        if stored_end_after_setitem != end_frame_int:
            self.table.item(row, 5).setData(Qt.UserRole, end_frame_int)
        
        # 시간 정보는 update_row_times에서 자동 계산
        # update_row_times는 이미 UserRole이 설정되어 있으면 덮어쓰지 않도록 수정됨
        self.update_row_times(row)
        
        # update_row_times 호출 후 값이 변경되었는지 확인하고 복원 (안전장치)
        stored_start_after_update = self.table.item(row, 4).data(Qt.UserRole)
        stored_end_after_update = self.table.item(row, 5).data(Qt.UserRole)
        if stored_start_after_update != start_frame_int:
            self.table.item(row, 4).setData(Qt.UserRole, start_frame_int)
        if stored_end_after_update != end_frame_int:
            self.table.item(row, 5).setData(Qt.UserRole, end_frame_int)
    
    def update_undo_redo_buttons(self):
        """Undo/Redo 버튼 활성화 상태 업데이트"""
        self.undoButton.setEnabled(len(self.undo_stack) > 0)
        self.redoButton.setEnabled(len(self.redo_stack) > 0)

    def smart_merge_by_scene(self):
        """스마트 병합 다이얼로그 표시"""
        # 다이얼로그 생성
        dialog = QDialog(self)
        dialog.setWindowTitle("스마트 병합")
        dialog.setMinimumSize(300, 150)
        
        layout = QVBoxLayout(dialog)
        
        label = QLabel("병합 방식을 선택하세요:")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        
        # 버튼 영역
        button_layout = QHBoxLayout()
        
        # Standard 버튼 (기존 엄격한 로직)
        std_btn = QPushButton("Standard\n(기본)")
        std_btn.setMinimumHeight(50)
        std_btn.setToolTip("기존 방식: 'Scene 8 - Panel A'와 같이 공백으로 구분된 형식만 병합합니다.\n'SCENE001' 등은 무시합니다.")
        std_btn.clicked.connect(lambda: [dialog.accept(), self._process_smart_merge_request(mode='legacy')])
        button_layout.addWidget(std_btn)
        
        # SCENE 버튼 (새로운 유연한 로직)
        scene_btn = QPushButton("SCENE\n(확장)")
        scene_btn.setMinimumHeight(50)
        scene_btn.setToolTip("확장 방식: 'SCENE001', 'Scene_01' 등 다양한 형식을 모두 병합합니다.")
        scene_btn.clicked.connect(lambda: [dialog.accept(), self._process_smart_merge_request(mode='new')])
        button_layout.addWidget(scene_btn)
        
        layout.addLayout(button_layout)
        
        dialog.exec_()

    def _process_smart_merge_request(self, mode='new'):
        """Scene 번호가 같은 연속된 항목들을 자동으로 병합 (모드에 따라 정규식 변경)"""
        import re

        
        row_count = self.table.rowCount()
        if row_count < 2:
            QMessageBox.information(self, "스마트 병합", "병합할 구간이 충분하지 않습니다.")
            return
        
        # 히스토리 저장 (병합 전 상태)
        self.save_history()
        
        # 모든 행에서 Scene 번호 추출
        scene_numbers = []
        for row in range(row_count):
            edit_text_item = self.table.item(row, 3)
            if not edit_text_item:
                scene_numbers.append(None)
                continue
            
            text = edit_text_item.text().strip()
            
            match = None
            if mode == 'legacy':
                # 기존 엄격한 패턴: "Scene 8 - Panel A" (공백 필수)
                # "SCENE001" 등은 무시됨
                match = re.search(r'Scene\s+(\d+)', text, re.IGNORECASE)
            else:
                # 새로운 유연한 패턴: "SCENE001", "Scene_01" 등 허용
                match = re.search(r'Scene\s*[-_]?\s*(\d+)', text, re.IGNORECASE)
                
            if match:
                scene_num = str(int(match.group(1)))  # 앞의 0 제거
                scene_numbers.append(scene_num)
            else:
                scene_numbers.append(None)
        
        # 연속된 행들을 Scene 번호로 그룹화
        groups = []  # [(scene_num, [row_indices])]
        current_group = None
        
        for row in range(row_count):
            scene_num = scene_numbers[row]
            
            if scene_num is None:
                pass
                # Scene 번호가 없으면 현재 그룹 종료
                if current_group and len(current_group[1]) >= 2:
                    groups.append(current_group)
                current_group = None
            else:
                if current_group is None:
                    pass
                    # 새 그룹 시작
                    current_group = (scene_num, [row])
                elif current_group[0] == scene_num:
                    pass
                    # 같은 Scene 번호면 현재 그룹에 추가
                    current_group[1].append(row)
                else:
                    pass
                    # Scene 번호가 바뀌면 현재 그룹 저장하고 새 그룹 시작
                    if len(current_group[1]) >= 2:
                        groups.append(current_group)
                    current_group = (scene_num, [row])
        
        # 마지막 그룹 처리
        if current_group and len(current_group[1]) >= 2:
            groups.append(current_group)
        
        if not groups:
            QMessageBox.information(
                self, 
                "스마트 병합", 
                "병합할 그룹이 없습니다.\n\n"
                "같은 Scene 번호를 가진 연속된 항목이 2개 이상 있어야 합니다.\n"
                "예: 'Scene 8 - Panel A', 'Scene 8 - Panel B' → 자동 병합"
            )
            return
        
        # 사용자 확인 (스크롤 가능한 커스텀 다이얼로그 사용)
        merge_count = sum(len(group[1]) for group in groups)
        
        # 커스텀 다이얼로그 생성
        dialog = QDialog(self)
        dialog.setWindowTitle("스마트 병합 확인")
        dialog.setMinimumSize(400, 200)
        
        layout = QVBoxLayout(dialog)
        
        # 설명 라벨
        info_label = QLabel(f"{len(groups)}개 그룹, 총 {merge_count}개 항목을 병합하시겠습니까?")
        info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(info_label)
        
        # 버튼 영역
        button_layout = QHBoxLayout()
        
        # 병합 실행 버튼
        merge_btn = QPushButton("병합 실행")
        merge_btn.setMinimumHeight(40)
        merge_btn.clicked.connect(lambda: [dialog.accept(), self._perform_smart_merge(groups)])
        button_layout.addWidget(merge_btn)
        
        # 취소 버튼
        cancel_btn = QPushButton("취소")
        cancel_btn.setMinimumHeight(40)
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        dialog.exec_()

    def _perform_smart_merge(self, groups):
        """스마트 병합 실행 (다이얼로그 확인 후)"""
        # 전체 병합 과정을 _updating으로 감싸서 성능 향상
        
        # 전체 병합 과정을 _updating으로 감싸서 성능 향상
        self._updating = True
        self.table.setUpdatesEnabled(False)
        
        # 병합된 행들의 인덱스를 추적 (하이라이트 제거용)
        merged_first_rows = []
        
        try:
            pass
            # 역순으로 병합 (뒤에서부터 병합해야 인덱스가 꼬이지 않음)
            for scene_num, rows in reversed(groups):
                if len(rows) < 2:
                    pass
                    continue
                
                # 첫 번째 행 인덱스 (병합된 결과가 들어갈 위치)
                first_row = rows[0]
                # 병합된 행 추적 (하이라이트 제거용)
                merged_first_rows.append(first_row)
                
                # 데이터 수집
                start_frames = []
                end_frames = []
                for row in rows:
                    start_frame_item = self.table.item(row, 4)
                    end_frame_item = self.table.item(row, 5)
                    if start_frame_item and start_frame_item.data(Qt.UserRole) is not None:
                        start_frames.append(int(start_frame_item.data(Qt.UserRole)))
                    if end_frame_item and end_frame_item.data(Qt.UserRole) is not None:
                        end_frames.append(int(end_frame_item.data(Qt.UserRole)))
                
                start_frame = min(start_frames) if start_frames else 0
                end_frame = max(end_frames) if end_frames else 0
                
                # 편집 텍스트: Panel 부분 제거, Scene 번호만 유지
                edit_text = f"Scene {scene_num}"
                
                # 첫 번째 행의 편집 텍스트 업데이트
                edit_text_item = self.table.item(first_row, 3)
                if edit_text_item:
                    edit_text_item.setText(edit_text)
                
                # detections 병합
                merged_detections = []
                for row in rows:
                    if row < len(self.segment_detections):
                        merged_detections.extend(self.segment_detections[row])
                
                # 시간 계산
                start_time = start_frame / self.fps if self.fps else 0.0
                end_time = (end_frame + 1) / self.fps if self.fps else 0.0
                num_frames = end_frame - start_frame + 1  # 구간 길이(프레임) - 정수
                
                # 첫 번째 행 업데이트
                self.table.item(first_row, 5).setText(str(end_frame + 1))
                self.table.item(first_row, 5).setData(Qt.UserRole, end_frame)
                self.table.item(first_row, 6).setText(f"{start_time:.3f}")
                self.table.item(first_row, 7).setText(f"{end_time:.3f}")
                self.table.item(first_row, 8).setText(str(num_frames))  # 프레임 단위 정수로 표시
                
                # detections 업데이트
                self.segment_detections[first_row] = merged_detections
                
                # 썸네일 이미지 업데이트 (기존대로: 첫 번째 행의 썸네일 사용, 다이얼로그 없음)
                is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']
                thumbnail_row = rows[0]  # 첫 번째 행 사용
                
                if is_ocr_mode:
                    pass
                    # OCR 모드: 첫 번째 행의 썸네일 사용
                    merged_image = self.segment_images[thumbnail_row] if thumbnail_row < len(self.segment_images) else None
                    if merged_image:
                        pass
                        # segment_images 업데이트
                        if first_row < len(self.segment_images):
                            self.segment_images[first_row] = merged_image
                        else:
                            pass
                            # 리스트가 짧으면 확장
                            while len(self.segment_images) <= first_row:
                                self.segment_images.append(None)
                            self.segment_images[first_row] = merged_image
                        
                        # 썸네일 위젯 업데이트
                        thumb_widget = self.table.cellWidget(first_row, 1)
                        if thumb_widget:
                            thumb_label = thumb_widget.findChild(QLabel)
                            if thumb_label:
                                pass
                                # 첫 번째 행의 detections 사용
                                selected_detections = self.segment_detections[thumbnail_row] if thumbnail_row < len(self.segment_detections) else merged_detections
                                
                                # 원본 pixmap 생성
                                original_pixmap = self._pixmap_with_boxes(merged_image, selected_detections, None)
                                
                                if original_pixmap:
                                    orig_width = original_pixmap.width()
                                    orig_height = original_pixmap.height()
                                    
                                    # 현재 슬라이더 값에 따라 썸네일 크기 계산 (일반 썸네일과 동일하게)
                                    slider_value = self.thumbnail_size_slider.value() if hasattr(self, 'thumbnail_size_slider') else 2
                                    base_height = 40
                                    target_height = base_height * slider_value  # 슬라이더 값에 따라 40~160
                                    aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                                    target_width = int(target_height * aspect_ratio)
                                    thumbnail_size = QSize(target_width, target_height)
                                    pixmap = original_pixmap.scaled(thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                else:
                                    pixmap = None
                                
                                if pixmap:
                                    thumb_label.setPixmap(pixmap)
                                    thumb_label.setProperty('original_pixmap', original_pixmap)
                                else:
                                    thumb_label.setText("이미지 없음")
                else:
                    pass
                    # 애니매틱 모드: 병합된 씬의 시작 프레임에서 썸네일 추출
                    if self.video_path and os.path.exists(self.video_path):
                        merged_thumbnail = self._extract_frame_thumbnail(self.video_path, start_frame)
                        if merged_thumbnail:
                            pass
                            # segment_images 업데이트
                            if first_row < len(self.segment_images):
                                self.segment_images[first_row] = merged_thumbnail
                            else:
                                pass
                                # 리스트가 짧으면 확장
                                while len(self.segment_images) <= first_row:
                                    self.segment_images.append(None)
                                self.segment_images[first_row] = merged_thumbnail
                            
                            # 썸네일 위젯 업데이트
                            thumb_widget = self.table.cellWidget(first_row, 1)
                            if thumb_widget:
                                thumb_label = thumb_widget.findChild(QLabel)
                                if thumb_label:
                                    pass
                                    # 원본 pixmap 생성
                                    original_pixmap = self._pixmap_with_boxes(merged_thumbnail, merged_detections, None)
                                    
                                    # 애니매틱 모드: 기존 방식 유지
                                    thumbnail_size = QSize(192, 108)
                                    pixmap = original_pixmap
                                    if pixmap:
                                        pixmap = pixmap.scaled(
                                            thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                                        )
                                    
                                    if pixmap:
                                        thumb_label.setPixmap(pixmap)
                                        thumb_label.setProperty('original_pixmap', original_pixmap)
                
                # 나머지 행들 삭제 (역순으로)
                for row in reversed(rows[1:]):
                    self.table.removeRow(row)
                    if 0 <= row < len(self.segment_images):
                        del self.segment_images[row]
                    if 0 <= row < len(self.segment_detections):
                        del self.segment_detections[row]
            
            # 전체 재인덱싱
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item:
                    item.setText(str(row + 1))
            
            # 병합된 행들의 하이라이트 제거 (녹색/노란색 하이라이트 초기화)
            default_color = QColor(0, 0, 0, 0)  # 투명 (기본 배경 사용)
            default_brush = QBrush(default_color)
            for first_row in merged_first_rows:
                # 행 인덱스가 유효한지 확인 (병합 과정에서 삭제된 행이 아닌지)
                if 0 <= first_row < self.table.rowCount():
                    for col in range(self.table.columnCount()):
                        item = self.table.item(first_row, col)
                        if item:
                            item.setBackground(default_brush)
        
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()
            self._updating = False
        
        # 첫 번째 행 선택
        if self.table.rowCount() > 0:
            pass
            # 스마트 병합 후 프리뷰 프레임 리셋 (이전 씬의 프레임이 표시되지 않도록)
            if hasattr(self, '_last_preview_row'):
                self._last_preview_row = None
            if hasattr(self, '_last_selected_row'):
                self._last_selected_row = None
            self._preview_current_display_frame = None
            self.table.selectRow(0)
            self.update_preview(0, immediate=True)
        
        # 타임라인, 요약, 시퀀스 업데이트
        segments = self.collect_segments(skip_detections_copy=True)
        self.timeline.set_segments(segments)
        self.update_summary_with_segments(segments)
        self.update_sequence_with_segments(segments)
        
        # 부모 VideoPlayer의 saved_edited_segments 업데이트
        parent = self.parent()
        if parent and hasattr(parent, 'saved_edited_segments'):
            parent.saved_edited_segments = segments
        
        # Undo/Redo 버튼 업데이트
        self.update_undo_redo_buttons()
        
        # 씬 이름 자동 리네임 (애니매틱/애니매틱2 모드일 때만)
        if getattr(self, 'ocr_mode', 'titmouse') in ['animatic', 'animatic2']:
            self._renumber_scene_names()
        
        # 씬 리스트 업데이트
        self._update_scene_list()
        
        QMessageBox.information(
            self,
            "스마트 병합 완료",
            f"{len(groups)}개 그룹이 병합되었습니다."
        )

        # 실시간 동기화 (비동기로 실행하여 UI 반응성 향상)
        QTimer.singleShot(0, self.broadcast_segments_change)

    def remove_selected_rows(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
        if not selected_rows:
            QMessageBox.information(self, "삭제할 구간 없음", "삭제할 구간을 선택하세요.")
            return
        
        # 히스토리 저장 (삭제 전 상태)
        self.save_history()
        
        # 전체 삭제 과정을 _updating으로 감싸서 성능 향상 (UI 업데이트 억제)
        self._updating = True
        try:
            pass
            # 테이블 업데이트를 일시 중지하여 성능 향상
            self.table.setUpdatesEnabled(False)
            try:
                for row in selected_rows:
                    self.table.removeRow(row)
                    if 0 <= row < len(self.segment_images):
                        del self.segment_images[row]
                    if 0 <= row < len(self.segment_detections):
                        del self.segment_detections[row]

                # Lazy loading 캐시 재조정: 삭제된 행 제거 및 인덱스 재조정 (최적화)
                if hasattr(self, '_thumbnail_cache'):
                    pass
                    # 삭제된 행을 set으로 변환하여 O(1) 룩업
                    deleted_rows_set = set(selected_rows)
                    # 삭제된 행 개수를 카운트하여 한 번에 조정
                    new_cache = {}
                    for cached_row, value in self._thumbnail_cache.items():
                        pass
                        # 삭제되지 않은 행만 처리
                        if cached_row not in deleted_rows_set:
                            pass
                            # 삭제된 행보다 아래에 있는 행의 개수만큼 인덱스 감소
                            # binary search를 사용하여 O(log n)으로 개선
                            import bisect
                            offset = bisect.bisect_left(selected_rows, cached_row)
                            adjusted_row = cached_row - offset
                            new_cache[adjusted_row] = value
                    self._thumbnail_cache = new_cache

                # 재인덱싱 (setUpdatesEnabled(False) 내에서 수행하여 성능 최적화)
                self.reindex_rows()
            finally:
                self.table.setUpdatesEnabled(True)
                # 명시적으로 테이블 업데이트 강제
                self.table.viewport().update()

            # 씬 이름 자동 리네임 (애니매틱 모드일 때만)
            if getattr(self, 'ocr_mode', 'titmouse') in ['animatic', 'animatic2']:
                self._renumber_scene_names()
            # 씬 리스트 증분 업데이트 (첫 번째 삭제된 행부터 끝까지)
            if selected_rows:
                first_deleted_row = selected_rows[-1]  # 역순 삭제이므로 마지막 원소가 가장 작은 행 번호
                self._update_scene_list(affected_rows=(first_deleted_row, self.table.rowCount()))
        finally:
            self._updating = False
        
        # collect_segments를 한 번만 호출하여 재사용 (detections 복사 생략으로 성능 향상)
        updated_segments = self.collect_segments(skip_detections_copy=True)
        
        # 타임라인, 요약, 시퀀스를 한 번에 업데이트
        self.timeline.set_segments(updated_segments)
        self.update_summary_with_segments(updated_segments)
        self.update_sequence_with_segments(updated_segments)
        
        if self.table.rowCount() > 0:
            target_row = min(selected_rows[-1], self.table.rowCount() - 1)
            # 삭제 후 프리뷰 프레임 리셋 (이전 씬의 프레임이 표시되지 않도록)
            self._preview_current_display_frame = None
            if hasattr(self, '_last_preview_row'):
                self._last_preview_row = None
            if hasattr(self, '_last_selected_row'):
                self._last_selected_row = None
            self.table.selectRow(target_row)
            self.update_preview(target_row, immediate=True)
        else:
            self.update_preview(-1, immediate=True)
        
        # 부모 VideoPlayer의 saved_edited_segments 업데이트 (저장 시 최신 상태 반영)
        parent = self.parent()
        if parent and hasattr(parent, 'saved_edited_segments'):
            parent.saved_edited_segments = updated_segments

        # 실시간 동기화 (비동기로 실행하여 UI 반응성 향상)
        QTimer.singleShot(0, self.broadcast_segments_change)

    def batch_rename_segments(self):
        """편집 텍스트를 패턴 매칭으로 일괄 변경"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QCheckBox, QPushButton, QHBoxLayout, QTextEdit
        
        # 리네임 다이얼로그 생성
        dialog = QDialog(self)
        dialog.setWindowTitle("일괄 리네임")
        dialog.setMinimumWidth(500)
        
        layout = QVBoxLayout(dialog)
        
        # 설명 라벨
        info_label = QLabel(
            "편집 텍스트를 패턴 매칭으로 일괄 변경합니다.\n"
            "예: 'Scene 377 - Panel A' → 'Scene 377'로 변경하려면\n"
            "찾을 텍스트: ' - Panel A', 바꿀 텍스트: '' (빈 문자열)\n\n"
            "정규식 예시:\n"
            "• ' - Pan[ae]t!? .*' → Panel/Panet/Panel!/Panet! 등 모든 변형 매칭\n"
            "• ' - Panel.*' → Panel로 시작하는 모든 것"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # 찾을 텍스트
        find_label = QLabel("찾을 텍스트 (또는 정규식 패턴):")
        layout.addWidget(find_label)
        find_input = QLineEdit()
        find_input.setPlaceholderText("예: ' - Panel A' 또는 정규식: ' - Pan[ae]t!? .*' (Panel/Panet/Panel! 등 모두 매칭)")
        layout.addWidget(find_input)
        
        # 바꿀 텍스트
        replace_label = QLabel("바꿀 텍스트:")
        layout.addWidget(replace_label)
        replace_input = QLineEdit()
        replace_input.setPlaceholderText("예: '' (빈 문자열로 제거)")
        layout.addWidget(replace_input)
        
        # 정규식 사용 옵션
        regex_checkbox = QCheckBox("정규식 사용")
        regex_checkbox.setToolTip(
            "체크하면 찾을 텍스트를 정규식 패턴으로 해석합니다.\n"
            "예: ' - Pan[ae]t!? .*' → Panel/Panet/Panel!/Panet! 등 모든 변형 매칭\n"
            "    [ae] = a 또는 e, !? = !가 있거나 없거나, .* = 나머지 모든 문자"
        )
        layout.addWidget(regex_checkbox)
        
        # 빠른 패턴 버튼들
        quick_patterns_layout = QHBoxLayout()
        quick_patterns_label = QLabel("빠른 패턴:")
        quick_patterns_layout.addWidget(quick_patterns_label)
        
        def set_pattern(pattern, use_regex_val=True):
            find_input.setText(pattern)
            regex_checkbox.setChecked(use_regex_val)
            update_preview()
        
        # 하이픈 이후 모든 것 제거 (Scene 번호만 남기기)
        scene_only_btn = QPushButton("Scene 번호만 남기기")
        scene_only_btn.setToolTip(
            "정규식: '-.*' → 하이픈 이후 모든 문자 제거, Scene-번호는 Scene 번호로 변환\n"
            "예: 'Scene 638 - Panel! A' → 'Scene 638'\n"
            "    'Scene.314-Pa' → 'Scene.314'\n"
            "    'Scene308-Panel A' → 'Scene308'\n"
            "    'Scene-322' → 'Scene 322'"
        )
        scene_only_btn.clicked.connect(lambda: set_pattern("-.*", True))
        quick_patterns_layout.addWidget(scene_only_btn)
        
        # Seq 번호만 남기기
        seq_only_btn = QPushButton("Seq 번호만 남기기")
        seq_only_btn.setToolTip(
            "Seq로 시작하는 경우 Seq 번호만 남기고 나머지 제거\n"
            "예: 'Seq 01A_S01 - Panel 1' → 'Seq 01A_S01'\n"
            "    'Seq 01A_S02 - Panel 1' → 'Seq 01A_S02'"
        )
        seq_only_btn.clicked.connect(lambda: set_pattern("SEQ_ONLY", True))
        quick_patterns_layout.addWidget(seq_only_btn)
        
        quick_patterns_layout.addStretch()
        layout.addLayout(quick_patterns_layout)
        
        # 미리보기 영역
        preview_label = QLabel("변경 미리보기 (변경될 항목만 표시):")
        layout.addWidget(preview_label)
        preview_text = QTextEdit()
        preview_text.setReadOnly(True)
        preview_text.setMaximumHeight(150)
        layout.addWidget(preview_text)
        
        # 미리보기 업데이트 함수
        def update_preview():
            find_text = find_input.text()
            replace_text = replace_input.text()
            use_regex = regex_checkbox.isChecked()
            
            if not find_text:
                preview_text.clear()
                return
            
            preview_lines = []
            changed_count = 0
            total_checked = 0
            
            # 모든 행을 확인하되, 변경되는 항목만 표시
            for row in range(self.table.rowCount()):
                text_item = self.table.item(row, 3)  # 편집 텍스트 컬럼
                if not text_item:
                    pass
                    continue
                
                original_text = text_item.text()
                total_checked += 1
                
                try:
                    if use_regex:
                        import re
                        # Scene 번호만 남기기 특수 처리
                        if find_text == "-.*":
                            pass
                            # 1. 단어-번호 패턴을 단어 번호로 변환 (하이픈을 공백으로, Scene뿐만 아니라 Seene, Scese 등도 처리)
                            temp_text = re.sub(r'(\w+)\s*-\s*(\d+)', r'\1 \2', original_text)
                            # 2. 단어번호-Panel 패턴에서 하이픈 이후 제거 (번호는 유지)
                            temp_text = re.sub(r'(\w+\s*\d+)-.*', r'\1', temp_text)
                            # 3. 단어 번호 이후의 모든 것 제거 (공백, 언더스코어, 하이픈 등)
                            # Scene 81 Pane → Scene 81, Scene365_PanelA → Scene365
                            temp_text = re.sub(r'(\w+\s*\d+)[\s_\-].*', r'\1', temp_text)
                            # 4. 남은 하이픈 이후 모든 것을 제거
                            new_text = re.sub(find_text, replace_text, temp_text)
                        # Seq 번호만 남기기 특수 처리
                        elif find_text == "SEQ_ONLY":
                            pass
                            # Seq로 시작하는 경우 Seq 번호만 남기기
                            # 예: 'Seq 01A_S01 - Panel 1' → 'Seq 01A_S01'
                            match = re.match(r'Seq\s+([\w\d_]+)', original_text, re.IGNORECASE)
                            if match:
                                new_text = f"Seq {match.group(1)}"
                            else:
                                new_text = original_text
                        else:
                            pass
                            # 정규식 패턴으로 치환 (전역 매칭)
                            new_text = re.sub(find_text, replace_text, original_text)
                    else:
                        new_text = original_text.replace(find_text, replace_text)
                    
                    if new_text != original_text:
                        changed_count += 1
                        # 변경되는 항목만 미리보기에 추가 (최대 20개)
                        if len(preview_lines) < 20:
                            preview_lines.append(f"{original_text} → {new_text}")
                except re.error as e:
                    pass
                    # 오류가 있는 경우에만 표시
                    if len(preview_lines) < 20:
                        preview_lines.append(f"✗ {original_text} (정규식 오류: {str(e)})")
                except Exception as e:
                    if len(preview_lines) < 20:
                        preview_lines.append(f"✗ {original_text} (오류: {str(e)})")
            
            if preview_lines:
                preview_text.setPlainText("\n".join(preview_lines))
                if changed_count > 20:
                    preview_text.append(f"\n... (총 {self.table.rowCount()}개 중 {changed_count}개 변경 예정, 위는 처음 20개)")
                else:
                    preview_text.append(f"\n(총 {self.table.rowCount()}개 중 {changed_count}개 변경 예정)")
            else:
                if total_checked > 0:
                    preview_text.setPlainText(f"변경할 항목이 없습니다. (총 {self.table.rowCount()}개 확인)")
                else:
                    preview_text.clear()
        
        # 입력 변경 시 미리보기 업데이트
        find_input.textChanged.connect(update_preview)
        replace_input.textChanged.connect(update_preview)
        regex_checkbox.toggled.connect(update_preview)
        
        # 버튼
        button_layout = QHBoxLayout()
        apply_button = QPushButton("적용")
        apply_button.setDefault(True)
        cancel_button = QPushButton("취소")
        button_layout.addWidget(apply_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        apply_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        
        if dialog.exec_() != QDialog.Accepted:
            pass
            return
        
        find_text = find_input.text()
        replace_text = replace_input.text()
        use_regex = regex_checkbox.isChecked()
        
        if not find_text:
            QMessageBox.warning(self, "입력 오류", "찾을 텍스트를 입력하세요.")
            return
        
        # 히스토리 저장 (리네임 전 상태)
        self.save_history()
        
        # 리네임 실행
        self._updating = True
        try:
            changed_count = 0
            error_count = 0
            
            for row in range(self.table.rowCount()):
                text_item = self.table.item(row, 3)  # 편집 텍스트 컬럼
                if not text_item:
                    pass
                    continue
                
                original_text = text_item.text()
                
                try:
                    if use_regex:
                        import re
                        # Scene 번호만 남기기 특수 처리
                        if find_text == "-.*":
                            pass
                            # 1. 단어-번호 패턴을 단어 번호로 변환 (하이픈을 공백으로, Scene뿐만 아니라 Seene, Scese 등도 처리)
                            temp_text = re.sub(r'(\w+)\s*-\s*(\d+)', r'\1 \2', original_text)
                            # 2. 단어번호-Panel 패턴에서 하이픈 이후 제거 (번호는 유지)
                            temp_text = re.sub(r'(\w+\s*\d+)-.*', r'\1', temp_text)
                            # 3. 단어 번호 이후의 모든 것 제거 (공백, 언더스코어, 하이픈 등)
                            # Scene 81 Pane → Scene 81, Scene365_PanelA → Scene365
                            temp_text = re.sub(r'(\w+\s*\d+)[\s_\-].*', r'\1', temp_text)
                            # 4. 남은 하이픈 이후 모든 것을 제거
                            new_text = re.sub(find_text, replace_text, temp_text)
                        # Seq 번호만 남기기 특수 처리
                        elif find_text == "SEQ_ONLY":
                            pass
                            # Seq로 시작하는 경우 Seq 번호만 남기기
                            # 예: 'Seq 01A_S01 - Panel 1' → 'Seq 01A_S01'
                            match = re.match(r'Seq\s+([\w\d_]+)', original_text, re.IGNORECASE)
                            if match:
                                new_text = f"Seq {match.group(1)}"
                            else:
                                new_text = original_text
                        else:
                            pass
                            # 정규식 패턴으로 치환 (전역 매칭)
                            new_text = re.sub(find_text, replace_text, original_text)
                    else:
                        new_text = original_text.replace(find_text, replace_text)
                    
                    if new_text != original_text:
                        text_item.setText(new_text)
                        changed_count += 1
                except re.error as e:
                    error_count += 1
                    print(f"리네임 정규식 오류 (행 {row}): {e}")
                except Exception as e:
                    error_count += 1
                    print(f"리네임 오류 (행 {row}): {e}")
        finally:
            self._updating = False
        
        # 업데이트
        updated_segments = self.collect_segments(skip_detections_copy=True)
        self.timeline.set_segments(updated_segments)
        self.update_summary_with_segments(updated_segments)
        self.update_sequence_with_segments(updated_segments)
        
        # 부모 VideoPlayer의 saved_edited_segments 업데이트
        parent = self.parent()
        if parent and hasattr(parent, 'saved_edited_segments'):
            parent.saved_edited_segments = updated_segments
        
        # 결과 메시지
        if error_count > 0:
            QMessageBox.warning(
                self,
                "리네임 완료 (일부 오류)",
                f"{changed_count}개 항목이 변경되었습니다.\n{error_count}개 항목에서 오류가 발생했습니다."
            )
        else:
            QMessageBox.information(
                self,
                "리네임 완료",
                f"{changed_count}개 항목이 변경되었습니다."
            )

        # 실시간 동기화 (비동기로 실행하여 UI 반응성 향상)
        if changed_count > 0:
            QTimer.singleShot(0, self.broadcast_segments_change)

    def merge_selected_rows(self):
        """선택된 여러 구간을 하나로 병합"""
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if len(selected_rows) < 2:
            QMessageBox.information(self, "병합할 구간 부족", "병합하려면 최소 2개 이상의 구간을 선택하세요.")
            return
        
        # 히스토리 저장 (병합 전 상태)
        self.save_history()
        
        # 비연속 구간도 병합 가능 (연속 체크 제거)
        
        # 선택된 구간들의 모든 편집 텍스트 수집 (중복 제거)
        all_texts = []
        for row in selected_rows:
            edit_text_item = self.table.item(row, 3)
            if edit_text_item:
                text = edit_text_item.text().strip()
                if text and text not in all_texts:
                    all_texts.append(text)
        
        # 사용자에게 이름 선택 또는 입력받기
        if all_texts:
            pass
            # 콤보박스로 선택 가능하도록 다이얼로그 생성
            items = all_texts + ["[새로운 이름 입력...]"]
            selected_text, ok = QInputDialog.getItem(
                self, 
                "병합된 구간 이름 선택", 
                "병합된 구간의 이름을 선택하거나 새로운 이름을 입력하세요:",
                items,
                0,
                True  # 편집 가능
            )
            if not ok:
                pass
                return  # 사용자가 취소
            
            # "[새로운 이름 입력...]"을 선택한 경우 다시 입력받기
            if selected_text == "[새로운 이름 입력...]":
                new_text, ok = QInputDialog.getText(
                    self,
                    "새로운 이름 입력",
                    "병합된 구간의 새로운 이름을 입력하세요:",
                    text=""
                )
                if not ok:
                    pass
                    return
                edit_text = new_text.strip()
            else:
                edit_text = selected_text.strip()
        else:
            pass
            # 모든 구간이 빈 텍스트인 경우
            edit_text, ok = QInputDialog.getText(
                self,
                "병합된 구간 이름 입력",
                "병합된 구간의 이름을 입력하세요:",
                text=""
            )
            if not ok:
                pass
                return
            edit_text = edit_text.strip()
        
        # 썸네일 선택 다이얼로그 (OCR 모드에서만)
        is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']
        thumbnail_row = selected_rows[0]  # 기본값: 첫 번째 행
        
        if is_ocr_mode and len(selected_rows) > 1:
            pass
            # 선택된 행들의 정보 수집
            thumbnail_options = []
            for row in selected_rows:
                edit_text_item = self.table.item(row, 3)
                start_frame_item = self.table.item(row, 4)
                text = edit_text_item.text() if edit_text_item else f"행 {row + 1}"
                start_frame = start_frame_item.data(Qt.UserRole) if start_frame_item and start_frame_item.data(Qt.UserRole) is not None else None
                if start_frame is None and start_frame_item:
                    start_frame = self._safe_int(start_frame_item) - 1
                frame_text = f"프레임 {start_frame + 1}" if start_frame is not None else "프레임 없음"
                thumbnail_options.append(f"행 {row + 1}: {text} ({frame_text})")
            
            # 썸네일 선택 다이얼로그
            selected_option, ok = QInputDialog.getItem(
                self,
                "썸네일 선택",
                "병합된 구간에 사용할 썸네일을 선택하세요:",
                thumbnail_options,
                0,  # 기본값: 첫 번째 옵션
                False  # 편집 불가
            )
            if not ok:
                pass
                return  # 사용자가 취소
            
            # 선택된 옵션에서 행 번호 추출
            selected_index = thumbnail_options.index(selected_option)
            thumbnail_row = selected_rows[selected_index]
        
        # 전체 병합 과정을 _updating으로 감싸서 성능 향상 (UI 업데이트 억제)
        self._updating = True
        try:
            pass
            # 첫 번째 행 인덱스 (병합된 결과가 들어갈 위치)
            first_row = selected_rows[0]
            
            # 데이터 수집
            # 시작 프레임: 선택된 모든 구간 중 가장 작은 시작 프레임
            # 종료 프레임: 선택된 모든 구간 중 가장 큰 종료 프레임
            start_frames = []
            end_frames = []
            for row in selected_rows:
                start_frame_item = self.table.item(row, 4)
                end_frame_item = self.table.item(row, 5)
                if start_frame_item and start_frame_item.data(Qt.UserRole) is not None:
                    start_frames.append(int(start_frame_item.data(Qt.UserRole)))
                if end_frame_item and end_frame_item.data(Qt.UserRole) is not None:
                    end_frames.append(int(end_frame_item.data(Qt.UserRole)))
            
            start_frame = min(start_frames) if start_frames else 0
            end_frame = max(end_frames) if end_frames else 0
            
            # ROI 텍스트: 첫 번째 구간의 텍스트 사용
            roi_text_item = self.table.item(first_row, 2)
            roi_text = roi_text_item.text() if roi_text_item else ""
            
            # ROI 샘플 이미지: 사용자가 선택한 행의 이미지 사용
            merged_image = self.segment_images[thumbnail_row] if thumbnail_row < len(self.segment_images) else None
            
            # detections 병합: 모든 선택된 구간의 detections 합침
            merged_detections = []
            for row in selected_rows:
                if row < len(self.segment_detections):
                    merged_detections.extend(self.segment_detections[row])
            
            # 시간 계산
            start_time = start_frame / self.fps if self.fps else 0.0
            end_time = (end_frame + 1) / self.fps if self.fps else 0.0
            num_frames = end_frame - start_frame + 1  # 구간 길이(프레임) - 정수
            
            # 편집 텍스트 업데이트 (사용자가 선택/입력한 텍스트)
            self.table.item(first_row, 3).setText(edit_text)
            
            # 시작 프레임 업데이트 (1-based로 표시)
            start_frame_item = self.table.item(first_row, 4)
            if start_frame_item:
                start_frame_item.setText(str(start_frame + 1))
                start_frame_item.setData(Qt.UserRole, start_frame)
            else:
                pass
                # 아이템이 없으면 새로 생성
                start_frame_item = QTableWidgetItem(str(start_frame + 1))
                start_frame_item.setData(Qt.UserRole, start_frame)
                self.table.setItem(first_row, 4, start_frame_item)
            
            # 종료 프레임 업데이트 (1-based로 표시)
            end_frame_item = self.table.item(first_row, 5)
            if end_frame_item:
                end_frame_item.setText(str(end_frame + 1))
                end_frame_item.setData(Qt.UserRole, end_frame)
            else:
                pass
                # 아이템이 없으면 새로 생성
                end_frame_item = QTableWidgetItem(str(end_frame + 1))
                end_frame_item.setData(Qt.UserRole, end_frame)
                self.table.setItem(first_row, 5, end_frame_item)
            
            # 시간 정보 업데이트
            self.table.item(first_row, 6).setText(f"{start_time:.3f}")
            self.table.item(first_row, 7).setText(f"{end_time:.3f}")
            self.table.item(first_row, 8).setText(str(num_frames))  # 프레임 단위 정수로 표시
            
            # detections 업데이트
            self.segment_detections[first_row] = merged_detections
            
            # 썸네일 이미지 업데이트: 사용자가 선택한 행의 썸네일 사용 (OCR 모드에서만)
            # 애니매틱 모드는 시작 프레임에서 썸네일 추출
            if is_ocr_mode:
                pass
                # OCR 모드: 사용자가 선택한 행의 썸네일 사용
                if merged_image:
                    pass
                    # segment_images 업데이트
                    if first_row < len(self.segment_images):
                        self.segment_images[first_row] = merged_image
                    else:
                        pass
                        # 리스트가 짧으면 확장
                        while len(self.segment_images) <= first_row:
                            self.segment_images.append(None)
                        self.segment_images[first_row] = merged_image
                    
                    # 썸네일 위젯 업데이트
                    thumb_widget = self.table.cellWidget(first_row, 1)
                    if thumb_widget:
                        thumb_label = thumb_widget.findChild(QLabel)
                        if thumb_label:
                            pass
                            # 선택한 행의 detections 사용 (썸네일과 일치하도록)
                            selected_detections = self.segment_detections[thumbnail_row] if thumbnail_row < len(self.segment_detections) else merged_detections
                            
                            # 원본 pixmap 생성
                            original_pixmap = self._pixmap_with_boxes(merged_image, selected_detections, None)

                            if original_pixmap:
                                orig_width = original_pixmap.width()
                                orig_height = original_pixmap.height()
                                
                                # 현재 슬라이더 값에 따라 썸네일 크기 계산 (일반 썸네일과 동일하게)
                                slider_value = self.thumbnail_size_slider.value() if hasattr(self, 'thumbnail_size_slider') else 2
                                base_height = 40
                                target_height = base_height * slider_value  # 슬라이더 값에 따라 40~160
                                aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                                target_width = int(target_height * aspect_ratio)
                                thumbnail_size = QSize(target_width, target_height)
                                pixmap = original_pixmap.scaled(thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            else:
                                pixmap = None
                            
                            if pixmap:
                                thumb_label.setPixmap(pixmap)
                                thumb_label.setProperty('original_pixmap', original_pixmap)
                            else:
                                thumb_label.setText("이미지 없음")
            else:
                pass
                # 애니매틱 모드: 병합된 씬의 시작 프레임에서 썸네일 추출
                if self.video_path and os.path.exists(self.video_path):
                    pass
                    # 병합된 씬의 시작 프레임에서 썸네일 추출
                    merged_thumbnail = self._extract_frame_thumbnail(self.video_path, start_frame)
                    if merged_thumbnail:
                        pass
                        # segment_images 업데이트
                        if first_row < len(self.segment_images):
                            self.segment_images[first_row] = merged_thumbnail
                        else:
                            pass
                            # 리스트가 짧으면 확장
                            while len(self.segment_images) <= first_row:
                                self.segment_images.append(None)
                            self.segment_images[first_row] = merged_thumbnail
                        
                        # 썸네일 위젯 업데이트
                        thumb_widget = self.table.cellWidget(first_row, 1)
                        if thumb_widget:
                            thumb_label = thumb_widget.findChild(QLabel)
                            if thumb_label:
                                pass
                                # 원본 pixmap 생성
                                original_pixmap = self._pixmap_with_boxes(merged_thumbnail, merged_detections, None)

                                # 애니매틱 모드: 기존 방식 유지 (원본 비율 유지하면서 스케일)
                                thumbnail_size = QSize(192, 108)
                                pixmap = original_pixmap
                                if pixmap:
                                    pixmap = pixmap.scaled(
                                        thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                                    )
                                
                                if pixmap:
                                    thumb_label.setPixmap(pixmap)
                                    thumb_label.setProperty('original_pixmap', original_pixmap)
            
            # 나머지 선택된 행들 삭제 (역순으로)
            # 테이블 업데이트를 일시 중지하여 성능 향상
            self.table.setUpdatesEnabled(False)
            try:
                pass
                # 삭제될 행 목록 (첫 번째 제외)
                rows_to_delete = selected_rows[1:]

                for row in reversed(rows_to_delete):
                    self.table.removeRow(row)
                    if 0 <= row < len(self.segment_images):
                        del self.segment_images[row]
                    if 0 <= row < len(self.segment_detections):
                        del self.segment_detections[row]

                # Lazy loading 캐시 재조정: 삭제된 행 제거 및 인덱스 재조정 (최적화)
                if hasattr(self, '_thumbnail_cache') and rows_to_delete:
                    pass
                    # 삭제된 행을 set으로 변환하여 O(1) 룩업
                    deleted_set = set(rows_to_delete)
                    # 정렬된 삭제 리스트를 사용하여 binary search 적용
                    sorted_deleted = sorted(rows_to_delete)
                    new_cache = {}
                    for cached_row, value in self._thumbnail_cache.items():
                        pass
                        # 삭제되지 않은 행만 처리
                        if cached_row not in deleted_set:
                            pass
                            # binary search를 사용하여 O(log n)으로 개선
                            import bisect
                            offset = bisect.bisect_left(sorted_deleted, cached_row)
                            adjusted_row = cached_row - offset
                            new_cache[adjusted_row] = value
                    self._thumbnail_cache = new_cache

                # 재인덱싱 (first_row부터만 - setUpdatesEnabled(False) 내에서 수행하여 성능 최적화)
                for row in range(first_row, self.table.rowCount()):
                    item = self.table.item(row, 0)
                    if item:
                        item.setText(str(row + 1))
            finally:
                self.table.setUpdatesEnabled(True)
                # 명시적으로 테이블 업데이트 강제
                self.table.viewport().update()

            # 씬 이름 자동 리네임 (애니매틱 모드일 때만)
            if getattr(self, 'ocr_mode', 'titmouse') in ['animatic', 'animatic2']:
                self._renumber_scene_names()

            # 씬 리스트 증분 업데이트 (병합된 첫 번째 행부터 끝까지)
            self._update_scene_list(affected_rows=(first_row, self.table.rowCount()))

            # 병합 후 썸네일 위젯도 테이블의 시작 프레임에 맞춰 업데이트 (애니매틱 모드에서만)
            # OCR 모드에서는 사용자가 선택한 썸네일을 유지하므로 건너뜀
            if not is_ocr_mode and self.video_path and os.path.exists(self.video_path):
                pass
                # 테이블에서 시작 프레임 다시 확인
                start_frame_item_after = self.table.item(first_row, 4)
                if start_frame_item_after:
                    actual_start_frame = start_frame_item_after.data(Qt.UserRole)
                    if actual_start_frame is None:
                        actual_start_frame = self._safe_int(start_frame_item_after) - 1
                    if actual_start_frame is not None and actual_start_frame != start_frame:
                        pass
                        # 프레임이 다르면 다시 추출
                        # print(f"[병합] 프레임 불일치 감지: start_frame={start_frame}, actual_start_frame={actual_start_frame}, 재추출")
                        correct_thumbnail = self._extract_frame_thumbnail(self.video_path, actual_start_frame)
                        if correct_thumbnail:
                            if first_row < len(self.segment_images):
                                self.segment_images[first_row] = correct_thumbnail
                            # 썸네일 위젯도 다시 업데이트
                            thumb_widget = self.table.cellWidget(first_row, 1)
                            if thumb_widget:
                                thumb_label = thumb_widget.findChild(QLabel)
                                if thumb_label:
                                    pass
                                    # 원본 pixmap 생성
                                    original_pixmap = self._pixmap_with_boxes(correct_thumbnail, merged_detections, None)

                                    # 애니매틱 모드: 기존 방식 유지 (원본 비율 유지하면서 스케일)
                                    thumbnail_size = QSize(192, 108)
                                    pixmap = original_pixmap
                                    if pixmap:
                                        pixmap = pixmap.scaled(
                                            thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                                        )
                                    
                                    if pixmap:
                                        thumb_label.setPixmap(pixmap)
                                        thumb_label.setProperty('original_pixmap', original_pixmap)
                                        # print(f"[병합] 썸네일 위젯 재업데이트 완료: actual_start_frame={actual_start_frame}")
        
        finally:
            self._updating = False
        
        # 병합된 행 선택 (미리보기 업데이트)
        self.table.selectRow(first_row)
        # 병합 후 프리뷰 프레임 리셋 (이전 씬의 프레임이 표시되지 않도록)
        if hasattr(self, '_last_preview_row'):
            self._last_preview_row = None
        if hasattr(self, '_last_selected_row'):
            self._last_selected_row = None
        self._preview_current_display_frame = None
        self.update_preview(first_row, immediate=True)
        
        # 병합된 행의 하이라이트 제거 (녹색/노란색 하이라이트 초기화)
        default_color = QColor(0, 0, 0, 0)  # 투명 (기본 배경 사용)
        default_brush = QBrush(default_color)
        for col in range(self.table.columnCount()):
            item = self.table.item(first_row, col)
            if item:
                item.setBackground(default_brush)
        
        # collect_segments를 한 번만 호출하여 재사용 (detections 복사 생략으로 성능 향상)
        segments = self.collect_segments(skip_detections_copy=True)
        
        # 타임라인, 요약, 시퀀스를 즉시 업데이트 (반응 속도 향상)
        self._update_ui_after_merge(segments)
        
        # 부모 VideoPlayer의 saved_edited_segments 업데이트 (저장 시 최신 상태 반영)
        parent = self.parent()
        if parent and hasattr(parent, 'saved_edited_segments'):
            parent.saved_edited_segments = segments
        
        # 병합 후 하이라이트는 건너뛰기 (성능 향상)
        # 필요 시 사용자가 테이블을 클릭하면 자동으로 업데이트됨
        # self._highlight_mergeable_rows()
        
        # 병합 완료 메시지 제거 (빠른 병합을 위해)
        # 메시지 박스를 QTimer로 지연 표시 (UI가 먼저 업데이트되도록)
        # QTimer.singleShot(10, lambda: QMessageBox.information(self, "병합 완료", f"{len(selected_rows)}개 구간을 하나로 병합했습니다."))

        # 실시간 동기화 (비동기로 실행하여 UI 반응성 향상)
        QTimer.singleShot(0, self.broadcast_segments_change)

    def _update_ui_after_merge(self, segments):
        """병합 후 UI 업데이트 (지연 실행으로 성능 향상)"""
        # 타임라인, 요약, 시퀀스를 한 번에 업데이트
        self.timeline.set_segments(segments)
        self.update_summary_with_segments(segments)
        self.update_sequence_with_segments(segments)
        
        # 부모 VideoPlayer의 saved_edited_segments 업데이트 (저장 시 최신 상태 반영)
        parent = self.parent()
        if parent and hasattr(parent, 'saved_edited_segments'):
            parent.saved_edited_segments = segments
    
    def split_selected_row(self):
        """선택된 하나의 씬을 지정한 프레임 위치에서 두 개의 씬으로 분할"""
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        
        if len(selected_rows) != 1:
            QMessageBox.information(self, "씬 분할", "분할하려면 정확히 1개의 씬을 선택하세요.")
            return
        
        row = selected_rows[0]
        
        # 선택된 행의 프레임 정보 가져오기
        start_frame_item = self.table.item(row, 4)
        end_frame_item = self.table.item(row, 5)
        
        if not start_frame_item or not end_frame_item:
            QMessageBox.warning(self, "오류", "선택한 씬의 프레임 정보를 찾을 수 없습니다.")
            return
        
        # 0-based 프레임 번호 가져오기
        start_frame = start_frame_item.data(Qt.UserRole)
        end_frame = end_frame_item.data(Qt.UserRole)
        
        if start_frame is None or end_frame is None:
            pass
            # UserRole이 없으면 텍스트에서 파싱
            try:
                start_frame = int(start_frame_item.text()) - 1
                end_frame = int(end_frame_item.text()) - 1
            except ValueError:
                QMessageBox.warning(self, "오류", "프레임 정보를 파싱할 수 없습니다.")
                return
        
        # 분할할 수 있는지 확인 (최소 2프레임 이상)
        total_frames = end_frame - start_frame + 1
        if total_frames < 2:
            QMessageBox.warning(self, "씬 분할", "씬이 너무 짧아서 분할할 수 없습니다. (최소 2프레임 필요)")
            return

        # 상대 프레임 위치 입력받기 (1부터 시작)
        # 예: 씬이 100~252(총 153프레임)이면, 1~153으로 입력받음
        # 입력값 2는 절대 프레임 101을 의미 (100 + (2-1))
        relative_frame, ok = QInputDialog.getInt(
            self,
            "씬 분할",
            f"분할할 상대 프레임 위치를 입력하세요:\n"
            f"(현재 씬: 절대 프레임 {start_frame + 1} ~ {end_frame + 1}, 총 {total_frames}프레임)\n"
            f"입력값 1 = 첫 프레임, 입력값 {total_frames} = 마지막 프레임\n"
            f"예: {total_frames} 입력 시 → 앞 씬은 {total_frames-1}프레임, 뒤 씬은 1프레임부터 시작",
            min=2,  # 최소 2 (첫 프레임은 남겨야 함)
            max=total_frames,  # 최대 마지막 프레임 (끝 프레임도 분할 가능)
            value=(total_frames // 2) + 1  # 중간 지점
        )

        if not ok:
            pass
            return  # 사용자가 취소

        # 상대 프레임을 절대 프레임으로 변환 (0-based)
        # 상대 프레임 N은 절대 프레임 start_frame + (N-1)을 의미
        split_frame = start_frame + (relative_frame - 1)

        # 분할 위치 유효성 검사
        # split_frame이 두 번째 씬의 시작 프레임이 됨
        # 첫 번째 씬: start_frame ~ split_frame - 1
        # 두 번째 씬: split_frame ~ end_frame
        if split_frame <= start_frame or split_frame > end_frame:
            QMessageBox.warning(self, "씬 분할", "분할 위치가 유효하지 않습니다.")
            return
        
        # 히스토리 저장 (분할 전 상태)
        self.save_history()
        
        # 전체 분할 과정을 _updating으로 감싸서 성능 향상
        self._updating = True
        try:
            pass
            # 첫 번째 씬: start_frame ~ split_frame - 1
            # 두 번째 씬: split_frame ~ end_frame
            
            # 기존 씬의 정보 가져오기
            roi_text_item = self.table.item(row, 2)
            edit_text_item = self.table.item(row, 3)
            roi_text = roi_text_item.text() if roi_text_item else ""
            edit_text = edit_text_item.text() if edit_text_item else ""
            
            # detections 가져오기
            detections = self.segment_detections[row] if row < len(self.segment_detections) else []
            
            # 기존 ROI 이미지의 종횡비 확인 (OCR 모드일 때 종횡비 유지용)
            original_roi_image = None
            original_aspect_ratio = None
            if row < len(self.segment_images) and self.segment_images[row]:
                original_roi_image = self.segment_images[row]
                # 기존 ROI 이미지의 종횡비 계산
                try:
                    import cv2
                    import numpy as np
                    nparr = np.frombuffer(original_roi_image, np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if img is not None:
                        orig_height, orig_width = img.shape[:2]
                        original_aspect_ratio = orig_width / orig_height if orig_height > 0 else None
                except Exception as e:
                    pass
                    # print(f"[씬 분할] 기존 ROI 이미지 종횡비 계산 실패: {e}")
            
            # 첫 번째 씬: start_frame ~ split_frame - 1 (기존 행 업데이트)
            first_start_frame = start_frame
            first_end_frame = split_frame - 1
            first_start_time = first_start_frame / self.fps
            first_end_time = first_end_frame / self.fps
            first_duration = first_end_time - first_start_time
            
            # 두 번째 씬: split_frame ~ end_frame (새 행으로 삽입)
            second_start_frame = split_frame
            second_end_frame = end_frame
            second_start_time = second_start_frame / self.fps
            second_end_time = second_end_frame / self.fps
            second_duration = second_end_time - second_start_time
            
            # 두 번째 씬을 새 행으로 삽입 (기존 행 뒤에)
            new_row = row + 1
            self.table.insertRow(new_row)
            
            # 첫 번째 씬: 기존 행 업데이트
            # 종료 프레임 업데이트
            end_frame_item.setText(str(first_end_frame + 1))
            end_frame_item.setData(Qt.UserRole, first_end_frame)
            
            # 시간 정보 업데이트 (update_row_times 사용하여 정수로 표시)
            self.update_row_times(row)
            
            # 첫 번째 씬의 썸네일 추출 및 업데이트
            # OCR 모드일 때는 기존 ROI 이미지 종횡비 유지
            first_thumbnail = None
            is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']
            
            if is_ocr_mode and original_roi_image and original_aspect_ratio:
                pass
                # OCR 모드: 기존 ROI 이미지 종횡비 유지 (기존 이미지 사용)
                first_thumbnail = original_roi_image
            elif self.video_path and os.path.exists(self.video_path):
                pass
                # 비디오에서 새로 추출
                first_thumbnail = self._extract_frame_thumbnail(self.video_path, first_start_frame)
                # OCR 모드이고 기존 종횡비가 있으면, 새 이미지를 기존 종횡비에 맞게 크롭
                if is_ocr_mode and original_aspect_ratio and first_thumbnail:
                    try:
                        import cv2
                        import numpy as np
                        nparr = np.frombuffer(first_thumbnail, np.uint8)
                        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if img is not None:
                            new_height, new_width = img.shape[:2]
                            new_aspect_ratio = new_width / new_height if new_height > 0 else 1.0
                            
                            # 종횡비가 다르면 기존 종횡비에 맞게 크롭
                            if abs(new_aspect_ratio - original_aspect_ratio) > 0.01:
                                if new_aspect_ratio > original_aspect_ratio:
                                    pass
                                    # 새 이미지가 더 넓음: 높이 기준으로 크롭
                                    target_width = int(new_height * original_aspect_ratio)
                                    x_offset = (new_width - target_width) // 2
                                    img = img[:, x_offset:x_offset + target_width]
                                else:
                                    pass
                                    # 새 이미지가 더 높음: 너비 기준으로 크롭
                                    target_height = int(new_width / original_aspect_ratio)
                                    y_offset = (new_height - target_height) // 2
                                    img = img[y_offset:y_offset + target_height, :]
                                
                                # 크롭된 이미지를 bytes로 변환
                                _, encoded = cv2.imencode('.png', img)
                                first_thumbnail = encoded.tobytes()
                    except Exception as e:
                        pass
                        # print(f"[씬 분할] 첫 번째 씬 이미지 종횡비 조정 실패: {e}")
            
            if first_thumbnail and row < len(self.segment_images):
                self.segment_images[row] = first_thumbnail
                
                # 썸네일 위젯 업데이트
                thumb_widget = self.table.cellWidget(row, 1)
                if thumb_widget:
                    thumb_label = thumb_widget.findChild(QLabel)
                    if thumb_label:
                        is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']

                        # 원본 pixmap 생성
                        original_pixmap = self._pixmap_with_boxes(first_thumbnail, detections, None)

                        if is_ocr_mode:
                            pass
                            # OCR 모드: 실제 이미지 종횡비에 맞게 조정
                            if original_pixmap:
                                orig_width = original_pixmap.width()
                                orig_height = original_pixmap.height()
                                target_height = 80
                                aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                                target_width = int(target_height * aspect_ratio)
                                thumbnail_size = QSize(target_width, target_height)
                                pixmap = original_pixmap.scaled(thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            else:
                                pixmap = None
                        else:
                            pass
                            # 애니매틱 모드: 기존 방식 유지
                            thumbnail_size = QSize(192, 108)
                            pixmap = original_pixmap
                            if pixmap:
                                pixmap = pixmap.scaled(
                                    thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                                )

                        if pixmap:
                            thumb_label.setPixmap(pixmap)
                            thumb_label.setProperty('original_pixmap', original_pixmap)
            
            # 두 번째 씬의 썸네일 추출
            # OCR 모드일 때는 기존 ROI 이미지 종횡비 유지
            second_thumbnail = None
            if is_ocr_mode and original_roi_image and original_aspect_ratio:
                pass
                # OCR 모드: 기존 ROI 이미지 종횡비 유지 (기존 이미지 사용)
                second_thumbnail = original_roi_image
            elif self.video_path and os.path.exists(self.video_path):
                pass
                # 비디오에서 새로 추출
                second_thumbnail = self._extract_frame_thumbnail(self.video_path, second_start_frame)
                # OCR 모드이고 기존 종횡비가 있으면, 새 이미지를 기존 종횡비에 맞게 크롭
                if is_ocr_mode and original_aspect_ratio and second_thumbnail:
                    try:
                        import cv2
                        import numpy as np
                        nparr = np.frombuffer(second_thumbnail, np.uint8)
                        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if img is not None:
                            new_height, new_width = img.shape[:2]
                            new_aspect_ratio = new_width / new_height if new_height > 0 else 1.0
                            
                            # 종횡비가 다르면 기존 종횡비에 맞게 크롭
                            if abs(new_aspect_ratio - original_aspect_ratio) > 0.01:
                                if new_aspect_ratio > original_aspect_ratio:
                                    pass
                                    # 새 이미지가 더 넓음: 높이 기준으로 크롭
                                    target_width = int(new_height * original_aspect_ratio)
                                    x_offset = (new_width - target_width) // 2
                                    img = img[:, x_offset:x_offset + target_width]
                                else:
                                    pass
                                    # 새 이미지가 더 높음: 너비 기준으로 크롭
                                    target_height = int(new_width / original_aspect_ratio)
                                    y_offset = (new_height - target_height) // 2
                                    img = img[y_offset:y_offset + target_height, :]
                                
                                # 크롭된 이미지를 bytes로 변환
                                _, encoded = cv2.imencode('.png', img)
                                second_thumbnail = encoded.tobytes()
                    except Exception as e:
                        pass
                        # print(f"[씬 분할] 두 번째 씬 이미지 종횡비 조정 실패: {e}")
            
            # 두 번째 씬 데이터 추가 (populate_table 로직 참고)
            # ROI 이미지 처리
            roi_bytes = second_thumbnail if second_thumbnail else None

            # segment_images와 segment_detections 리스트에 삽입 (insertRow에 맞춰)
            self.segment_images.insert(new_row, roi_bytes)
            self.segment_detections.insert(new_row, detections if detections else [])
            
            # 테이블에 데이터 추가 (populate_table의 로직 재사용)
            self.table.setItem(new_row, 0, QTableWidgetItem(str(new_row + 1)))
            
            # ROI 샘플 (썸네일) - populate_table의 로직 재사용
            thumb_widget = QWidget()
            thumb_layout = QVBoxLayout(thumb_widget)
            thumb_layout.setContentsMargins(0, 0, 0, 0)
            thumb_layout.setSpacing(0)
            
            thumb_label = QLabel()
            thumb_label.setAlignment(Qt.AlignCenter)
            thumb_label.setStyleSheet("QLabel { background: #050505; border: 1px solid #222; color: #555; }")

            is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']

            # 원본 pixmap 생성
            original_pixmap = self._pixmap_with_boxes(roi_bytes, detections, None)

            if is_ocr_mode:
                pass
                # OCR 모드: 실제 이미지 종횡비에 맞게 조정
                if original_pixmap:
                    orig_width = original_pixmap.width()
                    orig_height = original_pixmap.height()
                    target_height = 80
                    aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                    target_width = int(target_height * aspect_ratio)
                    thumbnail_size = QSize(target_width, target_height)
                    self.table.setRowHeight(new_row, target_height + 10)
                    if new_row == 0:
                        self.table.setColumnWidth(1, target_width + 10)
                    pixmap = original_pixmap.scaled(thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                else:
                    pixmap = None
            else:
                pass
                # 애니매틱 모드: 기존 방식 유지
                thumbnail_size = QSize(192, 108)
                self.table.setRowHeight(new_row, 118)
                if original_pixmap:
                    pixmap = original_pixmap.scaled(
                        thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                else:
                    pixmap = None

            if pixmap:
                thumb_label.setPixmap(pixmap)
                thumb_label.setProperty('original_pixmap', original_pixmap)
            else:
                thumb_label.setText("이미지 없음")
            
            # tooltip 생성
            tooltip_text = f"프레임: {second_start_frame + 1} → {second_end_frame + 1}"
            thumb_label.setToolTip(tooltip_text)
            thumb_layout.addWidget(thumb_label)
            
            # 재생 버튼 오버레이
            play_button = QPushButton("▶")
            play_button.setFixedSize(30, 30)
            play_button.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 165, 0, 100);
                    color: white;
                    border: 2px solid rgba(255, 255, 255, 100);
                    border-radius: 15px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: rgba(255, 165, 0, 180);
                    border: 2px solid rgba(255, 255, 255, 150);
                }
                QPushButton:pressed {
                    background: rgba(255, 140, 0, 200);
                }
            """)
            play_button.setCursor(Qt.PointingHandCursor)
            play_button.setProperty("table_row", new_row)
            play_button.setParent(thumb_label)
            play_button.raise_()
            play_button.show()
            
            def update_button_position():
                if thumb_label.pixmap():
                    label_width = thumb_label.width()
                    label_height = thumb_label.height()
                    x = (label_width - play_button.width()) // 2
                    y = (label_height - play_button.height()) // 2
                    play_button.move(x, y)
            
            original_resize_event = thumb_label.resizeEvent
            def resize_event_wrapper(e):
                if original_resize_event:
                    original_resize_event(e)
                update_button_position()
            thumb_label.resizeEvent = resize_event_wrapper
            
            play_button.clicked.connect(lambda checked, r=new_row: self._on_play_button_clicked(r))
            QTimer.singleShot(0, update_button_position)
            
            self.table.setCellWidget(new_row, 1, thumb_widget)
            
            # ROI 텍스트
            self.table.setItem(new_row, 2, QTableWidgetItem(roi_text))
            
            # 편집 텍스트
            self.table.setItem(new_row, 3, QTableWidgetItem(edit_text))
            
            # 시작 프레임
            start_item = QTableWidgetItem(str(second_start_frame + 1))
            start_item.setData(Qt.UserRole, second_start_frame)
            self.table.setItem(new_row, 4, start_item)
            
            # 종료 프레임
            end_item = QTableWidgetItem(str(second_end_frame + 1))
            end_item.setData(Qt.UserRole, second_end_frame)
            self.table.setItem(new_row, 5, end_item)
            
            # 시간 정보 업데이트 (update_row_times 사용하여 정수로 표시)
            self.update_row_times(new_row)
            
            # 재인덱싱 (new_row 이후의 모든 행)
            for r in range(new_row + 1, self.table.rowCount()):
                item = self.table.item(r, 0)
                if item:
                    item.setText(str(r + 1))

            # 씬 이름 자동 리네임 (애니매틱 모드일 때만)
            if getattr(self, 'ocr_mode', 'titmouse') in ['animatic', 'animatic2']:
                self._renumber_scene_names()
            
            # 씬 리스트 업데이트
            self._update_scene_list()
            
        finally:
            self._updating = False
        
        # 분할된 첫 번째 씬 선택 (미리보기 업데이트) - 기존 행 유지
        self.table.selectRow(row)
        self.update_preview(row)
        
        # segments 업데이트
        segments = self.collect_segments(skip_detections_copy=True)
        self.timeline.set_segments(segments)
        self.update_summary_with_segments(segments)
        self.update_sequence_with_segments(segments)
        
        # 부모 VideoPlayer의 saved_edited_segments 업데이트
        parent = self.parent()
        if parent and hasattr(parent, 'saved_edited_segments'):
            parent.saved_edited_segments = segments
        
        # 웹 UI에 변경사항 동기화 (비동기로 실행하여 UI 반응성 향상)
        QTimer.singleShot(0, self.broadcast_segments_change)

        QMessageBox.information(
            self,
            "씬 분할 완료",
            f"씬이 상대 프레임 {relative_frame} (절대 프레임 {split_frame + 1})에서 두 개로 분할되었습니다.\n"
            f"첫 번째 씬: {start_frame + 1} ~ {split_frame} ({split_frame - start_frame}프레임)\n"
            f"두 번째 씬: {split_frame + 1} ~ {end_frame + 1} ({end_frame - split_frame + 1}프레임)"
        )
    
    def _split_row_at_frame(self, row, split_frame):
        """지정된 행을 지정된 프레임 위치에서 두 개의 씬으로 분할 (WebSocket 명령용)"""
        # 선택된 행의 프레임 정보 가져오기
        start_frame_item = self.table.item(row, 4)
        end_frame_item = self.table.item(row, 5)
        
        if not start_frame_item or not end_frame_item:
            pass
            # print(f"[WebSocket] 씬 분할 오류: 프레임 정보를 찾을 수 없습니다 (row={row})")
            return
        
        # 0-based 프레임 번호 가져오기
        start_frame = start_frame_item.data(Qt.UserRole)
        end_frame = end_frame_item.data(Qt.UserRole)
        
        if start_frame is None or end_frame is None:
            pass
            # UserRole이 없으면 텍스트에서 파싱
            try:
                start_frame = int(start_frame_item.text()) - 1
                end_frame = int(end_frame_item.text()) - 1
            except ValueError:
                pass
                # print(f"[WebSocket] 씬 분할 오류: 프레임 정보를 파싱할 수 없습니다 (row={row})")
                return
        
        # 분할할 수 있는지 확인 (최소 2프레임 이상)
        if end_frame - start_frame < 2:
            pass
            # print(f"[WebSocket] 씬 분할 오류: 씬이 너무 짧습니다 (row={row}, frames={end_frame - start_frame + 1})")
            return

        # 분할 위치 유효성 검사 (split_frame은 이미 0-based)
        # split_frame이 두 번째 씬의 시작 프레임이 됨
        # 첫 번째 씬: start_frame ~ split_frame - 1
        # 두 번째 씬: split_frame ~ end_frame
        if split_frame <= start_frame or split_frame > end_frame:
            pass
            # print(f"[WebSocket] 씬 분할 오류: 분할 위치가 유효하지 않습니다 (row={row}, split_frame={split_frame}, start={start_frame}, end={end_frame})")
            return
        
        # 히스토리 저장 (분할 전 상태)
        self.save_history()
        
        # 전체 분할 과정을 _updating으로 감싸서 성능 향상
        self._updating = True
        try:
            pass
            # 첫 번째 씬: start_frame ~ split_frame - 1
            # 두 번째 씬: split_frame ~ end_frame
            
            # 기존 씬의 정보 가져오기
            roi_text_item = self.table.item(row, 2)
            edit_text_item = self.table.item(row, 3)
            roi_text = roi_text_item.text() if roi_text_item else ""
            edit_text = edit_text_item.text() if edit_text_item else ""
            
            # detections 가져오기
            detections = self.segment_detections[row] if row < len(self.segment_detections) else []
            
            # 기존 ROI 이미지의 종횡비 확인 (OCR 모드일 때 종횡비 유지용)
            original_roi_image = None
            original_aspect_ratio = None
            if row < len(self.segment_images) and self.segment_images[row]:
                original_roi_image = self.segment_images[row]
                # 기존 ROI 이미지의 종횡비 계산
                try:
                    import cv2
                    import numpy as np
                    nparr = np.frombuffer(original_roi_image, np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if img is not None:
                        orig_height, orig_width = img.shape[:2]
                        original_aspect_ratio = orig_width / orig_height if orig_height > 0 else None
                except Exception as e:
                    pass
                    # print(f"[씬 분할] 기존 ROI 이미지 종횡비 계산 실패: {e}")
            
            # 첫 번째 씬: start_frame ~ split_frame - 1 (기존 행 업데이트)
            first_start_frame = start_frame
            first_end_frame = split_frame - 1
            first_start_time = first_start_frame / self.fps
            first_end_time = first_end_frame / self.fps
            first_duration = first_end_time - first_start_time
            
            # 두 번째 씬: split_frame ~ end_frame (새 행으로 삽입)
            second_start_frame = split_frame
            second_end_frame = end_frame
            second_start_time = second_start_frame / self.fps
            second_end_time = second_end_frame / self.fps
            second_duration = second_end_time - second_start_time
            
            # 두 번째 씬을 새 행으로 삽입 (기존 행 뒤에)
            new_row = row + 1
            self.table.insertRow(new_row)
            
            # 첫 번째 씬: 기존 행 업데이트
            # 종료 프레임 업데이트
            end_frame_item.setText(str(first_end_frame + 1))
            end_frame_item.setData(Qt.UserRole, first_end_frame)
            
            # 시간 정보 업데이트 (update_row_times 사용하여 정수로 표시)
            self.update_row_times(row)
            
            # 첫 번째 씬의 썸네일 추출 및 업데이트
            # OCR 모드일 때는 기존 ROI 이미지 종횡비 유지
            first_thumbnail = None
            is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']
            
            if is_ocr_mode and original_roi_image and original_aspect_ratio:
                pass
                # OCR 모드: 기존 ROI 이미지 종횡비 유지 (기존 이미지 사용)
                first_thumbnail = original_roi_image
            elif self.video_path and os.path.exists(self.video_path):
                pass
                # 비디오에서 새로 추출
                first_thumbnail = self._extract_frame_thumbnail(self.video_path, first_start_frame)
                # OCR 모드이고 기존 종횡비가 있으면, 새 이미지를 기존 종횡비에 맞게 크롭
                if is_ocr_mode and original_aspect_ratio and first_thumbnail:
                    try:
                        import cv2
                        import numpy as np
                        nparr = np.frombuffer(first_thumbnail, np.uint8)
                        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if img is not None:
                            new_height, new_width = img.shape[:2]
                            new_aspect_ratio = new_width / new_height if new_height > 0 else 1.0
                            
                            # 종횡비가 다르면 기존 종횡비에 맞게 크롭
                            if abs(new_aspect_ratio - original_aspect_ratio) > 0.01:
                                if new_aspect_ratio > original_aspect_ratio:
                                    pass
                                    # 새 이미지가 더 넓음: 높이 기준으로 크롭
                                    target_width = int(new_height * original_aspect_ratio)
                                    x_offset = (new_width - target_width) // 2
                                    img = img[:, x_offset:x_offset + target_width]
                                else:
                                    pass
                                    # 새 이미지가 더 높음: 너비 기준으로 크롭
                                    target_height = int(new_width / original_aspect_ratio)
                                    y_offset = (new_height - target_height) // 2
                                    img = img[y_offset:y_offset + target_height, :]
                                
                                # 크롭된 이미지를 bytes로 변환
                                _, encoded = cv2.imencode('.png', img)
                                first_thumbnail = encoded.tobytes()
                    except Exception as e:
                        pass
                        # print(f"[씬 분할] 첫 번째 씬 이미지 종횡비 조정 실패: {e}")
            
            if first_thumbnail and row < len(self.segment_images):
                self.segment_images[row] = first_thumbnail
                
                # 썸네일 위젯 업데이트
                thumb_widget = self.table.cellWidget(row, 1)
                if thumb_widget:
                    thumb_label = thumb_widget.findChild(QLabel)
                    if thumb_label:
                        is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']

                        # 원본 pixmap 생성
                        original_pixmap = self._pixmap_with_boxes(first_thumbnail, detections, None)

                        if is_ocr_mode:
                            pass
                            # OCR 모드: 실제 이미지 종횡비에 맞게 조정
                            if original_pixmap:
                                orig_width = original_pixmap.width()
                                orig_height = original_pixmap.height()
                                target_height = 80
                                aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                                target_width = int(target_height * aspect_ratio)
                                thumbnail_size = QSize(target_width, target_height)
                                pixmap = original_pixmap.scaled(thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            else:
                                pixmap = None
                        else:
                            pass
                            # 애니매틱 모드: 기존 방식 유지
                            thumbnail_size = QSize(192, 108)
                            pixmap = original_pixmap
                            if pixmap:
                                pixmap = pixmap.scaled(
                                    thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                                )

                        if pixmap:
                            thumb_label.setPixmap(pixmap)
                            thumb_label.setProperty('original_pixmap', original_pixmap)
            
            # 두 번째 씬의 썸네일 추출
            # OCR 모드일 때는 기존 ROI 이미지 종횡비 유지
            second_thumbnail = None
            if is_ocr_mode and original_roi_image and original_aspect_ratio:
                pass
                # OCR 모드: 기존 ROI 이미지 종횡비 유지 (기존 이미지 사용)
                second_thumbnail = original_roi_image
            elif self.video_path and os.path.exists(self.video_path):
                pass
                # 비디오에서 새로 추출
                second_thumbnail = self._extract_frame_thumbnail(self.video_path, second_start_frame)
                # OCR 모드이고 기존 종횡비가 있으면, 새 이미지를 기존 종횡비에 맞게 크롭
                if is_ocr_mode and original_aspect_ratio and second_thumbnail:
                    try:
                        import cv2
                        import numpy as np
                        nparr = np.frombuffer(second_thumbnail, np.uint8)
                        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if img is not None:
                            new_height, new_width = img.shape[:2]
                            new_aspect_ratio = new_width / new_height if new_height > 0 else 1.0
                            
                            # 종횡비가 다르면 기존 종횡비에 맞게 크롭
                            if abs(new_aspect_ratio - original_aspect_ratio) > 0.01:
                                if new_aspect_ratio > original_aspect_ratio:
                                    pass
                                    # 새 이미지가 더 넓음: 높이 기준으로 크롭
                                    target_width = int(new_height * original_aspect_ratio)
                                    x_offset = (new_width - target_width) // 2
                                    img = img[:, x_offset:x_offset + target_width]
                                else:
                                    pass
                                    # 새 이미지가 더 높음: 너비 기준으로 크롭
                                    target_height = int(new_width / original_aspect_ratio)
                                    y_offset = (new_height - target_height) // 2
                                    img = img[y_offset:y_offset + target_height, :]
                                
                                # 크롭된 이미지를 bytes로 변환
                                _, encoded = cv2.imencode('.png', img)
                                second_thumbnail = encoded.tobytes()
                    except Exception as e:
                        pass
                        # print(f"[씬 분할] 두 번째 씬 이미지 종횡비 조정 실패: {e}")
            
            # 두 번째 씬 데이터 추가 (populate_table 로직 참고)
            # ROI 이미지 처리
            roi_bytes = second_thumbnail if second_thumbnail else None

            # segment_images와 segment_detections 리스트에 삽입 (insertRow에 맞춰)
            self.segment_images.insert(new_row, roi_bytes)
            self.segment_detections.insert(new_row, detections if detections else [])
            
            # 테이블에 데이터 추가 (populate_table의 로직 재사용)
            self.table.setItem(new_row, 0, QTableWidgetItem(str(new_row + 1)))
            
            # ROI 샘플 (썸네일) - populate_table의 로직 재사용
            thumb_widget = QWidget()
            thumb_layout = QVBoxLayout(thumb_widget)
            thumb_layout.setContentsMargins(0, 0, 0, 0)
            thumb_layout.setSpacing(0)
            
            thumb_label = QLabel()
            thumb_label.setAlignment(Qt.AlignCenter)
            thumb_label.setStyleSheet("QLabel { background: #050505; border: 1px solid #222; color: #555; }")

            is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']

            # 원본 pixmap 생성
            original_pixmap = self._pixmap_with_boxes(roi_bytes, detections, None)

            if is_ocr_mode:
                pass
                # OCR 모드: 실제 이미지 종횡비에 맞게 조정
                if original_pixmap:
                    orig_width = original_pixmap.width()
                    orig_height = original_pixmap.height()
                    target_height = 80
                    aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                    target_width = int(target_height * aspect_ratio)
                    thumbnail_size = QSize(target_width, target_height)
                    self.table.setRowHeight(new_row, target_height + 10)
                    if new_row == 0:
                        self.table.setColumnWidth(1, target_width + 10)
                    pixmap = original_pixmap.scaled(thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                else:
                    pixmap = None
            else:
                pass
                # 애니매틱 모드: 기존 방식 유지
                thumbnail_size = QSize(192, 108)
                self.table.setRowHeight(new_row, 118)
                if original_pixmap:
                    pixmap = original_pixmap.scaled(
                        thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                else:
                    pixmap = None

            if pixmap:
                thumb_label.setPixmap(pixmap)
                thumb_label.setProperty('original_pixmap', original_pixmap)
            else:
                thumb_label.setText("이미지 없음")
            
            # tooltip 생성
            tooltip_text = f"프레임: {second_start_frame + 1} → {second_end_frame + 1}"
            thumb_label.setToolTip(tooltip_text)
            thumb_layout.addWidget(thumb_label)
            
            # 재생 버튼 오버레이
            play_button = QPushButton("▶")
            play_button.setFixedSize(30, 30)
            play_button.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 165, 0, 100);
                    color: white;
                    border: 2px solid rgba(255, 255, 255, 100);
                    border-radius: 15px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: rgba(255, 165, 0, 180);
                    border: 2px solid rgba(255, 255, 255, 150);
                }
                QPushButton:pressed {
                    background: rgba(255, 140, 0, 200);
                }
            """)
            play_button.setCursor(Qt.PointingHandCursor)
            play_button.setProperty("table_row", new_row)
            play_button.setParent(thumb_label)
            play_button.raise_()
            play_button.show()
            
            def update_button_position():
                if thumb_label.pixmap():
                    label_width = thumb_label.width()
                    label_height = thumb_label.height()
                    x = (label_width - play_button.width()) // 2
                    y = (label_height - play_button.height()) // 2
                    play_button.move(x, y)
            
            original_resize_event = thumb_label.resizeEvent
            def resize_event_wrapper(e):
                if original_resize_event:
                    original_resize_event(e)
                update_button_position()
            thumb_label.resizeEvent = resize_event_wrapper
            
            play_button.clicked.connect(lambda checked, r=new_row: self._on_play_button_clicked(r))
            QTimer.singleShot(0, update_button_position)
            
            self.table.setCellWidget(new_row, 1, thumb_widget)
            
            # ROI 텍스트
            self.table.setItem(new_row, 2, QTableWidgetItem(roi_text))
            
            # 편집 텍스트
            self.table.setItem(new_row, 3, QTableWidgetItem(edit_text))
            
            # 시작 프레임
            start_item = QTableWidgetItem(str(second_start_frame + 1))
            start_item.setData(Qt.UserRole, second_start_frame)
            self.table.setItem(new_row, 4, start_item)
            
            # 종료 프레임
            end_item = QTableWidgetItem(str(second_end_frame + 1))
            end_item.setData(Qt.UserRole, second_end_frame)
            self.table.setItem(new_row, 5, end_item)
            
            # 시간 정보 업데이트 (update_row_times 사용하여 정수로 표시)
            self.update_row_times(new_row)
            
            # 재인덱싱 (new_row 이후의 모든 행)
            for r in range(new_row + 1, self.table.rowCount()):
                item = self.table.item(r, 0)
                if item:
                    item.setText(str(r + 1))

            # 씬 이름 자동 리네임 (애니매틱 모드일 때만)
            if getattr(self, 'ocr_mode', 'titmouse') in ['animatic', 'animatic2']:
                self._renumber_scene_names()
            
            # 씬 리스트 업데이트
            self._update_scene_list()
            
        finally:
            self._updating = False
        
        # 분할된 첫 번째 씬 선택 (미리보기 업데이트) - 기존 행 유지
        self.table.selectRow(row)
        self.update_preview(row)
        
        # segments 업데이트
        segments = self.collect_segments(skip_detections_copy=True)
        self.timeline.set_segments(segments)
        self.update_summary_with_segments(segments)
        self.update_sequence_with_segments(segments)
        
        # 부모 VideoPlayer의 saved_edited_segments 업데이트
        parent = self.parent()
        if parent and hasattr(parent, 'saved_edited_segments'):
            parent.saved_edited_segments = segments
        
        # 웹 UI에 변경사항 동기화 (비동기로 실행하여 UI 반응성 향상)
        QTimer.singleShot(0, self.broadcast_segments_change)
        
        # print(f"[WebSocket] 씬 분할 완료: row={row}, split_frame={split_frame + 1} (1-based)")
    
    def reindex_rows(self, start_row=0):
        """지정된 행부터 재인덱싱 (성능 최적화)"""
        for row in range(start_row, self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setText(str(row + 1))

    def update_summary(self):
        segments = self.collect_segments()
        self.update_summary_with_segments(segments)

    def update_summary_with_segments(self, segments):
        """segments를 파라미터로 받아서 요약 업데이트 (collect_segments 재호출 방지)"""
        total_segments = len(segments)
        total_duration = sum(max(0.0, seg["end_time"] - seg["start_time"]) for seg in segments)
        video_duration = (self.total_frames / self.fps) if self.fps else 0.0
        coverage = (total_duration / video_duration * 100.0) if video_duration else 0.0
        self.summaryLabel.setText(
            f"구간 수: {total_segments} | 총 길이: {total_duration:.2f}s | 커버리지: {coverage:.1f}%"
        )

    def update_sequence(self):
        segments = self.collect_segments()
        self.update_sequence_with_segments(segments)

    def update_sequence_with_segments(self, segments):
        """segments를 파라미터로 받아서 시퀀스 업데이트 (collect_segments 재호출 방지)"""
        if not hasattr(self, "sequenceEdit") or self.sequenceEdit is None:
            pass
            return
        if not segments:
            self.sequenceEdit.setPlainText("구간이 없습니다. ROI를 조정한 뒤 다시 분석하세요.")
            self.update_preview(-1)
            return
        lines = []
        for idx, seg in enumerate(segments, start=1):
            pass
            # edited_text가 있으면 우선 사용, 없으면 text(원본 OCR 결과) 사용
            display_text = seg.get('edited_text') or seg.get('text') or "구간"
            # 테이블과 동일하게 1-based로 표시 (VFX 업계 표준)
            start_frame = int(seg.get('start_frame', 0))
            end_frame = int(seg.get('end_frame', start_frame))
            lines.append(
                f"{idx:02d}. {display_text} | 프레임 {start_frame + 1} → {end_frame + 1} | "
                f"{seg['start_time']:.3f}s → {seg['end_time']:.3f}s"
            )
        self.sequenceEdit.setPlainText("\n".join(lines))

    def on_scene_list_item_clicked(self, item):
        """씬 리스트에서 아이템 클릭 시 테이블 행 선택 및 프리뷰 업데이트"""
        row = item.data(Qt.UserRole)
        if row is not None and 0 <= row < self.table.rowCount():
            self.table.selectRow(row)
            self.update_preview(row, immediate=True)  # 클릭 이벤트는 즉시 반응
    
    def on_selection_changed(self, selected, deselected):
        # print(f"[OCRReviewDialog] on_selection_changed 호출, _timeline_updating={getattr(self, '_timeline_updating', False)}")
        selection_model = self.table.selectionModel()
        selected_rows = []
        if selection_model:
            selected_rows = sorted({index.row() for index in selection_model.selectedRows()})
        # print(f"[OCRReviewDialog] 선택된 테이블 행: {selected_rows}")

        if selected_rows:
            pass
            # debounce 처리: 빠른 연속 호출 시 마지막 호출만 실행
            row = selected_rows[0]
            self._pending_preview_row = row

            # 새로운 행이 선택되었을 때 프리뷰 프레임 초기화 (OCR 모드에서도)
            # 이전에 선택된 행과 다른 행이 선택되면 _preview_current_display_frame을 리셋
            if not hasattr(self, '_last_selected_row') or self._last_selected_row != row:
                self._preview_current_display_frame = None  # 리셋하여 start_frame으로 초기화되도록
                self._last_selected_row = row

            self._preview_update_timer.stop()
            self._preview_update_timer.start(50)  # 50ms 지연

            # 씬 리스트 선택도 업데이트 (O(1) 접근으로 최적화)
            if hasattr(self, 'sceneListWidget'):
                pass
                # 테이블 행 인덱스와 씬 리스트 인덱스는 1:1 매핑됨
                if row < self.sceneListWidget.count():
                    self.sceneListWidget.setCurrentRow(row)
        else:
            self._pending_preview_row = -1
            self._preview_update_timer.stop()
            self._preview_update_timer.start(50)  # 50ms 지연
            
            # 씬 리스트 선택 해제
            if hasattr(self, 'sceneListWidget'):
                self.sceneListWidget.clearSelection()

        # 타임라인 하이라이트 동기화 (다중 선택 지원)
        # 타임라인이 테이블을 업데이트 중이면 타임라인 하이라이트를 변경하지 않음
        if hasattr(self, 'timeline') and self.timeline and not getattr(self, '_timeline_updating', False):
            pass
            # 프레임 검색 대신 인덱스 직접 전달 (O(N) -> O(1))
            # 테이블 행 인덱스는 타임라인 세그먼트 인덱스와 1:1 매핑됨
            self.timeline.highlight_segments_by_indices(selected_rows)
            
            # 타임라인 자동 스크롤 (첫 번째 선택된 항목이 보이도록)
            if selected_rows and hasattr(self, 'timeline_scroll'):
                first_index = selected_rows[0]
                x_pos = self.timeline.get_segment_x_position(first_index)
                if x_pos is not None:
                    pass
                    # 약간의 여백을 두고 스크롤 (왼쪽 정렬)
                    self.timeline_scroll.horizontalScrollBar().setValue(int(x_pos - self.timeline.thumbnail_spacing))

    def update_preview(self, row, immediate=False):
        """미리보기 업데이트 요청 (debounce 처리)
        
        Args:
            row: 업데이트할 행 번호
            immediate: True이면 즉시 실행 (클릭 이벤트 등), False이면 debounce 처리
        """
        if immediate:
            pass
            # 클릭 이벤트 등 즉시 반응이 필요한 경우
            self._preview_update_timer.stop()
            self._pending_preview_row = row
            self._do_update_preview()
        else:
            pass
            # 스크롤 등 연속 호출이 예상되는 경우 debounce 처리
            self._pending_preview_row = row
            self._preview_update_timer.stop()
            self._preview_update_timer.start(50)  # 50ms 지연
    
    def _do_update_preview(self):
        """실제 미리보기 업데이트 수행"""
        if not hasattr(self, "previewLabel"):
            pass
            return
        
        row = self._pending_preview_row
        if row is None:
            pass
            return
            
        if row < 0 or row >= self.table.rowCount():
            self.previewLabel.setPixmap(QPixmap())
            self.previewLabel.setText("프리뷰 영상")
            self.previewText.setPlainText("선택된 구간이 없습니다.")
            self._update_segment_info_display()
            return

        # OCR 모드 확인
        is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']
        
        roi_bytes = None
        detections = self.segment_detections[row] if row < len(self.segment_detections) else []
        start_frame = None
        
        # 테이블에서 시작 프레임 가져오기
        start_frame_item = self.table.item(row, 4)
        if start_frame_item:
            start_frame = start_frame_item.data(Qt.UserRole)
            if start_frame is None:
                start_frame = self._safe_int(start_frame_item) - 1
        
        selection_model = self.table.selectionModel() if hasattr(self.table, 'selectionModel') else None
        multi_selected = False
        if selection_model:
            selected_rows = selection_model.selectedRows()
            multi_selected = len(selected_rows) > 1

        # 타임라인 하이라이트 업데이트 (단일 선택일 때만)
        # 성능 최적화: on_selection_changed에서 이미 처리하므로 중복 호출 제거
        # if (not multi_selected) and start_frame is not None and hasattr(self, 'timeline') and self.timeline:
        #     if not hasattr(self, '_last_highlighted_frame') or self._last_highlighted_frame != start_frame:
        #         self.timeline.highlight_segment_by_frame(start_frame)
        #         self._last_highlighted_frame = start_frame
        
        # 프리뷰 영상은 항상 비디오에서 전체 프레임을 추출 (OCR/애니매틱 모두 동일)
        # ROI 샘플 이미지는 테이블에서만 사용하고, 프리뷰는 전체 프레임 표시
        # 애니매틱 모드: 씬 클릭 시 start_frame과 동기화 (ROI 샘플 이미지와 동일한 프레임 표시)
        # OCR 모드: 프레임 단위 이동 시 _preview_current_display_frame 사용
        
        # 종료 프레임도 미리 가져오기
        end_frame_item = self.table.item(row, 5)
        end_frame = None
        if end_frame_item:
            end_frame = end_frame_item.data(Qt.UserRole)
            if end_frame is None:
                end_frame = self._safe_int(end_frame_item) - 1
        
        if not is_ocr_mode:
            pass
            # 애니매틱 모드: 항상 start_frame 사용 (ROI 샘플 이미지와 동기화)
            display_frame = start_frame if start_frame is not None else 0
            # _preview_current_display_frame도 start_frame으로 초기화
            self._preview_current_display_frame = display_frame
            # 현재 씬의 시작/종료 프레임도 업데이트
            if start_frame is not None:
                self._preview_current_segment_start = start_frame
            if end_frame is not None:
                self._preview_current_segment_end = end_frame
            # 미디어 파일 로드 (오디오 재생을 위해)
            self._load_preview_media()
        else:
            pass
            # OCR 모드: row가 변경되었으면 start_frame으로 초기화, 아니면 현재 표시 중인 프레임 사용
            # row가 변경되었는지 확인 (이전에 선택된 row와 비교)
            if not hasattr(self, '_last_preview_row') or self._last_preview_row != row:
                pass
                # row가 변경되었으면 start_frame으로 초기화
                display_frame = start_frame if start_frame is not None else 0
                self._preview_current_display_frame = display_frame
                self._last_preview_row = row
                # 현재 씬의 시작/종료 프레임도 업데이트
                if start_frame is not None:
                    self._preview_current_segment_start = start_frame
                if end_frame is not None:
                    self._preview_current_segment_end = end_frame
                # 미디어 파일 로드 (오디오 재생을 위해)
                self._load_preview_media()
            else:
                pass
                # 같은 row이면 현재 표시 중인 프레임 사용 (프레임 단위 이동 시)
                # None이 아니고 0 이상이면 유효한 프레임으로 간주
                if hasattr(self, '_preview_current_display_frame') and self._preview_current_display_frame is not None:
                    display_frame = self._preview_current_display_frame
                else:
                    display_frame = start_frame if start_frame is not None else 0
                    self._preview_current_display_frame = display_frame
        if display_frame is not None and self.video_path and os.path.exists(self.video_path):
            pass
            # 성능 최적화: 프레임 추출 결과 캐싱
            if display_frame in self._preview_frame_cache:
                roi_bytes = self._preview_frame_cache[display_frame]
            else:
                roi_bytes = self._extract_frame_thumbnail(self.video_path, display_frame)
                if roi_bytes:
                    pass
                    # 캐시에 저장 (최대 20개만 유지)
                    if len(self._preview_frame_cache) >= 20:
                        pass
                        # 가장 오래된 항목 제거 (FIFO)
                        oldest_frame = next(iter(self._preview_frame_cache))
                        del self._preview_frame_cache[oldest_frame]
                    self._preview_frame_cache[display_frame] = roi_bytes
            
            # 성능 최적화: 로그 출력 제거
            # if is_ocr_mode:
            #     print(f"[프리뷰 업데이트] OCR 모드: 테이블 행={row + 1}, start_frame={start_frame}, 전체 프레임 추출={'성공' if roi_bytes else '실패'}")
            # else:
            #     print(f"[프리뷰 업데이트] 애니매틱 모드: 테이블 행={row + 1}, start_frame={start_frame}, 이미지 추출={'성공' if roi_bytes else '실패'}")
        
        # 이미지 처리 (roi_bytes가 있는 경우에만)
        if roi_bytes:
            pass
            # 캐시 키 생성 (start_frame을 포함하여 프레임별로 캐시)
            # row 대신 start_frame을 사용하여 병합/삭제 후에도 올바른 캐시 사용
            # 프리뷰 위젯의 크기를 기준으로 캐시 키 생성 (UI 확장 시에도 일관성 유지)
            preview_size = self.preview_widget.size()
            cache_key = (start_frame if start_frame is not None else row, preview_size.width(), preview_size.height())
            
            # 캐시 확인 (성능 최적화: 캐시 히트 시 즉시 표시)
            if cache_key in self._preview_cache:
                scaled = self._preview_cache[cache_key]
                self.previewLabel.setPixmap(scaled)
                self.previewLabel.setText("")
            else:
                pass
                # 프리뷰 영상은 전체 프레임이므로 hint_size를 None으로 전달 (원본 크기 유지)
                # OCR 모드일 때도 detections를 전달하여 OCR 박스 표시
                # 성능 최적화: pixmap 생성과 스케일링을 한 번에 처리
                pixmap = self._pixmap_with_boxes(roi_bytes, detections, None)
                if pixmap:
                    pass
                    # 프리뷰 영상 크기에 맞게 스케일 (KeepAspectRatio로 비율 유지)
                    # 부모 위젯의 크기를 사용하여 UI 확장 시에도 일관되게 표시
                    preview_size = self.preview_widget.size()
                    # 성능 최적화: FastTransformation 사용 (SmoothTransformation보다 빠름)
                    scaled = pixmap.scaled(
                        preview_size, Qt.KeepAspectRatio, Qt.FastTransformation
                    )
                    # 캐시에 저장 (최대 20개로 증가하여 캐시 히트율 향상)
                    if len(self._preview_cache) >= 20:
                        pass
                        # 가장 오래된 항목 제거 (FIFO)
                        oldest_key = next(iter(self._preview_cache))
                        del self._preview_cache[oldest_key]
                    self._preview_cache[cache_key] = scaled
                    self.previewLabel.setPixmap(scaled)
                    self.previewLabel.setText("")
                    # 오버레이가 항상 위에 표시되도록 다시 raise
                    if hasattr(self, 'frame_overlay'):
                        self.frame_overlay.raise_()
                        self.frame_overlay.show()
                else:
                    self.previewLabel.setPixmap(QPixmap())
                    self.previewLabel.setText("이미지 없음")
        else:
            pass
            # 비디오에서 추출하지 못했으면 segment_images에서 가져오기 (fallback, OCR 모드에서만)
            if is_ocr_mode:
                roi_bytes = self.segment_images[row] if row < len(self.segment_images) else None
                if roi_bytes:
                    pass
                    # ROI 샘플 이미지를 프리뷰에 표시 (전체 프레임을 추출하지 못한 경우)
                    pixmap = self._pixmap_with_boxes(roi_bytes, detections, None)
                    if pixmap:
                        pass
                        # 부모 위젯의 크기를 사용하여 UI 확장 시에도 일관되게 표시
                        preview_size = self.preview_widget.size()
                        scaled = pixmap.scaled(
                            preview_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                        self.previewLabel.setPixmap(scaled)
                        self.previewLabel.setText("")
                    else:
                        self.previewLabel.setPixmap(QPixmap())
                        self.previewLabel.setText("이미지 없음")
                else:
                    self.previewLabel.setPixmap(QPixmap())
                    self.previewLabel.setText("이미지 없음")
            else:
                self.previewLabel.setPixmap(QPixmap())
                self.previewLabel.setText("이미지 없음")

        text = self.table.item(row, 3).text() if self.table.item(row, 3) else ""
        # 테이블에서 프레임 정보 가져오기 (UserRole 우선 사용)
        start_frame_item = self.table.item(row, 4)
        end_frame_item = self.table.item(row, 5)
        
        if start_frame_item and start_frame_item.data(Qt.UserRole) is not None:
            start_frame = int(start_frame_item.data(Qt.UserRole))
        else:
            start_frame = self._safe_int(start_frame_item) - 1 if start_frame_item else 0
        
        if end_frame_item and end_frame_item.data(Qt.UserRole) is not None:
            end_frame = int(end_frame_item.data(Qt.UserRole))
        else:
            end_frame = self._safe_int(end_frame_item) - 1 if end_frame_item else 0
        
        # 현재 씬의 프레임 범위 저장 (프레임 단위 이동용)
        self._preview_current_segment_start = start_frame
        self._preview_current_segment_end = end_frame
        # 현재 표시 중인 프레임을 시작 프레임으로 초기화 (이미 설정되지 않은 경우만)
        if not hasattr(self, '_preview_current_display_frame') or self._preview_current_display_frame is None:
            self._preview_current_display_frame = start_frame if start_frame is not None else 0
        # 프레임 표시 업데이트
        self._update_frame_display()
        
        start_time = start_frame / self.fps if self.fps else 0.0
        end_time = (end_frame + 1) / self.fps if self.fps else 0.0
        detail_lines = self._format_detection_lines(detections)
        self.previewLabel.setToolTip("\n".join(detail_lines))
        # 테이블과 동일하게 1-based로 표시 (VFX 업계 표준)
        preview_content = (
            "텍스트: {text}\n프레임: {start} → {end}\n시간: {start_time:.3f}s → {end_time:.3f}s\n".format(
                text=text,
                start=start_frame + 1 if start_frame is not None else 0,
                end=end_frame + 1 if end_frame is not None else 0,
                start_time=start_time,
                end_time=end_time,
            )
            + "세부 인식:\n" + "\n".join(detail_lines)
        )
        self.previewText.setPlainText(preview_content)
        
        # 구간 길이 및 편집 텍스트 업데이트
        if start_frame is not None and end_frame is not None and end_frame >= start_frame:
            segment_length = (end_frame - start_frame) + 1
        else:
            segment_length = None
        self._update_segment_info_display(segment_length, self.fps, text)

    def _pixmap_with_boxes(self, data, detections, hint_size):
        if not data:
            pass
            return None
        pixmap = QPixmap()
        if not pixmap.loadFromData(data, "PNG"):
            pass
            return None
        
        # detections가 없으면 박스 그리기 생략하여 성능 향상
        if not detections:
            pass
            return pixmap
        
        painter = QPainter(pixmap)
        
        # 이미지 경계값 저장
        img_width = pixmap.width()
        img_height = pixmap.height()
        
        # 1. 사용자가 지정한 ROI 영역 전체를 주황색 박스로 표시
        roi_pen = QPen(QColor(255, 128, 0, 220))
        roi_pen.setWidth(max(3, pixmap.width() // 100))  # ROI 박스는 더 두껍게
        painter.setPen(roi_pen)
        # ROI 영역 전체를 주황색 박스로 표시 (이미지 전체가 ROI이므로)
        roi_rect = QRectF(0, 0, img_width, img_height)
        painter.drawRect(roi_rect)
        
        # 2. OCR이 인식한 개별 텍스트 박스는 더 얇은 선으로 표시 (선택적)
        if detections:
            font = painter.font()
            font.setPointSizeF(max(8.0, pixmap.height() * 0.06))
            painter.setFont(font)
            
            # OCR 텍스트 박스는 더 얇고 다른 스타일로 (선택사항)
            # ocr_pen = QPen(QColor(0, 255, 0, 180))  # 녹색으로 표시 (선택사항)
            # ocr_pen.setWidth(max(1, pixmap.width() // 200))
            # painter.setPen(ocr_pen)
            
            for det in detections:
                box = det.get("box")
                if not box or len(box) != 4:
                    pass
                    continue
                points = []
                for pt in box:
                    if isinstance(pt, (list, tuple)) and len(pt) == 2:
                        pass
                        # 좌표를 이미지 경계 내로 클리핑
                        x = max(0, min(img_width, pt[0] * img_width))
                        y = max(0, min(img_height, pt[1] * img_height))
                        points.append(QPointF(x, y))
                
                if len(points) != 4:
                    pass
                    continue
                
                # OCR 텍스트 박스는 주황색으로 표시 (ROI와 동일한 색상)
                # 또는 주석 처리하여 표시하지 않을 수도 있음
                polygon = QPolygonF(points)
                ocr_pen = QPen(QColor(255, 128, 0, 150))  # 반투명 주황색
                ocr_pen.setWidth(max(1, pixmap.width() // 200))
                painter.setPen(ocr_pen)
                painter.drawPolygon(polygon)
                
                text = det.get("text") or ""
                if text:
                    xs = [point.x() for point in points]
                    ys = [point.y() for point in points]
                    min_x, max_x = min(xs), max(xs)
                    min_y, max_y = min(ys), max(ys)
                    rect_width = max(20.0, max_x - min_x)
                    point_size = font.pointSizeF()
                    if point_size <= 0:
                        point_size = max(8.0, img_height * 0.06)
                        font.setPointSizeF(point_size)
                        painter.setFont(font)
                    text_height = point_size * 1.3
                    
                    # 텍스트 영역도 이미지 경계 내로 클리핑
                    text_x = max(0.0, min(min_x, img_width - rect_width))
                    text_y = max(0.0, min(min_y - text_height, img_height - text_height))
                    text_width = min(rect_width, img_width - text_x)
                    text_height_clipped = min(text_height, img_height - text_y)
                    
                    text_rect = QRectF(
                        text_x,
                        text_y,
                        text_width,
                        text_height_clipped,
                    )
                    painter.fillRect(text_rect, QColor(0, 0, 0, 160))
                    painter.setPen(QColor(255, 255, 255))
                    painter.drawText(text_rect, Qt.AlignCenter, text)
        
        painter.end()
        
        if hint_size:
            pass
            # 전체 이미지가 보이도록 비율을 유지하면서 16:9 영역에 맞춤
            # 이미지가 잘리지 않도록 타겟 영역 안에 완전히 들어가도록 처리
            original_width = pixmap.width()
            original_height = pixmap.height()
            
            if original_width <= 0 or original_height <= 0:
                pass
                return pixmap
            
            # 힌트 크기 (16:9 비율)
            target_width = hint_size.width()
            target_height = hint_size.height()
            
            # 전체 이미지가 타겟 영역 안에 들어가도록 스케일 계산
            # Qt.KeepAspectRatio를 사용하면 자동으로 비율을 유지하면서 타겟 크기 안에 맞춤
            # 타겟 크기를 넘지 않도록 하기 위해 Qt.KeepAspectRatio 사용
            scaled_pixmap = pixmap.scaled(
                target_width, target_height,
                Qt.KeepAspectRatio,  # 비율 유지하면서 타겟 크기 안에 맞춤
                Qt.SmoothTransformation
            )
            
            # 실제 스케일된 크기 (Qt.KeepAspectRatio로 인해 타겟보다 작거나 같음)
            actual_scaled_width = scaled_pixmap.width()
            actual_scaled_height = scaled_pixmap.height()
            
            # 16:9 배경에 중앙 정렬하여 배치
            result_pixmap = QPixmap(target_width, target_height)
            result_pixmap.fill(QColor(5, 5, 5))  # 배경색 (테이블 배경과 동일)
            
            painter = QPainter(result_pixmap)
            # 중앙 정렬 (스케일된 이미지가 타겟 크기보다 작거나 같으므로 잘리지 않음)
            x_offset = (target_width - actual_scaled_width) // 2
            y_offset = (target_height - actual_scaled_height) // 2
            painter.drawPixmap(x_offset, y_offset, scaled_pixmap)
            painter.end()
            
            return result_pixmap
        return pixmap

    def _update_segment_info_display(self, length_frames=None, fps=None, edit_text=None):
        """프레임 입력 필드 옆 정보 레이블을 업데이트"""
        if hasattr(self, 'segment_length_label') and self.segment_length_label:
            if length_frames is None or length_frames <= 0:
                self.segment_length_label.setText("-f")
            else:
                self.segment_length_label.setText(f"{length_frames}f")
        if hasattr(self, 'edit_text_label') and self.edit_text_label:
            text = edit_text.strip() if isinstance(edit_text, str) else ""
            display = text if text else "-"
            self.edit_text_label.setText(display)
            self.edit_text_label.setToolTip(display if display != "-" else "")

    def _on_play_button_clicked(self, row):
        """재생 버튼 클릭 핸들러 - 재생/정지 토글"""
        # sender()를 사용하여 클릭된 버튼을 찾고, 그 버튼이 어느 row에 속하는지 찾기
        sender_button = self.sender()
        if not sender_button:
            pass
            # print(f"[재생 버튼 클릭] sender를 찾을 수 없음")
            return
        
        # 클릭된 버튼이 어느 row에 속하는지 찾기
        actual_row = None
        for r in range(self.table.rowCount()):
            widget = self.table.cellWidget(r, 1)  # ROI 샘플 컬럼
            if widget:
                pass
                # 위젯 내부의 thumb_label 찾기
                thumb_label = widget.findChild(QLabel)
                if thumb_label and sender_button.parent() == thumb_label:
                    actual_row = r
                    break
        
        # 찾지 못하면 파라미터로 전달된 row 사용 (fallback)
        if actual_row is None:
            actual_row = row
            # print(f"[재생 버튼 클릭] row를 찾지 못해 파라미터 row 사용: 테이블 행={row + 1}")
        
        # 같은 세그먼트가 재생 중이면 정지, 아니면 재생
        if self._preview_playing and self._preview_playing_row == actual_row:
            pass
            # 현재 재생 중인 세그먼트를 정지
            # print(f"[재생 버튼 클릭] 정지: 테이블 행={actual_row + 1}")
            self._stop_preview_playback()
        else:
            pass
            # 새로운 세그먼트 재생
            # 테이블에서 직접 프레임 정보 가져오기
            start_item = self.table.item(actual_row, 4)  # 시작 프레임 컬럼
            end_item = self.table.item(actual_row, 5)    # 종료 프레임 컬럼
            
            if start_item and end_item:
                pass
                # UserRole에 0-based 프레임이 저장되어 있음
                seg_start_frame = start_item.data(Qt.UserRole)
                seg_end_frame = end_item.data(Qt.UserRole)
                
                # UserRole이 없으면 텍스트에서 가져오기 (1-based이므로 -1)
                if seg_start_frame is None:
                    seg_start_frame = self._safe_int(start_item) - 1
                if seg_end_frame is None:
                    seg_end_frame = self._safe_int(end_item) - 1
                
                # print(f"[재생 버튼 클릭] 재생: 테이블 행={actual_row + 1}, start_frame={seg_start_frame + 1}, end_frame={seg_end_frame + 1}")
                self._play_preview_segment(seg_start_frame, seg_end_frame, actual_row)
            else:
                pass
                # print(f"[재생 버튼 클릭] 프레임 정보 없음: 테이블 행={actual_row + 1}, start_item={start_item}, end_item={end_item}")
    
    def _play_preview_segment(self, start_frame, end_frame, row=None):
        """프리뷰 영역에서 비디오 세그먼트 재생"""
        if not self.video_path or not os.path.exists(self.video_path):
            pass
            # print(f"[프리뷰 재생] 비디오 경로 없음: {self.video_path}")
            return
        
        # print(f"[프리뷰 재생] 시작: 프레임 {start_frame + 1} → {end_frame + 1}, 테이블 행={row + 1 if row is not None else 'N/A'}")
        
        # 기존 재생 중지 (이전 버튼 텍스트 복원)
        self._stop_preview_playback()
        
        # 현재 재생 중인 row 저장
        self._preview_playing_row = row
        
        # 비디오 캡처 열기
        self._preview_video_cap = cv2.VideoCapture(self.video_path)
        if not self._preview_video_cap.isOpened():
            pass
            # print(f"[프리뷰 재생] 비디오 열기 실패: {self.video_path}")
            return
        
        # FPS 가져오기
        fps = self._preview_video_cap.get(cv2.CAP_PROP_FPS) or 24.0
        total_frames = int(self._preview_video_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # print(f"[프리뷰 재생] FPS: {fps}, 총 프레임: {total_frames}")
        
        # 프레임 범위 검증
        start_frame = max(0, min(start_frame, total_frames - 1))
        end_frame = max(start_frame, min(end_frame, total_frames - 1))
        # print(f"[프리뷰 재생] 검증 후: 프레임 {start_frame + 1} → {end_frame + 1}")

        # 타이머 간격: 빠르게 설정하여 부드러운 재생 (60fps 기준)
        frame_interval = 16  # 약 60fps로 체크 (오디오 위치 기반으로 프레임 동기화)

        # 재생 범위 설정
        self._preview_start_frame = start_frame
        self._preview_end_frame = end_frame
        self._preview_current_frame = start_frame
        self._preview_current_display_frame = start_frame
        self._preview_sync_counter = 0  # 싱크 카운터 초기화
        self._preview_fps = fps  # FPS 저장 (동기화에 사용)
        # 프레임 번호 오버레이 업데이트
        self._update_frame_display()
        
        # 시작 프레임으로 정확히 이동 (OpenCV의 set이 부정확할 수 있으므로 직접 이동)
        self._preview_video_cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        # 실제 위치 확인 및 보정
        actual_frame = int(self._preview_video_cap.get(cv2.CAP_PROP_POS_FRAMES))
        # print(f"[프리뷰 재생] 프레임 이동 시도: 요청={start_frame + 1}, 실제={actual_frame + 1}")
        
        # 정확한 프레임으로 이동 (차이가 있으면 보정)
        if actual_frame != start_frame:
            pass
            # 0번 프레임부터 읽어서 원하는 프레임까지 이동
            self._preview_video_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            for i in range(start_frame):
                ret = self._preview_video_cap.read()[0]
                if not ret:
                    pass
                    # print(f"[프리뷰 재생] 프레임 {i} 읽기 실패")
                    break
            actual_frame = int(self._preview_video_cap.get(cv2.CAP_PROP_POS_FRAMES))
            # print(f"[프리뷰 재생] 프레임 보정 후: 실제={actual_frame + 1}")
        
        # 첫 프레임을 즉시 표시 (재생 시작 전)
        ret, frame = self._preview_video_cap.read()
        if ret:
            pass
            # print(f"[프리뷰 재생] 첫 프레임 읽기 성공: {frame.shape}, 실제 프레임={actual_frame + 1}")
            # BGR을 RGB로 변환
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = frame_rgb.shape[:2]
            
            # QImage로 변환
            q_img = QImage(frame_rgb.data, w, h, w * 3, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)
            
            # 프리뷰 라벨 크기에 맞춰 스케일
            if hasattr(self, 'previewLabel') and self.previewLabel:
                pass
                # 부모 위젯의 크기를 사용하여 UI 확장 시에도 일관되게 표시
                preview_size = self.preview_widget.size()
                scaled = pixmap.scaled(
                    preview_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.previewLabel.setPixmap(scaled)
                self.previewLabel.setText("")
        else:
            pass
            # print(f"[프리뷰 재생] 첫 프레임 읽기 실패")
        
        # 재생 시작
        self._preview_playing = True
        self._preview_frame_log_counter = 0  # 로그 카운터 초기화
        self._preview_play_timer.start(frame_interval)
        # 프리뷰 재생 버튼 텍스트 업데이트
        if hasattr(self, 'preview_play_button'):
            self.preview_play_button.setText("⏸")
        # print(f"[프리뷰 재생] 재생 시작: {frame_interval}ms 간격 (오디오 기반 동기화)")

        # 오디오 재생 시작 (QMediaPlayer)
        if hasattr(self, '_preview_media_player'):
            pass
            # 미디어가 로드되어 있지 않으면 로드
            if self._preview_media_player.mediaStatus() == QMediaPlayer.NoMedia:
                media_content = QMediaContent(QUrl.fromLocalFile(self.video_path))
                self._preview_media_player.setMedia(media_content)
                # print(f"[프리뷰 재생] 미디어 파일 로드: {self.video_path}")

            # 동적 오프셋 계산 (메인 플레이어와 동일)
            video_duration = total_frames / fps if fps > 0 else 0
            dynamic_offset = self._calculate_audio_offset(video_duration, start_frame, fps)

            # 오프셋 저장 (프레임 동기화에 사용)
            self._preview_audio_offset = dynamic_offset

            # 시작 프레임에 해당하는 오디오 위치로 이동 (밀리초 단위, 오프셋 적용)
            audio_position = max(0, int(start_frame / fps * 1000) - dynamic_offset)
            self._preview_media_player.setPosition(audio_position)

            # 재생 시작
            self._preview_media_player.play()
            # print(f"[프리뷰 재생] 오디오 재생 시작: 위치={audio_position}ms, 프레임={start_frame + 1}, FPS={fps}, 오프셋={dynamic_offset}ms")

        # 재생 버튼 텍스트를 정지 아이콘으로 변경
        if row is not None:
            self._update_play_button_text(row, "⏸")
    
    def _update_preview_video_frame(self):
        """프리뷰 비디오 프레임 업데이트 (오디오 위치 기반 동기화)"""
        if not self._preview_playing or not self._preview_video_cap:
            pass
            return

        # QMediaPlayer의 현재 오디오 위치를 가져와서 비디오 프레임 계산
        if not hasattr(self, '_preview_media_player') or self._preview_media_player.state() != QMediaPlayer.PlayingState:
            self._stop_preview_playback()
            return

        # 오디오 현재 위치 (ms)
        audio_position = self._preview_media_player.position()

        # 오디오 위치를 비디오 프레임으로 변환
        # audio_position = (frame / fps * 1000) - offset
        # frame = (audio_position + offset) / 1000 * fps
        fps = getattr(self, '_preview_fps', 24.0)
        offset = getattr(self, '_preview_audio_offset', 0)
        calculated_frame = int((audio_position + offset) / 1000.0 * fps)

        # 디버그 로그 (100 프레임마다)
        if not hasattr(self, '_preview_frame_log_counter'):
            self._preview_frame_log_counter = 0
        self._preview_frame_log_counter += 1
        if self._preview_frame_log_counter % 100 == 0:
            pass
            # print(f"[프리뷰 동기화] 오디오={audio_position}ms, 오프셋={offset}ms, 프레임={calculated_frame + 1}, FPS={fps:.3f}")

        # 프레임 범위 확인 (웹 UI와 동일하게 >= 사용)
        # calculated_frame이 end_frame에 도달하거나 넘어서면 종료
        should_stop = calculated_frame >= self._preview_end_frame
        
        if should_stop:
            pass
            # end_frame 프레임을 표시하기 위해 current_frame을 end_frame으로 설정
            current_frame = self._preview_end_frame
        else:
            pass
            # 프레임 범위 제한 (end_frame까지 재생 가능하도록)
            current_frame = max(self._preview_start_frame, min(calculated_frame, self._preview_end_frame))

        # 현재 프레임 위치로 정확히 이동
        self._preview_video_cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)

        # 프레임 읽기
        ret, frame = self._preview_video_cap.read()
        if not ret:
            pass
            # print(f"[프리뷰 재생] 프레임 읽기 실패: 프레임={current_frame + 1}")
            self._stop_preview_playback()
            return

        # BGR을 RGB로 변환
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = frame_rgb.shape[:2]

        # QImage로 변환
        q_img = QImage(frame_rgb.data, w, h, w * 3, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)

        # 프리뷰 라벨 크기에 맞춰 스케일
        if hasattr(self, 'previewLabel') and self.previewLabel:
            pass
            # 부모 위젯의 크기를 사용하여 UI 확장 시에도 일관되게 표시
            preview_size = self.preview_widget.size()
            scaled = pixmap.scaled(
                preview_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.previewLabel.setPixmap(scaled)
            self.previewLabel.setText("")

        # 현재 표시 중인 프레임 업데이트
        self._preview_current_frame = current_frame
        self._preview_current_display_frame = current_frame
        # 프레임 번호 오버레이 업데이트
        self._update_frame_display()
        
        # end_frame에 도달했으면 종료
        if should_stop:
            pass
            # print(f"[프리뷰 재생] 종료: 계산된 프레임={calculated_frame + 1}, 종료 프레임={self._preview_end_frame + 1}")
            self._stop_preview_playback()
            return
    
    def _update_play_button_text(self, row, text):
        """특정 row의 재생 버튼 텍스트 업데이트"""
        if row < 0 or row >= self.table.rowCount():
            pass
            return
        
        widget = self.table.cellWidget(row, 1)  # ROI 샘플 컬럼
        if widget:
            pass
            # 위젯 내부의 재생 버튼 찾기
            play_button = widget.findChild(QPushButton)
            if play_button:
                play_button.setText(text)

    def resizeEvent(self, event):
        """다이얼로그 크기 변경 시 프리뷰 업데이트"""
        super().resizeEvent(event)

        # 크기 변경 시 캐시 무효화 (새 크기에 맞게 다시 스케일링)
        if hasattr(self, '_preview_cache'):
            self._preview_cache.clear()

        # 현재 선택된 행의 프리뷰를 다시 그림
        if hasattr(self, 'table') and self.table.rowCount() > 0:
            selected_rows = self.table.selectionModel().selectedRows()
            if selected_rows:
                current_row = selected_rows[0].row()
                # debounce 처리하여 여러 번 호출되지 않도록 함
                if hasattr(self, 'update_preview'):
                    self.update_preview(current_row)

    def _on_thumbnail_size_changed(self, value):
        """썸네일 크기 슬라이더 변경 핸들러 (최적화된 버전)"""
        # OCR 모드 확인
        is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']

        # 슬라이더 값에 따라 썸네일 크기 계산
        if is_ocr_mode:
            pass
            # OCR 모드: 높이 고정, 가로는 종횡비에 맞게 (첫 번째 이미지 기준)
            # 첫 번째 행의 원본 이미지 비율 확인
            if self.table.rowCount() > 0:
                widget = self.table.cellWidget(0, 1)
                if widget:
                    thumb_label = widget.findChild(QLabel)
                    if thumb_label:
                        original_pixmap = thumb_label.property('original_pixmap')
                        if original_pixmap:
                            orig_width = original_pixmap.width()
                            orig_height = original_pixmap.height()
                            aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0

                            # 높이 기준: 40 ~ 160 (슬라이더 값 1~4)
                            base_height = 40
                            thumbnail_height = base_height * value
                            thumbnail_width = int(thumbnail_height * aspect_ratio)
                        else:
                            pass
                            # 원본이 없으면 기본값
                            base_height = 40
                            thumbnail_height = base_height * value
                            thumbnail_width = thumbnail_height * 3  # 기본 3:1 비율 가정
                    else:
                        base_height = 40
                        thumbnail_height = base_height * value
                        thumbnail_width = thumbnail_height * 3
                else:
                    base_height = 40
                    thumbnail_height = base_height * value
                    thumbnail_width = thumbnail_height * 3
            else:
                base_height = 40
                thumbnail_height = base_height * value
                thumbnail_width = thumbnail_height * 3
        else:
            pass
            # 애니매틱 모드: 96x54 ~ 384x216
            base_width = 96
            base_height = 54
            thumbnail_width = base_width * value
            thumbnail_height = base_height * value

        # 크기 표시 레이블 업데이트
        if hasattr(self, 'thumbnail_size_value_label'):
            self.thumbnail_size_value_label.setText(f"{thumbnail_width}×{thumbnail_height}")

        # 테이블 컬럼 너비 및 행 높이 조정
        column_width = thumbnail_width + 10  # 여백 추가
        row_height = thumbnail_height + 10   # 여백 추가

        self.table.setColumnWidth(1, column_width)

        # 썸네일 크기 캐시 저장
        thumbnail_size = QSize(thumbnail_width, thumbnail_height)

        # 테이블 업데이트 블록 (한 번에 처리)
        self.table.setUpdatesEnabled(False)

        # 모든 행 업데이트
        for row in range(self.table.rowCount()):
            self.table.setRowHeight(row, row_height)

            # 썸네일 위젯 업데이트
            widget = self.table.cellWidget(row, 1)  # ROI 샘플 컬럼
            if widget:
                thumb_label = widget.findChild(QLabel)
                if thumb_label:
                    pass
                    # 기존 pixmap을 간단히 스케일링 (재생성하지 않음)
                    original_pixmap = thumb_label.property('original_pixmap')

                    if not original_pixmap and row < len(self.segment_images):
                        pass
                        # 처음 호출 시에만 원본 생성
                        roi_bytes = self.segment_images[row]
                        detections = self.segment_detections[row] if row < len(self.segment_detections) else []
                        original_pixmap = self._pixmap_with_boxes(roi_bytes, detections, None)

                        if original_pixmap:
                            thumb_label.setProperty('original_pixmap', original_pixmap)

                    # 원본 pixmap을 새 크기로 스케일링
                    if original_pixmap:
                        if is_ocr_mode:
                            pass
                            # OCR 모드: 실제 이미지 종횡비에 맞게
                            orig_width = original_pixmap.width()
                            orig_height = original_pixmap.height()
                            aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                            actual_width = int(thumbnail_height * aspect_ratio)
                            actual_size = QSize(actual_width, thumbnail_height)
                            scaled_pixmap = original_pixmap.scaled(
                                actual_size, Qt.KeepAspectRatio, Qt.FastTransformation
                            )
                        else:
                            pass
                            # 애니매틱 모드: 고정 크기
                            scaled_pixmap = original_pixmap.scaled(
                                thumbnail_size, Qt.KeepAspectRatio, Qt.FastTransformation
                            )
                        thumb_label.setPixmap(scaled_pixmap)

                # 재생 버튼 위치 업데이트 (즉시 처리)
                play_button = widget.findChild(QPushButton)
                if play_button and thumb_label:
                    thumb_rect = thumb_label.geometry()
                    button_size = play_button.size()
                    x = thumb_rect.center().x() - button_size.width() // 2
                    y = thumb_rect.center().y() - button_size.height() // 2
                    play_button.move(x, y)

        # 테이블 업데이트 재개
        self.table.setUpdatesEnabled(True)

        # print(f"[썸네일 크기 변경] 크기: {thumbnail_width}×{thumbnail_height}, 컬럼 너비: {column_width}, 행 높이: {row_height}")

    def _update_frame_display(self):
        """프레임 번호 오버레이 및 라벨 업데이트"""
        if not hasattr(self, 'frame_overlay'):
            pass
            return

        current_frame = getattr(self, '_preview_current_display_frame', None)
        start_frame = getattr(self, '_preview_current_segment_start', None)
        end_frame = getattr(self, '_preview_current_segment_end', None)

        # current_frame이 None이면 start_frame 사용
        if current_frame is None:
            current_frame = start_frame if start_frame is not None else 0

        # 씬 내 상대 프레임 번호 계산 (씬의 첫 프레임은 항상 1)
        if start_frame is not None:
            relative_frame = current_frame - start_frame + 1  # 씬 내에서 1부터 시작
            total_frames_in_scene = end_frame - start_frame + 1 if end_frame is not None else 1
        else:
            relative_frame = current_frame + 1  # start_frame이 없으면 절대 프레임 번호 사용
            total_frames_in_scene = end_frame + 1 if end_frame is not None else 1

        # 오버레이 업데이트 (씬 내 상대 프레임 번호) - 항상 표시
        frame_text = f"Frame: {relative_frame}"
        self.frame_overlay.setText(frame_text)
        self.frame_overlay.adjustSize()  # 텍스트 변경 후 크기 조정
        
        # 우하단 위치로 업데이트 (preview_container 기준)
        if hasattr(self, 'preview_widget'):
            preview_size = self.preview_widget.size()
            preview_pos = self.preview_widget.pos()  # preview_container 기준 위치
            overlay_size = self.frame_overlay.size()
            x = preview_pos.x() + preview_size.width() - overlay_size.width() - 10
            y = preview_pos.y() + preview_size.height() - overlay_size.height() - 10
            self.frame_overlay.move(x, y)
        
        # 오버레이가 항상 위에 표시되도록 다시 raise
        self.frame_overlay.raise_()
        self.frame_overlay.show()  # 명시적으로 표시
        
        # current_frame_label이 있으면 업데이트 (씬 내 상대 프레임 번호)
        if hasattr(self, 'current_frame_label'):
            if start_frame is not None and end_frame is not None:
                self.current_frame_label.setText(f"{relative_frame}/{total_frames_in_scene}")
            else:
                self.current_frame_label.setText(f"{relative_frame}")
        
        # 슬라이더 업데이트 (슬라이더가 드래그 중이 아닐 때만)
        if hasattr(self, 'frame_slider') and hasattr(self, '_slider_dragging') and not self._slider_dragging:
            if start_frame is not None and end_frame is not None and end_frame >= start_frame:
                total_frames = end_frame - start_frame + 1
                if total_frames > 0:
                    pass
                    # 현재 프레임을 0-100 범위로 변환
                    frame_offset = current_frame - start_frame
                    slider_value = int((frame_offset / total_frames) * 100)
                    slider_value = max(0, min(100, slider_value))  # 0-100 범위 제한
                    self.frame_slider.setValue(slider_value)
                else:
                    self.frame_slider.setValue(0)
            else:
                self.frame_slider.setValue(0)
    
    def _prev_frame(self):
        """이전 프레임으로 이동"""
        if not hasattr(self, '_preview_current_display_frame'):
            pass
            return

        current = self._preview_current_display_frame
        start = self._preview_current_segment_start

        # 시작 프레임보다 작아지지 않도록
        if start is not None and current is not None and current > start:
            self._preview_current_display_frame = current - 1
            self._update_frame_display()
            # 프리뷰 이미지 업데이트 (현재 프레임 표시)
            self._update_preview_frame(self._preview_current_display_frame)

            # 오디오 위치 동기화 (재생 중이 아닐 때만)
            if not self._preview_playing and hasattr(self, '_preview_media_player'):
                fps = self.fps if hasattr(self, 'fps') else 24.0
                # 동적 오프셋 계산
                total_frames = getattr(self, '_total_video_frames', 0)
                video_duration = total_frames / fps if fps > 0 else 0
                dynamic_offset = self._calculate_audio_offset(video_duration, self._preview_current_display_frame, fps)
                # 오프셋 적용
                audio_position = max(0, int(self._preview_current_display_frame / fps * 1000) - dynamic_offset)
                if self._preview_media_player.mediaStatus() != QMediaPlayer.NoMedia:
                    self._preview_media_player.setPosition(audio_position)
    
    def _next_frame(self):
        """다음 프레임으로 이동"""
        if not hasattr(self, '_preview_current_display_frame'):
            pass
            return

        current = self._preview_current_display_frame
        end = self._preview_current_segment_end

        # 종료 프레임보다 크지 않도록
        if end is not None and current is not None and current < end:
            self._preview_current_display_frame = current + 1
            self._update_frame_display()
            # 프리뷰 이미지 업데이트 (현재 프레임 표시)
            self._update_preview_frame(self._preview_current_display_frame)

            # 오디오 위치 동기화 (재생 중이 아닐 때만)
            if not self._preview_playing and hasattr(self, '_preview_media_player'):
                fps = self.fps if hasattr(self, 'fps') else 24.0
                # 동적 오프셋 계산
                total_frames = getattr(self, '_total_video_frames', 0)
                video_duration = total_frames / fps if fps > 0 else 0
                dynamic_offset = self._calculate_audio_offset(video_duration, self._preview_current_display_frame, fps)
                # 오프셋 적용
                audio_position = max(0, int(self._preview_current_display_frame / fps * 1000) - dynamic_offset)
                if self._preview_media_player.mediaStatus() != QMediaPlayer.NoMedia:
                    self._preview_media_player.setPosition(audio_position)
    
    def _update_preview_frame(self, frame):
        """특정 프레임의 이미지를 프리뷰에 표시"""
        if not self.video_path or not os.path.exists(self.video_path):
            pass
            return

        # 프레임 추출
        roi_bytes = self._extract_frame_thumbnail(self.video_path, frame)
        if not roi_bytes:
            pass
            return
        
        # detections 가져오기 (현재 선택된 row에서)
        detections = []
        if hasattr(self, '_pending_preview_row') and self._pending_preview_row is not None:
            row = self._pending_preview_row
            if row < len(self.segment_detections):
                detections = self.segment_detections[row]
        
        # 이미지 처리
        pixmap = self._pixmap_with_boxes(roi_bytes, detections, None)
        if pixmap:
            pass
            # 프리뷰 영상 크기에 맞게 스케일
            # 부모 위젯의 크기를 사용하여 UI 확장 시에도 일관되게 표시
            preview_size = self.preview_widget.size()
            scaled = pixmap.scaled(
                preview_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.previewLabel.setPixmap(scaled)
            self.previewLabel.setText("")
    
    def _on_slider_pressed(self):
        """슬라이더를 누를 때 (클릭 또는 드래그 시작)"""
        self._slider_dragging = True
        
        # 클릭 시에도 해당 프레임으로 즉시 이동
        if not hasattr(self, '_preview_current_segment_start') or not hasattr(self, '_preview_current_segment_end'):
            pass
            return
        
        start_frame = self._preview_current_segment_start
        end_frame = self._preview_current_segment_end
        
        if start_frame is not None and end_frame is not None and end_frame >= start_frame:
            total_frames = end_frame - start_frame + 1
            if total_frames > 0:
                pass
                # 슬라이더의 현재 값을 가져와서 프레임 번호로 변환
                slider_value = self.frame_slider.value()
                frame_offset = int(slider_value / 100.0 * total_frames)
                new_frame = start_frame + frame_offset
                # 범위 제한
                new_frame = max(start_frame, min(end_frame, new_frame))
                
                # 프레임 업데이트
                self._preview_current_display_frame = new_frame
                self._update_preview_frame(new_frame)
                
                # 오버레이와 라벨 업데이트 (씬 내 상대 프레임 번호로 표시)
                if hasattr(self, 'frame_overlay'):
                    pass
                    # 씬 내 상대 프레임 번호 계산 (씬의 첫 프레임은 항상 1)
                    relative_frame = (new_frame - start_frame) + 1
                    self.frame_overlay.setText(f"Frame: {relative_frame}")
                if hasattr(self, 'current_frame_label'):
                    pass
                    # 씬 내 상대 프레임 번호 계산
                    relative_frame = (new_frame - start_frame) + 1
                    total_frames_in_scene = end_frame - start_frame + 1
                    self.current_frame_label.setText(f"{relative_frame}/{total_frames_in_scene}")
    
    def _on_slider_moved(self, value):
        """슬라이더를 드래그할 때"""
        if not hasattr(self, '_preview_current_segment_start') or not hasattr(self, '_preview_current_segment_end'):
            pass
            return
        
        start_frame = self._preview_current_segment_start
        end_frame = self._preview_current_segment_end
        
        if start_frame is not None and end_frame is not None and end_frame >= start_frame:
            total_frames = end_frame - start_frame + 1
            if total_frames > 0:
                pass
                # 슬라이더 값을 프레임 번호로 변환
                frame_offset = int(value / 100.0 * total_frames)
                new_frame = start_frame + frame_offset
                # 범위 제한
                new_frame = max(start_frame, min(end_frame, new_frame))
                
                # 프레임 업데이트
                self._preview_current_display_frame = new_frame
                self._update_preview_frame(new_frame)
                
                # 오버레이와 라벨 업데이트 (씬 내 상대 프레임 번호로 표시)
                if hasattr(self, 'frame_overlay'):
                    pass
                    # 씬 내 상대 프레임 번호 계산 (씬의 첫 프레임은 항상 1)
                    relative_frame = (new_frame - start_frame) + 1
                    self.frame_overlay.setText(f"Frame: {relative_frame}")
                if hasattr(self, 'current_frame_label'):
                    pass
                    # 씬 내 상대 프레임 번호 계산
                    relative_frame = (new_frame - start_frame) + 1
                    total_frames_in_scene = end_frame - start_frame + 1
                    self.current_frame_label.setText(f"{relative_frame}/{total_frames_in_scene}")
    
    def _on_slider_released(self):
        """슬라이더를 놓을 때"""
        self._slider_dragging = False
        # 슬라이더 위치를 현재 프레임에 맞게 재동기화
        self._update_frame_display()

        # 오디오 위치 동기화는 재생 시작 시에만 수행하도록 변경
        # (슬라이더 드래그 후 재생 시 오디오 위치가 이중 설정되는 문제 방지)
    
    def _on_frame_input_entered(self):
        """프레임 번호 입력 필드에서 Enter 키 입력 시"""
        if not hasattr(self, 'frame_input'):
            pass
            return
        
        try:
            pass
            # 입력된 텍스트를 정수로 변환
            input_text = self.frame_input.text().strip()
            if not input_text:
                pass
                return
            
            frame_number = int(input_text)
            
            # 현재 선택된 세그먼트 범위 확인
            if hasattr(self, '_preview_current_segment_start') and hasattr(self, '_preview_current_segment_end'):
                start_frame = self._preview_current_segment_start
                end_frame = self._preview_current_segment_end
                
                if start_frame is not None and end_frame is not None:
                    pass
                    # 사용자가 입력한 값은 씬 내 상대 프레임 번호(1-based)로 해석
                    # 예: 사용자가 30을 입력하면 씬 내에서 30번 프레임(상대값)
                    relative_frame = frame_number  # 1-based 상대 프레임 번호

                    # 상대 프레임을 절대 프레임으로 변환 (0-based)
                    target_frame = start_frame + (relative_frame - 1)

                    # 세그먼트 범위 내로 제한
                    target_frame = max(start_frame, min(end_frame, target_frame))
                else:
                    pass
                    # 세그먼트 정보가 없으면 절대 프레임 번호로 처리
                    target_frame = frame_number - 1  # 1-based를 0-based로 변환
                    if target_frame < 0:
                        target_frame = 0
                    elif hasattr(self, 'total_frames') and target_frame >= self.total_frames:
                        target_frame = self.total_frames - 1
            else:
                pass
                # 세그먼트 정보가 없으면 절대 프레임 번호로 처리
                target_frame = frame_number - 1  # 1-based를 0-based로 변환
                if target_frame < 0:
                    target_frame = 0
                elif hasattr(self, 'total_frames') and target_frame >= self.total_frames:
                    target_frame = self.total_frames - 1
            
            # 프레임 이동
            self._preview_current_display_frame = target_frame
            self._update_preview_frame(target_frame)

            # 프레임 표시 업데이트 (상대 프레임 번호로 표시)
            self._update_frame_display()

            # 입력 필드 비우기
            self.frame_input.clear()

            # 포커스를 프리뷰 레이블로 이동하여 추가 키 이벤트 방지
            if hasattr(self, 'previewLabel'):
                self.previewLabel.setFocus()
            
        except ValueError:
            pass
            # 숫자가 아닌 경우 무시
            self.frame_input.clear()
            return
    
    def _toggle_preview_playback(self):
        """프리뷰 재생/일시정지 토글"""
        if not hasattr(self, '_preview_playing') or not self._preview_playing:
            pass
            # 재생 시작
            if hasattr(self, '_preview_current_segment_start') and hasattr(self, '_preview_current_segment_end'):
                start = self._preview_current_segment_start
                end = self._preview_current_segment_end
                if start is not None and end is not None:
                    pass
                    # 현재 표시 중인 프레임부터 재생
                    current = self._preview_current_display_frame if hasattr(self, '_preview_current_display_frame') else start
                    self._play_preview_segment(current, end)
        else:
            pass
            # 일시정지
            self._stop_preview_playback()

    def _on_volume_changed(self, value):
        """볼륨 슬라이더 변경 시 호출"""
        if hasattr(self, '_preview_media_player'):
            self._preview_media_player.setVolume(value)

        # 볼륨 퍼센트 레이블 업데이트
        if hasattr(self, 'volume_percent_label'):
            self.volume_percent_label.setText(f"{value}%")

    def _load_preview_media(self):
        """프리뷰 미디어 파일 로드 (세그먼트 변경 시 호출)"""
        if not hasattr(self, '_preview_media_player') or not self.video_path:
            pass
            return

        # 미디어 파일 설정 (재생은 하지 않음)
        media_content = QMediaContent(QUrl.fromLocalFile(self.video_path))
        self._preview_media_player.setMedia(media_content)
        # print(f"[미디어 로드] 비디오 파일: {self.video_path}")

    def _calculate_audio_offset(self, video_duration, current_frame, fps):
        """영상 길이와 현재 프레임에 따른 동적 오디오 오프셋 계산 (메인 플레이어와 동일)"""
        # 기본 오프셋 (짧은 영상용)
        base_offset = 20

        # 영상 길이에 따른 오프셋 조정
        if video_duration > 300:  # 5분 이상
            # 긴 영상에서는 더 큰 오프셋 사용
            duration_factor = min(video_duration / 300, 1.5)  # 최대 1.5배
            base_offset = int(20 * duration_factor)
        elif video_duration > 60:  # 1분 이상
            # 중간 길이 영상
            base_offset = 40

        # 현재 프레임 위치에 따른 미세 조정
        frame_progress = current_frame / (video_duration * fps) if (video_duration * fps) > 0 else 0
        if frame_progress > 0.8:  # 영상 후반부
            base_offset += 10
        elif frame_progress < 0.2:  # 영상 초반부
            base_offset -= 3

        return max(0, base_offset)

    def _stop_preview_playback(self):
        """프리뷰 재생 중지"""
        # 재생 버튼 텍스트를 재생 아이콘으로 복원
        if self._preview_playing_row is not None:
            self._update_play_button_text(self._preview_playing_row, "▶")

        # 프리뷰 재생 버튼 텍스트 업데이트
        if hasattr(self, 'preview_play_button'):
            self.preview_play_button.setText("▶")

        self._preview_playing = False
        self._preview_playing_row = None
        self._preview_play_timer.stop()
        if self._preview_video_cap:
            self._preview_video_cap.release()
            self._preview_video_cap = None

        # 오디오 정지 (QMediaPlayer)
        if hasattr(self, '_preview_media_player'):
            self._preview_media_player.stop()
            # print(f"[프리뷰 재생] 오디오 정지")
    
    def _update_scene_list(self, affected_rows=None):
        """씬 리스트를 테이블의 현재 상태에 맞게 업데이트

        Args:
            affected_rows: 업데이트할 행 범위 (start, end) 튜플. None이면 전체 업데이트.
        """
        if not hasattr(self, 'sceneListWidget'):
            pass
            return

        # UI 업데이트를 일시 중지하여 성능 향상
        self.sceneListWidget.setUpdatesEnabled(False)
        try:
            pass
            # 전체 업데이트가 필요한 경우
            if affected_rows is None:
                self.sceneListWidget.clear()
                start_row = 0
                end_row = self.table.rowCount()
            else:
                pass
                # 증분 업데이트: 영향받은 행만 업데이트
                start_row, end_row = affected_rows
                # 리스트에서 영향받은 아이템들 제거
                for i in range(end_row - start_row):
                    if start_row < self.sceneListWidget.count():
                        self.sceneListWidget.takeItem(start_row)

            # 영향받은 행만 업데이트
            for row in range(start_row, min(end_row, self.table.rowCount())):
                start_frame_item = self.table.item(row, 4)
                end_frame_item = self.table.item(row, 5)
                text_item = self.table.item(row, 3)

                if not start_frame_item or not end_frame_item:
                    pass
                    continue

                # 프레임 정보 가져오기
                start_frame = start_frame_item.data(Qt.UserRole)
                if start_frame is None:
                    start_frame = self._safe_int(start_frame_item) - 1

                end_frame = end_frame_item.data(Qt.UserRole)
                if end_frame is None:
                    end_frame = self._safe_int(end_frame_item) - 1

                # 시간 계산
                start_time = start_frame / self.fps if self.fps else 0.0
                end_time = (end_frame + 1) / self.fps if self.fps else 0.0

                # 텍스트 가져오기
                text = text_item.text() if text_item else ""

                # 테이블과 동일하게 1-based로 표시 (VFX 업계 표준, 로그와 일치)
                scene_text = f"{row+1:02d}. {text} | 프레임 {start_frame + 1} → {end_frame + 1} | {start_time:.3f}s → {end_time:.3f}s"
                list_item = QListWidgetItem(scene_text)
                list_item.setData(Qt.UserRole, row)

                # 증분 업데이트 시 삽입, 전체 업데이트 시 추가
                if affected_rows is None:
                    self.sceneListWidget.addItem(list_item)
                else:
                    self.sceneListWidget.insertItem(row, list_item)
        finally:
            self.sceneListWidget.setUpdatesEnabled(True)
    
    def _renumber_scene_names(self):
        """테이블의 모든 씬 이름을 Scene_001부터 순서대로 재정렬"""
        table_row_count = self.table.rowCount()

        # UI 업데이트를 일시 중지하여 성능 향상 (대량 씬에서 효과적)
        self.table.setUpdatesEnabled(False)
        try:
            for row in range(table_row_count):
                pass
                # 3번 컬럼(편집된 텍스트)에 새로운 씬 이름 설정
                new_scene_name = f"Scene_{row + 1:03d}"
                text_item = self.table.item(row, 3)
                if text_item:
                    text_item.setText(new_scene_name)
                else:
                    pass
                    # 아이템이 없으면 새로 생성
                    text_item = QTableWidgetItem(new_scene_name)
                    self.table.setItem(row, 3, text_item)

                # 2번 컬럼(ROI 텍스트)도 동일하게 업데이트 (일관성 유지)
                roi_text_item = self.table.item(row, 2)
                if roi_text_item:
                    roi_text_item.setText(new_scene_name)
        finally:
            self.table.setUpdatesEnabled(True)
    
    def _sync_segment_images_with_table(self):
        """segment_images 리스트를 테이블의 현재 상태와 동기화"""
        table_row_count = self.table.rowCount()
        
        # 새로운 리스트 생성 (테이블 row와 1:1 매핑)
        new_segment_images = []
        new_segment_detections = []
        
        for row in range(table_row_count):
            pass
            # 먼저 테이블의 썸네일 위젯에서 이미지 가져오기 시도
            image = None
            thumb_widget = self.table.cellWidget(row, 1)  # ROI 샘플 컬럼
            if thumb_widget:
                thumb_label = thumb_widget.findChild(QLabel)
                if thumb_label and thumb_label.pixmap():
                    pass
                    # QPixmap을 QImage로 변환 후 PNG 바이트로 변환
                    pixmap = thumb_label.pixmap()
                    if pixmap:
                        pass
                        # 원본 크기로 복원하려면 비디오에서 다시 추출해야 함
                        # 대신 segment_images에서 가져오거나 비디오에서 추출
                        pass
            
            # 썸네일 위젯에서 가져오지 못했으면 기존 segment_images에서 가져오기
            if not image and row < len(self.segment_images):
                image = self.segment_images[row]
            
            # detections는 기존 리스트에서 가져오기
            detections = self.segment_detections[row] if row < len(self.segment_detections) else []
            
            # 이미지가 없으면 비디오에서 추출
            if not image and self.video_path and os.path.exists(self.video_path):
                start_frame_item = self.table.item(row, 4)
                if start_frame_item:
                    start_frame = start_frame_item.data(Qt.UserRole)
                    if start_frame is None:
                        start_frame = self._safe_int(start_frame_item) - 1
                    if start_frame is not None:
                        image = self._extract_frame_thumbnail(self.video_path, start_frame)
            
            new_segment_images.append(image)
            new_segment_detections.append(detections)
        
        # 리스트 교체
        self.segment_images = new_segment_images
        self.segment_detections = new_segment_detections
    
    def _extract_frame_thumbnail(self, video_path, frame_number):
        """
        비디오에서 특정 프레임을 추출하여 PNG 바이트로 반환
        
        Args:
            video_path: 비디오 파일 경로
            frame_number: 추출할 프레임 번호 (0-based)
        
        Returns:
            bytes: PNG 인코딩된 이미지 바이트, 실패 시 None
        """
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                pass
                return None
            
            # 프레임으로 이동
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

            # 실제로 설정된 프레임 위치 확인 (디버깅용)
            actual_frame_pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            if actual_frame_pos != frame_number:
                pass
                # print(f"[프레임 추출] 요청: {frame_number}, 실제: {actual_frame_pos}")

            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                pass
                return None
            
            # BGR을 RGB로 변환
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # PNG로 인코딩
            success, buffer = cv2.imencode(".png", frame_rgb)
            if success:
                pass
                return buffer.tobytes()
            else:
                pass
                return None
        except Exception as e:
            pass
            # print(f"[썸네일 추출 오류] 프레임 {frame_number}: {e}")
            return None
    
    def _format_detection_lines(self, detections):
        lines = []
        for idx, det in enumerate(detections):
            if isinstance(det, dict):
                text = det.get("text") or ""
                score = det.get("score")
                if isinstance(score, (int, float)):
                    score_str = f"{score:.2f}"
                else:
                    score_str = "-"
                box = det.get("box")
                if box and len(box) == 4:
                    xs = [pt[0] for pt in box]
                    ys = [pt[1] for pt in box]
                    left = min(xs) * 100
                    right = max(xs) * 100
                    top = min(ys) * 100
                    bottom = max(ys) * 100
                    box_desc = f"{left:.1f}%/{top:.1f}% → {right:.1f}%/{bottom:.1f}%"
                else:
                    box_desc = "box 없음"
                lines.append(f"{idx + 1}. {text} (score {score_str}) @ {box_desc}")
            else:
                lines.append(f"{idx + 1}. {det}")
        return lines or ["세부 인식 없음"]

    def closeEvent(self, event):
        """다이얼로그 닫을 때 비디오 재생 정리"""
        self._stop_preview_playback()
        super().closeEvent(event)
    
    def export_all(self):
        """전체 내보내기 - _result_segments를 초기화하여 모든 세그먼트를 내보냄"""
        # 선택 항목만 내보내기로 설정된 경우를 초기화
        self._result_segments = None
        self.accept()
    
    def accept(self):
        # _result_segments가 이미 설정되어 있으면 (예: export_selected_only 호출) 덮어쓰지 않음
        if self._result_segments is None:
            segments = self.collect_segments()
            if not segments:
                QMessageBox.warning(self, "내보낼 구간 없음", "적어도 하나 이상의 구간이 필요합니다.")
                return
            self._result_segments = segments
        
        # 사운드 옵션 저장 (전체 내보내기인 경우)
        self._include_audio = self.includeAudioCheckBox.isChecked()
        # 내보내기 모드 저장
        self._export_mode = self.exportModeComboBox.currentData()
        # 비트레이트 저장 (fast 모드일 때만)
        if self._export_mode == 'fast':
            self._bitrate = self.bitrateComboBox.currentData()
        else:
            self._bitrate = None
        
        # 최종 확인
        if not self._result_segments:
            QMessageBox.warning(self, "내보낼 구간 없음", "적어도 하나 이상의 구간이 필요합니다.")
            return
        
        super().accept()

    def export_to_web(self):
        """OCR 분석 결과를 웹 페이지로 내보냅니다."""
        try:
            pass
            # 현재 세그먼트 수집
            segments = self.collect_segments()

            if not segments:
                QMessageBox.information(self, "웹분석", "내보낼 세그먼트가 없습니다.")
                return

            # 웹 리포트 생성
            html_path = web_info.generate_web_report(
                segments=segments,
                video_path=self.video_path,
                fps=self.fps,
                total_frames=self.total_frames,
                ocr_mode=self.ocr_mode
            )

            if html_path:
                pass
                # 브라우저로 열기
                if web_info.open_web_report(html_path):
                    QMessageBox.information(
                        self,
                        "웹분석 완료",
                        f"웹 리포트가 생성되었습니다.\n\n파일: {html_path}\n\n브라우저에서 열렸습니다."
                    )
                else:
                    QMessageBox.information(
                        self,
                        "웹분석 완료",
                        f"웹 리포트가 생성되었습니다.\n\n파일: {html_path}\n\n수동으로 파일을 열어주세요."
                    )
            else:
                QMessageBox.warning(self, "웹분석 실패", "웹 리포트 생성에 실패했습니다.")

        except Exception as e:
            QMessageBox.critical(self, "웹분석 오류", f"웹 리포트 생성 중 오류가 발생했습니다:\n\n{str(e)}")
            # print(f"[웹분석 오류] {e}")
            import traceback
            traceback.print_exc()

    def setup_websocket_server(self):
        """WebSocket 서버를 시작하여 실시간 동기화를 활성화합니다."""
        try:
            import json

            self.websocket_server = QWebSocketServer("OCR Review Sync", QWebSocketServer.NonSecureMode, self)

            if self.websocket_server.listen(QHostAddress.LocalHost, 8765):
                pass
                # print(f"[WebSocket] 서버 시작: ws://localhost:8765")
                self.websocket_server.newConnection.connect(self.on_new_connection)
                self.websocket_port = 8765
            else:
                pass
                # print(f"[WebSocket] 서버 시작 실패: {self.websocket_server.errorString()}")
                self.websocket_server = None
                self.websocket_port = None
        except Exception as e:
            pass
            # print(f"[WebSocket] 서버 초기화 오류: {e}")
            self.websocket_server = None
            self.websocket_port = None

    def on_new_connection(self):
        """새로운 WebSocket 클라이언트 연결 처리."""
        if not self.websocket_server:
            pass
            return

        client = self.websocket_server.nextPendingConnection()
        if client:
            pass
            # print(f"[WebSocket] 새 클라이언트 연결: {client.peerAddress().toString()}")
            self.websocket_clients.append(client)

            client.textMessageReceived.connect(lambda msg: self.on_text_message_received(client, msg))
            client.disconnected.connect(lambda: self.on_client_disconnected(client))

            # 초기 데이터 전송
            self.send_full_sync(client)

    def on_client_disconnected(self, client):
        """WebSocket 클라이언트 연결 해제 처리."""
        if client in self.websocket_clients:
            self.websocket_clients.remove(client)
            # print(f"[WebSocket] 클라이언트 연결 해제")

    def on_text_message_received(self, client, message):
        """웹 UI로부터 받은 변경사항을 처리합니다."""
        try:
            import json
            data = json.loads(message)

            msg_type = data.get('type')

            if msg_type == 'segments_update':
                pass
                # 웹에서 전체 세그먼트 업데이트
                segments = data.get('segments', [])
                selected_index = data.get('selected_index', None)  # 웹 UI에서 선택한 세그먼트 인덱스
                # print(f"[WebSocket] 웹으로부터 {len(segments)}개 세그먼트 수신 (selected_index={selected_index})")
                self.apply_segments_from_web(segments, selected_index=selected_index)

            elif msg_type == 'request_sync':
                pass
                # 전체 동기화 요청
                self.send_full_sync(client)

            elif msg_type == 'split_segment':
                pass
                # 씬 분할 명령
                row_index = data.get('row_index')
                split_frame = data.get('split_frame')
                # print(f"[WebSocket] 씬 분할 명령 수신: row={row_index}, split_frame={split_frame}")
                # 먼저 웹에서 선택한 행을 데스크탑에서도 선택
                if row_index is not None and row_index < self.table.rowCount():
                    self.table.selectRow(row_index)
                    # 분할 실행 (프레임을 직접 받는 헬퍼 메서드 호출)
                    self._split_row_at_frame(row_index, split_frame)

            elif msg_type == 'export_selected':
                pass
                # 선택한 항목만 내보내기 명령
                selected_indices = data.get('selected_indices', [])
                include_audio = data.get('include_audio', True)
                # print(f"[WebSocket] 선택 항목만 내보내기 명령 수신: {len(selected_indices)}개, include_audio={include_audio}")
                # 먼저 웹에서 선택한 행들을 데스크탑에서도 선택
                self.table.clearSelection()
                for idx in selected_indices:
                    if idx < self.table.rowCount():
                        self.table.selectRow(idx)
                # 사운드 옵션 설정
                if hasattr(self, 'includeAudioCheckBox'):
                    self.includeAudioCheckBox.setChecked(include_audio)
                # 내보내기 실행
                self.export_selected_only()

            elif msg_type == 'export_all':
                pass
                # 전체 내보내기 명령
                include_audio = data.get('include_audio', True)
                # print(f"[WebSocket] 전체 내보내기 명령 수신: include_audio={include_audio}")
                # 사운드 옵션 설정
                if hasattr(self, 'includeAudioCheckBox'):
                    self.includeAudioCheckBox.setChecked(include_audio)
                # 내보내기 실행
                self.export_all()

        except json.JSONDecodeError as e:
            pass
            # print(f"[WebSocket] JSON 파싱 오류: {e}")
        except Exception as e:
            pass
            # print(f"[WebSocket] 메시지 처리 오류: {e}")
            import traceback
            traceback.print_exc()

    def send_full_sync(self, client=None):
        """현재 세그먼트 상태를 클라이언트에 전송합니다."""
        try:
            import json
            import base64

            # segment_images 리스트 길이가 테이블 행 수와 일치하도록 보정
            total_rows = self.table.rowCount()
            if len(self.segment_images) < total_rows:
                self.segment_images.extend([None] * (total_rows - len(self.segment_images)))

            # 테이블 위젯에서 직접 썸네일을 읽어서 segment_images 동기화
            # 데스크톱 테이블에 표시된 썸네일이 정확한 소스
            for row in range(total_rows):
                roi_bytes = self.segment_images[row] if row < len(self.segment_images) else None

                if not roi_bytes:
                    thumb_widget = self.table.cellWidget(row, 1)
                    if thumb_widget:
                        thumb_label = thumb_widget.findChild(QLabel)
                        if thumb_label and thumb_label.pixmap():
                            pixmap = thumb_label.property('original_pixmap') or thumb_label.pixmap()
                            if pixmap:
                                from PyQt5.QtCore import QBuffer, QIODevice
                                buffer = QBuffer()
                                buffer.open(QIODevice.WriteOnly)
                                pixmap.save(buffer, 'PNG')
                                roi_bytes = buffer.data().data()
                                buffer.close()
                                self.segment_images[row] = roi_bytes

                if not roi_bytes:
                    pass
                    # 위젯에 pixmap이 없고 segment_images도 없으면 비디오에서 추출
                    if getattr(self, 'ocr_mode', 'titmouse') in ['animatic', 'animatic2'] and self.video_path and os.path.exists(self.video_path):
                        start_frame_item = self.table.item(row, 4)
                        if start_frame_item:
                            start_frame = start_frame_item.data(Qt.UserRole)
                            if start_frame is None:
                                start_frame = self._safe_int(start_frame_item) - 1
                            if start_frame is not None:
                                roi_bytes = self._extract_frame_thumbnail(self.video_path, start_frame)
                                self.segment_images[row] = roi_bytes

            segments = self.collect_segments()

            # 간단한 포맷으로 변환 (인덱스 추가)
            simple_segments = []
            for idx, seg in enumerate(segments):
                pass
                # 썸네일 이미지를 base64로 인코딩
                roi_image = seg.get('roi_image', None)
                thumbnail_data = ""
                if roi_image:
                    try:
                        thumbnail_data = base64.b64encode(roi_image).decode('utf-8')
                    except Exception as e:
                        pass
                        # print(f"[WebSocket] 썸네일 인코딩 오류 (row {idx}): {e}")

                simple_segments.append({
                    'index': idx,  # 웹 UI에서 정확한 매칭을 위해 인덱스 추가
                    'start_frame': seg.get('start_frame', 0),
                    'end_frame': seg.get('end_frame', 0),
                    'start_time': seg.get('start_time', 0.0),
                    'end_time': seg.get('end_time', 0.0),
                    'duration': seg.get('duration', 0.0),
                    'text': seg.get('text', ''),
                    'edited_text': seg.get('edited_text', ''),
                    'roi_image': thumbnail_data,
                })

            # 현재 선택된 행 인덱스 가져오기
            selected_index = None
            selection_model = self.table.selectionModel()
            if selection_model:
                selected_rows = sorted({index.row() for index in selection_model.selectedRows()})
                if selected_rows:
                    selected_index = selected_rows[0]

            message = {
                'type': 'full_sync',
                'segments': simple_segments,
                'selected_index': selected_index  # 현재 선택된 세그먼트 인덱스
            }

            json_str = json.dumps(message)

            if client:
                client.sendTextMessage(json_str)
            else:
                pass
                # 모든 클라이언트에 전송
                for c in self.websocket_clients:
                    c.sendTextMessage(json_str)

            # print(f"[WebSocket] {len(simple_segments)}개 세그먼트 전송 (테이블 위젯 기준, selected_index={selected_index})")
        except Exception as e:
            pass
            # print(f"[WebSocket] 전체 동기화 전송 오류: {e}")
            import traceback
            traceback.print_exc()

    def apply_segments_from_web(self, segments, selected_index=None):
        """웹 UI로부터 받은 세그먼트를 테이블에 적용합니다. (최적화: 배치 처리 및 이미지 재사용)"""
        try:
            pass
            # 백그라운드 썸네일 로딩 일시 중지 (WebSocket 업데이트 우선)
            self._background_loading_paused = True
            # print(f"[WebSocket] 백그라운드 로딩 일시 중지")

            # 테이블 업데이트 중 플래그 설정 (broadcast 방지)
            self._updating_from_web = True

            # 웹 UI에서 선택한 세그먼트 인덱스 저장
            self._web_selected_index = selected_index

            # UI 업데이트 비활성화 (성능 최적화)
            self.table.setUpdatesEnabled(False)
            old_updating = getattr(self, '_updating', False)
            self._updating = True

            try:
                pass
                # 테이블 클리어
                self.table.setRowCount(0)

                # segment_images와 segment_detections 초기화
                self.segment_images = []
                self.segment_detections = []

                # 썸네일 캐시 클리어 (중요: 테이블 재구성 시 필수)
                self._thumbnail_cache.clear()
                self._thumbnail_load_in_progress.clear()
                # print(f"[WebSocket] 썸네일 캐시 클리어")

                # 성능 최적화: 데이터만 먼저 설정하고 썸네일은 지연 로딩
                import base64
                num_segments = len(segments)
                
                # 모든 행을 한 번에 추가
                self.table.setRowCount(num_segments)
                
                # segment_images와 segment_detections 초기화
                self.segment_images = [None] * num_segments
                self.segment_detections = [[] for _ in range(num_segments)]
                
                # 성능 최적화: 모든 아이템을 먼저 준비하고 배치로 설정
                fps = self.fps if self.fps else 1.0
                
                # 플래그 미리 계산 (반복 계산 방지)
                non_editable_flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
                editable_flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable
                
                # 모든 아이템을 먼저 준비
                items_by_row = {}
                for row_position, item in enumerate(segments):
                    pass
                    # 프레임 정보 가져오기 (0-based로 저장되어 있음)
                    start_frame = int(item.get('start_frame', 0))
                    end_frame = int(item.get('end_frame', 0))
                    
                    # 이미지 데이터는 나중에 처리 (지연 로딩)
                    # 웹에서 전송된 썸네일 base64 데이터 저장 (빈 문자열이 아닐 때만)
                    roi_image_data = item.get('roi_image', '')
                    if roi_image_data and roi_image_data.strip():
                        self.segment_images[row_position] = roi_image_data  # base64 문자열로 저장
                    
                    # 시간 정보 직접 계산
                    start_time = item.get('start_time', start_frame / fps)
                    end_time = item.get('end_time', (end_frame + 1) / fps)
                    num_frames = end_frame - start_frame + 1
                    
                    # 텍스트 값 미리 계산
                    roi_text_value = item.get('edited_text') or item.get('text') or ""
                    display_text = item.get('edited_text') or item.get('text') or ""
                    
                    # 모든 아이템을 한 번에 생성
                    items_by_row[row_position] = {
                        0: QTableWidgetItem(str(row_position + 1)),  # 행 번호
                        2: QTableWidgetItem(roi_text_value),  # ROI 텍스트
                        3: QTableWidgetItem(display_text),  # 편집 텍스트
                        4: QTableWidgetItem(str(start_frame + 1)),  # 시작 프레임
                        5: QTableWidgetItem(str(end_frame + 1)),  # 종료 프레임
                        6: QTableWidgetItem(f"{start_time:.3f}"),  # 시작 시간
                        7: QTableWidgetItem(f"{end_time:.3f}"),  # 종료 시간
                        8: QTableWidgetItem(str(num_frames)),  # 프레임 수
                    }
                    
                    # 플래그 설정
                    items_by_row[row_position][0].setFlags(non_editable_flags)
                    items_by_row[row_position][2].setFlags(non_editable_flags)
                    items_by_row[row_position][4].setData(Qt.UserRole, start_frame)
                    items_by_row[row_position][5].setData(Qt.UserRole, end_frame)
                    items_by_row[row_position][6].setFlags(non_editable_flags)
                    items_by_row[row_position][7].setFlags(non_editable_flags)
                    items_by_row[row_position][8].setFlags(non_editable_flags)
                
                # 모든 아이템을 한 번에 설정 (배치 처리)
                for row_position, items in items_by_row.items():
                    for col, item in items.items():
                        self.table.setItem(row_position, col, item)
                
                # 썸네일 placeholder는 나중에 한 번에 설정 (또는 아예 설정하지 않음)
                # 썸네일은 백그라운드에서 생성되므로 placeholder 불필요
                
                # 이미지 디코딩 및 썸네일 생성은 백그라운드에서 처리
                QTimer.singleShot(0, lambda: self._populate_thumbnails_lazy(segments))
                
            finally:
                self._updating = old_updating
                # UI 업데이트 재활성화
                self.table.setUpdatesEnabled(True)
            
            # 타임라인, summary, 선택 상태, 프리뷰 업데이트는 모두 비동기로 처리 (성능 최적화)
            # _update_ui_async 완료 후에 _updating_from_web 플래그를 해제해야 함
            def complete_web_update():
                try:
                    self._update_ui_async()
                finally:
                    self._updating_from_web = False
                    # 백그라운드 로딩 재개
                    self._background_loading_paused = False
                    # print(f"[WebSocket] {len(segments)}개 세그먼트 적용 완료 (웹 업데이트 플래그 해제, 백그라운드 로딩 재개)")

            QTimer.singleShot(0, complete_web_update)

            # print(f"[WebSocket] {len(segments)}개 세그먼트 적용 시작")

        except Exception as e:
            pass
            # print(f"[WebSocket] 세그먼트 적용 오류: {e}")
            import traceback
            traceback.print_exc()
            self._updating_from_web = False
            # 오류 발생 시에도 백그라운드 로딩 재개
            self._background_loading_paused = False

    def _populate_thumbnails_lazy(self, segments):
        """썸네일을 지연 로딩으로 생성 (성능 최적화)"""
        import base64

        # 처음 30개는 무조건 즉시 로드 (populate_table과 동일)
        INITIAL_LOAD_COUNT = 30
        start_row = 0
        end_row = min(INITIAL_LOAD_COUNT, len(segments))
        
        # 이미지 디코딩 및 썸네일 생성
        for row_position in range(start_row, end_row):
            if row_position >= len(segments):
                pass
                break
                
            item = segments[row_position]
            roi_image_data = self.segment_images[row_position]
            
            # base64 디코딩
            roi_bytes = None
            if isinstance(roi_image_data, str) and roi_image_data:
                try:
                    roi_bytes = base64.b64decode(roi_image_data)
                    self.segment_images[row_position] = roi_bytes
                except Exception:
                    pass
                    # 디코딩 실패 시 비디오에서 추출
                    start_frame = int(item.get('start_frame', 0))
                    if self.video_path and os.path.exists(self.video_path):
                        roi_bytes = self._extract_frame_thumbnail(self.video_path, start_frame)
                        self.segment_images[row_position] = roi_bytes
            elif roi_image_data is None:
                pass
                # 이미지가 없으면 비디오에서 추출
                start_frame = int(item.get('start_frame', 0))
                if self.video_path and os.path.exists(self.video_path):
                    roi_bytes = self._extract_frame_thumbnail(self.video_path, start_frame)
                    self.segment_images[row_position] = roi_bytes
            else:
                roi_bytes = roi_image_data
            
            # 썸네일 위젯 생성
            self._create_thumbnail_widget(row_position, roi_bytes, item)
        
        # 나머지 행들은 백그라운드에서 처리
        if end_row < len(segments):
            QTimer.singleShot(50, lambda: self._populate_remaining_thumbnails(segments, end_row))
    
    def _get_visible_row_range(self):
        """현재 보이는 행 범위를 반환"""
        viewport = self.table.viewport()
        top_index = self.table.indexAt(viewport.rect().topLeft())
        bottom_index = self.table.indexAt(viewport.rect().bottomLeft())
        
        top = top_index.row() if top_index.isValid() else 0
        bottom = bottom_index.row() if bottom_index.isValid() else self.table.rowCount() - 1
        
        # 유효하지 않은 경우 전체 범위 반환
        if top < 0:
            top = 0
        if bottom < 0 or bottom >= self.table.rowCount():
            bottom = max(0, self.table.rowCount() - 1)
        
        return (top, bottom)
    
    def _populate_remaining_thumbnails(self, segments, start_row):
        """나머지 썸네일을 백그라운드에서 생성"""
        # WebSocket 업데이트 중에는 썸네일 로딩 일시 중지
        if self._background_loading_paused:
            pass
            # 500ms 후 다시 시도
            QTimer.singleShot(500, lambda: self._populate_remaining_thumbnails(segments, start_row))
            return

        import base64

        # 한 번에 처리할 행 수 (성능 고려)
        batch_size = 20
        end_row = min(start_row + batch_size, len(segments))
        
        for row_position in range(start_row, end_row):
            if row_position >= len(segments):
                pass
                break
                
            item = segments[row_position]
            roi_image_data = self.segment_images[row_position]
            
            # base64 디코딩
            roi_bytes = None
            if isinstance(roi_image_data, str) and roi_image_data:
                try:
                    roi_bytes = base64.b64decode(roi_image_data)
                    self.segment_images[row_position] = roi_bytes
                except Exception:
                    start_frame = int(item.get('start_frame', 0))
                    if self.video_path and os.path.exists(self.video_path):
                        roi_bytes = self._extract_frame_thumbnail(self.video_path, start_frame)
                        self.segment_images[row_position] = roi_bytes
            elif roi_image_data is None:
                start_frame = int(item.get('start_frame', 0))
                if self.video_path and os.path.exists(self.video_path):
                    roi_bytes = self._extract_frame_thumbnail(self.video_path, start_frame)
                    self.segment_images[row_position] = roi_bytes
            else:
                roi_bytes = roi_image_data
            
            # 썸네일 위젯 생성
            self._create_thumbnail_widget(row_position, roi_bytes, item)
        
        # 다음 배치 처리
        if end_row < len(segments):
            QTimer.singleShot(10, lambda: self._populate_remaining_thumbnails(segments, end_row))
    
    def _create_thumbnail_widget(self, row, roi_bytes, segment_item):
        """썸네일 위젯을 생성 (populate_table_row의 썸네일 부분만)"""
        detections = self.segment_detections[row] if row < len(self.segment_detections) else []
        
        # 썸네일을 담을 위젯
        thumb_widget = QWidget()
        thumb_layout = QVBoxLayout(thumb_widget)
        thumb_layout.setContentsMargins(0, 0, 0, 0)
        thumb_layout.setSpacing(0)
        
        thumb_label = QLabel()
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setStyleSheet("QLabel { background: #050505; border: 1px solid #222; color: #555; }")
        
        # OCR 모드에 따라 썸네일 크기 결정
        is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']
        slider_value = self.thumbnail_size_slider.value() if hasattr(self, 'thumbnail_size_slider') else 2
        
        # 원본 pixmap 생성
        original_pixmap = self._pixmap_with_boxes(roi_bytes, detections, None)
        
        if is_ocr_mode:
            if original_pixmap:
                orig_width = original_pixmap.width()
                orig_height = original_pixmap.height()
                base_height = 40
                target_height = base_height * slider_value
                aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                target_width = int(target_height * aspect_ratio)
                thumbnail_size = QSize(target_width, target_height)
                self.table.setRowHeight(row, target_height + 10)
                if row == 0:
                    self.table.setColumnWidth(1, target_width + 10)
                pixmap = original_pixmap.scaled(
                    thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            else:
                pixmap = None
        else:
            base_width = 96
            base_height = 54
            thumbnail_width = base_width * slider_value
            thumbnail_height = base_height * slider_value
            thumbnail_size = QSize(thumbnail_width, thumbnail_height)
            row_height = thumbnail_height + 10
            column_width = thumbnail_width + 10
            self.table.setRowHeight(row, row_height)
            if row == 0:
                self.table.setColumnWidth(1, column_width)
            if original_pixmap:
                pixmap = original_pixmap.scaled(
                    thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            else:
                pixmap = None
        
        if pixmap:
            thumb_label.setPixmap(pixmap)
            thumb_label.setProperty('original_pixmap', original_pixmap)
        else:
            thumb_label.setText("이미지 없음")
        
        # tooltip 생성
        start_frame = int(segment_item.get('start_frame', 0))
        end_frame = int(segment_item.get('end_frame', 0))
        tooltip_text = f"프레임: {start_frame + 1} → {end_frame + 1}"
        thumb_label.setToolTip(tooltip_text)
        thumb_layout.addWidget(thumb_label)
        
        # 재생 버튼 오버레이
        play_button = QPushButton("▶")
        play_button.setFixedSize(30, 30)
        play_button.setStyleSheet("""
            QPushButton {
                background: rgba(255, 165, 0, 200);
                color: white;
                border: 2px solid rgba(255, 255, 255, 150);
                border-radius: 15px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255, 165, 0, 255);
                border: 2px solid rgba(255, 255, 255, 200);
            }
            QPushButton:pressed {
                background: rgba(255, 140, 0, 255);
            }
        """)
        play_button.setCursor(Qt.PointingHandCursor)
        play_button.setProperty("table_row", row)
        play_button.setParent(thumb_label)
        play_button.raise_()
        play_button.show()
        
        def update_button_position():
            if thumb_label.pixmap():
                label_width = thumb_label.width()
                label_height = thumb_label.height()
                x = (label_width - play_button.width()) // 2
                y = (label_height - play_button.height()) // 2
                play_button.move(x, y)
        
        original_resize_event = thumb_label.resizeEvent
        def resize_event_wrapper(e):
            if original_resize_event:
                original_resize_event(e)
            update_button_position()
        thumb_label.resizeEvent = resize_event_wrapper
        
        play_button.clicked.connect(lambda checked, r=row: self._on_play_button_clicked(r))
        update_button_position()

        self.table.setCellWidget(row, 1, thumb_widget)

        # 캐시에 추가 (중요: 썸네일이 로드된 것으로 표시)
        self._thumbnail_cache[row] = True
    
    def _update_timeline_and_summary_async(self, data=None):
        """타임라인과 summary를 비동기로 업데이트 (성능 최적화)"""
        try:
            pass
            # _updating 플래그를 일시적으로 해제하여 collect_segments가 작동하도록
            old_updating = self._updating
            self._updating = False
            
            updated_segments = self.collect_segments()
            self.timeline.set_segments(updated_segments)
            self.update_summary()
            
            self._updating = old_updating
        except Exception as e:
            pass
            # print(f"[비동기 타임라인 업데이트 오류] {e}")
    
    def _update_ui_async(self):
        """UI 업데이트를 비동기로 처리 (성능 최적화)"""
        try:
            pass
            # 타임라인 및 summary 업데이트
            updated_segments = self.collect_segments()
            self.timeline.set_segments(updated_segments)
            self.update_summary()

            # 웹 UI에서 선택한 인덱스 확인
            web_selected_index = getattr(self, '_web_selected_index', None)

            if web_selected_index is not None:
                pass
                # 웹 UI에서 선택한 인덱스 사용
                if 0 <= web_selected_index < self.table.rowCount():
                    self.table.selectRow(web_selected_index)
                    self.update_preview(web_selected_index, immediate=True)
                    # print(f"[WebSocket] 웹 UI 선택 인덱스 적용: {web_selected_index}")
                else:
                    pass
                    # 인덱스가 범위를 벗어나면 마지막 행 선택
                    if self.table.rowCount() > 0:
                        last_row = self.table.rowCount() - 1
                        self.table.selectRow(last_row)
                        self.update_preview(last_row, immediate=True)
                    else:
                        self.update_preview(-1, immediate=True)
                # 사용 후 초기화
                self._web_selected_index = None
            else:
                pass
                # 웹 선택 인덱스가 없으면 기존 로직 사용
                # 선택 상태 업데이트 (삭제된 행이 선택되어 있었다면 선택 해제)
                selection_model = self.table.selectionModel()
                if selection_model:
                    selected_rows = sorted({index.row() for index in selection_model.selectedRows()})
                    # 유효하지 않은 행이 선택되어 있으면 선택 해제
                    valid_selected_rows = [r for r in selected_rows if 0 <= r < self.table.rowCount()]
                    if len(valid_selected_rows) != len(selected_rows):
                        pass
                        # 선택 해제
                        selection_model.clearSelection()
                        # 유효한 행이 있으면 첫 번째 행 선택
                        if valid_selected_rows:
                            self.table.selectRow(valid_selected_rows[0])
                        # 비디오 프리뷰 업데이트
                        if valid_selected_rows:
                            self.update_preview(valid_selected_rows[0], immediate=True)
                        else:
                            pass
                            # 선택된 행이 없으면 프리뷰 초기화
                            self.update_preview(-1, immediate=True)
                    elif valid_selected_rows:
                        pass
                        # 유효한 선택이 있으면 프리뷰 업데이트
                        self.update_preview(valid_selected_rows[0], immediate=True)
                else:
                    pass
                    # 선택 모델이 없으면 첫 번째 행 선택
                    if self.table.rowCount() > 0:
                        self.table.selectRow(0)
                        self.update_preview(0, immediate=True)
                    else:
                        pass
                        # 행이 없으면 프리뷰 초기화
                        self.update_preview(-1, immediate=True)
        except Exception as e:
            pass
            # print(f"[비동기 UI 업데이트 오류] {e}")

    def broadcast_segments_change(self):
        """테이블 변경사항을 웹 UI에 브로드캐스트합니다."""
        # 웹으로부터 업데이트 중이면 브로드캐스트하지 않음 (무한 루프 방지)
        if hasattr(self, '_updating_from_web') and self._updating_from_web:
            pass
            return

        if not self.websocket_clients:
            pass
            return

        self.send_full_sync()

    def _on_table_scrolled(self):
        """테이블 스크롤 시 보이는 행의 썸네일을 lazy loading합니다."""
        # WebSocket 업데이트 중에는 스크롤 로딩 건너뛰기
        if self._background_loading_paused:
            pass
            return

        # 현재 보이는 행 범위 계산
        viewport = self.table.viewport()
        top_left = self.table.indexAt(viewport.rect().topLeft())
        bottom_right = self.table.indexAt(viewport.rect().bottomRight())

        if not top_left.isValid() or not bottom_right.isValid():
            pass
            return

        start_row = max(0, top_left.row())
        end_row = min(self.table.rowCount() - 1, bottom_right.row())

        # 보이는 행 + 버퍼 (위아래 5개씩 추가)
        buffer = 5
        start_row = max(0, start_row - buffer)
        end_row = min(self.table.rowCount() - 1, end_row + buffer)

        # 보이는 행에 대해 썸네일 로드
        for row in range(start_row, end_row + 1):
            pass
            # 이미 로드된 행은 건너뛰기
            if row in self._thumbnail_cache:
                pass
                continue

            # 이미 segment_images에 썸네일이 있으면 캐시에 추가하고 건너뛰기
            if row < len(self.segment_images) and self.segment_images[row]:
                self._thumbnail_cache[row] = True
                continue

            # 현재 로딩 중인 행은 건너뛰기
            if row in self._thumbnail_load_in_progress:
                pass
                continue

            # 썸네일 로드 시작 (비디오에서 추출이 필요한 경우만)
            # 애니매틱 모드이고 비디오 경로가 있는 경우만 로드
            if getattr(self, 'ocr_mode', 'titmouse') in ['animatic', 'animatic2'] and \
               self.video_path and os.path.exists(self.video_path):
                self._thumbnail_load_in_progress.add(row)
                self._load_thumbnail_for_row(row)

    def _load_thumbnail_for_row(self, row):
        """특정 행의 썸네일을 로드합니다."""
        # segment_images에서 데이터 가져오기
        if row >= len(self.segment_images) or row >= len(self.segment_detections):
            self._thumbnail_load_in_progress.discard(row)
            return

        roi_bytes = self.segment_images[row]
        detections = self.segment_detections[row]

        # roi_bytes가 없고 비디오 경로가 있으면 프레임 추출
        if not roi_bytes and getattr(self, 'ocr_mode', 'titmouse') in ['animatic', 'animatic2'] and self.video_path and os.path.exists(self.video_path):
            pass
            # 테이블에서 start_frame 가져오기
            start_frame_item = self.table.item(row, 4)
            if start_frame_item:
                start_frame = start_frame_item.data(Qt.UserRole)  # 0-based
                roi_bytes = self._extract_frame_thumbnail(self.video_path, start_frame)
                self.segment_images[row] = roi_bytes  # 캐시에 저장

        # pixmap 생성
        original_pixmap = self._pixmap_with_boxes(roi_bytes, detections, None)

        # 셀 위젯 업데이트
        thumb_widget = self.table.cellWidget(row, 1)
        if thumb_widget:
            thumb_label = thumb_widget.findChild(QLabel)
            if thumb_label:
                pass
                # OCR 모드에 따라 썸네일 크기 결정
                is_ocr_mode = getattr(self, 'ocr_mode', 'titmouse') not in ['animatic', 'animatic2']

                if is_ocr_mode:
                    if original_pixmap:
                        orig_width = original_pixmap.width()
                        orig_height = original_pixmap.height()
                        target_height = 80
                        aspect_ratio = orig_width / orig_height if orig_height > 0 else 1.0
                        target_width = int(target_height * aspect_ratio)
                        thumbnail_size = QSize(target_width, target_height)
                        pixmap = original_pixmap.scaled(thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    else:
                        pixmap = None
                else:
                    pass
                    # 애니매틱 모드
                    thumbnail_size = QSize(192, 108)
                    if original_pixmap:
                        pixmap = original_pixmap.scaled(thumbnail_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    else:
                        pixmap = None

                if pixmap:
                    thumb_label.setPixmap(pixmap)
                    thumb_label.setProperty('original_pixmap', original_pixmap)
                else:
                    thumb_label.setText("이미지 없음")

        # 로딩 완료 표시
        self._thumbnail_cache[row] = True
        self._thumbnail_load_in_progress.discard(row)

    def _load_remaining_thumbnails(self):
        """
        다이얼로그가 열린 후 나머지 썸네일을 백그라운드에서 로드합니다.
        한 번에 10개씩 배치로 처리하여 UI가 블록되지 않도록 합니다.
        """
        # WebSocket 업데이트 중에는 백그라운드 로딩 일시 중지
        if self._background_loading_paused:
            pass
            # 500ms 후 다시 시도
            QTimer.singleShot(500, self._load_remaining_thumbnails)
            return

        INITIAL_LOAD_COUNT = 30  # populate_table과 동일한 값
        BATCH_SIZE = 10  # 한 번에 로드할 썸네일 개수

        total_rows = self.table.rowCount()

        # 이미 segment_images에 썸네일이 있는 행은 캐시에 추가하고 건너뛰기
        for row in range(INITIAL_LOAD_COUNT, total_rows):
            if row not in self._thumbnail_cache:
                pass
                # 이미 segment_images에 썸네일이 있으면 캐시에 추가하고 건너뛰기
                if row < len(self.segment_images) and self.segment_images[row]:
                    self._thumbnail_cache[row] = True
                    # UI 업데이트는 이미 populate_table에서 했으므로 건너뛰기

        # 로드할 행 찾기 (비디오에서 추출이 필요한 행만)
        rows_to_load = []
        for row in range(INITIAL_LOAD_COUNT, total_rows):
            if row not in self._thumbnail_cache and row not in self._thumbnail_load_in_progress:
                pass
                # segment_images에 썸네일이 없고, 애니매틱 모드이고, 비디오 경로가 있는 경우만 로드
                if (row >= len(self.segment_images) or not self.segment_images[row]) and \
                   getattr(self, 'ocr_mode', 'titmouse') in ['animatic', 'animatic2'] and \
                   self.video_path and os.path.exists(self.video_path):
                    rows_to_load.append(row)

        if not rows_to_load:
            pass
            # print(f"[백그라운드 로드] 모든 썸네일 로드 완료 (총 {total_rows}개)")
            return

        # 첫 번째 배치 처리
        batch = rows_to_load[:BATCH_SIZE]
        remaining = rows_to_load[BATCH_SIZE:]

        for row in batch:
            self._thumbnail_load_in_progress.add(row)
            self._load_thumbnail_for_row(row)

        # print(f"[백그라운드 로드] {len(batch)}개 썸네일 로드 완료, 남은 개수: {len(remaining)}")

        # 남은 배치가 있으면 50ms 후에 다음 배치 처리
        if remaining:
            QTimer.singleShot(50, self._load_remaining_thumbnails)

    def _show_table_context_menu(self, position):
        """테이블 우클릭 메뉴 표시"""
        menu = QMenu(self)
        
        # 선택한 구간 병합
        merge_action = menu.addAction("선택한 구간 병합")
        merge_action.triggered.connect(self.merge_selected_rows)
        merge_action.setShortcut("D")
        
        # 스마트 병합
        smart_merge_action = menu.addAction("스마트 병합")
        smart_merge_action.triggered.connect(self.smart_merge_by_scene)
        
        # 선택 구간 삭제
        remove_action = menu.addAction("선택 구간 삭제")
        remove_action.triggered.connect(self.remove_selected_rows)
        remove_action.setShortcut("X")
        
        menu.addSeparator()
        
        # 씬 분할
        split_action = menu.addAction("씬 분할")
        split_action.triggered.connect(self.split_selected_row)
        
        # 일괄 리네임
        rename_action = menu.addAction("일괄 리네임")
        rename_action.triggered.connect(self.batch_rename_segments)
        
        menu.addSeparator()
        
        # 실행 취소
        undo_action = menu.addAction("↶ 실행 취소")
        undo_action.triggered.connect(self.undo_action)
        undo_action.setShortcut(QKeySequence.Undo)
        undo_action.setEnabled(self.undoButton.isEnabled())
        
        # 다시 실행
        redo_action = menu.addAction("↷ 다시 실행")
        redo_action.triggered.connect(self.redo_action)
        redo_action.setShortcut(QKeySequence.Redo)
        redo_action.setEnabled(self.redoButton.isEnabled())
        
        menu.addSeparator()
        
        # 웹분석
        web_analysis_action = menu.addAction("웹분석")
        web_analysis_action.triggered.connect(self.export_to_web)
        
        menu.addSeparator()
        
        # 선택한 항목만 내보내기
        export_selected_action = menu.addAction("선택한 항목만 내보내기")
        export_selected_action.triggered.connect(self.export_selected_only)
        
        # 전체 내보내기
        export_all_action = menu.addAction("전체 내보내기")
        export_all_action.triggered.connect(self.export_all)
        export_all_action.setShortcut("R")
        
        menu.addSeparator()
        
        # 재분석
        reanalyze_action = menu.addAction("재분석")
        reanalyze_action.triggered.connect(self.reject)
        
        # 메뉴 표시
        menu.exec_(self.table.viewport().mapToGlobal(position))
    
    def _show_timeline_context_menu(self, position):
        """타임라인 우클릭 메뉴 표시"""
        menu = QMenu(self)
        
        # 선택한 구간 병합
        merge_action = menu.addAction("선택한 구간 병합")
        merge_action.triggered.connect(self.merge_selected_rows)
        merge_action.setShortcut("D")
        
        # 스마트 병합
        smart_merge_action = menu.addAction("스마트 병합")
        smart_merge_action.triggered.connect(self.smart_merge_by_scene)
        
        # 선택 구간 삭제
        remove_action = menu.addAction("선택 구간 삭제")
        remove_action.triggered.connect(self.remove_selected_rows)
        remove_action.setShortcut("X")
        
        menu.addSeparator()
        
        # 씬 분할
        split_action = menu.addAction("씬 분할")
        split_action.triggered.connect(self.split_selected_row)
        
        # 일괄 리네임
        rename_action = menu.addAction("일괄 리네임")
        rename_action.triggered.connect(self.batch_rename_segments)
        
        menu.addSeparator()
        
        # 실행 취소
        undo_action = menu.addAction("↶ 실행 취소")
        undo_action.triggered.connect(self.undo_action)
        undo_action.setShortcut(QKeySequence.Undo)
        undo_action.setEnabled(self.undoButton.isEnabled())
        
        # 다시 실행
        redo_action = menu.addAction("↷ 다시 실행")
        redo_action.triggered.connect(self.redo_action)
        redo_action.setShortcut(QKeySequence.Redo)
        redo_action.setEnabled(self.redoButton.isEnabled())
        
        menu.addSeparator()
        
        # 웹분석
        web_analysis_action = menu.addAction("웹분석")
        web_analysis_action.triggered.connect(self.export_to_web)
        
        menu.addSeparator()
        
        # 선택한 항목만 내보내기
        export_selected_action = menu.addAction("선택한 항목만 내보내기")
        export_selected_action.triggered.connect(self.export_selected_only)
        
        # 전체 내보내기
        export_all_action = menu.addAction("전체 내보내기")
        export_all_action.triggered.connect(self.export_all)
        export_all_action.setShortcut("R")
        
        menu.addSeparator()
        
        # 재분석
        reanalyze_action = menu.addAction("재분석")
        reanalyze_action.triggered.connect(self.reject)
        
        # 메뉴 표시
        menu.exec_(self.timeline.mapToGlobal(position))

    def closeEvent(self, event):
        """다이얼로그 종료 시 WebSocket 서버 정리."""
        if self.websocket_server:
            for client in self.websocket_clients:
                client.close()
            self.websocket_server.close()
            print("[WebSocket] 서버 종료")
        super().closeEvent(event)
