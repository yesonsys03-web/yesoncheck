"""Settings 메뉴에서 뺀 두 항목(GPU Acceleration·4K 성능 모드)과, 그 원인이던 믹스인 사이의 이름 겹침 (2026-11-12).

두 항목은 저장소 첫 커밋부터 고른 값이 적용된 적이 없음:
- 4K 성능 모드: set_performance_mode가 VideoPlayerBase(메뉴용 — 정수 index)와 PlayerPlaybackMixin(문자열 모드)에 같은 이름으로
  둘이라, MRO에서 앞선 쪽이 정수를 받아 늘 '자동' 갈래로 감 (메뉴 체크도 쌓임).
- GPU Acceleration: 빌드의 OpenCV에 CUDA가 없어 항목이 [CPU, AMD (OpenCL)] 둘인데 OpenCL에 index 2를 넘겨 아무 일도 안 함.

고쳐서 살리면 GPU는 색 변환이 느려지고(이 Mac 실측 4K 2.8ms → 25ms) 성능 모드는 재생이 아니라 슬라이더 드래그 미리보기 값만
바꿔서, 사용자 결정으로 메뉴에서 뺌. 값은 메뉴를 건드리지 않은 창이 늘 쓰던 값(켠 직후의 값) 그대로 — 동작은 바뀌지 않음.
"""

import ast
import inspect
import textwrap

import numpy as np
import pytest

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck.main_window import VideoPlayer

REMOVED_MENUS = ("GPU Acceleration", "4K 성능 모드")
# 뺀 설정의 메뉴 처리기·화면에 없던 콤보 상자·읽는 곳 없던 값 — 남아 있으면 없는 위젯을 가리키는 죽은 배선
REMOVED_NAMES = (
    "set_gpu_mode", "change_gpu_backend", "gpu_action_group", "gpuComboBox", "gpuLabel",
    "set_performance_mode", "change_performance_mode", "performance_action_group", "performanceComboBox",
    "skip_frame_processing",
)


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def settings_texts(player):
    [action] = [a for a in player.menuBar().actions() if a.text() == "&Settings"]
    return [a.text() for a in action.menu().actions()]


def test_settings_menu_does_not_offer_gpu_acceleration_or_4k_performance_mode(player):
    assert [text for text in settings_texts(player) if text in REMOVED_MENUS] == []


@pytest.mark.parametrize("name", REMOVED_NAMES)
def test_removed_settings_leave_no_wiring_behind(player, name):
    assert not hasattr(player, name)


def test_drag_preview_values_are_the_ones_every_window_started_with(player):
    """메뉴를 건드리지 않은 창이 늘 쓰던 값 — 메뉴를 빼도 드래그 미리보기(캐시 장수·갱신 간격 ms·건너뛰기 문턱)가 그대로."""
    assert (player.cache_size, player.drag_update_interval, player.frame_skip_threshold) == (50, 30, 5)
    assert player.performance_mode == "auto"


def test_frames_are_converted_on_the_cpu_as_before(player):
    """색 변환은 예전 기본값(CPU)대로 BGR → RGB 채널 뒤집기 — HD 길(process_frame)과 4K 길(optimize_for_4k) 모두."""
    assert (player.use_gpu, player.gpu_backend) == (False, None)
    rng = np.random.default_rng(7)
    hd = rng.integers(0, 256, (18, 32, 3), dtype=np.uint8)
    uhd = rng.integers(0, 256, (2160, 3840, 3), dtype=np.uint8)
    assert np.array_equal(player.process_frame(hd), hd[:, :, ::-1])
    assert np.array_equal(player.optimize_for_4k(uhd), uhd[:, :, ::-1])


def calls_super(function, name):
    """함수 본문에 진짜 `super().name(...)` 호출이 있는가 — 주석·docstring 속의 글자는 치지 않음."""
    for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(function)))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name:
            target = node.func.value
            if isinstance(target, ast.Call) and isinstance(target.func, ast.Name) and target.func.id == "super":
                return True
    return False


def test_calls_super_looks_at_real_calls_only():
    def extends(self):
        return super().extends() + 1

    def only_mentions(self):
        """super().only_mentions() 라고 적혀만 있음"""
        return 1  # super().only_mentions(

    assert calls_super(extends, "extends") and not calls_super(only_mentions, "only_mentions")


def test_no_player_class_silently_shadows_a_name_of_a_later_one():
    """VideoPlayer를 이루는 프로젝트 클래스 둘이 같은 이름을 정의하면 MRO에서 앞선 쪽만 불리고 뒤쪽은 말없이 죽은 코드가 됨
    (set_performance_mode·show_help가 그렇게 가려져 있었음). 뒤쪽을 super()로 이어 부르는 확장만 허용. __init__도 봄."""
    classes = [cls for cls in VideoPlayer.__mro__ if cls.__module__.startswith("yesoncheck.")]
    shadowed = []
    for index, cls in enumerate(classes):
        for name, value in vars(cls).items():
            if name.startswith("__") and name.endswith("__") and name != "__init__":
                continue
            later = [other.__name__ for other in classes[index + 1:] if name in vars(other)]
            if not later:
                continue
            function = getattr(value, "__func__", value)
            if inspect.isfunction(function) and calls_super(function, name):
                continue
            shadowed.append(f"{cls.__name__}.{name} 가 {', '.join(later)} 의 것을 가림")
    assert shadowed == []
