"""icon.icns에서 Windows용 icon.ico를 만듭니다.

icon.icns는 사실 1920x1080 크기의 가로로 긴 PNG입니다 (투명 배경에 "YESON ▶ CHECK" 배지).
Pillow의 ICO 저장은 원본 가로세로 비율을 그대로 유지하므로, 이 파일을 바로 ICO로 저장하면
모든 크기(256x144, 16x9 등)가 정사각형이 아니게 됩니다 (Windows 탐색기·타이틀바에서 아이콘이
눌린 것처럼 보이는 원인). 그래서 알파 채널의 실제 그림 영역만 잘라낸 뒤, 그 그림을 한 변이
긴 쪽 길이인 투명 정사각형 캔버스 가운데에 올려서(비율 유지, 늘이지 않음) 정사각형 ICO를 만듭니다.

사용법: ~/coding/p310/bin/python tools/make_icon_ico.py
"""

import os

from PIL import Image

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT_ROOT, "icon.icns")
DEST = os.path.join(PROJECT_ROOT, "icon.ico")
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main():
    im = Image.open(SRC).convert("RGBA")
    alpha = im.split()[-1]
    bbox = alpha.getbbox()
    if bbox is None:
        raise SystemExit(f"[make_icon_ico] {SRC}의 알파 채널이 모두 투명합니다")
    cropped = im.crop(bbox)
    side = max(cropped.width, cropped.height)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    offset = ((side - cropped.width) // 2, (side - cropped.height) // 2)
    canvas.paste(cropped, offset, cropped)
    canvas.save(DEST, sizes=SIZES)
    print(f"[make_icon_ico] {SRC} {im.size} -> bbox {bbox} -> 정사각형 캔버스 {canvas.size} -> {DEST}")


if __name__ == "__main__":
    main()
