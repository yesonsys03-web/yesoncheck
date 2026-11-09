"""소리 재생기(QMediaPlayer)의 진단 기록 (2026-11-09 — Windows 11에서 소리가 나오지 않는다는 보고, Windows 10은 정상).

그때까지 재생기의 오류·상태 신호를 아무도 받지 않아, 소리가 안 나와도 기록에 아무것도 없었음. attach(player)가 만들 때 한 번 출력 장치
(기본 장치·전체 목록)와 재생기를 쓸 수 있는지, 그 뒤로 파일마다 상태(여는 중·열림·열 수 없음…)·소리 트랙 유무·오류(종류와 errorString)를
`[소리] …` 줄로 남김. 신호는 재생기의 자식 객체가 받음 — 슬롯이 재생기를 붙잡지 않고 재생기와 함께 사라짐(순환 참조 없음).
"""

import os
import sys
import traceback

from PyQt5.QtCore import QCoreApplication, QObject
from PyQt5.QtMultimedia import QAudio, QAudioDeviceInfo, QMediaPlayer, QMultimedia

STATUS = {
    QMediaPlayer.UnknownMediaStatus: "알 수 없음(UnknownMediaStatus)",
    QMediaPlayer.NoMedia: "없음(NoMedia)",
    QMediaPlayer.LoadingMedia: "여는 중(LoadingMedia)",
    QMediaPlayer.LoadedMedia: "열림(LoadedMedia)",
    QMediaPlayer.StalledMedia: "멈춤(StalledMedia)",
    QMediaPlayer.BufferingMedia: "버퍼링(BufferingMedia)",
    QMediaPlayer.BufferedMedia: "준비됨(BufferedMedia)",
    QMediaPlayer.EndOfMedia: "끝(EndOfMedia)",
    QMediaPlayer.InvalidMedia: "열 수 없음(InvalidMedia)",
}
ERRORS = {
    QMediaPlayer.NoError: "없음(NoError)",
    QMediaPlayer.ResourceError: "자원(ResourceError)",
    QMediaPlayer.FormatError: "형식(FormatError)",
    QMediaPlayer.NetworkError: "네트워크(NetworkError)",
    QMediaPlayer.AccessDeniedError: "권한(AccessDeniedError)",
    QMediaPlayer.ServiceMissingError: "서비스 없음(ServiceMissingError)",
}
SUPPORT = {
    QMultimedia.NotSupported: "안 됨",
    QMultimedia.MaybeSupported: "아마",
    QMultimedia.ProbablySupported: "될 것",
    QMultimedia.PreferredService: "선호",
}
PLUGIN_ENV = "QT_MULTIMEDIA_PREFERRED_PLUGINS"  # Windows에서 소리 백엔드(directshow·windowsmediafoundation)를 고르는 Qt 환경 변수
# (Windows) Qt 소리 백엔드 DLL — 어느 쪽을 불러왔는지로 실제 백엔드를 봄 (K-Lite가 깔린 PC에서는 환경 변수가 안 먹어도 DirectShow로 소리가
# 나므로 소리만으로는 가를 수 없음)
WINDOWS_BACKENDS = (("dsengine.dll", "DirectShow"), ("wmfengine.dll", "Media Foundation"))
AVAILABILITY = {
    QMultimedia.Available: "쓸 수 있음",
    QMultimedia.ServiceMissing: "서비스 없음",
    QMultimedia.Busy: "사용 중",
    QMultimedia.ResourceError: "자원 오류",
}


def windows_backends(get_module=None):
    """(Windows) 지금 이 프로세스에 불러온 Qt 소리 백엔드 → ['DirectShow(dsengine.dll)', 'Media Foundation(wmfengine.dll)'] 중 불러온 것(차례대로).
    get_module: 이름 → 모듈 손잡이(0이면 없음) — 기본은 kernel32 GetModuleHandleW. 둘 다면 둘 다(Qt가 플러그인 정보를 읽느라 불렀을 수 있음)."""
    if get_module is None:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        get_module = kernel32.GetModuleHandleW
    return [f"{label}({dll})" for dll, label in WINDOWS_BACKENDS if get_module(dll)]


def plugin_files(paths=None):
    """Qt 플러그인 폴더들(paths — 기본은 QCoreApplication.libraryPaths())의 mediaservice 아래 파일 이름 (정렬) — 앱에 든 소리 백엔드."""
    names = set()
    for folder in QCoreApplication.libraryPaths() if paths is None else paths:
        service = os.path.join(folder, "mediaservice")
        if os.path.isdir(service):
            names.update(os.listdir(service))
    return sorted(names)


def _backend_text():
    """(Windows) 출력 장치 줄에 붙일 '백엔드 …·플러그인 [...]' — 알아내다 실패해도(진단일 뿐) 재생기는 그대로: 트레이스백을 남기고 '알 수 없음'."""
    try:
        loaded = windows_backends()
        backend = ", ".join(loaded) if loaded else "아직 없음"
    except Exception as exc:
        traceback.print_exc()
        backend = f"알 수 없음({type(exc).__name__}: {exc})"
    try:
        files = f"[{', '.join(plugin_files())}]"
    except Exception as exc:
        traceback.print_exc()
        files = f"알 수 없음({type(exc).__name__}: {exc})"
    return f" · 백엔드 {backend} · 플러그인 {files}"


class _PlayerLog(QObject):
    """재생기의 자식 — 상태·소리 트랙·오류 신호를 받아 한 줄씩."""

    def __init__(self, player):
        super().__init__(player)
        player.mediaStatusChanged.connect(self._status)
        player.audioAvailableChanged.connect(self._audio)
        player.error[QMediaPlayer.Error].connect(self._error)

    def _name(self):
        return self.parent().media().canonicalUrl().fileName() or "(파일 없음)"

    def _status(self, status):
        print(f"[소리] 상태: {STATUS.get(status, status)} — {self._name()}", flush=True)

    def _audio(self, available):
        print(f"[소리] 소리 트랙: {'있음' if available else '없음'} — {self._name()}", flush=True)

    def _error(self, error):
        print(f"[소리] 재생기 오류: {ERRORS.get(error, error)}: {self.parent().errorString()} — {self._name()}", flush=True)


def attach(player):
    """재생기에 진단 기록을 붙임 — 지금 출력 장치·재생기 상태·Qt가 보는 mov/mp4 재생 가능성(hasSupport)·백엔드 고르기 환경 변수를 한 줄 남기고,
    그 뒤 신호마다 한 줄. → 붙인 객체(재생기의 자식)."""
    default = QAudioDeviceInfo.defaultOutputDevice().deviceName() or "(없음)"
    names = [device.deviceName() for device in QAudioDeviceInfo.availableDevices(QAudio.AudioOutput)]
    availability = AVAILABILITY.get(player.availability(), player.availability())
    support = " · ".join(f"{label} {SUPPORT.get(QMediaPlayer.hasSupport(mime), QMediaPlayer.hasSupport(mime))}"
                         for label, mime in (("mov", "video/quicktime"), ("mp4", "video/mp4")))
    backend = _backend_text() if sys.platform == "win32" else ""
    print(f"[소리] 출력 장치: 기본 {default} · 모두 {len(names)}개 {names} · 재생기 {availability} · 재생 가능성 {support} · "
          f"{PLUGIN_ENV}={os.environ.get(PLUGIN_ENV) or '(없음)'}{backend}", flush=True)
    return _PlayerLog(player)
