"""네이티브 재생(Apple Silicon 전용: VideoToolbox → IOSurface → GL)을 쓸지의 판단 — 토글·플랫폼·파일 게이트. Qt·PyObjC 없음.

이 모듈은 어디서나(Windows·Intel Mac 포함) 불러올 수 있어야 하므로 판단만 한다: 실제 디코드·표시는 PyObjC가 있는 다른 모듈이
하고, 이 모듈의 답이 "아니오"면 기존 ffmpeg 파이프(movie_pipe_source)나 cv2 경로가 그대로 돈다. 불러오는 것은 순수 판정인
movie_pipe_source(ineligible_reason·MovieProbe — Qt는 알릴 때만 불러옴)뿐.

토글 YESONCHECK_MAC_NATIVE (YESONCHECK_MOVIE_SOURCE 선례 — 없거나 비면 auto, 대소문자 무시, 그 밖의 값은 ValueError):
  auto  Apple Silicon Mac(darwin이고 machine()이 arm64)이면 켬. Intel Mac은 꺼짐 — Rosetta 아래의 x86_64 빌드도 x86_64로
        보고하므로 꺼짐 (의도: 네이티브 경로는 Apple Silicon의 VideoToolbox 전제).
  on    켬 강제. macOS가 아니면 조용히 끄지 않고 ValueError (조용한 폴백 금지).
  off   끔 (킬 스위치).
"켬"은 후보일 뿐이고 파일마다 아래 게이트를 다시 통과해야 한다 — 양성 증거로만 켜지며 한 조건이라도 확인하지 못하면(값이 없거나
맞지 않으면) 음성이라 파이프 경로로 간다 (movie_pipe_source.pipe_eligible과 같은 원칙).

파일 게이트 (스펙 §5.4, 앞선 조건이 먼저 — native_ineligible_reason이 첫 어긋남을 조건 번호와 받은 값과 함께 돌려줌):
  ①~⑥  ffmpeg 파이프 게이트 그대로 (movie_pipe_source.ineligible_reason — 코덱 prores·일정한 프레임 속도·프레임 수/길이/속도
        일치·회전/화소 비율·시작 시각). 다시 구현하지 않고 부른다.
  ⑥½   4K: 너비 >= 3840 또는 높이 >= 2160. (4K 미만은 파이프도 실시간이라 네이티브의 이득이 없고 위험만 늘어남)
  ⑦    코덱이 prores. (① 파이프 대상 코덱이 늘어도 네이티브는 ProRes 디코더 전용이라 따로 둠)
  ⑧    4:4:4만 (yuv444p10le·yuv444p12le·yuva444p10le·yuva444p12le — 알파 포함). 4:2:2와 그 밖은 파이프에 남음.
  ⑨    색: 색 공간이 bt709·smpte170m·bt470bg(709/601 계열)이고, 범위는 tv·pc(또는 ffprobe가 안 줌), HDR이 아님
        (전달 함수 smpte2084·arib-std-b67 아님, 원색 bt2020 아님). 태그가 없는 파일은 파이프에 남음.

왜 4:2:2와 태그 없는 파일은 파이프에 남기나 (Stage 0 실측, 2026-11-03): 4:2:2는 VideoToolbox가 빠진 색차를 보간하고 ffmpeg(파이프)는
복사해서 홀수 열에서 최대 220 레벨 어긋남 — 4:4:4는 보간이 없어 실파일 4444(bt709)에서 최대 1·평균 0.03. 태그 없는 파일은 ffmpeg가
601로, VideoToolbox는 HD를 709로 읽어 ±4(사용자 허용 폭)를 넘으므로 추측하지 않고 기존 경로에 맡긴다. HDR은 이 앱이 톤매핑을
하지 않으므로 SDR 행렬로 잘못 칠하지 않게 거른다.
"""

import os
import platform
import sys

from yesoncheck.movie_pipe_source import ineligible_reason

NATIVE_MODE_ENV = "YESONCHECK_MAC_NATIVE"
NATIVE_MODES = ("auto", "on", "off")  # 환경 변수가 받는 값 (없거나 비어 있으면 "auto")

NATIVE_MIN_WIDTH = 3840  # ⑥½ 4K: 너비 또는 높이 하나만 닿아도 4K로 침 (UHD 3840×2160, DCI 4096×2160, 세로 영상 1920×2160 …)
NATIVE_MIN_HEIGHT = 2160
NATIVE_CODEC = "prores"  # ⑦
NATIVE_PIX_FMTS = ("yuv444p10le", "yuv444p12le", "yuva444p10le", "yuva444p12le")  # ⑧ ProRes 4444 디코더는 12비트로 내보냄 (알파 포함)
COLOR_SPACES_OK = ("bt709", "smpte170m", "bt470bg")  # ⑨ 709 / 601(NTSC·PAL) 계열
COLOR_RANGES_OK = ("", "unknown", "tv", "pc")  # ⑨ 범위 태그가 없어도 됨 (제한 범위로 읽음) — 있으면 tv·pc만
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")  # ⑨ PQ·HLG
HDR_PRIMARIES = "bt2020"  # ⑨ HDR이 아닌 BT.2020 SDR도 원색이 다르므로 같이 거름
UNTAGGED = ("", "unknown")  # ffprobe가 태그 없음을 나타내는 두 가지


def native_mode(env=os.environ):
    """YESONCHECK_MAC_NATIVE: 없거나 비면 "auto", "auto"·"on"·"off"(대소문자 무시)는 소문자로, 그 밖은 ValueError."""
    given = env.get(NATIVE_MODE_ENV, "")
    mode = given.lower() or "auto"
    if mode not in NATIVE_MODES:
        raise ValueError(f"{NATIVE_MODE_ENV}는 {', '.join(NATIVE_MODES)} 중 하나여야 합니다 (비우면 auto): {given!r}")
    return mode


def is_apple_silicon(platform_mod=platform, sys_mod=sys):
    """Apple Silicon Mac인가: macOS이고 이 프로세스가 arm64로 보고함 (Rosetta 아래의 x86_64 빌드·Windows ARM·Linux ARM은 아님)."""
    return sys_mod.platform == "darwin" and platform_mod.machine() == "arm64"


def native_wanted(env=os.environ, platform_mod=platform, sys_mod=sys):
    """토글과 플랫폼이 네이티브 경로를 후보로 삼는가 (파일 게이트는 따로). off는 아니오, on은 예(macOS가 아니면 ValueError),
    auto는 Apple Silicon일 때만 예."""
    mode = native_mode(env)
    if mode == "off":
        return False
    if mode == "on":
        if sys_mod.platform != "darwin":
            raise ValueError(f"{NATIVE_MODE_ENV}=on은 macOS에서만 쓸 수 있습니다 (이 시스템: {sys_mod.platform}) — 끄거나 auto로 두세요")
        return True
    return is_apple_silicon(platform_mod, sys_mod)


def _color_reason(probe):
    """⑨ 색 조건의 첫 어긋남 글, 없으면 None. HDR을 먼저 봄 — 진짜 HDR 파일은 색 공간도 bt2020nc라 순서가 반대면 사유가
    "색 공간이 아님"으로만 나와 HDR이라는 이유가 가려진다."""
    if probe.color_transfer in HDR_TRANSFERS:
        return f"⑨ HDR({probe.color_transfer})"
    if probe.color_primaries == HDR_PRIMARIES:
        return f"⑨ HDR(원색 {probe.color_primaries})"
    if probe.color_space in UNTAGGED:
        return f"⑨ 색 태그 없음(color_space {probe.color_space!r})"
    if probe.color_space not in COLOR_SPACES_OK:
        return f"⑨ 색 공간이 bt709/601 계열이 아님({probe.color_space})"
    if probe.color_range not in COLOR_RANGES_OK:
        return f"⑨ 색 범위가 tv/pc가 아님({probe.color_range})"
    return None


def native_ineligible_reason(probe):
    """네이티브 재생을 쓰면 안 되는 이유 한 줄 (모듈 설명의 ①~⑨ 중 처음 어긋난 조건, 앞에 조건 번호와 받은 값) — 모두 통과하면 None."""
    reason = ineligible_reason(probe)  # ①~⑥ 파이프 게이트 그대로
    if reason is not None:
        return reason
    if probe.width < NATIVE_MIN_WIDTH and probe.height < NATIVE_MIN_HEIGHT:  # ⑥½
        return f"⑥½ 4K가 아님({probe.width}×{probe.height})"
    if probe.codec != NATIVE_CODEC:  # ⑦
        return f"⑦ 코덱이 {NATIVE_CODEC}가 아님({probe.codec})"
    if probe.pix_fmt not in NATIVE_PIX_FMTS:  # ⑧
        return f"⑧ 4:4:4가 아님({probe.pix_fmt or '없음'})"
    return _color_reason(probe)  # ⑨


def native_eligible(probe):
    """네이티브 재생을 써도 되는 파일인가 (native_ineligible_reason이 None)."""
    return native_ineligible_reason(probe) is None
