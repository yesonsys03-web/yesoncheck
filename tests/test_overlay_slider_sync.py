"""V 모드(오버레이 컨트롤) 슬라이더 동기화 — 화살표 프레임 이동이 오버레이 슬라이더도 움직여야 한다.

사용자 보고(2026-10-28, Mac·Windows 공통): V 모드에서 ←/→로 프레임을 옮기면 영상은 움직이는데
오버레이 슬라이더 핸들이 멈춰 있고, 휠로는 제대로 움직임. 원인: 화살표 경로(prev_frame/next_frame →
_seek_*_fast → _update_ui_fast)가 메인 슬라이더·라벨만 갱신하고 update_overlay_controls()를 부르지
않았음 — 휠 경로(seek_to_frame → update_frame)는 부름.
"""

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)


@pytest.fixture
def player(new_player, dialogs, tmp_path, qapp):
    player = new_player(make_config(str(tmp_path), {}))
    video = write_test_video(str(tmp_path / "clip.mov"), frames=24)
    assert player.open_file('A', video)
    qapp.processEvents()
    return player


def test_next_frame_moves_overlay_slider(player):
    start = player.overlaySlider.value()

    player.next_frame()

    assert player.overlaySlider.value() == start + 1


def test_prev_frame_moves_overlay_slider(player):
    player.next_frame()
    player.next_frame()
    value = player.overlaySlider.value()

    player.prev_frame()

    assert player.overlaySlider.value() == value - 1


def test_right_arrow_key_moves_overlay_slider(player, qapp):
    """실제 키 입력 경로로도 — 창이 자기 자신에 건 eventFilter(player_base)가 받아 next_frame을 부름."""
    start = player.overlaySlider.value()

    QTest.keyClick(player, Qt.Key_Right)
    qapp.processEvents()

    assert player.overlaySlider.value() == start + 1
    assert player.labelFrameCount.text() == f"Current: {player.overlaySlider.value() + 1}"  # 메인·오버레이 일치


def test_sequential_fallback_shows_target_frame_with_consistent_labels(player, monkeypatch):
    """대체 경로(_seek_sequential_fast — _seek_direct_fast가 실패할 때)의 한 칸 어긋남 회귀 시험.

    예전에는 정방향 분기가 읽기 전 위치와 비교해 목표의 다음 프레임을 보여 줬고(영상은 한 칸 더 간 것이
    보이는데 메인 라벨·스크롤바는 목표 번호를 보여 줌), 오버레이 동기화가 들어오면서 메인과 오버레이가
    1 다르게 보이게 됐다. 시험 영상은 i번 프레임이 단색 (i*10)%255라 평균값으로 어느 프레임인지 판별."""
    monkeypatch.setattr(player, "_seek_direct_fast", lambda *a, **k: False)

    player.next_frame()  # 0 → 1 (대체 경로로)

    assert player.frame_a is not None
    assert abs(float(player.frame_a.mean()) - 10) < 4  # 1번 프레임(≈10) — 2번(≈20)이면 한 칸 어긋난 것
    assert player.overlaySlider.value() == 1
    assert player.labelFrameCount.text() == "Current: 2"  # 메인 라벨도 같은 프레임(1번, 1-based 2)을 가리킴
