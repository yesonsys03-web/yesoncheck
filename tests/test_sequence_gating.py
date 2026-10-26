"""이미지 시퀀스가 열려 있으면 OCR·컷 감지는 쓸 수 없다 (단일 판정 한 곳, 가드 6곳): 버튼은 꺼지고, 직접 불려도 아무 일 없이
창으로 알리고 돌아온다. 영상(mov)에서는 예전 그대로다. reset_ocr_state는 상태 청소라 시퀀스에서도 그대로 동작.

오류·안내 창은 conftest의 dialogs가 가로챈다 (실제 QMessageBox·파일 선택 창을 띄우지 않음).
"""

import pytest
from PyQt5.QtWidgets import QFileDialog, QInputDialog

from tests.conftest import write_test_video
from tests.test_sequence_capture import make_seq
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import player_review

ROI = (0.1, 0.1, 0.5, 0.5)


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def open_seq(player, tmp_path):
    assert player.open_file("A", make_seq(str(tmp_path / "shots"), "EX01_tk1", range(1, 7)))
    assert player.is_sequence_active()


def open_mov(player, tmp_path):
    assert player.open_file("A", write_test_video(str(tmp_path / "movs" / "a.mp4")))
    assert not player.is_sequence_active()


def select_mode(player, mode):
    player.ocrModeComboBox.setCurrentIndex(player.ocrModeComboBox.findData(mode))
    assert player.ocrModeComboBox.currentData() == mode


def ocr_controls(player):
    return {
        "select_roi": player.ocrSelectRoiButton.isEnabled(),
        "tracking": player.ocrTrackingCheckBox.isEnabled(),
        "analyze": player.ocrAnalyzeButton.isEnabled(),
        "analyze_range": player.ocrAnalyzeRangeButton.isEnabled(),
    }


ALL_OFF = {"select_roi": False, "tracking": False, "analyze": False, "analyze_range": False}


def modes(player):
    return [player.ocrModeComboBox.itemData(i) for i in range(player.ocrModeComboBox.count())]


def forbid(monkeypatch, owner, name):
    """호출되면 시험이 실패하는 함수로 바꿈 — 가드가 이 일을 시작하기 전에 돌아왔음을 보임."""
    def forbidden(*args, **kwargs):
        raise AssertionError(f"{name}이(가) 불리면 안 됩니다")

    monkeypatch.setattr(owner, name, forbidden)


# ---------------------------------------------------------------- 버튼


def test_ocr_buttons_disabled_for_sequence(player, tmp_path):
    open_seq(player, tmp_path)

    for mode in modes(player):  # 애니매틱류는 예전에 '영상만 있으면' 켜졌던 모드 — 시퀀스에서는 모두 꺼짐
        select_mode(player, mode)
        assert ocr_controls(player) == ALL_OFF, mode


def test_ocr_buttons_stay_disabled_after_roi_is_set_on_sequence(player, tmp_path):
    """on_roi_selected는 버튼을 켠 뒤 on_ocr_mode_changed를 부르므로, 거기서 다시 꺼져야 한다."""
    open_seq(player, tmp_path)

    player.on_roi_selected(ROI)

    assert ocr_controls(player) == ALL_OFF


def test_ocr_buttons_follow_the_open_source_kind(player, tmp_path):
    """시퀀스를 닫고 mov를 열면 예전 규칙대로 돌아온다 (OCR 모드는 ROI 지정 버튼, 애니매틱은 분석 버튼)."""
    open_seq(player, tmp_path)
    open_mov(player, tmp_path)

    select_mode(player, "titmouse")
    assert ocr_controls(player) == {"select_roi": True, "tracking": True, "analyze": False, "analyze_range": False}
    player.on_roi_selected(ROI)
    assert ocr_controls(player) == {"select_roi": True, "tracking": True, "analyze": True, "analyze_range": True}
    select_mode(player, "animatic")
    assert ocr_controls(player) == {"select_roi": False, "tracking": False, "analyze": True, "analyze_range": True}

    open_seq(player, tmp_path)  # 다시 시퀀스 -> 꺼짐
    assert ocr_controls(player) == ALL_OFF
    open_mov(player, tmp_path)
    assert ocr_controls(player)["analyze"] is True  # 애니매틱 모드는 영상만 있으면 켜짐 (예전 그대로)


def test_roi_button_tooltip_says_why_on_sequence_and_is_restored(player, tmp_path):
    select_mode(player, "titmouse")
    normal = player.ocrSelectRoiButton.toolTip()
    open_seq(player, tmp_path)
    assert "시퀀스" in player.ocrSelectRoiButton.toolTip()
    open_mov(player, tmp_path)
    assert player.ocrSelectRoiButton.toolTip() == normal


# ---------------------------------------------------------------- 직접 불려도 조기 반환


def test_ocr_run_guards_early_return(player, tmp_path, monkeypatch, dialogs):
    open_seq(player, tmp_path)
    player.ocr_roi = ROI  # ROI까지 있어도 막힘
    forbid(monkeypatch, type(player), "get_current_video_path")  # 분석 대상을 찾기도 전에 돌아옴
    forbid(monkeypatch, QInputDialog, "getInt")

    player.run_ocr_analysis()
    player.run_ocr_analysis_range()

    assert player.ocr_worker is None
    assert player.ocr_progress_dialog is None
    assert len(dialogs.messages) == 2 and all(kind == "information" for kind, _title, _text in dialogs.messages)
    assert all("시퀀스" in text for _kind, _title, text in dialogs.messages)  # 왜 안 되는지 알림 (소리 없이 무시하지 않음)


@pytest.mark.parametrize("mode", ["titmouse", "animatic"])
def test_ocr_run_guards_apply_in_every_mode(player, tmp_path, monkeypatch, mode):
    open_seq(player, tmp_path)
    select_mode(player, mode)
    forbid(monkeypatch, type(player), "get_current_video_path")

    player.run_ocr_analysis()
    player.run_ocr_analysis_range()

    assert player.ocr_worker is None


def test_roi_selection_guard(player, tmp_path, dialogs, monkeypatch):
    open_seq(player, tmp_path)
    forbid(monkeypatch, type(player.videoWidget), "enable_roi_selection")
    select_mode(player, "titmouse")

    player.ocrSelectRoiButton.setEnabled(True)  # 꺼진 단추라도 코드가 직접 켜 둘 수 있는 경우를 가정
    player.ocrSelectRoiButton.setChecked(True)  # toggled 신호 -> toggle_ocr_roi_selection(True)

    assert not player.ocrSelectRoiButton.isChecked()  # 눌린 채로 남지 않음
    assert not player.videoWidget.roi_selection_enabled
    assert [kind for kind, _t, _x in dialogs.messages] == ["information"]


def test_roi_selection_can_still_be_turned_off_on_sequence(player, tmp_path, dialogs):
    """꺼지는 쪽(checked=False)은 막지 않는다 — 가드가 켜기만 막음."""
    open_seq(player, tmp_path)
    player.videoWidget.roi_selection_enabled = True

    player.toggle_ocr_roi_selection(False)

    assert not player.videoWidget.roi_selection_enabled
    assert dialogs.messages == []


def test_load_and_reopen_guards(player, tmp_path, monkeypatch, dialogs):
    open_seq(player, tmp_path)
    player.last_ocr_segments = [{"text": "x", "start_frame": 0, "end_frame": 3}]  # 가드가 없으면 검토 창을 여는 상태
    forbid(monkeypatch, QFileDialog, "getOpenFileName")
    forbid(monkeypatch, player_review, "OCRReviewDialog")

    player.load_ocr_result()
    player.reopen_ocr_result()

    assert getattr(player, "ocr_review_dialog", None) is None
    assert len(dialogs.messages) == 2 and all(kind == "information" for kind, _title, _text in dialogs.messages)
    assert all("시퀀스" in text for _kind, _title, text in dialogs.messages)


def test_reset_ocr_state_is_not_gated(player, tmp_path):
    """상태 청소는 시퀀스가 열려 있어도 그대로 해야 한다 (영상을 바꿀 때 불림)."""
    open_seq(player, tmp_path)
    player.ocr_roi = ROI
    player.last_ocr_segments = [{"text": "x"}]
    player.saved_edited_segments = [{"text": "x"}]
    player._ocr_results_unsaved = True

    player.reset_ocr_state()

    assert player.ocr_roi is None
    assert player.last_ocr_segments == [] and player.saved_edited_segments is None
    assert player._ocr_results_unsaved is False
    assert ocr_controls(player) == ALL_OFF


# ---------------------------------------------------------------- mov는 예전 그대로


def test_movie_ocr_run_is_not_intercepted(player, tmp_path, dialogs):
    """mov에서는 가드가 끼지 않아 예전 흐름이 그대로 이어진다: ROI가 없으면 ROI 안내."""
    open_mov(player, tmp_path)
    select_mode(player, "titmouse")

    player.run_ocr_analysis()

    assert player.ocr_worker is None
    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("warning", "ROI 미지정")]


def test_movie_roi_selection_still_starts(player, tmp_path, dialogs):
    open_mov(player, tmp_path)

    player.ocrSelectRoiButton.setChecked(True)

    assert player.ocrSelectRoiButton.isChecked()
    assert player.videoWidget.roi_selection_enabled
    assert dialogs.messages == []


def test_movie_reopen_without_results_keeps_old_message(player, tmp_path, dialogs):
    open_mov(player, tmp_path)

    player.reopen_ocr_result()

    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("information", "결과 없음")]
