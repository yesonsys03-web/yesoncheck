"""실행 시험(yesoncheck/smoke_test.py)의 'ProRes 파이프 열기' 단계 단위 시험 — 소스 실행에서 단계 함수를 직접 부름.

빌드된 앱 안에서만 보이는 것(번들 ffmpeg·Windows CREATE_NO_WINDOW)은 CI의 빌드 앱 smoke가 본다. 여기서는 단계 자체의 판정:
성공 경로, 게이트가 cv2를 주면 실패, 환경 변수 모드가 auto가 아니면 실패.
"""

import cv2
import pytest

from yesoncheck import movie_pipe_source, sequence_source
from yesoncheck.smoke_test import PIPE_CLIP_FRAMES, prores_pipe_open


@pytest.fixture(autouse=True)
def auto_mode(monkeypatch):
    monkeypatch.delenv(movie_pipe_source.SOURCE_MODE_ENV, raising=False)


def test_prores_pipe_open_passes_on_pipe_capture(tmp_path):
    detail = prores_pipe_open(str(tmp_path))
    assert detail["capture"] == "FFmpegPipeCapture"
    assert len(detail["levels"]) == 3 and detail["level_after_set_1"] == pytest.approx(detail["levels"][1], abs=1)
    # 시험 영상은 smoke 폴더에 남음 (진단용) — 파이프가 아니라 cv2로도 읽히는 평범한 ProRes mov
    cap = cv2.VideoCapture(str(tmp_path / "pipe_prores.mov"))
    try:
        assert cap.get(cv2.CAP_PROP_FRAME_COUNT) == PIPE_CLIP_FRAMES
    finally:
        cap.release()


def test_prores_pipe_open_fails_when_gate_gives_cv2(tmp_path, monkeypatch):
    """게이트가 음성(None)이라 open_any_capture가 cv2.VideoCapture를 주면 조용히 통과하지 않고 실패."""
    monkeypatch.setattr(sequence_source, "maybe_pipe_capture", lambda path: None)
    with pytest.raises(AssertionError, match=r"VideoCapture.*FFmpegPipeCapture 기대"):
        prores_pipe_open(str(tmp_path))


@pytest.mark.parametrize("mode", ["cv2", "pipe"])
def test_prores_pipe_open_requires_auto_mode(tmp_path, monkeypatch, mode):
    """YESONCHECK_MOVIE_SOURCE가 auto가 아니면 단계 의미가 깨짐(cv2면 파이프를 안 보고, pipe면 게이트를 안 봄) → 실패."""
    monkeypatch.setenv(movie_pipe_source.SOURCE_MODE_ENV, mode)
    with pytest.raises(AssertionError, match="auto여야"):
        prores_pipe_open(str(tmp_path))
    assert not (tmp_path / "pipe_prores.mov").exists()  # 영상도 만들기 전에 멈춤
