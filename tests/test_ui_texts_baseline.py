"""한국어 화면의 글자가 그대로인지 (UI 개편 PR 3 '언어 고르기').

메인 창의 글자를 글자 표(`ui_text`)로 옮기는 동안 한국어 화면은 글자 하나 달라지면 안 된다. 옮기기 전에 모아 적어 둔 것
(`tests/data/main_window_texts_ko.json`)과 지금 모은 것(`tests/ui_texts.collect`)을 견준다.

기준 파일은 Mac에서 적었다 — 메뉴가 플랫폼마다 달라(재생 디코더는 Mac만, 화면 그리기·축소 필터는 Windows만, QuickTime 항목은
Mac만) 견주기는 Mac에서만 한다. Windows 전용 메뉴의 글은 그 메뉴의 시험이 따로 본다.

화면 글자를 일부러 바꿨을 때(새 메뉴 항목 등)만 다시 적는다: `pytest tests/test_ui_texts_baseline.py --write-ui-texts` 뒤
`git diff tests/data/main_window_texts_ko.json`으로 **바꾸려던 것만 달라졌는지** 본다.
"""

import json
import os
import sys

import pytest

from tests import ui_texts
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

BASELINE = os.path.join(os.path.dirname(__file__), "data", "main_window_texts_ko.json")


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path / "config"), {}))


def test_collect_covers_every_area(player, tmp_path):
    ui_texts.stage(player, tmp_path)
    texts = ui_texts.collect(player)
    assert tuple(texts) == ui_texts.AREAS
    assert [area for area in ui_texts.AREAS if not texts[area]] == []
    assert not any("<tmp>" not in text and str(tmp_path) in text for area in texts for text in texts[area])


def test_collecting_twice_gives_the_same_texts(player, tmp_path):
    """모으는 일이 화면을 바꾸지 않음(차례로 만들어 본 모양을 되돌림) — 안 그러면 '언어를 바꿨다 되돌리면 같다'를 볼 수 없음."""
    ui_texts.stage(player, tmp_path)
    assert ui_texts.collect(player) == ui_texts.collect(player)


@pytest.mark.skipif(sys.platform != "darwin", reason="기준 파일은 Mac의 메뉴로 적음 (플랫폼 전용 메뉴가 서로 다름)")
def test_korean_screen_matches_the_recorded_texts(player, tmp_path, request):
    ui_texts.stage(player, tmp_path)
    texts = ui_texts.collect(player)
    if request.config.getoption("--write-ui-texts"):
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        with open(BASELINE, "w", encoding="utf-8") as fh:
            json.dump(texts, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        return
    with open(BASELINE, encoding="utf-8") as fh:
        recorded = json.load(fh)
    changed = {area: (recorded.get(area), texts[area]) for area in ui_texts.AREAS if recorded.get(area) != texts[area]}
    assert changed == {}, "한국어 화면의 글자가 기준과 다름 (영역: 기준, 지금)"
