"""Main window implementation for the YesonCheck application."""

import copy
import datetime
import json
import os
import re
import subprocess
import sys
import time
import traceback

# cv2는 lazy import로 변경 (실제 사용 시점에만 로드)
# import cv2
from PyQt5.QtCore import (
    QEvent,
    QRect,
    QSize,
    QTimer,
    Qt,
    pyqtSlot,
)
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtMultimedia import QMediaPlayer
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollBar,
    QShortcut,
    QSizePolicy,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from yesoncheck.video_widget import CustomVideoWidget
from yesoncheck import bookmarks, build_info, default_app, external_tools, file_associations, image_io, instance_link, \
    instances, paths, timing_log, user_files, video_list
from yesoncheck.main_window_styles import (
    BOOKMARK_BUTTON_STYLE,
    BOOKMARK_LIST_REFRESH_BUTTON_STYLE,
    DARK_STYLESHEET,
    FILENAME_LABEL_STYLE,
    FRAME_COUNT_LABEL_STYLE,
    LIGHT_STYLESHEET,
    LIST_MODE_BUTTON_STYLE,
    OCR_LOG_TEXT_STYLE,
    OCR_OPTION_LABEL_STYLE,
    OVERLAY_CURRENT_FRAME_LABEL_STYLE,
    OVERLAY_FILE_NAME_LABEL_STYLE,
    OVERLAY_FILE_NAME_LABEL_STYLE_TEMPLATE,
    OVERLAY_FRAME_NUMBER_LABEL_STYLE,
    OVERLAY_FRAME_STYLE,
    OVERLAY_HELP_LABEL_STYLE,
    OVERLAY_PLAY_PAUSE_STYLE,
    OVERLAY_SLIDER_STYLE,
    OVERLAY_VOLUME_STYLE,
    PLAYBACK_FPS_LABEL_STYLE,
    PLAY_PAUSE_BUTTON_STYLE,
    POSITION_SCROLL_INITIAL_STYLE,
    POSITION_SCROLL_STYLE,
    STOP_BUTTON_STYLE,
    THUMBNAIL_MODE_BUTTON_STYLE,
    TIME_LABEL_STYLE,
    TOTAL_FRAMES_LABEL_STYLE,
    VOLUME_SLIDER_STYLE,
    WORK_PATH_BUTTON_STYLE,
)
from yesoncheck.slider_style import jump_to_click
from yesoncheck.update_banner import UpdateBanner
from yesoncheck.user_files import UserFileError
from yesoncheck.window_layout import ElidedLabel, InfoRowLayout, VerticalScrollArea, startup_geometry
# 놓아 준 워커를 붙잡아 두는 코드는 worker_lifecycle에 있고, 기존 경로(`from yesoncheck.player_base import EXIT_WAIT_S, release_worker,
# wait_for_released_workers`)를 위해 여기서 다시 내보냄. _RELEASED_WORKERS는 읽는 쪽(시험)용 같은 dict 객체 — 바꿔치기하려면
# worker_lifecycle에서 할 것 (이 모듈의 이름을 바꿔도 release_worker는 worker_lifecycle의 것을 씀)
from yesoncheck.worker_lifecycle import EXIT_WAIT_S, _RELEASED_WORKERS, release_worker, wait_for_released_workers
# 무거운 모듈들은 lazy import로 변경 (실제 사용 시점에만 로드)
# from yesoncheck.workers import OCRWorker, OCRExportWorker, SceneDetectWorker
# from yesoncheck.player_timeline import CollapsibleBox
# from yesoncheck.player_review import OCRReviewDialog


def _transnetv2_available():
    """TransNetV2(딥러닝 씬 감지, 애니매틱2)를 이 빌드/환경에서 쓸 수 있는지 (TensorFlow와 가중치가 있는지).

    transnetv2_detector는 cv2/numpy를 불러오므로 lazy import로 확인한다. TensorFlow는 불러오지 않는다
    (find_spec과 가중치 파일 존재만 확인 — 시작이 느려지지 않게. TF는 애니매틱2 감지를 시작할 때 불러옴).
    여기서 ImportError를 잡지 않는다 — transnetv2_detector 자체가 깨졌다면 그대로 드러나야 한다(조용히 '없음'으로 숨기지 않음).
    """
    from yesoncheck.transnetv2_detector import TRANSNETV2_AVAILABLE
    return TRANSNETV2_AVAILABLE


def _transnetv2_missing():
    """애니매틱2에 필요한데 이 빌드/환경에 없는 것 (숨길 때 로그에 남기는 이유)."""
    from yesoncheck.transnetv2_detector import transnetv2_missing
    return transnetv2_missing()


def korean_date(day):
    """'2026년 10월 20일'. strftime에 한글 형식을 넘기지 않음 — Windows의 strftime은 형식 문자열을 시스템 locale
    인코딩으로 바꾸므로 한글을 쓸 수 없는 locale(영어 Windows 등)에서는 UnicodeEncodeError로 창이 열리지 않음."""
    return f"{day.year}년 {day.month:02d}월 {day.day:02d}일"


def stored_and_native_path(stored_path, native_path):
    """파일에 적힌 영상 경로와 이 PC에서 연 경로를 메시지용으로. 둘이 같으면(Mac) 한 줄 그대로 (스펙 2-4)."""
    if stored_path == native_path:
        return native_path
    return f"저장된 경로: {stored_path}\n이 PC 경로: {native_path}"


class VideoPlayerBase(QMainWindow):
    # 창을 닫을 때 실행 중인 공유 설정 불러오기를 기다리는 최대 시간 (그 뒤에는 로그만 남기고 닫음)
    SHARED_CONFIG_CLOSE_WAIT_MS = 5000
    # 창을 닫을 때 실행 중인 분석·내보내기·병합을 기다리는 최대 시간 (그 뒤에는 끝날 때까지 붙잡아 둠)
    JOB_CLOSE_WAIT_MS = 10000

    def __init__(self, ffmpeg_path=None, load_shared_config=True):
        """load_shared_config=False: 공유 설정(NAS)을 읽지 않고 빈 '불러오는 중' 상태로 만듦 — 창을 보인 뒤
        start_shared_config_load()로 백그라운드에서 읽음 (app.launch). 기본값은 예전처럼 여기서 바로 읽음."""
        super().__init__()
        # 사용자 파일(북마크·오버레이·내보내기 폴더 설정)을 읽다 난 문제: 창이 보이기 전(시작)에는 모아 두었다가
        # show_user_file_problems가 알림 (스플래시에 가리지 않게), 그 뒤에는 바로. 같은 문제는 창 세션에 한 번만
        self._user_file_problems = []  # 알릴 (제목, 글) — None이면 창이 보이는 중
        self._user_file_problem_keys = set()
        # 소리 재생기(QMediaPlayer)는 처음 쓸 때 만듦 (mediaPlayer 속성) — Windows에서 처음 만들 때 8초쯤 걸림
        self._media_player = None
        self._media_volume = 100  # 재생기를 만들기 전에 정한 볼륨 (QMediaPlayer 기본값과 같음)
        self.media_player_create_seconds = None  # 재생기를 만드는 데 걸린 초 (만든 뒤에 채움)
        self._shared_config_load = None  # 실행 중인 공유 설정 불러오기 (SharedConfigLoad)
        self._shared_config_closed = False  # 창이 닫힘 → 늦게 온 공유 설정 결과는 버림
        # job 목록 정렬의 locale (이름 순서): 시작할 때 GUI 스레드에서 한 번 — 목록 다시 읽기 스레드의 정렬은 locale을 바꾸지 않음
        video_list.set_sort_locale()
        self.setWindowTitle(build_info.title_base())
        self.setGeometry(100, 100, 1080, 720)

        # 메뉴바 생성 (GPU 확인 포함 — 드라이버에 따라 느릴 수 있음)
        timing_log.startup("창: 메뉴 만드는 중…")
        started = time.perf_counter()
        self.create_menu_bar()
        timing_log.startup(f"창: 메뉴 만듦 ({timing_log.since(started)})")

        # 북마크 관련 초기화
        self.bookmarks = []
        self.bookmarks_file = bookmarks.default_path()
        self.load_bookmarks()

        # 작품 경로: 공유 설정 폴더의 work_paths.json (문제는 창 표시 후 resolve_shared_config_problem이 알림)
        if load_shared_config:
            self.shared_config_loading = False
            timing_log.startup("창: 공유 설정 읽는 중…")
            started = time.perf_counter()
            self.setup_shared_config()
            timing_log.startup(f"창: 공유 설정 읽음 ({timing_log.since(started)})")
        else:
            self.set_shared_config_loading_state()

        # 4K 성능 최적화를 위한 캐싱 시스템 추가
        self.frame_cache = {}
        self.cache_size = 50  # 캐시 크기 (메모리 사용량 조절)
        self.cache_hits = 0
        self.cache_misses = 0
        
        # 성능 최적화 설정
        self.performance_mode = 'auto'  # 'auto', 'speed', 'quality'
        self.skip_frame_processing = False  # 초고속 모드
        self.preview_mode = False  # 드래그 중 프리뷰 모드
        self.frame_skip_threshold = 5  # 프레임 스킵 임계값
        
        # 드래그 최적화를 위한 변수들
        self.last_drag_update = 0
        self.drag_update_interval = 30  # 30ms로 단축 (33fps)
        self.is_dragging = False
        
        # 고급스러운 메인 윈도우 스타일 적용
        self.setStyleSheet(DARK_STYLESHEET)
        
        self.controls_visible = True  # initUI() 호출 전에 먼저 정의

        timing_log.startup("창: 화면 구성 중…")
        started = time.perf_counter()
        self.initUI()
        timing_log.startup(f"창: 화면 구성 끝 ({timing_log.since(started)})")
        # 업데이트 확인 상태·3시간 타이머·알림 띠 버튼 (확인은 공유 설정을 불러온 뒤 시작 — PlayerUpdateMixin)
        self.setup_updates()

        self.loopEnabled = False
        self.filename_a = ""
        self.filename_b = ""
        self.cap_a = None
        self.cap_b = None
        self.frame_a = None
        self.frame_b = None

        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(True)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame_playback)
        self.videoWidget.fitToWindowChanged.connect(self.on_fit_to_window_changed)
        

        
        # 오버레이 컨트롤 생성
        self.create_overlay_controls()
        
        # 오버레이 타이머 초기화
        self.overlay_timer = QTimer(self)
        self.overlay_timer.setSingleShot(True)
        self.overlay_timer.timeout.connect(self.hide_overlay_controls)
        
        # videoWidget에 eventFilter 설치
        self.videoWidget.installEventFilter(self)
        
        self.playlist = []
        self.current_playlist_index = -1
        self.is_playlist_playing = False
        self._playlist_played_any = False  # 이번 선택 재생에서 연 영상이 있음 (없으면 끝날 때 보던 영상을 멈추지 않음)
        self._playlist_resolving = False  # 선택 재생이 다음 영상을 정하는 중 (그동안 영상이 끝나도 또 진행하지 않음)
        self.current_item = None
        self.use_gpu = False
        self.gpu_backend = None
        self.workComboBox.currentIndexChanged.connect(self.update_season_list)
        self.seasonComboBox.currentIndexChanged.connect(self.update_job_list)
        self.jobComboBox.currentIndexChanged.connect(self.update_playlist)
        # 같은 job을 다시 골라도 목록을 다시 읽음 (activated는 골랐을 때마다, currentIndexChanged는 job이 바뀔 때만).
        # 다른 job을 고르면 update_playlist가 읽은 (작품, 시즌, job)을 기억해 activated는 다시 읽지 않음 (한 번만 읽음)
        self._job_list_loaded_for = None
        self.jobComboBox.activated.connect(self._on_job_activated)

        self.installEventFilter(self)

        self.show_overlay = False
        self.isFullScreen = False
        
        # 처음 창 크기: 예전처럼 1080×720 이상, 레이아웃이 원하는 크기까지, 화면 작업 영역 안으로 (+ initial_geometry).
        # 예전에는 최소 크기가 이 역할을 해서 화면보다 커질 수 있었음 — 이제 줄일 수도 있음.
        self._startup_geometry_checked = False
        self.apply_startup_geometry()
        
        # 윈도우 포커스 설정 (빌드된 앱에서 키 이벤트 처리를 위해)
        self.activateWindow()
        
        # 재생 FPS 측정을 위한 변수들 초기화
        self.playback_fps_counter = 0
        self.playback_fps_timer = QTimer()
        self.playback_fps_timer.timeout.connect(self.update_playback_fps)
        self.playback_fps_timer.start(1000)  # 1초마다 FPS 업데이트
        self.last_fps_update_time = time.time()
        
        # 썸네일 관련 변수들 초기화
        
        self.thumbnail_size = 120
        self.is_thumbnail_mode = False
        self.thumbnail_workers = []  # 여러 워커를 관리
        
        
        # 디스크 기반 썸네일 시스템
        self.current_thumbnail_folder = None  # 현재 job의 썸네일 폴더
        self._thumbnail_problems_shown = set()  # 이번 실행에서 썸네일 문제 창을 띄운 (폴더, 창 제목) — 그 짝마다 한 번
        # 썸네일 폴더를 만들지 못한 문제 (폴더, 창 제목, 내용): 그동안 썸네일은 화면에만, 창은 썸네일을 쓸 때
        self._thumbnail_folder_problem = None
        self.thumbnail_loader_worker = None  # 백그라운드 로더 워커
        self.thumbnail_loading_timer = QTimer()
        self.thumbnail_loading_timer.setSingleShot(True)
        self.thumbnail_loading_timer.timeout.connect(self.start_background_thumbnail_loading)
        
        # 사이드바 폭 관리 변수
        self.default_sidebar_width = None  # 기본 사이드바 폭 (나중에 설정)

        # OCR / ROI 상태
        self.ocr_roi = None
        self.ocr_tracking_enabled = False
        self.ocr_worker = None
        self.ocr_progress_dialog = None
        self.ocr_review_dialog = None
        self.ocr_status_message = ""
        self.last_ocr_segments = []
        self._ocr_results_unsaved = False  # 'OCR 저장'을 누르지 않은 결과가 있음 (업데이트 확인 창용)
        self.ocr_cancelled = False
        self.pending_ocr_metadata = None
        self.ocr_export_worker = None
        self.ocr_export_progress_dialog = None

    @property
    def mediaPlayer(self):
        """소리 재생기. 처음 쓸 때 만든다 (Windows에서 QMediaPlayer를 처음 만들면 수 초가 걸려 시작할 때는 만들지 않음).

        소리를 실제로 여는 곳(open_file의 setMedia)에서만 쓴다. 정지·위치·상태처럼 이미 있는 재생기만 다루면 되는
        곳은 _media_player(없으면 None)를 본다 — 소리를 연 적이 없으면 할 일이 없음.
        """
        if self._media_player is None:
            timing_log.log("소리", "재생기 만드는 중…")
            started = time.perf_counter()
            QApplication.setOverrideCursor(Qt.WaitCursor)  # Windows에서 처음 만들면 수 초 — 멈춘 것처럼 보이지 않게
            try:
                player = QMediaPlayer(self)
                player.setVolume(self._media_volume)
            finally:
                QApplication.restoreOverrideCursor()
            self._media_player = player
            self.media_player_create_seconds = time.perf_counter() - started
            timing_log.log("소리", f"재생기 준비 ({timing_log.since(started)})")
        return self._media_player

    def media_volume(self):
        """지금 볼륨: 재생기가 있으면 그 값, 없으면 정해 둔 값 (재생기를 만들지 않음)."""
        if self._media_player is not None:
            return self._media_player.volume()
        return self._media_volume

    def stop_media_player(self):
        """소리 정지. 재생기를 아직 만들지 않았으면(소리를 연 적이 없음) 할 일이 없음."""
        if self._media_player is not None:
            self._media_player.stop()

    def set_media_position(self, position_ms):
        """소리 위치 맞추기. 재생기가 없으면(소리를 연 적이 없음) 할 일이 없음."""
        if self._media_player is not None:
            self._media_player.setPosition(position_ms)

    def initUI(self):
        self.current_theme = 'dark'  # 기본 테마
        self.videoWidget = CustomVideoWidget(self)
        self.videoWidget.wipePositionChanged.connect(self.update_frame)
        self.videoWidget.roiSelectionFinished.connect(self.on_roi_selected)
        self.init_annotation_system()

        self.gpuComboBox = QComboBox()
        self.gpuComboBox.addItem("CPU")
        # cv2 lazy import (GPU 옵션 확인용)
        import cv2
        if cv2.cuda.getCudaEnabledDeviceCount() > 0:
            self.gpuComboBox.addItem("NVIDIA (CUDA)")
        if cv2.ocl.haveOpenCL():
            self.gpuComboBox.addItem("AMD (OpenCL)")
        self.gpuComboBox.currentIndexChanged.connect(self.change_gpu_backend)

        # 4K 성능 최적화 모드 선택 추가
        performanceLabel = QLabel("4K 성능 모드:")
        self.performanceComboBox = QComboBox()
        self.performanceComboBox.addItem("자동 (Auto)")
        self.performanceComboBox.addItem("속도 우선 (Speed)")
        self.performanceComboBox.addItem("극한 속도 (Ultra)")
        self.performanceComboBox.addItem("품질 우선 (Quality)")
        self.performanceComboBox.currentIndexChanged.connect(self.change_performance_mode)

        workLabel = QLabel("Yeson 작품")
        workLabel.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.workComboBox = QComboBox()
        self.workComboBox.addItem(self._first_work_item())  # 불러오는 동안은 "공유 설정 불러오는 중…"
        # JSON에서 작품 목록 로드
        for work_name in sorted(self.work_paths.keys()):
            self.workComboBox.addItem(work_name)
        self._update_shared_config_title()
        self.seasonComboBox = QComboBox()
        self.seasonComboBox.addItem("시즌선택")
        self.jobComboBox = QComboBox()
        self.jobComboBox.addItem("job선택")

        openButtonA = QPushButton('Open Video A')
        openButtonA.clicked.connect(lambda: self.open_file('A'))
        openButtonB = QPushButton('Open Video B')
        openButtonB.clicked.connect(lambda: self.open_file('B'))

        self.ocrSelectRoiButton = QPushButton('OCR ROI 지정')
        self.ocrSelectRoiButton.setCheckable(True)
        self.ocrSelectRoiButton.toggled.connect(self.toggle_ocr_roi_selection)
        self.ocrSelectRoiButton.setToolTip('영상에서 OCR 분석에 사용할 영역을 드래그하여 지정합니다.')

        self.ocrClearRoiButton = QPushButton('ROI 초기화')
        self.ocrClearRoiButton.clicked.connect(self.clear_ocr_roi)
        self.ocrClearRoiButton.setEnabled(False)

        self.ocrTrackingCheckBox = QCheckBox('ROI 트래킹 활성화')
        self.ocrTrackingCheckBox.setToolTip('활성화하면 지정한 ROI 영역이 동영상에서 이동하는 텍스트를 자동으로 추적합니다.')
        self.ocrTrackingCheckBox.setEnabled(False)

        # OCR 분석 방식 선택
        ocr_mode_layout = QHBoxLayout()
        ocr_mode_label = QLabel('OCR 분석 방식:')
        self.ocrModeComboBox = QComboBox()
        self.ocrModeComboBox.addItem('Titmouse', 'titmouse')
        self.ocrModeComboBox.addItem('King', 'king')
        self.ocrModeComboBox.addItem('Bento', 'bento')
        self.ocrModeComboBox.addItem('All (사용자 패턴)', 'all')
        self.ocrModeComboBox.addItem('애니매틱 (Auto Cut)', 'animatic')
        ocr_mode_tooltip = (
            '이미지에 따라 분석 정확도가 다를 수 있으므로 적합한 방식을 선택하세요.\n'
            '- Titmouse: 기본 OCR 설정\n'
            '- King: 빨간색 텍스트 인식 최적화\n'
            '- Bento: 작은 텍스트 및 특수 패턴 인식 최적화 (예: Seq 02A_S09 - Panel 6)\n'
            '- All: 사용자 정의 패턴으로 텍스트 인식 (#=영문, W=숫자, 예: "### WW#_#WW - #### W")\n'
            '- 애니매틱: PySceneDetect를 사용한 자동 컷 감지 (ROI 불필요)'
        )
        # 애니매틱2(TransNetV2)는 선택적 의존성 — 설치되지 않은 빌드/환경에서는 목록에 보이지 않음
        # (선택해도 분석이 되지 않는 개발자용 pip 안내 오류를 사용자가 보지 않도록)
        if _transnetv2_available():
            self.ocrModeComboBox.addItem('애니매틱2 (TransNetV2)', 'animatic2')
            ocr_mode_tooltip += (
                '\n- 애니매틱2: TransNetV2(딥러닝)를 사용한 컷 감지 (디졸브/페이드 감지 향상, ROI 불필요)'
            )
        else:
            # 조용히 숨기지 않음: 왜 없는지(TensorFlow·가중치·CPU AVX) 시작 로그에 남김
            timing_log.startup(f"애니매틱2(TransNetV2) 항목 숨김 — 이 빌드/환경에 없는 것: {_transnetv2_missing()}")
        self.ocrModeComboBox.setToolTip(ocr_mode_tooltip)
        self.ocrModeComboBox.currentIndexChanged.connect(self.on_ocr_mode_changed)
        ocr_mode_layout.addWidget(ocr_mode_label)
        ocr_mode_layout.addWidget(self.ocrModeComboBox)
        
        # All 모드용 패턴 입력 필드
        self.ocrPatternLabel = QLabel('패턴:')
        self.ocrPatternLineEdit = QLineEdit()
        self.ocrPatternLineEdit.setPlaceholderText('예: ### WW#_#WW - #### W (#=영문, W=숫자)')
        self.ocrPatternLineEdit.setToolTip(
            'All 모드에서 사용할 텍스트 패턴을 입력하세요.\n'
            '- # = 영문 (A-Z, a-z)\n'
            '- W = 숫자 (0-9)\n'
            '- _ = 언더바\n'
            '- - = 하이픈\n'
            '- 공백 = 공백\n'
            '예시:\n'
            '- "seq 04A_S05 - Panel 1" → "### WW#_#WW - #### W"\n'
            '- "MS101_B010" → "##WWW_#WWW"'
        )
        self.ocrPatternLabel.setVisible(False)
        self.ocrPatternLineEdit.setVisible(False)
        ocr_mode_layout.addWidget(self.ocrPatternLabel)
        ocr_mode_layout.addWidget(self.ocrPatternLineEdit)
        
        ocr_mode_widget = QWidget()
        ocr_mode_widget.setLayout(ocr_mode_layout)

        self.ocrAnalyzeButton = QPushButton('OCR 구간 추출')
        self.ocrAnalyzeButton.clicked.connect(self.run_ocr_analysis)
        self.ocrAnalyzeButton.setEnabled(False)
        
        self.ocrAnalyzeRangeButton = QPushButton('선택 구간 분석')
        self.ocrAnalyzeRangeButton.clicked.connect(self.run_ocr_analysis_range)
        self.ocrAnalyzeRangeButton.setEnabled(False)
        self.ocrAnalyzeRangeButton.setToolTip('지정한 프레임 범위만 OCR 분석합니다. 결과는 기존 분석 결과에 병합됩니다.')
        
        self.ocrReopenResultButton = QPushButton('OCR 오픈')
        self.ocrReopenResultButton.clicked.connect(self.reopen_ocr_result)
        self.ocrReopenResultButton.setEnabled(False)
        self.ocrReopenResultButton.setToolTip('이전에 분석한 OCR 결과를 다시 엽니다 (분석한 내용과 수정한 내용이 모두 표시됩니다)')
        
        self.ocrSaveResultButton = QPushButton('OCR 저장')
        self.ocrSaveResultButton.clicked.connect(self.save_ocr_result)
        self.ocrSaveResultButton.setEnabled(False)
        self.ocrSaveResultButton.setToolTip('현재 OCR 분석 결과를 파일로 저장합니다')
        
        self.ocrLoadResultButton = QPushButton('OCR 로드')
        self.ocrLoadResultButton.clicked.connect(self.load_ocr_result)
        self.ocrLoadResultButton.setEnabled(True)
        self.ocrLoadResultButton.setToolTip('저장된 OCR 분석 결과를 불러옵니다')

# ocrStatusLabel 삭제됨 - 로그는 OCR 분석 팝업창에 표시
        self.fullscreenButton = QPushButton('Full screen')
        self.fullscreenButton.clicked.connect(self.toggle_fullscreen)
        helpButton = QPushButton('Help')
        helpButton.clicked.connect(self.show_help)
        self.loopCheckBox = QCheckBox("Loop Play")
        self.loopCheckBox.setToolTip('Enable loop playback')
        self.loopCheckBox.stateChanged.connect(self.toggle_loop_play)
        self.playPauseButton = QPushButton('Play')
        self.playPauseButton.clicked.connect(self.toggle_play_pause)
        self.playPauseButton.setFixedHeight(80)
        self.playPauseButton.setMinimumHeight(80)
        self.playPauseButton.setMaximumHeight(80)
        self.playPauseButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.playPauseButton.setStyleSheet(PLAY_PAUSE_BUTTON_STYLE)
        stopButton = QPushButton('Stop')
        stopButton.clicked.connect(self.stop_video)
        stopButton.setFixedHeight(80)
        stopButton.setMinimumHeight(80)
        stopButton.setMaximumHeight(80)
        stopButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        stopButton.setStyleSheet(STOP_BUTTON_STYLE)
        # 정보 줄 라벨 (예전 고정 너비 200·200·150이 창의 최소 너비를 묶었음). 너비는 글꼴로, 최소 너비는 라벨이 실제로
        # 그리는 방법 그대로 잼 (플랫폼·테마마다 글꼴이 다름). 자리가 있으면 예전과 같은 너비(글자가 더 넓은 글꼴이면
        # 글자 너비, 숫자가 바뀌어도 그대로). 모자라면 InfoRowLayout이 이 순서로 줄임 (줄여 그려지면 전체 글자는 툴팁,
        # 좁으면 글자가 안쪽 여백까지 씀):
        #   숫자 라벨의 빈 공간 → 파일 이름(가운데를 줄여 'A: H….mov'까지) → 재생 FPS('…'까지) →
        #   시간('00:00:00.000 / …'까지) → Total의 '(…F …f)'('Total: 00000…'까지)
        #   → 그래도 모자랄 때만(창이 최소 너비 근처) 칸을 접음: 재생 FPS → 파일 이름 → 시간.
        # 프레임 숫자는 창이 최소 너비여도 언제나 다 보임 (Current 전부, Total은 'Total: 00000'까지).
        self.filenameLabel = ElidedLabel(Qt.ElideMiddle, keep_ends=(4, 4), shrink_order=1, collapse_order=7,
                                         full_text_tooltip=True)
        self.labelFrameCount = ElidedLabel(Qt.ElideRight, keep_text="Current: 00000", hint_width=200,
                                           fit_text="Current: 00000", shrink_order=4)
        self.labelTotalFrames = ElidedLabel(Qt.ElideRight, keep_text="Total: 00000 (000F 00f)",
                                            keep_prefix="Total: 00000", hint_width=200,
                                            fit_text="Total: 00000 (000F 00f)", shrink_order=4)
        self.labelPlaybackFPS = ElidedLabel(Qt.ElideRight, keep_text="재생: 00.000 FPS", keep_prefix="",
                                            hint_width=150, fit_text="재생: 00.000 FPS", shrink_order=2,
                                            collapse_order=6)  # 재생 FPS 표시 위젯 추가
        font = QFont(); font.setPointSize(16)
        self.filenameLabel.setFont(font)
        self.labelFrameCount.setFont(font)
        self.labelTotalFrames.setFont(font)
        self.labelPlaybackFPS.setFont(font)  # FPS 위젯에도 폰트 적용
        self.filenameLabel.setStyleSheet(FILENAME_LABEL_STYLE)
        self.labelFrameCount.setStyleSheet(FRAME_COUNT_LABEL_STYLE)
        self.labelTotalFrames.setStyleSheet(TOTAL_FRAMES_LABEL_STYLE)
        self.labelPlaybackFPS.setStyleSheet(PLAYBACK_FPS_LABEL_STYLE)
        # FPS 위젯 초기 텍스트 설정
        self.labelPlaybackFPS.setText('재생: 대기')
        
        self.positionScroll = QSlider(Qt.Horizontal)
        self.positionScroll.setMinimum(0)
        self.positionScroll.setMaximum(100)
        self.positionScroll.setSingleStep(1)
        self.positionScroll.setPageStep(1)
        self.positionScroll.setStyleSheet(POSITION_SCROLL_INITIAL_STYLE)
        self.positionScroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.positionScroll.setMinimumSize(100, 20)
        self.positionScroll.setToolTip('Position')
        self.positionScroll.valueChanged.connect(self.on_slider_value_changed)  # 드래그 완료 시
        self.positionScroll.sliderMoved.connect(self.on_slider_moved)  # 드래그 중 실시간 업데이트
        self.positionScroll.sliderReleased.connect(self.sync_audio_on_release)
        
        self.frameRateLabel = QLabel("FPS")
        self.frameRateComboBox = QComboBox()
        self.frameRateComboBox.setToolTip('Frame rate (frames per second)')
        self.frameRateComboBox.setEditable(True)  # 직접 입력 가능하게
        # 일반적인 비표준 FPS 값들 추가 (23.976, 29.97, 59.94)
        common_fps = ["23.976", "29.97", "59.94"]
        # 정수 FPS (1-60)
        integer_fps = [str(i) for i in range(1, 61)]
        # 중복 제거하고 정렬
        all_fps = sorted(set(common_fps + integer_fps), key=lambda x: float(x) if x.replace('.', '').isdigit() else 999)
        self.frameRateComboBox.addItems(all_fps)
        self.frameRateComboBox.setCurrentText('24')
        self.wipeCheckBox = QCheckBox('Enable Wipe Effect')
        self.wipeCheckBox.setChecked(False)
        self.wipeCheckBox.stateChanged.connect(self.toggle_wipe_effect)
        self.wipeXButton = QPushButton('X-Axis Wipe'); self.wipeXButton.setCheckable(True)
        self.wipeXButton.toggled.connect(self.toggle_wipe_x)
        self.wipeYButton = QPushButton('Y-Axis Wipe'); self.wipeYButton.setCheckable(True)
        self.wipeYButton.toggled.connect(self.toggle_wipe_y)
        self.wipeXButton.setEnabled(False)
        self.wipeYButton.setEnabled(False)

        # 볼륨 슬라이더 (QSlider로 변경)
        self.volumeSlider = QSlider(Qt.Horizontal)
        self.volumeSlider.setRange(0, 100)
        self.volumeSlider.setValue(50)
        self.volumeSlider.setMinimumWidth(100)  # 자리가 있으면 예전처럼 150, 가운데 열이 좁으면 100까지
        self.volumeSlider.setMaximumWidth(150)
        self.volumeSlider.setToolTip("오디오 볼륨")
        self.volumeSlider.valueChanged.connect(self.setVolume)
        self.volumeSlider.setStyleSheet(VOLUME_SLIDER_STYLE)

        volumeLabel = QLabel("🔊 Volume:")
        volumeLabel.setStyleSheet("QLabel { font-weight: bold; }")

        # 볼륨 퍼센트 레이블
        self.volumePercentLabel = QLabel("50%")
        self.volumePercentLabel.setStyleSheet("QLabel { color: #ffae00; font-weight: bold; min-width: 40px; }")
        self.playSelectedButton = QPushButton('Play Selected')
        self.playSelectedButton.clicked.connect(self.play_selected_files)
        self.playSelectedButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.playSelectedPauseButton = QPushButton('Play/Pause Selected')
        self.playSelectedPauseButton.clicked.connect(self.toggle_play_pause_selected)
        self.playSelectedPauseButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.gpuLabel = QLabel("GPU Acceleration:")
        
        # OCR 기능을 접을 수 있는 그룹박스로 구성 (기본 접힌 상태)
        # 1. ROI 설정 그룹 (lazy import)
        from yesoncheck.player_timeline import CollapsibleBox
        roi_group = CollapsibleBox("▶ ROI 설정")
        roi_group.toggle_button.setChecked(False)  # 접힌 상태로 시작
        roi_group.content_area.setVisible(False)
        
        # 버튼 최소 너비 설정
        self.ocrSelectRoiButton.setMinimumWidth(140)
        self.ocrClearRoiButton.setMinimumWidth(140)
        
        roi_group.add_widget(self.ocrSelectRoiButton)
        roi_group.add_widget(self.ocrClearRoiButton)
        roi_group.add_widget(self.ocrTrackingCheckBox)
        
        # 2. OCR 분석 그룹
        analysis_group = CollapsibleBox("▶ OCR 분석")
        analysis_group.toggle_button.setChecked(False)  # 접힌 상태로 시작
        analysis_group.content_area.setVisible(False)
        
        # OCR 분석 방식을 별도로 추가하여 가독성 향상
        ocr_mode_label_widget = QLabel('OCR 분석 방식:')
        ocr_mode_label_widget.setStyleSheet(OCR_OPTION_LABEL_STYLE)
        analysis_group.add_widget(ocr_mode_label_widget)
        
        # 콤보박스 크기 정책 설정
        self.ocrModeComboBox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.ocrModeComboBox.setMinimumWidth(140)
        analysis_group.add_widget(self.ocrModeComboBox)
        
        # All 모드용 패턴 입력 필드 (별도 줄에 배치)
        self.ocrPatternLabel.setStyleSheet(OCR_OPTION_LABEL_STYLE)
        self.ocrPatternLineEdit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.ocrPatternLineEdit.setMinimumWidth(140)
        analysis_group.add_widget(self.ocrPatternLabel)
        analysis_group.add_widget(self.ocrPatternLineEdit)
        
        # 버튼 최소 너비 설정
        self.ocrAnalyzeButton.setMinimumWidth(140)
        self.ocrAnalyzeRangeButton.setMinimumWidth(140)
        analysis_group.add_widget(self.ocrAnalyzeButton)
        analysis_group.add_widget(self.ocrAnalyzeRangeButton)
        
        # 3. 결과 관리 그룹
        result_group = CollapsibleBox("▶ 결과 관리")
        result_group.toggle_button.setChecked(False)  # 접힌 상태로 시작
        result_group.content_area.setVisible(False)
        
        # 버튼 최소 너비 설정
        self.ocrReopenResultButton.setMinimumWidth(140)
        self.ocrSaveResultButton.setMinimumWidth(140)
        self.ocrLoadResultButton.setMinimumWidth(140)
        
        result_group.add_widget(self.ocrReopenResultButton)
        result_group.add_widget(self.ocrSaveResultButton)
        result_group.add_widget(self.ocrLoadResultButton)

        annotation_group = self.build_annotation_group()
        
        controlLayoutMiddle = QVBoxLayout()
        # 테마전환, Previous Frame, Next Frame 버튼은 UI에서 제거 (기능은 유지)
        controlLayoutMiddle.addWidget(openButtonA); controlLayoutMiddle.addWidget(openButtonB)
        
        # OCR 그룹박스 추가 (기본 접힌 상태)
        controlLayoutMiddle.addWidget(roi_group)
        controlLayoutMiddle.addWidget(analysis_group)
        controlLayoutMiddle.addWidget(result_group)
        controlLayoutMiddle.addWidget(annotation_group)
        # ocrStatusLabel 삭제됨 - 로그는 OCR 분석 팝업창에 표시
        
        # Full Screen과 Help 버튼은 UI에서 제거 (Full Screen 기능은 유지, Help는 메뉴바로 이동)
        controlLayoutMiddle.addWidget(self.loopCheckBox)
        controlLayoutMiddle.addWidget(volumeLabel); controlLayoutMiddle.addWidget(self.volumeSlider); controlLayoutMiddle.addWidget(self.volumePercentLabel)
        controlLayoutMiddle.addWidget(self.frameRateLabel); controlLayoutMiddle.addWidget(self.frameRateComboBox)
        controlLayoutMiddle.addWidget(self.wipeCheckBox); controlLayoutMiddle.addWidget(self.wipeXButton)
        controlLayoutMiddle.addWidget(self.wipeYButton); controlLayoutMiddle.addWidget(self.playSelectedButton)
        controlLayoutMiddle.addWidget(self.playSelectedPauseButton)
        # GPU Acceleration과 4K 성능 모드는 UI에서 제거 (메뉴바로 이동)
        controlLayoutMiddle.addWidget(workLabel); controlLayoutMiddle.addWidget(self.workComboBox)
        controlLayoutMiddle.addWidget(self.seasonComboBox); controlLayoutMiddle.addWidget(self.jobComboBox)
        controlLayoutMiddle.setContentsMargins(0,0,0,0)
        controlLayoutMiddle.setSpacing(5)
        
        controlLayoutRight = QVBoxLayout()
        controlLayoutRight.addWidget(self.positionScroll)
        controlLayoutRight.addWidget(self.playPauseButton, 0)  # stretch factor 0으로 고정
        controlLayoutRight.addWidget(stopButton, 0)  # stretch factor 0으로 고정
        controlLayoutRight.setContentsMargins(0,0,0,0)
        controlLayoutRight.setSpacing(5)
        
        fileInfoLayout = InfoRowLayout()  # 예전 QHBoxLayout + addStretch와 같은 배치 (시간 라벨은 오른쪽 끝)
        fileInfoLayout.addWidget(self.filenameLabel); fileInfoLayout.addWidget(self.labelFrameCount)
        fileInfoLayout.addWidget(self.labelTotalFrames); fileInfoLayout.addWidget(self.labelPlaybackFPS)
        fileInfoLayout.setContentsMargins(0,0,0,0); fileInfoLayout.setSpacing(5)
        splitter = QSplitter(Qt.Vertical); videoWidgetContainer = QWidget()
        videoWidgetLayout = QVBoxLayout(); videoWidgetLayout.addWidget(self.videoWidget)
        videoWidgetContainer.setLayout(videoWidgetLayout); videoWidgetLayout.setContentsMargins(0,0,0,0)
        videoWidgetLayout.setSpacing(0); fileInfoWidget = QWidget(); fileInfoWidget.setLayout(fileInfoLayout)
        splitter.addWidget(videoWidgetContainer); splitter.addWidget(fileInfoWidget); splitter.setSizes([700, 50])
        self.sidebar = QListWidget(); self.sidebar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.sidebar.setSelectionMode(QListWidget.ExtendedSelection)
        self.sidebar.itemClicked.connect(self.on_sidebar_item_clicked)
        # 목록을 비울 때(job 바꿈·폴더 불러오기·끌어다 놓기 — clear()는 모델을 초기화함)마다 1씩: 이벤트를 처리하며 썸네일을
        # 만드는 반복은 이 값이 바뀌면 멈춤 (지워진 항목을 쓰지 않고, 예전 목록의 영상을 계속 만들지 않게)
        self._sidebar_generation = 0
        self.sidebar.model().modelAboutToBeReset.connect(self._bump_sidebar_generation)
        # 목록에 영상을 넣은 곳(job 폴더·폴더, video_list.ListSource) → 그곳에서 새로 생긴 영상의 썸네일 자리. 목록 다시
        # 읽기(새로고침·F5·창이 다시 활성)가 이곳들을 처음과 같은 규칙으로 다시 읽음. 목록을 비우면 함께 잊음
        self._sidebar_sources = {}
        self.sidebar.model().modelAboutToBeReset.connect(self._forget_sidebar_sources)
        # 이번 실행에서 목록 문제 창을 띄운 (제목, 폴더 키, 오류) — 같은 문제는 한 번, 그 폴더를 다시 읽으면 기록을 지움
        self._list_problems_shown = set()
        self._sidebar_refresh_holds = 0  # 목록을 쓰는 중(썸네일 반복·job 목록 만들기·메뉴) — 그동안 다시 읽기는 미룸
        self._sidebar_refresh_deferred = False  # 목록을 다 쓰면 다시 읽음
        self._sidebar_scan = None  # 실행 중인 목록 다시 읽기 (SidebarScan — 디스크 읽기는 GUI 밖 스레드)
        self._sidebar_rescan_queued = False  # 읽는 동안 다시 읽어 달라는 요청이 옴 → 끝나면 한 번 더
        # 새로고침 버튼·F5(썸네일 모드): 다시 읽은 결과를 넣을 때 모든 영상의 썸네일도 확인 (한 번 쓰면 지움, 목록을 비우면 버림)
        self._sidebar_thumbnail_check_requested = False
        self._sidebar_scan_closed = False  # 창이 닫힘 → 늦게 온 다시 읽기 결과는 버림
        self._sidebar_refreshed_at = None  # 마지막으로 목록을 디스크에서 읽은 때 (처음 불러오기·다시 읽기, time.monotonic)
        self._sidebar_scan_seconds = 0.0  # 마지막으로 목록을 읽는 데 걸린 초 (앱이 다시 활성될 때 다시 읽기 간격)
        # 앱이 다시 활성되면(다른 앱에서 돌아옴) 조금 뒤 목록 다시 읽기 (활성화가 잇달아 와도 한 번). 이 앱의 창 사이를
        # 오가거나 메시지 창을 닫을 때는 읽지 않음 — 창 활성(ActivationChange)이 아니라 앱 상태로
        self._sidebar_refresh_timer = QTimer(self)
        self._sidebar_refresh_timer.setSingleShot(True)
        self._sidebar_refresh_timer.setInterval(300)
        self._sidebar_refresh_timer.timeout.connect(self._refresh_sidebar_on_activation)
        QApplication.instance().applicationStateChanged.connect(self._on_application_state_changed)
        self._app_state_connected = True
        self.sidebar.installEventFilter(self)
        self.sidebar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sidebar.customContextMenuRequested.connect(self.show_sidebar_context_menu)
        # 사이드바에 드래그앤드롭 기능 추가
        self.sidebar.setAcceptDrops(True)
        # 사이드바가 키보드 포커스를 받을 수 있도록 설정 (상하 화살표 키 작동을 위해)
        self.sidebar.setFocusPolicy(Qt.StrongFocus)
        selectFolderButton = QPushButton('Select Folder'); selectFolderButton.clicked.connect(self.select_folder)
        selectFolderButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # 북마크 관련 버튼들 추가
        bookmarkButton = QPushButton('Add Bookmark'); bookmarkButton.clicked.connect(self.add_bookmark)
        bookmarkButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bookmarkButton.setStyleSheet(BOOKMARK_BUTTON_STYLE)
        
        bookmarkListButton = QPushButton('Bookmarks'); bookmarkListButton.clicked.connect(self.show_bookmarks)
        bookmarkListButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bookmarkListButton.setStyleSheet(BOOKMARK_LIST_REFRESH_BUTTON_STYLE)
        
        # 작품 경로 관리 버튼 추가
        workPathButton = QPushButton('작품 경로 관리'); workPathButton.clicked.connect(self.manage_work_paths)
        workPathButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        workPathButton.setStyleSheet(WORK_PATH_BUTTON_STYLE)
        
        # 사이드바 뷰 모드 전환 버튼들 추가 (가로 배치)
        viewModeLayout = QHBoxLayout()
        
        self.listModeButton = QPushButton('List')
        self.listModeButton.setCheckable(True)
        self.listModeButton.setChecked(True)
        self.listModeButton.clicked.connect(self.switch_to_list_mode)
        self.listModeButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.listModeButton.setStyleSheet(LIST_MODE_BUTTON_STYLE)
        
        self.thumbnailModeButton = QPushButton('Thumb')
        self.thumbnailModeButton.setCheckable(True)
        self.thumbnailModeButton.clicked.connect(self.switch_to_thumbnail_mode)
        self.thumbnailModeButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.thumbnailModeButton.setStyleSheet(THUMBNAIL_MODE_BUTTON_STYLE)
        
        # 목록 다시 읽기: 다른 PC·Finder에서 NAS의 영상을 지우거나 넣었을 때 (창이 다시 활성될 때도 저절로 읽음)
        self.refreshListButton = QPushButton('새로고침')
        self.refreshListButton.setToolTip('목록 다시 읽기 (F5)')
        self.refreshListButton.clicked.connect(self._refresh_sidebar_by_user)
        self.refreshListButton.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refreshListButton.setStyleSheet(BOOKMARK_LIST_REFRESH_BUTTON_STYLE)
        refresh_shortcut = QShortcut(QKeySequence(Qt.Key_F5), self)
        refresh_shortcut.activated.connect(self._refresh_sidebar_by_user)

        viewModeLayout.addWidget(self.listModeButton)
        viewModeLayout.addWidget(self.thumbnailModeButton)
        viewModeLayout.addWidget(self.refreshListButton)
        
        # 썸네일 진행바 추가
        self.thumbnailProgressBar = QProgressBar()
        self.thumbnailProgressBar.setMinimum(0)
        self.thumbnailProgressBar.setMaximum(100)
        self.thumbnailProgressBar.setValue(0)
        self.thumbnailProgressBar.setTextVisible(True)
        self.thumbnailProgressBar.setFormat('썸네일 생성 대기')
        self.thumbnailProgressBar.setFixedHeight(18)
        self.thumbnailProgressBar.setStyleSheet('QProgressBar {border: 1px solid #aaa; border-radius: 6px; text-align: center; background: #f8f9fa;} QProgressBar::chunk {background: #fd7e14; border-radius: 6px;}')
        
        sidebarLayout = QVBoxLayout(); sidebarLayout.addWidget(selectFolderButton)
        sidebarLayout.addWidget(bookmarkButton); sidebarLayout.addWidget(bookmarkListButton)
        sidebarLayout.addWidget(workPathButton)  # 작품 경로 관리 버튼 추가
        sidebarLayout.addLayout(viewModeLayout)  # 가로 배치된 뷰 모드 버튼들 추가
        sidebarLayout.addWidget(self.thumbnailProgressBar)  # 진행바를 버튼 아래에 추가
        sidebarLayout.addWidget(self.sidebar)
        sidebarContainer = QWidget()
        sidebarContainer.setLayout(sidebarLayout); sidebarContainer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        middleContainer = QWidget()
        middleLayout = QVBoxLayout()
        middleLayout.addLayout(controlLayoutMiddle)
        middleLayout.addStretch(1)
        middleContainer.setLayout(middleLayout)
        # 두 열의 버튼: 좌우 안쪽 여백만 16 → 6px (글자는 가운데 정렬이라 버튼이 글자보다 넓으면 모습은 그대로, 최소 너비만
        # 작아짐 — 창 최소 너비). 위아래 여백·색은 창 스타일시트(테마) 그대로. 버튼 최소 너비가 글자를 지켜서
        # 예전 setMinimumWidth(200)은 뺌 (가운데 열의 처음 너비는 스플리터 setSizes의 220 그대로).
        compact_buttons = "QPushButton { padding-left: 6px; padding-right: 6px; }"
        sidebarContainer.setStyleSheet(compact_buttons)
        middleContainer.setStyleSheet(compact_buttons)

        # 가운데 열은 세로 스크롤 영역 안에: 창이 낮으면 스크롤 (예전에는 이 열의 최소 높이가 창의 최소 높이를 묶어
        # Windows 150% 배율에서 창이 화면보다 컸음). 창이 충분히 크면 스크롤바 없이 예전과 같음.
        self.middleScrollArea = VerticalScrollArea(middleContainer)
        mainSplitter = QSplitter(Qt.Horizontal); mainSplitter.addWidget(sidebarContainer)
        mainSplitter.addWidget(self.middleScrollArea); mainSplitter.addWidget(splitter)
        self.mainSplitter = mainSplitter
        mainSplitter.setStretchFactor(0,0); mainSplitter.setStretchFactor(1,0); mainSplitter.setStretchFactor(2,1)
        mainSplitter.setSizes([200, 220, 1000]); layout = QVBoxLayout(); layout.addWidget(mainSplitter)  # middle 영역 초기 너비를 220으로 증가하여 OCR 버튼 텍스트가 잘리지 않도록
        layout.addLayout(controlLayoutRight); layout.setContentsMargins(0,0,0,0); layout.setSpacing(5)
        # 새 버전 알림 띠: 맨 위 전체 너비, 알릴 것이 있을 때만 보임 (숨긴 동안은 자리·간격도 차지하지 않음).
        # 글자는 좁으면 …로 줄여 창의 최소 너비를 늘리지 않음 (update_banner)
        self.update_banner = UpdateBanner()
        layout.insertWidget(0, self.update_banner)
        widget = QWidget(); widget.setLayout(layout); self.setCentralWidget(widget)
        self.setAcceptDrops(True)
        self.control_widgets = [
            sidebarContainer, self.middleScrollArea, workLabel, stopButton, self.frameRateLabel, volumeLabel, self.workComboBox, self.seasonComboBox, self.jobComboBox,
            self.loopCheckBox, self.playPauseButton, self.playSelectedButton,
            self.volumeSlider, self.frameRateComboBox, self.wipeCheckBox, self.sidebar, self.wipeXButton, self.wipeYButton, openButtonA, openButtonB, self.volumeSlider, selectFolderButton, bookmarkButton, bookmarkListButton, workPathButton, self.listModeButton, self.thumbnailModeButton, self.refreshListButton, self.thumbnailProgressBar
        ]
        # 시간: 줄이면 뒤쪽(전체 시간)부터 …로 ('00:00:00.000 / …'까지). 너비는 예전처럼 이 모양의 글자 너비로 고정
        self.timeLabel = ElidedLabel(Qt.ElideRight, keep_text="00:00:00.000 / 00:00:00.000",
                                     keep_prefix="00:00:00.000 /", hint_text="00:00:00.000 / 00:00:00.000",
                                     shrink_order=3, collapse_order=8)
        self.timeLabel.setText("00:00:00.000 / 00:00:00.000"); self.timeLabel.setFont(QFont("Arial", 16))
        self.timeLabel.setStyleSheet(TIME_LABEL_STYLE)
        fileInfoLayout.addWidget(self.timeLabel); fileInfoLayout.setAlignment(self.timeLabel, Qt.AlignRight)
        
        # timeLabel을 control_widgets에 추가
        self.control_widgets.append(self.timeLabel)
        
        # positionScroll을 control_widgets에 추가
        self.control_widgets.append(self.positionScroll)
        
        # 나머지 UI 라벨들을 control_widgets에 추가
        self.control_widgets.append(self.filenameLabel)
        self.control_widgets.append(self.labelFrameCount)
        self.control_widgets.append(self.labelTotalFrames)
        self.control_widgets.append(self.labelPlaybackFPS)

        # 스크롤바 핸들(thumb) 크기를 고정 (예: 80px)
        self.positionScroll.setStyleSheet(POSITION_SCROLL_STYLE)
        # Windows(Fusion 포함)에서도 Mac처럼 왼쪽 클릭으로 그 위치로 바로 이동 + 드래그 계속되게
        jump_to_click(self.positionScroll)

        # 모든 주요 위젯들의 focusPolicy를 Qt.NoFocus로 설정 (전역 단축키 방해 방지)
        self.positionScroll.setFocusPolicy(Qt.NoFocus)
        self.volumeSlider.setFocusPolicy(Qt.NoFocus)
        self.gpuComboBox.setFocusPolicy(Qt.NoFocus)
        self.workComboBox.setFocusPolicy(Qt.NoFocus)
        self.seasonComboBox.setFocusPolicy(Qt.NoFocus)
        self.jobComboBox.setFocusPolicy(Qt.NoFocus)
        self.frameRateComboBox.setFocusPolicy(Qt.NoFocus)
        
        # 추가 위젯들의 focusPolicy 설정
        self.loopCheckBox.setFocusPolicy(Qt.NoFocus)
        self.wipeCheckBox.setFocusPolicy(Qt.NoFocus)
        self.playPauseButton.setFocusPolicy(Qt.NoFocus)
        self.fullscreenButton.setFocusPolicy(Qt.NoFocus)
        self.playSelectedButton.setFocusPolicy(Qt.NoFocus)
        self.playSelectedPauseButton.setFocusPolicy(Qt.NoFocus)
        self.wipeXButton.setFocusPolicy(Qt.NoFocus)
        self.wipeYButton.setFocusPolicy(Qt.NoFocus)
        openButtonA.setFocusPolicy(Qt.NoFocus)
        openButtonB.setFocusPolicy(Qt.NoFocus)
        stopButton.setFocusPolicy(Qt.NoFocus)
        selectFolderButton.setFocusPolicy(Qt.NoFocus)
        
        # 라벨들의 focusPolicy 설정
        self.filenameLabel.setFocusPolicy(Qt.NoFocus)
        self.labelFrameCount.setFocusPolicy(Qt.NoFocus)
        self.labelTotalFrames.setFocusPolicy(Qt.NoFocus)
        self.timeLabel.setFocusPolicy(Qt.NoFocus)
        self.gpuLabel.setFocusPolicy(Qt.NoFocus)
        workLabel.setFocusPolicy(Qt.NoFocus)
        volumeLabel.setFocusPolicy(Qt.NoFocus)
        self.frameRateLabel.setFocusPolicy(Qt.NoFocus)

        # 메인 윈도우가 항상 키보드 이벤트를 받을 수 있도록 설정
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocus()  # 초기 포커스 설정

    def eventFilter(self, source, event):
        # V키가 비활성화되어 있을 때는 오버레이 컨트롤 동작하지 않음 (컨트롤 패널이 표시되어 있을 때)
        if self.controls_visible:
            # 컨트롤 패널이 표시되어 있을 때는 오버레이 관련 이벤트를 완전히 무시
            if event.type() in [QEvent.MouseMove, QEvent.Enter, QEvent.Leave]:
                return False  # 기본 이벤트 처리 허용
        
        # videoWidget 마우스 움직임 감지 (컨트롤 패널이 숨겨져 있을 때만)
        if source == self.videoWidget and event.type() == QEvent.MouseMove:
            if not self.overlayFrame.isVisible():
                self.show_overlay_controls()
            # 마우스가 비디오 위젯에 있을 때는 타이머를 중지하여 오버레이가 사라지지 않도록 함
            self.overlay_timer.stop()
            return False  # 기본 이벤트 처리 허용
        

        
        # 마우스가 비디오 위젯에 들어올 때 오버레이 표시 (컨트롤 패널이 숨겨져 있을 때만)
        if source == self.videoWidget and event.type() == QEvent.Enter:
            if not self.overlayFrame.isVisible():
                self.show_overlay_controls()
            return False  # 기본 이벤트 처리 허용
        
        # 마우스가 비디오 위젯을 벗어날 때 오버레이 숨김 (오버레이 영역으로 이동하는 경우 제외)
        if source == self.videoWidget and event.type() == QEvent.Leave:
            # 마우스가 오버레이 영역으로 이동하는지 확인
            cursor_pos = self.cursor().pos()
            overlay_rect = self.overlayFrame.geometry()
            overlay_rect = self.mapToGlobal(overlay_rect.topLeft()), self.mapToGlobal(overlay_rect.bottomRight())
            overlay_rect = QRect(overlay_rect[0], overlay_rect[1])
            
            if not overlay_rect.contains(cursor_pos):
                self.hide_overlay_controls()
            return False  # 기본 이벤트 처리 허용
        
        if event.type() == QEvent.KeyPress:
            key = event.key()
            modifiers = event.modifiers()
            print(f"EventFilter - Key pressed: {key}, Modifiers: {modifiers} from source: {source}")  # 디버깅 출력 추가
            
            # Ctrl+O: 오버레이 컨트롤러 위치 리셋 (전역)
            if key == Qt.Key_O and (modifiers & Qt.ControlModifier):
                print("EventFilter - Ctrl+O detected!")
                if hasattr(self, 'overlayFrame'):
                    print("EventFilter - Resetting overlay position")
                    self.reset_overlay_position()
                    QTimer.singleShot(100, self.force_focus)
                event.accept()
                return True
            
            # Ctrl+O 대체 방법: O 키만 감지하고 Ctrl 상태 확인 (한글 ㅐ 키 지원)
            if key == Qt.Key_O or (hasattr(event, 'text') and event.text() == 'ㅐ'):
                print(f"EventFilter - O key pressed with modifiers: {modifiers}")
                if modifiers & Qt.ControlModifier:
                    print("EventFilter - Ctrl+O detected (alternative method)!")
                    if hasattr(self, 'overlayFrame'):
                        print("EventFilter - Resetting overlay position")
                        self.reset_overlay_position()
                        QTimer.singleShot(100, self.force_focus)
                    event.accept()
                    return True
            
            # 전역 프레임 이동 단축키 (, . ← →)
            if key in [Qt.Key_Comma, Qt.Key_Left]:
                self.prev_frame()
                event.accept()
                return True
            elif key in [Qt.Key_Period, Qt.Key_Right]:
                self.next_frame()
                event.accept()
                return True
            
            # Shift + F 단축키 처리 (전역) - 더 정확한 감지
            if key == Qt.Key_F:
                if modifiers == Qt.ShiftModifier:
                    print("EventFilter - Shift + F detected!")
                    self.toggle_video_only_fullscreen()
                    return True
                else:
                    # 단독 F 키 처리
                    self.toggle_fullscreen()
                    return True
            
            # 사이드바에서의 특별한 단축키 처리
            if source == self.sidebar:
                # 상하 화살표 키는 사이드바에서만 작동 (기본 동작 허용)
                if key in [Qt.Key_Up, Qt.Key_Down]:
                    # 사이드바에 포커스가 있을 때만 기본 동작 허용
                    if self.sidebar.hasFocus():
                        # 기본 동작을 허용하고, 키 이벤트 처리 후 선택된 항목을 비디오 A에 로드
                        QTimer.singleShot(10, self.load_selected_item_to_video_a)
                        return False  # 기본 동작 허용
                    else:
                        # 사이드바에 포커스가 없으면 사이드바에 포커스 설정 후 기본 동작 허용
                        self.sidebar.setFocus()
                        QTimer.singleShot(10, self.load_selected_item_to_video_a)
                        return False
                elif key == Qt.Key_Space: 
                    self.toggle_play_pause()
                    return True
                elif key in (Qt.Key_Return, Qt.Key_Enter): 
                    self.play_selected_files()
                    return True
                elif key == Qt.Key_Backslash: 
                    self.toggle_play_pause_selected()
                    return True
                elif key in [Qt.Key_Plus, Qt.Key_Equal, Qt.Key_2]: 
                    print("EventFilter - Zoom in triggered")
                    # 마우스 커서 위치를 비디오 위젯 좌표로 변환하여 전달
                    cursor_pos = self.videoWidget.mapFromGlobal(self.cursor().pos())
                    self.videoWidget.zoom_in(cursor_pos)
                    return True
                elif key in [Qt.Key_Minus, Qt.Key_1]: 
                    print("EventFilter - Zoom out triggered")
                    # 마우스 커서 위치를 비디오 위젯 좌표로 변환하여 전달
                    cursor_pos = self.videoWidget.mapFromGlobal(self.cursor().pos())
                    self.videoWidget.zoom_out(cursor_pos)
                    return True
                elif key == Qt.Key_3: 
                    self.videoWidget.reset_view()
                    return True
                elif key == Qt.Key_4: 
                    self.videoWidget.show_original_size()
                    return True
            
            # V 키 처리 (컨트롤 패널 표시/숨김) - 한글 ㅍ과 영문 V 모두 지원
            if key == Qt.Key_V or (hasattr(event, 'text') and event.text() == 'ㅍ'):
                print(f"EventFilter - V key pressed (key: {key}, text: '{event.text() if hasattr(event, 'text') else 'N/A'}')")  # 디버깅 출력
                
                # 컨트롤 패널 상태 변경
                self.controls_visible = not self.controls_visible
                valid_widgets = self.get_valid_control_widgets()
                for widget in valid_widgets:
                    try:
                        widget.setVisible(self.controls_visible)
                    except (RuntimeError, AttributeError):
                        continue
                
                # 컨트롤이 숨겨지면 오버레이를 표시하고, 컨트롤이 보이면 오버레이를 숨김
                if hasattr(self, 'overlayFrame'):
                    if not self.controls_visible:
                        print("EventFilter - Showing overlay controls")  # 디버깅 출력
                        # 오버레이를 강제로 표시
                        self.overlayFrame.setVisible(True)
                        self.overlayFrame.raise_()
                        
                        # V 키 활성화 시 하단 중앙으로 위치하도록 플래그 설정
                        self.overlay_is_bottom_center = True
                        
                        self.show_overlay_controls()
                    else:
                        print("EventFilter - Hiding overlay controls")  # 디버깅 출력
                        self.hide_overlay_controls()
                
                QTimer.singleShot(100, self.force_focus)  # V키 후 포커스 복원
                return True
            
            # R 키 처리 (썸네일 재생성)
            if key == Qt.Key_R:
                self.regenerate_selected_thumbnails()
                return True
            
            # 한글 키 처리 (ㄱ 키 - 썸네일 재생성)
            if hasattr(event, 'text') and event.text() == 'ㄱ':
                self.regenerate_selected_thumbnails()
                return True
        
        # 사이드바 드래그앤드롭 처리
        if source == self.sidebar:
            if event.type() == QEvent.DragEnter:
                if event.mimeData().hasUrls():
                    event.accept()
                else:
                    event.ignore()
                return True
            elif event.type() == QEvent.Drop:
                urls = event.mimeData().urls()
                video_files = []
                folder_paths = []  # 폴더 경로들을 저장할 리스트
                
                for url in urls:
                    file_path = paths.normalize_native(url.toLocalFile())
                    if os.path.isfile(file_path):
                        if self.is_video_file(file_path):
                            video_files.append(file_path)
                    elif os.path.isdir(file_path):
                        # 폴더인 경우 - 재귀적으로 비디오 파일 찾기
                        folder_paths.append(file_path)  # 폴더 경로 저장
                        folder_files = self.get_video_files_from_folder(file_path)
                        if folder_files is None:
                            # 폴더를 읽지 못함 (창으로 알림) — 기억해 두면 연결이 돌아온 뒤 새로고침(F5)으로 들어옴
                            self._register_unread_folder(file_path)
                            continue
                        folder_files.sort()  # 이름 순서대로 정렬
                        video_files.extend(folder_files)
                
                # 폴더가 포함된 경우 북마크에 자동 추가
                if folder_paths:
                    self.add_dropped_folders_to_bookmarks(folder_paths)
                
                if video_files:
                    # 폴더가 포함된 경우 썸네일 폴더 설정
                    if folder_paths:
                        # 첫 번째 폴더를 기준으로 썸네일 폴더 설정 (전에 고른 job·폴더가 아니라)
                        self._use_dropped_folder_for_thumbnails(folder_paths[0])
                    
                    self.add_files_to_sidebar(video_files, folder_paths)
                    
                    # 백그라운드 로딩 스케줄링
                    if folder_paths:
                        self.schedule_background_thumbnail_loading()
                return True
        
        return False  # 기본 이벤트 처리 허용
    
    def changeEvent(self, event):
        """윈도우 상태 변경 이벤트 처리 - 앱이 활성화될 때 포커스 설정"""
        if event.type() == QEvent.WindowStateChange:
            # 윈도우 상태가 변경될 때 포커스 설정
            QTimer.singleShot(100, self.force_focus)
            
            # V 키 활성 상태에서 윈도우 크기 변경 시 오버레이 컨트롤러를 하단 중앙으로 재배치
            if hasattr(self, 'controls_visible') and not self.controls_visible:
                if hasattr(self, 'overlayFrame') and self.overlayFrame and self.overlayFrame.isVisible():
                    QTimer.singleShot(150, self.reposition_overlay_to_bottom_center)
                    
        elif event.type() == QEvent.ActivationChange:
            # 앱이 활성화될 때 포커스 설정 (사이드바 목록 다시 읽기는 앱이 다시 활성될 때 — _on_application_state_changed)
            if self.isActiveWindow():
                QTimer.singleShot(100, self.force_focus)
        super().changeEvent(event)

    def _measure_polished_layout(self):
        """스타일시트·글꼴이 적용된 크기로 레이아웃을 다시 잼. 창을 보이기 전에는 레이아웃이 위젯마다 스타일 적용 전
        크기를 저장해 두고 있어서 (Windows에서 처음 창이 가운데 열보다 9px 낮았고 정보 줄 라벨이 좁았음) 모든 위젯을
        스타일 적용(ensurePolished)한 뒤 저장된 크기를 버리고(updateGeometry) 레이아웃 요청을 바로 처리한다."""
        self.ensurePolished()
        for widget in self.findChildren(QWidget):
            widget.ensurePolished()  # 창이 이미 스타일 적용됐으면 창의 ensurePolished는 자식으로 내려가지 않음
            widget.updateGeometry()  # 레이아웃 항목에 저장된 위젯 크기를 버림
        for layout in self.findChildren(QLayout):
            layout.invalidate()  # 보이기 전에는 updateGeometry가 부모 레이아웃까지 알리지 않음 (위젯이 아직 숨김 상태)
        for _ in range(2):  # 처리하면서 부모에 다시 요청이 쌓임
            QApplication.sendPostedEvents(None, QEvent.LayoutRequest)

    def apply_startup_geometry(self):
        """처음 창 크기·위치와 열 너비 (예전 모습): max(1080×720, 레이아웃이 원하는 크기)를 화면 작업 영역 안으로,
        사이드바·가운데 열은 예전 처음 너비(스플리터 setSizes 200·220, 최소 너비가 더 크면 최소 너비)."""
        self._measure_polished_layout()
        rect = startup_geometry(self.sizeHint(), self.minimumSizeHint(),
                                QApplication.primaryScreen().availableGeometry())
        self.setGeometry(rect)
        splitter = self.mainSplitter
        side, middle = (max(start, w.minimumSizeHint().width(), w.minimumWidth())
                        for start, w in ((200, splitter.widget(0)), (220, splitter.widget(1))))
        splitter.setSizes([side, middle, max(0, rect.width() - side - middle)])
        # 초기 창 크기 저장 (앱 처음 실행 시) — 동영상 전용 전체화면을 끝내면 이 크기로 돌아옴
        self.initial_geometry = self.geometry()

    def showEvent(self, event):
        """처음 보일 때(자식 위젯이 다 보이고 스타일이 적용된 뒤, 실제 창이 화면에 나타나기 전) 처음 크기를 한 번 더 잼:
        그사이 누가 창 크기를 바꾸지 않았고 결과가 다르면 맞춤 — 화면에 나타나기 전이라 크기가 바뀌는 게 보이지 않음."""
        super().showEvent(event)
        if self._startup_geometry_checked or event.spontaneous():
            return
        self._startup_geometry_checked = True
        if self.geometry() != self.initial_geometry or self.windowState() != Qt.WindowNoState:
            return
        before = self.geometry()
        self.apply_startup_geometry()
        if self.geometry() != before:
            timing_log.startup(f"창: 처음 크기 다시 맞춤 {before.width()}×{before.height()} → "
                               f"{self.width()}×{self.height()} (스타일 적용 뒤 레이아웃 크기)")

    def resizeEvent(self, event):
        """윈도우 크기 변경 이벤트 처리"""
        super().resizeEvent(event)
        
        # V 키 활성 상태에서 윈도우 크기 변경 시 오버레이 컨트롤러를 하단 중앙으로 재배치
        if hasattr(self, 'controls_visible') and not self.controls_visible:
            if hasattr(self, 'overlayFrame') and self.overlayFrame and self.overlayFrame.isVisible():
                QTimer.singleShot(100, self.reposition_overlay_to_bottom_center)
    
    def force_focus(self):
        """포커스를 메인 윈도우로 되돌림 (창 상태 변경·V 키·오버레이 위치 리셋 뒤 단축키가 먹도록).

        보통 QTimer로 100ms 뒤에 불리므로 실행되는 그 순간에 다시 확인한다: 모달 대화상자·팝업이 떠 있거나 이 앱의
        다른 창이 활성이면 아무것도 안 함. Windows에서는 여기의 activateWindow()가 모달 창(예: OCR 선택 구간 분석의
        '종료 프레임' 입력 창)에서 키보드 포커스를 빼앗아 글자가 입력되지 않았음. 이 앱에 활성 창이 없으면
        (다른 앱이 앞에 있음) 예전처럼 활성화를 시도한다.
        """
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return
        active_window = QApplication.activeWindow()
        if active_window is not None and active_window is not self:
            return
        self.setFocus()
        self.activateWindow()

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

    def on_sidebar_item_clicked(self, item):
        if self.is_playlist_playing: return
        # 캐시 초기화(이전 영상 프레임 방지)는 open_file이 영상을 연 뒤에 함 — 열지 못하면 보던 영상의 캐시는 그대로
        self.open_file('A', item.toolTip())

    @pyqtSlot(int)
    def set_dark_theme(self):
        self.setStyleSheet(DARK_STYLESHEET)
        self.current_theme = 'dark'

    def set_light_theme(self):
        self.setStyleSheet(LIGHT_STYLESHEET)
        self.current_theme = 'light'

    def toggle_theme(self):
        if self.current_theme == 'dark':
            self.set_light_theme()
        else:
            self.set_dark_theme()

    def toggle_ocr_roi_selection(self, checked):
        """Enable or disable ROI selection mode based on button state."""
        frame_a = getattr(self, "frame_a", None)
        cap_a = getattr(self, "cap_a", None)
        if checked:
            if hasattr(self, "annotationModeButton") and self.annotationModeButton.isChecked():
                self.annotationModeButton.setChecked(False)
            if not cap_a or frame_a is None:
                QMessageBox.warning(self, "ROI 지정 불가", "Video A를 먼저 로드한 뒤 사용할 수 있습니다.")
                self.ocrSelectRoiButton.blockSignals(True)
                self.ocrSelectRoiButton.setChecked(False)
                self.ocrSelectRoiButton.blockSignals(False)
                return
            self.videoWidget.enable_roi_selection(True)
            self.update_ocr_status_label("ROI: 비디오 위에서 드래그하여 영역을 지정하세요.")
        else:
            self.videoWidget.enable_roi_selection(False)
            self.update_ocr_status_label()

    def on_roi_selected(self, normalized_rect):
        """Handle ROI selection completion from the video widget."""
        self.ocr_roi = normalized_rect
        self.videoWidget.enable_roi_selection(False)
        self.videoWidget.set_roi_normalized_rect(normalized_rect)
        self.ocrSelectRoiButton.blockSignals(True)
        self.ocrSelectRoiButton.setChecked(False)
        self.ocrSelectRoiButton.blockSignals(False)
        self.ocrClearRoiButton.setEnabled(True)
        self.ocrAnalyzeButton.setEnabled(True)
        self.ocrAnalyzeRangeButton.setEnabled(True)
        self.ocrTrackingCheckBox.setEnabled(True)
        self.update_ocr_status_label()
        # 모드에 따라 UI 업데이트
        self.on_ocr_mode_changed()

    def on_ocr_mode_changed(self):
        """OCR 모드 변경 시 UI 업데이트"""
        ocr_mode = self.ocrModeComboBox.currentData() if hasattr(self, 'ocrModeComboBox') else 'titmouse'

        # All 모드일 때 패턴 입력 필드 표시
        try:
            if hasattr(self, 'ocrPatternLabel') and hasattr(self, 'ocrPatternLineEdit'):
                # 객체가 유효한지 확인 (삭제된 객체 접근 방지)
                if self.ocrPatternLabel is not None and self.ocrPatternLineEdit is not None:
                    if ocr_mode == 'all':
                        self.ocrPatternLabel.setVisible(True)
                        self.ocrPatternLineEdit.setVisible(True)
                    else:
                        self.ocrPatternLabel.setVisible(False)
                        self.ocrPatternLineEdit.setVisible(False)
        except RuntimeError:
            # 객체가 이미 삭제된 경우 무시
            pass

        # 애니매틱/애니매틱2 모드일 때는 ROI 선택 버튼 비활성화
        if ocr_mode in ['animatic', 'animatic2']:
            if hasattr(self, 'ocrSelectRoiButton'):
                self.ocrSelectRoiButton.setEnabled(False)
                mode_name = '애니매틱2' if ocr_mode == 'animatic2' else '애니매틱'
                self.ocrSelectRoiButton.setToolTip(f'{mode_name} 모드는 ROI가 필요 없습니다.')
            if hasattr(self, 'ocrTrackingCheckBox'):
                self.ocrTrackingCheckBox.setEnabled(False)

            # 애니매틱 모드는 ROI 없이도 분석 가능 (비디오만 있으면 됨)
            if hasattr(self, 'ocrAnalyzeButton') and self.filename_a:
                self.ocrAnalyzeButton.setEnabled(True)
            if hasattr(self, 'ocrAnalyzeRangeButton') and self.filename_a:
                self.ocrAnalyzeRangeButton.setEnabled(True)  # 애니매틱 모드도 선택 구간 분석 지원
        else:
            # OCR 모드일 때는 ROI 선택 버튼 활성화
            if hasattr(self, 'ocrSelectRoiButton'):
                self.ocrSelectRoiButton.setEnabled(True)
                self.ocrSelectRoiButton.setToolTip('영상에서 OCR 분석에 사용할 영역을 드래그하여 지정합니다.')
            if hasattr(self, 'ocrTrackingCheckBox'):
                self.ocrTrackingCheckBox.setEnabled(True)
            
            # OCR 모드는 ROI가 있어야 분석 가능
            if hasattr(self, 'ocrAnalyzeButton'):
                if self.ocr_roi and self.filename_a:
                    self.ocrAnalyzeButton.setEnabled(True)
                else:
                    self.ocrAnalyzeButton.setEnabled(False)
            if hasattr(self, 'ocrAnalyzeRangeButton'):
                if self.ocr_roi and self.filename_a:
                    self.ocrAnalyzeRangeButton.setEnabled(True)
                else:
                    self.ocrAnalyzeRangeButton.setEnabled(False)
    
    def update_ocr_status_label(self, message=None):
        """Update OCR status - OCR 관련 메시지는 팝업창에 표시, ROI 정보는 무시"""
        # OCR 관련 메시지는 팝업창에 표시
        if message and message.startswith("OCR:"):
            if self.ocr_progress_dialog and hasattr(self, 'ocr_log_text'):
                self.ocr_log_text.appendPlainText(message)
                scrollbar = self.ocr_log_text.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
        # ROI 정보는 더 이상 표시하지 않음 (로그창 삭제됨)

    def clear_ocr_roi(self):
        """Reset ROI information and disable related controls."""
        self.ocr_roi = None
        self.videoWidget.enable_roi_selection(False)
        self.videoWidget.clear_roi()
        self.ocrSelectRoiButton.blockSignals(True)
        self.ocrSelectRoiButton.setChecked(False)
        self.ocrSelectRoiButton.blockSignals(False)
        self.ocrClearRoiButton.setEnabled(False)
        self.ocrAnalyzeButton.setEnabled(False)
        self.ocrAnalyzeRangeButton.setEnabled(False)
        self.ocrTrackingCheckBox.setEnabled(False)
        self.ocrTrackingCheckBox.setChecked(False)
        self.update_ocr_status_label()

    def has_unsaved_ocr_results(self):
        """'OCR 저장'을 누르지 않은 OCR·애니매틱 검토 결과가 있는지 (업데이트로 창을 닫으면 사라짐)."""
        return self._ocr_results_unsaved

    def reset_ocr_state(self):
        """Clear OCR state when media changes."""
        self.ocr_roi = None
        self.last_ocr_segments = []
        self._ocr_results_unsaved = False
        self.saved_edited_segments = None  # 저장된 편집 상태도 초기화
        self.pending_ocr_metadata = None
        if hasattr(self, "ocrStatusLabel"):
            self.update_ocr_status_label()
        if hasattr(self, "ocrClearRoiButton"):
            self.ocrClearRoiButton.setEnabled(False)
        if hasattr(self, "ocrAnalyzeButton"):
            self.ocrAnalyzeButton.setEnabled(False)
        if hasattr(self, "ocrAnalyzeRangeButton"):
            self.ocrAnalyzeRangeButton.setEnabled(False)
        if hasattr(self, "ocrTrackingCheckBox"):
            self.ocrTrackingCheckBox.setEnabled(False)
            self.ocrTrackingCheckBox.setChecked(False)
        if hasattr(self, "ocrSelectRoiButton"):
            self.ocrSelectRoiButton.blockSignals(True)
            self.ocrSelectRoiButton.setChecked(False)
            self.ocrSelectRoiButton.blockSignals(False)
        if hasattr(self, "videoWidget"):
            self.videoWidget.clear_roi()
            self.videoWidget.enable_roi_selection(False)
        
        # 모드에 따라 버튼 활성화 상태 업데이트
        self.on_ocr_mode_changed()
        # 실행 중인 워커는 멈추라고만 하고 끝날 때까지 붙잡아 둠 (마지막 참조를 놓으면 실행 중에 파괴돼 앱이 죽음)
        worker, self.ocr_worker = self.ocr_worker, None
        if worker is not None:
            if worker.isRunning():
                worker.stop()
                self.ocr_cancelled = False
                # 놓은 분석의 진행 창: 신호를 막으므로 더는 갱신되지 않음 → 닫음
                print("[OCR] 영상이 바뀌어 실행 중인 분석·컷 감지를 멈추고 진행 창을 닫음")
                self.close_ocr_progress_dialog()
            release_worker(worker, "OCR 분석·컷 감지 (영상이 바뀜)")
        export_worker, self.ocr_export_worker = self.ocr_export_worker, None
        if export_worker is not None:
            if export_worker.isRunning():
                export_worker.stop()
            # 내보내기의 취소·오류 알림은 지금처럼 받음 (신호를 막지 않음)
            release_worker(export_worker, "OCR 구간 내보내기 (영상이 바뀜)", block_signals=False)
        if hasattr(self, 'ocr_review_dialog') and self.ocr_review_dialog is not None:
            self.ocr_review_dialog.close()
            self.ocr_review_dialog.deleteLater()
            self.ocr_review_dialog = None

    def get_current_video_path(self):
        """현재 사용할 비디오 경로를 반환합니다. 사이드바에서 선택된 동영상이 있으면 그것을, 없으면 Video A를 사용합니다."""
        # 사이드바에서 선택된 동영상이 있는지 확인
        selected_items = self.sidebar.selectedItems()
        if selected_items:
            # 첫 번째 선택된 아이템의 경로 사용
            video_path = selected_items[0].toolTip()
            if video_path and os.path.exists(video_path):
                return video_path
        
        # 사이드바에 선택된 항목이 없으면 Video A 사용
        if self.filename_a and os.path.exists(self.filename_a):
            return self.filename_a
        
        return None

    def run_ocr_analysis(self):
        """Kick off OCR worker to detect text changes and export segments."""
        if self.ocr_worker and self.ocr_worker.isRunning():
            QMessageBox.information(self, "OCR 진행 중", "이미 OCR 분석이 실행 중입니다.")
            return

        # 사이드바 또는 Video A에서 비디오 경로 가져오기
        video_path = self.get_current_video_path()
        if not video_path:
            QMessageBox.warning(self, "비디오 없음", "Video A를 먼저 로드하거나 사이드바에서 동영상을 선택해주세요.")
            return

        # OCR 분석 방식 확인
        ocr_mode = self.ocrModeComboBox.currentData() if hasattr(self, 'ocrModeComboBox') else 'titmouse'
        
        # 애니매틱/애니매틱2 모드가 아닐 때만 ROI 체크
        if ocr_mode not in ['animatic', 'animatic2'] and not self.ocr_roi:
            QMessageBox.warning(self, "ROI 미지정", "분석 전에 ROI를 지정해주세요.")
            return

        self.ocr_cancelled = False
        
        # OCR 분석 방식 확인
        ocr_mode = self.ocrModeComboBox.currentData() if hasattr(self, 'ocrModeComboBox') else 'titmouse'
        
        # 모드 전환 감지: 이전 모드와 다른 모드로 전환되면 모든 결과 초기화
        prev_ocr_mode = getattr(self, '_last_ocr_mode', None)
        if prev_ocr_mode is not None and prev_ocr_mode != ocr_mode:
            print(f"[모드 전환] 이전 모드={prev_ocr_mode}, 새 모드={ocr_mode}, 모든 결과 초기화")
            # 모드 전환 시 모든 결과 완전히 초기화
            self.pending_ocr_metadata = None
            self.saved_edited_segments = None
            self.last_ocr_segments = []
            self._ocr_results_unsaved = False
            # 기존 다이얼로그도 닫기
            if hasattr(self, 'ocr_review_dialog') and self.ocr_review_dialog is not None:
                if self.ocr_review_dialog.isVisible():
                    self.ocr_review_dialog.close()
                self.ocr_review_dialog.deleteLater()
                self.ocr_review_dialog = None
        else:
            # 같은 모드면 기존 결과 유지 (재분석 시)
            self.pending_ocr_metadata = None
            # 새로운 분석 시작 시 이전 수정 내용 클리어
            self.saved_edited_segments = None
            # 새로운 분석 시작 시 이전 결과도 클리어
            self.last_ocr_segments = []
            self._ocr_results_unsaved = False
        
        # OCR 모드 저장 (reopen_ocr_result에서 사용)
        self._last_ocr_mode = ocr_mode
        # 현재 분석 중인 비디오 경로 저장 (save_ocr_result에서 사용)
        self._current_ocr_video_path = video_path
        
        # 애니매틱/애니매틱2 모드인 경우 전용 워커 사용
        if ocr_mode == 'animatic':
            # 애니매틱 모드는 ROI가 필요 없음
            from .workers import SceneDetectWorker
            self.ocr_worker = SceneDetectWorker(
                video_path,
                threshold=30.0,  # 기본 임계값
                min_scene_len=15,  # 최소 15프레임
            )
        elif ocr_mode == 'animatic2':
            # 애니매틱2 모드는 TransNetV2 사용 (디졸브/페이드 감지 향상)
            from .workers import TransNetV2Worker
            self.ocr_worker = TransNetV2Worker(
                video_path,
                threshold=0.3,  # 낮은 임계값으로 더 민감하게 감지 (0.5 -> 0.3)
                min_scene_len=10,  # 최소 씬 길이 감소 (15 -> 10프레임)
                detect_gradual_transitions=True,  # 점진적 전환 감지 활성화
                post_process_histogram=True,  # 히스토그램 기반 추가 감지 활성화
            )
        else:
            # OCR 모드인 경우 OCRWorker 사용 (lazy import)
            from .workers import OCRWorker
            tracking_enabled = self.ocrTrackingCheckBox.isChecked() if hasattr(self, 'ocrTrackingCheckBox') else False
            
            if not self.ocr_roi:
                QMessageBox.warning(self, "ROI 미지정", "OCR 분석 전에 ROI를 지정해주세요.")
                return
            
            # All 모드일 때 패턴 가져오기
            pattern = None
            if ocr_mode == 'all':
                try:
                    if hasattr(self, 'ocrPatternLineEdit') and self.ocrPatternLineEdit is not None:
                        pattern = self.ocrPatternLineEdit.text().strip()
                        if not pattern:
                            QMessageBox.warning(self, "패턴 미입력", "All 모드를 사용하려면 패턴을 입력해주세요.\n예: ### WW#_#WW - #### W")
                            return
                    else:
                        QMessageBox.warning(self, "패턴 입력 필드 오류", "패턴 입력 필드를 찾을 수 없습니다.")
                        return
                except RuntimeError:
                    QMessageBox.warning(self, "패턴 입력 필드 오류", "패턴 입력 필드에 접근할 수 없습니다.")
                    return
            
            self.ocr_worker = OCRWorker(
                video_path,
                self.ocr_roi,
                tracking_enabled=tracking_enabled,
                ocr_mode=ocr_mode,
                pattern=pattern,
            )
        
        self.ocr_worker.progress.connect(self.on_ocr_progress)
        self.ocr_worker.status.connect(self.on_ocr_status)
        self.ocr_worker.error.connect(self.on_ocr_error)
        self.ocr_worker.completed.connect(self.on_ocr_completed)

        # OCR 분석 진행 다이얼로그 생성 (로그 표시 기능 포함)
        self.ocr_progress_dialog = QDialog(self)
        # 모드에 따라 다이얼로그 제목 변경
        if ocr_mode == 'animatic':
            self.ocr_progress_dialog.setWindowTitle("애니매틱 컷 감지")
        elif ocr_mode == 'animatic2':
            self.ocr_progress_dialog.setWindowTitle("애니매틱2 컷 감지 (TransNetV2)")
        else:
            self.ocr_progress_dialog.setWindowTitle("OCR 분석")
        self.ocr_progress_dialog.setWindowModality(Qt.NonModal)
        self.ocr_progress_dialog.resize(500, 300)
        
        layout = QVBoxLayout(self.ocr_progress_dialog)
        
        # 진행률 표시
        self.ocr_progress_bar = QProgressBar()
        self.ocr_progress_bar.setRange(0, 100)
        self.ocr_progress_bar.setValue(0)
        layout.addWidget(self.ocr_progress_bar)
        
        # 로그 표시 영역
        self.ocr_log_text = QPlainTextEdit()
        self.ocr_log_text.setReadOnly(True)
        self.ocr_log_text.setStyleSheet(OCR_LOG_TEXT_STYLE)
        layout.addWidget(self.ocr_log_text)
        
        # 버튼 레이아웃
        button_layout = QHBoxLayout()
        
        # 취소 버튼 (진행 중일 때만 표시)
        self.ocr_cancel_button = QPushButton("취소")
        self.ocr_cancel_button.clicked.connect(self.cancel_ocr_analysis)
        button_layout.addWidget(self.ocr_cancel_button)
        
        button_layout.addStretch()
        
        # 닫기 버튼 (완료 후 표시)
        self.ocr_close_button = QPushButton("닫기")
        self.ocr_close_button.clicked.connect(self.close_ocr_progress_dialog)
        self.ocr_close_button.setEnabled(False)  # 초기에는 비활성화
        self.ocr_close_button.setVisible(False)  # 초기에는 숨김
        button_layout.addWidget(self.ocr_close_button)
        
        layout.addLayout(button_layout)
        
        # 모드에 따라 다른 메시지 표시
        if ocr_mode == 'animatic':
            self.ocr_log_text.appendPlainText("애니매틱 컷 감지를 준비 중입니다…")
        elif ocr_mode == 'animatic2':
            self.ocr_log_text.appendPlainText("애니매틱2 컷 감지를 준비 중입니다 (TransNetV2)…")
        else:
            self.ocr_log_text.appendPlainText("OCR 분석을 준비 중입니다…")
        self.ocr_progress_dialog.show()
        if ocr_mode == 'animatic2':
            self._notice_first_tensorflow_load()

        # 로그는 팝업창에 표시되므로 여기서는 제거
        self.ocr_worker.start()

    # 첫 애니매틱2 분석 전에 진행 창에 쓰는 안내 (TensorFlow 첫 import가 수 초 동안 화면을 멈출 수 있음)
    FIRST_TENSORFLOW_LOAD_NOTICE = "TensorFlow 불러오는 중 (처음 한 번, 수 초 걸릴 수 있음)…"

    def _notice_first_tensorflow_load(self):
        """이 실행에서 TransNetV2 모델을 아직 불러오지 않았으면 진행 창에 안내를 쓰고 이벤트를 처리해 먼저 그려지게 함.
        워커의 첫 TensorFlow import는 몇 초 동안 GIL을 잡아 그동안 창이 다시 그려지지 않을 수 있음."""
        from yesoncheck.transnetv2_detector import transnetv2_model_loaded

        if transnetv2_model_loaded():
            return
        self.ocr_log_text.appendPlainText(self.FIRST_TENSORFLOW_LOAD_NOTICE)
        QApplication.processEvents()

    def run_ocr_analysis_range(self):
        """지정한 프레임 범위만 OCR 분석합니다."""
        print("[선택구간 분석] 시작됨")
        
        if self.ocr_worker and self.ocr_worker.isRunning():
            print("[선택구간 분석] 이미 OCR 진행 중")
            QMessageBox.information(self, "OCR 진행 중", "이미 OCR 분석이 실행 중입니다.")
            return

        # 사이드바 또는 Video A에서 비디오 경로 가져오기
        video_path = self.get_current_video_path()
        if not video_path:
            print("[선택구간 분석] 비디오 없음")
            QMessageBox.warning(self, "비디오 없음", "Video A를 먼저 로드하거나 사이드바에서 동영상을 선택해주세요.")
            return

        # OCR 분석 방식 확인 (먼저 확인)
        ocr_mode = self.ocrModeComboBox.currentData() if hasattr(self, 'ocrModeComboBox') else 'titmouse'

        # 애니매틱/애니매틱2 모드가 아닐 때만 ROI 체크
        if ocr_mode not in ['animatic', 'animatic2'] and not self.ocr_roi:
            print("[선택구간 분석] ROI 미지정")
            QMessageBox.warning(self, "ROI 미지정", "분석 전에 ROI를 지정해주세요.")
            return

        # 비디오 정보 가져오기 (lazy import)
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            QMessageBox.warning(self, "비디오 오류", "비디오를 열 수 없습니다.")
            return
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        
        # 시작/종료 프레임 입력받기
        start_frame, ok1 = QInputDialog.getInt(
            self, "시작 프레임", f"시작 프레임을 입력하세요 (1-{total_frames}):", 
            min=1, max=total_frames
        )
        if not ok1:
            print("[선택구간 분석] 시작 프레임 입력 취소")
            return
        
        end_frame, ok2 = QInputDialog.getInt(
            self, "종료 프레임", f"종료 프레임을 입력하세요 ({start_frame}-{total_frames}):", 
            min=start_frame, max=total_frames
        )
        if not ok2:
            print("[선택구간 분석] 종료 프레임 입력 취소")
            return
        
        print(f"[선택구간 분석] 프레임 범위: {start_frame}-{end_frame}")
        
        # 0-based로 변환
        start_frame_0based = start_frame - 1
        end_frame_0based = end_frame - 1
        
        if start_frame_0based >= end_frame_0based:
            print("[선택구간 분석] 프레임 범위 오류")
            QMessageBox.warning(self, "입력 오류", "시작 프레임이 종료 프레임보다 작아야 합니다.")
            return

        self.ocr_cancelled = False
        
        # 모드 전환 감지: 이전 모드와 다른 모드로 전환되면 모든 결과 초기화
        prev_ocr_mode = getattr(self, '_last_ocr_mode', None)
        if prev_ocr_mode is not None and prev_ocr_mode != ocr_mode:
            print(f"[선택구간 분석] 모드 전환: 이전 모드={prev_ocr_mode}, 새 모드={ocr_mode}, 모든 결과 초기화")
            # 모드 전환 시 모든 결과 완전히 초기화
            self.pending_ocr_metadata = None
            self.saved_edited_segments = None
            self.last_ocr_segments = []
            self._ocr_results_unsaved = False
            # 기존 다이얼로그도 닫기
            if hasattr(self, 'ocr_review_dialog') and self.ocr_review_dialog is not None:
                if self.ocr_review_dialog.isVisible():
                    self.ocr_review_dialog.close()
                self.ocr_review_dialog.deleteLater()
                self.ocr_review_dialog = None
        
        # OCR 모드 저장
        self._last_ocr_mode = ocr_mode

        # 현재 분석 중인 비디오 경로 저장 (save_ocr_result에서 사용)
        self._current_ocr_video_path = video_path

        # 애니매틱/애니매틱2 모드인 경우 전용 워커 사용
        if ocr_mode == 'animatic':
            # 애니매틱 모드: 선택 구간만 분석
            from .workers import SceneDetectWorker
            print(f"[선택구간 분석] 애니매틱 모드 - 프레임 {start_frame_0based}~{end_frame_0based}")
            self.ocr_worker = SceneDetectWorker(
                video_path,
                threshold=30.0,
                min_scene_len=15,
                start_frame=start_frame_0based,
                end_frame=end_frame_0based,
            )
        elif ocr_mode == 'animatic2':
            # 애니매틱2 모드: 선택 구간만 분석
            from .workers import TransNetV2Worker
            print(f"[선택구간 분석] 애니매틱2 모드 - 프레임 {start_frame_0based}~{end_frame_0based}")
            self.ocr_worker = TransNetV2Worker(
                video_path,
                threshold=0.3,
                min_scene_len=10,
                detect_gradual_transitions=True,
                post_process_histogram=True,
                start_frame=start_frame_0based,
                end_frame=end_frame_0based,
            )
        else:
            # OCR 모드
            tracking_enabled = self.ocrTrackingCheckBox.isChecked() if hasattr(self, 'ocrTrackingCheckBox') else False
            print(f"[선택구간 분석] OCR 모드: {ocr_mode}, 트래킹: {tracking_enabled}")

            if not self.ocr_roi:
                QMessageBox.warning(self, "ROI 미지정", "OCR 분석 전에 ROI를 지정해주세요.")
                return

            # OCRWorker lazy import
            from .workers import OCRWorker
            
            # All 모드일 때 패턴 가져오기
            pattern = None
            if ocr_mode == 'all':
                try:
                    if hasattr(self, 'ocrPatternLineEdit') and self.ocrPatternLineEdit is not None:
                        pattern = self.ocrPatternLineEdit.text().strip()
                        if not pattern:
                            QMessageBox.warning(self, "패턴 미입력", "All 모드를 사용하려면 패턴을 입력해주세요.\n예: ### WW#_#WW - #### W")
                            return
                    else:
                        QMessageBox.warning(self, "패턴 입력 필드 오류", "패턴 입력 필드를 찾을 수 없습니다.")
                        return
                except RuntimeError:
                    QMessageBox.warning(self, "패턴 입력 필드 오류", "패턴 입력 필드에 접근할 수 없습니다.")
                    return
            
            self.ocr_worker = OCRWorker(
                video_path,
                self.ocr_roi,
                tracking_enabled=tracking_enabled,
                start_frame=start_frame_0based,
                end_frame=end_frame_0based,
                ocr_mode=ocr_mode,
                pattern=pattern,
            )

        self.ocr_worker.progress.connect(self.on_ocr_progress)
        self.ocr_worker.status.connect(self.on_ocr_status)
        self.ocr_worker.error.connect(self.on_ocr_error)
        self.ocr_worker.completed.connect(self.on_ocr_analysis_range_completed)

        # OCR 분석 진행 다이얼로그 생성 (로그 표시 기능 포함)
        self.ocr_progress_dialog = QDialog(self)
        # 모드에 따라 다이얼로그 제목 변경
        if ocr_mode == 'animatic':
            self.ocr_progress_dialog.setWindowTitle("애니매틱 컷 감지 (선택 구간)")
        elif ocr_mode == 'animatic2':
            self.ocr_progress_dialog.setWindowTitle("애니매틱2 컷 감지 (선택 구간)")
        else:
            self.ocr_progress_dialog.setWindowTitle("OCR 분석 (선택 구간)")
        self.ocr_progress_dialog.setWindowModality(Qt.NonModal)
        self.ocr_progress_dialog.resize(500, 300)
        
        layout = QVBoxLayout(self.ocr_progress_dialog)
        
        # 진행률 표시
        self.ocr_progress_bar = QProgressBar()
        self.ocr_progress_bar.setRange(0, 100)
        self.ocr_progress_bar.setValue(0)
        layout.addWidget(self.ocr_progress_bar)
        
        # 로그 표시 영역
        self.ocr_log_text = QPlainTextEdit()
        self.ocr_log_text.setReadOnly(True)
        self.ocr_log_text.setStyleSheet(OCR_LOG_TEXT_STYLE)
        layout.addWidget(self.ocr_log_text)
        
        # 버튼 레이아웃
        button_layout = QHBoxLayout()
        
        # 취소 버튼 (진행 중일 때만 표시)
        self.ocr_cancel_button = QPushButton("취소")
        self.ocr_cancel_button.clicked.connect(self.cancel_ocr_analysis)
        button_layout.addWidget(self.ocr_cancel_button)
        
        button_layout.addStretch()
        
        # 닫기 버튼 (완료 후 표시)
        self.ocr_close_button = QPushButton("닫기")
        self.ocr_close_button.clicked.connect(self.close_ocr_progress_dialog)
        self.ocr_close_button.setEnabled(False)  # 초기에는 비활성화
        self.ocr_close_button.setVisible(False)  # 초기에는 숨김
        button_layout.addWidget(self.ocr_close_button)
        
        layout.addLayout(button_layout)
        
        self.ocr_log_text.appendPlainText(f"OCR 분석 중: 프레임 {start_frame}-{end_frame}")
        self.ocr_progress_dialog.show()

        if ocr_mode == 'animatic2':
            self._notice_first_tensorflow_load()

        print(f"[선택구간 분석] OCR 워커 시작...")
        # 로그는 팝업창에 표시되므로 여기서는 제거
        self.ocr_worker.start()

    def on_ocr_analysis_range_completed(self, result):
        """선택 구간 분석 완료 시 기존 결과에 병합"""
        print(f"[선택구간 분석 완료] result 타입: {type(result)}")
        
        # 완료 후에도 다이얼로그를 열어두어 로그를 볼 수 있도록 함
        if self.ocr_progress_dialog:
            # 진행률 100%로 설정
            if hasattr(self, 'ocr_progress_bar'):
                self.ocr_progress_bar.setValue(100)
            
            # 취소 버튼 숨기고 닫기 버튼 표시
            if hasattr(self, 'ocr_cancel_button'):
                self.ocr_cancel_button.setVisible(False)
            if hasattr(self, 'ocr_close_button'):
                self.ocr_close_button.setEnabled(True)
                self.ocr_close_button.setVisible(True)
            
            # 완료 메시지 추가
            if hasattr(self, 'ocr_log_text'):
                self.ocr_log_text.appendPlainText("\n[완료] 선택 구간 분석이 완료되었습니다. 로그를 확인한 후 닫기 버튼을 눌러주세요.")
                scrollbar = self.ocr_log_text.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
            
            # 다이얼로그를 자동으로 닫지 않음 (사용자가 닫기 버튼을 눌러야 함)
            # self.ocr_progress_dialog.close()  # 주석 처리
            # self.ocr_progress_dialog = None   # 주석 처리

        if self.ocr_worker:
            # 신호를 보낸 직후라 run()이 아직 안 끝났을 수 있음 → 끝날 때까지 붙잡아 두었다가 지움
            release_worker(self.ocr_worker, "OCR 분석·컷 감지")
            self.ocr_worker = None

        was_cancelled = bool(result.get("cancelled")) if isinstance(result, dict) else False
        self.ocr_cancelled = False
        
        if was_cancelled:
            print("[선택구간 분석] 취소됨")
            QMessageBox.information(self, "OCR 취소", "사용자가 OCR 분석을 취소했습니다.")
            self.update_ocr_status_label("OCR: 취소되었습니다.")
            return

        segments = result.get("segments", []) if isinstance(result, dict) else []
        fps = result.get("fps") if isinstance(result, dict) else None
        total_frames = result.get("total_frames") if isinstance(result, dict) else None
        
        # pending_ocr_metadata에 ocr_mode 저장
        if isinstance(result, dict):
            # 현재 분석 모드를 metadata에 저장
            ocr_mode = getattr(self, '_last_ocr_mode', 'titmouse')
            result['ocr_mode'] = ocr_mode
            if not hasattr(self, 'pending_ocr_metadata') or self.pending_ocr_metadata is None:
                self.pending_ocr_metadata = {}
            if isinstance(self.pending_ocr_metadata, dict):
                self.pending_ocr_metadata['ocr_mode'] = ocr_mode
        
        # 씬 감지 완료 후 각 씬의 첫 프레임 썸네일을 미리 추출 (애니매틱/애니매틱2 모드만)
        self._preload_scene_thumbnails(segments)
        
        print(f"[선택구간 분석] 세그먼트 개수: {len(segments)}")

        if not segments:
            print("[선택구간 분석] 세그먼트 없음")
            QMessageBox.information(self, "OCR 결과", "선택한 구간에서 변경된 텍스트 구간을 찾지 못했습니다.")
            self.update_ocr_status_label("OCR: 결과 없음")
            return

        # OCRReviewDialog가 이미 열려있으면 기존 다이얼로그에 결과 추가
        # 닫혀있으면 새로 생성
        dialog_exists = hasattr(self, 'ocr_review_dialog') and self.ocr_review_dialog is not None
        dialog_visible = dialog_exists and self.ocr_review_dialog.isVisible()
        print(f"[선택구간 분석] 다이얼로그 존재: {dialog_exists}, 표시 중: {dialog_visible}")
        
        if dialog_exists and dialog_visible:
            # 기존 다이얼로그의 모드와 현재 분석 모드가 같은지 확인
            current_ocr_mode = getattr(self, '_last_ocr_mode', 'titmouse')
            dialog_ocr_mode = getattr(self.ocr_review_dialog, 'ocr_mode', None)
            
            if dialog_ocr_mode == current_ocr_mode:
                print(f"[선택구간 분석] 기존 다이얼로그에 {len(segments)}개 세그먼트 추가 중...")
                # 기존 다이얼로그가 열려있으면 테이블에 새 세그먼트 추가
                # 다이얼로그의 현재 상태(수정된 내용 포함)를 반영하여 병합
                self.ocr_review_dialog.add_segments_to_table(segments)
                
                # 병합된 결과를 saved_edited_segments와 last_ocr_segments에 저장
                merged_segments = self.ocr_review_dialog.collect_segments()
                print(f"[선택구간 분석] 병합 후 총 세그먼트 개수: {len(merged_segments)}")
                self.saved_edited_segments = merged_segments
                self.last_ocr_segments = merged_segments
                self._ocr_results_unsaved = True
                
                # 저장 버튼 활성화
                if hasattr(self, 'ocrSaveResultButton'):
                    self.ocrSaveResultButton.setEnabled(True)
                    print("[선택구간 분석] 저장 버튼 활성화됨")
                
                self.update_ocr_status_label("OCR: 선택 구간 분석 결과가 기존 결과에 추가되었습니다.")
                QMessageBox.information(self, "선택 구간 분석 완료", f"{len(segments)}개의 새로운 구간이 추가되었습니다.\n총 {len(merged_segments)}개 구간")
                return  # 다이얼로그에 추가했으므로 여기서 종료
            else:
                # 다른 모드의 다이얼로그가 열려있으면 닫고 새로 생성
                print(f"[선택구간 분석] 모드 불일치: 다이얼로그={dialog_ocr_mode}, 현재={current_ocr_mode}, 다이얼로그 닫고 새로 생성")
                self.ocr_review_dialog.close()
                self.ocr_review_dialog.deleteLater()
                dialog_exists = False
                dialog_visible = False
        else:
            # 다이얼로그가 닫혀있으면 새로 생성
            # 기존 결과가 있으면 병합 (saved_edited_segments 우선, 없으면 last_ocr_segments 사용)
            # 단, 같은 모드의 결과만 병합 (모드 전환 시 섞임 방지)
            existing_segments = None
            current_ocr_mode = getattr(self, '_last_ocr_mode', 'titmouse')
            prev_mode = None
            if hasattr(self, 'pending_ocr_metadata') and isinstance(self.pending_ocr_metadata, dict):
                prev_mode = self.pending_ocr_metadata.get('ocr_mode')
            
            # 같은 모드의 결과만 사용
            if prev_mode == current_ocr_mode:
                if hasattr(self, 'saved_edited_segments') and self.saved_edited_segments:
                    # 수정된 내용이 있으면 그것을 사용
                    existing_segments = self.saved_edited_segments
                elif hasattr(self, 'last_ocr_segments') and self.last_ocr_segments:
                    # 수정된 내용이 없으면 원본 분석 결과 사용
                    existing_segments = self.last_ocr_segments
            else:
                # 다른 모드의 결과는 무시하고 완전히 초기화
                print(f"[선택구간 분석] 모드 불일치: 이전={prev_mode}, 현재={current_ocr_mode}, 이전 결과 무시 및 초기화")
                self.saved_edited_segments = None
                self.last_ocr_segments = []
                self._ocr_results_unsaved = False
                # 새로운 분석 결과만 사용 (existing_segments는 None으로 유지)
            
            if existing_segments:
                # 기존 세그먼트와 새 세그먼트 병합 (프레임 순서대로 정렬)
                merged_segments = existing_segments + segments
                def sort_key(seg):
                    start_frame = seg.get('start_frame', 0)
                    text = seg.get('text', '').strip()
                    normalized_text = text.replace(' ', '_').replace('-', '_').upper()
                    def natural_key(norm_text):
                        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', norm_text)]
                    return (start_frame, natural_key(normalized_text), text)
                merged_segments.sort(key=sort_key)
                segments = merged_segments
                self.last_ocr_segments = segments
                self._ocr_results_unsaved = True
                self.saved_edited_segments = segments  # 저장 시 최신 상태 반영
            else:
                # 기존 결과가 없으면 새 결과만 사용
                self.last_ocr_segments = segments
                self._ocr_results_unsaved = True
                self.saved_edited_segments = segments  # 저장 시 최신 상태 반영
                self.pending_ocr_metadata = result
            
            if hasattr(self, 'ocr_review_dialog') and self.ocr_review_dialog is not None:
                self.ocr_review_dialog.close()
                self.ocr_review_dialog.deleteLater()

            # OCR 모드 가져오기 (pending_ocr_metadata에서 가져오거나, 현재 선택된 모드 사용)
            ocr_mode = None
            if hasattr(self, 'pending_ocr_metadata') and isinstance(self.pending_ocr_metadata, dict):
                ocr_mode = self.pending_ocr_metadata.get('ocr_mode')
            if ocr_mode is None:
                ocr_mode = self.ocrModeComboBox.currentData() if hasattr(self, 'ocrModeComboBox') else 'titmouse'
            # OCRReviewDialog lazy import
            from yesoncheck.player_review import OCRReviewDialog
            self.ocr_review_dialog = OCRReviewDialog(self, segments, fps=fps, total_frames=total_frames, ocr_mode=ocr_mode)
            self.ocr_review_dialog.accepted.connect(self.on_ocr_review_accepted)
            self.ocr_review_dialog.rejected.connect(self.on_ocr_review_rejected)
            # 다이얼로그가 닫힐 때 항상 상태 저장 (X 버튼으로 닫아도)
            self.ocr_review_dialog.finished.connect(self.on_ocr_review_finished)
            self.ocr_review_dialog.show()
            self.update_ocr_status_label("OCR: 결과를 검토 중입니다. 필요하면 ROI를 조정해 다시 분석하세요.")
        
        # "OCR 오픈" 및 "OCR 저장" 버튼 활성화
        if hasattr(self, 'ocrReopenResultButton'):
            self.ocrReopenResultButton.setEnabled(True)
        if hasattr(self, 'ocrSaveResultButton'):
            self.ocrSaveResultButton.setEnabled(True)
            print("[선택구간 분석] 저장/오픈 버튼 활성화됨 (새 다이얼로그)")

    def on_ocr_progress(self, value):
        if self.ocr_progress_dialog and hasattr(self, 'ocr_progress_bar'):
            self.ocr_progress_bar.setValue(value)

    def on_ocr_status(self, message):
        # OCR 분석 팝업창에 로그 표시
        if self.ocr_progress_dialog and hasattr(self, 'ocr_log_text'):
            self.ocr_log_text.appendPlainText(f"OCR: {message}")
            # 자동 스크롤
            scrollbar = self.ocr_log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def on_ocr_error(self, message):
        # OCR 분석 팝업창에 오류 로그 표시
        if self.ocr_progress_dialog and hasattr(self, 'ocr_log_text'):
            self.ocr_log_text.appendPlainText(f"오류: {message}")
            scrollbar = self.ocr_log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        if self.ocr_progress_dialog:
            self.ocr_progress_dialog.close()
            self.ocr_progress_dialog = None
        if self.ocr_worker:
            # 신호를 보낸 직후라 run()이 아직 안 끝났을 수 있음 → 끝날 때까지 붙잡아 두었다가 지움
            release_worker(self.ocr_worker, "OCR 분석·컷 감지")
            self.ocr_worker = None
        self.ocr_cancelled = False
        QMessageBox.critical(self, "OCR 오류", message)

    def on_ocr_completed(self, result):
        # 완료 후에도 다이얼로그를 열어두어 로그를 볼 수 있도록 함
        if self.ocr_progress_dialog:
            # 진행률 100%로 설정
            if hasattr(self, 'ocr_progress_bar'):
                self.ocr_progress_bar.setValue(100)
            
            # 취소 버튼 숨기고 닫기 버튼 표시
            try:
                # 취소 버튼 숨기기
                if hasattr(self, 'ocr_cancel_button') and self.ocr_cancel_button:
                    self.ocr_cancel_button.setVisible(False)
                    self.ocr_cancel_button.setEnabled(False)
                
                # 닫기 버튼 표시
                if hasattr(self, 'ocr_close_button') and self.ocr_close_button:
                    self.ocr_close_button.setEnabled(True)
                    self.ocr_close_button.setVisible(True)
                    self.ocr_close_button.raise_()  # 버튼을 맨 앞으로
                else:
                    # 버튼이 없으면 레이아웃에서 찾아서 생성
                    layout = self.ocr_progress_dialog.layout()
                    if layout:
                        # 버튼 레이아웃 찾기
                        button_layout = None
                        for i in range(layout.count()):
                            item = layout.itemAt(i)
                            if item and item.layout() and isinstance(item.layout(), QHBoxLayout):
                                button_layout = item.layout()
                                break
                        
                        if button_layout:
                            # 닫기 버튼 생성 및 추가
                            from PyQt5.QtWidgets import QPushButton
                            self.ocr_close_button = QPushButton("닫기")
                            self.ocr_close_button.clicked.connect(self.close_ocr_progress_dialog)
                            button_layout.addWidget(self.ocr_close_button)
                            
                            # 취소 버튼 찾아서 숨기기
                            for i in range(button_layout.count()):
                                item = button_layout.itemAt(i)
                                if item and item.widget():
                                    widget = item.widget()
                                    if widget.text() == "취소":
                                        widget.setVisible(False)
                                        widget.setEnabled(False)
                                        if not hasattr(self, 'ocr_cancel_button'):
                                            self.ocr_cancel_button = widget
            except Exception as e:
                import traceback
                print(f"[디버그] 닫기 버튼 처리 중 오류: {e}")
                traceback.print_exc()
            
            # 완료 메시지 추가
            if hasattr(self, 'ocr_log_text'):
                self.ocr_log_text.appendPlainText("\n[완료] 컷 감지가 완료되었습니다. 로그를 확인한 후 닫기 버튼을 눌러주세요.")
                scrollbar = self.ocr_log_text.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
            
            # 다이얼로그를 자동으로 닫지 않음 (사용자가 닫기 버튼을 눌러야 함)
            # self.ocr_progress_dialog.close()  # 주석 처리
            # self.ocr_progress_dialog = None   # 주석 처리

        if self.ocr_worker:
            # 신호를 보낸 직후라 run()이 아직 안 끝났을 수 있음 → 끝날 때까지 붙잡아 두었다가 지움
            release_worker(self.ocr_worker, "OCR 분석·컷 감지")
            self.ocr_worker = None

        was_cancelled = bool(result.get("cancelled")) if isinstance(result, dict) else False
        self.ocr_cancelled = False
        self.pending_ocr_metadata = result
        # pending_ocr_metadata에 ocr_mode 저장 (reopen_ocr_result에서 사용)
        if isinstance(result, dict):
            # 현재 분석 모드를 metadata에 저장
            ocr_mode = getattr(self, '_last_ocr_mode', 'titmouse')
            result['ocr_mode'] = ocr_mode
            self.pending_ocr_metadata['ocr_mode'] = ocr_mode
        segments = result.get("segments", []) if isinstance(result, dict) else []
        fps = result.get("fps") if isinstance(result, dict) else None
        total_frames = result.get("total_frames") if isinstance(result, dict) else None

        # 씬 감지 완료 후 썸네일 미리 추출 (애니매틱/애니매틱2)
        self._preload_scene_thumbnails(segments)
        self.last_ocr_segments = segments
        self._ocr_results_unsaved = bool(segments) and not was_cancelled  # 취소한 분석의 일부 결과는 보여 주지 않음

        if was_cancelled:
            QMessageBox.information(self, "OCR 취소", "사용자가 OCR 분석을 취소했습니다.")
            self.update_ocr_status_label("OCR: 취소되었습니다.")
            return

        if not segments:
            QMessageBox.information(self, "OCR 결과", "변경된 텍스트 구간을 찾지 못했습니다.")
            self.update_ocr_status_label("OCR: 결과 없음")
            return
        
        # 디버깅: segments의 text 필드 확인 및 수정
        for segment in segments:
            text = segment.get("text", "")
            detections = segment.get("detections", [])
            # text가 비어있거나 "<미검출>"이면 detections에서 추출
            if not text or text == "<미검출>":
                if detections:
                    detected_texts = []
                    for det in detections:
                        if isinstance(det, dict) and det.get("text"):
                            detected_texts.append(det.get("text"))
                    if detected_texts:
                        segment["text"] = "\n".join(detected_texts)
            # edited_text 초기화 (text와 동일하게)
            if "edited_text" not in segment or not segment["edited_text"]:
                segment["edited_text"] = segment.get("text", "")

        # 이전에 저장된 수정된 segments가 있으면 사용 (재오픈 시)
        # 단, 같은 모드의 결과만 사용 (모드 전환 시 섞임 방지)
        current_ocr_mode = getattr(self, '_last_ocr_mode', 'titmouse')
        if hasattr(self, 'saved_edited_segments') and self.saved_edited_segments:
            # pending_ocr_metadata에서 이전 결과의 모드 확인
            prev_mode = None
            if hasattr(self, 'pending_ocr_metadata') and isinstance(self.pending_ocr_metadata, dict):
                prev_mode = self.pending_ocr_metadata.get('ocr_mode')
            # 같은 모드의 결과만 사용
            if prev_mode == current_ocr_mode:
                segments = self.saved_edited_segments
            else:
                # 다른 모드의 결과는 무시하고 완전히 초기화 (새로운 분석 결과 사용)
                print(f"[OCR 완료] 모드 불일치: 이전={prev_mode}, 현재={current_ocr_mode}, 이전 결과 무시 및 초기화")
                self.saved_edited_segments = None
                self.last_ocr_segments = []
                # 새로운 분석 결과만 사용 (segments는 그대로 사용)
        
        # "마지막 OCR 결과 보기" 및 "OCR 저장" 버튼 활성화
        if hasattr(self, 'ocrReopenResultButton'):
            self.ocrReopenResultButton.setEnabled(True)
        if hasattr(self, 'ocrSaveResultButton'):
            self.ocrSaveResultButton.setEnabled(True)
        
        # 기존 다이얼로그가 열려있으면 모드 확인 후 처리
        if hasattr(self, 'ocr_review_dialog') and self.ocr_review_dialog is not None:
            if self.ocr_review_dialog.isVisible():
                # 기존 다이얼로그의 모드와 현재 분석 모드가 같은지 확인
                dialog_ocr_mode = getattr(self.ocr_review_dialog, 'ocr_mode', None)
                current_ocr_mode = getattr(self, '_last_ocr_mode', 'titmouse')
                if dialog_ocr_mode != current_ocr_mode:
                    # 다른 모드의 다이얼로그가 열려있으면 닫고 새로 생성
                    print(f"[OCR 완료] 모드 불일치: 다이얼로그={dialog_ocr_mode}, 현재={current_ocr_mode}, 다이얼로그 닫고 새로 생성")
                    self.ocr_review_dialog.close()
                    self.ocr_review_dialog.deleteLater()
                else:
                    # 같은 모드면 기존 다이얼로그 내용을 업데이트하고 최상단으로 올림
                    if fps: self.ocr_review_dialog.fps = fps
                    if total_frames: self.ocr_review_dialog.total_frames = total_frames
                    self.ocr_review_dialog.populate_table(segments)
                    
                    self.ocr_review_dialog.raise_()
                    self.ocr_review_dialog.activateWindow()
                    return  # 기존 다이얼로그 사용
        
        # Non-modal dialog로 표시하여 백그라운드 작업 허용 (lazy import)
        from yesoncheck.player_review import OCRReviewDialog
        # OCR 모드 가져오기 (pending_ocr_metadata에서 가져오거나, 저장된 세그먼트의 경우 기본값 사용)
        ocr_mode = None
        if isinstance(self.pending_ocr_metadata, dict):
            ocr_mode = self.pending_ocr_metadata.get('ocr_mode')
        if ocr_mode is None:
            ocr_mode = getattr(self, '_last_ocr_mode', 'titmouse')
        self.ocr_review_dialog = OCRReviewDialog(self, segments, fps=fps, total_frames=total_frames, ocr_mode=ocr_mode)
        self.ocr_review_dialog.accepted.connect(self.on_ocr_review_accepted)
        self.ocr_review_dialog.rejected.connect(self.on_ocr_review_rejected)
        # 다이얼로그가 닫힐 때 항상 상태 저장 (X 버튼으로 닫아도)
        self.ocr_review_dialog.finished.connect(self.on_ocr_review_finished)
        self.ocr_review_dialog.show()
        self.update_ocr_status_label("OCR: 결과를 검토 중입니다. 필요하면 ROI를 조정해 다시 분석하세요.")
    
    def on_ocr_review_accepted(self):
        """OCR 검토 dialog에서 확인을 누른 경우"""
        if not hasattr(self, 'ocr_review_dialog') or self.ocr_review_dialog is None:
            return
        
        # 선택 항목만 내보내기인 경우 _result_segments를 사용, 아니면 전체 세그먼트 수집
        if hasattr(self.ocr_review_dialog, '_result_segments') and self.ocr_review_dialog._result_segments is not None:
            # 선택 항목만 내보내기
            reviewed_segments = self.ocr_review_dialog._result_segments
        else:
            # 전체 내보내기 - collect_segments()를 사용하여 테이블의 현재 상태를 정확히 반영
            reviewed_segments = self.ocr_review_dialog.collect_segments()
        
        # 사운드 옵션 가져오기
        include_audio = getattr(self.ocr_review_dialog, '_include_audio', True)
        # 내보내기 모드 가져오기
        export_mode = getattr(self.ocr_review_dialog, '_export_mode', 'balanced')
        # 비트레이트 가져오기 (fast 모드일 때만)
        bitrate = getattr(self.ocr_review_dialog, '_bitrate', None)
        
        # 현재 상태를 저장 (다시 열 때 사용) - 전체 내보내기인 경우에만 저장
        # 선택 항목만 내보내기인 경우는 전체 세그먼트를 저장하지 않음
        if not (hasattr(self.ocr_review_dialog, '_result_segments') and self.ocr_review_dialog._result_segments is not None):
            self.saved_edited_segments = reviewed_segments
            self.last_ocr_segments = reviewed_segments  # 동일한 세그먼트로 동기화
        
        self.ocr_review_dialog.deleteLater()
        self.ocr_review_dialog = None
        
        if not reviewed_segments:
            QMessageBox.warning(self, "내보낼 구간 없음", "모든 구간이 제거되어 내보낼 항목이 없습니다.")
            self.update_ocr_status_label("OCR: 내보낼 구간이 없습니다.")
            return
        
        self.update_ocr_status_label("OCR: 내보내기 준비 중…")
        self.prompt_ocr_export(reviewed_segments, include_audio, export_mode, bitrate)
    
    def on_ocr_review_rejected(self):
        """OCR 검토 dialog에서 취소(재분석)를 누른 경우"""
        if hasattr(self, 'ocr_review_dialog') and self.ocr_review_dialog is not None:
            # 현재 수정된 segments를 저장 (다시 열 때 사용)
            self.saved_edited_segments = self.ocr_review_dialog.collect_segments()
            self.ocr_review_dialog.deleteLater()
            self.ocr_review_dialog = None
        self.update_ocr_status_label("OCR: 결과를 검토 중입니다. 필요하면 ROI를 조정해 다시 분석하세요.")
    
    def on_ocr_review_finished(self, result_code):
        """OCR 검토 dialog가 닫힐 때 호출 (accepted, rejected, X 버튼 모두 포함)"""
        if hasattr(self, 'ocr_review_dialog') and self.ocr_review_dialog:
            # 다이얼로그가 닫힐 때 항상 현재 상태 저장
            try:
                current_segments = self.ocr_review_dialog.collect_segments()
                if current_segments:
                    self.saved_edited_segments = current_segments
                    # last_ocr_segments도 업데이트 (최신 상태 유지)
                    self.last_ocr_segments = current_segments
            except Exception as e:
                pass

    def close_ocr_progress_dialog(self):
        """OCR 진행 다이얼로그 닫기"""
        if self.ocr_progress_dialog:
            self.ocr_progress_dialog.close()
            self.ocr_progress_dialog = None
    
    def cancel_ocr_analysis(self):
        if self.ocr_progress_dialog and hasattr(self, 'ocr_log_text'):
            self.ocr_log_text.appendPlainText("OCR: 취소 중…")
        if self.ocr_worker and self.ocr_worker.isRunning():
            self.ocr_cancelled = True
            self.ocr_worker.stop()
    
    def reopen_ocr_result(self):
        """이전에 분석한 OCR 결과를 다시 엽니다"""
        # 원본 분석 결과가 없으면 오류 메시지 표시
        if not hasattr(self, 'last_ocr_segments') or not self.last_ocr_segments:
            QMessageBox.information(self, "결과 없음", "다시 열 OCR 결과가 없습니다. 먼저 OCR 분석을 실행하세요.")
            return
        
        # 저장된 수정 내용이 있으면 그것을 우선 사용 (병합, 삭제 등 모든 변경사항 포함)
        # 없으면 원본 분석 결과 사용
        if hasattr(self, 'saved_edited_segments') and self.saved_edited_segments:
            segments = copy.deepcopy(self.saved_edited_segments)
        else:
            segments = copy.deepcopy(self.last_ocr_segments)
        
        # pending_ocr_metadata에서 fps와 total_frames 정보 가져오기
        fps = None
        total_frames = None
        if hasattr(self, 'pending_ocr_metadata') and self.pending_ocr_metadata:
            fps = self.pending_ocr_metadata.get('fps')
            total_frames = self.pending_ocr_metadata.get('total_frames')
        
        # fps와 total_frames가 없으면 현재 비디오에서 가져오기
        if fps is None:
            fps = self.fps if hasattr(self, 'fps') and self.fps else 24.0
        if total_frames is None:
            total_frames = self.total_frames_a if hasattr(self, 'total_frames_a') and self.total_frames_a else 1
        
        # 기존 다이얼로그가 열려있으면 최상단으로 올리기
        if hasattr(self, 'ocr_review_dialog') and self.ocr_review_dialog is not None:
            if self.ocr_review_dialog.isVisible():
                # 이미 열려있으면 최상단으로 올리기
                self.ocr_review_dialog.raise_()
                self.ocr_review_dialog.activateWindow()
                return
        
        # OCRReviewDialog 다시 열기 (lazy import)
        from yesoncheck.player_review import OCRReviewDialog
        # OCR 모드 가져오기 (pending_ocr_metadata에서 가져오거나, 저장된 세그먼트의 경우 기본값 사용)
        ocr_mode = None
        if hasattr(self, 'pending_ocr_metadata') and isinstance(self.pending_ocr_metadata, dict):
            ocr_mode = self.pending_ocr_metadata.get('ocr_mode')
        if ocr_mode is None:
            ocr_mode = getattr(self, '_last_ocr_mode', 'titmouse')
        self.ocr_review_dialog = OCRReviewDialog(self, segments, fps=fps, total_frames=total_frames, ocr_mode=ocr_mode)
        self.ocr_review_dialog.accepted.connect(self.on_ocr_review_accepted)
        self.ocr_review_dialog.rejected.connect(self.on_ocr_review_rejected)
        # 다이얼로그가 닫힐 때 항상 상태 저장 (X 버튼으로 닫아도)
        self.ocr_review_dialog.finished.connect(self.on_ocr_review_finished)
        self.ocr_review_dialog.show()
        self.ocr_review_dialog.raise_()
        self.ocr_review_dialog.activateWindow()
        self.update_ocr_status_label("OCR: 결과를 검토 중입니다.")

    def _load_all_thumbnails_for_save(self):
        """
        저장 전에 모든 썸네일을 강제로 로드 (Lazy loading 문제 해결)

        Lazy loading으로 인해 화면에 표시되지 않은 행의 썸네일이 메모리에 없을 수 있습니다.
        이 메서드는 저장 전에 모든 행의 썸네일을 segment_images에 로드합니다.
        """
        if not hasattr(self, 'ocr_review_dialog') or self.ocr_review_dialog is None:
            print("[OCR 저장] OCR 검토 다이얼로그가 없습니다.")
            return

        from PyQt5.QtCore import QBuffer, QIODevice, Qt
        import cv2

        total_rows = self.ocr_review_dialog.table.rowCount()
        loaded_count = 0
        extracted_count = 0
        skipped_count = 0

        print(f"[OCR 저장] 총 {total_rows}개 행의 썸네일 로드 시작...")

        # segment_images 리스트 크기가 부족하면 확장
        while len(self.ocr_review_dialog.segment_images) < total_rows:
            self.ocr_review_dialog.segment_images.append(None)

        for row in range(total_rows):
            # 이미 썸네일이 있으면 스킵
            if row < len(self.ocr_review_dialog.segment_images) and self.ocr_review_dialog.segment_images[row]:
                skipped_count += 1
                continue

            # 1. 테이블 위젯에서 썸네일 읽기 시도
            thumb_widget = self.ocr_review_dialog.table.cellWidget(row, 1)
            if thumb_widget:
                thumb_label = thumb_widget.findChild(QLabel)
                if thumb_label and thumb_label.pixmap():
                    # 테이블 위젯의 pixmap을 PNG 바이트로 변환
                    pixmap = thumb_label.property('original_pixmap')
                    if not pixmap:
                        pixmap = thumb_label.pixmap()

                    if pixmap:
                        buffer = QBuffer()
                        buffer.open(QIODevice.WriteOnly)
                        pixmap.save(buffer, 'PNG')
                        roi_bytes = buffer.data().data()
                        buffer.close()

                        # segment_images 업데이트
                        self.ocr_review_dialog.segment_images[row] = roi_bytes
                        loaded_count += 1
                        continue

            # 2. 위젯에 썸네일이 없으면 비디오에서 추출 (애니매틱/애니매틱2 모드만)
            ocr_mode = getattr(self.ocr_review_dialog, 'ocr_mode', 'titmouse')
            if ocr_mode in ['animatic', 'animatic2']:
                video_path = self.ocr_review_dialog.video_path
                if video_path and os.path.exists(video_path):
                    # 테이블에서 start_frame 가져오기
                    start_frame_item = self.ocr_review_dialog.table.item(row, 4)
                    if start_frame_item:
                        start_frame = start_frame_item.data(Qt.UserRole)
                        if start_frame is not None:
                            # 비디오에서 프레임 추출
                            roi_bytes = self.ocr_review_dialog._extract_frame_thumbnail(video_path, start_frame)
                            if roi_bytes:
                                self.ocr_review_dialog.segment_images[row] = roi_bytes
                                extracted_count += 1
                                if extracted_count % 10 == 0:
                                    print(f"[OCR 저장] 진행: {extracted_count}개 프레임 추출 완료...")

        print(f"[OCR 저장] 썸네일 로드 완료: 총 {total_rows}개 중")
        print(f"  - 이미 로드됨: {skipped_count}개")
        print(f"  - 위젯에서 로드: {loaded_count}개")
        print(f"  - 비디오에서 추출: {extracted_count}개")

    def save_ocr_result(self):
        """OCR 분석 결과를 JSON 파일로 저장"""
        # OCR 검토 창이 열려있으면 최신 상태를 가져옴
        if hasattr(self, 'ocr_review_dialog') and self.ocr_review_dialog is not None and self.ocr_review_dialog.isVisible():
            try:
                # 저장 전에 모든 썸네일을 강제로 로드 (Lazy loading 문제 해결)
                print(f"[OCR 저장] 모든 썸네일 로드 시작...")
                self._load_all_thumbnails_for_save()
                print(f"[OCR 저장] 모든 썸네일 로드 완료")

                # 검토 창에서 현재 상태를 collect하여 저장
                current_segments = self.ocr_review_dialog.collect_segments()
                print(f"[DEBUG] OCR 검토 창 열려있음, collect_segments 결과: {len(current_segments)}개 세그먼트")
                if current_segments:
                    self.saved_edited_segments = current_segments
                    segments_to_save = current_segments
                else:
                    segments_to_save = self.saved_edited_segments if hasattr(self, 'saved_edited_segments') else self.last_ocr_segments
                    print(f"[DEBUG] collect_segments가 비어있음, fallback 사용: {len(segments_to_save)}개")
            except Exception as e:
                print(f"검토 창에서 segments 수집 실패: {e}")
                segments_to_save = self.saved_edited_segments if hasattr(self, 'saved_edited_segments') else self.last_ocr_segments
        elif not hasattr(self, 'saved_edited_segments') or not self.saved_edited_segments:
            if not hasattr(self, 'last_ocr_segments') or not self.last_ocr_segments:
                QMessageBox.warning(self, "저장할 결과 없음", "저장할 OCR 분석 결과가 없습니다. 먼저 OCR 분석을 실행하세요.")
                return
            segments_to_save = self.last_ocr_segments
            print(f"[DEBUG] saved_edited_segments 없음, last_ocr_segments 사용: {len(segments_to_save)}개")
        else:
            segments_to_save = self.saved_edited_segments
            print(f"[DEBUG] saved_edited_segments 사용: {len(segments_to_save)}개")
        
        # 현재 분석한 비디오 경로 사용 (사이드바 또는 Video A)
        current_video_path = getattr(self, '_current_ocr_video_path', None) or self.get_current_video_path() or self.filename_a
        default_dir = os.path.dirname(current_video_path) if current_video_path else os.path.expanduser("~")
        default_filename = os.path.splitext(os.path.basename(current_video_path))[0] + "_ocr_result.json" if current_video_path else "ocr_result.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "OCR 결과 저장",
            os.path.join(default_dir, default_filename),
            "JSON Files (*.json)"
        )
        
        if not file_path:
            return
        try:
            # 결과 파일에 적을 영상 경로 (Mac: 제자리가 아닌 곳에 붙은 공유는 공유 설정의 Mac 경로). 정하지 못하면 저장하지
            # 않음 — 이미지 폴더를 만들기 전에 (이 Mac에서만 열리는 /mnt… 경로를 적지 않게)
            stored_video_path = paths.to_storage(current_video_path)
        except paths.PathMapError as exc:
            QMessageBox.critical(
                self, "저장 실패",
                f"OCR 결과에 적을 영상 경로를 정하지 못해 저장하지 않았습니다:\n{current_video_path}\n\n{exc}",
            )
            return
        
        try:
            # ROI 이미지를 별도 폴더에 저장
            import cv2
            
            # 이미지 폴더 경로 생성 (JSON 파일명_images)
            json_dir = os.path.dirname(file_path)
            json_basename = os.path.splitext(os.path.basename(file_path))[0]
            images_dir = os.path.join(json_dir, f"{json_basename}_images")
            
            # 이미지 폴더 생성
            if not os.path.exists(images_dir):
                os.makedirs(images_dir)
            
            # OCR 모드 가져오기 (pending_ocr_metadata에서 가져오거나, 현재 선택된 모드 사용)
            ocr_mode = None
            if hasattr(self, 'pending_ocr_metadata') and isinstance(self.pending_ocr_metadata, dict):
                ocr_mode = self.pending_ocr_metadata.get('ocr_mode')
            if ocr_mode is None:
                ocr_mode = getattr(self, '_last_ocr_mode', 'titmouse')
            save_data = {
                "video_path": stored_video_path,
                "roi": self.ocr_roi if hasattr(self, 'ocr_roi') and self.ocr_roi else None,
                "fps": self.fps if hasattr(self, 'fps') and self.fps else 24.0,
                "total_frames": self.total_frames_a if hasattr(self, 'total_frames_a') and self.total_frames_a else 1,
                "ocr_mode": ocr_mode,  # OCR 모드 저장
                "segments": []
            }
            
            image_failures = []
            for idx, segment in enumerate(segments_to_save):
                text = segment.get("text", "")
                edited_text = segment.get("edited_text", "")
                detections = segment.get("detections", [])
                
                # text와 edited_text가 모두 "<미검출>"이거나 비어있으면 detections에서 추출
                if (not text or text == "<미검출>") and (not edited_text or edited_text == "<미검출>"):
                    if detections:
                        detected_texts = []
                        for det in detections:
                            if isinstance(det, dict) and det.get("text"):
                                detected_texts.append(det.get("text"))
                        if detected_texts:
                            text = "\n".join(detected_texts)
                            edited_text = text
                        else:
                            # detections도 비어있으면 둘 다 "<미검출>"
                            text = "<미검출>"
                            edited_text = "<미검출>"
                    else:
                        # detections 자체가 없으면 둘 다 "<미검출>"
                        text = "<미검출>"
                        edited_text = "<미검출>"
                else:
                    # edited_text가 비어있거나 "<미검출>"이면 text를 사용
                    if not edited_text or edited_text == "<미검출>":
                        edited_text = text if text and text != "<미검출>" else "<미검출>"
                    
                    # text가 비어있거나 "<미검출>"이면 edited_text를 사용
                    if not text or text == "<미검출>":
                        text = edited_text if edited_text and edited_text != "<미검출>" else "<미검출>"
                
                segment_data = {
                    "text": text,
                    "edited_text": edited_text,
                    "start_frame": segment.get("start_frame", 0),
                    "end_frame": segment.get("end_frame", 0),
                    "start_time": segment.get("start_time", 0.0),
                    "end_time": segment.get("end_time", 0.0),
                    "duration": segment.get("duration", 0.0),
                }
                
                # ROI 이미지를 리사이즈하여 저장 (로딩 속도 향상을 위해)
                if segment.get("roi_image"):
                    # JPEG로 저장하여 파일 크기 감소 (기존 PNG 대비 10배 이상 작음)
                    image_filename = f"segment_{idx:04d}.jpg"
                    image_path = os.path.join(images_dir, image_filename)
                    try:
                        # bytes를 numpy array로 변환
                        import numpy as np
                        nparr = np.frombuffer(segment["roi_image"], np.uint8)
                        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if img is not None:
                            h, w = img.shape[:2]
                            
                            # 애니매틱/애니매틱2 모드에서만 썸네일 슬라이더 최대값(384×216)으로 제한
                            # OCR 모드에서는 원본 해상도 유지 (더 높은 품질 필요)
                            if ocr_mode in ['animatic', 'animatic2']:
                                # 애니매틱/애니매틱2 모드: UI에서 최대 384×216으로 표시되므로 저장도 동일한 크기로 제한
                                max_width = 384
                                max_height = 216

                                # 리사이즈 필요 여부 확인
                                if w > max_width or h > max_height:
                                    scale = min(max_width / w, max_height / h)
                                    new_w = int(w * scale)
                                    new_h = int(h * scale)
                                    # INTER_AREA: 축소 시 품질 유지에 적합
                                    img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
                                    mode_name = '애니매틱2' if ocr_mode == 'animatic2' else '애니매틱'
                                    print(f"[이미지 저장] 세그먼트 {idx}: {w}x{h} → {new_w}x{new_h}로 리사이즈 ({mode_name} 모드: 썸네일 최대 크기 제한)")
                            else:
                                # OCR 모드: 원본 해상도 유지 (로딩 속도 향상을 위해 최대 1920×1080으로 제한)
                                max_width = 1920
                                max_height = 1080
                                
                                # 리사이즈 필요 여부 확인
                                if w > max_width or h > max_height:
                                    scale = min(max_width / w, max_height / h)
                                    new_w = int(w * scale)
                                    new_h = int(h * scale)
                                    # INTER_AREA: 축소 시 품질 유지에 적합
                                    img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
                                    print(f"[이미지 저장] 세그먼트 {idx}: {w}x{h} → {new_w}x{new_h}로 리사이즈 (OCR 모드: 최대 1920×1080 제한)")
                            
                            # JPEG로 저장 (품질 85% - 파일 크기와 품질의 균형)
                            image_io.imwrite(image_path, img, [cv2.IMWRITE_JPEG_QUALITY, 85])
                            segment_data["roi_image_file"] = image_filename
                    except Exception as e:
                        print(f"이미지 저장 실패 (segment {idx}): {e}")
                        image_failures.append(f"구간 {idx}: {e}")
                
                # Detections 저장 (box 좌표 포함)
                if detections:
                    segment_data["detections"] = detections
                
                save_data["segments"].append(segment_data)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            self._ocr_results_unsaved = False  # 파일을 썼음 (이미지 일부 실패는 아래에서 알림)
            
            if image_failures:
                QMessageBox.warning(
                    self, "일부 이미지 저장 실패",
                    f"OCR 결과는 저장했지만 구간 이미지 {len(image_failures)}개를 저장하지 못했습니다:\n"
                    + "\n".join(image_failures[:20]),
                )
            QMessageBox.information(self, "저장 완료", f"OCR 결과가 저장되었습니다:\n{file_path}")
            self.update_ocr_status_label(f"OCR: 결과 저장됨 ({os.path.basename(file_path)})")
        
        except Exception as e:
            QMessageBox.critical(self, "저장 실패", f"OCR 결과 저장 중 오류가 발생했습니다:\n{e}")
    
    def load_ocr_result(self):
        """저장된 OCR 분석 결과를 로드"""
        # 현재 비디오 경로 사용 (사이드바 또는 Video A)
        current_video_path = self.get_current_video_path() or self.filename_a
        default_dir = os.path.dirname(current_video_path) if current_video_path else os.path.expanduser("~")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "OCR 결과 로드",
            default_dir,
            "JSON Files (*.json)"
        )
        
        if not file_path:
            return
        
        try:
            import cv2
            with open(file_path, 'r', encoding='utf-8') as f:
                load_data = json.load(f)
            
            # 이미지 폴더 경로 유추
            json_dir = os.path.dirname(file_path)
            json_basename = os.path.splitext(os.path.basename(file_path))[0]
            images_dir = os.path.join(json_dir, f"{json_basename}_images")
            
            # 동영상 경로 확인 및 자동 로드
            stored_video_path = load_data.get("video_path")
            try:
                saved_video_path = paths.from_storage(stored_video_path)
            except paths.PathMapError as exc:
                QMessageBox.warning(
                    self, "동영상 경로 변환 실패",
                    f"저장된 동영상 경로를 이 PC 경로로 바꾸지 못했습니다:\n{stored_video_path}\n\n{exc}",
                )
                if not self.filename_a:
                    return
                saved_video_path = None  # 이미 연 영상으로 계속

            # 방법 2: 동영상이 로드되지 않았거나 경로가 다르면 자동으로 로드
            if saved_video_path:
                # 동영상이 로드되지 않은 경우
                if not self.filename_a:
                    if os.path.exists(saved_video_path):
                        reply = QMessageBox.question(
                            self,
                            "동영상 자동 로드",
                            f"저장된 동영상을 자동으로 로드하시겠습니까?\n\n경로: {saved_video_path}",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.Yes
                        )
                        if reply == QMessageBox.Yes:
                            self.open_file('A', saved_video_path)
                    else:
                        QMessageBox.warning(
                            self,
                            "동영상 파일 없음",
                            f"저장된 동영상 파일을 찾을 수 없습니다:\n{stored_and_native_path(stored_video_path, saved_video_path)}"
                            "\n\n수동으로 동영상을 로드한 후 다시 시도하세요."
                        )
                        return
                # 동영상 경로가 다른 경우
                elif not paths.same_path(saved_video_path, self.filename_a):
                    reply = QMessageBox.question(
                        self,
                        "동영상 경로 불일치",
                        f"저장된 결과의 동영상 경로가 다릅니다:\n저장됨: {saved_video_path}\n현재: {self.filename_a}\n\n저장된 동영상을 로드하시겠습니까?",
                        QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                        QMessageBox.Yes
                    )
                    if reply == QMessageBox.Yes:
                        if os.path.exists(saved_video_path):
                            self.open_file('A', saved_video_path)
                        else:
                            QMessageBox.warning(
                                self, "파일 없음",
                                f"동영상 파일을 찾을 수 없습니다:\n{stored_and_native_path(stored_video_path, saved_video_path)}",
                            )
                            return
                    elif reply == QMessageBox.Cancel:
                        return
                    # No를 선택하면 현재 동영상으로 계속
            
            # 동영상이 로드된 경우 메타데이터 직접 읽기 (open_file이 비동기적일 수 있음)
            actual_fps = None
            actual_total_frames = None
            if self.filename_a and os.path.exists(self.filename_a):
                try:
                    import cv2
                    temp_cap = cv2.VideoCapture(self.filename_a)
                    if temp_cap.isOpened():
                        actual_fps = temp_cap.get(cv2.CAP_PROP_FPS)
                        actual_total_frames = int(temp_cap.get(cv2.CAP_PROP_FRAME_COUNT))
                        temp_cap.release()
                except Exception as e:
                    pass
            
            # ROI 정보 복원
            if load_data.get("roi"):
                self.ocr_roi = load_data["roi"]
                self.videoWidget.set_roi_normalized_rect(self.ocr_roi)
                self.ocrClearRoiButton.setEnabled(True)
                self.ocrAnalyzeButton.setEnabled(True)
                self.ocrAnalyzeRangeButton.setEnabled(True)
                self.ocrTrackingCheckBox.setEnabled(True)
                self.update_ocr_status_label()
            
            # Segments 복원
            segments = []
            for segment_data in load_data.get("segments", []):
                text = segment_data.get("text", "")
                edited_text = segment_data.get("edited_text", "")
                
                # Detections 복원 (텍스트 추출에 필요할 수 있음)
                detections = segment_data.get("detections", [])
                
                # 방법 1 개선: text와 edited_text가 모두 비어있거나 "<미검출>"이면 detections에서 추출
                if (not text or text == "<미검출>") and (not edited_text or edited_text == "<미검출>"):
                    if detections:
                        # detections에서 텍스트 추출
                        detected_texts = []
                        for det in detections:
                            if isinstance(det, dict) and det.get("text"):
                                detected_texts.append(det.get("text"))
                        if detected_texts:
                            text = "\n".join(detected_texts)
                            edited_text = text
                        else:
                            # detections도 비어있으면 둘 다 "<미검출>"
                            text = "<미검출>"
                            edited_text = "<미검출>"
                    else:
                        # detections 자체가 없으면 둘 다 "<미검출>"
                        text = "<미검출>"
                        edited_text = "<미검출>"
                else:
                    # edited_text가 비어있거나 "<미검출>"이면 text를 사용
                    if not edited_text or edited_text == "<미검출>":
                        edited_text = text if text and text != "<미검출>" else "<미검출>"
                    
                    # text가 비어있거나 "<미검출>"이면 edited_text를 사용
                    if not text or text == "<미검출>":
                        text = edited_text if edited_text and edited_text != "<미검출>" else "<미검출>"
                
                segment = {
                    "text": text,
                    "edited_text": edited_text,
                    "start_frame": segment_data.get("start_frame", 0),
                    "end_frame": segment_data.get("end_frame", 0),
                    "start_time": segment_data.get("start_time", 0.0),
                    "end_time": segment_data.get("end_time", 0.0),
                    "duration": segment_data.get("duration", 0.0),
                }
                
                # ROI 이미지 복원 (JPEG/PNG 파일 우선, Base64 fallback)
                roi_image = None
                if segment_data.get("roi_image_file"):
                    # 새 방식: JPEG/PNG 파일에서 로드 (cv2.imread는 자동으로 형식 감지)
                    image_path = os.path.join(images_dir, segment_data["roi_image_file"])
                    if os.path.exists(image_path):
                        try:
                            img = image_io.imread(image_path)
                            if img is not None:
                                # numpy array를 bytes로 변환 (PNG 형식으로 인코딩하여 내부 저장)
                                # 저장 시 JPEG로 저장했어도, 메모리에서는 PNG로 인코딩하여 일관성 유지
                                is_success, buffer = cv2.imencode('.png', img)
                                if is_success:
                                    roi_image = buffer.tobytes()
                        except Exception as e:
                            print(f"이미지 로드 실패: {image_path}, {e}")
                elif segment_data.get("roi_image_base64"):
                    # 기존 방식: Base64 디코딩 (하위 호환)
                    import base64
                    roi_image = base64.b64decode(segment_data["roi_image_base64"])
                
                if roi_image:
                    segment["roi_image"] = roi_image
                
                # Detections 저장
                if detections:
                    segment["detections"] = detections
                
                segments.append(segment)
            
            # 로드된 segments를 저장
            self.last_ocr_segments = segments
            self._ocr_results_unsaved = False  # 저장된 파일에서 읽은 결과
            self.saved_edited_segments = segments
            
            # pending_ocr_metadata 설정 (reopen_ocr_result에서 사용)
            # 우선순위: 직접 읽은 메타데이터 > JSON 파일 > 현재 VideoPlayer 속성
            final_fps = actual_fps or load_data.get("fps") or (self.fps if hasattr(self, 'fps') and self.fps else 24.0)
            final_total_frames = actual_total_frames or load_data.get("total_frames") or (self.total_frames_a if hasattr(self, 'total_frames_a') and self.total_frames_a else 1)
            # OCR 모드 로드 (JSON 파일에서 가져오거나 기본값 사용)
            ocr_mode = load_data.get("ocr_mode", 'titmouse')
            if ocr_mode == 'animatic2' and not _transnetv2_available():
                print(
                    "[OCR 로드] 저장된 결과의 모드가 '애니매틱2(TransNetV2)'이지만 "
                    "이 빌드/환경에는 TransNetV2가 포함되어 있지 않아 '애니매틱 (Auto Cut)'으로 대체합니다."
                )
                ocr_mode = 'animatic'

            self.pending_ocr_metadata = {
                "fps": final_fps,
                "total_frames": final_total_frames,
                "ocr_mode": ocr_mode  # OCR 모드 저장
            }
            
            # 버튼 활성화
            if hasattr(self, 'ocrReopenResultButton'):
                self.ocrReopenResultButton.setEnabled(True)
            if hasattr(self, 'ocrSaveResultButton'):
                self.ocrSaveResultButton.setEnabled(True)
            
            QMessageBox.information(self, "로드 완료", f"OCR 결과 {len(segments)}개 구간이 로드되었습니다.\n'OCR 오픈' 버튼을 클릭하여 확인하세요.")
            self.update_ocr_status_label(f"OCR: 결과 로드됨 ({len(segments)}개 구간)")
        
        except Exception as e:
            QMessageBox.critical(self, "로드 실패", f"OCR 결과 로드 중 오류가 발생했습니다:\n{e}")

    def prompt_ocr_export(self, segments, include_audio=True, export_mode='balanced', bitrate=None):
        default_dir = os.path.dirname(self.filename_a) if self.filename_a else os.path.expanduser("~")
        output_dir = QFileDialog.getExistingDirectory(self, "OCR 구간 저장 위치 선택", default_dir)
        if not output_dir:
            self.update_ocr_status_label("OCR: 내보내기가 취소되었습니다.")
            return
        self.start_ocr_export(segments, output_dir, include_audio, export_mode, bitrate)

    def start_ocr_export(self, segments, output_dir, include_audio=True, export_mode='balanced', bitrate=None):
        if self.ocr_export_worker and self.ocr_export_worker.isRunning():
            QMessageBox.information(self, "내보내기 진행 중", "이미 OCR 구간 내보내기가 실행 중입니다.")
            return

        ffmpeg = self.require_ffmpeg()
        if ffmpeg is None:
            return

        # OCRExportWorker lazy import
        from .workers import OCRExportWorker
        self.ocr_export_worker = OCRExportWorker(
            self.filename_a,
            segments,
            output_dir,
            ffmpeg,
            include_audio=include_audio,
            export_mode=export_mode,
            bitrate=bitrate,
            max_workers=4,  # 병렬 처리: 4개의 FFmpeg 프로세스 동시 실행
        )
        self.ocr_export_worker.progress.connect(self.on_ocr_export_progress)
        self.ocr_export_worker.status.connect(self.on_ocr_export_status)
        self.ocr_export_worker.error.connect(self.on_ocr_export_error)
        self.ocr_export_worker.completed.connect(self.on_ocr_export_completed)

        # OCR 익스포트 진행 다이얼로그 생성 (로그 표시 기능 포함)
        self.ocr_export_progress_dialog = QDialog(self)
        self.ocr_export_progress_dialog.setWindowTitle("OCR 구간 내보내기")
        self.ocr_export_progress_dialog.setWindowModality(Qt.NonModal)
        self.ocr_export_progress_dialog.resize(500, 300)
        
        layout = QVBoxLayout(self.ocr_export_progress_dialog)
        
        # 진행률 표시
        self.ocr_export_progress_bar = QProgressBar()
        self.ocr_export_progress_bar.setRange(0, 100)
        self.ocr_export_progress_bar.setValue(0)
        layout.addWidget(self.ocr_export_progress_bar)
        
        # 로그 표시 영역
        self.ocr_export_log_text = QPlainTextEdit()
        self.ocr_export_log_text.setReadOnly(True)
        self.ocr_export_log_text.setStyleSheet(OCR_LOG_TEXT_STYLE)
        layout.addWidget(self.ocr_export_log_text)
        
        # 취소 버튼
        cancel_button = QPushButton("취소")
        cancel_button.clicked.connect(self.cancel_ocr_export)
        layout.addWidget(cancel_button)
        
        self.ocr_export_log_text.appendPlainText("OCR 구간을 내보내는 중…")
        self.ocr_export_progress_dialog.show()

        self.ocr_export_worker.start()

    def on_ocr_export_progress(self, value):
        if self.ocr_export_progress_dialog and hasattr(self, 'ocr_export_progress_bar'):
            self.ocr_export_progress_bar.setValue(value)

    def on_ocr_export_status(self, message):
        # OCR 익스포트 팝업창에 로그 표시
        if self.ocr_export_progress_dialog and hasattr(self, 'ocr_export_log_text'):
            self.ocr_export_log_text.appendPlainText(f"OCR: {message}")
            # 자동 스크롤
            scrollbar = self.ocr_export_log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def on_ocr_export_error(self, message):
        # OCR 익스포트 팝업창에 오류 로그 표시
        if self.ocr_export_progress_dialog and hasattr(self, 'ocr_export_log_text'):
            self.ocr_export_log_text.appendPlainText(f"오류: {message}")
            scrollbar = self.ocr_export_log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        if self.ocr_export_progress_dialog:
            self.ocr_export_progress_dialog.close()
            self.ocr_export_progress_dialog = None
        if self.ocr_export_worker:
            # 스레드가 완전히 종료될 때까지 기다림 (최대 5초)
            if self.ocr_export_worker.isRunning():
                if not self.ocr_export_worker.wait(5000):
                    # 5초 내에 종료되지 않으면 강제 종료
                    self.ocr_export_worker.terminate()
                    self.ocr_export_worker.wait(1000)
            self.ocr_export_worker.deleteLater()
            self.ocr_export_worker = None
        QMessageBox.critical(self, "OCR 내보내기 오류", message)

    def on_ocr_export_completed(self, result):
        if self.ocr_export_progress_dialog:
            self.ocr_export_progress_dialog.close()
            self.ocr_export_progress_dialog = None

        if self.ocr_export_worker:
            # 스레드가 완전히 종료될 때까지 기다림 (최대 5초)
            if self.ocr_export_worker.isRunning():
                if not self.ocr_export_worker.wait(5000):
                    # 5초 내에 종료되지 않으면 강제 종료
                    self.ocr_export_worker.terminate()
                    self.ocr_export_worker.wait(1000)
            self.ocr_export_worker.deleteLater()
            self.ocr_export_worker = None

        exported_segments = result.get("segments", []) if isinstance(result, dict) else []
        was_cancelled = bool(result.get("cancelled")) if isinstance(result, dict) else False
        self.last_ocr_segments = exported_segments or []
        if was_cancelled:
            if exported_segments:
                QMessageBox.information(
                    self,
                    "OCR 내보내기 취소",
                    "사용자가 내보내기를 취소했습니다. 이미 생성된 {count}개의 파일은 유지됩니다.".format(
                        count=len(exported_segments)
                    ),
                )
            else:
                QMessageBox.information(self, "OCR 내보내기 취소", "사용자가 내보내기를 취소했습니다.")
            self.update_ocr_status_label("OCR: 내보내기가 취소되었습니다.")
            return

        if not exported_segments:
            QMessageBox.information(self, "OCR 내보내기", "내보낼 구간이 없어 작업이 종료되었습니다.")
            self.update_ocr_status_label("OCR: 내보내기 대상이 없습니다.")
            return

        summary_lines = []
        for segment in exported_segments[:10]:
            label = segment.get("text") or "<공백>"
            path = os.path.basename(segment.get("output_path", ""))
            summary_lines.append(f"{label}: {path}")
        if len(exported_segments) > 10:
            summary_lines.append(f"… 외 {len(exported_segments) - 10}개 파일")

        QMessageBox.information(
            self,
            "OCR 내보내기 완료",
            "총 {count}개의 구간을 내보냈습니다.\n{details}".format(
                count=len(exported_segments),
                details="\n".join(summary_lines),
            ),
        )
        self.update_ocr_status_label("OCR: 내보내기가 완료되었습니다.")

    def _preload_scene_thumbnails(self, segments):
        """
        씬 감지 완료 후 각 씬의 첫 프레임 썸네일을 미리 추출하여 UI가 즉시 표시되도록 함.
        애니매틱/애니매틱2 모드에서만 동작하며, 이미 썸네일이 있는 세그먼트는 건너뜁니다.
        """
        if not segments:
            return

        current_ocr_mode = getattr(self, '_last_ocr_mode', 'titmouse')
        if current_ocr_mode not in ['animatic', 'animatic2']:
            return

        video_path = getattr(self, '_current_ocr_video_path', None) or self.get_current_video_path() or self.filename_a
        if not video_path or not os.path.exists(video_path):
            return

        try:
            import cv2
        except Exception:
            return

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return

        print(f"[씬 감지 완료] 썸네일 프리로드 시작 (총 {len(segments)}개)")
        loaded_count = 0
        try:
            for idx, segment in enumerate(segments):
                if not isinstance(segment, dict):
                    continue

                if segment.get("roi_image"):
                    continue

                start_frame = int(segment.get("start_frame", 0))
                try:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        continue

                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    success, buffer = cv2.imencode(".png", frame_rgb)
                    if success:
                        segment["roi_image"] = buffer.tobytes()
                        loaded_count += 1
                        if loaded_count % 10 == 0:
                            print(f"[씬 감지 완료] 썸네일 프리로드 진행: {loaded_count}/{len(segments)}")
                except Exception as e:  # pragma: no cover - best effort logging
                    print(f"[씬 감지 완료] 썸네일 프리로드 실패 (segment {idx}, frame {start_frame}): {e}")
        finally:
            cap.release()

        if loaded_count:
            print(f"[씬 감지 완료] 썸네일 프리로드 완료: {loaded_count}개 생성 (총 {len(segments)}개)")

    def cancel_ocr_export(self):
        if self.ocr_export_progress_dialog and hasattr(self, 'ocr_export_log_text'):
            self.ocr_export_log_text.appendPlainText("OCR: 내보내기 취소 중…")
        if self.ocr_export_worker and self.ocr_export_worker.isRunning():
            self.ocr_export_worker.stop()
            # 스레드가 종료될 때까지 기다림 (최대 5초)
            if not self.ocr_export_worker.wait(5000):
                # 5초 내에 종료되지 않으면 강제 종료
                self.ocr_export_worker.terminate()
                self.ocr_export_worker.wait(1000)

    def show(self):
        """앱이 표시될 때 포커스를 강제로 설정"""
        super().show()
        
        # 기본 사이드바 폭 설정 (앱이 처음 표시된 후)
        QTimer.singleShot(200, self.initialize_sidebar_width)
        QTimer.singleShot(100, self.force_focus)
    
    def create_menu_bar(self):
        """상단 메뉴바를 생성합니다."""
        menubar = self.menuBar()
        
        # Settings 메뉴
        settings_menu = menubar.addMenu('&Settings')
        
        # GPU Acceleration 서브메뉴
        gpu_menu = settings_menu.addMenu('GPU Acceleration')
        self.gpu_action_group = []
        
        # CPU 옵션
        cpu_action = gpu_menu.addAction('CPU')
        cpu_action.setCheckable(True)
        cpu_action.setChecked(True)
        cpu_action.triggered.connect(lambda: self.set_gpu_mode(0))
        self.gpu_action_group.append(cpu_action)
        
        # NVIDIA (CUDA) 옵션 (lazy import)
        import cv2
        if cv2.cuda.getCudaEnabledDeviceCount() > 0:
            cuda_action = gpu_menu.addAction('NVIDIA (CUDA)')
            cuda_action.setCheckable(True)
            cuda_action.triggered.connect(lambda: self.set_gpu_mode(1))
            self.gpu_action_group.append(cuda_action)
        
        # AMD (OpenCL) 옵션 (lazy import)
        import cv2
        if cv2.ocl.haveOpenCL():
            opencl_action = gpu_menu.addAction('AMD (OpenCL)')
            opencl_action.setCheckable(True)
            opencl_action.triggered.connect(lambda: self.set_gpu_mode(2))
            self.gpu_action_group.append(opencl_action)
        
        # 공유 설정 폴더 변경 (Windows: PC마다 고름)
        if paths.IS_WINDOWS:
            shared_config_action = settings_menu.addAction('공유 설정 폴더 변경...')
            shared_config_action.triggered.connect(lambda: self.choose_shared_config_dir())

        # 4K 성능 모드 서브메뉴
        performance_menu = settings_menu.addMenu('4K 성능 모드')
        self.performance_action_group = []
        
        performance_modes = [
            ('자동 (Auto)', 0),
            ('속도 우선 (Speed)', 1),
            ('극한 속도 (Ultra)', 2),
            ('품질 우선 (Quality)', 3)
        ]
        
        for name, index in performance_modes:
            action = performance_menu.addAction(name)
            action.setCheckable(True)
            if index == 0:
                action.setChecked(True)
            action.triggered.connect(lambda checked, idx=index: self.set_performance_mode(idx))
            self.performance_action_group.append(action)
        
        # Help 메뉴
        help_menu = menubar.addMenu('&Help')
        
        # Help 액션
        help_action = help_menu.addAction('사용법')
        help_action.setShortcut('F1')
        help_action.triggered.connect(self.show_help)
        
        # 실행 및 빌드 (원클릭, Mac 개발 환경 전용: run_app.sh·build_app.sh)
        if not paths.IS_WINDOWS:
            run_build_action = help_menu.addAction('실행 및 빌드')
            run_build_action.triggered.connect(self.show_run_and_build_dialog)

        # 업데이트 확인 (NAS·GitHub — 결과 창을 언제나 보임, PlayerUpdateMixin)
        update_check_action = help_menu.addAction('업데이트 확인…')
        update_check_action.triggered.connect(lambda: self.start_update_check(manual=True))

        # (Mac) .mov·.mp4를 더블클릭하면 YesonCheck로 — 묻지 않고 기본 앱으로 정함 (default_app, 처음 켤 때 묻기와 같은 일)
        if default_app.IS_MAC:
            default_app_action = help_menu.addAction(default_app.MENU_TEXT)
            default_app_action.triggered.connect(lambda: default_app.set_default_from_menu(self))
        # (Windows) 기본 앱은 앱이 바꿀 수 없음(Windows 10·11) → Windows 기본 앱 설정 화면의 YesonCheck 항목을 엶 (file_associations)
        if file_associations.IS_WINDOWS:
            default_apps_settings_action = help_menu.addAction(file_associations.MENU_TEXT)
            default_apps_settings_action.triggered.connect(lambda: file_associations.open_default_apps_settings())

        # About 액션
        about_action = help_menu.addAction('정보')
        about_action.triggered.connect(self.show_about)
    
    def set_gpu_mode(self, index):
        """GPU 모드를 설정합니다."""
        # 라디오 버튼처럼 동작하도록 다른 액션들의 체크 해제
        for i, action in enumerate(self.gpu_action_group):
            action.setChecked(i == index)
        
        # ComboBox 업데이트 (change_gpu_backend 메서드가 자동으로 호출됨)
        if hasattr(self, 'gpuComboBox'):
            self.gpuComboBox.setCurrentIndex(index)
    
    def set_performance_mode(self, index):
        """성능 모드를 설정합니다."""
        # 라디오 버튼처럼 동작하도록 다른 액션들의 체크 해제
        for i, action in enumerate(self.performance_action_group):
            action.setChecked(i == index)
        
        # ComboBox 업데이트 (change_performance_mode 메서드가 자동으로 호출됨)
        if hasattr(self, 'performanceComboBox'):
            self.performanceComboBox.setCurrentIndex(index)
    
    def show_help(self):
        """도움말을 표시합니다."""
        today_str = korean_date(datetime.date.today())
        help_text = f"""
<h2>Yeson Checker 사용법</h2>
<p><b>애니매틱 자르기 버전</b> - {today_str}까지 기록</p>

<h3>📹 비디오 재생</h3>
<ul>
<li><b>Open Video A/B</b>: 동영상 파일을 엽니다</li>
<li><b>Play/Pause</b>: 재생/일시정지</li>
<li><b>Stop</b>: 정지</li>
<li><b>Previous/Next Frame</b>: 이전/다음 프레임으로 이동 (화살표 키)</li>
<li><b>Full Screen</b>: 전체화면 전환 (F11)</li>
</ul>

<h3>📝 OCR 기능 상세 설명</h3>

<h4>1️⃣ ROI 설정 그룹</h4>
<ul>
<li><b>OCR ROI 지정</b>: 동영상에서 텍스트를 인식할 영역을 드래그로 지정합니다</li>
<li><b>ROI 초기화</b>: 지정한 ROI 영역을 제거합니다</li>
<li><b>ROI 트래킹 활성화</b>: 텍스트가 이동할 때 ROI 영역이 자동으로 따라갑니다</li>
</ul>

<h4>2️⃣ OCR 분석 그룹</h4>
<ul>
    <li><b>OCR 분석 방식</b>:
  <ul>
    <li><b>Titmouse</b>: 일반 텍스트에 적합한 기본 모드</li>
    <li><b>King</b>: 빨간색 텍스트 등 특수 색상 텍스트에 최적화된 모드</li>
    <li><b>Bento</b>: 작은 텍스트 및 특수 패턴 인식 최적화 (예: Seq 02A_S09 - Panel 6)</li>
  </ul>
</li>
<li><b>OCR 구간 추출</b>: 전체 동영상에서 텍스트를 자동으로 인식하고 구간별로 분류합니다</li>
<li><b>선택 구간 분석</b>: 현재 프레임 범위만 분석하여 기존 결과에 병합합니다</li>
</ul>

<h4>3️⃣ 결과 관리 그룹</h4>
<ul>
<li><b>OCR 오픈</b>: 분석한 결과를 검토 창에서 확인하고 편집합니다</li>
<li><b>OCR 저장</b>: 현재 분석 결과를 JSON 파일로 저장합니다</li>
<li><b>OCR 로드</b>: 저장한 분석 결과를 불러옵니다</li>
</ul>

<h4>📊 OCR 결과 검토 창 기능</h4>
<ul>
<li><b>텍스트 편집</b>: ROI 텍스트와 편집 텍스트를 직접 수정할 수 있습니다</li>
<li><b>구간 병합</b>: 여러 구간을 선택하여 하나로 합칠 수 있습니다 (D 또는 ㅇ 키)</li>
<li><b>구간 삭제</b>: 불필요한 구간을 제거할 수 있습니다</li>
<li><b>전체 내보내기</b>: 모든 구간을 개별 동영상 파일로 추출합니다 (R 또는 ㄱ 키)</li>
<li><b>선택 항목 내보내기</b>: 선택한 구간만 동영상 파일로 추출합니다</li>
<li><b>사운드 옵션</b>: 내보낼 때 오디오 포함 여부를 선택할 수 있습니다</li>
</ul>

<h4>💡 OCR 사용 팁</h4>
<ul>
<li>빨간색 텍스트는 <b>King</b> 모드를 사용하세요</li>
<li>작은 텍스트나 특수 패턴(예: Seq 02A_S09 - Panel 6)은 <b>Bento</b> 모드를 사용하세요</li>
<li>텍스트가 이동하는 경우 <b>ROI 트래킹</b>을 활성화하세요</li>
<li>분석 후 병합 표시(노란색)된 유사 구간은 병합하여 정리하세요</li>
<li>구간 길이는 프레임 단위로 표시됩니다</li>
</ul>

<h3>✏️ 수정 사항 주석 (영상에 메모 남기기)</h3>
<p>영상의 특정 장면에 <b>“여기 고쳐주세요”</b> 같은 메모를 그림·글자로 남기는 기능입니다. 유튜브 댓글 대신, 영상 위에 직접 표시하는 느낌이라고 생각하면 됩니다.</p>

<h4>1️⃣ 준비하기</h4>
<ul>
<li>먼저 <b>Open Video A</b>로 동영상을 엽니다.</li>
<li>왼쪽(또는 사이드) 컨트롤에서 <b>▶ 수정 사항 주석</b> 칸을 펼칩니다.</li>
<li><b>주석 모드</b> 버튼을 눌러 켭니다. (다시 누르면 꺼집니다)</li>
</ul>

<h4>2️⃣ 주석 그리기</h4>
<ul>
<li><b>도구</b>에서 원하는 것을 고릅니다:
  <ul>
    <li><b>텍스트</b> — 글자로 메모 (예: “배경 색 바꿔주세요”)</li>
    <li><b>사각형</b> — 네모로 영역 표시</li>
    <li><b>타원</b> — 동그란/타원으로 표시</li>
    <li><b>선</b> — 직선으로 가리키기</li>
    <li><b>화살표</b> — 화살표로 “여기!” 표시</li>
  </ul>
</li>
<li><b>색상</b>으로 빨강·노랑 등 색을 고릅니다.</li>
<li>영상 위에서 <b>마우스로 드래그</b>하면 도형이 그려집니다.</li>
<li><b>텍스트</b>는 클릭한 뒤, 나오는 창에 글을 입력합니다.</li>
<li><b>표시 프레임 (시작 ~ 끝)</b>: 주석이 몇 번 프레임부터 몇 번까지 보일지 정합니다. 시작과 끝을 같게 하면 <b>한 프레임만</b> 보입니다.</li>
</ul>

<h4>3️⃣ 주석 고치기·지우기</h4>
<ul>
<li>이미 그린 주석을 <b>클릭</b>하면 노란 점(핸들)이 나옵니다. 드래그해서 <b>위치 이동</b>이나 <b>크기 조절</b>이 됩니다.</li>
<li>아래 <b>목록</b>에서 주석을 고른 뒤 <b>선택 주석 삭제</b>로 하나만 지울 수 있습니다.</li>
<li><b>현재 프레임에 보이는 주석 전체 삭제</b>는 지금 화면에 보이는 주석을 한 번에 지웁니다.</li>
<li>목록에서 주석을 고르면 <b>표시 프레임</b> 숫자를 바꿔서 보이는 구간을 나중에도 수정할 수 있습니다.</li>
</ul>

<h4>4️⃣ 저장과 보내기</h4>
<ul>
<li>주석은 <b>자동 저장</b>됩니다. 동영상 파일 옆 <b>.yesoncheck</b> 폴더에 JSON 파일로 들어갑니다.</li>
<li>같은 영상을 다시 열면 예전에 남긴 주석이 <b>자동으로 불러와집니다</b>.</li>
<li><b>보내기 저장 폴더 선택</b>으로 결과 파일을 둘 폴더를 정합니다.</li>
<li><b>주석 포함 영상보내기</b>를 누르면, 주석이 영상에 박힌 새 파일(mp4 등)이 만들어집니다. 다른 사람에게 보낼 때 유용합니다.</li>
</ul>

<h4>💡 주석 사용 팁</h4>
<ul>
<li>주석은 <b>프레임 구간</b>마다 표시됩니다. 예: 시작 10, 끝 50이면 10~50번 프레임에서 계속 보입니다.</li>
<li><b>OCR ROI 지정</b>과 <b>주석 모드</b>는 동시에 켤 수 없습니다. 하나를 끄고 다른 것을 켜세요.</li>
<li>텍스트 크기·선 굵기는 위쪽 숫자로 바꿀 수 있고, 목록에서 주석을 고르면 그 주석에도 적용됩니다.</li>
</ul>

<h3>⌨️ 단축키</h3>
<ul>
<li><b>Space</b>: 재생/일시정지</li>
<li><b>←/→</b>: 이전/다음 프레임</li>
<li><b>F11</b>: 전체화면</li>
<li><b>F1</b>: 도움말</li>
<li><b>F5</b>: 사이드바 목록 다시 읽기 (새로고침 — 창으로 돌아올 때도 저절로). 썸네일 모드면 다시 렌더링한 영상의 썸네일도 다시 만듦</li>
<li><b>D (ㅇ)</b>: 선택 구간 병합 (OCR 결과 검토 창)</li>
<li><b>R (ㄱ)</b>: 전체 내보내기 (OCR 결과 검토 창)</li>
</ul>

<h3>⚙️ 설정 (상단 메뉴바)</h3>
<ul>
<li><b>Settings → GPU Acceleration</b>: CPU, NVIDIA (CUDA), AMD (OpenCL) 선택</li>
<li><b>Settings → 4K 성능 모드</b>: 자동, 속도 우선, 극한 속도, 품질 우선 선택</li>
</ul>
        """
        
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle('Yeson Checker 사용법')
        msg_box.setTextFormat(Qt.RichText)
        msg_box.setText(help_text)
        msg_box.setIcon(QMessageBox.Information)
        
        # 메시지 박스 크기 조정 (내용이 길어서 스크롤 가능하도록)
        msg_box.setStyleSheet("QLabel{min-width: 700px; min-height: 500px;}")
        
        msg_box.exec_()

    def require_ffmpeg(self):
        """ffmpeg 경로. 찾지 못하면 오류 창을 띄우고 None."""
        try:
            return external_tools.ffmpeg_path()
        except external_tools.ToolNotFoundError as exc:
            QMessageBox.critical(self, "ffmpeg 없음", str(exc))
            return None

    def show_run_and_build_dialog(self):
        """실행 및 빌드를 원클릭 버튼으로 제공하는 다이얼로그."""
        # 프로젝트 루트 (yesoncheck 패키지의 상위 디렉터리)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        run_script = os.path.join(project_root, "run_app.sh")
        build_script = os.path.join(project_root, "build_app.sh")

        dialog = QDialog(self)
        dialog.setWindowTitle("실행 및 빌드")
        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel("명령어 복사 없이 버튼 한 번으로 실행하거나 빌드할 수 있습니다."))
        layout.addSpacing(12)

        run_btn = QPushButton("▶ 앱 실행 (개발 모드)")
        run_btn.setToolTip("새 터미널에서 YesonCheck를 개발 모드로 실행합니다.")
        def on_run():
            if not os.path.isfile(run_script):
                QMessageBox.warning(dialog, "스크립트 없음", f"run_app.sh를 찾을 수 없습니다:\n{run_script}")
                return
            try:
                if sys.platform == "darwin":
                    esc = project_root.replace("\\", "\\\\").replace('"', '\\"')
                    subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "cd \\"{esc}\\" && ./run_app.sh"'])
                elif sys.platform == "win32":
                    subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", "run_app.bat"], cwd=project_root, shell=False)
                else:
                    subprocess.Popen(["x-terminal-emulator", "-e", f"bash '{run_script}'; exec bash"], cwd=project_root)
                QMessageBox.information(dialog, "실행", "새 터미널에서 앱이 실행됩니다.")
            except Exception as e:
                QMessageBox.critical(dialog, "오류", f"실행 실패:\n{e}")
        run_btn.clicked.connect(on_run)
        layout.addWidget(run_btn)

        build_btn = QPushButton("📦 macOS 앱 빌드 (PyInstaller)")
        build_btn.setToolTip("새 터미널에서 PyInstaller로 .app 번들을 생성합니다.")
        def on_build():
            if not os.path.isfile(build_script):
                QMessageBox.warning(dialog, "스크립트 없음", f"build_app.sh를 찾을 수 없습니다:\n{build_script}")
                return
            try:
                if sys.platform == "darwin":
                    esc = project_root.replace("\\", "\\\\").replace('"', '\\"')
                    subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "cd \\"{esc}\\" && ./build_app.sh"'])
                elif sys.platform == "win32":
                    subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", "build_app.bat"], cwd=project_root, shell=False)
                else:
                    subprocess.Popen(["x-terminal-emulator", "-e", f"bash '{build_script}'; exec bash"], cwd=project_root)
                QMessageBox.information(dialog, "빌드", "새 터미널에서 빌드가 시작됩니다. 완료 시 dist/YesonCheck_Autocut.app 에서 확인하세요.")
            except Exception as e:
                QMessageBox.critical(dialog, "오류", f"빌드 실행 실패:\n{e}")
        build_btn.clicked.connect(on_build)
        layout.addWidget(build_btn)

        layout.addSpacing(8)
        layout.addWidget(QLabel("※ 터미널에서 로그를 확인할 수 있습니다."))
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)
        dialog.exec_()
    
    def show_about(self):
        """프로그램 정보를 표시합니다."""
        today_str = korean_date(datetime.date.today())
        # 버전: 빌드된 앱은 build_info.json의 버전·커밋 7자리·빌드 날짜, 소스 실행은 "개발(소스)"
        info = build_info.current()
        version_text = build_info.display_version()
        if info is not None:
            version_text += f" · 커밋 {info.commit[:7]} · {info.built[:10]} 빌드"
        about_text = f"""
<h2>Yeson Checker</h2>
<p><b>애니매틱 자르기 버전</b></p>
<p><b>버전:</b> {version_text}</p>
<p>동영상 재생 및 OCR 분석 도구</p>
<p>{today_str}까지 기록</p>
<p>© 2025 Yeson Entertainment</p>
        """
        
        QMessageBox.about(self, 'Yeson Checker 정보', about_text)

    # 창을 닫을 때 멈추는(그리고 '업데이트' 전에 묻는) 작업: (이름, 워커 속성). 썸네일 만들기·목록 다시 읽기는 넣지 않음
    # — 묻지 않고 멈춤 (설계 5-2)
    RUNNING_JOB_ATTRS = (
        ("OCR 분석·컷 감지", "ocr_worker"),
        ("OCR 구간 내보내기", "ocr_export_worker"),
        ("주석 영상 내보내기", "annotation_export_worker"),
        ("영상 병합", "merge_worker"),
    )

    def running_jobs(self):
        """실행 중인 작업 [(이름, 워커)] — RUNNING_JOB_ATTRS 순서."""
        jobs = []
        for label, attr in self.RUNNING_JOB_ATTRS:
            worker = getattr(self, attr, None)
            if worker is not None and worker.isRunning():
                jobs.append((label, worker))
        return jobs

    def running_job_labels(self) -> list[str]:
        """실행 중인 OCR·컷 감지/OCR 구간 내보내기/주석 영상 내보내기/영상 병합의 이름."""
        return [label for label, _worker in self.running_jobs()]

    def stop_running_jobs(self, timeout_ms=None):
        """창을 닫을 때: 실행 중인 OCR 분석·컷 감지, OCR 구간 내보내기·주석 내보내기·병합을 멈추고 끝날 때까지 기다립니다
        (최대 timeout_ms, 기본 JOB_CLOSE_WAIT_MS).

        멈추지 않으면 ffmpeg가 (Windows에서는 보이지 않은 채) 남아 NAS의 출력 파일을 잡고 있고,
        실행 중인 QThread가 그대로 파괴됩니다. 시간 안에 끝나지 않은 작업(예: TensorFlow 추론 중인 애니매틱2)은
        끝날 때까지 붙잡아 둡니다 (release_worker, 앱 종료 전에 wait_for_released_workers가 기다림).
        """
        if timeout_ms is None:
            timeout_ms = self.JOB_CLOSE_WAIT_MS
        for label, worker in self.running_jobs():
            print(f"창 닫기: {label} 중지 중…")
            worker.blockSignals(True)  # 멈춘 뒤의 '취소됨'·오류 신호로 닫히는 중에 대화상자가 뜨지 않게
            worker.stop()
            if not worker.wait(timeout_ms):
                print(f"창 닫기: {label}이(가) {timeout_ms / 1000:g}초 안에 끝나지 않았습니다")
                release_worker(worker, label)

    # ---- 다른 창(프로세스)과: 창 기록·상태 묻기·업데이트의 닫기 요청 (instances·instance_link) ----

    def start_instance_link(self):
        """창을 보인 뒤(app.launch): 창 사이 연결 서버를 열고 창 기록을 남김 — 다른 창의 업데이트가 이 창을 세고
        상태를 묻고 닫기를 요청할 수 있게. 서버를 열지 못해도 기록은 남김(세어지면 그 업데이트는 이 창을 닫지 못해
        멈춤 — 모르는 채 앱 파일을 바꾸지 않게) + 경고 창."""
        server = instance_link.InstanceServer(self.instance_status, self.close_for_update, self)
        try:
            name = server.start()
            listen_error = None
        except instance_link.InstanceLinkError as exc:
            name = instance_link.server_name()
            listen_error = exc
            print(f"[창 연결] {exc}", flush=True)
        else:
            self._instance_server = server
        record = instances.register(instances.current_app_path(), name)  # 경고 창이 떠 있는 동안에도 세어지게 먼저
        print(f"[창 기록] pid {record.pid}, {record.app_path}, {record.server_name}", flush=True)
        if listen_error is not None:
            QMessageBox.warning(
                self, "다른 창과 연결하지 못함",
                f"다른 YesonCheck 창과 연결하지 못했습니다. 다른 창에서 업데이트하면 이 창을 닫지 못해 업데이트가 "
                f"멈춥니다.\n\n{listen_error}",
            )

    def stop_instance_link(self):
        """창을 닫을 때: 창 기록을 지우고 서버를 닫음 (닫히는 창은 다른 창의 업데이트가 세지 않음). 두 번 불러도 됨."""
        server, self._instance_server = getattr(self, '_instance_server', None), None
        if server is not None:
            server.close()
        instances.unregister()

    def instance_status(self) -> dict:
        """다른 창(업데이트)이 묻는 이 창의 상태: 창 제목·영상 A·하는 작업·저장 안 한 OCR·애니매틱 검토 결과."""
        return {
            "pid": os.getpid(),
            "title": self.windowTitle(),
            "video": self.filename_a or "",
            "jobs": self.running_job_labels(),
            "unsaved_ocr": self.has_unsaved_ocr_results(),
        }

    # 다른 창의 업데이트가 닫기를 요청한 뒤(close_for_update): 진행 창으로 도는 반복(썸네일 다시 만들기·변환표 찾기)이
    # 멈춘 뒤의 다음 창(완료 알림·변환표 확인 창 등)을 열지 않음
    _closing_for_update = False

    def close_for_update(self):
        """다른 창의 업데이트가 닫기를 요청함: 대화 상자를 Esc처럼 닫고 닫기 버튼을 누른 것처럼 닫음 (closeEvent — 작업
        멈춤 포함). 진행 창(QProgressDialog)은 cancel() — 그 창으로 도는 반복이 wasCanceled로 멈춤 (최소 표시 시간 전이라
        아직 보이지 않는 진행 창도). 그 밖의 보이는 모달 대화 상자(질문·파일 고르기 등)는 reject(). 모달이 아닌 창(OCR 검토
        창 등)은 앱이 끝날 때 닫힘."""
        self._closing_for_update = True
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QProgressDialog):
                if not widget.wasCanceled():
                    print(f"[창 연결] 업데이트로 닫음: 진행 창 취소 '{widget.labelText()}'", flush=True)
                    widget.cancel()
            elif isinstance(widget, QDialog) and widget.isVisible() and widget.isModal():
                print(f"[창 연결] 업데이트로 닫음: 대화 상자 취소 {type(widget).__name__} '{widget.windowTitle()}'",
                      flush=True)
                widget.reject()
        self.close()

    def closeEvent(self, event):
        """앱 종료 시 리소스를 빠르게 정리합니다. 맨 먼저 창 기록을 지움 — 지우다 오류가 나도 정리는 하고 그 오류를 올림."""
        try:
            self.stop_instance_link()
        finally:
            self._release_resources_on_close(event)

    def _release_resources_on_close(self, event):
        try:
            print("앱 종료 중 - 빠른 리소스 정리 시작")

            # 실행 중인 목록 다시 읽기: 기다리지 않고 끝날 때까지 붙잡아 둠 (응답 없는 NAS를 읽는 중일 수 있음 — 앱이
            # 끝나기 전에 wait_for_released_workers가 정해진 시간까지 기다림). 결과는 버림 (신호를 막음).
            # 맨 먼저: 뒤의 정리에서 오류가 나도 실행 중인 스레드를 놓지 않은 채 남기지 않게
            self._sidebar_scan_closed = True
            if getattr(self, '_app_state_connected', False):
                QApplication.instance().applicationStateChanged.disconnect(self._on_application_state_changed)
                self._app_state_connected = False
            if hasattr(self, '_sidebar_refresh_timer'):
                self._sidebar_refresh_timer.stop()
            scan, self._sidebar_scan = getattr(self, '_sidebar_scan', None), None
            if scan is not None:
                release_worker(scan, "사이드바 목록 다시 읽기")
            # 업데이트 확인: 3시간 타이머를 멈추고, 실행 중인 확인은 결과를 버린 채 끝날 때까지 붙잡아 둠
            self.stop_update_checks()
            # 업데이트 받기: 멈추라고 알리고 끝날 때까지 붙잡아 둠 (결과는 버림 — 기록·도우미로 넘어가지 않음)
            self.stop_update_download()

            # 실행 중인 내보내기·병합 중지 (ffmpeg 종료)
            self.stop_running_jobs()

            # 실행 중인 공유 설정 불러오기: 정해진 시간까지만 기다리고, 늦게 오는 결과는 버림
            self._shared_config_closed = True
            load = getattr(self, '_shared_config_load', None)
            if load is not None and load.isRunning():
                self.hide()  # 기다리는 동안(최대 몇 초) 보이는 창이 멈춰 있지 않게 먼저 숨김
                self.wait_for_shared_config_load(self.SHARED_CONFIG_CLOSE_WAIT_MS)

            # 백그라운드 썸네일 로딩 타이머 중지
            if hasattr(self, 'thumbnail_loading_timer'):
                self.thumbnail_loading_timer.stop()
            
            # 백그라운드 썸네일 로더 워커 빠른 중지
            if hasattr(self, 'thumbnail_loader_worker') and self.thumbnail_loader_worker:
                if self.thumbnail_loader_worker.isRunning():
                    print("백그라운드 썸네일 로더 워커 빠른 중지...")
                    self.thumbnail_loader_worker.stop()
                    # 대기 시간 단축 (1초)
                    if not self.thumbnail_loader_worker.wait(1000):
                        print("워커 강제 종료")
                        self.thumbnail_loader_worker.terminate()
                        self.thumbnail_loader_worker.wait(500)  # 0.5초 대기
                    self.thumbnail_loader_worker.deleteLater()
                    self.thumbnail_loader_worker = None
            
            # 모든 썸네일 워커를 빠르게 중지
            print(f"썸네일 워커 {len(self.thumbnail_workers)}개 빠른 중지...")
            for worker in self.thumbnail_workers:
                try:
                    if worker.isRunning():
                        worker.stop()
                        # 대기 시간 단축 (1초)
                        if not worker.wait(1000):
                            worker.terminate()
                            worker.wait(500)  # 0.5초 대기
                    worker.deleteLater()
                except Exception as e:
                    print(f"워커 중지 중 오류: {e}")
            
            # 워커 리스트 클리어
            self.thumbnail_workers.clear()
            
            # 비디오 캡처 객체 정리
            if hasattr(self, 'cap_a') and self.cap_a:
                self.cap_a.release()
            if hasattr(self, 'cap_b') and self.cap_b:
                self.cap_b.release()
            
            # 미디어 플레이어 정리 (만든 적이 없으면 만들지 않음 — mediaPlayer 속성은 처음 쓸 때 만듦)
            if getattr(self, '_media_player', None) is not None:
                self._media_player.stop()
            
            # 타이머 정리
            if hasattr(self, 'timer') and self.timer.isActive():
                self.timer.stop()
            
            # 빠른 메모리 정리
            import gc
            gc.collect()
            
            print("빠른 리소스 정리 완료")
            
        except Exception as e:
            print(f"앱 종료 중 오류: {e}")
        finally:
            # 부모 클래스의 closeEvent 호출
            super().closeEvent(event)

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

    def _report_user_file_problem(self, key, title, text):
        """사용자 파일(북마크·설정)을 읽거나 쓰다 난 문제를 경고 창으로 알림: key마다 창 세션에 한 번.

        창이 보이기 전(시작할 때 읽는 파일)에는 모아 두었다가 show_user_file_problems가 알림.
        """
        if key in self._user_file_problem_keys:
            return
        self._user_file_problem_keys.add(key)
        if self._user_file_problems is not None:
            self._user_file_problems.append((title, text))
        else:
            QMessageBox.warning(self, title, text)

    def show_user_file_problems(self):
        """시작할 때 모아 둔 사용자 파일 문제를 창으로 알림 (app.launch가 창을 보인 뒤 부름). 이후 문제는 바로 알림."""
        pending, self._user_file_problems = self._user_file_problems or [], None
        for title, text in pending:
            QMessageBox.warning(self, title, text)

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


