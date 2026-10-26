"""메인 창(player_base)의 스타일시트 문자열 모음 — 데이터만 있고 코드는 없음 (Qt도 불러오지 않는 잎 모듈).

창 전체에 거는 어두운·밝은 테마 시트(DARK_STYLESHEET·LIGHT_STYLESHEET)와, 위젯 하나가 자기 시트로 거는 큰(10줄 이상) 인라인 시트들.
위젯 자신의 시트는 창 시트보다 우선이라 테마를 바꿔도 그대로 남음. 글자까지 같은 시트를 쓰던 위젯 둘 이상은(짧아도) 상수 하나를 함께 씀.
여러 줄 문자열은 줄 앞 공백(들여쓰기)·앞뒤 줄바꿈까지 값의 일부라, player_base에 있을 때 모양 그대로 둠 — 한 글자도 바꾸지 말 것
(창 시트는 시험이 해시로 지킴. 일부러 고칠 때는 그 값도 함께 바꾸고 이유를 커밋에 남김).
"""

# 어두운 테마 — 창을 만들 때 걸고 set_dark_theme가 다시 검
DARK_STYLESHEET = """
QMainWindow, QWidget {
    background: #232323;
    color: #e0e0e0;
    font-family: 'Segoe UI', 'Malgun Gothic', Arial, sans-serif;
    font-size: 12px;
}
QLabel {
    color: #e0e0e0;
}
QPushButton {
    background: #2d2d2d;
    border: 1px solid #444;
    border-radius: 6px;
    color: #fafafa;
    font-weight: 500;
    padding: 8px 16px;
}
QPushButton:hover {
    background: #353535;
    border: 1px solid #ff9900;
    color: #ff9900;
}
QPushButton:pressed {
    background: #1a1a1a;
    border: 1px solid #ff9900;
}
QPushButton:disabled {
    background: #232323;
    border: 1px solid #444;
    color: #555;
}
QComboBox {
    background: #2d2d2d;
    border: 1px solid #444;
    border-radius: 6px;
    padding: 6px 12px;
    color: #fafafa;
}
QComboBox:hover, QComboBox:focus {
    border: 1px solid #ff9900;
}
QComboBox QAbstractItemView {
    background: #232323;
    border: 1px solid #444;
    selection-background-color: #444;
    color: #fafafa;
}
QCheckBox {
    color: #e0e0e0;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #444;
    border-radius: 3px;
    background: #232323;
}
QCheckBox::indicator:checked {
    background: #ff9900;
    border: 2px solid #ff9900;
}
QListWidget, QListView, QMenu {
    background: #232323;
    border: 1px solid #444;
    color: #fafafa;
    selection-background-color: #444;
    selection-color: #ff9900;
}
QListWidget::item:selected, QListView::item:selected {
    background: #444;
    color: #ff9900;
}
QTabWidget::pane {
    border: none;
}
QTabBar::tab {
    background: #2d2d2d;
    border: 1px solid #444;
    border-radius: 6px;
    color: #e0e0e0;
    padding: 4px 14px;
    margin: 0px 2px 4px 0px;
}
QTabBar::tab:hover {
    border: 1px solid #ff9900;
    color: #ff9900;
}
QTabBar::tab:selected {
    background: #444;
    border: 1px solid #ff9900;
    color: #ff9900;
}
QSplitter::handle {
    background: #353535;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: #232323;
    border: 1px solid #444;
    border-radius: 6px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #444;
    border-radius: 6px;
    min-height: 20px;
    min-width: 20px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: #ff9900;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QSlider:horizontal {
    height: 20px;
    background: #232323;
}
QSlider::groove:horizontal {
    height: 8px;
    background: #353535;
    border: 1px solid #444;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    min-width: 80px;
    max-width: 80px;
    height: 20px;
    background: #ff9900;
    border: 2px solid #ff9900;
    border-radius: 10px;
    margin: -6px 0;
}
QSlider::handle:horizontal:hover {
    background: #ffaa33;
    border: 2px solid #ffaa33;
}
QSlider::handle:horizontal:pressed {
    background: #ff9900;
    border: 2px solid #ff9900;
}
QSlider::sub-page:horizontal {
    background: #ff9900;
    border-radius: 4px;
}
QSlider::add-page:horizontal {
    background: #353535;
    border-radius: 4px;
}
QMessageBox {
    background: #232323;
    color: #fafafa;
}
"""

# 밝은 테마 — set_light_theme가 걺
LIGHT_STYLESHEET = """
QMainWindow {
    background: #fafafa;
    color: #2c3e50;
    font-family: 'Segoe UI', 'Malgun Gothic', Arial, sans-serif;
    font-size: 12px;
}
QWidget {
    background: transparent;
    color: #2c3e50;
    font-family: 'Segoe UI', 'Malgun Gothic', Arial, sans-serif;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    color: #2c3e50;
    font-weight: 500;
    padding: 8px 16px;
    min-height: 20px;
}
QPushButton:hover {
    background: #f8f9fa;
    border: 1px solid #d0d0d0;
    color: #1a252f;
}
QPushButton:pressed {
    background: #e9ecef;
    border: 1px solid #c0c0c0;
}
QPushButton:disabled {
    background: #f8f9fa;
    border: 1px solid #e9ecef;
    color: #adb5bd;
}
QComboBox {
    background: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 6px 12px;
    color: #2c3e50;
    min-height: 20px;
}
QComboBox:hover {
    border: 1px solid #d0d0d0;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 4px solid #6c757d;
    margin-right: 5px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #e0e0e0;
    selection-background-color: #e9ecef;
    color: #2c3e50;
}
QCheckBox {
    color: #2c3e50;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #e0e0e0;
    border-radius: 3px;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #495057;
    border: 2px solid #495057;
    image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iOSIgdmlld0JveD0iMCAwIDEyIDkiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxwYXRoIGQ9Ik0xIDQuNUw0LjUgOEwxMSAxIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPgo8L3N2Zz4K);
}
QLabel {
    color: #2c3e50;
    font-weight: 400;
}
QListWidget {
    background: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    color: #2c3e50;
    selection-background-color: #e9ecef;
    outline: none;
}
QListWidget::item {
    padding: 6px;
    border-bottom: 1px solid #f8f9fa;
}
QListWidget::item:hover {
    background: #f8f9fa;
}
QListWidget::item:selected {
    background: #e9ecef;
    color: #2c3e50;
}
QTabWidget::pane {
    border: none;
}
QTabBar::tab {
    background: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    color: #2c3e50;
    padding: 4px 14px;
    margin: 0px 2px 4px 0px;
}
QTabBar::tab:hover {
    background: #f8f9fa;
    border: 1px solid #d0d0d0;
    color: #1a252f;
}
QTabBar::tab:selected {
    background: #e9ecef;
    border: 1px solid #adb5bd;
    color: #1a252f;
}
QSplitter::handle {
    background: #e0e0e0;
    border-radius: 1px;
}
QSplitter::handle:horizontal {
    width: 2px;
}
QSplitter::handle:vertical {
    height: 2px;
}
QScrollBar:vertical {
    background: #f8f9fa;
    width: 12px;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background: #adb5bd;
    border-radius: 6px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #6c757d;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QSlider:horizontal {
    height: 20px;
    background: transparent;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #e9ecef;
    border: 1px solid #dee2e6;
    border-radius: 3px;
    margin: 7px 0;
}
QSlider::handle:horizontal {
    min-width: 80px;
    max-width: 80px;
    height: 16px;
    background: #495057;
    border: 1px solid #343a40;
    border-radius: 8px;
    margin: -5px 0;
}
QSlider::handle:horizontal:hover {
    background: #6c757d;
    border: 1px solid #495057;
}
QSlider::handle:horizontal:pressed {
    background: #343a40;
    border: 1px solid #212529;
}
QSlider::sub-page:horizontal {
    background: #495057;
    border-radius: 3px;
}
QSlider::add-page:horizontal {
    background: #e9ecef;
    border-radius: 3px;
}
QMessageBox {
    background: #fafafa;
    color: #2c3e50;
}
"""


# playPauseButton (Play/Pause) — 밝은 테마의 QPushButton 규칙과 같은 글자. 재생 중에는 "background-color: yellow;"로 바뀌었다가 ""로 지워짐
PLAY_PAUSE_BUTTON_STYLE = """
QPushButton {
    background: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    color: #2c3e50;
    font-weight: 500;
    padding: 8px 16px;
    min-height: 20px;
}
QPushButton:hover {
    background: #f8f9fa;
    border: 1px solid #d0d0d0;
    color: #1a252f;
}
QPushButton:pressed {
    background: #e9ecef;
    border: 1px solid #c0c0c0;
}
"""


# stopButton (Stop)
STOP_BUTTON_STYLE = """
QPushButton {
    background: #6c757d;
    border: 1px solid #5a6268;
    border-radius: 6px;
    color: white;
    font-weight: 500;
    font-size: 14px;
    padding: 12px 24px;
    min-height: 20px;
}
QPushButton:hover {
    background: #5a6268;
    border: 1px solid #495057;
}
QPushButton:pressed {
    background: #495057;
    border: 1px solid #343a40;
}
"""


# 정보 줄: 파일 이름 라벨 filenameLabel
FILENAME_LABEL_STYLE = """
QLabel {
    background: #f8f9fa;
    border: 1px solid #e9ecef;
    border-radius: 6px;
    color: #495057;
    font-weight: 500;
    padding: 10px;
}
"""


# 정보 줄: 현재 프레임 라벨 labelFrameCount
FRAME_COUNT_LABEL_STYLE = """
QLabel {
    background: #e9ecef;
    border: 1px solid #dee2e6;
    border-radius: 6px;
    color: #495057;
    font-weight: 500;
    padding: 10px;
}
"""


# 정보 줄: 전체 프레임 라벨 labelTotalFrames
TOTAL_FRAMES_LABEL_STYLE = """
QLabel {
    background: #dee2e6;
    border: 1px solid #ced4da;
    border-radius: 6px;
    color: #495057;
    font-weight: 500;
    padding: 10px;
}
"""


# 정보 줄: 재생 FPS 라벨 labelPlaybackFPS
PLAYBACK_FPS_LABEL_STYLE = """
QLabel {
    background: #d1ecf1;
    border: 1px solid #bee5eb;
    border-radius: 6px;
    color: #0c5460;
    font-weight: 500;
    padding: 10px;
}
"""


# positionScroll의 처음 시트 — 밝은 테마의 QSlider 규칙 7개와 같은 글자. initUI가 뒤에서 POSITION_SCROLL_STYLE로 덮어 씀
POSITION_SCROLL_INITIAL_STYLE = """
QSlider:horizontal {
    height: 20px;
    background: transparent;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #e9ecef;
    border: 1px solid #dee2e6;
    border-radius: 3px;
    margin: 7px 0;
}
QSlider::handle:horizontal {
    min-width: 80px;
    max-width: 80px;
    height: 16px;
    background: #495057;
    border: 1px solid #343a40;
    border-radius: 8px;
    margin: -5px 0;
}
QSlider::handle:horizontal:hover {
    background: #6c757d;
    border: 1px solid #495057;
}
QSlider::handle:horizontal:pressed {
    background: #343a40;
    border: 1px solid #212529;
}
QSlider::sub-page:horizontal {
    background: #495057;
    border-radius: 3px;
}
QSlider::add-page:horizontal {
    background: #e9ecef;
    border-radius: 3px;
}
"""


# volumeSlider
VOLUME_SLIDER_STYLE = """
            QSlider::groove:horizontal {
                border: 1px solid #555;
                height: 8px;
                background: #333;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #ffae00;
                border: 1px solid #ffae00;
                width: 18px;
                height: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: #ffc850;
                border: 1px solid #ffc850;
            }
            QSlider::sub-page:horizontal {
                background: #ffae00;
                border-radius: 4px;
            }
        """


# OCR 분석 방식 라벨과 패턴 라벨 (둘이 같은 글자)
OCR_OPTION_LABEL_STYLE = "color: #e0e0e0; padding: 2px;"


# 사이드바 버튼: bookmarkButton
BOOKMARK_BUTTON_STYLE = """
QPushButton {
    background: #28a745;
    border: 1px solid #28a745;
    border-radius: 6px;
    color: white;
    font-weight: 500;
    padding: 8px 6px;
}
QPushButton:hover {
    background: #218838;
    border: 1px solid #1e7e34;
}
QPushButton:pressed {
    background: #1e7e34;
    border: 1px solid #1c7430;
}
"""


# 사이드바 버튼: bookmarkListButton과 refreshListButton (둘이 같은 글자)
BOOKMARK_LIST_REFRESH_BUTTON_STYLE = """
QPushButton {
    background: #17a2b8;
    border: 1px solid #17a2b8;
    border-radius: 6px;
    color: white;
    font-weight: 500;
    padding: 8px 6px;
}
QPushButton:hover {
    background: #138496;
    border: 1px solid #117a8b;
}
QPushButton:pressed {
    background: #117a8b;
    border: 1px solid #10707f;
}
"""


# 사이드바 버튼: workPathButton
WORK_PATH_BUTTON_STYLE = """
QPushButton {
    background: #6f42c1;
    border: 1px solid #6f42c1;
    border-radius: 6px;
    color: white;
    font-weight: 500;
    padding: 8px 6px;
}
QPushButton:hover {
    background: #5a32a3;
    border: 1px solid #5a32a3;
}
QPushButton:pressed {
    background: #4c2a8a;
    border: 1px solid #4c2a8a;
}
"""


# 사이드바 버튼: listModeButton
LIST_MODE_BUTTON_STYLE = """
QPushButton {
    background: #6f42c1;
    border: 1px solid #6f42c1;
    border-radius: 6px;
    color: white;
    font-weight: 500;
    padding: 8px 6px;
}
QPushButton:hover {
    background: #5a32a3;
    border: 1px solid #4c2b8a;
}
QPushButton:pressed {
    background: #4c2b8a;
    border: 1px solid #3d2375;
}
QPushButton:checked {
    background: #4c2b8a;
    border: 1px solid #3d2375;
}
"""


# 주석 모드 버튼: annotationModeButton — 켜짐만 빨강(비디오 위 '주석 모드' 배지와 같은 계열),
# 꺼진 모양·hover는 테마 시트 그대로 (위젯 시트는 적은 규칙만 덮음)
ANNOTATION_MODE_BUTTON_STYLE = """
QPushButton:checked {
    background: #c81e1e;
    border: 1px solid #a01818;
    color: white;
    font-weight: bold;
}
"""


# 사이드바 버튼: thumbnailModeButton
THUMBNAIL_MODE_BUTTON_STYLE = """
QPushButton {
    background: #fd7e14;
    border: 1px solid #fd7e14;
    border-radius: 6px;
    color: white;
    font-weight: 500;
    padding: 8px 6px;
}
QPushButton:hover {
    background: #e8690b;
    border: 1px solid #d55a00;
}
QPushButton:pressed {
    background: #d55a00;
    border: 1px solid #c05000;
}
QPushButton:checked {
    background: #d55a00;
    border: 1px solid #c05000;
}
"""


# timeLabel
TIME_LABEL_STYLE = """
QLabel {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #f39c12, stop:1 #e67e22);
    border: 1px solid #e67e22;
    border-radius: 6px;
    color: white;
    font-weight: bold;
    padding: 10px;
}
"""


# positionScroll의 마지막 시트
POSITION_SCROLL_STYLE = """
QSlider:horizontal {
    height: 20px;
    background: transparent;
}
QSlider::groove:horizontal {
    height: 8px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #34495e, stop:1 #2c3e50);
    border: 1px solid #7f8c8d;
    border-radius: 4px;
    margin: 6px 0;
}
QSlider::handle:horizontal {
    min-width: 80px;
    max-width: 80px;
    height: 20px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #3498db, stop:1 #2980b9);
    border: 2px solid #2980b9;
    border-radius: 10px;
    margin: -6px 0;
}
QSlider::handle:horizontal:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #5dade2, stop:1 #3498db);
    border: 2px solid #5dade2;
}
QSlider::handle:horizontal:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #2980b9, stop:1 #21618c);
    border: 2px solid #21618c;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #3498db, stop:1 #2980b9);
    border-radius: 4px;
}
QSlider::add-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #34495e, stop:1 #2c3e50);
    border-radius: 4px;
}
"""


# OCR 분석 진행 창의 로그(ocr_log_text 두 곳)와 내보내기 로그(ocr_export_log_text) — 셋이 같은 글자
OCR_LOG_TEXT_STYLE = """
            QPlainTextEdit {
                background: #1d1d1d;
                color: #ffa500;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 8px;
                font-family: 'Menlo', 'Monaco', Consolas, monospace;
                font-size: 11px;
            }
        """


# 오버레이: overlayFrame
OVERLAY_FRAME_STYLE = '''
            QFrame {
                background-color: rgba(0, 0, 0, 200);
                border: 3px solid white;
                border-radius: 10px;
            }
            QFrame:hover {
                border: 3px solid rgba(255, 255, 255, 180);
                background-color: rgba(0, 0, 0, 220);
            }
        '''


# 오버레이: overlayHelpLabel
OVERLAY_HELP_LABEL_STYLE = '''
            QLabel {
                color: rgba(255, 255, 255, 120);
                font-size: 10px;
                font-family: 'Arial', sans-serif;
                background: rgba(0, 0, 0, 100);
                padding: 2px 6px;
                border-radius: 3px;
                border: 1px solid rgba(255, 255, 255, 40);
            }
        '''


# 오버레이: overlayPlayPause
OVERLAY_PLAY_PAUSE_STYLE = '''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255, 255, 255, 40),
                    stop:1 rgba(255, 255, 255, 20));
                border: 2px solid rgba(255, 255, 255, 120);
                border-radius: 28px;
                color: white;
                font-size: 24px;
                font-weight: bold;
                font-family: 'Arial', sans-serif;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255, 255, 255, 60),
                    stop:1 rgba(255, 255, 255, 40));
                border: 2px solid rgba(255, 255, 255, 180);
                transform: scale(1.05);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255, 255, 255, 80),
                    stop:1 rgba(255, 255, 255, 60));
                border: 2px solid rgba(255, 255, 255, 200);
            }
        '''


# 오버레이: overlayStartFrameLabel과 overlayEndFrameLabel (둘이 같은 글자)
OVERLAY_FRAME_NUMBER_LABEL_STYLE = '''
            QLabel {
                color: rgba(255, 255, 255, 200);
                font-size: 13px;
                font-weight: 600;
                font-family: 'Arial', sans-serif;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(0, 0, 0, 120),
                    stop:1 rgba(0, 0, 0, 80));
                padding: 4px 10px;
                border-radius: 6px;
                border: 1px solid rgba(255, 255, 255, 60);
            }
        '''


# 오버레이: overlayCurrentFrameLabel
OVERLAY_CURRENT_FRAME_LABEL_STYLE = '''
            QLabel {
                color: rgba(255, 255, 255, 255);
                font-size: 16px;
                font-weight: bold;
                font-family: 'Arial', sans-serif;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(0, 150, 255, 180),
                    stop:1 rgba(0, 120, 200, 160));
                padding: 6px 12px;
                border-radius: 8px;
                border: 2px solid rgba(255, 255, 255, 120);
                box-shadow: 0 2px 8px rgba(0, 150, 255, 0.4);
            }
        '''


# 오버레이: overlayFileNameLabel의 처음 시트 (font-size 20px). 파일 이름이 정해지면 아래 템플릿으로 바뀜 — 들여쓰기가 달라 같은 글자가 아님
OVERLAY_FILE_NAME_LABEL_STYLE = '''
            QLabel {
                color: rgba(255, 255, 255, 180);
                font-size: 20px;
                font-weight: 600;
                font-family: 'Arial', sans-serif;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(0, 0, 0, 100),
                    stop:1 rgba(0, 0, 0, 60));
                padding: 4px 10px;
                border-radius: 4px;
                border: 1px solid rgba(255, 255, 255, 40);
                min-width: 80px;
            }
        '''


# 오버레이: overlaySlider
OVERLAY_SLIDER_STYLE = '''
            QSlider::groove:horizontal {
                border: none;
                height: 12px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255, 255, 255, 30),
                    stop:1 rgba(255, 255, 255, 10));
                border-radius: 6px;
                margin: 0px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255, 255, 255, 220),
                    stop:1 rgba(255, 255, 255, 180));
                border: 3px solid rgba(255, 255, 255, 150);
                width: 24px;
                height: 24px;
                border-radius: 12px;
                margin: -6px 0;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
            }
            QSlider::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255, 255, 255, 255),
                    stop:1 rgba(255, 255, 255, 220));
                border: 3px solid rgba(255, 255, 255, 200);
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
            }
            QSlider::handle:horizontal:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255, 255, 255, 255),
                    stop:1 rgba(255, 255, 255, 240));
                border: 3px solid rgba(255, 255, 255, 250);
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(0, 180, 255, 200),
                    stop:1 rgba(0, 150, 220, 180));
                border-radius: 6px;
                margin: 0px;
            }
        '''


# 오버레이: overlayVolume
OVERLAY_VOLUME_STYLE = '''
            QScrollBar:horizontal {
                border: none;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255, 255, 255, 30),
                    stop:1 rgba(255, 255, 255, 10));
                height: 12px;
                border-radius: 6px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(0, 220, 120, 200),
                    stop:1 rgba(0, 180, 100, 180));
                border: 2px solid rgba(255, 255, 255, 120);
                min-width: 24px;
                border-radius: 6px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(0, 240, 140, 220),
                    stop:1 rgba(0, 200, 120, 200));
                border: 2px solid rgba(255, 255, 255, 150);
            }
            QScrollBar::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(0, 200, 100, 150),
                    stop:1 rgba(0, 160, 80, 130));
                border-radius: 6px;
                margin: 0px;
            }
        '''


# 오버레이: overlayFileNameLabel — 파일 이름 길이에 따라 font-size를 바꾸는 템플릿. `.format(font_size=…)`로 채움 (CSS의 중괄호는 {{ }})
OVERLAY_FILE_NAME_LABEL_STYLE_TEMPLATE = '''
                    QLabel {{
                        color: rgba(255, 255, 255, 180);
                        font-size: {font_size}px;
                        font-weight: 600;
                        font-family: 'Arial', sans-serif;
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 rgba(0, 0, 0, 100),
                            stop:1 rgba(0, 0, 0, 60));
                        padding: 4px 10px;
                        border-radius: 4px;
                        border: 1px solid rgba(255, 255, 255, 40);
                        min-width: 80px;
                    }}
                '''
