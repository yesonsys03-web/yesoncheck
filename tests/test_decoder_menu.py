"""Settings → '재생 디코더 (Mac)' 메뉴 — VideoToolbox(기본)·ffmpeg(예전 방식) 라디오, prefs.json 저장, 이 창에 바로 적용 (스펙 2026-11-04 §5.4).

- 메뉴는 macOS에서만 만든다(sys.platform == "darwin" — Windows·Linux에는 VideoToolbox가 없음): Mac 전용 시험은 Windows CI에서 skip(Ruling 2)하고,
  메뉴가 없음은 sys.platform을 win32·linux로 바꾼 뒤 만든 창으로 어느 플랫폼에서나 본다(메뉴는 창을 만들 때 sys.platform을 읽음).
- 체크·활성·툴팁은 지금 유효한 디코더(mac_native_gate.effective_decoder — 환경 변수 > prefs.json > 기본값)를 따른다. 환경 변수(YESONCHECK_MAC_NATIVE)나
  YESONCHECK_MOVIE_SOURCE=cv2가 덮으면 두 항목 비활성 + 툴팁, prefs.json을 읽지 못한 세션(SOURCE_FALLBACK)은 ffmpeg 체크 + 그 출처를 툴팁에(활성 그대로).
- 고르면 set_playback_decoder: ① prefs.json 저장(실패 → 기록 + 창 1회 + 체크 되돌림) ② 캐시(출처 prefs.json) ③ 기록 한 줄 — 유효 디코더가 그대로면 여기서
  메뉴만 맞춤 — ④ 캡처 바꿔 끼움(swap_movie_captures_for_decoder — 시험에서는 스파이) ⑤ 스트림 아이템의 GL 실패 걸쇠 풀기(reset_failure — 바꿔 끼운 뒤)
  ⑥ 메뉴 맞춤(바꿔 끼우다 예외가 나도 — finally).
conftest가 YESONCHECK_MAC_NATIVE=off를 고정하므로 auto를 보는 시험은 delenv하고, HOME은 conftest가 시험마다 빈 폴더로 돌려 prefs.json이 격리된다.
"""

import os
import sys

import numpy as np
import pytest
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtWidgets import QMessageBox, QStyleOptionGraphicsItem

from tests.native_fakes import fake_native_player, new_player  # noqa: F401 (픽스처 — new_player는 fake_native_player가 요청함)
from tests.test_work_paths_ui import make_config
from yesoncheck import app, mac_native_gate, mac_prefs, player_base, user_files
from yesoncheck.mac_native_gate import NATIVE_MODE_ENV, PREF_KEY, SOURCE_FALLBACK, SOURCE_PREFS, effective_decoder, preferred_decoder
from yesoncheck.movie_pipe_source import SOURCE_MODE_ENV

mac_only = pytest.mark.skipif(sys.platform != "darwin", reason="Mac 전용 메뉴")

MENU_TEXT = "재생 디코더 (Mac)"
LABELS = {"videotoolbox": "VideoToolbox (기본)", "ffmpeg": "ffmpeg (예전 방식)"}
CV2_TIP = "YESONCHECK_MOVIE_SOURCE=cv2가 모든 빠른 디코더를 끕니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다"
SET_LOG = "[재생] 디코더 설정: {} (Setting 메뉴)"
SAME_LOG = "캡처를 다시 열지 않음"  # 유효 디코더가 그대로일 때의 기록 줄 끝
RUNTIME_SOURCE = "네이티브 화면 그리기 실패 — 이 창만 ffmpeg"  # Task 5의 실행 중 폴백이 둘 출처(그 모양의 대역 — 메뉴는 알지 못하는 출처 글)


def settings_menu(player):
    [action] = [a for a in player.menuBar().actions() if a.text() == "&Settings"]
    return action.menu()


def decoder_submenu(player):
    [action] = [a for a in settings_menu(player).actions() if a.text() == MENU_TEXT]
    return action.menu()


def checked(player):
    """체크된 항목의 디코더 이름들 (라디오라 하나여야 함)."""
    return [name for name, action in player.decoder_actions.items() if action.isChecked()]


def write_prefs(text):
    path = mac_prefs.prefs_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture
def auto(monkeypatch):
    """토글 auto — conftest의 YESONCHECK_MAC_NATIVE=off 고정을 풂 (메뉴가 prefs·기본값을 따르게)."""
    monkeypatch.delenv(NATIVE_MODE_ENV, raising=False)


@pytest.fixture
def make_player(new_player, dialogs, tmp_path):  # noqa: F811 (new_player: 픽스처)
    """창 하나를 만드는 함수 — 메뉴는 만들 때의 캐시·환경 변수로 체크를 정하므로 시험이 그 앞을 차린 뒤 부름."""
    return lambda: new_player(make_config(str(tmp_path), {}))


@pytest.fixture
def spies(monkeypatch):
    """플레이어의 swap_movie_captures_for_decoder·스트림 아이템의 reset_failure를 기록하는 대역으로 바꾸는 함수 → 기록 list.
    swap 기록에는 그때의 캐시·prefs.json 값을 함께 남김 — 새 디코더로 다시 열려면 저장·캐시가 swap보다 먼저여야 함."""
    events = []

    def install(player, swap_result=True):
        def swap():
            saved = mac_prefs.read_prefs().get(PREF_KEY) if os.path.exists(mac_prefs.prefs_path()) else None
            events.append(("swap", preferred_decoder(), saved))
            return swap_result

        monkeypatch.setattr(player, "swap_movie_captures_for_decoder", swap)
        if player.videoWidget.video_item_stream:
            monkeypatch.setattr(player.videoWidget.video_item, "reset_failure", lambda: events.append(("reset",)))
        return events

    return install


def paint_on_raster(item):
    """아이템을 raster QImage에 그림 — 중첩 이벤트 루프(창)가 도는 동안의 paint 대역. 스트림 아이템은 GL 엔진이 아니라 실패(_fail)하거나, 걸쇠가 걸려 있으면 아무것도 안 함."""
    target = QImage(16, 16, QImage.Format_ARGB32)
    painter = QPainter(target)
    try:
        item.paint(painter, QStyleOptionGraphicsItem(), None)
    finally:
        painter.end()


def forbid_save(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(f"설정 파일에 쓰면 안 됩니다: {args}")

    monkeypatch.setattr(mac_prefs, "update_pref", forbidden)


# ---------------------------------------------------------------- 메뉴가 있는 곳 (Mac만)

@mac_only
def test_menu_is_the_first_settings_item_on_mac(make_player, auto):
    """Settings의 첫 항목이 '재생 디코더 (Mac)'(2026-11-12 전에는 'GPU Acceleration' 바로 뒤 — 그 항목을 뺌) — 체크 가능한 두 항목(이름·차례 고정), decoder_actions·decoder_action_group이 그 항목."""
    player = make_player()
    texts = [a.text() for a in settings_menu(player).actions()]
    assert texts[0] == MENU_TEXT
    items = decoder_submenu(player).actions()
    assert [a.text() for a in items] == [LABELS["videotoolbox"], LABELS["ffmpeg"]]
    assert all(a.isCheckable() for a in items)
    assert list(player.decoder_actions) == ["videotoolbox", "ffmpeg"]
    assert [player.decoder_actions[name] for name in ("videotoolbox", "ffmpeg")] == items == player.decoder_action_group


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_no_decoder_menu_off_mac(make_player, monkeypatch, platform):
    """macOS가 아니면 메뉴를 만들지 않음 (Windows 메뉴는 글자 하나 안 바뀜 — Linux도 VideoToolbox가 없음). 맞춤 함수는 할 일이 없음.
    가짜 플랫폼은 창을 만드는 동안만 — 창을 닫는(픽스처 끝) 길은 진짜 플랫폼으로."""
    with monkeypatch.context() as m:
        m.setattr(sys, "platform", platform)
        player = make_player()
    assert MENU_TEXT not in [a.text() for a in settings_menu(player).actions()]
    assert player.decoder_actions == {} and player.decoder_action_group == []
    player._sync_decoder_menu()


# ---------------------------------------------------------------- 시작 때의 체크·활성·툴팁

@mac_only
@pytest.mark.parametrize("prefs, expected", [(None, "videotoolbox"), ('{"playback_decoder": "ffmpeg"}', "ffmpeg"),
                                             ('{"playback_decoder": "videotoolbox"}', "videotoolbox")])
def test_menu_checks_the_effective_decoder_at_start(make_player, auto, dialogs, prefs, expected):
    """시작 때(app.load_playback_decoder가 prefs.json을 읽어 캐시에 둔 뒤 창을 만듦) 체크 = 유효한 디코더, 두 항목 활성, 툴팁은 다른 창 안내."""
    if prefs is not None:
        write_prefs(prefs)
    app.load_playback_decoder()
    player = make_player()
    assert checked(player) == [expected]
    for action in player.decoder_actions.values():
        assert action.isEnabled()
        assert action.toolTip() == player_base.DECODER_TIP
    assert "다른 창" in player_base.DECODER_TIP
    assert dialogs.messages == []


@mac_only
@pytest.mark.parametrize("mode, expected", [("off", "ffmpeg"), ("on", "videotoolbox"), ("OFF", "ffmpeg")])
def test_menu_disabled_with_tooltip_when_env_overrides(make_player, monkeypatch, mode, expected):
    """YESONCHECK_MAC_NATIVE가 설정을 덮으면 그 값으로 체크하고 두 항목 비활성 + 툴팁 "<출처>이|가 우선합니다 — …"(on이·off가 — 받침 따라) (설정값이 달라도)."""
    write_prefs('{"playback_decoder": "%s"}' % ("videotoolbox" if expected == "ffmpeg" else "ffmpeg"))
    monkeypatch.setenv(NATIVE_MODE_ENV, mode)
    app.load_playback_decoder()
    player = make_player()
    assert checked(player) == [expected]
    josa = "이" if mode.lower() == "on" else "가"
    tip = f"환경 변수 {NATIVE_MODE_ENV}={mode.lower()}{josa} 우선합니다 — 지우고 앱을 다시 켜면 이 설정을 씁니다"
    for action in player.decoder_actions.values():
        assert not action.isEnabled()
        assert action.toolTip() == tip


@mac_only
def test_menu_disabled_in_cv2_source_mode(make_player, auto, monkeypatch):
    """YESONCHECK_MOVIE_SOURCE=cv2(킬 스위치 — 네이티브·파이프 모두 끔)면 디코더 설정이 쓰이지 않으므로 두 항목 비활성 + cv2 툴팁 (환경 변수가 함께 있어도 cv2가 먼저)."""
    monkeypatch.setenv(SOURCE_MODE_ENV, "cv2")
    player = make_player()
    assert checked(player) == ["videotoolbox"]
    for action in player.decoder_actions.values():
        assert not action.isEnabled() and action.toolTip() == CV2_TIP
    monkeypatch.setenv(NATIVE_MODE_ENV, "off")
    player._sync_decoder_menu()
    assert checked(player) == ["ffmpeg"]
    assert all(a.toolTip() == CV2_TIP and not a.isEnabled() for a in player.decoder_actions.values())


@mac_only
def test_menu_after_prefs_read_failure_checks_ffmpeg_with_the_source(make_player, auto, dialogs):
    """깨진 prefs.json으로 켠 세션(SOURCE_FALLBACK — 이 세션만 ffmpeg): ffmpeg 체크 + 그 툴팁에 출처, 두 항목 활성 (VideoToolbox는 보통 안내)."""
    write_prefs("not json")
    app.load_playback_decoder()
    assert effective_decoder() == ("ffmpeg", SOURCE_FALLBACK)
    player = make_player()
    assert checked(player) == ["ffmpeg"]
    assert player.decoder_actions["ffmpeg"].toolTip() == SOURCE_FALLBACK
    assert player.decoder_actions["videotoolbox"].toolTip() == player_base.DECODER_TIP
    assert all(a.isEnabled() for a in player.decoder_actions.values())


# ---------------------------------------------------------------- 고르기

@mac_only
def test_choosing_ffmpeg_saves_logs_swaps_then_resets(fake_native_player, auto, spies, dialogs, capsys):
    """VideoToolbox(기본)로 연 창에서 ffmpeg를 고름(항목 trigger): prefs.json에 저장(다른 키는 그대로) → 캐시(출처 prefs.json) → 기록 한 줄 → 캡처
    바꿔 끼움 1회(그때 이미 저장·캐시가 ffmpeg) → 스트림 아이템의 걸쇠 풀기(바꿔 끼운 뒤 — Ruling 9) → ffmpeg 체크. 창 없음.

    깨지는 변경: 저장을 빼면 파일에 값이 없음; 캐시를 swap 뒤에 바꾸면 swap 기록의 캐시가 videotoolbox; reset을 swap 앞으로 옮기면 차례가 바뀜;
    set_preferred_decoder를 출처 없이 부르면 출처가 '기본값'."""
    write_prefs('{"asked_default_video_app": true}')
    rig = fake_native_player()
    player = rig.player
    assert player.videoWidget.video_item_stream
    events = spies(player)
    capsys.readouterr()

    player.decoder_actions["ffmpeg"].trigger()

    assert mac_prefs.read_prefs() == {"asked_default_video_app": True, PREF_KEY: "ffmpeg"}
    assert preferred_decoder() == "ffmpeg" and effective_decoder() == ("ffmpeg", SOURCE_PREFS)
    assert events == [("swap", "ffmpeg", "ffmpeg"), ("reset",)]
    assert capsys.readouterr().out.count(SET_LOG.format("ffmpeg") + "\n") == 1
    assert checked(player) == ["ffmpeg"]
    assert player.decoder_actions["ffmpeg"].toolTip() == player_base.DECODER_TIP
    assert dialogs.messages == []

    player.decoder_actions["videotoolbox"].trigger()  # 되돌리기도 같은 길
    assert mac_prefs.read_prefs()[PREF_KEY] == "videotoolbox" and preferred_decoder() == "videotoolbox"
    assert events[2:] == [("swap", "videotoolbox", "videotoolbox"), ("reset",)]
    assert checked(player) == ["videotoolbox"]


@mac_only
def test_choosing_with_pixmap_item_swaps_without_reset(fake_native_player, auto, spies, dialogs):
    """픽스맵 아이템(YESONCHECK_VIDEO_ITEM=pixmap — 걸쇠가 없음)이면 걸쇠 풀기 없이 저장·캐시·바꿔 끼움."""
    rig = fake_native_player(video_item="pixmap")
    player = rig.player
    assert not player.videoWidget.video_item_stream
    events = spies(player)
    player.set_playback_decoder("ffmpeg")
    assert events == [("swap", "ffmpeg", "ffmpeg")]
    assert checked(player) == ["ffmpeg"] and dialogs.messages == []


@mac_only
def test_swap_window_does_not_relatch_the_released_item(fake_native_player, auto, dialogs, monkeypatch):
    """GL 그리기 실패로 걸쇠가 걸린 스트림 아이템: ffmpeg를 고르는 동안 바꿔 끼움이 창을 띄우고(열기·ffprobe 실패 — 모달의 중첩 이벤트 루프) 그 루프가
    아직 옛(실패하는) 프레임을 그려도 걸쇠가 걸린 채라 다시 실패하지 않음 → 끝에 걸쇠가 풀려 있고 알린 실패는 처음 1번뿐 (Ruling 9 — 걸쇠는 바꿔 끼운 뒤 풂).

    깨지는 변경: reset_failure를 swap 앞에서 부르면 창 안의 paint가 다시 실패해 걸쇠가 다시 걸리고(_failed True) 실패 창이 하나 더 뜸.
    네이티브 그리기 실패의 자동 폴백(Task 5 — 아이템의 실패 콜백)은 끔: 이 시험은 메뉴 길의 순서만 봄(자동 폴백이 먼저 캐시를 ffmpeg로 바꾸면 ffmpeg 선택은
    그대로인 길 — tests/test_native_paint_fallback). 바꿔 끼움 대역은 창 뒤에 새 RGB 프레임을 검(진짜 바꿔 끼움처럼 — 네이티브 프레임이 남은 채 ffmpeg면
    걸쇠를 일부러 풀지 않으므로(되풀이 방지, Ruling 11) 그 경우는 이 순서 시험이 아님)."""
    rig = fake_native_player()
    player = rig.player
    item = player.videoWidget.video_item
    item.set_failure_callback(None)
    paint_on_raster(item)  # 옛 프레임을 그리다 실패 → 걸쇠
    player.timer.stop()
    from PyQt5.QtWidgets import QApplication
    QApplication.processEvents()
    assert item._failed and item.failure_count == 1
    dialogs.messages.clear()

    def swap_with_window():
        QMessageBox.critical(player, "재생 디코더를 바꾸지 못함", "가짜 열기 실패")  # 모달 — 그 루프가 아래 paint를 돌림
        paint_on_raster(item)  # 아직 옛 네이티브 프레임
        player.videoWidget.updateFrame(np.zeros((8, 16, 3), np.uint8), None)  # 바꿔 끼운 캡처의 RGB 프레임
        return True

    monkeypatch.setattr(player, "swap_movie_captures_for_decoder", swap_with_window)
    player.set_playback_decoder("ffmpeg")
    QApplication.processEvents()
    assert item._failed is False and item.failure_count == 1
    assert [m[:2] for m in dialogs.messages] == [("critical", "재생 디코더를 바꾸지 못함")]  # 실패 창이 다시 뜨지 않음
    assert checked(player) == ["ffmpeg"]


@mac_only
def test_swap_exception_still_syncs_the_menu(make_player, auto, monkeypatch):
    """바꿔 끼우다 예외가 나도(코드·빌드 쪽 — 잡지 않음) 메뉴는 맞춘 뒤 예외를 그대로 올림 — 두 항목이 함께 체크된 채 남지 않게."""
    player = make_player()

    def broken_swap():
        raise RuntimeError("가짜 바꿔 끼움 오류")

    monkeypatch.setattr(player, "swap_movie_captures_for_decoder", broken_swap)
    with pytest.raises(RuntimeError, match="가짜 바꿔 끼움 오류"):
        player.set_playback_decoder("ffmpeg")
    assert checked(player) == ["ffmpeg"]  # 저장·캐시는 이미 ffmpeg — 맞춘 메뉴
    assert effective_decoder() == ("ffmpeg", SOURCE_PREFS)


@mac_only
@pytest.mark.parametrize("prefs, name", [(None, "videotoolbox"), ('{"playback_decoder": "ffmpeg"}', "ffmpeg"),
                                         ('{"playback_decoder": "videotoolbox"}', "videotoolbox")])
def test_choosing_same_decoder_is_a_no_op(make_player, auto, spies, monkeypatch, capsys, prefs, name):
    """이미 그 값이 prefs.json·기본값에서 온 것이면 저장·기록·걸쇠 풀기·바꿔 끼움 모두 없음 — 체크된 항목을 다시 눌러 Qt가 끈 체크만 되돌림."""
    if prefs is not None:
        write_prefs(prefs)
    app.load_playback_decoder()
    player = make_player()
    events = spies(player)
    forbid_save(monkeypatch)
    capsys.readouterr()
    player.decoder_actions[name].trigger()
    assert events == []
    assert checked(player) == [name]
    assert "[재생] 디코더 설정" not in capsys.readouterr().out
    if prefs is None:
        assert not os.path.exists(mac_prefs.prefs_path())


@mac_only
def test_choosing_ffmpeg_in_fallback_session_saves_without_reopen(make_player, auto, spies, dialogs, capsys):
    """설정을 읽지 못해 이 세션만 ffmpeg인 창(파일은 그 뒤 고쳐짐 — 여기서는 지움)에서 ffmpeg를 고르면 no-op이 아님: 파일에 저장하고 출처가 prefs.json.
    유효 디코더는 ffmpeg 그대로라 캡처를 다시 열지도 걸쇠를 풀지도 않음(파이프 → 파이프 재열기는 채운 전체 프레임 캐시와 [측정] 기록만 버림)."""
    path = write_prefs("not json")
    app.load_playback_decoder()
    os.remove(path)
    player = make_player()
    events = spies(player)
    player.decoder_actions["ffmpeg"].trigger()
    assert mac_prefs.read_prefs() == {PREF_KEY: "ffmpeg"}
    assert effective_decoder() == ("ffmpeg", SOURCE_PREFS)
    assert events == []
    assert checked(player) == ["ffmpeg"]
    assert player.decoder_actions["ffmpeg"].toolTip() == player_base.DECODER_TIP
    out = capsys.readouterr().out
    assert SET_LOG.format("ffmpeg") in out and SAME_LOG in out


@mac_only
@pytest.mark.parametrize("native", ["", "A"])
def test_choosing_ffmpeg_after_runtime_fallback_saves_without_reopen(fake_native_player, auto, spies, dialogs, capsys, native):
    """실행 중 폴백(Task 5 — 이 창만 ffmpeg, 파일은 그대로)으로 캐시가 ffmpeg인 창: 메뉴는 그 출처를 ffmpeg 툴팁에 보이고, ffmpeg를 고르면 저장만 —
    이미 ffmpeg로 바꿔 끼운 캡처를 다시 열지 않음(바꿔 끼움·걸쇠 풀기 0회). A가 RGB(바꿔 끼운 뒤의 모습)여도, 네이티브 면이어도 걸쇠가 걸려 있지 않으면 —
    다시 바꿔 끼우는 것은 걸쇠가 걸린 창뿐(Ruling 11·최종 리뷰 F1 — tests/test_native_paint_fallback)."""
    rig = fake_native_player(native=native)
    player = rig.player
    events = spies(player)
    mac_native_gate.set_preferred_decoder("ffmpeg", source=RUNTIME_SOURCE)
    player._sync_decoder_menu()
    assert checked(player) == ["ffmpeg"] and player.decoder_actions["ffmpeg"].toolTip() == RUNTIME_SOURCE
    capsys.readouterr()
    player.decoder_actions["ffmpeg"].trigger()
    assert mac_prefs.read_prefs() == {PREF_KEY: "ffmpeg"}
    assert effective_decoder() == ("ffmpeg", SOURCE_PREFS)
    assert events == []
    assert checked(player) == ["ffmpeg"] and player.decoder_actions["ffmpeg"].toolTip() == player_base.DECODER_TIP
    out = capsys.readouterr().out
    assert SET_LOG.format("ffmpeg") in out and SAME_LOG in out
    assert dialogs.messages == []


@mac_only
def test_saving_under_env_override_does_not_reopen(make_player, monkeypatch, spies, capsys):
    """환경 변수가 덮는 동안(YESONCHECK_MAC_NATIVE=off — 항목은 비활성이라 부르는 쪽은 코드뿐) videotoolbox를 저장해도 유효 디코더는 ffmpeg 그대로라
    다시 열지 않음 — 비교는 고른 이름이 아니라 유효 디코더 전후로. 저장한 값은 다음에 환경 변수 없이 켤 때 쓰임."""
    monkeypatch.setenv(NATIVE_MODE_ENV, "off")
    player = make_player()
    events = spies(player)
    capsys.readouterr()
    player.set_playback_decoder("videotoolbox")
    assert mac_prefs.read_prefs() == {PREF_KEY: "videotoolbox"} and preferred_decoder() == "videotoolbox"
    assert events == []
    assert checked(player) == ["ffmpeg"] and not any(a.isEnabled() for a in player.decoder_actions.values())
    assert SAME_LOG in capsys.readouterr().out


@mac_only
@pytest.mark.parametrize("failure", ["broken", "write"])
def test_prefs_write_failure_shows_window_and_reverts_check(make_player, auto, spies, dialogs, monkeypatch, capsys, failure):
    """저장 실패(깨진 prefs.json — UserFileError, 쓰기 실패 — OSError): 트레이스백 기록 + 오류 창 1회('재생 디코더 설정') + 체크를 원래대로, 캐시·파일·캡처
    그대로 (저장하지 못한 설정을 이 창에만 몰래 적용하지 않음). 깨진 파일은 덮어 쓰지 않음."""
    player = make_player()
    events = spies(player)
    if failure == "broken":
        path = write_prefs("not json")
        expected_error = "UserFileError"
    else:
        path = mac_prefs.prefs_path()

        def no_write(*args, **kwargs):
            raise PermissionError(13, "Permission denied", path)

        monkeypatch.setattr(user_files, "update_json", no_write)
        expected_error = "PermissionError"
    capsys.readouterr()

    player.decoder_actions["ffmpeg"].trigger()

    assert len(dialogs.criticals) == 1 and len(dialogs.messages) == 1
    kind, title, text = dialogs.messages[0]
    assert (kind, title) == ("critical", "재생 디코더 설정")
    assert path in text and expected_error in text and "Traceback" in text
    assert checked(player) == ["videotoolbox"]
    assert effective_decoder() == ("videotoolbox", mac_native_gate.SOURCE_DEFAULT)
    assert events == []
    captured = capsys.readouterr()
    assert "Traceback" in captured.err and expected_error in captured.err
    assert SET_LOG.format("ffmpeg") not in captured.out
    if failure == "broken":
        assert read_text(path) == "not json"
    else:
        assert not os.path.exists(path)


@mac_only
@pytest.mark.parametrize("name", ["videotoolbox", "ffmpeg"])
def test_choosing_in_fallback_session_with_still_broken_prefs_fails_loudly(make_player, auto, spies, dialogs, name):
    """깨진 파일로 켠 세션(ffmpeg 체크)에서 어느 항목을 고르든(ffmpeg도 — 출처가 SOURCE_FALLBACK이라 no-op이 아님) 파일이 여전히 깨져 있으면 저장 실패 창
    1회 + ffmpeg 체크로 되돌림, 캐시는 SOURCE_FALLBACK 그대로, 바꿔 끼움 없음, 깨진 파일은 덮지 않음."""
    path = write_prefs("not json")
    app.load_playback_decoder()
    dialogs.messages.clear()
    player = make_player()
    events = spies(player)
    player.decoder_actions[name].trigger()
    assert [m[:2] for m in dialogs.messages] == [("critical", "재생 디코더 설정")]
    assert checked(player) == ["ffmpeg"]
    assert effective_decoder() == ("ffmpeg", SOURCE_FALLBACK)
    assert player.decoder_actions["ffmpeg"].toolTip() == SOURCE_FALLBACK
    assert events == [] and read_text(path) == "not json"


@mac_only
def test_swap_failure_keeps_new_setting_without_another_window(make_player, auto, spies, dialogs, capsys):
    """바꿔 끼우지 못한 쪽이 있으면(swap → False — 그 함수가 이미 창을 띄움) 창을 더 띄우지 않고 기록 한 줄: 설정은 저장됐고 메뉴는 새 값 (다음에 열 때부터)."""
    player = make_player()
    events = spies(player, swap_result=False)
    capsys.readouterr()
    player.decoder_actions["ffmpeg"].trigger()
    assert dialogs.messages == []
    assert events == [("swap", "ffmpeg", "ffmpeg")]
    assert mac_prefs.read_prefs() == {PREF_KEY: "ffmpeg"} and checked(player) == ["ffmpeg"]
    out = capsys.readouterr().out
    assert SET_LOG.format("ffmpeg") in out and "다음에 열 때부터" in out


@mac_only
def test_set_playback_decoder_rejects_unknown_name_before_saving(make_player, auto, monkeypatch):
    """메뉴 밖의 이름은 ValueError — 파일에 쓰기 전에 (나쁜 값이 저장되면 다음 시작이 그 파일을 거부함)."""
    player = make_player()
    forbid_save(monkeypatch)
    with pytest.raises(ValueError, match="playback_decoder"):
        player.set_playback_decoder("hevc")
    assert checked(player) == ["videotoolbox"]


def test_set_playback_decoder_refuses_off_macos(make_player, monkeypatch):
    """macOS가 아니면 RuntimeError — 메뉴가 없는 설정이라 prefs.json(Mac 경로)에 쓰지 않음 (가짜 플랫폼은 부르는 동안만)."""
    player = make_player()
    forbid_save(monkeypatch)
    with monkeypatch.context() as m:
        m.setattr(sys, "platform", "win32")
        with pytest.raises(RuntimeError, match="macOS 전용"):
            player.set_playback_decoder("ffmpeg")
