"""네이티브 재생(VideoToolbox → IOSurface → GL)을 쓸지의 판단 — 토글·플랫폼·파일 게이트. Qt·PyObjC 없음.

이 모듈은 어디서나(Windows·Intel Mac 포함) 불러올 수 있어야 하므로 판단만 한다: 실제 디코드·표시는 PyObjC가 있는 다른 모듈이
하고, 이 모듈의 답이 "아니오"면 기존 ffmpeg 파이프(movie_pipe_source)나 cv2 경로가 그대로 돈다. 불러오는 것은 순수 판정인
movie_pipe_source(ineligible_reason·MovieProbe — Qt는 알릴 때만 불러옴)뿐.

토글 YESONCHECK_MAC_NATIVE (YESONCHECK_MOVIE_SOURCE 선례 — 없거나 비면 auto, 대소문자 무시, 그 밖의 값은 ValueError):
  auto  macOS(darwin)면 칩과 상관없이, 사용자의 재생 디코더 설정이 videotoolbox(기본)일 때 켬 — Apple Silicon도 Intel Mac(Rosetta 아래
        x86_64 빌드 포함)도. 설정이 ffmpeg(예전 방식)면 꺼짐. macOS가 아니면(Windows·Linux, ARM이어도) 설정과 무관하게 꺼짐 (VideoToolbox가 없음).
  on    켬 강제 (설정을 덮음). macOS가 아니면 조용히 끄지 않고 ValueError (조용한 폴백 금지).
  off   끔 (킬 스위치 — 설정을 덮음).

재생 디코더 설정 (prefs.json의 "playback_decoder": "videotoolbox" | "ffmpeg", 없으면 videotoolbox) — 우선순위 환경 변수(on·off) > 설정 > 기본:
이 모듈은 파일을 읽지 않는다 (순수 유지 — 파일 I/O·Qt 없음). app.launch가 Mac에서 시작 때 한 번 mac_prefs로 읽어 검증한 값을 이 모듈의 프로세스
캐시에 넣고(set_preferred_decoder), native_wanted는 그 캐시만 본다. 캐시는 (디코더, 출처)를 함께 기억해 effective_decoder가 지금 유효한
디코더와 그 출처("환경 변수 YESONCHECK_MAC_NATIVE=on|off"·"prefs.json"·"기본값", 설정을 읽지 못해 이 세션만 ffmpeg면 SOURCE_FALLBACK)를 돌려줌 —
시작 기록과 Setting 메뉴가 같은 판단을 씀 (환경 변수가 덮는 경우는 출처가 "환경 변수"로 시작).
다른 창(프로세스)의 캐시는 건드리지 않는다: 설정을 바꾸면 다른 창은 다음에 켤 때 따라온다.
"켬"은 후보일 뿐이고 파일마다 아래 게이트를 다시 통과해야 한다 — 양성 증거로만 켜지며 한 조건이라도 확인하지 못하면(값이 없거나
맞지 않으면) 음성이라 파이프 경로로 간다 (movie_pipe_source.pipe_eligible과 같은 원칙).

파일 게이트 (앞선 조건이 먼저 — native_ineligible_reason이 첫 어긋남을 조건 번호와 받은 값과 함께 돌려줌):
  ①~⑥  ffmpeg 파이프 게이트 그대로 (movie_pipe_source.ineligible_reason — 코덱 prores·일정한 프레임 속도·프레임 수/길이/속도
        일치·회전/화소 비율·시작 시각). 다시 구현하지 않고 부른다.
  ⑦    코덱이 prores. (① 파이프 대상 코덱이 늘어도 네이티브는 ProRes 디코더 전용이라 따로 둠)
  ⑨    HDR이 아님: 전달 함수가 smpte2084·arib-std-b67(PQ·HLG)이 아니고 원색이 bt2020이 아님.
이 두 가지 밖에는 조건이 없다: 크기(4K 아니어도), 크로마(4:2:2도), 색 공간·범위 태그(없어도)는 보지 않는다. 옛 ⑥½(4K)·⑧(4:4:4)과
옛 ⑨의 색 태그 조건은 지웠고 번호는 다시 매기지 않는다 (기록·문서의 "⑨ HDR(…)"이 그대로 읽히게).

왜 HDR이 아닌 모든 ProRes를 네이티브로 보내나 (사용자 결정 2026-11-04 — "업계는 QuickTime 기준", VideoToolbox는 QuickTime과 같은 필터·행렬):
- 4:2:2: VideoToolbox는 빠진 색차를 보간하고 ffmpeg(파이프)는 복사한다. 실파일 1080p 4:2:2 HQ에서 파이프(bgr24) 대비 평균 1.4·최대 73,
  4를 넘는 픽셀 2.6%는 전부 홀수 열 — 색차(4:2:2 → 4:4:4) 수평 보간 필터 하나의 차이라 화면 전체로는 보이지 않고 색이 급변하는
  가장자리 1픽셀에서만 다르며, VideoToolbox 쪽이 QuickTime과 같다. (4:4:4는 보간이 없어 실파일 4444에서 최대 1·평균 0.03.)
- 색 태그가 없는 파일: VideoToolbox는 QuickTime처럼 HD를 709, SD를 601로 읽고 ffmpeg는 601로 가정한다 — 네이티브로 가면 태그 없는 HD가
  QuickTime과 같아진다 (예전 파이프 화면과는 달라짐).
- HDR만 거른다: 이 앱은 톤매핑을 하지 않으므로 SDR 행렬로 잘못 칠하지 않게 파이프에 남긴다.
- 크기로 가르지 않는다: 옛 근거(4K 미만은 파이프로도 실시간이라 이득이 없고 위험만 늘어남)보다 모든 Mac·모든 ProRes가 같은 디코더와
  QuickTime과 같은 색을 쓰는 쪽을 택함. Intel Mac 4K 4444 실측(2026-11-04): 네이티브 24.7fps·파일 열기 0.08초 대 파이프 22.3fps·0.6초.
"""

import os
import platform
import sys

from yesoncheck.movie_pipe_source import ineligible_reason

NATIVE_MODE_ENV = "YESONCHECK_MAC_NATIVE"
NATIVE_MODES = ("auto", "on", "off")  # 환경 변수가 받는 값 (없거나 비어 있으면 "auto")

PREF_KEY = "playback_decoder"  # prefs.json의 키
DECODERS = ("videotoolbox", "ffmpeg")  # 그 키가 받는 값 (videotoolbox = 네이티브, ffmpeg = 예전 방식)
DEFAULT_DECODER = "videotoolbox"
SOURCE_DEFAULT = "기본값"  # effective_decoder의 출처 — 설정을 읽지 않았거나 파일에 키가 없음
SOURCE_PREFS = "prefs.json"  # 출처 — 설정 파일에서 읽은 값
SOURCE_FALLBACK = "prefs.json 읽기 실패 — 이 세션만 ffmpeg"  # 출처 — 깨진 파일·나쁜 값 때문에 app.launch가 이 세션만 ffmpeg로 정함 (파일은 그대로)

NATIVE_CODEC = "prores"  # ⑦
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")  # ⑨ PQ·HLG
HDR_PRIMARIES = "bt2020"  # ⑨ HDR이 아닌 BT.2020 SDR도 원색이 다르므로 같이 거름


def native_mode(env=os.environ):
    """YESONCHECK_MAC_NATIVE: 없거나 비면 "auto", "auto"·"on"·"off"(대소문자 무시)는 소문자로, 그 밖은 ValueError."""
    given = env.get(NATIVE_MODE_ENV, "")
    mode = given.lower() or "auto"
    if mode not in NATIVE_MODES:
        raise ValueError(f"{NATIVE_MODE_ENV}는 {', '.join(NATIVE_MODES)} 중 하나여야 합니다 (비우면 auto): {given!r}")
    return mode


def is_apple_silicon(platform_mod=platform, sys_mod=sys):
    """Apple Silicon Mac인가: macOS이고 이 프로세스가 arm64로 보고함 (Rosetta 아래의 x86_64 빌드·Windows ARM·Linux ARM은 아님).
    네이티브 토글(native_wanted)은 더 이 판정을 쓰지 않는다 — 빌드 검사(check_frozen_imports)가 Apple Silicon 러너에서만 도는 디코드
    확인을 가를 때 쓴다."""
    return sys_mod.platform == "darwin" and platform_mod.machine() == "arm64"


_preferred = (DEFAULT_DECODER, SOURCE_DEFAULT)  # 프로세스 캐시: (디코더, 출처) — set_preferred_decoder가 바꿈


def set_preferred_decoder(name, source=SOURCE_DEFAULT) -> None:
    """프로세스 캐시의 선호 디코더를 name으로 (app.launch가 prefs.json에서 읽은 값을 source="prefs.json"으로, Setting 메뉴가 고른 값을). source는
    effective_decoder가 돌려주는 출처 글. DECODERS 밖의 name은 ValueError(설정 키와 받은 값을 글에) — 조용히 기본으로 넘기지 않으며 캐시는 그대로."""
    global _preferred
    if name not in DECODERS:
        raise ValueError(f"{PREF_KEY}는 {', '.join(DECODERS)} 중 하나여야 합니다: {name!r}")
    _preferred = (name, source)


def preferred_decoder() -> str:
    """프로세스 캐시의 선호 디코더 (환경 변수는 보지 않음 — 지금 유효한 것은 effective_decoder). 읽기 전의 기본은 videotoolbox."""
    return _preferred[0]


def effective_decoder(env=os.environ):
    """(지금 유효한 디코더, 출처) — 환경 변수 on은 ("videotoolbox", "환경 변수 YESONCHECK_MAC_NATIVE=on"), off는 ("ffmpeg", "환경 변수
    YESONCHECK_MAC_NATIVE=off"), auto(없음·빈 값 포함)는 캐시의 (디코더, 출처: "prefs.json"·"기본값"·SOURCE_FALLBACK). 나쁜 환경 변수 값은
    native_mode의 ValueError. 플랫폼은 보지 않는다 — Mac 전용 호출처(시작 기록·Setting 메뉴)가 쓰며, 실제로 네이티브를 고르는 길은 native_wanted."""
    mode = native_mode(env)
    if mode == "on":
        return "videotoolbox", f"환경 변수 {NATIVE_MODE_ENV}=on"
    if mode == "off":
        return "ffmpeg", f"환경 변수 {NATIVE_MODE_ENV}=off"
    return _preferred


def native_wanted(env=os.environ, platform_mod=platform, sys_mod=sys):
    """토글·플랫폼·설정이 네이티브 경로를 후보로 삼는가 (파일 게이트는 따로). off는 아니오, on은 예(macOS가 아니면 ValueError),
    auto는 macOS(darwin)이고 선호 디코더(캐시)가 videotoolbox면 예 — 칩은 보지 않는다. platform_mod는 호출처·시험의 시그니처를 지키려고 받기만 한다."""
    mode = native_mode(env)
    if mode == "off":
        return False
    if mode == "on":
        if sys_mod.platform != "darwin":
            raise ValueError(f"{NATIVE_MODE_ENV}=on은 macOS에서만 쓸 수 있습니다 (이 시스템: {sys_mod.platform}) — 끄거나 auto로 두세요")
        return True
    return sys_mod.platform == "darwin" and preferred_decoder() == "videotoolbox"


def _hdr_reason(probe):
    """⑨ HDR 조건의 어긋남 글, 없으면 None. 전달 함수를 먼저 봄 — 진짜 HDR 파일은 원색도 bt2020이라 순서가 반대면 사유가 "원색"으로만
    나와 PQ·HLG라는 이유가 가려진다."""
    if probe.color_transfer in HDR_TRANSFERS:
        return f"⑨ HDR({probe.color_transfer})"
    if probe.color_primaries == HDR_PRIMARIES:
        return f"⑨ HDR(원색 {probe.color_primaries})"
    return None


def native_ineligible_reason(probe):
    """네이티브 재생을 쓰면 안 되는 이유 한 줄 (모듈 설명의 ①~⑥·⑦·⑨ 중 처음 어긋난 조건, 앞에 조건 번호와 받은 값) — 모두 통과하면 None."""
    reason = ineligible_reason(probe)  # ①~⑥ 파이프 게이트 그대로
    if reason is not None:
        return reason
    if probe.codec != NATIVE_CODEC:  # ⑦
        return f"⑦ 코덱이 {NATIVE_CODEC}가 아님({probe.codec})"
    return _hdr_reason(probe)  # ⑨


def native_eligible(probe):
    """네이티브 재생을 써도 되는 파일인가 (native_ineligible_reason이 None)."""
    return native_ineligible_reason(probe) is None
