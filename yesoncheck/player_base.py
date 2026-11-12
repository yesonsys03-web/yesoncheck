"""Main window implementation for the YesonCheck application."""

import datetime
import os
import sys
import time
import traceback

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

from yesoncheck.video_widget import VIEWPORT_ENV, CustomVideoWidget
from yesoncheck import bookmarks, build_info, default_app, downscale_filter, error_window, external_tools, file_associations, \
    instance_link, instances, mac_native_gate, mac_prefs, manual_open, media_player_log, paths, timing_log, user_files, \
    video_list, windows_display
from yesoncheck.movie_pipe_source import movie_source_mode
from yesoncheck.user_files import UserFileError
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
from yesoncheck.player_hover_thumbs import PlayerHoverThumbsMixin
from yesoncheck.player_ocr import PlayerOcrMixin
from yesoncheck.player_overlay import PlayerOverlayMixin
from yesoncheck.slider_style import jump_to_click
from yesoncheck.update_banner import UpdateBanner
from yesoncheck.window_layout import ElidedLabel, InfoRowLayout, VerticalScrollArea, startup_geometry
# 놓아 준 워커를 붙잡아 두는 코드는 worker_lifecycle에 있고, 기존 경로(`from yesoncheck.player_base import EXIT_WAIT_S, release_worker,
# wait_for_released_workers`)를 위해 여기서 다시 내보냄. _RELEASED_WORKERS는 읽는 쪽(시험)용 같은 dict 객체 — 바꿔치기하려면
# worker_lifecycle에서 할 것 (이 모듈의 이름을 바꿔도 release_worker는 worker_lifecycle의 것을 씀)
from yesoncheck.worker_lifecycle import EXIT_WAIT_S, _RELEASED_WORKERS, release_worker, wait_for_released_workers

# Settings → '재생 디코더 (Mac)' (스펙 2026-11-04 §5.4) — 항목 차례는 mac_native_gate.DECODERS
DECODER_MENU_TEXT = "재생 디코더 (Mac)"
DISPLAY_TITLE = "화면 그리기 설정"  # Settings → 화면 그리기 (Windows) — windows_display
DISPLAY_TIP = "이 PC의 설정 파일(prefs.json)에 저장합니다 — 다음에 여는 창부터 적용됩니다"
DECODER_ACTION_TEXTS = {"videotoolbox": "VideoToolbox (기본)", "ffmpeg": "ffmpeg (예전 방식)"}
DECODER_SAVE_TITLE = "재생 디코더 설정"  # 저장 실패 창 제목 (app.load_playback_decoder의 읽기 실패 창과 같은 제목)
DECODER_TIP = "이 창은 바로 바꾸고 이 Mac의 설정 파일(prefs.json)에 저장합니다 — 이미 열린 다른 창은 다음에 켤 때부터 따릅니다"
DECODER_ENV_SOURCE_PREFIX = "환경 변수"  # mac_native_gate.effective_decoder가 환경 변수(YESONCHECK_MAC_NATIVE=on|off)가 덮을 때 돌려주는 출처의 머리
DECODER_CV2_TIP = "YESONCHECK_MOVIE_SOURCE=cv2가 모든 빠른 디코더를 끕니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다"
GL_FALLBACK_LOG = "[표시] GL 텍스처 스트리밍 실패 — 이 창을 ffmpeg 방식으로 바꿉니다"  # 네이티브 그리기 실패 폴백의 기록 줄 (스펙 2026-11-04 §5.8)
KEEP_LATCH_LOG = "[표시] 네이티브 프레임이 아직 남아 걸쇠를 풀지 않음 — 다시 그리면 또 실패하므로 영상 영역은 비워 둠"
DECODER_RETRY_LOG = "[재생] 이 창은 그리기가 멈춰 있어(걸쇠) ffmpeg로 캡처를 다시 바꿔 끼우고 걸쇠를 정리함"  # 메뉴에서 이미 유효한 ffmpeg를 다시 고름 (Ruling 11, 최종 리뷰 F1)
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


class VideoPlayerBase(PlayerHoverThumbsMixin, PlayerOcrMixin, PlayerOverlayMixin, QMainWindow):
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
        
        # 드래그 미리보기 값(cache_size·frame_skip_threshold·drag_update_interval)과 performance_mode는 고정 — Settings의
        # '4K 성능 모드'는 뺌(2026-11-12: 같은 이름의 처리기가 둘이라 고른 모드가 적용된 적이 없었음). 이 값이 모든 창이 늘 쓰던 값
        self.performance_mode = 'auto'  # optimize_for_4k가 읽음 — 늘 'auto'
        self.preview_mode = False  # 드래그 중 프리뷰 모드
        self.frame_skip_threshold = 5  # 프레임 스킵 임계값
        
        # 드래그 최적화를 위한 변수들
        self.last_drag_update = 0
        self.drag_update_interval = 30  # 30ms로 단축 (33fps)
        self.is_dragging = False
        
        # 고급스러운 메인 윈도우 스타일 적용
        self.setStyleSheet(DARK_STYLESHEET)
        
        self.controls_visible = True  # initUI() 호출 전에 먼저 정의
        self.middle_panel_visible = True  # N 키로 숨기는 가운데 컨트롤 열 (middleScrollArea)
        self._middle_panel_width = 220  # 숨기기 전 가운데 열의 스플리터 폭 (초기 setSizes의 220 — 숨긴 동안 0이 적히면 복원용)
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
        self.timer.setTimerType(Qt.PreciseTimer)  # 기본(Coarse)은 5% 안에서 간격을 바꿈 — 24fps가 25fps로 돌았음 (playback_clock)
        self.timer.timeout.connect(self.next_frame_playback)
        self._playback_clock = None  # 재생 틱의 시각표 — play_video가 Play마다 새로 만듦
        self.videoWidget.fitToWindowChanged.connect(self.on_fit_to_window_changed)
        

        
        # 오버레이 컨트롤 생성
        self.create_overlay_controls()
        self._init_hover_thumbs()  # 슬라이더 호버 썸네일 — 두 슬라이더가 창 안에 들어간 뒤 (필터가 slider.window()에도 걸림)
        
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
        # 색 변환(BGR → RGB)은 늘 CPU — Settings의 'GPU Acceleration'은 뺌(2026-11-12: 고른 값이 적용된 적이 없었고, OpenCL 변환은
        # CPU보다 느림 — 이 Mac 실측 4K 2.8ms 대 25ms). process_frame·optimize_for_4k의 GPU 갈래는 이 값이 False라 타지 않음
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
        self.playback_fps_counter = 0  # 재생 틱(next_frame_playback)이 진행한 프레임 수 — update_playback_fps가 틱마다 읽고 0으로
        self._playback_fps_tick = time.monotonic()  # 지난 틱 시각 (실제 fps = 진행한 수 ÷ 걸린 시간)
        self._playback_fps_was_playing = False  # 지난 틱에 재생 중이었나 — 재생 시작 뒤 첫 틱은 부분 구간이라 실제 fps를 적지 않음
        self.playback_fps_measured = None  # 지난 틱의 실제 fps (재생 중이 아니거나 첫 틱이면 None)
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
            self._media_player_log = media_player_log.attach(player)  # 출력 장치·상태·오류를 [소리] 줄로 (Windows 11 소리 조사, 2026-11-09)
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
        self.videoWidget.apply_theme_background(self.current_theme)  # 시작 테마가 바뀌어도 GL 여백 색이 따라오게
        self.videoWidget.wipePositionChanged.connect(self.update_frame)
        self.videoWidget.set_overlay_provider(self._overlay_text_for_native)  # B 키 글자 — 네이티브 프레임은 굽지 않고 위젯의 아이템으로
        self.videoWidget.set_annotation_provider(self._annotations_for_native)  # 주석도 — 네이티브 프레임은 위젯의 주석 층으로
        self.videoWidget.streamPaintFailed.connect(self._on_stream_paint_failed)  # (Mac) 네이티브 그리기 첫 실패 → 이 창만 ffmpeg
        self.videoWidget.roiSelectionFinished.connect(self.on_roi_selected)
        self.init_annotation_system()

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
        self.labelPlaybackFPS = ElidedLabel(Qt.ElideRight, keep_text="재생: 00.000 FPS · 실제 00.0", keep_prefix="",
                                            hint_width=150, fit_text="재생: 00.000 FPS · 실제 00.0", shrink_order=2,
                                            collapse_order=6)  # 재생 FPS 표시 위젯 — 재생 중엔 실제로 그린 fps도 (update_playback_fps)
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
        # All 탭: Mov·Seq 목록을 한 목록에 섞어 보여 줌 (항목은 복제 — 만들기·동작은 sidebar_all.SidebarAllMixin)
        self.all_sidebar = QListWidget(); self.all_sidebar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.all_sidebar.setSelectionMode(QListWidget.ExtendedSelection)
        self.all_sidebar.itemClicked.connect(self.on_all_item_clicked)
        self.all_sidebar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.all_sidebar.customContextMenuRequested.connect(self.show_all_context_menu)
        self.all_sidebar.installEventFilter(self)  # 목록이 포커스를 가져도 전역 단축키(프레임 이동 등)가 먹게
        self.all_sidebar.setFocusPolicy(Qt.StrongFocus)
        self.sidebar_tabs = QTabWidget()
        self.sidebar_tabs.addTab(self.sidebar, 'Mov')
        self.sidebar_tabs.addTab(self.seq_sidebar, 'Seq')
        self.sidebar_tabs.addTab(self.all_sidebar, 'All')
        self.sidebar_tabs.setFocusPolicy(Qt.NoFocus)
        self.sidebar_tabs.currentChanged.connect(self._on_sidebar_tab_changed)
        self.sidebar_count_label = QLabel()  # 목록 아래 개수 줄 — 지금 보는 탭의 개수 (sidebar_all·sidebar_counts)
        self.sidebar_count_label.setWordWrap(True)  # All의 포맷이 많아도 줄을 바꿈 — 사이드바(창) 최소 너비를 늘리지 않게
        self._init_all_tab_hooks()  # Mov·Seq 모델 변화 → All 목록 미룬 다시 만들기·개수 줄
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
        sidebarLayout.addWidget(self.sidebar_count_label)
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
        workLabel.setFocusPolicy(Qt.NoFocus)
        volumeLabel.setFocusPolicy(Qt.NoFocus)
        self.frameRateLabel.setFocusPolicy(Qt.NoFocus)

        # 메인 윈도우가 항상 키보드 이벤트를 받을 수 있도록 설정
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocus()  # 초기 포커스 설정

    def toggle_middle_panel(self):
        """N 키 — 가운데 컨트롤 열(middleScrollArea) 보이기/숨기기 (왼쪽 파일 목록·비디오는 그대로)."""
        self.middle_panel_visible = not self.middle_panel_visible
        if not (self.middle_panel_visible and self.controls_visible):
            sizes = self.mainSplitter.sizes()
            if sizes[1] > 0:
                self._middle_panel_width = sizes[1]
            self.middleScrollArea.setVisible(False)
            return
        self.middleScrollArea.setVisible(True)
        self._restore_middle_panel_width()

    def _restore_middle_panel_width(self):
        """가운데 열을 다시 보일 때 스플리터 폭 복원: 숨긴 동안 List/Thumb 폭 조절이 setSizes를 부르면 숨은 칸에
        0이 적혀, setVisible(True)만으로는 0폭(접힌 채)으로 나타남 — 기억한 폭을 영상 칸에서 가져와 되살림."""
        sizes = self.mainSplitter.sizes()
        if sizes[1] > 0:
            return
        sizes[1] = self._middle_panel_width
        sizes[2] = max(0, sizes[2] - self._middle_panel_width)
        self.mainSplitter.setSizes(sizes)

    def apply_middle_panel_state(self):
        """컨트롤 복원(V 키·전체화면 해제) 뒤에도 N 키로 숨긴 가운데 열은 숨김을 유지하고, 보이는 열은 폭을 되살림."""
        if not self.middle_panel_visible:
            self.middleScrollArea.setVisible(False)
        elif not self.middleScrollArea.isHidden():
            self._restore_middle_panel_width()

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

            # All 목록: 위아래 화살표는 고른 항목을 종류대로 열고, Enter·\는 선택 재생 (mov만 — sidebar_playlist가 거름)
            if source == self.all_sidebar:
                if key in [Qt.Key_Up, Qt.Key_Down]:
                    if not self.all_sidebar.hasFocus():
                        self.all_sidebar.setFocus()
                    QTimer.singleShot(10, self.load_selected_all_item)
                    return False  # 기본 동작(선택 이동) 허용
                elif key in (Qt.Key_Return, Qt.Key_Enter):
                    self.play_selected_files()
                    return True
                elif key == Qt.Key_Backslash:
                    self.toggle_play_pause_selected()
                    return True

            # Seq 목록: 위아래 화살표는 고른 시퀀스를 A로 엶 (All 목록과 같음 — 예전에는 누를 때만 열려 화살표로는 그림이 바뀌지 않았음)
            if source == self.seq_sidebar and key in [Qt.Key_Up, Qt.Key_Down]:
                if not self.seq_sidebar.hasFocus():
                    self.seq_sidebar.setFocus()
                QTimer.singleShot(10, self.load_selected_seq_item)
                return False  # 기본 동작(선택 이동) 허용

            # 사이드바 목록(Mov·Seq·All 어느 쪽이든 목록이 포커스를 가진 채)에서 먹는 단축키: 재생/정지와 확대·축소·화면 맞춤.
            # 선택 재생(Enter·\)은 재생목록 기계장치가 Mov 경로 전제라 위의 Mov·All 목록 전용
            if source in (self.sidebar, self.seq_sidebar, self.all_sidebar):
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
                self.apply_middle_panel_state()

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

            # N 키 처리 (가운데 컨트롤 열 보이기/숨기기) - 한글 ㅜ와 영문 N 모두 지원
            if key == Qt.Key_N or (hasattr(event, 'text') and event.text() == 'ㅜ'):
                self.toggle_middle_panel()
                QTimer.singleShot(100, self.force_focus)
                return True

            # P 키 처리 (북마크 관리 창) - 한글 ㅔ와 영문 P 모두 지원
            if key == Qt.Key_P or (hasattr(event, 'text') and event.text() == 'ㅔ'):
                self.show_bookmarks()
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
                frame_files = []  # 영상이 아닌 파일 — 이미지 시퀀스 프레임이면 Seq 목록에 넣음 (_dropped_frames가 이름을 봄)
                
                for url in urls:
                    file_path = paths.normalize_native(url.toLocalFile())
                    if os.path.isfile(file_path):
                        if self.is_video_file(file_path):
                            video_files.append(file_path)
                        else:
                            frame_files.append(file_path)
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
                
                # 이미지 시퀀스 프레임 파일: 그 시퀀스를 Seq 목록에 덧붙임 (열지는 않음 — Mov 목록에 놓은 영상처럼). 영상이 함께 있으면 보던 탭 그대로
                frames = self._dropped_frames(frame_files)
                if frames:
                    self._add_dropped_frames(frames, show_tab=not video_files)
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
        self.videoWidget.apply_theme_background('dark')  # GL 뷰포트는 스타일시트 배경 칠을 받지 않음
        self._apply_take_colors(repaint=True)  # Mov 항목의 테이크 색은 테마마다 다름
        self._schedule_all_rebuild()  # All 탭 시퀀스 글자 색을 테마에 맞춤

    def set_light_theme(self):
        self.setStyleSheet(LIGHT_STYLESHEET)
        self.current_theme = 'light'
        self.videoWidget.apply_theme_background('light')  # GL 뷰포트는 스타일시트 배경 칠을 받지 않음
        self._apply_take_colors(repaint=True)  # Mov 항목의 테이크 색은 테마마다 다름
        self._schedule_all_rebuild()  # All 탭 시퀀스 글자 색을 테마에 맞춤

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
        
        # 재생 디코더 서브메뉴 (Mac만 — VideoToolbox는 macOS에만 있음; Windows·Linux 메뉴는 그대로). 라디오의 체크는 맞춤 함수(_sync_decoder_menu)가 정함
        self.decoder_action_group = []  # 항목 차례(mac_native_gate.DECODERS) — Mac이 아니면 빈 채
        self.decoder_actions = {}  # 디코더 이름 → 항목
        if sys.platform == "darwin":
            decoder_menu = settings_menu.addMenu(DECODER_MENU_TEXT)
            decoder_menu.setToolTipsVisible(True)  # 비활성 사유·출처를 항목 툴팁으로 알림
            for name in mac_native_gate.DECODERS:
                action = decoder_menu.addAction(DECODER_ACTION_TEXTS[name])
                action.setCheckable(True)
                action.triggered.connect(lambda checked, decoder=name: self.set_playback_decoder(decoder))
                self.decoder_action_group.append(action)
                self.decoder_actions[name] = action
            self._sync_decoder_menu()
        self._add_display_menu(settings_menu)
        self._add_downscale_menu(settings_menu)  # (Windows) 축소 필터 — Linear·고품질 (downscale_filter)
        self._add_hover_thumbs_menu(settings_menu)  # 슬라이더 썸네일 켜기/끄기 (PlayerHoverThumbsMixin)

        # 공유 설정 폴더 변경 (Windows: PC마다 고름)
        if paths.IS_WINDOWS:
            shared_config_action = settings_menu.addAction('공유 설정 폴더 변경...')
            shared_config_action.triggered.connect(lambda: self.choose_shared_config_dir())

        # Help 메뉴
        help_menu = menubar.addMenu('&Help')
        
        # Help 액션
        help_action = help_menu.addAction('사용법')
        help_action.setShortcut('F1')
        help_action.triggered.connect(self.show_help)
        
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
    
    def set_playback_decoder(self, name: str) -> None:
        """(Mac) Settings → 재생 디코더 (Mac)에서 고른 디코더(mac_native_gate.DECODERS — videotoolbox·ffmpeg)를 이 Mac의 설정 파일에 저장하고 이 창에 바로 적용
        (스펙 2026-11-04 §5.4). 다른 창(프로세스)의 캐시는 건드리지 않음 — 다음에 켤 때 설정 파일을 따름.

        이미 그 값이 설정 파일·기본값에서 온 것이면 아무것도 하지 않고 체크만 맞춤(체크된 항목을 다시 누르면 Qt가 체크를 끔). 설정을 읽지 못해 이 세션만
        ffmpeg인 창(SOURCE_FALLBACK)에서 ffmpeg를 고르는 것은 저장이다(파일을 고쳤으면 그 값이 남음, 아직 깨져 있으면 아래 ①의 창).
        예외 — **걸쇠가 걸린 창**(_latched_under_ffmpeg: 네이티브 면이든 RGB 그림이든, 유효 ffmpeg — 자동 폴백·앞 선택의 바꿔 끼움이 열지 못해 네이티브 프레임에
        걸쇠가 걸린 채, 또는 부분 성공 뒤 와이프를 끈 창·파이프 RGB 업로드가 실패한 창): 유효 디코더가 그대로인 길(저장할 것이 없는 다시 누름, ③의 '그대로')에서도
        기록 한 줄(DECODER_RETRY_LOG) 뒤 ④⑤⑥을 다시 함 — 창 글이 권하는 'ffmpeg (예전 방식)'이 아무 일도 하지 않으면 영상 영역이 빈 채 남음(Ruling 11,
        최종 리뷰 F1). 차례:
        ① prefs.json에 저장(mac_prefs.update_pref) — 실패(깨진 파일 UserFileError·잠금 시간 초과·쓰기 실패 OSError)면 기록(트레이스백) + 오류 창 1회 +
           체크를 지금 유효한 값으로 되돌리고 끝(캐시·캡처 그대로 — 저장하지 못한 설정을 이 창에만 몰래 적용하지 않음)
        ② 게이트의 캐시를 그 값으로(출처 prefs.json) ③ 기록 한 줄 `[재생] 디코더 설정: <이름> (Setting 메뉴)` — 들어올 때와 유효 디코더(effective_decoder —
           환경 변수가 덮으면 그 값)가 같으면(이 세션만 ffmpeg였던 창에서 ffmpeg를 저장, 환경 변수가 덮는 동안) 기록 한 줄을 더하고 메뉴만 맞춤: 같은 디코더로
           다시 열면 파이프 → 파이프로 채운 전체 프레임 캐시와 [측정] 기록만 버림
        ④ 열린 A·B의 캡처를 새 디코더로 바꿔 끼움(swap_movie_captures_for_decoder — open_file을 부르지 않음). False면 그 함수가 이미 창을 띄웠으므로
           창을 더 띄우지 않고 기록 한 줄만 — 설정은 저장됐고 바꾸지 못한 쪽은 다음에 열 때부터
        ⑤ 스트림 아이템(VideoFrameItem)이면 GL 그리기 실패 걸쇠를 풂(reset_failure — 디코더를 바꾸는 것이 그 걸쇠의 탈출구). 바꿔 끼운 **뒤**에(Ruling 9):
           바꿔 끼우는 동안 뜬 창(모달)의 이벤트 루프가 아직 옛(실패하는) 프레임을 그려도 걸쇠가 걸린 채라 다시 실패하지 않고, 풀린 뒤의 paint는 새 프레임.
           단 유효 디코더가 ffmpeg인데 네이티브 면이 남았으면(바꾸지 못한 쪽) 풀지 않음 — 다시 그리면 또 실패해 창이 되풀이됨
        ⑥ 메뉴를 맞춤 — ④⑤가 예외를 내도(finally; 예외는 그대로 올림) 두 항목이 함께 체크된 채 남지 않게.
        ④⑤⑥은 네이티브 그리기 실패 폴백(_on_stream_paint_failed)과 같은 헬퍼(_swap_captures_and_settle_latch).
        name이 DECODERS 밖이면 ValueError — 파일에 쓰기 전에(나쁜 값이 저장되면 다음 시작이 그 파일을 거부함). macOS가 아니면 RuntimeError(메뉴가 없는 설정)."""
        if sys.platform != "darwin":
            raise RuntimeError(f"재생 디코더 설정은 macOS 전용입니다 (이 시스템: {sys.platform})")
        if name not in mac_native_gate.DECODERS:
            raise ValueError(f"{mac_native_gate.PREF_KEY}는 {', '.join(mac_native_gate.DECODERS)} 중 하나여야 합니다: {name!r}")
        before, source = mac_native_gate.effective_decoder()
        if name == mac_native_gate.preferred_decoder() and source in (mac_native_gate.SOURCE_PREFS, mac_native_gate.SOURCE_DEFAULT):
            if self._latched_under_ffmpeg():
                print(DECODER_RETRY_LOG, flush=True)
                self._swap_captures_and_settle_latch(f"[재생] 디코더 설정({name}): 이번에도 바꾸지 못한 쪽이 있음 — 그 쪽은 다음에 열 때부터")
                return
            self._sync_decoder_menu()
            return
        try:
            mac_prefs.update_pref(mac_native_gate.PREF_KEY, name)
        except (UserFileError, OSError) as e:  # TimeoutError(잠금)도 OSError
            details = traceback.format_exc()
            print(f"[재생] 디코더 설정을 저장하지 못해 바꾸지 않음: {name} — {mac_prefs.prefs_path()}", flush=True)
            traceback.print_exc()
            QMessageBox.critical(self, DECODER_SAVE_TITLE,
                                 f"재생 디코더 설정({DECODER_ACTION_TEXTS[name]})을 설정 파일에 저장하지 못해 바꾸지 않았습니다 — 지금 디코더 그대로입니다.\n"
                                 f"설정 파일: {mac_prefs.prefs_path()}\n이유: {type(e).__name__}: {e}\n\n{details}")
            self._sync_decoder_menu()
            return
        mac_native_gate.set_preferred_decoder(name, source=mac_native_gate.SOURCE_PREFS)
        print(f"[재생] 디코더 설정: {name} (Setting 메뉴)", flush=True)
        after, _ = mac_native_gate.effective_decoder()
        if after == before:
            if self._latched_under_ffmpeg():
                print(DECODER_RETRY_LOG, flush=True)
            else:
                print(f"[재생] 유효 디코더가 그대로({after}) — 캡처를 다시 열지 않음", flush=True)
                self._sync_decoder_menu()
                return
        self._swap_captures_and_settle_latch(
            f"[재생] 디코더 설정({name})은 저장했지만 지금 열린 영상 중 바꾸지 못한 쪽이 있음 — 그 쪽은 다음에 열 때부터")

    def _latched_under_ffmpeg(self) -> bool:
        """스트림 아이템의 그리기 실패 걸쇠가 걸린 채(네이티브 면이든 RGB 그림이든)이고 지금 유효한 디코더가 ffmpeg인가 — 메뉴에서 ffmpeg를 (다시) 고르면
        유효 디코더가 그대로여도 바꿔 끼움을 다시 하고 걸쇠를 정리할 창. 걸쇠를 풀지 않을지는 _latched_on_native_under_ffmpeg가 따로 판단(네이티브 면이 남으면 유지,
        RGB 그림이면 풀어 다시 그림). 창 글이 권하는 'ffmpeg (예전 방식)'이 아무 일도 하지 않으면 영상 영역이 빈 채 남음 — 교체 부분 성공 뒤 와이프를 끈 창,
        파이프 RGB 업로드가 실패한 창도 같음(최종 리뷰 F1)."""
        if not self.videoWidget.video_item_stream:
            return False
        return self.videoWidget.video_item.latched and mac_native_gate.effective_decoder()[0] == "ffmpeg"

    def _latched_on_native_under_ffmpeg(self) -> bool:
        """스트림 아이템의 그리기 실패 걸쇠가 네이티브(IOSurface) 면에 걸린 채이고 지금 유효한 디코더가 ffmpeg인가 — 바꿔 끼움이 그 쪽을 열지 못한 창
        (자동 폴백·메뉴 선택 뒤 — ffprobe·열기 실패, 바꿔 끼우다 예외). 그 걸쇠를 풀면 다음 paint가 같은 표면을 다시 묶다 또 실패하므로
        _swap_captures_and_settle_latch는 풀지 않음(set_playback_decoder가 유효 디코더가 그대로여도 다시 바꿔 끼울지는 더 넓은 _latched_under_ffmpeg가 판단 —
        그 뒤 네이티브 면이 남으면 여기서 걸쇠 유지, RGB면 풂). 유효 디코더가 VideoToolbox면
        네이티브 면은 고른 길이라 여기 들지 않음(풀어서 다시 그려 봄 — 다시 실패하면 자동 폴백)."""
        if not self.videoWidget.video_item_stream:
            return False
        item = self.videoWidget.video_item
        return item.latched and item.has_native_side() and mac_native_gate.effective_decoder()[0] == "ffmpeg"

    def _swap_captures_and_settle_latch(self, swap_failed_log: str) -> None:
        """지금 유효한 디코더로 열린 캡처를 바꿔 끼우고(swap_movie_captures_for_decoder — False면 그 함수가 창을 띄웠으므로 swap_failed_log 한 줄만) →
        스트림 아이템의 걸쇠를 바꿔 끼운 **뒤**에 풂(reset_failure — Ruling 9) — 단 _latched_on_native_under_ffmpeg면 풀지 않고 KEEP_LATCH_LOG 한 줄 →
        메뉴를 맞춤. 바꿔 끼우다 예외가 나도 걸쇠 판단과 메뉴 맞춤은 하고(finally) 예외는 그대로 올림. Setting 메뉴(set_playback_decoder)와 네이티브
        그리기 실패 폴백(_on_stream_paint_failed)이 함께 씀(Ruling 11)."""
        try:
            try:
                if not self.swap_movie_captures_for_decoder():
                    print(swap_failed_log, flush=True)
            finally:
                if self.videoWidget.video_item_stream:
                    if self._latched_on_native_under_ffmpeg():
                        print(KEEP_LATCH_LOG, flush=True)
                    else:
                        self.videoWidget.video_item.reset_failure()
        finally:
            self._sync_decoder_menu()

    def _on_stream_paint_failed(self, native: bool) -> None:
        """(Qt 루프 — CustomVideoWidget.streamPaintFailed) 스트림 아이템이 그리기에 실패했다고 알림(걸쇠 사이마다 첫 실패; 기록·오류 창은 아이템이 이미
        냄 — 여기서 창을 더 띄우지 않음). 네이티브(IOSurface) 면을 그리다 난 실패이고 macOS면 **큰 소리 폴백**(스펙 2026-11-04 §5.8·§7-9): 이 창(프로세스)만
        ffmpeg로 바꿔 계속 — 설정 파일(prefs.json)은 쓰지 않으므로 다음 창은 다시 VideoToolbox를 시도한다. 차례:
        ① 게이트 캐시를 ffmpeg로(출처 mac_native_gate.SOURCE_GL_FALLBACK) ② 기록 한 줄 GL_FALLBACK_LOG ③ 열린 캡처를 바꿔 끼움(swap_movie_captures_for_decoder —
           False면 그 함수가 창을 띄웠으므로 기록 한 줄만) ④ 아이템의 그림에 네이티브 면이 더 없으면 걸쇠를 풂(reset_failure — 바꿔 끼운 **뒤**: 그동안 뜬
           창의 이벤트 루프가 옛 프레임을 그려도 다시 실패하지 않게, Ruling 9) ⑤ 메뉴를 맞춤(체크 ffmpeg, 툴팁에 그 출처). ③이 예외를 내도 ④⑤는 함(finally)
           뒤 예외를 그대로 올림(코드·빌드 쪽 — PyQt가 sys.excepthook으로). ③④⑤는 Setting 메뉴와 같은 헬퍼(_swap_captures_and_settle_latch — Ruling 11).
        ④에서 네이티브 면이 남아 있으면(바꾸지 못한 쪽 — ffprobe·열기 실패, 바꿔 끼우다 예외) 걸쇠를 그대로 두고 기록 한 줄: 풀면 다음 paint가 같은
        표면을 다시 묶다 또 실패해 창 → 폴백 → 창이 끝없이 되풀이됨. 그 영역은 빈 채 — 창 글이 권하는 Settings → 재생 디코더 (Mac) → ffmpeg (예전 방식)을
        고르면 다시 바꿔 끼움(set_playback_decoder의 '걸쇠가 걸린 창'; 캐시는 이미 ffmpeg라 바꾸지 못한 쪽은 다음에 열 때도 ffmpeg).
        환경 변수 YESONCHECK_MAC_NATIVE(on·off)가 디코더를 덮으면 캐시를 바꿔도 같은 디코더로 다시 열리므로 바꾸지 않고 기록 한 줄(걸쇠·빈 영역 그대로).
        RGB 면 실패(native False)·macOS 밖은 아무것도 하지 않음 — 예전 규칙(걸쇠·창·빈 영역; Mac의 탈출구는 Settings → 재생 디코더 (Mac))."""
        if not native or sys.platform != "darwin":
            return
        _, source = mac_native_gate.effective_decoder()
        if source.startswith(DECODER_ENV_SOURCE_PREFIX):
            print(f"[표시] GL 텍스처 스트리밍 실패 — 디코더를 바꾸지 않음(우선: {source}) — 영상 영역은 비워 둠", flush=True)
            return
        mac_native_gate.set_preferred_decoder("ffmpeg", source=mac_native_gate.SOURCE_GL_FALLBACK)
        print(GL_FALLBACK_LOG, flush=True)
        self._swap_captures_and_settle_latch("[표시] ffmpeg 방식으로 바꾸지 못한 쪽이 있음 — 그 쪽은 다음에 열 때부터 ffmpeg")

    def _add_display_menu(self, settings_menu):
        """(Windows) Settings → 화면 그리기 — CPU·GPU 라디오와 '지금 이 창' 줄. 다른 플랫폼은 메뉴 없음(Mac은 늘 GL)."""
        self.display_actions = {}
        self.display_status_action = None
        if sys.platform != "win32":
            return
        menu = settings_menu.addMenu(windows_display.MENU_TEXT)
        menu.setToolTipsVisible(True)
        for name in windows_display.RENDERERS:
            action = menu.addAction(windows_display.ACTION_TEXTS[name])
            action.setCheckable(True)
            action.triggered.connect(lambda checked, renderer=name: self.set_display_renderer(renderer))
            self.display_actions[name] = action
        menu.addSeparator()
        self.display_status_action = menu.addAction("")
        self.display_status_action.setEnabled(False)
        self._sync_display_menu()
        menu.aboutToShow.connect(self._sync_display_menu)  # 메뉴는 영상 화면(videoWidget)보다 먼저 만들어지므로 '지금 이 창'은 열 때 맞춤

    def _sync_display_menu(self):
        """체크·활성·툴팁을 설정에 맞춤. 환경 변수 YESONCHECK_VIEWPORT가 있으면 그 값으로 체크하고 비활성(메뉴보다 우선). '지금 이 창'은 실제로 그리는 쪽 — GPU를 골랐어도 다음
        창부터이거나, 이 PC의 GL이 맞지 않아 CPU일 수 있음."""
        if not self.display_actions:
            return
        forced = os.environ.get(VIEWPORT_ENV)
        if forced:
            chosen, enabled = ("gpu" if forced == "gl" else "cpu"), False
            tip = f"{VIEWPORT_ENV}={forced}가 우선합니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다"
        else:
            try:  # 창마다 프로세스 — 다른 창이 고쳤을 수 있으니 파일을 다시 읽음. 깨졌으면 기록만 남기고 지금 값으로 (시작·저장 때 창으로 알림)
                windows_display.set_preferred(windows_display.read())
            except (user_files.UserFileError, ValueError):
                traceback.print_exc()
            chosen, enabled, tip = windows_display.preferred(), True, DISPLAY_TIP
        for name, action in self.display_actions.items():
            action.setChecked(name == chosen)
            action.setEnabled(enabled)
            action.setToolTip(tip)
        widget = getattr(self, "videoWidget", None)  # 창을 만드는 중이면 아직 없음
        if widget is not None:
            self.display_status_action.setText(f"지금 이 창: {'GPU' if widget.display_path() == 'gl' else 'CPU'}")

    def set_display_renderer(self, name):
        """(Windows) 메뉴에서 고른 화면 그리기를 이 PC의 설정 파일에 저장. 뷰포트는 창을 만들 때 정하므로 다음에 여는 창부터 적용 — 지금 창은 그대로. 저장 실패는 창으로 알리고 바꾸지 않음
        (깨진 파일을 덮지 않음). 파일이 이미 그 값이면 아무것도 하지 않음 — 이 창의 캐시가 아니라 파일과 견줌(창마다 프로세스라 다른 창이 고쳤을 수 있음)."""
        try:
            if windows_display.read() == name:
                self._sync_display_menu()
                return
            windows_display.save(name)
        except (user_files.UserFileError, OSError, TimeoutError) as exc:
            traceback.print_exc()
            QMessageBox.critical(self, DISPLAY_TITLE, f"화면 그리기 설정을 저장하지 못해 바꾸지 않았습니다.\n{exc}")
            self._sync_display_menu()
            return
        windows_display.set_preferred(name)
        print(f"[뷰포트] 화면 그리기 설정: {name} (Settings 메뉴)", flush=True)
        self._sync_display_menu()
        QMessageBox.information(self, DISPLAY_TITLE, f"{windows_display.ACTION_TEXTS[name]}로 저장했습니다. 다음에 여는 창부터 적용됩니다.\n{self.display_status_action.text()}")

    def _add_downscale_menu(self, settings_menu):
        """(Windows) Settings → 축소 필터 — Linear(기본)·고품질(면적 평균) 라디오. 다른 플랫폼은 메뉴 없음(늘 Linear — 사용자 지시 'Mac은 수정하지 않아도 됨').
        체크는 파일이 아니라 이 프로세스의 캐시(downscale_filter.preferred — 이 창이 실제로 그리는 필터)를 따름."""
        self.downscale_actions = {}
        if sys.platform != "win32":
            return
        menu = settings_menu.addMenu(downscale_filter.MENU_TEXT)
        menu.setToolTipsVisible(True)
        for name in downscale_filter.FILTERS:
            action = menu.addAction(downscale_filter.ACTION_TEXTS[name])
            action.setCheckable(True)
            action.setToolTip(downscale_filter.TIPS[name])
            action.triggered.connect(lambda checked, chosen=name: self.set_downscale_filter(chosen))
            self.downscale_actions[name] = action
        self._sync_downscale_menu()

    def _sync_downscale_menu(self):
        """체크를 이 창의 필터(캐시)에 맞춤 — 만들 때·고른 뒤(저장 실패면 되돌림)."""
        for name, action in self.downscale_actions.items():
            action.setChecked(name == downscale_filter.preferred())

    def set_downscale_filter(self, name):
        """(Windows) 메뉴에서 고른 축소 필터를 이 PC의 설정 파일에 저장하고 **이 창에 바로** 적용(지금 프레임을 다시 그림 — 영상 아이템이 그릴 때마다 캐시를 봄).
        이미 열린 다른 창(프로세스)은 다음에 켤 때부터. 모르는 이름은 쓰기 전에 ValueError. 이 창이 이미 그 필터면 체크만 맞춤(체크된 항목을 다시 누르면 Qt가 끔).
        파일이 이미 그 값이면 쓰지 않고(다른 창이 먼저 저장) 이 창에만 적용, 파일의 모르는 값은 고른 값으로 고침(명시적 선택). 저장 실패(깨진 파일·쓰기 오류·잠금)는
        트레이스백 + 창 + 체크 되돌림 — 필터는 그대로(깨진 파일을 덮지 않음)."""
        if name not in downscale_filter.FILTERS:
            raise ValueError(f"{downscale_filter.PREF_KEY}는 {', '.join(downscale_filter.FILTERS)} 중 하나여야 합니다: {name!r}")
        if name == downscale_filter.preferred():
            self._sync_downscale_menu()
            return
        try:
            if downscale_filter.read() != name:
                downscale_filter.save(name)
        except (user_files.UserFileError, OSError, TimeoutError) as exc:
            traceback.print_exc()
            QMessageBox.critical(self, downscale_filter.SETTINGS_TITLE, f"축소 필터 설정을 저장하지 못해 바꾸지 않았습니다.\n{exc}")
            self._sync_downscale_menu()
            return
        downscale_filter.set_preferred(name)
        print(f"{downscale_filter.LOG_PREFIX} 설정: {name} (Settings 메뉴)", flush=True)
        self._sync_downscale_menu()
        self.videoWidget.video_item.update()

    def _sync_decoder_menu(self):
        """(Mac) Settings → 재생 디코더 (Mac)의 체크·활성·툴팁을 지금 유효한 디코더(mac_native_gate.effective_decoder)에 맞춤 — 메뉴를 만들 때, 고른 뒤(저장
        실패면 되돌림), 디코더 캐시를 바꾼 다른 길(네이티브 그리기 실패 폴백) 뒤에 부름. 메뉴가 없으면(macOS가 아님) 할 일이 없음.
        - YESONCHECK_MOVIE_SOURCE=cv2(킬 스위치 — 네이티브·파이프 모두 끔): 두 항목 비활성 + DECODER_CV2_TIP (환경 변수보다 먼저 — cv2가 둘 다 덮음)
        - 환경 변수 YESONCHECK_MAC_NATIVE=on|off가 설정을 덮음(출처가 "환경 변수"로 시작): 그 값으로 체크, 두 항목 비활성 + "<출처>이|가 우선합니다 — …"(on이·off가)
        - 출처가 prefs.json·기본값: 두 항목 활성 + DECODER_TIP(다른 창은 다음에 켤 때 — 스펙 §5.2)
        - 그 밖의 출처(prefs.json을 읽지 못해 이 세션만 ffmpeg — SOURCE_FALLBACK 등): 활성, 체크된 항목의 툴팁이 그 출처 글."""
        if not self.decoder_actions:
            return
        decoder, source = mac_native_gate.effective_decoder()
        if movie_source_mode() == "cv2":
            enabled, tips = False, dict.fromkeys(self.decoder_actions, DECODER_CV2_TIP)
        elif source.startswith(DECODER_ENV_SOURCE_PREFIX):
            josa = "이" if source.endswith("=on") else "가"  # 받침 따라: on(온)이 · off(오프)가
            enabled, tips = False, dict.fromkeys(self.decoder_actions, f"{source}{josa} 우선합니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다")
        else:
            enabled, tips = True, dict.fromkeys(self.decoder_actions, DECODER_TIP)
            if source not in (mac_native_gate.SOURCE_PREFS, mac_native_gate.SOURCE_DEFAULT):
                tips[decoder] = source
        for name, action in self.decoder_actions.items():
            action.setChecked(name == decoder)
            action.setEnabled(enabled)
            action.setToolTip(tips[name])

    def show_help(self):
        """Help → 사용법(F1)·Help 단추: 사용법 매뉴얼을 엶 — 기능별 쪽·화면 그림·단축키 표·업데이트 내역이 든 HTML 한 파일을
        만들어 이 PC의 기본 프로그램(웹 브라우저)으로 (`manual_open`; 글 `manual_content`·`release_notes`, 그림 `manual_images/`).
        열지 못하면(그림이 빌드에서 빠짐·쓸 수 없음·열 프로그램 없음) 트레이스백째 오류 창."""
        try:
            path = manual_open.open_manual()
        except Exception:
            error_window.show_unexpected(manual_open.LOG_PREFIX, manual_open.OPEN_FAILED_TEXT)
            return
        print(f"{manual_open.LOG_PREFIX} 매뉴얼을 엶: {path}", flush=True)

    def require_ffmpeg(self):
        """ffmpeg 경로. 찾지 못하면 오류 창을 띄우고 None."""
        try:
            return external_tools.ffmpeg_path()
        except external_tools.ToolNotFoundError as exc:
            QMessageBox.critical(self, "ffmpeg 없음", str(exc))
            return None

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
            self._hover_thumbs_destroy()  # 슬라이더 썸네일: 띠 워커(ffmpeg) 정지도 맨 앞에 (같은 까닭) + 필터를 떼고 커서 위 창을 바로 지움
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

    def show_viewport_fallback(self):
        """GL 뷰포트 폴백 사유(video_widget이 만들 때 기록에 남기고 모아 둠)를 창으로 알림 — app.launch가
        스플래시를 닫은 뒤 부름 (위젯 생성 중 모달은 splash.finish 안에서 열려 시작 순서를 멈춤)."""
        reason, self.videoWidget.viewport_fallback_reason = self.videoWidget.viewport_fallback_reason, None
        if reason:
            error_window.show_window(reason)  # 기록(print)은 위젯이 만들 때 남겼음 — 꺼내며 비워 두 번 뜨지 않음
