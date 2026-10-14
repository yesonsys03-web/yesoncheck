"""Windows 버그 회귀 시험: OCR '선택 구간 분석'의 두 번째 입력 창('종료 프레임')에 글자가 안 들어가던 문제.

원인 (player_base.py): changeEvent가 메인 창이 활성화될 때(QEvent.ActivationChange) QTimer.singleShot(100,
self.force_focus)를 걸어 둔다. '시작 프레임' 창(QInputDialog.getInt)이 닫히면 메인 창이 다시 활성 → 타이머 예약 →
곧바로 '종료 프레임' 창이 열림 → 100ms 뒤 force_focus()의 activateWindow()가 모달 창의 이벤트 루프 안에서 실행돼
메인 창을 활성으로 만들고 키보드 포커스를 빼앗는다 (키는 모달에 막힌 메인 창으로 가서 아무것도 입력되지 않음).
macOS는 모달 창을 키 창으로 유지해서 가려졌다. offscreen 플랫폼(Mac·Windows CI)에서도 activateWindow()가
모달 창이 떠 있는데 메인 창을 활성으로 만들어 그대로 재현된다.

고치는 방법: force_focus()가 실행되는 그 순간에 모달·팝업이 떠 있거나 이 앱의 다른 창이 활성이면 아무것도 안 함.
그 밖에는 예전처럼 (창 상태 변경·V 키·오버레이 위치 리셋 뒤 단축키가 먹도록 메인 창에 포커스).
"""

import time

import pytest
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication, QDialog, QInputDialog, QLineEdit, QVBoxLayout, QWidget

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)


def _pump(ms):
    """ms 동안 이벤트 처리 (QTimer.singleShot 타이머가 실행될 수 있게)."""
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def _wait_until(condition, what, ms=1000):
    deadline = time.monotonic() + ms / 1000
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"{ms}ms 안에 되지 않음: {what}")
        QApplication.processEvents()
        time.sleep(0.01)


@pytest.fixture
def windows_to_close():
    """시험에서 띄운 창(모달 포함)을 실패해도 닫음 — 모달 창이 남으면 다음 시험의 activeModalWidget()이 오염됨."""
    windows = []
    yield windows
    for window in windows:
        window.close()
        window.deleteLater()
    QApplication.processEvents()


@pytest.fixture
def shown_player(new_player, dialogs, tmp_path):
    player = new_player(make_config(str(tmp_path), {}))
    player.show()
    _pump(300)  # show()가 거는 100ms force_focus·200ms 사이드바 폭 타이머가 다 지나가도록
    assert QApplication.activeWindow() is player
    return player


def _record_focus_calls(player, monkeypatch):
    """player.setFocus / activateWindow 호출을 기록. 실제 동작도 그대로 실행 — 포커스를 정말 빼앗는지까지 확인."""
    calls = []
    for name in ("setFocus", "activateWindow"):
        original = getattr(player, name)

        def recorder(*args, _name=name, _original=original):
            calls.append(_name)
            return _original(*args)

        monkeypatch.setattr(player, name, recorder)
    return calls


def _show_modal_dialog(parent, windows):
    dialog = QDialog(parent)
    dialog.setModal(True)
    line_edit = QLineEdit(dialog)
    QVBoxLayout(dialog).addWidget(line_edit)
    windows.append(dialog)
    dialog.show()
    _wait_until(lambda: QApplication.activeWindow() is dialog, "모달 창이 활성")
    _wait_until(lambda: QApplication.focusWidget() is line_edit, "모달 창의 입력칸에 포커스")
    return dialog, line_edit


def test_force_focus_leaves_modal_dialog_alone(shown_player, monkeypatch, windows_to_close):
    dialog, line_edit = _show_modal_dialog(shown_player, windows_to_close)
    assert QApplication.activeModalWidget() is dialog
    calls = _record_focus_calls(shown_player, monkeypatch)

    shown_player.force_focus()
    _pump(50)

    assert calls == []
    assert QApplication.activeWindow() is dialog
    assert QApplication.focusWidget() is line_edit


def test_force_focus_leaves_other_active_window_alone(shown_player, monkeypatch, windows_to_close):
    """모달이 아니어도 이 앱의 다른 창(예: OCR 결과 창)이 활성이면 그 창의 포커스를 빼앗지 않음."""
    other = QWidget()
    windows_to_close.append(other)
    other.show()
    other.activateWindow()
    _wait_until(lambda: QApplication.activeWindow() is other, "다른 창이 활성")
    assert QApplication.activeModalWidget() is None
    calls = _record_focus_calls(shown_player, monkeypatch)

    shown_player.force_focus()
    _pump(50)

    assert calls == []
    assert QApplication.activeWindow() is other


def test_force_focus_still_focuses_active_player(shown_player, monkeypatch):
    """원래 목적은 그대로: 모달·다른 창이 없고 메인 창이 활성이면 메인 창에 포커스 (단축키가 먹도록)."""
    calls = _record_focus_calls(shown_player, monkeypatch)

    shown_player.force_focus()

    assert calls == ["setFocus", "activateWindow"]


def test_force_focus_without_active_window(new_player, dialogs, tmp_path, monkeypatch):
    """이 앱에 활성 창이 없으면(다른 앱이 앞에 있음 — offscreen에서는 아무 창도 안 보인 상태) 예전처럼 활성화 시도."""
    player = new_player(make_config(str(tmp_path), {}))
    QApplication.processEvents()
    assert QApplication.activeWindow() is None
    calls = _record_focus_calls(player, monkeypatch)

    player.force_focus()

    assert calls == ["setFocus", "activateWindow"]


def test_end_frame_dialog_keeps_focus(shown_player, monkeypatch, windows_to_close):
    """실제 흐름 재현: '시작 프레임' 창이 닫혀 메인 창이 다시 활성(ActivationChange → 100ms 뒤 force_focus 예약)
    → 바로 '종료 프레임' 창이 열림 → 타이머가 실행돼도 '종료 프레임' 창이 활성이고 입력칸에 포커스가 남아야 함."""
    force_focus_runs = []
    original_force_focus = shown_player.force_focus

    def counting_force_focus():
        force_focus_runs.append(QApplication.activeModalWidget())
        original_force_focus()

    monkeypatch.setattr(shown_player, "force_focus", counting_force_focus)  # changeEvent가 거는 타이머도 이걸 부름
    calls = _record_focus_calls(shown_player, monkeypatch)

    start_dialog = QInputDialog(shown_player)
    start_dialog.setInputMode(QInputDialog.IntInput)
    start_dialog.setWindowTitle("시작 프레임")
    start_dialog.setModal(True)
    windows_to_close.append(start_dialog)
    start_dialog.show()
    _wait_until(lambda: QApplication.activeWindow() is start_dialog, "'시작 프레임' 창이 활성")

    start_dialog.accept()
    # 모달 창이 닫히면 Windows는 주인 창(메인 창)을 다시 활성화한다. offscreen 플랫폼은 이걸 하지 않으므로 OS가 하는
    # 일을 직접: 기록용 대체 함수가 아니라 원래 QWidget.activateWindow로 → 진짜 ActivationChange가 와서
    # changeEvent가 100ms 뒤 force_focus를 예약한다.
    QWidget.activateWindow(shown_player)
    _wait_until(lambda: QApplication.activeWindow() is shown_player, "'시작 프레임' 창이 닫힌 뒤 메인 창이 활성")

    end_dialog = QInputDialog(shown_player)
    end_dialog.setInputMode(QInputDialog.IntInput)
    end_dialog.setWindowTitle("종료 프레임")
    end_dialog.setModal(True)
    windows_to_close.append(end_dialog)
    end_dialog.show()
    _wait_until(lambda: QApplication.activeWindow() is end_dialog, "'종료 프레임' 창이 활성")
    end_input = QApplication.focusWidget()
    assert end_input is not None and end_dialog.isAncestorOf(end_input)

    _pump(300)  # 100ms 타이머가 확실히 실행되도록

    assert end_dialog in force_focus_runs  # 시험이 헛돌지 않음: 모달 창이 떠 있는 동안 예약된 force_focus가 실제로 실행됨
    assert calls == []
    assert QApplication.activeWindow() is end_dialog
    assert QApplication.focusWidget() is end_input


def test_activation_change_still_schedules_focus(shown_player, monkeypatch):
    """메인 창이 활성인 채 ActivationChange가 오면 예전처럼 100ms 뒤 메인 창에 포커스."""
    calls = _record_focus_calls(shown_player, monkeypatch)

    shown_player.changeEvent(QEvent(QEvent.ActivationChange))
    _pump(300)

    assert calls[:2] == ["setFocus", "activateWindow"]
