"""가운데 열의 단추 여섯을 둘씩 한 줄로 (2026-11-13).

사용자 요청: "빨간 사각형 안의 버튼 가로 사이즈만 50%씩 줄여서 한 줄로 만들면 중앙패널에 여유가 생길 거 같아 …
OCR 관련 버튼 펼치면 나머지 버튼 내부 항목이 보기 어려워서".
Open Video A | Open Video B · X-Axis Wipe | Y-Axis Wipe · Play Selected | Selected Play — 세 줄이 줄어 가운데 열에
세로 여유가 생긴다(개발 Mac에서 111px). 사용자 결정: 글자는 그대로 두고, 글자가 잘리지 않도록 가운데 열이 그만큼
넓어진다(개발 Mac 220 → 236px).

글꼴은 플랫폼마다 달라 픽셀 숫자가 아니라 관계(같은 줄·같은 폭·글자가 다 들어감·폭이 흔들리지 않음)로 확인한다.
"""

import pytest
from PyQt5.QtWidgets import QApplication, QPushButton

from yesoncheck.player_timeline import CollapsibleBox
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

PAIRS = [("Open Video A", "Open Video B"), ("X-Axis Wipe", "Y-Axis Wipe"), ("Play Selected", "Selected Play")]
PAUSE_STYLE = "background-color: yellow;"  # 선택 재생 중 단추의 시트 (player_playback·sidebar_playlist가 넣는 것)


def settle():
    for _ in range(5):
        QApplication.processEvents()


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    player = new_player(make_config(str(tmp_path), {}))
    player.resize(1440, 900)
    player.show()
    settle()
    return player


def column(player):
    return player.middleScrollArea.widget()


def button(player, text):
    found = [b for b in column(player).findChildren(QPushButton) if b.text() == text]
    assert len(found) == 1, f"'{text}' 단추가 {len(found)}개"
    return found[0]


def pairs(player):
    return [(button(player, left), button(player, right)) for left, right in PAIRS]


def left_edge(widget, player):
    return widget.mapTo(column(player), widget.rect().topLeft())


def show_pause_label(player):
    """선택 재생 중의 모습: 글자 'Selected Pause' + 노란 시트 (앱이 재생을 시작할 때 하는 그대로)."""
    player.playSelectedPauseButton.setText("Selected Pause")
    player.playSelectedPauseButton.setStyleSheet(PAUSE_STYLE)
    settle()


def test_pause_button_starts_with_the_short_label(player):
    """처음 글자도 한 번 쓴 뒤의 글자와 같은 'Selected Play' — 예전 처음 글자 'Play/Pause Selected'는 반 폭에 들어가지 않음."""
    assert player.playSelectedPauseButton.text() == "Selected Play"


def test_each_pair_sits_on_one_row(player):
    for left, right in pairs(player):
        a, b = left_edge(left, player), left_edge(right, player)
        assert a.y() == b.y(), f"{left.text()} · {right.text()}가 다른 줄"
        assert left.height() == right.height()
        gap = b.x() - (a.x() + left.width())
        assert 0 <= gap <= 8, f"{left.text()} · {right.text()} 사이 {gap}px"


def test_pair_buttons_share_the_row_equally(player):
    for left, right in pairs(player):
        assert abs(left.width() - right.width()) <= 1, f"{left.text()} {left.width()} · {right.text()} {right.width()}"


def test_rows_span_the_same_width_as_the_other_controls(player):
    """둘을 합친 줄은 한 줄짜리 위젯(콤보 상자)과 왼쪽·오른쪽 끝이 같음."""
    combo = player.frameRateComboBox
    start = left_edge(combo, player).x()
    end = start + combo.width()
    for left, right in pairs(player):
        assert left_edge(left, player).x() == start
        assert abs(left_edge(right, player).x() + right.width() - end) <= 1


def test_rows_follow_each_other_without_a_gap_row(player):
    """Open Video 줄 바로 아래가 첫 접는 상자 (B가 차지하던 줄이 없어짐)."""
    open_a = button(player, "Open Video A")
    first_box = column(player).findChildren(CollapsibleBox)[0]
    below = left_edge(first_box, player).y() - (left_edge(open_a, player).y() + open_a.height())
    assert 0 <= below <= 8


def test_every_label_fits(player):
    for left, right in pairs(player):
        for b in (left, right):
            assert b.width() >= b.minimumSizeHint().width(), f"{b.text()}: 폭 {b.width()} < 필요한 {b.minimumSizeHint().width()}"
    show_pause_label(player)
    pause = player.playSelectedPauseButton
    assert pause.width() >= pause.minimumSizeHint().width()


def test_every_label_fits_when_the_scrollbar_shows(player):
    """접는 상자를 펼쳐 세로 스크롤바가 생겨도(가운데 열의 내용 폭이 스크롤바만큼 줄어듦) 글자가 잘리지 않음."""
    player.resize(1440, 700)
    settle()
    annotation_box = column(player).findChildren(CollapsibleBox)[-1]
    annotation_box.toggle_button.click()
    settle()
    assert player.middleScrollArea.verticalScrollBar().isVisible(), "스크롤바가 생기지 않음 (시험 조건이 틀림)"
    rows = pairs(player)  # 글자를 바꾸기 전에 찾아 둠 (글자로 찾으므로)
    show_pause_label(player)
    for left, right in rows:
        for b in (left, right):
            assert b.width() >= b.minimumSizeHint().width(), f"{b.text()}: 폭 {b.width()} < 필요한 {b.minimumSizeHint().width()}"
        assert left_edge(right, player).x() + right.width() <= column(player).width()


def test_column_width_does_not_move_when_the_pause_label_changes(player):
    """재생·멈춤마다 글자가 Selected Play ↔ Selected Pause로 바뀌어도 가운데 열과 단추의 폭이 그대로 (영상 영역이 흔들리지 않음)."""
    pause = player.playSelectedPauseButton
    play = button(player, "Play Selected")
    before = (player.middleScrollArea.width(), pause.width(), play.width(), player.videoWidget.width())
    show_pause_label(player)
    during = (player.middleScrollArea.width(), pause.width(), play.width(), player.videoWidget.width())
    pause.setText("Selected Play")
    pause.setStyleSheet("")
    settle()
    after = (player.middleScrollArea.width(), pause.width(), play.width(), player.videoWidget.width())
    assert before == during == after


def test_pause_button_asks_for_the_same_width_in_both_states(player):
    """크기 힌트·최소 힌트가 두 글자에서 같고, 넓은 글자('Selected Pause')를 보통 단추에 넣었을 때의 폭과 같음."""
    pause = player.playSelectedPauseButton
    idle = (pause.sizeHint().width(), pause.minimumSizeHint().width())
    plain_idle = QPushButton.sizeHint(pause).width()
    show_pause_label(player)
    playing = (pause.sizeHint().width(), pause.minimumSizeHint().width())
    plain_playing = QPushButton.sizeHint(pause).width()  # 보통 QPushButton이 이 글자에 바라는 폭
    assert idle == playing == (plain_playing, plain_playing)
    assert plain_idle < plain_playing  # 짧은 글자만 보면 더 좁았을 것 — 넓은 쪽에 맞춘 것


def test_buttons_still_do_their_jobs(player, monkeypatch):
    """자리만 바뀌고 누르면 하는 일은 그대로."""
    opened = []
    monkeypatch.setattr(player, "open_file", lambda side, path=None: opened.append(side))
    button(player, "Open Video A").click()
    button(player, "Open Video B").click()
    assert opened == ["A", "B"]
    # 선택 재생 단추 둘은 만들 때의 메서드에 바로 이어져 있어 바꿔치기가 닿지 않음 — 이어져 있는지만 봄
    play = button(player, "Play Selected")
    pause = player.playSelectedPauseButton
    assert play.receivers(play.clicked) >= 1
    assert pause.receivers(pause.clicked) >= 1
    assert not button(player, "X-Axis Wipe").isEnabled() and not button(player, "Y-Axis Wipe").isEnabled()  # 와이프를 켜기 전에는 꺼진 채
