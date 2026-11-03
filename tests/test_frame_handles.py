import gc

import numpy as np
import pytest
from yesoncheck.frame_handles import NativeFrameArray, NativeHandle, native_surface_of, wrap_native


def _frame(width=4, height=2, bytes_per_row=16, keepalive=None):
    """(height, bytes_per_row) uint8 바탕 위에 손잡이를 단 프레임과 그 손잡이."""
    handle = NativeHandle(iosurface=1234, width=width, height=height, index=7, keepalive=keepalive or object())
    return wrap_native(np.zeros((height, bytes_per_row), np.uint8), handle), handle


def test_slice_keeps_handle_and_copy_drops_it():
    """깨지는 변경: __array_finalize__가 .native를 뷰로 전파하지 않음(슬라이스가 None) / copy()를 덮어쓰지 않아 복사본이 NativeFrameArray(또는 손잡이)를 유지."""
    h = NativeHandle(iosurface=1234, width=4, height=2, index=7, keepalive=object())
    a = wrap_native(np.zeros((2, 16), np.uint8), h)
    assert native_surface_of(a) is h and native_surface_of(a[:, :8]) is h and native_surface_of(a[..., :3]) is h
    assert native_surface_of(a.copy()) is None and type(a.copy()) is np.ndarray


def test_plain_arrays_have_no_handle():
    """깨지는 변경: native_surface_of가 isinstance 검사 없이 .native를 읽음(AttributeError) / 클래스 기본값 native=None을 지움."""
    assert native_surface_of(np.zeros((2, 2, 3), np.uint8)) is None and native_surface_of(None) is None


def test_handles_compare_by_identity():
    """깨지는 변경: NativeHandle을 값 비교 dataclass로 둠(@dataclass 기본 eq=True) — 필드가 같은 서로 다른 프레임 손잡이가 같다고 나오고 해시도 불가."""
    keepalive = object()
    first = NativeHandle(1, 4, 2, 0, keepalive=keepalive)
    second = NativeHandle(1, 4, 2, 0, keepalive=keepalive)
    assert first == first and first != second and len({first, second}) == 2


def test_keepalive_lives_while_any_view_lives():
    """깨지는 변경: 배열이 손잡이를 약한 참조로만 쥠 / 손잡이가 keepalive를 놓침 / 뷰가 사라져도 되살아나는 순환 참조(손잡이가 배열을 쥠)."""
    import weakref

    class Owner:
        pass

    o = Owner()
    ref = weakref.ref(o)
    a = wrap_native(np.zeros((2, 16), np.uint8), NativeHandle(1, 4, 2, 0, keepalive=o))
    del o
    v = a[:, :4]
    del a
    gc.collect()
    assert ref() is not None
    del v
    gc.collect()
    assert ref() is None


def test_keepalive_is_released_by_refcount_alone_so_there_is_no_cycle():
    """깨지는 변경: 손잡이↔배열 순환(예: 손잡이에 배열을 저장하거나 finalize 콜백이 배열을 닫아 쥠) — gc를 끈 채로는 keepalive가 풀리지 않음."""
    import weakref

    class Owner:
        pass

    o = Owner()
    ref = weakref.ref(o)
    gc.collect()
    gc.disable()
    try:
        a = wrap_native(np.zeros((2, 16), np.uint8), NativeHandle(1, 4, 2, 0, keepalive=o))
        v = a[:, :4]
        del o, a, v
        assert ref() is None
    finally:
        gc.enable()


def test_ufunc_result_has_no_handle():
    """깨지는 변경: __array_wrap__/__array_finalize__가 ufunc 결과(새 메모리)에도 .native를 붙임 — (a + 1)이 손잡이를 주장."""
    a, _ = _frame()
    for result in (a + 1, a * 2, np.add(a, 1), a.sum(axis=0), a > 0):
        assert type(result) is np.ndarray
        assert native_surface_of(result) is None


def test_full_reductions_stay_scalars_like_plain_arrays():
    """깨지는 변경: __array_wrap__가 0차원 결과를 스칼라로 바꾸지 않음 — a.sum()/a.max()가 0차원 배열로 나와 기존 코드(item·비교·포맷)가 달라짐."""
    a, _ = _frame()
    plain = np.zeros((2, 4, 4), np.uint8)
    for reduce in (lambda x: x.sum(), lambda x: x.max(), lambda x: x.mean(), lambda x: (x == 0).all(), lambda x: x.argmax()):
        assert type(reduce(a)) is type(reduce(plain)) and type(reduce(a)) is not np.ndarray


def test_inplace_op_keeps_the_same_object_and_handle():
    """깨지는 변경: __array_wrap__가 out=으로 들어온 손잡이 단 배열도 일반 뷰로 바꿈 — `a += 1`이 새 객체를 돌려줘 a가 손잡이를 잃음."""
    a, h = _frame()
    view = a[:, :8]
    same = view
    view += 1
    assert view is same and native_surface_of(view) is h and a[0, 0, 0] == 1  # 바탕 메모리에 실제로 반영
    assert np.add(a, 1, out=a) is a and native_surface_of(a) is h


def test_new_memory_results_other_than_ufuncs_have_no_handle():
    """깨지는 변경: __array_finalize__가 메모리 공유 확인 없이 .native를 물려줌 — astype·fancy 인덱싱·flatten은 새 메모리인데 손잡이를 주장."""
    a, _ = _frame()
    assert native_surface_of(a.astype(np.float32)) is None
    assert native_surface_of(a[[0, 1]]) is None
    assert native_surface_of(a.flatten()) is None
    assert native_surface_of(a[:, :2].reshape(-1)) is None  # 비연속 조각의 reshape는 복사 — 손잡이 없음


def test_reshape_view_that_aliases_the_same_memory_keeps_handle():
    """깨지는 변경: 공유 확인을 모양·바탕 주소 일치로 좁힘 — 같은 메모리를 가리키는 뷰(transpose·reshape)가 손잡이를 잃음."""
    a, h = _frame(bytes_per_row=16)
    assert native_surface_of(a.reshape(2, 16)) is h
    assert native_surface_of(a.transpose(1, 0, 2)) is h


def test_wrap_native_is_a_zero_copy_strided_view():
    """깨지는 변경: wrap_native가 np.array/ascontiguousarray로 복사하거나 bytesPerRow 패딩을 잘라 내지 않고 reshape(복사) — 메모리 공유·shape가 깨짐."""
    padded = np.arange(2 * 24, dtype=np.uint8).reshape(2, 24)  # 너비 4 → 16바이트만 쓰고 8바이트는 행 패딩
    handle = NativeHandle(1234, 4, 2, 7, keepalive=object())
    from_array = wrap_native(padded, handle)
    from_memoryview = wrap_native(memoryview(padded), handle)
    for frame in (from_array, from_memoryview):
        assert isinstance(frame, NativeFrameArray) and frame.shape == (2, 4, 4) and frame.dtype == np.uint8
        assert np.shares_memory(frame, padded)
        assert frame.strides == (24, 4, 1)  # 행 간격은 bytesPerRow 그대로 — 복사 없는 strided 뷰
        assert native_surface_of(frame) is handle
    padded[1, 5] = 99  # 바탕을 바꾸면 뷰에서 보인다
    assert from_array[1, 1, 1] == 99 and from_memoryview[1, 1, 1] == 99


@pytest.mark.parametrize(
    "buffer",
    [
        pytest.param(np.zeros((2, 16), np.int8), id="int8"),
        pytest.param(np.zeros((2, 16), np.float32), id="float32"),
        pytest.param(np.zeros((2, 15), np.uint8), id="bytesPerRow-15-lt-4x4"),
        pytest.param(np.zeros((3, 16), np.uint8), id="rows-differ-from-handle-height"),
        pytest.param(np.zeros(2, np.uint8), id="1-D"),
    ],
)
def test_wrap_native_rejects_wrong_dtype_or_size(buffer):
    """깨지는 변경: wrap_native가 해당 검증을 빼고 numpy reshape/IndexError에 맡김 — 조용히 통과하거나 우리 메시지("버퍼")가 없는 다른 예외."""
    handle = NativeHandle(1234, 4, 2, 7, keepalive=object())
    with pytest.raises(ValueError, match="버퍼"):
        wrap_native(buffer, handle)
