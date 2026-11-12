"""raster(픽스맵) 영상 아이템이 **줄여 그릴 때** 면적 평균으로 미리 줄인 그림을 그림 (2026-11-12).

사용자 보고: "윈도 버전에서 같은 그림을 띄워도 라인이 지글거려 보여. 1대1 사이즈로 보면 괜찮은데. 맥은 … 축소해도 라인이 깔끔하게 표시되거든."
Windows 기본(raster 뷰포트 — 화면 배율 1)은 창에 맞춰 줄일 때(예: 1080p를 0.44배) Qt의 부드러운 변환이 원본 픽셀을 띄엄띄엄 골라(겹선형 —
점 둘씩만 봄) 가는 선이 어떤 곳은 진하고 어떤 곳은 사라졌음. Mac은 Retina(배율 2)라 같은 창에서도 거의 줄이지 않아 티가 안 났음.
고침: 줄여 그릴 때는 그릴 크기로 면적 평균한 그림(QImage.scaled의 부드러운 줄이기)을 만들어 1:1로 그림 — 프레임마다·크기마다 한 번.
면적 평균은 프레임당 약 2ms 더 들어(Windows의 4K 재생은 여유가 없음) **프레임이 멈춰 있을 때만**: 새 프레임은 우선 예전처럼 빠르게 그리고,
SETTLE_MS 동안 그대로면 다시 그림 — 재생·드래그 중의 그리기는 예전 그대로.

여기서는 진짜 창의 영상 아이템을 장면째 그림(QGraphicsScene.render — 그리는 배율이 painter에 실림)에 그려 픽셀을 봄.
같은 자리·1:1·키워 그리기는 예전 그림 그대로여야 함.
"""

import numpy as np
import pytest
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QImage, QPainter, QPixmap
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QGraphicsPixmapItem, QGraphicsScene

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import raster_video_item
from yesoncheck.raster_video_item import SETTLE_MS, AreaScaledPixmapItem

WIDTH, HEIGHT = 1600, 400


@pytest.fixture
def widget(new_player, dialogs, tmp_path):  # noqa: F811
    player = new_player(make_config(str(tmp_path), {}))
    view = player.videoWidget
    assert not view.video_item_stream  # 화면 없는 시험은 raster — Windows 기본과 같은 길
    return view


def stripes():
    """4픽셀마다 1픽셀짜리 검은 세로선 — 평균 밝기 191.25 (선화의 가는 선)."""
    frame = np.full((HEIGHT, WIDTH, 3), 255, np.uint8)
    frame[:, ::4] = 0
    return frame


def noise(seed=3):
    return np.random.default_rng(seed).integers(0, 256, (HEIGHT, WIDTH, 3), dtype=np.uint8)


def to_array(image):
    image = image.convertToFormat(QImage.Format_RGB888)
    pointer = image.bits()
    pointer.setsize(image.byteCount())
    return np.frombuffer(pointer, np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width() * 3].reshape(
        image.height(), image.width(), 3).copy()


def render(scene, source, scale):
    """장면의 source 영역을 scale배로 그린 그림 (부드러운 변환 켬 — 뷰와 같음)."""
    width, height = round(source.width() * scale), round(source.height() * scale)
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(Qt.white)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    scene.render(painter, QRectF(0, 0, width, height), source)
    painter.end()
    return to_array(image)


def settle(widget):
    """프레임이 멈춘 뒤의 상태가 될 때까지 기다림 (위젯의 멈춤 타이머가 돎)."""
    QTest.qWait(SETTLE_MS + 80)
    assert widget.video_item.settled


def shown(widget, frame, scale):
    """프레임을 넣고 멈춘 뒤(면적 평균으로 다시 그리는 상태) scale배로 그린 그림."""
    widget.updateFrame(frame, None)
    settle(widget)
    return render(widget.scene, widget.video_item.sceneBoundingRect(), scale)


def plain(frame, scale):
    """보통 픽스맵 아이템(예전 그리기)으로 같은 그림을 그린 것."""
    scene = QGraphicsScene()
    height, width = frame.shape[:2]
    item = QGraphicsPixmapItem(QPixmap.fromImage(QImage(frame.data, width, height, 3 * width, QImage.Format_RGB888)))
    item.setTransformationMode(Qt.SmoothTransformation)
    scene.addItem(item)
    return render(scene, item.sceneBoundingRect(), scale)


def test_the_raster_video_item_is_the_area_scaling_item(widget):
    assert isinstance(widget.video_item, AreaScaledPixmapItem)


def test_thin_lines_survive_evenly_when_the_view_is_scaled_down(widget):
    """0.25배: 그리는 픽셀 하나가 원본 4열(검은 선 하나 포함)을 덮음 → 면적 평균이면 어디나 같은 회색(191). 예전 그리기는 선이 통째로 사라졌음."""
    view = shown(widget, stripes(), 0.25).astype(float)
    assert abs(view.mean() - 191.25) < 2
    assert view.std() < 2
    old = plain(stripes(), 0.25).astype(float)
    assert abs(old.mean() - 191.25) > 30  # 예전 그리기가 왜 지글거렸는지 — 이 그림에서는 선이 사라짐(시험이 차이를 가르는지의 증거)


@pytest.mark.parametrize("scale", [0.31, 0.44, 0.6, 0.85])
def test_scaled_down_views_keep_the_average_brightness_of_line_art(widget, scale):
    """줄이는 배율이 어떻든 선의 양(평균 밝기)이 보존됨."""
    assert abs(shown(widget, stripes(), scale).astype(float).mean() - 191.25) < 3


@pytest.mark.parametrize("scale", [0.31, 0.44, 0.6])
def test_lines_are_more_even_than_the_old_drawing_at_fractional_scales(widget, scale):
    """정수배가 아닌 축소(창에 맞춤의 보통 경우 — 1080p가 0.44배쯤): 예전 그리기는 선마다 새까맣거나 사라져 줄 안의 밝기가 크게 출렁임
    (이 그림에서 표준편차 약 83) — 면적 평균은 선이 덮인 만큼의 회색이라 훨씬 고름(0.31배 22 · 0.44배 46 · 0.6배 63)."""
    frame = stripes()
    new_row = shown(widget, frame, scale)[10, :, 0].astype(float)
    old_row = plain(frame, scale)[10, :, 0].astype(float)
    assert new_row.std() < 0.8 * old_row.std()
    assert new_row.min() > old_row.min() + 50  # 예전에는 새까만 점이 섞였음


def test_one_to_one_view_shows_the_frame_untouched(widget):
    frame = noise()
    assert np.array_equal(shown(widget, frame, 1.0), frame)


@pytest.mark.parametrize("scale", [1.5, 2.0])
def test_enlarged_views_are_drawn_as_before(widget, scale):
    frame = noise()
    assert np.array_equal(shown(widget, frame, scale), plain(frame, scale))


def test_the_frame_is_rescaled_once_per_frame_and_size(widget, monkeypatch):
    calls = []
    real = raster_video_item.area_scaled
    monkeypatch.setattr(raster_video_item, "area_scaled", lambda pixmap, width, height: calls.append((width, height)) or real(pixmap, width, height))
    shown(widget, stripes(), 0.5)
    render(widget.scene, widget.video_item.sceneBoundingRect(), 0.5)  # 같은 프레임·같은 크기를 다시 그림(창이 가려졌다 보임 등)
    assert calls == [(800, 200)]
    render(widget.scene, widget.video_item.sceneBoundingRect(), 0.25)  # 크기가 바뀜(확대·축소·창 크기)
    assert calls == [(800, 200), (400, 100)]
    shown(widget, noise(), 0.25)  # 새 프레임
    assert calls == [(800, 200), (400, 100), (400, 100)]


def test_a_new_frame_is_first_drawn_the_fast_way(widget, monkeypatch):
    """새 프레임이 막 들어온 때(재생·드래그 중)는 예전 그리기 그대로 — 줄이는 비용이 재생 틱에 실리지 않음."""
    calls = []
    monkeypatch.setattr(raster_video_item, "area_scaled", lambda *args: calls.append(args))
    widget.updateFrame(stripes(), None)
    assert widget.video_item.settled is False
    view = render(widget.scene, widget.video_item.sceneBoundingRect(), 0.25)
    assert np.array_equal(view, plain(stripes(), 0.25)) and calls == []


def test_frames_arriving_in_a_stream_are_never_rescaled_until_they_stop(widget, monkeypatch):
    calls = []
    real = raster_video_item.area_scaled
    monkeypatch.setattr(raster_video_item, "area_scaled", lambda pixmap, width, height: calls.append((width, height)) or real(pixmap, width, height))
    source = widget.video_item.sceneBoundingRect
    for seed in range(8):  # 프레임이 SETTLE_MS보다 촘촘히 바뀜 (재생 24fps = 42ms, 여기서는 30ms)
        widget.updateFrame(noise(seed), None)
        render(widget.scene, source(), 0.5)
        QTest.qWait(30)
    assert calls == [] and widget.video_item.settled is False
    settle(widget)  # 멈춤 — 위젯이 스스로 다시 그리게 함
    render(widget.scene, source(), 0.5)
    assert calls == [(800, 200)]


def test_item_geometry_is_still_the_frame_size(widget):
    """아이템의 픽스맵·테두리는 프레임 크기 그대로 — 창에 맞춤·와이프 선·ROI·주석이 이 좌표에 기댐."""
    widget.updateFrame(stripes(), None)
    item = widget.video_item
    assert (item.pixmap().width(), item.pixmap().height()) == (WIDTH, HEIGHT)
    assert item.boundingRect().size().toSize().width() in (WIDTH, WIDTH + 1)  # Qt가 테두리에 반 픽셀 여유를 둠


def test_a_failure_while_rescaling_is_reported_once_and_the_frame_is_still_drawn(widget, monkeypatch):
    """줄이다 실패하면 크게 알리고(한 번) 예전 방식으로 그림 — PyQt5 가상 함수에서 예외가 빠져나가면 프로세스가 끝나므로 paint가 잡음."""
    reports = []
    monkeypatch.setattr(raster_video_item.error_window, "report_from_handler", lambda prefix, context: reports.append((prefix, context)))

    def broken(pixmap, width, height):
        raise RuntimeError("줄이기 실패 (시험)")

    monkeypatch.setattr(raster_video_item, "area_scaled", broken)
    first = shown(widget, stripes(), 0.25)
    second = render(widget.scene, widget.video_item.sceneBoundingRect(), 0.25)
    assert len(reports) == 1 and reports[0][0] == raster_video_item.LOG_PREFIX
    assert np.array_equal(first, plain(stripes(), 0.25)) and np.array_equal(second, first)
