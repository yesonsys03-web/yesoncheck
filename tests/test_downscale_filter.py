"""(Windows) 축소 필터 설정 — 영상을 줄여 그릴 때 Linear(기본, 예전 그대로) 또는 고품질(면적 평균) (2026-11-12).

사용자 보고: "윈도 버전에서 같은 그림을 띄워도 라인이 지글거려 보여. 1대1 사이즈로 보면 괜찮은데." → "설정에서 안티알리어싱 필터링 방식으로" →
"맥 버전은 전혀 문제 없기 때문에 수정하지 않아도 돼." 그래서 메뉴·설정 읽기는 Windows만이고, 기본(Linear)에서는 그리기가 예전과 같음.
여기서는 값·저장·시작 때 읽기·메뉴와 '어디에 어떤 크기로 그릴지'의 규칙을 봄 — 그리기는 test_raster_video_item(CPU)·test_gl_video_item(GPU).
이 Mac에서는 sys.platform을 바꿔 봄 — 실제 Windows 화면은 사람이 확인.
"""

import json
import sys

import numpy as np
import pytest
from PyQt5.QtWidgets import QMenu, QMessageBox

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import app, downscale_filter, user_files


@pytest.fixture
def local_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")
    return tmp_path


def prefs_file(root):
    return root / "YesonCheck" / "prefs.json"


def write_prefs(root, text):
    prefs_file(root).parent.mkdir(parents=True, exist_ok=True)
    prefs_file(root).write_text(text, encoding="utf-8")


def saved(root):
    return json.loads(prefs_file(root).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 값과 저장


def test_default_is_linear():
    """기본은 예전 그리기 그대로 — 고품질은 골라야 켜짐 (Mac은 고르는 길이 없어 늘 이 값)."""
    assert downscale_filter.DEFAULT_FILTER == "linear" and downscale_filter.preferred() == "linear"
    assert downscale_filter.FILTERS == ("linear", "area")


def test_bad_name_raises_and_keeps_the_value():
    downscale_filter.set_preferred("area")
    with pytest.raises(ValueError, match="downscale_filter"):
        downscale_filter.set_preferred("lanczos")
    assert downscale_filter.preferred() == "area"


def test_saved_in_local_app_data_and_keeps_other_keys(local_app_data):
    write_prefs(local_app_data, json.dumps({"display_renderer": "gpu"}))
    downscale_filter.save("area")
    assert saved(local_app_data) == {"display_renderer": "gpu", "downscale_filter": "area"}
    assert downscale_filter.read() == "area"


def test_read_without_a_file_is_the_default(local_app_data):
    assert downscale_filter.read() == "linear"


def test_broken_prefs_raise_and_are_not_overwritten(local_app_data):
    write_prefs(local_app_data, "{깨짐")
    with pytest.raises(user_files.UserFileError):
        downscale_filter.read()
    with pytest.raises(user_files.UserFileError):
        downscale_filter.save("area")
    assert prefs_file(local_app_data).read_text(encoding="utf-8") == "{깨짐"


def test_saving_an_unknown_name_is_refused(local_app_data):
    with pytest.raises(ValueError, match="downscale_filter"):
        downscale_filter.save("lanczos")
    assert not prefs_file(local_app_data).exists()


# ---------------------------------------------------------------- 어디에 어떤 크기로 그릴지 (두 그리기 길이 함께 씀)


def test_minified_frame_is_placed_on_whole_device_pixels():
    """1920×1080을 (45.4, 30.6)–(1033.7, 586.5) 자리에 — 네 가장자리를 각각 가장 가까운 정수 픽셀로(다시 섞이지 않게)."""
    assert downscale_filter.snapped_rect(45.4, 30.6, 45.4 + 988.3, 30.6 + 555.9, 1920, 1080) == (45, 31, 989, 556)


def test_half_pixel_positions_round_up_like_qt():
    assert downscale_filter.snapped_rect(10.5, 20.5, 10.5 + 100.5, 20.5 + 50.5, 400, 200) == (11, 21, 100, 50)


def test_every_edge_stays_within_half_a_pixel():
    """왼쪽 자리와 크기를 따로 반올림하면 오른쪽·아래 끝이 1픽셀 가까이 어긋남(0.4에서 10.8까지 → 0..10) — 와이프 선·ROI·주석은 진짜 자리에 그려지므로
    가장자리마다 반 픽셀 안이어야 함 (리뷰에서 잡음)."""
    assert downscale_filter.snapped_rect(0.4, 0.4, 10.8, 10.8, 400, 400) == (0, 0, 11, 11)
    rng = np.random.default_rng(7)
    for _ in range(2000):
        x0, y0 = rng.uniform(-50, 300, 2)
        span_x, span_y = rng.uniform(2, 900), rng.uniform(2, 500)
        left, top, width, height = downscale_filter.snapped_rect(x0, y0, x0 + span_x, y0 + span_y, 1920, 1080)
        for snapped, real in ((left, x0), (top, y0), (left + width, x0 + span_x), (top + height, y0 + span_y)):
            assert abs(snapped - real) <= 0.5 + 1e-9


def test_negative_positions_round_to_the_nearest_pixel():
    """창 밖으로 밀린 자리 — int()는 0 쪽으로 잘라 한 픽셀 어긋남."""
    assert downscale_filter.snapped_rect(-30.7, -10.2, 69.3, 39.8, 400, 200) == (-31, -10, 100, 50)


@pytest.mark.parametrize("span", [(1920.0, 1080.0), (3840.0, 2160.0), (1900.0, 1068.75)])
def test_one_to_one_and_enlarged_frames_are_left_alone(span):
    """1:1·키워 그리기·1:1 언저리(반올림으로 한두 픽셀 모자란 크기)는 예전 그리기가 맞음."""
    assert downscale_filter.snapped_rect(0.0, 0.0, span[0], span[1], 1920, 1080) is None


def test_just_below_the_threshold_is_minified():
    span = 1920 * downscale_filter.DOWNSCALE_BELOW - 1
    assert downscale_filter.snapped_rect(0.0, 0.0, span, span * 1080 / 1920, 1920, 1080) is not None


def test_flipped_or_empty_placement_is_left_alone():
    assert downscale_filter.snapped_rect(100.0, 0.0, 0.0, 50.0, 400, 200) is None
    assert downscale_filter.snapped_rect(0.0, 50.0, 100.0, 0.0, 400, 200) is None
    assert downscale_filter.snapped_rect(5.0, 5.0, 5.0, 5.0, 400, 200) is None


def test_a_tiny_placement_is_at_least_one_pixel():
    assert downscale_filter.snapped_rect(3.2, 4.1, 3.5, 4.3, 400, 200) == (3, 4, 1, 1)


def test_area_scaling_averages_the_pixels_it_covers():
    """4픽셀마다 1픽셀 검은 선을 1/4로 — 어디나 같은 회색(선의 양이 보존됨). 겹선형으로 고르면 선이 통째로 사라지거나 새까맣게 됨."""
    frame = np.full((40, 160, 3), 255, np.uint8)
    frame[:, ::4] = 0
    small = downscale_filter.area_scaled(frame, 40, 10)
    assert small.shape == (10, 40, 3) and small.dtype == np.uint8 and small.flags["C_CONTIGUOUS"]
    assert small.min() == small.max() == 191


# ---------------------------------------------------------------- 시작 때 읽기


def test_launch_reads_the_saved_filter(local_app_data, capsys):
    downscale_filter.save("area")
    app.load_downscale_filter()
    assert downscale_filter.preferred() == "area"
    assert "[축소 필터] 설정: area" in capsys.readouterr().out


def test_launch_without_prefs_stays_linear(local_app_data, capsys):
    downscale_filter.set_preferred("area")  # 읽지 않으면 그대로 남아 실패
    app.load_downscale_filter()
    assert downscale_filter.preferred() == "linear"
    assert "[축소 필터] 설정: linear" in capsys.readouterr().out


def test_broken_prefs_at_launch_warn_once_and_use_linear(local_app_data, monkeypatch, capsys):
    write_prefs(local_app_data, "{깨짐")
    downscale_filter.set_preferred("area")
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[1:3]))
    app.load_downscale_filter()
    assert downscale_filter.preferred() == "linear"
    assert len(warned) == 1 and warned[0][0] == downscale_filter.SETTINGS_TITLE
    assert "설정 파일을 고치거나 지운 뒤" in warned[0][1]  # 깨진 파일은 메뉴로도 저장하지 못함 — '메뉴에서 바꿀 수 있다'고 말하지 않음
    assert "Traceback" in capsys.readouterr().err
    assert prefs_file(local_app_data).read_text(encoding="utf-8") == "{깨짐"


def test_a_bad_value_at_launch_warns_and_points_to_the_menu(local_app_data, monkeypatch, capsys):
    write_prefs(local_app_data, json.dumps({"downscale_filter": "lanczos"}))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[1:3]))
    app.load_downscale_filter()
    assert downscale_filter.preferred() == "linear"
    assert len(warned) == 1 and downscale_filter.MENU_TEXT in warned[0][1]
    assert "Traceback" in capsys.readouterr().err
    assert saved(local_app_data) == {"downscale_filter": "lanczos"}  # 파일은 그대로 — 값을 지어내 쓰지 않음


def test_launch_on_mac_reads_nothing(monkeypatch, capsys):
    """Mac은 이 설정을 읽지 않음 — 늘 Linear(예전 그리기 그대로)."""
    monkeypatch.setattr(downscale_filter, "read", lambda: pytest.fail("Windows 전용 설정을 읽음"))
    monkeypatch.setattr(sys, "platform", "darwin")
    app.load_downscale_filter()
    assert downscale_filter.preferred() == "linear" and "축소 필터" not in capsys.readouterr().out


def test_launch_loads_the_filter_before_the_window(qapp, monkeypatch):
    """app.launch가 창을 만들기 전에 읽음."""
    order = []
    monkeypatch.setattr(app, "load_downscale_filter", lambda: order.append("filter"))

    class Stop(Exception):
        pass

    def no_window(**kwargs):
        order.append("window")
        raise Stop

    monkeypatch.setattr(app, "VideoPlayer", no_window)
    with pytest.raises(Stop):
        app.launch(["yesoncheck"])
    assert order == ["filter", "window"]


# ---------------------------------------------------------------- 메뉴


class SpyItem:
    """영상 아이템 대역 — 다시 그리기 요청만 셈."""

    def __init__(self):
        self.updates = 0

    def update(self):
        self.updates += 1


@pytest.fixture
def menu_player(new_player, dialogs, tmp_path, local_app_data, monkeypatch):  # noqa: F811
    player = new_player(make_config(str(tmp_path), {}))
    player._add_downscale_menu(QMenu(player))
    return player


def test_settings_menu_has_the_filter_on_windows(new_player, dialogs, tmp_path, local_app_data):  # noqa: F811
    """창을 만들 때 Settings에 붙음 — 화면 그리기 (Windows) 바로 뒤."""
    player = new_player(make_config(str(tmp_path), {}))
    settings = next(action.menu() for action in player.menuBar().actions() if action.text() == "&Settings")
    titles = [action.text() for action in settings.actions()]
    assert titles.index(downscale_filter.MENU_TEXT) == titles.index("화면 그리기 (Windows)") + 1
    assert set(player.downscale_actions) == {"linear", "area"}


def test_no_menu_on_mac(new_player, dialogs, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sys, "platform", "darwin")
    player = new_player(make_config(str(tmp_path), {}))
    settings = next(action.menu() for action in player.menuBar().actions() if action.text() == "&Settings")
    assert downscale_filter.MENU_TEXT not in [action.text() for action in settings.actions()]
    assert player.downscale_actions == {}
    menu = QMenu(player)
    player._add_downscale_menu(menu)
    assert menu.isEmpty()


def test_menu_starts_on_this_windows_filter(menu_player):
    actions = menu_player.downscale_actions
    assert actions["linear"].isChecked() and not actions["area"].isChecked()
    assert actions["linear"].text() == "Linear (기본)" and actions["area"].text() == "고품질 (면적 평균)"
    assert actions["area"].toolTip() and actions["linear"].toolTip()


def test_choosing_area_saves_and_applies_to_this_window_right_away(menu_player, local_app_data, capsys):
    player = menu_player
    player.videoWidget.video_item = item = SpyItem()
    player.downscale_actions["area"].trigger()
    assert saved(local_app_data)["downscale_filter"] == "area"
    assert downscale_filter.preferred() == "area"
    assert player.downscale_actions["area"].isChecked() and not player.downscale_actions["linear"].isChecked()
    assert item.updates == 1  # 지금 보이는 프레임을 새 필터로 다시 그림
    assert "[축소 필터] 설정: area (Settings 메뉴)" in capsys.readouterr().out


def test_choosing_linear_again_goes_back(menu_player, local_app_data):
    player = menu_player
    player.downscale_actions["area"].trigger()
    player.downscale_actions["linear"].trigger()
    assert saved(local_app_data)["downscale_filter"] == "linear" and downscale_filter.preferred() == "linear"
    assert player.downscale_actions["linear"].isChecked() and not player.downscale_actions["area"].isChecked()


def test_choosing_the_checked_one_keeps_it_checked_and_writes_nothing(menu_player, local_app_data):
    player = menu_player
    player.videoWidget.video_item = item = SpyItem()
    player.downscale_actions["linear"].trigger()  # 체크된 항목을 다시 누르면 Qt가 체크를 끔 — 되돌려야 함
    assert player.downscale_actions["linear"].isChecked() and not prefs_file(local_app_data).exists()
    assert item.updates == 0


def test_another_windows_saved_choice_is_not_rewritten_but_applied_here(menu_player, local_app_data):
    """창마다 프로세스 — 다른 창이 이미 고품질을 저장했어도 이 창은 아직 Linear. 여기서 고품질을 고르면 파일은 그대로 두고 이 창에 적용."""
    player = menu_player
    downscale_filter.save("area")  # 다른 창
    before = prefs_file(local_app_data).stat().st_mtime_ns
    player.downscale_actions["area"].trigger()
    assert downscale_filter.preferred() == "area" and prefs_file(local_app_data).stat().st_mtime_ns == before


def test_a_bad_saved_value_is_replaced_by_the_choice(menu_player, local_app_data):
    write_prefs(local_app_data, json.dumps({"downscale_filter": "lanczos", "other": 1}))
    menu_player.downscale_actions["area"].trigger()
    assert saved(local_app_data) == {"downscale_filter": "area", "other": 1}


def test_save_failure_keeps_the_old_filter(menu_player, local_app_data, monkeypatch, capsys):
    player = menu_player
    player.videoWidget.video_item = item = SpyItem()
    write_prefs(local_app_data, "{깨짐")
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[1:3]))
    player.downscale_actions["area"].trigger()
    assert downscale_filter.preferred() == "linear" and item.updates == 0
    assert player.downscale_actions["linear"].isChecked() and not player.downscale_actions["area"].isChecked()
    assert len(errors) == 1 and errors[0][0] == downscale_filter.SETTINGS_TITLE
    assert "Traceback" in capsys.readouterr().err
    assert prefs_file(local_app_data).read_text(encoding="utf-8") == "{깨짐"


def test_unknown_filter_name_is_refused_before_anything_is_written(menu_player, local_app_data):
    with pytest.raises(ValueError, match="downscale_filter"):
        menu_player.set_downscale_filter("lanczos")
    assert not prefs_file(local_app_data).exists() and downscale_filter.preferred() == "linear"
