# -*- coding: utf-8 -*-
"""슬라이더 호버 썸네일의 Settings 켜기/끄기 + 시작 때 설정 읽기 (player_hover_thumbs의 메뉴 메서드, app.load_slider_thumbnails).

실제 VideoPlayer를 offscreen으로 띄워 Settings 메뉴의 항목을 찾아 trigger()하고, 설정 파일도 진짜 파일을 본다 — conftest의 autouse 픽스처가 HOME·
LOCALAPPDATA를 시험마다 새 빈 폴더로 돌려 hover_strip.prefs_path()가 임시 폴더를 가리킴 (사용자의 진짜 설정을 건드리지 않음). 띠 워커는 진짜
ffmpeg이고(번호 클립·real_builders — 시험이 끝나 창이 닫힌 뒤 스레드·프로세스가 남지 않았는지 늘 확인), 끄면 도는 워커가 멈추는지는 slow_ffmpeg로
'도는 중'인 워커를 잡아 본다. 플레이어·클립 픽스처와 도우미는 tests/test_player_hover_thumbs.py의 것을 가져다 씀.

프로세스 캐시(hover_strip.enabled)는 시험마다 켬(기본)에서 시작해 시험이 끝나면 되돌림 (autouse restore_cache).
"""

import json
import os
import sys

import psutil
import pytest
from PyQt5 import sip
from PyQt5.QtTest import QTest

from tests.test_player_hover_thumbs import (  # noqa: F401 (픽스처 — 이 모듈 안에서 이름으로 요청됨)
    CLIP_COUNT, WAIT_S, hover, numbered_clip, past_start_delay_ms, player_with_clip, real_builders, shown_player, slow_ffmpeg,
    start_and_catch_running, strip_done, wait_until,
)
from tests.test_sequence_capture import make_seq
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import app, hover_strip, windows_display
from yesoncheck.hover_strip import LOG_PREFIX, MENU_TEXT
from yesoncheck.player_hover_thumbs import HOVER_TIP

SET_OFF_LOG = f"{LOG_PREFIX} 설정: 끔 (Settings 메뉴)"
SET_ON_LOG = f"{LOG_PREFIX} 설정: 켬 (Settings 메뉴)"
SAVE_FAILED_HEAD = "설정을 저장하지 못해 바꾸지 않았습니다.\n"
STARTUP_NOTE = f"이 세션은 슬라이더 썸네일을 끕니다 — Settings → {MENU_TEXT}에서 다시 켤 수 있습니다"


@pytest.fixture(autouse=True)
def restore_cache(monkeypatch):
    """프로세스 캐시를 켬(기본)에서 시작하고, 시험이 set_enabled로 바꾼 값을 시험 뒤 되돌림 (monkeypatch가 원래 값을 되돌려 놓음)."""
    monkeypatch.setattr(hover_strip, "_enabled", True)


def settings_menu(player):
    [action] = [a for a in player.menuBar().actions() if a.text() == "&Settings"]
    return action.menu()


def hover_actions(player):
    return [a for a in settings_menu(player).actions() if a.text() == MENU_TEXT]


def write_prefs(text):
    """진짜 설정 파일(격리된 HOME 아래)에 text를 그대로 씀 → 그 경로."""
    path = hover_strip.prefs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def forbid_save(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(f"설정 파일에 쓰면 안 됩니다: {args}")

    monkeypatch.setattr(hover_strip, "save_enabled", forbidden)


def worker_gone(builder):
    return sip.isdeleted(builder) or not builder.isRunning()


# ---------------------------------------------------------------- 메뉴 항목

def test_menu_item_exists_checked_by_default(new_player, dialogs, tmp_path):  # noqa: F811
    """Settings 메뉴에 '슬라이더 썸네일' 항목 하나 — 체크 가능·체크됨(기본 켬)·툴팁 HOVER_TIP, 툴팁이 보이는 메뉴. 설정 파일은 만들지 않음."""
    player = new_player(make_config(str(tmp_path), {}))
    [action] = hover_actions(player)
    assert action.isCheckable() and action.isChecked()
    assert action.toolTip() == HOVER_TIP
    assert settings_menu(player).toolTipsVisible()
    assert player.hover_thumbs_action is action
    assert not os.path.exists(hover_strip.prefs_path()) and dialogs.messages == []


def test_menu_item_starts_unchecked_when_the_session_is_off(new_player, dialogs, tmp_path):  # noqa: F811
    """창을 만들 때 캐시가 꺼져 있으면(시작 때 설정이 꺼짐이었거나 읽지 못함) 체크 없이 시작 — 메뉴는 캐시를 따름."""
    hover_strip.set_enabled(False)
    player = new_player(make_config(str(tmp_path), {}))
    [action] = hover_actions(player)
    assert not action.isChecked()


def test_menu_item_follows_the_display_menu_on_windows(new_player, dialogs, tmp_path, monkeypatch):  # noqa: F811
    """삽입 자리: 화면 그리기 메뉴(Windows) 바로 뒤 — Mac·Windows 모두 항목이 있음 (Mac은 화면 그리기 메뉴가 없어 디코더 메뉴 뒤)."""
    monkeypatch.setattr(sys, "platform", "win32")
    player = new_player(make_config(str(tmp_path), {}))
    texts = [a.text() for a in settings_menu(player).actions()]
    assert texts.index(MENU_TEXT) == texts.index(windows_display.MENU_TEXT) + 1
    assert texts.count(MENU_TEXT) == 1


# ---------------------------------------------------------------- 끄기·켜기

def test_toggle_off_saves_and_closes(slow_ffmpeg, shown_player, numbered_clip, capsys):
    """띠 워커가 도는 중에 끔 → 파일에 false, 계획·저장소 없음, 워커·ffmpeg 끝, 기록 '설정: 끔', 호버에 창 없음, 체크 해제."""
    player = shown_player
    builder = start_and_catch_running(player, numbered_clip)
    pid = builder.pid
    capsys.readouterr()
    [action] = hover_actions(player)

    action.trigger()

    assert hover_strip.read_enabled(hover_strip.prefs_path()) is False
    assert json.loads(read_text(hover_strip.prefs_path())) == {hover_strip.PREF_KEY: False}
    assert hover_strip.enabled() is False and not action.isChecked()
    assert player._hover_plan is None and player._hover_strip is None and player._hover_builder is None
    assert worker_gone(builder) and not psutil.pid_exists(pid)
    assert not player._hover_timer.isActive()
    assert capsys.readouterr().out.count(SET_OFF_LOG) == 1
    for slider in (player.positionScroll, player.overlaySlider):
        hover(slider, slider.width() // 2)
        assert not player._hover_popup.isVisible()


def test_toggle_on_restarts_for_current_movie(player_with_clip, numbered_clip, capsys):
    """끈 뒤 다시 켬 → 지금 A 영상의 계획(path == filename_a)이 다시 서고 쉬면 띠를 만들어 그림을 보임, 파일은 true, 기록 '설정: 켬'."""
    player = player_with_clip
    [action] = hover_actions(player)
    action.trigger()
    assert player._hover_plan is None
    capsys.readouterr()

    action.trigger()

    assert hover_strip.read_enabled(hover_strip.prefs_path()) is True
    assert hover_strip.enabled() is True and action.isChecked()
    assert player._hover_path == player.filename_a == numbered_clip
    assert player._hover_plan.total == CLIP_COUNT and player._hover_strip is not None
    assert player._hover_builder is None and player._hover_timer.isActive()  # 워커는 쉬는 때 틱이 띄움 (열 때와 같음)
    assert capsys.readouterr().out.count(SET_ON_LOG) == 1
    wait_until(lambda: strip_done(player), WAIT_S, "다시 켠 뒤 띠를 만들지 못했습니다")


def test_toggle_on_without_movie_or_with_sequence_builds_nothing(shown_player, tmp_path, capsys):
    """영상이 없거나 A가 시퀀스면 켜도 계획·워커 없음 (설정만 바뀜 — 다음에 여는 영상부터)."""
    player = shown_player
    [action] = hover_actions(player)
    action.trigger()
    action.trigger()  # 영상 없음: 끄고 켜도 오류 없음
    assert hover_strip.enabled() is True and player._hover_plan is None and not player._hover_timer.isActive()

    sequence = make_seq(str(tmp_path / "seq"), "tk1", range(1, 7))
    assert player.open_file("A", sequence) is True
    action.trigger()
    action.trigger()
    assert hover_strip.enabled() is True and player._hover_plan is None and not player._hover_timer.isActive()
    QTest.qWait(past_start_delay_ms())
    assert player._hover_builder is None
    assert "Traceback" not in capsys.readouterr().err


# ---------------------------------------------------------------- 저장 실패·같은 값

@pytest.mark.parametrize("error", [OSError("디스크가 가득 참"), TimeoutError("잠금 시간 초과")])
def test_toggle_save_failure_reverts_check(player_with_clip, monkeypatch, dialogs, capsys, error):
    """끄려는데 저장 실패(OSError·TimeoutError) → 오류 창 1회(제목 hover_strip.SETTINGS_TITLE·글 '설정을 저장하지 못해 바꾸지 않았습니다.\\n<원인>'), 트레이스백 기록,
    체크는 그대로(켬), 캐시·계획 그대로 — 파일은 만들지 않음."""
    player = player_with_clip
    plan = player._hover_plan
    [action] = hover_actions(player)

    def failing_save(value, path=None):
        raise error

    monkeypatch.setattr(hover_strip, "save_enabled", failing_save)
    capsys.readouterr()

    action.trigger()

    assert [(kind, title) for kind, title, _ in dialogs.messages] == [("critical", hover_strip.SETTINGS_TITLE)]
    assert dialogs.criticals[0] == f"{SAVE_FAILED_HEAD}{error}"
    assert action.isChecked() and hover_strip.enabled() is True
    assert player._hover_plan is plan and player._hover_path == player.filename_a
    assert not os.path.exists(hover_strip.prefs_path())
    captured = capsys.readouterr()
    assert "Traceback" in captured.err and type(error).__name__ in captured.err and str(error) in captured.err
    assert "설정:" not in captured.out


def test_turning_on_save_failure_keeps_it_off(player_with_clip, monkeypatch, dialogs):
    """끈 상태에서 켜려는데 저장 실패 → 체크는 꺼진 채, 캐시 꺼짐, 계획 없음 (창 1회)."""
    player = player_with_clip
    [action] = hover_actions(player)
    action.trigger()
    assert dialogs.messages == []

    monkeypatch.setattr(hover_strip, "save_enabled", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("쓰기 실패")))
    action.trigger()

    assert len(dialogs.criticals) == 1 and "쓰기 실패" in dialogs.criticals[0]
    assert not action.isChecked() and hover_strip.enabled() is False and player._hover_plan is None


def test_broken_prefs_file_is_reported_and_not_overwritten(player_with_clip, dialogs, capsys):
    """설정 파일이 깨졌으면(UserFileError) 덮지 않고 오류 창 1회, 체크·캐시·계획 그대로."""
    player = player_with_clip
    plan = player._hover_plan
    [action] = hover_actions(player)
    path = write_prefs("{깨짐")
    capsys.readouterr()

    action.trigger()

    assert len(dialogs.criticals) == 1 and dialogs.criticals[0].startswith(SAVE_FAILED_HEAD)
    assert dialogs.messages[0][:2] == ("critical", hover_strip.SETTINGS_TITLE)
    assert read_text(path) == "{깨짐"
    assert action.isChecked() and hover_strip.enabled() is True and player._hover_plan is plan
    assert "UserFileError" in capsys.readouterr().err


def test_same_value_does_nothing(player_with_clip, monkeypatch, capsys):
    """파일도 이 창도 이미 꺼짐인데 set_slider_thumbnails(False) → 저장을 부르지 않고(바꿔치기가 부르면 실패) 기록·적용 없이 체크만 맞춤."""
    player = player_with_clip
    [action] = hover_actions(player)
    action.trigger()
    capsys.readouterr()
    forbid_save(monkeypatch)

    player.set_slider_thumbnails(False)

    assert not action.isChecked() and hover_strip.enabled() is False and player._hover_plan is None
    assert capsys.readouterr().out == ""


def test_value_another_window_saved_is_applied_here_without_writing(player_with_clip, monkeypatch, capsys):
    """다른 창이 이미 끔으로 저장했고(파일 false) 이 창은 아직 켬일 때 여기서 끔 → 파일은 다시 쓰지 않지만 이 창은 바로 꺼짐 (체크가 되돌아 켜진 채
    남지 않음 — 끌 길이 막히지 않게). 창마다 프로세스라 캐시와 파일이 어긋날 수 있음."""
    player = player_with_clip
    hover_strip.save_enabled(False)
    assert hover_strip.enabled() is True and player._hover_plan is not None
    [action] = hover_actions(player)
    forbid_save(monkeypatch)
    capsys.readouterr()

    action.trigger()

    assert not action.isChecked() and hover_strip.enabled() is False
    assert player._hover_plan is None and player._hover_builder is None and not player._hover_timer.isActive()
    assert capsys.readouterr().out.count(SET_OFF_LOG) == 1


def test_bad_value_in_file_is_replaced_by_the_explicit_choice(shown_player, numbered_clip, dialogs, capsys):
    """시작 때 나쁜 값('yes')으로 꺼진 세션에서 메뉴로 켜면 그 값을 사용자가 고른 값(true)으로 고침 — 시작 알림의 'Settings에서 다시 켤 수 있습니다'가
    성립. 나쁜 값은 트레이스백으로 기록에 남김 (조용히 넘기지 않음), 다른 키는 그대로."""
    player = shown_player
    path = write_prefs(json.dumps({hover_strip.PREF_KEY: "yes", "other": 1}))
    hover_strip.set_enabled(False)  # 시작 때 읽기 실패로 꺼진 세션
    assert player.open_file("A", numbered_clip) is True
    player._sync_hover_thumbs_menu()
    [action] = hover_actions(player)
    assert not action.isChecked() and player._hover_plan is None
    capsys.readouterr()

    action.trigger()

    assert json.loads(read_text(path)) == {hover_strip.PREF_KEY: True, "other": 1}
    assert hover_strip.enabled() is True and action.isChecked() and player._hover_path == numbered_clip
    assert dialogs.messages == []
    captured = capsys.readouterr()
    assert "ValueError" in captured.err and SET_ON_LOG in captured.out


# ---------------------------------------------------------------- 시작 때 읽기

def test_startup_reads_pref(dialogs, capsys):
    """prefs에 false → load_slider_thumbnails 뒤 enabled() False·창 없음·기록 '설정: 끔'. 파일 없음 → True (읽지 않으면 남아 있는 False로 실패)."""
    hover_strip.save_enabled(False)
    hover_strip.set_enabled(True)
    app.load_slider_thumbnails()
    assert hover_strip.enabled() is False and dialogs.messages == []
    assert capsys.readouterr().out == f"{LOG_PREFIX} 설정: 끔\n"

    os.remove(hover_strip.prefs_path())
    hover_strip.set_enabled(False)
    app.load_slider_thumbnails()
    assert hover_strip.enabled() is True and dialogs.messages == []
    assert capsys.readouterr().out == f"{LOG_PREFIX} 설정: 켬\n"

    hover_strip.save_enabled(True)
    hover_strip.set_enabled(False)
    app.load_slider_thumbnails()
    assert hover_strip.enabled() is True and dialogs.messages == []


@pytest.mark.parametrize("content, error_name", [
    ("{깨짐", "UserFileError"),
    (json.dumps({hover_strip.PREF_KEY: "yes"}), "ValueError"),
    (json.dumps({hover_strip.PREF_KEY: 1}), "ValueError"),  # 1은 불리언이 아님 (bool이 아닌 int)
])
def test_startup_broken_prefs_warns_and_disables(dialogs, capsys, content, error_name):
    """깨진 JSON(UserFileError)·불리언이 아닌 값(ValueError) → 경고 창 1회(제목 hover_strip.SETTINGS_TITLE — 메뉴의 저장 실패 창과 같은 상수, 글 '<원인>\\n\\n이 세션은 …끕니다'), 트레이스백,
    enabled() False(기본으로 치지 않음), 파일은 그대로, 끝 줄은 '설정: 끔'."""
    path = write_prefs(content)

    app.load_slider_thumbnails()

    assert hover_strip.SETTINGS_TITLE == "슬라이더 썸네일 설정"
    assert [(kind, title) for kind, title, _ in dialogs.messages] == [("warning", hover_strip.SETTINGS_TITLE)]
    assert dialogs.warnings[0].endswith(f"\n\n{STARTUP_NOTE}")
    assert hover_strip.enabled() is False
    assert read_text(path) == content
    captured = capsys.readouterr()
    assert "Traceback" in captured.err and error_name in captured.err
    assert captured.out == f"{LOG_PREFIX} 설정: 끔\n"


def test_launch_calls_loader(qapp, monkeypatch):
    """app.launch가 load_display_renderer 바로 뒤, 창(메뉴가 캐시를 봄)을 만들기 전에 load_slider_thumbnails를 부름 — 셋을 기록하는 대역."""
    calls = []

    class StopLaunch(Exception):
        pass

    def stop_at_window(**kwargs):
        calls.append("창")
        raise StopLaunch

    monkeypatch.setattr(app, "load_display_renderer", lambda: calls.append("화면 그리기"))
    monkeypatch.setattr(app, "load_slider_thumbnails", lambda: calls.append("슬라이더 썸네일"))
    monkeypatch.setattr(app, "VideoPlayer", stop_at_window)
    with pytest.raises(StopLaunch):
        app.launch(["yesoncheck"])
    assert calls == ["화면 그리기", "슬라이더 썸네일", "창"]

