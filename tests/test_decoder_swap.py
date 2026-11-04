"""재생 디코더를 바꿀 때의 캡처 바꿔 끼움 — VideoPlayer.swap_movie_captures_for_decoder (스펙 2026-11-04 §5.4 ③·§7-4·§8).

Setting 메뉴(Task 4)와 네이티브 그리기 실패 폴백(Task 5)이 디코더 캐시를 바꾼 뒤 부른다. open_file을 거치지 않으므로 OCR 상태(돌아가는 분석·
저장 안 된 결과·검토 창)·주석·소리(setMedia)·줌(initial_fit)·와이프·재생목록 상태는 그대로이고, 열린 A(와 B) 중 **ProRes 영상 파일**만
지금 유효한 디코더로 다시 연 캡처로 바꿔 끼워 같은 프레임에 놓는다(재생 중이었으면 이어서 재생). h264·시퀀스(.seq)·빈 쪽은 건드리지 않는다.
새 캡처를 열지 못하면(_open_movie_capture가 창으로 알림) 그 쪽은 옛 캡처 그대로 두고 False.

가짜 네이티브 리그(tests/native_fakes — _open_movie_capture를 부를 때마다 새 FakeNativeCapture)로 바꿔 끼움을 객체 동일성으로 보고, ProRes 판정의
ffprobe(player_playback.probe_movie)는 바꿔치기해 경로를 기록한다(리그의 시험 영상은 mp4v라 진짜 ffprobe는 prores라고 하지 않음). h264·시퀀스는
진짜 캡처와 진짜 ffprobe로 본다. 창은 conftest의 dialogs가 가로챈다.
"""

import os
import re
from fractions import Fraction
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from tests.native_fakes import (  # noqa: F401 (픽스처 — new_player는 native_fakes의 픽스처가 요청함)
    FAKE_FRAME_COUNT,
    FAKE_HEIGHT,
    FAKE_WIDTH,
    FakeNativeCapture,
    fake_native_player,
    new_player,
    player_with_fake_native,
    player_with_fake_native_ab,
)
from tests.test_sequence_capture import make_seq
from tests.test_work_paths_ui import make_config
from yesoncheck import player_playback
from yesoncheck.movie_pipe_source import MovieProbe, PipeCaptureError
from yesoncheck.movie_pipe_source import probe_movie as real_probe_movie
from yesoncheck.sequence_source import ImageSequenceCapture

MEASURE_PREFIX = "[측정]"


def fake_probe(codec):
    """swap이 읽는 값은 codec뿐 — 나머지는 가짜 리그의 영상에 맞춘 그럴듯한 값."""
    return MovieProbe(codec=codec, width=FAKE_WIDTH, height=FAKE_HEIGHT, r=Fraction(24), avg=Fraction(24),
                      nb_frames=FAKE_FRAME_COUNT, duration_ts=FAKE_FRAME_COUNT * 512, time_base=Fraction(1, 12288),
                      video_start=0.0, format_start=0.0, rotation=0, sar_ok=True, pix_fmt="yuv422p10le", codec_tag="apcn")


@pytest.fixture
def probes(monkeypatch):
    """player_playback.probe_movie(바꿔 끼움이 ProRes를 가르는 ffprobe)를 바꿔치기 → 기록 SimpleNamespace:
    calls(받은 경로 차례), codecs(파일 이름 → 돌려줄 codec, 없으면 "prores"), fail(파일 이름 — RuntimeError: ffprobe가 못 읽음),
    real(True면 진짜 ffprobe를 부르고 기록만)."""
    rec = SimpleNamespace(calls=[], codecs={}, fail=set(), real=False)

    def spy(path):
        rec.calls.append(path)
        name = os.path.basename(path)
        if name in rec.fail:
            raise RuntimeError(f"ffprobe가 파일을 읽지 못함 (종료 코드 1): {path}")
        if rec.real:
            return real_probe_movie(path)
        return fake_probe(rec.codecs.get(name, "prores"))

    monkeypatch.setattr(player_playback, "probe_movie", spy)
    return rec


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811 (new_player: 픽스처)
    return new_player(make_config(str(tmp_path), {}))


def forbid(monkeypatch, owner, name):
    """불리면 시험이 실패하는 함수로 바꿈."""
    def forbidden(*args, **kwargs):
        raise AssertionError(f"{name}이(가) 불리면 안 됩니다")

    monkeypatch.setattr(owner, name, forbidden)


def measure_lines(text):
    return [line for line in text.splitlines() if line.startswith(MEASURE_PREFIX)]


def test_swap_replaces_prores_capture_at_same_frame(player_with_fake_native, probes):
    """멈춘 채 60번을 보던 ProRes A: 새 캡처로 바꿔 끼우고(옛 캡처는 release) 같은 60번 프레임을 새 캡처에서 읽어 보임 — 재생은 켜지 않음,
    파일 이름은 그대로, ffprobe는 A에 한 번.

    깨지는 변경: 옛 캡처를 놓지 않으면 old.isOpened(); 끝에 seek_to_frame(get_current_frame_index())로 놓으면(1부터 세는 번호에 0부터 세는 번호를
    넘김) 59번; 탐색을 빼면 frame_a가 None이고 새 캡처는 0번; 멈춰 있었는데 play_video를 부르면 timer 단언."""
    rig = player_with_fake_native
    player = rig.player
    player.timer.stop()
    player.seek_to_frame(61)  # 1부터 세는 탐색 → 60번 프레임이 보임
    assert player.get_current_frame_index() == 60
    old, name = player.cap_a, player.filename_a

    assert player.swap_movie_captures_for_decoder() is True

    assert isinstance(player.cap_a, FakeNativeCapture) and player.cap_a is not old
    assert not old.isOpened()
    assert player.get_current_frame_index() == 60
    assert player.frame_a is player.cap_a.frames[60]
    assert not player.timer.isActive()
    assert player.filename_a == name
    assert probes.calls == [name]


def test_swap_keeps_playing_if_it_was_playing(player_with_fake_native, probes, capsys):
    """재생 중(Play 뒤 3틱 — 13번)에 바꿔 끼움: 재생이 이어지고(타이머 켜짐·버튼 Pause) 다음 틱은 새 캡처의 14번. [측정]은 옛 디코더의 Play를
    줄 없이 닫고(멈춘 Play처럼 — 줄은 끝까지 간 Play에만) 새 디코더로 새로 셈(새 기록, 0장) — 한 줄이 두 디코더에 걸치지 않음.

    깨지는 변경: 타이머를 멈추지 않고 play_video를 부르면(play_video는 재생 중이면 아무것도 안 함) 옛 기록이 남아 _measure_run 단언;
    끝에 play_video를 빼면 timer 단언; 바꿀 때 _print_measurement로 줄을 찍으면 measure_lines 단언."""
    rig = player_with_fake_native
    player = rig.player
    player.timer.stop()
    player.seek_to_frame(11)  # 10번
    player.play_video()
    for _ in range(3):
        player.next_frame_playback()
    assert player.get_current_frame_index() == 13
    run_before = player._measure_run
    assert run_before is not None and run_before.frames == 3
    capsys.readouterr()

    assert player.swap_movie_captures_for_decoder() is True

    assert player.timer.isActive()
    assert player.playPauseButton.text() == "Pause"
    assert player.get_current_frame_index() == 13
    assert player.frame_a is player.cap_a.frames[13]
    assert player._measure_run is not None and player._measure_run is not run_before and player._measure_run.frames == 0
    assert measure_lines(capsys.readouterr().out) == []
    player.next_frame_playback()
    assert player.frame_a is player.cap_a.frames[14]
    assert player._measure_run.frames == 1


def test_swap_preserves_ocr_annotation_audio_and_zoom_state(player_with_fake_native, probes, monkeypatch):
    """open_file의 부수 효과가 없음: OCR 결과·저장 안 됨 표시·ROI, 주석 저장소(같은 객체), 소리 재생기의 미디어(setMedia 0회), 줌(initial_fit
    False·뷰 변환), 이름 줄·스크롤 범위, 재생목록 재생(is_playlist_playing — 선택 재생 중 전환은 목록을 이어 감) 그대로. reset_ocr_state·주석 다시
    읽기·reset_view 0회.

    깨지는 변경: 바꿔 끼움 대신 open_file('A', 같은 경로)를 부르면 reset_ocr_state·setMedia·주석 다시 읽기가 불리고 initial_fit이 True;
    display_first_frame을 부르면 reset_view; stop_video를 부르면 is_playlist_playing이 False."""
    rig = player_with_fake_native
    player, widget = rig.player, rig.player.videoWidget
    segments = [{"text": "SC_001", "start_frame": 0, "end_frame": 12}]
    player.last_ocr_segments = segments
    player._ocr_results_unsaved = True
    player.ocr_roi = (0.1, 0.1, 0.5, 0.5)
    player.is_playlist_playing = True
    store = player.annotation_store
    media_url = player.mediaPlayer.media().canonicalUrl()
    widget.initial_fit = False
    widget.scale(2.0, 2.0)  # 사용자가 확대해 둔 상태
    transform = widget.transform()
    label, scroll_max = player.filenameLabel.text(), player.positionScroll.maximum()
    calls = []
    monkeypatch.setattr(player, "reset_ocr_state", lambda *a, **k: calls.append("reset_ocr_state"))
    monkeypatch.setattr(player, "on_video_annotations_reset", lambda *a, **k: calls.append("on_video_annotations_reset"))
    monkeypatch.setattr(widget, "reset_view", lambda *a, **k: calls.append("reset_view"))
    real_set_media = player.mediaPlayer.setMedia
    monkeypatch.setattr(player.mediaPlayer, "setMedia", lambda *a: (calls.append("setMedia"), real_set_media(*a)))
    old = player.cap_a

    assert player.swap_movie_captures_for_decoder() is True

    assert player.cap_a is not old
    assert calls == []
    assert player.last_ocr_segments is segments and player._ocr_results_unsaved is True
    assert player.ocr_roi == (0.1, 0.1, 0.5, 0.5)
    assert player.annotation_store is store
    assert player.mediaPlayer.media().canonicalUrl() == media_url
    assert widget.initial_fit is False and widget.transform() == transform
    assert (player.filenameLabel.text(), player.positionScroll.maximum()) == (label, scroll_max)
    assert player.is_playlist_playing is True and player.timer.isActive()


def test_swap_clears_frame_cache_of_old_decoder(player_with_fake_native, probes):
    """바꿔 끼우면 드래그 미리보기의 프레임 캐시(frame_cache — 옛 캡처가 준 RGB 사본)를 비움: 디코더마다 픽셀이 조금 다르므로(4:2:2 색차 보간·
    태그 없는 파일의 행렬 — 스펙 §3c·§3d) 옛 디코더의 색이 새 디코더 화면에 섞이지 않게. 바꿀 것이 없으면 캐시도 그대로(아래 h264 시험).

    깨지는 변경: clear_cache를 빼면 캐시가 남음."""
    player = player_with_fake_native.player
    player.frame_cache[5] = np.zeros((FAKE_HEIGHT, FAKE_WIDTH, 3), np.uint8)

    assert player.swap_movie_captures_for_decoder() is True

    assert player.frame_cache == {}


def test_swap_skips_h264_and_sequences(player, new_player, probes, make_video, tmp_path, monkeypatch):  # noqa: F811
    """h264 영상(진짜 cv2 캡처)과 시퀀스(.seq — ImageSequenceCapture)는 디코더 설정과 무관 — 캡처·프레임·캐시 그대로, 열기·탐색 0회, True.
    h264는 ffprobe로 걸러지고(1회 — 진짜 ffprobe가 "h264"), 시퀀스는 캡처 종류로 걸러져 ffprobe도 0회. 아무것도 안 열린 플레이어도 True.

    깨지는 변경: 코덱을 보지 않고 모든 영상을 다시 열면 _open_movie_capture 금지에 걸림; 시퀀스를 거르지 않으면 가상 경로로 ffprobe가 불려
    calls가 늘어남; 바꿀 것이 없는데 seek_to_frame·clear_cache를 부르면 금지·캐시 단언."""
    assert player.swap_movie_captures_for_decoder() is True  # 아무것도 안 열림
    assert probes.calls == []

    probes.real = True
    video = make_video(str(tmp_path / "movs" / "h264.mp4"))
    assert player.open_file("A", video)
    assert real_probe_movie(player.filename_a).codec == "h264"
    old, frame = player.cap_a, player.frame_a
    player.frame_cache[3] = np.zeros((4, 4, 3), np.uint8)
    forbid(monkeypatch, player, "_open_movie_capture")
    forbid(monkeypatch, player, "seek_to_frame")

    assert player.swap_movie_captures_for_decoder() is True

    assert player.cap_a is old and player.frame_a is frame and old.isOpened()
    assert probes.calls == [player.filename_a]
    assert list(player.frame_cache) == [3]

    seq_player = new_player(make_config(str(tmp_path / "seq_cfg"), {}))
    assert seq_player.open_file("A", make_seq(str(tmp_path / "shots"), "EX01_tk1", range(1, 7)))
    assert isinstance(seq_player.cap_a, ImageSequenceCapture)
    seq_cap, seq_frame = seq_player.cap_a, seq_player.frame_a
    probes.calls.clear()
    forbid(monkeypatch, seq_player, "_open_movie_capture")
    forbid(monkeypatch, seq_player, "seek_to_frame")

    assert seq_player.swap_movie_captures_for_decoder() is True

    assert seq_player.cap_a is seq_cap and seq_player.frame_a is seq_frame
    assert probes.calls == []


def test_swap_failure_keeps_old_capture_and_returns_false(player_with_fake_native, probes, dialogs, monkeypatch):
    """새 캡처를 열지 못함(진짜 _open_movie_capture — ffmpeg 파이프를 열지 못해 PipeCaptureError): 창은 열기 길이 한 번 띄우고, A는 옛 캡처
    그대로(놓지 않음)·보던 프레임 그대로, 재생은 이어 감, False.

    깨지는 변경: 열기 전에 옛 캡처를 놓으면 isOpened; 실패해도 cap_a에 None을 넣으면 cap_a 단언; 실패를 삼켜 True를 돌려주면 반환 단언;
    실패 뒤 재생을 이어 가지 않으면 timer 단언."""
    rig = player_with_fake_native
    player = rig.player
    player.seek_to_frame(21)
    old, frame = player.cap_a, player.frame_a
    monkeypatch.setattr(player, "_open_movie_capture", type(player)._open_movie_capture.__get__(player))

    def pipe_fails(path):
        raise PipeCaptureError(f"ffmpeg가 첫 프레임 전에 끝남: {path}", ["ffmpeg"], "stderr 전문")

    monkeypatch.setattr(player, "_native_or_pipe_capture", pipe_fails)
    dialogs.criticals.clear()

    assert player.swap_movie_captures_for_decoder() is False

    assert len(dialogs.criticals) == 1 and "ffmpeg 파이프로 열지 못했습니다" in dialogs.criticals[0]
    assert player.cap_a is old and old.isOpened()
    assert player.frame_a is frame and player.get_current_frame_index() == 20
    assert player.timer.isActive()


def test_swap_probe_failure_shows_window_and_keeps_capture(player_with_fake_native, probes, dialogs, monkeypatch):
    """ProRes인지 확인하는 ffprobe가 파일을 못 읽음(RuntimeError — NAS 끊김·깨진 파일): 열기 실패와 같게 — 기록(스택 트레이스)과 창 한 번
    (경로·이유·트레이스), 옛 캡처 그대로, 다시 열지 않음, False. 조용히 넘기지 않음(메뉴는 반환값을 따로 알리지 않음).

    깨지는 변경: RuntimeError를 잡지 않으면 예외가 메뉴 슬롯까지 올라감; 잡고 창 없이 넘기면 criticals 단언; 실패한 쪽을 그래도 다시 열면
    _open_movie_capture 금지."""
    rig = player_with_fake_native
    player = rig.player
    old, frame = player.cap_a, player.frame_a
    probes.fail.add(os.path.basename(player.filename_a))
    forbid(monkeypatch, player, "_open_movie_capture")
    dialogs.criticals.clear()

    assert player.swap_movie_captures_for_decoder() is False

    assert len(dialogs.criticals) == 1
    text = dialogs.criticals[0]
    assert player.filename_a in text and "RuntimeError" in text and "Traceback" in text
    assert player.cap_a is old and old.isOpened() and player.frame_a is frame


def test_swap_handles_b_side_with_wipe(player_with_fake_native_ab, probes):
    """와이프(A·B ProRes, X축 0.3)로 20번을 보던 중: A·B 모두 새 캡처로 바꾸고(옛 둘 release) 둘 다 20번 — 화면에는 새 A·새 B의 20번이 X축
    0.3으로(set_sides). 와이프 체크·축·위치, 재생 그대로. ffprobe는 A·B 한 번씩, 지금 번호는 A의 것을 한 번만 기억(B는 탐색이 A를 따라 맞춤).

    깨지는 변경: B를 건너뛰면 cap_b 단언; A를 바꾼 뒤 번호를 다시 읽으면(새 A는 0번) B가 0번; 와이프를 끄고 켜면 wipeXButton 단언."""
    rig = player_with_fake_native_ab
    player, widget = rig.player, rig.player.videoWidget
    player.wipeXButton.setChecked(True)
    widget.wipe_position_x = 0.3
    player.seek_to_frame(21)
    old_a, old_b = player.cap_a, player.cap_b
    rig.sides.clear()

    assert player.swap_movie_captures_for_decoder() is True

    new_a, new_b = player.cap_a, player.cap_b
    assert isinstance(new_a, FakeNativeCapture) and isinstance(new_b, FakeNativeCapture)
    assert new_a is not old_a and new_b is not old_b
    assert not old_a.isOpened() and not old_b.isOpened()
    assert player.get_current_frame_index() == 20
    assert player.frame_a is new_a.frames[20] and player.frame_b is new_b.frames[20]
    assert player.wipeCheckBox.isChecked() and player.wipeXButton.isChecked() and widget.wipe_position_x == 0.3
    assert player.timer.isActive()
    assert probes.calls == [player.filename_a, player.filename_b]
    last = rig.sides[-1]
    assert last.a is new_a.frames[20] and last.b is new_b.frames[20] and (last.axis, last.ratio) == ("x", 0.3)


def test_swap_keeps_b_position_when_wipe_is_off(player_with_fake_native_ab, probes):
    """와이프를 끈 동안 B는 탐색을 따라가지 않음(seek_to_frame은 와이프일 때만 B를 맞춤) — 바꿔 끼운 새 B는 옛 B가 있던 자리(10번을 읽은 뒤 11)에
    놓이고(새 캡처는 0번에서 시작하므로 옮겨 둠) 프레임은 비움, A는 30번. 와이프를 다시 켜면 예전처럼 그 자리에서 이어짐.

    깨지는 변경: B의 자리를 옮겨 두지 않으면 새 B는 0번."""
    rig = player_with_fake_native_ab
    player = rig.player
    player.seek_to_frame(11)  # 와이프 켬 — B도 10번을 읽어 다음 자리 11
    player.wipeCheckBox.setChecked(False)
    player.seek_to_frame(31)  # 와이프 끔 — A만 30번
    assert int(player.cap_b.get(cv2.CAP_PROP_POS_FRAMES)) == 11

    assert player.swap_movie_captures_for_decoder() is True

    assert int(player.cap_b.get(cv2.CAP_PROP_POS_FRAMES)) == 11
    assert player.frame_b is None
    assert player.get_current_frame_index() == 30
    assert not player.wipeCheckBox.isChecked()


def test_swap_only_touches_the_prores_side(fake_native_player, probes):
    """A는 ProRes가 아닌 영상(진짜 cv2 캡처 — h264 흉내), B는 ProRes(가짜 네이티브): B만 바꿔 끼우고 A는 같은 캡처 객체 — 탐색 한 번이 A를
    다시 읽고 와이프라 새 B도 같은 번호로 맞춤.

    깨지는 변경: 한 쪽이라도 ProRes가 아니면 전체를 건너뛰면 cap_b 단언; 코덱과 무관하게 A도 다시 열면 cap_a 단언."""
    rig = fake_native_player(ab=True, native="B")
    player = rig.player
    probes.codecs[os.path.basename(player.filename_a)] = "mpeg4"
    player.seek_to_frame(6)
    old_a, old_b = player.cap_a, player.cap_b

    assert player.swap_movie_captures_for_decoder() is True

    assert player.cap_a is old_a and old_a.isOpened()
    assert player.cap_b is not old_b and not old_b.isOpened()
    assert player.get_current_frame_index() == 5
    assert player.frame_b is player.cap_b.frames[5]
    assert probes.calls == [player.filename_a, player.filename_b]


def test_swap_logs_each_replaced_side(player_with_fake_native_ab, probes, capsys):
    """기록: 바꿔 끼운 쪽마다 한 줄 `[재생] 디코더 전환: <쪽> 캡처 바꿔 끼움 — <이름> (<번호>번)` — 사용자 기록에서 전환을 따라가게."""
    rig = player_with_fake_native_ab
    player = rig.player
    player.seek_to_frame(8)
    capsys.readouterr()

    assert player.swap_movie_captures_for_decoder() is True

    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("[재생] 디코더 전환")]
    assert lines == ["[재생] 디코더 전환: A 캡처 바꿔 끼움 — clip_a.mov (7번)",
                     "[재생] 디코더 전환: B 캡처 바꿔 끼움 — clip_b.mov (7번)"]
    assert all(re.search(r"\(\d+번\)$", line) for line in lines)
