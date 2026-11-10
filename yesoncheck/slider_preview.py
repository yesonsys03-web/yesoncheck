# -*- coding: utf-8 -*-
"""슬라이더 호버 썸네일의 화면 쪽 — 커서 위 작은 창(SliderPreviewPopup)·마우스 x → 슬라이더 값(slider_value_at)·호버 필터(SliderHoverFilter).

왜: 시간 슬라이더 위에 커서를 올리면 그 자리 프레임의 그림과 번호가 커서 위에 떠서 커서를 따라 움직인다. 이 모듈은 '보이기'만 맡는다 —
어떤 프레임인지(프레임 변환)·그림을 어디서 꺼내는지(띠 저장소)·디코드·파일 읽기는 하나도 모른다. 필터는 슬라이더 값을 부른 쪽이 준 lookup(value)에
넘기고, 그 대답(None = 숨김, 아니면 (번호 글, 그림|None))을 창에 그릴 뿐이다. 슬라이더마다 값 → 프레임 식이 달라서 변환은 부른 쪽의 몫이다.

x → 값은 Qt의 QSliderPrivate::pixelPosToRangeValue 식을 **그대로** 쓴다 (slider_value_at). 이 앱의 시트는 핸들 폭이 subControlRect에서 -1로 나오기도 하고
(slider_style 설명) 오버레이는 30이라, 핸들 폭을 0으로 막거나 핸들 반을 빼는 식으로 '그럴듯하게' 고치면 클릭이 착지하는 값과 어긋난다
(측정: 그런 식은 900칸 중 162·333칸이 틀렸고 Qt 식은 0칸). 호버 그림의 프레임이 클릭하면 실제로 가는 프레임과 같아야 하므로 Qt가 클릭 때 쓰는 식과 같아야 한다.

eventFilter는 PyQt5 가상 함수라 거기서 빠져나간 예외는 qFatal(프로세스 종료, 오류 창 없음)이다. 호버는 마우스가 움직일 때마다 불려 lookup이 던진 예외 하나로
앱이 죽으면 안 되므로, 본문 전체를 try/except로 감싸 창을 숨기고 이벤트는 그대로 흘려보낸다. 알림은 필터마다 처음 한 번만 error_window.report_from_handler
(트레이스백 전부 기록 + 오류 창)이고, 그 뒤로는 창 없이 기록(stderr) 한 줄씩(예외 종류·글) — lookup의 버그 하나로 마우스가 움직일 때마다 창이 쌓이지 않게,
그래도 조용히 넘기지는 않게. 필터는 늘 False를 돌려줘 슬라이더의 기본 처리(클릭·드래그)를 막지 않는다.
"""

import sys
from typing import Callable, Optional, Tuple

import numpy as np
from PyQt5.QtCore import QEvent, QObject, QPoint, Qt
from PyQt5.QtGui import QGuiApplication, QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QSlider, QStyle, QStyleOptionSlider, QVBoxLayout, QWidget

from yesoncheck import error_window
from yesoncheck.hover_strip import LOG_PREFIX

GAP = 8  # 창과 슬라이더 사이 간격(px) — 창의 아래 끝이 슬라이더 위 끝에서 이만큼 위 (위가 모자라면 슬라이더 아래 끝에서 이만큼 아래)

ERROR_CONTEXT = "슬라이더 호버 처리 중 오류"  # eventFilter 예외의 기록·창 글 (모듈 설명)

LookupResult = Optional[Tuple[str, Optional[np.ndarray]]]

# 인라인 스타일만 — main_window_styles.py의 시트는 건드리지 않는다. parent가 플레이어 창이면(Mac·Linux — popup_parent) 앱 창의 시트가 내려오지만, 여기서 정한
# 속성(배경·테두리·글자 색·크기·굵기)은 이 시트가 가까워 이긴다 — 내려오는 것은 정하지 않은 글꼴 종류뿐(창의 다른 글자와 같은 목록, 어두운·
# 밝은 테마 모두 같음 — 시험이 두 테마에서 배경·테두리·글자 색을 확인)
_POPUP_STYLE = """
#sliderPreviewPopup { background: #1e1e1e; border: 1px solid #8a8a8a; }
#sliderPreviewImage { background: transparent; border: none; }
#sliderPreviewNumber { background: transparent; border: none; color: white; font-size: 22px; font-weight: bold; }
"""


def slider_value_at(slider: QSlider, x: int) -> int:
    """슬라이더 좌표의 x(px)를 슬라이더 값으로 — Qt QSliderPrivate::pixelPosToRangeValue와 같은 식 (모듈 설명: 클릭이 착지하는 값과 같다).

    핸들 폭이 -1이어도 보정하지 않고 핸들 반을 빼지도 않는다. 범위 밖 x는 최솟값·최댓값으로 붙는다 (sliderValueFromPosition).
    가로 슬라이더 전용 — 세로 슬라이더는 y축 식이 달라 이 함수로는 맞지 않는다."""
    opt = QStyleOptionSlider()
    slider.initStyleOption(opt)
    style = slider.style()
    groove = style.subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, slider)
    handle = style.subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, slider)
    center = handle.center() - handle.topLeft()
    pos = x - center.x() - groove.x()
    span = groove.right() - handle.width() + 1 - groove.x()
    return QStyle.sliderValueFromPosition(slider.minimum(), slider.maximum(), pos, span, opt.upsideDown)


def popup_parent(window: QWidget) -> QWidget:
    """SliderPreviewPopup에 줄 parent — Qt5 QToolTip(qtooltip.cpp)과 같은 플랫폼 분기.

    Windows: 그 창이 있는 화면의 desktop screen 위젯. qtooltip.cpp의 Win32 주석대로 위젯을 parent로 쓰면 툴팁이 뜰 때 그 창이 앞으로
    올라온다(raise) — 가려진·비활성 창의 슬라이더에 호버만 해도 창이 튀어나오면 안 된다. 단 Qt 5의 QWidget은 Desktop 종류 parent를 화면을
    고르는 데만 쓰고 parent는 비운다(실측: 팝업의 parent()가 None — QToolTip의 Win32 QTipLabel도 같음). 그래서 Windows의 팝업은 parent 없는
    최상위 창이고 Python이 가진다(창과 함께 지워지지 않음 — 그래서 창을 닫을 때 부른 쪽이 바로 지운다: player_hover_thumbs._hover_thumbs_destroy).
    그 밖(Mac·Linux): window 자신 — 창과 함께 지워짐. sys.platform은 부를 때 읽는다(시험이 바꿔 끼움)."""
    if sys.platform == "win32":
        desktop = QApplication.desktop()
        return desktop.screen(desktop.screenNumber(window))
    return window


class SliderPreviewPopup(QWidget):
    """커서 위에 뜨는 작은 창 — 그림(고정 크기 상자) 아래 번호. 포커스를 가져가지 않는다 (ToolTip 창 + 활성화 없이 보임 + 포커스 없음).

    그림이 없으면(None) 상자는 비우고 크기는 그대로 둔다 — 아직 안 만든 자리에서도 번호는 보이고 창이 들쭉날쭉 변하지 않는다.

    parent: popup_parent(창)로 고를 것 (플랫폼 분기 — 위의 popup_parent). Qt.ToolTip은 창 종류 플래그라 parent가 있어도 따로 뜨는 최상위 창이고
    (isWindow 그대로) place_above의 move는 그대로 화면 좌표다. 위젯 parent가 있으면 그 창이 지워질 때 함께 지워진다 — parent 없는 최상위 창은
    인터프리터가 끝날 때 QApplication보다 늦게 지워져 종료 순서가 꼬일 수 있다는 리뷰 가설(이 Mac 종료 세그폴트 플레이크 18/24 → 7/24로 줄었음)."""

    def __init__(self, thumb_width: int, thumb_height: int, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setObjectName("sliderPreviewPopup")
        self.setAttribute(Qt.WA_StyledBackground, True)  # QWidget 자체는 시트의 배경·테두리를 이 속성이 있어야 그림
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet(_POPUP_STYLE)

        self.image_label = QLabel(self)
        self.image_label.setObjectName("sliderPreviewImage")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.number_label = QLabel(self)
        self.number_label.setObjectName("sliderPreviewNumber")
        self.number_label.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(self.image_label)
        layout.addWidget(self.number_label)
        self.set_thumb_size(thumb_width, thumb_height)

    def set_thumb_size(self, width: int, height: int) -> None:
        """새 띠 계획의 그림 크기로 — 그림 라벨을 이 크기로 고정하고 창을 그에 맞춤 (가로 영상 ↔ 세로 영상 전환)."""
        self.image_label.setFixedSize(width, height)
        self.adjustSize()

    def show_frame(self, number_text: str, image: Optional[np.ndarray]) -> None:
        """번호 글과 그림을 바꾸고 창을 새 내용에 맞춤 (번호 글이 그림 폭보다 넓으면 늘고, 짧아지면 다시 줄어듦 — place_above는 이 뒤에 부를 것).

        image는 (h, w, 3) uint8 RGB 연속 배열, None이면 빈 상자. 배열은 다른 스레드가 쓰는 버퍼의 보기일 수 있어 QImage를 .copy()해서 쥔다
        (원본을 가리킨 채로 두지 않음). 모양이 다르면 아무것도 바꾸기 전에 ValueError — 연속이 아닌 배열을 QImage에 그대로 넘기면 엉뚱한
        바이트를 읽고, 번호만 바뀌고 그림은 낡은 채로 남아서도 안 된다."""
        if image is not None:
            if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8 or not image.flags["C_CONTIGUOUS"]:
                raise ValueError(
                    f"그림은 (h, w, 3) uint8 연속 RGB 배열이어야 합니다: shape={image.shape} dtype={image.dtype} "
                    f"연속={image.flags['C_CONTIGUOUS']}"
                )
        self.number_label.setText(number_text)
        if image is None:
            self.image_label.clear()
        else:
            height, width = image.shape[:2]
            qimage = QImage(image.data, width, height, width * 3, QImage.Format_RGB888).copy()
            self.image_label.setPixmap(QPixmap.fromImage(qimage))
        self.adjustSize()

    def place_above(self, slider: QSlider, x: int) -> None:
        """창을 슬라이더 좌표 x(커서)에 가로 가운데로, 아래 끝은 슬라이더 위 끝에서 GAP 위로 — 커서가 있는 화면의 쓸 수 있는 영역 안으로 밀어 넣음.

        위에 들어갈 자리가 없으면 슬라이더 아래 끝에서 GAP 아래로. (show_frame이 창 크기를 맞춘 뒤에 부를 것.) 화면은 커서 자리(슬라이더 세로
        가운데)의 QGuiApplication.screenAt — 모니터가 둘이고 앱 창이 걸쳐 있으면 slider.screen()(창이 속한 화면 하나)은 커서 쪽이 아닐 수 있음;
        어느 화면에도 없으면(None) slider.screen()."""
        cursor = slider.mapToGlobal(QPoint(x, slider.height() // 2))
        available = (QGuiApplication.screenAt(cursor) or slider.screen()).availableGeometry()
        slider_top = slider.mapToGlobal(QPoint(0, 0)).y()
        cursor_x = cursor.x()

        left = cursor_x - self.width() // 2
        top = slider_top - GAP - self.height()
        if top < available.top():
            top = slider_top + slider.height() + GAP
        left = max(available.left(), min(left, available.right() + 1 - self.width()))
        top = max(available.top(), min(top, available.bottom() + 1 - self.height()))
        self.move(left, top)


class SliderHoverFilter(QObject):
    """슬라이더에 커서가 올라오면 popup을 띄워 그 자리의 프레임을 보이고 커서를 따라가게 하는 이벤트 필터 (모듈 설명).

    lookup(value)는 **슬라이더 값**을 받아 None(숨김) 또는 (번호 글, (h, w, 3) uint8 RGB 그림|None)을 돌려준다 — 값 → 프레임 변환은 부른 쪽의 몫.
    슬라이더가 창 계층에 들어간 뒤에 만들 것 (slider.window()에도 걸어 창이 비활성이 되면 숨기므로).
    수명 주의: 호출부가 이 필터의 참조를 쥐거나 parent를 줄 것 — Qt는 설치된 이벤트 필터를 붙잡아 주지 않는다
    (parent=None으로 만들고 변수에 안 담으면 필터가 지워져 호버가 오류 없이 죽는다). 창을 지우기 전에 detach()로 떼고 창 참조를 끊을 것."""

    def __init__(
        self,
        slider: QSlider,
        lookup: Callable[[int], LookupResult],
        popup: SliderPreviewPopup,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._slider = slider
        self._lookup = lookup
        self._popup = popup
        self._reported = False  # eventFilter 예외를 창으로 알렸음 (처음 한 번만 — 모듈 설명)
        self._drawn = None  # 마지막으로 그린 (번호 글, 그림 데이터 주소|None) — 같으면 다시 그리지 않음 (_show_at)
        self._window = slider.window()  # 설치한 창 (detach가 같은 창에서 뗌)
        slider.setMouseTracking(True)  # 버튼을 안 눌러도 MouseMove가 와야 함
        slider.installEventFilter(self)
        self._window.installEventFilter(self)

    def detach(self) -> None:
        """생성자가 설치한 두 곳(슬라이더·그때의 slider.window())에서 떼고 창 참조를 끊음 — 그 뒤로 eventFilter는 아무것도 안 하고 False
        (지운 창을 만지지 않게). 여러 번 불러도 됨. 창을 닫을 때(player_hover_thumbs._hover_thumbs_destroy) 창을 지우기 전에 부름."""
        if self._popup is None:
            return
        self._slider.removeEventFilter(self)
        self._window.removeEventFilter(self)
        self._popup = None

    def eventFilter(self, watched, event):
        """슬라이더의 Enter·MouseMove → 보이기/갱신, Leave·MouseButtonPress·Hide와 창의 WindowDeactivate → 숨기기. 늘 False (기본 처리 그대로).
        detach() 뒤에는 아무것도 하지 않음."""
        if self._popup is None:
            return False
        try:
            kind = event.type()
            if kind == QEvent.WindowDeactivate:
                self._popup.hide()
            elif watched is self._slider:
                if kind in (QEvent.Enter, QEvent.MouseMove):
                    self._show_at(event.pos().x())
                elif kind in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.Hide):
                    self._popup.hide()
        except BaseException as exc:
            if self._popup is not None:
                self._popup.hide()  # 낡은 그림이 남지 않게 (오류는 아래에서 보임)
            if not self._reported:
                self._reported = True
                error_window.report_from_handler(LOG_PREFIX, ERROR_CONTEXT)
            else:  # 창은 처음 한 번만 — 그 뒤로는 기록 한 줄씩 (조용히 넘기지 않음)
                print(f"{LOG_PREFIX} {ERROR_CONTEXT} (되풀이 — 트레이스백·오류 창은 처음 한 번만): {type(exc).__name__}: {exc}",
                      file=sys.stderr, flush=True)
        return False

    def _show_at(self, x: int) -> None:
        """슬라이더 좌표 x의 값으로 lookup → 창을 그리고 커서 위에 놓아 보임. 끌고 있을 때·lookup이 None이면 숨김.

        MouseMove마다 다시 그리지 않는다: (번호 글, 그림 데이터의 주소)가 이 필터가 마지막으로 그린 것과 같고 창이 떠 있으면 show_frame(QImage
        복사·adjustSize)을 건너뛰고 자리만 옮김. 그림은 객체가 아니라 데이터 주소로 본다 — 띠의 image(i)는 부를 때마다 새 뷰 객체지만 같은 행은
        같은 주소이고, 한 띠 안에서 행은 한 번만 채워짐(hover_strip). 창이 숨어 있었으면 늘 다시 그림 — 파일을 바꿀 때(띠를 버리면 창을 숨김)
        새 띠가 옛 주소를 물려받아도 옛 그림이 남지 않고, 두 필터가 창 하나를 나눠 써도 그 사이엔 Leave로 숨음."""
        if self._slider.isSliderDown():
            self._popup.hide()
            return
        result = self._lookup(slider_value_at(self._slider, x))
        if result is None:
            self._popup.hide()
            return
        number_text, image = result
        drawn = (number_text, None if image is None else image.__array_interface__["data"][0])
        if drawn != self._drawn or not self._popup.isVisible():
            self._popup.show_frame(number_text, image)
            self._drawn = drawn  # show_frame이 거부(ValueError)하면 바꾸지 않음
        self._popup.place_above(self._slider, x)
        self._popup.show()
