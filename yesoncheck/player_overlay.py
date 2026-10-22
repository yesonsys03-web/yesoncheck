"""오버레이 컨트롤 믹스인 (PlayerOverlayMixin): 영상 위에 띄우는 재생 막대(V 키로 컨트롤 패널을 숨기면 보임)의 위젯 만들기,
위치·크기(드래그·크기 조절·하단 중앙 재배치)와 설정 파일(`~/.yeson_overlay_settings.json`) 읽기·쓰기, 보이기·숨기기·값 갱신.

VideoPlayerBase의 부모 클래스로 붙음 — `class VideoPlayerBase(PlayerOcrMixin, PlayerOverlayMixin, QMainWindow)`. 그래서
VideoPlayer의 MRO에서 VideoPlayerBase 뒤(QMainWindow 앞)에 오고, 다른 믹스인과의 가림 관계·`VideoPlayerBase.X`로 찾는 접근은
예전과 같음. 위젯·상태(`self.overlay*`)는 예전처럼 VideoPlayerBase.__init__이 부르는 create_overlay_controls·
load_overlay_settings가 만들고, 이 메서드들을 부르는 `eventFilter`·`changeEvent`·`resizeEvent`와 재생 믹스인은 `self.`로
부르므로 그대로 닿음.

player_base를 모듈 수준에서 import하지 말 것 — player_base가 상속하려고 이 모듈을 불러오므로 순환이 됨. 사용자 파일 문제 알림
(`_report_user_file_problem`)은 VideoPlayerBase에 남아 있고 `self.`로 부름.
"""

import os
import traceback

from PyQt5.QtCore import QRect, QSize, Qt
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from yesoncheck import user_files
from yesoncheck.main_window_styles import (
    OVERLAY_CURRENT_FRAME_LABEL_STYLE,
    OVERLAY_FILE_NAME_LABEL_STYLE,
    OVERLAY_FILE_NAME_LABEL_STYLE_TEMPLATE,
    OVERLAY_FRAME_NUMBER_LABEL_STYLE,
    OVERLAY_FRAME_STYLE,
    OVERLAY_HELP_LABEL_STYLE,
    OVERLAY_PLAY_PAUSE_STYLE,
    OVERLAY_SLIDER_STYLE,
    OVERLAY_VOLUME_STYLE,
)
from yesoncheck.slider_style import jump_to_click
from yesoncheck.user_files import UserFileError


class PlayerOverlayMixin:
    """VideoPlayer의 오버레이 컨트롤(영상 위 재생 막대) — 만들기·위치와 크기·설정 저장·보이기와 갱신."""

    def reposition_overlay_to_bottom_center(self):
        """V 키 활성 상태에서 윈도우 크기 변경 시 오버레이 컨트롤러를 하단 중앙으로 재배치"""
        if not hasattr(self, 'overlayFrame') or not self.overlayFrame:
            return
            
        if not self.overlayFrame.isVisible():
            return
            
        # 현재 윈도우 크기
        parent_size = self.size()
        overlay_size = self.overlayFrame.size()
        
        # 하단 중앙 위치 계산
        x = max(0, (parent_size.width() - overlay_size.width()) // 2)
        y = max(0, parent_size.height() - overlay_size.height() - 50)  # 하단에서 50px 위
        
        # 오버레이 위치 설정
        self.overlayFrame.move(x, y)
        
        # 하단 중앙 위치임을 표시하는 플래그 설정
        self.overlay_is_bottom_center = True
        
        # 현재 위치와 윈도우 크기를 저장 (비율 계산용)
        self.overlay_saved_pos = (x, y)
        self.overlay_saved_parent_size = (parent_size.width(), parent_size.height())
        
        print(f"오버레이 컨트롤러를 하단 중앙으로 재배치: ({x}, {y})")

    def create_overlay_controls(self):
        """오버레이 컨트롤을 생성합니다."""
        self.overlayFrame = QFrame(self)
        self.overlayFrame.setStyleSheet(OVERLAY_FRAME_STYLE)
        
        # 리사이즈 영역을 시각적으로 표시하는 오버레이 위젯
        self.resize_overlay = QWidget(self.overlayFrame)
        self.resize_overlay.setStyleSheet('''
            QWidget {
                background-color: rgba(255, 255, 255, 30);
                border: 1px solid rgba(255, 255, 255, 60);
            }
        ''')
        self.resize_overlay.setVisible(False)
        self.resize_overlay.raise_()
        
        # 도움말 라벨 추가
        self.overlayHelpLabel = QLabel('드래그로 이동, 테두리로 크기조절, Ctrl+휠로 확대/축소, Ctrl+O로 리셋', self.overlayFrame)
        self.overlayHelpLabel.setStyleSheet(OVERLAY_HELP_LABEL_STYLE)
        self.overlayHelpLabel.setAlignment(Qt.AlignCenter)
        self.overlayHelpLabel.setVisible(False)  # 초기에는 숨김
        
        # 도움말 표시/숨김 토글
        def toggle_help():
            self.overlayHelpLabel.setVisible(not self.overlayHelpLabel.isVisible())
        
        # 통합된 마우스 프레스 이벤트 핸들러
        def unified_mouse_press_event(event):
            if event.button() == Qt.RightButton:
                toggle_help()
            elif event.button() == Qt.LeftButton:
                overlay_mouse_press_event(event)
        
        self.overlayFrame.mousePressEvent = unified_mouse_press_event
        self.overlayFrame.setMinimumHeight(80)  # 최소 높이 설정
        self.overlayFrame.setMaximumHeight(200)  # 최대 높이 설정
        self.overlayFrame.setMinimumWidth(400)  # 최소 너비 설정
        self.overlayFrame.setMaximumWidth(1200)  # 최대 너비 설정
        
        # 저장된 크기가 있으면 사용, 없으면 기본 크기
        if hasattr(self, 'overlay_saved_size') and self.overlay_saved_size:
            width, height = self.overlay_saved_size
            # 크기 제한 적용
            width = max(400, min(1200, width))
            height = max(80, min(200, height))
            self.overlayFrame.resize(width, height)
        else:
            self.overlayFrame.resize(800, 120)  # 기본 크기 설정
        self.overlayFrame.setVisible(False)
        self.overlayFrame.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        
        # 드래그 및 리사이즈 관련 변수 초기화
        self.overlay_dragging = False
        self.overlay_resizing = False
        self.overlay_drag_start_pos = None
        self.overlay_original_pos = None
        self.overlay_original_size = None
        self.overlay_resize_edge = None
        
        # 오버레이 설정 저장/복원을 위한 변수
        self.overlay_settings_file = os.path.join(os.path.expanduser('~'), '.yeson_overlay_settings.json')
        self.load_overlay_settings()
        
        # 오버레이 프레임을 최상위로 올리고 부모 위젯에 명시적으로 추가
        self.overlayFrame.raise_()
        self.overlayFrame.setAttribute(Qt.WA_TranslucentBackground, False)
        self.overlayFrame.setWindowFlags(Qt.FramelessWindowHint)
        self.overlayFrame.setAttribute(Qt.WA_ShowWithoutActivating, True)
        
        # 재생/일시정지 버튼
        self.overlayPlayPause = QPushButton('▶', self.overlayFrame)  # 초기 상태는 재생 버튼
        self.overlayPlayPause.setFixedSize(56, 56)
        self.overlayPlayPause.setStyleSheet(OVERLAY_PLAY_PAUSE_STYLE)
        self.overlayPlayPause.clicked.connect(self.toggle_play_pause)
        
        # 슬라이더 컨테이너 (프레임 표시를 위한 수직 레이아웃)
        sliderContainer = QVBoxLayout()
        sliderContainer.setSpacing(8)
        
        # 프레임 표시 라벨들
        frameLabelsLayout = QHBoxLayout()
        frameLabelsLayout.setContentsMargins(0, 0, 0, 0)
        
        # 시작 프레임 라벨
        self.overlayStartFrameLabel = QLabel('0', self.overlayFrame)
        self.overlayStartFrameLabel.setStyleSheet(OVERLAY_FRAME_NUMBER_LABEL_STYLE)
        self.overlayStartFrameLabel.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        # 현재 프레임 라벨 (드래그 중 실시간 업데이트)
        self.overlayCurrentFrameLabel = QLabel('1', self.overlayFrame)
        self.overlayCurrentFrameLabel.setStyleSheet(OVERLAY_CURRENT_FRAME_LABEL_STYLE)
        self.overlayCurrentFrameLabel.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        self.overlayCurrentFrameLabel.setVisible(False)  # 초기에는 숨김
        
        # 파일명 라벨
        self.overlayFileNameLabel = QLabel('No File', self.overlayFrame)
        self.overlayFileNameLabel.setStyleSheet(OVERLAY_FILE_NAME_LABEL_STYLE)
        self.overlayFileNameLabel.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        self.overlayFileNameLabel.setWordWrap(True)
        self.overlayFileNameLabel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # 끝 프레임 라벨
        self.overlayEndFrameLabel = QLabel('0', self.overlayFrame)
        self.overlayEndFrameLabel.setStyleSheet(OVERLAY_FRAME_NUMBER_LABEL_STYLE)
        self.overlayEndFrameLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        frameLabelsLayout.addWidget(self.overlayStartFrameLabel)
        frameLabelsLayout.addStretch()
        frameLabelsLayout.addWidget(self.overlayCurrentFrameLabel)
        frameLabelsLayout.addStretch()
        frameLabelsLayout.addWidget(self.overlayFileNameLabel)
        frameLabelsLayout.addStretch()
        frameLabelsLayout.addWidget(self.overlayEndFrameLabel)
        
        # 슬라이더
        self.overlaySlider = QSlider(Qt.Horizontal, self.overlayFrame)
        self.overlaySlider.setMinimum(0)
        self.overlaySlider.setMaximum(100)
        self.overlaySlider.setSingleStep(1)
        self.overlaySlider.setFixedHeight(36)
        self.overlaySlider.setStyleSheet(OVERLAY_SLIDER_STYLE)
        # Windows(Fusion 포함)에서도 Mac처럼 왼쪽 클릭으로 그 위치로 바로 이동 + 드래그 계속되게
        jump_to_click(self.overlaySlider)
        self.overlaySlider.sliderMoved.connect(self.on_overlay_slider_moved)
        self.overlaySlider.sliderReleased.connect(self.on_overlay_slider_released)
        self.overlaySlider.sliderPressed.connect(self.on_overlay_slider_pressed)
        
        # 슬라이더 컨테이너에 추가
        sliderContainer.addLayout(frameLabelsLayout)
        sliderContainer.addWidget(self.overlaySlider)
        
        # 볼륨 컨트롤
        self.overlayVolume = QScrollBar(Qt.Horizontal, self.overlayFrame)
        self.overlayVolume.setRange(0, 100)
        self.overlayVolume.setValue(50)
        self.overlayVolume.setFixedWidth(100)  # 너비 반으로 감소 (200 -> 100)
        self.overlayVolume.setFixedHeight(18)  # 높이 반으로 감소 (36 -> 18)
        self.overlayVolume.setStyleSheet(OVERLAY_VOLUME_STYLE)
        self.overlayVolume.valueChanged.connect(self.setVolume)
        
        # 프레임 라벨들에 볼륨 슬라이더 추가 (같은 Y 좌표에 배치)
        frameLabelsLayout.addWidget(self.overlayVolume)
        
        # 메인 레이아웃
        layout = QHBoxLayout(self.overlayFrame)
        layout.setContentsMargins(35, 10, 35, 10)  # 상하 여백 반으로 감소 (20 -> 10)
        layout.setSpacing(30)  # 간격 증가
        layout.addWidget(self.overlayPlayPause)
        layout.addLayout(sliderContainer, 2)  # 슬라이더 컨테이너의 stretch factor 증가
        self.overlayFrame.setLayout(layout)
        
        # 도움말 라벨을 오버레이 프레임의 하단에 배치
        help_layout = QVBoxLayout()
        help_layout.addStretch()
        help_layout.addWidget(self.overlayHelpLabel)
        help_layout.setContentsMargins(0, 0, 0, 5)
        
        # 메인 레이아웃에 도움말 레이아웃 추가
        main_layout = QVBoxLayout()
        main_layout.addLayout(layout)
        main_layout.addLayout(help_layout)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 기존 레이아웃을 메인 레이아웃으로 교체
        self.overlayFrame.setLayout(main_layout)
        
        # 오버레이 프레임에 마우스 이벤트 연결 (컨트롤 패널 상태 확인 후)
        def safe_mouse_enter(event):
            if not self.controls_visible:
                self.on_overlay_mouse_enter()
        
        def safe_mouse_leave(event):
            if not self.controls_visible:
                self.on_overlay_mouse_leave()
        
        # 드래그 및 리사이즈를 위한 마우스 이벤트 오버라이드
        def overlay_mouse_press_event(event):
            if event.button() == Qt.LeftButton:
                # 리사이즈 영역 확인 (테두리 15px로 증가)
                edge_size = 15
                rect = self.overlayFrame.rect()
                
                # 리사이즈 영역 체크 (더 정확한 조건)
                is_left_edge = event.x() <= edge_size
                is_right_edge = event.x() >= rect.width() - edge_size
                is_top_edge = event.y() <= edge_size
                is_bottom_edge = event.y() >= rect.height() - edge_size
                
                if is_left_edge or is_right_edge or is_top_edge or is_bottom_edge:
                    # 리사이즈 모드
                    self.overlay_resizing = True
                    self.overlay_resize_edge = self._get_resize_edge(event.pos(), rect, edge_size)
                    self.overlay_original_size = self.overlayFrame.size()
                    self.overlay_drag_start_pos = event.globalPos()
                else:
                    # 드래그 모드
                    self.overlay_dragging = True
                    self.overlay_drag_start_pos = event.globalPos()
                    self.overlay_original_pos = self.overlayFrame.pos()
            
            # 기존 마우스 이벤트 처리
            if not self.controls_visible:
                self.on_overlay_mouse_enter()
        
        def overlay_mouse_move_event(event):
            if self.overlay_dragging and self.overlay_drag_start_pos:
                # 드래그 처리
                delta = event.globalPos() - self.overlay_drag_start_pos
                new_pos = self.overlay_original_pos + delta
                
                # 화면 경계 체크
                parent_rect = self.rect()
                new_rect = QRect(new_pos, self.overlayFrame.size())
                
                if new_rect.left() < 0:
                    new_pos.setX(0)
                if new_rect.top() < 0:
                    new_pos.setY(0)
                if new_rect.right() > parent_rect.width():
                    new_pos.setX(parent_rect.width() - self.overlayFrame.width())
                if new_rect.bottom() > parent_rect.height():
                    new_pos.setY(parent_rect.height() - self.overlayFrame.height())
                
                self.overlayFrame.move(new_pos)
            
            elif self.overlay_resizing and self.overlay_drag_start_pos:
                # 리사이즈 처리
                delta = event.globalPos() - self.overlay_drag_start_pos
                new_size = QSize(self.overlay_original_size)  # 복사본 생성
                
                # 각 엣지별로 크기 조정
                if 'left' in self.overlay_resize_edge:
                    new_width = max(400, min(1200, self.overlay_original_size.width() - delta.x()))
                    new_size.setWidth(new_width)
                
                if 'right' in self.overlay_resize_edge:
                    new_width = max(400, min(1200, self.overlay_original_size.width() + delta.x()))
                    new_size.setWidth(new_width)
                
                if 'top' in self.overlay_resize_edge:
                    new_height = max(80, min(200, self.overlay_original_size.height() - delta.y()))
                    new_size.setHeight(new_height)
                
                if 'bottom' in self.overlay_resize_edge:
                    new_height = max(80, min(200, self.overlay_original_size.height() + delta.y()))
                    new_size.setHeight(new_height)
                
                self.overlayFrame.resize(new_size)
            
            # 커서 모양 변경 및 리사이즈 영역 표시
            if not self.overlay_dragging and not self.overlay_resizing:
                edge_size = 15  # 마우스 프레스와 동일한 크기
                rect = self.overlayFrame.rect()
                resize_edge = self._get_resize_edge(event.pos(), rect, edge_size)
                
                # 리사이즈 영역 시각적 표시
                if resize_edge:
                    self.resize_overlay.setVisible(True)
                    # 리사이즈 영역 위치 계산 (더 정확한 계산)
                    overlay_rect = QRect()
                    if 'left' in resize_edge:
                        overlay_rect.setLeft(0)
                        overlay_rect.setRight(edge_size)
                    if 'right' in resize_edge:
                        overlay_rect.setLeft(rect.width() - edge_size)
                        overlay_rect.setRight(rect.width())
                    if 'top' in resize_edge:
                        overlay_rect.setTop(0)
                        overlay_rect.setBottom(edge_size)
                    if 'bottom' in resize_edge:
                        overlay_rect.setTop(rect.height() - edge_size)
                        overlay_rect.setBottom(rect.height())
                    
                    # 교차 영역 처리
                    if len(resize_edge) == 2:
                        if 'left' in resize_edge and 'top' in resize_edge:
                            overlay_rect = QRect(0, 0, edge_size, edge_size)
                        elif 'right' in resize_edge and 'top' in resize_edge:
                            overlay_rect = QRect(rect.width() - edge_size, 0, edge_size, edge_size)
                        elif 'left' in resize_edge and 'bottom' in resize_edge:
                            overlay_rect = QRect(0, rect.height() - edge_size, edge_size, edge_size)
                        elif 'right' in resize_edge and 'bottom' in resize_edge:
                            overlay_rect = QRect(rect.width() - edge_size, rect.height() - edge_size, edge_size, edge_size)
                    
                    self.resize_overlay.setGeometry(overlay_rect)
                    
                    # 커서 모양 설정
                    if ('left' in resize_edge and 'top' in resize_edge) or ('right' in resize_edge and 'bottom' in resize_edge):
                        self.overlayFrame.setCursor(Qt.SizeFDiagCursor)
                    elif ('right' in resize_edge and 'top' in resize_edge) or ('left' in resize_edge and 'bottom' in resize_edge):
                        self.overlayFrame.setCursor(Qt.SizeBDiagCursor)
                    elif 'left' in resize_edge or 'right' in resize_edge:
                        self.overlayFrame.setCursor(Qt.SizeHorCursor)
                    elif 'top' in resize_edge or 'bottom' in resize_edge:
                        self.overlayFrame.setCursor(Qt.SizeVerCursor)
                else:
                    self.resize_overlay.setVisible(False)
                    self.overlayFrame.setCursor(Qt.SizeAllCursor)
            
            # 기존 마우스 이벤트 처리
            if not self.controls_visible:
                self.on_overlay_mouse_enter()
        
        def overlay_mouse_release_event(event):
            if event.button() == Qt.LeftButton:
                print(f"마우스 릴리즈: 드래그={self.overlay_dragging}, 리사이즈={self.overlay_resizing}")  # 디버깅
                # 드래그나 리사이즈가 완료되면 설정 저장
                if self.overlay_dragging or self.overlay_resizing:
                    print("설정 저장 호출")  # 디버깅
                    self.save_overlay_settings()
                
                self.overlay_dragging = False
                self.overlay_resizing = False
                self.overlay_drag_start_pos = None
                self.overlay_resize_edge = None
                self.overlayFrame.setCursor(Qt.ArrowCursor)
                
                # 리사이즈 오버레이 숨기기
                if hasattr(self, 'resize_overlay'):
                    self.resize_overlay.setVisible(False)
            
            # 기존 마우스 이벤트 처리
            if not self.controls_visible:
                self.on_overlay_mouse_enter()
        
        def overlay_wheel_event(event):
            # Ctrl+휠로 크기 조절
            if event.modifiers() == Qt.ControlModifier:
                delta = event.angleDelta().y()
                current_size = self.overlayFrame.size()
                
                if delta > 0:
                    # 확대
                    new_width = min(1200, current_size.width() + 20)
                    new_height = min(200, current_size.height() + 10)
                else:
                    # 축소
                    new_width = max(400, current_size.width() - 20)
                    new_height = max(80, current_size.height() - 10)
                
                self.overlayFrame.resize(new_width, new_height)
                # 크기 변경 후 설정 저장
                self.save_overlay_settings()
                event.accept()
            else:
                event.ignore()
        
        self.overlayFrame.mousePressEvent = overlay_mouse_press_event
        self.overlayFrame.mouseMoveEvent = overlay_mouse_move_event
        self.overlayFrame.mouseReleaseEvent = overlay_mouse_release_event
        self.overlayFrame.wheelEvent = overlay_wheel_event
        self.overlayFrame.enterEvent = safe_mouse_enter
        self.overlayFrame.leaveEvent = safe_mouse_leave

    def _get_resize_edge(self, pos, rect, edge_size):
        """마우스 위치에 따라 리사이즈 엣지를 반환합니다."""
        edges = []
        
        # 더 정확한 엣지 감지
        if pos.x() <= edge_size:
            edges.append('left')
        if pos.x() >= rect.width() - edge_size:
            edges.append('right')
        if pos.y() <= edge_size:
            edges.append('top')
        if pos.y() >= rect.height() - edge_size:
            edges.append('bottom')
        
        return edges

    def reset_overlay_position(self):
        """오버레이 컨트롤러의 위치와 크기를 기본값으로 리셋합니다."""
        if hasattr(self, 'overlayFrame'):
            # 저장된 위치와 크기 초기화
            self.overlay_saved_pos = None
            self.overlay_saved_size = None
            
            # 기본 크기로 리셋
            self.overlayFrame.resize(800, 120)
            # 기본 위치로 이동
            self.position_overlay_controls()
            # 설정 저장
            self.save_overlay_settings()
            print("오버레이 컨트롤러 위치가 리셋되었습니다.")

    @staticmethod
    def _overlay_pair(settings, key, path):
        """설정의 key 값: 없으면 None, 숫자 두 개의 목록이어야 하며 아니면 UserFileError."""
        value = settings.get(key)
        if value is None:
            return None
        if (not isinstance(value, list) or len(value) != 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
            raise UserFileError(f"오버레이 설정 파일 형식이 올바르지 않습니다: {path}\n'{key}'는 숫자 두 개의 목록이어야 합니다: {value!r}")
        return value

    def load_overlay_settings(self):
        """오버레이 설정을 파일에서 로드합니다. 읽지 못하면 기본값 (기록에 스택 트레이스 + 창 한 번, 파일은 그대로)."""
        self.overlay_saved_pos = None
        self.overlay_saved_size = None
        self.overlay_saved_parent_size = None
        self.overlay_is_bottom_center = False
        path = self.overlay_settings_file
        try:
            settings = user_files.read_json(path, {})
            if not isinstance(settings, dict):
                raise UserFileError(f"오버레이 설정 파일 형식이 올바르지 않습니다 (설정 목록이어야 함): {path}")
            saved_pos = self._overlay_pair(settings, 'position', path)
            saved_size = self._overlay_pair(settings, 'size', path)
            saved_parent_size = self._overlay_pair(settings, 'parent_size', path)
        except UserFileError as exc:
            traceback.print_exc()
            self._report_user_file_problem(
                "overlay-read", "오버레이 설정을 읽지 못함",
                f"오버레이 컨트롤러의 저장된 위치를 읽지 못해 기본 위치를 씁니다 (파일은 그대로 둡니다):\n{exc}")
            return

        # 유효성 검사
        if saved_pos and (saved_pos[0] < 0 or saved_pos[1] < 0):
            print("저장된 위치가 유효하지 않아 기본값으로 초기화합니다.")
            saved_pos = None
        if saved_parent_size and (saved_parent_size[0] <= 0 or saved_parent_size[1] <= 0):
            print("저장된 창 크기가 유효하지 않아 기본값으로 초기화합니다.")
            saved_parent_size = None

        self.overlay_saved_pos = saved_pos
        self.overlay_saved_size = saved_size
        self.overlay_saved_parent_size = saved_parent_size
        self.overlay_is_bottom_center = bool(settings.get('is_bottom_center', False))
        print(f"오버레이 설정을 로드했습니다. 위치={self.overlay_saved_pos}, 창크기={self.overlay_saved_parent_size}, 하단중앙={self.overlay_is_bottom_center}")

    def save_overlay_settings(self):
        """오버레이 설정을 파일에 저장합니다 (원자적으로 — 마지막에 쓴 창의 값이 남음). 쓰지 못하면 기록 + 창 한 번."""
        if hasattr(self, 'overlayFrame'):
            # 현재 실제 위치와 크기 가져오기
            current_pos = [self.overlayFrame.x(), self.overlayFrame.y()]
            current_size = [self.overlayFrame.width(), self.overlayFrame.height()]
            current_parent_size = [self.width(), self.height()]

            # 유효성 검사
            if current_parent_size[0] <= 0 or current_parent_size[1] <= 0:
                print("창 크기가 유효하지 않아 설정 저장을 건너뜁니다.")
                return

            # 하단 중앙 위치인지 확인 (더 정확한 감지)
            x_ratio = current_pos[0] / current_parent_size[0]
            y_ratio = current_pos[1] / current_parent_size[1]

            # 하단 중앙 판단 기준:
            # 1. Y 위치가 화면 하단 10% 이내
            # 2. X 위치가 화면 중앙에서 ±15% 이내
            # 3. 또는 저장된 하단 중앙 플래그가 True인 경우
            is_bottom_center = (
                (y_ratio >= 0.85 and abs(x_ratio - 0.5) < 0.15) or
                (hasattr(self, 'overlay_is_bottom_center') and self.overlay_is_bottom_center)
            )

            settings = {
                'position': current_pos,
                'size': current_size,
                'parent_size': current_parent_size,
                'is_bottom_center': is_bottom_center
            }
            try:
                user_files.write_json_atomic(self.overlay_settings_file, settings)
            except OSError as exc:
                traceback.print_exc()
                self._report_user_file_problem(
                    "overlay-write", "오버레이 설정을 저장하지 못함",
                    f"오버레이 컨트롤러의 위치를 저장하지 못했습니다 (파일은 그대로 둡니다):\n"
                    f"{self.overlay_settings_file}\n{type(exc).__name__}: {exc}")
                return

            # 메모리 변수도 업데이트
            self.overlay_saved_pos = current_pos
            self.overlay_saved_size = current_size
            self.overlay_saved_parent_size = current_parent_size
            self.overlay_is_bottom_center = is_bottom_center

            print(f"오버레이 설정 저장됨: 위치={current_pos}, 크기={current_size}, 창크기={current_parent_size}, 하단중앙={is_bottom_center}")

    def position_overlay_controls(self):
        print("position_overlay_controls() 호출됨")  # 디버깅
        # overlayFrame이 없으면 아무 동작도 하지 않음
        if hasattr(self, 'overlayFrame') and self.overlayFrame:
            print("overlayFrame 확인됨")  # 디버깅
            parent_size = self.size()
            overlay_size = self.overlayFrame.size()
            print(f"parent_size: {parent_size}, overlay_size: {overlay_size}")  # 디버깅
            
            # V 키 활성 상태에서 확대/축소 시 항상 하단 중앙으로 위치
            if hasattr(self, 'controls_visible') and not self.controls_visible:
                # V 키 활성 상태에서는 항상 하단 중앙으로 위치
                x = max(0, (parent_size.width() - overlay_size.width()) // 2)
                y = max(0, parent_size.height() - overlay_size.height() - 50)  # 하단에서 50px 위
                
                # 하단 중앙 위치임을 표시하는 플래그 설정
                self.overlay_is_bottom_center = True
                
                # 현재 위치와 윈도우 크기를 저장
                self.overlay_saved_pos = (x, y)
                self.overlay_saved_parent_size = (parent_size.width(), parent_size.height())
                
                print(f"V 키 활성 상태 - 하단 중앙으로 위치: ({x}, {y})")
            else:
                # V 키 비활성 상태에서는 기존 로직 사용
                # 저장된 설정이 있으면 사용, 없으면 기본 위치
                if hasattr(self, 'overlay_saved_pos') and self.overlay_saved_pos and self.overlay_saved_pos is not None:
                    print(f"저장된 위치 사용: {self.overlay_saved_pos}")  # 디버깅
                    saved_x, saved_y = self.overlay_saved_pos
                    
                    # 저장된 위치가 어떤 창 크기에서 설정되었는지 확인
                    if hasattr(self, 'overlay_saved_parent_size') and self.overlay_saved_parent_size:
                        saved_parent_width, saved_parent_height = self.overlay_saved_parent_size
                        
                        # 비율 계산 (0으로 나누기 방지)
                        if saved_parent_width > 0 and saved_parent_height > 0:
                            x_ratio = saved_x / saved_parent_width
                            y_ratio = saved_y / saved_parent_height
                            
                            # 하단 중앙 위치인지 확인 (저장된 플래그 또는 현재 위치 기반)
                            is_bottom_center = (
                                (hasattr(self, 'overlay_is_bottom_center') and self.overlay_is_bottom_center) or
                                (y_ratio >= 0.85 and abs(x_ratio - 0.5) < 0.15)
                            )
                            
                            if is_bottom_center:
                                # 하단 중앙 위치면 항상 하단 중앙으로 유지
                                x = max(0, (parent_size.width() - overlay_size.width()) // 2)
                                y = max(0, parent_size.height() - overlay_size.height() - 50)  # 하단에서 50px 위
                                print(f"하단 중앙 위치 감지, 하단 중앙으로 유지: ({x}, {y})")
                            else:
                                # 다른 위치면 비율에 맞게 조정
                                x = int(x_ratio * parent_size.width())
                                y = int(y_ratio * parent_size.height())
                                print(f"비율 기반 위치 조정: 저장된 비율=({x_ratio:.3f}, {y_ratio:.3f}), 새 위치=({x}, {y})")  # 디버깅
                        else:
                            # 저장된 창 크기가 유효하지 않으면 저장된 위치 그대로 사용
                            x, y = saved_x, saved_y
                            print(f"저장된 창 크기가 유효하지 않음, 저장된 위치 사용: ({x}, {y})")
                    else:
                        # 비율 정보가 없으면 저장된 위치 그대로 사용
                        x, y = saved_x, saved_y
                        print(f"비율 정보 없음, 저장된 위치 사용: ({x}, {y})")
                    
                    # 화면 경계 체크 완전 제거 - 비율에 맞는 정확한 위치 유지
                    # 오버레이가 화면 밖으로 나가도 비율은 정확히 유지
                else:
                    print("기본 위치 사용")  # 디버깅
                    # 기본 위치 (화면 하단 중앙)
                    x = max(0, (parent_size.width() - overlay_size.width()) // 2)
                    y = max(0, parent_size.height() - overlay_size.height() - 50)  # 하단에서 50px 위
            
            print(f"Positioning overlay at ({x}, {y}) - parent: {parent_size}, overlay: {overlay_size}")
            self.overlayFrame.move(x, y)
            print("overlayFrame.move() 완료")  # 디버깅
        else:
            print("overlayFrame not available for positioning")

    def show_overlay_controls(self):
        """오버레이 컨트롤을 표시합니다."""
        print("show_overlay_controls() 호출됨")  # 디버깅
        if hasattr(self, 'overlayFrame'):
            print(f"overlayFrame 존재: {self.overlayFrame}")  # 디버깅
            print(f"overlayFrame.isVisible(): {self.overlayFrame.isVisible()}")  # 디버깅
            
            # 위치를 먼저 조정 (표시 전에 위치 설정)
            print("위치 조정 시작")  # 디버깅
            self.position_overlay_controls()
            print("위치 조정 완료")  # 디버깅
            
            # 오버레이를 강제로 표시
            self.overlayFrame.setVisible(True)
            self.overlayFrame.raise_()  # 최상위로 올리기
            self.overlayFrame.show()  # 강제로 표시
            self.overlayFrame.repaint()  # 강제로 다시 그리기
            self.overlayFrame.update()  # 업데이트 강제 실행
            
            # 상태 업데이트
            self.update_overlay_controls()  # 오버레이 컨트롤 상태 업데이트
            
            # 타이머 중지 (V 키로 호출된 경우 계속 표시)
            self.overlay_timer.stop()
        else:
            print("overlayFrame이 존재하지 않음")  # 디버깅

    def hide_overlay_controls(self):
        """오버레이 컨트롤을 숨깁니다."""
        self.overlayFrame.setVisible(False)
        self.overlay_timer.stop()  # 타이머도 중지

    def update_overlay_controls(self):
        """오버레이 컨트롤의 상태를 동기화합니다."""
        if not self.cap_a:
            return
        # cv2 lazy import
        import cv2
        total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
        current_frame = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        if current_frame < 0:
            current_frame = 0
        
        # 오버레이 슬라이더 업데이트 (신호 차단으로 무한 루프 방지)
        self.overlaySlider.blockSignals(True)
        self.overlaySlider.setMaximum(max(1, total_frames - 1))
        self.overlaySlider.setValue(current_frame)
        self.overlaySlider.blockSignals(False)
        
        # 프레임 라벨들 업데이트
        if hasattr(self, 'overlayStartFrameLabel'):
            self.overlayStartFrameLabel.setText(f'{current_frame + 1}')
        if hasattr(self, 'overlayEndFrameLabel'):
            self.overlayEndFrameLabel.setText(f'{total_frames}')
        if hasattr(self, 'overlayCurrentFrameLabel'):
            self.overlayCurrentFrameLabel.setText(f'{current_frame + 1}')
        
        # 파일명 업데이트
        if hasattr(self, 'overlayFileNameLabel'):
            if self.filename_a:
                # 파일명에서 확장자 제거
                file_name = os.path.splitext(os.path.basename(self.filename_a))[0]
                
                # 파일명 길이에 따라 폰트 사이즈 동적 조정
                if len(file_name) <= 15:
                    font_size = 20
                elif len(file_name) <= 25:
                    font_size = 16
                elif len(file_name) <= 35:
                    font_size = 14
                elif len(file_name) <= 45:
                    font_size = 12
                else:
                    font_size = 10
                
                # 동적으로 스타일시트 업데이트
                self.overlayFileNameLabel.setStyleSheet(OVERLAY_FILE_NAME_LABEL_STYLE_TEMPLATE.format(font_size=font_size))
                
                self.overlayFileNameLabel.setText(file_name)
            else:
                self.overlayFileNameLabel.setText('No File')
        
        if self.timer.isActive():
            self.overlayPlayPause.setText('⏸')  # 재생 중일 때 일시정지 아이콘
        else:
            self.overlayPlayPause.setText('▶')  # 정지 상태일 때 재생 아이콘
        
        # 메인 컨트롤 패널의 재생 버튼도 동기화
        if hasattr(self, 'playPauseButton'):
            if self.timer.isActive():
                self.playPauseButton.setText('Pause')
                self.playPauseButton.setStyleSheet("background-color: yellow;")
            else:
                self.playPauseButton.setText('Play')
                self.playPauseButton.setStyleSheet("")
        
        self.overlayVolume.setValue(self.media_volume())  # 재생기가 없으면 정해 둔 볼륨 (만들지 않음)
    
    def on_overlay_mouse_enter(self):
        """오버레이 영역에 마우스가 들어올 때 호출됩니다."""
        # 컨트롤 패널이 표시되어 있으면 오버레이 이벤트 무시
        if self.controls_visible:
            return
        self.overlay_timer.stop()
    
    def on_overlay_mouse_leave(self):
        """오버레이 영역에서 마우스가 나갈 때 호출됩니다."""
        # 컨트롤 패널이 표시되어 있으면 오버레이 이벤트 무시
        if self.controls_visible:
            return
        # 마우스가 비디오 위젯 영역으로 이동하는지 확인
        cursor_pos = self.cursor().pos()
        video_rect = self.videoWidget.geometry()
        video_rect = self.mapToGlobal(video_rect.topLeft()), self.mapToGlobal(video_rect.bottomRight())
        video_rect = QRect(video_rect[0], video_rect[1])
        
        if not video_rect.contains(cursor_pos):
            self.hide_overlay_controls()
