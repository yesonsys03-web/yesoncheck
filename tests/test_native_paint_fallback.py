"""네이티브(IOSurface) 화면 그리기의 첫 실패 → 큰 소리 폴백: 창 1회 + 이 창(프로세스)만 ffmpeg (스펙 2026-11-04 §5.8·§7-9, Ruling 10).

- 아이템(VideoFrameItem._fail): 기록(트레이스백)·오류 창 예약은 예전대로, 그 바로 뒤에 실패 콜백(set_failure_callback)을 Qt 루프로 미뤄 부름 —
  값 native는 그리던 그림(set_sides·set_surface의 면)에 IOSurface 손잡이가 있었는가(has_native_side). 콜백이 예외를 내면 _last_resort(Qt 루프 밖으로
  내보내지 않음). 네이티브 면 실패이고 Mac이고 받을 쪽(콜백)이 있으면 창의 첫 줄이 "이 창은 ffmpeg 방식으로 바꿉니다"(나머지 줄은 그대로).
- 위젯(CustomVideoWidget): 스트림 아이템이면 콜백을 등록해 streamPaintFailed(bool) 신호로 넘김. 플레이어가 그 신호를 _on_stream_paint_failed에 이음.
- 플레이어: native이고 Mac이면 캐시만 ffmpeg(출처 SOURCE_GL_FALLBACK — prefs.json은 그대로) → 기록 한 줄 → 캡처 바꿔 끼움 → 네이티브 면이 다 빠졌으면
  걸쇠 풀기 → 메뉴 맞춤. RGB 면 실패·Mac 밖은 아무것도 안 함(예전 걸쇠·창·빈 영역).

가짜 GL은 tests/test_gl_video_item의 것(RecordingGL·GL2 페인터 대역·CGL 대역 — CGL 컨텍스트 NULL이면 IOSurface 묶기가 GLBindingError)을 그대로 씀.
'다음 프레임은 RGB 길'은 리그의 열기 자리(_open_movie_capture)를 디코더를 따르게 바꿔 봄: 지금 유효한 디코더가 네이티브면(native_wanted) 리그의 가짜
네이티브 캡처, 아니면 시험 영상의 진짜 cv2 캡처(RGB 프레임 — 진짜 길의 ffmpeg 파이프 자리). 바꿔 끼움의 ProRes 판정(ffprobe)은 가짜 probe.
conftest가 YESONCHECK_MAC_NATIVE=off를 고정하므로 폴백을 보는 시험은 auto(delenv) — 환경 변수가 덮는 동안은 바꾸지 않음(시험 하나).
"""

import io
import os
import sys
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PyQt5.QtGui import QTransform

from tests.native_fakes import (  # noqa: F401 (픽스처 — new_player는 native_fakes의 픽스처가 요청함)
    FAKE_HEIGHT,
    FAKE_WIDTH,
    fake_native_player,
    new_player,
    player_with_fake_native,
    spy_frames,
)
from tests.test_decoder_menu import checked, forbid_save, paint_on_raster, read_text, write_prefs
from tests.test_decoder_swap import fake_probe
from tests.test_gl_video_item import FakeCGL, FakeGLPainter, gl_contexts, paint_gl, recording_gl  # noqa: F401 (픽스처 둘)
from yesoncheck import app, error_window, gl_bindings, gl_surface, gl_video_item, mac_native_gate, mac_prefs, player_base, \
    player_playback
from yesoncheck.frame_handles import native_surface_of
from yesoncheck.gl_bindings import GL_RGB, GL_TEXTURE_2D, GL_UNSIGNED_BYTE
from yesoncheck.gl_video_item import VIDEO_ITEM_ENV, VideoFrameItem
from yesoncheck.mac_native_gate import NATIVE_MODE_ENV, SOURCE_DEFAULT, SOURCE_PREFS, effective_decoder, preferred_decoder

mac_only = pytest.mark.skipif(sys.platform != "darwin", reason="Mac 전용 폴백(재생 디코더 메뉴·VideoToolbox)")

RUNTIME_SOURCE = "네이티브 화면 그리기 실패 — 이 창만 ffmpeg"  # mac_native_gate.SOURCE_GL_FALLBACK (Ruling 10)
NATIVE_FIRST_LINE = "네이티브 화면 그리기에 실패해 이 창은 ffmpeg 방식으로 바꿉니다(설정 파일은 그대로 — 다음 창은 다시 시도)"
OLD_FIRST_LINE = "영상 화면(GL 텍스처 스트리밍)을 그리지 못했습니다 — 영상 영역을 비워 둡니다 (재생·다른 기능은 그대로)."
MENU_HINT = "Setting → 재생 디코더 → ffmpeg (예전 방식) 으로 바꾸면 예전 방식으로 재생합니다"
ENV_HINT = f"{VIDEO_ITEM_ENV}=pixmap 으로 켜면 예전 방식으로 그립니다"
SWITCH_LOG = "[표시] GL 텍스처 스트리밍 실패 — 이 창을 ffmpeg 방식으로 바꿉니다"  # 플레이어의 stdout 줄 (스펙 §5.8)
STDERR_LOG = "[표시] GL 텍스처 스트리밍 실패 — 영상 영역을 비워 둡니다"  # 아이템의 stderr 줄(트레이스백 앞) — 예전 그대로
KEEP_LOG = "[표시] 네이티브 프레임이 아직 남아 걸쇠를 풀지 않음"  # 바꿔 끼운 뒤에도 네이티브 면이 남았을 때
SWAP_FALSE_LOG = "[표시] ffmpeg 방식으로 바꾸지 못한 쪽이 있음"


@pytest.fixture
def auto(monkeypatch):
    """토글 auto — conftest의 YESONCHECK_MAC_NATIVE=off 고정을 풂 (폴백이 캐시를 따르게; off·on이면 환경 변수가 덮어 바꾸지 않음).
    창(리그)보다 먼저 요청할 것 — 메뉴는 창을 만들 때의 유효 디코더로 체크를 정함."""
    monkeypatch.delenv(NATIVE_MODE_ENV, raising=False)


@pytest.fixture
def fake_gl(recording_gl, gl_contexts, monkeypatch):  # noqa: F811 (픽스처)
    """가짜 GL·CGL과 GL2 페인터 대역 → SimpleNamespace(gl, cgl, painter) — 진짜 아이템(플레이어의 videoWidget.video_item)을 paint_gl(item, painter)로 그림.
    cgl.context = 0이면 CGLGetCurrentContext()가 NULL이라 네이티브 면 묶기가 GLBindingError(그리기 실패가 일어나는 진짜 자리)."""
    cgl = FakeCGL(recording_gl)
    monkeypatch.setattr(gl_surface, "bind_cgl", lambda: cgl)
    return SimpleNamespace(gl=recording_gl, cgl=cgl, painter=FakeGLPainter(recording_gl, QTransform()))


@pytest.fixture
def prores_probe(monkeypatch):
    """바꿔 끼움의 ProRes 판정(player_playback.probe_movie — ffprobe)을 네이티브 게이트를 통과하는 가짜 probe로 (리그의 시험 영상은 mp4v)."""
    monkeypatch.setattr(player_playback, "probe_movie", lambda path: fake_probe("prores"))


def spy_swap(player, monkeypatch):
    """swap_movie_captures_for_decoder를 진짜로 부르며 기록 → list(SimpleNamespace(latched, decoder)) — 부를 때 걸쇠가 아직 걸려 있었는지
    (Ruling 9·10: 걸쇠는 바꿔 끼운 뒤 풂 — 바꿔 끼우는 동안의 창이 옛 프레임을 다시 그려도 다시 실패하지 않게)와 그때의 캐시."""
    calls = []
    real = player.swap_movie_captures_for_decoder
    item = player.videoWidget.video_item

    def swap():
        calls.append(SimpleNamespace(latched=item._failed, decoder=preferred_decoder()))
        return real()

    monkeypatch.setattr(player, "swap_movie_captures_for_decoder", swap)
    return calls


def reopen_by_decoder(rig, monkeypatch):
    """리그의 열기 자리를 지금 유효한 디코더를 따르게 → 연 캡처 list: native_wanted()면 리그의 가짜 네이티브 캡처, 아니면 시험 영상의 진짜 cv2 캡처
    (RGB 프레임 — 진짜 길에서 ffmpeg 파이프가 여는 자리)."""
    native_open = rig.player._open_movie_capture
    opened = []

    def open_capture(path):
        cap = native_open(path) if mac_native_gate.native_wanted() else cv2.VideoCapture(path)
        opened.append(cap)
        return cap

    monkeypatch.setattr(rig.player, "_open_movie_capture", open_capture)
    return opened


def first_line(text):
    return text.split("\n", 1)[0]


# ---------------------------------------------------------------- 플레이어: 네이티브 면 실패 → 이 창만 ffmpeg

@mac_only
def test_native_paint_failure_switches_this_process_to_ffmpeg(auto, player_with_fake_native, fake_gl, prores_probe, dialogs, monkeypatch,
                                                              capsys, qapp):
    """A가 네이티브인 창: IOSurface 묶기가 실패(가짜 CGL — 컨텍스트 NULL) → paint 안에서는 걸쇠만(디코더·캡처 그대로) → Qt 루프에서 오류 창 1회(첫 줄
    "이 창은 ffmpeg 방식으로 바꿉니다", 예외 줄·메뉴 안내·킬 스위치 안내 그대로) + stderr 기록(트레이스백) + stdout 한 줄 + 캐시 ffmpeg(출처
    SOURCE_GL_FALLBACK, prefs.json은 쓰지 않음 — 없던 파일은 없는 채) + 바꿔 끼움 1회(걸쇠가 걸린 채로) → 걸쇠 풀림 → 메뉴는 ffmpeg 체크·툴팁에 그 출처.
    그 뒤 paint는 파이프(여기서는 cv2) RGB 프레임을 2D 텍스처에 올려 그리고(IOSurface 묶기 없음, 실패·창 더 없음) 다음 재생 틱도 RGB 길(set_sides 아님).

    깨지는 변경: 콜백을 예약하지 않으면 캐시 단언; set_preferred_decoder를 swap 뒤로 옮기면 swap 기록의 디코더가 videotoolbox; reset_failure를 swap 앞으로
    옮기면 latched 단언; 걸쇠를 풀지 않으면 _failed; prefs.json에 쓰면 forbid_save; 플레이어가 창을 하나 더 띄우면 창 수."""
    rig = player_with_fake_native
    player = rig.player
    item = player.videoWidget.video_item
    assert item.has_native_side() and native_surface_of(player.frame_a) is not None
    swaps = spy_swap(player, monkeypatch)
    opened = reopen_by_decoder(rig, monkeypatch)
    forbid_save(monkeypatch)
    dialogs.messages.clear()
    capsys.readouterr()
    fake_gl.cgl.context = 0

    paint_gl(item, fake_gl.painter)
    assert item._failed and item.failure_count == 1
    assert preferred_decoder() == "videotoolbox" and swaps == []  # paint 안에서는 바꾸지 않음 — Qt 루프에서
    qapp.processEvents()

    assert preferred_decoder() == "ffmpeg"
    assert effective_decoder() == ("ffmpeg", RUNTIME_SOURCE)
    assert not os.path.exists(mac_prefs.prefs_path())
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("critical", error_window.TITLE)
    assert first_line(text) == NATIVE_FIRST_LINE
    assert "GLBindingError: CGLGetCurrentContext()가 NULL" in text and text.endswith(f"\n\n{MENU_HINT}\n{ENV_HINT}")
    captured = capsys.readouterr()
    assert captured.out.count(SWITCH_LOG + "\n") == 1
    assert "[재생] 디코더 전환: A 캡처 바꿔 끼움" in captured.out
    assert captured.err.count(STDERR_LOG) == 1 and "Traceback" in captured.err
    assert [(call.latched, call.decoder) for call in swaps] == [(True, "ffmpeg")]
    [new_cap] = opened
    assert isinstance(new_cap, cv2.VideoCapture) and player.cap_a is new_cap
    assert item._failed is False and item.failure_count == 1
    assert native_surface_of(player.frame_a) is None and not item.has_native_side()
    assert checked(player) == ["ffmpeg"] and player.decoder_actions["ffmpeg"].toolTip() == RUNTIME_SOURCE

    fake_gl.gl.calls.clear()
    paint_gl(item, fake_gl.painter)  # 풀린 걸쇠 뒤의 paint — 새 프레임
    qapp.processEvents()
    frame = item.frame()
    assert native_surface_of(frame) is None
    h, w = frame.shape[:2]
    assert ("glTexSubImage2D", (GL_TEXTURE_2D, 0, 0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, frame.ctypes.data)) in fake_gl.gl.calls
    assert "CGLTexImageIOSurface2D" not in fake_gl.gl.names()
    assert item.failure_count == 1 and len(dialogs.messages) == 1

    sides_before = len(rig.sides)
    player.next_frame_playback()
    assert len(rig.sides) == sides_before  # set_sides(네이티브 길)가 아니라 set_frame
    assert native_surface_of(player.frame_a) is None and item._sides is None and item.frame() is not frame


@mac_only
def test_rgb_paint_failure_keeps_old_behaviour(fake_native_player, auto, fake_gl, dialogs, monkeypatch, capsys, qapp):
    """RGB 프레임(네이티브가 아닌 A — h264·파이프)을 그리다 실패(가짜 GL 업로드 실패): 예전 규칙 그대로 — 오류 창 1회(예전 첫 줄)·걸쇠·빈 영역, 캐시는
    videotoolbox(기본값) 그대로, 바꿔 끼움 0회, 플레이어 기록 줄 없음, 메뉴 그대로."""
    rig = fake_native_player(native="")
    player = rig.player
    item = player.videoWidget.video_item
    assert item.frame() is not None and not item.has_native_side()
    swaps = spy_swap(player, monkeypatch)
    dialogs.messages.clear()
    capsys.readouterr()
    fake_gl.gl.fail_on = "glTexSubImage2D"

    paint_gl(item, fake_gl.painter)
    qapp.processEvents()

    assert effective_decoder() == ("videotoolbox", SOURCE_DEFAULT)
    assert swaps == []
    assert item._failed is True and item.failure_count == 1
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("critical", error_window.TITLE) and first_line(text) == OLD_FIRST_LINE
    assert text.endswith(f"\n\n{MENU_HINT}\n{ENV_HINT}")
    assert SWITCH_LOG not in capsys.readouterr().out
    assert checked(player) == ["videotoolbox"] and player.decoder_actions["videotoolbox"].toolTip() == player_base.DECODER_TIP


def test_native_paint_failure_off_mac_changes_nothing(auto, player_with_fake_native, fake_gl, dialogs, monkeypatch, capsys, qapp):
    """macOS가 아니면(VideoToolbox·재생 디코더 메뉴가 없음 — 가짜 플랫폼은 그리기·이벤트 처리 동안만) 네이티브 면 실패도 예전 규칙: 창 1회(예전 첫 줄,
    메뉴 안내 없음)·걸쇠, 캐시·캡처 그대로. 어느 플랫폼에서나 돎. auto라 환경 변수가 아니라 플랫폼 조건이 막는 것을 봄."""
    rig = player_with_fake_native
    player = rig.player
    item = player.videoWidget.video_item
    swaps = spy_swap(player, monkeypatch)
    old_cap = player.cap_a
    dialogs.messages.clear()
    capsys.readouterr()
    fake_gl.cgl.context = 0
    with monkeypatch.context() as m:
        m.setattr(sys, "platform", "win32")
        paint_gl(item, fake_gl.painter)
        qapp.processEvents()
    assert preferred_decoder() == "videotoolbox" and swaps == [] and player.cap_a is old_cap
    assert item._failed is True
    [(_, _, text)] = dialogs.messages
    assert first_line(text) == OLD_FIRST_LINE and "재생 디코더" not in text
    assert SWITCH_LOG not in capsys.readouterr().out


@mac_only
def test_menu_reflects_the_runtime_switch(fake_native_player, auto, fake_gl, prores_probe, dialogs, monkeypatch, qapp):
    """prefs.json이 videotoolbox인 창(출처 prefs.json)에서 폴백: 메뉴는 'ffmpeg (예전 방식)' 체크 + 그 툴팁이 출처 "… 이 창만 ffmpeg"(두 항목 활성 —
    다시 VideoToolbox를 고를 수 있음), 파일은 글자 그대로 videotoolbox — 다음 창(시작 때 다시 읽기)은 videotoolbox(출처 prefs.json)로 다시 시도."""
    text = '{"playback_decoder": "videotoolbox"}'
    path = write_prefs(text)
    app.load_playback_decoder()
    assert effective_decoder() == ("videotoolbox", SOURCE_PREFS)
    rig = fake_native_player()
    player = rig.player
    assert checked(player) == ["videotoolbox"]
    reopen_by_decoder(rig, monkeypatch)
    forbid_save(monkeypatch)
    fake_gl.cgl.context = 0

    paint_gl(player.videoWidget.video_item, fake_gl.painter)
    qapp.processEvents()

    assert checked(player) == ["ffmpeg"]
    tip = player.decoder_actions["ffmpeg"].toolTip()
    assert tip == RUNTIME_SOURCE and "이 창만" in tip
    assert player.decoder_actions["videotoolbox"].toolTip() == player_base.DECODER_TIP
    assert all(action.isEnabled() for action in player.decoder_actions.values())
    assert read_text(path) == text
    app.load_playback_decoder()  # 다음에 켜는 창의 시작 읽기
    assert effective_decoder() == ("videotoolbox", SOURCE_PREFS)


# ---------------------------------------------------------------- 플레이어 처리기를 직접 (자동 폴백은 끄고 걸쇠만 걸어 둔 창)

@pytest.fixture
def latched(player_with_fake_native, dialogs, qapp):
    """A가 네이티브인 리그의 스트림 아이템에 걸쇠만 — 실패 콜백을 끄고 raster paint로 실패시킨 뒤 그 창을 비움 → (rig, item). 시험이 처리기를 직접 부름."""
    rig = player_with_fake_native
    item = rig.player.videoWidget.video_item
    item.set_failure_callback(None)
    paint_on_raster(item)
    qapp.processEvents()
    assert item._failed and item.has_native_side()
    dialogs.messages.clear()
    return rig, item


@mac_only
def test_fallback_keeps_the_latch_while_a_native_frame_is_still_shown(auto, latched, monkeypatch, capsys, dialogs):
    """바꿔 끼우지 못해(swap → False — 그 함수가 이미 창을 띄움) 네이티브 프레임이 아직 그려질 그림이면 걸쇠를 풀지 않음: 풀면 다음 paint가 같은 표면을
    다시 묶다 실패해 창·폴백이 끝없이 되풀이됨. 캐시는 ffmpeg(다음에 열 때부터), 기록 줄, 메뉴 맞춤, 처리기는 창을 띄우지 않음."""
    rig, item = latched
    player = rig.player
    calls = []
    monkeypatch.setattr(player, "swap_movie_captures_for_decoder", lambda: calls.append("swap") or False)
    capsys.readouterr()

    player._on_stream_paint_failed(True)

    assert calls == ["swap"]
    assert effective_decoder() == ("ffmpeg", RUNTIME_SOURCE)
    assert item._failed is True
    out = capsys.readouterr().out
    assert SWITCH_LOG in out and SWAP_FALSE_LOG in out and KEEP_LOG in out
    assert checked(player) == ["ffmpeg"] and dialogs.messages == []


@mac_only
@pytest.mark.parametrize("replaced", [True, False])
def test_swap_exception_still_settles_latch_and_menu(auto, latched, monkeypatch, replaced):
    """바꿔 끼우다 예외(코드·빌드 쪽 — 잡지 않음)가 나도 걸쇠 판단과 메뉴 맞춤은 함(finally) 뒤 예외를 그대로 올림: 예외 전에 새 RGB 프레임이 걸렸으면
    걸쇠를 풀고, 네이티브 프레임이 그대로면 풀지 않음(다시 실패 → 되풀이 방지)."""
    rig, item = latched
    player = rig.player

    def broken_swap():
        if replaced:
            player.videoWidget.updateFrame(np.zeros((FAKE_HEIGHT, FAKE_WIDTH, 3), np.uint8), None)
        raise RuntimeError("가짜 바꿔 끼움 오류")

    monkeypatch.setattr(player, "swap_movie_captures_for_decoder", broken_swap)
    with pytest.raises(RuntimeError, match="가짜 바꿔 끼움 오류"):
        player._on_stream_paint_failed(True)
    assert item._failed is (not replaced)
    assert checked(player) == ["ffmpeg"] and player.decoder_actions["ffmpeg"].toolTip() == RUNTIME_SOURCE


@mac_only
def test_env_override_keeps_the_decoder(latched, monkeypatch, capsys):
    """YESONCHECK_MAC_NATIVE=on(켬 강제 — 설정·캐시를 덮음)이면 캐시를 바꿔도 다시 네이티브로 열리므로 바꾸지 않음: 캐시·캡처 그대로, 걸쇠 그대로(빈 영역 —
    예전 규칙), 기록 한 줄에 그 출처."""
    monkeypatch.setenv(NATIVE_MODE_ENV, "on")
    rig, item = latched
    player = rig.player
    forbid_swap = []
    monkeypatch.setattr(player, "swap_movie_captures_for_decoder", lambda: forbid_swap.append("swap"))
    capsys.readouterr()

    player._on_stream_paint_failed(True)

    assert forbid_swap == []
    assert preferred_decoder() == "videotoolbox" and effective_decoder() == ("videotoolbox", f"환경 변수 {NATIVE_MODE_ENV}=on")
    assert item._failed is True
    out = capsys.readouterr().out
    assert f"환경 변수 {NATIVE_MODE_ENV}=on" in out and SWITCH_LOG not in out


@mac_only
def test_rgb_failure_signal_does_nothing(auto, latched, monkeypatch, capsys):
    """native=False(RGB 면 실패)는 처리기가 아무것도 안 함 — 캐시·캡처·걸쇠·메뉴 그대로, 기록 없음."""
    rig, item = latched
    player = rig.player
    monkeypatch.setattr(player, "swap_movie_captures_for_decoder", lambda: pytest.fail("바꿔 끼우면 안 됩니다"))
    capsys.readouterr()
    player._on_stream_paint_failed(False)
    assert effective_decoder() == ("videotoolbox", SOURCE_DEFAULT) and item._failed is True
    assert capsys.readouterr().out == "" and checked(player) == ["videotoolbox"]


# ---------------------------------------------------------------- 아이템: 실패 콜백·창 글

def rgb_frame():
    return np.zeros((FAKE_HEIGHT, FAKE_WIDTH, 3), np.uint8)


def show(item, picture):
    """picture대로 아이템에 그림을 건다 — native: 네이티브 A만, rgb: RGB 배열, native_then_rgb: 네이티브 뒤 RGB(set_frame이 면 그리기를 끝냄),
    rgb_a_native_b_wipe: A RGB + B 네이티브(와이프 x — B를 그림), rgb_a_native_b_no_wipe: 같은 면이지만 와이프 없음(B를 그리지 않음)."""
    [native] = spy_frames(1, [])
    if picture == "native":
        item.set_surface(native)
    elif picture == "rgb":
        item.set_frame(rgb_frame())
    elif picture == "native_then_rgb":
        item.set_surface(native)
        item.set_frame(rgb_frame())
    elif picture == "rgb_a_native_b_wipe":
        item.set_sides(rgb_frame(), native, "x", 0.5)
    elif picture == "rgb_a_native_b_no_wipe":
        item.set_sides(rgb_frame(), native, None, 0.0)
    else:
        raise AssertionError(picture)


@pytest.mark.parametrize("picture, native", [("native", True), ("rgb", False), ("native_then_rgb", False),
                                             ("rgb_a_native_b_wipe", True), ("rgb_a_native_b_no_wipe", False)])
def test_failure_callback_gets_native_flag_in_the_qt_loop(qapp, dialogs, picture, native):
    """콜백은 _fail 안(paint 안)이 아니라 Qt 루프에서 한 번, 값은 그리던 그림에 IOSurface 면이 있었는가(그릴 면만 — 와이프가 아니면 B는 안 셈) —
    걸쇠가 걸린 동안의 두 번째 실패는 알리지 않음(콜백도 없음). 오류 창도 1회."""
    item = VideoFrameItem(stream=True)
    calls = []
    item.set_failure_callback(calls.append)
    show(item, picture)
    assert item.has_native_side() is native
    item._fail(gl_bindings.GLBindingError("x"))
    item._fail(gl_bindings.GLBindingError("y"))
    assert calls == []
    qapp.processEvents()
    assert calls == [native] and len(dialogs.messages) == 1


@pytest.mark.parametrize("platform, callback, picture, announces", [
    ("darwin", True, "native", True),
    ("darwin", False, "native", False),  # 받을 쪽이 없으면 바꾼다고 하지 않음
    ("darwin", True, "rgb", False),
    ("win32", True, "native", False),  # Mac 밖에는 바꿀 디코더가 없음
])
def test_native_failure_window_announces_the_switch(qapp, dialogs, monkeypatch, platform, callback, picture, announces):
    """네이티브 면 실패 + Mac + 콜백이 있으면 창의 첫 줄만 "이 창은 ffmpeg 방식으로 바꿉니다…" — 예외 줄·메뉴 안내(Mac)·킬 스위치 안내는 그대로.
    그 밖은 예전 첫 줄."""
    monkeypatch.setattr(sys, "platform", platform)
    item = VideoFrameItem(stream=True)
    if callback:
        item.set_failure_callback(lambda native: None)
    show(item, picture)
    item._fail(gl_bindings.GLBindingError("x"))
    qapp.processEvents()
    [(_, _, text)] = dialogs.messages
    menu = f"{MENU_HINT}\n" if platform == "darwin" else ""
    assert text == f"{NATIVE_FIRST_LINE if announces else OLD_FIRST_LINE}\n\nGLBindingError: x\n\n{menu}{ENV_HINT}"


def test_failure_callback_exception_goes_to_last_resort(qapp, dialogs, monkeypatch):
    """콜백이 예외를 내도 _fail은 예외를 내지 않고(paint 가드) Qt 루프로도 내보내지 않음 — 원래 stderr(_last_resort)에 무엇을 못 했는지 + 콜백의 트레이스백.
    오류 창은 그대로 뜸."""
    original = io.StringIO()
    monkeypatch.setattr(sys, "__stderr__", original)
    item = VideoFrameItem(stream=True)

    def broken(native):
        raise RuntimeError("가짜 콜백 오류")

    item.set_failure_callback(broken)
    show(item, "native")
    item._fail(gl_bindings.GLBindingError("x"))
    assert original.getvalue() == ""
    qapp.processEvents()
    logged = original.getvalue()
    assert logged.count("[표시] 오류를 알리지 못했습니다") == 1 and "실패 콜백" in logged and "가짜 콜백 오류" in logged
    assert len(dialogs.messages) == 1 and item.failure_count == 1


def test_failure_callback_scheduling_error_goes_to_last_resort(qapp, dialogs, monkeypatch):
    """콜백 예약 자체가 실패해도(QTimer 대역) _fail은 예외를 내지 않음 — _last_resort에 기록, 창 예약은 그 앞이라 그대로."""
    original = io.StringIO()
    monkeypatch.setattr(sys, "__stderr__", original)
    item = VideoFrameItem(stream=True)
    item.set_failure_callback(lambda native: None)
    show(item, "native")
    scheduled = []

    class OneShotTimer:
        @staticmethod
        def singleShot(msec, func):
            if scheduled:
                raise RuntimeError("가짜 예약 실패")
            scheduled.append(func)

    monkeypatch.setattr(gl_video_item, "QTimer", OneShotTimer)
    item._fail(gl_bindings.GLBindingError("x"))
    assert len(scheduled) == 1  # 창
    assert "실패 콜백" in original.getvalue() and "가짜 예약 실패" in original.getvalue()


def test_set_failure_callback_accepts_none_and_rejects_non_callables(qapp, dialogs):
    """None은 끔(창만 — 예전 동작), 부를 수 없는 값은 TypeError."""
    item = VideoFrameItem(stream=True)
    calls = []
    item.set_failure_callback(calls.append)
    item.set_failure_callback(None)
    show(item, "native")
    item._fail(gl_bindings.GLBindingError("x"))
    qapp.processEvents()
    assert calls == [] and len(dialogs.messages) == 1
    assert first_line(dialogs.messages[0][2]) == OLD_FIRST_LINE
    with pytest.raises(TypeError, match="실패 콜백"):
        item.set_failure_callback("not callable")


# ---------------------------------------------------------------- 위젯: 콜백 → streamPaintFailed 신호

def test_stream_widget_reemits_failure_as_signal(qapp, dialogs, monkeypatch):
    """스트림 아이템을 가진 위젯(강제 GL 뷰포트)은 아이템의 실패 콜백을 streamPaintFailed(bool)로 넘김 — Qt 루프에서, 값 그대로."""
    from yesoncheck.video_widget import CustomVideoWidget

    monkeypatch.setenv("YESONCHECK_VIEWPORT", "gl")
    widget = CustomVideoWidget()
    try:
        assert widget.video_item_stream
        got = []
        widget.streamPaintFailed.connect(got.append)
        show(widget.video_item, "native")
        widget.video_item._fail(gl_bindings.GLBindingError("x"))
        assert got == []
        qapp.processEvents()
        assert got == [True]
    finally:
        widget.close()


def test_player_connects_the_stream_failure_signal(player_with_fake_native):
    """플레이어가 창을 만들 때(공급자 등록 옆) 위젯의 streamPaintFailed를 처리기 하나에 이음 — 어느 플랫폼에서나(처리기가 Mac 밖에서는 아무것도 안 함).
    신호 → 처리기의 실제 흐름은 위 Mac 시험들이 아이템의 실패부터 따라감."""
    widget = player_with_fake_native.player.videoWidget
    assert widget.receivers(widget.streamPaintFailed) == 1
