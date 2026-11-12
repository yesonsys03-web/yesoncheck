"""메인 창 테마 스타일시트 고정 시험: 스타일시트를 상수로 빼거나 다른 모듈로 옮겨도 글자 하나 바뀌지 않아야 함.

창의 `styleSheet()` 문자열 전체의 sha256과 글자 수를 박아 둔다. 코드 구조가 아니라 창에 실제로 걸리는 결과를 보므로
스타일시트를 어디에 두든(`player_base` 안의 문자열, 모듈 상수, 별도 모듈) 그대로 유효하다. 일부러 시트를 고칠 때는
이 값을 새 시트의 값으로 바꾸고 이유를 커밋에 남긴다.
"""

import hashlib

import pytest

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)


# 2026-11-12 (밝은 테마에 어두운 테마가 섞임 — tests/test_light_theme.py): 두 시트에 접는 상자 머리의 색 규칙(QPushButton#collapsibleToggle
# — 어두운 쪽은 위젯에 직접 넣던 색 그대로)을 더하고, 밝은 시트는 QMainWindow 규칙을 QWidget 규칙 뒤로 옮김(그 옮김은 글자 수 그대로)
DARK_SHA256 = "d07dce1e05f40622f83cc2859f1b3aea46d3fcd478ca121ae885cbae8c5cddb8"  # 어두운 시트, 3,519자
LIGHT_SHA256 = "70252c0fc4e5d2b6dfe8d4bf44c234839db64d37adf9b9a9da0211e11285cf19"  # 밝은 시트, 4,443자
DARK_LENGTH = 3519
LIGHT_LENGTH = 4443


def sha256_of(sheet):
    return hashlib.sha256(sheet.encode("utf-8")).hexdigest()


@pytest.fixture
def window(new_player, dialogs, tmp_path):
    """시트를 아무것도 건드리지 않은, 막 만든 메인 창."""
    player = new_player(make_config(str(tmp_path), {}))
    yield player
    assert dialogs.errors() == []


def test_dark_sheet_identical_both_paths(window):
    """어두운 시트는 두 경로(① 창을 만들 때 처음 걸리는 것, ② set_dark_theme가 다시 거는 것)에서 글자까지 같다."""
    first = window.styleSheet()
    assert len(first) == DARK_LENGTH
    assert sha256_of(first) == DARK_SHA256

    window.setStyleSheet("")  # 처음 것을 지워 set_dark_theme의 것만 남김
    assert window.styleSheet() == ""
    window.set_dark_theme()
    again = window.styleSheet()
    assert len(again) == DARK_LENGTH
    assert sha256_of(again) == DARK_SHA256
    assert again == first


def test_light_sheet_frozen(window):
    """밝은 시트(set_light_theme)가 글자 하나 바뀌지 않았다."""
    window.set_light_theme()
    sheet = window.styleSheet()
    assert len(sheet) == LIGHT_LENGTH
    assert sha256_of(sheet) == LIGHT_SHA256
