"""가운데 열의 단추 여섯을 둘씩 한 줄로 (2026-11-13).

사용자 요청: "빨간 사각형 안의 버튼 가로 사이즈만 50%씩 줄여서 한 줄로 만들면 중앙패널에 여유가 생길 거 같아 …
OCR 관련 버튼 펼치면 나머지 버튼 내부 항목이 보기 어려워서".
Open Video A | Open Video B · X-Axis Wipe | Y-Axis Wipe · Play Selected | Selected Play — 세 줄이 줄어 가운데 열에
세로 여유가 생긴다(개발 Mac에서 111px). 사용자 결정: 글자는 그대로 두고, 글자가 잘리지 않도록 가운데 열의 처음 폭이
그만큼 넓어진다(개발 Mac 220 → 236px).

둘이 글자째 들어갈 폭이 안 되면 예전처럼 위아래로 놓는다(ButtonPairRow) — 한 줄 배치가 열·창의 최소 폭을 키우지 않게.
글꼴 없는 Windows CI는 글자마다 12px로 재서, 한 줄 배치를 최소 폭으로 삼으면 창의 최소 폭이 900을 넘는다
(test_window_resize — 흉내 측정: 879 → 993).

글꼴은 플랫폼마다 달라 픽셀 숫자가 아니라 관계(같은 줄·같은 폭·글자가 다 들어감·폭이 흔들리지 않음)로 확인한다.
"""

import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication, QPushButton, QStyleFactory, QVBoxLayout, QWidget

from yesoncheck.player_timeline import CollapsibleBox
from yesoncheck.window_layout import ButtonPairRow, SteadyTextButton
from tests.test_window_resize import large_screen  # noqa: F401 (fixture)
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

PAIRS = [("Open Video A", "Open Video B"), ("X-Axis Wipe", "Y-Axis Wipe"), ("Play Selected", "Selected Play")]
PAUSE_STYLE = "background-color: yellow;"  # 선택 재생 중 단추의 시트 (player_playback·sidebar_playlist가 넣는 것)
OLD_START_WIDTH = 220  # 예전 가운데 열의 처음 폭 (스플리터 setSizes)


def settle():
    for _ in range(8):
        QApplication.processEvents()


@pytest.fixture
def player(large_screen, new_player, dialogs, tmp_path):  # noqa: F811
    """처음 켠 모습 — 화면이 충분히 클 때 (offscreen 화면 800×600에서는 글자가 넓은 플랫폼의 열이 처음 폭을 못 받음)."""
    player = new_player(make_config(str(tmp_path), {}))
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


def row_of(left, right):
    row = left.parentWidget()
    assert isinstance(row, ButtonPairRow) and right.parentWidget() is row
    return row


def left_edge(widget, player):
    return widget.mapTo(column(player), widget.rect().topLeft())


def show_pause_label(player):
    """선택 재생 중의 모습: 글자 'Selected Pause' + 노란 시트 (앱이 재생을 시작할 때 하는 그대로)."""
    player.playSelectedPauseButton.setText("Selected Pause")
    player.playSelectedPauseButton.setStyleSheet(PAUSE_STYLE)
    settle()


def set_column_width(player, width):
    sizes = player.mainSplitter.sizes()
    total = sum(sizes)
    player.mainSplitter.setSizes([sizes[0], width, total - sizes[0] - width])
    settle()
    return player.mainSplitter.sizes()[1]


def show_scrollbar(player):
    """창을 낮추고 접는 상자를 펼쳐 가운데 열에 세로 스크롤바가 생기게 (내용 폭이 스크롤바만큼 줄어듦)."""
    player.resize(player.width(), 700)
    settle()
    column(player).findChildren(CollapsibleBox)[-1].toggle_button.click()
    settle()
    assert player.middleScrollArea.verticalScrollBar().isVisible(), "스크롤바가 생기지 않음 (시험 조건이 틀림)"


def side_by_side(left, right):
    return left.y() == right.y()


def assert_side_by_side(left, right, spacing_at_most=8):
    assert left.y() == right.y(), f"{left.text()} · {right.text()}가 다른 줄"
    assert left.height() == right.height()
    gap = right.x() - (left.x() + left.width())
    assert 0 <= gap <= spacing_at_most, f"{left.text()} · {right.text()} 사이 {gap}px"


def assert_stacked(left, right, spacing_at_most=8):
    """예전 모습: 왼쪽 단추가 위, 오른쪽 단추가 바로 아래 — 둘 다 줄의 폭 전체."""
    row = left.parentWidget()
    assert left.x() == right.x() == 0
    assert left.width() == right.width() == row.width()
    gap = right.y() - (left.y() + left.height())
    assert 0 <= gap <= spacing_at_most, f"{left.text()} 아래 {right.text()}까지 {gap}px"


def assert_fits(*buttons):
    for b in buttons:
        assert b.width() >= b.minimumSizeHint().width(), f"{b.text()}: 폭 {b.width()} < 필요한 {b.minimumSizeHint().width()}"
        assert b.height() >= b.minimumSizeHint().height(), f"{b.text()}: 높이 {b.height()} < 필요한 {b.minimumSizeHint().height()}"


# ---- 처음 켠 모습: 둘씩 한 줄 ----

def test_pause_button_starts_with_the_short_label(player):
    """처음 글자도 한 번 쓴 뒤의 글자와 같은 'Selected Play' — 예전 처음 글자 'Play/Pause Selected'는 반 폭에 들어가지 않음."""
    assert player.playSelectedPauseButton.text() == "Selected Play"


def test_each_pair_sits_on_one_row(player):
    for left, right in pairs(player):
        row_of(left, right)
        assert_side_by_side(left, right)


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
    open_a, open_b = button(player, "Open Video A"), button(player, "Open Video B")
    stacked = column(player).layout().itemAt(0).layout()  # 가운데 열에 세로로 쌓은 항목들 (그 아래는 늘어나는 빈칸)
    assert stacked.itemAt(0).widget() is row_of(open_a, open_b)  # 첫 항목이 Open Video 줄
    first_box = stacked.itemAt(1).widget()
    assert isinstance(first_box, CollapsibleBox)
    below = left_edge(first_box, player).y() - (left_edge(open_a, player).y() + open_a.height())
    assert 0 <= below <= 8


def test_every_label_fits(player):
    for left, right in pairs(player):
        assert_fits(left, right)
    show_pause_label(player)
    assert_fits(player.playSelectedPauseButton)


def test_start_width_keeps_the_pairs_when_the_scrollbar_shows(player):
    """처음 폭에서는 세로 스크롤바가 생겨도(내용 폭이 스크롤바만큼 줄어듦) 둘씩 한 줄이고 글자가 잘리지 않음."""
    show_scrollbar(player)
    rows = pairs(player)  # 글자를 바꾸기 전에 찾아 둠 (글자로 찾으므로)
    show_pause_label(player)
    for left, right in rows:
        assert_side_by_side(left, right)
        assert_fits(left, right)
        assert left_edge(right, player).x() + right.width() <= column(player).width()


def test_start_width_is_no_wider_than_the_pairs_need(player):
    """가운데 열의 처음 폭 = max(예전 220, 단추 쌍이 스크롤바가 보여도 한 줄에 들어가는 폭) — 그보다 1px 좁으면 가장 넓은 쌍이 위아래로."""
    area = player.middleScrollArea
    start = player.mainSplitter.sizes()[1]
    assert start == area.width() == max(OLD_START_WIDTH, area.minimumWidth(), area.width_for_content_hint())
    widest = max((row_of(left, right) for left, right in pairs(player)), key=lambda row: row.side_by_side_width())
    chrome = column(player).width() - widest.width()  # 열의 안쪽 여백
    needed = widest.side_by_side_width() + chrome + area.verticalScrollBar().sizeHint().width()
    assert area.width_for_content_hint() == needed  # 가운데 열에서 가장 넓은 것이 단추 쌍
    if needed > OLD_START_WIDTH:
        show_scrollbar(player)
        assert set_column_width(player, start - 1) == start - 1
        left, right = widest.findChildren(QPushButton)
        assert not side_by_side(left, right)


# ---- 좁으면 예전처럼 위아래 ----

def test_pairing_does_not_widen_the_columns_minimum(player):
    """열의 최소 폭은 위아래로 놓았을 때의 것 — 한 줄 배치가 열(과 창)의 최소 폭을 키우지 않음."""
    for left, right in pairs(player):
        row = row_of(left, right)
        assert row.minimumSizeHint().width() == max(left.minimumSizeHint().width(), right.minimumSizeHint().width())
        assert row.sizeHint().width() == row.side_by_side_width() > row.minimumSizeHint().width()
    area = player.middleScrollArea
    assert area.minimumWidth() < area.width_for_content_hint()


def test_narrow_column_stacks_the_pairs_like_before(player):
    """가운데 열을 최소 폭까지 좁히면 글자째 한 줄에 못 들어가는 쌍은 위아래로 — 글자는 어느 쪽이든 잘리지 않음."""
    area = player.middleScrollArea
    assert set_column_width(player, area.minimumWidth()) == area.minimumWidth()
    stacked = 0
    for left, right in pairs(player):
        row = row_of(left, right)
        if row.width() >= row.side_by_side_width():
            assert_side_by_side(left, right)
        else:
            assert_stacked(left, right)
            stacked += 1
        assert_fits(left, right)
    play, pause = button(player, "Play Selected"), player.playSelectedPauseButton
    assert not side_by_side(play, pause), "가장 넓은 쌍은 최소 폭에서 위아래여야 함 (시험 조건)"
    assert stacked >= 1


def test_stacked_pair_pushes_the_rest_down(player):
    """위아래로 놓이면 줄의 높이가 두 단추만큼 — 다음 항목이 아래 단추와 겹치지 않음."""
    area = player.middleScrollArea
    set_column_width(player, area.minimumWidth())
    for left, right in pairs(player):
        row = row_of(left, right)
        if side_by_side(left, right):
            assert row.height() == left.height()
        else:
            assert row.height() >= left.height() + right.height()
            assert right.y() + right.height() <= row.height()
    items = column(player).layout().itemAt(0).layout()
    tops = [items.itemAt(i).geometry() for i in range(items.count())]
    for above, below in zip(tops, tops[1:]):
        assert above.bottom() < below.top(), "줄이 겹침"


def test_widening_the_column_again_pairs_them_back(player):
    area = player.middleScrollArea
    start = player.mainSplitter.sizes()[1]
    set_column_width(player, area.minimumWidth())
    assert not side_by_side(button(player, "Play Selected"), player.playSelectedPauseButton)
    assert set_column_width(player, start) == start
    for left, right in pairs(player):
        assert_side_by_side(left, right)
        assert_fits(left, right)


# ---- 글자가 바뀌어도 흔들리지 않음 ----

def test_column_width_does_not_move_when_the_pause_label_changes(player):
    """재생·멈춤마다 글자가 Selected Play ↔ Selected Pause로 바뀌어도 가운데 열과 단추의 폭이 그대로 (영상 영역이 흔들리지 않음)."""
    pause = player.playSelectedPauseButton
    play = button(player, "Play Selected")

    def snapshot():
        return (player.middleScrollArea.width(), pause.width(), play.width(), player.videoWidget.width(),
                side_by_side(play, pause), column(player).height())

    before = snapshot()
    show_pause_label(player)
    during = snapshot()
    pause.setText("Selected Play")
    pause.setStyleSheet("")
    settle()
    after = snapshot()
    assert before == during == after
    assert before[4] is True


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


# ---- 그 밖 ----

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
    wipe_x, wipe_y = button(player, "X-Axis Wipe"), button(player, "Y-Axis Wipe")
    assert not wipe_x.isEnabled() and not wipe_y.isEnabled()  # 와이프를 켜기 전에는 꺼진 채
    player.wipeCheckBox.setChecked(True)
    assert wipe_x.isEnabled() and wipe_y.isEnabled()
    wipe_x.setChecked(True)
    assert (player.videoWidget.wipe_enabled_x, player.videoWidget.wipe_enabled_y) == (True, False)
    wipe_y.setChecked(True)
    assert (player.videoWidget.wipe_enabled_x, player.videoWidget.wipe_enabled_y) == (True, True)
    player.wipeCheckBox.setChecked(False)  # 끄면 두 단추도 풀리고 꺼짐
    assert not wipe_x.isEnabled() and not wipe_y.isEnabled()
    assert not wipe_x.isChecked() and not wipe_y.isChecked()
    assert (player.videoWidget.wipe_enabled_x, player.videoWidget.wipe_enabled_y) == (False, False)


def test_light_theme_keeps_the_rows(player):
    """밝은 테마로 바꿔도 같은 줄·글자가 다 들어감·폭이 그대로 (테마는 색만 바꿈)."""
    before = (player.middleScrollArea.width(), player.videoWidget.width())
    player.set_light_theme()
    settle()
    for left, right in pairs(player):
        assert_side_by_side(left, right)
        assert_fits(left, right)
    show_pause_label(player)
    assert (player.middleScrollArea.width(), player.videoWidget.width()) == before


def test_hiding_and_showing_the_column_restores_its_width(player):
    """N 키로 가운데 열을 숨겼다 다시 보이면 같은 폭·같은 배치."""
    width = player.middleScrollArea.width()
    for _ in range(2):
        player.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_N, Qt.NoModifier, "n"))
        settle()
    assert not player.middleScrollArea.isHidden()
    assert player.middleScrollArea.width() == width
    for left, right in pairs(player):
        assert_side_by_side(left, right)
        assert_fits(left, right)


# ---- ButtonPairRow 하나만: 폭에 따라 한 줄 ↔ 위아래 ----

SPACING = 5


@pytest.fixture
def lone_row(qapp):
    """단추 쌍 하나만 든 창 — 창의 폭 = 줄의 폭."""
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    left, right = QPushButton("Open the first one"), QPushButton("Close the second one")  # 스타일의 최소 폭 바닥보다 긴 글자
    row = ButtonPairRow(left, right, SPACING)
    layout.addWidget(row)
    layout.addStretch(1)
    host.resize(row.side_by_side_width() + 100, 300)
    host.show()
    settle()
    yield host, row, left, right
    host.close()


def test_row_hints(lone_row):
    host, row, left, right = lone_row
    need = left.minimumSizeHint().width() + SPACING + right.minimumSizeHint().width()
    assert row.side_by_side_width() == need
    assert row.sizeHint().width() == need
    assert row.minimumSizeHint().width() == max(left.minimumSizeHint().width(), right.minimumSizeHint().width()) < need


def test_row_pairs_exactly_when_both_labels_fit(lone_row):
    host, row, left, right = lone_row
    need = row.side_by_side_width()
    assert row.width() == host.width()
    assert_side_by_side(left, right, spacing_at_most=SPACING)
    assert row.height() == left.height()

    host.resize(need, 300)
    settle()
    assert_side_by_side(left, right, spacing_at_most=SPACING)
    assert_fits(left, right)

    host.resize(need - 1, 300)
    settle()
    assert_stacked(left, right, spacing_at_most=SPACING)
    assert_fits(left, right)
    assert row.height() == left.height() + SPACING + right.height()
    assert (row.sizeHint().width(), row.minimumSizeHint().height()) == (need, row.height())  # 원하는 폭은 여전히 한 줄

    host.resize(need, 300)
    settle()
    assert_side_by_side(left, right, spacing_at_most=SPACING)
    assert row.height() == left.height()


def test_row_can_shrink_to_its_widest_button(lone_row):
    host, row, left, right = lone_row
    narrowest = row.minimumSizeHint().width()
    host.resize(1, 300)  # 창의 최소 폭까지만 줄어듦
    settle()
    assert host.width() == row.width() == narrowest
    assert_stacked(left, right, spacing_at_most=SPACING)
    assert_fits(left, right)


def test_row_restacks_when_a_label_grows_without_a_resize(lone_row):
    """줄의 폭은 그대로인데 단추의 글자가 길어져 둘이 못 들어가게 되면 위아래로 (글자가 줄면 다시 한 줄)."""
    host, row, left, right = lone_row
    host.resize(row.side_by_side_width(), 300)
    settle()
    width = row.width()
    assert_side_by_side(left, right, spacing_at_most=SPACING)

    left.setText("Open the first one, please")  # 혼자서는 지금 폭에 들어가지만 둘은 못 들어감
    settle()
    assert left.minimumSizeHint().width() <= width
    assert row.width() == width < row.side_by_side_width()
    assert_stacked(left, right, spacing_at_most=SPACING)
    assert_fits(left, right)

    left.setText("Open the first one")
    settle()
    assert_side_by_side(left, right, spacing_at_most=SPACING)



# ---- SteadyTextButton: 어느 스타일에서든 '가장 넓은 글자를 넣은 보통 단추'의 폭 ----

@pytest.fixture
def fusion(qapp):
    style = QStyleFactory.create("Fusion")  # 글자 있는 단추의 폭에 바닥(80px)이 있는 스타일 — 플랫폼과 무관하게 같은 규칙
    assert style is not None
    return style


def plain_hint(text, style, sheet):
    plain = QPushButton(text)
    plain.setStyle(style)
    plain.setStyleSheet(sheet)
    return plain.sizeHint().width()


@pytest.mark.parametrize("sheet", ["", "QPushButton { padding: 3px 9px; border: 1px solid gray; }"])
@pytest.mark.parametrize("current, texts", [
    ("Play", ("Play", "Pause long")),        # 짧은 글자가 스타일의 최소 폭 바닥에 걸림 — 바닥 위에 차이를 얹으면 틀림
    ("Pause long", ("Play", "Pause long")),
    ("OK", ("OK", "No")),                    # 둘 다 바닥 아래
    ("", ("A&B", "Selected Pause")),         # 빈 글자는 Qt가 'XXXX'로 잼, &는 단축키 표시
    ("Selected Play", ("Selected Play", "Selected Pause")),
])
def test_steady_button_asks_for_the_widest_plain_button_width(fusion, sheet, current, texts):
    steady = SteadyTextButton(current, texts)
    steady.setStyle(fusion)
    steady.setStyleSheet(sheet)
    expected = max(plain_hint(text, fusion, sheet) for text in (current,) + tuple(texts))
    assert steady.sizeHint().width() == expected
    assert steady.minimumSizeHint().width() == expected
    assert steady.sizeHint().height() == QPushButton.sizeHint(steady).height()
    for text in texts:  # 글자를 바꿔도 그대로
        steady.setText(text)
        assert steady.sizeHint().width() == expected


def test_steady_button_refuses_texts_that_are_not_strings(qapp):
    """글자가 아닌 값은 만들 때 거절 — 크기 힌트(가상 함수) 안에서 터지면 PyQt5가 프로세스를 끝냄."""
    with pytest.raises(TypeError):
        SteadyTextButton("Play", ("Play", None))
