"""컷 감지 백그라운드 워커: 애니매틱(SceneDetectWorker — PySceneDetect)·애니매틱2(TransNetV2Worker — TransNetV2).
기존 경로 `yesoncheck.workers`에서도 불러올 수 있음."""

from pathlib import Path

import cv2
from PyQt5.QtCore import QThread, pyqtSignal

# Auto trim module import
try:
    from .auto_trim import detect_scene_cuts, detect_scene_cuts_with_opencv, SCENEDETECT_AVAILABLE
except ImportError:
    try:
        from yesoncheck.auto_trim import detect_scene_cuts, detect_scene_cuts_with_opencv, SCENEDETECT_AVAILABLE
    except ImportError:
        # Fallback if auto_trim is not available
        SCENEDETECT_AVAILABLE = False
        def detect_scene_cuts(*args, **kwargs):
            raise ImportError("auto_trim module not available")
        def detect_scene_cuts_with_opencv(*args, **kwargs):
            raise ImportError("auto_trim module not available")

# TransNetV2(애니매틱2): transnetv2_detector는 TensorFlow를 불러오지 않음 (감지를 시작할 때만 불러옴).
# 이 모듈이 깨졌다면 조용히 '없음'으로 숨기지 않고 그대로 실패해야 하므로 ImportError를 잡지 않음
from yesoncheck.transnetv2_detector import (
    TRANSNETV2_AVAILABLE, TransNetV2Stopped, detect_scene_cuts_transnetv2, transnetv2_missing,
)


class SceneDetectWorker(QThread):
    """Worker for automatic scene cut detection using PySceneDetect."""
    
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    completed = pyqtSignal(dict)  # {'segments': [...], 'fps': float, 'total_frames': int, 'cancelled': bool}
    
    def __init__(self, video_path, threshold=30.0, min_scene_len=15, detect_background_change=True, start_frame=None, end_frame=None):
        super().__init__()
        self.video_path = video_path
        self.threshold = threshold
        self.min_scene_len = min_scene_len
        self.detect_background_change = detect_background_change
        self.start_frame = start_frame  # None이면 전체, 0-based 인덱스
        self.end_frame = end_frame  # None이면 전체, 0-based 인덱스
        self._is_running = True
        self._was_cancelled = False
    
    def stop(self):
        """Stop the worker."""
        self._is_running = False
        self._was_cancelled = True
    
    def run(self):
        """Run scene detection."""
        try:
            if not Path(self.video_path).exists():
                self.error.emit(f"비디오 파일을 찾을 수 없습니다: {self.video_path}")
                return
            
            # Get video info
            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                self.error.emit("비디오를 열 수 없습니다.")
                return
            
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
            cap.release()
            
            if total_frames <= 0:
                self.error.emit("유효하지 않은 비디오 파일입니다.")
                return
            
            mode_text = "배경 변화 감지" if self.detect_background_change else "일반 컷 감지"
            self.status.emit(f"컷 감지 시작... ({mode_text}, 임계값: {self.threshold}, 최소 길이: {self.min_scene_len}프레임)")
            # print(f"[SceneDetectWorker] 컷 감지 시작: {self.video_path}")
            # print(f"[SceneDetectWorker] 모드: {mode_text}, 임계값: {self.threshold}, 최소 길이: {self.min_scene_len}프레임")
            # print(f"[SceneDetectWorker] 비디오 정보: {total_frames}프레임, {fps:.2f}fps")
            
            # Try PySceneDetect first, fallback to OpenCV
            try:
                if SCENEDETECT_AVAILABLE:
                    self.status.emit("PySceneDetect를 사용하여 컷 감지 중...")
                    # 로그 콜백 함수: status 시그널로 전달
                    def log_callback(msg):
                        self.status.emit(f"OCR: {msg}")
                    segments = detect_scene_cuts(
                        self.video_path,
                        threshold=self.threshold,
                        min_scene_len=self.min_scene_len,
                        fps=fps,
                        detect_background_change=self.detect_background_change,
                        start_frame=self.start_frame,
                        end_frame=self.end_frame,
                        log_callback=log_callback
                    )
                else:
                    self.status.emit("OpenCV를 사용하여 컷 감지 중... (PySceneDetect 미설치)")
                    # 로그 콜백 함수: status 시그널로 전달
                    def log_callback(msg):
                        self.status.emit(f"OCR: {msg}")
                    segments = detect_scene_cuts_with_opencv(
                        self.video_path,
                        threshold=self.threshold,
                        min_scene_len=self.min_scene_len,
                        fps=fps,
                        detect_background_change=self.detect_background_change,
                        start_frame=self.start_frame,
                        end_frame=self.end_frame,
                        log_callback=log_callback
                    )
            except Exception as e:
                # Fallback to OpenCV if PySceneDetect fails
                self.status.emit(f"PySceneDetect 실패, OpenCV로 전환: {e}")
                # print(f"[SceneDetectWorker] PySceneDetect 실패, OpenCV로 전환: {e}")
                # 로그 콜백 함수: status 시그널로 전달
                def log_callback(msg):
                    self.status.emit(f"OCR: {msg}")
                segments = detect_scene_cuts_with_opencv(
                    self.video_path,
                    threshold=self.threshold,
                    min_scene_len=self.min_scene_len,
                    fps=fps,
                    detect_background_change=self.detect_background_change,
                    start_frame=self.start_frame,
                    end_frame=self.end_frame,
                    log_callback=log_callback
                )
            
            if not self._is_running:
                self.status.emit("컷 감지가 취소되었습니다.")
                self.progress.emit(100)
                self.completed.emit({
                    "segments": [],
                    "fps": fps,
                    "total_frames": total_frames,
                    "cancelled": True,
                })
                return
            
            self.progress.emit(50)
            self.status.emit(f"{len(segments)}개 컷 감지됨")
            # print(f"[SceneDetectWorker] {len(segments)}개 컷 감지됨")

            # 선택 구간 필터링 (start_frame, end_frame이 지정된 경우)
            if self.start_frame is not None and self.end_frame is not None:
                original_count = len(segments)
                filtered_segments = []
                for seg in segments:
                    seg_start = seg['start_frame']
                    seg_end = seg['end_frame']
                    # 세그먼트가 선택 구간과 겹치는 경우만 포함
                    if seg_end >= self.start_frame and seg_start <= self.end_frame:
                        # 구간 경계 조정
                        adjusted_start = max(seg_start, self.start_frame)
                        adjusted_end = min(seg_end, self.end_frame)
                        seg['start_frame'] = adjusted_start
                        seg['end_frame'] = adjusted_end
                        seg['start_time'] = adjusted_start / fps
                        seg['end_time'] = adjusted_end / fps
                        seg['duration'] = (adjusted_end - adjusted_start) / fps
                        filtered_segments.append(seg)
                segments = filtered_segments
                filter_msg = f"선택 구간 필터링: {original_count}개 → {len(segments)}개 (프레임 {self.start_frame}~{self.end_frame})"
                self.status.emit(filter_msg)
                # print(f"[SceneDetectWorker] {filter_msg}")

            # Convert segments to match OCR format
            formatted_segments = []
            for idx, seg in enumerate(segments, start=1):
                formatted_seg = {
                    'start_frame': seg['start_frame'],
                    'end_frame': seg['end_frame'],
                    'start_time': seg['start_time'],
                    'end_time': seg['end_time'],
                    'duration': seg['duration'],
                    'text': seg.get('text', f'Scene_{idx:03d}'),
                    'edited_text': seg.get('edited_text', seg.get('text', f'Scene_{idx:03d}')),
                    'roi_preview': seg.get('roi_preview'),
                    'detections': seg.get('detections', []),
                }
                formatted_segments.append(formatted_seg)
            
            self.progress.emit(100)
            log_msg = f"컷 감지 완료: {len(formatted_segments)}개 구간 감지"
            self.status.emit(log_msg)
            # print(f"[SceneDetectWorker] {log_msg}")
            
            self.completed.emit({
                "segments": formatted_segments,
                "fps": fps,
                "total_frames": total_frames,
                "cancelled": self._was_cancelled,
            })
            
        except Exception as e:
            error_msg = f"컷 감지 중 오류 발생: {e}"
            self.error.emit(error_msg)
            # print(f"[SceneDetectWorker] {error_msg}")
            import traceback
            traceback.print_exc()


class TransNetV2Worker(QThread):
    """Worker for automatic scene cut detection using TransNetV2 (deep learning-based).

    TransNetV2 is specifically designed to detect both hard cuts and gradual transitions
    (dissolves, fades) which are common in animatics and storyboards.
    """

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    completed = pyqtSignal(dict)  # {'segments': [...], 'fps': float, 'total_frames': int, 'cancelled': bool}

    def __init__(self, video_path, threshold=0.5, min_scene_len=15, detect_gradual_transitions=True, post_process_histogram=False, start_frame=None, end_frame=None):
        super().__init__()
        self.video_path = video_path
        self.threshold = threshold
        self.min_scene_len = min_scene_len
        self.detect_gradual_transitions = detect_gradual_transitions
        self.post_process_histogram = post_process_histogram
        self.start_frame = start_frame  # None이면 전체, 0-based 인덱스
        self.end_frame = end_frame  # None이면 전체, 0-based 인덱스
        self._is_running = True
        self._was_cancelled = False

    def stop(self):
        """Stop the worker."""
        self._is_running = False
        self._was_cancelled = True

    def run(self):
        """Run TransNetV2 scene detection."""
        try:
            if not Path(self.video_path).exists():
                self.error.emit(f"비디오 파일을 찾을 수 없습니다: {self.video_path}")
                return

            if not TRANSNETV2_AVAILABLE:
                # 개발자용 안내(무엇이 없는지·경로)는 로그에만 (사용자 대화상자에는 쓸모가 없으므로)
                print(
                    "[TransNetV2Worker] 이 빌드에는 TensorFlow 또는 TransNetV2 가중치가 없습니다 "
                    f"(빌드 환경·spec 확인, BUILD.md): {transnetv2_missing() or 'TRANSNETV2_AVAILABLE=False'}"
                )
                self.error.emit(
                    "이 빌드에는 Animatic2(TransNetV2) 씬 감지가 포함되지 않았습니다. "
                    "Animatic (Auto Cut) 모드를 쓰세요."
                )
                return

            # Get video info
            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                self.error.emit("비디오를 열 수 없습니다.")
                return

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
            cap.release()

            if total_frames <= 0:
                self.error.emit("유효하지 않은 비디오 파일입니다.")
                return

            mode_text = "점진적 전환 감지 포함" if self.detect_gradual_transitions else "하드 컷만 감지"
            self.status.emit(
                f"TransNetV2 컷 감지 시작... ({mode_text}, 임계값: {self.threshold}, "
                f"최소 길이: {self.min_scene_len}프레임)"
            )
            # print(f"[TransNetV2Worker] 컷 감지 시작: {self.video_path}")
            # print(f"[TransNetV2Worker] 모드: {mode_text}, 임계값: {self.threshold}, 최소 길이: {self.min_scene_len}프레임")
            # print(f"[TransNetV2Worker] 비디오 정보: {total_frames}프레임, {fps:.2f}fps")

            self.progress.emit(10)

            # Run TransNetV2 detection
            try:
                self.status.emit("TransNetV2를 사용하여 컷 감지 중...")
                # 로그 콜백 함수: status 시그널로 전달
                def log_callback(msg):
                    if self._is_running:
                        self.status.emit(f"OCR: {msg}")

                segments = detect_scene_cuts_transnetv2(
                    self.video_path,
                    threshold=self.threshold,
                    min_scene_len=self.min_scene_len,
                    fps=fps,
                    detect_gradual_transitions=self.detect_gradual_transitions,
                    post_process_histogram=self.post_process_histogram,
                    start_frame=self.start_frame,
                    end_frame=self.end_frame,
                    log_callback=log_callback,
                    should_stop=lambda: not self._is_running,
                )
            except TransNetV2Stopped as stopped:
                # 멈추라는 요청(취소·영상 바꿈·창 닫기)으로 중간에 끝남: 오류가 아니라 취소로 알림 (결과 없음)
                print(f"[TransNetV2Worker] {stopped}")
                self.status.emit(str(stopped))
                self.progress.emit(100)
                self.completed.emit({
                    "segments": [],
                    "fps": fps,
                    "total_frames": total_frames,
                    "cancelled": True,
                })
                return
            except Exception as e:
                error_msg = f"TransNetV2 실패: {e}"
                self.status.emit(error_msg)
                self.error.emit(error_msg)
                # print(f"[TransNetV2Worker] {error_msg}")
                import traceback
                traceback.print_exc()
                return

            if not self._is_running:
                self.status.emit("컷 감지가 취소되었습니다.")
                self.progress.emit(100)
                self.completed.emit({
                    "segments": [],
                    "fps": fps,
                    "total_frames": total_frames,
                    "cancelled": True,
                })
                return

            self.progress.emit(80)
            self.status.emit(f"{len(segments)}개 컷 감지됨")
            # print(f"[TransNetV2Worker] {len(segments)}개 컷 감지됨")

            # 선택 구간 필터링 (start_frame, end_frame이 지정된 경우)
            if self.start_frame is not None and self.end_frame is not None:
                original_count = len(segments)
                filtered_segments = []
                for seg in segments:
                    seg_start = seg['start_frame']
                    seg_end = seg['end_frame']
                    # 세그먼트가 선택 구간과 겹치는 경우만 포함
                    if seg_end >= self.start_frame and seg_start <= self.end_frame:
                        # 구간 경계 조정
                        adjusted_start = max(seg_start, self.start_frame)
                        adjusted_end = min(seg_end, self.end_frame)
                        seg['start_frame'] = adjusted_start
                        seg['end_frame'] = adjusted_end
                        seg['start_time'] = adjusted_start / fps
                        seg['end_time'] = adjusted_end / fps
                        seg['duration'] = (adjusted_end - adjusted_start) / fps
                        filtered_segments.append(seg)
                segments = filtered_segments
                filter_msg = f"선택 구간 필터링: {original_count}개 → {len(segments)}개 (프레임 {self.start_frame}~{self.end_frame})"
                self.status.emit(filter_msg)
                # print(f"[TransNetV2Worker] {filter_msg}")

            # Convert segments to match OCR format
            formatted_segments = []
            for idx, seg in enumerate(segments, start=1):
                formatted_seg = {
                    'start_frame': seg['start_frame'],
                    'end_frame': seg['end_frame'],
                    'start_time': seg['start_time'],
                    'end_time': seg['end_time'],
                    'duration': seg['duration'],
                    'text': seg.get('text', f'Scene_{idx:03d}'),
                    'edited_text': seg.get('edited_text', seg.get('text', f'Scene_{idx:03d}')),
                    'roi_preview': seg.get('roi_preview'),
                    'detections': seg.get('detections', []),
                }
                formatted_segments.append(formatted_seg)

            self.progress.emit(100)
            log_msg = f"TransNetV2 컷 감지 완료: {len(formatted_segments)}개 구간 감지"
            self.status.emit(log_msg)
            # print(f"[TransNetV2Worker] {log_msg}")

            self.completed.emit({
                "segments": formatted_segments,
                "fps": fps,
                "total_frames": total_frames,
                "cancelled": self._was_cancelled,
            })

        except Exception as e:
            error_msg = f"컷 감지 중 오류 발생: {e}"
            self.error.emit(error_msg)
            # print(f"[TransNetV2Worker] {error_msg}")
            import traceback
            traceback.print_exc()
