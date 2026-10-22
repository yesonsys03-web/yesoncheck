"""사이드바 썸네일 백그라운드 워커 (ThumbnailWorker·ThumbnailLoaderWorker). 기존 경로 `yesoncheck.workers`에서도 불러올 수 있음."""

import os
import sys
import traceback

import cv2
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap

from yesoncheck import thumbnails


class ThumbnailWorker(QThread):
    thumbnail_ready = pyqtSignal(str, QPixmap)
    save_failed = pyqtSignal(str, str)  # 썸네일 폴더, 내용 (썸네일 파일 경로·오류)
    # 썸네일을 만들지 못함: 내용 (영상·까닭 — 예상 못 한 오류는 스택 트레이스). 사이드바가 (폴더, 제목)마다 한 번 창으로
    failed = pyqtSignal(str)
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

    def _fail(self, reason):
        """썸네일을 만들지 못함 → 로그(stderr)와 failed 신호 (멈춘 워커는 알리지 않음 — 목록이 바뀌었거나 창을 닫음)."""
        print(f"썸네일을 만들지 못함: {self.file_path}\n{reason}", file=sys.stderr, flush=True)
        if self._is_running:
            self.failed.emit(f"영상: {self.file_path}\n{reason}")

    def run(self):
        cap = None
        try:
            if not self._is_running:
                return

            print(f"ThumbnailWorker 시작: {self.file_path}")

            # 썸네일 파일 경로 생성
            if self.thumbnail_folder:
                thumbnail_path = thumbnails.thumbnail_path(self.thumbnail_folder, self.file_path)

                # 영상보다 새 썸네일이 있으면 그대로 씀 (영상이 바뀌었으면 새로 만들어 바꿈).
                # 확인하지 못하면(썸네일 권한 등 — 사이드바가 창으로 알림) 새로 만듦. 영상이 없으면 아래에서 열지 못함
                try:
                    fresh = thumbnails.is_fresh(thumbnail_path, self.file_path)
                except OSError as exc:
                    print(f"썸네일을 확인하지 못해 새로 만듦: {thumbnail_path}\n{type(exc).__name__}: {exc}")
                    fresh = False
                if fresh:
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
                        except FileNotFoundError:
                            pass  # 그사이 다른 PC가 지움
                        except OSError as exc:
                            # 사이드바가 먼저 지워 보고 못 지우면 창으로 알림. 새 썸네일은 아래에서 바꿔 저장함 (못 하면 저장 실패)
                            print(f"깨진 썸네일을 지우지 못함 (바꿔 저장해 봄): {thumbnail_path}\n{type(exc).__name__}: {exc}")

            # OpenCV로 비디오 파일 열기
            cap = cv2.VideoCapture(self.file_path)
            if not cap.isOpened():
                self._fail("OpenCV가 영상을 열지 못함 (손상되었거나 지원하지 않는 형식·읽기 권한 없음)")
                return

            try:
                # 첫 번째 프레임 읽기
                ret, frame = cap.read()
                if not self._is_running:
                    return
                if not ret:
                    self._fail("영상의 첫 프레임을 읽지 못함 (손상되었거나 프레임이 없는 영상)")
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
                    self._fail(f"썸네일 이미지(QImage)를 만들지 못함 ({width}x{height})")
                    return

                # QPixmap 생성
                pixmap = QPixmap.fromImage(q_image)

                # QPixmap 유효성 검사
                if pixmap.isNull():
                    self._fail(f"썸네일 이미지(QPixmap)를 만들지 못함 ({width}x{height})")
                    return

                print(
                    f"QPixmap 생성 완료: {self.file_path}, pixmap isNull: {pixmap.isNull()}, size: {pixmap.size()}"
                )

                # 디스크에 썸네일 저장. 실패하면 창으로 알리고(save_failed), 이번 실행에서는 아이콘으로만 보여 줌.
                # 이 스레드에서는 QImage를 저장 (QPixmap은 GUI 스레드 전용). q_image가 가리키는 resized_frame을 지우기 전에
                if self.thumbnail_folder and thumbnail_path:
                    try:
                        thumbnails.save(q_image, thumbnail_path)
                        print(f"썸네일 디스크 저장 완료: {thumbnail_path}")
                    except (OSError, RuntimeError) as exc:
                        message = f"썸네일 파일: {thumbnail_path}\n이유: {type(exc).__name__}: {exc}"
                        if exc.__context__ is not None:
                            # 저장이 실패한 뒤 임시 파일 지우기도 실패함 → 먼저 난 원래 오류도 알림
                            original = exc.__context__
                            message += f"\n먼저 난 오류: {type(original).__name__}: {original}"
                        print(f"썸네일 디스크 저장 실패: {message}")
                        if self._is_running:
                            self.save_failed.emit(self.thumbnail_folder, message)

                # 메모리 정리
                del frame_rgb, resized_frame, q_image

                if self._is_running:
                    self.thumbnail_ready.emit(self.file_path, pixmap)
                    print(
                        f"썸네일 생성 완료: {self.file_path}, pixmap isNull: {pixmap.isNull()}, size: {pixmap.size()}"
                    )

            except Exception:
                self._fail(f"썸네일을 만들다 예상치 못한 오류:\n{traceback.format_exc()}")

        except Exception:
            self._fail(f"썸네일 워커에서 예상치 못한 오류:\n{traceback.format_exc()}")

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

    def __init__(self, thumbnail_files):
        """thumbnail_files: [(영상 경로, 그 영상의 썸네일 경로)] — 영상마다 자기 썸네일 폴더 (사이드바 항목의 자리)."""
        super().__init__()
        self.thumbnail_files = thumbnail_files
        self._is_running = True

    def stop(self):
        self._is_running = False
        self.wait(3000)  # 3초 대기
        if self.isRunning():
            self.terminate()
            self.wait(2000)  # 2초 대기

    def run(self):
        try:
            loaded_count = 0
            total_files = len(self.thumbnail_files)

            for file_path, thumbnail_path in self.thumbnail_files:
                if not self._is_running:
                    break

                try:
                    # 영상보다 새 썸네일만 보냄 (바뀐 영상은 썸네일 모드에서 새로 만듦)
                    if thumbnails.is_fresh(thumbnail_path, file_path):
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
