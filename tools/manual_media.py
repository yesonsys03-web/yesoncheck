"""사용법 매뉴얼 스크린샷에 쓰는 합성 영상·이미지 시퀀스 만들기 (개발 도구 — 앱에 들어가지 않음).

저장소가 공개라 스크린샷에 실제 작품의 그림·이름·경로가 들어가면 안 됨 → 여기서 직접 그린 그림만 씀:
도형으로 그린 장면 다섯(언덕·얼굴·도시·자동차·나무)을 연필 스케치(TK1)와 색을 칠한 판(TK2) 두 가지로.
파일 이름도 지어낸 것(`EP101_SC001_TK1.mov`). 왼쪽 아래의 슬레이트 글자(`SEQ 01A_S01 - PANEL 1`)는 OCR ROI 설명용.

`make_media(root, ffmpeg)`가 만드는 것:
  root/EP101/EP101_SC00n_TK1.mov (n = 1..5, 스케치) · EP101_SC001_TK2.mov · EP101_SC002_TK2.mov (색)
  root/EP101/EP101_SC00n_TK1-00NN.png (n = 1..3, 이미지 시퀀스 12장씩)
  root/ANIMATIC/EP101_ANIMATIC_v03.mov (다섯 장면을 이은 애니매틱)
"""
import math
import os
import subprocess

import cv2
import numpy as np

WIDTH, HEIGHT = 1280, 720
FPS = 24
SHOT_FRAMES = 48  # 샷 하나 2초
ANIMATIC_SCENE_FRAMES = 30
SEQUENCE_FRAMES = 12
SEQUENCE_SIZE = (640, 360)
ANIMATIC_NAME = "EP101_ANIMATIC_v03.mov"

INK = (46, 42, 40)  # BGR — 연필 선
AA = cv2.LINE_AA

# 이름 → (스케치 색, 칠한 색) BGR
PALETTE = {
    "sky": ((240, 239, 235), (238, 214, 168)),
    "ground": ((226, 224, 218), (128, 196, 140)),
    "hill": ((214, 212, 206), (104, 172, 112)),
    "hill_far": ((224, 222, 216), (140, 190, 150)),
    "sun": ((250, 250, 248), (96, 214, 255)),
    "house": ((236, 234, 230), (214, 228, 246)),
    "roof": ((204, 202, 196), (92, 98, 214)),
    "skin": ((238, 236, 232), (190, 214, 250)),
    "hair": ((180, 178, 172), (60, 70, 110)),
    "night": ((222, 220, 214), (120, 70, 50)),
    "building": ((206, 204, 198), (150, 110, 90)),
    "window": ((244, 243, 240), (140, 230, 255)),
    "road": ((200, 198, 192), (90, 90, 96)),
    "car": ((232, 230, 226), (70, 80, 230)),
    "trunk": ((196, 194, 188), (70, 110, 150)),
    "leaf": ((218, 216, 210), (90, 170, 80)),
}


def _colors(colored):
    return lambda name: PALETTE[name][1 if colored else 0]


def _outline_circle(img, center, radius, fill):
    cv2.circle(img, center, radius, fill, -1, AA)
    cv2.circle(img, center, radius, INK, 3, AA)


def _outline_rect(img, p1, p2, fill):
    cv2.rectangle(img, p1, p2, fill, -1)
    cv2.rectangle(img, p1, p2, INK, 3, AA)


def _outline_poly(img, points, fill):
    pts = np.array(points, np.int32)
    cv2.fillPoly(img, [pts], fill, AA)
    cv2.polylines(img, [pts], True, INK, 3, AA)


def _hill(img, center, axes, fill):
    cv2.ellipse(img, center, axes, 0, 180, 360, fill, -1, AA)
    cv2.ellipse(img, center, axes, 0, 180, 360, INK, 3, AA)


def scene_hills(img, t, c):
    img[:] = c("sky")
    _outline_circle(img, (int(260 + 520 * t), 170), 64, c("sun"))
    _hill(img, (980, 590), (520, 260), c("hill_far"))
    _hill(img, (360, 590), (560, 220), c("hill"))
    cv2.rectangle(img, (0, 560), (WIDTH, HEIGHT), c("ground"), -1)
    cv2.line(img, (0, 560), (WIDTH, 560), INK, 3, AA)
    _outline_rect(img, (820, 440), (960, 560), c("house"))
    _outline_poly(img, [(800, 440), (890, 360), (980, 440)], c("roof"))
    _outline_rect(img, (872, 500), (908, 560), c("roof"))


def scene_face(img, t, c):
    img[:] = c("sky")
    bob = int(14 * math.sin(t * 2 * math.pi))
    cx, cy = 640, 350 + bob
    cv2.ellipse(img, (cx, cy - 60), (236, 220), 0, 180, 360, c("hair"), -1, AA)
    _outline_circle(img, (cx, cy), 210, c("skin"))
    blink = 0.45 < t < 0.55
    for ex in (cx - 78, cx + 78):
        if blink:
            cv2.line(img, (ex - 24, cy - 30), (ex + 24, cy - 30), INK, 4, AA)
        else:
            _outline_circle(img, (ex, cy - 30), 24, (250, 250, 250))
            cv2.circle(img, (ex + int(8 * math.cos(t * 2 * math.pi)), cy - 30), 9, INK, -1, AA)
    cv2.ellipse(img, (cx, cy + 70), (84, 46), 0, 10, 170, INK, 4, AA)


def scene_city(img, t, c):
    img[:] = c("night")
    _outline_circle(img, (1040 - int(120 * t), 140), 52, c("sun"))
    heights = (300, 420, 240, 480, 340, 270)
    for index, height in enumerate(heights):
        x = 60 + index * 200
        _outline_rect(img, (x, 640 - height), (x + 160, 640), c("building"))
        for row in range(height // 70):
            for col in range(3):
                wx, wy = x + 22 + col * 44, 640 - height + 24 + row * 62
                lit = (index + row + col + int(t * 4)) % 3 != 0
                cv2.rectangle(img, (wx, wy), (wx + 28, wy + 36), c("window") if lit else c("building"), -1)
                cv2.rectangle(img, (wx, wy), (wx + 28, wy + 36), INK, 2, AA)
    cv2.rectangle(img, (0, 640), (WIDTH, HEIGHT), c("road"), -1)
    cv2.line(img, (0, 640), (WIDTH, 640), INK, 3, AA)


def scene_car(img, t, c):
    img[:] = c("sky")
    _hill(img, (640, 520), (760, 190), c("hill_far"))
    cv2.rectangle(img, (0, 500), (WIDTH, HEIGHT), c("road"), -1)
    cv2.line(img, (0, 500), (WIDTH, 500), INK, 3, AA)
    for x in range(-120 + int(-240 * t) % 240, WIDTH, 240):
        cv2.line(img, (x, 610), (x + 120, 610), (244, 243, 240), 8, AA)
    x = int(120 + 760 * t)
    _outline_poly(img, [(x + 70, 440), (x + 110, 380), (x + 250, 380), (x + 300, 440)], c("window"))
    _outline_rect(img, (x, 440), (x + 380, 530), c("car"))
    for wx in (x + 84, x + 296):
        _outline_circle(img, (wx, 536), 42, (70, 68, 66))
        cv2.circle(img, (wx, 536), 14, (220, 220, 220), -1, AA)


def scene_tree(img, t, c):
    img[:] = c("sky")
    cv2.rectangle(img, (0, 580), (WIDTH, HEIGHT), c("ground"), -1)
    cv2.line(img, (0, 580), (WIDTH, 580), INK, 3, AA)
    _outline_rect(img, (360, 380), (420, 580), c("trunk"))
    sway = int(10 * math.sin(t * 2 * math.pi))
    for dx, dy, radius in ((-90, 20, 96), (90, 20, 96), (0, -70, 120), (0, 40, 110)):
        _outline_circle(img, (390 + dx + sway, 300 + dy), radius, c("leaf"))
    bx, by = int(1180 - 620 * t), 190 + int(30 * math.sin(t * 4 * math.pi))
    flap = int(26 * math.sin(t * 12 * math.pi))
    cv2.polylines(img, [np.array([(bx - 46, by - flap), (bx, by), (bx + 46, by - flap)], np.int32)], False, INK, 5, AA)


SCENES = (scene_hills, scene_face, scene_city, scene_car, scene_tree)
SLATES = ("SEQ 01A_S01 - PANEL 1", "SEQ 01A_S02 - PANEL 1", "SEQ 01A_S03 - PANEL 2", "SEQ 01B_S01 - PANEL 1",
          "SEQ 01B_S02 - PANEL 3")


def slate_box(text):
    """슬레이트 글자 상자의 자리 (x1, y1, x2, y2) — 스크린샷 도구가 OCR ROI를 이 위에 놓음."""
    (text_width, text_height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.95, 2)
    x, y = 44, HEIGHT - 40
    return x - 14, y - text_height - 14, x + text_width + 14, y + baseline + 10


def draw_slate(img, text):
    x1, y1, x2, y2 = slate_box(text)
    cv2.rectangle(img, (x1, y1), (x2, y2), (255, 255, 255), -1)
    cv2.rectangle(img, (x1, y1), (x2, y2), INK, 2, AA)
    cv2.putText(img, text, (44, HEIGHT - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (20, 20, 20), 2, AA)


def frame(scene_index, t, colored=False, slate=None):
    """장면 하나의 한 장 (BGR). t는 0 이상 1 미만의 진행."""
    img = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    SCENES[scene_index](img, t, _colors(colored))
    draw_slate(img, SLATES[scene_index] if slate is None else slate)
    return img


def encode(ffmpeg, path, frames):
    """BGR 프레임들을 H.264 mov로 (번들 ffmpeg — 파이프로 넘김)."""
    process = subprocess.Popen(
        [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
         "-i", "pipe:0", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "12", "-threads", "2", path],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for image in frames:
        process.stdin.write(image.tobytes())
    process.stdin.close()
    stderr = process.stderr.read().decode("utf-8", "replace")
    if process.wait() != 0:
        raise RuntimeError(f"합성 영상을 만들지 못함: {path}\n{stderr}")


def make_media(root, ffmpeg):
    job = os.path.join(root, "EP101")
    animatic = os.path.join(root, "ANIMATIC")
    os.makedirs(job)
    os.makedirs(animatic)
    for index in range(len(SCENES)):
        encode(ffmpeg, os.path.join(job, f"EP101_SC{index + 1:03d}_TK1.mov"),
               (frame(index, n / SHOT_FRAMES) for n in range(SHOT_FRAMES)))
    for index in (0, 1):
        encode(ffmpeg, os.path.join(job, f"EP101_SC{index + 1:03d}_TK2.mov"),
               (frame(index, n / SHOT_FRAMES, colored=True) for n in range(SHOT_FRAMES)))
    for index in range(3):
        for n in range(SEQUENCE_FRAMES):
            image = cv2.resize(frame(index, n / SEQUENCE_FRAMES, colored=True), SEQUENCE_SIZE, interpolation=cv2.INTER_AREA)
            name = f"EP101_SC{index + 1:03d}_TK1-{n + 1:04d}.png"
            if not cv2.imwrite(os.path.join(job, name), image):
                raise RuntimeError(f"시퀀스 프레임을 쓰지 못함: {name}")
    encode(ffmpeg, os.path.join(animatic, ANIMATIC_NAME),
           (frame(index, n / ANIMATIC_SCENE_FRAMES) for index in range(len(SCENES)) for n in range(ANIMATIC_SCENE_FRAMES)))
