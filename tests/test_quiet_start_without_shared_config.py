"""공유 설정을 찾지 못하면 시작할 때 알림 창을 띄우지 않는다 (사용자 요청·결정 2026-11-23).

예손 사내 공유 설정(작품 경로)이 보이지 않는 PC에서는 켤 때마다 '공유 설정 오류' 창이 떴다 (Windows는 그 전에 '공유 설정 폴더 선택'
안내와 폴더 고르기 창까지). 회사 밖에서는 이 앱을 혼자(스탠드얼론) 쓰므로 필요 없는 알림이고, 앱은 '밖에서 켠 노트북'과 '사내에서 NAS가
끊긴 PC'를 구별하지 못한다 → **공유 설정을 찾지 못했을 때(`SharedConfigState.config_not_found` — 없음·NAS에 닿지 않음)는 어느 PC에서도
시작할 때 창을 띄우지 않고** 창 제목의 표시와 기록에만 남긴다 (사용자 결정 '시작 창 아예 없앰').

- 찾지 못함: 공유 설정 폴더가 지금 이 PC에서 보이지 않음 (Mac: 기본 자리에 폴더가 없음, Windows: 정해 둔 폴더가 없고 하나도 못 찾음·정해 둔
  폴더가 열리지 않거나 응답 없음)
- 창으로 알리는 진짜 문제: 폴더는 열리는데 파일이 없거나 깨짐, 권한이 없어 열지 못함, PC별 설정 파일이 깨짐, 예상 못 한 오류
  (test_fast_startup), Windows에서 설정 폴더를 여럿 찾음 → 고르기 (test_path_map_auto_ui의 test_multiple_config_dirs_pick_one)

메뉴로 부르는 길(Tools → 작품 경로 관리의 사유 안내, Windows의 Settings → 공유 설정 폴더 변경)은 그대로.
"""

import os
import sys

import pytest
from PyQt5.QtWidgets import QFileDialog

from tests.test_fast_startup import wait_until
from tests.test_mac_mounts import NO_SUCH_CONFIG
from tests.test_path_map_auto_ui import win  # noqa: F401 (fixture)
from yesoncheck import hover_strip, mac_prefs, path_map_setup, paths, shared_config, shared_config_load, work_picker

mac_only = pytest.mark.skipif(sys.platform == "win32", reason="Mac의 공유 설정 자리(POSIX 경로) — Windows 동작은 win 픽스처의 시험")

NOT_SET = "공유 설정 폴더가 아직 정해지지 않았습니다."
QUIET_LOG = "창으로 알리지 않음"
GONE_UNC = "\\\\localhost\\yc_fake_gone\\test_jn\\.yesoncheck"  # 열리지 않는 가짜 주소 (Windows에서 열어 봐도 바로 실패)


@pytest.fixture
def mac_env(qapp, monkeypatch):
    """Mac 동작, 환경 변수로 정한 공유 설정 폴더 없음."""
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    monkeypatch.delenv(shared_config.CONFIG_DIR_ENV, raising=False)


@pytest.fixture
def no_share_mac(mac_env, monkeypatch):
    """공유가 보이지 않는 Mac (회사 밖, 또는 사내에서 NAS가 끊김): 공유 설정의 자리가 통째로 없음."""
    monkeypatch.setattr(shared_config, "MAC_CONFIG_DIR", NO_SUCH_CONFIG)


@pytest.fixture
def share_place(mac_env, monkeypatch, tmp_path):
    """공유는 붙어 있는 Mac → 그 아래 공유 설정 폴더가 놓일 자리 (아직 만들지 않음)."""
    place = tmp_path / "USA_DB" / "test_jn" / ".yesoncheck"
    monkeypatch.setattr(shared_config, "MAC_CONFIG_DIR", str(place))
    return place


@pytest.fixture
def players():
    made = []

    def make(**kwargs):
        from yesoncheck.main_window import VideoPlayer

        player = VideoPlayer(**kwargs)
        made.append(player)
        return player

    yield make
    for player in made:
        player.close()
    paths.activate(None)


def no_shares_windows(win, monkeypatch):  # noqa: F811
    """공유가 보이지 않는 Windows PC: 네트워크 드라이브도 Harmony식 폴더도 없음, 환경 변수로 정한 폴더 없음."""
    win.shares = []
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: False)
    monkeypatch.delenv(shared_config.CONFIG_DIR_ENV, raising=False)


def folder_picker_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: calls.append(a) or "")
    return calls


def window_kinds(dialogs):
    return [(kind, title) for kind, title, _text in dialogs.messages]


# ---------------------------------------------------------------- 읽는 쪽 (Mac): '찾지 못함'과 '진짜 문제'를 가름

@mac_only
def test_mac_without_the_config_folder_is_not_found(no_share_mac):
    state = shared_config_load.gather_shared_config()
    assert f"작품 경로 파일이 없습니다: {NO_SUCH_CONFIG}" in state.shared_config_problem
    assert "Traceback" in state.shared_config_problem
    assert state.config_not_found is True


@mac_only
def test_mac_share_without_the_config_folder_is_not_found(share_place):
    state = shared_config_load.gather_shared_config()
    assert "작품 경로 파일이 없습니다" in state.shared_config_problem
    assert state.config_not_found is True


@mac_only
def test_mac_folder_without_the_file_is_real_trouble(share_place):
    share_place.mkdir(parents=True)
    state = shared_config_load.gather_shared_config()
    assert "작품 경로 파일이 없습니다" in state.shared_config_problem
    assert state.config_not_found is False


@mac_only
def test_mac_broken_file_is_real_trouble(share_place):
    share_place.mkdir(parents=True)
    (share_place / "work_paths.json").write_text("{broken", encoding="utf-8")
    state = shared_config_load.gather_shared_config()
    assert "읽지 못했습니다" in state.shared_config_problem
    assert state.config_not_found is False


@mac_only
def test_mac_file_of_the_wrong_shape_is_real_trouble(share_place):
    share_place.mkdir(parents=True)
    (share_place / "work_paths.json").write_text('["a"]', encoding="utf-8")
    state = shared_config_load.gather_shared_config()
    assert "형식 오류" in state.shared_config_problem
    assert state.config_not_found is False


@mac_only
def test_mac_folder_that_may_not_be_opened_is_real_trouble(share_place):
    """권한이 없어 설정 폴더를 열지 못함 — 폴더가 보이지 않는 것과 같아 보이지만 고칠 수 있는 문제라 알림."""
    if os.geteuid() == 0:
        pytest.skip("root는 권한 없는 폴더도 열 수 있음")
    share_place.mkdir(parents=True)
    locked = share_place.parent
    locked.chmod(0)
    try:
        state = shared_config_load.gather_shared_config()
    finally:
        locked.chmod(0o755)
    assert "읽지 못했습니다" in state.shared_config_problem and "PermissionError" in state.shared_config_problem
    assert state.config_not_found is False


@mac_only
def test_folder_named_by_the_environment_that_is_not_there_is_not_found(mac_env, monkeypatch, tmp_path):
    monkeypatch.setenv(shared_config.CONFIG_DIR_ENV, str(tmp_path / "nowhere"))
    state = shared_config_load.gather_shared_config()
    assert "작품 경로 파일이 없습니다" in state.shared_config_problem
    assert state.config_not_found is True


@mac_only
def test_readable_config_is_no_problem(share_place):
    share_place.mkdir(parents=True)
    (share_place / "work_paths.json").write_text("{}", encoding="utf-8")
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem is None and state.config_not_found is False


@mac_only
def test_config_folder_that_does_not_answer_counts_as_not_found(share_place, monkeypatch):
    """파일을 읽지 못한 뒤 폴더가 있는지 물어도 정해진 시간 안에 답이 없음 (서버가 꺼짐) → 닿지 않는 것으로.
    (폴더는 만들어 둠 — 시간 제한 없이 물었다면 '있음'이 되어 진짜 문제로 갔을 자리)"""
    share_place.mkdir(parents=True)
    asked = []
    monkeypatch.setattr(path_map_setup, "probe", lambda func, path, *a, **k: asked.append((func, path)) and None)
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem and state.config_not_found is True
    assert asked == [(os.path.isdir, str(share_place))]


# ---------------------------------------------------------------- 읽는 쪽 (Windows)

def test_windows_without_any_config_folder_is_not_found(win, monkeypatch):  # noqa: F811
    no_shares_windows(win, monkeypatch)
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem == NOT_SET and state.config_dir_search_failed
    assert state.config_not_found is True


def test_windows_with_several_config_folders_is_asked_to_pick(win, monkeypatch):  # noqa: F811
    no_shares_windows(win, monkeypatch)
    a, b = "\\\\localhost\\yc_fake_a", "\\\\localhost\\yc_fake_b"
    win.shares = [path_map_setup.Share(a, ["A:"]), path_map_setup.Share(b, ["B:"])]
    targets = [f"{a}\\test_jn\\.yesoncheck", f"{b}\\test_jn\\.yesoncheck"]
    files = {f"{t}\\work_paths.json".casefold() for t in targets}
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: p.casefold() in files)
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem == NOT_SET and state.config_dir_candidates == targets
    assert state.config_not_found is False  # 찾은 폴더가 있음 → 창이 고르게 함


def test_windows_harmony_folder_that_cannot_be_followed_is_not_found(win, monkeypatch):  # noqa: F811
    """C:\\USA_DB 링크의 대상(NAS)에 닿지 않음 — 밖에서 켠 사내 노트북의 모습. 확인하지 못한 곳은 상태에 남음(기록용)."""
    no_shares_windows(win, monkeypatch)
    trouble = "C:\\USA_DB\\test_jn\\.yesoncheck — 실제 위치(링크 대상)를 알 수 없음: (가짜 재현)"
    monkeypatch.setattr(path_map_setup, "find_local_config_dir", lambda *a, **k: (None, trouble))
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem == NOT_SET and state.config_dir_search_problems == [trouble]
    assert state.config_not_found is True


def test_windows_saved_folder_that_no_longer_opens_is_not_found(win, monkeypatch):  # noqa: F811
    """PC별 설정에 적힌 폴더가 열리지 않음 — 밖에서 켠 사내 노트북, 또는 사내에서 NAS가 끊김."""
    no_shares_windows(win, monkeypatch)
    shared_config.save_local_settings({"config_dir": GONE_UNC})
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem and state.config_dir == GONE_UNC
    assert state.config_not_found is True


def test_windows_saved_folder_behind_a_network_error_is_not_found(win, monkeypatch):  # noqa: F811
    """서버에 닿지 않을 때 Windows가 '파일 없음'이 아닌 네트워크 오류를 낼 수도 있음 — 폴더가 보이지 않으면 그것도 찾지 못함."""
    no_shares_windows(win, monkeypatch)
    shared_config.save_local_settings({"config_dir": GONE_UNC})

    def unreachable(work_paths_file):
        try:
            raise OSError(1231, "The network location cannot be reached (가짜 재현)", work_paths_file)
        except OSError as exc:
            raise shared_config.SharedConfigError(f"작품 경로 파일을 읽지 못했습니다: {work_paths_file}\n{exc}") from exc

    monkeypatch.setattr(shared_config, "read_work_paths", unreachable)
    state = shared_config_load.gather_shared_config()
    assert "읽지 못했습니다" in state.shared_config_problem and "가짜 재현" in state.shared_config_problem
    assert state.config_not_found is True


def test_windows_found_folder_that_could_not_be_saved_is_real_trouble(win, monkeypatch):  # noqa: F811
    """공유 설정 폴더를 찾았는데 PC별 설정에 적지 못함 — 찾지 못한 것이 아니라 이 PC의 문제."""
    no_shares_windows(win, monkeypatch)
    share = "\\\\localhost\\yc_fake_cfg"
    win.shares = [path_map_setup.Share(share, ["U:"])]
    target = f"{share}\\test_jn\\.yesoncheck"
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: p.casefold() == f"{target}\\work_paths.json".casefold())

    def refuse(updates):
        raise OSError("디스크가 가득 참 (가짜 재현)")

    monkeypatch.setattr(shared_config, "save_local_settings", refuse)
    state = shared_config_load.gather_shared_config()
    assert "저장하지 못했습니다" in state.shared_config_problem and "가짜 재현" in state.shared_config_problem
    assert state.config_not_found is False


def test_windows_saved_folder_that_does_not_answer_is_not_found(win, monkeypatch):  # noqa: F811
    no_shares_windows(win, monkeypatch)
    shared_config.save_local_settings({"config_dir": GONE_UNC})
    monkeypatch.setattr(shared_config_load, "_config_dir_usable", lambda config_dir: None)
    state = shared_config_load.gather_shared_config()
    assert "응답하지 않습니다" in state.shared_config_problem and state.config_dir is None
    assert state.config_not_found is True


def test_windows_saved_folder_without_the_file_is_real_trouble(win, monkeypatch, tmp_path):  # noqa: F811
    """정해 둔 폴더는 열리는데 그 안에 작품 경로 파일이 없음 — 공유 설정이 망가진 것."""
    no_shares_windows(win, monkeypatch)
    folder = tmp_path / "cfg" / ".yesoncheck"
    folder.mkdir(parents=True)
    shared_config.save_local_settings({"config_dir": str(folder)})
    state = shared_config_load.gather_shared_config()
    assert "작품 경로 파일이 없습니다" in state.shared_config_problem
    assert state.config_not_found is False


def test_windows_broken_pc_settings_file_is_real_trouble(win, monkeypatch, tmp_path):  # noqa: F811
    no_shares_windows(win, monkeypatch)
    settings = tmp_path / "appdata" / "YesonCheck" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{broken", encoding="utf-8")
    state = shared_config_load.gather_shared_config()
    assert "PC별 설정 파일을 읽지 못했습니다" in state.shared_config_problem
    assert state.config_not_found is False


def test_windows_folder_named_by_the_environment_that_is_not_there_is_not_found(win, monkeypatch, tmp_path):  # noqa: F811
    no_shares_windows(win, monkeypatch)
    monkeypatch.setenv(shared_config.CONFIG_DIR_ENV, str(tmp_path / "nowhere"))
    state = shared_config_load.gather_shared_config()
    assert "작품 경로 파일이 없습니다" in state.shared_config_problem
    assert state.config_not_found is True


# ---------------------------------------------------------------- 창: 찾지 못했으면 조용히

@mac_only
def test_mac_gets_no_window_and_the_reason_goes_to_the_log(no_share_mac, players, dialogs, capsys):
    player = players()
    assert player.shared_config_not_found is True
    capsys.readouterr()
    player.resolve_shared_config_problem()
    assert dialogs.messages == []
    out = capsys.readouterr().out
    assert "[공유 설정]" in out and QUIET_LOG in out
    assert "작품 경로 파일이 없습니다" in out and "Traceback" in out  # 사유는 기록에 그대로
    assert "공유 설정 오류" in player.windowTitle()  # 창 제목의 표시는 그대로
    assert player.workPickerGroup.isHidden()  # 작품을 읽어 온 적이 없는 PC


@mac_only
def test_mac_that_has_read_works_before_is_quiet_too(no_share_mac, players, dialogs):
    """사내에서 쓰던 PC(노트북)를 밖에서 켬 = 사내에서 NAS가 끊김 — 앱은 둘을 구별하지 못하고, 어느 쪽이든 창은 없음 (사용자 결정)."""
    mac_prefs.update_pref(work_picker.PREF_KEY, True, hover_strip.prefs_path())
    player = players()
    player.resolve_shared_config_problem()
    assert dialogs.messages == []
    assert "공유 설정 오류" in player.windowTitle()
    assert not player.workPickerGroup.isHidden()  # 작품 묶음의 자리는 그대로 (안내 항목만)


@mac_only
def test_launch_path_shows_no_window_and_still_checks_for_updates(no_share_mac, players, dialogs, monkeypatch):
    from yesoncheck.main_window import VideoPlayer

    checks = []
    monkeypatch.setattr(VideoPlayer, "start_update_check", lambda self, manual=False: checks.append(manual))
    player = players(load_shared_config=False)
    player.start_shared_config_load()
    wait_until(lambda: not player.shared_config_loading)
    assert player.shared_config_problem and player.shared_config_not_found is True
    assert dialogs.messages == []
    assert checks == [False]


def test_windows_pc_gets_no_folder_picker_and_no_error_window(win, dialogs, monkeypatch, capsys):  # noqa: F811
    no_shares_windows(win, monkeypatch)
    picker = folder_picker_calls(monkeypatch)
    player = win.player()
    assert player.shared_config_not_found is True
    capsys.readouterr()
    player.resolve_shared_config_problem()
    assert dialogs.messages == [] and picker == []
    out = capsys.readouterr().out
    assert QUIET_LOG in out and NOT_SET in out


def test_windows_laptop_away_from_its_saved_folder_gets_no_window(win, dialogs, monkeypatch, capsys):  # noqa: F811
    no_shares_windows(win, monkeypatch)
    shared_config.save_local_settings({"config_dir": GONE_UNC})
    picker = folder_picker_calls(monkeypatch)
    player = win.player()
    assert player.shared_config_not_found is True
    capsys.readouterr()
    player.resolve_shared_config_problem()
    assert dialogs.messages == [] and picker == []
    assert QUIET_LOG in capsys.readouterr().out
    assert shared_config.load_local_settings() == {"config_dir": GONE_UNC}  # 정해 둔 폴더는 그대로 (돌아오면 다시 읽음)


def test_places_that_could_not_be_checked_go_to_the_log(win, dialogs, monkeypatch, capsys):  # noqa: F811
    no_shares_windows(win, monkeypatch)
    line = "Z: 연결 정보를 읽지 못함 (가짜 재현)"
    monkeypatch.setattr(path_map_setup, "connected_shares", lambda remote_of_drive=None: ([], [line]))
    player = win.player()
    assert player.config_dir_search_problems == [line]
    capsys.readouterr()
    player.resolve_shared_config_problem()
    assert dialogs.messages == []
    assert line in capsys.readouterr().out


# ---------------------------------------------------------------- 창: 진짜 문제는 그대로 알림

@mac_only
def test_broken_file_is_still_told_on_a_mac(share_place, players, dialogs):
    share_place.mkdir(parents=True)
    (share_place / "work_paths.json").write_text("{broken", encoding="utf-8")
    player = players()
    assert player.shared_config_not_found is False
    player.resolve_shared_config_problem()
    assert window_kinds(dialogs) == [("critical", "공유 설정 오류")]
    assert "읽지 못했습니다" in dialogs.criticals[0] and "작품 목록 없이 계속합니다" in dialogs.criticals[0]


@mac_only
def test_folder_without_the_file_is_still_told_on_a_mac(share_place, players, dialogs):
    share_place.mkdir(parents=True)
    player = players()
    player.resolve_shared_config_problem()
    assert window_kinds(dialogs) == [("critical", "공유 설정 오류")]
    assert "작품 경로 파일이 없습니다" in dialogs.criticals[0]


def test_saved_folder_without_the_file_is_still_asked_about_on_windows(win, dialogs, monkeypatch, tmp_path):  # noqa: F811
    no_shares_windows(win, monkeypatch)
    folder = tmp_path / "cfg" / ".yesoncheck"
    folder.mkdir(parents=True)
    shared_config.save_local_settings({"config_dir": str(folder)})
    picker = folder_picker_calls(monkeypatch)
    player = win.player()
    assert player.shared_config_not_found is False
    player.resolve_shared_config_problem()
    assert window_kinds(dialogs) == [("information", "공유 설정 폴더 선택"), ("critical", "공유 설정 오류")]
    assert len(picker) == 1


# ---------------------------------------------------------------- 메뉴로 부르는 길은 그대로 (사유는 여기서 봄)

@mac_only
def test_work_path_manager_still_says_why(no_share_mac, players, dialogs):
    player = players()
    player.manage_work_paths()
    assert window_kinds(dialogs) == [("warning", "작품 경로 관리")]
    assert "관리할 수 없습니다" in dialogs.warnings[0] and "작품 경로 파일이 없습니다" in dialogs.warnings[0]


def test_work_path_manager_also_lists_the_places_that_could_not_be_checked(win, dialogs, monkeypatch):  # noqa: F811
    """시작할 때의 폴더 고르기 창이 보여 주던 '확인하지 못한 곳'은 이제 여기(와 기록)에서 봄."""
    no_shares_windows(win, monkeypatch)
    line = "Z: 연결 정보를 읽지 못함 (가짜 재현)"
    monkeypatch.setattr(path_map_setup, "connected_shares", lambda remote_of_drive=None: ([], [line]))
    player = win.player()
    player.manage_work_paths()
    assert window_kinds(dialogs) == [("warning", "작품 경로 관리")]
    assert NOT_SET in dialogs.warnings[0] and line in dialogs.warnings[0]


def test_choosing_the_folder_from_the_menu_still_asks(win, dialogs, monkeypatch):  # noqa: F811
    no_shares_windows(win, monkeypatch)
    picker = folder_picker_calls(monkeypatch)
    player = win.player()
    assert player.choose_shared_config_dir() is False  # 고르지 않고 닫음
    assert len(picker) == 1
