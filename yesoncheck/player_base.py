"""Main window implementation for the YesonCheck application."""

import datetime
import os
import subprocess
import sys
import time

# cv2는 lazy import로 변경 (실제 사용 시점에만 로드)
# import cv2
from PyQt5.QtCore import (
    QEvent,
    QRect,
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
    QHBoxLayout,
    QLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from yesoncheck.video_widget import CustomVideoWidget
from yesoncheck import bookmarks, build_info, default_app, external_tools, file_associations, instance_link, \
    instances, paths, timing_log, video_list
from yesoncheck.main_window_styles import (
    BOOKMARK_BUTTON_STYLE,
    BOOKMARK_LIST_REFRESH_BUTTON_STYLE,
    DARK_STYLESHEET,
    FILENAME_LABEL_STYLE,
    FRAME_COUNT_LABEL_STYLE,
    LIGHT_STYLESHEET,
    LIST_MODE_BUTTON_STYLE,
    OCR_OPTION_LABEL_STYLE,
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
from yesoncheck.player_ocr import PlayerOcrMixin
from yesoncheck.player_overlay import PlayerOverlayMixin
from yesoncheck.slider_style import jump_to_click
from yesoncheck.update_banner import UpdateBanner
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


class VideoPlayerBase(PlayerOcrMixin, PlayerOverlayMixin, QMainWindow):
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
        # 사이드바 Mov·Seq 탭 (initUI가 위젯을 만듦; SidebarSequencesMixin이 씀): 탭 위젯, Seq 목록(이미지 시퀀스), 폴더를 읽어 찾은 시퀀스
        # (path_key → [SeqInfo] — 영상 경로만 돌려주는 get_video_files_from_folder와 목록을 채우는 쪽 사이)
        self.sidebar_tabs = None
        self.seq_sidebar = None
        self._folder_sequences = {}
        # Seq 썸네일의 뒤 스레드 일 (SidebarSequencesMixin이 씀): 도는 워커들(읽기·만들기), 만들 대기열, 지금 만드는 ThumbnailWorker
        self._seq_thumbnail_workers = []
        self._seq_generation_queue = []
        self._seq_generating = None
        # Mov 탭이 썸네일을 만드는 동안 시작한 Seq 썸네일 읽기를 만들기가 끝난 뒤 한 번 더 하게 하는 타이머 (SidebarSequencesMixin이 씀)
        self._seq_thumbnail_timer = QTimer(self)
        self._seq_thumbnail_timer.setSingleShot(True)
        self._seq_thumbnail_timer.timeout.connect(self._load_seq_thumbnails_after_mov)
        # 시퀀스 -> mov 일괄 내보내기 (SidebarSequencesMixin이 씀): 지금(또는 마지막) 실행의 워커(RUNNING_JOB_ATTRS가 창 닫기·업데이트 가드로 잡음)와 진행 창
        self.seq_export_worker = None
        self.seq_export_dialog = None

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
        # Mov·Seq 탭: Mov 페이지는 위의 self.sidebar 그대로 (스캔·다시 읽기·썸네일·메뉴가 모두 이 목록에 묶여 있음), Seq 페이지는 이미지
        # 시퀀스 목록. Mov 목록을 비우면 Seq 목록도 비움 (job을 바꿈·폴더를 불러옴 — 지난 시퀀스가 남지 않게). 탭 막대는 포커스를
        # 받지 않음 (←→ 프레임 이동 단축키가 탭 막대에 먹혀 탭이 바뀌지 않게 — 다른 단추들처럼; QTabWidget의 포커스 정책은 탭 막대에도 감)
        self.seq_sidebar = QListWidget(); self.seq_sidebar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.seq_sidebar.setSelectionMode(QListWidget.ExtendedSelection)
        self.seq_sidebar.itemClicked.connect(self.on_seq_item_clicked)
        self.seq_sidebar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.seq_sidebar.customContextMenuRequested.connect(self.show_seq_context_menu)
        self.seq_sidebar.installEventFilter(self)  # Mov 목록처럼 목록이 포커스를 가져도 전역 단축키(프레임 이동 등)가 먹게
        self.seq_sidebar.setFocusPolicy(Qt.StrongFocus)
        self.sidebar.model().modelAboutToBeReset.connect(self._clear_seq_items)
        self.sidebar_tabs = QTabWidget()
        self.sidebar_tabs.addTab(self.sidebar, 'Mov')
        self.sidebar_tabs.addTab(self.seq_sidebar, 'Seq')
        self.sidebar_tabs.setFocusPolicy(Qt.NoFocus)
        self.sidebar_tabs.currentChanged.connect(self._on_sidebar_tab_changed)
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
        # Seq 목록도 같은 표시 모드를 따름: 위의 Mov 쪽 슬롯이 모드를 바꾼 다음에 불리도록 그 뒤에 이음 (Mov 쪽 메서드는 그대로)
        self.listModeButton.clicked.connect(self._apply_seq_display_mode)
        self.thumbnailModeButton.clicked.connect(self._apply_seq_display_mode)

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
        sidebarLayout.addWidget(self.sidebar_tabs)  # Mov(self.sidebar)·Seq 탭
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
        # self.sidebar는 넣지 않음: 이제 Mov 탭의 페이지라, V 키·전체화면 복원이 손으로 setVisible(True)하면 Seq 탭이 보이는 동안에도
        # Mov 목록이 보이게 됨 (사이드바 컨테이너가 이미 목록 전체를 숨기고 보임 — 보이고 숨는 모습은 예전과 같음)
        self.control_widgets = [
            sidebarContainer, self.middleScrollArea, workLabel, stopButton, self.frameRateLabel, volumeLabel, self.workComboBox, self.seasonComboBox, self.jobComboBox,
            self.loopCheckBox, self.playPauseButton, self.playSelectedButton,
            self.volumeSlider, self.frameRateComboBox, self.wipeCheckBox, self.wipeXButton, self.wipeYButton, openButtonA, openButtonB, self.volumeSlider, selectFolderButton, bookmarkButton, bookmarkListButton, workPathButton, self.listModeButton, self.thumbnailModeButton, self.refreshListButton, self.thumbnailProgressBar
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
                elif key in (Qt.Key_Return, Qt.Key_Enter): 
                    self.play_selected_files()
                    return True
                elif key == Qt.Key_Backslash: 
                    self.toggle_play_pause_selected()
                    return True
            
            # 사이드바 목록(Mov·Seq 어느 쪽이든 목록이 포커스를 가진 채)에서 먹는 단축키: 재생/정지와 확대·축소·화면 맞춤.
            # 선택 재생(Enter·\)·위아래 화살표로 열기는 재생목록 기계장치가 Mov 목록 전제라 위의 Mov 목록 전용
            if source in (self.sidebar, self.seq_sidebar):
                if key == Qt.Key_Space: 
                    self.toggle_play_pause()
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
                elif self._dropped_folders_have_sequences(folder_paths):
                    # 시퀀스만 든 폴더: 영상 폴더를 놓을 때처럼 목록에 덧붙이되 Seq 탭을 보여 줌 (조용히 아무것도 안 하지 않음)
                    self._show_dropped_sequence_folders(folder_paths)
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
        ("시퀀스 MOV 만들기", "seq_export_worker"),
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
        """실행 중인 OCR·컷 감지/OCR 구간 내보내기/주석 영상 내보내기/영상 병합/시퀀스 MOV 만들기의 이름."""
        return [label for label, _worker in self.running_jobs()]

    def stop_running_jobs(self, timeout_ms=None):
        """창을 닫을 때: 실행 중인 OCR 분석·컷 감지, OCR 구간 내보내기·주석 내보내기·병합·시퀀스 MOV 만들기를 멈추고 끝날 때까지 기다립니다
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

            # Seq 썸네일의 뒤 스레드 일: 결과를 버리고 도는 워커는 끝날 때까지 붙잡아 둠 (앱이 끝나기 전에 wait_for_released_workers가 기다림)
            self._stop_seq_thumbnail_work()

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
