"""슬라이더 호버 썸네일을 플레이어에 잇는 믹스인 (yesoncheck/player_hover_thumbs.py) — 열기·쉬는 때·놓기·닫기·실패 알림.

실제 VideoPlayer를 offscreen으로 띄워 번호 클립(tests/prores_clips — 프레임 i의 그림이 번호 i를 실음, 320×180이라 띠 그림도 축소 없이
번호가 그대로 읽힘)을 A로 연다. ProRes는 conftest의 기본값(네이티브 off·캐시 ring)이라 ffmpeg 파이프 캡처, mp4는 cv2 캡처로 열린다.

호버는 offscreen 하네스라 QTest.mouseMove 대신 이벤트를 직접 만들어 QApplication.sendEvent로 보낸다 (test_slider_preview와 같은 방법 —
Enter는 QEnterEvent로: 필터가 Enter의 pos()를 읽으므로 맨 QEvent(Enter)는 쓰지 않음). 띠 워커는 두 가지로 본다:
- 진짜 워커(HoverStripBuilder — 진짜 ffmpeg): 모든 시험에서 만든 것을 기록해(real_builders, autouse) 시험이 끝나 창이 닫힌 뒤 스레드가
  끝났고 ffmpeg 프로세스가 남지 않았는지 늘 확인한다.
- 대역(FakeBuilder — fake_builders): 띄운 횟수·paused 값·신호를 시험이 정할 때 (프로세스 없음).
둘 다 hover_strip_builder 모듈의 이름을 바꿔치기한다 (믹스인이 그 모듈에서 이름을 읽음).
"""

import os
import time

import cv2
import numpy as np
import psutil
import pytest
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QPoint, QPointF, Qt, pyqtSignal
from PyQt5.QtGui import QEnterEvent, QImage, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from tests.conftest import write_test_video
from tests.prores_clips import frame_number, make_numbered_clip
from tests.test_sequence_capture import make_seq
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import error_window, external_tools, hover_strip, hover_strip_builder
from yesoncheck.hover_strip import LOG_PREFIX, MENU_TEXT
from yesoncheck.slider_preview import slider_value_at

CLIP_COUNT = 48
SECOND_COUNT = 24
WAIT_S = 20  # 띠 하나(320×180 48장)를 만드는 데 넉넉히 — 실제는 1초 안쪽


# ---------------------------------------------------------------- 클립 (session: 인코딩 반복 방지)

@pytest.fixture(scope="session")
def numbered_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("hover_a") / "numbered_48.mov")
    make_numbered_clip(path, count=CLIP_COUNT)
    return path


@pytest.fixture(scope="session")
def second_clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("hover_b") / "numbered_24.mov")
    make_numbered_clip(path, count=SECOND_COUNT)
    return path


@pytest.fixture(scope="session")
def mp4_clip(tmp_path_factory):
    return write_test_video(str(tmp_path_factory.mktemp("hover_mp4") / "clip.mp4"), frames=24)


# ---------------------------------------------------------------- 워커 기록·대역

@pytest.fixture(autouse=True)
def real_builders(monkeypatch):
    """믹스인이 만든 진짜 워커를 전부 기록. autouse라 new_player보다 먼저 만들어져 나중에 정리된다 — 창이 닫힌 뒤 모든 워커의 스레드가
    끝났고(지워졌으면 끝난 뒤 지운 것 — release_worker는 끝난 워커만 지움) ffmpeg 프로세스가 거둬졌는지 단언."""
    made = []

    class RecordingBuilder(hover_strip_builder.HoverStripBuilder):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr(hover_strip_builder, "HoverStripBuilder", RecordingBuilder)
    yield made
    for builder in made:
        assert sip.isdeleted(builder) or not builder.isRunning(), f"창을 닫았는데 띠 워커가 돌고 있습니다: {builder.path}"
        if builder.pid is not None:
            assert not psutil.pid_exists(builder.pid), f"창을 닫았는데 띠 ffmpeg(pid {builder.pid})가 남았습니다"


class FakeBuilder(QObject):
    """HoverStripBuilder 대역 — 프로세스·스레드 없음. 믹스인이 넣는 paused 값과 start·stop 호출을 그대로 들고 있음."""

    progress = pyqtSignal(int)
    done = pyqtSignal(int, float)
    failed = pyqtSignal(str)

    def __init__(self, path, strip, ffmpeg=None, parent=None):
        super().__init__(parent)
        self.path = path
        self.strip = strip
        self.paused = False
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def isRunning(self):
        return False


@pytest.fixture
def fake_builders(monkeypatch):
    """믹스인이 띄우는 워커를 대역으로 — 만든 대역 목록. 시험 인자에서 player_with_clip보다 앞에 둘 것 (열기 전에 바꿔치기)."""
    made = []

    def make(*args, **kwargs):
        builder = FakeBuilder(*args, **kwargs)
        made.append(builder)
        return builder

    monkeypatch.setattr(hover_strip_builder, "HoverStripBuilder", make)
    return made


# ---------------------------------------------------------------- 플레이어

@pytest.fixture
def shown_player(new_player, dialogs, tmp_path, qapp):
    """보이는 창 (슬라이더 지오메트리·전역 좌표가 진짜여야 호버 x가 클릭 x와 같은 값이 됨)."""
    player = new_player(make_config(str(tmp_path), {}))
    player.resize(1200, 800)
    player.show()
    QTest.qWaitForWindowExposed(player)
    qapp.processEvents()
    return player


@pytest.fixture
def player_with_clip(shown_player, numbered_clip, qapp):
    assert shown_player.open_file("A", numbered_clip) is True
    qapp.processEvents()
    return shown_player


def hover(slider, x):
    """슬라이더 좌표 x로 커서가 들어와 움직임 (버튼 없음)."""
    pos = QPointF(x, slider.height() // 2)
    global_pos = QPointF(slider.mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(slider, QEnterEvent(pos, pos, global_pos))
    QApplication.sendEvent(slider, QMouseEvent(QEvent.MouseMove, pos, global_pos, Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    QApplication.processEvents()


def popup_image(popup):
    """창의 그림 — RGB 배열, 빈 상자면 None."""
    pixmap = popup.image_label.pixmap()
    if pixmap is None or pixmap.isNull():
        return None
    image = pixmap.toImage().convertToFormat(QImage.Format_RGB888)
    height, width, stride = image.height(), image.width(), image.bytesPerLine()
    pointer = image.constBits()
    pointer.setsize(stride * height)
    return np.frombuffer(pointer, np.uint8).reshape(height, stride)[:, :width * 3].reshape(height, width, 3).copy()


def wait_until(condition, timeout, what):
    """이벤트를 처리하며 condition()이 참이 될 때까지 (시간 초과면 실패)."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"{timeout}초 안에 {what}")
        QTest.qWait(20)


def strip_done(player):
    strip = player._hover_strip
    return (strip is not None and strip.filled_count == player._hover_plan.count and player._hover_builder is not None
            and not player._hover_timer.isActive())


def sample_xs(slider):
    """끝·고르게 흩은 x + 마지막 세 값(최대값 − 2·− 1·최대값)이 처음 나오는 x — 끝 근처는 '최대값 − 1 이상이면 마지막 장' 규칙을 지남."""
    width = slider.width()
    xs = {0, 1, 2, width // 9, width // 4, width // 3, width // 2, 2 * width // 3, 3 * width // 4, width - 2, width - 1}
    for value in (slider.maximum() - 2, slider.maximum() - 1, slider.maximum()):
        xs.add(next(x for x in range(width) if slider_value_at(slider, x) == value))
    return sorted(xs)


# ---------------------------------------------------------------- 번호 = 클릭 착지

@pytest.mark.parametrize("kind", ["prores", "mp4"])
def test_hover_shows_number_matching_current_label(shown_player, numbered_clip, mp4_clip, qapp, kind):
    """여러 x에서 호버한 번호가 같은 x를 클릭했을 때의 'Current:' 번호와 같음 — 메인·오버레이 슬라이더 모두 (각자의 착지 식).
    ProRes(파이프 캡처)와 mp4(cv2 캡처) 둘 다."""
    player = shown_player
    path, count = (numbered_clip, CLIP_COUNT) if kind == "prores" else (mp4_clip, 24)
    assert player.open_file("A", path) is True
    qapp.processEvents()
    popup = player._hover_popup

    for name in ("main", "overlay"):
        if name == "overlay":
            player.show_overlay_controls()
            qapp.processEvents()
        slider = player.positionScroll if name == "main" else player.overlaySlider
        assert slider.isVisible() and slider.maximum() == count - 1
        numbers = []
        for x in sample_xs(slider):
            hover(slider, x)
            assert popup.isVisible(), (name, x)
            number = popup.number_label.text()
            numbers.append(number)
            QTest.mouseClick(slider, Qt.LeftButton, Qt.NoModifier, QPoint(x, slider.height() // 2))
            qapp.processEvents()
            assert not popup.isVisible(), (name, x)  # 누르면 숨김
            player.update_position_info()
            assert player.labelFrameCount.text() == f"Current: {number}", (name, x, numbers)
        assert numbers[0] == "1" and numbers[-1] == str(count), (name, numbers)
        assert len(set(numbers)) >= 8, (name, numbers)  # 한두 값이 아니라 폭에 걸쳐 고르게


# ---------------------------------------------------------------- 쉬면 띠를 만들고 그림을 보임

def test_strip_builds_when_idle_and_popup_shows_image(player_with_clip, numbered_clip, real_builders, capsys):
    """열자마자는 번호 + 빈 상자, 쉬면(0.5초 + 쉬는 때) 띠를 만들고 다 만든 뒤에는 그 프레임의 그림 (간격 1). 띠는 재생 캡처를 쓰지
    않음 — 파이프 세션·위치가 그대로."""
    player = player_with_clip
    slider, popup = player.positionScroll, player._hover_popup
    cap = player.cap_a
    session, position = cap._session, cap.get(cv2.CAP_PROP_POS_FRAMES)

    hover(slider, slider.width() // 2)
    assert popup.isVisible() and popup.number_label.text().isdigit() and popup_image(popup) is None  # 번호 + 빈 상자

    wait_until(lambda: strip_done(player), WAIT_S, "띠를 다 만들지 못했습니다")
    out = capsys.readouterr().out
    assert f"{LOG_PREFIX} 띠 만들기 시작: {CLIP_COUNT}장(간격 1, 전체 {CLIP_COUNT}장) 320×180 — {numbered_clip}" in out
    assert f"{LOG_PREFIX} 띠 완성: {CLIP_COUNT}/{CLIP_COUNT}장 " in out and f"초 — {numbered_clip}" in out
    assert len(real_builders) == 1 and real_builders[0].path == numbered_clip

    for x in sample_xs(slider):
        hover(slider, x)
        image = popup_image(popup)
        assert image is not None and image.shape == (180, 320, 3), x
        assert frame_number(image) == int(popup.number_label.text()) - 1, x
    assert player.cap_a is cap and cap._session is session and cap.get(cv2.CAP_PROP_POS_FRAMES) == position  # 재생 캡처는 그대로


# ---------------------------------------------------------------- 쉬는 때

def test_builder_not_spawned_before_start_delay_and_pauses_while_playing(fake_builders, player_with_clip, numbered_clip):
    player = player_with_clip
    QTest.qWait(300)
    assert fake_builders == []  # 열린 지 START_DELAY_S 전

    player.timer.start(60_000)  # 재생 흉내 (틱은 오지 않음 — isActive만 참)
    QTest.qWait(1000)
    assert fake_builders == []  # 재생 중에는 띄우지 않음

    player.timer.stop()
    wait_until(lambda: len(fake_builders) == 1, 2, "쉬는데 워커를 띄우지 않았습니다")
    builder = fake_builders[0]
    assert builder.started and builder.path == numbered_clip and builder.strip is player._hover_strip
    QTest.qWait(100)
    assert builder.paused is False

    player.timer.start(60_000)
    wait_until(lambda: builder.paused is True, 1, "재생 중인데 워커를 멈추지 않았습니다")
    player.timer.stop()
    wait_until(lambda: builder.paused is False, 1, "재생을 멈췄는데 워커를 이어 가지 않았습니다")
    assert len(fake_builders) == 1


def test_arrow_stepping_counts_as_busy(fake_builders, player_with_clip):
    """화살표 연타처럼 프레임이 계속 움직이면 쉬는 때가 아님 — 재생 캡처의 위치 변화가 IDLE_S 안에 있으면 paused."""
    player = player_with_clip
    wait_until(lambda: len(fake_builders) == 1, 3, "워커를 띄우지 않았습니다")
    builder = fake_builders[0]
    QTest.qWait(100)
    assert builder.paused is False

    seen = []
    for frame in range(2, 12):
        player.seek_to_frame(frame)
        last_move = time.monotonic()
        QTest.qWait(100)
        seen.append(builder.paused)
    assert seen == [True] * 10

    wait_until(lambda: builder.paused is False, 2, "멈춘 뒤에도 워커가 쉬지 못합니다")
    from yesoncheck.player_hover_thumbs import IDLE_S  # 함수 안: 모듈이 없을 때도 다른 시험은 모아짐
    assert time.monotonic() - last_move >= IDLE_S


def test_stale_is_dragging_flag_does_not_block_the_strip(shown_player, numbered_clip, real_builders, capsys):
    """기존 표지 is_dragging이 드래그 뒤 True로 남아도(드래그 미리보기가 값을 blockSignals로 써 둬 놓을 때 valueChanged가 안 옴 — 실기
    보고) 쉬면 띠를 만듦: 쉬는 때는 is_dragging을 보지 않고 isSliderDown·위치 변화로 드래그를 덮는다."""
    player = shown_player
    player.is_dragging = True  # 고장 난 채 남은 표지 흉내 — open_file은 이 표지를 되돌리지 않음
    assert player.open_file("A", numbered_clip) is True
    wait_until(lambda: strip_done(player), WAIT_S, "is_dragging이 남은 채로는 띠를 만들지 못했습니다")
    assert player.is_dragging is True  # 시험 내내 남아 있었음 (기존 표지는 건드리지 않음)
    assert len(real_builders) == 1
    assert f"{LOG_PREFIX} 띠 완성: {CLIP_COUNT}/{CLIP_COUNT}장 " in capsys.readouterr().out


def test_slider_held_down_waits_and_logs_once_then_completes(shown_player, numbered_clip, real_builders, monkeypatch, capsys):
    """메인 슬라이더를 누르고 있는 동안은 쉬는 때가 아님 — 워커를 띄우지 않고, 워커 없이 BUSY_LOG_S보다 오래 바쁘면 진단 기록 한 줄(계획마다
    한 번). 놓으면 이어서 띠를 다 만듦."""
    from yesoncheck import player_hover_thumbs

    monkeypatch.setattr(player_hover_thumbs, "BUSY_LOG_S", 0.4)
    player = shown_player
    player.positionScroll.setSliderDown(True)
    assert player.open_file("A", numbered_clip) is True
    QTest.qWait(1500)
    assert real_builders == [] and player._hover_builder is None
    out = capsys.readouterr().out
    assert out.count(f"{LOG_PREFIX} 쉬는 때를 기다리는 중 ") == 1
    line = next(line for line in out.splitlines() if "쉬는 때를 기다리는 중" in line)
    assert "재생 False, 슬라이더 누름 True/False, 위치 변화 " in line and line.endswith(f"초 전 — {numbered_clip}")

    player.positionScroll.setSliderDown(False)
    wait_until(lambda: strip_done(player), WAIT_S, "슬라이더를 놓은 뒤 띠를 다 만들지 못했습니다")
    assert len(real_builders) == 1
    assert "쉬는 때를 기다리는 중" not in capsys.readouterr().out


# ---------------------------------------------------------------- 열기·놓기·닫기

def test_quick_reopen_never_spawns_ffmpeg(fake_builders, player_with_clip, second_clip):
    """열린 지 0.5초 안에 다른 파일을 A로 — 첫 파일로는 워커를 띄우지 않고, 새 계획은 둘째 파일의 것 (Review Focus 2)."""
    player = player_with_clip
    QTest.qWait(100)
    assert player.open_file("A", second_clip) is True
    assert player._hover_path == second_clip and player._hover_plan.total == SECOND_COUNT
    wait_until(lambda: len(fake_builders) == 1, 3, "둘째 파일의 워커를 띄우지 않았습니다")
    QTest.qWait(200)
    assert [builder.path for builder in fake_builders] == [second_clip]


def test_signals_from_a_replaced_builder_are_ignored(fake_builders, player_with_clip, second_clip, dialogs, capsys):
    """옛 워커가 놓이기 전에 낸 done·failed(GUI 대기열에 남은 것)가 새 파일의 상태를 건드리지 않음 — 보낸 쪽이 지금 워커일 때만 받음."""
    player = player_with_clip
    wait_until(lambda: len(fake_builders) == 1, 3, "워커를 띄우지 않았습니다")
    old = fake_builders[0]
    assert player.open_file("A", second_clip) is True
    assert old.stopped and not sip.isdeleted(old)
    capsys.readouterr()

    old.blockSignals(False)  # release_worker가 막은 것을 풂 — 막기 전에 대기열에 들어간 신호를 흉내 냄
    old.done.emit(CLIP_COUNT, 0.5)
    old.failed.emit("옛 워커의 늦은 실패")
    QApplication.processEvents()

    captured = capsys.readouterr()
    assert "띠 완성" not in captured.out and "띠를 만들지 못했습니다" not in captured.err
    assert dialogs.messages == []
    assert player._hover_timer.isActive() and player._hover_path == second_clip


def test_sequence_and_b_side_do_not_build(player_with_clip, numbered_clip, mp4_clip, tmp_path, qapp):
    player = player_with_clip
    plan = player._hover_plan
    assert player.open_file("B", mp4_clip) is True
    assert player._hover_plan is plan and player._hover_path == numbered_clip  # B는 띠에 손대지 않음

    sequence = make_seq(str(tmp_path / "seq"), "tk1", range(1, 7))
    assert player.open_file("A", sequence) is True
    assert player._hover_plan is None and player._hover_builder is None and not player._hover_timer.isActive()
    hover(player.positionScroll, player.positionScroll.width() // 2)
    assert not player._hover_popup.isVisible()
    QTest.qWait(800)
    assert player._hover_builder is None


@pytest.fixture
def slow_ffmpeg(monkeypatch):
    """띠 ffmpeg를 -re(제 속도로 읽기)로 느리게 — 48장 24fps = 2초라 '도는 중'인 진짜 워커를 확실히 잡는다 (build_command를 감쌈)."""
    real_command = hover_strip_builder.build_command
    monkeypatch.setattr(hover_strip_builder, "build_command",
                        lambda *args: (lambda cmd: cmd[:2] + ["-re"] + cmd[2:])(real_command(*args)))


def start_and_catch_running(player, path):
    """path를 A로 열고 진짜 워커가 ffmpeg를 띄워 아직 채우는 중일 때 → 그 워커 (slow_ffmpeg와 함께)."""
    assert player.open_file("A", path) is True
    wait_until(lambda: player._hover_builder is not None and player._hover_builder.pid is not None, 5,
               "워커가 ffmpeg를 띄우지 않았습니다")
    builder = player._hover_builder
    assert builder.isRunning() and psutil.pid_exists(builder.pid)
    assert player._hover_strip.filled_count < player._hover_plan.count  # 아직 도는 중
    return builder


def test_release_and_close_stop_builder(slow_ffmpeg, new_player, shown_player, numbered_clip, real_builders, tmp_path, qapp):
    """워커(진짜 ffmpeg)가 도는 중에 _release_side('A')·창 닫기 → 스레드가 끝나고 프로세스가 거둬짐."""

    builder = start_and_catch_running(shown_player, numbered_clip)
    shown_player._release_side("A")
    assert sip.isdeleted(builder) or not builder.isRunning()
    assert not psutil.pid_exists(builder.pid)
    assert shown_player._hover_builder is None and shown_player._hover_plan is None
    assert not shown_player._hover_timer.isActive()

    other = new_player(make_config(str(tmp_path / "other"), {}))
    other.show()
    QTest.qWaitForWindowExposed(other)
    builder = start_and_catch_running(other, numbered_clip)
    other.close()
    assert sip.isdeleted(builder) or not builder.isRunning()
    assert not psutil.pid_exists(builder.pid)
    assert len(real_builders) == 2

    def ffmpeg_children():
        return [p.pid for p in psutil.Process().children(recursive=True) if "ffmpeg" in p.name().lower()]

    wait_until(lambda: ffmpeg_children() == [], 5, f"ffmpeg 프로세스가 남았습니다: {ffmpeg_children()}")


def test_reopening_same_path_restarts_builder(slow_ffmpeg, shown_player, numbered_clip, real_builders):
    """같은 경로를 A로 다시 열면 옛 워커가 멈추고(옛 ffmpeg 없음) 새 계획에서 새 워커가 뜸 (스펙: 같은 경로도 다시 만듦)."""
    player = shown_player
    old = start_and_catch_running(player, numbered_clip)
    old_pid = old.pid
    assert player.open_file("A", numbered_clip) is True
    assert sip.isdeleted(old) or not old.isRunning()
    assert not psutil.pid_exists(old_pid)
    assert player._hover_builder is None and player._hover_path == numbered_clip  # 새 계획 — 워커는 쉬는 때 다시

    wait_until(lambda: player._hover_builder is not None and player._hover_builder.pid is not None, 5,
               "다시 연 파일의 워커를 띄우지 않았습니다")
    assert player._hover_builder is not old and player._hover_builder.pid != old_pid
    assert [builder.path for builder in real_builders] == [numbered_clip, numbered_clip]


def test_stale_plan_never_shows_after_a_is_dropped_elsewhere(player_with_clip):
    """_release_side를 거치지 않고 A를 놓는 길(job 불러오기의 cap_a.release·None·filename_a "")이 띠가 끝난 뒤(틱도 멈춤)에 와도 호버에
    옛 파일의 번호·그림이 뜨지 않음 — 조회마다 캡처·파일 이름을 다시 봄. A의 파일 이름이 계획의 것이 아니어도 마찬가지."""
    player = player_with_clip
    slider, popup = player.positionScroll, player._hover_popup
    wait_until(lambda: strip_done(player), WAIT_S, "띠를 다 만들지 못했습니다")
    hover(slider, slider.width() // 2)
    assert popup.isVisible() and popup_image(popup) is not None

    path, player.filename_a = player.filename_a, "/다른/영상.mov"
    hover(slider, slider.width() // 2)
    assert not popup.isVisible()
    player.filename_a = path
    hover(slider, slider.width() // 2)
    assert popup.isVisible()

    player.cap_a.release()  # job 불러오기(player_playback._load_job_list)의 세 줄 그대로
    player.cap_a = None
    player.filename_a = ""
    for target in (player.positionScroll, player.overlaySlider):
        hover(target, target.width() // 2)
        assert not popup.isVisible()


def test_job_switch_without_videos_drops_the_strip(new_player, dialogs, work_area, qapp):
    """실제 job 불러오기 길: 영상이 있는 job에서 띠가 끝난 뒤 영상이 없는 job을 고르면 A가 놓이며 띠도 버림 (계획·워커 없음, 창 없음)."""
    write_test_video(os.path.join(work_area.local, "S1", "job_01", "scene-001", "frames", "a.mov"))
    os.makedirs(os.path.join(work_area.local, "S1", "job_02", "scene-001", "frames"))
    player = new_player(make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map))
    player.resize(1200, 800)
    player.show()
    QTest.qWaitForWindowExposed(player)
    player.workComboBox.setCurrentText("SMOKE")
    player.seasonComboBox.setCurrentText("S1")
    player.jobComboBox.setCurrentText("job_01")
    assert player.cap_a is not None and player._hover_plan is not None  # 첫 영상을 A로 엶
    wait_until(lambda: strip_done(player), WAIT_S, "띠를 다 만들지 못했습니다")
    builder = player._hover_builder

    player.jobComboBox.setCurrentText("job_02")
    assert player.cap_a is None and player.filename_a == ""
    assert player._hover_plan is None and player._hover_strip is None and player._hover_builder is None
    assert sip.isdeleted(builder) or not builder.isRunning()
    hover(player.positionScroll, player.positionScroll.width() // 2)
    assert not player._hover_popup.isVisible()
    assert dialogs.errors() == []


def test_dead_capture_hides_popup_and_stops_tick(player_with_clip):
    """재생 캡처가 닫히면(파이프 도중 실패·release) 틱 한 번에 띠를 버리고 창을 숨기고 틱을 멈춤 (Review Focus 1)."""
    player = player_with_clip
    slider, popup = player.positionScroll, player._hover_popup
    hover(slider, slider.width() // 3)
    assert popup.isVisible()

    player.cap_a.release()
    player._hover_thumbs_tick()
    assert player._hover_plan is None and player._hover_strip is None and not player._hover_timer.isActive()
    assert not popup.isVisible()
    hover(slider, slider.width() // 3)
    assert not popup.isVisible()


# ---------------------------------------------------------------- 만들지 않음·실패

def test_size_cap_skips_with_log(player_with_clip, numbered_clip, monkeypatch, capsys):
    """파일이 MAX_FILE_BYTES보다 크면 띠를 만들지 않음 (기록 한 줄) — 호버는 번호 + 빈 상자 (그 파일 비율의 상자)."""
    player = player_with_clip
    monkeypatch.setattr(hover_strip, "MAX_FILE_BYTES", 1)
    capsys.readouterr()
    assert player.open_file("A", numbered_clip) is True
    reason = hover_strip.skip_reason(numbered_clip)

    QTest.qWait(900)
    assert player._hover_builder is None and player._hover_strip is None and not player._hover_timer.isActive()
    slider, popup = player.positionScroll, player._hover_popup
    hover(slider, slider.width() - 1)
    assert popup.isVisible() and popup.number_label.text() == str(CLIP_COUNT) and popup_image(popup) is None
    assert (popup.image_label.width(), popup.image_label.height()) == (320, 180)
    out = capsys.readouterr().out  # 열고 0.9초 쉬고 호버한 뒤까지 — 기록 줄은 정확히 한 번
    assert out.count(f"{LOG_PREFIX} 띠를 만들지 않음: {reason} — {numbered_clip}") == 1
    assert "띠 만들기 시작" not in out


def test_unknown_size_or_unreadable_file_skips_with_log(player_with_clip, numbered_clip, tmp_path, capsys):
    """장수·크기를 모르는 캡처(get이 0)와 크기를 읽지 못하는 파일(os.stat OSError)은 띠를 만들지 않음 — 기록(OSError는 트레이스백까지)만
    남기고 열기는 그대로 (예외를 open_file로 올리지 않음). 계획이 없으니 호버에 창 없음."""
    player = player_with_clip
    capsys.readouterr()
    player._hover_thumbs_open(numbered_clip, 0, 320, 180)
    assert player._hover_plan is None and not player._hover_timer.isActive()
    assert f"{LOG_PREFIX} 띠를 만들지 않음: 장수·크기를 알 수 없음 (장수 0, 320×180) — {numbered_clip}" in capsys.readouterr().out

    missing = str(tmp_path / "gone.mov")
    player._hover_thumbs_open(missing, CLIP_COUNT, 320, 180)
    assert player._hover_plan is None and not player._hover_timer.isActive()
    err = capsys.readouterr().err
    assert f"{LOG_PREFIX} 파일 크기를 읽지 못해 띠를 만들지 않음 — {missing}" in err
    assert "Traceback" in err and "FileNotFoundError" in err
    hover(player.positionScroll, player.positionScroll.width() // 2)
    assert not player._hover_popup.isVisible()


def test_builder_failure_logs_and_shows_window_once(fake_builders, player_with_clip, numbered_clip, monkeypatch, dialogs,
                                                     capsys):
    """워커 실패 → 기록(stderr)은 매번, 오류 창은 파일마다 한 번. 틱은 멈춤."""
    player = player_with_clip
    shown = []
    real_show_error = error_window.show_error

    def recording_show_error(prefix, text):
        shown.append((prefix, text))
        real_show_error(prefix, text)

    monkeypatch.setattr(error_window, "show_error", recording_show_error)
    wait_until(lambda: len(fake_builders) == 1, 3, "워커를 띄우지 않았습니다")
    builder = fake_builders[0]

    builder.failed.emit("가짜 실패 1")
    builder.failed.emit("가짜 실패 2")
    QApplication.processEvents()

    message = f"띠를 만들지 못했습니다 — {numbered_clip}\n가짜 실패 1\n\nSettings → {MENU_TEXT}을 끄면 만들지 않습니다"
    assert shown == [(LOG_PREFIX, message)]
    assert dialogs.criticals == [message]  # error_window.show_window → QMessageBox.critical (dialogs가 가로챔)
    err = capsys.readouterr().err
    assert err.count(f"{LOG_PREFIX} 띠를 만들지 못했습니다 — {numbered_clip}") == 2 and "가짜 실패 2" in err
    assert not player._hover_timer.isActive()


def test_missing_ffmpeg_reports_once_and_stops_tick(player_with_clip, numbered_clip, monkeypatch, dialogs, capsys):
    """ffmpeg를 찾지 못해 워커를 만들지 못하면 실패와 같은 길(기록 + 창 1회)이고 틱을 멈춤 — 50ms마다 다시 시도해 창이 쌓이지 않음."""
    player = player_with_clip

    def no_ffmpeg():
        raise external_tools.ToolNotFoundError("시험: ffmpeg 없음")

    monkeypatch.setattr(hover_strip_builder, "ffmpeg_path", no_ffmpeg)
    wait_until(lambda: not player._hover_timer.isActive(), 3, "틱이 멈추지 않았습니다")
    QTest.qWait(300)
    assert player._hover_builder is None
    assert len(dialogs.criticals) == 1 and dialogs.criticals[0].startswith(f"띠를 만들지 못했습니다 — {numbered_clip}\n")
    assert "ToolNotFoundError: 시험: ffmpeg 없음" in dialogs.criticals[0]
    assert capsys.readouterr().err.count(f"{LOG_PREFIX} 띠를 만들지 못했습니다") == 1


def test_disabled_feature_shows_nothing(shown_player, numbered_clip, monkeypatch, qapp):
    """기능을 끄면 계획도 워커도 없고 호버에 창이 뜨지 않음. 예전 'Position' 툴팁도 없음 (창이 그 자리를 대신함 — 꺼도 되살리지 않음)."""
    player = shown_player
    monkeypatch.setattr(hover_strip, "_enabled", hover_strip.enabled())  # 시험 뒤 되돌림
    hover_strip.set_enabled(False)
    assert player.open_file("A", numbered_clip) is True
    QTest.qWait(800)
    assert player._hover_plan is None and player._hover_builder is None and not player._hover_timer.isActive()
    for slider in (player.positionScroll, player.overlaySlider):
        hover(slider, slider.width() // 2)
        assert not player._hover_popup.isVisible()
    assert player.positionScroll.toolTip() == ""


def test_single_frame_movie_shows_1(shown_player, tmp_path, capsys):
    """한 장짜리 영상(슬라이더 최대값 1): 모든 x에서 번호 1, 0으로 나누지 않음, 띠는 샘플 0 하나 (Review Focus 4)."""
    player = shown_player
    path = str(tmp_path / "single.mov")
    make_numbered_clip(path, count=1)
    assert player.open_file("A", path) is True
    slider, popup = player.positionScroll, player._hover_popup
    assert slider.maximum() == 1 and player._hover_plan.total == 1

    for x in range(0, slider.width(), 7):
        hover(slider, x)
        assert popup.isVisible() and popup.number_label.text() == "1", x
    wait_until(lambda: strip_done(player), WAIT_S, "한 장짜리 띠를 만들지 못했습니다")
    hover(slider, slider.width() - 1)
    assert popup.number_label.text() == "1" and frame_number(popup_image(popup)) == 0
    assert "슬라이더 호버 처리 중 오류" not in capsys.readouterr().err
