"""Threaded worker helpers for media processing and thumbnail management."""

import copy
import ntpath
import os
import re
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap

from yesoncheck import external_tools, file_names, paths

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

# TransNetV2 module import
try:
    from .transnetv2_detector import detect_scene_cuts_transnetv2, TRANSNETV2_AVAILABLE
except ImportError:
    try:
        from yesoncheck.transnetv2_detector import detect_scene_cuts_transnetv2, TRANSNETV2_AVAILABLE
    except ImportError:
        # Fallback if transnetv2_detector is not available
        TRANSNETV2_AVAILABLE = False
        def detect_scene_cuts_transnetv2(*args, **kwargs):
            raise ImportError("transnetv2_detector module not available")


class FFmpegWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, merge_function):
        super().__init__()
        self.merge_function = merge_function

    def run(self):
        try:
            self.merge_function()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))


class ThumbnailWorker(QThread):
    thumbnail_ready = pyqtSignal(str, QPixmap)
    finished = pyqtSignal()

    def __init__(self, file_path, thumbnail_size=120, thumbnail_folder=None):
        super().__init__()
        self.file_path = file_path
        self.thumbnail_size = thumbnail_size
        self.thumbnail_folder = thumbnail_folder
        self._is_running = True

    def stop(self):
        """스레드를 안전하게 중지"""
        self._is_running = False
        self.wait(3000)  # 3초 대기
        if self.isRunning():
            self.terminate()
            self.wait(2000)  # 2초 대기

    def run(self):
        cap = None
        try:
            if not self._is_running:
                return

            print(f"ThumbnailWorker 시작: {self.file_path}")

            # 썸네일 파일 경로 생성
            if self.thumbnail_folder:
                file_hash = paths.thumbnail_key(self.file_path)
                thumbnail_path = os.path.join(self.thumbnail_folder, f"{file_hash}.jpg")

                # 이미 썸네일이 존재하는지 확인
                if os.path.exists(thumbnail_path):
                    print(f"기존 썸네일 발견: {thumbnail_path}")
                    pixmap = QPixmap(thumbnail_path)
                    if not pixmap.isNull():
                        if self._is_running:
                            self.thumbnail_ready.emit(self.file_path, pixmap)
                        return
                    else:
                        print(f"기존 썸네일이 손상됨, 재생성: {thumbnail_path}")
                        try:
                            os.remove(thumbnail_path)
                        except Exception:
                            pass

            # OpenCV로 비디오 파일 열기
            cap = cv2.VideoCapture(self.file_path)
            if not cap.isOpened():
                print(f"비디오 파일을 열 수 없음: {self.file_path}")
                return

            try:
                # 첫 번째 프레임 읽기
                ret, frame = cap.read()
                if not ret or not self._is_running:
                    print(f"첫 번째 프레임을 읽을 수 없음: {self.file_path}")
                    return

                print(f"프레임 읽기 성공: {self.file_path}, frame shape: {frame.shape}")

                # 프레임을 RGB로 변환
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # 썸네일 크기 계산 (비율 유지)
                height, width = frame_rgb.shape[:2]
                aspect_ratio = width / height
                thumbnail_width = self.thumbnail_size
                thumbnail_height = int(thumbnail_width / aspect_ratio)

                print(f"썸네일 크기 계산: {thumbnail_width}x{thumbnail_height}")

                # 프레임 리사이즈
                resized_frame = cv2.resize(frame_rgb, (thumbnail_width, thumbnail_height))

                # QImage 생성
                height, width, channel = resized_frame.shape
                bytes_per_line = 3 * width
                q_image = QImage(
                    resized_frame.data,
                    width,
                    height,
                    bytes_per_line,
                    QImage.Format_RGB888,
                )

                # QImage 유효성 검사
                if q_image.isNull():
                    print(f"QImage 생성 실패: {self.file_path}")
                    return

                # QPixmap 생성
                pixmap = QPixmap.fromImage(q_image)

                # QPixmap 유효성 검사
                if pixmap.isNull():
                    print(f"QPixmap 생성 실패: {self.file_path}")
                    return

                print(
                    f"QPixmap 생성 완료: {self.file_path}, pixmap isNull: {pixmap.isNull()}, size: {pixmap.size()}"
                )

                # 디스크에 썸네일 저장
                if self.thumbnail_folder and thumbnail_path:
                    # 폴더가 없으면 생성
                    if not os.path.exists(self.thumbnail_folder):
                        os.makedirs(self.thumbnail_folder, exist_ok=True)
                    success = pixmap.save(thumbnail_path, "JPG", 85)  # JPG 품질 85
                    if success:
                        print(f"썸네일 디스크 저장 완료: {thumbnail_path}")
                    else:
                        print(f"썸네일 디스크 저장 실패: {thumbnail_path}")

                # QPixmap 유효성 검사
                if pixmap.isNull():
                    print(f"QPixmap 생성 실패: {self.file_path}")
                    return

                print(
                    f"QPixmap 생성 완료: {self.file_path}, pixmap isNull: {pixmap.isNull()}, size: {pixmap.size()}"
                )

                # 디스크에 썸네일 저장
                if self.thumbnail_folder and thumbnail_path:
                    success = pixmap.save(thumbnail_path, "JPG", 85)  # JPG 품질 85
                    if success:
                        print(f"썸네일 디스크 저장 완료: {thumbnail_path}")
                    else:
                        print(f"썸네일 디스크 저장 실패: {thumbnail_path}")

                # 메모리 정리
                del frame_rgb, resized_frame, q_image

                if self._is_running:
                    self.thumbnail_ready.emit(self.file_path, pixmap)
                    print(
                        f"썸네일 생성 완료: {self.file_path}, pixmap isNull: {pixmap.isNull()}, size: {pixmap.size()}"
                    )

            except Exception as e:
                print(f"썸네일 생성 중 오류: {self.file_path}, 오류: {e}")

        except Exception as e:
            print(f"ThumbnailWorker 실행 중 오류: {self.file_path}, 오류: {e}")

        finally:
            # 리소스 정리
            if cap is not None:
                cap.release()

            # 메모리 정리
            import gc

            gc.collect()

            if self._is_running:
                self.finished.emit()


class ThumbnailLoaderWorker(QThread):
    """백그라운드에서 디스크에 저장된 썸네일들을 로드하는 워커"""

    loading_progress = pyqtSignal(int, int)  # current, total
    loading_finished = pyqtSignal()
    thumbnail_loaded = pyqtSignal(str, QPixmap)

    def __init__(self, thumbnail_folder, current_files):
        super().__init__()
        self.thumbnail_folder = thumbnail_folder
        self.current_files = current_files
        self._is_running = True

    def stop(self):
        self._is_running = False
        self.wait(3000)  # 3초 대기
        if self.isRunning():
            self.terminate()
            self.wait(2000)  # 2초 대기

    def run(self):
        try:
            if not os.path.exists(self.thumbnail_folder):
                print(f"썸네일 폴더가 존재하지 않음: {self.thumbnail_folder}")
                return

            loaded_count = 0
            total_files = len(self.current_files)

            for file_path in self.current_files:
                if not self._is_running:
                    break

                try:
                    # 파일 해시로 썸네일 경로 생성
                    file_hash = paths.thumbnail_key(file_path)
                    thumbnail_path = os.path.join(self.thumbnail_folder, f"{file_hash}.jpg")

                    if os.path.exists(thumbnail_path):
                        pixmap = QPixmap(thumbnail_path)
                        if not pixmap.isNull():
                            self.thumbnail_loaded.emit(file_path, pixmap)
                            loaded_count += 1
                            print(f"백그라운드 썸네일 로드: {file_path}")

                except Exception as e:
                    print(f"썸네일 로드 중 오류: {file_path}, 오류: {e}")

                # 진행상황 보고
                self.loading_progress.emit(loaded_count, total_files)

                # CPU 부하 감소를 위한 짧은 대기
                self.msleep(10)

            print(f"백그라운드 썸네일 로딩 완료: {loaded_count}/{total_files}")

        except Exception as e:
            print(f"ThumbnailLoaderWorker 실행 중 오류: {e}")
        finally:
            self.loading_finished.emit()


class _ClearBeforeInput:
    """Paddle 입력 텐서 래퍼: 새 입력을 넣기 직전에 이전 실행의 중간 텐서를 비운다.

    paddle 3.0.0(macOS) 추론은 입력 크기(배치 수·폭)가 두 번째로 커질 때
    "(NotFound) No allocator found for the place, Place(undefined:0) [operator < matmul > error]"로 실패한다.
    예: 글자 상자 수가 1→2→1→3으로 바뀌면 3에서 실패 (2.6.2에는 없는 버그).
    매번 중간 텐서를 비우면 매 실행이 첫 할당처럼 동작해 피할 수 있다. 결과·속도는 동일함을 확인.
    (실행 직전에 비우면 방금 넣은 입력까지 지워지므로 입력 복사 직전에 비움)
    """

    def __init__(self, tensor, predictor):
        self._tensor = tensor
        self._predictor = predictor

    def copy_from_cpu(self, array):
        self._predictor.clear_intermediate_tensor()
        return self._tensor.copy_from_cpu(array)

    def __getattr__(self, name):
        return getattr(self._tensor, name)


def guard_paddle_buffer_growth(ocr_engine):
    """PaddleOCR 엔진의 검출·분류·인식 predictor에 _ClearBeforeInput을 적용한다.

    검출·인식은 항상 있어야 하므로 직접 접근한다 (paddleocr 내부 이름이 바뀌면 회피가 조용히 빠지지 않고
    AttributeError로 드러나게). 분류기는 use_angle_cls=False면 만들어지지 않는다.
    주의: rec_algorithm을 SRN/SAR/RobustScanner/CAN으로 바꾸면 paddleocr가 입력 핸들을 직접 써서 이 회피가 적용되지 않는다.
    """
    stages = [ocr_engine.text_detector, ocr_engine.text_recognizer]
    if hasattr(ocr_engine, "text_classifier"):
        stages.append(ocr_engine.text_classifier)
    for stage in stages:
        stage.input_tensor = _ClearBeforeInput(stage.input_tensor, stage.predictor)


def paddleocr_base_dir(platform=sys.platform, environ=os.environ):
    """Windows: OCR 모델을 둘 ASCII 경로 (사용자 이름이 한글이면 paddle이 홈 폴더의 모델을 못 읽음). 그 외 None."""
    if platform != "win32":
        return None
    return ntpath.join(environ["ProgramData"], "YesonCheck", "paddleocr") + "\\"


def use_ascii_paddleocr_dir():
    """PaddleOCR 생성 전에 호출: 모델 폴더(BASE_DIR)를 바꿈. 모델이 없으면 그 폴더에 내려받음."""
    base_dir = paddleocr_base_dir()
    if base_dir is None:
        return
    import paddleocr.paddleocr as paddleocr_module

    paddleocr_module.BASE_DIR = base_dir


class OCRWorker(QThread):
    """Run OCR over a video ROI, detect text changes, and export clips."""

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    completed = pyqtSignal(dict)  # {'segments': [...], 'fps': float, 'total_frames': int}

    def __init__(
        self,
        video_path,
        roi_normalized,
        diff_threshold=8.0,
        frame_step=1,
        tracking_enabled=False,
        start_frame=None,
        end_frame=None,
        ocr_mode='titmouse',
        pattern=None,  # All 모드용 사용자 정의 패턴
    ):
        super().__init__()
        self.video_path = video_path
        self.roi_normalized = roi_normalized
        self.diff_threshold = diff_threshold
        self.frame_step = max(1, frame_step)
        self.tracking_enabled = tracking_enabled
        self.start_frame = start_frame  # None이면 전체 분석
        self.end_frame = end_frame  # None이면 전체 분석
        self.ocr_mode = ocr_mode  # 'titmouse', 'king', 'bento', 'all'
        self.pattern = pattern  # All 모드용 패턴 (예: "### WW#_#WW - #### W")
        self._is_running = True
        self._was_cancelled = False

        # OCR 결과 캐싱 (프레임 번호 → OCR 결과)
        # LRU 캐시로 메모리 관리 (최대 50개 프레임 캐시)
        self._ocr_cache = {}
        self._cache_max_size = 50
        self._cache_access_order = []  # LRU 추적용

    def stop(self):
        self._is_running = False
        self._was_cancelled = True

    def _get_from_cache(self, frame_key):
        """캐시에서 OCR 결과 가져오기 (LRU 업데이트)"""
        if frame_key in self._ocr_cache:
            # LRU 업데이트: 최근 사용으로 이동
            if frame_key in self._cache_access_order:
                self._cache_access_order.remove(frame_key)
            self._cache_access_order.append(frame_key)
            return self._ocr_cache[frame_key]
        return None

    def _add_to_cache(self, frame_key, ocr_result):
        """OCR 결과를 캐시에 추가 (LRU 정책)"""
        # 캐시가 가득 찬 경우, 가장 오래된 항목 제거
        if len(self._ocr_cache) >= self._cache_max_size:
            if self._cache_access_order:
                oldest_key = self._cache_access_order.pop(0)
                if oldest_key in self._ocr_cache:
                    del self._ocr_cache[oldest_key]

        self._ocr_cache[frame_key] = ocr_result
        self._cache_access_order.append(frame_key)

    def _preprocess_for_red_text(self, roi_frame, scale_factor=5.0):
        """
        King 모드용: 빨간색 텍스트 인식 개선을 위한 이미지 전처리

        빨간색 텍스트를 HSV 색 공간에서 추출하고 이진화하여 인식률을 높입니다.

        Args:
            roi_frame: 원본 ROI 이미지
            scale_factor: 업스케일 배율 (기본 5.0, ROI 크기에 따라 적응형 조정)
        """
        # 먼저 업스케일 (적응형 배율로 증가하여 더 선명하게)
        upscaled = cv2.resize(roi_frame, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
        
        # 가우시안 블러로 노이즈 제거 (이진화 전)
        denoised = cv2.GaussianBlur(upscaled, (3, 3), 0)
        
        # HSV 색 공간으로 변환 (빨간색 추출에 유리)
        hsv = cv2.cvtColor(denoised, cv2.COLOR_BGR2HSV)

        # 빨간색 범위 확대 (더 넓은 범위의 빨간색 포착)
        # Saturation 최소값 40 → 30으로 낮춰 더 넓은 빨간색 포착
        # 낮은 빨간색 범위 (0~15)
        lower_red1 = np.array([0, 30, 40])
        upper_red1 = np.array([15, 255, 255])
        mask1 = cv2.inRange(hsv, lower_red1, upper_red1)

        # 높은 빨간색 범위 (165~180)
        lower_red2 = np.array([165, 30, 40])
        upper_red2 = np.array([180, 255, 255])
        mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
        
        # 두 마스크 합치기
        red_mask = cv2.bitwise_or(mask1, mask2)
        
        # 모폴로지 연산으로 노이즈 제거 및 텍스트 연결 (더 큰 커널)
        kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel_close)  # 텍스트 내부 구멍 메우기
        
        kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel_open)   # 작은 노이즈 제거
        
        # 마스크 확장 (텍스트 경계 보강)
        kernel_dilate = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        red_mask = cv2.dilate(red_mask, kernel_dilate, iterations=1)
        
        # 빨간색 텍스트 추출
        red_text = cv2.bitwise_and(upscaled, upscaled, mask=red_mask)
        
        # 그레이스케일 변환
        gray = cv2.cvtColor(red_text, cv2.COLOR_BGR2GRAY)

        # CLAHE로 대비 향상 (clipLimit 4.0 → 3.0으로 낮춰 과도한 대비 방지)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        
        # Otsu 이진화 (자동으로 최적 임계값 찾기)
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # 이진화 결과 반전 (흰색 배경에 검은색 글자 → 검은색 배경에 흰색 글자)
        # PaddleOCR은 일반적으로 어두운 배경에 밝은 글자를 더 잘 인식
        inverted = cv2.bitwise_not(binary)
        
        # 추가 모폴로지 연산으로 텍스트 굵기 보강 (인식률 향상)
        kernel_thick = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        thickened = cv2.dilate(inverted, kernel_thick, iterations=1)
        
        # 샤프닝 필터 적용 (텍스트 경계 강조)
        kernel_sharpen = np.array([
            [-1, -1, -1],
            [-1,  9, -1],
            [-1, -1, -1]
        ])
        sharpened = cv2.filter2D(thickened, -1, kernel_sharpen)
        
        # BGR로 변환 (PaddleOCR 입력용)
        result_bgr = cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)
        
        return result_bgr
    
    def _correct_scene_panel_pattern(self, text):
        """
        King 모드용: "Scene [숫자] - Panel [문자]" 패턴 보정

        OCR이 잘못 인식한 경우를 패턴 기반으로 보정합니다.
        예: "5cene 76 - Pane1 Q" → "Scene 76 - Panel Q"

        개선사항:
        - 특수문자 필터링 (!@#$%^&* 등)
        - 숫자/문자 혼동 처리 강화 (0/O, 1/I/l)
        - 문맥 기반 보정
        """
        if not text:
            return text

        import re

        # 공백 정규화 (여러 공백을 하나로)
        if text and isinstance(text, str):
            text = ' '.join(text.split())
        else:
            text = ""

        # 특수문자 필터링 (Scene/Panel 패턴에서 불필요한 특수문자 제거)
        # 단, 하이픈(-), 언더스코어(_), 마침표(.)는 유지
        text = re.sub(r'[!@#$%^&*()+=\[\]{};:\'",<>?/\\|`~]', '', text)
        
        # 패턴 1: "Scene" 강제 치환 (어떤 변형이든 Scene으로)
        # 목표: cene, ene, Scene, Scone, 5cene 등 모두 Scene으로
        # 1-1. "cene"로 끝나는 패턴 (앞에 어떤 문자가 와도, 뒤에 공백/점/하이픈/언더스코어 가능)
        text = re.sub(r'(?i)\w*[cC][eE][nN][eE](?=\s|[._\-]|\d|$)', 'Scene', text)
        # 1-2. "ene"로 끝나는 패턴 (Scene의 S가 빠진 경우)
        text = re.sub(r'(?i)(?<!\w)[eE][nN][eE](?=\s|[._\-]|\d|$)', 'Scene', text)
        
        # 패턴 2: "Panel" 강제 치환 (어떤 변형이든 Panel로)
        # 먼저 "Pane" (l이 없는 경우)를 "Panel"로 변환 (단어 경계 사용)
        text = re.sub(r'(?i)\bPane\b', 'Panel', text)
        # 그 다음 나머지 변형들 처리 (Pane1, Pane!, PaneI, Pan€l, Panei 등)
        text = re.sub(r'(?i)[Pp][aA][nN][eE€][l1!Ii]\b', 'Panel', text)
        
        # 패턴 3: Scene과 숫자 사이, 숫자와 Panel 사이 공백/기호 정리
        # "Scene_9PanelC" → "Scene 9 - Panel C"
        # "Scene9PanelA" → "Scene 9 - Panel A"
        # 먼저 Scene 뒤의 숫자를 찾아서 공백 추가
        text = re.sub(r'([Ss][cC][eE][nN][eE])[\s_]*(\d+)', r'Scene \2', text)
        
        # 숫자 뒤에 Panel이 바로 붙어있으면 " - " 추가
        text = re.sub(r'(\d+)\s*([Pp][aA][nN][eE][lL])', r'\1 - Panel', text)
        
        # Panel 뒤에 알파벳/숫자가 바로 붙어있으면 공백 추가
        text = re.sub(r'([Pp][aA][nN][eE][lL])([A-Za-z0-9])', r'Panel \2', text)
        
        # 패턴 4: 언더스코어를 하이픈과 공백으로 변환 (남아있는 경우)
        text = text.replace('_', ' - ')
        
        # 패턴 5: 하이픈 주변 공백 정규화
        text = re.sub(r'\s*[-–—]+\s*', ' - ', text)
        
        # 패턴 6: 전체 패턴 매칭 및 보정
        # "Scene [숫자] - Panel [문자/숫자]" 형식 강제
        pattern = r'([Ss][cC][eE][nN][eE])\s+(\d+)\s*[-]?\s*([Pp][aA][nN][eE][lL])\s*([A-Za-z0-9]+)'
        match = re.search(pattern, text)
        
        if match:
            scene_num = match.group(2)
            panel_id = match.group(4)

            # 패턴 6: Scene 번호 보정 (숫자/문자 혼동 처리)
            # O(문자) → 0(숫자), I/l(문자) → 1(숫자)
            scene_num_corrected = scene_num
            scene_num_corrected = scene_num_corrected.replace('O', '0').replace('o', '0')
            scene_num_corrected = scene_num_corrected.replace('I', '1').replace('l', '1')
            # 숫자만 남기기
            scene_num_corrected = ''.join(c for c in scene_num_corrected if c.isdigit())
            if scene_num_corrected:
                scene_num = scene_num_corrected

            # 패턴 7: Panel ID 보정 (혼동되기 쉬운 문자)
            panel_id_original = panel_id

            # Panel ID는 주로 문자이므로:
            # - 숫자 0 → 문자 O (단, 전체가 숫자인 경우는 제외)
            # - 숫자 1은 문맥에 따라 I 또는 그대로 (앞뒤 문자 확인)
            if not panel_id.isdigit():
                # 0 → O (Panel ID는 문자 위주)
                panel_id = panel_id.replace('0', 'O')
                # l(소문자 L) → I
                panel_id = panel_id.replace('l', 'I')

            # 패턴 8: Panel ID가 2글자 이상이고 같은 문자가 반복되면 하나로
            if len(panel_id) >= 2:
                # "AA" → "A", "BB" → "B" 등
                if all(c == panel_id[0] for c in panel_id):
                    panel_id = panel_id[0]
                # "IC" → "C" (I가 불필요하게 붙은 경우)
                elif panel_id.startswith('I') and len(panel_id) == 2 and panel_id[1].isalpha():
                    panel_id = panel_id[1]
                # "1C" → "C" (숫자 1이 불필요하게 붙은 경우)
                elif panel_id[0].isdigit() and len(panel_id) == 2 and panel_id[1].isalpha():
                    panel_id = panel_id[1]

            # 대문자로 통일
            panel_id = panel_id.upper()
            
            return f"Scene {scene_num} - Panel {panel_id}"
        
        # 패턴이 완전히 매칭되지 않으면 "Scene [숫자] - Panel" 형식인지 확인
        # Panel ID가 없는 경우: "Scene 5 - Panel" → 그대로 유지
        # 또는 "Scene 5 - Panel !", "Scene 5 - Panel ." 같은 특수 문자만 있는 경우
        pattern_no_panel = r'([Ss][cC][eE][nN][eE])\s+(\d+)\s*[-]?\s*([Pp][aA][nN][eE][lL])\s*([!.,;:]*)\s*$'
        match_no_panel = re.search(pattern_no_panel, text)
        if match_no_panel:
            scene_num = match_no_panel.group(2)
            return f"Scene {scene_num} - Panel"
        
        # 패턴이 완전히 매칭되지 않으면 부분 보정된 결과 반환
        return text
    
    def _correct_seq_pattern(self, text):
        """
        Bento 모드용: "Seq XXA_SXX" 또는 "Seq XXA_SXX - Panel X" 패턴 보정

        OCR이 잘못 인식한 경우를 패턴 기반으로 보정합니다.
        예: "5eq 01A_503" → "Seq 01A_S03"

        개선사항:
        - 특수문자 필터링
        - 숫자/문자 혼동 처리 강화
        """
        if not text:
            return text

        import re

        # 공백 정규화 (여러 공백을 하나로)
        if text and isinstance(text, str):
            text = ' '.join(text.split())
        else:
            text = ""

        # 특수문자 필터링 (Seq 패턴에서 불필요한 특수문자 제거)
        text = re.sub(r'[!@#$%^&*()+=\[\]{};:\'",<>?/\\|`~]', '', text)
        
        # 패턴 1: "Seq" 강제 치환 (어떤 변형이든 Seq로)
        # 5eq, Seq, 5eq, $eq 등 모두 Seq로
        text = re.sub(r'(?i)\w*[sS][eE][qQ](?=\s|[._\-]|\d|$)', 'Seq', text)
        text = re.sub(r'(?i)(?<!\w)[eE][qQ](?=\s|[._\-]|\d|$)', 'Seq', text)
        
        # 패턴 2: "Seq" 뒤의 숫자와 문자 패턴 정리
        # "Seq 01A_S03" 또는 "Seq 01A S03" 형식으로 정규화
        # Seq 뒤의 숫자 추출
        seq_match = re.search(r'[Ss][eE][qQ]\s*(\d+)([A-Z]?)[_\s]*[Ss]?(\d+)', text)
        if seq_match:
            seq_num = seq_match.group(1)  # "01"
            seq_letter = seq_match.group(2) or ""  # "A" or "B" or ""
            seq_scene = seq_match.group(3)  # "03"

            # 숫자 보정 (O → 0, I/l → 1)
            seq_num = seq_num.replace('O', '0').replace('o', '0').replace('I', '1').replace('l', '1')
            seq_scene = seq_scene.replace('O', '0').replace('o', '0').replace('I', '1').replace('l', '1')

            # Panel 정보가 있는지 확인
            panel_match = re.search(r'[Pp][aA][nN][eE][lL!1]*\s*([A-Za-z0-9:]+)', text)
            if panel_match:
                panel_id = panel_match.group(1).upper().strip()
                # Panel ID 보정
                if not panel_id.isdigit():
                    panel_id = panel_id.replace('0', 'O').replace('l', 'I')
                # 불필요한 문자 제거
                if len(panel_id) >= 2 and panel_id[0].isdigit() and panel_id[1].isalpha():
                    panel_id = panel_id[1]  # "1A" → "A"
                return f"Seq {seq_num}{seq_letter}_S{seq_scene} - Panel {panel_id}"
            else:
                return f"Seq {seq_num}{seq_letter}_S{seq_scene}"
        
        # 패턴 3: 언더스코어를 하이픈과 공백으로 변환 (남아있는 경우)
        text = text.replace('_', ' - ')
        
        # 패턴 4: 하이픈 주변 공백 정규화
        text = re.sub(r'\s*[-–—]+\s*', ' - ', text)
        
        return text

    def _correct_titmouse_pattern(self, text):
        """
        Titmouse 모드용: "프로젝트-쇼넘버-언더바-알파벳-씬번호" 패턴 보정
        Strict format: [프로젝트코드][숫자]_[1 letter][3 digits]
        프로젝트 코드: MS, BM, TJS, PEW, ART, RTK 등 (2-4자 알파벳)
        """
        if not text:
            return text

        import re

        # 1. Normalize spacing and remove invalid chars
        text = re.sub(r'\s+', '', text) # Remove all spaces
        text = text.replace(',', '').replace('.', '')
        text = text.replace('-', '_') # Hyphen to underscore
        
        # Remove other special chars but keep underscore
        text = re.sub(r'[^A-Za-z0-9_]', '', text)

        # 프로젝트 코드 패턴: 기존 MS|BM|TJS와 새로운 프로젝트 코드 지원 (2-4자 알파벳)
        # 기존 프로젝트를 우선 매칭하도록 순서 유지
        project_pattern = r'(MS|BM|TJS|PEW|ART|RTK|[A-Z]{2,4})'

        # 1.5 Check for Reversed Pattern: [Letter][SceneNum]_[Project][ShowNum]
        # e.g. "E003_BM802" -> "BM802_E003"
        # Relaxed regex to handle surrounding noise (removed ^ and $)
        reversed_pattern = r'([A-Z0-9])([\dOQIl]{3})_?' + project_pattern + r'([\dOQIl]+)'
        rev_match = re.search(reversed_pattern, text, re.IGNORECASE)
        if rev_match:
            letter, scene, proj, show = rev_match.groups()
            # Swap to correct order for further processing
            text = f"{proj}{show}_{letter}{scene}"
            # Continue to standard processing to handle normalization (O->0, etc.)

        # 2. Try Refined Regex FIRST (Handles noise like "1B" before letter)
        # Checks for "Project Show _? Letter(noisy) Scene"
        # Removing '$' anchor to allow trailing noise (e.g. "BO02 -")
        pattern_refined = project_pattern + r'([\dOQIl]+)_?([A-Z0-9]+?)([\dOQIl]{3})'
        match = re.search(pattern_refined, text, re.IGNORECASE)
        if match:
             proj, show, letter_raw, scene = match.groups()
             
             # Normalize Show
             show = show.upper().replace('O', '0').replace('Q', '0').replace('I', '1').replace('L', '1')
             if len(show) > 3: 
                 # If > 3 digits, usually noise is appended (e.g. 8021 -> 802)
                 show = show[:3]
             else: 
                 show = show.zfill(3)

             # Normalize Scene
             scene = scene.upper().replace('O', '0').replace('Q', '0').replace('I', '1').replace('L', '1')
            
             # Normalize Letter
             # If letter_raw has multiple chars, take the last alpha
             # e.g. "1C" -> "C"
             letter_alphas = [c for c in letter_raw if c.isalpha()]
             if letter_alphas:
                 letter = letter_alphas[-1].upper()
             else:
                 # No alpha found. Check if digits can be mapped.
                 # 0->O, 1->I
                 if letter_raw:
                     l = letter_raw[-1]
                     if l == '0': letter = 'O'
                     elif l == '1': letter = 'I'
                     else: letter = l.upper() # Fallback
                 else:
                     return text # Should not happen given regex

             return f"{proj}{show}_{letter}{scene}"

        # 3. Standard Pattern (Fallback for unanchored matches)
        # ENFORCE 3 digits for Scene Number to avoid matching prefixes like "MS101" as "MS 1 0 1"
        pattern = project_pattern + r'([\dOQIl]+)_?([A-Z0-9])([\dOQIl]{3})'
        match = re.search(pattern, text, re.IGNORECASE)
        
        if match:
            proj, show, letter, scene = match.groups()
            
            # Normalize Project
            proj = proj.upper()
            
            # Normalize Show Number
            show = show.upper().replace('O', '0').replace('Q', '0').replace('I', '1').replace('L', '1')
            if len(show) != 3:
                 if len(show) > 3: 
                     show = show[:3]
                 else: 
                     show = show.zfill(3)
                 
            # Normalize Letter
            letter = letter.upper()
            if letter.isdigit():
                # Common OCR errors for letters
                if letter == '0': letter = 'O'
                elif letter == '1': letter = 'I'
                elif letter == '4': letter = 'A'
                elif letter == '8': letter = 'B'
                pass
            
            # Normalize Scene
            scene = scene.upper().replace('O', '0').replace('Q', '0').replace('I', '1').replace('L', '1')
                
            return f"{proj}{show}_{letter}{scene}"

        return text

    def _merge_nearby_boxes(self, detections, img_width, img_height):
        """
        인접한 텍스트 박스들을 병합합니다.
        같은 줄에 있고 가까이 있는 박스들을 하나로 합칩니다.

        개선사항:
        - 작은 노이즈 박스 필터링 (면적 임계값)
        - 가로/세로 배열 모두 처리
        - 텍스트 높이 불일치 처리
        """
        if not detections or len(detections) <= 1:
            return detections

        # 박스의 중심점과 크기를 계산
        boxes_info = []
        min_area_threshold = 0.0001  # 최소 면적 임계값 (정규화 좌표 기준, 전체의 0.01%)

        for det in detections:
            box = det.get("box")
            if not box or len(box) != 4:
                continue
            
            # 정규화된 좌표를 픽셀 좌표로 변환
            points = []
            for pt in box:
                if isinstance(pt, (list, tuple)) and len(pt) == 2:
                    x = pt[0] * img_width
                    y = pt[1] * img_height
                    points.append((x, y))
            
            if len(points) != 4:
                continue
            
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            
            center_x = (min_x + max_x) / 2
            center_y = (min_y + max_y) / 2
            width = max_x - min_x
            height = max_y - min_y

            # 작은 노이즈 박스 필터링 (면적이 너무 작으면 제외)
            box_area = (width / img_width) * (height / img_height)
            if box_area < min_area_threshold:
                continue

            boxes_info.append({
                "detection": det,
                "min_x": min_x,
                "max_x": max_x,
                "min_y": min_y,
                "max_y": max_y,
                "center_x": center_x,
                "center_y": center_y,
                "width": width,
                "height": height,
                "points": points,
            })
        
        if len(boxes_info) <= 1:
            return detections
        
        # X 좌표 기준으로 정렬 (왼쪽에서 오른쪽으로)
        boxes_info.sort(key=lambda b: b["min_x"])

        # 같은 줄에 있는 박스들을 그룹화
        merged_groups = []
        current_group = [boxes_info[0]]

        for i in range(1, len(boxes_info)):
            prev_box = boxes_info[i - 1]
            curr_box = boxes_info[i]

            # 같은 줄인지 판단: Y 좌표 차이가 높이 기준으로 판단
            # 높이 불일치 처리: max 높이를 사용하여 더 관대하게 판단
            max_height = max(prev_box["height"], curr_box["height"])
            min_height = min(prev_box["height"], curr_box["height"])
            avg_height = (prev_box["height"] + curr_box["height"]) / 2
            y_diff = abs(curr_box["center_y"] - prev_box["center_y"])

            # 박스 간 거리 계산
            x_gap = curr_box["min_x"] - prev_box["max_x"]

            # 같은 줄이고 가까이 있으면 같은 그룹에 추가
            # Y 차이가 작은 높이의 70% 이내이고, X 간격이 평균 높이의 250% 이내
            # (기존 50%, 200%에서 더 관대하게 조정)
            if y_diff <= min_height * 0.7 and x_gap <= avg_height * 2.5:
                current_group.append(curr_box)
            else:
                # 다른 줄이거나 너무 멀면 현재 그룹을 저장하고 새 그룹 시작
                merged_groups.append(current_group)
                current_group = [curr_box]

        if current_group:
            merged_groups.append(current_group)
        
        # 각 그룹의 박스들을 병합
        merged_detections = []
        for group in merged_groups:
            if len(group) == 1:
                merged_detections.append(group[0]["detection"])
            else:
                # 그룹 내의 모든 박스를 하나로 병합
                min_x = min(b["min_x"] for b in group)
                max_x = max(b["max_x"] for b in group)
                min_y = min(b["min_y"] for b in group)
                max_y = max(b["max_y"] for b in group)
                
                # 병합된 박스의 4개 꼭짓점
                merged_points = [
                    [round(min_x / img_width, 4), round(min_y / img_height, 4)],
                    [round(max_x / img_width, 4), round(min_y / img_height, 4)],
                    [round(max_x / img_width, 4), round(max_y / img_height, 4)],
                    [round(min_x / img_width, 4), round(max_y / img_height, 4)],
                ]
                
                # 텍스트 병합 (None 값 필터링)
                texts = [
                    str(b["detection"].get("text", "")).strip() 
                    for b in group 
                    if b["detection"].get("text") is not None and str(b["detection"].get("text", "")).strip()
                ]
                merged_text = " ".join(texts).strip() if texts else ""
                
                # 평균 score 계산
                scores = [b["detection"].get("score") for b in group if b["detection"].get("score") is not None]
                avg_score = sum(scores) / len(scores) if scores else None
                
                merged_detections.append({
                    "text": merged_text,
                    "score": avg_score,
                    "box": merged_points,
                })
        
        return merged_detections if merged_detections else detections
    
    def _merge_all_boxes(self, detections, img_width, img_height):
        """
        모든 detection 박스를 하나로 병합합니다.
        """
        if not detections:
            return None
        
        all_min_x = []
        all_max_x = []
        all_min_y = []
        all_max_y = []
        
        for det in detections:
            box = det.get("box")
            if not box or len(box) != 4:
                continue
            
            for pt in box:
                if isinstance(pt, (list, tuple)) and len(pt) == 2:
                    x = pt[0] * img_width
                    y = pt[1] * img_height
                    all_min_x.append(x)
                    all_max_x.append(x)
                    all_min_y.append(y)
                    all_max_y.append(y)
        
        if not all_min_x:
            return None
        
        min_x, max_x = min(all_min_x), max(all_max_x)
        min_y, max_y = min(all_min_y), max(all_max_y)
        
        return [
            [round(min_x / img_width, 4), round(min_y / img_height, 4)],
            [round(max_x / img_width, 4), round(min_y / img_height, 4)],
            [round(max_x / img_width, 4), round(max_y / img_height, 4)],
            [round(min_x / img_width, 4), round(max_y / img_height, 4)],
        ]

    def _normalize_titmouse_for_comparison(self, text):
        return self._correct_titmouse_pattern(text)

    def _pattern_to_regex(self, pattern):
        """
        사용자 입력 패턴을 정규식으로 변환
        # = 영문 (A-Z, a-z)
        W = 숫자 (0-9)
        _ = 언더바
        - = 하이픈
        공백 = 공백
        그 외 = 그대로 사용
        
        예: "### WW#_#WW - #### W" -> 정규식
        """
        import re
        regex = ""
        i = 0
        while i < len(pattern):
            if pattern[i] == '#':
                # 연속된 #를 하나의 그룹으로 처리
                count = 1
                while i + count < len(pattern) and pattern[i + count] == '#':
                    count += 1
                regex += f'[A-Za-z]{{{count}}}'
                i += count
            elif pattern[i] == 'W':
                # 연속된 W를 하나의 그룹으로 처리
                count = 1
                while i + count < len(pattern) and pattern[i + count] == 'W':
                    count += 1
                regex += f'[\\dOQIl]{{{count}}}'  # OCR 오류 고려 (O->0, Q->0, I->1, L->1)
                i += count
            elif pattern[i] in ['_', '-', ' ']:
                # 특수 문자는 이스케이프
                regex += re.escape(pattern[i])
                i += 1
            else:
                # 그 외 문자는 그대로
                regex += re.escape(pattern[i])
                i += 1
        return regex

    def _correct_all_pattern(self, text, pattern):
        """
        All 모드용: 사용자 정의 패턴으로 텍스트 정규화 (단순화된 버전)
        
        규칙:
        1. 사용자 패턴이 제1 순위 - 패턴 규칙을 엄격하게 따라야 함
        2. -, _ 외에는 어떤 특수문자도 사용하지 않음. 공백도 사용하지 않음.
        3. 편집 텍스트 역전 현상 생기지 않게 함 (MS101_A001 → A001_MS101 방지)
        4. 패턴에 어긋나는 텍스트도 패턴에 맞게 수정 시도
        
        Args:
            text: OCR로 인식된 텍스트 (예: "MS101 A001", "MS101,A001", "MS101A001")
            pattern: 사용자 입력 패턴 (예: "##WWW_#WWW")
        
        Returns:
            정규화된 텍스트 (예: "MS101_A001")
        """
        if not text or not pattern:
            return text

        import re

        # 1. 텍스트 전처리: 특수문자를 허용된 구분자로 변환
        # 패턴에서 허용된 구분자 확인
        pattern_sep = None
        for char in pattern:
            if char in ['_', '-']:
                pattern_sep = char
                break
        
        # 기본 구분자는 언더바
        if pattern_sep is None:
            pattern_sep = '_'
        
        # 텍스트를 대문자로 변환
        cleaned = text.upper()
        
        # 특수문자(, / . @ 등)와 공백을 패턴의 구분자로 변환
        # 먼저 기존 구분자(-, _)는 보존
        # 다른 특수문자는 모두 구분자로 변환
        cleaned = re.sub(r'[,\s/\.@#\$%\^&\*\+=\[\]\{\}\|\\:;"\'<>?`~!]', pattern_sep, cleaned)
        
        # 연속된 구분자를 하나로 통합
        cleaned = re.sub(r'[_-]+', pattern_sep, cleaned)
        
        # 2. 패턴 파싱
        pattern_parts = []
        i = 0
        while i < len(pattern):
            if pattern[i] == 'W':
                count = 1
                while i + count < len(pattern) and pattern[i + count] == 'W':
                    count += 1
                pattern_parts.append(('W', count))
                i += count
            elif pattern[i] == '#':
                count = 1
                while i + count < len(pattern) and pattern[i + count] == '#':
                    count += 1
                pattern_parts.append(('#', count))
                i += count
            elif pattern[i] in ['_', '-']:
                pattern_parts.append(('sep', pattern[i]))
                i += 1
            else:
                i += 1
        
        # 3. 패턴을 구분자로 분리하여 각 part의 패턴 구조 파악
        pattern_segments = []
        current_segment = []
        for part_type, part_value in pattern_parts:
            if part_type == 'sep':
                if current_segment:
                    pattern_segments.append(current_segment)
                    current_segment = []
            else:
                current_segment.append((part_type, part_value))
        if current_segment:
            pattern_segments.append(current_segment)
        
        # 4. 텍스트를 구분자로 분리
        # 구분자가 없으면 패턴에 맞게 구분자 삽입
        # 예: "MS109K003" → "MS109" + "_" + "K003" (패턴: ##WWW_#WWW)
        # 패턴 세그먼트 길이에 맞춰, 문자 스트림에서 타입(영문/숫자)에 맞게 추출
        # 구분자 제거한 연속 문자열에서 순서대로 소모하며, 타입이 맞지 않는 문자는 건너뛰고 다음 문자를 찾음
        char_stream = re.sub(r'[_-]+', '', cleaned)
        stream_idx = 0

        parts = []
        for seg in pattern_segments:
            # 세그먼트 내 기대 타입 시퀀스 생성
            seq = []
            for part_type, count in seg:
                seq.extend(['L'] * count if part_type == '#' else ['D'] * count)

            seg_text_chars = []
            for typ in seq:
                if stream_idx >= len(char_stream):
                    break
                ch = char_stream[stream_idx]
                if (typ == 'L' and ch.isalpha()) or (typ == 'D' and ch.isdigit()):
                    seg_text_chars.append(ch)
                    stream_idx += 1
                else:
                    # 타입이 맞지 않으면 현재 위치를 유지해 다음 세그먼트에서 사용
                    break
            parts.append(''.join(seg_text_chars))
        
        # 구분자가 없고 하나의 part만 있는 경우, 패턴에 맞게 분리
        if len(parts) == 1 and len(pattern_segments) > 1:
            single_part = parts[0]
            # 첫 번째 패턴 세그먼트 길이 계산
            first_seg_length = sum(count for _, count in pattern_segments[0])
            if len(single_part) > first_seg_length:
                # 첫 번째 세그먼트 길이만큼 분리
                first_part = single_part[:first_seg_length]
                second_part = single_part[first_seg_length:]
                parts = [first_part, second_part]
        
        # 숫자만 있거나 영문만 있는 짧은 세그먼트는 다음 세그먼트와 병합 (OCR 오류로 인한 잘못된 분리)
        # 예: ["MS109", "9", "K003"] → ["MS109", "9K003"]
        # 예: ["MS109", "I", "K003"] → ["MS109", "IK003"]
        merged_parts = []
        i = 0
        while i < len(parts):
            current_part = parts[i]
            # 숫자만 있는 세그먼트이고 다음 세그먼트가 있으면 병합
            if current_part.isdigit() and i + 1 < len(parts):
                merged_parts.append(current_part + parts[i + 1])
                i += 2
            # 영문만 있는 세그먼트(1-2자)이고 다음 세그먼트가 있으면 병합
            elif current_part.isalpha() and len(current_part) <= 2 and i + 1 < len(parts):
                merged_parts.append(current_part + parts[i + 1])
                i += 2
            else:
                merged_parts.append(current_part)
                i += 1
        parts = merged_parts
        
        # 5. 각 텍스트 part를 패턴과 매칭하면서 타입별 OCR 오류 보정
        corrected_parts = []
        for i, part in enumerate(parts):
            if i < len(pattern_segments):
                pattern_seg = pattern_segments[i]
                corrected_part = list(part)
                char_idx = 0
                
                # 패턴 세그먼트가 영문으로 시작하면, 세그먼트에서 패턴에 맞는 영문+숫자 조합을 찾아 매칭
                # 예: "97K003"에서 패턴이 "#WWW"이면, "K003"을 찾아 매칭
                # 예: "9NK003"에서 패턴이 "#WWW"이면, "K003"을 찾아 매칭 (N은 OCR 오류로 간주)
                if pattern_seg and pattern_seg[0][0] == '#':
                    # 패턴 세그먼트 구조 파악: 영문 개수와 숫자 개수
                    letter_count = sum(count for part_type, count in pattern_seg if part_type == '#')
                    digit_count = sum(count for part_type, count in pattern_seg if part_type == 'W')
                    
                    # 세그먼트에서 영문+숫자 조합 찾기 (정규식 사용)
                    # 예: "9NK003"에서 "K003" (영문 1자 + 숫자 3자) 찾기
                    pattern_str = f'[A-Z]{{{letter_count}}}\\d{{{digit_count}}}'
                    match = re.search(pattern_str, ''.join(corrected_part))
                    if match:
                        # 매칭된 부분부터 사용
                        match_start = match.start()
                        corrected_part = corrected_part[match_start:]
                        char_idx = 0
                    else:
                        # 매칭 실패 시 첫 번째 영문부터 사용 (기존 로직)
                        first_letter_idx = None
                        for idx, char in enumerate(corrected_part):
                            if char.isalpha():
                                first_letter_idx = idx
                                break
                        if first_letter_idx is not None and first_letter_idx > 0:
                            corrected_part = corrected_part[first_letter_idx:]
                            char_idx = 0
                
                for part_type, part_value in pattern_seg:
                    count = part_value
                    if part_type == '#':
                        # 영문 자리: OCR 오류 보정
                        # 0 → O, 1 → I (또는 L), Q → O
                        for j in range(count):
                            if char_idx < len(corrected_part):
                                char = corrected_part[char_idx]
                                if char == '0':
                                    corrected_part[char_idx] = 'O'
                                elif char == '1':
                                    corrected_part[char_idx] = 'I'  # 1을 I로 변환 (OCR 오류)
                                elif char == 'Q':
                                    corrected_part[char_idx] = 'O'
                                char_idx += 1
                    elif part_type == 'W':
                        # 숫자 자리: OCR 오류 보정
                        # O → 0, I/L → 1, Q → 0
                        for j in range(count):
                            if char_idx < len(corrected_part):
                                char = corrected_part[char_idx]
                                if char in ['O', 'Q']:
                                    corrected_part[char_idx] = '0'
                                elif char in ['I', 'L']:
                                    corrected_part[char_idx] = '1'
                                char_idx += 1
                
                # 패턴 세그먼트 길이를 초과하는 문자는 제거 (OCR 오류로 간주)
                # 예: "MS109I"에서 패턴이 "##WWW"이면 "MS109"까지만 사용하고 "I"는 제거
                pattern_seg_length = sum(count for _, count in pattern_seg)
                if len(corrected_part) > pattern_seg_length:
                    # 초과 문자 제거
                    corrected_part = corrected_part[:pattern_seg_length]
                
                corrected_parts.append(''.join(corrected_part))
            else:
                # 패턴에 없는 추가 세그먼트: 기본 OCR 오류 보정 적용
                corrected_part = part
                corrected_part = corrected_part.replace('O', '0').replace('Q', '0')
                corrected_part = re.sub(r'(\d)[LI]', r'\g<1>1', corrected_part)
                corrected_part = re.sub(r'[LI](\d)', r'1\g<1>', corrected_part)
                corrected_parts.append(corrected_part)
        
        # 5. 숫자와 영문 추출 (보정된 텍스트에서)
        numbers = []
        letters = []
        
        for part in corrected_parts:
            # 숫자만 있는 경우
            if part.isdigit():
                numbers.append(part)
            # 영문만 있는 경우
            elif part.isalpha():
                letters.append(part)
            # 숫자와 영문이 섞인 경우 분리
            else:
                # 숫자 추출
                num_matches = re.findall(r'\d+', part)
                numbers.extend(num_matches)
                # 영문 추출
                let_matches = re.findall(r'[A-Z]+', part)
                letters.extend(let_matches)
        
        
        # 6. 패턴에 맞게 매칭 (순서 보장 - 역전 방지)
        result = []
        num_idx = 0
        let_idx = 0
        
        for part_type, part_value in pattern_parts:
            if part_type == 'W':
                # 숫자 그룹
                count = part_value
                if num_idx < len(numbers):
                    num_str = numbers[num_idx]
                    if len(num_str) >= count:
                        result.append(num_str[:count])
                        if len(num_str) > count:
                            numbers[num_idx] = num_str[count:]
                        else:
                            num_idx += 1
                    else:
                        # 부족하면 0으로 패딩
                        result.append(num_str.zfill(count))
                        num_idx += 1
                else:
                    # 숫자 부족 - 0으로 채움
                    result.append('0' * count)
                    
            elif part_type == '#':
                # 영문 그룹
                count = part_value
                if let_idx < len(letters):
                    let_str = letters[let_idx]
                    if len(let_str) >= count:
                        result.append(let_str[:count])
                        if len(let_str) > count:
                            letters[let_idx] = let_str[count:]
                        else:
                            let_idx += 1
                    else:
                        # 부족하면 X로 패딩하여 패턴 길이 맞추기
                        padded = let_str.ljust(count, 'X')
                        result.append(padded)
                        let_idx += 1
                else:
                    # 영문 부족 - X로 채움
                    result.append('X' * count)
                    
            elif part_type == 'sep':
                # 구분자 (패턴에 명시된 구분자만 사용)
                result.append(part_value)
        
        normalized = ''.join(result)
        
        # 5. 패턴 형식 검증: -, _ 외 특수문자나 공백이 있으면 제거
        normalized = re.sub(r'[^A-Z0-9_-]', '', normalized)
        
        
        return normalized

    def _normalize_all_for_comparison(self, text, pattern):
        """All 모드용 정규화 함수 (단순화)"""
        if not text or not pattern:
            return None
        
        normalized = self._correct_all_pattern(text, pattern)
        
        # 정규화 실패 시 None 반환
        if normalized == text:
            # 이미 정규화된 형식인지 확인
            import re
            # 패턴 형식에 맞는지 확인: -, _ 외 특수문자 없음, 공백 없음
            if re.search(r'[^A-Z0-9_-]', normalized):
                return None
        
        return normalized
    
    def _levenshtein_similarity(self, s1, s2):
        """
        Levenshtein distance 기반 유사도 계산 (0.0 ~ 1.0)
        1.0 = 완전 일치, 0.0 = 완전 다름

        Args:
            s1, s2: 비교할 문자열

        Returns:
            float: 유사도 (0.0 ~ 1.0)
        """
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 1.0

        # Levenshtein distance 계산
        len1, len2 = len(s1), len(s2)
        if len1 > len2:
            s1, s2 = s2, s1
            len1, len2 = len2, len1

        # 이전 행과 현재 행만 유지 (메모리 최적화)
        prev_row = list(range(len2 + 1))

        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                # 삽입, 삭제, 교체 비용 계산
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (0 if c1 == c2 else 1)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row

        # 유사도 = 1 - (distance / max_length)
        distance = prev_row[-1]
        max_len = max(len(s1), len(s2))
        similarity = 1.0 - (distance / max_len) if max_len > 0 else 0.0
        return similarity

    def _extract_scene_part_from_pattern(self, text, pattern):
        """
        패턴에서 Scene 번호 부분만 추출 (OCR 오류 보정 포함)
        예: 패턴 '#####WWW-#####W'에서 'SCENE001-PANELA' → 'SCENE001' 추출
        'SEENE007-PANELF' → 'SCENE007' 추출 (OCR 오류 보정)
        """
        if not text or not pattern:
            return None
        
        import re
        
        # 패턴을 분석하여 첫 번째 구분자(- 또는 _) 이전까지가 Scene 번호 부분
        # 패턴에서 첫 번째 구분자 찾기
        first_sep_match = re.search(r'[-_\s]', pattern)
        if not first_sep_match:
            # 구분자가 없으면 전체가 Scene 번호
            return text
        
        # 텍스트에서 첫 번째 구분자 찾기
        text_sep_match = re.search(r'[-_\s]', text)
        if text_sep_match:
            # 첫 번째 구분자 이전까지가 Scene 번호
            scene_part = text[:text_sep_match.start()]
        else:
            # 구분자가 없으면 전체를 Scene 번호로 간주
            scene_part = text
        
        # OCR 오류 보정: Scene 관련 오인식 처리
        # SEENE, SCENE, cene 등 → SCENE으로 보정
        scene_part_upper = scene_part.upper()
        if 'EENE' in scene_part_upper or 'CENE' in scene_part_upper:
            # SEENE, SCENE 등을 SCENE으로 보정
            if scene_part_upper.startswith('SEENE'):
                scene_part = 'SCENE' + scene_part[5:]  # SEENE → SCENE
            elif scene_part_upper.startswith('SCENE'):
                scene_part = 'SCENE' + scene_part[5:]  # 이미 SCENE
            elif 'CENE' in scene_part_upper:
                # CENE이 포함되어 있으면 앞에 S 추가
                cene_pos = scene_part_upper.find('CENE')
                if cene_pos > 0:
                    scene_part = scene_part[:cene_pos] + 'SCENE' + scene_part[cene_pos + 4:]
                else:
                    scene_part = 'SCENE' + scene_part[cene_pos + 4:]
        
        return scene_part

    def _merge_noise_segments(self, segments, min_frames=3):
        """
        잡음 세그먼트를 인접 세그먼트에 병합합니다.

        OCR 오류로 인해 1-2프레임 정도의 짧은 세그먼트가 잘못 생성되는 경우,
        이를 이전 또는 다음 세그먼트에 병합합니다.

        병합 규칙:
        1. min_frames 미만의 세그먼트를 찾음
        2. 이전 세그먼트와 다음 세그먼트의 정규화된 텍스트를 비교
        3. 둘 중 하나와 같으면 해당 세그먼트에 병합
        4. 둘 다 같으면 이전 세그먼트에 병합 (연속성 우선)
        5. 둘 다 다르면 병합하지 않음 (실제 짧은 컷일 수 있음)

        Args:
            segments: 세그먼트 리스트
            min_frames: 최소 프레임 수 (이 미만은 잡음으로 간주)

        Returns:
            병합된 세그먼트 리스트
        """
        if not segments or len(segments) <= 1:
            return segments

        # 반복 병합 (한 번에 모든 잡음 제거가 안 될 수 있음)
        changed = True
        max_iterations = 10  # 무한 루프 방지
        iteration = 0

        while changed and iteration < max_iterations:
            changed = False
            iteration += 1
            merged = []
            i = 0

            while i < len(segments):
                seg = segments[i]
                seg_frames = seg['end_frame'] - seg['start_frame'] + 1

                # 짧은 세그먼트가 아니면 그대로 추가
                if seg_frames >= min_frames:
                    merged.append(seg)
                    i += 1
                    continue

                # 짧은 세그먼트: 이전/다음과 비교하여 병합 결정
                prev_seg = merged[-1] if merged else None
                next_seg = segments[i + 1] if i + 1 < len(segments) else None

                # 현재/이전/다음 세그먼트의 텍스트
                curr_text = seg.get('text', '')
                prev_text = prev_seg.get('text', '') if prev_seg else None
                next_text = next_seg.get('text', '') if next_seg else None

                # 병합 결정 (모드별 비교 로직 사용)
                merge_with_prev = False
                merge_with_next = False

                # 1-2프레임 세그먼트는 매우 공격적으로 병합 (더 낮은 threshold)
                aggressive_threshold = 0.75 if seg_frames <= 2 else 0.85

                # [New Logic] Bridge Noise: If prev and next are identical/similar, merge current noise into them
                # All 모드에서 정규화 실패한 경우는 프레임 수 제한 없이 bridge 가능
                max_bridge_frames = 2 if self.ocr_mode != 'all' else 10  # All 모드는 더 관대하게

                # N-way Bridge: 더 멀리 있는 세그먼트 찾기 (최대 5개 앞까지 확인)
                # All 모드 전용으로, 중간에 여러 개의 OCR 오류가 있어도 병합
                bridge_target_idx = None
                bridge_skip_count = 0
                if self.ocr_mode == 'all' and self.pattern and prev_text and seg_frames <= max_bridge_frames:
                    prev_norm = self._normalize_all_for_comparison(prev_text, self.pattern)

                    # 앞쪽으로 최대 5개 세그먼트 확인
                    for look_ahead in range(1, min(6, len(segments) - i)):
                        candidate_seg = segments[i + look_ahead]
                        candidate_text = candidate_seg.get('text', '')
                        candidate_norm = self._normalize_all_for_comparison(candidate_text, self.pattern)

                        if prev_norm and candidate_norm and prev_norm == candidate_norm:
                            # 이전과 일치하는 세그먼트 발견!
                            bridge_target_idx = i + look_ahead
                            bridge_skip_count = look_ahead
                            break

                    # N-way Bridge 실행
                    if bridge_target_idx is not None:
                        target_seg = segments[bridge_target_idx]
                        # 이전 세그먼트를 target까지 확장
                        prev_seg['end_frame'] = target_seg['end_frame']
                        prev_seg['end_time'] = target_seg['end_time']
                        prev_seg['duration'] = prev_seg['end_time'] - prev_seg['start_time']

                        changed = True
                        if iteration == 1:
                            skipped_texts = [segments[i + j].get('text', '') for j in range(bridge_skip_count + 1)]
                            self.status.emit(f"[노이즈 N-way Bridge] {bridge_skip_count + 1}개 세그먼트 병합: {' → '.join(skipped_texts)}")

                        # 모든 중간 세그먼트 건너뛰기
                        i += bridge_skip_count + 1
                        continue

                if prev_text and next_text and seg_frames <= max_bridge_frames:
                    is_bridgeable = False
                    if self.ocr_mode == 'titmouse':
                        prev_norm = self._normalize_titmouse_for_comparison(prev_text)
                        next_norm = self._normalize_titmouse_for_comparison(next_text)
                        if prev_norm and next_norm and prev_norm == next_norm:
                            is_bridgeable = True
                    elif self.ocr_mode == 'all' and self.pattern:
                        prev_norm = self._normalize_all_for_comparison(prev_text, self.pattern)
                        next_norm = self._normalize_all_for_comparison(next_text, self.pattern)
                        curr_norm = self._normalize_all_for_comparison(curr_text, self.pattern)
                        # 정규화 결과가 있으면 성공으로 간주
                        prev_success = prev_norm is not None
                        next_success = next_norm is not None
                        curr_success = curr_norm is not None
                        
                        # 이전과 다음이 완전히 같으면 bridge 가능 (중간 OCR 오류 무시)
                        # 예: MS109_A012 → MS109_V012 → MS109_A012
                        # 예: MS109_A016 → YA016_M109 → MS109_A016
                        # 중요: Scene 번호만 비교하지 않고 전체 정규화된 텍스트를 비교
                        # MS109_I001과 MS109_I002는 Scene 번호는 같지만 다른 씬이므로 병합하면 안 됨
                        if prev_success and next_success and prev_norm == next_norm:
                            # 이전과 다음이 완전히 같으면 중간을 bridge (현재 정규화 실패해도 무시)
                            is_bridgeable = True
                        # 또는 현재가 정규화 실패하고, 이전과 다음이 같으면 bridge 가능
                        elif not curr_success and prev_success and next_success and prev_norm == next_norm:
                            is_bridgeable = True
                    else:
                        if self._is_similar_text(prev_text, next_text, threshold=aggressive_threshold):
                            is_bridgeable = True
                    
                    if is_bridgeable:
                        # Bridge! Merge curr AND next into prev
                        # 1. Merge curr into prev
                        prev_seg['end_frame'] = seg['end_frame']
                        
                        # 2. Merge next into prev
                        prev_seg['end_frame'] = next_seg['end_frame']
                        prev_seg['end_time'] = next_seg['end_time']
                        prev_seg['duration'] = prev_seg['end_time'] - prev_seg['start_time']
                        
                        changed = True
                        if iteration == 1:
                            self.status.emit(f"[노이즈 병합(Bridge)] '{curr_text}' ({seg['start_frame']}-{seg['end_frame']}) → '{prev_text}'와 연결")
                        
                        # Skip both curr and next
                        i += 2
                        continue

                if not merge_with_prev and prev_text and curr_text:
                    if self.ocr_mode == 'titmouse':
                        # Titmouse 모드: 정규화 비교 시도
                        curr_norm = self._normalize_titmouse_for_comparison(curr_text)
                        prev_norm = self._normalize_titmouse_for_comparison(prev_text)
                        if curr_norm and prev_norm:
                            merge_with_prev = curr_norm == prev_norm
                        else:
                            # 정규화 실패 시 _is_similar_text로 대체
                            merge_with_prev = self._is_similar_text(curr_text, prev_text, threshold=aggressive_threshold)
                    elif self.ocr_mode == 'all' and self.pattern:
                        # All 모드: 씬 번호(prefix)가 같으면 병합 허용
                        def _scene_prefix(text):
                            return text.split('-', 1)[0] if text else None

                        curr_norm = self._normalize_all_for_comparison(curr_text, self.pattern)
                        prev_norm = self._normalize_all_for_comparison(prev_text, self.pattern)
                        curr_prefix = _scene_prefix(curr_norm) if curr_norm else None
                        prev_prefix = _scene_prefix(prev_norm) if prev_norm else None
                        if curr_norm and prev_norm and curr_norm == prev_norm:
                            merge_with_prev = True
                        elif curr_prefix and prev_prefix and curr_prefix == prev_prefix:
                            merge_with_prev = True
                    else:
                        # 기타 모드: _is_similar_text 사용
                        merge_with_prev = self._is_similar_text(curr_text, prev_text, threshold=aggressive_threshold)

                if next_text and curr_text:
                    if self.ocr_mode == 'titmouse':
                        # Titmouse 모드: 정규화 비교 시도
                        curr_norm = self._normalize_titmouse_for_comparison(curr_text)
                        next_norm = self._normalize_titmouse_for_comparison(next_text)
                        if curr_norm and next_norm:
                            merge_with_next = curr_norm == next_norm
                        else:
                            # 정규화 실패 시 _is_similar_text로 대체
                            merge_with_next = self._is_similar_text(curr_text, next_text, threshold=aggressive_threshold)
                    elif self.ocr_mode == 'all' and self.pattern:
                        # All 모드: 씬 번호(prefix)가 같으면 병합 허용
                        def _scene_prefix(text):
                            return text.split('-', 1)[0] if text else None

                        curr_norm = self._normalize_all_for_comparison(curr_text, self.pattern)
                        next_norm = self._normalize_all_for_comparison(next_text, self.pattern)
                        if curr_norm and next_norm:
                            if curr_norm == next_norm:
                                merge_with_next = True
                            else:
                                curr_prefix = _scene_prefix(curr_norm)
                                next_prefix = _scene_prefix(next_norm)
                                if curr_prefix and next_prefix and curr_prefix == next_prefix:
                                    merge_with_next = True
                                else:
                                    merge_with_next = False
                        else:
                            merge_with_next = False
                    else:
                        # 기타 모드: _is_similar_text 사용
                        merge_with_next = self._is_similar_text(curr_text, next_text, threshold=aggressive_threshold)

                if merge_with_prev:
                    # 이전 세그먼트에 병합 (end_frame 확장)
                    prev_seg['end_frame'] = seg['end_frame']
                    prev_seg['end_time'] = seg['end_time']
                    prev_seg['duration'] = prev_seg['end_time'] - prev_seg['start_time']
                    changed = True
                    # 병합 로그
                    if iteration == 1:  # 첫 번째 반복에서만 로그 출력
                        self.status.emit(f"[노이즈 병합] '{curr_text}' ({seg['start_frame']}-{seg['end_frame']}, {seg_frames}프레임) → 이전 '{prev_text}'로 병합")
                elif merge_with_next and not merge_with_prev:
                    # 다음 세그먼트에 병합 (start_frame 확장)
                    next_seg['start_frame'] = seg['start_frame']
                    next_seg['start_time'] = seg['start_time']
                    next_seg['duration'] = next_seg['end_time'] - next_seg['start_time']
                    changed = True
                    # 병합 로그
                    if iteration == 1:  # 첫 번째 반복에서만 로그 출력
                        self.status.emit(f"[노이즈 병합] '{curr_text}' ({seg['start_frame']}-{seg['end_frame']}, {seg_frames}프레임) → 다음 '{next_text}'로 병합")
                else:
                    # 병합 불가 - 그대로 유지 (실제 짧은 컷)
                    merged.append(seg)
                    # 디버그: 1-2프레임인데 병합 안 되는 경우 로그
                    if seg_frames <= 2 and iteration == 1:
                        self.status.emit(f"[병합 실패] '{curr_text}' ({seg['start_frame']}-{seg['end_frame']}, {seg_frames}프레임) - 이전:'{prev_text}', 다음:'{next_text}'")

                i += 1

            segments = merged

        return segments

    def _extract_scene_number_from_text(self, text):
        """
        원본 텍스트에서 Scene 번호를 추출합니다.
        예: "Scene1-Panel A" → "1", "Scene 2-Panel B" → "2", "SCENE001-PANELA" → "001"
        """
        if not text:
            return None
        
        import re
        
        # 패턴 1: "Scene" 또는 "SCENE" 다음의 숫자 추출 (대소문자 무시)
        # "Scene1", "Scene 1", "SCENE001", "Scene1-Panel" 등
        scene_match = re.search(r'(?i)scene\s*(\d+)', text)
        if scene_match:
            return scene_match.group(1)
        
        # 패턴 2: 이미 정규화된 형식 "SCENE001-PANELA"에서 추출
        scene_match = re.search(r'SCENE(\d+)', text.upper())
        if scene_match:
            return scene_match.group(1)
        
        # 패턴 3: "SEENE" 같은 OCR 오류 처리
        scene_match = re.search(r'(?i)[se]e?ne\s*(\d+)', text)
        if scene_match:
            return scene_match.group(1)
        
        return None

    def _merge_same_scene_segments(self, segments):
        """
        All 모드에서 이전/다음 비교해서 같으면 중간 병합
        
        규칙:
        1. 이전, 다음 비교해서 같으면 중간은 병합
           예: MS101_A001, MS101_LA001, MT101_A001, MS101_A001 
           → 처음과 끝이 MS101_A001이니까 MS101_A001로 병합
        2. 이름이 완전히 다른 건 병합하지 않음
           예: MS101_A001, MS101_A002 → 병합 안 함
        
        Args:
            segments: 세그먼트 리스트
            
        Returns:
            병합된 세그먼트 리스트
        """
        if not segments or len(segments) <= 1 or self.ocr_mode != 'all' or not self.pattern:
            return segments
        
        merged = []
        i = 0
        
        while i < len(segments):
            current_seg = segments[i]
            current_text = current_seg.get('text', '')
            current_norm = self._normalize_all_for_comparison(current_text, self.pattern)
            
            if not current_norm:
                # 정규화 실패 시 그대로 추가
                merged.append(current_seg)
                i += 1
                continue
            
            # 같은 정규화된 텍스트를 가진 연속된 세그먼트들을 찾아서 병합
            group = [current_seg]
            j = i + 1
            
            while j < len(segments):
                next_seg = segments[j]
                next_text = next_seg.get('text', '')
                next_norm = self._normalize_all_for_comparison(next_text, self.pattern)
                
                
                # 정규화된 텍스트가 같으면 그룹에 추가
                if next_norm and next_norm == current_norm:
                    group.append(next_seg)
                    j += 1
                else:
                    # 다를 때: Bridge 병합 체크 (이전과 다음이 같으면 중간 병합)
                    if j + 1 < len(segments):
                        next_next_seg = segments[j + 1]
                        next_next_text = next_next_seg.get('text', '')
                        next_next_norm = self._normalize_all_for_comparison(next_next_text, self.pattern)
                        
                        # 이전(현재)과 그 다음이 같으면 중간도 병합
                        if next_next_norm and next_next_norm == current_norm:
                            group.append(next_seg)
                            group.append(next_next_seg)
                            j += 2
                            self.status.emit(f"[병합] 이전/다음 일치로 중간 병합: '{next_text}' → '{current_text}'")
                            continue
                    
                    # Bridge 병합 불가능하면 종료
                    break
            
            # 그룹이 2개 이상이면 병합
            if len(group) > 1:
                merged_seg = group[0].copy()
                merged_seg['end_frame'] = group[-1]['end_frame']
                merged_seg['end_time'] = group[-1]['end_time']
                merged_seg['duration'] = merged_seg['end_time'] - merged_seg['start_time']
                
                # 텍스트는 첫 번째 세그먼트의 정규화된 텍스트 사용
                merged_seg['text'] = current_norm
                
                # detections 병합
                all_detections = []
                for seg in group:
                    if seg.get('detections'):
                        all_detections.extend(seg['detections'])
                if all_detections:
                    merged_seg['detections'] = all_detections
                
                merged.append(merged_seg)
                self.status.emit(f"[병합] {len(group)}개 세그먼트 병합: '{current_text}' → '{current_norm}'")
            else:
                # 그룹이 1개면 그대로 추가
                merged.append(current_seg)
            
            i = j
        
        return merged

    def _is_similar_text(self, text1, text2, threshold=0.85, scene_only=False):
        """
        두 텍스트가 유사한지 판단 (OCR 분석용 - 세그먼트 생성).

        개선사항:
        - Scene 번호는 엄격하게 비교 (정확히 일치해야 함)
        - Panel ID는 유연하게 비교 (1글자 차이 허용)
        - 연속 프레임 변화 패턴 고려 (급격한 변화 vs 점진적 변화)
        - 유효하지 않은 패턴(공백 문자, 특수문자만) 필터링

        King OCR 모드: "Scene [번호] - Panel [ID]" 패턴에서 Scene 번호와 Panel ID를 모두 비교
        - "Scene 17 - Panel A"와 "Scene 17 - Panel F" → False (Panel ID가 다름)
        - "Scene 17 - Panel A"와 "Scene 17 - Pane! A" → True (Panel ID 같고 OCR 오류)

        일반 모드:
        1. 토큰 순서 정규화: "TJS101_A001"과 "A001_TJS101"은 같은 텍스트
        2. 숫자 부분이 다르면 무조건 다른 샷 (A008 vs A009 = 다름)
        3. 숫자가 같고 문자만 다르면 OCR 오류로 간주 (A008 vs 1A008 = 같음)

        Args:
            text1, text2: 비교할 텍스트
            threshold: 유사도 임계값 (0~1, 기본 0.85 = 85%)
            scene_only: True이면 Scene 번호만 비교 (노이즈 병합용), False이면 전체 텍스트 비교 (세그먼트 생성용)

        Returns:
            bool: 유사하면 True (같은 구간으로 처리)
        """
        if text1 == text2:
            return True

        # Titmouse 모드 전용: "프로젝트코드+쇼넘버_알파벳+씬번호" 패턴 비교
        if self.ocr_mode == 'titmouse':
            norm1 = self._normalize_titmouse_for_comparison(text1)
            norm2 = self._normalize_titmouse_for_comparison(text2)

            # 프로젝트 코드 패턴: 기존 MS|BM|TJS와 새로운 프로젝트 코드 지원 (2-4자 알파벳)
            valid_pattern = r'^(MS|BM|TJS|PEW|ART|RTK|[A-Z]{2,4})\d{2,3}_[A-Z]\d{3}$'
            is_valid1 = bool(norm1 and re.match(valid_pattern, norm1))
            is_valid2 = bool(norm2 and re.match(valid_pattern, norm2))

            if is_valid1 and is_valid2:
                return norm1 == norm2
            
            # Current (text2) is valid, New (text1) is invalid -> Ignore noise (treat as similar)
            if is_valid2:
                return True
        
        # All 모드: 사용자 정의 패턴 기반 비교
        if self.ocr_mode == 'all' and self.pattern:
            norm1 = self._normalize_all_for_comparison(text1, self.pattern)
            norm2 = self._normalize_all_for_comparison(text2, self.pattern)


            if norm1 and norm2:
                if scene_only:
                    # 노이즈 병합 시: 전체 정규화된 텍스트를 비교
                    # 사용자 요구사항: "이름이 완전히 다른 건 병합하지 마. MS101_A001, MS101_A002"
                    # MS109_J000, MS109_J002, MS109_J003은 모두 다른 씬이므로 병합하지 않음
                    result = norm1 == norm2
                    return result
                else:
                    # 세그먼트 생성 시: 전체 텍스트를 완전히 일치해야 함 (Panel ID가 다르면 다른 세그먼트)
                    # MS109_D006과 MS109_D007은 숫자가 다르므로 반드시 다른 세그먼트로 처리
                    result = norm1 == norm2
                    return result

            # 정규화 실패 시 처리
            if scene_only:
                # 노이즈 병합 시: 둘 다 정규화 실패면 같은 노이즈로 간주
                if not norm1 and not norm2:
                    return True
            else:
                # 세그먼트 생성 시: 정규화 실패는 다른 세그먼트로 처리
                # 하나라도 정규화 실패하면 다른 세그먼트로 간주
                if not norm1 or not norm2:
                    return False
            
            # 둘 다 정규화 실패했지만 scene_only=False인 경우는 위에서 처리됨
            return False

        # 빈 문자열이나 <미검출>은 정확히 일치해야 함
        if not text1 or not text2 or text1 == "<미검출>" or text2 == "<미검출>":
            return text1 == text2

        # 유효하지 않은 패턴 필터링 (노이즈 텍스트 거부)
        # 공백, 특수문자, t, $만 있는 텍스트는 거부
        invalid_pattern = r'^[\s\t$]+$'
        if re.match(invalid_pattern, text1) or re.match(invalid_pattern, text2):
            return False
        
        # King/Bento OCR 모드 전용: "Scene [번호] - Panel [ID]" 또는 "Seq XXA_SXX" 패턴 처리
        if self.ocr_mode in ['king', 'bento']:
            # "Seq XXA_SXX" 패턴 처리 (Bento 모드용)
            seq_pattern = r'[Ss][eE][qQ]\s*(\d+)([A-Z]?)[_]\s*[Ss](\d+)'
            seq_match1 = re.search(seq_pattern, text1)
            seq_match2 = re.search(seq_pattern, text2)

            if seq_match1 and seq_match2:
                # Seq 패턴이 둘 다 있으면 비교
                seq_num1 = seq_match1.group(1)  # "01"
                seq_letter1 = seq_match1.group(2) or ""  # "A", "B", "C" 등 또는 ""
                seq_scene1 = seq_match1.group(3)  # "03"

                seq_num2 = seq_match2.group(1)
                seq_letter2 = seq_match2.group(2) or ""
                seq_scene2 = seq_match2.group(3)
                
                # Seq 번호, Letter, Scene 번호가 모두 같으면 같은 세그먼트
                if seq_num1 == seq_num2 and seq_letter1 == seq_letter2 and seq_scene1 == seq_scene2:
                    return True
                
                # 하나라도 다르면 다른 세그먼트
                return False
            
            # 하나만 Seq 패턴이면 다른 세그먼트
            if (seq_match1 and not seq_match2) or (not seq_match1 and seq_match2):
                return False
            # Scene 번호 추출 (여러 패턴 시도)
            # 1순위: "Scene [숫자]" 패턴
            scene_pattern1 = r'[Ss][cC][eE][nN][eE]\s*[.\s]*?(\d+)'
            # 2순위: "cene [숫자]" 패턴 (S가 빠진 경우)
            scene_pattern2 = r'[cC][eE][nN][eE]\s*[.\s]*?(\d+)'
            # 3순위: "$cene [숫자]" 패턴
            scene_pattern3 = r'\$[cC][eE][nN][eE]\s*[.\s]*?(\d+)'
            
            scene_match1 = re.search(scene_pattern1, text1) or re.search(scene_pattern2, text1) or re.search(scene_pattern3, text1)
            scene_match2 = re.search(scene_pattern1, text2) or re.search(scene_pattern2, text2) or re.search(scene_pattern3, text2)
            
            # Scene 패턴 매칭 실패 시 백업: "Scene"/"cene" 다음의 첫 번째 숫자 추출
            if not scene_match1:
                # "Scene"/"cene" 다음의 첫 번째 숫자 찾기
                fallback_match = re.search(r'(?:[Ss]?[cC]?[eE][nN][eE]|Scene|cene)\s*[.\s]*?(\d+)', text1)
                if fallback_match:
                    scene_num1 = str(int(fallback_match.group(1)))  # 앞의 0 제거
                else:
                    # 완전히 실패하면 첫 번째 숫자 사용
                    nums1 = re.findall(r'\d+', text1)
                    scene_num1 = str(int(nums1[0])) if nums1 else None
            else:
                scene_num1 = str(int(scene_match1.group(1)))  # 앞의 0 제거
            
            if not scene_match2:
                # "Scene"/"cene" 다음의 첫 번째 숫자 찾기
                fallback_match = re.search(r'(?:[Ss]?[cC]?[eE][nN][eE]|Scene|cene)\s*[.\s]*?(\d+)', text2)
                if fallback_match:
                    scene_num2 = str(int(fallback_match.group(1)))  # 앞의 0 제거
                else:
                    # 완전히 실패하면 첫 번째 숫자 사용
                    nums2 = re.findall(r'\d+', text2)
                    scene_num2 = str(int(nums2[0])) if nums2 else None
            else:
                scene_num2 = str(int(scene_match2.group(1)))  # 앞의 0 제거
            
            # 둘 다 Scene 번호를 추출했으면
            if scene_num1 and scene_num2:
                # Scene 번호는 엄격하게 비교 (정확히 일치해야 함)
                if scene_num1 != scene_num2:
                    # print(f"[_is_similar_text] Scene 번호 다름: '{text1}' (Scene {scene_num1}) vs '{text2}' (Scene {scene_num2}) → False")
                    return False

                # Scene 번호가 같을 때, Panel ID 비교
                # Panel ID 추출 (Panel/Pane/Pane! 등 허용)
                panel_pattern = r'[Pp][aA][nN][eE][lL!1]*\s*([A-Za-z0-9:]+)'
                panel_match1 = re.search(panel_pattern, text1)
                panel_match2 = re.search(panel_pattern, text2)

                # 2순위: Panel 패턴 없으면 마지막 대문자 알파벳을 Panel ID로 간주
                if not panel_match1:
                    fallback = re.findall(r'\b([A-Z])\b', text1)
                    panel_id1 = fallback[-1] if fallback else None
                else:
                    panel_id1 = panel_match1.group(1).upper().strip()

                if not panel_match2:
                    fallback = re.findall(r'\b([A-Z])\b', text2)
                    panel_id2 = fallback[-1] if fallback else None
                else:
                    panel_id2 = panel_match2.group(1).upper().strip()

                # Panel ID 비교 (유연하게)
                if panel_id1 and panel_id2:
                    # Panel ID가 정확히 같으면 유사 (같은 세그먼트)
                    if panel_id1 == panel_id2:
                        return True

                    # 1글자 Panel ID끼리는 엄격하게 비교 (A vs B = 다른 패널)
                    if len(panel_id1) == 1 and len(panel_id2) == 1:
                        # 숫자/문자 혼동 가능성 고려 (O vs 0, I vs 1 등)
                        # O/0, I/1/l 변환 후 재비교
                        normalized_id1 = panel_id1.replace('0', 'O').replace('l', 'I')
                        normalized_id2 = panel_id2.replace('0', 'O').replace('l', 'I')
                        if normalized_id1 == normalized_id2:
                            return True
                        return False  # 정말 다른 패널

                    # 다글자 Panel ID는 Levenshtein distance로 유사도 체크
                    # (OCR 오류 허용: 예: "AB" vs "A8")
                    max_len = max(len(panel_id1), len(panel_id2))
                    if max_len > 1:
                        # 간단한 편집 거리 계산
                        distance = sum(c1 != c2 for c1, c2 in zip(panel_id1, panel_id2))
                        # 길이 차이도 거리에 추가
                        distance += abs(len(panel_id1) - len(panel_id2))
                        # 1글자 차이까지 허용 (OCR 오류)
                        if distance <= 1:
                            return True
                        return False

                # Panel ID가 하나만 있으면 다른 세그먼트
                # (예: "Scene 5 - Panel" vs "Scene 5 - Panel A" → 다른 세그먼트)
                if (panel_id1 and not panel_id2) or (not panel_id1 and panel_id2):
                    return False

                # Panel ID가 둘 다 없으면 같은 세그먼트
                # (예: "Scene 5 - Panel" vs "Scene 5 - Panel" → 같은 세그먼트)
                return True



        # 일반 모드 또는 Scene-Panel 패턴이 아닌 경우
        # 토큰 순서 정규화 체크: "TJS101_A001" vs "A001_TJS101"
        # "_"와 공백으로 토큰 분리
        tokens1 = re.split(r'[_\s]+', text1)
        tokens2 = re.split(r'[_\s]+', text2)
        
        # 토큰을 역순 정렬하여 비교 (OCR 읽기 순서 무시)
        if len(tokens1) > 1 and len(tokens2) > 1:
            sorted_tokens1 = sorted(tokens1, reverse=True)
            sorted_tokens2 = sorted(tokens2, reverse=True)
            if sorted_tokens1 == sorted_tokens2:
                return True  # "TJS101_A001" == "A001_TJS101"
        
        # 숫자 추출 (마지막 연속된 숫자 그룹)
        nums1 = re.findall(r'\d+', text1)
        nums2 = re.findall(r'\d+', text2)
        
        # 숫자가 있고 마지막 숫자가 다르면 다른 샷
        if nums1 and nums2:
            last_num1 = nums1[-1]
            last_num2 = nums2[-1]
            if last_num1 != last_num2:
                return False  # A008 vs A009 = 다른 샷
        
        # 숫자가 같으면 Levenshtein distance로 유사도 체크 (OCR 오류 허용)
        len1, len2 = len(text1), len(text2)
        if len1 == 0 or len2 == 0:
            return False
        
        # DP 테이블
        dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]
        
        for i in range(len1 + 1):
            dp[i][0] = i
        for j in range(len2 + 1):
            dp[0][j] = j
        
        for i in range(1, len1 + 1):
            for j in range(1, len2 + 1):
                if text1[i-1] == text2[j-1]:
                    dp[i][j] = dp[i-1][j-1]
                else:
                    dp[i][j] = 1 + min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1])
        
        distance = dp[len1][len2]
        max_len = max(len1, len2)
        similarity = 1.0 - (distance / max_len)
        
        return similarity >= threshold

    def run(self):
        cap = None
        ocr_engine = None
        try:
            try:
                from paddleocr import PaddleOCR
            except ImportError as e:
                import sys
                import os
                error_msg = f"PaddleOCR 모듈을 불러올 수 없습니다.\n에러: {str(e)}\n"
                if getattr(sys, 'frozen', False):
                    error_msg += f"sys.path: {sys.path[:5]}\n"
                    _MEIPASS = getattr(sys, '_MEIPASS', 'N/A')
                    error_msg += f"_MEIPASS: {_MEIPASS}\n"
                    apted_path = os.path.join(_MEIPASS, 'apted') if _MEIPASS != 'N/A' else 'N/A'
                    paddleocr_path = os.path.join(_MEIPASS, 'paddleocr') if _MEIPASS != 'N/A' else 'N/A'
                    error_msg += f"apted 존재: {os.path.exists(apted_path) if _MEIPASS != 'N/A' else False}\n"
                    error_msg += f"paddleocr 존재: {os.path.exists(paddleocr_path) if _MEIPASS != 'N/A' else False}\n"
                self.error.emit(error_msg)
                # print(f"[OCRWorker] ImportError details: {e}")
                import traceback
                traceback.print_exc()
                return

            try:
                # GPU 사용 가능 여부 확인
                use_gpu = False
                try:
                    import paddle
                    if paddle.is_compiled_with_cuda():
                        use_gpu = True
                        print("[OCRWorker] CUDA 사용 가능 - GPU 가속 활성화")
                except Exception:
                    print("[OCRWorker] GPU 사용 불가 - CPU 모드로 실행")

                use_ascii_paddleocr_dir()

                # OCR 모드에 따라 PaddleOCR 설정
                if self.ocr_mode == 'king':
                    # King 모드: 더 정확한 인식을 위한 최적화 설정
                    ocr_engine = PaddleOCR(
                        use_angle_cls=True,
                        lang="en",
                        show_log=False,
                        use_gpu=use_gpu,         # GPU 가속 활성화
                        use_mp=True,             # 멀티프로세싱 활성화
                        total_process_num=2,     # 프로세스 수 (CPU 코어에 맞게)
                        det_db_thresh=0.3,       # Detection threshold (낮을수록 더 많이 감지)
                        det_db_box_thresh=0.5,   # Box threshold (낮을수록 더 작은 박스도 인식)
                        rec_batch_num=16,        # Recognition batch size (증가)
                        use_space_char=True,     # 공백 문자 인식 활성화
                    )
                elif self.ocr_mode == 'bento':
                    # Bento 모드: 작은 텍스트 및 특수 패턴 인식 최적화 (예: Seq 02A_S09 - Panel 6)
                    ocr_engine = PaddleOCR(
                        use_angle_cls=True,
                        lang="en",
                        show_log=False,
                        use_gpu=use_gpu,         # GPU 가속 활성화
                        use_mp=True,             # 멀티프로세싱 활성화
                        total_process_num=2,     # 프로세스 수
                        det_db_thresh=0.25,      # Detection threshold (더 낮춰서 작은 텍스트도 감지)
                        det_db_box_thresh=0.4,   # Box threshold (더 낮춰서 작은 박스도 인식)
                        det_db_unclip_ratio=1.8, # Unclip ratio (박스 확장 비율 증가)
                        rec_batch_num=32,        # Recognition batch size (더 큰 배치)
                        use_space_char=True,     # 공백 문자 인식 활성화
                    )
                else:  # 'titmouse' (기본값)
                    # Titmouse 모드: 기본 설정
                    ocr_engine = PaddleOCR(
                        use_angle_cls=False,     # 수평 텍스트이므로 각도 분류 비활성화 (오인식 방지)
                        lang="en",
                        show_log=False,
                        use_gpu=use_gpu,         # GPU 가속 활성화
                        use_mp=True,             # 멀티프로세싱 활성화
                        total_process_num=2,     # 프로세스 수
                        rec_batch_num=16,        # Recognition batch size
                        rec_image_shape="3, 64, 320", # 인식 해상도 높임 (기본 3, 48, 320 -> 3, 64, 320) - 5/6 구분 개선
                        use_space_char=True,     # 공백 문자 인식 활성화 (중요)
                    )
                # paddle 3.0.0 입력 크기 변화 버그 회피 (_ClearBeforeInput 참고)
                guard_paddle_buffer_growth(ocr_engine)
            except Exception as exc:
                self.error.emit(f"PaddleOCR 초기화 실패: {exc}")
                return

            if not Path(self.video_path).exists():
                self.error.emit("동영상 파일을 찾을 수 없습니다.")
                return

            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                self.error.emit("동영상을 열 수 없습니다.")
                return

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            if fps <= 0.0:
                fps = 24.0

            roi_x, roi_y, roi_w, roi_h = self.roi_normalized
            segments = []
            current_text = None
            segment_start_frame = 0
            current_segment_roi = None
            current_boxes = None
            prev_small_roi = None
            last_processed_frame = -1
            last_ocr_frame = -1  # 마지막 OCR 실행 프레임 (강제 OCR 실행용)
            scan_weight = 70
            last_roi_preview = None
            last_detections = None

            # 트래킹 관련 변수
            tracker = None
            tracker_initialized = False
            tracking_failed_count = 0
            max_tracking_failures = 10  # 연속 실패 허용 횟수
            # 트래킹 업데이트 간격: frame_step이 1이면 2프레임마다, 그 외에는 frame_step과 동일
            # 이렇게 하면 속도 향상과 정확도 유지의 균형을 맞춤
            tracking_update_interval = max(2, self.frame_step) if self.frame_step == 1 else self.frame_step
            last_tracking_frame = -1  # 마지막 트래킹 업데이트 프레임

            if self.tracking_enabled:
                self.status.emit("ROI 트래킹 초기화 중…")
                print("[OCRWorker] ROI 트래킹 초기화 중…")
            else:
                self.status.emit("PaddleOCR 분석을 시작합니다…")
                print("[OCRWorker] PaddleOCR 분석을 시작합니다…")
            
            # 분석 설정 정보 로그
            config_msg = f"분석 설정: 모드={self.ocr_mode}, 프레임 스텝={self.frame_step}, 차이 임계값={self.diff_threshold}"
            self.status.emit(config_msg)
            # print(f"[OCRWorker] {config_msg}")

            # 시작/종료 프레임 설정
            if self.start_frame is not None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, self.start_frame)
            
            frame_index = 0
            while self._is_running:
                # 종료 프레임이 지정된 경우, 읽기 전에 현재 위치 확인
                if self.end_frame is not None:
                    # cap.read() 전에 현재 위치 확인
                    current_pos_before_read = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                    # 0-based로 변환
                    zero_index_before_read = current_pos_before_read - 1
                    # end_frame을 넘어서면 읽지 않고 중단
                    if zero_index_before_read > self.end_frame:
                        break
                
                ret, frame = cap.read()
                if not ret:
                    break
                
                # 현재 프레임 위치 확인
                current_frame_pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                
                frame_index += 1
                zero_index = current_frame_pos if self.start_frame is not None else frame_index - 1
                
                # 종료 프레임이 지정되었고 현재 프레임이 종료 프레임을 넘었으면 중단
                # zero_index를 사용하여 정확하게 체크 (이중 체크)
                if self.end_frame is not None and zero_index > self.end_frame:
                    break

                if frame_index % self.frame_step != 0:
                    continue

                height, width = frame.shape[:2]
                
                # 트래킹이 활성화된 경우
                if self.tracking_enabled:
                    if not tracker_initialized:
                        # 첫 프레임에서 tracker 초기화
                        try:
                            # TrackerKCF 사용 (CSRT보다 빠르고 정확도도 좋음)
                            # TrackerCSRT는 정확하지만 느림, TrackerKCF는 빠르고 정확도도 괜찮음
                            tracker = cv2.TrackerKCF_create()
                            x1 = max(0, min(width - 1, int(roi_x * width)))
                            y1 = max(0, min(height - 1, int(roi_y * height)))
                            x2 = max(0, min(width, int((roi_x + roi_w) * width)))
                            y2 = max(0, min(height, int((roi_y + roi_h) * height)))
                            
                            if x2 > x1 and y2 > y1:
                                bbox = (x1, y1, x2 - x1, y2 - y1)
                                tracker.init(frame, bbox)
                                tracker_initialized = True
                                last_tracking_frame = zero_index
                                log_msg = f"ROI 트래킹 시작 - PaddleOCR 분석 중… (초기 ROI: {x1},{y1} → {x2},{y2})"
                                self.status.emit(log_msg)
                                # print(f"[OCRWorker] {log_msg}")
                            else:
                                self.error.emit("ROI 영역이 유효하지 않습니다.")
                                return
                        except Exception as e:
                            self.error.emit(f"트래킹 초기화 실패: {e}")
                            return
                    else:
                        # 트래킹 업데이트 간격 조정 (모든 프레임마다 업데이트하지 않음)
                        should_update_tracking = (zero_index - last_tracking_frame) >= tracking_update_interval
                        
                        if should_update_tracking:
                            # tracker 업데이트
                            try:
                                success, bbox = tracker.update(frame)
                                if success:
                                    tracking_failed_count = 0
                                    x1, y1, w, h = [int(v) for v in bbox]
                                    x2 = x1 + w
                                    y2 = y1 + h
                                    # 경계 체크
                                    x1 = max(0, min(width - 1, x1))
                                    y1 = max(0, min(height - 1, y1))
                                    x2 = max(0, min(width, x2))
                                    y2 = max(0, min(height, y2))
                                    
                                    # 정규화된 좌표 업데이트
                                    roi_x = x1 / width
                                    roi_y = y1 / height
                                    roi_w = (x2 - x1) / width
                                    roi_h = (y2 - y1) / height
                                    last_tracking_frame = zero_index
                                else:
                                    # 추적 실패 시 이전 위치 유지
                                    tracking_failed_count += 1
                                    if tracking_failed_count >= max_tracking_failures:
                                        log_msg = f"트래킹 실패 - 마지막 성공 위치 사용 중… (프레임 {zero_index}, 실패 횟수: {tracking_failed_count})"
                                        self.status.emit(log_msg)
                                        # print(f"[OCRWorker] {log_msg}")
                                    # 이전 ROI 좌표 그대로 사용
                                    x1 = max(0, min(width - 1, int(roi_x * width)))
                                    y1 = max(0, min(height - 1, int(roi_y * height)))
                                    x2 = max(0, min(width, int((roi_x + roi_w) * width)))
                                    y2 = max(0, min(height, int((roi_y + roi_h) * height)))
                            except Exception as e:
                                # 예외 발생 시 이전 위치 사용
                                tracking_failed_count += 1
                                x1 = max(0, min(width - 1, int(roi_x * width)))
                                y1 = max(0, min(height - 1, int(roi_y * height)))
                                x2 = max(0, min(width, int((roi_x + roi_w) * width)))
                                y2 = max(0, min(height, int((roi_y + roi_h) * height)))
                        else:
                            # 트래킹 업데이트 간격이 안 되었으면 이전 위치 사용
                            x1 = max(0, min(width - 1, int(roi_x * width)))
                            y1 = max(0, min(height - 1, int(roi_y * height)))
                            x2 = max(0, min(width, int((roi_x + roi_w) * width)))
                            y2 = max(0, min(height, int((roi_y + roi_h) * height)))
                else:
                    # 트래킹 비활성화 시 기존 로직 사용
                    x1 = max(0, min(width - 1, int(roi_x * width)))
                    y1 = max(0, min(height - 1, int(roi_y * height)))
                    x2 = max(0, min(width, int((roi_x + roi_w) * width)))
                    y2 = max(0, min(height, int((roi_y + roi_h) * height)))

                if x2 <= x1 or y2 <= y1:
                    continue

                roi_frame = frame[y1:y2, x1:x2]
                roi_height, roi_width = roi_frame.shape[:2]
                # 차이 계산용: 작은 크기로 리사이즈 (128x128 → 64x64, 4배 빠름)
                # 히스토그램 평활화 생략 (원본 그레이스케일로 비교)
                roi_gray = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2GRAY)
                resized_roi = cv2.resize(roi_gray, (64, 64), interpolation=cv2.INTER_AREA)

                diff_value = self.diff_threshold + 1.0
                if prev_small_roi is not None:
                    diff_value = float(np.mean(cv2.absdiff(resized_roi, prev_small_roi)))

                prev_small_roi = resized_roi
                last_processed_frame = zero_index

                # King/Bento/Titmouse/All 모드: Scene/Seq/Shot 번호가 바뀌는지 확인하기 위해 주기적으로 OCR 실행
                force_ocr = False
                if self.ocr_mode in ['king', 'bento', 'titmouse', 'all'] and current_text is not None:
                    # 마지막 OCR 실행 후 일정 프레임 경과 시 강제 실행 (Scene/Seq/Shot 번호 변경 감지)
                    frames_since_last_ocr = zero_index - last_ocr_frame if last_ocr_frame >= 0 else 0

                    # 동적 강제 OCR 주기 계산 (프레임 레이트 기반)
                    # 24fps 기준: King 30프레임(1.25초), Bento 18프레임(0.75초), Titmouse 15프레임(0.625초), All 15프레임(0.625초)
                    # 60fps 기준: King 75프레임(1.25초), Bento 45프레임(0.75초), Titmouse 37프레임(0.625초), All 37프레임(0.625초)
                    if self.ocr_mode == 'titmouse':
                        # Titmouse: 더 자주 강제 OCR → 경계 섞임 완화 (기존 0.625s→0.45s)
                        base_interval_seconds = 0.45
                    elif self.ocr_mode == 'bento':
                        base_interval_seconds = 0.75  # Bento: 0.75초마다 강제 OCR (이전 0.625초)
                    elif self.ocr_mode == 'all':
                        # All: Titmouse와 동일하게 자주 강제 OCR
                        base_interval_seconds = 0.45
                    else:
                        base_interval_seconds = 1.25  # King: 1.25초마다 강제 OCR

                    force_ocr_interval = int(fps * base_interval_seconds)
                    # 최소값 보장 (저프레임레이트 비디오 대비)
                    if self.ocr_mode == 'titmouse':
                        # 더 촘촘하게: 최소 10프레임마다 강제 OCR
                        force_ocr_interval = max(force_ocr_interval, 10)
                    elif self.ocr_mode == 'bento':
                        force_ocr_interval = max(force_ocr_interval, 18)  # 15 → 18 프레임
                    elif self.ocr_mode == 'all':
                        # All: Titmouse와 동일하게 최소 10프레임
                        force_ocr_interval = max(force_ocr_interval, 10)
                    else:
                        force_ocr_interval = max(force_ocr_interval, 30)

                    if frames_since_last_ocr >= force_ocr_interval:
                        force_ocr = True

                # Bento/Titmouse/All 모드: diff_value threshold를 낮춰서 더 자주 OCR 실행
                effective_threshold = self.diff_threshold
                if self.ocr_mode == 'bento':
                    # Bento 모드는 threshold를 30% 낮춰서 더 민감하게 반응
                    effective_threshold = self.diff_threshold * 0.7
                elif self.ocr_mode == 'titmouse':
                    # Titmouse 모드는 threshold를 55% 낮춰서 더 민감하게 반응 (씬 누락 방지)
                    effective_threshold = self.diff_threshold * 0.45
                elif self.ocr_mode == 'all':
                    # All 모드는 threshold를 55% 낮춰서 더 민감하게 반응 (Titmouse와 동일)
                    effective_threshold = self.diff_threshold * 0.45
                
                if diff_value < effective_threshold and current_text is not None and not force_ocr:
                    if self.ocr_mode in ['king', 'bento', 'titmouse', 'all']:
                        threshold_display = effective_threshold if self.ocr_mode in ['bento', 'titmouse', 'all'] else self.diff_threshold
                        log_msg = f"[Frame {zero_index}] diff_value={diff_value:.2f} < threshold={threshold_display:.2f} → OCR 스킵"
                        # print(log_msg)
                        # self.status.emit(log_msg)
                    progress = int(min(scan_weight, (frame_index / max(total_frames, 1)) * scan_weight))
                    self.progress.emit(progress)
                    continue

                # OCR 실행
                if self.ocr_mode in ['king', 'bento', 'titmouse', 'all']:
                    if force_ocr:
                        mode_name = 'Scene' if self.ocr_mode == 'king' else ('Seq' if self.ocr_mode == 'bento' else ('Shot' if self.ocr_mode == 'titmouse' else 'Pattern'))
                        log_msg = f"[Frame {zero_index}] 강제 OCR 실행 ({force_ocr_interval}프레임/{base_interval_seconds:.2f}초 경과, {mode_name} 번호 변경 감지)"
                        print(log_msg)
                        self.status.emit(log_msg)
                    else:
                        threshold_display = effective_threshold if self.ocr_mode in ['bento', 'titmouse', 'all'] else self.diff_threshold
                        log_msg = f"[Frame {zero_index}] diff_value={diff_value:.2f} ≥ threshold={threshold_display:.2f} → OCR 실행"
                        print(log_msg)
                        self.status.emit(log_msg)
                
                # 마지막 OCR 실행 프레임 업데이트
                last_ocr_frame = zero_index

                # ROI 크기에 따른 적응형 업스케일 계산
                # 작은 ROI(< 200px)는 더 크게, 큰 ROI(> 800px)는 덜 크게
                roi_area = roi_width * roi_height
                if roi_area < 40000:  # 200x200 미만
                    base_scale_king = 6.0
                    base_scale_bento = 4.0
                    base_scale_titmouse = 3.0
                elif roi_area < 160000:  # 400x400 미만
                    base_scale_king = 5.0
                    base_scale_bento = 3.0
                    base_scale_titmouse = 2.5
                elif roi_area < 640000:  # 800x800 미만
                    base_scale_king = 4.0
                    base_scale_bento = 2.5
                    base_scale_titmouse = 2.0
                else:  # 800x800 이상
                    base_scale_king = 3.0
                    base_scale_bento = 2.0
                    base_scale_titmouse = 1.5

                # OCR용 이미지 전처리
                if self.ocr_mode == 'king':
                    # King 모드: 빨간색 텍스트 인식 개선을 위한 전처리 (적응형 업스케일)
                    upscaled_roi = self._preprocess_for_red_text(roi_frame, scale_factor=base_scale_king)
                    upscale_factor = base_scale_king
                elif self.ocr_mode == 'bento':
                    # Bento 모드: 작은 텍스트 인식 개선을 위한 전처리 (적응형 업스케일)
                    upscaled_roi = cv2.resize(roi_frame, None, fx=base_scale_bento, fy=base_scale_bento, interpolation=cv2.INTER_CUBIC)
                    upscale_factor = base_scale_bento
                else:
                    # Titmouse 모드: 기본 전처리 (적응형 업스케일)
                    upscaled_roi = cv2.resize(roi_frame, None, fx=base_scale_titmouse, fy=base_scale_titmouse, interpolation=cv2.INTER_CUBIC)
                    upscale_factor = base_scale_titmouse
                
                # OCR 실행 전 로그
                if self.ocr_mode in ['king', 'bento']:
                    self.status.emit(f"[Frame {zero_index}] OCR 실행 중... (업스케일: {upscale_factor}x, ROI 크기: {roi_width}x{roi_height})")
                
                ocr_result = ocr_engine.ocr(upscaled_roi, cls=True)
                
                # OCR 결과 요약 로그
                if ocr_result and isinstance(ocr_result, (list, tuple)) and len(ocr_result) > 0:
                    first_page = ocr_result[0]
                    if first_page is not None and isinstance(first_page, (list, tuple)):
                        detected_count = len([line for line in first_page if line is not None])
                        if self.ocr_mode in ['king', 'bento'] and detected_count > 0:
                            self.status.emit(f"[Frame {zero_index}] OCR 감지: {detected_count}개 텍스트 박스 발견")

                # upscaled_roi의 크기 (OCR 결과 box 좌표는 이 크기 기준)
                upscaled_height, upscaled_width = upscaled_roi.shape[:2]
                
                # 원본 roi_frame 크기 (병합 함수에서 사용하므로 미리 정의)
                original_roi_width = roi_width
                original_roi_height = roi_height

                extracted_tokens = []
                detections = []
                # PaddleOCR returns [page_results], so iterate over first page
                # None 값과 빈 리스트 체크를 더 안전하게 처리
                ocr_lines = []
                if ocr_result and isinstance(ocr_result, (list, tuple)) and len(ocr_result) > 0:
                    first_page = ocr_result[0]
                    if first_page is not None and isinstance(first_page, (list, tuple)):
                        ocr_lines = [line for line in first_page if line is not None]
                
                # OCR 신뢰도 임계값 설정 (모드별)
                # King/Bento 모드는 더 엄격하게 (0.6), Titmouse는 기본값 (0.5)
                confidence_threshold = 0.6 if self.ocr_mode in ['king', 'bento'] else 0.5

                for line in ocr_lines:
                    if not line or not isinstance(line, (list, tuple)) or len(line) < 2:
                        continue
                    metadata = line[1]
                    if not metadata or not isinstance(metadata, (list, tuple)) or len(metadata) == 0:
                        continue
                    # None 값 체크 및 문자열 변환
                    if metadata[0] is None:
                        continue
                    try:
                        candidate = str(metadata[0]).strip()
                    except (TypeError, ValueError):
                        continue

                    # 신뢰도 체크
                    score_value = None
                    if len(metadata) > 1 and isinstance(metadata[1], (int, float)):
                        score_value = float(metadata[1])

                    # 신뢰도가 임계값 미만이면 필터링
                    if score_value is not None and score_value < confidence_threshold:
                        # if self.ocr_mode in ['king', 'bento']:
                            # print(f"[Frame {zero_index}] 낮은 신뢰도 필터링: '{candidate}' (score={score_value:.2f} < {confidence_threshold})")
                        continue

                    if candidate:
                        extracted_tokens.append(candidate)
                        box = line[0] if isinstance(line[0], list) else None
                        normalized_box = None
                        # box 좌표는 upscaled_roi 기준이므로 원본 roi_frame 크기로 정규화해야 함
                        # upscaled_roi는 roi_frame을 upscale_factor배로 확대한 것이므로, 원본 크기로 변환
                        if box and len(box) == 4 and upscaled_width > 0 and upscaled_height > 0:
                            
                            # upscaled 좌표를 원본 크기로 변환 후 정규화
                            normalized_box = [
                                [
                                    round((pt[0] / upscale_factor) / original_roi_width, 4) if original_roi_width > 0 else 0.0,
                                    round((pt[1] / upscale_factor) / original_roi_height, 4) if original_roi_height > 0 else 0.0
                                ]
                                for pt in box
                                if isinstance(pt, (list, tuple)) and len(pt) == 2
                            ]
                        detections.append(
                            {
                                "text": candidate,
                                "score": score_value,
                                "box": normalized_box,
                            }
                        )

                # 토큰 순서 정규화: OCR 읽기 순서가 달라도 일관된 결과 생성
                # 예: ["TJS101", "A007"] 또는 ["A007", "TJS101"] → 항상 ["TJS101", "A007"]로 정렬
                # 일반적으로 프로젝트/씬 코드(TJS101)가 샷 번호(A007)보다 앞에 옴
                # None 값을 필터링하고 문자열로 변환
                extracted_tokens = [
                    str(det.get("text", "")).strip() 
                    for det in detections 
                    if det.get("text") is not None and str(det.get("text", "")).strip()
                ]
                if len(extracted_tokens) == 2:
                    # 역순 정렬: 숫자가 크거나 길이가 긴 토큰이 앞으로 (프로젝트 코드 우선)
                    extracted_tokens = sorted(extracted_tokens, reverse=True)
                
                # 토큰 병합: 패턴에 따라 "_" 복원
                if len(extracted_tokens) >= 2:
                    # "TJS101" + "A007" 같은 패턴 감지 (영숫자 + 영숫자)
                    merged_tokens = []
                    i = 0
                    while i < len(extracted_tokens):
                        current = extracted_tokens[i]
                        # None 체크 및 문자열 변환
                        if current is None:
                            i += 1
                            continue
                        current = str(current).strip()
                        if not current:
                            i += 1
                            continue
                        # 다음 토큰이 있고, 둘 다 영숫자로만 구성된 경우
                        if i + 1 < len(extracted_tokens):
                            next_token = extracted_tokens[i + 1]
                            # None 체크 및 문자열 변환
                            if next_token is not None:
                                next_token = str(next_token).strip()
                                if next_token and current.replace('_', '').isalnum() and next_token.replace('_', '').isalnum():
                                    # "_"로 연결 (언더스코어 복원)
                                    merged_tokens.append(f"{current}_{next_token}")
                                    i += 2
                                    continue
                        merged_tokens.append(current)
                        i += 1
                    # None 값 필터링 후 join
                    merged_tokens = [str(t).strip() for t in merged_tokens if t is not None and str(t).strip()]
                    text = " ".join(merged_tokens) if merged_tokens else ""
                else:
                    # None 값 필터링 후 join
                    extracted_tokens = [str(t).strip() for t in extracted_tokens if t is not None and str(t).strip()]
                    text = " ".join(extracted_tokens) if extracted_tokens else ""
                
                # text가 None이 아니고 문자열인지 확인 후 처리
                if text and isinstance(text, str):
                    text = " ".join(text.strip().split())
                else:
                    text = ""
                if not text:
                    text = "<미검출>"
                
                # 썸네일용으로 원본 detections 백업 (실제 텍스트 박스 위치)
                detections_for_thumbnail = copy.deepcopy(detections) if detections else []

                # 모드별 패턴 보정 적용
                if detections:
                    original_text = text

                    if self.ocr_mode == 'king':
                        # King 모드: "Scene [숫자] - Panel [문자]" 형식 보정
                        text = self._correct_scene_panel_pattern(text)
                    elif self.ocr_mode == 'bento':
                        # Bento 모드: "Seq XXA_SXX" 또는 "Seq XXA_SXX - Panel X" 형식 보정
                        text = self._correct_seq_pattern(text)
                    elif self.ocr_mode == 'titmouse':
                        # Titmouse 모드: "프로젝트-쇼넘버_알파벳-씬번호" 형식 보정
                        text = self._correct_titmouse_pattern(text)
                    elif self.ocr_mode == 'all' and self.pattern:
                        # All 모드: 사용자 정의 패턴으로 텍스트 정규화
                        text = self._correct_all_pattern(text, self.pattern)

                    if original_text != text:
                        log_msg = f"[Frame {zero_index}] 패턴 보정: '{original_text}' → '{text}'"
                        print(log_msg)
                        self.status.emit(log_msg)
                    else:
                        if self.ocr_mode in ['king', 'bento', 'titmouse', 'all']:
                            # 강제 OCR인 경우 더 상세한 로그 표시
                            if force_ocr:
                                log_msg = f"[Frame {zero_index}] 강제 OCR 결과(원본): '{original_text}' → 보정: '{text}'"
                            else:
                                log_msg = f"[Frame {zero_index}] OCR 결과: '{text}'"
                            print(log_msg)
                            self.status.emit(log_msg)

                    # King/Bento/Titmouse/All 모드에서는 detection 박스를 전체 ROI로 변경 (텍스트 처리 후)
                    if self.ocr_mode in ['king', 'bento', 'titmouse', 'all']:
                        # 평균 score 계산
                        all_scores = [det.get("score") for det in detections if det.get("score") is not None]
                        avg_score = sum(all_scores) / len(all_scores) if all_scores else None

                        # 전체 ROI 영역을 하나의 detection 박스로 설정 (normalized 좌표: 0,0 ~ 1,1)
                        full_roi_box = [
                            [0.0, 0.0],  # 좌상단
                            [1.0, 0.0],  # 우상단
                            [1.0, 1.0],  # 우하단
                            [0.0, 1.0],  # 좌하단
                        ]

                        # 하나의 detection으로 통합 (패턴 보정된 text 사용)
                        detections = [{
                            "text": text,
                            "score": avg_score,
                            "box": full_roi_box,
                        }]

                # 썸네일 생성: 실제 감지된 텍스트 박스 영역만 크롭
                roi_preview_bytes = self._encode_roi_image(roi_frame, detections_for_thumbnail)
                if roi_preview_bytes is not None:
                    last_roi_preview = roi_preview_bytes

                detections = detections or []
                if detections:
                    last_detections = copy.deepcopy(detections)


                if current_text is None:
                    current_text = text
                    segment_start_frame = zero_index
                    current_segment_roi = roi_preview_bytes
                    current_boxes = copy.deepcopy(detections)
                    log_msg = f"[Frame {zero_index}] 첫 세그먼트 시작: '{text}'"
                    print(log_msg)
                    self.status.emit(log_msg)
                else:
                    is_similar = self._is_similar_text(text, current_text)
                    
                    if not is_similar:
                        # 텍스트가 달라졌음 - 새 세그먼트 생성
                        end_frame = max(segment_start_frame, zero_index - 1)
                        if end_frame >= segment_start_frame:
                            log_msg = f"[Frame {zero_index}] 새 세그먼트 감지: '{current_text}' ({segment_start_frame}-{end_frame}) → '{text}'"
                            print(log_msg)
                            self.status.emit(log_msg)
                            segments.append(
                                self._build_segment(
                                    current_text,
                                    segment_start_frame,
                                    end_frame,
                                    fps,
                                    current_segment_roi,
                                    copy.deepcopy(current_boxes) if current_boxes else [],
                                )
                            )
                        current_text = text
                        segment_start_frame = zero_index
                        current_segment_roi = roi_preview_bytes
                        current_boxes = copy.deepcopy(detections)
                    elif current_segment_roi is None:
                        # 텍스트가 유사함 - 같은 세그먼트로 처리
                        if self.ocr_mode in ['king', 'bento', 'titmouse']:
                            log_msg = f"[Frame {zero_index}] 유사 텍스트 스킵 (ROI 없음): '{text}' ≈ '{current_text}'"
                            print(log_msg)
                            self.status.emit(log_msg)
                        current_segment_roi = roi_preview_bytes
                        if detections:
                            current_boxes = copy.deepcopy(detections)
                    elif not current_boxes and detections:
                        # 텍스트가 유사하지만 boxes정보가 없었던 경우 업데이트
                        if self.ocr_mode in ['king', 'bento', 'titmouse']:
                            log_msg = f"[Frame {zero_index}] 유사 텍스트 (박스 정보 추가): '{text}'"
                            print(log_msg)
                            self.status.emit(log_msg)
                        current_boxes = copy.deepcopy(detections)



                progress = int(min(scan_weight, (frame_index / max(total_frames, 1)) * scan_weight))
                self.progress.emit(progress)
                # 진행률 로그 (10% 단위로만 표시하여 로그 과다 방지)
                if progress % 10 == 0 or progress == scan_weight:
                    self.status.emit(f"진행률: {progress}% (프레임 {zero_index}/{total_frames})")

            if cap is not None:
                cap.release()

            if not self._is_running:
                self.status.emit("OCR 분석이 취소되었습니다.")
                self.progress.emit(100)
                self.completed.emit(
                    {
                        "segments": [],
                        "fps": fps,
                        "total_frames": total_frames,
                        "cancelled": True,
                    }
                )
                return

            # 마지막 세그먼트 처리
            # 선택 구간이 지정된 경우 end_frame으로 제한, 아니면 전체 비디오의 마지막 프레임
            if self.end_frame is not None:
                final_frame = self.end_frame
            else:
                final_frame = total_frames - 1
            
            # (frame_step이나 OCR 스킵으로 인한 1프레임 오차 방지)
            if current_segment_roi is None:
                current_segment_roi = last_roi_preview
            if current_boxes is None:
                current_boxes = copy.deepcopy(last_detections) if last_detections else []
            if current_text is not None and final_frame >= segment_start_frame:
                segments.append(
                    self._build_segment(
                        current_text,
                        segment_start_frame,
                        final_frame,
                        fps,
                        current_segment_roi,
                        copy.deepcopy(current_boxes) if current_boxes else [],
                    )
                )

            if not segments:
                log_msg = "변경된 텍스트를 찾지 못했습니다."
                self.status.emit(log_msg)
                # print(f"[OCRWorker] {log_msg}")
                self.progress.emit(100)
                self.completed.emit(
                    {
                        "segments": [],
                        "fps": fps,
                        "total_frames": total_frames,
                        "cancelled": self._was_cancelled,
                    }
                )
                return

            # 후처리: 짧은 노이즈 세그먼트 병합 (1-3프레임)
            original_count = len(segments)
            self.status.emit(f"[후처리] 노이즈 세그먼트 병합 시작 (총 {original_count}개 세그먼트)")
            segments = self._merge_noise_segments(segments, min_frames=4)
            merged_count = original_count - len(segments)
            if merged_count > 0:
                self.status.emit(f"[후처리 완료] {merged_count}개 노이즈 세그먼트 병합됨")
            
            # All 모드: 같은 Scene 번호를 가진 연속된 세그먼트 병합
            if self.ocr_mode == 'all' and self.pattern:
                before_scene_merge = len(segments)
                segments = self._merge_same_scene_segments(segments)
                scene_merged_count = before_scene_merge - len(segments)
                if scene_merged_count > 0:
                    self.status.emit(f"[후처리 완료] {scene_merged_count}개 Scene 세그먼트 병합됨 (최종 {len(segments)}개 세그먼트)")
                else:
                    self.status.emit(f"[후처리 완료] 최종 {len(segments)}개 세그먼트")
            else:
                if merged_count == 0:
                    self.status.emit(f"[후처리 완료] 병합된 노이즈 세그먼트 없음")
                else:
                    self.status.emit(f"[후처리 완료] 최종 {len(segments)}개 세그먼트")

            self.progress.emit(100)
            log_msg = f"PaddleOCR 분석이 완료되었습니다. (총 {len(segments)}개 세그먼트 감지)"
            self.status.emit(log_msg)
            # print(f"[OCRWorker] {log_msg}")
            self.completed.emit(
                {
                    "segments": segments,
                    "fps": fps,
                    "total_frames": total_frames,
                    "cancelled": self._was_cancelled,
                }
            )
        except Exception as e:
            # 모든 예외를 안전하게 처리하여 크래시 방지
            import traceback
            error_msg = f"OCR 분석 중 오류 발생: {str(e)}"
            # print(f"[OCRWorker] 예외 발생: {error_msg}")
            # print(f"[OCRWorker] 트레이스백:\n{traceback.format_exc()}")
            try:
                self.error.emit(error_msg)
            except:
                pass  # 시그널 전송 실패 시 무시
            finally:
                # 리소스 정리
                if cap is not None:
                    try:
                        cap.release()
                    except:
                        pass
                # 완료 시그널 전송 (빈 결과)
                try:
                    self.progress.emit(100)
                    self.completed.emit(
                        {
                            "segments": [],
                            "fps": 0.0,
                            "total_frames": 0,
                            "cancelled": True,
                        }
                    )
                except:
                    pass

    def _build_segment(self, text, start_frame, end_frame, fps, roi_image=None, boxes=None):
        start_time = start_frame / fps if fps else 0.0
        end_time = (end_frame + 1) / fps if fps else 0.0
        # duration: end_frame까지만 포함 (다음 프레임 미포함)
        num_frames = end_frame - start_frame + 1
        duration = num_frames / fps if fps else 0.0
        return {
            "text": text,
            "edited_text": text,  # 초기값은 text와 동일
            "start_frame": start_frame,
            "end_frame": end_frame,
            "start_time": start_time,
            "end_time": end_time,
            "duration": duration,
            "roi_image": roi_image,
            "detections": boxes,
        }

    def _encode_roi_image(self, roi_frame, detections=None):
        """
        ROI 프레임을 인코딩하여 썸네일 생성.
        detections가 제공되면 실제 감지된 텍스트 박스 영역만 크롭하여 반환.
        """
        if roi_frame is None or roi_frame.size == 0:
            return None

        try:
            # detections가 있으면 텍스트 박스 영역만 추출
            if detections:
                roi_height, roi_width = roi_frame.shape[:2]

                # 모든 텍스트 박스를 포함하는 최소 영역 계산
                min_x, min_y = float('inf'), float('inf')
                max_x, max_y = 0, 0

                for det in detections:
                    box = det.get('box')
                    if box and len(box) == 4:
                        for pt in box:
                            if isinstance(pt, (list, tuple)) and len(pt) == 2:
                                # normalized 좌표 (0~1)를 픽셀 좌표로 변환
                                x = pt[0] * roi_width
                                y = pt[1] * roi_height
                                min_x = min(min_x, x)
                                min_y = min(min_y, y)
                                max_x = max(max_x, x)
                                max_y = max(max_y, y)

                # 유효한 박스가 발견되면 해당 영역만 크롭
                if min_x < float('inf') and max_x > min_x and max_y > min_y:
                    # 약간의 패딩 추가 (5% 여유)
                    padding_x = max(5, int((max_x - min_x) * 0.05))
                    padding_y = max(5, int((max_y - min_y) * 0.05))

                    x1 = max(0, int(min_x) - padding_x)
                    y1 = max(0, int(min_y) - padding_y)
                    x2 = min(roi_width, int(max_x) + padding_x)
                    y2 = min(roi_height, int(max_y) + padding_y)

                    # 크롭된 영역 추출
                    cropped_roi = roi_frame[y1:y2, x1:x2]

                    if cropped_roi.size > 0:
                        roi_rgb = cv2.cvtColor(cropped_roi, cv2.COLOR_BGR2RGB)
                        success, buffer = cv2.imencode(".png", roi_rgb)
                        if success:
                            return buffer.tobytes()

            # detections가 없거나 크롭 실패 시 전체 ROI 사용
            roi_rgb = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2RGB)
            success, buffer = cv2.imencode(".png", roi_rgb)
            if success:
                return buffer.tobytes()

        except Exception as exc:
            print(f"ROI 이미지 인코딩 실패: {exc}")
        return None


class OCRExportWorker(QThread):
    """Export OCR-detected segments to individual video clips with parallel processing."""

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    completed = pyqtSignal(dict)  # {'segments': [...], 'cancelled': bool}

    def __init__(self, video_path, segments, output_dir, ffmpeg_path, include_audio=True, export_mode='balanced', bitrate=None, max_workers=4):
        super().__init__()
        self.video_path = video_path
        self.segments = segments or []
        self.output_dir = Path(output_dir)
        self.ffmpeg_path = ffmpeg_path
        self.include_audio = include_audio
        self.export_mode = export_mode  # 'fast' (VideoToolbox), 'quality' (libx264 slower), 'balanced' (libx264 faster)
        self.bitrate = bitrate or "8000k"  # 기본값: 8000k (fast 모드에서만 사용)
        self.max_workers = max_workers  # 동시 FFmpeg 프로세스 수 (기본값: 4)
        self._is_running = True
        self._was_cancelled = False
        self._progress_lock = Lock()  # 스레드 안전한 진행률 업데이트
        self._completed_count = 0
        self._executor = None  # ThreadPoolExecutor 참조 저장
        self._procs = set()  # 실행 중인 ffmpeg (취소 시 끝냄)
        self._procs_lock = Lock()

    def stop(self):
        self._is_running = False
        self._was_cancelled = True
        # ThreadPoolExecutor가 있으면 취소 시도
        if self._executor is not None:
            try:
                # 실행 중인 작업 취소 시도 (Python 3.9+)
                if hasattr(self._executor, 'shutdown'):
                    self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass  # 이미 종료되었거나 오류 발생 시 무시
        # 실행 중인 ffmpeg를 끝냄 (Windows에서는 남은 ffmpeg가 출력 파일을 잠금)
        with self._procs_lock:
            running = list(self._procs)
        for proc in running:
            proc.kill()

    def _export_single_segment(self, idx, segment, total_segments):
        """Export a single segment to video file. Returns (success, segment_with_path, error_msg)."""
        if not self._is_running:
            return (False, None, "취소됨")

        # duration이 segment에 직접 포함되어 있으면 사용 (정확한 프레임 계산)
        # 없으면 end_time - start_time으로 계산 (하위 호환성)
        if "duration" in segment:
            duration = segment["duration"]
        else:
            duration = max(0.0, segment["end_time"] - segment["start_time"])

        if duration <= 0.0:
            log_msg = f"[구간 {idx}/{total_segments}] duration이 0이므로 스킵"
            self.status.emit(log_msg)
            # print(f"[OCRExportWorker] {log_msg}")
            return (False, None, None)

        # edited_text가 있으면 우선 사용, 없으면 text(원본 OCR 결과) 사용
        safe_name = segment.get("edited_text") or segment.get("text") or "blank"
        safe_name = re.sub(r"[^0-9A-Za-z_-]+", "_", safe_name)[:80] or "segment"
        safe_name = file_names.avoid_reserved_name(safe_name)

        # 중복 파일명 처리: 같은 이름이 있으면 _1, _2, _3... 추가
        base_filename = f"{safe_name}.mp4"
        output_path = self.output_dir / base_filename
        counter = 1
        while output_path.exists():
            base_filename = f"{safe_name}_{counter}.mp4"
            output_path = self.output_dir / base_filename
            counter += 1

        filename = base_filename

        # 구간 정보 로그
        log_msg = f"[구간 {idx}/{total_segments}] '{filename}' 내보내기 시작..."
        self.status.emit(log_msg)
        # print(f"[OCRExportWorker] {log_msg}")

        # FFmpeg 정밀도 문제로 다음 프레임이 포함되는 것을 방지
        # end_time을 약간 일찍 끊어서 end_frame까지만 정확히 포함
        # 프레임의 마지막 시점 직전에 끊기
        start_frame = segment['start_frame']
        end_frame = segment['end_frame']
        start_time = segment['start_time']

        # fps 계산: duration과 프레임 수로 역산
        num_frames = end_frame - start_frame + 1
        if duration > 0:
            fps = num_frames / duration
        elif start_time > 0 and start_frame > 0:
            fps = start_frame / start_time
        else:
            fps = 24.0  # 기본값

        # end_frame의 끝 시점에서 약간 일찍 끊기 (다음 프레임 미포함)
        precise_end_time = (end_frame + 1 - 0.001) / fps

        # 구간 상세 정보 로그
        log_msg = f"[구간 {idx}/{total_segments}] 프레임: {start_frame}-{end_frame} ({num_frames}프레임), 시간: {start_time:.3f}s-{precise_end_time:.3f}s ({duration:.3f}s), FPS: {fps:.2f}"
        self.status.emit(log_msg)
        # print(f"[OCRExportWorker] {log_msg}")

        ffmpeg_cmd = [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(self.video_path),
            "-ss",
            f"{segment['start_time']:.6f}",
            "-to",
            f"{precise_end_time:.6f}",
        ]

        # 내보내기 모드에 따라 인코딩 설정 (고속: Mac VideoToolbox, Windows libx264 veryfast + 비트레이트)
        ffmpeg_cmd.extend(external_tools.video_encoder_args(self.export_mode, self.bitrate))
        if self.include_audio:
            ffmpeg_cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            ffmpeg_cmd.append("-an")
        mode_name = {"fast": external_tools.fast_mode_label(), "quality": "고품질 (libx264 slower, CRF 18)"}.get(
            self.export_mode, "균형 (libx264 faster, CRF 20)")
        bitrate_note = f", 비트레이트: {self.bitrate}" if self.export_mode == "fast" else ""
        log_msg = f"[구간 {idx}/{total_segments}] 인코딩 모드: {mode_name}{bitrate_note} (오디오: {'포함' if self.include_audio else '제외'})"

        self.status.emit(log_msg)
        # print(f"[OCRExportWorker] {log_msg}")

        ffmpeg_cmd.append(str(output_path))

        # FFmpeg 명령어 로그 (디버깅용)
        log_msg = f"[구간 {idx}/{total_segments}] FFmpeg 실행: {' '.join(ffmpeg_cmd[:10])}... (명령어 길이: {len(ffmpeg_cmd)}개 인자)"
        self.status.emit(log_msg)
        # print(f"[OCRExportWorker] {log_msg}")

        try:
            log_msg = f"[구간 {idx}/{total_segments}] FFmpeg 인코딩 시작..."
            self.status.emit(log_msg)
            # print(f"[OCRExportWorker] {log_msg}")

            proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    **external_tools.subprocess_kwargs())
        except OSError as exc:
            return (False, None, f"FFmpeg 실행 실패 ({filename}): {exc}")
        with self._procs_lock:
            self._procs.add(proc)
        if not self._is_running:  # stop()이 Popen과 등록 사이에 불린 경우
            proc.kill()
        try:
            _, stderr = proc.communicate()
        finally:
            with self._procs_lock:
                self._procs.discard(proc)
        if not self._is_running:
            output_path.unlink(missing_ok=True)  # 취소로 끊긴 미완성 파일
            return (False, None, "취소됨")
        if proc.returncode != 0:
            return (False, None, f"FFmpeg 오류 ({filename}): {external_tools.decode_output(stderr)}")

        log_msg = f"[구간 {idx}/{total_segments}] '{filename}' 내보내기 완료 → {output_path}"
        self.status.emit(log_msg)
        segment_with_path = dict(segment)
        segment_with_path["output_path"] = str(output_path)
        return (True, segment_with_path, None)

    def run(self):
        if not self.segments:
            log_msg = "내보낼 구간이 없습니다."
            self.progress.emit(100)
            self.status.emit(log_msg)
            # print(f"[OCRExportWorker] {log_msg}")
            self.completed.emit({"segments": [], "cancelled": False})
            return

        log_msg = f"FFmpeg로 구간을 내보내는 중… (총 {len(self.segments)}개 구간, 모드: {self.export_mode}, 병렬 처리: {self.max_workers}개)"
        self.status.emit(log_msg)
        # print(f"[OCRExportWorker] {log_msg}")

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            log_msg = f"출력 폴더 생성 완료: {self.output_dir}"
            self.status.emit(log_msg)
            # print(f"[OCRExportWorker] {log_msg}")
        except Exception as exc:
            error_msg = f"출력 폴더를 생성할 수 없습니다: {exc}"
            self.error.emit(error_msg)
            # print(f"[OCRExportWorker] {error_msg}")
            return

        total_segments = len(self.segments)
        exported_segments = []

        # ThreadPoolExecutor를 사용한 병렬 내보내기
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self._executor = executor
        future_to_segment = {}  # finally 블록에서 사용하기 위해 미리 초기화
        
        try:
            # 모든 구간을 비동기로 제출
            future_to_segment = {
                executor.submit(self._export_single_segment, idx, segment, total_segments): (idx, segment)
                for idx, segment in enumerate(self.segments, start=1)
            }

            # 완료된 순서대로 처리 (실행 순서와 다를 수 있음)
            for future in as_completed(future_to_segment):
                if not self._is_running:
                    log_msg = "구간 내보내기가 취소되었습니다."
                    self.status.emit(log_msg)
                    # print(f"[OCRExportWorker] {log_msg}")
                    self.progress.emit(100)
                    self.completed.emit({"segments": exported_segments, "cancelled": True})
                    break  # 루프 종료, finally에서 executor 종료

                idx, segment = future_to_segment[future]

                try:
                    success, segment_with_path, error_msg = future.result()

                    if error_msg and error_msg != "취소됨":
                        # FFmpeg 오류 발생
                        self.error.emit(error_msg)
                        # print(f"[OCRExportWorker] {error_msg}")
                        self.progress.emit(100)
                        self.completed.emit({"segments": exported_segments, "cancelled": False})
                        break  # 루프 종료, finally에서 executor 종료

                    if success and segment_with_path:
                        exported_segments.append(segment_with_path)

                    # 스레드 안전한 진행률 업데이트
                    with self._progress_lock:
                        self._completed_count += 1
                        progress = int((self._completed_count / total_segments) * 100)
                        self.progress.emit(progress)
                        log_msg = f"진행률: {progress}% ({self._completed_count}/{total_segments} 구간 완료)"
                        self.status.emit(log_msg)

                except Exception as exc:
                    error_msg = f"예상치 못한 오류: {exc}"
                    self.error.emit(error_msg)
                    # print(f"[OCRExportWorker] {error_msg}")
                    self.progress.emit(100)
                    self.completed.emit({"segments": exported_segments, "cancelled": False})
                    break  # 루프 종료, finally에서 executor 종료
        finally:
            # ThreadPoolExecutor 안전하게 종료
            try:
                if self._is_running:
                    # 정상 종료: 모든 작업 완료 대기
                    executor.shutdown(wait=True)
                else:
                    # 취소된 경우: 실행 중인 작업 취소 시도 후 대기
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        # Python 3.8 이하에서는 cancel_futures 지원 안 함
                        executor.shutdown(wait=False)
                    # 취소된 작업이 완료될 때까지 대기 (최대 10초)
                    import time
                    if future_to_segment:
                        start_time = time.time()
                        while time.time() - start_time < 10:
                            if all(future.done() for future in future_to_segment.keys()):
                                break
                            time.sleep(0.1)
            except Exception as exc:
                # print(f"[OCRExportWorker] Executor 종료 중 오류 (무시): {exc}")
                pass
            finally:
                self._executor = None

        self.progress.emit(100)
        log_msg = f"OCR 구간 내보내기가 완료되었습니다. (총 {len(exported_segments)}개 파일 생성, 출력 폴더: {self.output_dir})"
        self.status.emit(log_msg)
        # print(f"[OCRExportWorker] {log_msg}")
        self.completed.emit({"segments": exported_segments, "cancelled": self._was_cancelled})


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
                self.error.emit(
                    "TransNetV2가 설치되지 않았습니다.\n"
                    "설치: pip install git+https://github.com/soCzech/TransNetV2.git"
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
                    log_callback=log_callback
                )
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
