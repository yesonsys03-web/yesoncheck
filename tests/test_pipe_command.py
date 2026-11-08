"""ffmpeg 파이프 명령의 디코더 스레드 방식 — 조각(slice) 스레드 (2026-11-09).

왜: Windows 선택 재생의 '[측정] 열기'에서 '첫 프레임'(ffmpeg가 첫 4K 프레임을 넘겨주기까지)이 평균 0.74초로 전환 시간의 약 70%였음. 기본
(프레임 스레드)은 여러 프레임을 동시에 디코드하느라 첫 장이 늦음 — 이 Mac(Intel 16 논리 코어)에서 4K ProRes 4444 첫 프레임 기본 0.56초 대
`-thread_type slice` 0.17초, 334장 연속은 기본 48~49fps 대 조각 52fps(OS 캐시에 올린 파일, 디코드 + bgr24). 재시작(뒤로 탐색·슬라이더)도
같은 첫 프레임을 기다리므로 함께 빨라짐. 픽셀은 스레드 방식과 무관 — cv2와의 바이트 대조 시험(test_pipe_spike·test_movie_pipe_capture)이 지킴.
"""

from yesoncheck.movie_pipe_source import _pipe_command


def _decoder_options(command):
    """-i 앞(입력·디코더 옵션)만."""
    return command[:command.index("-i")]


def test_decoder_uses_slice_threads():
    options = _decoder_options(_pipe_command("/clips/a.mov", "pipe:1"))
    assert options[options.index("-thread_type") + 1] == "slice"


def test_restart_command_uses_slice_threads_too():
    options = _decoder_options(_pipe_command("/clips/a.mov", "pipe:1", seek_seconds=4.5))
    assert options[options.index("-thread_type") + 1] == "slice"
    assert options[options.index("-ss") + 1] == "4.500000"
