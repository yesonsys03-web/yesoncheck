"""앱 다시 열기(Mac 'reopen')와 파일 열기 받기 — 새 창(앱 프로세스)으로 보냄 (설계 3-1·3-2).

`install(app, on_reopen, on_open_files, argv_files)`를 QApplication을 만든 바로 다음에 부르고, 창을 보인 뒤
`FileOpenRouter.ready(open_here)`를 부른다(app.launch).

- 받은 파일: 시작 인자(argv) + ready 전에 온 파일 열기 이벤트(`QFileOpenEvent`, Mac)를 받은 차례대로 모았다가 ready 때 첫
  파일은 `open_here`(이 창의 A), 나머지는 `on_open_files`(→ new_window.spawn, 파일마다 새 앱). ready 뒤의 파일 열기는
  이벤트마다 `on_open_files([파일])` — 이 창이나 다른 창에 열린 영상이어도 새 창("무조건 새 창").
- 시작 인자와 같은 파일의 이벤트: 시작 중(ready 전)에만, 시작 인자 하나가 이벤트 하나만 흡수(한 번만 엶). 비교 키는
  `unicodedata.normalize("NFC", os.path.realpath(p))`. 실험에서는 이런 중복이 한 번도 없었다(아래) — 안전망.
- Mac: ready 안에서 'aevt'/'rapp'(kAEReopenApplication — Dock 아이콘 클릭, 켜져 있을 때 Finder·Launchpad·Spotlight로 앱을
  다시 실행) 처리기를 등록 → `on_reopen()`(→ new_window.spawn([]), 빈 새 창). 모든 창(프로세스)이 등록한다.
- Mac이 아니면 파일만 나눈다(이벤트 필터도 Apple Event도 없음 — Objective-C 런타임을 불러오지 않음). Windows에서 여러
  파일을 한 명령으로 받은 경우도 첫 파일은 이 창, 나머지는 새 창.
- 콜백(open_here·on_open_files·on_reopen)은 Qt 루프에서 부른다(QTimer.singleShot(0) — 모달 대화 상자가 떠 있어도 그 안에서
  돎). 실패하면 바로 기록(stderr — 빌드 앱은 기록 파일)에 트레이스백(new_window의 RuntimeError면 명령·출력)을 남기고, 오류 창은
  Qt 루프에서 error_window로(빌드 앱은 앱의 예외 창 — 기록 파일 경로가 붙고 한 번에 하나만, 트레이스백은 끝 부분만이고 무엇이
  실패했는지는 그대로) — 이 창은 그대로. PyQt5는 eventFilter 같은 가상 함수·Qt 루프의 일에서 빠져나간 예외로 프로세스를
  끝내고(qFatal — 소스 실행), ctypes는 IMP에서 빠져나간 예외를 한 줄 남기고 버리므로, 모두 안에서 잡아 같은 방법으로 보인다.
  알리다 또 실패하면(기록 파일 쓰기·오류 창) 원래 stderr(sys.__stderr__)에 남긴다(_report_error·_last_resort).

Step 1 실험 (2026-10-21, macOS 26.2 x86_64, PyQt5 5.15.11 / Qt 5.15.14, PyInstaller 6.14.1 onedir `argv_emulation`, 진짜 앱
spec 모양의 실험 앱 — 빌드 앱과 소스 실행):

- 고른 방법 (가): ctypes로 만든 Objective-C 처리기를 `[[NSAppleEventManager sharedAppleEventManager]
  setEventHandler:andSelector:forEventClass:'aevt' andEventID:'rapp']`로 등록 (NSAppleEventManager·objc 런타임은 12.3에
  있음, PyObjC 없음). 관찰: Dock 아이콘(접근성 '누르기')·`open -a <번들>`(Finder 더블클릭·Launchpad·Spotlight와 같은
  LaunchServices 경로) → 콜백 정확히 1번, AppleScript `activate` → 0번, 첫 실행 → 0번, 모달 대화 상자가 떠 있어도 1번
  (모달의 중첩 루프 안에서 불리고 모달은 그대로), 최소화한 창은 최소화된 채(AppKit 기본 처리기의 창 올리기가 없어짐),
  `QFileOpenEvent`·종료 Apple Event는 그대로 옴.
- 버린 방법 (나) Qt `ApplicationStateChange`의 강제 Active(이미 Active인데 또 옴): 모달이 떠 있으면 강제 Active가 오지 않음
  (0번), AppKit 기본 처리기가 남아 최소화한 창이 올라옴(설계 0장 위반), 앱이 Inactive일 때 온 reopen은 `Inactive→Active`로
  평범한 활성화와 구별할 수 없음.
- 등록 시점: AppKit은 `-[NSApplication finishLaunching]`(Qt의 첫 이벤트 처리 — launch의 스플래시 `processEvents` 안)에서 자기
  'rapp' 처리기를 등록한다. 그 전에 등록하면 오류 없이 덮여 콜백이 0번이다(덮였는지 알려 주는 API도 없음). 그래서 창을 보인
  뒤 ready 안에서 동기로 등록한다 — 이 모양(스플래시 processEvents → 창 → 동기 등록)을 빌드 앱에서 확인함. 창을 만드는 동안
  온 rapp는 Apple Event 큐에서 기다린다(추론 — 확인 안 함): 보통은 그다음 이벤트 처리(splash.finish가 창이 보이기를 기다리는
  동안)에서 아직 남아 있는 AppKit 기본 처리기가 처리해 새 창이 뜨지 않고, ready가 이 처리기를 등록할 때까지 큐에 남아 있었다면
  등록 뒤 처리돼 새 창이 하나 더 뜬다 — 타이밍에 따라 다름.
- 여러 프로세스: Dock 타일이 프로세스마다 하나씩 생기고 타일은 자기 프로세스에만 rapp, `open -a`는 먼저 켜진 프로세스에
  rapp → 모든 프로세스가 등록해야 함. `open -n <번들> --args <파일>`(새 창 띄우기)은 새 프로세스의 argv로만 가고 옛
  프로세스에는 아무 이벤트도 없음.
- 시작 때 파일: PyInstaller 부트로더(`argv_emulation`)가 첫 'odoc'을 먹고 파일을 argv에 붙인다(NFD — 한글 자모 분해,
  링크 푼 경로 /tmp → /private/tmp). 같은 파일의 `QFileOpenEvent`는 한 번도 오지 않았다(빠른/느린 시작, 파일 1·2개, 각 2번
  이상). 시작 중 따로 연 다른 파일은 ~100 ms 안이면 argv에 합쳐지고, 그 뒤면 `QFileOpenEvent`로 온다 — 이벤트 루프 전
  (스플래시 processEvents 안)일 수도 있어, 필터를 스플래시 뒤에 달면 그 파일이 말없이 사라졌다(2/2) → install은
  QApplication 바로 다음. `QFileOpenEvent`는 qApp에 보내지고 켜진 뒤 여러 파일은 파일마다 하나씩 연달아 온다.
- 화면이 잠겨 있어 확인하지 못한 것(사람 확인 — 잠긴 동안 macOS는 어떤 앱도 앞으로 가져오지 않고, 가짜 키·클릭은 보내지
  않음): 실제 마우스로 Dock 클릭(YesonCheck가 앞일 때·뒤일 때), ⌘Tab, 다른 앱이 앞일 때 창 클릭, Mission Control → 새 창
  0개, Finder 더블클릭·Launchpad·Spotlight의 실제 동작(같은 경로인 `open -a`로 1번 확인), 다른 앱에서 돌아올 때 사이드바
  다시 읽기. Apple Event 전달(rapp·odoc)은 잠금과 관계없어 콜백 수·모달·최소화·파일 열기는 확인됨. arm64는 이 Mac에서 돌려
  보지 못함(시험 test_reopen_handler_dispatch_calls_callback이 Apple Silicon CI에서 같은 경로를 탐).
- 부작용: 처리기를 바꾸면 AppKit 기본 reopen 처리가 통째로 사라져, Qt의 `applicationShouldHandleReopen`이 불리지 않고 Dock
  클릭 때의 강제 `applicationStateChanged(ApplicationActive)`도 없어진다(사이드바 다시 읽기는 이 신호를 씀 —
  sidebar_refresh의 _on_application_state_changed). 다른 앱에서 돌아오는 평범한 `Inactive→Active`는 그대로라 다시 읽기는
  유지되고, 이미 앞인 창에서 Dock을 누르면 이제 새 창이 뜬다.
"""

import ctypes
import os
import sys
import traceback
import unicodedata
from ctypes import CFUNCTYPE, c_bool, c_char_p, c_size_t, c_uint32, c_void_p
from typing import Callable

from PyQt5.QtCore import QEvent, QObject, QTimer

from yesoncheck import error_window

LOG_PREFIX = "[앱 이벤트]"  # 기록 줄의 머리 (_report_error)
REOPEN_FAILED_TEXT = "Dock 클릭·앱 다시 열기로 새 YesonCheck 창을 띄우지 못했습니다."
REGISTER_FAILED_TEXT = "Dock 클릭·앱 다시 열기로 새 창을 띄우는 기능을 켜지 못했습니다 (이 창은 그대로 쓸 수 있습니다)."
FILE_OPEN_FAILED_TEXT = "파일 열기(Finder 더블클릭·다음으로 열기)를 처리하지 못했습니다."

# Apple Event 종류 (AEEventClass·AEEventID — 네 글자 UInt32)
K_CORE_EVENT_CLASS = int.from_bytes(b"aevt", "big")  # kCoreEventClass
K_AE_REOPEN_APPLICATION = int.from_bytes(b"rapp", "big")  # kAEReopenApplication

_LIBOBJC = "/usr/lib/libobjc.A.dylib"
_FOUNDATION = "/System/Library/Frameworks/Foundation.framework/Foundation"  # NSAppleEventManager
_HANDLER_CLASS_NAME = b"YesonCheckReopenHandler"
_REOPEN_SELECTOR = b"handleReopen:withReplyEvent:"
# IMP: -(void)handleReopen:(NSAppleEventDescriptor *)event withReplyEvent:(NSAppleEventDescriptor *)reply  ("v@:@@")
_REOPEN_IMP_TYPE = CFUNCTYPE(None, c_void_p, c_void_p, c_void_p, c_void_p)


def path_key(path: str) -> str:
    """같은 파일인지 비교하는 키: 링크를 푼 경로의 NFC (Finder·argv_emulation은 NFD, `open --args`로 넘긴 경로는 넘긴 그대로)."""
    return unicodedata.normalize("NFC", os.path.realpath(path))


class FileOpenRouter(QObject):
    """받은 파일을 이 창·새 창으로 나눔 (모듈 설명). install이 만들고, Mac이면 QApplication의 이벤트 필터."""

    def __init__(self, on_reopen: Callable[[], None], on_open_files: Callable[[list[str]], None],
                 argv_files: list[str], platform: str):
        super().__init__()
        self._on_reopen = on_reopen
        self._on_open_files = on_open_files
        self._platform = platform
        self._waiting = list(argv_files)  # ready 전: 받은 차례대로 (시작 인자 먼저)
        self._absorbable = [path_key(path) for path in argv_files]  # 시작 인자 하나가 같은 파일 이벤트 하나만 흡수
        self._is_ready = False

    def waiting_files(self) -> list[str]:
        """ready 전에 받아 아직 열지 않은 파일 (ready 뒤에는 빈 목록)."""
        return list(self._waiting)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt 가상 함수 이름)
        # QApplication의 필터라 이 프로세스(메인 스레드)의 모든 이벤트가 지나감 → 종류만 보고 바로 돌려보냄
        if event.type() != QEvent.FileOpen:
            return False
        try:
            self._file_opened(event.file(), event.url())
        except BaseException:  # 빠져나가면 PyQt5가 프로세스를 끝냄 (오류 창 없이)
            _report_error(FILE_OPEN_FAILED_TEXT)
        return True

    def _file_opened(self, path, url):
        if not path:
            raise RuntimeError(f"파일 경로가 없는 파일 열기 이벤트입니다 (url {url.toString()!r})")
        if self._is_ready:
            print(f"[파일 열기] 켜진 뒤 연 파일 → 새 창: {path}", flush=True)
            _later(f"영상을 새 창으로 열지 못했습니다: {path}", self._on_open_files, [path])
            return
        key = path_key(path)
        if key in self._absorbable:
            self._absorbable.remove(key)
            print(f"[파일 열기] 시작 인자와 같은 파일의 열기 이벤트 — 한 번만 엶: {path}", flush=True)
            return
        print(f"[파일 열기] 시작 중에 연 파일 — 창을 보인 뒤 엶: {path}", flush=True)
        self._waiting.append(path)

    def ready(self, open_here: Callable[[str], None]) -> None:
        """창을 보인 뒤 한 번: 모아 둔 첫 파일은 open_here, 나머지는 on_open_files (둘 다 Qt 루프에서). Mac이면 여기서
        reopen 처리기를 동기로 등록 — AppKit finishLaunching(스플래시의 processEvents) 뒤여야 덮이지 않음."""
        if self._is_ready:
            raise RuntimeError("FileOpenRouter.ready()는 한 번만 부를 수 있습니다")
        self._is_ready = True
        files, self._waiting, self._absorbable = self._waiting, [], []
        if self._platform == "darwin":
            try:
                register_reopen_handler(self._on_reopen)
            except Exception:
                _report_error(REGISTER_FAILED_TEXT)
        if not files:
            return
        first, rest = files[0], files[1:]
        _later(f"영상을 열지 못했습니다: {first}", open_here, first)
        if rest:
            print(f"[파일 열기] 받은 파일 {len(files)}개 — 첫 파일은 이 창, 나머지는 새 창: {rest!r}", flush=True)
            _later(f"영상을 새 창으로 열지 못했습니다: {rest}", self._on_open_files, rest)


def install(app, on_reopen: Callable[[], None], on_open_files: Callable[[list[str]], None], argv_files: list[str],
            platform: str = sys.platform) -> FileOpenRouter:
    """QApplication을 만든 바로 다음에 (스플래시의 processEvents·업데이트 확인보다 먼저 — 그사이 온 파일 열기를 놓치지 않게).

    Mac이면 파일 열기 이벤트 필터를 app에 걸고, 그 밖에는 시작 인자만 나누는 라우터. 돌려받은 라우터는 앱이 끝날 때까지
    붙잡아 둘 것(지워지면 필터도 빠짐)."""
    router = FileOpenRouter(on_reopen, on_open_files, argv_files, platform)
    if platform == "darwin":
        app.installEventFilter(router)
    return router


def _later(context: str, fn: Callable, *args) -> None:
    """fn(*args)를 Qt 루프에서 — 실패하면 context와 트레이스백을 기록·오류 창으로 (이 창은 그대로)."""
    QTimer.singleShot(0, lambda: _run_guarded(context, fn, *args))


def _run_guarded(context: str, fn: Callable, *args) -> None:
    try:
        fn(*args)
    except BaseException:  # Qt 루프에서 빠져나가면 PyQt5가 프로세스를 끝냄 (소스 실행 — 빌드 앱은 예외 창)
        _report_error(context)


def _report_error(context: str) -> None:
    """(except 블록 안에서) 지금 처리 중인 예외를 바로 트레이스백째 기록(stderr — 빌드 앱은 기록 파일)하고, 오류 창은 Qt 루프에서
    (Apple Event·이벤트 처리 안에서 모달 창을 열지 않게) error_window로 — 빌드 앱은 앱의 예외 창(기록 파일 경로, 한 번에 하나만),
    글은 context 그대로 + 트레이스백의 끝 부분.

    eventFilter·IMP·미룬 콜백의 except 블록에서 불리므로 예외를 내보내지 않는다: 알리다 또 실패하면 _last_resort."""
    try:
        details = traceback.format_exc()
        print(f"{LOG_PREFIX} {context}\n{details}", file=sys.stderr, flush=True)
        text = error_window.with_details(context, details)
        QTimer.singleShot(0, lambda: _show_error_window(text))
    except BaseException:
        _last_resort(context)


def _show_error_window(text: str) -> None:
    """(Qt 루프에서) 오류 창 — 실패해도 Qt 루프로 내보내지 않음 (_last_resort)."""
    try:
        error_window.show_window(text)
    except BaseException:
        _last_resort(text)


def _last_resort(message: str) -> None:
    """(except 블록 안에서) 오류를 알리다 또 실패함: 원래 stderr(sys.__stderr__ — setup_app_logging이 기록 파일로 바꾸기 전)에
    message와 지금 처리 중인 예외(알리던 예외가 앞에 이어진 트레이스백)를 씀. 원래 stderr가 없으면(Windows 창 앱) 그 예외를 그대로
    올림 — 조용히 삼키지 않음."""
    stream = sys.__stderr__
    if stream is None:
        raise
    stream.write(f"{LOG_PREFIX} 오류를 알리지 못했습니다 — {message}\n{traceback.format_exc()}\n")
    stream.flush()


# ---- Mac: 'aevt'/'rapp' 처리기 (ctypes — PyObjC 없음) ----


class _ObjCRuntime:
    """Objective-C 런타임 함수 (Mac에서 처음 쓸 때 한 번 불러옴 — 다른 플랫폼에서는 불러오지 않음).

    objc_msgSend는 가변 인자로 부르지 않는다(arm64에서 인자가 깨짐): 호출 모양마다 인자·반환 형을 정한 함수 포인터를
    그 주소로 만든다."""

    def __init__(self):
        self.lib = ctypes.CDLL(_LIBOBJC)
        ctypes.CDLL(_FOUNDATION)
        lib = self.lib
        lib.objc_getClass.restype = c_void_p
        lib.objc_getClass.argtypes = [c_char_p]
        lib.sel_registerName.restype = c_void_p
        lib.sel_registerName.argtypes = [c_char_p]
        lib.objc_allocateClassPair.restype = c_void_p
        lib.objc_allocateClassPair.argtypes = [c_void_p, c_char_p, c_size_t]
        lib.objc_registerClassPair.restype = None
        lib.objc_registerClassPair.argtypes = [c_void_p]
        lib.class_addMethod.restype = c_bool
        lib.class_addMethod.argtypes = [c_void_p, c_void_p, c_void_p, c_char_p]
        self.msg_send = ctypes.cast(lib.objc_msgSend, c_void_p).value
        # -(id)selector · +(id)selector
        self.send_id = CFUNCTYPE(c_void_p, c_void_p, c_void_p)(self.msg_send)
        # -(void)setEventHandler:(id)h andSelector:(SEL)s forEventClass:(AEEventClass)c andEventID:(AEEventID)i
        self.send_set_handler = CFUNCTYPE(None, c_void_p, c_void_p, c_void_p, c_void_p, c_uint32, c_uint32)(
            self.msg_send)

    def cls(self, name: bytes) -> int:
        found = self.lib.objc_getClass(name)
        if not found:
            raise RuntimeError(f"Objective-C 클래스 {name.decode()}를 찾지 못했습니다")
        return found

    def sel(self, name: bytes) -> int:
        return self.lib.sel_registerName(name)


class _ReopenHandler:
    """'rapp'를 받는 Objective-C 객체 (NSObject 하위 클래스 하나에 IMP 하나). 프로세스에 하나 — 클래스는 이름당 한 번만
    만들 수 있고, NSAppleEventManager는 처리기를 붙잡아 주지 않으므로 객체와 IMP(CFUNCTYPE)는 끝까지 둔다."""

    def __init__(self, runtime: _ObjCRuntime):
        self.runtime = runtime
        self.callback = None
        self.imp = _REOPEN_IMP_TYPE(self._imp)
        rt = runtime
        cls = rt.lib.objc_allocateClassPair(rt.cls(b"NSObject"), _HANDLER_CLASS_NAME, 0)
        if not cls:
            raise RuntimeError(f"objc_allocateClassPair 실패 ({_HANDLER_CLASS_NAME.decode()} 클래스가 이미 있음?)")
        if not rt.lib.class_addMethod(cls, rt.sel(_REOPEN_SELECTOR), ctypes.cast(self.imp, c_void_p), b"v@:@@"):
            raise RuntimeError(f"class_addMethod 실패 ({_REOPEN_SELECTOR.decode()})")
        rt.lib.objc_registerClassPair(cls)
        self.object = rt.send_id(rt.send_id(cls, rt.sel(b"alloc")), rt.sel(b"init"))  # 놓지 않음
        if not self.object:
            raise RuntimeError(f"[[{_HANDLER_CLASS_NAME.decode()} alloc] init]이 nil입니다")

    def register(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        rt = self.runtime
        manager = rt.send_id(rt.cls(b"NSAppleEventManager"), rt.sel(b"sharedAppleEventManager"))
        if not manager:
            raise RuntimeError("[NSAppleEventManager sharedAppleEventManager]가 nil입니다")
        rt.send_set_handler(manager, rt.sel(b"setEventHandler:andSelector:forEventClass:andEventID:"), self.object,
                            rt.sel(_REOPEN_SELECTOR), K_CORE_EVENT_CLASS, K_AE_REOPEN_APPLICATION)

    def _imp(self, self_ptr, cmd, event, reply):
        # 메인 스레드, AppKit의 Apple Event 처리 안(모달 대화 상자의 중첩 루프 안일 수도) → 일은 Qt 루프로 미루고 바로 돌아옴
        try:
            callback = self.callback
            print("[앱 다시 열기] Dock 클릭·앱 다시 열기(reopen) → 새 창", flush=True)
            _later(REOPEN_FAILED_TEXT, callback)
        except BaseException:  # ctypes 콜백에서 빠져나가면 한 줄만 남고 사라짐
            _report_error(REOPEN_FAILED_TEXT)


_objc = None  # _ObjCRuntime (Mac에서 처음 쓸 때)
_reopen_handler = None  # _ReopenHandler (프로세스에 하나, 놓지 않음)


def _objc_runtime() -> _ObjCRuntime:
    global _objc
    if _objc is None:
        _objc = _ObjCRuntime()
    return _objc


def register_reopen_handler(on_reopen: Callable[[], None]) -> None:
    """(Mac) 'aevt'/'rapp'를 받으면 on_reopen()을 Qt 루프에서 부름. 다시 부르면 콜백만 바뀜.

    AppKit finishLaunching 뒤(이 앱은 FileOpenRouter.ready)에 부를 것 — 그 전이면 AppKit이 오류 없이 덮어씀."""
    global _reopen_handler
    if _reopen_handler is None:
        _reopen_handler = _ReopenHandler(_objc_runtime())
    _reopen_handler.register(on_reopen)
