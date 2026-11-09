"""소리 진단 기록 (사용자 보고 2026-11-09 — Windows 11에서 소리가 나오지 않음, Windows 10은 정상).

그때까지 기록에 남는 것이 없었음: ① 빌드 앱은 파이썬의 stdout·stderr만 기록 파일로 보내 Qt(C++)의 경고 — 소리 백엔드(DirectShow·WMF)가
'파일을 열지 못함'을 알리는 길 — 는 콘솔 없는 Windows 앱에서 어디에도 안 남음 ② QMediaPlayer의 오류·상태 신호를 아무도 받지 않음.
원인을 짐작해 고치기 전에(systematic debugging 1단계) 기록부터: ① Qt 메시지를 기록 파일로(qt_messages) ② 재생기의 출력 장치·상태·오류
(media_player_log).
"""

import io
import sys

import pytest
from PyQt5.QtCore import QtMsgType, qInstallMessageHandler, qWarning
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer

from tests.test_app_logging import _read, frozen_env  # noqa: F401 (픽스처)
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: 픽스처)
from yesoncheck import app, media_player_log, qt_messages


@pytest.fixture
def restore_qt_handler():
    yield
    qInstallMessageHandler(None)  # 시험 뒤 Qt 기본 처리기로


# ---------------------------------------------------------------- Qt 메시지 → 기록


def test_qt_message_line_format():
    assert qt_messages.qt_message_line(QtMsgType.QtWarningMsg, "DirectShowPlayerService::doRender: Unresolved error code 0x80040266") == \
        "[Qt 경고] DirectShowPlayerService::doRender: Unresolved error code 0x80040266"
    assert qt_messages.qt_message_line(QtMsgType.QtCriticalMsg, "x").startswith("[Qt 심각] ")


def test_handler_writes_qt_warnings_to_stderr(restore_qt_handler, monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    qt_messages.install()
    qWarning(b"mediaservice: no plugin")
    assert "[Qt 경고] mediaservice: no plugin" in stream.getvalue()


def test_frozen_app_logs_qt_warnings_to_the_log_file(frozen_env, restore_qt_handler):  # noqa: F811
    """빌드 앱의 기록 파일에 Qt 경고가 남음 — 예전에는 콘솔 없는 Windows 앱에서 사라졌음."""
    log_path = app.setup_app_logging("win32")
    qWarning(b"DirectShowPlayerService::doRender: Unresolved error code 0x80040266")
    assert "[Qt 경고] DirectShowPlayerService::doRender: Unresolved error code 0x80040266" in _read(log_path)


def test_handler_never_raises(restore_qt_handler, monkeypatch):
    """기록에 쓰다 실패해도 Qt 콜백 밖으로 예외를 내지 않음 (원래 stderr에 한 번)."""
    class Broken:
        def write(self, text):
            raise OSError(28, "No space left on device")

        def flush(self):
            pass

    original = io.StringIO()
    monkeypatch.setattr(sys, "stderr", Broken())
    monkeypatch.setattr(sys, "__stderr__", original)
    qt_messages.install()
    qWarning(b"boom")
    assert "boom" in original.getvalue() and "No space left on device" in original.getvalue()


# ---------------------------------------------------------------- 재생기 상태·오류


def test_attach_logs_output_devices(qapp, capsys):
    player = QMediaPlayer()
    media_player_log.attach(player)
    out = capsys.readouterr().out
    assert out.startswith("[소리] 출력 장치: ")
    assert "기본 " in out and "재생기 " in out and "재생 가능성 mov " in out and "QT_MULTIMEDIA_PREFERRED_PLUGINS=" in out


def test_status_and_error_lines(qapp, capsys, tmp_path):
    player = QMediaPlayer()
    media_player_log.attach(player)
    player.setMedia(QMediaContent())  # 이름 없는 상태에서도 줄이 깨지지 않음
    capsys.readouterr()
    player.mediaStatusChanged.emit(QMediaPlayer.InvalidMedia)
    player.error[QMediaPlayer.Error].emit(QMediaPlayer.FormatError)
    player.audioAvailableChanged.emit(False)
    out = capsys.readouterr().out.splitlines()
    assert any(line.startswith("[소리] 상태: 열 수 없음(InvalidMedia)") for line in out), out
    assert any(line.startswith("[소리] 재생기 오류: 형식(FormatError)") for line in out), out
    assert any(line.startswith("[소리] 소리 트랙: 없음") for line in out), out


def test_player_property_attaches_the_log(new_player_with_log, capsys):
    """창의 재생기(mediaPlayer 속성 — 처음 쓸 때 만듦)에 진단 기록이 붙음."""
    player = new_player_with_log
    capsys.readouterr()
    _ = player.mediaPlayer
    assert "[소리] 출력 장치: " in capsys.readouterr().out


@pytest.fixture
def new_player_with_log(new_player, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))
