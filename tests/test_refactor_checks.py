"""리팩토링 검증 도구(tools/refactor_checks): 결합 비교(mixin_coupling)와 전역 이름 점검(runtime_globals).

실제 저장소로는 '자기 자신과 같다·지운 메서드를 잡는다·풀리지 않는 전역 이름이 없다'를 확인하고,
작은 가짜 패키지로는 '메서드를 다른 믹스인으로 옮기기만 하면 차이가 없다·본문이 바뀌면 잡힌다·워커 같은 플레이어 밖 클래스의
구조(메서드 소속·시그널·기반 클래스)와 모듈 상수 값이 바뀌면 잡히고 클래스·상수를 다른 파일로 옮기기만 하면 차이가 없다·허용
목록(--allow)이 정확히 맞아야만 통과하고 접두 이름이 비슷한 다른 항목은 허용하지 않는다·풀리지 않는 전역 이름이 있으면 실패한다'를
확인한다. 도구는 모두 하위 프로세스로 돌려 종료 코드를 본다."""

import json
import os
import subprocess
import sys

import pytest

from tests.conftest import ROOT

COUPLING = os.path.join(ROOT, "tools", "refactor_checks", "mixin_coupling.py")
GLOBALS = os.path.join(ROOT, "tools", "refactor_checks", "runtime_globals.py")


def run(script, *args):
    # 도구가 어떤 예외로 죽어도 종료 코드는 1이므로(차이 있음과 같은 값), 호출하는 쪽이 출력까지 확인할 수 있게 문자열로 받음.
    # 한글 출력이 Windows 파이프의 기본 인코딩에 걸리지 않게 UTF-8로 고정
    env = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, script, *map(str, args)], capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=env
    )


# ---------------------------------------------------------------- 실제 저장소


def test_snapshot_then_compare_self_is_identical(tmp_path):
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    assert run(COUPLING, "snapshot", "-o", first).returncode == 0
    assert run(COUPLING, "snapshot", "-o", second).returncode == 0
    # 같은 작업 트리에서 뜬 스냅샷은 바이트까지 같아야 함 (집합 순서 등 실행마다 달라지는 값이 없음)
    assert first.read_bytes() == second.read_bytes()

    result = run(COUPLING, "compare", "--baseline", first)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "차이 없음" in result.stdout


def test_snapshot_records_classes_mro_and_super_targets(tmp_path):
    out = tmp_path / "snap.json"
    assert run(COUPLING, "snapshot", "-o", out).returncode == 0
    snap = json.loads(out.read_text(encoding="utf-8"))

    # 클래스별 메서드 목록·self 속성 읽기/쓰기 (메서드를 어느 믹스인으로 옮겨도 성립하도록 클래스 전체에서 봄)
    classes = snap["classes"]
    assert classes["base"]["class"] == "VideoPlayerBase"
    assert any("closeEvent" in c["members"] for c in classes.values())
    assert any(c["stores"] for c in classes.values()) and any(c["loads"] for c in classes.values())
    # MRO — VideoPlayer가 믹스인을 이 차례로 상속하고, 맨 끝은 Qt 기반 클래스
    mro = snap["normalized"]["mro"]
    assert mro["VideoPlayer"][0] == "VideoPlayer" and "VideoPlayerBase" in mro["VideoPlayer"]
    assert mro["VideoPlayer"][-1] == "QMainWindow"
    assert mro["VideoPlayerBase"][0] == "VideoPlayerBase"
    # 메서드별 super() 대상
    assert snap["normalized"]["super_targets"] and snap["normalized"]["super_calls"]


def test_compare_detects_removed_method(tmp_path):
    out = tmp_path / "snap.json"
    assert run(COUPLING, "snapshot", "-o", out).returncode == 0
    snap = json.loads(out.read_text(encoding="utf-8"))
    removed = sorted(snap["normalized"]["effective_members"])[0]
    del snap["normalized"]["effective_members"][removed]  # 지금 코드에는 있는 메서드가 baseline에는 없는 상태
    fake = tmp_path / "fake_baseline.json"
    fake.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")

    result = run(COUPLING, "compare", "--baseline", fake)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr  # 도구가 죽어서 1이 된 것이 아님
    assert f"effective_members ~ {removed}:" in result.stdout
    assert "차이 없음" not in result.stdout


def test_runtime_globals_clean():
    result = run(GLOBALS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "unresolved: 0" in result.stdout
    # 아무것도 보지 않고 0이 나온 것이 아님 (수백 개 함수를 훑음)
    functions = int(result.stdout.split("functions:")[1].split()[0])
    assert functions > 500, result.stdout


# ---------------------------------------------------------------- 작은 가짜 패키지

FILES = {
    "__init__.py": "",
    "main_window.py": (
        "from .player_base import VideoPlayerBase\n"
        "from .player_sidebar import PlayerSidebarMixin\n\n\n"
        "class VideoPlayer(PlayerSidebarMixin, VideoPlayerBase):\n    pass\n"
    ),
    "player_base.py": (
        "import os\n\n\n"
        "class VideoPlayerBase:\n"
        "    def __init__(self):\n        self.count = 0\n\n"
        "    def helper(self):\n        return self.count + 1\n\n"
        "    def moved_candidate(self):\n        return os.sep + str(self.helper())\n\n"
        "    def close(self):\n        return 'base'\n"
    ),
    "player_sidebar.py": (
        "class PlayerSidebarMixin:\n"
        "    def refresh(self):\n        return self.helper()\n\n"
        "    def close(self):\n        return super().close()\n"
    ),
    "player_review.py": "class OCRTimelineWidget:\n    pass\n\n\nclass OCRReviewDialog:\n    pass\n",
    # 플레이어 밖 클래스(워커)와 모듈 상수 — Qt 대신 같은 이름의 작은 대역을 둠
    "workers.py": (
        "EXIT_WAIT_S = 30\n\n\n"
        "def pyqtSignal(*types):\n    return types\n\n\n"
        "class QObject:\n    pass\n\n\n"
        "class QThread(QObject):\n    pass\n\n\n"
        "class WorkerA(QThread):\n"
        "    done = pyqtSignal(int)\n\n"
        "    def run(self):\n        return 1\n\n"
        "    def stop(self):\n        return 2\n\n\n"
        "class WorkerB(QThread):\n    def run(self):\n        return 3\n"
    ),
}


def make_package(root, **overrides):
    """root/yesoncheck/에 가짜 패키지를 만든다 (overrides: 파일 이름 → 내용으로 FILES를 바꿔 끼움). 도구에 줄 root를 돌려줌."""
    for name, text in {**FILES, **overrides}.items():
        path = root / "yesoncheck" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def baseline_of(root, tmp_path):
    out = tmp_path / "baseline.json"
    result = run(COUPLING, "snapshot", "--root", root, "-o", out)
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def test_moving_a_method_between_mixins_is_not_a_difference(tmp_path):
    before = make_package(tmp_path / "before")
    moved_text = FILES["player_base.py"].replace(
        "    def moved_candidate(self):\n        return os.sep + str(self.helper())\n\n", ""
    )
    sidebar_text = "import os\n\n\n" + FILES["player_sidebar.py"] + (
        "\n    def moved_candidate(self):\n        return os.sep + str(self.helper())\n"
    )
    after = make_package(tmp_path / "after", **{"player_base.py": moved_text, "player_sidebar.py": sidebar_text})
    assert "moved_candidate" not in (after / "yesoncheck" / "player_base.py").read_text(encoding="utf-8")

    result = run(COUPLING, "compare", "--baseline", baseline_of(before, tmp_path), "--root", after)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "차이 없음" in result.stdout


def test_changed_body_and_super_target_are_reported(tmp_path):
    before = make_package(tmp_path / "before")
    # sidebar의 close()가 base 대신 새 믹스인 쪽을 거치도록 MRO를 바꾸면 super() 대상(과 MRO)이 달라짐
    new_main = (
        "from .player_base import VideoPlayerBase\n"
        "from .player_sidebar import PlayerSidebarMixin\n\n\n"
        "class Shadow:\n    def close(self):\n        return 'shadow'\n\n\n"
        "class VideoPlayer(PlayerSidebarMixin, Shadow, VideoPlayerBase):\n    pass\n"
    )
    after = make_package(tmp_path / "after", **{"main_window.py": new_main})
    result = run(COUPLING, "compare", "--baseline", baseline_of(before, tmp_path), "--root", after)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "[다름] mro" in result.stdout
    assert "[다름] super_targets" in result.stdout


def changed_helper_package(root):
    changed = FILES["player_base.py"].replace("self.count + 1", "self.count + 2")
    return make_package(root, **{"player_base.py": changed})


def test_changed_method_body_is_reported(tmp_path):
    before = make_package(tmp_path / "before")
    after = changed_helper_package(tmp_path / "after")
    result = run(COUPLING, "compare", "--baseline", baseline_of(before, tmp_path), "--root", after)
    assert result.returncode == 1
    assert "effective_members ~ helper:" in result.stdout
    assert "player_base.py:VideoPlayerBase.helper" in result.stdout  # 함수 본문 목록에는 어느 함수였는지가 붙음


# 이름은 양쪽을 닫아 쓴다: `~ 이름:` / `:클래스.이름"` (이름 뒤를 열어 두면 접두 이름이 같은 다른 항목까지 허용됨)
ALLOW = """\
# helper의 본문만 바뀌는 작업
effective_members ~ helper: *
function_bodies - *:VideoPlayerBase.helper"*
function_bodies + *:VideoPlayerBase.helper"*
"""


def test_allow_file_accepts_exactly_the_expected_differences(tmp_path):
    baseline = baseline_of(make_package(tmp_path / "before"), tmp_path)
    after = changed_helper_package(tmp_path / "after")

    allow = tmp_path / "allow.txt"
    allow.write_text(ALLOW, encoding="utf-8")
    ok = run(COUPLING, "compare", "--baseline", baseline, "--allow", allow, "--root", after)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "허용된 차이만" in ok.stdout and "차이 없음" not in ok.stdout
    assert "허용 줄별 맞은 차이 수:" in ok.stdout and '  1  function_bodies - *:VideoPlayerBase.helper"*' in ok.stdout

    # 허용 목록에 없는 차이가 하나라도 남으면 실패
    one_short = ALLOW.replace('function_bodies + *:VideoPlayerBase.helper"*\n', "")
    assert one_short != ALLOW
    allow.write_text(one_short, encoding="utf-8")
    missing = run(COUPLING, "compare", "--baseline", baseline, "--allow", allow, "--root", after)
    assert missing.returncode == 1
    assert "허용되지 않은 차이" in missing.stdout

    # 허용했는데 나타나지 않은 차이(예상이 빗나감)도 실패
    allow.write_text(ALLOW + "effective_members ~ refresh: *\n", encoding="utf-8")
    unused = run(COUPLING, "compare", "--baseline", baseline, "--allow", allow, "--root", after)
    assert unused.returncode == 1
    assert "나타나지 않은 허용" in unused.stdout and "refresh" in unused.stdout


def sidebar_with_thumbnails(first, second):
    return (
        "class PlayerSidebarMixin:\n"
        "    def refresh(self):\n        return self.helper()\n\n"
        f"    def generate_thumbnail(self):\n        return {first}\n\n"
        f"    def generate_thumbnails_for_all_items(self):\n        return {second}\n\n"
        "    def close(self):\n        return super().close()\n"
    )


def test_allow_does_not_cover_other_items_with_a_similar_prefix(tmp_path):
    baseline = baseline_of(make_package(tmp_path / "before", **{"player_sidebar.py": sidebar_with_thumbnails(1, 2)}), tmp_path)
    after = make_package(tmp_path / "after", **{"player_sidebar.py": sidebar_with_thumbnails(10, 20)})
    allow = tmp_path / "allow.txt"

    # 닫힌 모양: generate_thumbnail만 허용하고 generate_thumbnails_for_all_items의 차이 3줄은 허용되지 않음
    allow.write_text(
        'effective_members ~ generate_thumbnail: *\n'
        'function_bodies - *:PlayerSidebarMixin.generate_thumbnail"*\n'
        'function_bodies + *:PlayerSidebarMixin.generate_thumbnail"*\n',
        encoding="utf-8",
    )
    closed = run(COUPLING, "compare", "--baseline", baseline, "--allow", allow, "--root", after)
    assert closed.returncode == 1
    assert "허용되지 않은 차이 3개" in closed.stdout
    assert "\n    effective_members ~ generate_thumbnails_for_all_items:" in closed.stdout  # (허용) 표시가 없음
    assert "  1  effective_members ~ generate_thumbnail: *" in closed.stdout  # 맞은 줄 수가 1

    # 열린 모양은 둘 다 허용해 통과하지만, 줄별 맞은 수가 2로 보여 느슨함을 알 수 있음
    allow.write_text(
        "effective_members ~ generate_thumbnail*\n"
        "function_bodies - *PlayerSidebarMixin.generate_thumbnail*\n"
        "function_bodies + *PlayerSidebarMixin.generate_thumbnail*\n",
        encoding="utf-8",
    )
    loose = run(COUPLING, "compare", "--baseline", baseline, "--allow", allow, "--root", after)
    assert loose.returncode == 0, loose.stdout + loose.stderr
    assert "  2  effective_members ~ generate_thumbnail*" in loose.stdout


def worker_variant(replacements=(), append=""):
    text = FILES["workers.py"]
    for old, new in replacements:
        assert old in text, old
        text = text.replace(old, new)
    return text + append


STOP = "\n    def stop(self):\n        return 2\n"
WORKER_B = "class WorkerB(QThread):\n    def run(self):\n        return 3\n"
WORKER_CHANGES = {
    # 워커 클래스 사이로 메서드를 옮김 — 함수 본문 해시는 그대로라 class_decls만 봄
    "method_moved_to_other_worker": (
        worker_variant([(STOP, ""), (WORKER_B, WORKER_B + STOP)]),
        ["class_decls ~ WorkerA:", "class_decls ~ WorkerB:", "[같음] function_bodies"],
    ),
    # 워커 메서드를 모듈 함수로 내림 — 본문 해시는 그대로
    "method_demoted_to_module_function": (
        worker_variant([(STOP, "")], "\n\ndef stop(self):\n    return 2\n"),
        ["class_decls ~ WorkerA:", "[같음] function_bodies"],
    ),
    "signal_signature_changed": (
        worker_variant([("pyqtSignal(int)", "pyqtSignal(str)")]),
        ["class_decls ~ WorkerA:", "pyqtSignal(str)"],
    ),
    "base_class_changed": (
        worker_variant([("class WorkerA(QThread):", "class WorkerA(QObject):")]),
        ["class_decls ~ WorkerA:", "QObject"],
    ),
    "module_constant_changed": (
        worker_variant([("EXIT_WAIT_S = 30", "EXIT_WAIT_S = 31")]),
        ["module_constants ~ EXIT_WAIT_S:"],
    ),
}


@pytest.mark.parametrize("change", sorted(WORKER_CHANGES))
def test_structure_changes_outside_the_player_are_reported(tmp_path, change):
    workers, expected = WORKER_CHANGES[change]
    baseline = baseline_of(make_package(tmp_path / "before"), tmp_path)
    after = make_package(tmp_path / "after", **{"workers.py": workers})
    result = run(COUPLING, "compare", "--baseline", baseline, "--root", after)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    for text in expected:
        assert text in result.stdout, (text, result.stdout)


def test_moving_a_class_or_constant_to_another_module_is_not_a_difference(tmp_path):
    with_constant = FILES["workers.py"] + "\n\nMOVED_CONSTANT = 5\n"
    baseline = baseline_of(make_package(tmp_path / "before", **{"workers.py": with_constant}), tmp_path)
    after = make_package(
        tmp_path / "after",
        **{
            "workers.py": FILES["workers.py"].replace("\n\n" + WORKER_B, "\n"),
            "workers_extra.py": "from .workers import QThread\n\n\n" + WORKER_B + "\n\nMOVED_CONSTANT = 5\n",
        },
    )
    assert "WorkerB" not in (after / "yesoncheck" / "workers.py").read_text(encoding="utf-8")
    result = run(COUPLING, "compare", "--baseline", baseline, "--root", after)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "차이 없음" in result.stdout


def test_runtime_globals_reports_unresolved_name(tmp_path):
    root = make_package(tmp_path / "pkg")
    (root / "yesoncheck" / "leaf.py").write_text(
        "import os\n\n\n"
        "def fine():\n    return os.sep\n\n\n"
        "class Holder:\n"
        "    def broken(self):\n        return [missing_name for _ in range(1)]\n",  # 컴프리헨션 안의 이름도 잡아야 함
        encoding="utf-8",
    )
    result = run(GLOBALS, "--root", root)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "yesoncheck.leaf.Holder.broken" in result.stdout and "missing_name" in result.stdout
    assert "unresolved: 1" in result.stdout

    # 그 이름을 정의하면 깨끗해짐
    (root / "yesoncheck" / "leaf.py").write_text(
        "missing_name = 1\n\n\nclass Holder:\n    def broken(self):\n        return [missing_name for _ in range(1)]\n",
        encoding="utf-8",
    )
    fixed = run(GLOBALS, "--root", root)
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "unresolved: 0" in fixed.stdout
