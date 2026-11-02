"""파이프 캡처의 프레임 보관본 _FrameStore (yesoncheck/movie_pipe_source.py — 스펙 §5.4·§6): 번호별 보관·FIFO 내보내기·같은 번호 교체,
호출자에게는 늘 새 복사본, 링 모드(keep_across_restart 거짓)는 재시작에서 비우고 전체 모드는 남김. ffmpeg 없이 작은 배열로만 본다.
"""

import numpy as np
from yesoncheck.movie_pipe_source import _FrameStore

def arr(v):
    return np.full((2, 3, 3), v, np.uint8)

def test_ring_mode_keeps_last_n_in_fifo_order():
    s = _FrameStore(3, keep_across_restart=False)
    for i in range(5):
        s.keep(i, arr(i))
    assert s.indices() == [2, 3, 4] and not s.has(1) and s.has(4) and len(s) == 3

def test_copy_of_is_independent_of_kept_array():
    s = _FrameStore(3, keep_across_restart=False)
    kept = arr(1)
    s.keep(0, kept)
    out = s.copy_of(0)
    out[:] = 9
    assert kept[0, 0, 0] == 1 and s.copy_of(0)[0, 0, 0] == 1

def test_ring_mode_clears_on_restart_and_full_mode_keeps():
    ring = _FrameStore(3, keep_across_restart=False)
    full = _FrameStore(10, keep_across_restart=True)
    for s in (ring, full):
        s.keep(0, arr(0)); s.keep(1, arr(1))
        s.on_restart()
    assert len(ring) == 0 and full.indices() == [0, 1]

def test_full_mode_never_evicts_within_capacity():
    s = _FrameStore(4, keep_across_restart=True)
    for i in (5, 6, 0, 1):
        s.keep(i, arr(i))
    assert s.indices() == [5, 6, 0, 1] and s.bytes == 4 * arr(0).nbytes

def test_rekeeping_an_index_replaces_and_refreshes_order():
    s = _FrameStore(2, keep_across_restart=False)
    s.keep(0, arr(0)); s.keep(1, arr(1)); s.keep(0, arr(7))
    assert s.indices() == [1, 0] and s.copy_of(0)[0, 0, 0] == 7

def test_clear_empties():
    s = _FrameStore(2, keep_across_restart=True)
    s.keep(0, arr(0)); s.clear()
    assert len(s) == 0 and s.bytes == 0 and not s.has(0)
