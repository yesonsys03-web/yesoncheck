# -*- coding: utf-8 -*-
"""슬라이더 호버 썸네일의 화면 쪽 — 커서 위 작은 창(SliderPreviewPopup)·마우스 x → 슬라이더 값(slider_value_at)·호버 필터(SliderHoverFilter).

왜: 시간 슬라이더 위에 커서를 올리면 그 자리 프레임의 그림과 번호가 커서 위에 떠서 커서를 따라 움직인다. 이 모듈은 '보이기'만 맡는다 —
어떤 프레임인지(프레임 변환)·그림을 어디서 꺼내는지(띠 저장소)·디코드·파일 읽기는 하나도 모른다. 필터는 슬라이더 값을 부른 쪽이 준 lookup(value)에
넘기고, 그 대답(None = 숨김, 아니면 (번호 글, 그림|None))을 창에 그릴 뿐이다. 슬라이더마다 값 → 프레임 식이 달라서 변환은 부른 쪽의 몫이다.

x → 값은 Qt의 QSliderPrivate::pixelPosToRangeValue 식을 **그대로** 쓴다 (slider_value_at). 이 앱의 시트는 핸들 폭이 subControlRect에서 -1로 나오기도 하고
(slider_style 설명) 오버레이는 30이라, 핸들 폭을 0으로 막거나 핸들 반을 빼는 식으로 '그럴듯하게' 고치면 클릭이 착지하는 값과 어긋난다
(측정: 그런 식은 900칸 중 162·333칸이 틀렸고 Qt 식은 0칸). 호버 그림의 프레임이 클릭하면 실제로 가는 프레임과 같아야 하므로 Qt가 클릭 때 쓰는 식과 같아야 한다.

eventFilter는 PyQt5 가상 함수라 거기서 빠져나간 예외는 qFatal(프로세스 종료, 오류 창 없음)이다. 호버는 마우스가 움직일 때마다 불려 lookup이 던진 예외 하나로
앱이 죽으면 안 되므로, 본문 전체를 try/except로 감싸 error_window.report_from_handler로 기록(트레이스백 전부)·오류 창에 알리고 이벤트는 그대로 흘려보낸다
(삼키지 않음 — 조용한 실패가 아니라 보이는 실패). 필터는 늘 False를 돌려줘 슬라이더의 기본 처리(클릭·드래그)를 막지 않는다.
"""

from typing import Callable, Optional, Tuple

import numpy as np
from PyQt5.QtCore import QEvent, QObject, QPoint, Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QLabel, QSlider, QStyle, QStyleOptionSlider, QVBoxLayout, QWidget

from yesoncheck import error_window

GAP = 8  # 창과 슬라이더 사이 간격(px) — 창의 아래 끝이 슬라이더 위 끝에서 이만큼 위 (위가 모자라면 슬라이더 아래 끝에서 이만큼 아래)

LookupResult = Optional[Tuple[str, Optional[np.ndarray]]]

# 인라인 스타일만 — main_window_styles.py의 시트는 건드리지 않는다. 창은 부모 없는 최상위 창이라 앱 창의 시트가 내려오지도 않음
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


class SliderPreviewPopup(QWidget):
    """커서 위에 뜨는 작은 창 — 그림(고정 크기 상자) 아래 번호. 포커스를 가져가지 않는다 (ToolTip 창 + 활성화 없이 보임 + 포커스 없음).

    그림이 없으면(None) 상자는 비우고 크기는 그대로 둔다 — 아직 안 만든 자리에서도 번호는 보이고 창이 들쭉날쭉 변하지 않는다."""

    def __init__(self, thumb_width: int, thumb_height: int):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
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
        """창을 슬라이더 좌표 x(커서)에 가로 가운데로, 아래 끝은 슬라이더 위 끝에서 GAP 위로 — 화면의 쓸 수 있는 영역 안으로 밀어 넣음.

        위에 들어갈 자리가 없으면 슬라이더 아래 끝에서 GAP 아래로. (show_frame이 창 크기를 맞춘 뒤에 부를 것.)"""
        available = slider.screen().availableGeometry()
        slider_top = slider.mapToGlobal(QPoint(0, 0)).y()
        cursor_x = slider.mapToGlobal(QPoint(x, 0)).x()

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
    (parent=None으로 만들고 변수에 안 담으면 필터가 지워져 호버가 오류 없이 죽는다)."""

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
        slider.setMouseTracking(True)  # 버튼을 안 눌러도 MouseMove가 와야 함
        slider.installEventFilter(self)
        slider.window().installEventFilter(self)

    def eventFilter(self, watched, event):
        """슬라이더의 Enter·MouseMove → 보이기/갱신, Leave·MouseButtonPress·Hide와 창의 WindowDeactivate → 숨기기. 늘 False (기본 처리 그대로)."""
        try:
            kind = event.type()
            if kind == QEvent.WindowDeactivate:
                self._popup.hide()
            elif watched is self._slider:
                if kind in (QEvent.Enter, QEvent.MouseMove):
                    self._show_at(event.pos().x())
                elif kind in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.Hide):
                    self._popup.hide()
        except BaseException:
            self._popup.hide()  # 낡은 그림이 남지 않게 (오류는 아래에서 보임)
            error_window.report_from_handler("[슬라이더 썸네일]", "슬라이더 호버 처리 중 오류")
        return False

    def _show_at(self, x: int) -> None:
        """슬라이더 좌표 x의 값으로 lookup → 창을 그리고 커서 위에 놓아 보임. 끌고 있을 때·lookup이 None이면 숨김."""
        if self._slider.isSliderDown():
            self._popup.hide()
            return
        result = self._lookup(slider_value_at(self._slider, x))
        if result is None:
            self._popup.hide()
            return
        number_text, image = result
        self._popup.show_frame(number_text, image)
        self._popup.place_above(self._slider, x)
        self._popup.show()
