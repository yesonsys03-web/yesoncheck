"""네이티브 프레임 손잡이 — IOSurface를 쥔 NativeHandle과 그 메모리 위의 numpy 배열 (Qt·PyObjC 없음, 어느 플랫폼에서도 import).

플레이어는 프레임을 numpy 배열(frame_a)로 들고 다니는데, 네이티브 재생 경로의 프레임은 IOSurface가 받쳐 주는 CVPixelBuffer 안에 있다.
그래서 프레임은 NativeFrameArray(ndarray 서브클래스)이고 .native가 NativeHandle이다 — 배열을 그대로 쓰는 기존 코드는 손잡이를 몰라도 되고,
GPU 쪽은 native_surface_of(frame)로 표면을 꺼내 복사 없이 질감으로 쓴다.

내용 약속:
- 픽셀은 (높이, 너비, 4) uint8 BGRX 뷰다 — 읽기 잠금이 걸린 버퍼의 바탕 주소 위에 복사 없이 씌운다. 행 간격(bytesPerRow)이 너비×4보다 크면
  strided 뷰이고 패딩 바이트는 보이지 않는다. 마지막 채널 X는 쓰지 않는 값이다(알파로 읽지 말 것).
- 픽셀을 읽는 것은 잠금을 쥔 쪽(디코더가 만든 wrap_native 호출자)이 넘긴 배열뿐이다. 잠금·해제는 keepalive(버퍼 소유자)의 몫이고 이 모듈은
  모른다 — 손잡이가 살아 있는 동안 keepalive가 산다는 것만 보장한다. 쓰기 가능 여부는 넘겨받은 버퍼 그대로라(wrap_native는 플래그를 안 건드린다)
  읽기 잠금 버퍼는 읽기 전용 memoryview로 넘겨야 실수로 쓰는 일이 막힌다.
- 수명: 배열이 손잡이를, 손잡이가 keepalive를 쥔다(배열 → 손잡이 → keepalive, 한 방향). 손잡이는 배열을 쥐지 않으므로 순환이 없어 마지막
  뷰가 사라지는 즉시(참조 계수만으로, gc 없이) 풀린다.
- 전파: 슬라이스·reshape·transpose 같이 같은 메모리를 가리키는 뷰는 손잡이를 물려받는다. copy()·astype·fancy 인덱싱·산술(ufunc) 결과는 새
  메모리라 손잡이가 없고, copy()와 ufunc 결과는 아예 일반 np.ndarray다. 손잡이가 붙은 조각 뷰도 손잡이를 돌려주므로, 표면을 통째로 쓰려는
  쪽은 frame.shape == (handle.height, handle.width, 4)인지 스스로 확인해야 한다.

전파 판정은 np.may_share_memory(바운드 비교, O(1))다. 새로 할당된 배열은 살아 있는 다른 버퍼의 바운드와 겹칠 수 없으므로 '겹치면 뷰, 아니면 새
메모리'가 이 용도에선 정확하고, 정확한 np.shares_memory는 비연속 배열에서 비싸질 수 있어 쓰지 않는다. 크기 0 조각은 겹침이 없다고 나와 손잡이를 잃는다
(읽을 픽셀이 없으니 무해).
"""

from dataclasses import dataclass

import numpy as np

BYTES_PER_PIXEL = 4  # BGRX


@dataclass(eq=False)
class NativeHandle:
    """한 프레임의 IOSurface 손잡이. iosurface: IOSurfaceRef C 포인터(int), index: 프레임 번호,
    keepalive: 버퍼 소유자 — 이 손잡이가 살아 있는 동안 버퍼가 산다. 같음은 동일성(is)이다."""
    iosurface: int
    width: int
    height: int
    index: int
    keepalive: object


class NativeFrameArray(np.ndarray):
    """(높이, 너비, 4) uint8 BGRX 프레임 + .native(NativeHandle). 같은 메모리를 가리키는 뷰는 손잡이를 물려받는다."""

    native = None  # 손잡이 없는 NativeFrameArray(astype·fancy 인덱싱 결과, 일반 배열을 직접 view한 것)의 값

    def __array_finalize__(self, obj):
        if isinstance(obj, NativeFrameArray) and obj.native is not None and np.may_share_memory(self, obj):
            self.native = obj.native

    def __array_wrap__(self, array, context=None, return_scalar=False):
        """ufunc 결과는 새 메모리라 손잡이 없는 일반 ndarray로 돌려준다(numpy 1.x 기본 구현은 NativeFrameArray로 감싼다). 0차원 결과(a.sum() 등)는
        일반 배열처럼 스칼라로(numpy 2가 넘기는 return_scalar는 이 규칙으로 충분해 쓰지 않는다). 손잡이 단 배열이 out=으로 들어온 경우(a += 1)만 그 객체 그대로 — 제자리 연산이 같은 객체·손잡이를 지킨다."""
        if array.ndim == 0:
            return array[()]
        return array if getattr(array, "native", None) is not None else np.asarray(array)

    def copy(self, order="C"):
        """복사본은 손잡이 없는 일반 ndarray."""
        return self.view(np.ndarray).copy(order)


def wrap_native(buffer_view, handle):
    """(높이, bytesPerRow) uint8 버퍼(memoryview 또는 ndarray)를 (높이, 너비, 4) 뷰로 씌워 손잡이를 단다 — 복사 없음.
    uint8이 아니거나 2차원이 아니거나 행 수가 손잡이 높이와 다르거나 bytesPerRow < 너비×4면 ValueError (조용히 reshape하지 않는다)."""
    raw = np.asarray(buffer_view)
    row_bytes = handle.width * BYTES_PER_PIXEL
    if raw.dtype != np.uint8 or raw.ndim != 2:
        raise ValueError(f"버퍼는 (높이, bytesPerRow) uint8여야 함: dtype={raw.dtype}, shape={raw.shape}")
    if raw.shape[0] != handle.height or raw.shape[1] < row_bytes:
        raise ValueError(f"버퍼 모양 {raw.shape}이 손잡이 {handle.width}x{handle.height}(행 {row_bytes}바이트 이상)와 맞지 않음")
    frame = raw[:, :row_bytes].reshape(handle.height, handle.width, BYTES_PER_PIXEL).view(NativeFrameArray)
    frame.native = handle
    return frame


def native_surface_of(frame):
    """frame이 NativeFrameArray이고 손잡이가 있으면 그 NativeHandle, 아니면 None (None·일반 배열·복사본·새 메모리 결과)."""
    if not isinstance(frame, NativeFrameArray):
        return None
    return frame.native
