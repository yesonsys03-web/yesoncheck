"""주석 층 — 네이티브(IOSurface) 프레임의 주석을 굽지 않고 Qt 아이템으로 겹쳐 그림 (Mac 네이티브 재생).

네이티브 프레임은 읽기 전용 표면이라 burn_annotations_on_frame처럼 픽셀 복사본에 구울 수 없다(복사하면 4K 프레임마다 CPU 복사·변환이 생기고, 복사본은
손잡이 없는 4채널 배열이라 GL 아이템의 RGB 길에서 실패). 그래서 CustomVideoWidget이 이 층 하나를 장면에 두고(z ANNOTATION_OVERLAY_Z — B 키 상자 위,
편집 미리보기 아래), updateFrame의 네이티브 분기가 플레이어의 공급자에게 받은 보이는 프레임의 주석으로 프레임마다 set_annotations, RGB 프레임이면
clear(그때 주석은 프레임에 구움). 위젯이 아이템을 갖고 플레이어가 주석(데이터)을 가짐.

좌표: 층은 장면 원점의 프레임 사각형(0, 0, 너비, 높이 — 영상 아이템과 같은 자리·크기)이라 층 좌표 = 프레임 픽셀. ItemIgnoresTransformations 없음 —
구운 픽셀처럼 줌·맞춤에 따라 함께 커짐. 층은 자식을 그 사각형으로 자름(ItemClipsChildrenToShape — cv2가 프레임 밖을 자르고 글자 패치를 프레임 끝에서
자르는 것과 같게; 없으면 오른쪽 끝을 넘는 글자·가장자리 획의 바깥 반이 뷰의 여백에 보임). 층 자체는 그리지 않음(ItemHasNoContents·펜·붓 없음).
기하는 굽는 길과 같은 함수(annotation_burn.annotation_spec — 좌표·기본 굵기·글자 크기, rect_corners·ellipse_center_axes·arrow_tip_points·
annotation_font)이고, 픽셀 격자에 놓는 법만 아이템의 몫:
- cv2 정수 좌표 p는 픽셀 p의 가운데 → 아이템 좌표 p + 0.5 (PIXEL_CENTER — 없으면 안티앨리어싱 뷰에서 획이 반 픽셀 왼쪽 위로 번짐)
- 획 폭은 cv2가 그 굵기로 실제로 덮는 폭(burned_stroke_extent — 굵기 3을 5px로 칠함; 굵기 그대로 두면 구운 획보다 눈에 띄게 가늚), 둥근 끝·둥근 이음
  (cv2 굵은 선은 끝·꺾임에 원을 칠함 — 사각형 모서리도 둥긂)
- 글자: 굽는 길의 패치(render_text_patch)는 (x1, y1)에서 시작하고 글자를 (4, 4 + 주 글꼴 ascent)에 그림 → 기준선 (x1 + 4, y1 + 4 + ascent).
  QGraphicsSimpleTextItem은 글줄 위를 원점으로 두고 기준선을 글줄 ascent(QTextLayout — 대체 글꼴이 섞이면 주 글꼴보다 큼)에 두므로 그만큼 올려 놓음.
  글자 아이템은 줄바꿈(\\n)을 여러 줄로 그리지만 굽는 길(drawText)은 한 줄 — 앱의 입력 창(QInputDialog.getText)은 한 줄만 받음.
알고 둔 차이(눈 확인 몫): Qt는 안티앨리어싱(뷰 설정)으로, cv2는 계단(LINE_8)으로 그림; 레티나에서는 아이템이 화면 해상도로 그려져 구운 글자보다 또렷함;
와이프가 켜져도 층은 A 위에 통째로(굽는 길은 B 쪽에서 주석이 잘림); ROI(10)·와이프 선(0)보다 위.
"""

from PyQt5.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QFontMetrics, QPainterPath, QPen, QTextLayout
from PyQt5.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
)

from yesoncheck.annotation_burn import (
    TEXT_PATCH_INSET,
    annotation_font,
    annotation_spec,
    arrow_tip_length,
    arrow_tip_points,
    burned_stroke_extent,
    ellipse_center_axes,
    rect_corners,
)

PIXEL_CENTER = 0.5  # cv2 정수 좌표 p(픽셀 p) → 아이템 좌표 p + 0.5(그 픽셀의 가운데)

ITEM_CLASSES = {
    "rect": QGraphicsRectItem,
    "ellipse": QGraphicsEllipseItem,
    "line": QGraphicsLineItem,
    "arrow": QGraphicsPathItem,
    "text": QGraphicsSimpleTextItem,
}


def drawable(spec):
    """굽는 길이 그리는 주석인지 — 아는 종류이고, 글자 주석이면 글자가 있음(빈 글자·모르는 종류는 굽는 길도 건너뜀)."""
    return spec.kind in ITEM_CLASSES and (spec.kind != "text" or bool(spec.text))


def _center(value):
    return value + PIXEL_CENTER


def _stroke_pen(spec):
    """도형의 펜 — 주석 색(spec.rgb — 굽는 길의 hex_to_rgb), 폭은 cv2가 덮는 폭, 둥근 끝·이음. 굵기는 프레임 픽셀(cosmetic 아님 — 줌과 함께 커짐)."""
    pen = QPen(QColor(*spec.rgb))
    pen.setWidthF(burned_stroke_extent(spec.stroke_width))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCosmetic(False)
    return pen


def _text_line_ascent(text, font):
    """QGraphicsSimpleTextItem이 글자를 놓는 글줄의 ascent — 아이템과 같은 배치(줄바꿈 → 줄 구분자, 장치 없는 QTextLayout)의 첫 줄."""
    layout = QTextLayout(text.replace("\n", "\u2028"), font)
    layout.beginLayout()
    line = layout.createLine()
    layout.endLayout()
    return line.ascent()


def _apply(spec, item):
    """아이템 하나를 spec의 기하·색으로 (층 좌표 = 프레임 픽셀)."""
    x1, y1, x2, y2 = spec.x1, spec.y1, spec.x2, spec.y2
    if spec.kind == "text":
        font = annotation_font(spec.font_size)
        baseline = y1 + TEXT_PATCH_INSET + QFontMetrics(font).ascent()  # 굽는 길의 drawText 기준선 (정수 ascent)
        item.setFont(font)
        item.setText(spec.text)
        item.setBrush(QBrush(QColor(spec.color)))  # 굽는 길의 글자 펜 QColor(색 글자)와 같음
        item.setPos(x1 + TEXT_PATCH_INSET, baseline - _text_line_ascent(spec.text, font))
        return
    item.setPen(_stroke_pen(spec))
    if spec.kind == "rect":
        left, top, right, bottom = rect_corners(x1, y1, x2, y2)
        item.setRect(QRectF(QPointF(_center(left), _center(top)), QPointF(_center(right), _center(bottom))))
    elif spec.kind == "ellipse":
        center_x, center_y, axis_x, axis_y = ellipse_center_axes(x1, y1, x2, y2)
        item.setRect(QRectF(_center(center_x - axis_x), _center(center_y - axis_y), 2 * axis_x, 2 * axis_y))
    elif spec.kind == "line":
        item.setLine(QLineF(_center(x1), _center(y1), _center(x2), _center(y2)))
    elif spec.kind == "arrow":
        tip = QPointF(_center(x2), _center(y2))
        path = QPainterPath(QPointF(_center(x1), _center(y1)))
        path.lineTo(tip)
        for tip_x, tip_y in arrow_tip_points(x1, y1, x2, y2, arrow_tip_length(spec.stroke_width)):
            path.moveTo(_center(tip_x), _center(tip_y))
            path.lineTo(tip)
        item.setPath(path)
    else:
        raise ValueError(f"그릴 수 없는 주석 종류입니다: {spec.kind!r}")  # drawable이 거른 뒤라 닿으면 코드 오류
    if spec.kind != "line":
        item.setBrush(QBrush(Qt.NoBrush))


class AnnotationOverlay(QGraphicsRectItem):
    """주석 층 (모듈 설명) — 프레임 사각형 하나가 주석마다 자식 아이템을 가짐. 보임/숨김·z는 이 층 하나로; 자식의 쌓임은 주석 차례(나중 주석이 위 —
    굽는 차례와 같음). 프레임마다 불려도 싸게: 주석의 그릴 값(AnnotationSpec)이 앞과 같으면 그 자식은 건드리지 않음."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPen(QPen(Qt.NoPen))
        self.setBrush(QBrush(Qt.NoBrush))
        self.setFlag(QGraphicsItem.ItemHasNoContents, True)
        self.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        self.setVisible(False)
        self._drawn = []  # [(AnnotationSpec, 자식 아이템)] — 쌓임 차례(주석 차례)

    def set_annotations(self, annotations, width, height):
        """annotations(주석 dict 목록 — 플레이어의 annotation_store.get_frame)을 width×height 프레임에 그림. 그리지 않는 주석(drawable 아님)은 건너뜀;
        그릴 것이 없으면 층을 숨김. 자식은 다시 씀: 앞에서부터 종류가 같은 동안은 그 아이템의 기하만(값이 바뀐 것만) 고치고, 종류가 달라진 자리부터는
        지우고 새로 만들어 붙임(새 아이템은 형제 중 맨 위에 쌓이므로 차례가 주석 차례 그대로). (QGraphicsItem.update — 다시 그리기 요청 — 와 이름이
        겹치지 않게 set_annotations)"""
        specs = [spec for spec in (annotation_spec(annotation, width, height) for annotation in annotations) if drawable(spec)]
        frame_rect = QRectF(0, 0, width, height)
        if self.rect() != frame_rect:
            self.setRect(frame_rect)
        keep = 0
        while keep < min(len(specs), len(self._drawn)) and specs[keep].kind == self._drawn[keep][0].kind:
            keep += 1
        self._remove_from(keep)
        for index in range(keep):
            old_spec, item = self._drawn[index]
            if specs[index] != old_spec:
                _apply(specs[index], item)
                self._drawn[index] = (specs[index], item)
        for spec in specs[keep:]:
            item = ITEM_CLASSES[spec.kind](self)
            _apply(spec, item)
            self._drawn.append((spec, item))
        self.setVisible(bool(self._drawn))

    def clear(self):
        """자식을 모두 빼고 숨김 — RGB 프레임(주석은 구움)·빈 화면. 이미 비어 있으면 할 일 없음(RGB 재생의 틱마다 불림)."""
        if not self._drawn and not self.isVisible():
            return
        self._remove_from(0)
        self.setVisible(False)

    def _remove_from(self, index):
        """index번 자식부터 끝까지 장면·층에서 뺌(파이썬 참조를 놓으면 지워짐)."""
        scene = self.scene()
        for _spec, item in self._drawn[index:]:
            if scene is not None:
                scene.removeItem(item)
            else:
                item.setParentItem(None)
        del self._drawn[index:]
