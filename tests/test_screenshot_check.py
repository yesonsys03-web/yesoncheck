"""화면 픽셀 비교 검사(ci/screenshot_check.py) 자체의 시험.

진짜 앱 창을 찍는 시험(같은 작업 트리에서 두 번 찍어 비교 → 같음)은 느리므로 장면 2개(main_window·ocr_review)만 찍는다.
나머지는 손으로 만든 작은 장면 폴더(PNG + 트리 JSON)로 compare가 '같음·다른 픽셀 영역·다른 트리·없는 장면·환경이 다름'을
가려내는지 보고(하위 프로세스로 돌려 종료 코드와 출력을 봄), 정착(settle)·트리 덤프·경로 정리는 작은 위젯으로 같은 프로세스에서
직접 부른다."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QLabel, QWidget

from tests.conftest import ROOT

SCRIPT = os.path.join(ROOT, "ci", "screenshot_check.py")
REAL_SCENES = ["main_window", "ocr_review"]  # 진짜 창을 찍는 시험은 이 둘만 (느림)
SCENE_ARGS = [arg for scene in REAL_SCENES for arg in ("--scene", scene)]


def run(*args):
    # 한글 출력이 Windows 파이프의 기본 인코딩에 걸리지 않게 UTF-8로 고정 (도구 안에서 죽어도 종료 코드 1이라 출력까지 확인)
    env = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, SCRIPT, *map(str, args)], capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=env
    )


def capture(out):
    result = run("capture", "--out", out, *SCENE_ARGS)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope="module")
def real_captures(tmp_path_factory):
    """같은 작업 트리에서 두 번 찍은 폴더 둘 + 각 capture의 출력 (두 시험이 함께 씀)."""
    base = tmp_path_factory.mktemp("shots")
    first, second = base / "first", base / "second"
    return first, second, capture(first), capture(second)


# ---------------------------------------------------------------- 진짜 창


def test_capture_twice_compare_equal(real_captures):
    first, second, first_output, _second_output = real_captures
    for scene in REAL_SCENES:
        for folder in (first, second):
            assert (folder / f"{scene}.png").stat().st_size > 0
            assert (folder / f"{scene}.tree.json").stat().st_size > 0
        # 정착(1.5초 뒤 연속 두 번 grab이 같음)이 장면마다 출력에 남음
        assert f"{scene}: 정착" in first_output.stdout and "연속 두 번 같음" in first_output.stdout

    result = run("compare", "--baseline", first, "--current", second, *SCENE_ARGS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "차이 없음" in result.stdout

    # 트리 덤프는 클래스·objectName·geometry·보임·글자·styleSheet 해시를 담음
    tree = json.loads((first / "main_window.tree.json").read_text(encoding="utf-8"))["tree"]
    for key in ("class", "name", "geometry", "visible", "text", "style_sha256", "children"):
        assert key in tree
    assert tree["class"] == "VideoPlayer" and tree["visible"] is True and tree["geometry"][2:] == [1200, 800]


def test_compare_detects_difference(real_captures, tmp_path):
    first, second, _first_output, _second_output = real_captures
    changed = tmp_path / "changed"
    shutil.copytree(second, changed)
    png = changed / "main_window.png"
    data = bytearray(png.read_bytes())
    data[len(data) // 2] ^= 0x01  # PNG 한 바이트만 바꾼 사본
    png.write_bytes(bytes(data))

    result = run("compare", "--baseline", first, "--current", changed, *SCENE_ARGS)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "== main_window: 다름" in result.stdout and "PNG 바이트가 다름" in result.stdout
    assert "== ocr_review: 같음" in result.stdout  # 바꾸지 않은 장면은 같다고 나옴
    assert "차이 있음: 1/2 장면 (main_window)" in result.stdout


# ---------------------------------------------------------------- 손으로 만든 장면 폴더


def node(name="", children=(), **fields):
    base = {"class": "QWidget", "meta_class": "QWidget", "name": name, "geometry": [0, 0, 100, 80], "visible": True,
            "enabled": True, "text": "", "values": {}, "style_sha256": "", "children": list(children)}
    base.update(fields)
    return base


def write_scene(folder, scene="fake_scene", rect=None, tree=None, dialogs=()):
    """100x80 PNG(바탕 한 색, rect=(x, y, w, h)이면 그 사각형만 다른 색)와 트리 JSON을 씀."""
    folder.mkdir(parents=True, exist_ok=True)
    image = QImage(100, 80, QImage.Format_ARGB32)
    image.fill(QColor(10, 20, 30))
    if rect:
        x, y, w, h = rect
        for px in range(x, x + w):
            for py in range(y, y + h):
                image.setPixelColor(px, py, QColor(200, 100, 50))
    assert image.save(str(folder / f"{scene}.png"), "PNG")
    document = {"scene": scene, "dialogs": list(dialogs), "tree": tree or node("root", [node("child")])}
    (folder / f"{scene}.tree.json").write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")


def compare(baseline, current, *extra):
    return run("compare", "--baseline", baseline, "--current", current, *extra)


def test_compare_identical_folders(tmp_path):
    write_scene(tmp_path / "a")
    write_scene(tmp_path / "b")
    result = compare(tmp_path / "a", tmp_path / "b")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "차이 없음" in result.stdout


def test_compare_reports_the_changed_pixel_region(tmp_path):
    write_scene(tmp_path / "a")
    write_scene(tmp_path / "b", rect=(30, 20, 5, 4))
    result = compare(tmp_path / "a", tmp_path / "b")
    assert result.returncode == 1
    assert "fake_scene" in result.stdout
    assert "20개" in result.stdout  # 다른 픽셀 5 x 4
    assert "x=30..34" in result.stdout and "y=20..23" in result.stdout  # 다른 곳의 바운딩 박스


def test_compare_reports_separate_regions(tmp_path):
    write_scene(tmp_path / "a")
    write_scene(tmp_path / "b")
    image = QImage(str(tmp_path / "b" / "fake_scene.png"))
    for x, y in ((2, 3), (90, 70)):  # 멀리 떨어진 두 곳
        image.setPixelColor(x, y, QColor(255, 255, 255))
    assert image.save(str(tmp_path / "b" / "fake_scene.png"), "PNG")
    result = compare(tmp_path / "a", tmp_path / "b")
    assert result.returncode == 1
    assert "2곳" in result.stdout and "x=2..2 y=3..3" in result.stdout and "x=90..90 y=70..70" in result.stdout


def test_compare_reports_size_change(tmp_path):
    write_scene(tmp_path / "a")
    write_scene(tmp_path / "b")
    small = QImage(60, 40, QImage.Format_ARGB32)
    small.fill(QColor(10, 20, 30))
    assert small.save(str(tmp_path / "b" / "fake_scene.png"), "PNG")
    result = compare(tmp_path / "a", tmp_path / "b")
    assert result.returncode == 1
    assert "100x80" in result.stdout and "60x40" in result.stdout


def test_compare_reports_tree_difference_with_identical_pixels(tmp_path):
    write_scene(tmp_path / "a", tree=node("root", [node("title", text="재생: 대기", geometry=[1, 2, 30, 10])]))
    write_scene(tmp_path / "b", tree=node("root", [node("title", text="재생: 0 FPS", geometry=[1, 2, 31, 10]),
                                                   node("extra")]))
    result = compare(tmp_path / "a", tmp_path / "b")
    assert result.returncode == 1
    out = result.stdout
    assert "PNG 동일" in out and "PNG 바이트가 다름" not in out  # 그림은 같음 → 트리 차이만 보고
    assert "text" in out and "재생: 대기" in out and "재생: 0 FPS" in out
    assert "geometry" in out and "[1, 2, 30, 10]" in out and "[1, 2, 31, 10]" in out
    assert "QWidget#title" in out and "QWidget#extra" in out  # 바뀐 곳·새로 생긴 곳의 경로


def test_compare_reports_changed_dialogs(tmp_path):
    write_scene(tmp_path / "a", dialogs=[{"kind": "information", "title": "완료", "text": "3개"}])
    write_scene(tmp_path / "b", dialogs=[{"kind": "information", "title": "완료", "text": "4개"}])
    result = compare(tmp_path / "a", tmp_path / "b")
    assert result.returncode == 1
    assert "대화 상자" in result.stdout and "3개" in result.stdout and "4개" in result.stdout


def test_compare_reports_scene_missing_on_one_side(tmp_path):
    write_scene(tmp_path / "a", scene="only_before")
    write_scene(tmp_path / "a", scene="both")
    write_scene(tmp_path / "b", scene="both")
    result = compare(tmp_path / "a", tmp_path / "b")
    assert result.returncode == 1
    assert "only_before" in result.stdout and "현재 폴더에 없음" in result.stdout


def test_compare_unknown_scene_or_missing_folder_is_a_usage_error(tmp_path):
    write_scene(tmp_path / "a")
    assert compare(tmp_path / "a", tmp_path / "no_such").returncode == 2
    assert run("capture", "--out", tmp_path / "x", "--scene", "no_such_scene").returncode == 2


def test_compare_notes_a_different_environment_without_failing(tmp_path):
    write_scene(tmp_path / "a")
    write_scene(tmp_path / "b")
    environment = {"python": "3.10.0", "qt": "5.15.14", "pyqt": "5.15.11", "platform": "x", "machine": "x86_64",
                   "style": "fusion", "font": "A 12", "screen": [800, 600, 1.0, 100.0]}
    for folder, qt in (("a", "5.15.14"), ("b", "5.15.19")):
        meta = {"scene": "fake_scene", "environment": {**environment, "qt": qt}, "media_sha256": {"clip": qt}}
        (tmp_path / folder / "fake_scene.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    result = compare(tmp_path / "a", tmp_path / "b")
    assert result.returncode == 0, result.stdout + result.stderr  # 그림·트리가 같으면 통과, 환경은 알리기만
    assert "[주의]" in result.stdout and "qt" in result.stdout and "5.15.19" in result.stdout
    assert "합성 영상 파일이 다름" in result.stdout


def test_compare_limits_the_tree_lines_per_scene(tmp_path):
    many = [node(f"w{i}", text="before") for i in range(5)]
    changed = [node(f"w{i}", text="after") for i in range(5)]
    write_scene(tmp_path / "a", tree=node("root", many))
    write_scene(tmp_path / "b", tree=node("root", changed))
    result = compare(tmp_path / "a", tmp_path / "b", "--max-diff", 2)
    assert result.returncode == 1
    assert "트리: 5곳 다름" in result.stdout and "외 3곳" in result.stdout
    assert result.stdout.count("~ ") == 2


# ---------------------------------------------------------------- 도구 안의 부품 (작은 위젯으로 직접)


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)  # ci/__pycache__에 .pyc를 남기지 않음
    spec = importlib.util.spec_from_file_location("screenshot_check_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "FIXED_WAIT_S", 0.05)  # 작은 위젯이라 짧게
    monkeypatch.setattr(module, "GAP_S", 0.05)
    monkeypatch.setattr(module, "SETTLE_MAX_S", 0.6)
    return module


def test_settle_returns_once_two_consecutive_grabs_match(qapp, tool):
    label = QLabel("고정")
    label.resize(80, 30)
    label.show()
    image, info = tool.settle(qapp, label)
    sip.delete(label)
    assert not image.isNull() and (image.width(), image.height()) == (80, 30)
    assert info["rounds"] == 1 and info["consecutive_identical"] == 2 and info["fixed_wait_s"] == 0.05


def test_settle_fails_loudly_when_the_picture_keeps_changing(qapp, tool):
    label = QLabel("0")
    label.resize(80, 30)
    label.show()
    count = iter(range(10**6))
    timer = QTimer()
    timer.timeout.connect(lambda: label.setText(str(next(count))))  # 글자가 계속 바뀜
    timer.start(5)
    try:
        with pytest.raises(RuntimeError, match=r"정착하지 않음.*x=\d+\.\.\d+ y=\d+\.\.\d+"):
            tool.settle(qapp, label)
    finally:
        timer.stop()
        sip.delete(label)


def test_tree_dump_does_not_depend_on_creation_order(qapp, tool):
    def build(order):
        root = QWidget()
        root.resize(200, 100)
        for name in order:
            label = QLabel(name, root)
            label.setObjectName(name)
            label.setGeometry("abc".index(name) * 50, 0, 40, 20)
        return root

    first, second = build("abc"), build("cba")  # 같은 자리에 만든 차례만 다름
    identity = tool.normalizer("/no/such/work")
    try:
        assert tool.dump_widget(first, identity) == tool.dump_widget(second, identity)
    finally:
        sip.delete(first)
        sip.delete(second)


def test_tree_dump_records_class_name_geometry_visibility_text_and_style_hash(qapp, tool):
    root = QWidget()
    root.resize(200, 100)
    label = QLabel("제목 /no/such/work/media/clip.mp4", root)
    label.setObjectName("title")
    label.setGeometry(5, 6, 70, 20)
    label.setStyleSheet("color: red;")
    try:
        tree = tool.dump_widget(root, tool.normalizer("/no/such/work"))
        (child,) = tree["children"]
        assert (child["class"], child["name"], child["geometry"], child["visible"]) == ("QLabel", "title", [5, 6, 70, 20], False)
        assert child["text"] == "제목 <TMP>/media/clip.mp4"  # 임시 폴더 경로는 고정 문자열로
        assert child["style_sha256"] == hashlib.sha256(b"color: red;").hexdigest()
        assert tree["style_sha256"] == ""  # 스타일시트가 없으면 빈 값
    finally:
        sip.delete(root)


def test_normalizer_hides_values_that_change_every_run(tool):
    normalize = tool.normalizer("/tmp/yc_work")
    assert normalize("ws://127.0.0.1:50321/?token=AbC_123-x 끝") == "ws://127.0.0.1:<PORT>/?token=<TOKEN> 끝"
    assert normalize(["/tmp/yc_work/home", {"k": "/tmp/yc_work/media/a.mp4"}, 3]) == ["<TMP>/home", {"k": "<TMP>/media/a.mp4"}, 3]
