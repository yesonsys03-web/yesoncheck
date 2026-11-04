"""플레이어의 네이티브 분기 (Apple Silicon 네이티브 재생 — 계획 Task 11·B6).

네이티브 프레임(IOSurface 위 BGRX 뷰 — frame_handles.NativeFrameArray)은 재생 틱·탐색에서 CPU가 픽셀을 만지지 않는다: process_frame·
optimize_for_4k·드래그 미리보기의 색 변환을 건너뛰고(cv2.cvtColor는 4채널 strided 배열도 받아 3채널 복사본을 만들어 손잡이를 조용히 잃음),
frame_cache에 넣지 않고(copy() 4K 33MB), videoWidget.updateFrame이 numpy 합성 없이 VideoFrameItem.set_sides로 넘긴다(와이프는 axis·ratio —
X·Y가 함께면 "xy"와 (rx, ry)). 픽스맵 아이템(킬 스위치·raster)은 A만 Format_RGB32로 표면 메모리를 가리키고 그 배열을 _pixmap_backing에 쥔다.
재생이 마지막 프레임에 닿으면 [측정] 줄 하나(Play마다 — 모든 캡처).

가짜 네이티브 캡처(tests/native_fakes — VideoToolbox·PyObjC 없음)를 플레이어의 캡처 열기 자리에 꽂은 진짜 VideoPlayer(offscreen)를 쓴다.
화면은 GL 뷰포트 + 스트림 아이템(YESONCHECK_VIEWPORT=gl 강제 — Apple Silicon의 기본 길; offscreen엔 GL 컨텍스트가 없지만 창을 띄우지 않아
paint는 일어나지 않음)이고 set_sides는 기록하며 진짜로 부른다(인자가 틀리면 진짜 set_sides의 ValueError로 드러남). 픽셀 접근은 둘로 센다:
rig.reads(SpyNativeArray가 본 파이썬 쪽 접근 — 인덱싱·ufunc·numpy 함수·tobytes·.data …)와 rig.cvt_calls(네이티브 프레임을 받은 cv2.cvtColor —
C 확장의 버퍼 읽기는 파이썬에서 못 보므로 함수를 바꿔치기). 비네이티브 길이 그대로인지는 기존 시험 파일(test_display_single_draw·test_pipe_player·
test_overlay_slider_sync·test_gl_video_item 등)의 무수정 통과와 ci/screenshot_check.py가 지킨다(Ruling 4 — 여기서 갈음 시험을 따로 두지 않음).
"""

import re

import pytest
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QGraphicsPixmapItem, QOpenGLWidget

from tests.conftest import write_test_video
from tests.native_fakes import (  # noqa: F401 (픽스처 — new_player는 native_fakes의 픽스처가 요청함)
    FAKE_FRAME_COUNT,
    FAKE_HEIGHT,
    FAKE_WIDTH,
    fake_bgr,
    fake_native_player,
    new_player,
    player_with_fake_native,
    player_with_fake_native_ab,
)
from tests.test_work_paths_ui import make_config
from yesoncheck.gl_video_item import VideoFrameItem

TOTAL = FAKE_FRAME_COUNT
MEASURE = re.compile(r"^\[측정\] (\d+)장 (\d+\.\d\d)초 \((\d+\.\d)fps\) 네이티브=(yes|no) 와이프=(on|off) 표시=(gl|pixmap|raster) — (.+)$")


def assert_untouched(rig):
    """연 뒤로 네이티브 프레임의 픽셀을 CPU가 만진 적이 없음 — 파이썬 쪽 접근 0, cv2.cvtColor 0."""
    assert rig.reads == [], f"네이티브 프레임의 픽셀을 파이썬에서 읽음: {rig.reads}"
    assert rig.cvt_calls == [], f"네이티브 프레임을 cv2.cvtColor로 변환함 (code {rig.cvt_calls})"


def measure_lines(text):
    return [line for line in text.splitlines() if line.startswith("[측정]")]


def play_to_end(player):
    """재생 중인 플레이어의 틱을 직접 돌려 끝까지 (끝을 지나면 handle_video_end가 타이머를 멈춤) → 돈 틱 수."""
    ticks = 0
    while player.timer.isActive():
        player.next_frame_playback()
        ticks += 1
        assert ticks <= TOTAL + 2, "끝에 닿았는데 재생이 멈추지 않음"
    return ticks


# ---------------------------------------------------------------- 재생 틱

def test_playback_tick_touches_no_pixels(player_with_fake_native):
    """재생 틱 5번(와이프 꺼짐): 픽셀 접근 0·cvtColor 0, frame_a는 캡처가 준 그 객체, 틱마다 set_sides 한 번(A = 그 프레임, B 없음, axis None).

    깨지는 변경: process_frame 첫 줄의 네이티브 가드를 빼면 cvtColor가 3채널 복사본을 만듦(cvt_calls, frame_a가 다른 객체, set_sides 대신 set_frame);
    updateFrame의 네이티브 분기를 빼면 기존 길이 frame_a.data를 읽고(reads) set_frame이 4채널을 거부(ValueError)."""
    rig = player_with_fake_native
    player = rig.player
    assert player.videoWidget.video_item_stream and isinstance(player.videoWidget.video_item, VideoFrameItem)
    rig.sides.clear()

    for _ in range(5):
        player.next_frame_playback()

    assert_untouched(rig)
    assert player.get_current_frame_index() == 5
    assert player.frame_a is rig.cap_a.frames[5]
    assert len(rig.sides) == 5, f"틱 5번에 set_sides {len(rig.sides)}번"
    for call, index in zip(rig.sides, range(1, 6)):
        assert call.a is rig.cap_a.frames[index] and call.b is None and call.axis is None
    assert player.videoWidget.video_item.surface_handle() is rig.cap_a.frames[5].native  # 진짜 set_sides까지 감 — 표면 전체로 받음


def test_wipe_tick_touches_no_pixels_and_uses_sides(player_with_fake_native_ab):
    """A·B 와이프 틱: 픽셀 접근 0·cvtColor 0, B도 캡처가 준 그 객체이고 numpy 합성 없이 set_sides(A, B, axis, ratio)로 —
    축 없음 → (A, None, None), X만 → ("x", wipe_position_x), X·Y → ("xy", (rx, ry)) (Ruling 17), Y만 → ("y", wipe_position_y).

    깨지는 변경: updateFrame 네이티브 분기의 axis·ratio 대응이 틀리면(예: X·Y를 "x" 하나로) 단언이, 와이프인데 B를 빼면 b 단언이, 기존 numpy 합성
    길로 떨어지면 frame_a.copy()·조각 대입(reads)이 잡음. 틱에서 B의 process_frame 가드를 빼면 cvt_calls."""
    rig = player_with_fake_native_ab
    player, widget = rig.player, rig.player.videoWidget
    rig.sides.clear()
    player.next_frame_playback()  # 와이프 체크만 켜고 축은 끔 — B는 읽지만 싣지 않음
    assert player.frame_b is rig.cap_b.frames[1]
    assert [(c.a is rig.cap_a.frames[1], c.b, c.axis) for c in rig.sides] == [(True, None, None)]

    player.wipeXButton.setChecked(True)
    widget.wipe_position_x = 0.25
    rig.sides.clear()

    for _ in range(3):
        player.next_frame_playback()

    assert_untouched(rig)
    assert len(rig.sides) == 3
    for call, index in zip(rig.sides, range(2, 5)):
        assert call.a is rig.cap_a.frames[index] and call.b is rig.cap_b.frames[index]
        assert (call.axis, call.ratio) == ("x", 0.25)
    assert player.frame_b is rig.cap_b.frames[4]

    player.wipeYButton.setChecked(True)  # X·Y 함께 — 토글이 한 번 그림(같은 프레임)
    widget.wipe_position_y = 0.75
    rig.sides.clear()
    player.next_frame_playback()
    call = rig.sides[-1]
    assert call.a is rig.cap_a.frames[5] and call.b is rig.cap_b.frames[5]
    assert (call.axis, call.ratio) == ("xy", (0.25, 0.75))

    player.wipeXButton.setChecked(False)  # Y만
    rig.sides.clear()
    player.next_frame_playback()
    call = rig.sides[-1]
    assert call.a is rig.cap_a.frames[6] and call.b is rig.cap_b.frames[6]
    assert (call.axis, call.ratio) == ("y", 0.75)

    player.wipeYButton.setChecked(False)  # 축 없음 — B를 늘 넘기는 호출처(_update_ui_for_last_frame)에서도 B를 싣지 않음
    rig.sides.clear()
    player._precise_seek(TOTAL - 1, TOTAL)
    assert player.frame_b is rig.cap_b.frames[TOTAL - 1]  # B는 읽었음 (와이프 체크가 켜져 있음)
    assert len(rig.sides) >= 2  # _update_ui_for_last_frame(B를 넘김)와 그 뒤 update_frame(B 없음) 둘 다
    for call in rig.sides:
        assert call.a is rig.cap_a.frames[TOTAL - 1] and call.b is None and call.axis is None
    assert_untouched(rig)


def test_4k_frames_skip_optimize_for_4k_conversion(fake_native_player):
    """4K 크기 네이티브 프레임(optimize_for_4k의 4K 갈래 — 성능 모드별 cv2.cvtColor·process_frame_gpu_optimized): 그 함수를 지나는 탐색 길
    (_quick_preview_seek·_overlay_slider_preview_seek — 드래그 아님, _overlay_slider_final_seek; A·B)에서 픽셀 접근 0·cvtColor 0, 캡처가 준 그 객체.
    HD 이하 프레임은 optimize_for_4k가 process_frame으로 넘겨 그 가드에 걸리므로 4K 크기가 있어야 이 가드를 봄.

    깨지는 변경: optimize_for_4k 첫 줄의 네이티브 가드를 빼면 4K 갈래의 cvtColor가 3채널 복사본을 만듦(cvt_calls·frame_a가 다른 객체)."""
    rig = fake_native_player(ab=True, size=(3840, 2160))
    player = rig.player
    assert rig.cap_a.frames[0].shape == (2160, 3840, 4)
    player.wipeXButton.setChecked(True)

    player._quick_preview_seek(40, TOTAL)
    assert player.frame_a is rig.cap_a.frames[40] and player.frame_b is rig.cap_b.frames[40]
    player._overlay_slider_preview_seek(20, TOTAL)
    assert player.frame_a is rig.cap_a.frames[20]
    player._overlay_slider_final_seek(30, TOTAL)
    assert player.frame_a is rig.cap_a.frames[30] and player.frame_b is rig.cap_b.frames[30]

    assert_untouched(rig)
    assert rig.sides[-1].a is player.frame_a and rig.sides[-1].b is player.frame_b


def test_mixed_rgb_a_and_native_b_uses_sides(fake_native_player):
    """혼합 비교(A = cv2 RGB 프레임 — h264 흉내, B = 네이티브): A만 RGB여도 B가 네이티브면 네이티브 분기 — set_sides(RGB A, 네이티브 B, axis)로
    아이템이 면마다 따로 올리고/묶음; B의 픽셀은 CPU가 만지지 않음.

    깨지는 변경: updateFrame 분기 조건을 A만 보게 하면 기존 길로 떨어져(4채널 B는 shape이 달라 검정으로 합성) set_sides가 없음."""
    rig = fake_native_player(ab=True, native="B", size=(32, 16), count=24)
    player = rig.player
    player.wipeXButton.setChecked(True)
    rig.sides.clear()

    player.next_frame_playback()

    assert player.frame_a.shape == (16, 32, 3) and player.frame_b is rig.cap_b.frames[1]
    call = rig.sides[-1]
    assert call.a is player.frame_a and call.b is rig.cap_b.frames[1] and call.axis == "x"
    assert_untouched(rig)


# ---------------------------------------------------------------- 탐색 길

def _drag(player):
    player.is_dragging = True


def _loop_at_end(player):
    player.loopCheckBox.setChecked(True)
    player.seek_to_frame(TOTAL)  # 마지막 프레임 — 다음 틱의 read가 끝(False)


def _loop_action(player):
    player.next_frame_playback()  # 끝 → handle_video_end → 반복: seek_to_frame(1) → play_video
    assert player.timer.isActive(), "반복 재생이 다시 재생을 켜지 않음"
    player.next_frame_playback()  # 처음부터 이어 재생 — 1번 프레임


# (시험 id, 길, 준비, 동작, 보일 프레임 번호, 화면에 실린 B: "B" = 이번에 읽은 B[번호], "none" = B 없음, "held" = 전에 읽어 둔 플레이어의 frame_b 그대로)
SEEK_PATHS = [
    ("seek_to_frame", "seek_to_frame — 휠·되감기", None, lambda p: p.seek_to_frame(41), 40, "B"),
    ("next_frame", "next_frame — → (_seek_direct_fast 가까운 앞)", None, lambda p: p.next_frame(), 1, "held"),
    ("prev_frame", "prev_frame — ← (_seek_prev_frame_optimized)", lambda p: p.seek_to_frame(21), lambda p: p.prev_frame(), 19, "held"),
    ("seek_direct_fast_far", "_seek_direct_fast 먼 곳", None, lambda p: p._seek_direct_fast(30, TOTAL), 30, "held"),
    ("seek_direct_fast_near_back", "_seek_direct_fast 가까운 뒤", lambda p: p.seek_to_frame(11), lambda p: p._seek_direct_fast(7, TOTAL), 7, "held"),
    ("quick_preview_drag", "_quick_preview_seek 드래그 중 — 인라인 색 변환 자리", _drag, lambda p: p._quick_preview_seek(40, TOTAL), 40, "none"),
    ("quick_preview", "_quick_preview_seek 드래그 아님 — optimize_for_4k(A·B)", None, lambda p: p._quick_preview_seek(40, TOTAL), 40, "B"),
    ("minimal_preview", "_minimal_preview_seek — OCR 검토 창, 인라인 색 변환 자리", None, lambda p: p._minimal_preview_seek(60, TOTAL), 60, "none"),
    ("precise_seek_middle", "_precise_seek 가운데 — 슬라이더 놓음(_seek_direct)", None, lambda p: p._precise_seek(30, TOTAL), 30, "B"),
    ("precise_seek_last", "_precise_seek 끝 — 슬라이더 끝(_seek_to_last_frame)", None, lambda p: p._precise_seek(TOTAL - 1, TOTAL), TOTAL - 1, "B"),
    ("overlay_preview_drag", "_overlay_slider_preview_seek 드래그 중 — 인라인 색 변환 자리", _drag,
     lambda p: p._overlay_slider_preview_seek(40, TOTAL), 40, "none"),
    ("overlay_preview", "_overlay_slider_preview_seek 드래그 아님 — optimize_for_4k", None, lambda p: p._overlay_slider_preview_seek(40, TOTAL), 40, "none"),
    ("overlay_final", "_overlay_slider_final_seek — optimize_for_4k(A·B)", None, lambda p: p._overlay_slider_final_seek(40, TOTAL), 40, "B"),
    ("loop_at_end", "반복 재생 끝 → 처음부터", _loop_at_end, _loop_action, 1, "B"),
]


@pytest.mark.parametrize("name, prepare, action, index, shown_b", [case[1:] for case in SEEK_PATHS], ids=[case[0] for case in SEEK_PATHS])
def test_seek_paths_touch_no_pixels(fake_native_player, name, prepare, action, index, shown_b):
    """탐색 길마다(A·B 와이프 X를 켠 상태 — B를 읽는 길의 B 쪽 자리까지): 픽셀 접근 0·cvtColor 0, frame_a(·frame_b)는 캡처가 준 그 객체, 마지막 그림은
    set_sides에 그 프레임 — 몇 길은 예외를 삼키므로(_quick_preview_seek 등) 그림까지 갔는지를 set_sides로 확인.

    깨지는 변경: process_frame·optimize_for_4k 첫 줄의 네이티브 가드, 드래그 미리보기 세 자리(_overlay_slider_preview_seek·_minimal_preview_seek·
    _quick_preview_seek)를 process_frame(…, gpu=False)로 보낸 것 중 하나라도 되돌리면 cvt_calls(그리고 frame_a가 다른 객체); updateFrame의 네이티브
    분기를 빼면 reads 또는 set_sides 없음."""
    rig = fake_native_player(ab=True)
    player = rig.player
    player.wipeXButton.setChecked(True)
    if prepare is not None:
        prepare(player)
    rig.sides.clear()

    action(player)

    assert_untouched(rig)
    assert player.frame_a is rig.cap_a.frames[index], f"{name}: 보일 프레임 {index}가 아님"
    assert rig.sides, "set_sides로 그리지 않음 (탐색 길이 그림까지 가지 않았거나 네이티브 분기를 안 탐)"
    last = rig.sides[-1]
    assert last.a is player.frame_a and last.axis == "x"
    if shown_b == "B":
        assert player.frame_b is rig.cap_b.frames[index] and last.b is player.frame_b
    elif shown_b == "none":
        assert last.b is None
    else:
        assert last.b is player.frame_b and player.frame_b is not None


def test_frame_cache_skips_native(player_with_fake_native):
    """드래그 미리보기가 frame_cache에 넣는 자리(_quick_preview_seek → cache_frame)와 cache_frame 직접 호출 모두 네이티브 프레임은 넣지 않음.

    깨지는 변경: cache_frame 첫 줄의 네이티브 가드를 빼면 frame.copy()(4K 33MB)가 캐시에 들어감(frame_cache·reads의 copy)."""
    rig = player_with_fake_native
    player = rig.player
    player.is_dragging = True

    player._quick_preview_seek(40, TOTAL)
    player.cache_frame(7, rig.cap_a.frames[7])

    assert player.frame_a is rig.cap_a.frames[40]  # 탐색은 일어났음 (캐시에 넣는 줄까지 감)
    assert len(player.frame_cache) == 0
    assert player.get_cached_frame(40) is None
    assert_untouched(rig)


# ---------------------------------------------------------------- 픽스맵 폴백

@pytest.mark.parametrize("viewport, video_item", [("gl", "pixmap"), ("raster", None)], ids=["pixmap_kill_switch", "raster_viewport"])
def test_pixmap_fallback_keeps_backing(fake_native_player, viewport, video_item):
    """스트림 아이템이 아닌 화면(킬 스위치 YESONCHECK_VIDEO_ITEM=pixmap·raster 뷰포트): 네이티브 A를 QImage Format_RGB32로 복사 없이 가리켜
    픽스맵으로 — 그 배열을 _pixmap_backing에 쥠(RGB32 픽스맵은 버퍼를 함께 씀), 그림은 BGRX 바이트 그대로의 색(행 패딩 반영), 와이프를 켜도 A만.

    깨지는 변경: _pixmap_backing을 쥐지 않으면 backing 단언; bytesPerLine을 너비×4로 두면(행 패딩 무시) 둘째 행부터 색이 어긋남; RGB888로 읽으면
    색·크기가 틀림; 픽스맵 길에서 B를 합성하면 오른쪽 절반이 B 색."""
    rig = fake_native_player(ab=True, viewport=viewport, video_item=video_item)
    player, widget = rig.player, rig.player.videoWidget
    assert widget.video_item_stream is False and type(widget.video_item) is QGraphicsPixmapItem
    player.wipeXButton.setChecked(True)

    player.next_frame_playback()

    frame = rig.cap_a.frames[1]
    assert player.frame_a is frame and widget._pixmap_backing is frame
    image = widget.video_item.pixmap().toImage()
    assert (image.width(), image.height()) == (FAKE_WIDTH, FAKE_HEIGHT)
    for x, y in ((0, 0), (5, 3), (FAKE_WIDTH - 1, FAKE_HEIGHT - 1)):  # 오른쪽 끝 = 와이프 X의 B 쪽
        b, g, r = fake_bgr(1, x, y, "A")
        assert image.pixelColor(x, y) == QColor(r, g, b), f"({x}, {y})"

    player.next_frame_playback()
    assert widget._pixmap_backing is rig.cap_a.frames[2]  # 다음 그림의 배열로 바뀜
    assert rig.cvt_calls == []


# ---------------------------------------------------------------- [측정] 줄

@pytest.mark.parametrize(
    "viewport, video_item, ab, display, wipe",
    [("gl", None, False, "gl", "off"), ("gl", "pixmap", False, "pixmap", "off"), ("raster", None, False, "raster", "off"),
     ("gl", None, True, "gl", "on")],
    ids=["gl_stream", "pixmap_kill_switch", "raster", "gl_wipe"],
)
def test_playback_end_prints_measurement_line(fake_native_player, capsys, viewport, video_item, ab, display, wipe):
    """Play부터 마지막 프레임까지: [측정] 줄이 정확히 한 번 — 장 수 = Play 뒤 진행한 장 수, 네이티브=yes, 와이프·표시 토큰, 파일 이름.
    도중에 멈췄다 다시 Play하면 그 Play부터 다시 셈(멈춘 Play는 줄이 없음).

    깨지는 변경: play_video의 시작 기록을 빼면 줄이 없음; Play마다 리셋하지 않으면 둘째 줄의 장 수가 틀림; 마지막 틱에서 기록을 닫지 않으면
    끝(읽기 실패)에서 한 번 더 찍혀 두 줄; 표시 토큰을 위젯 상태에서 가르지 않으면 표시= 단언."""
    rig = fake_native_player(ab=ab, viewport=viewport, video_item=video_item)
    player = rig.player
    if ab:
        player.wipeXButton.setChecked(True)
    player.timer.stop()
    capsys.readouterr()

    player.play_video()  # 첫 프레임(0)이 보이는 자리에서 Play
    play_to_end(player)

    lines = measure_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    match = MEASURE.match(lines[0])
    assert match, lines[0]
    frames, seconds, fps, native, wipe_token, display_token, name = match.groups()
    assert int(frames) == TOTAL - 1  # 1번부터 마지막(TOTAL-1)번까지 진행
    assert float(seconds) >= 0 and float(fps) >= 0
    assert (native, wipe_token, display_token, name) == ("yes", wipe, display, "clip_a.mov")

    player.play_video()  # 끝난 뒤 stop_video가 처음으로 되감음 — 두 번째 Play
    for _ in range(3):
        player.next_frame_playback()
    player.pause_video()  # 멈춘 Play는 줄 없음
    player.play_video()  # 세 번째 Play — 4번 프레임 다음부터
    play_to_end(player)

    lines = measure_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert int(MEASURE.match(lines[0]).group(1)) == TOTAL - 1 - 3
    assert_untouched(rig)


def test_measurement_line_when_capture_overreports_frame_count(fake_native_player, capsys):
    """프레임 수를 실제보다 크게 알리는 캡처(cv2 영상에 있음): 마지막 틱에 '끝 자리'에 닿지 않으므로 끝을 읽기 실패에서 알고 그때 한 줄 —
    시간은 마지막으로 그린 틱까지.

    깨지는 변경: next_frame_playback의 읽기 실패 자리에서 [측정] 줄을 찍지 않으면 줄이 없음."""
    rig = fake_native_player(reported_count=TOTAL + 2)
    player = rig.player
    player.timer.stop()
    capsys.readouterr()

    player.play_video()
    play_to_end(player)

    lines = measure_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert MEASURE.match(lines[0]).group(1, 4, 6) == (str(TOTAL - 1), "yes", "gl")


def test_measurement_line_for_cv2_capture(new_player, dialogs, tmp_path, qapp, capsys):  # noqa: F811 (new_player: 픽스처)
    """네이티브가 아닌 캡처(시험 영상의 cv2 캡처 — offscreen 기본 raster)에서도 끝에 한 줄: 네이티브=no·표시=raster.

    깨지는 변경: [측정] 줄을 네이티브 프레임일 때만 찍으면 줄이 없음."""
    player = new_player(make_config(str(tmp_path), {}))
    video = write_test_video(str(tmp_path / "plain.mov"), frames=12)
    assert player.open_file("A", video)
    assert not isinstance(player.videoWidget.viewport(), QOpenGLWidget)
    capsys.readouterr()

    player.play_video()
    player.timer.start(600000)  # 저절로 울리지 않게 — 틱은 시험이 직접 (play_video가 켠 간격만 바꿈)
    while player.timer.isActive():
        player.next_frame_playback()

    lines = measure_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert MEASURE.match(lines[0]).groups()[0] == "11"
    assert MEASURE.match(lines[0]).group(4, 5, 6, 7) == ("no", "off", "raster", "plain.mov")
