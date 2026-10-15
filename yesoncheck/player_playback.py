"""Playback and transport controls for VideoPlayer."""

import os
import subprocess
import sys
import time

import cv2
import numpy as np
from PyQt5.QtCore import QDateTime, QPointF, Qt, QTimer, QUrl
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap, QTransform
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from yesoncheck.frame_utils import FrameCalculator
from yesoncheck.workers import FFmpegWorker
from yesoncheck import external_tools, file_names, paths, thumbnails

class PlayerPlaybackMixin:

    def get_video_codec(self, file_path):
        """
        ffprobe를 사용하여 비디오 코덱 정보를 추출합니다.
        """
        try:
            result = subprocess.run(
                [external_tools.ffprobe_path(), '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=codec_name', '-of',
                 'default=noprint_wrappers=1:nokey=1', file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                **external_tools.subprocess_kwargs(),
            )
            codec_name = external_tools.decode_output(result.stdout).strip()
            if not codec_name:
                return "코덱 정보를 찾을 수 없습니다."
            return codec_name
        except external_tools.ToolNotFoundError as e:
            return f"오류: {e}"
        except subprocess.CalledProcessError as e:
            print(f"ffprobe 실행 중 오류 발생:\n{external_tools.decode_output(e.stderr)}")
            return f"ffprobe 실행 오류: {e.returncode}"
        except Exception as e:
            print(f"예상치 못한 오류 발생:\n{e}")
            return f"오류 발생: {str(e)}"

    def merge_videos(self):
        selected_items = self.sidebar.selectedItems()
        if not selected_items:
            return

        file_paths = [item.toolTip() for item in selected_items]
        file_paths.sort()

        output_file_path, _ = QFileDialog.getSaveFileName(self, "병합된 비디오 저장", "", "비디오 파일 (*.mov *.mp4)")

        if not output_file_path:
            return

        output_file_path = paths.normalize_native(file_names.with_extension(output_file_path, '.mov'))
        ffmpeg = self.require_ffmpeg()
        if ffmpeg is None:
            return

        self.progress_dialog = QProgressDialog("비디오 병합 중...", "취소", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setAutoReset(False)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.show()

        self.merge_worker = FFmpegWorker(
            lambda worker: external_tools.merge_videos_ffmpeg(
                ffmpeg, file_paths, output_file_path, worker.progress.emit, worker.register_process
            ),
            partial_output=output_file_path,
        )
        self.merge_worker.progress.connect(self.update_progress)
        self.merge_worker.finished.connect(self.on_merge_finished)
        self.merge_worker.error.connect(self.on_merge_error)
        self.merge_worker.start()

    def update_progress(self, value):
        self.progress_dialog.setValue(value)

    def on_merge_finished(self):
        self.progress_dialog.close()
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText("애니매틱 하나로 합치기가 완료되었습니다.")
        msg_box.setWindowTitle("완료")
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec_()

    def on_merge_error(self, error_message):
        self.progress_dialog.close()
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setText(f"오류가 발생했습니다: {error_message}")
        msg_box.setWindowTitle("오류")
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec_()

    def open_video_a(self, index):
        file_path = self.sidebar.item(index.row()).toolTip()
        self.open_file('A', file_path)

    def open_video_b(self, index):
        file_path = self.sidebar.item(index.row()).toolTip()
        self.open_file('B', file_path)

    def update_playlist(self):
        selected_job = self.jobComboBox.currentText()
        if selected_job != "job선택":
            self.sidebar.clear()
            selected_work = self.workComboBox.currentText()
            selected_season = self.seasonComboBox.currentText()

            try:
                # JSON에서 작품 기본 경로 가져오기
                work_base_path = self.get_work_path(selected_work)
                
                if not work_base_path:
                    base_path = None
                elif selected_work == "The_Johnsons":
                    # The_Johnsons는 시즌이 없으므로 시즌 경로 제외
                    base_path = os.path.join(work_base_path, selected_job)
                elif selected_work == "TJS_Animatic":
                    # TJS_Animatic는 시즌이 없으므로 시즌 경로 제외
                    base_path = os.path.join(work_base_path, selected_job)
                elif selected_season != "시즌선택":
                    # 시즌이 있는 경우
                    base_path = os.path.join(work_base_path, selected_season, selected_job)
                else:
                    base_path = None

                if base_path and os.path.isdir(base_path):
                    # 선택된 job 경로를 current_job_path로 설정 (UI job 선택용)
                    self.current_job_path = base_path
                    
                    # UI job 선택 시 직접 썸네일 폴더 설정 (지연 최소화).
                    # 전에 연 폴더(폴더 선택·끌어다 놓기·북마크)는 이제 상관없음 → 그곳에 썸네일을 저장하지 않게 지움
                    self.selected_folder_path = None
                    # 작품·시즌을 바꾸면 job 목록을 비우면서 빈 job으로 불림 → base_path가 작품·시즌 폴더이므로 만들지 않고,
                    # 이때 보이는 영상(TJS_Animatic은 모든 job의 영상)의 썸네일은 화면에만 (영상 폴더에도 만들지 않음)
                    if not selected_job:
                        self.current_thumbnail_folder = None
                        self._thumbnail_folder_problem = None
                        self._thumbnail_memory_only = True
                        print("job을 고르지 않음: 썸네일은 저장하지 않고 화면에만")
                    else:
                        self._thumbnail_memory_only = False
                        try:
                            self.current_thumbnail_folder = thumbnails.ensure_folder(base_path)
                            self._thumbnail_folder_problem = None
                        except OSError as e:
                            # 썸네일 폴더 생성 실패해도 파일 표시는 계속 진행: 이 작업의 썸네일은 화면에만.
                            # 지금은 로그만 남기고 창은 썸네일을 쓸 때 (작업을 열 때마다 창이 뜨지 않게)
                            self.current_thumbnail_folder = None
                            self._remember_thumbnail_folder_problem(os.path.join(base_path, thumbnails.FOLDER_NAME), e)
                    
                    # 메인 스레드에서 직접 처리 (스레드 제거로 지연 해결)
                    all_mov_files = []

                    # MS_Animatic, TJS_Animatic 전용 처리
                    if selected_work == "MS_Animatic":
                        mov_files = [f for f in os.listdir(base_path) if file_names.is_listed_video(f)]
                        for mov_file in mov_files:
                            full_path = os.path.join(base_path, mov_file)
                            all_mov_files.append((mov_file, full_path))
                    elif selected_work == "TJS_Animatic":
                        # TJS_Animatic: 먼저 base_path에서 직접 파일 검색
                        print(f"TJS_Animatic: Searching in base_path: {base_path}")
                        try:
                            if os.path.isdir(base_path):
                                # base_path의 모든 항목 확인
                                all_items = os.listdir(base_path)
                                print(f"Found {len(all_items)} items in {base_path}")
                                
                                mov_files = [f for f in all_items 
                                           if os.path.isfile(os.path.join(base_path, f))
                                           and f.lower().endswith(('.mov', '.mp4')) 
                                           and not f.startswith('.')]
                                print(f"Found {len(mov_files)} video files in base_path: {mov_files}")
                                
                                for mov_file in mov_files:
                                    full_path = os.path.join(base_path, mov_file)
                                    all_mov_files.append((mov_file, full_path))
                                    print(f"Added file: {mov_file}")
                                
                                # 하위 폴더에서도 검색 (ANIMATIC 폴더 등)
                                for folder in all_items:
                                    folder_path = os.path.join(base_path, folder)
                                    if os.path.isdir(folder_path) and not folder.startswith('.'):
                                        try:
                                            sub_items = os.listdir(folder_path)
                                            sub_mov_files = [f for f in sub_items 
                                                            if os.path.isfile(os.path.join(folder_path, f))
                                                            and f.lower().endswith(('.mov', '.mp4')) 
                                                            and not f.startswith('.')]
                                            if sub_mov_files:
                                                print(f"Found {len(sub_mov_files)} video files in subfolder {folder}: {sub_mov_files}")
                                            for mov_file in sub_mov_files:
                                                full_path = os.path.join(folder_path, mov_file)
                                                all_mov_files.append((mov_file, full_path))
                                        except (PermissionError, OSError) as e:
                                            print(f"Error accessing folder {folder_path}: {e}")
                                            pass
                                print(f"Total files found: {len(all_mov_files)}")
                        except Exception as e:
                            print(f"Error in TJS_Animatic file search: {e}")
                            import traceback
                            traceback.print_exc()
                            print(f"base_path: {base_path}")
                            print(f"base_path exists: {os.path.exists(base_path) if base_path else False}")
                            print(f"base_path isdir: {os.path.isdir(base_path) if base_path else False}")
                    
                    # 다른 작품들 처리 (최적화)
                    else:
                        # 먼저 부모 폴더에서 직접 검색 (가장 빠름)
                        parent_mov_files = [f for f in os.listdir(base_path) if file_names.is_listed_video(f)]
                        for parent_mov_file in parent_mov_files:
                            full_path = os.path.join(base_path, parent_mov_file)
                            all_mov_files.append((parent_mov_file, full_path))
                        
                        # 그 다음 하위 폴더 검색
                        for folder in os.listdir(base_path):
                            if os.path.isdir(os.path.join(base_path, folder)):
                                if selected_work == "BB_Animatic":
                                    frames_path = os.path.join(base_path, folder, "Quicktime")
                                elif selected_work == "TGN_Animatic":
                                    frames_path = os.path.join(base_path, folder, "ANIMATIC")
                                elif selected_work in ["BM_Animatic", "KOTH_Animatic"]:
                                    # 아래 특수 케이스에서 고정 폴더만 검색
                                    frames_path = None
                                else:
                                    # 기본: Harmony scene 구조 (scene-*/frames/*.mov)
                                    # 작품 경로 관리에서 새로 등록한 작품도 이 규칙을 따름
                                    frames_path = os.path.join(base_path, folder, "frames")

                                if frames_path and os.path.isdir(frames_path):
                                    mov_files = [f for f in os.listdir(frames_path) if file_names.is_listed_video(f)]
                                    for mov_file in mov_files:
                                        full_path = os.path.join(frames_path, mov_file)
                                        all_mov_files.append((mov_file, full_path))

                        # 특수 케이스 처리
                        if selected_work == "BM_Animatic":
                            frames_path = os.path.join(base_path, "ANIMATIC")
                            if os.path.isdir(frames_path):
                                mov_files = [f for f in os.listdir(frames_path) if file_names.is_listed_video(f)]
                                for mov_file in mov_files:
                                    full_path = os.path.join(frames_path, mov_file)
                                    all_mov_files.append((mov_file, full_path))

                        if selected_work == "KOTH_Animatic":
                            # 애니매틱 폴더 이름: 시즌 15까지 'POST-LOCK ANIMATIC', 시즌 16부터 '1601_ANIMATIC'·'1604_ANIMATICS'
                            for anim_folder in os.listdir(base_path):
                                frames_path = os.path.join(base_path, anim_folder)
                                if 'ANIMATIC' in anim_folder.upper() and os.path.isdir(frames_path):
                                    mov_files = [f for f in os.listdir(frames_path) if file_names.is_listed_video(f)]
                                    for mov_file in mov_files:
                                        full_path = os.path.join(frames_path, mov_file)
                                        all_mov_files.append((mov_file, full_path))

                    def sort_key(item, case_sensitive=False):
                        filename = item[0]
                        is_hd = '_HD' in filename
                        parts = filename.split('_')
                        if len(parts) >= 4:
                            series_ep = parts[0] + '_' + parts[1]  # BB_802
                            scene = parts[2]  # A001, B001 등
                            scene_letter = scene[0]  # A, B 등
                            scene_number = int(scene[1:]) if scene[1:].isdigit() else 0  # 001, 002 등을 정수로
                            take = parts[3]  # TK1 등
                            return (is_hd, series_ep, scene_letter, scene_number, take)
                        else:
                            return (is_hd, filename if case_sensitive else filename.lower())

                    # 파일을 HD와 non-HD로 분리 (최적화)
                    hd_files = [f for f in all_mov_files if '_HD' in f[0]]
                    non_hd_files = [f for f in all_mov_files if '_HD' not in f[0]]
                    
                    # locale 설정을 한 번만 수행
                    import locale
                    try:
                        current_locale = locale.getlocale()
                        if current_locale[0] != 'en_US':
                            locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
                    except locale.Error:
                        try:
                            locale.setlocale(locale.LC_ALL, '')
                        except:
                            pass  # locale 설정 실패 시 기본 정렬 사용
                    
                    # 정렬 수행
                    try:
                        hd_files.sort(key=lambda x: locale.strxfrm(x[0]))
                        non_hd_files.sort(key=lambda x: locale.strxfrm(x[0]))
                    except:
                        # locale 정렬 실패 시 기본 정렬 사용
                        hd_files.sort(key=lambda x: x[0].lower())
                        non_hd_files.sort(key=lambda x: x[0].lower())

                    # 정렬된 non-HD 파일을 먼저 추가하고, 그 다음 HD 파일 추가
                    all_mov_files = non_hd_files + hd_files

                    # 사이드바 업데이트 최적화
                    self.sidebar.setUpdatesEnabled(False)  # UI 업데이트 일시 중지
                    for mov_file, full_path in all_mov_files:
                        item = QListWidgetItem(mov_file)  # Display filename only
                        item.setData(Qt.UserRole, full_path)  # 파일 경로를 UserRole에 저장
                        item.setToolTip(full_path)  # Full path as tooltip
                        self.sidebar.addItem(item)
                    self.sidebar.setUpdatesEnabled(True)  # UI 업데이트 재개

                    # Close previous video files
                    if self.cap_a:
                        self.cap_a.release()
                        self.cap_a = None
                    if self.cap_b:
                        self.cap_b.release()
                        self.cap_b = None

                    # Initialize video file info
                    self.filename_a = ""
                    self.filename_b = ""
                    self.frame_a = None
                    self.frame_b = None

                    # Automatically open the first video file
                    if all_mov_files:
                        self.playlist = [full_path for _, full_path in all_mov_files]
                        self.open_file('A', self.playlist[0])
                        # 썸네일 로딩은 썸네일 버튼을 누를 때만 실행하도록 변경
                else:
                    print(f"Directory not found or invalid: {base_path}")
            except Exception as e:
                print(f"An error occurred: {e}")

    def open_file(self, video_type, file_path=None):
        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(self, f"Open Video {video_type}")

        if file_path:
            file_path = paths.normalize_native(file_path)
            # 플레이리스트 재생 중이 아닐 때만 stop_video 호출
            if not self.is_playlist_playing:
                self.stop_video()
            else:
                # 플레이리스트 재생 중에는 타이머만 정지
                self.timer.stop()
                self.stop_media_player()
                
            print(f"Attempting to open video file: {file_path}")
            
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                print(f"Failed to open video file: {file_path}")
                return

            # 새로운 영상을 열 때 프레임 캐시 초기화 (이전 영상 프레임 방지)
            self.clear_cache()

            if video_type == 'A':
                if self.cap_a: self.cap_a.release()
                self.filename_a = file_path
                self.cap_a = cap
                # 소리 재생기를 처음 만드는 곳 (mediaPlayer 속성: 처음 쓸 때 만듦)
                self.mediaPlayer.setMedia(QMediaContent(QUrl.fromLocalFile(file_path)))
                
                total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
                self.positionScroll.setMaximum(max(1, total_frames - 1))
                # 스크롤바 핸들 크기를 고정 (페이지 스텝 설정)
                # self.positionScroll.setPageStep(100)  # 고정된 페이지 스텝 값

            elif video_type == 'B':
                if self.cap_b: self.cap_b.release()
                self.filename_b = file_path
                self.cap_b = cap

            if self.filename_a and self.filename_b:
                self.filenameLabel.setText(f"A: {os.path.basename(self.filename_a)}, B: {os.path.basename(self.filename_b)}")
            elif self.filename_a:
                self.filenameLabel.setText(f"A: {os.path.basename(self.filename_a)}")

            self.videoWidget.initial_fit = True
            self.detect_fps()
            self.labelPlaybackFPS.setText('재생: 대기')
            # 스레드 안전성을 위해 QTimer.singleShot 대신 직접 호출
            self.display_first_frame()
            if video_type == 'A':
                self.reset_ocr_state()
                if hasattr(self, 'on_video_annotations_reset'):
                    self.on_video_annotations_reset(file_path)

    def change_gpu_backend(self, index):
        backend = self.gpuComboBox.currentText()
        if backend == "CPU":
            self.use_gpu = False
            self.gpu_backend = None
        elif backend == "NVIDIA (CUDA)":
            self.use_gpu = True
            self.gpu_backend = 'cuda'
            if cv2.cuda.getCudaEnabledDeviceCount() > 0:
                cv2.cuda.setDevice(0)
        elif backend == "AMD (OpenCL)":
            self.use_gpu = True
            self.gpu_backend = 'opencl'
            if cv2.ocl.haveOpenCL():
                cv2.ocl.setUseOpenCL(True)

        if self.cap_a:
            current_pos = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES))
            self.seek_to_frame(current_pos)

    def process_frame(self, frame):
        if self.use_gpu:
            if self.gpu_backend == 'cuda':
                gpu_frame = cv2.cuda_GpuMat()
                gpu_frame.upload(frame)
                gpu_frame = cv2.cuda.cvtColor(gpu_frame, cv2.COLOR_BGR2RGB)
                return gpu_frame.download()
            elif self.gpu_backend == 'opencl':
                gpu_frame = cv2.UMat(frame)
                return cv2.cvtColor(gpu_frame, cv2.COLOR_BGR2RGB).get()
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def detect_fps(self):
        if self.cap_a:
            fps = self.cap_a.get(cv2.CAP_PROP_FPS)
            if fps > 0:
                # 일반적인 비표준 FPS 값들 감지 (23.976, 29.97, 59.94 등)
                # 23.976 감지 (23.98 근사값도 처리)
                if abs(fps - 23.976) < 0.01:
                    fps_str = "23.976"
                # 29.97 감지
                elif abs(fps - 29.97) < 0.01:
                    fps_str = "29.97"
                # 59.94 감지
                elif abs(fps - 59.94) < 0.01:
                    fps_str = "59.94"
                # 정수 FPS인 경우
                elif fps == int(fps):
                    fps_str = str(int(fps))
                # 기타 소수점 FPS는 정확한 값 사용
                else:
                    fps_str = f"{fps:.3f}"
                
                # 콤보박스에 값이 없으면 추가
                existing_items = [self.frameRateComboBox.itemText(i) for i in range(self.frameRateComboBox.count())]
                if fps_str not in existing_items:
                    self.frameRateComboBox.addItem(fps_str)
                
                self.frameRateComboBox.setCurrentText(fps_str)

    def display_first_frame(self):
        if self.cap_a:
            self.seek_to_frame(1)
            if not self.is_playlist_playing:
                self.videoWidget.reset_view()

    def update_frame(self):
        # 슬라이더 드래그 중이고 OCR 검토 창이 열려있으면 업데이트 스킵 (성능 최적화)
        is_dragging = self.positionScroll.isSliderDown() or getattr(self, 'is_dragging', False)
        has_ocr_dialog = hasattr(self, 'ocr_review_dialog') and self.ocr_review_dialog is not None and self.ocr_review_dialog.isVisible()
        
        if is_dragging and has_ocr_dialog:
            # 드래그 중일 때는 최소한의 업데이트만 수행 (오버레이도 스킵)
            frame_a_to_show = self.frame_a
            if hasattr(self, "prepare_frame_for_display"):
                frame_a_to_show = self.prepare_frame_for_display(self.frame_a)
            
            frame_b_to_show = None  # OCR 검토 창이 열려있을 때는 B 프레임도 스킵
            self.videoWidget.updateFrame(frame_a_to_show, frame_b_to_show)
            if hasattr(self, 'refresh_frame_annotations_display'):
                self.refresh_frame_annotations_display()
            return  # OCR 검토 창 업데이트 스킵
        
        # OCR 검토 창이 열려있고 재생 중일 때도 업데이트 빈도를 줄임
        if has_ocr_dialog and self.timer.isActive():
            # 재생 중일 때는 매 프레임마다 업데이트하지 않고 2프레임마다 업데이트
            if not hasattr(self, '_ocr_dialog_frame_skip_counter'):
                self._ocr_dialog_frame_skip_counter = 0
            self._ocr_dialog_frame_skip_counter += 1
            if self._ocr_dialog_frame_skip_counter % 2 != 0:
                return  # 홀수 프레임은 스킵
        
        # 재생 중일 때만 FPS 카운터 증가
        if self.timer.isActive():
            self.increment_fps_counter()
        
        # 오버레이 컨트롤 상태 동기화
        self.update_overlay_controls()
        
        # print(f"update_frame 호출됨 - frame_a 크기: {self.frame_a.shape if self.frame_a is not None else 'None'}")
        
        # 오른쪽 끝 드래그 감지 및 특별 처리
        if self.cap_a and self.positionScroll.isSliderDown():
            total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
            current_scroll_value = self.positionScroll.value()
            
            # 오른쪽 끝에 정확히 있을 때만 Total frame과 일치하도록 표시
            if current_scroll_value == self.positionScroll.maximum():
                print(f"오른쪽 끝 드래그 감지: Total={total_frames}, Current={total_frames}로 강제 설정")
                self.labelFrameCount.setText(f'Current: {total_frames}')
                feet_display = self.get_feet_display(total_frames)
                self.labelTotalFrames.setText(f'Total: {total_frames} {feet_display}')
                
                # 시간 정보도 업데이트
                original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
                if original_fps > 0:
                    current_time = (total_frames - 1) / original_fps if total_frames > 1 else 0
                    total_time = (total_frames - 1) / original_fps if total_frames > 1 else 0
                    self.timeLabel.setText(f"{self.format_time(current_time)} / {self.format_time(total_time)}")
        
        frame_a_to_show = self.frame_a
        if hasattr(self, "prepare_frame_for_display"):
            frame_a_to_show = self.prepare_frame_for_display(self.frame_a)
        elif frame_a_to_show is not None and self.show_overlay:
            frame_a_to_show = self.frame_a.copy()
            self.overlay_text(frame_a_to_show)
        
        frame_b_to_show = self.frame_b if (self.videoWidget.wipe_enabled_x or self.videoWidget.wipe_enabled_y) else None
        
        self.videoWidget.updateFrame(frame_a_to_show, frame_b_to_show)
        if hasattr(self, 'refresh_frame_annotations_display'):
            self.refresh_frame_annotations_display()
        self.update_position_info()

    def overlay_text(self, frame):
        height, width = frame.shape[:2]
        text = f"File: {os.path.basename(self.filename_a)}, Frame: {int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES))}/{int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))}"
        font, scale, thickness = cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2
        (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
        
        # 텍스트가 프레임 너비를 초과하지 않도록 위치 조정
        x = 10
        y = height - 20
        
        # 텍스트가 오른쪽 끝을 넘어가면 왼쪽으로 이동
        if x + tw + 10 > width:
            x = width - tw - 10
        
        # 텍스트가 여전히 너무 크면 폰트 크기 줄이기
        if x < 10:
            scale = 0.5
            (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
            x = max(10, width - tw - 10)
        
        cv2.rectangle(frame, (x - 5, y - th - 5), (x + tw + 5, y + 5), (255,255,255), -1)
        cv2.putText(frame, text, (x, y), font, scale, (0,0,0), thickness)

    def change_position(self, value):
        """기존 메서드 - 호환성을 위해 유지"""
        self.on_slider_value_changed(value)

    def on_overlay_slider_pressed(self):
        """오버레이 슬라이더를 누를 때 현재 프레임 라벨 표시"""
        if hasattr(self, 'overlayCurrentFrameLabel'):
            self.overlayCurrentFrameLabel.setVisible(True)

    def on_overlay_slider_moved(self, value):
        """오버레이 슬라이더 드래그 중 실시간 업데이트"""
        if not self.cap_a:
            return

        # 드래그 중 업데이트 빈도 제어
        current_time = QDateTime.currentMSecsSinceEpoch()
        if current_time - self.last_drag_update < self.drag_update_interval:
            return
        
        self.last_drag_update = current_time
        self.is_dragging = True

        total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 1:
            return

        # 오버레이 슬라이더는 직접 프레임 인덱스를 사용
        target_frame_idx = max(0, min(value, total_frames - 1))

        # 현재 프레임 라벨 실시간 업데이트
        if hasattr(self, 'overlayCurrentFrameLabel'):
            self.overlayCurrentFrameLabel.setText(f'{target_frame_idx + 1}')
            self.overlayCurrentFrameLabel.setVisible(True)
        
        # 시작 프레임 라벨도 실시간 업데이트 (드래그 중일 때)
        if hasattr(self, 'overlayStartFrameLabel'):
            self.overlayStartFrameLabel.setText(f'{target_frame_idx + 1}')

        # 오버레이 슬라이더 전용: B 프레임을 완전히 무시하고 A 프레임만 처리
        self._overlay_slider_preview_seek(target_frame_idx, total_frames)

    def _overlay_slider_preview_seek(self, target_frame_idx, total_frames):
        """오버레이 슬라이더 전용 프리뷰 - B 프레임 완전 무시"""
        try:
            # 오버레이 슬라이더 드래그 중에는 캐시를 사용하지 않음 (이전 영상 프레임 방지)
            # 1. 성능 모드별 동적 프레임 스킵
            current_pos = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            if current_pos < 0:
                current_pos = 0
            
            # 성능 모드에 따른 동적 스킵 임계값
            skip_threshold = self.frame_skip_threshold
            if abs(target_frame_idx - current_pos) < skip_threshold:
                return
            
            # 2. 초고속 프레임 이동 (A 프레임만 처리, 캐시 무시)
            self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
            ret_a, frame_a = self.cap_a.read()
            
            if ret_a and frame_a is not None:
                # 드래그 중일 때는 최소한의 처리만 수행
                if self.is_dragging:
                    # 컬러 변환만 수행 (GPU 처리 스킵)
                    self.frame_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2RGB)
                else:
                    # 일반 모드: 4K 최적화 적용
                    self.frame_a = self.optimize_for_4k(frame_a)
                
                # 오버레이 슬라이더 드래그 중에는 캐시에 저장하지 않음
                # (이전 영상의 프레임이 섞이는 것을 방지)
                
                # B 프레임을 강제로 None으로 설정 (오버레이 슬라이더에서는 완전 무시)
                self.frame_b = None
                
                # 오버레이 슬라이더 전용 UI 업데이트
                self._overlay_slider_ui_update(target_frame_idx, total_frames)
                
        except Exception as e:
            # 오류 발생 시 무시하고 계속 진행
            pass

    def _overlay_slider_ui_update(self, frame_idx, total_frames):
        """오버레이 슬라이더 전용 UI 업데이트 - B 프레임 완전 무시"""
        # B 키 오버레이 적용
        frame_a_to_show = self.frame_a
        if hasattr(self, "prepare_frame_for_display"):
            frame_a_to_show = self.prepare_frame_for_display(self.frame_a)
        elif frame_a_to_show is not None and self.show_overlay:
            frame_a_to_show = self.frame_a.copy()
            self.overlay_text(frame_a_to_show)
        
        # 오버레이 슬라이더에서는 B 프레임을 절대 표시하지 않음
        frame_b_to_show = None
        
        # 비디오 프레임 업데이트 (A 프레임만)
        self.videoWidget.updateFrame(frame_a_to_show, frame_b_to_show)
        if hasattr(self, "refresh_frame_annotations_display"):
            self.refresh_frame_annotations_display()
        
        # 현재 프레임 번호만 업데이트 (간소화)
        self.labelFrameCount.setText(f'Current: {frame_idx + 1}')
        
        # 오버레이 현재 프레임 라벨 업데이트
        if hasattr(self, 'overlayCurrentFrameLabel'):
            self.overlayCurrentFrameLabel.setText(f'{frame_idx + 1}')
        
        # 시작 프레임 라벨도 업데이트 (드래그 중일 때)
        if hasattr(self, 'overlayStartFrameLabel'):
            self.overlayStartFrameLabel.setText(f'{frame_idx + 1}')
        
        # 스크롤바 업데이트 (신호 차단으로 무한 루프 방지)
        if total_frames > 1:
            scroll_val = round((frame_idx / (total_frames - 1)) * self.positionScroll.maximum())
            scroll_val = max(0, min(scroll_val, self.positionScroll.maximum()))
            self.positionScroll.blockSignals(True)
            self.positionScroll.setValue(scroll_val)
            self.positionScroll.blockSignals(False)

    def on_overlay_slider_released(self):
        """오버레이 슬라이더 드래그 완료 후"""
        if not self.cap_a:
            return

        # 드래그 상태 초기화
        self.is_dragging = False

        # 현재 프레임 라벨 숨김
        if hasattr(self, 'overlayCurrentFrameLabel'):
            self.overlayCurrentFrameLabel.setVisible(False)

        total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 1:
            return

        # 오버레이 슬라이더의 현재 값 사용
        value = self.overlaySlider.value()
        target_frame_idx = max(0, min(value, total_frames - 1))

        # 오버레이 슬라이더 드래그 완료 후: B 프레임을 안전하게 복원
        self._overlay_slider_final_seek(target_frame_idx, total_frames)
        
        # 오디오 동기화
        self.sync_audio_on_release()

    def _overlay_slider_final_seek(self, target_frame_idx, total_frames):
        """오버레이 슬라이더 드래그 완료 후 최종 처리 - B 프레임 안전 복원"""
        try:
            # 1. A 프레임 정확한 위치로 이동
            self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
            ret_a, frame_a = self.cap_a.read()
            
            if ret_a and frame_a is not None:
                self.frame_a = self.optimize_for_4k(frame_a)
                
                # 2. B 프레임 안전하게 복원 (wipe가 활성화된 경우에만)
                if self.cap_b and self.videoWidget.wipeEnabled:
                    self.cap_b.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
                    ret_b, frame_b = self.cap_b.read()
                    if ret_b and frame_b is not None:
                        self.frame_b = self.optimize_for_4k(frame_b)
                    else:
                        self.frame_b = None
                else:
                    self.frame_b = None
                
                # 3. UI 업데이트
                self._update_ui_after_seek(target_frame_idx, total_frames)
                
        except Exception as e:
            print(f"오버레이 슬라이더 최종 처리 실패: {e}")
            # 실패 시 일반적인 seek로 폴백
            self._precise_seek(target_frame_idx, total_frames)

    def on_slider_moved(self, value):
        """메인 슬라이더 드래그 중 실시간 업데이트"""
        if not self.cap_a:
            return

        # OCR 검토 창이 열려있을 때는 업데이트 빈도를 더 낮춤
        has_ocr_dialog = hasattr(self, 'ocr_review_dialog') and self.ocr_review_dialog is not None and self.ocr_review_dialog.isVisible()
        if has_ocr_dialog:
            # OCR 검토 창이 열려있을 때는 업데이트 간격을 3배로 늘림
            drag_update_interval = self.drag_update_interval * 3
        else:
            drag_update_interval = self.drag_update_interval

        # 드래그 중 업데이트 빈도 제어
        current_time = QDateTime.currentMSecsSinceEpoch()
        if current_time - self.last_drag_update < drag_update_interval:
            return
        
        self.last_drag_update = current_time
        self.is_dragging = True

        total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 1:
            return

        # 스크롤바 값이 최대값에 가까우면 마지막 프레임으로 설정
        if value >= self.positionScroll.maximum() - 1:
            target_frame_idx = total_frames - 1
        else:
            target_frame_idx = round((value / self.positionScroll.maximum()) * (total_frames - 1))
            target_frame_idx = max(0, min(target_frame_idx, total_frames - 1))

        # OCR 검토 창이 열려있을 때는 최소한의 업데이트만 수행
        if has_ocr_dialog:
            self._minimal_preview_seek(target_frame_idx, total_frames)
        else:
            # 드래그 중일 때는 빠른 프리뷰를 위해 간소화된 처리
            self._quick_preview_seek(target_frame_idx, total_frames)

    def on_slider_value_changed(self, value):
        """슬라이더 값 변경 시 (드래그 완료 후)"""
        if not self.cap_a:
            return

        # 드래그 상태 초기화
        self.is_dragging = False

        total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 1:
            return

        # 스크롤바 값이 최대값에 가까우면 마지막 프레임으로 설정
        if value >= self.positionScroll.maximum() - 1:
            target_frame_idx = total_frames - 1
        else:
            target_frame_idx = round((value / self.positionScroll.maximum()) * (total_frames - 1))
            target_frame_idx = max(0, min(target_frame_idx, total_frames - 1))

        # 드래그가 끝났을 때는 정확한 프레임으로 이동
        self._precise_seek(target_frame_idx, total_frames)

    def _minimal_preview_seek(self, target_frame_idx, total_frames):
        """OCR 검토 창이 열려있을 때 최소한의 프리뷰만 수행"""
        try:
            # OCR 검토 창이 열려있을 때는 프레임 스킵 임계값을 더 크게 설정
            current_pos = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            if current_pos < 0:
                current_pos = 0
            
            # OCR 검토 창이 열려있을 때는 더 큰 스킵 임계값 사용 (5배)
            skip_threshold = self.frame_skip_threshold * 5
            if abs(target_frame_idx - current_pos) < skip_threshold:
                return
            
            # 최소한의 프레임 이동만 수행
            self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
            ret_a, frame_a = self.cap_a.read()
            
            if ret_a and frame_a is not None:
                # 컬러 변환만 수행 (모든 추가 처리 스킵)
                self.frame_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2RGB)
                
                # UI 업데이트는 최소한만 (오버레이 스킵)
                self.videoWidget.updateFrame(self.frame_a, None)
                
                # 프레임 카운터만 업데이트 (시간 라벨 스킵)
                self.labelFrameCount.setText(f'Current: {target_frame_idx + 1}')
                return
            
        except Exception as e:
            print(f"최소 프리뷰 오류: {e}")
    
    def _quick_preview_seek(self, target_frame_idx, total_frames):
        """드래그 중 초고속 프리뷰 - 4K 최적화"""
        try:
            # 1. 캐시에서 먼저 확인 (가장 빠른 경로)
            cached_frame = self.get_cached_frame(target_frame_idx)
            if cached_frame is not None:
                self.frame_a = cached_frame
                # 캐시 히트 시 B 키 오버레이 적용하여 UI 업데이트
                self._ultra_fast_ui_update(target_frame_idx, total_frames)
                return
            
            # 2. 성능 모드별 동적 프레임 스킵
            current_pos = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            if current_pos < 0:
                current_pos = 0
            
            # 성능 모드에 따른 동적 스킵 임계값
            skip_threshold = self.frame_skip_threshold
            if abs(target_frame_idx - current_pos) < skip_threshold:
                return
            
            # 3. 초고속 프레임 이동 (최소한의 처리만)
            self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
            ret_a, frame_a = self.cap_a.read()
            
            if ret_a and frame_a is not None:
                # 드래그 중일 때는 최소한의 처리만 수행
                if self.is_dragging:
                    # 컬러 변환만 수행 (GPU 처리 스킵)
                    self.frame_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2RGB)
                else:
                    # 일반 모드: 4K 최적화 적용
                    self.frame_a = self.optimize_for_4k(frame_a)
                
                # 캐시에 저장 (즉시 처리)
                self.cache_frame(target_frame_idx, self.frame_a)
                
                # B 동기화 (드래그 중에는 완전히 스킵)
                if not self.is_dragging and self.cap_b and self.videoWidget.wipeEnabled:
                    self.cap_b.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
                    ret_b, frame_b = self.cap_b.read()
                    if ret_b and frame_b is not None:
                        self.frame_b = self.optimize_for_4k(frame_b)
                    else:
                        self.frame_b = None
                else:
                    # 드래그 중이거나 B 비디오가 없으면 B 프레임을 None으로 설정
                    self.frame_b = None
                
                # 초고속 UI 업데이트 (시간 정보만 업데이트)
                self._ultra_fast_ui_update(target_frame_idx, total_frames)
                
        except Exception as e:
            # 오류 발생 시 무시하고 계속 진행
            pass

    def _ultra_fast_ui_update(self, frame_idx, total_frames):
        """초고속 UI 업데이트 - 드래그 중 전용"""
        # B 키 오버레이 적용
        frame_a_to_show = self.frame_a
        if hasattr(self, "prepare_frame_for_display"):
            frame_a_to_show = self.prepare_frame_for_display(self.frame_a)
        elif frame_a_to_show is not None and self.show_overlay:
            frame_a_to_show = self.frame_a.copy()
            self.overlay_text(frame_a_to_show)
        
        # 드래그 중이거나 B 프레임이 없으면 B 프레임을 표시하지 않음
        frame_b_to_show = None
        if not self.is_dragging and self.frame_b is not None and (self.videoWidget.wipe_enabled_x or self.videoWidget.wipe_enabled_y):
            frame_b_to_show = self.frame_b
        
        # 비디오 프레임 업데이트
        self.videoWidget.updateFrame(frame_a_to_show, frame_b_to_show)
        if hasattr(self, "refresh_frame_annotations_display"):
            self.refresh_frame_annotations_display()
        
        # 드래그 중일 때는 최소한의 UI 업데이트만
        if self.is_dragging:
            # 현재 프레임 번호만 업데이트 (간소화)
            self.labelFrameCount.setText(f'Current: {frame_idx + 1}')
            
            # 오버레이 현재 프레임 라벨 업데이트
            if hasattr(self, 'overlayCurrentFrameLabel'):
                self.overlayCurrentFrameLabel.setText(f'{frame_idx + 1}')
            
            # 시작 프레임 라벨도 업데이트 (드래그 중일 때)
            if hasattr(self, 'overlayStartFrameLabel'):
                self.overlayStartFrameLabel.setText(f'{frame_idx + 1}')
            
            # 스크롤바 업데이트 (신호 차단으로 무한 루프 방지)
            if total_frames > 1:
                scroll_val = round((frame_idx / (total_frames - 1)) * self.positionScroll.maximum())
                scroll_val = max(0, min(scroll_val, self.positionScroll.maximum()))
                self.positionScroll.blockSignals(True)
                self.positionScroll.setValue(scroll_val)
                self.positionScroll.blockSignals(False)
                
                # 오버레이 슬라이더도 함께 업데이트
                if hasattr(self, 'overlaySlider'):
                    self.overlaySlider.blockSignals(True)
                    self.overlaySlider.setValue(frame_idx)
                    self.overlaySlider.blockSignals(False)
            
            # 드래그 중에는 시간 정보 업데이트 스킵 (성능 향상)
        else:
            # 일반 모드: 전체 UI 업데이트
            self._quick_ui_update(frame_idx, total_frames)

    def _precise_seek(self, target_frame_idx, total_frames):
        """정확한 프레임 이동 (드래그 완료 후)"""
        print(f"정확한 이동: 목표프레임={target_frame_idx}, 전체프레임={total_frames}")

        # 마지막 프레임인 경우 특별 처리
        if target_frame_idx == total_frames - 1:
            self._seek_to_last_frame(total_frames)
        # 마지막 프레임 근처에서는 더 보수적으로 접근
        elif target_frame_idx >= total_frames - 3:
            self._seek_conservative(target_frame_idx, total_frames)
        else:
            # 일반적인 경우 직접 프레임 이동 시도
            if self._seek_direct(target_frame_idx, total_frames):
                pass
            else:
                self._seek_sequential(target_frame_idx, total_frames)

    def _quick_ui_update(self, frame_idx, total_frames):
        """드래그 중 빠른 UI 업데이트"""
        # B 키 오버레이 적용
        frame_a_to_show = self.frame_a
        if hasattr(self, "prepare_frame_for_display"):
            frame_a_to_show = self.prepare_frame_for_display(self.frame_a)
        elif frame_a_to_show is not None and self.show_overlay:
            frame_a_to_show = self.frame_a.copy()
            self.overlay_text(frame_a_to_show)
        
        # 드래그 중이거나 B 프레임이 없으면 B 프레임을 표시하지 않음
        frame_b_to_show = None
        if not self.is_dragging and self.frame_b is not None and (self.videoWidget.wipe_enabled_x or self.videoWidget.wipe_enabled_y):
            frame_b_to_show = self.frame_b
        
        # 비디오 프레임 업데이트
        self.videoWidget.updateFrame(frame_a_to_show, frame_b_to_show)
        if hasattr(self, "refresh_frame_annotations_display"):
            self.refresh_frame_annotations_display()
        
        # 드래그 중일 때는 최소한의 UI 업데이트만
        if self.is_dragging:
            # 현재 프레임 번호만 업데이트 (간소화)
            self.labelFrameCount.setText(f'Current: {frame_idx + 1}')
        else:
            # 현재 프레임 번호 업데이트
            self.labelFrameCount.setText(f'Current: {frame_idx + 1}')
            
            # 시간 정보 업데이트 (간소화)
            original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
            if original_fps > 0:
                current_time = frame_idx / original_fps
                total_time = (total_frames - 1) / original_fps if total_frames > 1 else 0
                self.timeLabel.setText(f"{self.format_time(current_time)} / {self.format_time(total_time)}")

    def _seek_to_last_frame(self, total_frames):
        """마지막 프레임으로 정확하게 이동하는 전용 메서드"""
        try:
            print(f"마지막 프레임 이동: {total_frames - 1}")
            
            # 방법 1: 실제 마지막 프레임 찾기 (보고된 프레임 수보다 작을 수 있음)
            actual_last_frame = self._find_actual_last_frame(total_frames)
            print(f"실제 마지막 프레임: {actual_last_frame}")
            
            if actual_last_frame >= 0:
                # 실제 마지막 프레임으로 이동
                self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, actual_last_frame)
                ret_a, frame_a = self.cap_a.read()
                
                if ret_a and frame_a is not None:
                    self.frame_a = self.process_frame(frame_a)
                    
                    # B 동기화
                    if self.cap_b and self.videoWidget.wipeEnabled:
                        self.cap_b.set(cv2.CAP_PROP_POS_FRAMES, actual_last_frame)
                        ret_b, frame_b = self.cap_b.read()
                        if ret_b and frame_b is not None:
                            self.frame_b = self.process_frame(frame_b)
                    
                    # UI 업데이트 - OpenCV가 보고하는 총 프레임 수를 사용하여 일치시킴
                    self._update_ui_for_last_frame(total_frames)
                    return True
                else:
                    print("마지막 프레임 읽기 실패")
                    return False
            else:
                print("실제 마지막 프레임을 찾을 수 없음")
                return False
                
        except Exception as e:
            print(f"마지막 프레임 이동 실패: {e}")
            return False

    def _find_actual_last_frame(self, reported_total):
        """실제 마지막 프레임을 찾습니다"""
        try:
            # 빠른 검색: 끝에서부터 역순으로 확인
            test_frames = [reported_total - 1, reported_total - 2, reported_total - 3, 
                          reported_total - 5, reported_total - 10, reported_total - 20]
            
            for test_frame in test_frames:
                if test_frame < 0:
                    continue
                    
                self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, test_frame)
                ret, frame = self.cap_a.read()
                if ret and frame is not None:
                    print(f"실제 마지막 프레임 발견: {test_frame}")
                    return test_frame
            
            # 빠른 검색 실패 시 순차적 검색 (더 느리지만 확실함)
            print("빠른 검색 실패, 순차적 검색 시작")
            self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, 0)
            
            last_valid_frame = -1
            for i in range(min(reported_total, 10000)):  # 최대 10000프레임까지만 검색
                ret, frame = self.cap_a.read()
                if ret and frame is not None:
                    last_valid_frame = i
                else:
                    break
            
            print(f"순차적 검색 결과: {last_valid_frame}")
            return last_valid_frame
            
        except Exception as e:
            print(f"실제 마지막 프레임 검색 실패: {e}")
            return -1

    def _update_ui_for_last_frame(self, actual_total_frames):
        """마지막 프레임에 대한 UI 업데이트"""
        self.videoWidget.updateFrame(self.frame_a, self.frame_b)
        
        # 오른쪽 끝 드래그 시 Current frame을 Total frame과 정확히 일치시킴
        # OpenCV가 보고하는 총 프레임 수를 사용
        reported_total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
        self.labelFrameCount.setText(f'Current: {reported_total_frames}')
        
        # 스크롤바를 최대값으로 설정
        self.positionScroll.blockSignals(True)
        self.positionScroll.setValue(self.positionScroll.maximum())
        self.positionScroll.blockSignals(False)
        
        # 오버레이 슬라이더도 최대값으로 설정
        if hasattr(self, 'overlaySlider'):
            self.overlaySlider.blockSignals(True)
            self.overlaySlider.setValue(reported_total_frames - 1)
            self.overlaySlider.blockSignals(False)
        
        # 오버레이 현재 프레임 라벨 업데이트
        if hasattr(self, 'overlayCurrentFrameLabel'):
            self.overlayCurrentFrameLabel.setText(f'{reported_total_frames}')
        
        # 시작 프레임 라벨도 업데이트
        if hasattr(self, 'overlayStartFrameLabel'):
            self.overlayStartFrameLabel.setText(f'{reported_total_frames}')
        
        # 전체 프레임 정보 업데이트 - OpenCV가 보고하는 총 프레임 수 사용
        feet_display = self.get_feet_display(reported_total_frames)
        total_frames_text = f'Total: {reported_total_frames} {feet_display}'
        if self.videoWidget.wipeEnabled and self.cap_b:
            total_frames_b = int(self.cap_b.get(cv2.CAP_PROP_FRAME_COUNT))
            feet_display_b = self.get_feet_display(total_frames_b)
            total_frames_text = f'Total A: {reported_total_frames} {feet_display}, B: {total_frames_b} {feet_display_b}'
        self.labelTotalFrames.setText(total_frames_text)
        
        # 시간 정보 업데이트
        original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
        if original_fps > 0:
            current_time = (reported_total_frames - 1) / original_fps if reported_total_frames > 1 else 0
            total_time = (reported_total_frames - 1) / original_fps if reported_total_frames > 1 else 0
            self.timeLabel.setText(f"{self.format_time(current_time)} / {self.format_time(total_time)}")
        
        self.update_frame()

    def _seek_conservative(self, target_frame_idx, total_frames):
        """보수적인 프레임 이동 방법 - 마지막 프레임 근처에서 사용"""
        try:
            current_pos = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES))
            if target_frame_idx > current_pos:
                for i in range(current_pos, target_frame_idx + 1):
                    ret_a, frame_a = self.cap_a.read()
                    if ret_a and frame_a is not None:
                        if i == target_frame_idx:
                            self.frame_a = self.process_frame(frame_a)
                            self._update_ui_after_seek(target_frame_idx, total_frames)
                            return True
                    else:
                        break
            elif target_frame_idx < current_pos:
                start_frame = max(0, target_frame_idx - 10)
                self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                for i in range(start_frame, target_frame_idx + 1):
                    ret_a, frame_a = self.cap_a.read()
                    if ret_a and frame_a is not None:
                        if i == target_frame_idx:
                            self.frame_a = self.process_frame(frame_a)
                            self._update_ui_after_seek(target_frame_idx, total_frames)
                            return True
                    else:
                        break
            return False
        except Exception as e:
            return False

    def _seek_direct(self, target_frame_idx, total_frames):
        """직접 프레임 이동을 시도합니다. 빠른 반응을 위해 사용됩니다."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 마지막 프레임 근처에서는 보수적으로 접근
                if target_frame_idx >= total_frames - 5:
                    # 마지막 5프레임 근처에서는 이전 프레임부터 시작
                    start_frame = max(0, target_frame_idx - 5)
                    self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                    
                    # 목표 프레임까지 순차적으로 읽기
                    for i in range(start_frame, target_frame_idx + 1):
                        ret_a, frame_a = self.cap_a.read()
                        if ret_a and frame_a is not None:
                            if i == target_frame_idx:
                                self.frame_a = self.process_frame(frame_a)
                                
                                # B 동기화
                                if self.cap_b and self.videoWidget.wipeEnabled:
                                    self.cap_b.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                                    for j in range(start_frame, target_frame_idx + 1):
                                        ret_b, frame_b = self.cap_b.read()
                                        if ret_b and frame_b is not None:
                                            if j == target_frame_idx:
                                                self.frame_b = self.process_frame(frame_b)
                                                break
                                        else:
                                            break
                                
                                # UI 업데이트
                                self._update_ui_after_seek(target_frame_idx, total_frames)
                                return True
                        else:
                            break
                    return False
                else:
                    # 일반적인 경우 직접 프레임 이동
                    self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
                    
                    # 프레임 읽기
                    ret_a, frame_a = self.cap_a.read()
                    if ret_a and frame_a is not None:
                        self.frame_a = self.process_frame(frame_a)
                        
                        # B 동기화
                        if self.cap_b and self.videoWidget.wipeEnabled:
                            self.cap_b.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
                            ret_b, frame_b = self.cap_b.read()
                            if ret_b and frame_b is not None:
                                self.frame_b = self.process_frame(frame_b)
                        
                        # UI 업데이트
                        self._update_ui_after_seek(target_frame_idx, total_frames)
                        return True
                    else:
                        # 프레임 읽기 실패 시 다음 프레임 시도
                        if attempt < max_retries - 1:
                            target_frame_idx += 1
                            continue
                        else:
                            print("직접 프레임 읽기 실패")
                            return False
                        
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"직접 프레임 이동 실패: {e}")
                    return False
                continue
        
        return False

    def _seek_sequential(self, target_frame_idx, total_frames):
        """순차적 프레임 읽기를 사용하여 목표 프레임으로 이동합니다."""
        print("순차적 프레임 읽기 사용")
        self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, 0)
        
        found = False
        for i in range(target_frame_idx + 1):
            ret_a, frame_a = self.cap_a.read()
            if ret_a and frame_a is not None:
                if i == target_frame_idx:
                    print(f"순차적 읽기로 프레임 {i} 찾음")
                    self.frame_a = self.process_frame(frame_a)
                    found = True
                    break
            else:
                print(f"순차적 읽기 실패 at {i}")
                break

        if found:
            # B 동기화
            if self.cap_b and self.videoWidget.wipeEnabled:
                self.cap_b.set(cv2.CAP_PROP_POS_FRAMES, 0)
                for i in range(target_frame_idx + 1):
                    ret_b, frame_b = self.cap_b.read()
                    if ret_b and frame_b is not None:
                        if i == target_frame_idx:
                            self.frame_b = self.process_frame(frame_b)
                            break
                    else:
                        break
            
            self._update_ui_after_seek(target_frame_idx, total_frames)
        else:
            print(f"프레임을 찾지 못했습니다: {target_frame_idx}")

    def _update_ui_after_seek(self, frame_idx, total_frames):
        """프레임 이동 후 UI를 업데이트합니다."""
        # B 키 오버레이 적용
        frame_a_to_show = self.frame_a
        if hasattr(self, "prepare_frame_for_display"):
            frame_a_to_show = self.prepare_frame_for_display(self.frame_a)
        elif frame_a_to_show is not None and self.show_overlay:
            frame_a_to_show = self.frame_a.copy()
            self.overlay_text(frame_a_to_show)
        
        # 드래그 중이거나 B 프레임이 없으면 B 프레임을 표시하지 않음
        frame_b_to_show = None
        if not self.is_dragging and self.frame_b is not None and (self.videoWidget.wipe_enabled_x or self.videoWidget.wipe_enabled_y):
            frame_b_to_show = self.frame_b
        
        # 비디오 프레임 업데이트
        self.videoWidget.updateFrame(frame_a_to_show, frame_b_to_show)
        if hasattr(self, "refresh_frame_annotations_display"):
            self.refresh_frame_annotations_display()
        
        # 실제 프레임 위치 확인
        actual_frame_pos = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES))
        
        # 프레임 정보 업데이트 - 실제 프레임 위치 사용
        current_frame_num = actual_frame_pos + 1
        self.labelFrameCount.setText(f'Current: {current_frame_num}')
        
        # 드래그 중이 아닐 때만 전체 프레임 정보 업데이트
        if not self.positionScroll.isSliderDown():
            feet_display = self.get_feet_display(total_frames)
            total_frames_text = f'Total: {total_frames} {feet_display}'
            if self.videoWidget.wipeEnabled and self.cap_b:
                total_frames_b = int(self.cap_b.get(cv2.CAP_PROP_FRAME_COUNT))
                feet_display_b = self.get_feet_display(total_frames_b)
                total_frames_text = f'Total A: {total_frames} {feet_display}, B: {total_frames_b} {feet_display_b}'
            self.labelTotalFrames.setText(total_frames_text)
        
        # 시간 정보 업데이트
        original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
        if original_fps > 0:
            current_time = (actual_frame_pos - 1) / original_fps if actual_frame_pos > 0 else 0
            total_time = (total_frames - 1) / original_fps if total_frames > 1 else 0
            self.timeLabel.setText(f"{self.format_time(current_time)} / {self.format_time(total_time)}")
        
        # 오버레이 슬라이더 업데이트
        if hasattr(self, 'overlaySlider'):
            self.overlaySlider.blockSignals(True)
            self.overlaySlider.setValue(frame_idx)
            self.overlaySlider.blockSignals(False)
        
        # 오버레이 현재 프레임 라벨 업데이트
        if hasattr(self, 'overlayCurrentFrameLabel'):
            self.overlayCurrentFrameLabel.setText(f'{frame_idx + 1}')
        
        # 시작 프레임 라벨도 업데이트
        if hasattr(self, 'overlayStartFrameLabel'):
            self.overlayStartFrameLabel.setText(f'{frame_idx + 1}')
        
        # 드래그 중이 아닐 때만 추가 업데이트
        if not self.positionScroll.isSliderDown():
            self.update_frame()

    def sync_audio_on_release(self):
        if self.cap_a:
            # 드래그가 끝났을 때 정확한 위치로 조정
            total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
            current_scroll_value = self.positionScroll.value()
            
            # 오른쪽 끝에 가까우면 마지막 프레임으로 설정
            if current_scroll_value >= self.positionScroll.maximum() - 1:
                print("드래그 완료: 오른쪽 끝 - 마지막 프레임으로 설정")
                self._seek_to_last_frame(total_frames)
            else:
                target_frame_idx = round((current_scroll_value / self.positionScroll.maximum()) * (total_frames - 1))
                target_frame_idx = max(0, min(target_frame_idx, total_frames - 1))
                
                # 현재 실제 프레임 위치 확인
                actual_frame_idx = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                if actual_frame_idx < 0:
                    actual_frame_idx = 0
                
                # 오차가 크면 순차적 읽기로 정확한 위치로 조정
                if abs(actual_frame_idx - target_frame_idx) > 5:
                    print(f"드래그 완료: 정확한 위치로 조정 {actual_frame_idx} -> {target_frame_idx}")
                    self._seek_sequential(target_frame_idx, total_frames)
            
            # 개선된 오디오 동기화 - 동적 오프셋 계산
            original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
            if original_fps > 0:
                current_frame_idx = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                if current_frame_idx < 0:
                    current_frame_idx = 0
                
                # 영상 길이에 따른 동적 오프셋 계산
                video_duration = total_frames / original_fps
                dynamic_offset = self._calculate_audio_offset(video_duration, current_frame_idx, original_fps)
                
                # 오디오 위치 설정 (음수 방지)
                audio_position = max(0, round(current_frame_idx / original_fps * 1000) - dynamic_offset)
                # 더 부드러운 동기화 (지연 시간 증가)
                QTimer.singleShot(5, lambda: self.set_media_position(audio_position))
                print(f"오디오 동기화: 프레임 {current_frame_idx}, 위치 {audio_position}ms, 오프셋 {dynamic_offset}ms")

    def _calculate_audio_offset(self, video_duration, current_frame, fps):
        """영상 길이와 현재 프레임에 따른 동적 오디오 오프셋 계산"""
        # 기본 오프셋 (짧은 영상용) - 더 작게
        base_offset = 20
        
        # 영상 길이에 따른 오프셋 조정
        if video_duration > 300:  # 5분 이상
            # 긴 영상에서는 더 큰 오프셋 사용
            duration_factor = min(video_duration / 300, 1.5)  # 최대 1.5배로 감소
            base_offset = int(20 * duration_factor)
        elif video_duration > 60:  # 1분 이상
            # 중간 길이 영상
            base_offset = 40
        
        # 현재 프레임 위치에 따른 미세 조정
        frame_progress = current_frame / (video_duration * fps)
        if frame_progress > 0.8:  # 영상 후반부
            base_offset += 10
        elif frame_progress < 0.2:  # 영상 초반부
            base_offset -= 3
            
        return max(0, base_offset)

    def _smooth_audio_sync(self, target_position, current_position):
        """점진적으로 오디오 위치를 조정하여 끊김 방지"""
        if abs(target_position - current_position) < 100:  # 차이가 작으면 즉시 조정
            QTimer.singleShot(1, lambda: self.set_media_position(target_position))
        else:
            # 큰 차이는 더 점진적으로 조정
            steps = 5  # 3에서 5로 증가
            step_size = (target_position - current_position) / steps
            for i in range(1, steps + 1):
                intermediate_pos = current_position + (step_size * i)
                QTimer.singleShot(i * 3, lambda pos=intermediate_pos: self.set_media_position(int(pos)))  # 2에서 3으로 증가

    def update_position_info(self):
        if self.cap_a and self.cap_a.isOpened():
            # 스크롤바 드래그 중일 때는 스크롤바 업데이트를 건너뜀
            if self.positionScroll.isSliderDown():
                return
                
            total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
            # 다음 읽을 프레임 인덱스(0-based)를 현재 프레임 번호(1-based)로 변환
            current_frame_num = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES))
            
            # 오른쪽 끝에 정확히 있을 때만 Total frame과 일치하도록 표시
            current_scroll_value = self.positionScroll.value()
            if current_scroll_value == self.positionScroll.maximum():
                print(f"update_position_info: 정확한 오른쪽 끝 감지, Current={total_frames}로 강제 설정")
                self.labelFrameCount.setText(f'Current: {total_frames}')
            else:
                self.labelFrameCount.setText(f'Current: {current_frame_num}')

            if total_frames > 1:
                scroll_val = round(((current_frame_num - 1) / (total_frames - 1)) * self.positionScroll.maximum())
                if scroll_val != self.positionScroll.value():
                    self.positionScroll.blockSignals(True)
                    self.positionScroll.setValue(scroll_val)
                    self.positionScroll.blockSignals(False)
                
                # 오버레이 슬라이더도 함께 업데이트
                if hasattr(self, 'overlaySlider'):
                    overlay_val = current_frame_num - 1
                    if overlay_val != self.overlaySlider.value():
                        self.overlaySlider.blockSignals(True)
                        self.overlaySlider.setValue(overlay_val)
                        self.overlaySlider.blockSignals(False)
                
                # 오버레이 현재 프레임 라벨 업데이트
                if hasattr(self, 'overlayCurrentFrameLabel'):
                    self.overlayCurrentFrameLabel.setText(f'{current_frame_num}')
                
                # 시작 프레임 라벨도 업데이트
                if hasattr(self, 'overlayStartFrameLabel'):
                    self.overlayStartFrameLabel.setText(f'{current_frame_num}')
            
            # --- 피트 표시 포함 Total 프레임 표시 ---
            feet_display = self.get_feet_display(total_frames)
            total_frames_text = f'Total: {total_frames} {feet_display}'
            if self.videoWidget.wipeEnabled and self.cap_b:
                total_frames_b = int(self.cap_b.get(cv2.CAP_PROP_FRAME_COUNT))
                feet_display_b = self.get_feet_display(total_frames_b)
                total_frames_text = f'Total A: {total_frames} {feet_display}, B: {total_frames_b} {feet_display_b}'
            self.labelTotalFrames.setText(total_frames_text)
            # --- 피트 표시 끝 ---

            # 비디오의 원래 FPS를 사용하여 시간 계산
            original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
            if original_fps > 0:
                # 오른쪽 끝에 정확히 있을 때만 Total frame 기준으로 시간 계산
                if current_scroll_value == self.positionScroll.maximum():
                    current_time = (total_frames - 1) / original_fps if total_frames > 1 else 0
                else:
                    current_time = (current_frame_num - 1) / original_fps if current_frame_num > 0 else 0
                total_time = (total_frames - 1) / original_fps if total_frames > 1 else 0
                self.timeLabel.setText(f"{self.format_time(current_time)} / {self.format_time(total_time)}")

    def format_time(self, seconds):
        if seconds < 0: seconds = 0
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"

    def get_frame_rate(self):
        try:
            return float(self.frameRateComboBox.currentText().strip())
        except (ValueError, TypeError):
            if self.cap_a:
                fps = self.cap_a.get(cv2.CAP_PROP_FPS)
                return fps if fps > 0 else 24.0
            return 24.0

    def get_feet_display(self, total_frames):
        """프레임 수를 피트로 변환하여 표시 형식으로 반환"""
        try:
            sheet_length = FrameCalculator.calculate_sheet_length(total_frames)
            feet_display = FrameCalculator.format_feet_display(sheet_length)
            return f"({feet_display})"
        except:
            return "(0F 00f)"

    def next_frame_playback(self):
        if not self.cap_a or not self.timer.isActive(): 
            return
            
        # 재생 중 주기적 오디오 동기화 (긴 영상에서 누적 오차 방지)
        current_frame = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        if current_frame < 0:
            current_frame = 0
            
        # 주기적 오디오 동기화 (더 부드럽게)
        if hasattr(self, '_sync_counter'):
            self._sync_counter += 1
        else:
            self._sync_counter = 0
            
        # 매 180프레임마다 동기화 (훨씬 적게)
        if self._sync_counter >= 180:
            self._sync_counter = 0
            # 재생 중일 때만 동기화 (재생기를 만든 적이 없으면 소리도 재생 중이 아님)
            media_player = self._media_player
            if media_player is not None and media_player.state() == QMediaPlayer.PlayingState:
                original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
                if original_fps > 0:
                    total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
                    video_duration = total_frames / original_fps
                    dynamic_offset = self._calculate_audio_offset(video_duration, current_frame, original_fps)
                    audio_position = max(0, round(current_frame / original_fps * 1000) - dynamic_offset)
                    
                    # 현재 오디오 위치와 차이가 클 때만 동기화 (임계값 더 증가)
                    current_audio_pos = media_player.position()
                    if abs(audio_position - current_audio_pos) > 400:  # 250ms에서 400ms로 증가
                        # 더 부드러운 동기화를 위해 점진적 조정
                        self._smooth_audio_sync(audio_position, current_audio_pos)
                        print(f"부드러운 동기화: 프레임 {current_frame}, 오디오 위치 {audio_position}ms (차이: {audio_position - current_audio_pos}ms)")
            
        ret_a, frame_a = self.cap_a.read()
        if ret_a:
            self.frame_a = self.process_frame(frame_a)
            if self.cap_b and self.videoWidget.wipeEnabled:
                ret_b, frame_b = self.cap_b.read()
                self.frame_b = self.process_frame(frame_b) if ret_b else None
            self.update_frame()
        else:
            print("Video end detected in next_frame_playback")
            self.handle_video_end()

    def next_frame(self):
        if not self.cap_a: 
            return
            
        total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 1:
            return
            
        # 실제 현재 프레임 위치 가져오기 (CAP_PROP_POS_FRAMES는 다음 읽을 프레임)
        current_frame_idx = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        if current_frame_idx < 0:
            current_frame_idx = 0
        
        print(f"next_frame: 실제 현재 프레임 = {current_frame_idx}")
        
        # 다음 프레임으로 이동 - 범위 제한 강화
        next_frame_idx = min(current_frame_idx + 1, total_frames - 1)
        next_frame_idx = max(0, next_frame_idx)  # 음수 방지
        
        # 추가 안전장치: 음수나 범위를 벗어나는 경우 처리
        if next_frame_idx < 0 or next_frame_idx >= total_frames:
            print(f"Next frame: 잘못된 프레임 인덱스 {next_frame_idx}, 현재 위치 유지")
            return
        
        # 현재 위치와 동일하면 이동하지 않음
        if next_frame_idx == current_frame_idx:
            print(f"Next frame: 이미 마지막 프레임입니다 ({current_frame_idx})")
            return
        
        print(f"Next frame: {current_frame_idx} -> {next_frame_idx}")
        
        # 효율적인 프레임 이동 - 직접 프레임 설정 시도
        if self._seek_direct_fast(next_frame_idx, total_frames):
            print(f"Next frame {next_frame_idx} 직접 이동 성공")
        else:
            # 실패 시 순차적 읽기로 폴백
            print(f"Next frame {next_frame_idx} 직접 이동 실패, 순차적 읽기로 폴백")
            self._seek_sequential_fast(next_frame_idx, total_frames)

    def prev_frame(self):
        if not self.cap_a: 
            return
            
        total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 1:
            return
            
        # 실제 현재 프레임 위치 가져오기 (CAP_PROP_POS_FRAMES는 다음 읽을 프레임)
        current_frame_idx = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        if current_frame_idx < 0:
            current_frame_idx = 0
        
        print(f"prev_frame: 실제 현재 프레임 = {current_frame_idx}")
        
        # 이전 프레임으로 이동 - 범위 제한 강화
        prev_frame_idx = max(current_frame_idx - 1, 0)  # 음수 방지
        prev_frame_idx = min(prev_frame_idx, total_frames - 1)  # 최대값 제한
        
        # 추가 안전장치: 음수나 범위를 벗어나는 경우 처리
        if prev_frame_idx < 0 or prev_frame_idx >= total_frames:
            print(f"Prev frame: 잘못된 프레임 인덱스 {prev_frame_idx}, 현재 위치 유지")
            return
        
        # 현재 위치와 동일하면 이동하지 않음
        if prev_frame_idx == current_frame_idx:
            print(f"Prev frame: 이미 첫 번째 프레임입니다 ({current_frame_idx})")
            return
        
        print(f"Prev frame: {current_frame_idx} -> {prev_frame_idx}")
        
        # 최적화된 이전 프레임 이동
        if self._seek_prev_frame_optimized(prev_frame_idx, total_frames):
            print(f"Prev frame {prev_frame_idx} 최적화 이동 성공")
        else:
            # 실패 시 기존 방법으로 폴백
            print(f"Prev frame {prev_frame_idx} 최적화 실패, 기존 방법으로 폴백")
            if self._seek_direct_fast(prev_frame_idx, total_frames):
                print(f"Prev frame {prev_frame_idx} 직접 이동 성공")
            else:
                self._seek_sequential_fast(prev_frame_idx, total_frames)

    def _seek_prev_frame_optimized(self, target_frame_idx, total_frames):
        """이전 프레임 이동 최적화 - 직접 프레임 설정 우선"""
        try:
            # 이전 프레임은 항상 직접 프레임 설정이 가장 빠름
            self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
            ret_a, frame_a = self.cap_a.read()
            if ret_a and frame_a is not None:
                self.frame_a = self.process_frame(frame_a)
                self._update_ui_fast(target_frame_idx, total_frames)
                return True
            return False
            
        except Exception as e:
            print(f"이전 프레임 최적화 이동 실패: {e}")
            return False

    def _seek_direct_fast(self, target_frame_idx, total_frames):
        """빠른 직접 프레임 이동 - 단축키용"""
        try:
            # 현재 위치 정확히 계산 (CAP_PROP_POS_FRAMES는 다음 읽을 프레임)
            current_pos = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            if current_pos < 0:
                current_pos = 0
            
            print(f"_seek_direct_fast: 현재위치={current_pos}, 목표위치={target_frame_idx}")
                
            if abs(target_frame_idx - current_pos) <= 5:
                # 가까운 경우 현재 위치에서 순차적 읽기
                if target_frame_idx > current_pos:
                    # 앞으로 이동 - 현재 위치에서 시작하여 목표까지 읽기
                    frames_to_read = target_frame_idx - current_pos
                    for _ in range(frames_to_read + 1):
                        ret_a, frame_a = self.cap_a.read()
                        if ret_a and frame_a is not None:
                            current_pos += 1
                            if current_pos == target_frame_idx:
                                self.frame_a = self.process_frame(frame_a)
                                self._update_ui_fast(target_frame_idx, total_frames)
                                return True
                        else:
                            break
                else:
                    # 뒤로 이동하는 경우 - 최적화된 방법
                    frames_to_go_back = current_pos - target_frame_idx
                    if frames_to_go_back <= 10:
                        # 가까운 경우 현재 위치에서 뒤로 읽기 (캐시 활용)
                        # 현재 위치에서 목표 위치까지 다시 읽기
                        self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
                        ret_a, frame_a = self.cap_a.read()
                        if ret_a and frame_a is not None:
                            self.frame_a = self.process_frame(frame_a)
                            self._update_ui_fast(target_frame_idx, total_frames)
                            return True
                    else:
                        # 먼 경우 직접 프레임 설정
                        self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
                        ret_a, frame_a = self.cap_a.read()
                        if ret_a and frame_a is not None:
                            self.frame_a = self.process_frame(frame_a)
                            self._update_ui_fast(target_frame_idx, total_frames)
                            return True
            else:
                # 먼 경우 직접 프레임 설정
                self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
                ret_a, frame_a = self.cap_a.read()
                if ret_a and frame_a is not None:
                    self.frame_a = self.process_frame(frame_a)
                    self._update_ui_fast(target_frame_idx, total_frames)
                    return True
                    
            return False
            
        except Exception as e:
            print(f"빠른 직접 프레임 이동 실패: {e}")
            return False

    def _seek_sequential_fast(self, target_frame_idx, total_frames):
        """빠른 순차적 프레임 읽기 - 단축키용"""
        try:
            # 현재 위치에서 시작하여 목표 프레임까지 읽기
            current_pos = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            if current_pos < 0:
                current_pos = 0
            
            print(f"_seek_sequential_fast: 현재위치={current_pos}, 목표위치={target_frame_idx}")
                
            if target_frame_idx >= current_pos:
                # 앞으로 이동하는 경우
                frames_to_read = target_frame_idx - current_pos
                for _ in range(frames_to_read + 1):
                    ret_a, frame_a = self.cap_a.read()
                    if ret_a and frame_a is not None:
                        if current_pos == target_frame_idx:
                            self.frame_a = self.process_frame(frame_a)
                            self._update_ui_fast(target_frame_idx, total_frames)
                            return True
                        current_pos += 1
                    else:
                        break
            else:
                # 뒤로 이동하는 경우 - 최적화된 방법
                frames_to_go_back = current_pos - target_frame_idx
                if frames_to_go_back <= 10:
                    # 가까운 경우 직접 프레임 설정이 더 빠름
                    self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
                    ret_a, frame_a = self.cap_a.read()
                    if ret_a and frame_a is not None:
                        self.frame_a = self.process_frame(frame_a)
                        self._update_ui_fast(target_frame_idx, total_frames)
                        return True
                else:
                    # 먼 경우에도 직접 프레임 설정이 더 효율적
                    self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, target_frame_idx)
                    ret_a, frame_a = self.cap_a.read()
                    if ret_a and frame_a is not None:
                        self.frame_a = self.process_frame(frame_a)
                        self._update_ui_fast(target_frame_idx, total_frames)
                        return True
                        
            return False
            
        except Exception as e:
            print(f"빠른 순차적 프레임 읽기 실패: {e}")
            return False

    def _update_ui_fast(self, frame_idx, total_frames):
        """빠른 UI 업데이트 - 단축키용 (오버레이 반영)"""
        # 프레임 범위 체크 강화
        frame_idx = max(0, min(frame_idx, total_frames - 1))
        
        # 오버레이 반영
        frame_a_to_show = self.frame_a
        if hasattr(self, "prepare_frame_for_display"):
            frame_a_to_show = self.prepare_frame_for_display(self.frame_a)
        elif frame_a_to_show is not None and self.show_overlay:
            frame_a_to_show = self.frame_a.copy()
            self.overlay_text(frame_a_to_show)
        frame_b_to_show = self.frame_b if (self.videoWidget.wipe_enabled_x or self.videoWidget.wipe_enabled_y) else None
        self.videoWidget.updateFrame(frame_a_to_show, frame_b_to_show)
        if hasattr(self, "refresh_frame_annotations_display"):
            self.refresh_frame_annotations_display()
        
        # 프레임 라벨 직접 업데이트 (중복 방지)
        current_frame_num = frame_idx + 1
        self.labelFrameCount.setText(f'Current: {current_frame_num}')
        
        # 스크롤바 업데이트
        if total_frames > 1:
            scroll_val = round((frame_idx / (total_frames - 1)) * self.positionScroll.maximum())
            scroll_val = max(0, min(scroll_val, self.positionScroll.maximum()))
            self.positionScroll.blockSignals(True)
            self.positionScroll.setValue(scroll_val)
            self.positionScroll.blockSignals(False)
        
        # 시간 정보 업데이트
        original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
        if original_fps > 0:
            current_time = frame_idx / original_fps
            total_time = (total_frames - 1) / original_fps if total_frames > 1 else 0
            self.timeLabel.setText(f"{self.format_time(current_time)} / {self.format_time(total_time)}")

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        text = event.text()
        
        # 앱이 활성화되어 있지 않으면 포커스 강제 설정
        if not self.isActiveWindow():
            self.force_focus()
        
        # V 키 처리 (한글 ㅍ과 영문 V 모두 지원)
        if key == Qt.Key_V or text == 'ㅍ':
            self.controls_visible = not self.controls_visible
            print(f"V key pressed (key: {key}, text: '{text}') - controls_visible: {self.controls_visible}")  # 디버깅 출력
            valid_widgets = self.get_valid_control_widgets()
            for widget in valid_widgets:
                try:
                    widget.setVisible(self.controls_visible)
                except (RuntimeError, AttributeError):
                    continue
            # 컨트롤이 숨겨지면 오버레이를 표시하고, 컨트롤이 보이면 오버레이를 숨김
            if hasattr(self, 'overlayFrame'):
                if not self.controls_visible:
                    print("Showing overlay controls")  # 디버깅 출력
                    # 오버레이를 강제로 표시
                    self.overlayFrame.setVisible(True)
                    self.overlayFrame.raise_()
                    self.show_overlay_controls()
                else:
                    print("Hiding overlay controls")  # 디버깅 출력
                    self.hide_overlay_controls()
            QTimer.singleShot(100, self.force_focus)  # V키 후 포커스 복원
            event.accept()
            return
        
        # 한글 자판 대응 단축키 매핑 (V 키 제외)
        # T-ㅅ, B-ㅠ, F-ㄹ, R-ㄱ
        # ㅅ: '\u3145', ㅠ: '\u315C', ㄹ: '\u3139', ㄱ: '\u3131'
        if text in ['ㅅ', 'ㅠ', 'ㄹ', 'ㄱ']:
            if text == 'ㅅ':  # T
                self.toggle_theme()
                event.accept()
                return
            elif text == 'ㅠ':  # B
                self.show_overlay = not self.show_overlay
                self.update_frame()
                self.activateWindow()  # 윈도우를 활성화
                self.setFocus(Qt.OtherFocusReason)  # 포커스를 메인 윈도우로 강제 이동
                # 모든 위젯의 포커스를 해제
                for widget in self.control_widgets:
                    if hasattr(widget, 'clearFocus'):
                        widget.clearFocus()
                event.accept()
                return
            elif text == 'ㄹ':  # F
                if modifiers == Qt.ShiftModifier:
                    self.toggle_video_only_fullscreen()
                else:
                    self.toggle_fullscreen()
                event.accept()
                return
            elif text == 'ㄱ':  # R
                # 썸네일 재생성 단축키
                self.regenerate_selected_thumbnails()
                event.accept()
                return
        
        # 기존 영문 단축키 처리
        # Shift + F 단축키 처리 (더 정확한 감지)
        if key == Qt.Key_F:
            if modifiers == Qt.ShiftModifier:
                print("Shift + F detected!")  # 디버깅 출력 추가
                self.toggle_video_only_fullscreen()
                event.accept()
                return
            else:
                # 단독 F 키 처리
                self.toggle_fullscreen()
                event.accept()
                return
        elif key == Qt.Key_T:
            self.toggle_theme()
            event.accept()
            return
        elif key == Qt.Key_B: 
            self.show_overlay = not self.show_overlay; 
            self.update_frame()
        elif key in [Qt.Key_Comma, Qt.Key_Left]: 
            self.prev_frame()
        elif key in [Qt.Key_Period, Qt.Key_Right]: 
            self.next_frame()
        elif key == Qt.Key_Space: 
            self.toggle_play_pause()
        elif key in [Qt.Key_Plus, Qt.Key_Equal, Qt.Key_2]: 
            print("Zoom in triggered"); 
            # 마우스 커서 위치를 비디오 위젯 좌표로 변환하여 전달
            cursor_pos = self.videoWidget.mapFromGlobal(self.cursor().pos())
            self.videoWidget.zoom_in(cursor_pos)
        elif key in [Qt.Key_Minus, Qt.Key_1]: 
            print("Zoom out triggered"); 
            # 마우스 커서 위치를 비디오 위젯 좌표로 변환하여 전달
            cursor_pos = self.videoWidget.mapFromGlobal(self.cursor().pos())
            self.videoWidget.zoom_out(cursor_pos)
        elif key == Qt.Key_3: 
            self.videoWidget.reset_view()
        elif key == Qt.Key_4: 
            self.videoWidget.show_original_size()
        elif key == Qt.Key_R:
            # 썸네일 재생성 단축키
            self.regenerate_selected_thumbnails()
            event.accept()
            return
        # Ctrl+H는 eventFilter에서 처리하므로 여기서는 제거
        else: 
            super().keyPressEvent(event)

    def toggle_video_only_fullscreen(self):
        """동영상만 전체화면에 표시하는 모드 전환"""
        print(f"toggle_video_only_fullscreen called, current state: {getattr(self, 'video_only_fullscreen', False)}")
        
        if not hasattr(self, 'video_only_fullscreen'):
            self.video_only_fullscreen = False
            self.previous_ui_state = {}
        
        if self.video_only_fullscreen:
            print("Exiting video-only fullscreen mode")
            # 동영상 전용 전체화면 모드 해제
            self.exit_video_only_fullscreen()
        else:
            print("Entering video-only fullscreen mode")
            # 동영상 전용 전체화면 모드 진입
            self.enter_video_only_fullscreen()

    def enter_video_only_fullscreen(self):
        """동영상 전용 전체화면 모드 진입"""
        if not self.cap_a:
            return  # 비디오가 로드되지 않은 경우 무시
        
        try:
            # 현재 UI 상태 저장
            self.previous_ui_state = {
                'window_geometry': self.geometry(),
                'window_state': self.windowState(),
                'controls_visible': self.controls_visible
            }
            
            # 모든 UI 요소 숨기기
            self.hide_all_ui_elements()
            
            # 전체화면으로 설정
            self.showFullScreen()
            self.video_only_fullscreen = True
            
            # 비디오 위젯 크기 조정
            self.videoWidget.fit_to_window()
            
            # 오디오 동기화 유지
            if self.timer.isActive():
                original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
                if original_fps > 0:
                    current_frame = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                    if current_frame < 0:
                        current_frame = 0
                    # 오디오를 약간 앞당기기 위해 50ms 오프셋 추가
                    self.set_media_position(round(current_frame / original_fps * 1000) - 50)
            
            # V 키 모드 진입 시 오버레이 컨트롤러 표시
            if hasattr(self, 'overlayFrame') and not self.controls_visible:
                self.show_overlay_controls()
            
            # 포커스를 강제로 설정하여 키보드 이벤트가 정상 작동하도록 함
            QTimer.singleShot(100, self.force_focus)
            
            print("동영상 전용 전체화면 모드 진입")
        except Exception as e:
            print(f"동영상 전용 전체화면 모드 진입 실패: {e}")

    def exit_video_only_fullscreen(self):
        """동영상 전용 전체화면 모드 해제"""
        try:
            # 전체화면 해제
            self.showNormal()
            self.video_only_fullscreen = False
            
            # 앱 처음 실행 시의 창 크기로 복원
            if hasattr(self, 'initial_geometry'):
                self.setGeometry(self.initial_geometry)
            
            # 항상 일반 창 상태로 복원 (F 키 상태 무시)
            self.setWindowState(Qt.WindowNoState)
            self.isFullScreen = False
            self.fullscreenButton.setText('Full screen')
            
            # UI 요소 복원
            self.restore_ui_elements()
            
            # 비디오 위젯 크기 재조정
            self.videoWidget.fit_to_window()
            
            # 오디오 동기화 유지
            if self.timer.isActive():
                original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
                if original_fps > 0:
                    current_frame = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                    if current_frame < 0:
                        current_frame = 0
                    # 오디오를 약간 앞당기기 위해 50ms 오프셋 추가
                    self.set_media_position(round(current_frame / original_fps * 1000) - 50)
            
            # V 키 모드 해제 시 오버레이 컨트롤러 숨김
            if hasattr(self, 'overlayFrame'):
                self.hide_overlay_controls()
            
            print("동영상 전용 전체화면 모드 해제")
        except Exception as e:
            print(f"동영상 전용 전체화면 모드 해제 실패: {e}")
            # 실패 시 기본 상태로 복원
            try:
                self.showNormal()
                self.video_only_fullscreen = False
                self.restore_ui_elements()
            except:
                pass

    def hide_all_ui_elements(self):
        """모든 UI 요소를 숨깁니다"""
        # 메뉴바 숨기기
        if self.menuBar():
            self.menuBar().hide()
        
        # 상태바 숨기기
        if self.statusBar():
            self.statusBar().hide()
        
        # 툴바 숨기기
        for toolbar in self.findChildren(QWidget):
            if isinstance(toolbar, type(self.menuBar())):  # 툴바 타입 확인
                toolbar.hide()
        
        # 컨트롤 위젯들 숨기기
        valid_widgets = self.get_valid_control_widgets()
        for widget in valid_widgets:
            try:
                widget.hide()
            except (RuntimeError, AttributeError):
                continue

    def get_valid_control_widgets(self):
        """유효한 컨트롤 위젯들만 반환합니다"""
        valid_widgets = []
        if hasattr(self, 'control_widgets'):
            for widget in self.control_widgets:
                try:
                    if widget and hasattr(widget, 'setVisible'):
                        valid_widgets.append(widget)
                except (RuntimeError, AttributeError):
                    continue
        return valid_widgets

    def restore_ui_elements(self):
        """UI 요소를 복원합니다"""
        # 메뉴바 복원
        if self.menuBar():
            self.menuBar().show()
        
        # 상태바 복원
        if self.statusBar():
            self.statusBar().show()
        
        # 툴바 복원
        for toolbar in self.findChildren(QWidget):
            if isinstance(toolbar, type(self.menuBar())):  # 툴바 타입 확인
                toolbar.show()
        
        # 컨트롤 위젯들 상태 복원 - 안전하게 처리
        valid_widgets = self.get_valid_control_widgets()
        for widget in valid_widgets:
            try:
                widget.setVisible(self.controls_visible)
            except (RuntimeError, AttributeError):
                continue

    def wheelEvent(self, event):
        """전역 휠 이벤트 처리 - 사이드바를 제외한 모든 영역에서 프레임 이동"""
        # 사이드바 영역에서는 휠 이벤트를 무시
        if self.sidebar.underMouse():
            event.ignore()
            return
            
        # 비디오가 로드되지 않은 경우 무시
        if not self.cap_a:
            event.ignore()
            return
            
        delta = event.angleDelta().y()
        frame_step = 1  # 3에서 1로 변경
        
        # CAP_PROP_POS_FRAMES는 다음 읽을 프레임의 0-based 인덱스
        current_frame_idx = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        if current_frame_idx < 0:
            current_frame_idx = 0
        
        if delta < 0:  # 휠 다운 (이전)
            target_frame_idx = max(0, current_frame_idx - frame_step)
        else:  # 휠 업 (다음)
            total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
            target_frame_idx = min(total_frames - 1, current_frame_idx + frame_step)
        
        # 프레임 이동
        self.seek_to_frame(target_frame_idx + 1)  # seek_to_frame은 1-based
        event.accept()

    def handle_video_end(self):
        print(f"handle_video_end called - is_playlist_playing: {self.is_playlist_playing}")
        self.timer.stop()
        
        if self.is_playlist_playing: 
            print("Current video ended, moving to next in playlist")
            self.play_next_in_playlist()
        elif self.loopEnabled:
            print("Loop enabled, restarting current video")
            self.seek_to_frame(1)
            self.play_video()
        else:
            print("Video ended, stopping playback")
            self.stop_video()
            self.playPauseButton.setText('Play')
            self.playPauseButton.setStyleSheet("")

    def toggle_fullscreen(self):
        if self.isFullScreen:
            self.showNormal(); self.isFullScreen = False
            self.fullscreenButton.setText('Full screen')
        else:
            self.showFullScreen(); self.isFullScreen = True
            self.fullscreenButton.setText('Exit Full screen')

    def toggle_loop_play(self, state):
        self.loopEnabled = state == Qt.Checked

    def play_video(self):
        if not self.timer.isActive() and self.cap_a:
            current_frame = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES))
            total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
            if current_frame >= total_frames: 
                self.seek_to_frame(1)
            # 비디오의 원래 FPS를 사용하여 재생 속도 설정
            original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
            if original_fps > 0: 
                # 개선된 타이머 설정 - 더 정확한 타이밍
                timer_interval = max(1, int(1000 / original_fps))
                self.timer.start(timer_interval)
                
                # 현재 프레임 위치를 비디오의 원래 FPS로 계산하여 오디오 동기화
                current_frame = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                if current_frame < 0:
                    current_frame = 0
                
                # 개선된 오디오 동기화 - 동적 오프셋 사용
                video_duration = total_frames / original_fps
                dynamic_offset = self._calculate_audio_offset(video_duration, current_frame, original_fps)
                audio_position = max(0, round(current_frame / original_fps * 1000) - dynamic_offset)  # 음수 방지
                # 재생 시작 시 즉시 동기화
                self.set_media_position(audio_position)
                
                print(f"재생 시작: 프레임 {current_frame}, 오디오 위치 {audio_position}ms, 오프셋 {dynamic_offset}ms")
                
            if self._media_player is not None:  # 영상 A를 열면(setMedia) 만들어져 있음
                self._media_player.play()
            self.playPauseButton.setText('Pause')
            self.playPauseButton.setStyleSheet("background-color: yellow;")
            
            # 동기화 카운터 초기화
            self._sync_counter = 0
            
            # 오버레이 재생 버튼도 업데이트
            if hasattr(self, 'overlayPlayPause'):
                self.overlayPlayPause.setText('⏸')  # 재생 중일 때 일시정지 아이콘
            
            print(f"play_video called - is_playlist_playing: {self.is_playlist_playing}")

    def pause_video(self):
        if self.timer.isActive():
            self.timer.stop()
            if self._media_player is not None:
                self._media_player.pause()
            self.playPauseButton.setText('Play')
            self.playPauseButton.setStyleSheet("")
            self.labelPlaybackFPS.setText('재생: 일시정지')
            
            # 오버레이 재생 버튼도 업데이트
            if hasattr(self, 'overlayPlayPause'):
                self.overlayPlayPause.setText('▶')  # 정지 상태일 때 재생 아이콘
            
            print(f"pause_video called - is_playlist_playing: {self.is_playlist_playing}")

    def stop_video(self):
        self.timer.stop(); self.stop_media_player()
        if self.cap_a: self.seek_to_frame(1)
        self.playPauseButton.setText('Play'); self.playPauseButton.setStyleSheet("")
        self.labelPlaybackFPS.setText('재생: 정지')
        
        # 오버레이 재생 버튼도 업데이트
        if hasattr(self, 'overlayPlayPause'):
            self.overlayPlayPause.setText('▶')  # 정지 상태일 때 재생 아이콘
        
        if self.is_playlist_playing:
            self.is_playlist_playing = False; self.reset_sidebar_colors()
        self.playSelectedPauseButton.setText('Selected Play'); self.playSelectedPauseButton.setStyleSheet("")

    def seek_to_frame(self, frame_number, update_audio=True):
        if not self.cap_a:
            return
            
        target_index = max(0, frame_number - 1)
        total_frames = int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # 비표준 해상도 파일을 위한 재시도 로직
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 프레임 위치 설정
                self.cap_a.set(cv2.CAP_PROP_POS_FRAMES, target_index)
                
                # 실제로 설정된 프레임 위치 확인
                actual_pos = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES))
                
                # 프레임 읽기
                ret_a, frame_a = self.cap_a.read()
                
                if ret_a and frame_a is not None:
                    self.frame_a = self.process_frame(frame_a)
                    
                    # 비디오 B도 동기화
                    if self.cap_b and self.videoWidget.wipeEnabled:
                        self.cap_b.set(cv2.CAP_PROP_POS_FRAMES, target_index)
                        ret_b, frame_b = self.cap_b.read()
                        self.frame_b = self.process_frame(frame_b) if ret_b else None
                    
                    # 개선된 오디오 동기화
                    if update_audio:
                        # 비디오의 원래 FPS를 사용하여 오디오 동기화
                        original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
                        if original_fps > 0:
                            # 동적 오프셋 계산
                            video_duration = total_frames / original_fps
                            dynamic_offset = self._calculate_audio_offset(video_duration, actual_pos, original_fps)
                            audio_position = max(0, round(actual_pos / original_fps * 1000) - dynamic_offset)  # 음수 방지
                            # 프레임 이동 시 부드러운 동기화 (지연 시간 증가)
                            QTimer.singleShot(3, lambda: self.set_media_position(audio_position))
                            print(f"프레임 이동: {actual_pos}, 오디오 위치 {audio_position}ms, 오프셋 {dynamic_offset}ms")
                    
                    self.update_frame()
                    break
                    
                else:
                    # 프레임 읽기 실패 시 다음 프레임 시도
                    if attempt < max_retries - 1:
                        target_index += 1
                        continue
                        
            except Exception as e:
                print(f"Seek attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    print(f"Failed to seek to frame {frame_number} after {max_retries} attempts")
                    break

    def setVolume(self, volume):
        # 재생기를 아직 만들지 않았으면 기억만 해 두고 만들 때 적용 (볼륨 때문에 만들지 않음)
        self._media_volume = volume
        if self._media_player is not None:
            self._media_player.setVolume(volume)
        # 볼륨 퍼센트 레이블 업데이트
        if hasattr(self, 'volumePercentLabel'):
            self.volumePercentLabel.setText(f"{volume}%")

    def on_fit_to_window_changed(self, is_fit):
        self.is_fit_to_window = is_fit

    def toggle_play_pause(self):
        if self.timer.isActive(): 
            self.pause_video()
        elif self.cap_a:
            # 플레이리스트 재생 중이 아닐 때만 일반 재생 모드로 설정
            if not self.is_playlist_playing:
                self.is_playlist_playing = False
            self.play_video()

    def toggle_play_pause_selected(self):
        if self.is_playlist_playing:
            if self.timer.isActive():
                self.pause_video(); self.playSelectedPauseButton.setText('Selected Play'); self.playSelectedPauseButton.setStyleSheet("")
            else:
                self.play_video(); self.playSelectedPauseButton.setText('Selected Pause'); self.playSelectedPauseButton.setStyleSheet("background-color: yellow;")
        else:
            self.play_selected_files()

    def toggle_wipe_effect(self, state):
        enabled = state == Qt.Checked
        self.videoWidget.toggleWipeEffect(enabled)
        self.wipeXButton.setEnabled(enabled)
        self.wipeYButton.setEnabled(enabled)
        if not enabled:
            self.wipeXButton.setChecked(False); self.wipeYButton.setChecked(False)
        self.update_frame()

    def toggle_wipe_x(self, checked):
        self.videoWidget.wipe_enabled_x = checked; self.update_frame()

    def toggle_wipe_y(self, checked):
        self.videoWidget.wipe_enabled_y = checked; self.update_frame()

    def show_video_info(self, index):
        file_path = self.sidebar.item(index.row()).toolTip()
        if not file_path: return
        msg_box = QMessageBox(self); msg_box.setWindowTitle("미디어 정보")
        try:
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened(): raise Exception("비디오 파일을 열 수 없습니다.")
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS); total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration_sec = (total_frames - 1) / fps if fps > 0 and total_frames > 1 else 0
            duration_str = self.format_time(duration_sec)
            codec = self.get_video_codec(file_path)
            msg = (f"**해상도:** {width} x {height}\n"
                   f"**코덱:** {codec}\n"
                   f"**길이:** {duration_str}\n"
                   f"**프레임:** {total_frames}\n"
                   f"**프레임 속도 (FPS):** {fps:.2f}\n"
                   f"**파일 경로:** {file_path}")
            cap.release()
        except Exception as e:
            msg = f"미디어 정보를 가져오는 데 실패했습니다: {e}"
        msg_box.setText(msg)
        msg_box.exec_()

    def show_help(self):
        """단축키 도움말을 표시합니다"""
        help_text = """
<h2>🎬 Yeson Video Player - 단축키 도움말</h2>

<h3>📁 파일 관리</h3>
• <b>드래그앤드롭</b>: 파일을 윈도우나 사이드바에 드래그하여 로드<br>
• <b>단일 파일</b>: Video A에 자동 로드<br>
• <b>두 개 파일</b>: Video A와 B에 각각 로드<br>
• <b>여러 파일</b>: 사이드바에 추가

<h3>▶️ 재생 제어</h3>
• <b>Space</b>: 재생/일시정지<br>
• <b>Enter</b>: 선택된 파일들 순차 재생<br>
• <b>\\</b>: 선택된 파일들 재생/일시정지<br>
• <b>← →</b>: 이전/다음 프레임<br>
• <b>마우스 휠</b>: 1프레임씩 이동

<h3>🔍 줌 및 뷰</h3>
• <b>+ / 2</b>: 마우스 커서 위치 중심으로 줌 인<br>
• <b>- / 1</b>: 마우스 커서 위치 중심으로 줌 아웃<br>
• <b>Ctrl + 휠</b>: 마우스 커서 위치 중심으로 줌 인/아웃<br>
• <b>3</b>: 화면에 맞춤<br>
• <b>4</b>: 원본 크기<br>
• <b>마우스 드래그</b>: 줌 상태에서 화면 이동

<h3>🖥️ 화면 모드</h3>
• <b>F</b>: 전체화면 전환 (UI 포함)<br>
• <b>Shift + F</b>: 동영상만 전체화면 (UI 숨김)<br>
• <b>V</b>: 컨트롤 패널 표시/숨김

<h3>🎛️ 테마 전환</h3>
• <b>T</b>: 테마 전환

<h3>📝 OCR 기능</h3>

<h4>▶ ROI 설정</h4>
• <b>OCR ROI 지정</b>: 동영상에서 텍스트 인식 영역을 드래그로 지정<br>
• <b>ROI 초기화</b>: 지정한 ROI 영역 제거<br>
• <b>ROI 트래킹</b>: 텍스트가 이동할 때 ROI가 자동으로 추적

<h4>▶ OCR 분석</h4>
• <b>분석 방식</b>: Titmouse(일반), King(빨간색 텍스트 최적화)<br>
• <b>OCR 구간 추출</b>: 전체 동영상 자동 인식 및 구간 분류<br>
• <b>선택 구간 분석</b>: 현재 프레임 범위만 분석하여 결과 병합

<h4>▶ 결과 관리</h4>
• <b>OCR 오픈</b>: 분석 결과 검토 창 열기<br>
• <b>OCR 저장</b>: JSON 파일로 결과 저장<br>
• <b>OCR 로드</b>: 저장된 결과 불러오기

<h4>▶ OCR 검토 창</h4>
• <b>D (ㅇ)</b>: 선택 구간 병합<br>
• <b>R (ㄱ)</b>: 전체 내보내기<br>
• <b>텍스트 편집</b>: ROI/편집 텍스트 직접 수정<br>
• <b>사운드 옵션</b>: 내보낼 때 오디오 포함 여부 선택

<h4>💡 OCR 팁</h4>
• 빨간색 텍스트는 King 모드 사용<br>
• 텍스트 이동 시 ROI 트래킹 활성화<br>
• 노란색 표시된 유사 구간은 병합 권장<br>
• 구간 길이는 프레임 단위로 표시

<h3>✏️ 수정 사항 주석</h3>
<p>영상 위에 “여기 고쳐주세요” 같은 메모를 그림·글자로 남기는 기능입니다.</p>

<h4>▶ 시작하기</h4>
• <b>Open Video A</b>로 동영상을 연 뒤, <b>▶ 수정 사항 주석</b> 칸을 펼칩니다<br>
• <b>주석 모드</b> 버튼을 켜면 그리기가 시작됩니다

<h4>▶ 그리는 방법</h4>
• <b>도구</b>: 텍스트 / 사각형 / 타원 / 선 / 화살표 중 선택<br>
• <b>색상</b>: 빨강, 노랑 등 원하는 색 선택<br>
• 도형은 영상 위에서 <b>드래그</b>, 텍스트는 <b>클릭</b> 후 글 입력<br>
• <b>표시 프레임 (시작~끝)</b>: 주석이 보일 프레임 범위 (같으면 한 프레임만)<br>
• <b>텍스트 크기</b>, <b>선 굵기</b> 숫자로 조절

<h4>▶ 고치기·지우기</h4>
• 그린 주석을 <b>클릭</b> → 노란 점으로 <b>이동·크기 조절</b><br>
• <b>선택 주석 삭제</b>: 목록에서 고른 주석 하나 삭제<br>
• <b>현재 프레임에 보이는 주석 전체 삭제</b>: 지금 화면에 보이는 주석 전부 삭제<br>
• 목록에서 주석 선택 후 <b>표시 프레임</b> 숫자 변경 가능

<h4>▶ 저장·보내기</h4>
• 주석은 <b>자동 저장</b> (동영상 옆 <b>.yesoncheck</b> 폴더)<br>
• 같은 영상을 다시 열면 주석이 <b>자동으로 복구</b><br>
• <b>보내기 저장 폴더 선택</b> → <b>주석 포함 영상보내기</b>로 주석이 박힌 새 영상 파일 생성

<h4>💡 주석 팁</h4>
• 주석은 <b>프레임 구간</b>으로 표시 (예: 10~50번 프레임 동안 계속 보임)<br>
• <b>OCR ROI 지정</b>과 <b>주석 모드</b>는 동시 사용 불가

<h3>🎛️ 기타</h3>
• <b>B</b>: 파일 프레임 오버레이 표시/숨김<br>
• <b>우클릭</b>: 사이드바에서 컨텍스트 메뉴

<h3>🎛️ 썸네일 모드</h3>
• <b>썸네일 모드</b>: Thumb 버튼 클릭(시간이 걸립니다)<br>
• <b>R / ㄱ</b>: 선택된 파일들의 썸네일 재생성

<h3>⚙️ 설정 (상단 메뉴바)</h3>
• <b>Settings → GPU Acceleration</b>: CPU, NVIDIA(CUDA), AMD(OpenCL)<br>
• <b>Settings → 4K 성능 모드</b>: 자동, 속도 우선, 극한 속도, 품질 우선

<h3>💡 유용한 팁</h3>
• 슬라이더를 드래그하여 빠른 위치 이동<br>
• 사이드바에서 파일 선택 후 Enter로 순차 재생<br>
• 와이프 효과로 두 비디오 비교 가능<br>
• GPU 가속으로 성능 향상<br>
• Shift+F로 깔끔한 동영상 감상 모드
        """
        
        # 스크롤 가능한 커스텀 다이얼로그 생성
        dialog = QDialog(self)
        dialog.setWindowTitle("Yeson Checker - 사용법")
        dialog.resize(800, 600)
        
        layout = QVBoxLayout(dialog)
        
        # QTextBrowser 사용 (자동 스크롤, HTML 렌더링)
        text_browser = QTextBrowser()
        text_browser.setHtml(help_text)
        text_browser.setOpenExternalLinks(False)
        layout.addWidget(text_browser)
        
        # OK 버튼
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)
        
        dialog.exec_()

    def change_performance_mode(self, index):
        """4K 성능 모드 변경"""
        mode_text = self.performanceComboBox.currentText()
        if "극한" in mode_text or "Ultra" in mode_text:
            self.set_performance_mode('ultra')
            print("4K 성능 모드: 극한 속도 (Ultra) - 최대 성능 모드")
        elif "속도" in mode_text or "Speed" in mode_text:
            self.set_performance_mode('speed')
            print("4K 성능 모드: 속도 우선 (Speed) - 드래그 최적화 활성화")
        elif "품질" in mode_text or "Quality" in mode_text:
            self.set_performance_mode('quality')
            print("4K 성능 모드: 품질 우선 (Quality) - 균형 모드")
        else:  # 자동
            self.set_performance_mode('auto')
            print("4K 성능 모드: 자동 (Auto) - 적응형 최적화")
        
        # 캐시 최적화
        self.clear_cache()
        print(f"캐시 크기: {self.cache_size}, 드래그 업데이트 빈도: {1000/self.drag_update_interval:.0f}fps")

    def set_performance_mode(self, mode):
        """성능 모드 설정"""
        self.performance_mode = mode
        if mode == 'ultra':
            self.skip_frame_processing = True
            self.cache_size = 300  # 캐시 크기 극한 증가
            self.drag_update_interval = 2   # 500fps로 극한 성능 (2ms 간격)
            self.frame_skip_threshold = 30  # 프레임 스킵 임계값 극한 증가
        elif mode == 'speed':
            self.skip_frame_processing = True
            self.cache_size = 200  # 캐시 크기 더 증가
            self.drag_update_interval = 5   # 200fps로 극한 성능 (5ms 간격)
            self.frame_skip_threshold = 20  # 프레임 스킵 임계값 더 증가
        elif mode == 'quality':
            self.skip_frame_processing = False
            self.cache_size = 50   # 캐시 크기 증가
            self.drag_update_interval = 25  # 40fps
            self.frame_skip_threshold = 8   # 프레임 스킵 임계값 증가
        else:  # auto
            self.skip_frame_processing = False
            self.cache_size = 100   # 캐시 크기 증가
            self.drag_update_interval = 15  # 67fps
            self.frame_skip_threshold = 10  # 프레임 스킵 임계값 증가

    def get_cached_frame(self, frame_idx):
        """캐시에서 프레임 가져오기"""
        if frame_idx in self.frame_cache:
            self.cache_hits += 1
            return self.frame_cache[frame_idx]
        self.cache_misses += 1
        return None

    def cache_frame(self, frame_idx, frame):
        """프레임을 캐시에 저장"""
        if len(self.frame_cache) >= self.cache_size:
            # LRU 캐시: 가장 오래된 항목 제거
            oldest_key = min(self.frame_cache.keys())
            del self.frame_cache[oldest_key]
        self.frame_cache[frame_idx] = frame.copy()

    def clear_cache(self):
        """캐시 초기화"""
        self.frame_cache.clear()
        self.cache_hits = 0
        self.cache_misses = 0

    def get_cache_stats(self):
        """캐시 통계 반환"""
        total_requests = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_requests * 100) if total_requests > 0 else 0
        return {
            'hits': self.cache_hits,
            'misses': self.cache_misses,
            'hit_rate': hit_rate,
            'cache_size': len(self.frame_cache)
        }

    def optimize_for_4k(self, frame):
        """4K 프레임 최적화 처리"""
        height, width = frame.shape[:2]
        
        # 4K 이상 해상도 감지
        if width >= 3840 or height >= 2160:
            # 성능 모드에 따른 처리
            if self.performance_mode == 'ultra':
                # 극한 속도: 최소한의 처리만 (컬러 변환만)
                return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            elif self.performance_mode == 'speed':
                # 속도 우선: 컬러 변환만 수행 (GPU 스킵)
                return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            elif self.performance_mode == 'quality':
                # 품질 우선: GPU 가속 활용
                if self.use_gpu and self.gpu_backend:
                    return self.process_frame_gpu_optimized(frame)
                else:
                    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            else:  # auto 모드
                # 자동 최적화: 드래그 중이면 최소 처리
                if self.is_dragging:
                    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                elif self.use_gpu and self.gpu_backend:
                    return self.process_frame_gpu_optimized(frame)
                else:
                    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        else:
            # HD 이하: 기존 처리
            return self.process_frame(frame)

    def process_frame_gpu_optimized(self, frame):
        """GPU 최적화된 프레임 처리"""
        try:
            if self.gpu_backend == 'cuda':
                # CUDA 최적화
                if not hasattr(self, '_cuda_gpu_mat'):
                    self._cuda_gpu_mat = cv2.cuda_GpuMat()
                
                self._cuda_gpu_mat.upload(frame)
                gpu_result = cv2.cuda.cvtColor(self._cuda_gpu_mat, cv2.COLOR_BGR2RGB)
                return gpu_result.download()
                
            elif self.gpu_backend == 'opencl':
                # OpenCL 최적화
                if not hasattr(self, '_opencl_umat'):
                    self._opencl_umat = cv2.UMat()
                
                self._opencl_umat = cv2.UMat(frame)
                result_umat = cv2.cvtColor(self._opencl_umat, cv2.COLOR_BGR2RGB)
                return result_umat.get()
                
        except Exception as e:
            # GPU 실패 시 CPU로 폴백
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def detect_video_resolution(self, file_path):
        """비디오 해상도 감지"""
        cap = cv2.VideoCapture(file_path)
        if cap.isOpened():
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            
            if width >= 3840 or height >= 2160:
                return '4K'
            elif width >= 1920 or height >= 1080:
                return 'FullHD'
            else:
                return 'HD'
        return 'Unknown'

    def update_playback_fps(self):
        """재생 FPS를 계산하고 표시합니다."""
        # 비디오의 원래 FPS를 표시하도록 수정
        if self.cap_a:
            original_fps = self.cap_a.get(cv2.CAP_PROP_FPS)
            if original_fps > 0:
                # 소수점 FPS는 정확히 표시 (23.976 등)
                if original_fps == int(original_fps):
                    fps_str = str(int(original_fps))
                else:
                    fps_str = f"{original_fps:.3f}"
                self.labelPlaybackFPS.setText(f'재생: {fps_str} FPS')
            else:
                self.labelPlaybackFPS.setText('재생: 0 FPS')
        else:
            self.labelPlaybackFPS.setText('재생: 0 FPS')

    def increment_fps_counter(self):
        """프레임 카운터를 증가시킵니다."""
        self.playback_fps_counter += 1
