"""Threaded worker helpers for media processing and thumbnail management."""

# 워커는 워커별 모듈에 있고, 이 모듈은 기존 경로(`from yesoncheck.workers import X`)를 위해 바로 불러와 다시 내보내기만 함.
# - 앱 시작 때 player_sidebar·player_playback이 이 모듈을 부르므로 여기서 scene_workers까지 바로 불러, auto_trim(scenedetect)·
#   transnetv2_detector가 지금처럼 시작 때 불림 (TensorFlow는 첫 애니매틱2 분석 때).
# - 아래 차례는 나누기 전 이 파일의 import 차례(cv2·numpy → PyQt5 → external_tools·file_names → thumbnails → auto_trim →
#   transnetv2_detector)대로 모듈이 처음 불리게 맞춘 것.
# - 워커가 읽는 모듈 전역 이름(TRANSNETV2_AVAILABLE·detect_scene_cuts_transnetv2·QImage·paddleocr_base_dir 등)은 그 워커의
#   모듈에 있음 — 시험에서 바꿔치기하려면 그 모듈에서 바꿀 것 (이 모듈에는 그 이름이 없음).
from yesoncheck.ocr_worker import (
    OCRWorker, _ClearBeforeInput, guard_paddle_buffer_growth, paddleocr_base_dir, use_ascii_paddleocr_dir,
)
from yesoncheck.ffmpeg_worker import FFmpegWorker
from yesoncheck.ocr_export_worker import OCRExportWorker
from yesoncheck.thumbnail_workers import ThumbnailLoaderWorker, ThumbnailWorker
from yesoncheck.scene_workers import SceneDetectWorker, TransNetV2Worker
