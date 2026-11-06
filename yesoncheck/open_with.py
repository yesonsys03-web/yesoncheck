"""다른 앱으로 열기 — 사이드바 우클릭의 'QuickTime Player로 열기'(Mac)·'다른 앱으로 열기 ▸'(등록한 앱) (Qt 없음; 메뉴는 sidebar_open_with).

띄우기:
- Mac: QuickTime Player는 `/usr/bin/open -b com.apple.QuickTimePlayerX <파일…>`(앱 ID — 이름이 아니라; 파일은 문서 열기 이벤트로), 등록한
  앱은 `open -n -a <앱 경로> --args <파일…>` — **파일을 명령 줄 인자로**: DJV 3.7.5 같은 크로스 플랫폼 뷰어는 문서 열기 이벤트를 받지 않아
  `open -a <앱> <파일>`로는 앱만 켜짐(사용자 보고 2026-11-06; 인자를 적는 가짜 앱으로 확인 — 문서 열기는 인자 0개, --args는 공백·한글 경로
  그대로). -n은 그 앱이 이미 떠 있어도 새로 띄워 인자가 닿게(안 주면 떠 있는 앱을 앞으로 가져오기만 하고 인자는 버려짐). **파일마다 따로
  띄움**(Mac·Windows): DJV 3.7.5는 인자로 파일을 여럿 받아도 마지막 하나만 엶(`djv one.mov two.mov -exit -log` → `Files opened: 1`) — 그래서
  고른 파일마다 앱 창이 하나씩(여러 파일을 한 창에 받는 앱도 마찬가지 — 알고 둠). 실패하면 거기서 멈추고 몇 개를 열었는지 알림. 문서 열기 이벤트로만 파일을 받는 Mac 전용 앱은 이 방식으로 파일이 들어가지 않음(알고 둠 — 그런 앱은 Finder의 '다음으로 열기').
  `open`은 LaunchServices가 앱을 띄운 뒤 곧 돌아오므로 끝나기를 기다림(OPEN_TIMEOUT_S — new_window와 같음): 0이 아니거나 시간이 지나면
  RuntimeError(명령과 출력). 앱은 LaunchServices가 띄우므로 이 앱의 환경 변수를 물려받지 않음.
- Windows: 등록한 .exe를 `[exe, 파일…]`로 앱 폴더에서(cwd) 바로 띄우고 기다리지 않음(셸 없음 — 경로 하나가 인자 하나). 명령 줄 한도
  (external_tools.WINDOWS_COMMAND_LIMIT)를 넘으면 띄우지 않고 ValueError. **빌드 앱이면 PyInstaller가 바꾼 것을 걸러서 띄움** — 그대로
  물려주면 다른 Qt 앱이 이 앱의 Qt 플러그인·DLL을 읽어 죽을 수 있음(PyInstaller 문서 'Launching external programs from the Frozen
  Application'): PATH에서 앱 폴더(sys._MEIPASS)와 그 아래 폴더(paddle이 불러올 때 넣음)를 빼고, 앱 폴더 아래를 가리키는 다른 변수
  (PyQt5 런타임 훅의 QT_PLUGIN_PATH·QML2_IMPORT_PATH, TCL_LIBRARY 등)를 빼고, PYINSTALLER_RESET_ENVIRONMENT=1(띄우는 앱이 PyInstaller
  앱일 때 — new_window와 같은 이유), 부트로더가 정한 DLL 검색 경로(SetDllDirectoryW — 자식이 물려받음)를 띄우는 동안만 풀었다 띄우기 전
  값으로 되돌림(뒤늦게 불러오는 이 앱의 DLL을 위해 — 띄우다 실패해도). 풀지 못하면 띄우지 않고 OSError, 띄운 뒤 되돌리지 못하면
  DllDirectoryRestoreError(열기는 됐음). 푼 동안 다른 스레드가 이 앱의 DLL을 이름으로 불러오면 못 찾을 수 있음(아주 짧음 — 알고 둠).
- QuickTime Player는 Mac에만 (Windows판은 Apple이 2016년에 지원을 끝냄 — 메뉴에 없음).

등록한 앱 목록: 이 PC의 prefs.json `open_with_apps`(앱 경로 목록, 등록한 차례) — Mac ~/Library/Application Support/YesonCheck/prefs.json
(mac_prefs), Windows %LOCALAPPDATA%\\YesonCheck\\prefs.json. NAS 공유 설정에 넣지 않음(PC마다 앱 경로가 다름). 더하기·빼기는 잠금 안에서
다시 읽고 고침(mac_prefs.edit_prefs — 다른 창이 그사이 더한 앱을 지우지 않게). 값이 글자 목록이 아니면 UserFileError(빈 목록으로 치지 않아
다음 저장이 덮어 지우지 않음). 앱은 Mac은 .app 폴더, Windows는 .exe 파일만 받음.
"""

import ntpath
import os
import subprocess
import sys

from yesoncheck import external_tools, mac_prefs, paths
from yesoncheck.update_install import PYINSTALLER_RESET_ENV
from yesoncheck.user_files import UserFileError

PREF_KEY = "open_with_apps"
QUICKTIME_LABEL = "QuickTime Player"
QUICKTIME_BUNDLE_ID = "com.apple.QuickTimePlayerX"
MAC_OPEN = "/usr/bin/open"
OPEN_TIMEOUT_S = 30  # Mac `open`이 돌아오기를 기다리는 한도 (new_window.OPEN_TIMEOUT_S와 같음)
APP_SUFFIX = {"darwin": ".app", "win32": ".exe"}
PYINSTALLER_ENV_KEYS = ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH")  # PyInstaller의 PyQt5 런타임 훅이 넣는 것 (원래 값은 남지 않음)


def _check_platform(platform):
    if platform not in APP_SUFFIX:
        raise RuntimeError(f"다른 앱으로 열기는 Mac·Windows에서만 됩니다 (이 시스템: {platform})")


def quicktime_available(platform=None) -> bool:
    return (platform or sys.platform) == "darwin"


# ---------------------------------------------------------------- 명령


def _need_files(files):
    if not files:
        raise ValueError("열 파일이 없습니다")


def quicktime_command(files) -> list:
    _need_files(files)
    return [MAC_OPEN, "-b", QUICKTIME_BUNDLE_ID, *files]


def app_command(app, files, platform) -> list:
    """등록한 앱 app으로 files를 여는 명령. Windows는 명령 줄 한도를 넘으면 ValueError."""
    _check_platform(platform)
    _need_files(files)
    if platform == "darwin":
        return [MAC_OPEN, "-n", "-a", app, "--args", *files]
    args = [app, *files]
    length = len(subprocess.list2cmdline(args))
    if length > external_tools.WINDOWS_COMMAND_LIMIT:
        raise ValueError(f"고른 파일이 많아 Windows 명령 줄 한도(약 {external_tools.WINDOWS_COMMAND_LIMIT:,}자)를 넘습니다 "
                         f"({len(files)}개, {length:,}자). 한 번에 열 파일 수를 줄이세요.")
    return args


def app_label(app) -> str:
    """메뉴에 보일 이름: 파일 이름에서 확장자를 뺀 것 (DJV.app → DJV, vlc.exe → vlc)."""
    return os.path.splitext(ntpath.basename(app.rstrip("/\\")))[0]  # ntpath는 /와 \를 모두 나눔 (어느 OS에서든 Windows 경로도)


def app_missing(app, platform) -> bool:
    """등록한 앱이 지금 그 자리에 없음 (지웠거나 옮김 — 메뉴에서 꺼 둠)."""
    return not (os.path.isdir(app) if platform == "darwin" else os.path.isfile(app))


# ---------------------------------------------------------------- 등록한 앱 목록


def prefs_path(platform) -> str:
    _check_platform(platform)
    if platform == "darwin":
        return mac_prefs.prefs_path()
    return os.path.join(os.environ["LOCALAPPDATA"], "YesonCheck", mac_prefs.PREFS_FILE_NAME)


def _apps_of(prefs, path) -> list:
    value = prefs.get(PREF_KEY, [])
    if not isinstance(value, list) or not all(isinstance(app, str) for app in value):
        raise UserFileError(f"설정 파일의 {PREF_KEY}가 앱 경로 목록이 아닙니다: {path} ({value!r})")
    return value


def registered_apps(platform) -> list:
    """등록한 앱 경로들 (등록한 차례). 파일이 없으면 []; 깨졌거나 값이 목록이 아니면 UserFileError."""
    path = prefs_path(platform)
    return list(_apps_of(mac_prefs.read_prefs(path), path))


def add_app(app, platform) -> list:
    """app을 목록 끝에 더함(이미 있으면 그대로 — 자리도) → 새 목록. Mac은 .app 폴더, Windows는 .exe 파일이 아니면 ValueError."""
    _check_platform(platform)
    suffix = APP_SUFFIX[platform]
    if not app.lower().endswith(suffix) or app_missing(app, platform):
        raise ValueError(f"앱으로 등록할 수 없습니다 — {suffix} {'폴더' if platform == 'darwin' else '파일'}가 아닙니다: {app}")
    path = prefs_path(platform)

    def edit(prefs):
        apps = _apps_of(prefs, path)
        if not any(paths.same_path(app, known) for known in apps):
            prefs[PREF_KEY] = [*apps, app]

    return list(_apps_of(mac_prefs.edit_prefs(edit, path), path))


def remove_app(app, platform) -> list:
    """app을 목록에서 뺌 → 새 목록 (없으면 그대로)."""
    path = prefs_path(platform)

    def edit(prefs):
        prefs[PREF_KEY] = [known for known in _apps_of(prefs, path) if not paths.same_path(app, known)]

    return list(_apps_of(mac_prefs.edit_prefs(edit, path), path))


# ---------------------------------------------------------------- 띄우기


def open_with_quicktime(files, platform=None, popen=subprocess.Popen) -> None:
    platform = platform or sys.platform
    if not quicktime_available(platform):
        raise RuntimeError(f"{QUICKTIME_LABEL}는 Mac에서만 열 수 있습니다 (이 시스템: {platform})")
    _run_mac_open(quicktime_command(files), popen)


def open_with_app(app, files, platform=None, popen=subprocess.Popen, dll_directory=None) -> None:
    """등록한 앱 app으로 files를 엶 — **파일마다 따로 띄움** (모듈 설명의 '띄우기'). dll_directory: 시험용 (Windows 빌드 앱의 DLL 검색 경로 — get·set)."""
    platform = platform or sys.platform
    _need_files(files)
    commands = [app_command(app, [file], platform) for file in files]
    if platform == "darwin":
        _launch_each(commands, files, lambda args: _run_mac_open(args, popen))
    else:
        _launch_windows(commands, files, popen, dll_directory)


def _launch_each(commands, files, launch) -> None:
    """commands를 차례로 띄움 — 실패하면 거기서 멈춤. 앞에서 띄운 것이 있으면 몇 개를 열었는지 담은 RuntimeError(원인은 __cause__)."""
    for index, args in enumerate(commands):
        try:
            launch(args)
        except (OSError, RuntimeError) as exc:
            if index == 0:
                raise
            raise RuntimeError(f"파일 {len(commands)}개 중 {index}개는 열었고 {index + 1}번째에서 멈췄습니다: {files[index]}") from exc


def _run_mac_open(args, popen) -> None:
    """`open`을 띄워 끝나기를 기다림. 0이 아니거나 시간이 지나면 RuntimeError (new_window._open_new_instance와 같은 모양)."""
    proc = popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                 encoding="utf-8", errors="replace")
    try:
        output, _ = proc.communicate(timeout=OPEN_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        output, _ = proc.communicate()
        raise RuntimeError(_open_error(f"open이 {OPEN_TIMEOUT_S}초 안에 끝나지 않아 끝냈습니다", args, output)) from exc
    if proc.returncode != 0:
        raise RuntimeError(_open_error(f"open이 종료 코드 {proc.returncode}로 끝났습니다", args, output))


def _open_error(reason, args, output) -> str:
    return f"다른 앱으로 열지 못했습니다 — {reason}.\n명령: {' '.join(args)}\n출력: {(output or '').strip() or '(없음)'}"


class DllDirectoryRestoreError(OSError):
    """(Windows 빌드 앱) 앱은 띄웠지만 DLL 검색 경로를 되돌리지 못함 — 열기는 됐음. 이 창이 나중에 불러오는 DLL(OCR·애니매틱2 등)을
    못 찾을 수 있어 알림 (메뉴는 '열었지만 …, 앱을 다시 켜세요')."""


def _launch_windows(commands, files, popen, dll_directory) -> None:
    """파일마다의 명령을 차례로 띄움 — 빌드 앱이면 DLL 검색 경로를 한 번 풀고 다 띄운 뒤 한 번 되돌림 (모듈 설명)."""
    meipass = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  cwd=ntpath.dirname(commands[0][0]))  # 앱 폴더에서 — 자기 폴더 기준으로 파일을 찾는 앱
    if meipass is None:  # 소스 실행: 바꾼 것이 없음
        _launch_each(commands, files, lambda args: popen(args, **kwargs))
        return
    dll = dll_directory or _WindowsDllDirectory()
    before = dll.get()
    dll.set(None)  # 실패하면 OSError — 정리하지 못한 채 띄우지 않음
    launched = False
    env = _clean_env(meipass)
    try:
        _launch_each(commands, files, lambda args: popen(args, env=env, **kwargs))
        launched = True
    finally:
        try:
            dll.set(before)
        except OSError as exc:
            if not launched:
                raise  # 띄우기 실패가 __context__로 남음
            raise DllDirectoryRestoreError(f"앱은 띄웠지만 DLL 검색 경로를 되돌리지 못했습니다 ({before}): {exc}") from exc


def _clean_env(meipass) -> dict:
    """이 앱의 환경에서 PyInstaller·번들 라이브러리가 넣은 것을 뺀 사본 (모듈 설명) — 이 앱의 환경은 그대로.
    PATH는 앱 폴더(_MEIPASS)와 그 아래 폴더(paddle이 불러올 때 넣는 paddle\\base 등)만 빼고, 다른 변수는 값(;로 나눈 어느 조각이든)이
    앱 폴더 아래를 가리키면 통째로 뺌(런타임 훅의 QT_PLUGIN_PATH·TCL_LIBRARY 등). Windows 규칙(구분자 ;, 대소문자 무시, .. 풀기)."""
    bundle = _windows_dir_key(meipass)

    def in_bundle(entry):
        key = _windows_dir_key(entry)
        return key == bundle or key.startswith(bundle + "\\")

    env = {}
    for key, value in os.environ.items():
        if key.upper() == "PATH":
            env[key] = ";".join(entry for entry in value.split(";") if entry and not in_bundle(entry))
        elif key not in PYINSTALLER_ENV_KEYS and not any(part and in_bundle(part) for part in value.split(";")):
            env[key] = value
    env[PYINSTALLER_RESET_ENV] = "1"
    return env


def _windows_dir_key(path) -> str:
    return ntpath.normcase(ntpath.normpath(path))


DLL_DIRECTORY_BUFFER = 32768  # GetDllDirectoryW 버퍼 (글자 수 — Windows 경로 최대 길이)


class _WindowsDllDirectory:
    """kernel32의 GetDllDirectoryW·SetDllDirectoryW (Windows에서만 만듦 — 시험은 get·set이 같은 모양인 가짜를 넣음)."""

    def __init__(self):
        import ctypes

        self._ctypes = ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        kernel32.SetDllDirectoryW.restype = ctypes.c_int  # BOOL
        kernel32.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
        kernel32.GetDllDirectoryW.restype = ctypes.c_uint32  # 복사한 글자 수 (끝 NUL 빼고), 실패·없음이면 0
        self._kernel32 = kernel32

    def get(self):
        """지금 정해진 DLL 검색 경로 — 없으면 None. 실패는 OSError."""
        buffer = self._ctypes.create_unicode_buffer(DLL_DIRECTORY_BUFFER)
        self._ctypes.set_last_error(0)
        length = self._kernel32.GetDllDirectoryW(DLL_DIRECTORY_BUFFER, buffer)
        if length == 0:
            error = self._ctypes.get_last_error()
            if error:
                raise OSError(f"GetDllDirectoryW가 실패했습니다 (오류 {error})")
            return None
        if length >= DLL_DIRECTORY_BUFFER:
            raise OSError(f"GetDllDirectoryW: DLL 검색 경로가 너무 깁니다 ({length}자)")
        return buffer.value

    def set(self, path):
        """path(None = 기본 검색 순서로)로 정함. 실패는 OSError."""
        if not self._kernel32.SetDllDirectoryW(path):
            raise OSError(f"SetDllDirectoryW({path!r})가 실패했습니다 (오류 {self._ctypes.get_last_error()})")
