"""주석 층 — 네이티브 프레임의 주석을 굽지 않고 Qt 아이템으로 (Apple Silicon 네이티브 재생 — 계획 Task 13·B8).

네이티브 프레임(IOSurface 위 BGRX 뷰, 읽기 전용)에는 주석을 굽지 않는다: prepare_frame_for_display·burn_frame_annotations가 프레임을 그대로
돌려주고(복사·cv2 굽기 없음), CustomVideoWidget이 가진 주석 층 하나(annotation_overlay.AnnotationOverlay — 프레임 사각형, 장면 원점이라 층 좌표 =
프레임 픽셀, z 13.5: B 키 상자 13 위 — 굽는 차례도 글자 다음 주석 —, 편집 미리보기 14 아래)가 주석마다 자식 아이템을 둔다. 층은 updateFrame의
네이티브 분기가 플레이어의 공급자(_annotations_for_native — 보이는 프레임의 주석)로 프레임마다 갱신하고, A가 RGB면(굽는 길) 비운다.
기하는 굽는 길(burn_annotations_on_frame)과 같은 규칙 — 같은 함수(annotation_burn.annotation_spec)를 두 길이 부름: 좌표·굵기 기본값·화살표 촉·
글꼴과 크기. 획 폭은 cv2가 굵기 t로 실제로 덮는 픽셀 폭(burned_stroke_extent — t ≥ 2이면 2·ceil(t/2) + 1), 좌표는 픽셀 가운데(+0.5).
그림 비교는 장면을 QImage에 그려(뷰처럼 안티앨리어싱) 같은 주석을 구운 프레임과 견줌 — 글자의 그림 비교는 Windows offscreen에서 글리프가
그려지지 않아(CLAUDE.md '다음 후보' — test_annotation_burn_color와 같은 사정) 그 플랫폼에서는 기하만 봄.
"""

import math
import sys

import cv2
import numpy as np
import pytest
from PyQt5.QtCore import QPoint, QRectF, Qt
from PyQt5.QtGui import QFont, QFontMetrics, QFontMetricsF, QImage, QPainter, QColor
from PyQt5.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
)

from tests.native_fakes import (  # noqa: F401 (픽스처 — new_player는 native_fakes의 픽스처가 요청함)
    FAKE_FRAME_COUNT,
    FAKE_HEIGHT,
    FAKE_WIDTH,
    fake_native_player,
    new_player,
    player_with_fake_native,
)
from yesoncheck.annotation_burn import burn_annotations_on_frame
from yesoncheck.frame_annotations import MAX_FONT_SIZE, MIN_FONT_SIZE

W, H = 320, 180
TOTAL = FAKE_FRAME_COUNT
RED = (255, 51, 51)  # "#ff3333"
STROKE_PX = {1: 1, 2: 3, 3: 5, 4: 5, 5: 7, 8: 9}  # cv2 굵기 t가 덮는 픽셀 폭 — 아래 test_burned_stroke_extent_matches_cv2가 cv2로 잼


def ann(kind, x1=0.125, y1=0.2, x2=0.75, y2=0.8, **extra):
    """주석 dict (320×180이면 (40, 36)–(240, 144))."""
    item = {"type": kind, "norm_x1": x1, "norm_y1": y1, "norm_x2": x2, "norm_y2": y2, "color": "#ff3333"}
    item.update(extra)
    return item


def new_layer(annotations=(), width=W, height=H):
    """주석 층 하나 — annotations를 width×height 프레임에 둔 것."""
    from yesoncheck.annotation_overlay import AnnotationOverlay

    layer = AnnotationOverlay()
    layer.set_annotations(list(annotations), width, height)
    return layer


def only_child(layer):
    children = layer.childItems()
    assert len(children) == 1, f"주석 층의 자식 {len(children)}개"
    return children[0]


def drawn(annotation, width=W, height=H):
    """주석 하나를 둔 층과 그 자식 — (층, 자식). 층을 쥐고 있어야 함(자식은 층이 가진 C++ 아이템이라 층이 지워지면 함께 지워짐)."""
    layer = new_layer([annotation], width, height)
    return layer, only_child(layer)


def render_layer(layer, source=QRectF(0, 0, W, H)):
    """층만 든 장면의 source 영역(장면 단위 = 픽셀)을 검정 바탕에 그림 — 뷰처럼 안티앨리어싱 → (높이, 너비, 3) RGB 배열."""
    scene = QGraphicsScene()
    scene.addItem(layer)
    image = QImage(int(source.width()), int(source.height()), QImage.Format_RGB32)
    image.fill(Qt.black)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    scene.render(painter, QRectF(0, 0, source.width(), source.height()), source)
    painter.end()
    scene.removeItem(layer)
    bits = image.constBits()
    bits.setsize(image.byteCount())
    bgra = np.frombuffer(bits, np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)[:, : image.width()]
    return bgra[..., [2, 1, 0]].copy()


def burned(annotations, width=W, height=H):
    """같은 주석을 width×height 검정 RGB 프레임에 구운 것 (굽는 길 — 기준)."""
    return burn_annotations_on_frame(np.zeros((height, width, 3), np.uint8), list(annotations))


def red(image):
    """빨강(#ff3333 — R 255) 잉크가 절반 넘게 덮은 픽셀."""
    return image[..., 0] >= 128


def bbox(mask):
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def assert_untouched(rig):
    """연 뒤로 네이티브 프레임의 픽셀을 CPU가 만진 적이 없음 — 파이썬 쪽 접근 0, cv2.cvtColor 0."""
    assert rig.reads == [], f"네이티브 프레임의 픽셀을 파이썬에서 읽음: {rig.reads}"
    assert rig.cvt_calls == [], f"네이티브 프레임을 cv2.cvtColor로 변환함 (code {rig.cvt_calls})"


# ---------------------------------------------------------------- 기하 (굽는 길과 같은 규칙)

@pytest.mark.parametrize("kind", ["rect", "ellipse", "line", "arrow"])
def test_rect_item_geometry_equals_burn_bbox(qapp, kind):
    """사각형·타원·선·화살표 (굵기 3, 320×180): 구운 빨강 픽셀의 상자(끝 픽셀 포함 → 오른쪽·아래 +1)와 아이템의 sceneBoundingRect가 ±1px —
    사각형은 정확히 같음(왼쪽 위 = 모서리 − 2, 오른쪽 아래 = 모서리 + 3: 픽셀 가운데 + 0.5 ± 획 폭 5의 반).

    깨지는 변경: 층 좌표를 프레임 픽셀이 아닌 정규 좌표·다른 배율로 두거나 사각형의 min/max 모서리를 쓰지 않거나 타원 반지름을 지름으로 두면 상자가
    어긋남; 픽셀 가운데(+0.5)를 빼거나 펜 폭을 cv2가 덮는 폭(5)이 아닌 굵기 그대로(3) 두면 사각형 상자가 0.5~1px 어긋남."""
    annotation = ann(kind, 0.75, 0.8, 0.125, 0.2, stroke_width=3) if kind == "rect" else ann(kind, stroke_width=3)
    _layer, item = drawn(annotation)
    left, top, right, bottom = bbox(red(burned([annotation])))
    box = item.sceneBoundingRect()
    tolerance = 0.01 if kind == "rect" else 1.0
    assert box.left() == pytest.approx(left, abs=tolerance)
    assert box.top() == pytest.approx(top, abs=tolerance)
    assert box.right() == pytest.approx(right + 1, abs=tolerance)
    assert box.bottom() == pytest.approx(bottom + 1, abs=tolerance)
    if kind == "rect":
        assert (left, top, right, bottom) == (40 - 2, 36 - 2, 240 + 2, 144 + 2)  # 이 cv2에서 굵기 3이 덮는 5px


@pytest.mark.parametrize("corners", [(0.125, 0.2, 0.75, 0.8), (0.75, 0.8, 0.125, 0.2), (0.1, 0.85, 0.9, 0.1)],
                         ids=["down_right", "up_left", "diagonal_up"])
@pytest.mark.parametrize("stroke", [3, 5])
@pytest.mark.parametrize("kind", ["rect", "ellipse", "line", "arrow"])
def test_shape_items_cover_the_burned_pixels(qapp, kind, stroke, corners):
    """층을 그린 그림(안티앨리어싱, 절반 넘게 덮인 픽셀)과 구운 그림이 거의 같은 픽셀 — 다른 픽셀이 구운 픽셀의 10% 이하(실측 ≤ 5%: 타원은 cv2가
    다각형으로 근사, 선 끝은 둥근 끝의 래스터 차이). 거꾸로 그린 모서리·대각선 포함.

    깨지는 변경: 펜 폭을 굵기 그대로 두면(cv2는 굵기 3을 5px, 5를 7px로 덮음) 획이 가늘어 다른 픽셀이 ~40%; 화살표 촉의 길이·각이 cv2와 다르면 촉
    자리가 어긋남; 층이 테두리를 그리거나(펜 있음) 채우면 그만큼 늘어남."""
    annotation = ann(kind, *corners, stroke_width=stroke)
    shown = red(render_layer(new_layer([annotation])))
    burnt = red(burned([annotation]))
    differ = int((shown ^ burnt).sum())
    assert differ <= 0.1 * burnt.sum(), f"{kind} 굵기 {stroke}: 다른 픽셀 {differ} / 구운 픽셀 {int(burnt.sum())}"


def test_burned_stroke_extent_matches_cv2(qapp):
    """burned_stroke_extent(t) = cv2가 굵기 t의 선(cv2.line·rectangle·ellipse가 함께 쓰는 ThickLine)으로 실제로 덮는 픽셀 폭 — 이 cv2(4.6)를 그려서 잼:
    t = 1은 1px, t ≥ 2는 반폭 ceil(t/2)의 다각형 + 끝 픽셀 포함 → 2·ceil(t/2) + 1.

    깨지는 변경: 식을 굵기 그대로(t)나 t + 1로 바꾸면 홀수 굵기에서 틀림. cv2를 올려 그리는 법이 바뀌면 여기서 드러남(층의 획 폭을 다시 맞출 것)."""
    from yesoncheck.annotation_burn import burned_stroke_extent

    for t in range(1, 13):
        frame = np.zeros((60, 60), np.uint8)
        cv2.line(frame, (10, 30), (50, 30), 255, t)
        covered = int(np.count_nonzero(frame[:, 30]))
        assert burned_stroke_extent(t) == covered, f"굵기 {t}: cv2가 덮는 폭 {covered}px"
    assert {t: burned_stroke_extent(t) for t in STROKE_PX} == STROKE_PX


def test_line_arrow_ellipse_text_items_created(qapp):
    """종류마다 자식 하나: 사각형 → QGraphicsRectItem(모서리 + 0.5, 채움 없음), 타원 → QGraphicsEllipseItem(가운데 (x1 + x2)//2·반지름 |x2 − x1|//2 —
    정수 나눗셈), 선 → QGraphicsLineItem, 화살표 → QGraphicsPathItem, 글자 → QGraphicsSimpleTextItem. 도형의 펜: 색 = 주석 색(RGB), 폭 = cv2가 덮는
    폭(굵기 3 → 5 — 프레임 픽셀, cosmetic 아님), 둥근 끝·둥근 이음(cv2 굵은 선은 끝과 꺾임이 둥긂). 글자: 글자·색(붓), 글꼴은 굽는 길과 같은 것(annotation_font — 크기 14: 320×180의
    기본 max(14, int(180/45))), 자리 (x1 + 4, …) — 기준선이 y1 + 4 + 글꼴 ascent(정수, 굽는 길의 drawText)에 옴.

    깨지는 변경: 색을 BGR로 넣거나 기본색을 바꾸면 색이 틀림; cosmetic 펜이면 줌해도 획이 커지지 않음; 타원을 반올림·실수 나눗셈으로 두면 가운데·반지름이 0.5 어긋남; 글자 안쪽 여백 4를
    빼면 자리가 틀림; 글꼴 크기를 Qt 기본(13pt)이나 픽셀 크기로 두면 굽는 글자와 크기가 다름."""
    from yesoncheck.annotation_burn import annotation_font

    cases = {
        "rect": (ann("rect", 0.13, 0.21, stroke_width=3), QGraphicsRectItem),
        "ellipse": (ann("ellipse", 0.13, 0.21, stroke_width=3), QGraphicsEllipseItem),
        "line": (ann("line", stroke_width=3), QGraphicsLineItem),
        "arrow": (ann("arrow", stroke_width=3), QGraphicsPathItem),
        "text": (ann("text", text="note", color="#33cc66"), QGraphicsSimpleTextItem),
    }
    for kind, (annotation, item_class) in cases.items():
        _layer, item = drawn(annotation)
        assert type(item) is item_class, kind
        if kind == "text":
            continue
        pen = item.pen()
        assert pen.color().getRgb()[:3] == RED and pen.widthF() == 5, kind
        assert pen.capStyle() == Qt.RoundCap and pen.joinStyle() == Qt.RoundJoin, kind
        assert not pen.isCosmetic(), kind  # 폭은 프레임 픽셀 — 줌과 함께 커짐(구운 획처럼)
        if kind in ("rect", "ellipse", "arrow"):
            assert item.brush().style() == Qt.NoBrush, kind

    # (41, 37)–(240, 144): 사각형은 모서리 그대로, 타원은 가운데 (140, 90)·반지름 (99, 53)
    _layer, rect = drawn(cases["rect"][0])
    assert rect.rect() == QRectF(41.5, 37.5, 199, 107)
    _layer, ellipse = drawn(cases["ellipse"][0])
    assert ellipse.rect() == QRectF(140 - 99 + 0.5, 90 - 53 + 0.5, 198, 106)
    _layer, line_item = drawn(cases["line"][0])
    line = line_item.line()
    assert (line.x1(), line.y1(), line.x2(), line.y2()) == (40.5, 36.5, 240.5, 144.5)

    _layer, text = drawn(cases["text"][0])
    font = text.font()
    assert text.text() == "note" and text.brush().color().getRgb()[:3] == (0x33, 0xCC, 0x66)
    assert font == annotation_font(14) and font.pointSize() == 14
    assert text.pos().x() == 40 + 4
    assert text.pos().y() + QFontMetricsF(font).ascent() == pytest.approx(36 + 4 + QFontMetrics(font).ascent(), abs=1e-6)
    assert abs(text.pos().y() - (36 + 4)) <= 0.5  # 글줄 위 ≈ 패치 위 + 4


@pytest.mark.parametrize("size, stroke, expected", [((W, H), None, 3), ((W, H), 1, 1), ((W, H), 0, 1), ((W, H), -3, 1), ((W, H), 8, 9),
                                                    ((1920, 1080), None, 3), ((3840, 2160), None, 7)],
                         ids=["auto_320", "one", "zero_is_one", "negative_is_one", "eight", "auto_1080p", "auto_4k"])
def test_stroke_width_rule(qapp, size, stroke, expected):
    """획 폭: 굵기가 없으면 굽는 길의 기본 max(2, int(min(높이, 너비)/400))(320×180·1080p 2 → 3px, 4K 5 → 7px), 1 아래(0·음수)는 1, 그다음 cv2가 덮는 폭.

    깨지는 변경: 기본 굵기 식(400·최소 2)이나 1 아래 자르기를 바꾸면 폭이 틀림."""
    extra = {} if stroke is None else {"stroke_width": stroke}
    _layer, item = drawn(ann("rect", **extra), *size)
    assert item.pen().widthF() == expected


@pytest.mark.parametrize("size, font_size, expected", [((W, H), None, 14), ((1920, 1080), None, 24), ((3840, 2160), None, 48),
                                                       ((W, H), 30, 30), ((W, H), 200, 120), ((W, H), 5, 12)],
                         ids=["default_320", "default_1080p", "default_4k", "given", "clamp_max", "clamp_min"])
def test_text_font_size_rule(qapp, size, font_size, expected):
    """글자 크기(점): 주석에 없으면 굽는 길의 기본 max(14, int(min(높이, 너비)/45)), 그다음 MIN_FONT_SIZE(12)~MAX_FONT_SIZE(120)로 자름.

    깨지는 변경: 기본 식(45·최소 14)이나 자르기 한도를 바꾸면 크기가 굽는 글자와 다름."""
    assert (MIN_FONT_SIZE, MAX_FONT_SIZE) == (12, 120)
    extra = {} if font_size is None else {"font_size": font_size}
    _layer, text = drawn(ann("text", text="note", **extra), *size)
    assert text.font().pointSize() == expected


def test_empty_text_and_unknown_type_draw_nothing(qapp):
    """빈 글자·모르는 종류는 굽는 길처럼 그리지 않음 — 자식 없음, 층 숨김.

    깨지는 변경: 빈 글자에도 아이템을 두거나 모르는 종류를 사각형으로 그리면 자식이 생김."""
    layer = new_layer([ann("text", text=""), ann("polygon")])
    assert layer.childItems() == [] and not layer.isVisible()


def test_arrow_tip_matches_cv2_rule(qapp):
    """화살표 촉: cv2.arrowedLine과 같은 식 — 촉 길이 = 선 길이 × tipLength(min(0.35, max(0.12, 0.08 + 굵기·0.02)) — 굵기 3이면 0.14), 끝점 (x2, y2)에서
    선을 거꾸로 본 각 ± 45°, 정수로 반올림(cvRound). 경로는 몸통 (x1, y1) → (x2, y2)와 촉 둘(촉 끝 → (x2, y2)), 모두 픽셀 가운데(+0.5).
    cv2가 그린 화살표 = cv2.line으로 몸통 + 두 촉을 그린 것(같은 끝점이면 바이트까지 같음)으로 촉 끝점이 cv2 내부 값과 같음을 확인.

    깨지는 변경: tipLength 식(0.08·0.02·0.12·0.35)이나 45°를 바꾸거나 촉을 (x1, y1) 쪽에 두거나 반올림을 버림으로 하면 촉이 cv2와 어긋남; 층이 굵기와
    상관없는 촉 비율을 쓰면 굵기 1·5·14에서 촉 끝이 틀림."""
    from yesoncheck.annotation_burn import arrow_tip_length, arrow_tip_points

    assert (arrow_tip_length(1), arrow_tip_length(3), arrow_tip_length(14)) == (0.12, pytest.approx(0.14), 0.35)
    annotation = ann("arrow", 0.125, 0.84, 0.78, 0.22, stroke_width=3)  # (40, 151) → (249, 39)
    x1, y1, x2, y2 = 40, 151, 249, 39
    size = math.hypot(x1 - x2, y1 - y2) * 0.14
    angle = math.atan2(y1 - y2, x1 - x2)
    expected = [(round(x2 + size * math.cos(angle + s * math.pi / 4)), round(y2 + size * math.sin(angle + s * math.pi / 4))) for s in (1, -1)]
    assert arrow_tip_points(x1, y1, x2, y2, 0.14) == expected

    _layer, arrow = drawn(annotation)
    path = arrow.path()
    points = [(path.elementAt(i).x, path.elementAt(i).y, path.elementAt(i).isMoveTo()) for i in range(path.elementCount())]
    c = 0.5
    assert points == [(x1 + c, y1 + c, True), (x2 + c, y2 + c, False),
                      (expected[0][0] + c, expected[0][1] + c, True), (x2 + c, y2 + c, False),
                      (expected[1][0] + c, expected[1][1] + c, True), (x2 + c, y2 + c, False)]
    for stroke, fraction in ((1, 0.12), (5, 0.18), (14, 0.35)):  # 층도 굵기마다 그 비율 — 아래·위 한도 포함
        _layer, thick = drawn(dict(annotation, stroke_width=stroke))
        tips = arrow_tip_points(x1, y1, x2, y2, fraction)
        assert [(thick.path().elementAt(i).x - c, thick.path().elementAt(i).y - c) for i in (2, 4)] == tips, f"굵기 {stroke}"

    for stroke, (ax1, ay1, ax2, ay2) in ((1, (x1, y1, x2, y2)), (3, (x1, y1, x2, y2)), (2, (300, 20, 31, 170)), (1, (100, 90, 103, 92))):
        tip = arrow_tip_length(stroke)
        cv2_arrow = np.zeros((H, W), np.uint8)
        cv2.arrowedLine(cv2_arrow, (ax1, ay1), (ax2, ay2), 255, stroke, tipLength=tip)
        by_lines = np.zeros((H, W), np.uint8)
        cv2.line(by_lines, (ax1, ay1), (ax2, ay2), 255, stroke)
        for point in arrow_tip_points(ax1, ay1, ax2, ay2, tip):
            cv2.line(by_lines, point, (ax2, ay2), 255, stroke)
        assert np.array_equal(cv2_arrow, by_lines), f"굵기 {stroke} ({ax1}, {ay1}) → ({ax2}, {ay2}): 촉 끝점이 cv2와 다름"


@pytest.mark.parametrize("text", ["note", "수정 필요 abc", "漢字テスト"])
def test_text_item_lands_on_burned_text(qapp, text):
    """글자 아이템의 기준선·왼쪽이 구운 글자와 같은 자리: 글자는 Qt 글줄(QTextLayout — 대체 글꼴이 섞이면 글줄 ascent가 주 글꼴보다 큼) 위에
    놓이므로 아이템 자리는 기준선(y1 + 4 + 주 글꼴 ascent) − 글줄 ascent. 그림 비교(Windows offscreen은 글리프가 안 그려져 그 밖에서만): 그린 글자의
    잉크 상자가 구운 글자의 것과 ±1px.

    깨지는 변경: 글줄 ascent 대신 주 글꼴의 ascent(QFontMetricsF)를 빼면 대체 글꼴이 섞인 글자('漢字テスト' — 이 Mac offscreen에서 9px)가 아래로 내려감;
    안쪽 여백 4를 빼면 왼쪽·위가 4px 어긋남."""
    annotation = ann("text", 0.125, 0.25, text=text, font_size=28)
    layer = new_layer([annotation])
    item = only_child(layer)
    assert item.pos().x() == 40 + 4
    if sys.platform != "win32":
        shown, burnt = bbox(red(render_layer(layer))), bbox(red(burned([annotation])))
        assert all(abs(a - b) <= 1 for a, b in zip(shown, burnt)), f"그린 글자 {shown} ≠ 구운 글자 {burnt}"


def test_layer_clips_to_frame_rect(qapp):
    """층은 프레임 사각형 밖을 그리지 않음 — 굽는 길이 프레임 밖을 자르듯: 프레임 가장자리를 따라 그린 굵은 사각형의 바깥 반, 오른쪽 끝을 넘는 글자가
    프레임 밖(뷰의 여백)에 보이지 않음; 안쪽 반은 보임.

    깨지는 변경: 층이 자식을 프레임 사각형으로 자르지 않으면(ItemClipsChildrenToShape) 획·글자가 프레임 둘레 여백에 그려짐."""
    edge = ann("rect", 0.0, 0.0, 1.0, 1.0, stroke_width=8)
    long_text = ann("text", 0.85, 0.4, text="오른쪽 끝을 넘는 글자", font_size=40)
    margin = 40
    image = red(render_layer(new_layer([edge, long_text]), QRectF(-margin, -margin, W + 2 * margin, H + 2 * margin)))
    inside = image[margin:margin + H, margin:margin + W].copy()
    image[margin:margin + H, margin:margin + W] = False
    assert not image.any(), f"프레임 밖에 그린 픽셀 {int(image.sum())}개"
    assert inside[:, :3].all() and inside[:3, :].all() and inside[:, -3:].all() and inside[-3:, :].all()


def test_update_reuses_items_and_clears(qapp):
    """같은 주석을 다시 주면 자식 아이템을 그대로 씀(같은 객체); 기하만 바뀌면 같은 객체의 기하만 바뀜; 종류가 바뀐 자리부터는 새로 만들되 쌓임은
    주석 차례 그대로(나중 주석이 위 — childItems는 쌓임 차례); 줄면 남는 것을 장면·층에서 뺌; 비우면(빈 목록·clear) 자식 0개·층 숨김, 다시 주면 보임.

    깨지는 변경: 매번 새로 만들면 객체가 바뀜(프레임마다 아이템 생성); 남는 자식을 지우지 않으면 지운 주석이 화면에 남음; 바뀐 자리의 새 아이템을
    끝에 덧붙이기만 하면 쌓임이 주석 차례와 어긋남; 빈 목록에서 숨기지 않으면 층이 남음."""
    rect, line, text = ann("rect"), ann("line"), ann("text", text="note")
    layer = new_layer([rect, line, text])
    scene = QGraphicsScene()
    scene.addItem(layer)
    first = layer.childItems()
    assert [type(item) for item in first] == [QGraphicsRectItem, QGraphicsLineItem, QGraphicsSimpleTextItem]
    assert layer.isVisible()

    layer.set_annotations([dict(rect), dict(line), dict(text)], W, H)
    assert layer.childItems() == first

    moved = dict(rect, norm_x1=0.25)
    layer.set_annotations([moved, line, text], W, H)
    assert layer.childItems() == first and first[0].rect().left() == 80.5

    ellipse = ann("ellipse")
    layer.set_annotations([moved, ellipse, text], W, H)
    now = layer.childItems()
    assert now[0] is first[0] and [type(item) for item in now] == [QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsSimpleTextItem]
    assert first[1].scene() is None and first[1].parentItem() is None
    order = scene.items(Qt.DescendingOrder)
    assert order.index(now[2]) < order.index(now[1]) < order.index(now[0])

    layer.set_annotations([moved], W, H)
    assert layer.childItems() == [first[0]] and now[1].scene() is None and now[2].scene() is None

    layer.set_annotations([], W, H)
    assert layer.childItems() == [] and not layer.isVisible()
    layer.set_annotations([rect], W, H)
    assert len(layer.childItems()) == 1 and layer.isVisible()
    layer.clear()
    assert layer.childItems() == [] and not layer.isVisible()


def test_layer_rect_follows_frame_size(qapp):
    """층의 사각형 = 프레임 (0, 0, 너비, 높이) — 해상도가 바뀌면 따라감(자르는 사각형), 같은 주석도 새 크기의 픽셀로.

    깨지는 변경: 처음 크기에 사각형을 고정하면 큰 프레임에서 오른쪽·아래 주석이 잘림."""
    layer = new_layer([ann("rect")])
    assert layer.rect() == QRectF(0, 0, W, H) and layer.pos().x() == 0 and layer.pos().y() == 0
    layer.set_annotations([ann("rect")], 3840, 2160)
    assert layer.rect() == QRectF(0, 0, 3840, 2160)
    assert only_child(layer).rect().left() == 480.5


# ---------------------------------------------------------------- 굽는 길은 그대로 (리팩터 전과 바이트까지)

def _legacy_hex_to_rgb(color_hex):
    color_hex = (color_hex or "#ff3333").lstrip("#")
    if len(color_hex) != 6:
        return (255, 51, 51)
    return tuple(int(color_hex[i : i + 2], 16) for i in (0, 2, 4))


def _legacy_paste_rgba_patch(frame, patch_rgb, mask, x, y):
    patch_h, patch_w = patch_rgb.shape[:2]
    frame_h, frame_w = frame.shape[:2]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(frame_w, x + patch_w)
    y2 = min(frame_h, y + patch_h)
    if x2 <= x1 or y2 <= y1:
        return

    sx1 = x1 - x
    sy1 = y1 - y
    sw = x2 - x1
    sh = y2 - y1
    region = frame[y1:y2, x1:x2]
    patch = patch_rgb[sy1 : sy1 + sh, sx1 : sx1 + sw]
    alpha = mask[sy1 : sy1 + sh, sx1 : sx1 + sw].astype(np.float32) / 255.0
    alpha = alpha[..., np.newaxis]
    frame[y1:y2, x1:x2] = (patch * alpha + region * (1.0 - alpha)).astype(np.uint8)


def _legacy_render_text_patch(text, color_hex, font_size=22):
    font = QFont("Apple SD Gothic Neo", font_size)
    if not QFont(font.family()).exactMatch():
        font = QFont("Malgun Gothic", font_size)
    if not QFont(font.family()).exactMatch():
        font = QFont("Arial", font_size)

    metrics = QFontMetrics(font)
    text_width = metrics.horizontalAdvance(text) + 8
    text_height = metrics.height() + 8
    image = QImage(text_width, text_height, QImage.Format_ARGB32)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setFont(font)
    painter.setPen(QColor(color_hex))
    painter.drawText(4, metrics.ascent() + 4, text)
    painter.end()

    buffer = image.bits()
    buffer.setsize(image.byteCount())
    array = np.frombuffer(buffer, dtype=np.uint8).reshape(text_height, text_width, 4)
    rgb = array[:, :, [2, 1, 0]].copy()
    alpha = array[:, :, 3].copy()
    return rgb, alpha


def _legacy_burn(frame, annotations):
    """434f230의 burn_annotations_on_frame 본문 그대로(이름만 _legacy_ — 리팩터 전 기준)."""
    if frame is None or not annotations:
        return frame

    output = frame.copy()
    height, width = output.shape[:2]
    auto_stroke = max(2, int(min(height, width) / 400))

    for annotation in annotations:
        ann_type = annotation.get("type", "rect")
        color = annotation.get("color", "#ff3333")
        rgb = _legacy_hex_to_rgb(color)
        stroke_width = int(annotation.get("stroke_width", auto_stroke))
        stroke_width = max(1, stroke_width)

        x1 = int(annotation.get("norm_x1", 0.0) * width)
        y1 = int(annotation.get("norm_y1", 0.0) * height)
        x2 = int(annotation.get("norm_x2", annotation.get("norm_x1", 0.0)) * width)
        y2 = int(annotation.get("norm_y2", annotation.get("norm_y1", 0.0)) * height)

        if ann_type == "text":
            text = annotation.get("text", "")
            if not text:
                continue
            font_size = int(annotation.get("font_size", max(14, int(min(height, width) / 45))))
            font_size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, font_size))
            patch_rgb, alpha = _legacy_render_text_patch(text, color, font_size=font_size)
            _legacy_paste_rgba_patch(output, patch_rgb, alpha, x1, y1)
        elif ann_type == "rect":
            cv2.rectangle(
                output,
                (min(x1, x2), min(y1, y2)),
                (max(x1, x2), max(y1, y2)),
                rgb,
                stroke_width,
            )
        elif ann_type == "ellipse":
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2
            axis_x = max(1, abs(x2 - x1) // 2)
            axis_y = max(1, abs(y2 - y1) // 2)
            cv2.ellipse(output, (center_x, center_y), (axis_x, axis_y), 0, 0, 360, rgb, stroke_width)
        elif ann_type == "line":
            cv2.line(output, (x1, y1), (x2, y2), rgb, stroke_width)
        elif ann_type == "arrow":
            tip_length = min(0.35, max(0.12, 0.08 + stroke_width * 0.02))
            cv2.arrowedLine(
                output, (x1, y1), (x2, y2), rgb, stroke_width, tipLength=tip_length
            )

    return output


LEGACY_SET = [
    ann("rect", 0.75, 0.8, 0.125, 0.2, stroke_width=3),
    {"type": "ellipse", "norm_x1": 0.3, "norm_y1": 0.3, "norm_x2": 0.61, "norm_y2": 0.77, "color": "#ffff00"},  # 굵기 없음 — 기본
    ann("line", 0.05, 0.95, 0.95, 0.05, stroke_width=1, color="#00ff00"),
    ann("arrow", 0.2, 0.9, 0.85, 0.15, stroke_width=4, color="#3366ff"),
    ann("text", 0.1, 0.1, text="수정 필요 note", color="#ffffff"),  # 크기 없음 — 기본
    ann("text", 0.6, 0.5, text="크게", font_size=200),
    ann("text", 0.6, 0.7, text="작게", font_size=5),
    ann("text", 0.5, 0.5, text=""),
    {"type": "rect", "norm_x1": 0.4, "norm_y1": 0.4, "stroke_width": 0},  # x2·y2 없음 — x1·y1, 굵기 0 → 1
    ann("rect", 0.3, 0.6, 0.45, 0.9, stroke_width=-1),  # 음수 굵기 → 1 (자르지 않으면 cv2는 음수를 '채움'으로 그림)
    ann("polygon"),
    ann("rect", 0.9, 0.9, 1.0, 1.0, stroke_width=6, color="#ff33"),  # 가장자리, 잘못된 색 → 빨강
]


@pytest.mark.parametrize("size", [(W, H), (1920, 1080), (720, 486)], ids=["320x180", "1080p", "720x486"])
def test_burn_output_unchanged_after_refactor(qapp, size):
    """같은 규칙을 두 길이 함께 쓰게 나눈(annotation_spec 등) 뒤에도 구운 프레임이 리팩터 전 함수(434f230 그대로 옮긴 _legacy_burn)와 바이트까지 같음 —
    다섯 종류·기본 굵기·기본 글자 크기·크기 자르기·빈 글자·x2 없음·굵기 0·음수 굵기·모르는 종류·가장자리·잘못된 색, 검정과 무늬 바탕. 내보내기가 여전히
    굽는 것은 무수정 tests/test_export.py가 지킴.

    깨지는 변경: 나눈 규칙(기본 굵기·1 아래 자르기·좌표·글자 크기·촉 길이·글꼴 고르기)이 하나라도 예전 식과 다르면 바이트가 달라짐."""
    width, height = size
    rng = np.random.default_rng(13)
    for background in (np.zeros((height, width, 3), np.uint8), rng.integers(0, 256, (height, width, 3), dtype=np.uint8)):
        assert np.array_equal(burn_annotations_on_frame(background, LEGACY_SET), _legacy_burn(background, LEGACY_SET))


# ---------------------------------------------------------------- 플레이어·위젯 (네이티브 프레임)

RECT = {"type": "rect", "norm_x1": 0.25, "norm_y1": 0.25, "norm_x2": 0.75, "norm_y2": 0.75, "color": "#ff3333", "stroke_width": 3}
ELLIPSE = {"type": "ellipse", "norm_x1": 0.25, "norm_y1": 0.25, "norm_x2": 0.75, "norm_y2": 0.75, "color": "#ff3333", "stroke_width": 3}


def test_native_frame_does_not_burn_but_overlay_updates(player_with_fake_native):
    """보이는 네이티브 프레임에 사각형 주석 하나 → 목록 갱신(refresh_annotation_ui — 다시 그림): 프레임은 굽지 않고 그대로(prepare_frame_for_display가
    같은 객체, set_sides의 A도 그 프레임), 주석 층이 보이고 자식 1개(z 13.5) — 사각형 (4, 2)–(12, 6) (16×8). 주석 없는 다음 프레임(재생 틱) → 층 숨김·
    자식 0개. OCR 검토 창 미리보기(_minimal_preview_seek — prepare_frame_for_display를 거치지 않음)로 주석 있는 61번(0부터 60)에 가면 층이 그 타원을 보임.
    그동안 네이티브 픽셀 접근 0.

    깨지는 변경: 플레이어가 공급자를 등록하지 않거나(set_annotation_provider) updateFrame의 네이티브 분기가 층을 갱신하지 않으면 층이 안 보임; 공급자가
    보이는 프레임(get_current_frame_index — 캡처 위치 − 1)이 아닌 주석을 주면 다음 프레임에 남거나 미리보기에서 빠짐; 층 갱신을
    prepare_frame_for_display에 두면 미리보기에서 앞 프레임의 층이 남음."""
    from yesoncheck.video_widget import ANNOTATION_OVERLAY_Z

    rig = player_with_fake_native
    player, widget = rig.player, rig.player.videoWidget
    layer = widget.annotation_overlay
    frame = player.frame_a
    assert player.get_current_frame_index() == 0 and not layer.isVisible()
    player.annotation_store.add(0, RECT)
    rig.sides.clear()

    player.refresh_annotation_ui()

    assert player.prepare_frame_for_display(frame) is frame
    assert rig.sides and rig.sides[-1].a is frame and player.frame_a is frame
    assert layer.isVisible() and layer.zValue() == ANNOTATION_OVERLAY_Z == 13.5
    child = only_child(layer)
    assert isinstance(child, QGraphicsRectItem) and child.rect() == QRectF(4.5, 2.5, 8, 4)

    player.next_frame_playback()
    assert player.get_current_frame_index() == 1 and player.frame_a is rig.cap_a.frames[1]
    assert not layer.isVisible() and layer.childItems() == []

    player.annotation_store.add(60, ELLIPSE)
    player._minimal_preview_seek(60, TOTAL)
    assert player.frame_a is rig.cap_a.frames[60]
    assert layer.isVisible() and isinstance(only_child(layer), QGraphicsEllipseItem)
    assert_untouched(rig)


def test_burn_frame_annotations_returns_native_frame_unchanged(player_with_fake_native):
    """burn_frame_annotations(네이티브 프레임) → 그 객체 그대로(복사·굽기 없음) — prepare_frame_for_display를 거치지 않고 부르는 곳이 있어도 읽기 전용
    표면을 복사하지 않음. 주석은 층의 몫.

    깨지는 변경: burn_frame_annotations의 네이티브 첫 줄 가드를 빼면 burn_annotations_on_frame이 frame.copy()(reads에 "copy")에 구워 손잡이 없는 4채널
    복사본을 돌려줌."""
    rig = player_with_fake_native
    player = rig.player
    player.annotation_store.add(player.get_current_frame_index(), RECT)
    frame = player.frame_a

    assert player.burn_frame_annotations(frame) is frame
    assert_untouched(rig)


def test_overlay_stacks_above_b_text_and_below_edit_preview(player_with_fake_native):
    """B 키 글자와 주석이 함께 보일 때 장면 쌓임: 주석(층의 자식) 위에 편집 미리보기(z 14)·편집 핸들(z 16), 아래에 B 키 글자와 그 흰 상자(z 13) —
    굽는 길이 B 글자를 먼저, 주석을 그 위에 굽는 것과 같은 차례(Ruling 18).

    깨지는 변경: 층의 z를 13 아래(예: 12)로 두면 B 키 흰 상자가 주석을 가림; 14 이상이면 편집 미리보기를 가림."""
    from yesoncheck.video_widget import ANNOTATION_OVERLAY_Z, OVERLAY_ITEM_Z

    rig = player_with_fake_native
    player, widget = rig.player, rig.player.videoWidget
    assert OVERLAY_ITEM_Z < ANNOTATION_OVERLAY_Z < 14
    player.show_overlay = True
    item = player.annotation_store.add(0, RECT)
    player.annotationModeButton.setChecked(True)
    player.refresh_annotation_ui()
    player._focus_annotation(item)
    widget.annotation_tool = "rect"  # 그리는 중의 미리보기(도형 도구) — 끌기 중간 그대로
    widget._update_annotation_preview(QPoint(2, 2), QPoint(40, 30))

    child = only_child(widget.annotation_overlay)
    box, text = widget.overlay_box_item, widget.overlay_text_item
    preview = widget.annotation_preview_item
    handles = widget.annotation_edit_handle_items
    assert box.isVisible() and text.isVisible() and child.isVisible() and preview is not None and handles
    order = widget.scene.items(Qt.DescendingOrder)
    assert all(order.index(handle) < order.index(child) for handle in handles)
    assert order.index(preview) < order.index(child) < order.index(text) < order.index(box)
    assert_untouched(rig)


@pytest.mark.parametrize("next_frame", ["rgb", "cleared"])
def test_rgb_frame_hides_annotation_overlay(player_with_fake_native, next_frame):
    """네이티브 프레임에 주석 층이 보이는 뒤에 RGB 프레임(굽는 길 — 주석은 프레임에 구움)이 오거나 화면을 비우면(frame None) 층을 비움 — 앞 네이티브
    프레임의 주석이 구운 주석과 겹치거나 빈 화면에 남지 않음.

    깨지는 변경: updateFrame의 RGB 길(또는 frame None 갈래)에서 층을 비우지 않으면 아이템이 남음."""
    rig = player_with_fake_native
    player, widget = rig.player, rig.player.videoWidget
    player.annotation_store.add(0, RECT)
    player.refresh_annotation_ui()
    assert widget.annotation_overlay.isVisible()

    widget.updateFrame(np.zeros((FAKE_HEIGHT, FAKE_WIDTH, 3), np.uint8) if next_frame == "rgb" else None, None)

    assert not widget.annotation_overlay.isVisible() and widget.annotation_overlay.childItems() == []


def test_rgb_a_with_native_b_burns_annotations_once(fake_native_player):
    """혼합 비교(A = cv2 RGB, B = 네이티브, 와이프 X): A는 굽는 길 그대로 — prepare_frame_for_display가 A의 복사본에 주석을 구워 set_sides의 A로
    넘기고, 네이티브 분기지만 층은 비어 있음(A의 주석은 이미 구웠으므로 두 번 그리지 않음). B의 픽셀 접근 0.

    깨지는 변경: 네이티브 분기에서 A가 네이티브인지 보지 않고 층을 채우면 구운 주석 위에 아이템이 한 번 더 보임."""
    rig = fake_native_player(ab=True, native="B", size=(32, 16), count=24)
    player, widget = rig.player, rig.player.videoWidget
    player.wipeXButton.setChecked(True)
    player.annotation_store.add(player.get_current_frame_index(), RECT)
    rig.sides.clear()

    player.update_frame()

    call = rig.sides[-1]
    assert call.b is player.frame_b and call.axis == "x"
    assert call.a is not player.frame_a and np.all(call.a == RED, axis=2).any(), "A에 주석이 구워지지 않음"
    assert not widget.annotation_overlay.isVisible() and widget.annotation_overlay.childItems() == []
    assert_untouched(rig)


@pytest.mark.parametrize("viewport, video_item", [("gl", "pixmap"), ("raster", None)], ids=["pixmap_kill_switch", "raster_viewport"])
def test_pixmap_path_shows_annotation_layer_too(fake_native_player, viewport, video_item):
    """픽스맵 아이템 길(킬 스위치 YESONCHECK_VIDEO_ITEM=pixmap·raster 뷰포트)도 같은 층: 주석 있는 프레임에서 보이고, 주석 없는 다음 틱에 숨음, 픽셀 접근 0.

    깨지는 변경: 층 갱신을 스트림 아이템(set_sides) 갈래에만 두면 픽스맵 길에서는 주석이 안 보임."""
    rig = fake_native_player(viewport=viewport, video_item=video_item)
    player, widget = rig.player, rig.player.videoWidget
    assert widget.video_item_stream is False
    player.annotation_store.add(0, RECT)

    player.refresh_annotation_ui()
    assert widget.annotation_overlay.isVisible() and len(widget.annotation_overlay.childItems()) == 1
    player.next_frame_playback()
    assert not widget.annotation_overlay.isVisible()
    assert widget._pixmap_backing is player.frame_a
    assert_untouched(rig)


def test_annotation_edits_on_native_frame_update_layer_without_pixels(fake_native_player):
    """멈춘 네이티브 프레임(320×180)에서 주석 모드로 사각형을 그리고(on_annotation_shape_finished — 그린 뒤 길), 몸통을 끌어 옮기고(누름·끎·놓음), 목록에서
    지우면(delete_selected_annotation): 층이 매번 따라감 — 1개 → 옮긴 자리 → 숨김. 그동안 네이티브 픽셀 접근 0(편집 손잡이·미리보기는 위젯이 따로 그림).

    깨지는 변경: 편집 뒤 다시 그리기(_redraw_frame_with_annotations → updateFrame)가 층을 갱신하지 않으면 옮긴 자리·지운 것이 화면에 반영되지 않음."""
    rig = fake_native_player(size=(W, H), count=4)
    player, widget = rig.player, rig.player.videoWidget
    layer = widget.annotation_overlay
    player.stop_video()
    player.annotationModeButton.setChecked(True)
    assert widget.annotation_mode_enabled

    player.on_annotation_shape_finished({"type": "rect", "norm_x1": 0.25, "norm_y1": 0.25, "norm_x2": 0.5, "norm_y2": 0.5,
                                         "color": "#ff3333", "stroke_width": 3})
    assert only_child(layer).rect() == QRectF(80.5, 45.5, 80, 45)

    player.on_annotation_move_pressed(0.375, 0.375)
    assert widget.annotation_edit_interaction
    player.on_annotation_move_dragged(0.5, 0.375)
    player.on_annotation_move_released(0.5, 0.375)
    assert only_child(layer).rect() == QRectF(120.5, 45.5, 80, 45)

    player.delete_selected_annotation()
    assert player.annotation_store.get_frame(player.get_current_frame_index()) == []
    assert not layer.isVisible() and layer.childItems() == []
    assert_untouched(rig)


def test_set_annotation_provider_requires_callable(player_with_fake_native):
    """주석 공급자는 호출할 수 있어야 함 — 아니면 TypeError(등록 때 바로; 프레임마다 부를 때 터지지 않게).

    깨지는 변경: 검사 없이 받아 두면 다음 네이티브 프레임에서 재생 타이머 슬롯 안의 TypeError."""
    widget = player_with_fake_native.player.videoWidget
    with pytest.raises(TypeError):
        widget.set_annotation_provider([RECT])
