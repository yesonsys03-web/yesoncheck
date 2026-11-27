"""회사 밖 PC에서 혼자(스탠드얼론) 쓰기 — 공유 설정이 없어도, 시작 알림 창이 없어도 쓰는 데 아무 문제가 없어야 한다
(사용자 요구 2026-11-23: "이 팝업창이 뜨지 않아도 회사 밖 컴에서 사용하는데 아무런 문제가 없어야 해").

공유 설정을 찾지 못한 채 켠 창에서 회사 밖 사용자가 하는 일을 그대로 한다 — 켜기, 영상 열기·프레임 이동, B를 열어 와이프, 폴더를 목록에
넣기, 북마크, 주석 저장·다시 읽기, 저장되는 경로, 자동 업데이트 확인 — 그동안 **경고·오류 창이 하나도 뜨지 않아야** 하고 결과가 맞아야 함.
작품 고르기와 작품 경로 관리(사내 전용)만 못 씀 (그 안내는 test_quiet_start_without_shared_config).

이 OS 그대로 돈다 (paths.IS_WINDOWS를 바꾸지 않음): Mac은 공유 설정의 자리가 없는 Mac, Windows(CI)는 정해 둔 폴더·네트워크 드라이브·
Harmony식 폴더가 없고 변환표도 없는 PC — 그래서 Windows의 변환표 없는 경로 처리(to_storage·thumbnail_key)도 진짜로 지나감.
"""

import json
import os
import sys

import pytest

from tests.conftest import write_test_video
from tests.test_fast_startup import wait_until
from tests.test_mac_mounts import NO_SUCH_CONFIG
from tests.test_sidebar_refresh import wait_refreshed
from tests.test_update_ui import _built_app, check_now, fake_check  # noqa: F401 (fake_check: fixture)
from yesoncheck import frame_annotations, path_map_setup, paths, shared_config


@pytest.fixture
def standalone(qapp, dialogs, monkeypatch, tmp_path):
    """회사 밖 PC에서 app.launch처럼 켠 창: 공유 설정 없이 만들어 보인 뒤 뒤 스레드로 읽음 → 찾지 못함. 창이 하나도 안 뜬 것까지 확인."""
    from yesoncheck.main_window import VideoPlayer

    monkeypatch.delenv(shared_config.CONFIG_DIR_ENV, raising=False)
    if sys.platform == "win32":
        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))  # PC별 설정 없음
        monkeypatch.setenv("SystemDrive", str(tmp_path / "sysdrive"))  # Harmony식 폴더 없음
        monkeypatch.setattr(path_map_setup, "connected_shares", lambda remote_of_drive=None: ([], []))
        monkeypatch.setattr(path_map_setup, "local_link_shares", lambda *a, **k: ([], []))
    else:
        monkeypatch.setattr(shared_config, "MAC_CONFIG_DIR", NO_SUCH_CONFIG)
    player = VideoPlayer(load_shared_config=False)
    try:
        player.show()
        player.start_shared_config_load()
        wait_until(lambda: not player.shared_config_loading)
        assert player.shared_config_problem and player.shared_config_not_found is True
        assert player.work_paths == {} and dialogs.messages == []
        yield player
    finally:
        player.close()
        paths.activate(None)


def video_in(folder, name):
    return write_test_video(os.path.join(str(folder), name))


def test_start_is_quiet_and_only_the_work_picker_is_missing(standalone, dialogs):
    assert dialogs.messages == []
    assert standalone.workPickerGroup.isHidden()
    assert "공유 설정 오류" not in standalone.windowTitle()  # 창 제목에도 표시 없음 (2026-11-27 — 전에는 제목에만 남겼음)
    for button in (standalone.openFolderButton, standalone.listModeButton):
        assert button.isEnabled()


def test_opening_and_stepping_through_a_video(standalone, dialogs, tmp_path):
    video = video_in(tmp_path / "clips", "a.mp4")
    standalone.open_file("A", video)
    assert standalone.cap_a is not None and paths.same_path(standalone.filename_a, video)
    assert standalone.frame_a is not None
    standalone.seek_to_frame(10)
    assert standalone.frame_a is not None
    assert dialogs.messages == []


def test_comparing_two_videos_with_a_wipe(standalone, dialogs, tmp_path):
    a = video_in(tmp_path / "clips", "a.mp4")
    b = video_in(tmp_path / "clips", "b.mp4")
    standalone.open_file("A", a)
    assert standalone.open_b_and_wipe(b)
    assert standalone.cap_b is not None and standalone.videoWidget.wipe_enabled_x
    assert dialogs.messages == []


def test_loading_a_folder_into_the_sidebar(standalone, dialogs, tmp_path):
    folder = tmp_path / "shots"
    for name in ("s01.mp4", "s02.mp4", "s03.mp4"):
        video_in(folder, name)
    standalone.load_videos_from_folder(str(folder))
    assert standalone.sidebar.count() == 3
    assert paths.same_path(standalone.filename_a, str(folder / "s01.mp4"))  # 첫 영상이 A에 열림
    assert [(kind, title) for kind, title, _text in dialogs.messages] == [("information", "폴더 로드 완료")]  # 평소의 안내뿐


def test_refreshing_the_list_picks_up_a_new_video(standalone, dialogs, tmp_path):
    folder = tmp_path / "shots"
    for name in ("s01.mp4", "s02.mp4"):
        video_in(folder, name)
    standalone.load_videos_from_folder(str(folder))
    assert standalone.sidebar.count() == 2
    video_in(folder, "s03.mp4")
    standalone._refresh_sidebar_by_user()  # 새로고침 단추·F5
    wait_refreshed(standalone)
    assert standalone.sidebar.count() == 3
    assert dialogs.errors() == []


def test_bookmarking_a_folder(standalone, dialogs, tmp_path):
    folder = tmp_path / "shots"
    folder.mkdir()
    dialogs.folders.append(str(folder))
    standalone.add_bookmark()
    assert paths.contains_path(standalone.bookmarks, str(folder))
    assert dialogs.errors() == []  # '북마크 추가' 안내 창만


def test_annotations_are_saved_next_to_the_video_and_read_back(standalone, dialogs, tmp_path):
    video = video_in(tmp_path / "clips", "a.mp4")
    standalone.open_file("A", video)
    standalone.annotation_store.add(3, {"type": "rect", "norm_x1": 0.2, "norm_y1": 0.2, "norm_x2": 0.6, "norm_y2": 0.6,
                                        "color": "#ff3333", "stroke_width": 2})
    assert standalone.auto_save_annotations() is True
    saved = frame_annotations.annotation_file_path(standalone.filename_a)
    with open(saved, encoding="utf-8") as fh:
        data = json.load(fh)
    assert paths.same_path(data["video_path"], video)  # 이 PC의 경로 그대로 (변환표 없이)
    standalone.open_file("A", video)  # 다시 열면 읽어 옴
    assert standalone.annotation_store.total_count() == 1
    assert dialogs.messages == []


def test_stored_paths_and_thumbnail_names_work_without_a_path_map(standalone, tmp_path):
    video = video_in(tmp_path / "clips", "a.mp4")
    stored = paths.to_storage(video)
    assert stored == video  # 로컬 영상은 경로 그대로 적음
    assert paths.from_storage(stored) == video
    assert len(paths.thumbnail_key(video)) == 32


def test_automatic_update_check_is_quiet_and_leaves_the_nas_alone(standalone, dialogs, monkeypatch, fake_check, tmp_state_dir):  # noqa: F811
    _built_app(monkeypatch, "1.1.0")  # 빌드한 앱처럼 (소스 실행은 업데이트를 확인하지 않음)
    check_now(standalone)
    [(_current, _platform_key, config_dir, _base_url)] = fake_check.calls
    assert config_dir is None  # 찾지 못한 공유 설정 폴더(NAS)를 다시 읽지 않음 — GitHub만
    assert dialogs.messages == []


def test_manual_update_check_says_the_share_was_not_found_without_alarm(standalone, dialogs, monkeypatch, tmp_state_dir):
    """Help → 업데이트 확인…: NAS 쪽은 확인하지 못했다고만 보임 — 경고 창이 아니라 안내 창 (진짜 updates.check, GitHub 확인은 끔)."""
    _built_app(monkeypatch, "1.1.0")
    check_now(standalone, manual=True)
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("information", "업데이트 확인")
    assert "NAS: 확인하지 못함" in text and "찾지 못함" in text


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX의 '폴더가 아님' 오류로 재현 (Windows의 네트워크 오류 자리)")
def test_automatic_update_check_shows_no_window_when_the_share_answers_with_an_error(qapp, dialogs, monkeypatch, tmp_path, tmp_state_dir):
    """공유 설정을 찾지 못한 PC의 자동 업데이트 확인이 그 폴더를 다시 읽다 '파일 없음'이 아닌 오류를 만나면 '새 버전을 확인하다 문제가
    생겼습니다' 창이 켤 때마다 떴음 (밖에서 켠 사내 노트북 — 서버에 닿지 않을 때의 네트워크 오류). 진짜 updates.check로 재현."""
    from yesoncheck.main_window import VideoPlayer

    blocker = tmp_path / "not_a_folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    monkeypatch.delenv(shared_config.CONFIG_DIR_ENV, raising=False)
    monkeypatch.setattr(shared_config, "MAC_CONFIG_DIR", str(blocker / ".yesoncheck"))  # 그 아래를 열면 NotADirectoryError
    _built_app(monkeypatch, "1.1.0")
    player = VideoPlayer()
    try:
        assert "NotADirectoryError" in player.shared_config_problem and player.shared_config_not_found is True
        check_now(player)
        assert dialogs.messages == []
    finally:
        player.close()
        paths.activate(None)
