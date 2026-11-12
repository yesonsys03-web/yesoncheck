"""raster(픽스맵) 뷰포트의 영상 아이템 — **줄여 그릴 때** 면적 평균으로 미리 줄인 그림을 그림.

사용자 보고(2026-11-12): "윈도 버전에서 같은 그림을 띄워도 라인이 지글거려 보여. 1대1 사이즈로 보면 괜찮은데. 맥은 … 축소해도 라인이
깔끔하게 표시되거든." Windows 기본 화면 그리기(raster, 화면 배율 1)는 창에 맞춰 줄일 때(1080p를 0.44배쯤) Qt의 부드러운 변환이
그리는 픽셀마다 원본 점 넷만 섞음(겹선형) — 원본 픽셀을 띄엄띄엄 고르는 셈이라 가는 선이 어떤 곳은 진하고 어떤 곳은 사라짐.
Mac은 Retina(배율 2)라 같은 창에서도 거의 줄이지 않아 티가 안 났음(GL 길 — 이 아이템과 무관).

고침: 그리는 배율(뷰 배율 × 화면 배율)이 1보다 작으면, 그릴 크기(장치 픽셀)로 **면적 평균**해 줄인 그림을 만들어 아이템 자리에
그대로(거의 1:1) 그림 — `QImage.scaled(…, Qt.SmoothTransformation)`이 줄일 때 면적 평균을 씀. 프레임(픽스맵)마다·크기마다 한 번만 줄이고
다시 그릴 때는 그 그림을 씀. 1:1·키워 그리기·돌린 그림은 예전 그리기 그대로(부모 QGraphicsPixmapItem).

**프레임이 멈춰 있을 때만**(`settled`): 면적 평균은 원본 픽셀을 모두 읽어 프레임당 약 2ms 더 듦(이 Mac, 앱의 그리기 길 — 1080p 4.1 → 6.1ms,
4K 6.7 → 9.1ms; Windows의 4K 재생은 그만한 여유가 없음). 그래서 새 프레임이 들어오면 위젯이 `settled = False`로 두고 예전처럼 빠르게
그리고, 프레임이 `SETTLE_MS` 동안 그대로면(멈춤·한 장씩 넘김·드래그를 놓음) `settled = True`로 한 번 다시 그림 — 재생·드래그 중의 그리기
비용은 예전 그대로(video_widget의 `_frame_changed`·`_draw_settled_frame`).

아이템의 픽스맵·테두리는 프레임 크기 그대로(창에 맞춤·와이프 선·ROI·주석이 이 좌표에 기댐) — 그리는 그림만 다름.
"""

from PyQt5.QtCore import QRectF, QSizeF, Qt
from PyQt5.QtGui import QPainter, QTransform
from PyQt5.QtWidgets import QGraphicsPixmapItem

from yesoncheck import error_window

LOG_PREFIX = "[표시]"
# 이 배율 미만으로 줄여 그릴 때만 미리 줄임 — 1:1 언저리(반올림으로 한두 픽셀 모자란 크기)는 예전 그리기가 더 정확함
DOWNSCALE_BELOW = 0.98
# 프레임이 이만큼(ms) 그대로면 멈춘 것으로 보고 면적 평균으로 다시 그림 — 24fps의 프레임 간격(42ms)·드래그 미리보기 간격보다 넉넉히 길게
SETTLE_MS = 120


def area_scaled(pixmap, width, height):
    """픽스맵을 width×height로 면적 평균해 줄인 QImage (Qt의 부드러운 줄이기)."""
    return pixmap.toImage().scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def downscaled_size(transform, pixel_ratio, width, height):
    """그리는 변환·화면 배율에서 width×height 그림이 차지할 장치 픽셀 크기 — 줄여 그리는 경우에만, 아니면 None.
    돌리거나 기울인 변환(이 앱에는 없음)은 None — 예전 그리기에 맡김."""
    if transform.type() > QTransform.TxScale:
        return None
    scale_x, scale_y = abs(transform.m11()) * pixel_ratio, abs(transform.m22()) * pixel_ratio
    if scale_x >= DOWNSCALE_BELOW and scale_y >= DOWNSCALE_BELOW:
        return None
    return max(1, int(width * scale_x + 0.5)), max(1, int(height * scale_y + 0.5))


class AreaScaledPixmapItem(QGraphicsPixmapItem):
    """QGraphicsPixmapItem — 줄여 그릴 때만 면적 평균으로 줄인 그림을 그림 (모듈 설명)."""

    def __init__(self, *args):
        super().__init__(*args)
        self._scaled = None  # 지금 픽스맵을 줄인 그림
        self._scaled_for = None  # (픽스맵 cacheKey, 너비, 높이) — 무엇을 어느 크기로 줄였는지
        self.settled = True  # 프레임이 멈춰 있음 — 위젯이 새 프레임에 False, SETTLE_MS 뒤 True (False인 동안은 예전의 빠른 그리기)
        self._failed = False  # 줄이다 실패함 — 한 번 알린 뒤로는 예전 그리기

    def paint(self, painter, option, widget=None):
        # PyQt5 가상 함수에서 빠져나간 예외는 프로세스를 끝냄(qFatal) — 줄이는 길의 실패는 여기서 잡아 한 번 크게 알리고 예전 방식으로 그림
        if self.settled and not self._failed:
            try:
                if self._paint_scaled_down(painter):
                    return
            except BaseException:
                self._failed = True
                error_window.report_from_handler(LOG_PREFIX, "영상을 줄여 그리다 실패했습니다 — 이 창은 예전 방식으로 그립니다")
        super().paint(painter, option, widget)

    def _paint_scaled_down(self, painter):
        """줄여 그릴 상황이면 미리 줄인 그림을 그리고 True, 아니면 False (부모가 그림)."""
        pixmap = self.pixmap()
        if pixmap.isNull():
            return False
        size = downscaled_size(painter.worldTransform(), painter.device().devicePixelRatioF(), pixmap.width(), pixmap.height())
        if size is None:
            return False
        key = (pixmap.cacheKey(), *size)
        if key != self._scaled_for:
            self._scaled = area_scaled(pixmap, *size)
            self._scaled_for = key
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(QRectF(self.offset(), QSizeF(pixmap.width(), pixmap.height())), self._scaled)
        painter.restore()
        return True
