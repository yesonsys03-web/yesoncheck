"""ffmpeg 파이프 명령의 디코더 스레드 방식 — Windows만 조각(slice) 스레드 (2026-11-09).

왜: Windows 선택 재생의 '[측정] 열기'에서 '첫 프레임'(ffmpeg가 첫 4K 프레임을 넘겨주기까지)이 평균 0.74초로 전환 시간의 약 70%였음. 기본
(프레임 스레드)은 여러 프레임을 동시에 디코드하느라 첫 장이 늦음 — 이 Mac(Intel 16 논리 코어)에서 4K ProRes 4444 첫 프레임 기본 0.56초 대
`-thread_type slice` 0.17초, 334장 연속은 기본 48~49fps 대 조각 52fps(OS 캐시에 올린 파일, 디코드 + bgr24). 재시작(뒤로 탐색·슬라이더)도
같은 첫 프레임을 기다리므로 함께 빨라짐. Windows 실측(사용자 PC, 4K 10개): 전환 1.10 → 0.61초, 파일마다 가장 긴 간격 75~98ms — 사용자 판정 '안정적'.
픽셀은 스레드 방식과 무관 — cv2와의 바이트 대조 시험(test_pipe_spike·test_movie_pipe_capture)이 지킴.
Mac은 그대로(사용자 요청 '맥 버전은 그대로 유지' — Mac 재생은 대부분 VideoToolbox이고, ffmpeg를 고른 창·HDR·주석 내보내기의 파이프는 예전 명령).
"""

import sys

import pytest

from yesoncheck import movie_pipe_source
from yesoncheck.movie_pipe_source import _pipe_command

OLD_COMMAND_TAIL = ["-i", "/clips/a.mov", "-map", "0:V:0", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]


@pytest.fixture(autouse=True)
def _ffmpeg_name(monkeypatch):
    """플랫폼을 바꿔치기하면 ffmpeg 찾기도 그 플랫폼을 봄 — 명령의 모양만 보므로 이름으로 고정."""
    monkeypatch.setattr(movie_pipe_source, "ffmpeg_path", lambda: "ffmpeg")


def _decoder_options(command):
    """-i 앞(입력·디코더 옵션)만."""
    return command[:command.index("-i")]


def test_windows_decoder_uses_slice_threads(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    options = _decoder_options(_pipe_command("/clips/a.mov", "pipe:1"))
    assert options[options.index("-thread_type") + 1] == "slice"


def test_windows_restart_command_uses_slice_threads_too(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    options = _decoder_options(_pipe_command("/clips/a.mov", "pipe:1", seek_seconds=4.5))
    assert options[options.index("-thread_type") + 1] == "slice"
    assert options[options.index("-ss") + 1] == "4.500000"


def test_mac_command_is_unchanged(monkeypatch):
    """Mac(그 밖의 OS도)은 예전 명령 글자 그대로 — 디코더 스레드 옵션 없음."""
    monkeypatch.setattr(sys, "platform", "darwin")
    command = _pipe_command("/clips/a.mov", "pipe:1")
    assert command[1:] == ["-nostdin", "-v", "error", *OLD_COMMAND_TAIL]
    restart = _pipe_command("/clips/a.mov", "pipe:1", seek_seconds=4.5)
    assert restart[1:] == ["-nostdin", "-v", "error", "-ss", "4.500000", *OLD_COMMAND_TAIL]
