# -*- coding: utf-8 -*-
"""(Windows) 축소 필터 설정 — 영상을 줄여 그릴 때 Linear(겹선형, 기본 — 예전 그대로) 또는 고품질(면적 평균). Qt 없음.

사용자 보고(2026-11-12, Windows 3840×1440 화면 배율 100%): "윈도 버전에서 같은 그림을 띄워도 라인이 지글거려 보여. 1대1 사이즈로 보면 괜찮은데."
원인은 필터가 아니라 줄이는 배율: 겹선형(Linear)은 그리는 픽셀마다 원본 점 넷만 섞어, 반쯤으로 줄이면 원본 픽셀을 띄엄띄엄 고르는 셈이라 1~2px 선이
어떤 곳은 진하고 어떤 곳은 옅음(같은 PC의 DJV·QuickTime Player도 같음 — 사용자 확인; 화면 배율 150%면 덜 줄여 덜함). Mac은 Retina(배율 2)라 같은 창에서
거의 줄이지 않아 깨끗함 — 그래서 **Windows만**: 메뉴(player_base)·설정 읽기(app.load_downscale_filter)가 Windows에서만 돌고, 다른 플랫폼은 이 값이
늘 Linear라 그리기가 예전과 같음(사용자 지시 "맥 버전은 전혀 문제 없기 때문에 수정하지 않아도 돼").

고품질(area): 그릴 자리의 장치 픽셀 크기로 프레임을 **면적 평균**해 줄이고(그리는 픽셀이 덮는 원본 픽셀을 모두 평균 — 선의 양이 보존됨), 그 그림을
**정수 크기·정수 장치 픽셀 자리에 1:1로** 그림(snapped_rect — 그릴 자리는 보통 크기도 자리도 소수라 그대로 맞춰 그리면 한 번 더 보간돼 흐려짐; GL은 자리가
반 픽셀만 어긋나도 이웃 픽셀과 섞임). 재생·정지 구분 없이 늘 같은 필터(사용자 지시 — 멈췄을 때만
다시 그리는 방식은 버림). 두 그리기 길이 이 규칙을 함께 씀: CPU 그리기 raster_video_item, GPU 그리기 gl_video_item(줄인 그림을 텍스처로 올림 —
새 GL 기능을 쓰지 않음). 대가는 프레임마다 줄이는 CPU 시간(이 Mac 실측 — CLAUDE.md '최근 변경 사항' 2026-11-12).

GPU 밉맵(GL_LINEAR_MIPMAP_LINEAR)을 쓰지 않은 까닭(CPU로 흉내 낸 수치 — 1px 선을 줄였을 때 선을 따라 잉크가 출렁이는 정도): 면적 평균 1.8%,
밉맵 1.9~6.8%, 겹선형 11~42% — 밉맵도 고르지만 두 단계를 섞어 그림이 흐려지고(면적 평균과의 평균 차가 겹선형보다 큼), 낡은 GL 기능
(GL_GENERATE_MIPMAP)이 Windows 드라이버마다 되는지 이 Mac에서 확인할 길이 없음.

설정은 이 PC의 prefs.json(windows_display.prefs_path — 화면 그리기 설정과 같은 파일)의 "downscale_filter". 이 창에는 바로 적용, 이미 열린 다른 창
(프로세스)은 다음에 켤 때부터. 값을 지어내지 않음: 깨진 파일은 UserFileError, 모르는 값은 ValueError.
"""

import math

import cv2

from yesoncheck import mac_prefs, windows_display

PREF_KEY = "downscale_filter"
FILTERS = ("linear", "area")
DEFAULT_FILTER = "linear"
MENU_TEXT = "축소 필터 (Windows)"
ACTION_TEXTS = {"linear": "Linear (기본)", "area": "고품질 (면적 평균)"}
TIPS = {
    "linear": "예전 방식 — 가장 빠름. 영상을 반쯤으로 줄여 보면 가는 선이 고르지 않을 수 있습니다",
    "area": "줄여 볼 때 가는 선이 고르게 보입니다 — 프레임마다 CPU로 줄이므로 4K 재생이 느려지면 Linear로 되돌리세요 (이 창에 바로 적용)",
}
SETTINGS_TITLE = "축소 필터 설정"
LOG_PREFIX = "[축소 필터]"
# 이 배율 미만으로 줄여 그릴 때만 미리 줄임 — 1:1 언저리(반올림으로 한두 픽셀 모자란 크기)는 예전 그리기가 더 정확함
DOWNSCALE_BELOW = 0.98

_preferred = DEFAULT_FILTER  # 프로세스 캐시 — app.load_downscale_filter가 시작 때 정하고 메뉴가 바꿈 (windows_display와 같은 모양)


def _checked(name):
    """FILTERS 안의 이름이면 그대로, 아니면 ValueError(키와 받은 값을 글에) — 조용히 기본으로 넘기지 않음."""
    if name not in FILTERS:
        raise ValueError(f"{PREF_KEY}는 {', '.join(FILTERS)} 중 하나여야 합니다: {name!r}")
    return name


def set_preferred(name) -> None:
    """FILTERS 밖의 값은 ValueError — 캐시는 그대로."""
    global _preferred
    _preferred = _checked(name)


def preferred() -> str:
    return _preferred


def read():
    """저장된 값 그대로 (없으면 기본). 깨진 파일은 UserFileError, 모르는 값은 부른 쪽이 set_preferred로 걸러 ValueError."""
    return mac_prefs.read_prefs(windows_display.prefs_path()).get(PREF_KEY, DEFAULT_FILTER)


def save(name) -> None:
    """파일에 저장 (그 키만 고침). 모르는 이름은 쓰기 전에 ValueError, 깨진 파일은 덮지 않고 UserFileError."""
    mac_prefs.update_pref(PREF_KEY, _checked(name), windows_display.prefs_path())


def snapped_rect(x0, y0, x1, y1, width, height):
    """width×height 프레임이 그려질 장치 픽셀 자리 (x0, y0)–(x1, y1)(왼쪽 위·오른쪽 아래, 소수) → 면적 평균으로 미리 줄여 그릴 **정수** 자리
    (왼쪽, 위, 너비, 높이). 줄여 그리는 경우가 아니면(두 축 모두 DOWNSCALE_BELOW 이상 — 1:1·키워 그리기) None, 뒤집혔거나 빈 자리도 None — 예전 그리기에 맡김.
    반올림은 Qt처럼 .5 올림(파이썬 round·int 아님 — 음수 자리에서도 가장 가까운 픽셀)."""
    span_x, span_y = x1 - x0, y1 - y0
    if span_x <= 0 or span_y <= 0:
        return None
    if span_x >= width * DOWNSCALE_BELOW and span_y >= height * DOWNSCALE_BELOW:
        return None
    return math.floor(x0 + 0.5), math.floor(y0 + 0.5), max(1, math.floor(span_x + 0.5)), max(1, math.floor(span_y + 0.5))


def area_scaled(frame, width, height):
    """(높이, 너비, 채널) uint8 배열을 width×height로 면적 평균해 줄인 새 배열 (C 연속) — GPU 그리기가 텍스처로 올릴 그림."""
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
