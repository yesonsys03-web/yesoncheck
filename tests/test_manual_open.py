"""사용법 매뉴얼 열기(manual_open)와 Help → 사용법(F1)의 연결."""
import os
import subprocess
import sys
import types

import pytest

from yesoncheck import build_info, manual_html, manual_open
from yesoncheck.build_info import BuildInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_images_dir_is_the_package_folder_in_a_source_run():
    assert manual_open.images_dir() == os.path.join(ROOT, "yesoncheck", "manual_images")


def test_images_dir_is_the_bundle_folder_in_a_built_app(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert manual_open.images_dir() == os.path.join(str(tmp_path), "manual_images")


def test_load_image_reads_bytes_and_does_not_invent_a_missing_one(tmp_path):
    (tmp_path / "shot.png").write_bytes(b"png bytes")
    assert manual_open.load_image("shot", str(tmp_path)) == b"png bytes"
    with pytest.raises(FileNotFoundError):
        manual_open.load_image("nowhere", str(tmp_path))


def test_output_dir_per_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", os.path.join(str(tmp_path), "Local"))
    home = os.path.expanduser("~")
    assert manual_open.output_dir("darwin") == os.path.join(home, "Library", "Caches", "YesonCheck", "manual")
    assert manual_open.output_dir("win32") == os.path.join(str(tmp_path), "Local", "YesonCheck", "manual")
    assert manual_open.output_dir("linux") == os.path.join(home, ".cache", "YesonCheck", "manual")


def test_write_makes_one_complete_file(tmp_path):
    folder = tmp_path / "새 폴더" / "manual"
    path = manual_open.write(str(folder))
    assert path == os.path.join(str(folder), manual_open.FILE_NAME)
    assert os.listdir(folder) == [manual_open.FILE_NAME]  # 임시 파일이 남지 않음
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert text.startswith("<!DOCTYPE html>") and text.rstrip().endswith("</html>")
    assert f"버전 {build_info.SOURCE_VERSION}" in text  # 소스 실행


def test_write_overwrites_the_previous_file(tmp_path):
    first = manual_open.write(str(tmp_path))
    with open(first, "w", encoding="utf-8") as fh:
        fh.write("낡은 글")
    second = manual_open.write(str(tmp_path))
    assert second == first
    with open(second, encoding="utf-8") as fh:
        assert fh.read().startswith("<!DOCTYPE html>")


def test_write_failure_leaves_no_half_file_and_raises(tmp_path, monkeypatch):
    (tmp_path / manual_open.FILE_NAME).write_text("앞서 쓴 글", encoding="utf-8")

    def refuse(src, dst):
        raise PermissionError("바꿔 끼울 수 없음")

    monkeypatch.setattr(manual_open.os, "replace", refuse)
    with pytest.raises(PermissionError, match="바꿔 끼울 수 없음"):
        manual_open.write(str(tmp_path))
    assert os.listdir(tmp_path) == [manual_open.FILE_NAME]
    assert (tmp_path / manual_open.FILE_NAME).read_text(encoding="utf-8") == "앞서 쓴 글"


def test_write_does_not_hide_a_missing_image(tmp_path, monkeypatch):
    """빌드에서 그림이 빠졌으면 빈 매뉴얼을 쓰지 않고 FileNotFoundError."""
    monkeypatch.setattr(manual_open, "images_dir", lambda: str(tmp_path / "없는 그림 폴더"))
    with pytest.raises(FileNotFoundError):
        manual_open.write(str(tmp_path / "out"))
    assert not os.path.exists(tmp_path / "out" / manual_open.FILE_NAME)


@pytest.mark.parametrize("info, expected_text, expected_current", [
    (None, build_info.SOURCE_VERSION, None),
    (BuildInfo("1.9.0", "a" * 40, "2026-11-11T10:00:00+09:00", "mac-arm64"), "1.9.0", "1.9.0"),
    (BuildInfo("1.9.0+0f4d3d7", "0f4d3d7" + "e" * 33, "2026-11-11T10:00:00+09:00", "mac-arm64"),
     "1.9.0+0f4d3d7" + build_info.TEST_BUILD_MARK, None),
])
def test_build_marks_the_current_version_only_for_a_released_build(monkeypatch, info, expected_text, expected_current):
    seen = {}

    def fake_build(load_image, version_text=None, current_version=None):
        seen.update(load=load_image, text=version_text, current=current_version)
        return "html"

    monkeypatch.setattr(build_info, "current", lambda: info)
    monkeypatch.setattr(manual_html, "build", fake_build)
    assert manual_open.build() == "html"
    assert seen == {"load": manual_open.load_image, "text": expected_text, "current": expected_current}


def test_open_file_on_mac_runs_open_with_the_path_as_one_argument(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(manual_open.subprocess, "run", fake_run)
    manual_open.open_file("/tmp/새 폴더/YesonCheck_manual.html", platform="darwin")
    assert calls == [(["/usr/bin/open", "/tmp/새 폴더/YesonCheck_manual.html"],
                      {"capture_output": True, "text": True, "timeout": manual_open.OPEN_TIMEOUT_S})]


def test_open_file_on_mac_reports_a_failed_open(monkeypatch):
    monkeypatch.setattr(manual_open.subprocess, "run",
                        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "No application knows how to open"))
    with pytest.raises(RuntimeError) as caught:
        manual_open.open_file("/tmp/x.html", platform="darwin")
    text = str(caught.value)
    assert "종료 코드 1" in text and "/usr/bin/open" in text and "No application knows how to open" in text


def test_open_file_on_windows_uses_startfile_and_lets_its_error_through(monkeypatch):
    opened = []
    monkeypatch.setattr(manual_open.os, "startfile", opened.append, raising=False)
    monkeypatch.setattr(manual_open.subprocess, "run", lambda *a, **k: pytest.fail("Windows는 startfile로 엶"))
    manual_open.open_file(r"C:\Users\나\manual.html", platform="win32")
    assert opened == [r"C:\Users\나\manual.html"]

    def refuse(path):
        raise OSError(1155, "연결된 프로그램이 없습니다")

    monkeypatch.setattr(manual_open.os, "startfile", refuse, raising=False)
    with pytest.raises(OSError, match="연결된 프로그램이 없습니다"):
        manual_open.open_file(r"C:\x.html", platform="win32")


def test_open_manual_writes_then_opens(monkeypatch, tmp_path):
    order = []
    monkeypatch.setattr(manual_open, "write", lambda: order.append("write") or str(tmp_path / "m.html"))
    monkeypatch.setattr(manual_open, "open_file", lambda path: order.append(("open", path)))
    assert manual_open.open_manual() == str(tmp_path / "m.html")
    assert order == ["write", ("open", str(tmp_path / "m.html"))]


# ---------------------------------------------------------------- 창과의 연결


def test_only_one_show_help_exists_and_the_window_uses_it(qapp):
    """같은 이름의 메서드를 두 믹스인에 두지 않음 — 예전에는 player_playback의 것이 player_base의 것을 가렸음."""
    from yesoncheck import main_window, player_base, player_playback

    assert main_window.VideoPlayer.show_help is player_base.VideoPlayerBase.show_help
    assert "show_help" not in vars(player_playback.PlayerPlaybackMixin)
    owners = [cls.__name__ for cls in main_window.VideoPlayer.__mro__ if "show_help" in vars(cls)]
    assert owners == ["VideoPlayerBase"]


def test_show_help_opens_the_manual_and_logs_the_path(monkeypatch, capsys):
    from yesoncheck import player_base

    calls = []
    monkeypatch.setattr(player_base.manual_open, "open_manual", lambda: calls.append(1) or "/tmp/manual.html")
    player_base.VideoPlayerBase.show_help(None)
    assert calls == [1]
    assert capsys.readouterr().out == "[사용법] 매뉴얼을 엶: /tmp/manual.html\n"


def test_show_help_failure_shows_the_error_window_with_the_traceback(monkeypatch, capsys):
    from yesoncheck import error_window, player_base

    def fail():
        raise FileNotFoundError("manual_images/overview.png")

    shown = []
    monkeypatch.setattr(player_base.manual_open, "open_manual", fail)
    monkeypatch.setattr(error_window, "show_window", shown.append)
    player_base.VideoPlayerBase.show_help(None)  # 예외를 밖으로 내지 않음 (슬롯)
    assert len(shown) == 1
    assert shown[0].startswith(manual_open.OPEN_FAILED_TEXT)
    assert "FileNotFoundError" in shown[0] and "manual_images/overview.png" in shown[0]
    captured = capsys.readouterr()
    assert "[사용법] " + manual_open.OPEN_FAILED_TEXT in captured.err and "Traceback" in captured.err
    assert captured.out == ""


def test_help_menu_and_button_are_wired_to_show_help():
    """Help → 사용법(F1)과 Help 단추가 이 메서드를 부름 (글자로 확인 — 창을 만들지 않음)."""
    with open(os.path.join(ROOT, "yesoncheck", "player_base.py"), encoding="utf-8") as fh:
        text = fh.read()
    assert "help_action = help_menu.addAction('사용법')" in text
    assert "help_action.setShortcut('F1')" in text
    assert "help_action.triggered.connect(self.show_help)" in text
    assert "helpButton.clicked.connect(self.show_help)" in text


# ---------------------------------------------------------------- 빌드한 앱의 확인 (smoke)


def test_smoke_step_writes_the_manual_with_all_images(tmp_path):
    from yesoncheck import smoke_test

    detail = smoke_test.manual_written(str(tmp_path / "manual"))
    assert detail["path"] == os.path.join(str(tmp_path / "manual"), manual_open.FILE_NAME)
    assert detail["bytes"] == os.path.getsize(detail["path"]) > 1_000_000
    assert detail["images"] == len(manual_html.image_names())


def test_smoke_step_fails_when_the_bundle_lacks_an_image(tmp_path, monkeypatch):
    from yesoncheck import smoke_test

    monkeypatch.setattr(manual_open, "images_dir", lambda: str(tmp_path / "빈 묶음"))
    with pytest.raises(FileNotFoundError):
        smoke_test.manual_written(str(tmp_path / "manual"))


def test_smoke_runs_the_manual_step():
    with open(os.path.join(ROOT, "yesoncheck", "smoke_test.py"), encoding="utf-8") as fh:
        text = fh.read()
    assert 'check("사용법 매뉴얼", lambda: manual_written(os.path.join(out_dir, "manual")))' in text


def test_spec_bundles_exactly_the_manual_images():
    """spec이 매뉴얼이 쓰는 그림을 앱의 manual_images/에 넣고, 하나라도 없으면 빌드를 멈춤."""
    with open(os.path.join(ROOT, "YesonCheck_Autocut.spec"), encoding="utf-8") as fh:
        text = fh.read()
    assert "for _name in _manual_html.image_names():" in text
    assert "manual_datas.append((_path, 'manual_images'))" in text
    assert "raise SystemExit(f\"[spec] 사용법 매뉴얼의 그림이 없습니다" in text
    assert "+ manual_datas +" in text
    assert manual_open.IMAGES_FOLDER == "manual_images"
