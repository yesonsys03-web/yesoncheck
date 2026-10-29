"""재생 틱 한 번에 화면을 한 번만 그린다 (4K 재생 성능 — 사용자 승인 예외, 2026-10-29).

update_frame은 videoWidget.updateFrame으로 그린 직후 refresh_frame_annotations_display()를 불렀고, 그 함수는 프레임 번호가
바뀌었을 때 _redraw_frame_with_annotations()로 같은 프레임을 prepare_frame_for_display로 다시 만들어 updateFrame을 한 번 더
불렀다 (틱마다 두 번 그림 — 4K에서 틱당 ~10ms 낭비). 지금은 update_frame이 redraw=False로 불러 다시 그리지 않는다.

지키는 것:
- 재생 틱(next_frame_playback → update_frame) 한 번에 updateFrame 정확히 한 번, 그 그림이 주석까지 구운 마지막 그림.
- 주석 모드에서 편집 대상(핸들) 갱신은 그리기와 상관없이 그대로 (redraw=False에서도 _set_edit_target).
- 프레임 번호 비교·목록·상태 라벨 갱신도 그대로 (redraw=False에서도).
- 다른 호출처(update_frame 없이 부르는 곳)는 redraw 기본값(True)이라 여전히 그린다.
- 드래그 + OCR 검토 창 분기: 앞 그림이 B를 뺀 그림이라(와이프가 켜져 있으면) 거기선 다시 그려야 마지막 그림이 변경 전과 같다.
"""

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from tests.conftest import write_test_video
from tests.test_frame_annotations_merge import text_item
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

POS = cv2.CAP_PROP_POS_FRAMES


@pytest.fixture
def player(new_player, dialogs, tmp_path, qapp, monkeypatch):
    player = new_player(make_config(str(tmp_path), {}))
    video = write_test_video(str(tmp_path / "clip.mov"), frames=24)
    assert player.open_file("A", video)
    qapp.processEvents()
    return player


@pytest.fixture
def draws(player, monkeypatch):
    """videoWidget.updateFrame 호출을 (frame_a, frame_b) 순서대로 기록하면서 진짜로도 그린다."""
    calls = []
    real = player.videoWidget.updateFrame

    def spy(frame_a, frame_b):
        calls.append((frame_a, frame_b))
        return real(frame_a, frame_b)

    monkeypatch.setattr(player.videoWidget, "updateFrame", spy)
    return calls


@pytest.fixture
def edit_targets(player, monkeypatch):
    """videoWidget.set_annotation_edit_target 호출 인자를 기록하면서 진짜로도 부른다."""
    calls = []
    real = player.videoWidget.set_annotation_edit_target

    def spy(annotation):
        calls.append(annotation)
        return real(annotation)

    monkeypatch.setattr(player.videoWidget, "set_annotation_edit_target", spy)
    return calls


@pytest.fixture
def ticking(player):
    """재생 중 상태 (timer 활성) — 간격을 아주 길게 해서 저절로는 안 울리고 시험이 next_frame_playback을 직접 부른다."""
    player.timer.start(600000)
    yield player
    player.timer.stop()


def add_selected_annotation(player, frame_idx):
    """frame_idx에 텍스트 주석을 넣고, 목록에서 선택하고, 주석 모드를 켠 뒤 첫 프레임으로 되감는다 (목록에서 고르면 그 주석의
    프레임으로 가므로)."""
    item = player.annotation_store.add(frame_idx, text_item("hello"))
    player.refresh_annotation_ui(redraw=False)
    player.annotationListWidget.setCurrentRow(0)
    player.annotationModeButton.setChecked(True)
    assert player.annotationModeButton.isChecked()
    assert player._get_selected_annotation()["id"] == item["id"]
    player.seek_to_frame(1)
    assert player.get_current_frame_index() == 0
    return item


# ---------------------------------------------------------------- 재생 틱: 한 번만 그림

def test_playback_tick_draws_exactly_once(ticking, draws):
    for expected_idx in (1, 2, 3):
        draws.clear()

        ticking.next_frame_playback()

        assert ticking.get_current_frame_index() == expected_idx  # 틱마다 프레임 번호가 바뀜 (예전엔 이때 두 번 그렸음)
        assert len(draws) == 1, f"틱 하나에 updateFrame {len(draws)}번"


def test_update_frame_alone_draws_once_when_frame_index_changed(player, draws):
    player.cap_a.set(POS, 6)  # 프레임 번호가 바뀐 상태
    ok, player.frame_a = player.cap_a.read()
    assert ok and player.get_current_frame_index() == 6
    assert player._last_annotation_frame_idx != 6

    player.update_frame()

    assert len(draws) == 1
    assert player._last_annotation_frame_idx == 6  # 프레임 번호 비교·갱신은 그대로


def test_tick_draws_annotation_in_the_single_draw(ticking, draws):
    """주석이 있는 프레임으로 가는 틱: 한 번 그린 그림이 주석을 구운 그림이다."""
    add_selected_annotation(ticking, 2)
    ticking.next_frame_playback()  # 프레임 1 (주석 없음)
    draws.clear()

    ticking.next_frame_playback()  # 프레임 2 (주석 있음)

    assert ticking.get_current_frame_index() == 2
    assert len(draws) == 1
    shown, _ = draws[0]
    assert not np.array_equal(shown, ticking.frame_a)  # 구운 그림 (원본이 그대로 가지 않음)


def test_tick_with_wipe_draws_once_with_frame_b(ticking, draws):
    ticking.videoWidget.wipe_enabled_x = True
    ticking.frame_b = np.full_like(ticking.frame_a, 77)

    ticking.cap_a.set(POS, 4)
    ok, ticking.frame_a = ticking.cap_a.read()
    assert ok

    ticking.update_frame()

    assert len(draws) == 1
    assert draws[0][1] is ticking.frame_b  # 와이프의 B를 실어 그림


# ---------------------------------------------------------------- 주석 모드: 편집 대상 갱신은 그대로

def test_tick_still_updates_edit_target_in_annotation_mode(ticking, draws, edit_targets):
    item = add_selected_annotation(ticking, 3)

    for _ in range(3):
        draws.clear()
        edit_targets.clear()

        ticking.next_frame_playback()

        assert len(draws) == 1
        assert edit_targets, "프레임이 바뀐 틱에서 편집 대상을 갱신하지 않음"
        assert edit_targets[-1]["id"] == item["id"]
    assert ticking.videoWidget.annotation_edit_target["id"] == item["id"]


def test_tick_prefers_the_annotation_being_edited_as_edit_target(ticking, edit_targets):
    item = add_selected_annotation(ticking, 3)
    other = ticking.annotation_store.add(5, text_item("other", x=0.5))
    ticking._editing_annotation = other
    edit_targets.clear()

    ticking.next_frame_playback()

    assert edit_targets and edit_targets[-1]["id"] == other["id"] != item["id"]


def test_tick_leaves_edit_target_alone_when_annotation_mode_is_off(ticking, edit_targets):
    add_selected_annotation(ticking, 3)
    ticking.annotationModeButton.setChecked(False)
    edit_targets.clear()

    ticking.next_frame_playback()

    assert edit_targets == []  # 주석 모드가 꺼져 있으면 편집 대상을 건드리지 않음 — 변경 전과 같은 동작


def test_no_edit_target_update_when_frame_index_unchanged(player, draws, edit_targets):
    add_selected_annotation(player, 3)
    draws.clear()
    edit_targets.clear()

    player.update_frame()  # 프레임 번호 그대로 → refresh는 아무것도 안 함

    assert len(draws) == 1
    assert edit_targets == []


# ---------------------------------------------------------------- redraw=False: 그리기만 빠짐

def test_refresh_without_redraw_keeps_list_status_and_index_updates(player, draws, edit_targets):
    item = add_selected_annotation(player, 5)
    player.cap_a.set(POS, 6)
    assert player.get_current_frame_index() == 5
    player._last_annotation_frame_idx = 0
    player.annotationStatusLabel.setText("")
    draws.clear()
    edit_targets.clear()

    player.refresh_frame_annotations_display(redraw=False)

    assert draws == []
    assert player._last_annotation_frame_idx == 5
    assert "현재 프레임 6: 1개" in player.annotationStatusLabel.text()
    assert player.annotationListWidget.count() == 1
    assert edit_targets and edit_targets[-1]["id"] == item["id"]


def test_redraw_without_draw_does_nothing_when_no_frame(player, draws, edit_targets):
    add_selected_annotation(player, 5)
    player.frame_a = None
    draws.clear()
    edit_targets.clear()

    player._redraw_frame_with_annotations(draw=False)
    player._redraw_frame_with_annotations()

    assert draws == []
    assert edit_targets == []  # frame_a가 없으면 변경 전처럼 아무것도 안 함


# ---------------------------------------------------------------- 다른 호출처: 그대로 그림

def test_refresh_alone_still_draws(player, draws):
    player.cap_a.set(POS, 6)  # update_frame 없이 프레임 번호만 바뀐 상태 (탐색 직후 등)
    assert player.get_current_frame_index() == 5
    assert player._last_annotation_frame_idx != 5

    player.refresh_frame_annotations_display()

    assert len(draws) == 1
    assert player._last_annotation_frame_idx == 5


def test_refresh_alone_does_not_draw_when_frame_index_unchanged(player, draws):
    player.refresh_frame_annotations_display()
    draws.clear()

    player.refresh_frame_annotations_display()

    assert draws == []


def test_refresh_annotation_ui_still_draws(player, draws):
    player.refresh_annotation_ui(redraw=True)

    assert len(draws) == 1


def test_overlay_slider_update_still_draws_for_a_new_frame(player, draws):
    """update_frame을 거치지 않는 호출처(오버레이 슬라이더) — 앞 그림 뒤에 refresh가 다시 그리는 동작 그대로."""
    player.cap_a.set(POS, 8)
    ok, player.frame_a = player.cap_a.read()
    assert ok

    player._overlay_slider_ui_update(8, 24)

    assert len(draws) == 2


# ---------------------------------------------------------------- 드래그 + OCR 검토 창 분기

@pytest.fixture
def dragging_with_ocr_dialog(player):
    player.is_dragging = True
    player.ocr_review_dialog = SimpleNamespace(isVisible=lambda: True)
    yield player
    player.is_dragging = False
    player.ocr_review_dialog = None


def move_to_new_frame(player, pos):
    player.cap_a.set(POS, pos)
    ok, player.frame_a = player.cap_a.read()
    assert ok


def test_drag_with_ocr_dialog_draws_once_without_wipe(dragging_with_ocr_dialog, draws):
    player = dragging_with_ocr_dialog
    move_to_new_frame(player, 6)

    player.update_frame()

    assert len(draws) == 1
    assert draws[0][1] is None
    assert player._last_annotation_frame_idx == 6


def test_drag_with_ocr_dialog_and_wipe_still_ends_with_the_b_frame(dragging_with_ocr_dialog, draws):
    """와이프가 켜져 있으면 앞 그림(B 없음)과 다시 그리는 그림(B 있음)이 다르다 — 마지막 그림은 변경 전과 같아야 함."""
    player = dragging_with_ocr_dialog
    player.videoWidget.wipe_enabled_x = True
    player.frame_b = np.full_like(player.frame_a, 77)
    move_to_new_frame(player, 6)

    player.update_frame()

    assert draws[0][1] is None
    assert draws[-1][1] is player.frame_b
