"""(스파이크 — spike/mac-native) 네이티브 프레임 손잡이: CVPixelBuffer(IOSurface)를 쥔 NativeHandle과 그 메모리 위의 numpy 배열.

frame_a 자리에 들어가는 것은 NativeFrameArray — (높이, 너비, 4) uint8 BGRA, CVPixelBuffer의 바탕 주소(읽기 잠금) 위의 뷰라 복사 0.
.native가 NativeHandle(IOSurface 포인터·크기·프레임 번호, 버퍼를 붙잡음)이고, 손잡이가 GC되면 잠금을 풀고 버퍼를 놓는다.
슬라이스 같은 뷰는 손잡이를 물려받고 copy()·ufunc 결과는 새 메모리라 native_surface_of가 None을 준다(바탕 주소·모양으로 확인).
"""

import weakref

import numpy as np


class NativeHandle:
    """한 프레임의 CVPixelBuffer 손잡이. surface: IOSurfaceRef C 포인터(int), address: 잠근 바탕 주소(int).
    unlock: GC 때 한 번 부를 함수(인자 없음 — 버퍼를 닫아 쥔 클로저) — weakref.finalize로 걸어 둔다."""

    __slots__ = ("buffer", "surface", "width", "height", "bytes_per_row", "address", "index", "__weakref__")

    def __init__(self, buffer, surface, width, height, bytes_per_row, address, index, unlock):
        self.buffer = buffer
        self.surface = surface
        self.width = width
        self.height = height
        self.bytes_per_row = bytes_per_row
        self.address = address
        self.index = index
        weakref.finalize(self, unlock)

    def __repr__(self):
        return f"NativeHandle(index={self.index}, {self.width}x{self.height}, surface=0x{self.surface:x})"


class NativeFrameArray(np.ndarray):
    """BGRA 프레임 배열 + .native(NativeHandle). 뷰는 손잡이를 물려받음 — 손잡이가 살아 있는 동안 메모리가 유효."""

    def __array_finalize__(self, obj):
        if obj is None:
            return
        self.native = getattr(obj, "native", None)


def wrap_native(view, handle):
    """(h, w, 4) uint8 뷰 → 손잡이를 단 NativeFrameArray (복사 없음)."""
    frame = view.view(NativeFrameArray)
    frame.native = handle
    return frame


def native_surface_of(frame):
    """frame이 손잡이의 프레임 전체 뷰(같은 바탕 주소·(h, w, 4))면 그 NativeHandle, 아니면 None (복사본·RGB 배열·None)."""
    if not isinstance(frame, NativeFrameArray):
        return None
    handle = frame.native
    if handle is None:
        return None
    if frame.shape != (handle.height, handle.width, 4) or frame.ctypes.data != handle.address:
        return None
    return handle
