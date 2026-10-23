"""Frame annotation UI and playback integration."""

import os
import traceback

import cv2
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from yesoncheck import external_tools, paths, user_files
from yesoncheck.user_files import UserFileError
from yesoncheck.annotation_export import AnnotationExportWorker
from yesoncheck.annotation_burn import burn_annotations_on_frame
from yesoncheck.frame_annotations import (
    DEFAULT_COLOR,
    DEFAULT_FONT_SIZE,
    DEFAULT_STROKE_WIDTH,
    MAX_FONT_SIZE,
    MIN_FONT_SIZE,
    MIN_STROKE_WIDTH,
    MAX_STROKE_WIDTH,
    AnnotationFileError,
    FrameAnnotationStore,
    annotation_export_suggested_name,
    annotation_file_path,
    annotation_share_problem,
    annotation_storage_dir,
    is_annotation_storage_writable,
    new_annotation_id,
)
from yesoncheck.player_timeline import CollapsibleBox

ANNOTATION_PANEL_MAX_HEIGHT = 300


class PlayerAnnotationsMixin:
    """Mixin providing per-frame text/shape annotations burned onto video frames."""

    def init_annotation_system(self):
        self.annotation_store = FrameAnnotationStore()
        self._annotation_unreadable_video = None  # 주석 파일을 읽지 못한 영상 (그 영상은 저장하지 않음)
        self._editing_annotation = None
        self._edit_handle = None
        self._edit_origin_norm = None
        self._edit_snapshot = None
        self._annotation_draft_start = 0
        self._annotation_draft_end = 0
        self._annotation_list_navigating = False
        self.annotation_export_worker = None
        self.annotation_export_dialog = None
        self.annotation_export_settings_file = os.path.join(
            os.path.expanduser("~"), ".yeson_annotation_export.json"
        )
        self.annotation_export_dir = ""
        self._load_annotation_export_settings()
        self.annotation_ui_widgets = []

        self.annotationModeButton = QPushButton("주석 모드")
        self.annotationModeButton.setCheckable(True)
        self.annotationModeButton.setToolTip(
            "활성화 후 도형을 그리거나 텍스트를 입력합니다.\n"
            "기존 주석을 클릭하면 자동으로 편집(이동·크기 조절)할 수 있습니다."
        )
        self.annotationModeButton.toggled.connect(self.toggle_annotation_mode)

        tool_row = QLabel("도구:")
        self.annotationToolCombo = QComboBox()
        self.annotationToolCombo.addItem("텍스트", "text")
        self.annotationToolCombo.addItem("사각형", "rect")
        self.annotationToolCombo.addItem("타원", "ellipse")
        self.annotationToolCombo.addItem("선", "line")
        self.annotationToolCombo.addItem("화살표", "arrow")
        self.annotationToolCombo.currentIndexChanged.connect(self.on_annotation_tool_changed)

        color_row = QLabel("색상:")
        self.annotationColorCombo = QComboBox()
        for label, value in [
            ("빨강", "#ff3333"),
            ("노랑", "#ffcc00"),
            ("초록", "#33cc66"),
            ("하늘", "#33aaff"),
            ("흰색", "#ffffff"),
        ]:
            self.annotationColorCombo.addItem(label, value)
        self.annotationColorCombo.currentIndexChanged.connect(self.on_annotation_color_changed)

        self.annotationFontSizeSpin = QSpinBox()
        self.annotationFontSizeSpin.setRange(MIN_FONT_SIZE, MAX_FONT_SIZE)
        self.annotationFontSizeSpin.setValue(DEFAULT_FONT_SIZE)
        self.annotationFontSizeSpin.setSuffix(" px")
        self.annotationFontSizeSpin.setToolTip("텍스트 주석 크기 (선택 항목 또는 새 텍스트에 적용)")
        self.annotationFontSizeSpin.valueChanged.connect(self.on_annotation_font_size_changed)

        font_size_row = QWidget()
        font_size_layout = QHBoxLayout(font_size_row)
        font_size_layout.setContentsMargins(0, 0, 0, 0)
        font_size_layout.addWidget(QLabel("텍스트 크기:"))
        font_size_layout.addWidget(self.annotationFontSizeSpin)

        self.annotationStrokeWidthSpin = QSpinBox()
        self.annotationStrokeWidthSpin.setRange(MIN_STROKE_WIDTH, MAX_STROKE_WIDTH)
        self.annotationStrokeWidthSpin.setValue(DEFAULT_STROKE_WIDTH)
        self.annotationStrokeWidthSpin.setSuffix(" px")
        self.annotationStrokeWidthSpin.setToolTip("도형·선·화살표 굵기 (선택 항목 또는 새 도형에 적용)")
        self.annotationStrokeWidthSpin.valueChanged.connect(self.on_annotation_stroke_width_changed)

        stroke_row = QWidget()
        stroke_layout = QHBoxLayout(stroke_row)
        stroke_layout.setContentsMargins(0, 0, 0, 0)
        stroke_layout.addWidget(QLabel("선 굵기:"))
        stroke_layout.addWidget(self.annotationStrokeWidthSpin)

        self._range_controls_updating = False
        self.annotationRangeStartSpin = QSpinBox()
        self.annotationRangeStartSpin.setMinimum(1)
        self.annotationRangeStartSpin.setMaximum(1)
        self.annotationRangeStartSpin.setValue(1)
        self.annotationRangeStartSpin.setKeyboardTracking(False)
        self.annotationRangeStartSpin.setMinimumWidth(72)
        self.annotationRangeStartSpin.setToolTip(
            "주석이 보이기 시작하는 프레임 (1부터 시작)\n"
            "입력 후 Enter 또는 다른 칸을 클릭하세요."
        )
        self.annotationRangeStartSpin.editingFinished.connect(self.on_annotation_range_committed)
        self.annotationRangeStartSpin.valueChanged.connect(self.on_annotation_range_committed)

        self.annotationRangeEndSpin = QSpinBox()
        self.annotationRangeEndSpin.setMinimum(1)
        self.annotationRangeEndSpin.setMaximum(1)
        self.annotationRangeEndSpin.setValue(1)
        self.annotationRangeEndSpin.setKeyboardTracking(False)
        self.annotationRangeEndSpin.setMinimumWidth(72)
        self.annotationRangeEndSpin.setToolTip(
            "주석이 보이기 끝나는 프레임 (시작 프레임 이상)\n"
            "입력 후 Enter 또는 다른 칸을 클릭하세요."
        )
        self.annotationRangeEndSpin.editingFinished.connect(self.on_annotation_range_committed)
        self.annotationRangeEndSpin.valueChanged.connect(self.on_annotation_range_committed)

        range_row = QWidget()
        range_layout = QHBoxLayout(range_row)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.addWidget(QLabel("표시 프레임:"))
        range_layout.addWidget(QLabel("시작"))
        range_layout.addWidget(self.annotationRangeStartSpin)
        range_layout.addWidget(QLabel("~ 끝"))
        range_layout.addWidget(self.annotationRangeEndSpin)

        self._style_controls_updating = False

        self.annotationListWidget = QListWidget()
        self.annotationListWidget.setMaximumHeight(120)
        self.annotationListWidget.setToolTip(
            "전체 주석 목록 · 클릭하면 시작 프레임으로 이동"
        )
        self.annotationListWidget.itemSelectionChanged.connect(self.on_annotation_selection_changed)

        self.annotationDeleteButton = QPushButton("선택 주석 삭제")
        self.annotationDeleteButton.clicked.connect(self.delete_selected_annotation)

        self.annotationClearFrameButton = QPushButton("현재 프레임에 보이는 주석 전체 삭제")
        self.annotationClearFrameButton.clicked.connect(self.clear_current_frame_annotations)

        self.annotationExportButton = QPushButton("주석 포함 영상보내기")
        self.annotationExportButton.setToolTip(
            "주석이 픽셀에 박힌 새 영상 파일을 생성합니다.\n"
            "먼저 아래에서 보내기 저장 폴더를 선택하세요."
        )
        self.annotationExportButton.clicked.connect(self.export_annotated_video)

        self.annotationExportDirButton = QPushButton("보내기 저장 폴더 선택")
        self.annotationExportDirButton.clicked.connect(self.choose_annotation_export_dir)

        self.annotationExportDirLabel = QLabel("보내기 저장 폴더: 미지정")
        self.annotationExportDirLabel.setWordWrap(True)
        self.annotationExportDirLabel.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        self._update_annotation_export_dir_label()

        self.annotationStorageLabel = QLabel("")
        self.annotationStorageLabel.setWordWrap(True)
        self.annotationStorageLabel.setStyleSheet("color: #aaaaaa; font-size: 11px;")

        self.annotationStatusLabel = QLabel("주석: 없음 (자동 저장)")
        self.annotationStatusLabel.setWordWrap(True)

        self.videoWidget.annotationShapeFinished.connect(self.on_annotation_shape_finished)
        self.videoWidget.annotationTextRequested.connect(self.on_annotation_text_requested)
        self.videoWidget.annotationMovePressed.connect(self.on_annotation_move_pressed)
        self.videoWidget.annotationMoveDragged.connect(self.on_annotation_move_dragged)
        self.videoWidget.annotationMoveReleased.connect(self.on_annotation_move_released)
        self._sync_annotation_style_to_widget()

        self.annotation_ui_widgets = [
            self.annotationModeButton,
            tool_row,
            self.annotationToolCombo,
            color_row,
            self.annotationColorCombo,
            font_size_row,
            stroke_row,
            range_row,
            self.annotationListWidget,
            self.annotationDeleteButton,
            self.annotationClearFrameButton,
            self.annotationExportDirButton,
            self.annotationExportDirLabel,
            self.annotationExportButton,
            self.annotationStorageLabel,
            self.annotationStatusLabel,
        ]

    def _load_annotation_export_settings(self):
        """내보내기 저장 폴더 설정을 읽음. 읽지 못하면 미지정 (기록에 스택 트레이스 + 창 한 번, 파일은 그대로)."""
        self.annotation_export_dir = ""
        path = self.annotation_export_settings_file
        try:
            data = user_files.read_json(path, {})
            if not isinstance(data, dict) or not isinstance(data.get("export_dir", ""), str):
                raise UserFileError(f"주석 내보내기 설정 파일 형식이 올바르지 않습니다 (export_dir 글자가 든 설정이어야 함): {path}")
        except UserFileError as exc:
            traceback.print_exc()
            self._report_user_file_problem(
                "annotation-export-read", "주석 내보내기 설정을 읽지 못함",
                f"주석 내보내기 저장 폴더 설정을 읽지 못해 폴더를 미지정으로 둡니다 (파일은 그대로 둡니다):\n{exc}")
            return
        export_dir = data.get("export_dir", "")
        if export_dir and os.path.isdir(export_dir):
            self.annotation_export_dir = export_dir

    def _save_annotation_export_settings(self):
        """내보내기 저장 폴더를 원자적으로 저장 (마지막에 쓴 창의 값이 남음). 쓰지 못하면 기록 + 창 한 번."""
        try:
            user_files.write_json_atomic(self.annotation_export_settings_file, {"export_dir": self.annotation_export_dir})
        except OSError as exc:
            traceback.print_exc()
            self._report_user_file_problem(
                "annotation-export-write", "주석 내보내기 설정을 저장하지 못함",
                f"주석 내보내기 저장 폴더를 저장하지 못했습니다 (파일은 그대로 둡니다):\n"
                f"{self.annotation_export_settings_file}\n{type(exc).__name__}: {exc}")

    def _update_annotation_export_dir_label(self):
        if self.annotation_export_dir:
            self.annotationExportDirLabel.setText(
                f"보내기 저장 폴더: {self.annotation_export_dir}"
            )
        else:
            self.annotationExportDirLabel.setText("보내기 저장 폴더: 미지정 (선택 필요)")

    def choose_annotation_export_dir(self):
        start_dir = self.annotation_export_dir or (os.path.dirname(self.filename_a) if self.filename_a else "")
        folder = QFileDialog.getExistingDirectory(
            self,
            "보내기 저장 폴더 선택",
            start_dir,
        )
        if not folder:
            return
        self.annotation_export_dir = folder
        self._save_annotation_export_settings()
        self._update_annotation_export_dir_label()

    def _ensure_annotation_export_dir(self):
        if self.annotation_export_dir and os.path.isdir(self.annotation_export_dir):
            return True
        reply = QMessageBox.question(
            self,
            "보내기 저장 폴더",
            "보내기 저장 폴더가 지정되지 않았습니다.\n지금 선택할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return False
        self.choose_annotation_export_dir()
        return bool(self.annotation_export_dir and os.path.isdir(self.annotation_export_dir))

    def _default_export_output_path(self):
        filename = annotation_export_suggested_name(self.filename_a)
        return os.path.join(self.annotation_export_dir, filename)

    def _sync_annotation_style_to_widget(self):
        self.videoWidget.annotation_font_size = self.annotationFontSizeSpin.value()
        self.videoWidget.annotation_stroke_width = self.annotationStrokeWidthSpin.value()

    def _get_total_frames(self):
        if not self.cap_a:
            return 1
        return max(1, int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT)))

    def _update_annotation_range_spin_limits(self):
        total = self._get_total_frames()
        for spin in (self.annotationRangeStartSpin, self.annotationRangeEndSpin):
            spin.setMaximum(total)

    def _get_annotation_range_0based(self):
        start = self.annotationRangeStartSpin.value() - 1
        end = self.annotationRangeEndSpin.value() - 1
        total = self._get_total_frames() - 1
        start = max(0, min(start, total))
        end = max(0, min(end, total))
        return start, end

    def _set_range_spin_values(self, start_0based, end_0based):
        self._range_controls_updating = True
        try:
            self.annotationRangeStartSpin.setValue(int(start_0based) + 1)
            self.annotationRangeEndSpin.setValue(int(end_0based) + 1)
        finally:
            self._range_controls_updating = False

    def _push_range_spins_from_draft(self):
        self._update_annotation_range_spin_limits()
        self._set_range_spin_values(self._annotation_draft_start, self._annotation_draft_end)

    def _push_range_spins_from_item(self, item):
        self._update_annotation_range_spin_limits()
        start = int(item.get("start_frame", 0))
        end = int(item.get("end_frame", start))
        self._set_range_spin_values(start, end)

    def _set_draft_range_to_current_frame(self):
        current = self.get_current_frame_index()
        self._annotation_draft_start = current
        self._annotation_draft_end = current

    def on_annotation_range_committed(self):
        """Apply range after user finishes typing (Enter / focus out)."""
        if self._range_controls_updating:
            return

        sender = self.sender()
        start_ui = self.annotationRangeStartSpin.value()
        end_ui = self.annotationRangeEndSpin.value()

        if sender is self.annotationRangeEndSpin and end_ui < start_ui:
            self._range_controls_updating = True
            try:
                self.annotationRangeEndSpin.setValue(start_ui)
            finally:
                self._range_controls_updating = False
        elif sender is self.annotationRangeStartSpin and start_ui > end_ui:
            self._range_controls_updating = True
            try:
                self.annotationRangeEndSpin.setValue(start_ui)
            finally:
                self._range_controls_updating = False

        start, end = self._get_annotation_range_0based()
        item = self._get_selected_annotation()
        if item:
            self.annotation_store.update_by_id(
                item["id"],
                {"start_frame": start, "end_frame": end},
            )
            self.auto_save_annotations()
            frame_idx = self.get_current_frame_index()
            self._update_annotation_list_ui(frame_idx)
            self._update_annotation_status_label()
            self._redraw_frame_with_annotations()
        else:
            self._annotation_draft_start = start
            self._annotation_draft_end = end

    def _get_selected_annotation(self):
        selected = self.annotationListWidget.currentItem()
        if not selected:
            return None
        ann_id = selected.data(Qt.UserRole)
        _, item = self.annotation_store.find_item_by_id(ann_id)
        return item

    def _select_annotation_in_list(self, annotation_id):
        if not annotation_id:
            return
        for row in range(self.annotationListWidget.count()):
            item = self.annotationListWidget.item(row)
            if item.data(Qt.UserRole) == annotation_id:
                self.annotationListWidget.setCurrentRow(row)
                return

    def _set_edit_target(self, annotation):
        if self.annotationModeButton.isChecked():
            self.videoWidget.set_annotation_edit_target(annotation)
        else:
            self.videoWidget.set_annotation_edit_target(None)

    def _focus_annotation(self, annotation):
        """Select annotation in list and show edit handles."""
        if not annotation:
            self.annotationListWidget.clearSelection()
            self._set_edit_target(None)
            return
        self._select_annotation_in_list(annotation.get("id"))
        item = self._get_selected_annotation()
        self._set_edit_target(item or annotation)

    def on_annotation_move_pressed(self, norm_x, norm_y):
        if not self.annotationModeButton.isChecked():
            return
        frame_idx = self.get_current_frame_index()
        item, handle = self.annotation_store.find_edit_candidate(frame_idx, norm_x, norm_y)
        if not item or not handle:
            self._editing_annotation = None
            self.videoWidget.annotation_edit_interaction = False
            self.annotationListWidget.clearSelection()
            self._set_edit_target(None)
            return

        self.videoWidget.annotation_edit_interaction = True
        self._editing_annotation = item
        self._edit_handle = handle
        self._edit_origin_norm = (norm_x, norm_y)
        self._edit_snapshot = dict(item)
        self._focus_annotation(item)

    def on_annotation_move_dragged(self, norm_x, norm_y):
        if not self._editing_annotation or not self._edit_snapshot or not self._edit_handle:
            return

        frame_idx = self.get_current_frame_index()
        ann_id = self._editing_annotation["id"]

        if self._edit_handle == "move":
            origin_x, origin_y = self._edit_origin_norm
            delta_x = norm_x - origin_x
            delta_y = norm_y - origin_y
            updated = FrameAnnotationStore.move_item(self._edit_snapshot, delta_x, delta_y)
        else:
            updated = FrameAnnotationStore.resize_item_by_handle(
                self._edit_snapshot, self._edit_handle, norm_x, norm_y
            )

        self.annotation_store.update_by_id(ann_id, updated)
        self._editing_annotation = updated
        self._set_edit_target(updated)
        self._redraw_frame_with_annotations()

    def on_annotation_move_released(self, norm_x, norm_y):
        if not self._editing_annotation:
            return
        self.on_annotation_move_dragged(norm_x, norm_y)
        frame_idx = self.get_current_frame_index()
        self._update_annotation_list_ui(frame_idx)
        self._editing_annotation = None
        self._edit_handle = None
        self._edit_origin_norm = None
        self._edit_snapshot = None
        self.auto_save_annotations()
        self._update_annotation_status_label()
        self._set_edit_target(self._get_selected_annotation())

    def on_annotation_selection_changed(self):
        item = self._get_selected_annotation()
        if item and not self._annotation_list_navigating:
            start_frame = int(item.get("start_frame", 0))
            if self.get_current_frame_index() != start_frame:
                self._annotation_list_navigating = True
                try:
                    self.seek_to_frame(start_frame + 1)
                finally:
                    self._annotation_list_navigating = False

        if not self.annotationModeButton.isChecked():
            if item:
                self._push_range_spins_from_item(item)
            return

        self._set_edit_target(item)
        if item:
            self._push_range_spins_from_item(item)
        else:
            self._push_range_spins_from_draft()
        self._style_controls_updating = True
        try:
            if item:
                if item.get("type") == "text":
                    self.annotationFontSizeSpin.setValue(
                        int(item.get("font_size", DEFAULT_FONT_SIZE))
                    )
                else:
                    self.annotationStrokeWidthSpin.setValue(
                        int(item.get("stroke_width", DEFAULT_STROKE_WIDTH))
                    )
        finally:
            self._style_controls_updating = False
        self._update_style_control_enabled_state(item)

    def _update_style_control_enabled_state(self, selected_item=None):
        if selected_item is None:
            selected_item = self._get_selected_annotation()
        tool = self.annotationToolCombo.currentData()
        self.annotationFontSizeSpin.setEnabled(
            selected_item is None or selected_item.get("type") == "text" or tool == "text"
        )
        self.annotationStrokeWidthSpin.setEnabled(
            selected_item is None
            or selected_item.get("type") != "text"
            or tool in ("rect", "ellipse", "line", "arrow")
        )
        if tool in ("rect", "ellipse", "line", "arrow"):
            self.annotationStrokeWidthSpin.setEnabled(True)
        if tool == "text":
            self.annotationFontSizeSpin.setEnabled(True)

    def on_annotation_font_size_changed(self, value):
        if self._style_controls_updating:
            return
        self._sync_annotation_style_to_widget()
        item = self._get_selected_annotation()
        if item and item.get("type") == "text":
            frame_idx = self.get_current_frame_index()
            self.annotation_store.update_by_id(
                item["id"], {"font_size": int(value)}
            )
            self.auto_save_annotations()
            self._update_annotation_list_ui(frame_idx)
            self._redraw_frame_with_annotations()

    def on_annotation_stroke_width_changed(self, value):
        if self._style_controls_updating:
            return
        self._sync_annotation_style_to_widget()
        item = self._get_selected_annotation()
        if item and item.get("type") != "text":
            frame_idx = self.get_current_frame_index()
            self.annotation_store.update_by_id(
                item["id"], {"stroke_width": int(value)}
            )
            self.auto_save_annotations()
            self._update_annotation_list_ui(frame_idx)
            self._redraw_frame_with_annotations()

    def build_annotation_group(self):
        group = CollapsibleBox("▶ 수정 사항 주석")
        group.toggle_button.setChecked(False)
        group.content_area.setVisible(False)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(5)
        for widget in self.annotation_ui_widgets:
            inner_layout.addWidget(widget)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMaximumHeight(ANNOTATION_PANEL_MAX_HEIGHT)
        scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        group.add_widget(scroll)
        return group

    def get_current_frame_index(self):
        if not self.cap_a:
            return 0
        frame_idx = int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        return max(0, frame_idx)

    def current_frame_has_annotations(self):
        if not hasattr(self, "annotation_store"):
            return False
        return bool(self.annotation_store.get_frame(self.get_current_frame_index()))

    def burn_frame_annotations(self, frame):
        if frame is None or not hasattr(self, "annotation_store"):
            return frame
        items = self.annotation_store.get_frame(self.get_current_frame_index())
        if not items:
            return frame
        return burn_annotations_on_frame(frame, items)

    def prepare_frame_for_display(self, frame):
        if frame is None:
            return None
        has_annotations = self.current_frame_has_annotations()
        if not self.show_overlay and not has_annotations:
            return frame
        output = frame.copy()
        if self.show_overlay:
            self.overlay_text(output)
        if has_annotations:
            return self.burn_frame_annotations(output)
        return output

    def auto_save_annotations(self):
        if not self.filename_a:
            return False
        if self._annotation_unreadable_video == self.filename_a:
            # 이 영상의 주석 파일을 열 때 읽지 못했음(창으로 알림) → 읽지 못한 파일을 덮어 지우지 않게 저장하지 않음
            self.annotationStorageLabel.setText(
                f"⚠ 주석 저장 안 함 (주석 파일을 읽지 못함): {annotation_file_path(self.filename_a)}"
            )
            return False
        if not is_annotation_storage_writable(self.filename_a):
            self.annotationStorageLabel.setText(
                f"⚠ 주석 저장 불가 (쓰기 권한 없음): {annotation_storage_dir(self.filename_a)}"
            )
            return False
        ids_before = self._annotation_ids()
        try:
            path = self.annotation_store.save()
        except paths.PathMapError as exc:
            # (Mac) 주석 파일에 적을 영상 경로를 정하지 못함 (제자리가 아닌 곳에 붙은 공유) → 저장하지 않음. 자동 저장은
            # 주석을 바꿀 때마다 불리므로 창은 (영상, 까닭)마다 한 번
            self.annotationStorageLabel.setText(f"⚠ 주석 저장 실패: {exc}")
            self._show_annotation_problem_once(
                "주석 저장 실패", str(exc),
                f"주석 파일에 적을 영상 경로를 정하지 못해 주석을 저장하지 않았습니다:\n{self.filename_a}\n\n{exc}",
            )
            return False
        except AnnotationFileError as exc:
            # 저장하려고 다시 읽는 중에 파일이 깨졌거나 읽을 수 없게 됨 (다른 창·PC가 쓰다 만 파일 등) → 그 파일은 그대로 두고 저장하지 않음
            traceback.print_exc()
            self.annotationStorageLabel.setText(f"⚠ 주석 저장 실패: {exc}")
            self._show_annotation_problem_once(
                "주석 저장 실패", str(exc),
                f"주석 파일을 읽지 못해 주석을 저장하지 않았습니다 (파일은 그대로 두었습니다):\n{exc}",
            )
            return False
        except Exception as exc:
            # 쓰기 실패(NAS 연결 끊김·권한·디스크 가득 등): 원래 파일은 그대로, 로그에 스택 트레이스, 창은 (영상, 까닭)마다 한 번
            detail = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            self.annotationStorageLabel.setText(f"⚠ 주석 저장 실패: {detail}")
            self._show_annotation_problem_once(
                "주석 저장 실패", detail,
                f"주석을 저장하지 못했습니다 (원래 파일은 그대로입니다):\n{annotation_file_path(self.filename_a)}\n\n{detail}",
            )
            return False
        self._update_annotation_storage_label(path)
        self._report_annotation_share_problem()
        if self._annotation_ids() != ids_before:
            # 저장하며 합친 결과로 다른 창이 넣거나 지운 항목이 바뀜 → 목록·화면에 반영
            self.refresh_annotation_ui(redraw=True)
        return True

    def _annotation_ids(self):
        return {item.get("id") for _start, _end, _anchor, item in self.annotation_store.all_items_sorted()}

    def _show_annotation_problem_once(self, title, reason, text):
        """주석 저장 문제를 창으로 ((영상, 까닭)마다 한 번 — 자동 저장은 주석을 바꿀 때마다 불림)."""
        shown = self.__dict__.setdefault("_annotation_problems_shown", set())
        if (self.filename_a, reason) in shown:
            return
        shown.add((self.filename_a, reason))
        QMessageBox.critical(self, title, text)

    def _report_annotation_share_problem(self):
        """내가 만든 주석 폴더의 권한을 바꾸지 못했으면 창으로 (폴더마다 한 번): 이 PC에서는 저장하지만 다른 NAS 계정의 PC는 못 쓸 수 있음."""
        folder = annotation_storage_dir(self.filename_a)
        problem = annotation_share_problem(folder)
        if problem:
            self._show_annotation_problem_once(
                "주석 폴더 권한",
                f"{folder}\n{problem}",
                "주석 폴더의 권한을 바꾸지 못했습니다. 이 PC에서는 주석을 저장하지만, 다른 NAS 계정을 쓰는 PC(Windows 등)는 "
                f"이 폴더에 저장하지 못할 수 있습니다.\n{folder}\n이유: {problem}",
            )

    def _update_annotation_storage_label(self, json_path=None):
        if not self.filename_a:
            self.annotationStorageLabel.setText("")
            return
        path = json_path or annotation_file_path(self.filename_a)
        writable = is_annotation_storage_writable(self.filename_a)
        prefix = "서버 공유 저장" if writable else "⚠ 저장 불가"
        self.annotationStorageLabel.setText(f"{prefix}: {path}")

    def on_video_annotations_reset(self, video_path):
        fps = 0.0
        if self.cap_a:
            fps = float(self.cap_a.get(cv2.CAP_PROP_FPS) or 0.0)
        self.annotation_store.set_video(video_path, fps)
        self._last_annotation_frame_idx = None
        self._annotation_unreadable_video = None
        try:
            loaded = self.annotation_store.load()
        except AnnotationFileError as exc:
            # 주석 파일이 있는데 읽지 못함(깨짐·권한·NAS 오류) → 창으로 알리고 이 영상은 주석을 저장하지 않음
            # (비어 있는 줄 알고 저장하다 그 파일을 덮어 지우지 않게)
            traceback.print_exc()
            loaded = False
            self._annotation_unreadable_video = video_path
            QMessageBox.critical(
                self, "주석 파일을 읽지 못함",
                f"이 영상의 주석 파일을 읽지 못해 주석을 불러오지 않았고, 이 영상의 주석은 저장하지 않습니다 "
                f"(파일은 그대로 둡니다):\n{exc}\n\n파일을 고치거나 옮긴 뒤 영상을 다시 열어 주세요.",
            )
        self._set_draft_range_to_current_frame()
        self._push_range_spins_from_draft()
        self.refresh_annotation_ui(redraw=False)
        self._update_annotation_storage_label()
        if self._annotation_unreadable_video:
            self.annotationStorageLabel.setText(
                f"⚠ 주석 저장 안 함 (주석 파일을 읽지 못함): {annotation_file_path(video_path)}"
            )
            self.annotationStatusLabel.setText("⚠ 주석 파일을 읽지 못함 — 이 영상은 주석을 저장하지 않음")
        elif loaded:
            count = self.annotation_store.total_count()
            self.annotationStatusLabel.setText(
                f"주석 {count}개 자동 로드 · 서버 공유 JSON"
            )
        else:
            self.annotationStatusLabel.setText("주석: 없음 (서버 폴더에 자동 저장)")

    def toggle_annotation_mode(self, checked):
        if checked and getattr(self, "ocrSelectRoiButton", None) and self.ocrSelectRoiButton.isChecked():
            self.ocrSelectRoiButton.setChecked(False)
        tool = self.annotationToolCombo.currentData()
        color = self.annotationColorCombo.currentData() or DEFAULT_COLOR
        self._sync_annotation_style_to_widget()
        self.videoWidget.enable_annotation_mode(checked, tool=tool, color=color)
        self._update_style_control_enabled_state()
        if checked and not self.filename_a:
            QMessageBox.information(self, "주석 모드", "먼저 Video A 파일을 열어주세요.")
            self.annotationModeButton.setChecked(False)

    def on_annotation_tool_changed(self):
        self._update_style_control_enabled_state()
        if self.annotationModeButton.isChecked():
            tool = self.annotationToolCombo.currentData()
            color = self.annotationColorCombo.currentData() or DEFAULT_COLOR
            self._sync_annotation_style_to_widget()
            self.videoWidget.enable_annotation_mode(True, tool=tool, color=color)

    def on_annotation_color_changed(self):
        if self.annotationModeButton.isChecked():
            color = self.annotationColorCombo.currentData() or DEFAULT_COLOR
            self.videoWidget.annotation_color = color

    def on_annotation_shape_finished(self, payload):
        frame_idx = self.get_current_frame_index()
        payload.setdefault("stroke_width", self.annotationStrokeWidthSpin.value())
        start_frame, end_frame = self._get_annotation_range_0based()
        item = self.annotation_store.add(
            frame_idx, payload, start_frame=start_frame, end_frame=end_frame
        )
        self.auto_save_annotations()
        self.refresh_annotation_ui(redraw=True)
        self._focus_annotation(item)
        self.annotationStatusLabel.setText(
            f"프레임 {start_frame + 1}~{end_frame + 1}에 {item.get('type')} 주석 추가 (자동 저장)"
        )

    def on_annotation_text_requested(self, norm_x, norm_y):
        text, ok = QInputDialog.getText(
            self,
            "텍스트 주석",
            f"프레임 {self.get_current_frame_index() + 1}에 표시할 텍스트:",
        )
        if not ok or not text.strip():
            return
        frame_idx = self.get_current_frame_index()
        start_frame, end_frame = self._get_annotation_range_0based()
        payload = {
            "type": "text",
            "norm_x1": norm_x,
            "norm_y1": norm_y,
            "norm_x2": norm_x,
            "norm_y2": norm_y,
            "text": text.strip(),
            "color": self.annotationColorCombo.currentData() or DEFAULT_COLOR,
            "font_size": self.annotationFontSizeSpin.value(),
            "id": new_annotation_id(),
        }
        item = self.annotation_store.add(
            frame_idx, payload, start_frame=start_frame, end_frame=end_frame
        )
        self.auto_save_annotations()
        self.refresh_annotation_ui(redraw=True)
        self._focus_annotation(item)
        self.annotationStatusLabel.setText(
            f"프레임 {start_frame + 1}~{end_frame + 1}에 텍스트 주석 추가 (자동 저장)"
        )

    def _redraw_frame_with_annotations(self):
        if self.frame_a is None:
            return
        frame_a_to_show = self.prepare_frame_for_display(self.frame_a)
        frame_b_to_show = (
            self.frame_b
            if (self.videoWidget.wipe_enabled_x or self.videoWidget.wipe_enabled_y)
            else None
        )
        self.videoWidget.updateFrame(frame_a_to_show, frame_b_to_show)
        if self.annotationModeButton.isChecked():
            if self._editing_annotation:
                self._set_edit_target(self._editing_annotation)
            else:
                self._set_edit_target(self._get_selected_annotation())

    def refresh_annotation_ui(self, redraw=True):
        frame_idx = self.get_current_frame_index()
        self._last_annotation_frame_idx = frame_idx
        self._update_annotation_range_spin_limits()
        self._update_annotation_list_ui(frame_idx)
        self._update_annotation_status_label()
        if redraw:
            self._redraw_frame_with_annotations()

    def _update_annotation_list_ui(self, frame_idx=None):
        if frame_idx is None:
            frame_idx = self.get_current_frame_index()

        selected_id = None
        current_item = self.annotationListWidget.currentItem()
        if current_item:
            selected_id = current_item.data(Qt.UserRole)

        self.annotationListWidget.blockSignals(True)
        self.annotationListWidget.clear()
        select_row = -1
        for row, (start, end, _anchor_frame, item) in enumerate(
            self.annotation_store.all_items_sorted()
        ):
            label = self._annotation_list_label(item)
            list_item = QListWidgetItem(label)
            ann_id = item.get("id")
            list_item.setData(Qt.UserRole, ann_id)
            if start <= frame_idx <= end:
                list_item.setBackground(QColor(48, 72, 48))
            self.annotationListWidget.addItem(list_item)
            if selected_id and ann_id == selected_id:
                select_row = row
        if select_row >= 0:
            self.annotationListWidget.setCurrentRow(select_row)
        self.annotationListWidget.blockSignals(False)

    def _update_annotation_status_label(self):
        frame_idx = self.get_current_frame_index()
        items = self.annotation_store.get_frame(frame_idx)
        total = self.annotation_store.total_count()
        frame_count = len(self.annotation_store.frames_with_annotations())
        self.annotationStatusLabel.setText(
            f"전체 {total}개 / {frame_count}개 프레임에 표시 · 목록 {total}개 · 현재 프레임 {frame_idx + 1}: {len(items)}개 (자동 저장)"
        )

    def _annotation_list_label(self, item):
        start = int(item.get("start_frame", 0))
        end = int(item.get("end_frame", start))
        range_label = f"F{start + 1}" if start == end else f"F{start + 1}~{end + 1}"
        ann_type = item.get("type", "rect")
        if ann_type == "text":
            text = item.get("text", "")
            preview = text if len(text) <= 24 else text[:24] + "..."
            size = item.get("font_size", DEFAULT_FONT_SIZE)
            return f"[{range_label} 텍스트 {size}px] {preview}"
        stroke = item.get("stroke_width", DEFAULT_STROKE_WIDTH)
        return f"[{range_label} {ann_type} {stroke}px]"

    def delete_selected_annotation(self):
        selected = self.annotationListWidget.currentItem()
        if not selected:
            QMessageBox.information(self, "주석 삭제", "삭제할 주석을 목록에서 선택하세요.")
            return
        ann_id = selected.data(Qt.UserRole)
        if self.annotation_store.remove_by_id(ann_id):
            self.auto_save_annotations()
            self.videoWidget.set_annotation_edit_target(None)
            self.refresh_annotation_ui()

    def clear_current_frame_annotations(self):
        frame_idx = self.get_current_frame_index()
        if not self.annotation_store.get_frame(frame_idx):
            return
        reply = QMessageBox.question(
            self,
            "주석 삭제",
            f"프레임 {frame_idx + 1}에 보이는 모든 주석을 삭제할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.annotation_store.clear_visible_on_frame(frame_idx)
            self.auto_save_annotations()
            self.videoWidget.set_annotation_edit_target(None)
            self.refresh_annotation_ui()

    def export_annotated_video(self):
        if not self.filename_a:
            QMessageBox.warning(self, "영상보내기", "Video A 파일을 먼저 열어주세요.")
            return
        if self.annotation_store.total_count() == 0:
            QMessageBox.information(self, "영상보내기", "보낼 주석이 없습니다.")
            return
        if self.annotation_export_worker and self.annotation_export_worker.isRunning():
            QMessageBox.information(self, "영상보내기", "이미 보내기 작업이 진행 중입니다.")
            return
        if not self._ensure_annotation_export_dir():
            return

        default_output = self._default_export_output_path()
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "주석 포함 영상 저장",
            default_output,
            "Video Files (*.mp4 *.mov);;All Files (*)",
        )
        if not output_path:
            return

        chosen_dir = os.path.dirname(output_path)
        if chosen_dir and os.path.isdir(chosen_dir):
            self.annotation_export_dir = chosen_dir
            self._save_annotation_export_settings()
            self._update_annotation_export_dir_label()

        dialog = QDialog(self)
        dialog.setWindowTitle("주석 포함 영상보내기")
        dialog.resize(420, 220)
        layout = QVBoxLayout(dialog)

        info = QLabel(
            f"주석 {self.annotation_store.total_count()}개를 영상에 박아서 저장합니다.\n"
            f"원본: {os.path.basename(self.filename_a)}"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("품질:"))
        mode_combo = QComboBox()
        mode_combo.addItem("균형 (권장)", "balanced")
        mode_combo.addItem(external_tools.fast_mode_label(), "fast")
        mode_combo.addItem("고품질", "quality")
        mode_row.addWidget(mode_combo)
        layout.addLayout(mode_row)

        audio_check = QCheckBox("오디오 포함")
        audio_check.setChecked(True)
        if self.is_sequence_active():
            # 이미지 시퀀스에는 소리가 없음 (내보내기도 소리 입력 없이 영상만 만듦)
            audio_check.setChecked(False)
            audio_check.setEnabled(False)
            audio_check.setToolTip("이미지 시퀀스에는 소리가 없습니다.")
        layout.addWidget(audio_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        self.auto_save_annotations()
        total_frames = self._get_total_frames()
        self._start_annotation_export(
            output_path=output_path,
            export_mode=mode_combo.currentData(),
            include_audio=audio_check.isChecked(),
            total_frames=total_frames,
        )

    def _start_annotation_export(
        self, output_path, export_mode="balanced", include_audio=True, total_frames=None
    ):
        ffmpeg = self.require_ffmpeg()
        if ffmpeg is None:
            return

        frame_dict = self.annotation_store.as_frame_dict(total_frames=total_frames)
        self.annotation_export_worker = AnnotationExportWorker(
            self.filename_a,
            frame_dict,
            output_path,
            ffmpeg,
            include_audio=include_audio,
            export_mode=export_mode,
        )
        self.annotation_export_worker.progress.connect(self._on_annotation_export_progress)
        self.annotation_export_worker.status.connect(self._on_annotation_export_status)
        self.annotation_export_worker.error.connect(self._on_annotation_export_error)
        self.annotation_export_worker.completed.connect(self._on_annotation_export_completed)

        self.annotation_export_dialog = QDialog(self)
        self.annotation_export_dialog.setWindowTitle("주석 포함 영상보내기")
        self.annotation_export_dialog.setWindowModality(Qt.NonModal)
        self.annotation_export_dialog.resize(520, 280)

        export_layout = QVBoxLayout(self.annotation_export_dialog)
        export_layout.addWidget(QLabel(f"저장 위치: {output_path}"))

        self.annotation_export_progress = QProgressBar()
        self.annotation_export_progress.setRange(0, 100)
        export_layout.addWidget(self.annotation_export_progress)

        self.annotation_export_log = QPlainTextEdit()
        self.annotation_export_log.setReadOnly(True)
        export_layout.addWidget(self.annotation_export_log)

        cancel_button = QPushButton("취소")
        cancel_button.clicked.connect(self.cancel_annotation_export)
        export_layout.addWidget(cancel_button)

        self.annotation_export_log.appendPlainText("주석 포함 영상 인코딩을 시작합니다…")
        self.annotation_export_dialog.show()
        self.annotation_export_worker.start()

    def _on_annotation_export_progress(self, value):
        if self.annotation_export_progress:
            self.annotation_export_progress.setValue(value)

    def _on_annotation_export_status(self, message):
        if self.annotation_export_log:
            self.annotation_export_log.appendPlainText(message)

    def _on_annotation_export_error(self, message):
        if self.annotation_export_log:
            self.annotation_export_log.appendPlainText(f"오류: {message}")
        QMessageBox.critical(self, "영상보내기 실패", message)
        self._close_annotation_export_dialog()

    def _on_annotation_export_completed(self, output_path):
        if self.annotation_export_log:
            self.annotation_export_log.appendPlainText(f"완료: {output_path}")
        QMessageBox.information(
            self,
            "영상보내기 완료",
            f"주석이 포함된 영상을 저장했습니다.\n{output_path}",
        )
        self._close_annotation_export_dialog()

    def cancel_annotation_export(self):
        if self.annotation_export_worker and self.annotation_export_worker.isRunning():
            self.annotation_export_worker.stop()
            self.annotation_export_worker.wait(3000)
        self._close_annotation_export_dialog()

    def _close_annotation_export_dialog(self):
        if self.annotation_export_dialog:
            self.annotation_export_dialog.close()
            self.annotation_export_dialog = None
        self.annotation_export_worker = None

    def refresh_frame_annotations_display(self):
        if not hasattr(self, "annotation_store"):
            return
        frame_idx = self.get_current_frame_index()
        if getattr(self, "_last_annotation_frame_idx", None) == frame_idx:
            return
        self._last_annotation_frame_idx = frame_idx
        self._update_annotation_list_ui(frame_idx)
        self._update_annotation_status_label()
        self._redraw_frame_with_annotations()
