"""yesoncheck/file_associations.py 시험: Windows에서 .mov·.mp4의 "연결 프로그램"·기본 앱 설정에 YesonCheck (설계 3-3·4장·6장).

- 레지스트리는 대역(FakeRegistry — winreg와 같은 이름의 함수·상수)으로 바꿔 끼움: Mac·Windows CI 모두 이 PC의 레지스트리를
  건드리지 않음. 설정 화면 열기(_open_uri)도 대역.
- 설치 파일(installer/yesoncheck.iss)의 [Registry]가 association_entries와 같은지 Mac에서도 비교 (둘이 어긋나지 않게).
- 설치 파일이 실제로 쓴 값·지운 값: test_installer_registers_open_with / test_uninstaller_removes_open_with — CI
  (windows-build.yml)가 무음 설치·무음 제거 바로 뒤에 환경 변수 YC_INSTALLED_EXE / YC_UNINSTALLED_EXE(설치한 exe 경로)를 주고
  이 시험만 돌림. 변수가 없으면(보통 시험) 건너뛰고, 있는데 Windows가 아니면 실패 (CI 단계가 말없이 건너뛰지 않게).
"""

import codecs
import os
import re
import sys
import time

import pytest
from PyQt5.QtWidgets import QApplication, QWidget

from tests.conftest import ROOT
from tests.test_fast_startup import wait_until
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import app as app_module  # sys.frozen을 바꾸기 전에 (불러올 때 frozen이면 _MEIPASS를 찾음)
from yesoncheck import default_app, file_associations

EXE = r"C:\Program Files\Yeson Check\YesonCheck_Autocut.exe"  # 공백이 든 설치 경로
ISS_PATH = os.path.join(ROOT, "installer", "yesoncheck.iss")
INSTALLED_EXE = os.environ.get("YC_INSTALLED_EXE")
UNINSTALLED_EXE = os.environ.get("YC_UNINSTALLED_EXE")


class _Key:
    """FakeRegistry의 열린 키 (with 블록 — winreg의 PyHKEY처럼). path: 연 그대로의 경로."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeRegistry:
    """winreg 대역 — HKCU만. 키 경로·값 이름은 Windows처럼 대소문자 무관. 없는 키·값은 FileNotFoundError(winreg와 같음).
    writes: 쓴 차례 (키, 값 이름, 값). deny_write / deny_read: 이 키(소문자)는 PermissionError (액세스 거부)."""

    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1
    REG_EXPAND_SZ = 2
    KEY_QUERY_VALUE = 0x0001
    KEY_SET_VALUE = 0x0002

    def __init__(self):
        self.keys = {}  # 키 경로(소문자) → {값 이름(소문자): (값, 형)}
        self.writes = []
        self.deny_write = set()
        self.deny_read = set()

    def put(self, path, name, value, kind=REG_SZ):
        self._create(path)[name.lower()] = (value, kind)

    def get(self, path, name):
        return self.keys.get(path.lower(), {}).get(name.lower())

    def _create(self, path):
        parts = path.lower().split("\\")
        for i in range(1, len(parts) + 1):
            self.keys.setdefault("\\".join(parts[:i]), {})
        return self.keys[path.lower()]

    def OpenKey(self, root, path, reserved=0, access=KEY_QUERY_VALUE):  # noqa: N802 (winreg 이름)
        assert root == self.HKEY_CURRENT_USER and access == self.KEY_QUERY_VALUE
        if path.lower() in self.deny_read:
            raise PermissionError(13, "시험: 액세스가 거부되었습니다")
        if path.lower() not in self.keys:
            raise FileNotFoundError(2, "시험: 지정된 파일을 찾을 수 없습니다")
        return _Key(path)

    def CreateKeyEx(self, root, path, reserved=0, access=KEY_SET_VALUE):  # noqa: N802
        assert root == self.HKEY_CURRENT_USER and access == self.KEY_SET_VALUE
        if path.lower() in self.deny_write:
            raise PermissionError(13, "시험: 액세스가 거부되었습니다")
        self._create(path)
        return _Key(path)

    def QueryValueEx(self, key, name):  # noqa: N802
        values = self.keys[key.path.lower()]
        if name.lower() not in values:
            raise FileNotFoundError(2, "시험: 지정된 파일을 찾을 수 없습니다")
        return values[name.lower()]

    def SetValueEx(self, key, name, reserved, kind, value):  # noqa: N802
        assert reserved == 0
        self.writes.append((key.path, name, value))
        self.keys[key.path.lower()][name.lower()] = (value, kind)


@pytest.fixture
def reg():
    return FakeRegistry()


@pytest.fixture
def notified():
    return []


def ensure(reg, notified, exe=EXE):
    return file_associations.ensure_registered(exe, reg=reg, notify=lambda: notified.append(exe))


# ---- 등록할 항목 ----


def test_entries_quote_exe_and_percent1():
    entries = file_associations.association_entries(EXE)
    assert entries == [
        (r"Software\Classes\YesonCheck.Video", "", "Yeson Checker 동영상"),
        (r"Software\Classes\YesonCheck.Video\DefaultIcon", "", EXE + ",0"),
        # 공백이 든 경로·파일 이름도 한 인자로: exe와 %1을 각각 따옴표로
        (r"Software\Classes\YesonCheck.Video\shell\open\command", "",
         '"C:\\Program Files\\Yeson Check\\YesonCheck_Autocut.exe" "%1"'),
        (r"Software\Classes\.mov\OpenWithProgids", "YesonCheck.Video", ""),
        (r"Software\Classes\.mp4\OpenWithProgids", "YesonCheck.Video", ""),
        (r"Software\Classes\Applications\YesonCheck_Autocut.exe\SupportedTypes", ".mov", ""),
        (r"Software\Classes\Applications\YesonCheck_Autocut.exe\SupportedTypes", ".mp4", ""),
        (r"Software\YesonCheck\Capabilities", "ApplicationName", "Yeson Checker"),
        (r"Software\YesonCheck\Capabilities", "ApplicationDescription", file_associations.APP_DESCRIPTION),
        (r"Software\YesonCheck\Capabilities\FileAssociations", ".mov", "YesonCheck.Video"),
        (r"Software\YesonCheck\Capabilities\FileAssociations", ".mp4", "YesonCheck.Video"),
        (r"Software\RegisteredApplications", "YesonCheck", r"Software\YesonCheck\Capabilities"),
    ]
    # 확장자는 사이드바가 보여 주는 영상 종류와 같음 (file_names.LISTED_VIDEO_EXTENSIONS)
    assert file_associations.EXTENSIONS == (".mov", ".mp4")
    # 설정 화면 링크의 registeredAppUser = RegisteredApplications의 값 이름
    assert file_associations.SETTINGS_URI == "ms-settings:defaultapps?registeredAppUser=YesonCheck"
    assert file_associations.MENU_TEXT == "동영상 기본 앱 설정 열기…"
    # 모든 키는 HKCU 아래 경로 (HKLM·HKCR 없음 — 관리자 권한 없이), 값은 모두 글자
    for key, name, value in entries:
        assert key.startswith("Software\\") and not key.endswith("\\") and "/" not in key
        assert isinstance(name, str) and isinstance(value, str)


# ---- 켤 때 이 계정에 등록 (ensure_registered) ----


def test_ensure_registered_idempotent(reg, notified):
    # 함께 쓰는 키에 있던 다른 앱의 값은 그대로 둠
    reg.put(r"Software\Classes\.mov\OpenWithProgids", "QuickTime.mov", "")
    reg.put(r"Software\RegisteredApplications", "Other App", r"Software\Other\Capabilities")
    entries = file_associations.association_entries(EXE)

    # 처음(이 계정에 등록 없음): 모두 쓰고 Windows에 한 번 알림
    assert ensure(reg, notified) is True
    assert notified == [EXE]
    assert reg.writes == entries
    for key, name, value in entries:
        assert reg.get(key, name) == (value, reg.REG_SZ)
    assert reg.get(r"Software\Classes\.mov\OpenWithProgids", "QuickTime.mov") == ("", reg.REG_SZ)
    assert reg.get(r"Software\RegisteredApplications", "Other App") == (r"Software\Other\Capabilities", reg.REG_SZ)

    # 다시 켬(설치 파일이 이미 등록한 계정과 같음): 읽기만 — 쓰지도 알리지도 않음
    reg.writes.clear()
    assert ensure(reg, notified) is False
    assert reg.writes == [] and notified == [EXE]

    # 다른 자리의 앱이 등록돼 있으면(설치 폴더를 옮김) 이 앱의 경로로 — 다른 값만 씀
    old = r"D:\Old\YesonCheck_Autocut.exe"
    assert ensure(reg, notified, old) is True
    reg.writes.clear()
    assert ensure(reg, notified) is True
    assert reg.writes == [(r"Software\Classes\YesonCheck.Video\DefaultIcon", "", EXE + ",0"),
                          (r"Software\Classes\YesonCheck.Video\shell\open\command", "", f'"{EXE}" "%1"')]
    assert notified == [EXE, old, EXE]

    # 값은 같아도 형이 다르면(REG_EXPAND_SZ) REG_SZ로 다시 씀
    reg.put(r"Software\YesonCheck\Capabilities", "ApplicationName", "Yeson Checker", reg.REG_EXPAND_SZ)
    reg.writes.clear()
    assert ensure(reg, notified) is True
    assert reg.writes == [(r"Software\YesonCheck\Capabilities", "ApplicationName", "Yeson Checker")]
    assert ensure(reg, notified) is False


def test_ensure_registered_reports_registry_errors(reg, notified):
    """레지스트리를 읽거나 쓰지 못하면(액세스 거부 등) FileAssociationError — 어느 키·값인지와 원래 오류. 그 앞에서 바꾼 것이
    있으면 Windows에 알림은 함. 없는 키·값(FileNotFoundError)은 오류가 아니라 '등록할 것'."""
    command_key = r"Software\Classes\YesonCheck.Video\shell\open\command"
    reg.deny_write.add(command_key.lower())
    with pytest.raises(file_associations.FileAssociationError) as caught:
        ensure(reg, notified)
    text = str(caught.value)
    assert f"HKCU\\{command_key}" in text and "PermissionError" in text and "액세스가 거부" in text
    assert len(reg.writes) == 2 and notified == [EXE]  # 앞의 두 값은 썼음 → 알림

    reg.deny_write.clear()
    reg.deny_read.add(r"software\registeredapplications")
    notified.clear()
    with pytest.raises(file_associations.FileAssociationError, match=r"HKCU\\Software\\RegisteredApplications"):
        ensure(reg, notified)
    assert notified == [EXE]  # 읽기 오류 앞에서 나머지를 썼음


# ---- 켤 때 (app.launch) ----


@pytest.fixture
def windows_app(monkeypatch):
    """Windows 빌드 앱처럼: sys.frozen, 실행 파일 sys.executable은 EXE. Mac 기본 앱 묻기는 없음."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", EXE)
    monkeypatch.setattr(file_associations, "IS_WINDOWS", True)
    monkeypatch.setattr(default_app, "IS_MAC", False)


def test_register_at_start_registers_running_exe(qapp, windows_app, dialogs, monkeypatch, reg, notified, capsys):
    monkeypatch.setattr(file_associations, "_winreg", lambda: reg)
    monkeypatch.setattr(file_associations, "notify_associations_changed", lambda: notified.append("notify"))
    file_associations.register_at_start()
    assert reg.get(r"Software\Classes\YesonCheck.Video\shell\open\command", "") == (f'"{EXE}" "%1"', reg.REG_SZ)
    assert notified == ["notify"] and dialogs.messages == []
    assert "[파일 연결]" in capsys.readouterr().out  # 바꾼 것을 기록에
    file_associations.register_at_start()
    assert notified == ["notify"] and dialogs.messages == []


def test_register_at_start_failure_shows_error_window(qapp, windows_app, dialogs, monkeypatch, tmp_path, capsys):
    """실패는 앱의 오류 창(app.make_excepthook의 창 — 기록 파일 경로)으로, 기록에는 트레이스백. 예상된 실패(레지스트리 오류)는
    창에 무엇이 왜, 예상 못 한 오류는 창에도 트레이스백."""
    log_path = str(tmp_path / "yesoncheck_20261021_123.log")
    monkeypatch.setattr(sys, "excepthook", app_module.make_excepthook(log_path))

    def denied(exe_path):
        assert exe_path == EXE
        raise file_associations.FileAssociationError(r"HKCU\Software\Classes\YesonCheck.Video: PermissionError: 시험")

    monkeypatch.setattr(file_associations, "ensure_registered", denied)
    file_associations.register_at_start()
    [(kind, title, text)] = dialogs.messages
    assert kind == "critical" and title == "YesonCheck 오류"
    assert file_associations.REGISTER_FAILED_TEXT in text and "PermissionError: 시험" in text
    assert f"로그: {log_path}" in text and "Traceback" not in text
    assert "Traceback" in capsys.readouterr().err

    def broken(exe_path):
        raise RuntimeError("시험: 예상 못 한 오류")

    dialogs.messages.clear()
    monkeypatch.setattr(file_associations, "ensure_registered", broken)
    file_associations.register_at_start()
    [(kind, title, text)] = dialogs.messages
    assert kind == "critical" and "Traceback" in text and "시험: 예상 못 한 오류" in text
    assert "시험: 예상 못 한 오류" in capsys.readouterr().err


def test_registers_at_start_only_in_built_windows_app(qapp, windows_app, monkeypatch):
    """빌드한 Windows 앱만, 창을 보인 뒤(시작을 늦추지 않게) 다른 시작 일 다음에. 소스 실행·Mac은 하지 않음."""
    assert file_associations.registers_on_start()
    monkeypatch.setattr(file_associations, "IS_WINDOWS", False)
    assert not file_associations.registers_on_start()
    monkeypatch.setattr(file_associations, "IS_WINDOWS", True)
    monkeypatch.delattr(sys, "frozen")
    assert not file_associations.registers_on_start()
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    events = []

    class FakePlayer(QWidget):
        def __init__(self, **kwargs):
            super().__init__()

        def show(self):
            events.append("show")
            super().show()

        def handle_update_startup(self, update_token):
            events.append(("update", update_token))

        def start_instance_link(self):
            events.append("instances")

        def show_user_file_problems(self):
            events.append("user_files")

        def start_shared_config_load(self):
            events.append("load")

    created = []
    monkeypatch.setattr(app_module, "VideoPlayer", lambda **kwargs: created.append(FakePlayer(**kwargs)) or created[-1])
    monkeypatch.setattr(app_module, "update_in_progress_at_start", lambda: False)
    monkeypatch.setattr(file_associations, "register_at_start", lambda: events.append("register"))
    try:
        assert app_module.launch(["yesoncheck"]) == 0
        wait_until(lambda: "register" in events)
        assert events == ["show", ("update", None), "instances", "user_files", "load", "register"]

        # 소스 실행: 등록하지 않음 (sys.executable이 python.exe)
        events.clear()
        monkeypatch.delattr(sys, "frozen")
        assert app_module.launch(["yesoncheck"]) == 0
        wait_until(lambda: "load" in events)
        for _ in range(5):
            QApplication.processEvents()
        assert events == ["show", ("update", None), "instances", "user_files", "load"]
    finally:
        for player in created:
            player.close()


# ---- Help 메뉴 ----


@pytest.mark.parametrize("is_windows", [True, False])
def test_help_menu_opens_settings_on_windows(new_player, dialogs, tmp_path, monkeypatch, is_windows):
    """Windows만 "동영상 기본 앱 설정 열기…" → Windows 기본 앱 설정 화면의 YesonCheck 항목. 열지 못하면 오류 창.
    Mac 항목("동영상 기본 앱으로 정하기…")은 Mac만 (default_app)."""
    monkeypatch.setattr(file_associations, "IS_WINDOWS", is_windows)
    monkeypatch.setattr(default_app, "IS_MAC", not is_windows)
    opened = []
    monkeypatch.setattr(file_associations, "_open_uri", opened.append)
    player = new_player(make_config(str(tmp_path), {}))
    [help_menu] = [action.menu() for action in player.menuBar().actions() if action.text() == "&Help"]
    texts = [action.text() for action in help_menu.actions()]
    assert (file_associations.MENU_TEXT in texts) is is_windows
    assert (default_app.MENU_TEXT in texts) is (not is_windows)
    if not is_windows:
        return
    [action] = [action for action in help_menu.actions() if action.text() == file_associations.MENU_TEXT]
    action.trigger()
    assert opened == ["ms-settings:defaultapps?registeredAppUser=YesonCheck"]
    assert dialogs.messages == []

    def fail(uri):
        raise OSError(22, "시험: 설정 화면을 열 수 없음")

    monkeypatch.setattr(file_associations, "_open_uri", fail)
    action.trigger()
    [(kind, title, text)] = dialogs.messages
    assert kind == "critical" and file_associations.SETTINGS_FAILED_TEXT in text
    assert file_associations.SETTINGS_URI in text and "시험: 설정 화면을 열 수 없음" in text


def test_platform_flag_matches_this_platform():
    assert file_associations.IS_WINDOWS is (sys.platform == "win32")


# ---- 설치 파일 (installer/yesoncheck.iss) ----


def _iss_bytes():
    with open(ISS_PATH, "rb") as fh:
        return fh.read()


def _iss_lines():
    """설치 파일의 줄들 — ISCC처럼 앞의 UTF-8 BOM은 버리고 줄 끝은 LF·CRLF 모두 (Windows의 git checkout은 CRLF — core.autocrlf;
    re.M의 '$'나 split("\\n")은 줄 끝의 \\r을 남겨 #define·구역 이름을 못 찾음)."""
    return _iss_bytes().decode("utf-8-sig").splitlines()


def _iss_defines(lines):
    """ISPP #define 이름 → 값 (따옴표로 묶은 글자만)."""
    found = (re.fullmatch(r'#define (\w+) "([^"]*)"', line.strip()) for line in lines)
    return dict(match.groups() for match in found if match)


def _iss_sections(lines):
    """구역 이름("[Setup]" 등) → 그 구역의 줄들 (앞뒤 공백 없이, 빈 줄·';' 주석·'#' 전처리 줄은 뺌)."""
    sections, current = {}, None
    for line in lines:
        line = line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line, [])
        elif current is not None:
            current.append(line)
    return sections


def _iss_params(line):
    """Inno 항목 한 줄 → {이름: 값}. 값은 ';'로 나뉘고, 따옴표 안의 ';'는 값의 일부, 따옴표 안의 ""는 "."""
    params, i = {}, 0
    while i < len(line):
        name_end = line.index(":", i)
        name = line[i:name_end].strip()
        i = name_end + 1
        while i < len(line) and line[i] == " ":
            i += 1
        if i < len(line) and line[i] == '"':
            value, i = [], i + 1
            while True:
                if line[i] == '"':
                    if i + 1 < len(line) and line[i + 1] == '"':
                        value.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                value.append(line[i])
                i += 1
            value = "".join(value)
            rest = line[i:].lstrip()
            assert rest == "" or rest.startswith(";"), line
            i = len(line) - len(rest) + 1
        else:
            end = line.find(";", i)
            end = len(line) if end < 0 else end
            value = line[i:end].strip()
            i = end + 1
        params[name] = value
        while i < len(line) and line[i] == " ":
            i += 1
    return params


def _iss_registry():
    """[Registry] 항목들 ({이름: 값}) — ISPP의 {#이름}은 같은 파일의 #define 값으로 바꿈."""
    lines = _iss_lines()
    defines = _iss_defines(lines)
    return [_iss_params(re.sub(r"\{#(\w+)\}", lambda m: defines[m.group(1)], line))
            for line in _iss_sections(lines).get("[Registry]", [])]


def test_installer_registry_matches_association_entries():
    """설치 파일의 [Registry]와 앱이 켤 때 등록하는 것(association_entries)이 같음. 모두 HKCU, 지울 때 우리 키는
    통째로(uninsdeletekey), 다른 앱과 함께 쓰는 키는 우리 값만(uninsdeletevalue). 설치·제거 때 Windows에 알림
    (ChangesAssociations=yes)."""
    entries = _iss_registry()
    assert entries, "[Registry] 항목이 없습니다"
    for entry in entries:
        assert entry["Root"] == "HKCU", entry
    values = [(e["Subkey"], e["ValueName"], e["ValueData"]) for e in entries if "ValueType" in e]
    for entry in entries:
        if "ValueType" in entry:
            assert entry["ValueType"] == "string", entry
    expected = file_associations.association_entries(r"{app}\YesonCheck_Autocut.exe")
    assert sorted(values) == sorted(expected) and len(values) == len(set(values))

    flags = {(e["Subkey"], e.get("ValueName")): set(e.get("Flags", "").split()) for e in entries}
    key_only = {e["Subkey"]: set(e.get("Flags", "").split()) for e in entries if "ValueType" not in e}
    owned = file_associations.OWNED_KEYS
    for key in owned:
        # 우리 키의 맨 위는 통째로 지움 (값이 없는 항목이면 키만 만들고 지울 때 지움)
        top = [f for (subkey, _), f in flags.items() if subkey == key]
        assert top and all("uninsdeletekey" in f for f in top), key
    for subkey, name, _ in values:
        if any(subkey == key or subkey.startswith(key + "\\") for key in owned):
            continue
        # 함께 쓰는 키(.mov·.mp4의 OpenWithProgids, RegisteredApplications): 우리 값만 지움 — 키는 지우지 않음
        assert flags[(subkey, name)] == {"uninsdeletevalue"}, (subkey, name)
    for key, key_flags in key_only.items():
        assert key in owned and key_flags == {"uninsdeletekey"}, key

    lines = _iss_lines()
    assert "ChangesAssociations=yes" in _iss_sections(lines)["[Setup]"]
    defines = _iss_defines(lines)
    assert defines["MyAppExeName"] == "YesonCheck_Autocut.exe" and defines["MyAppName"] == "Yeson Checker"


def test_installer_script_is_utf8_with_bom():
    """ProgID 이름("Yeson Checker 동영상") 등 한글을 레지스트리에 씀 → ISCC가 UTF-8로 읽어야 함. Inno Setup 6.3부터는 BOM 없는
    UTF-8도 알아보지만(내용으로 판단), 그 전 6.x는 BOM이 없으면 ANSI(한국어 Windows는 949)로 읽어 글자가 깨짐 — 어느 ISCC로
    컴파일해도 같게 BOM을 둠 (CI는 설치 뒤 레지스트리의 값을 다시 읽어 확인 — test_installer_registers_open_with)."""
    raw = _iss_bytes()
    assert raw.startswith(codecs.BOM_UTF8)
    assert "Yeson Checker 동영상" in raw[len(codecs.BOM_UTF8):].decode("utf-8")  # BOM 뒤는 모두 UTF-8


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["LF", "CRLF"])
def test_installer_parser_handles_crlf_and_bom(tmp_path, monkeypatch, newline):
    """Windows CI의 checkout은 줄 끝이 CRLF(git core.autocrlf — 저장소에는 LF)이고 파일 앞에 BOM: 설치 파일 시험들이 같은 내용을
    LF·CRLF 어느 쪽으로 받아도 같은 결과 (CRLF에서 #define을 못 찾아 KeyError로 깨졌었음 — CI 39615777321). BOM 바로 뒤 첫 줄의
    #define, 따옴표 두 개("")·{#이름}·줄 끝의 \r이 값에 남지 않는지는 작은 글로."""
    with open(ISS_PATH, "rb") as fh:
        text = fh.read().decode("utf-8-sig").replace("\r\n", "\n")
    path = tmp_path / "yesoncheck.iss"
    path.write_bytes(codecs.BOM_UTF8 + text.replace("\n", newline).encode("utf-8"))
    assert (b"\r\n" in path.read_bytes()) is (newline == "\r\n")
    monkeypatch.setattr(sys.modules[__name__], "ISS_PATH", str(path))
    test_installer_registry_matches_association_entries()
    test_installer_script_is_utf8_with_bom()
    assert len(_iss_registry()) == 14

    tiny = ['#define MyAppExeName "a.exe"', "", "[Registry]", "; 주석",
            'Root: HKCU; Subkey: "K\\{#MyAppExeName}"; ValueType: string; ValueName: ""; '
            'ValueData: """x"" ""%1"""; Flags: uninsdeletekey', "", "[Run]", 'Filename: "y"']
    path.write_bytes(codecs.BOM_UTF8 + newline.join(tiny).encode("utf-8") + newline.encode("ascii"))
    assert _iss_registry() == [{"Root": "HKCU", "Subkey": "K\\a.exe", "ValueType": "string", "ValueName": "",
                                "ValueData": '"x" "%1"', "Flags": "uninsdeletekey"}]


# ---- 설치 파일이 실제로 쓴 레지스트리 (CI — Windows, 무음 설치·제거 바로 뒤) ----


def _read_hkcu(key_path, name):
    """HKCU의 (값, 형), 키나 값이 없으면 None."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_QUERY_VALUE) as key:
            return winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None


def _hkcu_key_exists(key_path):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_QUERY_VALUE):
            return True
    except FileNotFoundError:
        return False


@pytest.mark.skipif(not INSTALLED_EXE, reason="CI의 설치 파일 시험 단계에서만 (YC_INSTALLED_EXE — 무음 설치 바로 뒤)")
def test_installer_registers_open_with():
    """무음 설치가 이 사용자(HKCU)에 association_entries를 모두 썼는지 다시 읽어 확인 (ProgID의 한글 이름 — .iss가 UTF-8로
    읽혔는지 — 과 RegisteredApplications\\YesonCheck 포함)."""
    assert sys.platform == "win32", "YC_INSTALLED_EXE는 Windows CI에서만 줌"
    import winreg

    problems = []
    for key, name, value in file_associations.association_entries(INSTALLED_EXE):
        found = _read_hkcu(key, name)
        print(f"HKCU\\{key} [{name or '(기본값)'}] = {found!r}")
        if found != (value, winreg.REG_SZ):
            problems.append(f"HKCU\\{key} [{name or '(기본값)'}]: {found!r} (기대 {value!r}, REG_SZ)")
    assert not problems, "\n".join(problems)


@pytest.mark.skipif(not UNINSTALLED_EXE, reason="CI의 설치 파일 시험 단계에서만 (YC_UNINSTALLED_EXE — 무음 제거 바로 뒤)")
def test_uninstaller_removes_open_with():
    """무음 제거가 우리 키는 통째로(OWNED_KEYS), 함께 쓰는 키에서는 우리 값만 지웠는지. 제거 프로그램은 임시 폴더의 사본이
    마저 지우므로 잠깐(최대 60초) 기다리며 확인."""
    assert sys.platform == "win32", "YC_UNINSTALLED_EXE는 Windows CI에서만 줌"
    owned = file_associations.OWNED_KEYS

    def left():
        found = [f"HKCU\\{key} (키)" for key in owned if _hkcu_key_exists(key)]
        for key, name, _ in file_associations.association_entries(UNINSTALLED_EXE):
            if any(key == top or key.startswith(top + "\\") for top in owned):
                continue
            value = _read_hkcu(key, name)
            if value is not None:
                found.append(f"HKCU\\{key} [{name}] = {value!r}")
        return found

    deadline = time.monotonic() + 60
    while left() and time.monotonic() < deadline:
        time.sleep(2)
    assert not left(), "제거 뒤에도 남은 등록:\n" + "\n".join(left())
