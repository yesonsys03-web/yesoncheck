"""Mac: 동영상(.mov·.mp4)을 YesonCheck로 열기 — 기본 앱 정하기, 처음 켤 때 한 번 묻기, Help 메뉴 (설계 3-3·6장).

- "다음으로 열기"에 늘 보이는 것은 Info.plist의 CFBundleDocumentTypes(YesonCheck_Autocut.spec — 종류 VIDEO_UTIS, 역할
  Viewer, LSHandlerRank Alternate: 설치만으로 기본 앱을 빼앗지 않음). 이 모듈은 더블클릭으로 여는 기본 앱을 정한다.
- 처음 켤 때 한 번(app.launch → ask_at_start — 빌드한 Mac 앱만, 창을 보이고 지난 업데이트의 결과 판정(handle_update_startup)
  이 끝난 뒤. 도우미가 켠 앱(--update-result)은 묻지 않고 다음에 보통으로 켤 때 — asks_on_start): prefs.json에 답이 없고 두
  종류 중 하나라도 기본 앱이 YesonCheck가 아니면(should_ask) ASK_TEXT [예]/[아니요].
  - [예]·[아니요] 단추를 누른 것만 기록한다(prefs.json의 "asked_default_video_app": true — 다시 묻지 않음, Help 메뉴로는
    언제든). 다른 창의 업데이트가 이 창에 닫기를 요청해 열린 대화 상자가 reject()로 닫히거나(player_base.close_for_update) 앱
    끝내기·로그아웃으로 창이 닫히는 것처럼 단추 없이 닫히면 기록하지 않는다(다음에 켤 때 다시 물음 — _ask). 취소 키(Esc, Mac은
    ⌘.도)도 [아니요]를 누르지 않고 닫으므로 기록하지 않음 (_AskBox — Qt 기본은 [아니요]를 누름).
  - 이미 기본 앱이면 묻지도 기록하지도 않는다(답한 것이 아님).
  - [예] → set_default → 같은 앱 ID의 다른 사본(other_copies)이 있으면 그 경로들과 지우라는 안내(지우지는 않음).
- Help → MENU_TEXT(Mac만 — Windows 항목은 file_associations): 묻지 않고 같은 일 + 정했다는 창. 소스 실행은 안내만.
- dmg 안(/Volumes)·임시 격리 위치(AppTranslocation)에서 켠 앱은 정하지 않고 묻지도 않는다(location_problem): 그 상태에서는
  응용 프로그램 폴더의 진짜 사본이 '다른 사본'으로 보여 지우라고 안내하게 되고, 정해 봐야 dmg를 빼면 소용이 없다.
- 오류: 예상된 실패 — DefaultAppError(LaunchServices의 상태 코드, 정한 뒤 다시 읽은 값이 다름, 앱의 Info.plist), prefs.json의
  UserFileError — 는 무엇이 왜인지 오류 창(트레이스백 없이). 예상 못 한 예외는 기록(stderr)과 오류 창에 트레이스백. 오류 창은
  빌드 앱이면 앱의 예외 창(app.make_excepthook의 창 — 기록 파일 경로를 붙이고 한 번에 하나만), 그 창이 없으면(소스 실행)
  같은 제목의 QMessageBox.critical (error_window — file_associations와 함께 씀).

고른 API — LaunchServices C API를 ctypes로 (CoreServices·CoreFoundation, PyObjC 없음):
`LSCopyDefaultRoleHandlerForContentType`(읽기)·`LSSetDefaultRoleHandlerForContentType`(정하기, 역할 kLSRolesAll — Finder의
'정보 가져오기 → 모두 변경'과 같은 항목)·`LSRegisterURL`(정하기 전에 이 번들을 등록 — 이미 있으면 그대로)·
`LSCopyApplicationURLsForBundleIdentifier`(같은 앱 ID의 사본). macOS 10.4/10.10부터 있고 26.2 SDK에서도 "앞으로
deprecated"(API_TO_BE_DEPRECATED)일 뿐 그대로 있다 → 12.3~최신 모두. 동기 호출이라 블록(완료 처리기)이 필요 없다.
대안 NSWorkspace `setDefaultApplicationAtURL:toOpenContentType:completionHandler:`(12+)는 Objective-C 블록·UTType이 필요하고
결과가 비동기로 온다 — 헤더 설명: "Some types require user consent" → 그 경우 macOS가 확인 창을 띄운 뒤 완료 처리기를 부름.

확인한 것 (2026-10-21, macOS 26.2 x86_64 — 이 모듈의 set_default·other_copies를 시험용 앱 ID(com.yeson.T15Probe)의 빈 번들
두 개로, 원래 기본 앱을 저장 → 정함 → 확인 → 되돌림 → 확인):
- 확인 창 없음: 두 종류 모두 OSStatus 0, 0.03초 만에 끝나고 바로 다시 읽은 값이 정한 앱 ID(역할 All·Viewer·Editor 모두),
  기본 앱 URL(LSCopyDefaultApplicationURLForContentType)도 그 번들. 정한 뒤 1.5초 동안 새 창 없음(화면 창 목록 — 잠긴 화면이라
  눈으로는 못 봄. 확인 창이 필요한 종류라면 사용자가 답하기 전에는 바뀌지 않아야 하므로 바로 바뀐 것이 확인 창이 없었다는 근거).
- 다시 읽은 앱 ID는 Info.plist 그대로(com.yeson.T15Probe), 저장 파일(com.apple.launchservices.secure.plist)에는 소문자 — 그래서
  비교는 대소문자 무관(_same_app).
- 임시 폴더(/tmp)의 번들은 LaunchServices가 'in-temp-dir'로 표시해(lsregister -dump) 앱 ID로 찾지 않는다: 정하기는 OSStatus 0인데
  다시 읽으면 다른 앱(QuickTime)이었고 사본 목록도 비었다 — 다시 읽어 확인하므로 DefaultAppError로 드러남(조용한 성공 없음).
- other_copies: 같은 앱 ID의 두 번들 중 자기 아닌 것 하나 (앱 ID를 소문자로 줘도 같음). 등록을 지우면(lsregister -u) 빈 목록.
- 부작용: 되돌리기도 kLSRolesAll로 하므로, 원래 명시한 항목이 없던 종류(이 Mac의 public.mpeg-4)에는 그때의 기본 앱(QuickTime)이
  명시 항목으로 남는다 — 더블클릭 앱은 같고, 편집 역할만 LaunchServices가 고르던 앱에서 그 앱으로 (항목을 지우는 API는 없음).

몬터레이(12.3)에서 남은 것 (사람 확인 — Task 18): 같은 함수가 확인 창 없이 바로 정해지는지·다시 읽은 값이 맞는지, Finder 더블클릭이
YesonCheck를 여는지, "다음으로 열기"에 YesonCheck가 보이는지, 처음 켤 때 묻는 창. 최신 macOS에서도 실제 화면(잠기지 않은)으로 확인
창이 없는지 눈으로. arm64 ctypes는 Apple Silicon CI(진짜 API 읽기 시험)와 사람 확인.
"""

import ctypes
import os
import plistlib
import sys
import traceback
import xml.parsers.expat
from ctypes import POINTER, byref, c_bool, c_char_p, c_int32, c_long, c_uint32, c_void_p, create_string_buffer

from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QMessageBox

from yesoncheck import error_window, update_install, user_files
from yesoncheck.user_files import UserFileError

IS_MAC = sys.platform == "darwin"  # Help 메뉴 항목·처음 켤 때 묻기 (시험이 바꿔 끼움)
VIDEO_UTIS = ("com.apple.quicktime-movie", "public.mpeg-4")  # .mov · .mp4 (file_names.LISTED_VIDEO_EXTENSIONS)
ASKED_KEY = "asked_default_video_app"  # prefs.json: [예]·[아니요]로 답했으면 true
PREFS_FILE_NAME = "prefs.json"

TITLE = "동영상 기본 앱"
LOG_PREFIX = "[기본 앱]"  # 기록 줄의 머리 (_log·오류 창 — error_window)
ASK_TEXT = "동영상(.mov·.mp4)을 더블클릭하면 YesonCheck로 열까요?"
YES_BUTTON = "예"
NO_BUTTON = "아니요"
MENU_TEXT = "동영상 기본 앱으로 정하기…"
DONE_TEXT = "동영상(.mov·.mp4)을 더블클릭하면 YesonCheck로 열립니다."
OTHER_COPIES_TEXT = ("같은 앱 ID의 YesonCheck 사본이 이 Mac에 더 있습니다 — 동영상을 더블클릭하면 macOS가 그중 하나를 열 수 "
                     "있습니다. 쓰지 않는 사본은 지워 주세요 (YesonCheck는 지우지 않습니다):")
SET_FAILED_TEXT = "동영상(.mov·.mp4)의 기본 앱을 YesonCheck로 정하지 못했습니다."
COPIES_FAILED_TEXT = "기본 앱은 정했지만, 같은 앱의 다른 사본이 있는지 확인하지 못했습니다."
CHECK_FAILED_TEXT = "동영상 기본 앱을 확인하지 못했습니다."
PREFS_READ_FAILED_TEXT = "설정 파일을 읽지 못해 동영상 기본 앱을 묻지 않았습니다."
RECORD_FAILED_TEXT = "동영상 기본 앱 질문의 답을 기록하지 못했습니다 — 다음에 켤 때 다시 물을 수 있습니다."
START_FAILED_TEXT = "동영상 기본 앱을 확인하다 예상치 못한 오류가 났습니다."
MENU_FAILED_TEXT = "동영상 기본 앱을 정하다 예상치 못한 오류가 났습니다."
SOURCE_RUN_TEXT = "소스에서 실행 중 — 빌드한 앱에서만 동영상 기본 앱을 정할 수 있습니다"
TRANSLOCATED_TEXT = ("이 앱이 임시 격리 위치에서 실행되고 있어 동영상 기본 앱으로 정할 수 없습니다. "
                     "앱을 완전히 끄고 응용 프로그램 폴더(Applications)로 옮긴 뒤 거기서 다시 열어 주세요.")
VOLUMES_TEXT = ("이 앱이 디스크 이미지(dmg)나 다른 디스크(/Volumes)에서 실행되고 있어 동영상 기본 앱으로 정할 수 없습니다. "
                "앱을 응용 프로그램 폴더(Applications)로 끌어다 놓은 뒤 거기서 다시 열어 주세요.")
ALREADY_ANSWERED_LOG = "[기본 앱] 이미 답함 — 묻지 않음"  # 기록 줄 (ci/update_e2e.py가 다른 창의 기록에서 찾음)

_BOX_TITLE_PROPERTY = "ycTitle"  # player_update.BOX_TITLE_PROPERTY와 같음 (macOS는 QMessageBox의 제목을 버림)


class DefaultAppError(Exception):
    """예상된 실패 — LaunchServices가 오류 상태를 돌려줌, 정한 뒤 다시 읽은 값이 다름, 앱의 Info.plist를 읽지 못함.
    글에 무엇이 왜인지(상태 코드·다시 읽은 값·경로)."""


# ---- 설정 파일 (prefs.json) ----


def prefs_path() -> str:
    """(Mac) ~/Library/Application Support/YesonCheck/prefs.json — HOME을 부를 때마다 읽음 (시험·업데이트 끝까지 시험은 HOME을
    바꿈)."""
    return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "YesonCheck", PREFS_FILE_NAME)


def _as_prefs(value, path):
    if not isinstance(value, dict):
        raise UserFileError(f"설정 파일이 JSON 객체가 아닙니다: {path} ({type(value).__name__})")
    return value


def read_prefs() -> dict:
    """prefs.json의 값 (없으면 {}). 깨졌거나 객체가 아니면 UserFileError — 빈 값으로 치지 않음."""
    path = prefs_path()
    return _as_prefs(user_files.read_json(path, {}), path)


def record_asked() -> None:
    """prefs.json에 "asked_default_video_app": true (잠금 안에서 다시 읽고 고침 — 다른 키는 그대로). 깨진 파일은 덮지 않고
    UserFileError, 잠금 시간 초과는 TimeoutError, 쓰기 실패는 OSError."""
    path = prefs_path()

    def mutate(prefs):
        prefs = _as_prefs(prefs, path)
        prefs[ASKED_KEY] = True
        return prefs

    user_files.update_json(path, mutate, {})


def should_ask(prefs: dict, handlers: dict, bundle_id: str) -> bool:
    """(순수) 처음 켤 때 물을지: 이미 [예]·[아니요]로 답했으면(prefs) 아니요, 두 종류(VIDEO_UTIS) 모두 기본 앱이 bundle_id면
    아니요, 그 밖에는 예. handlers: UTI → 기본 앱 ID(없으면 None). 앱 ID는 대소문자 무관 (LaunchServices가 소문자로 돌려주기도 함)."""
    if prefs.get(ASKED_KEY) is True:
        return False
    return not all(_same_app(handlers[uti], bundle_id) for uti in VIDEO_UTIS)


def _same_app(handler, bundle_id) -> bool:
    return handler is not None and handler.lower() == bundle_id.lower()


# ---- 기본 앱 (LaunchServices) ----


def bundle_id_of(app_path: str) -> str:
    """app_path(.app)의 앱 ID (Contents/Info.plist의 CFBundleIdentifier). 읽지 못하면 DefaultAppError."""
    plist_path = os.path.join(app_path, "Contents", "Info.plist")
    try:
        with open(plist_path, "rb") as fh:
            info = plistlib.load(fh)
    except (OSError, ValueError, xml.parsers.expat.ExpatError) as exc:
        raise DefaultAppError(f"앱의 Info.plist를 읽지 못했습니다: {plist_path}\n{type(exc).__name__}: {exc}") from exc
    bundle_id = info.get("CFBundleIdentifier") if isinstance(info, dict) else None
    if not isinstance(bundle_id, str) or not bundle_id:
        raise DefaultAppError(f"앱의 Info.plist에 앱 ID(CFBundleIdentifier)가 없습니다: {plist_path}")
    return bundle_id


def current_handler(uti: str) -> str | None:
    """uti의 기본 앱 ID (LaunchServices가 돌려준 그대로 — 소문자일 수 있음), 없으면 None."""
    return _launch_services().default_handler(uti)


def set_default(app_path: str) -> None:
    """app_path(.app)를 두 종류(VIDEO_UTIS) 모두의 기본 앱으로: 이 번들을 LaunchServices에 등록(이미 있으면 그대로) → 종류마다
    정함 → 둘 다 다시 읽어 그 앱 ID인지 확인. 한 종류가 실패해도 다른 종류는 정하고, 실패(상태 코드·다시 읽은 값)를 모두 담아
    DefaultAppError. LaunchServices는 앱 ID로 기억하므로 같은 앱 ID의 다른 사본이 열릴 수 있다 — other_copies."""
    bundle_id = bundle_id_of(app_path)
    services = _launch_services()
    status = services.register(app_path)
    if status != 0:
        raise DefaultAppError(f"LaunchServices에 이 앱을 등록하지 못했습니다 (LSRegisterURL, OSStatus {status}): {app_path}")
    statuses = {uti: services.set_default_handler(uti, bundle_id) for uti in VIDEO_UTIS}
    problems = []
    for uti in VIDEO_UTIS:
        handler = services.default_handler(uti)
        if statuses[uti] != 0 or not _same_app(handler, bundle_id):
            problems.append(f"- {uti}: LSSetDefaultRoleHandlerForContentType OSStatus {statuses[uti]}, "
                            f"다시 읽은 기본 앱 {handler!r}")
    if problems:
        raise DefaultAppError(f"앱 ID {bundle_id} ({app_path}):\n" + "\n".join(problems))


def other_copies(bundle_id: str, own_path: str) -> list[str]:
    """LaunchServices에 등록된, 앱 ID가 bundle_id인 사본 중 own_path(이 앱 — 같은 파일인지로 비교)가 아닌 것의 경로 (받은 차례,
    겹치지 않게). 등록만 남고 지금은 없는 경로(지운 앱·뺀 dmg)는 빼고 기록에 남김. 목록을 읽지 못하면 DefaultAppError."""
    copies, seen = [], set()
    for path in _launch_services().application_paths(bundle_id):
        if not os.path.isdir(path):
            print(f"[기본 앱] LaunchServices에 등록만 남은 사본(지금은 없음)은 뺌: {path}", flush=True)
            continue
        if os.path.samefile(path, own_path):
            continue
        key = os.path.realpath(path)
        if key not in seen:
            seen.add(key)
            copies.append(path)
    return copies


def location_problem(app_path: str) -> str | None:
    """이 자리의 앱은 기본 앱으로 정하지 않음 → 사용자에게 보일 안내 (AppTranslocation·/Volumes), 아니면 None."""
    if "/AppTranslocation/" in app_path:
        return TRANSLOCATED_TEXT
    if app_path.startswith("/Volumes/"):
        return VOLUMES_TEXT
    return None


_CORE_FOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_CORE_SERVICES = "/System/Library/Frameworks/CoreServices.framework/CoreServices"
_UTF8 = 0x08000100  # kCFStringEncodingUTF8
_ROLES_ALL = 0xFFFFFFFF  # kLSRolesAll
_APPLICATION_NOT_FOUND = -10814  # kLSApplicationNotFoundErr — 그 앱 ID로 등록된 앱이 없음 (오류 아님)
_PATH_BUFFER = 4096


class _LaunchServices:
    """LaunchServices·CoreFoundation 함수 (Mac에서 처음 쓸 때 한 번 불러옴). 모두 고정 인자의 C 함수라 인자·반환 형을 정해
    부르면 x86_64·arm64가 같음 (objc_msgSend의 가변 인자 문제 없음). Copy·Create로 받은 것은 모두 CFRelease."""

    def __init__(self):
        cf = self.cf = ctypes.CDLL(_CORE_FOUNDATION)
        cs = self.cs = ctypes.CDLL(_CORE_SERVICES)
        _declare(cf.CFRelease, None, [c_void_p])
        _declare(cf.CFStringCreateWithCString, c_void_p, [c_void_p, c_char_p, c_uint32])
        _declare(cf.CFStringGetLength, c_long, [c_void_p])
        _declare(cf.CFStringGetMaximumSizeForEncoding, c_long, [c_long, c_uint32])
        _declare(cf.CFStringGetCString, c_bool, [c_void_p, c_char_p, c_long, c_uint32])
        _declare(cf.CFURLCreateFromFileSystemRepresentation, c_void_p, [c_void_p, c_char_p, c_long, c_bool])
        _declare(cf.CFURLGetFileSystemRepresentation, c_bool, [c_void_p, c_bool, c_char_p, c_long])
        _declare(cf.CFArrayGetCount, c_long, [c_void_p])
        _declare(cf.CFArrayGetValueAtIndex, c_void_p, [c_void_p, c_long])
        _declare(cf.CFErrorGetCode, c_long, [c_void_p])
        _declare(cs.LSCopyDefaultRoleHandlerForContentType, c_void_p, [c_void_p, c_uint32])
        _declare(cs.LSSetDefaultRoleHandlerForContentType, c_int32, [c_void_p, c_uint32, c_void_p])
        _declare(cs.LSRegisterURL, c_int32, [c_void_p, c_bool])
        _declare(cs.LSCopyApplicationURLsForBundleIdentifier, c_void_p, [c_void_p, POINTER(c_void_p)])

    def default_handler(self, uti: str) -> str | None:
        with self._string(uti) as uti_ref:
            handler = self.cs.LSCopyDefaultRoleHandlerForContentType(uti_ref, _ROLES_ALL)
        if not handler:
            return None
        try:
            return self._text(handler)
        finally:
            self.cf.CFRelease(handler)

    def set_default_handler(self, uti: str, bundle_id: str) -> int:
        """OSStatus (0이면 됨)."""
        with self._string(uti) as uti_ref, self._string(bundle_id) as bundle_ref:
            return self.cs.LSSetDefaultRoleHandlerForContentType(uti_ref, _ROLES_ALL, bundle_ref)

    def register(self, app_path: str) -> int:
        """LSRegisterURL(번들, inUpdate=false) — 이미 등록됐고 바뀌지 않았으면 그대로. OSStatus (0이면 됨)."""
        raw = os.fsencode(app_path)
        url = self.cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), True)
        if not url:
            raise RuntimeError(f"CFURLCreateFromFileSystemRepresentation이 NULL입니다: {app_path!r}")
        try:
            return self.cs.LSRegisterURL(url, False)
        finally:
            self.cf.CFRelease(url)

    def application_paths(self, bundle_id: str) -> list[str]:
        error = c_void_p()
        with self._string(bundle_id) as bundle_ref:
            array = self.cs.LSCopyApplicationURLsForBundleIdentifier(bundle_ref, byref(error))
        code = None
        if error.value:
            code = self.cf.CFErrorGetCode(error.value)
            self.cf.CFRelease(error.value)
        if not array:
            if code == _APPLICATION_NOT_FOUND:
                return []
            raise DefaultAppError(f"앱 ID {bundle_id}의 사본 목록을 읽지 못했습니다 "
                                  f"(LSCopyApplicationURLsForBundleIdentifier, 오류 {code})")
        try:
            return [self._path(self.cf.CFArrayGetValueAtIndex(array, i)) for i in range(self.cf.CFArrayGetCount(array))]
        finally:
            self.cf.CFRelease(array)

    def _string(self, text: str):
        ref = self.cf.CFStringCreateWithCString(None, text.encode("utf-8"), _UTF8)
        if not ref:
            raise RuntimeError(f"CFStringCreateWithCString이 NULL입니다: {text!r}")
        return _Released(self.cf, ref)

    def _text(self, ref) -> str:
        size = self.cf.CFStringGetMaximumSizeForEncoding(self.cf.CFStringGetLength(ref), _UTF8) + 1
        buffer = create_string_buffer(size)
        if not self.cf.CFStringGetCString(ref, buffer, size, _UTF8):
            raise RuntimeError("CFStringGetCString이 실패했습니다 (UTF-8)")
        return buffer.value.decode("utf-8")

    def _path(self, url) -> str:
        buffer = create_string_buffer(_PATH_BUFFER)
        if not self.cf.CFURLGetFileSystemRepresentation(url, True, buffer, _PATH_BUFFER):
            raise RuntimeError("CFURLGetFileSystemRepresentation이 실패했습니다")
        return os.fsdecode(buffer.value)


class _Released:
    """with 블록이 끝나면 CFRelease (받은 CF 객체)."""

    def __init__(self, cf, ref):
        self.cf = cf
        self.ref = ref

    def __enter__(self):
        return self.ref

    def __exit__(self, exc_type, exc, tb):
        self.cf.CFRelease(self.ref)


def _declare(function, restype, argtypes):
    function.restype = restype
    function.argtypes = argtypes


_services = None  # _LaunchServices (처음 쓸 때)


def _launch_services() -> _LaunchServices:
    """LaunchServices (시험은 이 함수를 대역으로 바꿔 끼움)."""
    global _services
    if _services is None:
        _services = _LaunchServices()
    return _services


# ---- 창 (처음 켤 때 묻기 · Help 메뉴) ----


def asks_on_start(update_token: str | None) -> bool:
    """app.launch: 이번에 켤 때 묻기(ask_at_start)를 할지 — 빌드한 Mac 앱이고 도우미가 켠 앱(--update-result)이 아닐 때."""
    if not (IS_MAC and getattr(sys, "frozen", False)):
        return False
    if update_token is not None:
        _log("업데이트 뒤 도우미가 켠 앱 — 이번에는 묻지 않음 (다음에 보통으로 켤 때)")
        return False
    return True


def ask_at_start(parent) -> None:
    """처음 켤 때 한 번 (모듈 설명): 물을 때면 ASK_TEXT [예]/[아니요] → 답을 기록 → [예]면 기본 앱으로 정하고 다른 사본을 알림.
    오류는 모두 창으로 (밖으로 내보내지 않음 — Qt 루프에서 부름)."""
    try:
        _ask_at_start(parent)
    except DefaultAppError as exc:
        error_window.show_error(LOG_PREFIX, f"{CHECK_FAILED_TEXT}\n\n{exc}")
    except Exception:
        error_window.show_unexpected(LOG_PREFIX, START_FAILED_TEXT)


def _ask_at_start(parent):
    try:
        prefs = read_prefs()
    except UserFileError as exc:
        error_window.show_error(LOG_PREFIX, f"{PREFS_READ_FAILED_TEXT}\n\n{exc}")
        return
    if prefs.get(ASKED_KEY) is True:  # should_ask와 같은 판단 — 답한 뒤에는 앱 자리·LaunchServices도 보지 않게 먼저
        print(f"{ALREADY_ANSWERED_LOG} ({prefs_path()})", flush=True)
        return
    app_path = update_install.running_app_location()
    problem = location_problem(app_path)
    if problem is not None:
        _log(f"이 자리의 앱은 기본 앱으로 정하지 않음 — 묻지 않음, 기록하지 않음 ({app_path})")
        return
    bundle_id = bundle_id_of(app_path)
    handlers = {uti: current_handler(uti) for uti in VIDEO_UTIS}
    if not should_ask(prefs, handlers, bundle_id):
        _log(f"이미 기본 앱이 {bundle_id} — 묻지 않음 {handlers}")
        return
    _log(f"지금 기본 앱 {handlers} — 물음")
    answer = _ask(parent)
    if answer is None:
        _log("묻는 창이 [예]·[아니요] 없이 닫힘 — 기록하지 않음 (다음에 켤 때 다시 물음)")
        return
    _log(f"답: [{YES_BUTTON if answer else NO_BUTTON}] → 기록 ({prefs_path()})")
    try:
        record_asked()
    except (UserFileError, TimeoutError, OSError) as exc:
        traceback.print_exc()
        error_window.show_error(LOG_PREFIX, f"{RECORD_FAILED_TEXT}\n\n{type(exc).__name__}: {exc}")
    if answer:
        _apply(parent, app_path, bundle_id, announce=False)


def set_default_from_menu(parent) -> None:
    """Help → MENU_TEXT: 묻지 않고 이 앱을 기본 앱으로 → 정했다는 창(다른 사본이 있으면 그 안내도). 소스 실행·dmg 안·격리
    위치면 안내만. 오류는 모두 창으로."""
    try:
        if not getattr(sys, "frozen", False):
            QMessageBox.information(parent, TITLE, SOURCE_RUN_TEXT)
            return
        app_path = update_install.running_app_location()
        problem = location_problem(app_path)
        if problem is not None:
            _log(f"이 자리의 앱은 기본 앱으로 정하지 않음 ({app_path})")
            QMessageBox.warning(parent, TITLE, problem)
            return
        _apply(parent, app_path, bundle_id_of(app_path), announce=True)
    except DefaultAppError as exc:
        error_window.show_error(LOG_PREFIX, f"{SET_FAILED_TEXT}\n\n{exc}")
    except Exception:
        error_window.show_unexpected(LOG_PREFIX, MENU_FAILED_TEXT)


def _apply(parent, app_path, bundle_id, announce):
    """set_default → 다른 사본 안내. announce면(Help) 정했다는 말도. 예상된 실패는 오류 창 (예상 못 한 것은 부른 쪽으로)."""
    try:
        set_default(app_path)
    except DefaultAppError as exc:
        error_window.show_error(LOG_PREFIX, f"{SET_FAILED_TEXT}\n\n{exc}")
        return
    _log(f"기본 앱을 정함: {', '.join(VIDEO_UTIS)} → {bundle_id} ({app_path})")
    try:
        copies = other_copies(bundle_id, app_path)
    except DefaultAppError as exc:
        error_window.show_error(LOG_PREFIX, f"{COPIES_FAILED_TEXT}\n\n{exc}")
        return
    if copies:
        _log(f"같은 앱 ID의 다른 사본 {len(copies)}개 — 지우라고 안내: {copies!r}")
        lines = [DONE_TEXT, ""] if announce else []
        lines += [OTHER_COPIES_TEXT, *[f"- {path}" for path in copies], "", f"이 앱: {app_path}"]
        QMessageBox.information(parent, TITLE, "\n".join(lines))
    elif announce:
        QMessageBox.information(parent, TITLE, DONE_TEXT)


class _AskBox(QMessageBox):
    """묻는 창: 취소 키(QKeySequence.Cancel — Esc, Mac은 ⌘.)는 [아니요]를 누르지 않고 reject()로 닫음 (Qt 기본은 탈출 단추
    [아니요]를 누름 → 답으로 기록될 것). [아니요]는 탈출 단추로 남겨 둠 — 창 닫기(QCloseEvent: 앱 끝내기·로그아웃)가 막히지
    않게 (탈출 단추가 없으면 QMessageBox는 닫기를 무시함)."""

    def keyPressEvent(self, event):  # noqa: N802 (Qt 가상 함수 이름)
        if event.matches(QKeySequence.Cancel):
            self.reject()
            return
        super().keyPressEvent(event)


def _ask(parent) -> bool | None:
    """ASK_TEXT [예]/[아니요] (기본 [예]) → 누른 단추로 True·False. 단추를 누르지 않고 닫히면 None: 다른 창의 닫기 요청(reject),
    취소 키(Esc·⌘. — _AskBox), 앱 끝내기·로그아웃의 창 닫기(QCloseEvent — Qt는 exec_()의 결과를 [아니요]로 두지만 사용자가
    답한 것이 아님)."""
    box = _AskBox(QMessageBox.Question, TITLE, ASK_TEXT, QMessageBox.Yes | QMessageBox.No, parent)
    box.setProperty(_BOX_TITLE_PROPERTY, TITLE)
    box.button(QMessageBox.Yes).setText(YES_BUTTON)
    box.button(QMessageBox.No).setText(NO_BUTTON)
    box.setDefaultButton(QMessageBox.Yes)
    pressed = []
    # 연결한 함수가 box를 붙잡지 않게 (box ↔ 함수 순환이면 창이 나중의 아무 때나 — 다른 이벤트 처리 중에 — 순환 GC로 지워짐)
    box.buttonClicked.connect(pressed.append)
    try:
        box.exec_()
        if not pressed:
            return None
        return box.standardButton(pressed[-1]) == QMessageBox.Yes
    finally:
        box.deleteLater()  # 부모(창)가 있으면 그 창이 끝날 때까지 남지 않게 — 지금 이벤트 루프에서 지움


def _log(line):
    print(f"{LOG_PREFIX} {line}", flush=True)
