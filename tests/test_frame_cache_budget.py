import pytest
from yesoncheck import frame_cache_budget as b
from yesoncheck import movie_pipe_source

GB = 1024**3
FRAME_4K = 3840 * 2160 * 3  # 24,883,200

def test_full_when_inside_budget_and_available():
    d = b.full_cache_decision(FRAME_4K, 334, ram_total=128 * GB, ram_available=100 * GB, committed=0)
    assert d.full is True and d.total_bytes == FRAME_4K * 334
    assert d.reason == "전체 334장 8.3GB (예산 27.5GB, 사용 중 8.3GB)"

def test_ring_when_budget_remaining_is_too_small():
    d = b.full_cache_decision(FRAME_4K, 334, ram_total=32 * GB, ram_available=30 * GB, committed=0)
    assert d.full is False
    assert d.reason == "링 — 파일 8.3GB > 남은 예산 6.9GB (물리 RAM 34.4GB의 20% = 6.9GB, 다른 캡처 0.0GB)"

def test_committed_bytes_shrink_the_budget():
    d = b.full_cache_decision(FRAME_4K, 334, ram_total=64 * GB, ram_available=60 * GB, committed=FRAME_4K * 334)
    assert d.full is False and d.reason.startswith("링 — 파일 8.3GB > 남은 예산 5.4GB")

def test_ring_when_available_memory_is_short():
    d = b.full_cache_decision(FRAME_4K, 334, ram_total=128 * GB, ram_available=9 * GB, committed=0)
    assert d.full is False and d.reason == "링 — 사용 가능 메모리 9.7GB − 다른 캡처 0.0GB < 8.3GB + 2.1GB"

def test_available_check_subtracts_other_captures_reservation():
    """A/B 둘 다 자기 첫 프레임에서 판정하고 그때는 앞 캡처의 보관이 아직 차지 않아 사용 가능 메모리에 안 잡힌다 — 그래서 ②도
    다른 캡처가 잡은 바이트를 뺀다 (최종 검토의 사례: 128GiB·사용 가능 15GiB·앞 캡처 4K 하나 → 둘째 파일은 링, 앞 캡처가 없으면 전체)."""
    one_4k = FRAME_4K * 334
    assert one_4k == 8_310_988_800
    second = b.full_cache_decision(FRAME_4K, 334, ram_total=128 * GB, ram_available=15 * GB, committed=one_4k)
    assert second.full is False  # ① 예산은 남음(27.5GB − 8.3GB) — ②가 가름
    assert second.reason == "링 — 사용 가능 메모리 16.1GB − 다른 캡처 8.3GB < 8.3GB + 2.1GB"
    alone = b.full_cache_decision(FRAME_4K, 334, ram_total=128 * GB, ram_available=15 * GB, committed=0)
    assert alone.full is True

def test_budget_check_comes_before_available_check():
    d = b.full_cache_decision(FRAME_4K, 334, ram_total=32 * GB, ram_available=1 * GB, committed=0)
    assert d.reason.startswith("링 — 파일")

def test_gb_is_decimal_one_digit():
    assert b.gb(8_311_000_000) == "8.3GB" and b.gb(0) == "0.0GB"

def test_memory_snapshot_uses_psutil():
    total, available = b.memory_snapshot()
    assert total > available > 0

@pytest.mark.parametrize("value, expected", [(None, "auto"), ("", "auto"), ("RING", "ring"), ("auto", "auto")])
def test_frame_cache_mode(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv(movie_pipe_source.FRAME_CACHE_ENV, raising=False)
    else:
        monkeypatch.setenv(movie_pipe_source.FRAME_CACHE_ENV, value)
    assert movie_pipe_source.frame_cache_mode() == expected

def test_frame_cache_mode_rejects_unknown(monkeypatch):
    monkeypatch.setenv(movie_pipe_source.FRAME_CACHE_ENV, "full")
    with pytest.raises(ValueError, match=movie_pipe_source.FRAME_CACHE_ENV):
        movie_pipe_source.frame_cache_mode()

def test_launch_rejects_bad_frame_cache_mode(qapp, monkeypatch):
    """test_movie_pipe_integration::test_launch_rejects_a_bad_mode_before_the_window과 같은 모양."""
    import re
    from yesoncheck import app as app_module

    def no_window(**kwargs):
        raise AssertionError("나쁜 모드인데 창을 만들었습니다")

    monkeypatch.setattr(app_module, "VideoPlayer", no_window)
    monkeypatch.setenv(movie_pipe_source.FRAME_CACHE_ENV, "full")
    with pytest.raises(ValueError, match=re.escape(repr("full"))):
        app_module.launch(["yesoncheck"])

def test_conftest_pins_ring_for_existing_seek_tests():
    import os
    assert os.environ.get(movie_pipe_source.FRAME_CACHE_ENV) == "ring"
