"""시간 슬라이더를 모든 플랫폼에서 '클릭한 위치로 바로 이동 + 그 자리에서 드래그 계속'하게 만듦.

macOS에서는 QStyle.SH_Slider_AbsoluteSetButtons 힌트가 Qt.LeftButton을 포함해서,
슬라이더 트랙(홈)의 아무 곳이나 왼쪽 클릭하면 핸들이 그 위치로 즉시 이동하고 그대로 드래그가
이어진다. Windows의 기본 스타일(그리고 Fusion)에서는 이 힌트가 Qt.MiddleButton만 포함해서,
왼쪽 클릭은 그냥 페이지 스텝(pageStep)만큼만 움직인다 — 이 앱의 핸들 스타일시트는
min-width/max-width가 커서 핸들의 실제 폭이 -1로 계산되어(subControlRect) 잡을 핸들 자체가
없고, 그래서 Windows에서는 슬라이더를 드래그하거나 클릭으로 이동할 방법이 없어진다.

이 모듈은 QProxyStyle로 SH_Slider_AbsoluteSetButtons 힌트만 가로채 macOS와 같은 값
(Qt.LeftButton | Qt.MiddleButton)을 돌려주고, 나머지는 모두 기존 스타일(및 스타일시트)에
그대로 넘긴다. 슬라이더의 스타일시트나 생김새는 건드리지 않는다.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QProxyStyle, QStyle


class _JumpToClickSliderStyle(QProxyStyle):
    """SH_Slider_AbsoluteSetButtons만 macOS와 같게 바꾸고 나머지는 base style에 그대로 위임."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_Slider_AbsoluteSetButtons:
            return int(Qt.LeftButton | Qt.MiddleButton)
        return super().styleHint(hint, option, widget, returnData)


def jump_to_click(slider):
    """슬라이더에 '클릭한 위치로 바로 이동' 동작을 적용 (Mac에서는 이미 되던 동작과 동일).

    QProxyStyle()을 base 스타일 없이 만들어 애플리케이션 스타일을 그대로 쓰게 하고(소유권은
    가져가지 않음), slider.setStyle(...)로 적용한 뒤 슬라이더의 스타일시트를 다시 적용해
    위젯 스타일시트(QStyleSheetStyle)가 바뀐 스타일 위에서도 손 가는 모양 그대로 보이게 한다.

    proxy 객체는 파이썬 쪽에서 GC되면 Qt가 들고 있는 포인터가 끊겨 죽을 수 있으므로,
    슬라이더에 참조를 보관해 슬라이더가 살아있는 동안 함께 산다. 여러 번 호출해도 안전
    (마지막 호출의 proxy만 유지됨).
    """
    proxy = _JumpToClickSliderStyle()
    slider._jump_to_click_proxy_style = proxy  # GC 방지용 참조 보관
    slider.setStyle(proxy)
    stylesheet = slider.styleSheet()
    if stylesheet:
        # setStyle() 이후에도 위젯 스타일시트가 똑같이 그려지도록 다시 적용
        slider.setStyleSheet(stylesheet)
    return proxy
