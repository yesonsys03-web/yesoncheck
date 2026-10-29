"""ProRes 파이프 게이트 (yesoncheck/movie_pipe_source.py 1부): 실제 ffprobe로 클립 공장 클립을 읽어 판정한다 (mock 없음).

게이트 ①~⑥은 스펙 §5.2. 실제 클립은 여러 조건이 한꺼번에 걸리기도 해서(held는 avg≠r이기도 함) 사유는 probe 필드로 확인하고,
조건 하나씩의 경계는 좋은 probe의 필드 하나만 바꾼 사본(dataclasses.replace)으로 본다.
"""

import dataclasses
import math
import re
from fractions import Fraction

import pytest

from tests.prores_clips import (
    make_audio_first, make_held, make_neg, make_numbered_clip, make_rot, make_vfr_h264, make_voff, run_ffmpeg,
)
from yesoncheck.movie_pipe_source import movie_source_mode, pipe_eligible, probe_movie

COUNT = 120


# ---------------------------------------------------------------- 클립 (session: 인코딩 반복 방지)

@pytest.fixture(scope="session")
def prores_clip(tmp_path_factory):
    """4444 120장 24fps."""
    path = str(tmp_path_factory.mktemp("gate_4444") / "numbered_4444.mov")
    make_numbered_clip(path, count=COUNT, fps="24", profile="4", pix_fmt="yuv444p10le")
    return path


@pytest.fixture(scope="session")
def prores_422_clip(tmp_path_factory):
    """422 HQ 120장 23.976fps(24000/1001)."""
    path = str(tmp_path_factory.mktemp("gate_422") / "numbered_422.mov")
    make_numbered_clip(path, count=COUNT, fps="24000/1001", profile="3", pix_fmt="yuv422p10le")
    return path


@pytest.fixture(scope="session")
def two_frame_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("gate_two_frame") / "two_frame.mov")
    make_numbered_clip(path, count=2, fps="24")
    return path


@pytest.fixture(scope="session")
def voff_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("gate_voff") / "voff.mov")
    make_voff(path)
    return path


@pytest.fixture(scope="session")
def held_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("gate_held") / "held.mov")
    make_held(path)
    return path


@pytest.fixture(scope="session")
def neg_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("gate_neg") / "neg.mov")
    make_neg(path)
    return path


@pytest.fixture(scope="session")
def rot_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("gate_rot") / "rot.mov")
    make_rot(path)
    return path


@pytest.fixture(scope="session")
def audio_first_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("gate_audio_first") / "audio_first.mov")
    make_audio_first(path)
    return path


@pytest.fixture(scope="session")
def vfr_h264_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("gate_vfr_h264") / "vfr.mp4")
    make_vfr_h264(path)
    return path


@pytest.fixture(scope="session")
def audio_only_file(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("gate_audio_only") / "tone.wav")
    run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=1", path], "소리만 있는 파일 생성")
    return path


def media_duration(probe):
    """게이트 ④ 오른쪽 변 (초, Fraction): duration_ts x time_base."""
    return probe.duration_ts * probe.time_base


# ---------------------------------------------------------------- 게이트 (스펙 §5.2)

def test_gate_positive_clean_prores(prores_clip, prores_422_clip):
    """4444 24fps·422 23.976fps(24000/1001): 게이트 통과. 프레임 수·속도·크기가 probe에 그대로 담김."""
    for path, rate in ((prores_clip, Fraction(24)), (prores_422_clip, Fraction(24000, 1001))):
        probe = probe_movie(path)
        assert (probe.codec, probe.width, probe.height) == ("prores", 320, 180)
        assert (probe.r, probe.avg, probe.nb_frames) == (rate, rate, COUNT)
        assert Fraction(COUNT) / probe.r == media_duration(probe)
        assert (probe.rotation, probe.sar_ok) == (0, True)
        assert pipe_eligible(probe), probe


def test_gate_negative_edge_clips(held_clip, neg_clip, rot_clip, vfr_h264_clip):
    """실제로 겪은 문제 파일: held·neg는 프레임 수·길이·속도 삼자 일치(④)가 깨지고, rot는 회전(⑤), h264는 코덱(①)."""
    for name, path in (("held", held_clip), ("neg", neg_clip)):
        probe = probe_movie(path)
        assert probe.codec == "prores" and probe.rotation == 0, name
        assert Fraction(probe.nb_frames) / probe.r != media_duration(probe), name
        assert not pipe_eligible(probe), name

    probe = probe_movie(rot_clip)
    assert (probe.width, probe.height) == (320, 180)  # 회전은 크기에 반영하지 않음 (cv2는 돌려서 180x320)
    assert abs(probe.rotation) == 90
    assert not pipe_eligible(probe)

    probe = probe_movie(vfr_h264_clip)
    assert probe.codec == "h264"
    assert not pipe_eligible(probe)


def test_gate_voff_eligible(voff_clip):
    """영상 트랙 start 0.5초 오프셋이 있어도 ④는 통과 — 오프셋은 탐색이 보정한다 (⑥)."""
    probe = probe_movie(voff_clip)
    assert probe.video_start == pytest.approx(0.5)
    assert probe.format_start == 0.0
    assert Fraction(probe.nb_frames) / probe.r == media_duration(probe)
    assert pipe_eligible(probe), probe


def test_gate_two_frame_clip(two_frame_clip):
    probe = probe_movie(two_frame_clip)
    assert probe.nb_frames == 2
    assert pipe_eligible(probe), probe


@pytest.fixture
def good_probe(prores_clip):
    return probe_movie(prores_clip)


@pytest.mark.parametrize("change", [
    pytest.param(dict(codec="h264"), id="1_codec"),
    pytest.param(dict(codec=""), id="1_codec_empty"),
    pytest.param(dict(r=None), id="2_r_missing"),
    pytest.param(dict(r=Fraction(241), avg=Fraction(241)), id="2_r_over_240"),
    pytest.param(dict(r=Fraction(0), avg=Fraction(0)), id="2_r_zero"),
    pytest.param(dict(avg=None), id="2_avg_missing"),
    pytest.param(dict(avg=Fraction(25)), id="2_avg_differs"),
    pytest.param(dict(nb_frames=0), id="3_no_frames"),
    pytest.param(dict(nb_frames=None), id="3_frames_missing"),
    pytest.param(dict(width=0), id="3_width_zero"),
    pytest.param(dict(height=0), id="3_height_zero"),
    pytest.param(dict(duration_ts=None), id="4_duration_missing"),
    pytest.param(dict(time_base=None), id="4_time_base_missing"),
    pytest.param(dict(nb_frames=COUNT + 1), id="4_one_frame_extra"),
    pytest.param(dict(rotation=90), id="5_rotation"),
    pytest.param(dict(rotation=-90), id="5_rotation_negative"),
    pytest.param(dict(rotation=360), id="5_rotation_full_turn"),
    pytest.param(dict(sar_ok=False), id="5_sar"),
    pytest.param(dict(video_start=math.nan), id="6_video_start_nan"),
    pytest.param(dict(format_start=math.inf), id="6_format_start_inf"),
])
def test_gate_rejects_each_condition(good_probe, change):
    """좋은 probe에서 조건 하나만 틀리게 하면 거짓 — 게이트가 한 조건도 빠뜨리지 않았는지."""
    assert pipe_eligible(good_probe)
    assert not pipe_eligible(dataclasses.replace(good_probe, **change))


def test_gate_accepts_nonzero_starts(good_probe):
    """⑥: 시작 시각은 유한하기만 하면 통과 (음수도)."""
    assert pipe_eligible(dataclasses.replace(good_probe, video_start=-0.25, format_start=3600.0))


def test_gate_duration_equation_is_exact(good_probe):
    """④는 Fraction 정확 등식 — float이면 1e-17 어긋남이 사라져 통과해 버림."""
    exact = dataclasses.replace(good_probe, nb_frames=1, r=Fraction(1), avg=Fraction(1), duration_ts=10 ** 17,
                                time_base=Fraction(1, 10 ** 17))
    off_by_tick = dataclasses.replace(exact, duration_ts=10 ** 17 + 1)
    assert float(media_duration(off_by_tick)) == float(media_duration(exact))
    assert pipe_eligible(exact)
    assert not pipe_eligible(off_by_tick)


# ---------------------------------------------------------------- probe

def test_probe_audio_first_picks_video(audio_first_clip):
    """소리 트랙이 index 0이어도 영상 트랙의 값을 담는다."""
    probe = probe_movie(audio_first_clip)
    assert (probe.codec, probe.width, probe.height) == ("prores", 320, 180)
    assert pipe_eligible(probe), probe


def test_probe_audio_only_file_is_ineligible_not_an_error(audio_only_file):
    """영상 트랙이 없는 파일: 없는 값은 None/0으로 담고 게이트가 거짓 (열기 실패 판단은 호출한 쪽 몫)."""
    probe = probe_movie(audio_only_file)
    assert (probe.codec, probe.width, probe.height) == ("", 0, 0)
    assert (probe.r, probe.avg, probe.nb_frames, probe.duration_ts, probe.time_base) == (None,) * 5
    assert not pipe_eligible(probe)


def test_probe_runtime_error_propagates(tmp_path):
    """ffprobe가 못 읽는 파일(깨진 파일·없는 파일)은 RuntimeError가 그대로 나온다 — 여기서 삼키지 않음."""
    broken = tmp_path / "broken.mov"
    broken.write_bytes(b"this is not a movie" * 100)
    with pytest.raises(RuntimeError, match="ffprobe로 읽지 못했습니다"):
        probe_movie(str(broken))
    with pytest.raises(RuntimeError, match="ffprobe로 읽지 못했습니다"):
        probe_movie(str(tmp_path / "missing.mov"))


# ---------------------------------------------------------------- 환경 변수

def test_movie_source_mode(monkeypatch):
    monkeypatch.delenv("YESONCHECK_MOVIE_SOURCE", raising=False)
    assert movie_source_mode() == "auto"
    for given, expected in (("", "auto"), ("auto", "auto"), ("AUTO", "auto"), ("pipe", "pipe"), ("cv2", "cv2"),
                            ("PIPE", "pipe"), ("Cv2", "cv2")):
        monkeypatch.setenv("YESONCHECK_MOVIE_SOURCE", given)
        assert movie_source_mode() == expected, given
    for bad in ("x", "pipe cv2", " pipe"):
        monkeypatch.setenv("YESONCHECK_MOVIE_SOURCE", bad)
        with pytest.raises(ValueError, match=re.escape(repr(bad))):
            movie_source_mode()
