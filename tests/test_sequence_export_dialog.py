"""Seq 목록의 오른쪽 클릭 메뉴와 시퀀스 → mov 일괄 내보내기 창 (SidebarSequencesMixin.show_seq_context_menu·export_selected_sequences).

대부분의 시험은 신호만 흉내 내는 FakeWorker로 창의 흐름을 봄 (실제 인코딩은 test_sequence_export.py가 이미 시험함). 끝에서 끝까지 한 번은
진짜 워커로 작은 시퀀스를 mov로 만들어 창이 '완료'에 닿는지 봄. 실제 QMessageBox·QFileDialog·QMenu는 띄우지 않음 (conftest의 dialogs가
메시지 창·폴더 선택을 가로채고, 메뉴는 QMenu.exec_를 바꿔 치기). 예시 이름만 씀 (공개 저장소).
"""

import os
import shutil
import time

import pytest
from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMenu

from tests.test_sequence_capture import make_movie, make_seq
from tests.test_sequence_export import hold_at
from tests.test_thumbnails import wait_until
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import sidebar_sequences
from yesoncheck.player_base import VideoPlayerBase
from yesoncheck.sequence_export_worker import SequenceExportWorker
from yesoncheck.sequence_scan import group_sequences
from yesoncheck.sidebar_sequences import SequenceExportDialog

MENU_TEXTS = ["비디오 A로 열기", "비디오 B로 열기", "선택한 시퀀스로 MOV 만들기…", "썸네일 다시 만들기", "정보 보기"]
JOB_LABEL = "시퀀스 MOV 만들기"


class FakeWorker(QThread):
    """SequenceExportWorker와 같은 신호·메서드 모양 — 스레드를 돌리지 않고 시험이 신호를 직접 냄."""

    item_started = pyqtSignal(int, str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, items, out_dir, ffmpeg):
        super().__init__()
        self.items = list(items)
        self.out_dir = out_dir
        self.ffmpeg = ffmpeg
        self.running = False
        self.stops = 0
        self.waits = []
        self.cancelled = False
        self.failures = []

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def stop(self):
        self.stops += 1
        self.cancelled = True

    def wait(self, timeout=None):
        """GUI 스레드가 부르면 막힘 — 창 닫기(stop_running_jobs)만 부름. 부른 기록을 남기고 스레드가 끝난 것으로 함."""
        self.waits.append(timeout)
        self.running = False
        return True

    def end_thread(self):
        """stop() 뒤 정리(ffmpeg 끝내기·부분 출력 지우기)를 마치고 스레드가 끝남."""
        self.running = False


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    window = new_player(make_config(str(tmp_path), {}))
    window.require_ffmpeg = lambda: "ffmpeg-for-test"
    return window


@pytest.fixture
def workers(monkeypatch):
    """내보내기 워커를 FakeWorker로 바꿔 치기 → 만들어진 워커 목록."""
    created = []

    def make(items, out_dir, ffmpeg):
        worker = FakeWorker(items, out_dir, ffmpeg)
        created.append(worker)
        return worker

    monkeypatch.setattr(sidebar_sequences, "SequenceExportWorker", make)
    return created


@pytest.fixture
def menus(monkeypatch):
    """QMenu.exec_를 가로챔 → 뜬 메뉴들의 글자 [ [..], ..]. pick에 글자를 넣어 두면 그 항목을 누른 것으로 함."""
    shown = []
    pick = []

    def fake_exec(self, *args):
        shown.append([a.text() for a in self.actions() if not a.isSeparator()])
        for text in pick:
            next(a for a in self.actions() if a.text() == text).trigger()
        return None

    monkeypatch.setattr(QMenu, "exec_", fake_exec)
    return type("Menus", (), {"shown": shown, "pick": pick})


def folder_with(tmp_path, name="src", bases=("EX01_tk1", "EX01_tk2", "EX01_tk3")):
    """bases마다 프레임 1~4장이 든 시퀀스 폴더."""
    folder = tmp_path / name
    for base in bases:
        make_seq(str(folder), base, range(1, 5))
    return folder


def fill_list(player, folder):
    seqs = group_sequences(str(folder), sorted(os.listdir(folder)))
    player._set_seq_items(seqs)
    return seqs


def select_rows(player, *rows):
    player.seq_sidebar.clearSelection()
    for row in rows:
        player.seq_sidebar.item(row).setSelected(True)


def item_pos(player, row):
    player.show()
    QApplication.processEvents()
    return player.seq_sidebar.visualItemRect(player.seq_sidebar.item(row)).center()


def current_dialog(player):
    return player.seq_export_dialog


def settle(player):
    """시험 끝: 열린 비모달 진행 창이 다른 시험의 최상위 창 목록에 남지 않게 숨김 (워커는 시험이 끝나며 창 닫기가 정리)."""
    dialog = player.seq_export_dialog
    if dialog is not None:
        dialog.hide()  # close()는 작업 중이면 무시되므로 hide


# ---------------------------------------------------------------- 메뉴


def test_seq_list_is_multi_select_like_the_mov_list(player):
    assert player.seq_sidebar.selectionMode() == player.sidebar.selectionMode()
    assert player.seq_sidebar.selectionMode() != player.seq_sidebar.SingleSelection


def test_context_menu_actions_for_seq_items(player, tmp_path, menus):
    """Seq 항목의 메뉴는 정해진 다섯 개뿐 (mov 전용 합치기·OCR류·복사 없음)."""
    fill_list(player, folder_with(tmp_path))
    player.show_seq_context_menu(item_pos(player, 1))

    assert menus.shown == [MENU_TEXTS]


def test_context_menu_is_wired_to_the_seq_list_only(player, tmp_path, menus):
    fill_list(player, folder_with(tmp_path))
    assert player.seq_sidebar.contextMenuPolicy() == Qt.CustomContextMenu

    player.seq_sidebar.customContextMenuRequested.emit(item_pos(player, 0))  # 연결을 거쳐

    assert menus.shown == [MENU_TEXTS]


def test_context_menu_on_empty_area_shows_nothing(player, tmp_path, menus):
    fill_list(player, folder_with(tmp_path))
    below = item_pos(player, 2)
    below.setY(player.seq_sidebar.viewport().height() - 1)
    assert player.seq_sidebar.itemAt(below) is None

    player.show_seq_context_menu(below)

    assert menus.shown == []


def test_context_menu_open_in_a_and_b_use_the_clicked_sequence(player, tmp_path, menus, monkeypatch):
    seqs = fill_list(player, folder_with(tmp_path))
    opened = []
    monkeypatch.setattr(player, "open_file", lambda video_type, path=None: opened.append((video_type, path)))

    menus.pick[:] = ["비디오 A로 열기"]
    player.show_seq_context_menu(item_pos(player, 1))
    menus.pick[:] = ["비디오 B로 열기"]
    player.show_seq_context_menu(item_pos(player, 2))

    assert opened == [("A", seqs[1].identity), ("B", seqs[2].identity)]


def test_context_menu_holds_the_list_refresh_while_open(player, tmp_path, monkeypatch):
    """메뉴가 떠 있는 동안 목록 다시 읽기는 미룸 (Mov 목록 메뉴와 같음) — 끝나면 풀림."""
    fill_list(player, folder_with(tmp_path))
    holds = []
    monkeypatch.setattr(QMenu, "exec_", lambda self, *a: holds.append(player._sidebar_refresh_holds))

    player.show_seq_context_menu(item_pos(player, 0))

    assert holds == [1] and player._sidebar_refresh_holds == 0


def test_context_menu_on_unselected_item_selects_only_it(player, tmp_path, menus):
    """선택 밖의 항목에서 메뉴를 열면 그 항목만 선택 (메뉴의 일은 눌린 항목에 대한 것)."""
    fill_list(player, folder_with(tmp_path))
    select_rows(player, 0, 1)

    player.show_seq_context_menu(item_pos(player, 2))

    assert [i.data(Qt.UserRole).base for i in player.seq_sidebar.selectedItems()] == ["EX01_tk3"]


def test_context_menu_on_selected_item_keeps_the_whole_selection(player, tmp_path, menus):
    fill_list(player, folder_with(tmp_path))
    select_rows(player, 0, 1)

    player.show_seq_context_menu(item_pos(player, 1))

    assert sorted(i.data(Qt.UserRole).base for i in player.seq_sidebar.selectedItems()) == ["EX01_tk1", "EX01_tk2"]


def test_context_menu_make_mov_starts_the_export_for_the_selection(player, tmp_path, menus, workers, dialogs):
    fill_list(player, folder_with(tmp_path))
    select_rows(player, 0, 2)
    out = tmp_path / "out"
    out.mkdir()
    dialogs.folders.append(str(out))
    menus.pick[:] = ["선택한 시퀀스로 MOV 만들기…"]

    player.show_seq_context_menu(item_pos(player, 2))

    assert [seq.base for seq in workers[0].items] == ["EX01_tk1", "EX01_tk3"]
    settle(player)


def test_context_menu_regenerate_uses_the_selected_items(player, tmp_path, menus, monkeypatch):
    fill_list(player, folder_with(tmp_path))
    select_rows(player, 1, 2)
    regenerated = []
    monkeypatch.setattr(player, "regenerate_seq_thumbnails", lambda items: regenerated.append(list(items)))
    menus.pick[:] = ["썸네일 다시 만들기"]

    player.show_seq_context_menu(item_pos(player, 1))

    assert [[i.data(Qt.UserRole).base for i in group] for group in regenerated] == [["EX01_tk2", "EX01_tk3"]]


def test_context_menu_info_shows_the_clicked_sequence(player, tmp_path, menus, monkeypatch):
    seqs = fill_list(player, folder_with(tmp_path))
    shown = []
    monkeypatch.setattr(player, "show_seq_info", lambda item: shown.append(item.data(Qt.UserRole)))
    menus.pick[:] = ["정보 보기"]

    player.show_seq_context_menu(item_pos(player, 2))

    assert shown == [seqs[2]]


# ---------------------------------------------------------------- 정보 보기


def test_info_dialog_shows_range_and_missing(player, tmp_path, dialogs):
    """범위·개수·빠짐·fps·해상도 — 빠진 프레임이 있는 시퀀스 (짝 영상 있음: fps는 짝 영상의 것)."""
    folder = tmp_path / "info"
    make_seq(str(folder), "EX01_tk2", [1, 2, 3, 5, 6])
    make_movie(str(folder / "EX01_tk2.mov"), 30)
    fill_list(player, folder)

    player.show_seq_info(player.seq_sidebar.item(0))

    box = dialogs.boxes[-1]
    for expected in ("EX01_tk2", "0001–0006", "5프레임", "빠짐: 1프레임", "30.00 fps", "64 x 48", str(folder)):
        assert expected in box.text, expected
    assert box.details == ""  # 오류 없음


def test_info_dialog_without_missing_frames_and_paired_movie(player, tmp_path, dialogs):
    folder = folder_with(tmp_path, "info2", bases=("EX01_tk1",))
    fill_list(player, folder)

    player.show_seq_info(player.seq_sidebar.item(0))

    text = dialogs.boxes[-1].text
    assert "0001–0004" in text and "4프레임" in text and "빠짐: 없음" in text
    assert "24.00 fps" in text and "짝 영상 없음" in text


def test_info_dialog_is_loud_when_the_sequence_cannot_be_read(player, tmp_path, dialogs, capsys):
    """폴더가 사라진 시퀀스: 알고 있는 범위는 보이고, 읽지 못한 이유는 스택 트레이스째 (조용히 비워 두지 않음)."""
    folder = folder_with(tmp_path, "gone", bases=("EX01_tk1",))
    fill_list(player, folder)
    shutil.rmtree(folder)

    player.show_seq_info(player.seq_sidebar.item(0))

    box = dialogs.boxes[-1]
    assert "0001–0004" in box.text and "읽지 못했습니다" in box.text
    assert "Traceback" in box.details and "FileNotFoundError" in box.details
    assert "Traceback" in capsys.readouterr().err


def test_info_dialog_releases_the_capture(player, tmp_path, dialogs, monkeypatch):
    """정보를 보려고 연 캡처는 곧바로 놓음 (선읽기 예산·메모리를 붙잡지 않음)."""
    fill_list(player, folder_with(tmp_path, "rel", bases=("EX01_tk1",)))
    opened = []
    real = sidebar_sequences.ImageSequenceCapture

    def spy(identity):
        cap = real(identity)
        opened.append(cap)
        return cap

    monkeypatch.setattr(sidebar_sequences, "ImageSequenceCapture", spy)

    player.show_seq_info(player.seq_sidebar.item(0))

    assert len(opened) == 1 and not opened[0].isOpened()


# ---------------------------------------------------------------- 폴더 고르기·시작


def test_export_rejects_source_dir_then_accepts(player, tmp_path, dialogs, workers):
    """원본 폴더를 고르면 경고하고 다시 고르게 함 — 올바른 폴더를 고르면 그 폴더로 워커를 시작."""
    src = folder_with(tmp_path)
    fill_list(player, src)
    select_rows(player, 0, 1)
    out = tmp_path / "out"
    out.mkdir()
    dialogs.folders.extend([str(src), str(out)])

    player.export_selected_sequences()

    assert len(dialogs.warnings) == 1 and str(src) in dialogs.warnings[0] and "원본 폴더" in dialogs.warnings[0]
    assert dialogs.folders == []  # 폴더 선택을 두 번 열었음
    assert len(workers) == 1 and workers[0].out_dir == str(out)
    assert [seq.base for seq in workers[0].items] == ["EX01_tk1", "EX01_tk2"]
    assert workers[0].running and player.seq_export_worker is workers[0]
    assert workers[0].ffmpeg == "ffmpeg-for-test"
    settle(player)


def test_export_picker_cancel_after_refusal_starts_nothing(player, tmp_path, dialogs, workers):
    src = folder_with(tmp_path)
    fill_list(player, src)
    select_rows(player, 0)
    dialogs.folders.extend([str(src), ""])  # 거부된 뒤 폴더 선택을 취소

    player.export_selected_sequences()

    assert len(dialogs.warnings) == 1
    assert workers == [] and player.seq_export_worker is None and player.seq_export_dialog is None


def test_export_picker_cancel_at_once_is_quiet(player, tmp_path, dialogs, workers):
    fill_list(player, folder_with(tmp_path))
    select_rows(player, 0)
    dialogs.folders.append("")

    player.export_selected_sequences()

    assert workers == [] and dialogs.messages == []


def test_export_refuses_when_any_item_is_in_the_chosen_folder(player, tmp_path, dialogs, workers):
    """여러 폴더의 시퀀스를 고른 경우: 그중 하나라도 원본 폴더면 거부."""
    first, second = folder_with(tmp_path, "a", ("EX01_tk1",)), folder_with(tmp_path, "b", ("EX02_tk1",))
    player._set_seq_items(group_sequences(str(first), sorted(os.listdir(first)))
                          + group_sequences(str(second), sorted(os.listdir(second))))
    select_rows(player, 0, 1)
    dialogs.folders.extend([str(second), ""])

    player.export_selected_sequences()

    assert len(dialogs.warnings) == 1 and str(second) in dialogs.warnings[0]
    assert workers == []


def test_export_without_selection_uses_the_current_item(player, tmp_path, dialogs, workers):
    seqs = fill_list(player, folder_with(tmp_path))
    player.seq_sidebar.clearSelection()
    player.seq_sidebar.setCurrentItem(player.seq_sidebar.item(1), player.seq_sidebar.selectionModel().NoUpdate)
    out = tmp_path / "out"
    out.mkdir()
    dialogs.folders.append(str(out))

    player.export_selected_sequences()

    assert [seq.base for seq in workers[0].items] == [seqs[1].base]
    settle(player)


def test_export_without_any_item_tells_the_user(player, dialogs, workers):
    player.export_selected_sequences()

    assert workers == [] and len(dialogs.messages) == 1 and dialogs.messages[0][1] == JOB_LABEL


def test_export_items_follow_the_list_order_not_the_click_order(player, tmp_path, dialogs, workers):
    fill_list(player, folder_with(tmp_path))
    out = tmp_path / "out"
    out.mkdir()
    dialogs.folders.append(str(out))
    for row in (2, 0, 1):  # 누른 순서
        player.seq_sidebar.item(row).setSelected(True)

    player.export_selected_sequences()

    assert [seq.base for seq in workers[0].items] == ["EX01_tk1", "EX01_tk2", "EX01_tk3"]
    settle(player)


def test_export_without_ffmpeg_starts_nothing(player, tmp_path, dialogs, workers):
    fill_list(player, folder_with(tmp_path))
    select_rows(player, 0)
    player.require_ffmpeg = lambda: None  # 안내 창은 require_ffmpeg가 이미 띄움
    dialogs.folders.append(str(tmp_path / "out"))

    player.export_selected_sequences()

    assert workers == [] and player.seq_export_dialog is None
    assert dialogs.folders == [str(tmp_path / "out")]  # 폴더를 고르게 하기 전에 알림


def start_export(player, tmp_path, dialogs, rows=(0, 1), out_name="out"):
    out = tmp_path / out_name
    out.mkdir(exist_ok=True)
    select_rows(player, *rows)
    dialogs.folders.append(str(out))
    player.export_selected_sequences()
    return player.seq_export_worker, current_dialog(player), out


# ---------------------------------------------------------------- 진행 창


def test_progress_dialog_is_non_modal_and_shows_progress(player, tmp_path, dialogs, workers):
    fill_list(player, folder_with(tmp_path))
    worker, dialog, out = start_export(player, tmp_path, dialogs, rows=(0, 1, 2))

    assert not dialog.isModal() and dialog.isVisible()
    assert str(out) in dialog.windowTitle() + dialog.out_label.text()
    assert dialog.items_label.text() == "0/3 항목"

    worker.item_started.emit(1, "EX01_tk2")
    worker.progress.emit(6, 12)
    dialog.flush_progress()

    assert dialog.items_label.text() == "2/3 항목" and "EX01_tk2" in dialog.current_label.text()
    assert (dialog.progress_bar.value(), dialog.progress_bar.maximum()) == (6, 12)
    assert "EX01_tk2" in dialog.log.toPlainText()
    assert dialog.state == "running" and dialog.cancel_button.isEnabled()
    settle(player)


def test_progress_updates_are_throttled(player, tmp_path, dialogs, workers, monkeypatch):
    """프레임마다 오는 진행 신호를 막대에 그대로 옮기지 않음 — 마지막 값은 곧 반영됨."""
    fill_list(player, folder_with(tmp_path))
    worker, dialog, _out = start_export(player, tmp_path, dialogs)
    sets = []
    real_set = dialog.progress_bar.setValue
    monkeypatch.setattr(dialog.progress_bar, "setValue", lambda v: (sets.append(v), real_set(v))[1])

    for done in range(1, 501):
        worker.progress.emit(done, 500)

    assert len(sets) < 50  # 신호 500개가 막대 갱신 500번이 되지 않음
    wait_until(lambda: dialog.progress_bar.value() == 500)  # 마지막 값은 타이머가 반영
    settle(player)


def test_progress_dialog_cancel_calls_worker_stop(player, tmp_path, dialogs, workers):
    """취소 단추는 워커 stop()에 연결되어 있고, 워커 스레드가 끝난 뒤에야 '취소됨'을 보임."""
    fill_list(player, folder_with(tmp_path))
    worker, dialog, _out = start_export(player, tmp_path, dialogs)
    worker.item_started.emit(0, "EX01_tk1")

    dialog.cancel_button.click()

    assert worker.stops == 1 and dialog.state == "cancelling" and "취소하는 중" in dialog.state_label.text()
    assert not dialog.cancel_button.isEnabled()
    worker.end_thread()  # ffmpeg를 끝내고 부분 출력을 지운 뒤 스레드가 끝남
    wait_until(lambda: dialog.state == "cancelled")
    assert worker.stops == 1 and "취소됨" in dialog.state_label.text() and "취소" in dialog.log.toPlainText()
    assert dialogs.messages == []  # 취소는 사용자의 뜻 — 오류 창 없음
    settle(player)


def test_cancel_does_not_block_the_gui_and_shows_cancelling_until_the_thread_ends(player, tmp_path, dialogs, workers):
    """취소는 GUI 스레드에서 워커를 기다리지 않음 (느린 정리에도 창이 얼지 않음): 바로 돌아와 '취소하는 중…'을 보이고,
    워커가 도는 동안은 이벤트를 몇 번 처리해도 '취소됨'이 되지 않으며, 끝나야 '취소됨'."""
    fill_list(player, folder_with(tmp_path))
    worker, dialog, _out = start_export(player, tmp_path, dialogs)

    started = time.monotonic()
    dialog.cancel_button.click()
    elapsed = time.monotonic() - started

    assert elapsed < 0.5 and worker.waits == []  # 기다리지 않음 (wait() 호출 자체가 없음)
    assert dialog.state == "cancelling" and "취소하는 중" in dialog.state_label.text()
    deadline = time.monotonic() + 0.5  # 확인 타이머가 여러 번 돌 시간
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert dialog.state == "cancelling" and worker.stops == 1  # 스레드가 도는 동안은 취소됨이 아님
    worker.end_thread()
    wait_until(lambda: dialog.state == "cancelled")
    assert worker.waits == []
    settle(player)


def test_enter_key_does_not_cancel_the_export(player, tmp_path, dialogs, workers):
    """Enter/Return은 '취소'를 누른 것이 아님 (닫으려는 흔한 몸짓이 긴 작업을 죽이지 않게): 창에서도 로그에 포커스가 있어도."""
    fill_list(player, folder_with(tmp_path))
    worker, dialog, _out = start_export(player, tmp_path, dialogs)
    requested = []
    dialog.cancel_requested.connect(lambda: requested.append(True))
    dialog.log.setFocus()

    for target in (dialog, dialog.log, dialog.cancel_button, dialog.close_button):
        for key in (Qt.Key_Return, Qt.Key_Enter):
            QTest.keyClick(target, key)
    QApplication.processEvents()

    assert requested == [] and worker.stops == 0 and dialog.state == "running" and dialog.cancel_button.isEnabled()
    assert dialog.isVisible()  # 닫기 단추도 Enter의 기본 단추가 아님
    settle(player)


def test_cancel_shows_failures_that_happened_before(player, tmp_path, dialogs, workers):
    fill_list(player, folder_with(tmp_path))
    worker, dialog, _out = start_export(player, tmp_path, dialogs)
    worker.failures.append(("EX01_tk1", "FFmpeg 오류 (종료 코드 1)"))

    dialog.cancel_button.click()
    worker.end_thread()
    wait_until(lambda: dialog.state == "cancelled")

    log = dialog.log.toPlainText()
    assert dialog.state == "cancelled" and "EX01_tk1" in log and "FFmpeg 오류 (종료 코드 1)" in log
    settle(player)


def test_late_finished_after_cancel_is_ignored(player, tmp_path, dialogs, workers):
    """취소한 뒤 아주 작은 틈에 finished·error가 늦게 와도 상태·창이 바뀌지 않음."""
    fill_list(player, folder_with(tmp_path))
    worker, dialog, _out = start_export(player, tmp_path, dialogs)
    dialog.cancel_button.click()
    worker.end_thread()
    wait_until(lambda: dialog.state == "cancelled")
    log_before = dialog.log.toPlainText()

    worker.finished.emit()
    worker.error.emit("1개 중 1개 실패\n[EX01_tk1] 가짜 오류")
    worker.progress.emit(3, 8)
    worker.item_started.emit(1, "EX01_tk2")
    dialog.flush_progress()

    assert dialog.state == "cancelled" and "취소됨" in dialog.state_label.text()
    assert dialog.log.toPlainText() == log_before and dialog.progress_bar.value() == 0
    assert dialogs.messages == []
    settle(player)


def test_finished_shows_success_state(player, tmp_path, dialogs, workers):
    fill_list(player, folder_with(tmp_path))
    worker, dialog, out = start_export(player, tmp_path, dialogs)
    worker.item_started.emit(0, "EX01_tk1")
    worker.item_started.emit(1, "EX01_tk2")
    worker.progress.emit(8, 8)

    worker.finished.emit()

    assert dialog.state == "finished" and "완료" in dialog.state_label.text()
    assert dialog.items_label.text() == "2/2 항목" and dialog.progress_bar.value() == 8
    assert str(out) in dialog.log.toPlainText()
    assert not dialog.cancel_button.isEnabled()
    assert dialogs.messages == []
    settle(player)


def test_error_summary_is_shown_loudly_and_dialog_stays(player, tmp_path, dialogs, workers, capsys):
    fill_list(player, folder_with(tmp_path))
    worker, dialog, _out = start_export(player, tmp_path, dialogs)
    summary = "2개 중 1개 실패\n[EX01_tk2] FFmpeg 오류 (종료 코드 1, 3/4프레임 보냄)\nstderr 끝부분"
    worker.running = False

    worker.error.emit(summary)

    assert dialog.state == "failed" and "실패" in dialog.state_label.text()
    assert dialog.isVisible() and summary in dialog.log.toPlainText()
    assert len(dialogs.criticals) == 1 and "[EX01_tk2]" in dialogs.criticals[0]  # 자세한 글에 요약 전체
    assert not dialog.cancel_button.isEnabled()
    assert "[EX01_tk2]" in capsys.readouterr().out
    settle(player)


def test_closing_the_dialog_keeps_the_job_running_and_it_comes_back(player, tmp_path, dialogs, workers):
    """창을 닫아도 작업은 멈추지 않고(취소 아님), 다시 시작하려 하면 같은 창이 앞으로 나오고, 끝나면 저절로 다시 나타남."""
    fill_list(player, folder_with(tmp_path))
    worker, dialog, _out = start_export(player, tmp_path, dialogs)

    dialog.close()

    assert not dialog.isVisible() and worker.stops == 0 and dialog.state == "running"
    player.export_selected_sequences()  # 이미 만드는 중 -> 안내하며 같은 창을 보임
    assert dialog.isVisible() and len(workers) == 1
    dialog.close_button.click()
    assert not dialog.isVisible() and worker.stops == 0
    worker.finished.emit()
    assert dialog.isVisible() and dialog.state == "finished"
    settle(player)


def test_error_brings_a_closed_dialog_back(player, tmp_path, dialogs, workers):
    fill_list(player, folder_with(tmp_path))
    worker, dialog, _out = start_export(player, tmp_path, dialogs)
    dialog.close()

    worker.error.emit("1개 중 1개 실패\n[EX01_tk1] 이유")

    assert dialog.isVisible() and dialog.state == "failed" and len(dialogs.criticals) == 1
    settle(player)


def test_second_export_while_running_does_not_replace_the_worker(player, tmp_path, dialogs, workers):
    fill_list(player, folder_with(tmp_path))
    worker, dialog, _out = start_export(player, tmp_path, dialogs)
    dialogs.folders.append(str(tmp_path / "other"))

    player.export_selected_sequences()

    assert len(workers) == 1 and player.seq_export_worker is worker and current_dialog(player) is dialog
    assert len(dialogs.messages) == 1 and "만드는 중" in dialogs.messages[0][2]
    assert dialogs.folders == [str(tmp_path / "other")]  # 폴더 선택도 열지 않음
    settle(player)


def test_fresh_worker_and_dialog_per_run(player, tmp_path, dialogs, workers):
    fill_list(player, folder_with(tmp_path))
    first, first_dialog, _out = start_export(player, tmp_path, dialogs)
    first_dialog.cancel_button.click()
    first.end_thread()
    assert first.stops == 1

    second, second_dialog, _out = start_export(player, tmp_path, dialogs, out_name="out2")

    assert second is not first and second_dialog is not first_dialog
    assert player.seq_export_worker is second and len(workers) == 2
    assert first.stops == 1 and second.stops == 0  # 멈춘 워커를 다시 쓰지 않음
    # 지난 실행의 늦은 신호가 새 창에 닿지 않음
    first.finished.emit()
    first.error.emit("지난 실행의 오류")
    assert second_dialog.state == "running" and dialogs.messages == []
    settle(player)


def test_export_after_finished_run_starts_a_new_one(player, tmp_path, dialogs, workers):
    fill_list(player, folder_with(tmp_path))
    first, first_dialog, _out = start_export(player, tmp_path, dialogs)
    first.running = False
    first.finished.emit()

    second, second_dialog, _out = start_export(player, tmp_path, dialogs, out_name="out2")

    assert second is not first and second_dialog is not first_dialog and not first_dialog.isVisible()
    # 끝난 지난 실행의 워커가 (취소 없이도) 새 실행의 창을 건드리지 못함
    first.error.emit("1개 중 1개 실패\n[EX01_tk1] 지난 실행의 오류")
    first.progress.emit(5, 8)
    first.item_started.emit(0, "EX01_tk1")
    second_dialog.flush_progress()
    assert second_dialog.state == "running" and second_dialog.progress_bar.value() == 0
    assert "지난 실행" not in second_dialog.log.toPlainText() and dialogs.messages == []
    settle(player)


# ---------------------------------------------------------------- 창 닫기 가드


def test_running_job_attr_blocks_close(player, tmp_path, dialogs, workers):
    """내보내는 동안 '실행 중인 작업'에 잡히고 (업데이트·닫기 가드), 창 닫기의 stop_running_jobs가 멈춘 뒤에는 창이 뜨지 않음."""
    fill_list(player, folder_with(tmp_path))
    worker, dialog, _out = start_export(player, tmp_path, dialogs)

    assert (JOB_LABEL, "seq_export_worker") in VideoPlayerBase.RUNNING_JOB_ATTRS
    assert player.running_jobs() == [(JOB_LABEL, worker)] and player.running_job_labels() == [JOB_LABEL]

    player.stop_running_jobs()  # 창 닫기가 부르는 진짜 길

    assert worker.stops == 1 and player.running_jobs() == []
    worker.error.emit("닫는 중의 오류")  # 신호는 막혀 있음 — 닫히는 중에 창이 뜨지 않음
    worker.finished.emit()
    assert dialog.state == "running" and dialogs.messages == []
    settle(player)


@pytest.fixture
def parked_real_worker(monkeypatch):
    """진짜 SequenceExportWorker인데 진행이 3장에 닿으면 stop()이 불릴 때까지 워커 스레드를 세워 둠 → (reached Event 목록)."""
    reached = []

    def make(items, out_dir, ffmpeg):
        worker = SequenceExportWorker(items, out_dir, ffmpeg)
        reached.append(hold_at(worker, out_dir, 3)[0])
        return worker

    monkeypatch.setattr(sidebar_sequences, "SequenceExportWorker", make)
    return reached


def start_real_export(player, tmp_path, dialogs, frames=60):
    src = tmp_path / "big"
    make_seq(str(src), "EX01_tk1", range(1, frames + 1))
    player._set_seq_items(group_sequences(str(src), sorted(os.listdir(src))))
    out = tmp_path / "out"
    out.mkdir()
    select_rows(player, 0)
    dialogs.folders.append(str(out))
    player.require_ffmpeg = VideoPlayerBase.require_ffmpeg.__get__(player)
    player.export_selected_sequences()
    return player.seq_export_worker, out


def test_real_worker_close_guard_stops_and_removes_partial(player, tmp_path, dialogs, parked_real_worker):
    """진짜 워커로: 내보내는 중 창 닫기 가드(진짜 stop_running_jobs)가 멈추고 부분 출력을 지움."""
    worker, out = start_real_export(player, tmp_path, dialogs)
    assert parked_real_worker[0].wait(60)  # 3장째에서 멈춰 있음 (ffmpeg가 파일을 만든 뒤)
    assert (JOB_LABEL, worker) in player.running_jobs()

    player.stop_running_jobs()

    assert not worker.isRunning() and os.listdir(out) == []
    assert dialogs.messages == []


def test_real_worker_cancel_button_removes_partial_and_ends_quietly(player, tmp_path, dialogs, parked_real_worker):
    """진짜 워커로: 취소 단추 -> 워커가 끝나고 부분 출력이 지워지고 창은 '취소됨', 오류 창은 없음."""
    worker, out = start_real_export(player, tmp_path, dialogs)
    assert parked_real_worker[0].wait(60)
    dialog = player.seq_export_dialog

    dialog.cancel_button.click()
    wait_until(lambda: dialog.state == "cancelled")  # 워커 스레드가 끝나야 '취소됨'

    assert not worker.isRunning() and os.listdir(out) == []
    assert dialogs.messages == []
    QApplication.processEvents()  # 늦게 온 신호가 있어도 상태가 그대로
    assert dialog.state == "cancelled"
    settle(player)


# ---------------------------------------------------------------- 진짜 워커로 끝에서 끝까지


def test_real_export_end_to_end(player, tmp_path, dialogs):
    """작은 시퀀스 둘 → mov 둘이 생기고 창이 '완료'에 닿음 (진짜 워커·ffmpeg)."""
    src = folder_with(tmp_path, "real", bases=("EX01_tk1", "EX01_tk2"))
    fill_list(player, src)
    player.require_ffmpeg = VideoPlayerBase.require_ffmpeg.__get__(player)
    out = tmp_path / "movs"
    out.mkdir()
    select_rows(player, 0, 1)
    dialogs.folders.append(str(out))

    player.export_selected_sequences()
    dialog = player.seq_export_dialog
    wait_until(lambda: dialog.state != "running", timeout=60)

    assert dialog.state == "finished", dialog.log.toPlainText()
    assert sorted(os.listdir(out)) == ["EX01_tk1.mov", "EX01_tk2.mov"]
    assert dialog.items_label.text() == "2/2 항목" and dialog.progress_bar.value() == dialog.progress_bar.maximum() == 8
    assert dialogs.messages == []
    player.seq_export_worker.wait(5000)
    settle(player)


def test_real_export_failure_is_shown_in_the_dialog(player, tmp_path, dialogs):
    """진짜 워커의 실패 요약이 창에 보임: 시퀀스의 프레임이 사라진 뒤 내보냄."""
    src = folder_with(tmp_path, "real2", bases=("EX01_tk1",))
    fill_list(player, src)
    for name in os.listdir(src):  # 목록은 그대로 두고 프레임을 지움
        os.remove(src / name)
    player.require_ffmpeg = VideoPlayerBase.require_ffmpeg.__get__(player)
    out = tmp_path / "movs2"
    out.mkdir()
    select_rows(player, 0)
    dialogs.folders.append(str(out))

    player.export_selected_sequences()
    dialog = player.seq_export_dialog
    wait_until(lambda: dialog.state != "running", timeout=60)

    assert dialog.state == "failed" and "1개 중 1개 실패" in dialog.log.toPlainText()
    assert "[EX01_tk1]" in dialog.log.toPlainText()
    assert os.listdir(out) == [] and len(dialogs.criticals) == 1
    player.seq_export_worker.wait(5000)
    settle(player)


def test_dialog_class_is_a_plain_view():
    """창 클래스는 워커 없이도 만들 수 있고 취소 요청을 신호로만 알림 (연결은 부르는 쪽)."""
    dialog = SequenceExportDialog(None, 3, "/some/out")
    requested = []
    dialog.cancel_requested.connect(lambda: requested.append(True))

    dialog.cancel_button.click()

    assert requested == [True] and dialog.state == "running"
    dialog.set_finished("끝")
    dialog.close()

