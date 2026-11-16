"""재생 줄의 아이콘 — QPainter로 직접 그린 한 색 그림 (글꼴·이모지에 기대지 않음: 플랫폼마다 글리프가 다르거나 없음).

`pixmap(종류, 색, 크기, dpr)`은 투명 바탕에 그 색 하나로 그린다. 테마가 바뀌면 부르는 쪽이 새 색으로 다시 만든다.
종류: first(|◀ 처음) · prev(◀| 한 장 뒤) · play(▶) · pause(❙❙) · next(|▶ 한 장 앞) · last(▶| 끝) · loop(둥근 화살표) · volume(스피커)
· wipe(세로로 나뉜 사각형 — A|B 와이프) · annotate(연필 — 주석) · ocr(모서리 표시 안의 글자 줄).
"""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

KINDS = ("first", "prev", "play", "pause", "next", "last", "loop", "volume", "wipe", "annotate", "ocr")
ICON_DPR = 2.0  # 아이콘은 Retina에서도 또렷하게 2배로 그려 둠 (보이는 크기는 size)


def _triangle(painter, s, base_x, tip_x):
    painter.drawPolygon(QPolygonF([QPointF(base_x, s * 0.2), QPointF(base_x, s * 0.8), QPointF(tip_x, s * 0.5)]))


def _bar(painter, s, x, width=None):
    painter.drawRect(QRectF(x, s * 0.2, s * 0.13 if width is None else width, s * 0.6))


def _draw(painter, kind, colour, s):
    if kind == "play":
        _triangle(painter, s, s * 0.28, s * 0.84)
    elif kind == "pause":
        _bar(painter, s, s * 0.26, s * 0.18)
        _bar(painter, s, s * 0.56, s * 0.18)
    elif kind == "first":  # |◀
        _bar(painter, s, s * 0.16)
        _triangle(painter, s, s * 0.84, s * 0.34)
    elif kind == "prev":  # ◀|
        _triangle(painter, s, s * 0.66, s * 0.16)
        _bar(painter, s, s * 0.72)
    elif kind == "next":  # |▶
        _bar(painter, s, s * 0.15)
        _triangle(painter, s, s * 0.34, s * 0.84)
    elif kind == "last":  # ▶|
        _triangle(painter, s, s * 0.16, s * 0.66)
        _bar(painter, s, s * 0.71)
    elif kind == "loop":
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(colour, s * 0.11, Qt.SolidLine, Qt.RoundCap))
        path = QPainterPath()
        rect = QRectF(s * 0.18, s * 0.26, s * 0.64, s * 0.48)
        path.arcMoveTo(rect, 35)
        path.arcTo(rect, 35, 290)
        painter.drawPath(path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        painter.drawPolygon(QPolygonF([QPointF(s * 0.66, s * 0.14), QPointF(s * 0.9, s * 0.3), QPointF(s * 0.64, s * 0.44)]))
    elif kind == "volume":
        painter.drawPolygon(QPolygonF([QPointF(s * 0.12, s * 0.38), QPointF(s * 0.3, s * 0.38), QPointF(s * 0.52, s * 0.18),
                                       QPointF(s * 0.52, s * 0.82), QPointF(s * 0.3, s * 0.62), QPointF(s * 0.12, s * 0.62)]))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(colour, s * 0.09, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(QRectF(s * 0.46, s * 0.3, s * 0.3, s * 0.4), -60 * 16, 120 * 16)
        painter.drawArc(QRectF(s * 0.44, s * 0.16, s * 0.48, s * 0.68), -60 * 16, 120 * 16)
    elif kind == "wipe":  # 왼쪽 반은 채움(A), 오른쪽 반은 테두리만(B), 가운데에 나누는 선
        u = s / 18.0  # 18px에서 픽셀에 맞는 눈금
        painter.drawRect(QRectF(2 * u, 4 * u, 7 * u, 10 * u))
        painter.drawRect(QRectF(8.5 * u, 2 * u, 1 * u, 14 * u))
        painter.setBrush(Qt.NoBrush)
        pen = QPen(colour, 1.4 * u)
        pen.setJoinStyle(Qt.MiterJoin)
        painter.setPen(pen)
        painter.drawRect(QRectF(9 * u, 4.7 * u, 6.3 * u, 8.6 * u))
    elif kind == "annotate":  # 연필 — 오른쪽 위에서 왼쪽 아래(촉)로
        u = s / 18.0
        painter.drawPolygon(QPolygonF([QPointF(12 * u, 2 * u), QPointF(16 * u, 6 * u), QPointF(8 * u, 14 * u),
                                       QPointF(2 * u, 16 * u), QPointF(4 * u, 10 * u)]))
    elif kind == "ocr":  # 읽을 영역의 네 모서리 표시 + 그 안의 글자 두 줄
        u = s / 18.0
        low, high, arm, thick = 2 * u, 16 * u, 5 * u, 2 * u
        for x, y in ((low, low), (high - arm, low), (low, high - thick), (high - arm, high - thick)):
            painter.drawRect(QRectF(x, y, arm, thick))  # 가로 획
        for x, y in ((low, low), (high - thick, low), (low, high - arm), (high - thick, high - arm)):
            painter.drawRect(QRectF(x, y, thick, arm))  # 세로 획
        painter.drawRect(QRectF(6 * u, 7 * u, 6 * u, 2 * u))
        painter.drawRect(QRectF(6 * u, 10 * u, 4 * u, 1.5 * u))


def pixmap(kind, color, size=18, dpr=1.0):
    """종류의 그림 — 보이는 크기 size×size, 픽셀은 그 dpr배. 모르는 종류는 ValueError(그리기 전에)."""
    if kind not in KINDS:
        raise ValueError(f"모르는 아이콘 종류: {kind!r} (쓸 수 있는 값: {', '.join(KINDS)})")
    colour = QColor(color)
    result = QPixmap(round(size * dpr), round(size * dpr))
    result.setDevicePixelRatio(dpr)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        _draw(painter, kind, colour, float(size))
    finally:
        painter.end()
    return result


def icon(kind, color, size=18):
    """단추에 넣을 QIcon (2배로 그려 둠)."""
    return QIcon(pixmap(kind, color, size, ICON_DPR))
