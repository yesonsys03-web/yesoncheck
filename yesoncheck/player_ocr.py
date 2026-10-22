"""OCR 묶음 믹스인 (PlayerOcrMixin): ROI·분석 방식 UI 상태, 분석 시작(OCR·애니매틱·애니매틱2)과 진행·완료 콜백,
검토 창 수명, 결과 저장·불러오기, 구간 내보내기.

VideoPlayerBase의 부모 클래스로 붙음 — `class VideoPlayerBase(PlayerOcrMixin, QMainWindow)`. 그래서 VideoPlayer의 MRO에서
VideoPlayerBase 바로 뒤(QMainWindow 앞)에 오고, 다른 믹스인과의 가림 관계·`VideoPlayerBase.X`로 찾는 접근은 예전과 같음.
상태(`self.ocr_*` 등)는 예전처럼 VideoPlayerBase.__init__이 만듦.

player_base를 모듈 수준에서 import하지 말 것 — player_base가 상속하려고 이 모듈을 불러오므로 순환이 됨. 워커(`from .workers
import X`)·검토 창(player_review)·cv2는 예전처럼 메서드 안에서 불러옴(앱 시작 때 불러오지 않음).
"""

import copy
import json
import os
import re

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from yesoncheck import image_io, paths
from yesoncheck.main_window_styles import OCR_LOG_TEXT_STYLE
from yesoncheck.worker_lifecycle import release_worker


def stored_and_native_path(stored_path, native_path):
    """파일에 적힌 영상 경로와 이 PC에서 연 경로를 메시지용으로. 둘이 같으면(Mac) 한 줄 그대로 (스펙 2-4)."""
    if stored_path == native_path:
        return native_path
    return f"저장된 경로: {stored_path}\n이 PC 경로: {native_path}"


class PlayerOcrMixin:
    """VideoPlayer의 OCR·컷 감지 분석과 그 결과(검토·저장·불러오기·내보내기)."""

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
