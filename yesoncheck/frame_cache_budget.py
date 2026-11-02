"""프레임 캐시 예산 — 파일 하나의 모든 프레임을 RAM에 둬도 되는지 가르는 순수 판단 (Qt·캡처 상태 없음).

캡처가 열릴 때 부른 쪽이 프레임 한 장 크기·장수·물리 RAM·사용 가능 메모리·이미 다른 캡처가 잡은 바이트를 넘기면,
전체 보관(full) 또는 링(최근 몇 장만)을 돌려준다. 근거 글(reason)은 기록에 그대로 남기려는 것이라 링일 때도 "링 — "으로만
시작하고 링 장수는 부른 쪽(캡처)이 붙인다. 메모리를 읽는 psutil의 예외는 삼키지 않는다.
"""

from dataclasses import dataclass

import psutil

FULL_CACHE_RAM_FRACTION = 0.20  # 모든 캡처의 전체 보관을 합쳐 물리 RAM의 이만큼까지만
FULL_CACHE_HEADROOM_BYTES = 2 * 1024**3  # 전체 보관 뒤에도 사용 가능 메모리에 이만큼은 남아야 함


@dataclass(frozen=True)
class CacheDecision:
    """full: 전체 보관 여부, reason: 기록에 남길 근거 글, total_bytes: 파일 전체 프레임의 바이트 (frame_bytes * count)."""
    full: bool
    reason: str
    total_bytes: int


def gb(n):
    """바이트를 십진 GB 소수 한 자리 글로 (8_311_000_000 → "8.3GB")."""
    return f"{n / 1e9:.1f}GB"


def memory_snapshot():
    """(물리 RAM 전체, 사용 가능) 바이트 — psutil.virtual_memory()를 그대로 읽는다 (실패하면 예외 그대로)."""
    memory = psutil.virtual_memory()
    return memory.total, memory.available


def full_cache_decision(frame_bytes, count, ram_total, ram_available, committed):
    """파일 전체(count장)를 RAM에 둘지 정한다. 예산 검사가 사용 가능 메모리 검사보다 먼저다.

    committed: 이미 다른 캡처가 전체 보관으로 잡은 바이트. 예산 = 물리 RAM의 FULL_CACHE_RAM_FRACTION에서 committed를 뺀 것."""
    total = frame_bytes * count
    budget = int(ram_total * FULL_CACHE_RAM_FRACTION)
    remaining = budget - committed
    if total > remaining:
        return CacheDecision(False, (
            f"링 — 파일 {gb(total)} > 남은 예산 {gb(remaining)} "
            f"(물리 RAM {gb(ram_total)}의 {FULL_CACHE_RAM_FRACTION:.0%} = {gb(budget)}, 다른 캡처 {gb(committed)})"), total)
    if ram_available < total + FULL_CACHE_HEADROOM_BYTES:
        return CacheDecision(False, (
            f"링 — 사용 가능 메모리 {gb(ram_available)} < {gb(total)} + {gb(FULL_CACHE_HEADROOM_BYTES)}"), total)
    return CacheDecision(True, f"전체 {count}장 {gb(total)} (예산 {gb(budget)}, 사용 중 {gb(committed + total)})", total)
