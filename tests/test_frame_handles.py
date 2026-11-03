import gc

import numpy as np
import pytest
from yesoncheck.frame_handles import NativeFrameArray, NativeHandle, native_surface_of, whole_surface_handle, wrap_native


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
    """깨지는 변경: native_surface_of가 isinstance 검사 없이 .native를 읽음(일반 배열에서 AttributeError) / 클래스 기본값 native=None을 지움(손잡이 없는 NativeFrameArray에서 AttributeError)."""
    assert native_surface_of(np.zeros((2, 2, 3), np.uint8)) is None and native_surface_of(None) is None
    handleless = np.zeros((2, 2, 3), np.uint8).view(NativeFrameArray)  # 손잡이 없는 서브클래스 배열
    assert handleless.native is None and native_surface_of(handleless) is None


@pytest.mark.parametrize(
    "to_plain",
    [
        pytest.param(np.asarray, id="np.asarray"),
        pytest.param(lambda frame: frame.view(np.ndarray), id="view(np.ndarray)"),
        pytest.param(np.ascontiguousarray, id="np.ascontiguousarray"),
    ],
)
def test_plain_views_keep_keepalive_alive(to_plain):
    """깨지는 변경: 바탕 배열의 .base 사슬 끝에 손잡이를 쥔 객체가 없음 — numpy가 같은 타입 base만 따라 접어 일반 ndarray 뷰의 사슬이 NativeFrameArray를 건너뛰고 원본 버퍼에서 끝나, 뷰가 남아 있어도 keepalive(잠금·버퍼 반환)가 먼저 풀린다."""
    import weakref

    class Owner:
        pass

    buffer = np.zeros((2, 16), np.uint8)  # 바탕 메모리는 따로 살아 있다 — keepalive만 뷰와 함께 살아야 함
    o = Owner()
    ref = weakref.ref(o)
    frame = wrap_native(memoryview(buffer), NativeHandle(1, 4, 2, 0, keepalive=o))
    plain = to_plain(frame)
    assert type(plain) is np.ndarray and np.shares_memory(plain, buffer)  # 복사가 아니라 같은 메모리의 일반 뷰
    del frame, o
    gc.collect()
    assert ref() is not None
    del plain
    gc.collect()
    assert ref() is None


def test_readonly_buffer_stays_readonly_through_every_view():
    """깨지는 변경: 바탕 객체의 __array_interface__가 읽기 전용 표시를 잃음 — 읽기 잠금 버퍼(읽기 전용 memoryview) 위의 프레임·슬라이스·일반 뷰에 쓸 수 있게 된다."""
    buffer = np.zeros((2, 16), np.uint8)
    frame = wrap_native(memoryview(buffer).toreadonly(), NativeHandle(1, 4, 2, 0, keepalive=object()))
    for view in (frame, frame[:, :2], np.asarray(frame), frame.view(np.ndarray)):
        assert not view.flags.writeable
    with pytest.raises(ValueError):
        frame[0, 0, 0] = 1
    assert wrap_native(buffer, NativeHandle(1, 4, 2, 0, keepalive=object())).flags.writeable  # 넘긴 그대로(쓰기 가능이면 쓰기 가능)


def test_handles_compare_by_identity():
    """깨지는 변경: NativeHandle을 값 비교 dataclass로 둠(@dataclass 기본 eq=True) — 필드가 같은 서로 다른 프레임 손잡이가 같다고 나오고 해시도 불가."""
    keepalive = object()
    first = NativeHandle(1, 4, 2, 0, keepalive=keepalive)
    second = NativeHandle(1, 4, 2, 0, keepalive=keepalive)
    assert first == first and first != second and len({first, second}) == 2


def test_keepalive_lives_while_any_view_lives():
    """깨지는 변경: 배열이 손잡이를 약한 참조로만 쥠 / 손잡이가 keepalive를 놓침 — 뷰가 살아 있는데 keepalive가 먼저 풀린다. 또는 마지막 뷰가 사라져도 keepalive가 남음(바탕 객체가 바탕 배열을 쥐는 순환 — 일반 ndarray는 gc가 추적하지 못해 gc.collect로도 안 풀린다)."""
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
    """깨지는 변경: 손잡이·바탕 객체(_SurfaceBuffer)↔배열 순환(예: 바탕 객체나 손잡이가 배열을 저장) — gc를 끈 채로는 keepalive가 풀리지 않음."""
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
        plain = np.asarray(a)
        del o, a, v
        assert ref() is not None  # 일반 뷰가 남아 있는 동안은 산다
        del plain
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
        pytest.param(np.zeros((2, 32), np.uint8)[:, ::2], id="column-stride-not-1"),
    ],
)
def test_wrap_native_rejects_wrong_dtype_or_size(buffer):
    """깨지는 변경: wrap_native가 해당 검증을 빼고 numpy reshape/IndexError에 맡김 — 조용히 통과하거나 우리 메시지("버퍼")가 없는 다른 예외. (열 간격이 1이 아닌 바탕은 표면의 픽셀 배치가 아니다)"""
    handle = NativeHandle(1234, 4, 2, 7, keepalive=object())
    with pytest.raises(ValueError, match="버퍼"):
        wrap_native(buffer, handle)


def test_whole_surface_handle_for_the_whole_frame_and_plain_views_of_it():
    """깨지는 변경: whole_surface_handle이 NativeFrameArray의 .native만 읽음 — 표면 전체를 가리키는 일반 ndarray 뷰(asarray·view·ascontiguousarray)가 None이 된다(바탕 사슬 끝의 손잡이 객체로 찾아야 함)."""
    a, h = _frame(bytes_per_row=24)  # 행 패딩 8바이트가 있는 strided 프레임
    whole_views = (a, a[...], np.asarray(a), a.view(np.ndarray), a[::-1][::-1])  # 두 번 뒤집으면 원래 배치
    for view in whole_views:
        assert whole_surface_handle(view) is h
    contiguous, ch = _frame(bytes_per_row=16)
    assert whole_surface_handle(np.ascontiguousarray(contiguous)) is ch  # 연속 프레임이면 복사 없이 같은 메모리
    assert np.shares_memory(np.ascontiguousarray(contiguous), contiguous)


@pytest.mark.parametrize(
    "partial",
    [
        pytest.param(lambda a: a[::-1], id="flipped-vertically"),
        pytest.param(lambda a: a[..., ::-1], id="channels-reversed"),
        pytest.param(lambda a: a[:, :8], id="left-columns"),
        pytest.param(lambda a: a[..., :3], id="three-channels"),
        pytest.param(lambda a: a[:1], id="first-row"),
        pytest.param(lambda a: a[:, ::2], id="every-other-column"),
        pytest.param(lambda a: a.view(np.int8), id="int8-reinterpretation"),
        pytest.param(lambda a: a.reshape(2, -1), id="reshaped"),
        pytest.param(lambda a: a.copy(), id="copy"),
        pytest.param(lambda a: a.astype(np.uint8), id="astype-copy"),
        pytest.param(lambda a: a + 1, id="ufunc-result"),
    ],
)
def test_whole_surface_handle_rejects_partial_flipped_or_copied_views(partial):
    """깨지는 변경: whole_surface_handle이 shape만 비교(뒤집힌·채널 역순 뷰가 통과) / dtype을 안 봄(int8 재해석) / 바탕 사슬 없이 .native를 믿음(복사본·ufunc 결과)."""
    a, _ = _frame(width=16, bytes_per_row=72)  # 너비 16(a[:, :8]이 왼쪽 절반이 되도록), 행 패딩 8바이트
    assert whole_surface_handle(a) is not None
    view = partial(a)
    assert whole_surface_handle(view) is None
    if isinstance(view, np.ndarray):
        assert whole_surface_handle(np.asarray(view)) is None  # 일반 뷰로 바꿔도 마찬가지


def test_whole_surface_handle_rejects_same_shape_with_different_strides():
    """깨지는 변경: strides 비교를 뺌 — 정사각 프레임의 transpose는 shape·시작 주소가 같지만 행/열 간격이 달라 표면 배치가 아니다."""
    square, _ = _frame(width=4, height=4, bytes_per_row=16)
    swapped = square.transpose(1, 0, 2)
    assert swapped.shape == square.shape and swapped.ctypes.data == square.ctypes.data and swapped.strides != square.strides
    assert whole_surface_handle(swapped) is None


def test_whole_surface_handle_rejects_same_layout_shifted_into_row_padding():
    """깨지는 변경: 시작 주소 비교를 뺌 — shape·strides가 같아도 행 패딩 쪽으로 어긋난 뷰는 표면 전체가 아니다."""
    a, _ = _frame(bytes_per_row=32)  # 행마다 16바이트 패딩
    root = a
    while isinstance(root.base, np.ndarray):
        root = root.base  # 손잡이 객체 바로 위의 (높이, bytesPerRow) 바탕 배열
    shifted = root[:, 8:24].reshape(2, 4, 4)
    assert shifted.shape == a.shape and shifted.strides == a.strides and shifted.ctypes.data != a.ctypes.data
    assert whole_surface_handle(shifted) is None


def test_whole_surface_handle_is_none_without_a_native_buffer_behind_it():
    """깨지는 변경: 바탕 사슬을 확인하지 않고 shape·strides만 맞으면 통과 — 같은 shape의 일반 배열·손잡이 없는 서브클래스 배열·비배열이 손잡이를 주장."""
    plain = np.zeros((2, 4, 4), np.uint8)
    assert whole_surface_handle(plain) is None
    assert whole_surface_handle(plain.view(NativeFrameArray)) is None
    assert whole_surface_handle(None) is None and whole_surface_handle(memoryview(b"abcd")) is None
