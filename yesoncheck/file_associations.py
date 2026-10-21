"""Windows: 동영상(.mov·.mp4)의 "연결 프로그램"·Windows 기본 앱 설정에 YesonCheck (설계 3-3·4장·6장).

- Windows 10·11은 앱·설치 파일이 기본 앱을 바꾸지 못하게 한다 → 이 사용자(HKCU — 관리자 권한 없이)에 YesonCheck를 .mov·.mp4를
  여는 앱으로 등록만 하고(association_entries: ProgID YesonCheck.Video, 확장자의 OpenWithProgids, Applications\\<exe>\\
  SupportedTypes, Capabilities + RegisteredApplications), 기본 앱은 사용자가 한 번 "항상"으로 고른다. Help → MENU_TEXT가 Windows
  기본 앱 설정 화면을 연다(open_default_apps_settings — Windows 11(2023-04 업데이트 이후)은 YesonCheck 항목으로 바로, 그 전·
  Windows 10은 기본 앱 화면).
- 등록하는 곳은 둘이고 내용이 같다(tests/test_file_associations.py가 비교):
  - 설치 파일 installer/yesoncheck.iss [Registry] — 설치한 계정. 지울 때 우리 키(OWNED_KEYS)는 통째로, 다른 앱과 함께 쓰는 키
    (.mov·.mp4의 OpenWithProgids, RegisteredApplications)는 우리 값만 지움. ChangesAssociations=yes로 Windows에 알림.
  - 앱이 켤 때(register_at_start — 빌드한 Windows 앱만, 창을 보인 뒤): 같은 PC의 다른 계정은 설치 파일이 쓴 HKCU가 없으므로 그
    계정에서 처음 켤 때 같은 내용을 등록(설계 6장 "Windows 파일 연결은 계정마다"). 값을 읽어 다른 것만 쓰고, 쓴 것이 있으면
    SHChangeNotify(SHCNE_ASSOCCHANGED) — 설치한 계정에서는 읽기만(수 ms).
  - 알고 둔 한계: 제거 프로그램은 제거하는 계정의 HKCU만 지운다 — 다른 계정에 앱이 등록한 항목은 남는다(그 계정의 "연결
    프로그램"에 남은 YesonCheck는 없는 exe를 가리킴).
- 오류: 예상된 실패 — 레지스트리를 읽거나 쓰지 못함(액세스 거부 등 OSError → FileAssociationError: 어느 키·값과 원래 오류),
  설정 화면을 열지 못함(os.startfile의 OSError) — 는 오류 창에 무엇이 왜(기록에는 트레이스백도). 예상 못 한 예외는 기록과
  오류 창에 트레이스백. 오류 창은 빌드 앱이면 앱의 예외 창(app.make_excepthook가 sys.excepthook.dialog로 둔 창 — 기록 파일
  경로를 붙이고 한 번에 하나만), 그 창이 없으면(소스 실행) 같은 제목의 QMessageBox.critical (default_app._show_error와 같음).
- winreg·shell32는 Windows에만 있다 → 쓸 때 불러옴(_winreg·notify_associations_changed). 시험은 레지스트리(reg=)·알림(notify=)·
  설정 화면 열기(_open_uri)를 바꿔 끼워 Mac에서도 돈다.
"""

import ctypes
import os
import sys
import traceback

from PyQt5.QtWidgets import QMessageBox

from yesoncheck import file_names

IS_WINDOWS = sys.platform == "win32"  # Help 메뉴 항목·켤 때 등록 (시험이 바꿔 끼움)
EXTENSIONS = file_names.LISTED_VIDEO_EXTENSIONS  # .mov · .mp4

PROG_ID = "YesonCheck.Video"
PROG_ID_NAME = "Yeson Checker 동영상"  # 파일 종류 이름 (탐색기의 '유형')
EXE_NAME = "YesonCheck_Autocut.exe"  # 설치 파일의 MyAppExeName, PyInstaller spec의 name
APP_NAME = "Yeson Checker"  # 설치 파일의 MyAppName (시작 메뉴 바로 가기 이름) — 기본 앱 설정 화면의 앱 이름
APP_DESCRIPTION = "동영상 A/B 비교·검토"
REGISTERED_APP = "YesonCheck"  # RegisteredApplications의 값 이름 = 설정 화면 링크의 registeredAppUser
CAPABILITIES_KEY = r"Software\YesonCheck\Capabilities"
REGISTERED_APPLICATIONS_KEY = r"Software\RegisteredApplications"
# 제거 프로그램이 통째로 지우는 우리 키 (.iss uninsdeletekey) — 그 밖의 등록은 함께 쓰는 키의 우리 값(uninsdeletevalue)
OWNED_KEYS = (rf"Software\Classes\{PROG_ID}", rf"Software\Classes\Applications\{EXE_NAME}", r"Software\YesonCheck")

SETTINGS_URI = f"ms-settings:defaultapps?registeredAppUser={REGISTERED_APP}"
MENU_TEXT = "동영상 기본 앱 설정 열기…"
ERROR_TITLE = "YesonCheck 오류"  # 앱의 예외 창(app._ErrorDialog)과 같은 제목
REGISTER_FAILED_TEXT = ("동영상(.mov·.mp4)을 여는 앱으로 YesonCheck를 이 계정에 등록하지 못했습니다 — 탐색기의 '연결 프로그램'·"
                        "Windows 기본 앱 설정에 YesonCheck가 보이지 않을 수 있습니다.")
REGISTER_UNEXPECTED_TEXT = "동영상 연결 프로그램 등록을 확인하다 예상치 못한 오류가 났습니다."
SETTINGS_FAILED_TEXT = "Windows 기본 앱 설정 화면을 열지 못했습니다."
SETTINGS_UNEXPECTED_TEXT = "Windows 기본 앱 설정 화면을 열다 예상치 못한 오류가 났습니다."

SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000


class FileAssociationError(Exception):
    """예상된 실패 — 레지스트리의 키·값을 읽거나 쓰지 못함(액세스 거부 등). 글에 어느 키·값과 원래 오류."""


def association_entries(exe_path: str) -> list[tuple[str, str, str]]:
    """(순수) 이 사용자(HKCU)에 등록할 값들 (키, 값 이름 — 기본값은 "", 값 — 모두 REG_SZ). exe_path: 설치된
    YesonCheck_Autocut.exe (설치 파일은 "{app}\\YesonCheck_Autocut.exe")."""
    entries = [
        (rf"Software\Classes\{PROG_ID}", "", PROG_ID_NAME),
        (rf"Software\Classes\{PROG_ID}\DefaultIcon", "", f"{exe_path},0"),
        (rf"Software\Classes\{PROG_ID}\shell\open\command", "", f'"{exe_path}" "%1"'),
    ]
    entries += [(rf"Software\Classes\{ext}\OpenWithProgids", PROG_ID, "") for ext in EXTENSIONS]
    entries += [(rf"Software\Classes\Applications\{EXE_NAME}\SupportedTypes", ext, "") for ext in EXTENSIONS]
    entries += [
        (CAPABILITIES_KEY, "ApplicationName", APP_NAME),
        (CAPABILITIES_KEY, "ApplicationDescription", APP_DESCRIPTION),
    ]
    entries += [(rf"{CAPABILITIES_KEY}\FileAssociations", ext, PROG_ID) for ext in EXTENSIONS]
    entries.append((REGISTERED_APPLICATIONS_KEY, REGISTERED_APP, CAPABILITIES_KEY))
    return entries


def ensure_registered(exe_path: str, reg=None, notify=None) -> bool:
    """association_entries(exe_path)를 HKCU에서 읽어 없거나 다른 값(형이 REG_SZ가 아닌 것 포함)만 씀. 쓴 것이 있으면 Windows에
    알리고(notify — 기본 notify_associations_changed) True, 모두 같으면 아무것도 쓰지 않고 False. 함께 쓰는 키의 다른 앱 값은
    건드리지 않음. 읽기·쓰기 실패는 FileAssociationError (그 앞에서 쓴 것이 있으면 알림은 함).

    reg: winreg 모듈(기본 — Windows에서만 불러옴) 또는 같은 이름의 대역."""
    if reg is None:
        reg = _winreg()
    if notify is None:
        notify = notify_associations_changed
    changed = []
    try:
        for key_path, name, value in association_entries(exe_path):
            current = _read(reg, key_path, name)
            if current is not None and tuple(current) == (value, reg.REG_SZ):
                continue
            _write(reg, key_path, name, value)
            changed.append(f"HKCU\\{key_path} [{_shown(name)}] {current!r} → {value!r}")
    finally:
        if changed:
            _log(f"이 계정에 등록 ({len(changed)}개):\n" + "\n".join(f"  {line}" for line in changed))
            notify()
    return bool(changed)


def _read(reg, key_path, name):
    """(값, 형), 키나 값이 없으면 None (등록할 것 — 오류 아님). 그 밖의 OSError는 FileAssociationError."""
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_QUERY_VALUE) as key:
            return reg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise FileAssociationError(f"레지스트리를 읽지 못했습니다: HKCU\\{key_path} [{_shown(name)}]\n"
                                   f"{type(exc).__name__}: {exc}") from exc


def _write(reg, key_path, name, value):
    try:
        with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_SET_VALUE) as key:
            reg.SetValueEx(key, name, 0, reg.REG_SZ, value)
    except OSError as exc:
        raise FileAssociationError(f"레지스트리에 쓰지 못했습니다: HKCU\\{key_path} [{_shown(name)}] = {value!r}\n"
                                   f"{type(exc).__name__}: {exc}") from exc


def _shown(name):
    return name or "(기본값)"


def _winreg():
    """winreg 모듈 (Windows에만 있음 — 쓸 때 불러옴; 시험은 이 함수를 대역으로 바꿔 끼움)."""
    import winreg  # pylint: disable=import-outside-toplevel

    return winreg


def notify_associations_changed() -> None:
    """(Windows) 파일 연결이 바뀌었다고 셸에 알림 — SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, NULL, NULL). 돌려주는 값이
    없는 함수(void)라 확인할 결과가 없음."""
    function = ctypes.WinDLL("shell32").SHChangeNotify
    function.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    function.restype = None
    function(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)


# ---- 켤 때 · Help 메뉴 ----


def registers_on_start() -> bool:
    """app.launch: 이번에 켤 때 이 계정에 등록(register_at_start)할지 — 빌드한 Windows 앱만 (소스 실행의 sys.executable은
    python.exe)."""
    return IS_WINDOWS and bool(getattr(sys, "frozen", False))


def register_at_start() -> None:
    """(빌드한 Windows 앱, 창을 보인 뒤) 이 실행 파일(sys.executable)로 이 계정에 등록 — ensure_registered. 오류는 모두 창으로
    (밖으로 내보내지 않음 — Qt 루프에서 부름)."""
    exe_path = sys.executable
    try:
        changed = ensure_registered(exe_path)
    except FileAssociationError as exc:
        traceback.print_exc()
        _show_error(f"{REGISTER_FAILED_TEXT}\n\n{exc}")
        return
    except Exception:
        _show_unexpected(REGISTER_UNEXPECTED_TEXT)
        return
    if not changed:
        _log(f"이 계정에 이미 등록됨 ({exe_path})")


def open_default_apps_settings() -> None:
    """Help → MENU_TEXT: Windows 기본 앱 설정 화면(SETTINGS_URI — 지원하는 Windows 11은 YesonCheck 항목으로 바로). 열지 못하면
    오류 창 (무엇을·왜)."""
    try:
        _open_uri(SETTINGS_URI)
    except OSError as exc:
        traceback.print_exc()
        _show_error(f"{SETTINGS_FAILED_TEXT}\n{SETTINGS_URI}\n\n{type(exc).__name__}: {exc}")
        return
    except Exception:
        _show_unexpected(f"{SETTINGS_UNEXPECTED_TEXT}\n{SETTINGS_URI}")
        return
    _log(f"Windows 기본 앱 설정 화면을 엶: {SETTINGS_URI}")


def _open_uri(uri: str) -> None:
    """(Windows) ShellExecute로 uri를 엶 — os.startfile은 열지 못하면 OSError(돌려주는 값 없음). 시험은 대역으로 바꿔 끼움."""
    os.startfile(uri)  # pylint: disable=no-member (Windows에만 있음)


def _log(line):
    print(f"[파일 연결] {line}", flush=True)


def _show_unexpected(context):
    """예외 처리 중에: context와 트레이스백을 기록·오류 창으로."""
    _show_error(f"{context}\n\n{traceback.format_exc()}")


def _show_error(text):
    """기록(stderr)에 남기고 오류 창 — 빌드 앱이면 앱의 예외 창(app.make_excepthook가 sys.excepthook.dialog로 둔 창: 기록
    파일 경로를 붙이고, 이미 떠 있으면 기록에만), 그 창이 없으면(소스 실행) 같은 제목의 QMessageBox.critical."""
    print(f"[파일 연결] {text}", file=sys.stderr, flush=True)
    dialog = getattr(sys.excepthook, "dialog", None)
    if dialog is not None:
        dialog.show_error(text)
    else:
        QMessageBox.critical(None, ERROR_TITLE, text)
