"""CPU 그리기(raster 뷰포트·픽스맵 길)의 영상 아이템 — 축소 필터가 '고품질'이면 **줄여 그릴 때** 면적 평균으로 줄인 그림을 그림.

왜·규칙은 downscale_filter(Windows의 Settings → 축소 필터). 이 아이템은 그릴 때마다 그 설정을 봄:
- Linear(기본 — Mac은 늘 이 값): 부모 QGraphicsPixmapItem의 그리기 그대로 — 예전과 같은 픽셀.
- 고품질: 그릴 자리가 프레임보다 작으면(downscale_filter.snapped_rect) 그 장치 픽셀 크기로 **면적 평균**해 줄인 그림(QImage.scaled의 부드러운 줄이기)을
  **정수 크기·정수 장치 픽셀 자리에 1:1로** 그림 — 그릴 자리는 보통 크기가 소수(1920×0.5146 = 988.03)라 줄인 그림을 그 자리에 그대로 맞추면 한 번 더
  보간돼 흐려지므로 크기·자리를 반 픽셀 안에서 맞춤(영상 가장자리가 와이프 선·ROI와 반 픽셀까지 어긋날 수 있음 — 받아들임; 크기가 같은 그림의 자리는 Qt
  raster도 스스로 정수에 맞춤 — 실험). 프레임(픽스맵)·크기마다 한 번만 줄이고 다시 그릴 때는 그 그림을 씀. 1:1·키워 그리기·돌린 그림은 부모 그리기.
  재생·드래그 중에도 같은 필터(프레임마다 줄임 — 그만큼의 CPU 시간이 그리기에 더 듦; 사용자가 고른 것).

아이템의 픽스맵·테두리는 프레임 크기 그대로(창에 맞춤·와이프 선·ROI·주석이 이 좌표에 기댐) — 그리는 그림만 다름.
"""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QPainter, QTransform
from PyQt5.QtWidgets import QGraphicsPixmapItem

from yesoncheck import downscale_filter, error_window

LOG_PREFIX = "[표시]"


def area_scaled(pixmap, width, height):
    """픽스맵을 width×height로 면적 평균해 줄인 QImage (Qt의 부드러운 줄이기)."""
    return pixmap.toImage().scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


class AreaScaledPixmapItem(QGraphicsPixmapItem):
    """QGraphicsPixmapItem — 축소 필터가 고품질이고 줄여 그릴 때만 면적 평균으로 줄인 그림을 그림 (모듈 설명)."""

    def __init__(self, *args):
        super().__init__(*args)
        self._scaled = None  # 지금 픽스맵을 줄인 그림
        self._scaled_for = None  # (픽스맵 cacheKey, 너비, 높이) — 무엇을 어느 크기로 줄였는지
        self._failed = False  # 줄이다 실패함 — 한 번 알린 뒤로는 이 창을 닫을 때까지 예전 그리기 (메뉴에서 다시 골라도 다시 시도하지 않음 — 알림 글에 적음)

    def paint(self, painter, option, widget=None):
        # PyQt5 가상 함수에서 빠져나간 예외는 프로세스를 끝냄(qFatal) — 줄이는 길의 실패는 여기서 잡아 한 번 크게 알리고 예전 방식으로 그림
        if downscale_filter.preferred() == "area" and not self._failed:
            try:
                if self._paint_area_scaled(painter):
                    return
            except BaseException:
                self._failed = True
                error_window.report_from_handler(
                    LOG_PREFIX,
                    f"영상을 면적 평균으로 줄여 그리다 실패했습니다(Settings → {downscale_filter.MENU_TEXT} → {downscale_filter.ACTION_TEXTS['area']}) — "
                    "이 창은 다시 켤 때까지 예전 방식(Linear)으로 그립니다")
        super().paint(painter, option, widget)

    def _paint_area_scaled(self, painter):
        """줄여 그릴 상황이면 면적 평균으로 줄인 그림을 정수 장치 픽셀 자리에 그리고 True, 아니면 False (부모가 그림)."""
        pixmap = self.pixmap()
        if pixmap.isNull():
            return False
        transform = painter.deviceTransform()  # 아이템 좌표 → 장치 픽셀 (화면 배율·위젯 자리까지 든 것 — 정수로 맞출 격자가 이것)
        if transform.type() > QTransform.TxScale:  # 돌리거나 기울인 변환(이 앱에는 없음) — 부모 그리기에 맡김
            return False
        width, height = pixmap.width(), pixmap.height()
        top_left = transform.map(self.offset())
        bottom_right = transform.map(self.offset() + QPointF(width, height))
        rect = downscale_filter.snapped_rect(top_left.x(), top_left.y(), bottom_right.x(), bottom_right.y(), width, height)
        if rect is None:
            return False
        left, top, scaled_width, scaled_height = rect
        key = (pixmap.cacheKey(), scaled_width, scaled_height)
        if key != self._scaled_for:
            self._scaled = area_scaled(pixmap, scaled_width, scaled_height)
            self._scaled_for = key
        inverse, invertible = transform.inverted()
        if not invertible:
            return False
        painter.save()
        try:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)  # 장치 픽셀에 1:1 — 다시 섞지 않음
            painter.drawImage(inverse.mapRect(QRectF(left, top, scaled_width, scaled_height)), self._scaled)
        finally:  # 그리다 실패해도 painter 상태(부드러운 변환 끔)를 부모 그리기에 남기지 않음
            painter.restore()
        return True
