"""슬라이더 호버 썸네일의 순수 규칙 (yesoncheck/hover_strip.py) — Qt·ffmpeg 없이 본다.

띠 계획(장수·간격·크기)·띠 저장소(numpy 한 덩어리 + 채움 표시)·파일 크기 상한·켬/끔 설정을 시험한다. 상수는 시험이
monkeypatch로 바꿔 끼울 수 있게 모듈 값을 부를 때마다 읽는다 (MAX_THUMBS·MAX_FILE_BYTES).
"""

import os
import sys

import pytest

from yesoncheck import hover_strip, mac_prefs, windows_display
from yesoncheck.frame_cache_budget import gb
from yesoncheck.user_files import UserFileError


@pytest.fixture(autouse=True)
def restore_enabled_cache():
    """set_enabled가 바꾸는 프로세스 캐시를 시험이 끝나면 기본(켬)으로 — 실행 순서·다른 시험에 영향을 남기지 않음."""
    yield
    hover_strip.set_enabled(True)


# ---------------------------------------------------------------- 띠 계획


def test_plan_short_file_every_frame():
    plan = hover_strip.plan_for(334, 3840, 2160)
    assert (plan.step, plan.count, plan.width, plan.height) == (1, 334, 320, 180)
    assert plan.source_frame(10) == 10 and plan.sample_for(10) == 10


def test_plan_long_file_is_sampled():
    assert (hover_strip.plan_for(501, 1920, 1080).step, hover_strip.plan_for(501, 1920, 1080).count) == (2, 251)
    plan = hover_strip.plan_for(14_400, 1920, 1080)
    assert (plan.step, plan.count) == (29, 497)
    assert plan.source_frame(3) == 87
    assert plan.sample_for(0) == 0 and plan.sample_for(14_399) == 496 and plan.sample_for(43) == 1 and plan.sample_for(44) == 2


def test_plan_single_frame():
    plan = hover_strip.plan_for(1, 320, 240)
    assert (plan.step, plan.count) == (1, 1) and plan.sample_for(0) == 0


def test_plan_reads_max_thumbs_at_call_time(monkeypatch):
    monkeypatch.setattr(hover_strip, "MAX_THUMBS", 12)
    assert (hover_strip.plan_for(12, 320, 240).step, hover_strip.plan_for(12, 320, 240).count) == (1, 12)
    plan = hover_strip.plan_for(100, 320, 240)
    assert (plan.step, plan.count) == (9, 12)
    assert plan.sample_for(99) == 11  # 99 / 9 = 11 — 마지막 샘플 안


def test_plan_frame_bytes():
    assert hover_strip.plan_for(10, 3840, 2160).frame_bytes == 320 * 180 * 3


@pytest.mark.parametrize("size,expected", [((3840, 2160), (320, 180)), ((1920, 1080), (320, 180)), ((1002, 562), (320, 180)),
                                           ((320, 240), (320, 240)), ((1080, 1920), (180, 320)), ((4, 2), (320, 160)),
                                           ((1000, 1000), (320, 320)), ((2, 1000), (2, 320))])
def test_thumb_size_even_and_proportional(size, expected):
    assert hover_strip.thumb_size(*size) == expected


@pytest.mark.parametrize("args", [(0, 1920, 1080), (-3, 1920, 1080), (10, 0, 1080), (10, 1920, 0)])
def test_plan_rejects_bad_input(args):
    with pytest.raises(ValueError):
        hover_strip.plan_for(*args)


def test_plan_keeps_source_size():
    """계획은 원본 크기도 들고 있음 — 띠 ffmpeg의 스레드 규칙(thread_limits)이 원본 화소 수로 정함 (그림 크기와 별개)."""
    plan = hover_strip.plan_for(334, 3840, 2160)
    assert (plan.source_width, plan.source_height) == (3840, 2160) and (plan.width, plan.height) == (320, 180)
    portrait = hover_strip.plan_for(10, 1080, 1920)
    assert (portrait.source_width, portrait.source_height) == (1080, 1920) and (portrait.width, portrait.height) == (180, 320)


# ---------------------------------------------------------------- 띠 ffmpeg의 스레드 규칙


@pytest.mark.parametrize("size,expected", [
    ((1920, 1080), (None, None)),  # Full HD 그대로 — 묶지 않음 (ffmpeg 기본)
    ((1280, 720), (None, None)),
    ((1080, 1920), (None, None)),  # 세로 Full HD도 화소 수가 같음
    ((320, 180), (None, None)),
    ((1921, 1080), (1, 1)),  # Full HD보다 한 화소 줄이라도 크면 지금처럼 1코어
    ((1920, 1081), (1, 1)),
    ((3840, 2160), (1, 1)),
    ((2160, 3840), (1, 1)),
])
def test_thread_limits_by_source_pixels(size, expected):
    """원본 화소 수가 SINGLE_THREAD_ABOVE_PIXELS(1920×1080)보다 많으면 부른 쪽의 값(큰 파일의 디코더·필터 스레드), 그 이하면 (None, None) —
    옵션을 넣지 않음. 4K는 지금 명령 그대로라 측정된 설정이 바뀌지 않음."""
    assert hover_strip.SINGLE_THREAD_ABOVE_PIXELS == 1920 * 1080
    plan = hover_strip.plan_for(48, *size)
    assert hover_strip.thread_limits(plan, 1, 1) == expected


def test_thread_limits_passes_caller_values_and_reads_threshold_at_call_time(monkeypatch):
    """큰 파일의 값은 부른 쪽(hover_strip_builder의 두 상수)이 넘긴 그대로 (None이면 None). 문턱은 부를 때마다 모듈 값으로 읽음."""
    plan_4k = hover_strip.plan_for(48, 3840, 2160)
    assert hover_strip.thread_limits(plan_4k, 4, 3) == (4, 3)
    assert hover_strip.thread_limits(plan_4k, None, 2) == (None, 2)
    plan_hd = hover_strip.plan_for(48, 1920, 1080)
    assert hover_strip.thread_limits(plan_hd, 4, 3) == (None, None)
    monkeypatch.setattr(hover_strip, "SINGLE_THREAD_ABOVE_PIXELS", 1280 * 720)
    assert hover_strip.thread_limits(plan_hd, 4, 3) == (4, 3)
    assert hover_strip.thread_limits(hover_strip.plan_for(48, 1280, 720), 4, 3) == (None, None)


# ---------------------------------------------------------------- 띠 저장소


def test_strip_put_has_image_and_memory_bound():
    plan = hover_strip.plan_for(500, 3840, 2160)
    strip = hover_strip.HoverStrip(plan)
    assert strip.plan is plan
    assert strip.nbytes <= 500 * 320 * 180 * 3 and strip.filled_count == 0 and not strip.has(7)
    assert hover_strip.HoverStrip(hover_strip.plan_for(500, 1080, 1920)).nbytes <= 500 * 320 * 320 * 3  # 세로 영상도 320 상자 안
    with pytest.raises(LookupError):
        strip.image(7)
    strip.put(7, bytes([9]) * plan.frame_bytes)
    assert strip.has(7) and strip.filled_count == 1 and strip.image(7).shape == (180, 320, 3) and int(strip.image(7)[0, 0, 0]) == 9
    with pytest.raises(ValueError):
        strip.put(8, b"\x00" * (plan.frame_bytes - 1))
    assert not strip.has(8) and strip.filled_count == 1  # 길이가 틀린 put은 채움 표시를 남기지 않음


def test_strip_put_accepts_memoryview_and_copies():
    plan = hover_strip.plan_for(4, 320, 240)
    strip = hover_strip.HoverStrip(plan)
    buffer = bytearray([5]) * plan.frame_bytes
    strip.put(2, memoryview(buffer))
    buffer[0] = 77  # 넣은 뒤에 원본 버퍼를 고쳐도 띠의 그림은 그대로 (복사)
    assert int(strip.image(2)[0, 0, 0]) == 5 and strip.image(2).shape == (240, 320, 3)
    assert not strip.has(1) and not strip.has(3)


def test_strip_refill_same_row_keeps_count():
    plan = hover_strip.plan_for(3, 320, 240)
    strip = hover_strip.HoverStrip(plan)
    strip.put(1, bytes([1]) * plan.frame_bytes)
    strip.put(1, bytes([2]) * plan.frame_bytes)  # 같은 행을 다시 채워도 장수는 그대로
    assert strip.filled_count == 1 and int(strip.image(1)[239, 319, 2]) == 2


# ---------------------------------------------------------------- 파일 크기 상한


def test_skip_reason_by_file_size(tmp_path, monkeypatch):
    small = tmp_path / "a.mov"
    small.write_bytes(b"x" * 11)
    assert hover_strip.skip_reason(str(small)) is None
    monkeypatch.setattr(hover_strip, "MAX_FILE_BYTES", 10)
    assert hover_strip.skip_reason(str(small)) == "파일 0.0GB > 상한 0.0GB"
    with pytest.raises(OSError):
        hover_strip.skip_reason(str(tmp_path / "none.mov"))


def test_skip_reason_boundary_and_gb_text(tmp_path, monkeypatch):
    monkeypatch.setattr(hover_strip, "MAX_FILE_BYTES", 10)  # 작은 파일로 경계를 봄 (큰 파일·구멍 파일은 만들지 않음)
    path = tmp_path / "a.mov"
    path.write_bytes(b"x" * 10)
    assert hover_strip.skip_reason(str(path)) is None  # 상한과 같으면 만든다 (넘을 때만 건너뜀)
    path.write_bytes(b"x" * 11)
    assert hover_strip.skip_reason(str(path)) == f"파일 {gb(11)} > 상한 {gb(10)}"  # 1바이트 넘으면 글 (십진 GB — frame_cache_budget.gb)


# ---------------------------------------------------------------- 설정


def test_enabled_pref_roundtrip(tmp_path):
    path = str(tmp_path / "prefs.json")
    assert hover_strip.read_enabled(path) is True  # 파일 없음 → 기본 켬
    mac_prefs.update_pref("x", 1, path)
    assert hover_strip.read_enabled(path) is True  # 다른 키만 있음 → 기본 켬
    hover_strip.save_enabled(False, path)
    assert hover_strip.read_enabled(path) is False
    assert mac_prefs.read_prefs(path) == {"x": 1, hover_strip.PREF_KEY: False}  # 다른 키 보존
    hover_strip.save_enabled(True, path)
    assert hover_strip.read_enabled(path) is True


@pytest.mark.parametrize("text", ['{"slider_thumbnails": "yes"}', '{"slider_thumbnails": 1}', '{"slider_thumbnails": null}'])
def test_enabled_pref_rejects_non_bool(tmp_path, text):
    path = tmp_path / "prefs.json"
    path.write_text(text)
    with pytest.raises(ValueError):
        hover_strip.read_enabled(str(path))
    assert path.read_text() == text  # 읽기만 하고 파일은 그대로


@pytest.mark.parametrize("bad", ["yes", 1, None])
def test_save_enabled_rejects_non_bool(tmp_path, bad):
    path = tmp_path / "prefs.json"
    with pytest.raises(TypeError):
        hover_strip.save_enabled(bad, str(path))
    assert not os.path.exists(path)  # 잘못된 값은 파일을 만들지 않음


def test_enabled_pref_broken_file_raises_user_file_error(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text("{not json")
    with pytest.raises(UserFileError):
        hover_strip.read_enabled(str(path))
    with pytest.raises(UserFileError):
        hover_strip.save_enabled(False, str(path))
    assert path.read_text() == "{not json"  # 깨진 파일은 덮지 않음


def test_enabled_pref_default_path(tmp_path, monkeypatch):
    path = str(tmp_path / "prefs.json")
    monkeypatch.setattr(hover_strip, "prefs_path", lambda: path)
    assert hover_strip.read_enabled() is True
    hover_strip.save_enabled(False)
    assert mac_prefs.read_prefs(path) == {hover_strip.PREF_KEY: False} and hover_strip.read_enabled() is False


def test_prefs_path_by_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")
    assert hover_strip.prefs_path() == windows_display.prefs_path()
    assert hover_strip.prefs_path().startswith(str(tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    assert hover_strip.prefs_path() == mac_prefs.prefs_path()


def test_enabled_cache():
    assert hover_strip.enabled() is True  # 기본 켬 (끝나면 autouse fixture가 되돌림)
    hover_strip.set_enabled(False)
    assert hover_strip.enabled() is False
    for bad in ("no", 0, None):
        with pytest.raises(TypeError):
            hover_strip.set_enabled(bad)
    assert hover_strip.enabled() is False  # 틀린 값은 캐시를 바꾸지 않음
    hover_strip.set_enabled(True)
    assert hover_strip.enabled() is True


def test_constants():
    assert (hover_strip.THUMB_WIDTH, hover_strip.MAX_THUMBS, hover_strip.MAX_FILE_BYTES) == (320, 500, 4_000_000_000)
    assert hover_strip.PREF_KEY == "slider_thumbnails" and hover_strip.MENU_TEXT == "슬라이더 썸네일"
    assert hover_strip.LOG_PREFIX == "[슬라이더 썸네일]"
