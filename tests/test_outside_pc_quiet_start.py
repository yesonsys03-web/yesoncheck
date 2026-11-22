"""회사 밖 PC에서는 시작할 때 공유 설정 알림 창을 띄우지 않는다 (사용자 요청 2026-11-23).

예손 사내 공유 설정(작품 경로)이 없는 PC에서는 켤 때마다 '공유 설정 오류' 창이 떴다 (Windows는 그 전에 '공유 설정 폴더 선택' 안내와
폴더 고르기 창까지). 회사 밖에서는 쓰지 않는 기능의 알림이라, 다음 둘이 모두 참이면 창 없이 기록만 남긴다:

- 이 PC에 공유 설정이 아예 없음 (`SharedConfigState.config_missing`) — 설정을 찾지 못했고 **사내 공유를 쓰던 흔적도 없음**:
  Mac은 공유의 앞부분(/USA_DB)이 이 Mac에 없고 자동 연결 설정·fstab에도 그 이름의 공유가 없음, Windows는 정해 둔 폴더가 없고 이 PC의
  공유에서 하나도 못 찾았으며 Harmony식 `C:\\USA_DB`(폴더·링크)·`C:\\USA_DB.lnk`도 없음
- 이 PC에서 작품을 읽어 온 적이 없음 (prefs.json의 `work_picker_seen` — 사이드바의 작품 묶음을 숨기는 것과 같은 기억)

그 밖은 예전처럼 창으로 알린다: 작품을 읽어 온 적이 있는 PC(사내 PC의 NAS 끊김), 흔적이 있는 PC, 폴더는 있는데 파일이 없거나 깨짐·권한
없음, 환경 변수로 정한 폴더, Windows에서 정해 둔 폴더가 열리지 않음·설정 폴더를 여럿 찾음(test_path_map_auto_ui의
test_multiple_config_dirs_pick_one)·Harmony식 폴더를 확인하다 문제가 남(같은 파일의
test_harmony_link_realpath_error_shown_when_nothing_found), 예상 못 한 오류(test_fast_startup), 그 기억을 읽지 못함.
"""

import os
import sys

import pytest
from PyQt5.QtWidgets import QFileDialog

from tests.test_fast_startup import wait_until
from tests.test_mac_mounts import NO_SUCH_CONFIG, write
from tests.test_path_map_auto_ui import win  # noqa: F401 (fixture)
from tests.test_work_paths_ui import remember_works_were_read
from yesoncheck import hover_strip, mac_mounts, path_map_setup, paths, shared_config, shared_config_load

mac_only = pytest.mark.skipif(sys.platform == "win32", reason="Mac의 공유 자리(POSIX 경로·자동 연결 설정) — Windows 동작은 win 픽스처의 시험")

NOT_SET = "공유 설정 폴더가 아직 정해지지 않았습니다."
AUTOMOUNT_SHARE = "yc_quiet_share"  # 어느 Mac에도 /yc_quiet_share는 없음 — 자동 연결 설정으로만 아는 공유
QUIET_LOG = "창으로 알리지 않음"


@pytest.fixture
def mac_env(qapp, monkeypatch):
    """Mac 동작, 환경 변수로 정한 공유 설정 폴더 없음."""
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    monkeypatch.delenv(shared_config.CONFIG_DIR_ENV, raising=False)


@pytest.fixture
def outside_mac(mac_env, monkeypatch, tmp_path):
    """회사 밖 Mac (사용자 스크린숏의 Mac): 공유의 앞부분이 이 Mac에 없고 자동 연결 설정·fstab에도 그 이름의 공유가 없음."""
    monkeypatch.setattr(shared_config, "MAC_CONFIG_DIR", NO_SUCH_CONFIG)
    paths.activate_mount_map(mac_mounts.read_mount_map(root=str(tmp_path / "mac")))  # 자동 연결 설정이 없는 Mac


@pytest.fixture
def share_place(mac_env, monkeypatch, tmp_path):
    """공유의 앞부분이 이 Mac에 있는 Mac(공유가 붙어 있는 사내 Mac) → 그 아래 설정 폴더가 놓일 자리 (아직 만들지 않음).
    자리는 진짜 폴더(tmp) 아래이고 자동 연결 설정은 읽지 않은 채(None)라, 흔적은 그 경로의 맨 앞 이름(/private 등)이 이 Mac에
    있다는 데서 옴 — tmp 아래의 USA_DB 폴더를 만들었는지와는 무관. '앞부분의 폴더가 있어서'라는 까닭 자체는
    test_share_trace_with_automount_settings_read_sees_a_share_folder_on_this_mac·test_share_trace_is_assumed_…가 지킴."""
    place = tmp_path / "USA_DB" / "test_jn" / ".yesoncheck"
    monkeypatch.setattr(shared_config, "MAC_CONFIG_DIR", str(place))
    return place


@pytest.fixture
def automount_mac(mac_env, monkeypatch, tmp_path):
    """자동 연결 설정에 공유 설정의 공유가 있는 사내 Mac인데 NAS가 붙지 않아 설정 폴더가 안 보임 → 열어 보는 설정 폴더.
    (공유의 앞부분은 이 Mac에 없고 자동 연결 폴더 아래에 붙는 모양 — test_mac_mounts의 mac_b처럼. 주소는 지어낸 것)"""
    root = tmp_path / "mac"
    mnt = root / "System" / "Volumes" / "Data" / "mnt"
    write(root / "etc" / "auto_master", "/System/Volumes/Data/mnt auto_yc\n")
    write(root / "etc" / "auto_yc", f"{AUTOMOUNT_SHARE} -fstype=nfs,rw nfs://nas.example:/data/{AUTOMOUNT_SHARE}\n")
    (mnt / AUTOMOUNT_SHARE).mkdir(parents=True)  # 붙지 않은 빈 자동 연결 폴더
    monkeypatch.setattr(shared_config, "MAC_CONFIG_DIR", f"/{AUTOMOUNT_SHARE}/test_jn/.yesoncheck")
    paths.activate_mount_map(mac_mounts.read_mount_map(root=str(root)))
    return str(mnt / AUTOMOUNT_SHARE / "test_jn" / ".yesoncheck")


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


def outside_windows(win, monkeypatch):  # noqa: F811
    """회사 밖 Windows PC: 정해 둔 공유 설정 폴더가 없고, 네트워크 드라이브도 Harmony식 폴더·바로 가기도 없음."""
    win.shares = []
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: False)
    monkeypatch.delenv(shared_config.CONFIG_DIR_ENV, raising=False)


def system_drive_item(tmp_path, name):
    """win 픽스처의 %SystemDrive% 바로 아래 항목의 경로 (C:\\USA_DB 자리)."""
    return str(tmp_path / "sysdrive") + "\\" + name


def folder_picker_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: calls.append(a) or "")
    return calls


def window_kinds(dialogs):
    return [(kind, title) for kind, title, _text in dialogs.messages]


# ---------------------------------------------------------------- 읽는 쪽 (Mac): '없음'과 '망가짐·흔적 있음'을 가름

@mac_only
def test_mac_with_no_trace_of_the_share_is_marked_missing(outside_mac):
    state = shared_config_load.gather_shared_config()
    assert f"작품 경로 파일이 없습니다: {NO_SUCH_CONFIG}" in state.shared_config_problem
    assert "공유도 자동 연결 설정·fstab에 없음" in state.shared_config_problem and "Traceback" in state.shared_config_problem
    assert state.config_missing is True


@mac_only
def test_mac_with_no_trace_is_missing_even_when_the_automount_settings_were_not_read(mac_env, monkeypatch):
    monkeypatch.setattr(shared_config, "MAC_CONFIG_DIR", NO_SUCH_CONFIG)
    assert paths.active_mount_map() is None
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem and state.config_missing is True


@mac_only
def test_mac_with_the_share_but_no_config_folder_is_trouble_not_missing(share_place):
    """공유의 앞부분은 이 Mac에 있는데 그 아래 설정 폴더가 없음 — 공유를 쓰는 Mac이므로 알릴 일."""
    state = shared_config_load.gather_shared_config()
    assert "작품 경로 파일이 없습니다" in state.shared_config_problem
    assert state.config_missing is False


@mac_only
def test_mac_with_the_share_in_its_automount_settings_is_trouble_not_missing(automount_mac):
    assert mac_mounts.share_trace(None, shared_config.MAC_CONFIG_DIR) is False  # 이 Mac의 폴더로는 흔적이 없음 — 설정으로만 앎
    state = shared_config_load.gather_shared_config()
    assert f"작품 경로 파일이 없습니다: {automount_mac}" in state.shared_config_problem
    assert state.config_missing is False


@mac_only
def test_mac_folder_without_the_file_is_trouble_not_missing(share_place):
    share_place.mkdir(parents=True)
    state = shared_config_load.gather_shared_config()
    assert "작품 경로 파일이 없습니다" in state.shared_config_problem
    assert state.config_missing is False


@mac_only
def test_mac_broken_file_is_trouble_not_missing(share_place, monkeypatch):
    """읽다 난 문제(깨진 파일)는 '없음'이 아님 — 공유의 흔적이 없다고 나와도. 파일이 없을 때만 '없음'."""
    monkeypatch.setattr(mac_mounts, "share_trace", lambda *a, **k: False)
    share_place.mkdir(parents=True)
    (share_place / "work_paths.json").write_text("{broken", encoding="utf-8")
    state = shared_config_load.gather_shared_config()
    assert "읽지 못했습니다" in state.shared_config_problem
    assert state.config_missing is False


@mac_only
def test_mac_folder_that_cannot_be_looked_into_is_trouble_not_missing(share_place, monkeypatch):
    """설정 폴더의 위 폴더를 열 권한이 없음 — 읽다 난 문제이지 '없음'이 아님 (공유의 흔적이 없다고 나와도)."""
    if os.geteuid() == 0:
        pytest.skip("root는 권한 없는 폴더도 열 수 있음")
    monkeypatch.setattr(mac_mounts, "share_trace", lambda *a, **k: False)
    share_place.mkdir(parents=True)
    locked = share_place.parent
    locked.chmod(0)
    try:
        state = shared_config_load.gather_shared_config()
    finally:
        locked.chmod(0o755)
    assert "읽지 못했습니다" in state.shared_config_problem and "PermissionError" in state.shared_config_problem
    assert state.config_missing is False


@mac_only
def test_folder_named_by_the_environment_is_never_missing(outside_mac, monkeypatch, tmp_path):
    monkeypatch.setenv(shared_config.CONFIG_DIR_ENV, str(tmp_path / "nowhere"))
    state = shared_config_load.gather_shared_config()
    assert "작품 경로 파일이 없습니다" in state.shared_config_problem
    assert state.config_missing is False


@mac_only
def test_readable_config_is_not_missing(share_place):
    share_place.mkdir(parents=True)
    (share_place / "work_paths.json").write_text("{}", encoding="utf-8")
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem is None and state.config_missing is False


@mac_only
def test_share_trace_is_assumed_when_it_cannot_be_checked(monkeypatch):
    """공유의 앞부분이 이 Mac에 있는지 확인하지 못하면 흔적이 있는 쪽 — 모르면 알리는 쪽."""
    def refuse(path):
        raise PermissionError(13, "Permission denied", path)

    assert mac_mounts.share_trace(None, NO_SUCH_CONFIG) is False
    monkeypatch.setattr(mac_mounts, "_exists", refuse)
    assert mac_mounts.share_trace(None, NO_SUCH_CONFIG) is True


@mac_only
def test_share_trace_with_automount_settings_read_sees_a_share_folder_on_this_mac(tmp_path):
    """자동 연결 설정에 그 공유가 없어도 앞부분의 폴더가 이 Mac에 있으면 흔적 (손으로 붙인 공유·붙는 자리)."""
    (tmp_path / "mac" / "yc_here").mkdir(parents=True)
    mount_map = mac_mounts.read_mount_map(root=str(tmp_path / "mac"))
    assert mount_map.mounts == []
    assert mac_mounts.share_trace(mount_map, "/yc_here/test_jn/.yesoncheck") is True
    assert mac_mounts.share_trace(mount_map, "/yc_gone/test_jn/.yesoncheck") is False


# ---------------------------------------------------------------- 읽는 쪽 (Windows)

def test_windows_without_any_config_folder_is_marked_missing(win, monkeypatch):  # noqa: F811
    outside_windows(win, monkeypatch)
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem == NOT_SET and state.config_dir_search_failed
    assert state.config_missing is True


def test_windows_with_several_config_folders_is_not_missing(win, monkeypatch):  # noqa: F811
    outside_windows(win, monkeypatch)
    a, b = "\\\\localhost\\yc_fake_a", "\\\\localhost\\yc_fake_b"
    win.shares = [path_map_setup.Share(a, ["A:"]), path_map_setup.Share(b, ["B:"])]
    targets = [f"{a}\\test_jn\\.yesoncheck", f"{b}\\test_jn\\.yesoncheck"]
    files = {f"{t}\\work_paths.json".casefold() for t in targets}
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: p.casefold() in files)
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem == NOT_SET and state.config_dir_candidates == targets
    assert state.config_missing is False  # 찾은 폴더가 있음 → 고르게 함


def test_windows_with_a_harmony_folder_it_could_not_use_is_not_missing(win, monkeypatch):  # noqa: F811
    """C:\\USA_DB 링크·바로 가기를 확인하다 문제가 남 — 예손 설정이 된 PC이므로 알릴 일 (작품을 읽어 온 적이 없어도)."""
    outside_windows(win, monkeypatch)
    trouble = "C:\\USA_DB\\test_jn\\.yesoncheck — 실제 위치(링크 대상)를 알 수 없음: (가짜 재현)"
    monkeypatch.setattr(path_map_setup, "find_local_config_dir", lambda *a, **k: (None, trouble))
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem == NOT_SET and state.config_dir_search_failed
    assert state.config_dir_search_problems == [trouble]
    assert state.config_missing is False


def test_windows_with_a_usa_db_folder_that_holds_no_config_is_not_missing(win, monkeypatch, tmp_path):  # noqa: F811
    """C:\\USA_DB가 (링크든 폴더든) 있는데 그 아래에 설정이 없음 — 찾기는 문제 줄 없이 지나가지만 예손 설정의 흔적."""
    outside_windows(win, monkeypatch)
    top = system_drive_item(tmp_path, "USA_DB")
    win.folders.add(top.casefold())
    monkeypatch.setattr(path_map_setup, "_path_kind", lambda p: "디렉터리 링크" if p == top else "없음")
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem == NOT_SET and state.config_dir_search_failed
    assert state.config_dir_search_problems == []  # 문제 줄은 없음 — 흔적만
    assert state.config_missing is False


def test_windows_with_a_usa_db_shortcut_that_leads_to_no_config_is_not_missing(win, monkeypatch, tmp_path):  # noqa: F811
    outside_windows(win, monkeypatch)
    lnk = system_drive_item(tmp_path, "USA_DB.lnk")
    monkeypatch.setattr(path_map_setup, "find_local_config_dir", lambda *a, **k: (None, None))  # 바로 가기 대상에 설정이 없음
    monkeypatch.setattr(path_map_setup, "_default_is_file", lambda p: p == lnk)
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem == NOT_SET and state.config_dir_search_problems == []
    assert state.config_missing is False


def test_harmony_folder_trace_names_what_is_on_the_system_drive(monkeypatch):
    kinds, files = {}, set()
    monkeypatch.setattr(path_map_setup, "_path_kind", lambda p: kinds.get(p, "없음"))

    def trace():
        return path_map_setup.harmony_folder_trace(drive="C:", is_file=lambda p: p in files)

    assert trace() is None
    files.add("C:\\USA_DB.lnk")
    assert "C:\\USA_DB.lnk" in trace()
    kinds["C:\\USA_DB"] = "폴더"
    assert "C:\\USA_DB" in trace() and "폴더" in trace() and ".lnk" not in trace()
    kinds["C:\\USA_DB"] = "종류를 알 수 없음 (가짜 재현)"  # 확인하지 못해도 흔적이 있는 쪽
    assert "가짜 재현" in trace()


def test_windows_saved_folder_that_no_longer_opens_is_not_missing(win, monkeypatch):  # noqa: F811
    """PC별 설정에 폴더가 적혀 있으면 사내에서 쓰던 PC — 열리지 않는 것은 알릴 일."""
    outside_windows(win, monkeypatch)
    shared_config.save_local_settings({"config_dir": "\\\\localhost\\yc_fake_gone\\test_jn\\.yesoncheck"})
    state = shared_config_load.gather_shared_config()
    assert state.shared_config_problem and state.config_missing is False


def test_windows_folder_named_by_the_environment_is_never_missing(win, monkeypatch, tmp_path):  # noqa: F811
    outside_windows(win, monkeypatch)
    monkeypatch.setenv(shared_config.CONFIG_DIR_ENV, str(tmp_path / "nowhere"))
    state = shared_config_load.gather_shared_config()
    assert "작품 경로 파일이 없습니다" in state.shared_config_problem
    assert state.config_missing is False


# ---------------------------------------------------------------- 창: 회사 밖 PC는 조용히

@mac_only
def test_outside_mac_gets_no_window_and_the_reason_goes_to_the_log(outside_mac, players, dialogs, capsys):
    player = players()
    assert player.shared_config_missing is True and player._work_picker_seen is False
    capsys.readouterr()
    player.resolve_shared_config_problem()
    assert dialogs.messages == []
    out = capsys.readouterr().out
    assert "[공유 설정]" in out and QUIET_LOG in out
    assert "작품 경로 파일이 없습니다" in out and "Traceback" in out  # 사유는 기록에 그대로
    assert "공유 설정 오류" in player.windowTitle()  # 창 제목의 표시는 그대로
    assert player.workPickerGroup.isHidden()


@mac_only
def test_launch_path_on_an_outside_mac_shows_no_window_and_still_checks_for_updates(outside_mac, players, dialogs, monkeypatch):
    from yesoncheck.main_window import VideoPlayer

    checks = []
    monkeypatch.setattr(VideoPlayer, "start_update_check", lambda self, manual=False: checks.append(manual))
    player = players(load_shared_config=False)
    player.start_shared_config_load()
    wait_until(lambda: not player.shared_config_loading)
    assert player.shared_config_problem and player.shared_config_missing is True
    assert dialogs.messages == []
    assert checks == [False]


def test_outside_windows_pc_gets_no_folder_picker_and_no_error_window(win, dialogs, monkeypatch, capsys):  # noqa: F811
    outside_windows(win, monkeypatch)
    picker = folder_picker_calls(monkeypatch)
    player = win.player()
    assert player.shared_config_missing is True and player._work_picker_seen is False
    capsys.readouterr()
    player.resolve_shared_config_problem()
    assert dialogs.messages == [] and picker == []
    out = capsys.readouterr().out
    assert QUIET_LOG in out and NOT_SET in out


def test_places_that_could_not_be_checked_go_to_the_log_on_an_outside_windows_pc(win, dialogs, monkeypatch, capsys):  # noqa: F811
    outside_windows(win, monkeypatch)
    line = "Z: 연결 정보를 읽지 못함 (가짜 재현)"
    monkeypatch.setattr(path_map_setup, "connected_shares", lambda remote_of_drive=None: ([], [line]))
    player = win.player()
    assert player.config_dir_search_problems == [line]
    capsys.readouterr()
    player.resolve_shared_config_problem()
    assert dialogs.messages == []
    assert line in capsys.readouterr().out


# ---------------------------------------------------------------- 창: 알릴 일은 그대로 알림

@mac_only
def test_mac_that_has_read_works_before_is_still_told(outside_mac, players, dialogs):
    remember_works_were_read()
    player = players()
    assert player.shared_config_missing is True and player._work_picker_seen is True
    player.resolve_shared_config_problem()
    assert window_kinds(dialogs) == [("critical", "공유 설정 오류")]
    assert "작품 경로 파일이 없습니다" in dialogs.criticals[0] and "작품 목록 없이 계속합니다" in dialogs.criticals[0]


@mac_only
def test_mac_with_the_share_in_its_automount_settings_is_told_before_it_ever_read_a_work(automount_mac, players, dialogs):
    """사내에 새로 설치한 Mac이 처음 켤 때 NAS가 붙지 않음 — 공유를 쓰게 되어 있는 Mac이므로 알림."""
    player = players()
    assert player.shared_config_missing is False and player._work_picker_seen is False
    player.resolve_shared_config_problem()
    assert window_kinds(dialogs) == [("critical", "공유 설정 오류")]
    assert "NAS 연결을 확인하세요" in dialogs.criticals[0]


@mac_only
def test_trouble_on_a_mac_that_never_read_works_is_still_told(share_place, players, dialogs):
    """폴더는 있는데 파일이 깨짐 — 없는 것이 아니라 망가진 것."""
    share_place.mkdir(parents=True)
    (share_place / "work_paths.json").write_text("{broken", encoding="utf-8")
    player = players()
    assert player.shared_config_missing is False and player._work_picker_seen is False
    player.resolve_shared_config_problem()
    assert window_kinds(dialogs) == [("critical", "공유 설정 오류")]
    assert "읽지 못했습니다" in dialogs.criticals[0]


@mac_only
def test_unreadable_memory_of_reading_works_is_told(outside_mac, players, dialogs):
    """prefs.json을 읽지 못하면 작품을 읽어 온 적이 있는지 모름 — 모르면 알리는 쪽."""
    path = hover_strip.prefs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{ 깨진 JSON")
    player = players()
    assert player.shared_config_missing is True and player._work_picker_seen is None
    player.resolve_shared_config_problem()
    assert window_kinds(dialogs) == [("critical", "공유 설정 오류")]


def test_windows_pc_that_has_read_works_before_is_asked_for_the_folder(win, dialogs, monkeypatch):  # noqa: F811
    outside_windows(win, monkeypatch)
    remember_works_were_read()
    picker = folder_picker_calls(monkeypatch)
    player = win.player()
    player.resolve_shared_config_problem()
    assert window_kinds(dialogs) == [("information", "공유 설정 폴더 선택"), ("critical", "공유 설정 오류")]
    assert len(picker) == 1


def test_windows_pc_with_a_usa_db_folder_is_asked_for_the_folder_before_it_ever_read_a_work(win, dialogs, monkeypatch, tmp_path):  # noqa: F811
    """사내에 새로 설치한 PC(C:\\USA_DB가 있음)가 설정을 찾지 못함 — 예손 설정이 된 PC이므로 폴더를 고르게 함."""
    outside_windows(win, monkeypatch)
    top = system_drive_item(tmp_path, "USA_DB")
    win.folders.add(top.casefold())
    monkeypatch.setattr(path_map_setup, "_path_kind", lambda p: "폴더" if p == top else "없음")
    picker = folder_picker_calls(monkeypatch)
    player = win.player()
    assert player.shared_config_missing is False and player._work_picker_seen is False
    player.resolve_shared_config_problem()
    assert window_kinds(dialogs) == [("information", "공유 설정 폴더 선택"), ("critical", "공유 설정 오류")]
    assert len(picker) == 1


# ---------------------------------------------------------------- 조용한 PC에서도 메뉴로는 그대로

@mac_only
def test_work_path_manager_on_an_outside_mac_still_says_why(outside_mac, players, dialogs):
    player = players()
    player.manage_work_paths()
    assert window_kinds(dialogs) == [("warning", "작품 경로 관리")]
    assert "관리할 수 없습니다" in dialogs.warnings[0] and "작품 경로 파일이 없습니다" in dialogs.warnings[0]


def test_choosing_the_folder_from_the_menu_still_asks_on_an_outside_windows_pc(win, dialogs, monkeypatch):  # noqa: F811
    outside_windows(win, monkeypatch)
    picker = folder_picker_calls(monkeypatch)
    player = win.player()
    assert player.choose_shared_config_dir() is False  # 고르지 않고 닫음
    assert len(picker) == 1
