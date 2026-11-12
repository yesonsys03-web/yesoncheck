"""CPU 그리기(raster 뷰포트)의 영상 아이템 — 축소 필터가 '고품질'이면 **줄여 그릴 때** 면적 평균으로 줄인 그림을 그림 (2026-11-12).

사용자 보고(Windows): "같은 그림을 띄워도 라인이 지글거려 보여. 1대1 사이즈로 보면 괜찮은데." 겹선형(Linear)으로 반쯤 줄이면 원본 픽셀을 띄엄띄엄 골라
가는 선이 어떤 곳은 진하고 어떤 곳은 사라짐. 고품질은 그릴 크기로 면적 평균한 그림을 정수 장치 픽셀 자리에 1:1로 그림.
**기본(Linear)은 예전 그리기 그대로**여야 하고(Mac은 고르는 길이 없어 늘 이쪽), 필터는 재생·정지 구분 없이 늘 같음(멈췄을 때만 다시 그리는 방식은 버림 — 사용자 지시).

여기서는 진짜 창의 영상 아이템을 장면째 그림(QGraphicsScene.render — 그리는 배율이 painter에 실림)에 그려 픽셀을 봄.
"""

import numpy as np
import pytest
from PyQt5.QtCore import QPoint, QRectF, Qt
from PyQt5.QtGui import QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QGraphicsPixmapItem, QGraphicsScene

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import downscale_filter, raster_video_item
from yesoncheck.raster_video_item import AreaScaledPixmapItem

WIDTH, HEIGHT = 1600, 400


@pytest.fixture
def widget(new_player, dialogs, tmp_path):  # noqa: F811
    player = new_player(make_config(str(tmp_path), {}))
    view = player.videoWidget
    assert not view.video_item_stream  # 화면 없는 시험은 raster — Windows의 CPU 그리기와 같은 길
    return view


@pytest.fixture
def area():
    """축소 필터 = 고품질 (Windows의 Settings 메뉴가 고른 상태 — conftest가 시험 뒤 Linear로 되돌림)."""
    downscale_filter.set_preferred("area")


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


def render(scene, source, scale, offset=(0.0, 0.0), pixel_ratio=1.0):
    """장면의 source 영역을 scale배로, offset(논리 픽셀)만큼 밀어 그린 그림 (부드러운 변환 켬 — 뷰와 같음). pixel_ratio: 화면 배율(장치 픽셀 = 논리 × 배율)."""
    width, height = source.width() * scale, source.height() * scale
    image = QImage(round((width + offset[0] + 2) * pixel_ratio), round((height + offset[1] + 2) * pixel_ratio), QImage.Format_RGB32)
    image.setDevicePixelRatio(pixel_ratio)
    image.fill(Qt.white)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    scene.render(painter, QRectF(offset[0], offset[1], width, height), source)
    painter.end()
    return to_array(image)


def shown(widget, frame, scale, **how):
    """프레임을 넣고 scale배로 그린 그림."""
    widget.updateFrame(frame, None)
    return render(widget.scene, widget.video_item.sceneBoundingRect(), scale, **how)


def plain(frame, scale, **how):
    """보통 픽스맵 아이템(예전 그리기)으로 같은 그림을 그린 것."""
    scene = QGraphicsScene()
    height, width = frame.shape[:2]
    item = QGraphicsPixmapItem(QPixmap.fromImage(QImage(frame.data, width, height, 3 * width, QImage.Format_RGB888)))
    item.setTransformationMode(Qt.SmoothTransformation)
    scene.addItem(item)
    return render(scene, item.sceneBoundingRect(), scale, **how)


def count_rescales(monkeypatch):
    calls = []
    real = raster_video_item.area_scaled
    monkeypatch.setattr(raster_video_item, "area_scaled", lambda pixmap, width, height: calls.append((width, height)) or real(pixmap, width, height))
    return calls


def test_the_raster_video_item_is_the_area_scaling_item(widget):
    assert isinstance(widget.video_item, AreaScaledPixmapItem)


# ---------------------------------------------------------------- 기본(Linear) — 예전 그리기 그대로


@pytest.mark.parametrize("scale", [0.25, 0.31, 0.44, 0.6, 0.85, 1.0, 1.5])
def test_the_default_filter_draws_exactly_as_before(widget, monkeypatch, scale):
    """기본값에서는 어떤 배율에서도 보통 픽스맵 아이템과 같은 픽셀 — Mac과 고르지 않은 Windows는 바뀐 것이 없음."""
    calls = count_rescales(monkeypatch)
    assert downscale_filter.preferred() == "linear"
    for frame in (stripes(), noise()):
        assert np.array_equal(shown(widget, frame, scale, offset=(3.4, 7.6)), plain(frame, scale, offset=(3.4, 7.6)))
    assert calls == []


# ---------------------------------------------------------------- 고품질(면적 평균)


def test_thin_lines_survive_evenly_when_the_view_is_scaled_down(widget, area):
    """0.25배: 그리는 픽셀 하나가 원본 4열(검은 선 하나 포함)을 덮음 → 면적 평균이면 어디나 같은 회색(191). 겹선형은 선이 통째로 사라졌음."""
    view = shown(widget, stripes(), 0.25)[:100, :400].astype(float)
    assert abs(view.mean() - 191.25) < 2
    assert view.std() < 2
    old = plain(stripes(), 0.25)[:100, :400].astype(float)
    assert abs(old.mean() - 191.25) > 30  # 겹선형이 왜 지글거렸는지 — 이 그림에서는 선이 사라짐(시험이 차이를 가르는지의 증거)


@pytest.mark.parametrize("scale", [0.31, 0.44, 0.6, 0.85])
def test_scaled_down_views_keep_the_average_brightness_of_line_art(widget, area, scale):
    """줄이는 배율이 어떻든 선의 양(평균 밝기)이 보존됨."""
    view = shown(widget, stripes(), scale)[:round(HEIGHT * scale), :round(WIDTH * scale)].astype(float)
    assert abs(view.mean() - 191.25) < 3


@pytest.mark.parametrize("scale", [0.31, 0.44, 0.6])
def test_lines_are_more_even_than_linear_at_fractional_scales(widget, area, scale):
    """정수배가 아닌 축소(창에 맞춤의 보통 경우 — 1080p가 0.44~0.5배쯤): 겹선형은 선마다 새까맣거나 사라져 줄 안의 밝기가 크게 출렁임 —
    면적 평균은 선이 덮인 만큼의 회색이라 훨씬 고름."""
    frame = stripes()
    cut = slice(0, round(WIDTH * scale) - 2)
    new_row = shown(widget, frame, scale)[10, cut, 0].astype(float)
    old_row = plain(frame, scale)[10, cut, 0].astype(float)
    assert new_row.std() < 0.8 * old_row.std()
    assert new_row.min() > old_row.min() + 50  # 겹선형에는 새까만 점이 섞였음


@pytest.mark.parametrize("scale, offset", [(0.44, (0.0, 0.0)), (0.4406, (10.4, 7.6)), (0.5146, (3.5, 2.5)), (0.3127, (0.3, 0.9))])
def test_the_scaled_picture_lands_on_whole_pixels_without_being_blended_again(widget, area, scale, offset):
    """그릴 자리는 보통 크기도 자리도 소수(1600×0.4406 = 704.96) — 줄인 그림(705px)을 그 자리에 맞춰 그리면 한 번 더 보간돼 흐려짐.
    정수 크기·정수 장치 픽셀 자리에 1:1로: 그린 결과가 줄인 그림 그 자체."""
    frame = noise()
    view = shown(widget, frame, scale, offset=offset)
    left, top, width, height = downscale_filter.snapped_rect(offset[0], offset[1], offset[0] + WIDTH * scale, offset[1] + HEIGHT * scale, WIDTH, HEIGHT)
    expected = to_array(raster_video_item.area_scaled(widget.video_item.pixmap(), width, height))
    assert np.array_equal(view[top:top + height, left:left + width], expected)
    outside = view.copy()
    outside[top:top + height, left:left + width] = 255
    assert outside.min() == 255  # 그 자리 밖에는 아무것도 그리지 않음


@pytest.mark.parametrize("pixel_ratio, offset", [(1.25, (0.0, 0.0)), (1.5, (0.0, 0.0)), (2.0, (0.0, 0.0)), (1.25, (3.4, 7.7)), (1.5, (10.3, 2.9))])
def test_the_size_follows_the_screen_scale(widget, area, monkeypatch, pixel_ratio, offset):
    """화면 배율(Windows 125%·150% 등)까지 넣은 장치 픽셀 크기·자리로 — 논리 크기로 줄이면 다시 키워 그려 흐려짐."""
    real = raster_video_item.area_scaled
    calls = count_rescales(monkeypatch)
    scale = 0.25
    view = shown(widget, noise(), scale, offset=offset, pixel_ratio=pixel_ratio)
    left, top, width, height = downscale_filter.snapped_rect(
        offset[0] * pixel_ratio, offset[1] * pixel_ratio, (offset[0] + WIDTH * scale) * pixel_ratio, (offset[1] + HEIGHT * scale) * pixel_ratio, WIDTH, HEIGHT)
    assert calls == [(width, height)] and abs(width - WIDTH * scale * pixel_ratio) <= 1
    assert np.array_equal(view[top:top + height, left:left + width], to_array(real(widget.video_item.pixmap(), width, height)))


def test_inside_the_real_window_the_picture_lands_on_the_window_pixel_grid(new_player, dialogs, tmp_path, area):  # noqa: F811
    """진짜 창 안의 뷰포트는 창의 그림(backing store)에 **자기 자리만큼 밀려** 그려짐 — 정수로 맞출 격자는 그 장치 좌표(painter.deviceTransform)여야 함.
    창 전체를 그려(QWidget.grab — 자식 위젯은 자리만큼 밀린 painter로 그림) 영상 자리의 픽셀이 줄인 그림 그 자체인지 봄 (리뷰에서 권한 시험)."""
    player = new_player(make_config(str(tmp_path), {}))
    player.resize(1000, 760)
    player.show()
    view = player.videoWidget
    frame = noise()
    view.updateFrame(frame, None)
    view.resetTransform()
    view.scale(0.3127, 0.3127)  # 소수 크기 (1600 × 0.3127 = 500.32)
    QApplication.processEvents()
    shot = to_array(player.grab().toImage())
    origin = view.viewport().mapTo(player, QPoint(0, 0))
    mapping, rect = view.viewportTransform(), view.video_item.sceneBoundingRect()
    top_left, bottom_right = mapping.map(rect.topLeft()), mapping.map(rect.bottomRight())
    left, top, width, height = downscale_filter.snapped_rect(origin.x() + top_left.x(), origin.y() + top_left.y(),
                                                             origin.x() + bottom_right.x(), origin.y() + bottom_right.y(), WIDTH, HEIGHT)
    expected = to_array(raster_video_item.area_scaled(view.video_item.pixmap(), width, height))
    inner = (slice(20, height - 20), slice(40, width - 40))  # 가운데 — 영상 위에 겹쳐 그리는 것(줌 라벨 등)을 피함
    assert np.array_equal(shot[top:top + height, left:left + width][inner], expected[inner])


def test_one_to_one_view_shows_the_frame_untouched(widget, area, monkeypatch):
    calls = count_rescales(monkeypatch)
    frame = noise()
    assert np.array_equal(shown(widget, frame, 1.0)[:HEIGHT, :WIDTH], frame)
    assert calls == []


@pytest.mark.parametrize("scale", [1.5, 2.0])
def test_enlarged_views_are_drawn_as_before(widget, area, scale):
    frame = noise()
    assert np.array_equal(shown(widget, frame, scale), plain(frame, scale))


def test_the_frame_is_rescaled_once_per_frame_and_size(widget, area, monkeypatch):
    calls = count_rescales(monkeypatch)
    shown(widget, stripes(), 0.5)
    render(widget.scene, widget.video_item.sceneBoundingRect(), 0.5)  # 같은 프레임·같은 크기를 다시 그림(창이 가려졌다 보임 등)
    render(widget.scene, widget.video_item.sceneBoundingRect(), 0.5, offset=(30.2, 4.9))  # 자리만 바뀜(창을 옮김·팬)
    assert calls == [(800, 200)]
    render(widget.scene, widget.video_item.sceneBoundingRect(), 0.25)  # 크기가 바뀜(확대·축소·창 크기)
    assert calls == [(800, 200), (400, 100)]
    shown(widget, noise(), 0.25)  # 새 프레임
    assert calls == [(800, 200), (400, 100), (400, 100)]


def test_every_frame_is_filtered_while_frames_keep_coming(widget, area, monkeypatch):
    """재생·드래그 중에도 같은 필터 — 프레임마다 줄여 그림(멈췄을 때만 또렷해지는 방식이 아님 — 사용자 지시)."""
    real = raster_video_item.area_scaled
    calls = count_rescales(monkeypatch)
    for seed in range(6):
        frame = noise(seed)
        view = shown(widget, frame, 0.5)
        assert np.array_equal(view[:200, :800], to_array(real(widget.video_item.pixmap(), 800, 200)))
    assert calls == [(800, 200)] * 6


def test_switching_the_filter_applies_to_the_next_paint(widget, monkeypatch):
    """메뉴로 바꾸면 이 창에 바로 — 아이템은 그릴 때마다 설정을 봄."""
    calls = count_rescales(monkeypatch)
    frame = stripes()
    assert np.array_equal(shown(widget, frame, 0.25), plain(frame, 0.25))
    downscale_filter.set_preferred("area")
    filtered = render(widget.scene, widget.video_item.sceneBoundingRect(), 0.25)
    assert calls == [(400, 100)] and not np.array_equal(filtered, plain(frame, 0.25))
    downscale_filter.set_preferred("linear")
    assert np.array_equal(render(widget.scene, widget.video_item.sceneBoundingRect(), 0.25), plain(frame, 0.25))


def test_item_geometry_is_still_the_frame_size(widget, area):
    """아이템의 픽스맵·테두리는 프레임 크기 그대로 — 창에 맞춤·와이프 선·ROI·주석이 이 좌표에 기댐."""
    widget.updateFrame(stripes(), None)
    item = widget.video_item
    render(widget.scene, item.sceneBoundingRect(), 0.25)
    assert (item.pixmap().width(), item.pixmap().height()) == (WIDTH, HEIGHT)
    assert item.boundingRect().size().toSize().width() in (WIDTH, WIDTH + 1)  # Qt가 테두리에 반 픽셀 여유를 둠


def test_an_empty_item_is_left_to_the_plain_drawing(widget, area, monkeypatch):
    """영상이 없는 창(빈 픽스맵) — 줄이지도 실패하지도 않음."""
    reports = []
    monkeypatch.setattr(raster_video_item.error_window, "report_from_handler", lambda prefix, context: reports.append(context))
    calls = count_rescales(monkeypatch)
    widget.updateFrame(None, None)
    render(widget.scene, QRectF(0, 0, 100, 50), 0.5)
    assert reports == [] and calls == []


def test_a_failure_while_rescaling_is_reported_once_and_the_frame_is_still_drawn(widget, area, monkeypatch):
    """줄이다 실패하면 크게 알리고(한 번) 예전 방식으로 그림 — PyQt5 가상 함수에서 예외가 빠져나가면 프로세스가 끝나므로 paint가 잡음."""
    reports = []
    monkeypatch.setattr(raster_video_item.error_window, "report_from_handler", lambda prefix, context: reports.append((prefix, context)))

    def broken(pixmap, width, height):
        raise RuntimeError("줄이기 실패 (시험)")

    monkeypatch.setattr(raster_video_item, "area_scaled", broken)
    first = shown(widget, stripes(), 0.25)
    second = render(widget.scene, widget.video_item.sceneBoundingRect(), 0.25)
    assert len(reports) == 1 and reports[0][0] == raster_video_item.LOG_PREFIX
    assert "다시 켤 때까지" in reports[0][1]  # 그 뒤로 이 창은 메뉴에서 고품질을 다시 골라도 줄이지 않음 — 그대로 알림
    assert np.array_equal(first, plain(stripes(), 0.25)) and np.array_equal(second, first)
