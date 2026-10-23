"""이미지 시퀀스를 기존 재생 경로로 엶 (open_file의 .seq 분기·혼합 차단): 캡처가 cap_a/cap_b에 꽂히고, 소리 재생기는 건드리지
않고, 종류(mov/seq)가 다른 쪽은 놓고, 열지 못하면 창으로 알리되 어느 쪽도 반쯤 열린 채로 남지 않는다.

시퀀스 프레임은 번호마다 서로 다른 단색이라 화면의 한 점 색으로 어느 번호의 프레임인지 알 수 있다 (손실 없는 TGA).
오류 창은 conftest의 dialogs가 가로챈다 (실제 QMessageBox를 띄우지 않음).
"""

import os

import cv2
import pytest
from PyQt5.QtMultimedia import QMediaPlayer

from tests.conftest import write_test_video
from tests.test_sequence_capture import color_for, make_movie, make_seq
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import paths, player_playback, sequence_source
from yesoncheck.main_window import VideoPlayer
from yesoncheck.sequence_source import ImageSequenceCapture

LEFT, RIGHT = 4, 60  # 64폭 프레임의 와이프 선(0.5) 왼쪽·오른쪽 한 점


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def seq_in(tmp_path, folder, base="tk1", nums=range(1, 7), **kwargs):
    return make_seq(str(tmp_path / folder), base, nums, **kwargs)


def mov_in(tmp_path, name):
    return write_test_video(str(tmp_path / "movs" / name))


def shown(player, x):
    """화면(videoWidget)에 그려진 그림의 (x, 위쪽 한 줄) 점 색 (R, G, B)."""
    color = player.videoWidget.video_item.pixmap().toImage().pixelColor(x, 2)
    return (color.red(), color.green(), color.blue())


def frame_color(frame):
    return tuple(int(v) for v in frame[2, 2])  # player.frame_a·frame_b는 RGB


def turn_wipe_on(player):
    player.wipeCheckBox.setChecked(True)
    player.wipeXButton.setChecked(True)


def assert_wipe_off(player):
    assert not player.wipeCheckBox.isChecked()
    assert player.videoWidget.wipeEnabled is False
    assert not player.videoWidget.wipe_enabled_x and not player.videoWidget.wipe_enabled_y
    assert not player.wipeXButton.isChecked() and not player.wipeYButton.isChecked()
    assert not player.wipeXButton.isEnabled() and not player.wipeYButton.isEnabled()


def forbid_media_player_property(monkeypatch):
    """self.mediaPlayer 속성은 접근만으로 QMediaPlayer를 만든다 (Windows에서 수 초) — 시퀀스를 열 때 닿으면 시험이 실패."""
    def forbidden(self):
        raise AssertionError("시퀀스 경로에서 mediaPlayer 속성에 닿았습니다 (QMediaPlayer를 만들 수 있음)")

    monkeypatch.setattr(VideoPlayer, "mediaPlayer", property(forbidden))


def virtual(path):
    return paths.normalize_native(path)


# ---------------------------------------------------------------- 열기


def test_open_seq_sets_capture_and_virtual_filename(player, tmp_path):
    identity = seq_in(tmp_path, "shots")

    assert player.open_file("A", identity) is True

    assert isinstance(player.cap_a, ImageSequenceCapture) and player.cap_a.isOpened()
    assert player.filename_a == virtual(identity)  # 파일이 아닌 .seq 가상 경로 그대로 (주석·창 제목이 쓰는 값)
    assert player.cap_b is None and player.filename_b == ""
    assert player.filenameLabel.text() == "A: tk1.seq"
    assert player.positionScroll.maximum() == 5  # 6프레임 -> 0..5
    assert frame_color(player.frame_a) == color_for(1)  # 첫 프레임이 화면에 (display_first_frame)
    assert shown(player, LEFT) == color_for(1)
    assert player.annotation_store.video_path == virtual(identity)


def test_open_seq_as_b(player, tmp_path):
    a = seq_in(tmp_path, "a", base="tk1", nums=range(1, 5))
    b = seq_in(tmp_path, "b", base="tk2", nums=range(5, 9))
    assert player.open_file("A", a) and player.open_file("B", b)

    assert isinstance(player.cap_a, ImageSequenceCapture) and isinstance(player.cap_b, ImageSequenceCapture)
    assert player.filename_b == virtual(b)
    assert player.filenameLabel.text() == "A: tk1.seq, B: tk2.seq"


def test_is_sequence_active_follows_the_a_side(player, tmp_path):
    assert player.is_sequence_active() is False  # 아무것도 안 열림
    assert player.open_file("A", mov_in(tmp_path, "a.mp4"))
    assert player.is_sequence_active() is False
    assert player.open_file("A", seq_in(tmp_path, "shots"))
    assert player.is_sequence_active() is True
    assert player.open_file("A", mov_in(tmp_path, "a.mp4"))
    assert player.is_sequence_active() is False


def test_open_seq_skips_media_player_and_stops_previous(player, tmp_path, monkeypatch):
    mov = mov_in(tmp_path, "a.mp4")
    assert player.open_file("A", mov)  # 소리 재생기가 만들어지고 이 영상의 소리를 엶
    media = player._media_player
    assert media is not None and not media.media().isNull()
    stops = []
    real_stop = media.stop
    monkeypatch.setattr(media, "stop", lambda: (stops.append(True), real_stop())[1])
    forbid_media_player_property(monkeypatch)

    assert player.open_file("A", seq_in(tmp_path, "shots")) is True

    assert stops  # 이전 mov의 소리를 멈춤
    assert media.state() == QMediaPlayer.StoppedState
    assert media.media().isNull()  # 멈추기만 하고 두면 재생 버튼이 옛 mov의 소리를 다시 낼 수 있음 -> 소리 자체를 놓음
    assert player._media_player is media  # 새로 만들지도 않음


def test_open_seq_never_creates_media_player(player, tmp_path, monkeypatch):
    forbid_media_player_property(monkeypatch)
    a = seq_in(tmp_path, "a", base="tk1", nums=range(1, 5))
    b = seq_in(tmp_path, "b", base="tk2", nums=range(5, 9))

    assert player.open_file("A", a) and player.open_file("B", b)
    player.play_video()  # 재생기가 없으면 소리 쪽은 할 일이 없음
    player.pause_video()
    player.stop_video()

    assert player._media_player is None
    assert player.findChildren(QMediaPlayer) == []


def test_fps_combo_shows_paired_mov_fps(player, tmp_path):
    folder = tmp_path / "paired"
    identity = seq_in(tmp_path, "paired")
    make_movie(str(folder / "tk1.mov"), fps=25)
    assert player.frameRateComboBox.currentText() == "24"

    assert player.open_file("A", identity)

    assert player.frameRateComboBox.currentText() == "25"


def test_fps_combo_falls_back_to_24_without_paired_mov(player, tmp_path):
    player.frameRateComboBox.setCurrentText("30")

    assert player.open_file("A", seq_in(tmp_path, "unpaired"))

    assert player.frameRateComboBox.currentText() == "24"


# ---------------------------------------------------------------- 혼합 차단


def test_cross_type_open_releases_other_side_and_wipe(player, tmp_path):
    """seq A+B 와이프 중 mov A를 열면 B(seq)를 놓고 와이프를 끈다."""
    a = seq_in(tmp_path, "a", base="tk1", nums=range(1, 5))
    b = seq_in(tmp_path, "b", base="tk2", nums=range(5, 9))
    assert player.open_file("A", a) and player.open_file("B", b)
    turn_wipe_on(player)
    old_a, old_b = player.cap_a, player.cap_b
    mov = mov_in(tmp_path, "a.mp4")

    assert player.open_file("A", mov) is True

    assert player.filename_a == virtual(mov) and isinstance(player.cap_a, cv2.VideoCapture)
    assert player.cap_b is None and player.filename_b == "" and player.frame_b is None
    assert not old_b.isOpened()  # 놓음 (선읽기 예산 반납)
    assert not old_a.isOpened()  # 바꿔 끼운 쪽의 옛 캡처도 놓음
    assert_wipe_off(player)
    assert player.filenameLabel.text() == f"A: {os.path.basename(mov)}"
    assert player.is_sequence_active() is False
    assert len(sequence_source._LIVE) == 0


def test_cross_type_open_of_b_releases_the_a_side(player, tmp_path):
    """mov A + mov B 와이프 중 seq를 B로 열면 A(mov)를 놓고 그 소리도 놓는다."""
    assert player.open_file("A", mov_in(tmp_path, "a.mp4")) and player.open_file("B", mov_in(tmp_path, "b.mp4"))
    turn_wipe_on(player)
    old_a = player.cap_a
    media = player._media_player
    assert not media.media().isNull()
    seq = seq_in(tmp_path, "shots")

    assert player.open_file("B", seq) is True

    assert player.cap_a is None and player.filename_a == "" and player.frame_a is None
    assert not old_a.isOpened()
    assert isinstance(player.cap_b, ImageSequenceCapture) and player.filename_b == virtual(seq)
    assert_wipe_off(player)
    assert media.media().isNull()  # 놓은 A의 소리가 남지 않음
    assert player.is_sequence_active() is False  # A 쪽 기준
    assert player.filenameLabel.text() == ""
    assert player.videoWidget.video_item.pixmap().isNull()  # 놓은 A의 마지막 그림이 화면에 남지 않음


def test_same_type_open_keeps_other_side(player, tmp_path):
    """mov A 교체 시 mov B 유지(기존 동작) — 와이프도 그대로."""
    assert player.open_file("A", mov_in(tmp_path, "a1.mp4")) and player.open_file("B", mov_in(tmp_path, "b.mp4"))
    turn_wipe_on(player)
    cap_b, filename_b = player.cap_b, player.filename_b
    other = mov_in(tmp_path, "a2.mp4")

    assert player.open_file("A", other) is True

    assert player.cap_b is cap_b and cap_b.isOpened() and player.filename_b == filename_b
    assert player.filename_a == virtual(other)
    assert player.wipeCheckBox.isChecked() and player.videoWidget.wipeEnabled and player.videoWidget.wipe_enabled_x


def test_same_type_seq_open_keeps_other_side_and_releases_replaced(player, tmp_path):
    a = seq_in(tmp_path, "a", base="tk1", nums=range(1, 5))
    b = seq_in(tmp_path, "b", base="tk2", nums=range(5, 9))
    assert player.open_file("A", a) and player.open_file("B", b)
    turn_wipe_on(player)
    old_a, cap_b = player.cap_a, player.cap_b
    a2 = seq_in(tmp_path, "a2", base="tk3", nums=range(1, 4))

    assert player.open_file("A", a2) is True

    assert not old_a.isOpened()
    assert player.cap_b is cap_b and cap_b.isOpened() and player.filename_b == virtual(b)
    assert player.wipeCheckBox.isChecked() and player.videoWidget.wipe_enabled_x
    assert len(sequence_source._LIVE) == 2  # 옛 A는 예산에서 빠짐


def test_replaced_sequence_is_released_before_the_new_one_is_created(player, tmp_path, monkeypatch):
    """선읽기 예산을 나눠 쓰는 옛 캡처는 새 캡처가 만들어지기 전에 놓음 (놓지 않은 캡처는 GC까지 몫을 차지함)."""
    assert player.open_file("A", seq_in(tmp_path, "a", base="tk1", nums=range(1, 5)))
    old_a = player.cap_a
    seen = []
    real_open = player_playback.open_any_capture

    def recording_open(path):
        seen.append((old_a.isOpened(), len(sequence_source._LIVE)))
        return real_open(path)

    monkeypatch.setattr(player_playback, "open_any_capture", recording_open)  # 이름을 읽는 모듈에서 바꿈

    assert player.open_file("A", seq_in(tmp_path, "b", base="tk2", nums=range(1, 4)))

    assert seen == [(False, 0)]
    assert len(sequence_source._LIVE) == 1


# ---------------------------------------------------------------- 재생 경로 (기존 코드가 시퀀스 캡처로 그대로 동작)


def test_seek_and_step_work_on_sequence(player, tmp_path):
    assert player.open_file("A", seq_in(tmp_path, "shots", nums=range(1, 7)))

    player.seek_to_frame(3)  # 1부터 세는 프레임 번호
    assert frame_color(player.frame_a) == color_for(3)
    assert shown(player, LEFT) == color_for(3)
    assert int(player.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) == 3

    player.next_frame()
    assert frame_color(player.frame_a) == color_for(4)
    player.next_frame()
    assert frame_color(player.frame_a) == color_for(5)
    player.prev_frame()
    player.prev_frame()
    assert frame_color(player.frame_a) == color_for(3)

    player.seek_to_frame(6)
    assert frame_color(player.frame_a) == color_for(6)
    player.next_frame()  # 끝에서 더 가지 않음
    assert frame_color(player.frame_a) == color_for(6)
    player.stop_video()  # 정지 = 첫 프레임으로
    assert frame_color(player.frame_a) == color_for(1)


def test_playback_tick_advances_sequence(player, tmp_path):
    assert player.open_file("A", seq_in(tmp_path, "shots", nums=range(1, 7)))
    player.play_video()  # 타이머가 돌아야 틱이 일함 (이벤트는 처리하지 않으니 틱은 아래에서 직접)

    player.next_frame_playback()
    player.next_frame_playback()
    player.pause_video()

    assert frame_color(player.frame_a) == color_for(3)


def test_wipe_seq_vs_seq_composites(player, tmp_path):
    a = seq_in(tmp_path, "a", base="tk1", nums=range(1, 5))
    b = seq_in(tmp_path, "b", base="tk2", nums=range(5, 9))
    assert player.open_file("A", a) and player.open_file("B", b)
    turn_wipe_on(player)

    player.seek_to_frame(1)
    assert shown(player, LEFT) == color_for(1)  # 와이프 선 왼쪽 = A
    assert shown(player, RIGHT) == color_for(5)  # 오른쪽 = B

    player.seek_to_frame(2)  # 탐색은 B도 같이 맞춤 (키보드 한 장씩 가기는 mov도 A만 움직이는 기존 동작이라 여기서 쓰지 않음)
    assert shown(player, LEFT) == color_for(2)
    assert shown(player, RIGHT) == color_for(6)

    player.play_video()
    player.next_frame_playback()  # 재생 틱도 둘을 같이 앞으로
    player.pause_video()
    assert shown(player, LEFT) == color_for(3)
    assert shown(player, RIGHT) == color_for(7)


# ---------------------------------------------------------------- 열지 못할 때


def reported(dialogs):
    """오류 창 글 (QMessageBox.critical) — 하나여야 함."""
    assert len(dialogs.criticals) == 1, dialogs.messages
    return dialogs.criticals[0]


def assert_side_empty(player, side):
    cap, filename, frame = ((player.cap_a, player.filename_a, player.frame_a) if side == "A"
                            else (player.cap_b, player.filename_b, player.frame_b))
    assert cap is None and filename == "" and frame is None


def test_open_seq_in_missing_folder_reports_with_traceback(player, dialogs, tmp_path):
    missing = str(tmp_path / "gone" / "tk1.seq")

    assert player.open_file("A", missing) is False

    text = reported(dialogs)
    assert missing in text and "FileNotFoundError" in text and "Traceback" in text  # 이유와 스택 트레이스째
    assert_side_empty(player, "A")
    assert len(sequence_source._LIVE) == 0


def test_open_seq_with_corrupt_first_frame_reports_with_traceback(player, dialogs, tmp_path):
    identity = seq_in(tmp_path, "bad", nums=range(1, 5))
    with open(tmp_path / "bad" / "tk1-0001.tga", "wb") as fh:
        fh.write(b"not an image")

    assert player.open_file("A", identity) is False

    text = reported(dialogs)
    assert identity in text and "ValueError" in text and "tk1-0001.tga" in text and "Traceback" in text
    assert_side_empty(player, "A")
    assert len(sequence_source._LIVE) == 0


def test_open_seq_without_enough_frames_reports(player, dialogs, tmp_path):
    seq_in(tmp_path, "one", nums=[1])  # 프레임 한 장은 시퀀스가 아님
    identity = str(tmp_path / "one" / "tk1.seq")

    assert player.open_file("A", identity) is False

    assert identity in reported(dialogs)
    assert_side_empty(player, "A")


def test_failed_seq_open_releases_the_replaced_seq_but_keeps_the_other_side(player, dialogs, tmp_path):
    """시퀀스 A를 바꾸다 실패: 바꾸려던 A는 (새 캡처를 만들기 전에 놓았으므로) 비고, B는 그대로."""
    a = seq_in(tmp_path, "a", base="tk1", nums=range(1, 5))
    b = seq_in(tmp_path, "b", base="tk2", nums=range(5, 9))
    assert player.open_file("A", a) and player.open_file("B", b)
    turn_wipe_on(player)
    old_a, cap_b = player.cap_a, player.cap_b
    player.timer.start(1000)  # 재생 중이었다고 치고: 빈 A를 두고 타이머가 돌면 안 됨

    assert player.open_file("A", str(tmp_path / "gone" / "tk9.seq")) is False

    reported(dialogs)
    assert not old_a.isOpened()
    assert_side_empty(player, "A")
    assert not player.timer.isActive()
    assert player.cap_b is cap_b and cap_b.isOpened() and player.filename_b == virtual(b)
    assert len(sequence_source._LIVE) == 1  # 놓은 A의 예산 몫이 B에게 돌아감
    assert player.videoWidget.video_item.pixmap().isNull()  # 놓은 A의 마지막 그림이 화면에 남지 않음


def test_failed_cross_type_open_keeps_everything_playing(player, dialogs, tmp_path):
    """mov A+B 와이프 중 seq 열기가 실패하면 보던 것은 그대로 (종류가 다른 쪽도 열기에 성공한 뒤에야 놓음)."""
    assert player.open_file("A", mov_in(tmp_path, "a.mp4")) and player.open_file("B", mov_in(tmp_path, "b.mp4"))
    turn_wipe_on(player)
    cap_a, cap_b = player.cap_a, player.cap_b
    filename_a, filename_b = player.filename_a, player.filename_b

    assert player.open_file("B", str(tmp_path / "gone" / "tk9.seq")) is False

    reported(dialogs)
    assert player.cap_a is cap_a and cap_a.isOpened() and player.filename_a == filename_a
    assert player.cap_b is cap_b and cap_b.isOpened() and player.filename_b == filename_b
    assert player.wipeCheckBox.isChecked() and player.videoWidget.wipe_enabled_x


def test_failed_seq_open_over_a_playing_mov_keeps_the_mov(player, dialogs, tmp_path):
    """mov는 cv2처럼 보던 영상을 멈추지 않는 기존 약속 그대로 (예산을 쓰지 않는 옛 mov는 새 캡처를 만든 뒤에 놓음)."""
    mov = mov_in(tmp_path, "a.mp4")
    assert player.open_file("A", mov)
    cap_a = player.cap_a

    assert player.open_file("A", str(tmp_path / "gone" / "tk9.seq")) is False

    reported(dialogs)
    assert player.cap_a is cap_a and cap_a.isOpened() and player.filename_a == virtual(mov)


def test_open_mov_still_reports_unopenable_as_before(player, dialogs, tmp_path):
    broken = tmp_path / "movs" / "broken.mov"
    broken.parent.mkdir()
    broken.write_bytes(b"not a video")

    assert player.open_file("A", str(broken)) is False

    assert str(broken) in reported(dialogs)
    assert player.cap_a is None
