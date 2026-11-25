"""(Mac) 기본 열기 창을 직접 띄우는 `mac_open_panel` — 폴더도 파일도, 파일은 여러 개도 ('폴더 열기' 단추, 2026-11-25).

진짜 창은 띄우지 않음: AppKit 대역(`sys.modules`)으로 창에 넘긴 설정·돌려준 경로·취소를 보고, 진짜 AppKit(Mac — PyObjC)에는 쓰는
이름이 있는지만 물음. Windows 빌드에는 PyObjC가 없으므로 모듈 자체는 AppKit 없이 불려야 함.
"""

import ast
import sys
import types
import unicodedata

import pytest

from yesoncheck import mac_open_panel


class FakePanel:
    """NSOpenPanel 대역: 받은 설정을 적고, 정해 둔 답(확인 1·취소 0)과 고른 URL을 돌려줌. during은 창이 떠 있는 동안 불림."""

    def __init__(self, response, chosen, during=None):
        self.response, self.chosen, self.during = response, chosen, during
        self.calls, self.shown, self.cancelled = {}, 0, 0

    def __getattr__(self, name):
        if not name.startswith("set"):
            raise AttributeError(name)
        return lambda value: self.calls.__setitem__(name, value)

    def runModal(self):  # noqa: N802 (Objective-C 이름)
        self.shown += 1
        if self.during is not None:
            self.during()
        return 0 if self.cancelled else self.response

    def cancel_(self, sender):
        self.cancelled += 1

    def URLs(self):  # noqa: N802
        return [types.SimpleNamespace(path=lambda chosen=chosen: chosen) for chosen in self.chosen]


@pytest.fixture
def appkit(monkeypatch):
    """AppKit 대역을 끼움 → panel(response, chosen, during)로 다음에 뜰 창을 정함."""
    state = types.SimpleNamespace(panel=None)

    def make(response, chosen, during=None):
        state.panel = FakePanel(response, chosen, during)
        return state.panel

    module = types.SimpleNamespace(NSOpenPanel=types.SimpleNamespace(openPanel=lambda: state.panel), NSModalResponseOK=1)
    monkeypatch.setitem(sys.modules, "AppKit", module)
    return make


def test_the_panel_picks_folders_and_several_files(appkit):
    """파일·폴더·여러 개를 모두 켬 — Qt의 QFileDialog로는 '폴더도 파일도'와 '여러 개'를 함께 켤 수 없음(AnyFile은 하나만, ExistingFiles는
    파일만: 2026-11-25 이 Mac에서 창을 띄워 NSOpenPanel의 값으로 확인)."""
    panel = appkit(1, ["/x/a.mov", "/x/b.mov"])

    assert mac_open_panel.pick_folders_or_files("제목") == ["/x/a.mov", "/x/b.mov"]
    assert panel.shown == 1
    assert panel.calls == {"setCanChooseFiles_": True, "setCanChooseDirectories_": True, "setAllowsMultipleSelection_": True,
                           "setMessage_": "제목"}


def test_cancelling_returns_nothing_even_though_the_panel_reports_a_folder(appkit):
    """취소한 창도 URLs에 그때 보던 폴더를 돌려줌(이 Mac에서 확인) — 답을 보지 않고 읽으면 취소가 그 폴더를 불러옴."""
    appkit(0, ["/x/the-folder-it-was-showing"])

    assert mac_open_panel.pick_folders_or_files("제목") == []


def test_paths_come_back_composed_like_the_ones_qt_gives(appkit):
    """한글 이름은 NFC로 — Qt의 기본 창·끌어다 놓기가 주는 경로와 같은 모양 (자모로 풀린 NFD 경로는 NFS 공유에서 다른 이름이고,
    주석 파일 이름도 달라짐). fileURLWithPath로 만든 URL의 path()는 NFC 이름도 NFD로 풀어 줌(이 Mac에서 확인)."""
    decomposed = unicodedata.normalize("NFD", "/x/한글폴더/가나다.mov")
    assert decomposed != unicodedata.normalize("NFC", decomposed)
    appkit(1, [decomposed])

    assert mac_open_panel.pick_folders_or_files("제목") == [unicodedata.normalize("NFC", decomposed)]


def test_a_url_without_a_file_path_is_an_error_not_the_text_none(appkit):
    appkit(1, [None])

    with pytest.raises(ValueError, match="파일 경로"):
        mac_open_panel.pick_folders_or_files("제목")


def test_the_running_panel_can_be_cancelled_from_outside(appkit):
    """다른 창의 업데이트가 이 창을 닫을 때: runModal은 Qt의 대화 상자가 아니라 reject로는 닫히지 않음 — 떠 있는 창을 취소로 닫음."""
    seen = []
    panel = appkit(1, ["/x/a.mov"], during=lambda: seen.append(mac_open_panel.cancel_running()))

    assert mac_open_panel.pick_folders_or_files("제목") == []  # 취소됨: 고른 것을 가져오지 않음

    assert seen == [1] and panel.cancelled == 1
    assert mac_open_panel.cancel_running() == 0  # 닫힌 뒤에는 떠 있는 창이 없음


def test_no_panel_is_left_registered_when_showing_it_fails(appkit):
    def boom():
        raise RuntimeError("창을 띄우지 못함")

    appkit(1, ["/x/a.mov"], during=boom)

    with pytest.raises(RuntimeError):
        mac_open_panel.pick_folders_or_files("제목")
    assert mac_open_panel.cancel_running() == 0


def test_cancelling_with_no_panel_does_nothing():
    assert mac_open_panel.cancel_running() == 0


def test_the_real_open_panel_has_the_methods_this_module_uses():
    """진짜 AppKit(Mac — PyObjC)에서 쓰는 이름이 맞는지: 창을 만들거나 띄우지 않고 클래스에 묻기만 함."""
    AppKit = pytest.importorskip("AppKit", reason="PyObjC의 AppKit은 Mac에만 (Windows 빌드에는 없음)")  # noqa: N806

    for selector in (b"setCanChooseFiles:", b"setCanChooseDirectories:", b"setAllowsMultipleSelection:", b"setMessage:",
                     b"runModal", b"URLs", b"cancel:"):
        assert AppKit.NSOpenPanel.instancesRespondToSelector_(selector), selector
    assert AppKit.NSModalResponseOK == 1


def test_the_module_loads_without_appkit_or_qt():
    """Windows 빌드에는 PyObjC가 없음 — AppKit은 창을 띄우는 함수 안에서만 불러오고, Qt도 쓰지 않음 (맨 위 import만 봄)."""
    tree = ast.parse(open(mac_open_panel.__file__, encoding="utf-8").read())
    top = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = {alias.name.split(".")[0] for node in top if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module.split(".")[0] for node in top if isinstance(node, ast.ImportFrom) and node.module}
    assert names == {"unicodedata"}
