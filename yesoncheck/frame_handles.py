"""네이티브 프레임 손잡이 — IOSurface를 쥔 NativeHandle과 그 메모리 위의 numpy 배열 (Qt·PyObjC 없음, 어느 플랫폼에서도 import).

플레이어는 프레임을 numpy 배열(frame_a)로 들고 다니는데, 네이티브 재생 경로의 프레임은 IOSurface가 받쳐 주는 CVPixelBuffer 안에 있다.
그래서 프레임은 NativeFrameArray(ndarray 서브클래스)이고 .native가 NativeHandle이다 — 배열을 그대로 쓰는 기존 코드는 손잡이를 몰라도 되고,
GPU 쪽은 whole_surface_handle(frame)으로 표면 전체인지 확인하며 꺼내 복사 없이 질감으로 쓴다.

내용 약속:
- 픽셀은 (높이, 너비, 4) uint8 BGRX 뷰다 — 읽기 잠금이 걸린 버퍼의 바탕 주소 위에 복사 없이 씌운다. 행 간격(bytesPerRow)이 너비×4보다 크면
  strided 뷰이고 패딩 바이트는 보이지 않는다. 마지막 채널 X는 쓰지 않는 값이다(알파로 읽지 말 것).
- 픽셀을 읽는 것은 잠금을 쥔 쪽(디코더가 만든 wrap_native 호출자)이 넘긴 배열뿐이다. 잠금·해제는 keepalive(버퍼 소유자)의 몫이고 이 모듈은
  모른다 — 손잡이가 살아 있는 동안 keepalive가 산다는 것만 보장한다. 쓰기 가능 여부는 넘겨받은 버퍼 그대로라(wrap_native는 플래그를 안 건드린다)
  읽기 잠금 버퍼는 읽기 전용 memoryview로 넘겨야 실수로 쓰는 일이 막힌다.
- 수명: 모든 뷰의 .base 사슬은 손잡이를 쥔 작은 객체(_SurfaceBuffer) 하나에서 끝난다 — wrap_native가 바탕 배열을 그 객체의 __array_interface__로 만들기
  때문이다. np.asarray(frame)·frame.view(np.ndarray)·np.ascontiguousarray(frame) 같은 일반 ndarray 뷰도 사슬이 같은 곳에서 끝나므로(numpy는
  같은 타입의 base만 따라 접어 NativeFrameArray를 건너뛰지만 끝은 그 객체다) 뷰가 하나라도 살아 있으면 손잡이와 keepalive가 산다. 이 객체는 손잡이·
  원본 버퍼만 쥐고 배열은 쥐지 않으므로(배열 → _SurfaceBuffer → 손잡이 → keepalive, 한 방향) 순환이 없어 마지막 뷰가 사라지는 즉시(참조 계수만으로,
  gc 없이) 풀린다.
- 전파: 슬라이스·reshape·transpose 같이 같은 메모리를 가리키는 뷰는 .native를 물려받는다. copy()·astype·fancy 인덱싱·산술(ufunc) 결과는 새
  메모리라 손잡이가 없고, copy()와 ufunc 결과는 아예 일반 np.ndarray다. 일반 ndarray로 바꾼 뷰는 .native가 없어 native_surface_of가 None이다.
- 표면 전체 판별: native_surface_of는 조각·상하 반전(a[::-1])·채널 역순(a[..., ::-1]) 뷰에도 손잡이를 돌려준다(shape이 같아도 배치가 다르다). GPU 질감처럼
  표면을 그대로 쓰는 쪽은 whole_surface_handle(frame)을 쓴다 — shape (높이, 너비, 4)·strides (bytesPerRow, 4, 1)·시작 주소·uint8이 표면과 정확히 같을
  때만 손잡이를 주고(표면 전체를 가리키는 일반 ndarray 뷰도 포함 — 위 사슬이 수명을 지킨다) 아니면 None이다.

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


class _SurfaceBuffer:
    """한 프레임 바탕 메모리((높이, bytesPerRow) uint8 전체)의 주인 — 모든 뷰의 .base 사슬 끝. 손잡이와 원본 버퍼를 쥐고, __array_interface__로
    바탕 주소·모양·strides·읽기 전용 여부를 그대로 내보낸다. 배열은 쥐지 않는다(순환 방지). address·frame_strides는 whole_surface_handle의 기준."""

    def __init__(self, raw, handle):
        self.source = raw  # 바탕 메모리를 살려 둔다(memoryview의 주인까지 사슬로 이어짐)
        self.handle = handle
        self.__array_interface__ = dict(raw.__array_interface__)
        self.address = raw.ctypes.data
        self.frame_strides = (raw.strides[0], BYTES_PER_PIXEL, 1)


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
    바탕 배열은 _SurfaceBuffer에서 만들어 모든 뷰의 .base 사슬이 손잡이를 쥔 그 객체에서 끝난다.
    uint8이 아니거나 2차원이 아니거나 열 간격이 1이 아니거나 행 수가 손잡이 높이와 다르거나 bytesPerRow < 너비×4면 ValueError (조용히 reshape하지 않는다)."""
    raw = np.asarray(buffer_view)
    row_bytes = handle.width * BYTES_PER_PIXEL
    if raw.dtype != np.uint8 or raw.ndim != 2 or raw.strides[1] != 1:
        raise ValueError(f"버퍼는 (높이, bytesPerRow) uint8, 열 간격 1이어야 함: dtype={raw.dtype}, shape={raw.shape}, strides={raw.strides}")
    if raw.shape[0] != handle.height or raw.shape[1] < row_bytes:
        raise ValueError(f"버퍼 모양 {raw.shape}이 손잡이 {handle.width}x{handle.height}(행 {row_bytes}바이트 이상)와 맞지 않음")
    base = np.asarray(_SurfaceBuffer(raw, handle))  # base.base가 _SurfaceBuffer — 이 배열에서 갈라진 모든 뷰가 손잡이를 붙든다
    frame = base[:, :row_bytes].reshape(handle.height, handle.width, BYTES_PER_PIXEL).view(NativeFrameArray)
    frame.native = handle
    return frame


def native_surface_of(frame):
    """frame이 NativeFrameArray이고 손잡이가 있으면 그 NativeHandle, 아니면 None (None·일반 배열·복사본·새 메모리 결과).
    조각·뒤집힌 뷰도 손잡이를 돌려준다 — 표면을 그대로 쓰려면 whole_surface_handle."""
    if not isinstance(frame, NativeFrameArray):
        return None
    return frame.native


def whole_surface_handle(frame):
    """frame이 표면 전체와 정확히 같은 배치((높이, 너비, 4) uint8, strides (bytesPerRow, 4, 1), 같은 시작 주소)면 그 NativeHandle, 아니면 None.
    조각·상하 반전·채널 역순·복사본·재해석뿐 아니라 NativeFrameArray가 아닌 표면 전체 뷰(np.asarray(frame) 등)도 바탕 사슬로 찾아 판정한다."""
    owner = frame
    while isinstance(owner, np.ndarray):  # .base 사슬을 따라 손잡이를 쥔 객체까지
        owner = owner.base
    if not isinstance(owner, _SurfaceBuffer):
        return None
    handle = owner.handle
    if (
        frame.dtype == np.uint8
        and frame.shape == (handle.height, handle.width, BYTES_PER_PIXEL)
        and frame.strides == owner.frame_strides
        and frame.ctypes.data == owner.address
    ):
        return handle
    return None
