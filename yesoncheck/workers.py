"""Threaded worker helpers for media processing and thumbnail management."""

# 워커는 워커별 모듈에 있고, 이 모듈은 기존 경로(`from yesoncheck.workers import X`)를 위해 바로 불러와 다시 내보내기만 함.
# - 앱 시작 때 sidebar_thumbnails·player_playback이 이 모듈을 부르므로 여기서 scene_workers까지 바로 불러, auto_trim(scenedetect)·
#   transnetv2_detector가 지금처럼 시작 때 불림 (TensorFlow는 첫 애니매틱2 분석 때).
# - 아래 차례는 나누기 전 이 파일의 import 차례(cv2·numpy → PyQt5 → external_tools·file_names → thumbnails → auto_trim →
#   transnetv2_detector)대로 모듈이 처음 불리게 맞춘 것.
# - 워커·도우미가 읽는 모듈 전역 이름은 그 코드가 있는 모듈의 전역임: TRANSNETV2_AVAILABLE·detect_scene_cuts_transnetv2는 scene_workers,
#   QImage는 thumbnail_workers, paddleocr_base_dir는 ocr_worker — 시험에서 바꿔치기하려면 그 모듈에서 바꿀 것.
#   아래에서 다시 내보내는 paddleocr_base_dir·use_ascii_paddleocr_dir 등은 이 모듈에서도 같은 객체로 불려 읽을 수 있을 뿐이라,
#   여기서 그 이름을 바꿔치기해도 ocr_worker 안의 호출(use_ascii_paddleocr_dir가 부르는 paddleocr_base_dir)에는 닿지 않음.
from yesoncheck.ocr_worker import (
    OCRWorker, _ClearBeforeInput, guard_paddle_buffer_growth, paddleocr_base_dir, use_ascii_paddleocr_dir,
)
from yesoncheck.ffmpeg_worker import FFmpegWorker
from yesoncheck.ocr_export_worker import OCRExportWorker
from yesoncheck.thumbnail_workers import ThumbnailLoaderWorker, ThumbnailWorker
from yesoncheck.scene_workers import SceneDetectWorker, TransNetV2Worker
