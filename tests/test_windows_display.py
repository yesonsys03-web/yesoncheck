"""(Windows) 화면 그리기 설정 — Settings 메뉴로 CPU·GPU를 고름 (사용자 확인 2026-11-05: 4K를 GL로 그리면 끊김이 줄었지만 PC마다 그래픽 카드가 달라 끄는 길이 필요).

기본은 CPU(예전 그대로 — 사용자 결정). GPU를 골라도 이 PC의 GL이 그리기 코드와 맞지 않으면(ANGLE·소프트웨어 GL·낡은 GL) CPU로 돌리고 알림.
이 Mac에서는 sys.platform·플랫폼 이름을 바꿔 규칙을 봄 — 실제 Windows GL은 사람이 확인."""

import ctypes
import json
import re
import sys
import time

import pytest
from PyQt5.QtWidgets import QApplication, QMenu, QMessageBox

from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import app, gl_bindings, gl_video_item, user_files, video_widget, windows_display
from yesoncheck.player_playback import _MeasureRun, measurement_line
from yesoncheck.video_widget import CustomVideoWidget, viewport_mode

NVIDIA = gl_bindings.GLInfo(is_es=False, version=(4, 6), renderer="NVIDIA GeForce RTX 3060/PCIe/SSE2")


@pytest.fixture
def local_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")
    return tmp_path


def prefs_file(root):
    return root / "YesonCheck" / "prefs.json"


# ---------------------------------------------------------------- 값과 저장


def test_default_is_cpu():
    assert windows_display.preferred() == "cpu"


def test_bad_name_raises_and_keeps_the_value():
    with pytest.raises(ValueError, match="display_renderer"):
        windows_display.set_preferred("metal")
    assert windows_display.preferred() == "cpu"


def test_saved_in_local_app_data_and_keeps_other_keys(local_app_data):
    prefs_file(local_app_data).parent.mkdir(parents=True)
    prefs_file(local_app_data).write_text(json.dumps({"other": 1}), encoding="utf-8")
    windows_display.save("gpu")
    saved = json.loads(prefs_file(local_app_data).read_text(encoding="utf-8"))
    assert saved == {"other": 1, "display_renderer": "gpu"}
    assert windows_display.read() == "gpu"


def test_broken_prefs_raise_and_are_not_overwritten(local_app_data):
    prefs_file(local_app_data).parent.mkdir(parents=True)
    prefs_file(local_app_data).write_text("{깨짐", encoding="utf-8")
    with pytest.raises(user_files.UserFileError):
        windows_display.read()
    with pytest.raises(user_files.UserFileError):
        windows_display.save("gpu")
    assert prefs_file(local_app_data).read_text(encoding="utf-8") == "{깨짐"


# ---------------------------------------------------------------- 시작 때 읽기


def test_launch_reads_gpu_from_prefs(local_app_data, capsys):
    windows_display.save("gpu")
    app.load_display_renderer()
    assert windows_display.preferred() == "gpu"
    assert "[뷰포트] 화면 그리기 설정: gpu" in capsys.readouterr().out


def test_launch_without_prefs_stays_cpu(local_app_data):
    windows_display.set_preferred("gpu")  # 읽지 않으면 그대로 남아 실패
    app.load_display_renderer()
    assert windows_display.preferred() == "cpu"


def test_broken_prefs_at_launch_warn_and_use_cpu(local_app_data, monkeypatch, capsys):
    prefs_file(local_app_data).parent.mkdir(parents=True)
    prefs_file(local_app_data).write_text("{깨짐", encoding="utf-8")
    windows_display.set_preferred("gpu")
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[1:3]))
    app.load_display_renderer()
    assert windows_display.preferred() == "cpu"
    assert warned and "Traceback" in capsys.readouterr().err


def test_launch_on_mac_reads_nothing(monkeypatch):
    monkeypatch.setattr(windows_display, "read", lambda: pytest.fail("Windows 전용 설정을 읽음"))
    monkeypatch.setattr(sys, "platform", "darwin")
    app.load_display_renderer()


# ---------------------------------------------------------------- 뷰포트 선택


def test_windows_follows_the_setting():
    assert viewport_mode("windows", {}, "cpu") == "raster"
    assert viewport_mode("windows", {}, "gpu") == "gl"


def test_env_overrides_the_setting():
    assert viewport_mode("windows", {"YESONCHECK_VIEWPORT": "raster"}, "gpu") == "raster"
    assert viewport_mode("windows", {"YESONCHECK_VIEWPORT": "gl"}, "cpu") == "gl"


def test_other_platforms_ignore_the_setting():
    assert viewport_mode("cocoa", {}, "cpu") == "gl"
    assert viewport_mode("offscreen", {}, "gpu") == "raster"


# ---------------------------------------------------------------- 이 PC의 GL이 맞는가


def test_real_gpu_has_no_problem():
    assert windows_display.gl_problem(NVIDIA) is None


@pytest.mark.parametrize("info, word", [
    (None, "만들지"),
    (gl_bindings.GLInfo(True, (3, 0), "ANGLE (Intel)"), "ANGLE"),
    (gl_bindings.GLInfo(False, (1, 1), "GDI Generic"), "소프트웨어"),
    (gl_bindings.GLInfo(False, (1, 4), "Old Card"), "1.4"),
    (gl_bindings.GLInfo(False, (4, 5), "llvmpipe (LLVM 12.0, 256 bits)"), "소프트웨어"),
    (gl_bindings.GLInfo(False, (3, 3), "Microsoft Basic Render Driver"), "소프트웨어"),
    (gl_bindings.GLInfo(False, (4, 5), "Google SwiftShader"), "소프트웨어"),
])
def test_unusable_gl_is_named(info, word):
    assert word in windows_display.gl_problem(info)


@pytest.fixture
def gpu_on_windows(monkeypatch):
    monkeypatch.setattr(video_widget.QApplication, "platformName", staticmethod(lambda: "windows"))
    monkeypatch.setattr(video_widget, "gl_context_available", lambda: True)
    windows_display.set_preferred("gpu")


def test_unusable_gl_falls_back_to_cpu_and_tells_why(qapp, gpu_on_windows, monkeypatch, capsys):
    monkeypatch.setattr(gl_bindings, "context_info", lambda: gl_bindings.GLInfo(True, (3, 0), "ANGLE (Intel)"))
    widget = CustomVideoWidget()
    assert widget.video_item_stream is False
    assert widget.display_path() == "raster"
    assert "ANGLE" in widget.viewport_fallback_reason and windows_display.MENU_TEXT in widget.viewport_fallback_reason
    assert "raster로 계속" in capsys.readouterr().out


def test_good_gl_uses_the_gpu(qapp, gpu_on_windows, monkeypatch):
    monkeypatch.setattr(gl_bindings, "context_info", lambda: NVIDIA)
    widget = CustomVideoWidget()
    assert widget.video_item_stream is True
    assert widget.viewport_fallback_reason is None


def test_failed_probe_falls_back_without_crashing(qapp, gpu_on_windows, monkeypatch, capsys):
    """확인이 예외를 내도 창은 열려야 함 — GPU를 고른 PC가 앱을 못 켜면 메뉴로 되돌릴 수도 없음. 트레이스백은 기록에."""
    def boom():
        raise OSError("드라이버 오류")

    monkeypatch.setattr(gl_bindings, "context_info", boom)
    widget = CustomVideoWidget()
    assert widget.video_item_stream is False
    assert "드라이버 오류" in widget.viewport_fallback_reason
    assert "Traceback" in capsys.readouterr().err


def test_env_forced_gl_skips_the_check(qapp, gpu_on_windows, monkeypatch):
    """환경 변수는 진단용 강제 — 확인 없이 그대로(기존 규칙)."""
    monkeypatch.setenv("YESONCHECK_VIEWPORT", "gl")
    monkeypatch.setattr(gl_bindings, "context_info", lambda: pytest.fail("강제인데 확인함"))
    assert CustomVideoWidget().video_item_stream is True


def test_context_info_is_none_without_a_context(qapp):
    """offscreen은 컨텍스트를 못 만듦 — 예외가 아니라 None."""
    assert QApplication.platformName() == "offscreen"
    assert gl_bindings.context_info() is None


class FakeContext:
    """QOpenGLContext 대역 — getProcAddress가 진짜 C 함수 주소를 줌 (context_info는 ctypes로 부름)."""

    def __init__(self, renderer=b"NVIDIA RTX", proc="real", current=True, es=False):
        self.done, self.current = 0, current
        self.es = es
        self._buffer = ctypes.create_string_buffer(renderer) if renderer is not None else None
        self._callback = ctypes.CFUNCTYPE(ctypes.c_size_t, ctypes.c_uint)(self._get_string)
        self._proc = ctypes.cast(self._callback, ctypes.c_void_p).value if proc == "real" else proc

    def _get_string(self, name):
        assert name == gl_bindings.GL_RENDERER
        return ctypes.addressof(self._buffer) if self._buffer is not None else 0

    def create(self):
        return True

    def format(self):
        from PyQt5.QtGui import QSurfaceFormat
        fmt = QSurfaceFormat()
        fmt.setVersion(4, 6)
        return fmt

    def makeCurrent(self, _surface):
        return self.current

    def doneCurrent(self):
        self.done += 1

    def getProcAddress(self, _name):
        return self._proc

    def isOpenGLES(self):
        return self.es


class FakeSurface:
    def setFormat(self, _fmt):
        pass

    def create(self):
        pass


def probe_with(monkeypatch, context):
    monkeypatch.setattr(gl_bindings, "QOpenGLContext", lambda: context)
    monkeypatch.setattr(gl_bindings, "QOffscreenSurface", FakeSurface)
    return gl_bindings.context_info()


def test_context_info_reads_the_gl(monkeypatch):
    context = FakeContext()
    assert probe_with(monkeypatch, context) == gl_bindings.GLInfo(False, (4, 6), "NVIDIA RTX")
    assert context.done == 1


def test_context_info_without_make_current_is_none(monkeypatch):
    assert probe_with(monkeypatch, FakeContext(current=False)) is None


@pytest.mark.parametrize("proc", [None, 0, 1, 2, 3, -1])
def test_context_info_refuses_bad_function_addresses(monkeypatch, proc):
    """일부 드라이버는 없는 함수에 1·2·3·-1을 돌려줌 — 그대로 부르면 앱이 죽음. 예외면 부른 쪽이 CPU로 돌림."""
    context = FakeContext(proc=proc)
    with pytest.raises(gl_bindings.GLBindingError):
        probe_with(monkeypatch, context)
    assert context.done == 1


def test_context_info_refuses_a_null_renderer(monkeypatch):
    """빈 글자로 치면 소프트웨어 GL 판정을 지나 '쓸 수 있음'이 됨."""
    with pytest.raises(gl_bindings.GLBindingError):
        probe_with(monkeypatch, FakeContext(renderer=None))


def test_paint_failure_points_to_the_menu_on_windows():
    """GL 그리기가 실패하면 영상 영역이 비므로 창이 되돌리는 길을 알려야 함."""
    assert windows_display.MENU_TEXT in gl_video_item.failure_menu_hint("win32")
    assert "재생 디코더" in gl_video_item.failure_menu_hint("darwin")
    assert gl_video_item.failure_menu_hint("linux") == ""


# ---------------------------------------------------------------- 메뉴


@pytest.fixture
def menu_player(new_player, dialogs, tmp_path, local_app_data, monkeypatch):  # noqa: F811
    player = new_player(make_config(str(tmp_path), {}))
    notes = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: notes.append(args[2]))
    player._add_display_menu(QMenu(player))
    return player, notes


def test_window_builds_with_the_menu_on_windows(menu_player):
    """Settings 메뉴는 영상 화면보다 먼저 만들어짐 — 메뉴를 맞추다 videoWidget을 찾으면 Windows에서 창이 안 열림 (fixture의 창 생성이 그 길). 열 때 맞춤."""
    player, _notes = menu_player
    menu = QMenu(player)
    player._add_display_menu(menu)
    player.display_status_action.setText("")
    menu.actions()[0].menu().aboutToShow.emit()
    assert player.display_status_action.text() == "지금 이 창: CPU"


def test_no_menu_on_mac(new_player, dialogs, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sys, "platform", "darwin")
    player = new_player(make_config(str(tmp_path), {}))
    menu = QMenu(player)
    player._add_display_menu(menu)
    assert player.display_actions == {} and menu.isEmpty()


def test_menu_starts_on_the_saved_choice(menu_player):
    player, _notes = menu_player
    assert player.display_actions["cpu"].isChecked() and not player.display_actions["gpu"].isChecked()
    assert player.display_actions["cpu"].text() == "CPU (기본)"
    assert player.display_status_action.text() == "지금 이 창: CPU"
    assert not player.display_status_action.isEnabled()


def test_choosing_gpu_saves_and_says_when_it_applies(menu_player, local_app_data):
    player, notes = menu_player
    player.display_actions["gpu"].trigger()
    assert json.loads(prefs_file(local_app_data).read_text(encoding="utf-8"))["display_renderer"] == "gpu"
    assert windows_display.preferred() == "gpu"
    assert player.display_actions["gpu"].isChecked() and not player.display_actions["cpu"].isChecked()
    assert "다음에 여는 창" in notes[-1]
    assert player.display_status_action.text() == "지금 이 창: CPU"  # 이 창은 그대로 — 뷰포트는 창을 만들 때 정함


def test_choosing_after_another_window_saved_writes_the_file(menu_player, local_app_data):
    """창마다 프로세스 — 다른 창이 GPU를 저장한 뒤 이 창에서 CPU를 고르면 저장돼야 함. 이 창의 캐시(cpu)만 보면 아무 일도 안 해 다음 창이 GPU로 열림."""
    player, notes = menu_player
    windows_display.save("gpu")  # 다른 창
    player.display_actions["cpu"].trigger()
    assert json.loads(prefs_file(local_app_data).read_text(encoding="utf-8"))["display_renderer"] == "cpu"
    assert notes


def test_opening_the_menu_shows_what_another_window_saved(menu_player):
    player, _notes = menu_player
    windows_display.save("gpu")  # 다른 창
    player._sync_display_menu()
    assert player.display_actions["gpu"].isChecked() and not player.display_actions["cpu"].isChecked()


def test_broken_file_while_opening_the_menu_keeps_it_usable(menu_player, local_app_data, capsys):
    player, _notes = menu_player
    prefs_file(local_app_data).parent.mkdir(parents=True)
    prefs_file(local_app_data).write_text("{깨짐", encoding="utf-8")
    player._sync_display_menu()
    assert player.display_actions["cpu"].isChecked()
    assert "Traceback" in capsys.readouterr().err


def test_choosing_the_same_again_does_nothing(menu_player, local_app_data):
    player, notes = menu_player
    player.display_actions["cpu"].trigger()
    assert notes == [] and not prefs_file(local_app_data).exists()
    assert player.display_actions["cpu"].isChecked()


def test_save_failure_keeps_the_old_choice(menu_player, local_app_data, monkeypatch):
    player, notes = menu_player
    prefs_file(local_app_data).parent.mkdir(parents=True)
    prefs_file(local_app_data).write_text("{깨짐", encoding="utf-8")
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[2]))
    player.display_actions["gpu"].trigger()
    assert windows_display.preferred() == "cpu"
    assert player.display_actions["cpu"].isChecked() and not player.display_actions["gpu"].isChecked()
    assert errors and notes == []


def test_env_override_disables_the_menu(new_player, dialogs, tmp_path, local_app_data, monkeypatch):  # noqa: F811
    monkeypatch.setenv("YESONCHECK_VIEWPORT", "raster")
    player = new_player(make_config(str(tmp_path), {}))
    player._add_display_menu(QMenu(player))
    assert player.display_actions["cpu"].isChecked()
    assert not player.display_actions["cpu"].isEnabled() and not player.display_actions["gpu"].isEnabled()
    assert "YESONCHECK_VIEWPORT=raster" in player.display_actions["gpu"].toolTip()


# ---------------------------------------------------------------- [측정] 줄의 흔들림


def test_measure_run_counts_stalls_and_longest_gap():
    """평균만으로는 '일정한지'를 모름 — 가장 긴 간격과, 프레임 시간의 1.5배를 넘은 횟수."""
    run = _MeasureRun(0.0, 1 / 24)
    for position, now in enumerate((0.042, 0.083, 0.125, 0.250, 0.292), start=1):  # 125ms 한 번
        run.note_tick(now, position)
    assert run.frames == 5
    assert run.last == 0.292
    assert run.max_gap == pytest.approx(0.125)
    assert run.stalls == 1


def test_first_tick_is_not_a_stall():
    """Play 뒤 첫 틱은 한 프레임을 기다리고 재생 시작 일까지 더해져 늘 길음 — 세면 문제없는 재생도 끊김 1, 최대간격도 그 값에 가려짐."""
    run = _MeasureRun(0.0, 1 / 24)
    run.note_tick(0.200, 11)
    run.note_tick(0.242, 12)
    assert run.stalls == 0
    assert run.max_gap == pytest.approx(0.042)
    assert run.frames == 2 and run.last == 0.242


def test_seek_during_playback_is_not_a_stall():
    """탐색은 사용자가 한 일 — 번호가 건너뛴 틱의 간격은 세지 않음 (시간은 전체 fps에 그대로 들어감)."""
    run = _MeasureRun(0.0, 1 / 24)
    for position, now in ((1, 0.042), (2, 0.083), (500, 0.700), (501, 0.742)):
        run.note_tick(now, position)
    assert run.stalls == 0
    assert run.max_gap == pytest.approx(0.042)
    assert run.frames == 4


def test_stall_reaches_the_printed_line(new_player, dialogs, tmp_path, monkeypatch, capsys):  # noqa: F811
    """진짜 재생: 느린 프레임 하나가 [측정] 줄의 끊김으로 나옴 — 값을 줄까지 넘기지 않거나 프레임 시간을 잘못 주면 실패."""
    player = new_player(make_config(str(tmp_path), {}))
    assert player.open_file("A", write_test_video(str(tmp_path / "clip.mp4"), frames=24)) is True
    real_update = player.update_frame
    calls = []

    def slow_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 8:
            time.sleep(0.2)
        return real_update(*args, **kwargs)

    monkeypatch.setattr(player, "update_frame", slow_once)
    capsys.readouterr()
    player.play_video()
    deadline = time.perf_counter() + 10
    while player.timer.isActive() and time.perf_counter() < deadline:
        QApplication.processEvents()
        time.sleep(0.001)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("[측정]")]
    assert len(lines) == 1, lines
    match = re.search(r"최대간격 (\d+)ms 끊김 (\d+)번", lines[0])
    assert match and int(match.group(1)) >= 190 and int(match.group(2)) >= 1, lines[0]


def test_measurement_line_shows_them():
    line = measurement_line(333, 13.88, True, False, "gl", "a.mov", max_gap=0.0464, stalls=2)
    assert line == "[측정] 333장 13.88초 (24.0fps) 최대간격 46ms 끊김 2번 네이티브=yes 와이프=off 표시=gl — a.mov"
