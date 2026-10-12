"""Custom Qt style helpers."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QProxyStyle, QStyle
from PyQt5.QtWidgets import QStyleOptionSlider


class FixedHandleStyle(QProxyStyle):
    def __init__(self, base_style=None, handle_width=80):
        super().__init__(base_style)
        self.handle_width = handle_width

    def subControlRect(self, cc, opt, sc, widget=None):
        rect = super().subControlRect(cc, opt, sc, widget)
        if (
            cc == QStyle.CC_ScrollBar
            and sc == QStyle.SC_ScrollBarSlider
            and isinstance(opt, QStyleOptionSlider)
        ):
            if opt.orientation == Qt.Horizontal:
                rect.setWidth(self.handle_width)
        return rect
