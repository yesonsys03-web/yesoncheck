"""시퀀스 프레임 한 장(`<base>-NNNN.<확장자>`)을 영상처럼 여는 경로: 이름 해석(parse_frame_name)·폴더에서 시퀀스 찾기
(resolve_frame_path)·open_file이 프레임을 그 프레임의 시퀀스로 엶(Open Video A/B·Finder 열기·끌어다 놓기가 모두 거치는 곳)·
끌어다 놓은 프레임 파일이 mov 파일처럼 열리고 Seq 목록에 들어감.

프레임은 tests.test_sequence_capture.make_seq가 만든 작은 TGA (번호마다 다른 단색). 예시 이름만 씀 (공개 저장소).
창·대화상자는 conftest의 dialogs가 가로챔 (실제 QMessageBox·QFileDialog를 띄우지 않음).
"""

import os
from types import SimpleNamespace

import pytest
from PyQt5.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt5.QtGui import QDropEvent
from PyQt5.QtWidgets import QFileDialog

from tests.conftest import write_test_video
from tests.test_sequence_capture import color_for, make_seq
from tests.test_sidebar_refresh import refresh
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import paths, player_playback, sequence_scan, sequence_source
from yesoncheck.player_sidebar import PlayerSidebarMixin
from yesoncheck.sequence_scan import SEQ_EXTENSIONS, FolderFrames, group_sequences, parse_frame_name, sequence_of_frame
from yesoncheck.sequence_source import ImageSequenceCapture, find_frame_sequence, resolve_frame_path


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def frame(folder, base, number, ext="tga", pad=4):
    """폴더 안 프레임 파일의 경로 (파일을 만들지는 않음)."""
    return os.path.join(str(folder), f"{base}-{number:0{pad}d}.{ext}")


def virtual(path):
    return paths.normalize_native(path)


def frame_color(player_frame):
    return tuple(int(v) for v in player_frame[2, 2])  # player.frame_a·frame_b는 RGB


def spy_scandir(monkeypatch):
    """os.scandir 호출 기록 (진짜로 읽음)."""
    calls = []
    real = os.scandir

    def spy(path="."):
        calls.append(str(path))
        return real(path)

    monkeypatch.setattr(os, "scandir", spy)
    return calls


# ---------------------------------------------------------------- 이름 해석 (sequence_scan: 디스크 없음)


@pytest.mark.parametrize("name, expected", [
    ("EX01_tk1-0042.tga", ("EX01_tk1", 42, "tga", 4)),
    ("scene-09B_tk1-0001.tga", ("scene-09B_tk1", 1, "tga", 4)),  # base 안의 '-'는 base의 일부 (마지막 '-'까지가 base)
    ("EX01_tk1-0042.TGA", ("EX01_tk1", 42, "tga", 4)),  # 확장자는 소문자로
    ("a_tk1-00007.png", ("a_tk1", 7, "png", 5)),
    ("a_tk1-12.exr", ("a_tk1", 12, "exr", 2)),
    ("a_tk1-0100.tiff", ("a_tk1", 100, "tiff", 4)),
    ("clip.v2-0003.jpeg", ("clip.v2", 3, "jpeg", 4)),
])
def test_parse_frame_name_matches_frames(name, expected):
    assert parse_frame_name(name) == expected


@pytest.mark.parametrize("name", [
    "EX01_tk1.mov",  # 영상
    "EX01_tk1.seq",  # 시퀀스의 가상 경로는 프레임이 아님
    "EX01_tk1-0042.seq",
    "EX01_tk1-0042.mov",  # 프레임 번호가 있어도 이미지 확장자가 아님
    "EX01_tk1-0042.txt",
    "EX01_tk1-0042",  # 확장자 없음
    "readme.txt",
    "a-1.tga",  # 번호가 한 자리
    "a-xyz.tga",
    "-0001.tga",  # base가 없음
    ".hidden-0001.tga",  # 숨김 파일
    "._EX01_tk1-0001.tga",  # macOS 리소스 포크 파일
    "a-１２３４.tga",  # 전각 숫자 (ASCII 숫자만)
    "",
])
def test_parse_frame_name_rejects_non_frames(name):
    assert parse_frame_name(name) is None


def test_group_sequences_agrees_with_parse_frame_name():
    names = ["a-0001.tga", "a-0002.TGA", "b-001.png", "b-002.png", "c.mov", ".x-0001.tga", "d-0001.seq"]
    grouped = {(s.base, s.ext, s.pad, s.count) for s in group_sequences("/j", names)}
    assert grouped == {("a", "tga", 4, 2), ("b", "png", 3, 2)}


def test_sequence_of_frame_finds_the_group_of_that_frame():
    names = ["a-0001.tga", "a-0002.tga", "a-0004.tga", "b-0001.tga", "b-0002.tga", "a.mov"]
    seq = sequence_of_frame("/j", names, "a-0004.tga")
    assert (seq.dir, seq.base, seq.ext, seq.pad, seq.first, seq.last, seq.count) == ("/j", "a", "tga", 4, 1, 4, 3)
    assert sequence_of_frame("/j", names, "b-0002.tga").base == "b"


def test_sequence_of_frame_none_cases():
    names = ["a-0001.tga", "a-0002.tga", "a-0004.tga", "lone-0001.tga", "t-001.tga", "t-0001.tga"]
    assert sequence_of_frame("/j", names, "a-0003.tga") is None  # 그 번호의 프레임이 목록에 없음 (범위 안이어도)
    assert sequence_of_frame("/j", names, "lone-0001.tga") is None  # 한 장뿐
    assert sequence_of_frame("/j", names, "t-001.tga") is None  # 자릿수가 다른 둘은 별개이고 각각 한 장뿐
    assert sequence_of_frame("/j", names, "a.mov") is None  # 프레임 이름이 아님
    assert sequence_of_frame("/j", names, "zzz-0001.tga") is None  # 폴더에 없음


def test_sequence_of_frame_ignores_a_group_the_capture_would_not_open():
    """같은 base의 시퀀스가 여럿이면 캡처는 첫 묶음(ext 이름순)만 엶 — 그 밖 묶음의 프레임은 다른 프레임들로 열리게 하지 않음."""
    names = ["a-0001.png", "a-0002.png", "a-0001.tga", "a-0002.tga"]
    assert sequence_of_frame("/j", names, "a-0001.png").ext == "png"
    assert sequence_of_frame("/j", names, "a-0001.tga") is None


# ---------------------------------------------------------------- 폴더에서 시퀀스 찾기 (sequence_source: 폴더를 한 번 읽음)


def test_resolve_frame_with_siblings_returns_the_identity(tmp_path):
    identity = make_seq(str(tmp_path / "shot"), "EX01_tk1", range(1, 7))
    assert resolve_frame_path(frame(tmp_path / "shot", "EX01_tk1", 4)) == identity
    seq = find_frame_sequence(frame(tmp_path / "shot", "EX01_tk1", 4))
    assert (seq.base, seq.first, seq.last, seq.count) == ("EX01_tk1", 1, 6, 6)


def test_resolve_frame_is_case_insensitive_on_extension(tmp_path):
    folder = tmp_path / "shot"
    make_seq(str(folder), "a", range(1, 4))
    os.rename(frame(folder, "a", 2), frame(folder, "a", 2, ext="TGA"))
    assert resolve_frame_path(frame(folder, "a", 2, ext="TGA")) == os.path.join(str(folder), "a.seq")


def test_resolve_orphan_frame_is_none(tmp_path):
    folder = tmp_path / "shot"
    make_seq(str(folder), "lone", [1])
    assert resolve_frame_path(frame(folder, "lone", 1)) is None
    assert find_frame_sequence(frame(folder, "lone", 1)) is None


def test_resolve_missing_frame_file_is_none(tmp_path):
    folder = tmp_path / "shot"
    make_seq(str(folder), "a", [1, 2, 4])
    assert resolve_frame_path(frame(folder, "a", 3)) is None  # 3번 파일이 없음 (옛 경로)


def test_resolve_nonexistent_folder_is_none(tmp_path):
    assert resolve_frame_path(frame(tmp_path / "nowhere", "a", 1)) is None


def test_resolve_folder_that_is_a_file_is_none(tmp_path):
    (tmp_path / "plain").write_text("x")
    assert resolve_frame_path(frame(tmp_path / "plain", "a", 1)) is None


def test_resolve_other_read_errors_are_not_swallowed(tmp_path, monkeypatch):
    folder = tmp_path / "shot"
    make_seq(str(folder), "a", range(1, 4))

    def denied(path="."):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(os, "scandir", denied)
    with pytest.raises(PermissionError):
        resolve_frame_path(frame(folder, "a", 1))


def test_resolve_leaves_seq_and_movie_paths_alone_without_reading_the_folder(tmp_path, monkeypatch):
    mov = write_test_video(str(tmp_path / "movs" / "a.mov"))
    identity = make_seq(str(tmp_path / "shot"), "a", range(1, 4))
    calls = spy_scandir(monkeypatch)

    assert resolve_frame_path(identity) is None
    assert resolve_frame_path(mov) is None
    assert resolve_frame_path(str(tmp_path / "movs" / "scene-0001.mov")) is None
    assert resolve_frame_path(str(tmp_path / "readme.txt")) is None

    assert calls == []


# ---------------------------------------------------------------- open_file: 프레임 한 장 -> 그 시퀀스


def test_open_frame_as_a_opens_the_whole_sequence(player, tmp_path):
    identity = make_seq(str(tmp_path / "shot"), "EX01_tk1", range(1, 7))

    assert player.open_file("A", frame(tmp_path / "shot", "EX01_tk1", 4)) is True

    assert isinstance(player.cap_a, ImageSequenceCapture) and player.cap_a.isOpened()
    assert player.filename_a == virtual(identity)  # 프레임 파일이 아니라 .seq 가상 경로 (주석·창 제목·OCR 막기가 쓰는 값)
    assert player.positionScroll.maximum() == 5  # 6프레임 -> 0..5
    assert frame_color(player.frame_a) == color_for(1)
    assert player.filenameLabel.text() == "A: EX01_tk1.seq"
    assert player.annotation_store.video_path == virtual(identity)
    assert player.is_sequence_active() is True


def test_open_frame_as_b_opens_the_whole_sequence(player, tmp_path):
    a = make_seq(str(tmp_path / "a"), "tk1", range(1, 5))
    b = make_seq(str(tmp_path / "b"), "tk2", range(5, 12))
    assert player.open_file("A", a)

    assert player.open_file("B", frame(tmp_path / "b", "tk2", 9)) is True

    assert isinstance(player.cap_b, ImageSequenceCapture)
    assert player.filename_b == virtual(b)
    assert int(player.cap_b.get(7)) == 7  # CAP_PROP_FRAME_COUNT: 5~11
    assert player.filenameLabel.text() == "A: tk1.seq, B: tk2.seq"


def test_open_frame_resolves_before_the_kind_check_so_mixing_still_applies(player, tmp_path):
    """프레임으로 연 시퀀스도 시퀀스: 반대쪽이 mov면 놓고 와이프를 끄는 혼합 차단이 그대로 적용됨."""
    mov = write_test_video(str(tmp_path / "movs" / "a.mp4"))
    make_seq(str(tmp_path / "shot"), "tk1", range(1, 5))
    assert player.open_file("A", mov)

    assert player.open_file("B", frame(tmp_path / "shot", "tk1", 2))

    assert isinstance(player.cap_b, ImageSequenceCapture)
    assert player.cap_a is None and player.filename_a == ""


def test_open_orphan_frame_keeps_todays_behavior(player, tmp_path, monkeypatch):
    folder = tmp_path / "shot"
    make_seq(str(folder), "lone", [1])
    lone = virtual(frame(folder, "lone", 1))
    calls = []
    monkeypatch.setattr(player, "_open_movie_capture", lambda path: calls.append(("movie", path)))
    monkeypatch.setattr(player, "_open_sequence_capture", lambda path: calls.append(("seq", path)))

    assert player.open_file("A", lone) is False  # 대역이 None을 돌려줌 (열지 못함)

    assert calls == [("movie", lone)]  # 한 장은 예전처럼 영상 경로로


def test_open_missing_frame_next_to_siblings_reports_missing_file(player, dialogs, tmp_path):
    folder = tmp_path / "shot"
    make_seq(str(folder), "a", [1, 2, 4])

    assert player.open_file("A", frame(folder, "a", 3)) is False  # 3번 파일은 없음: 예전처럼 '영상 없음'

    assert len(dialogs.warnings) == 1 and "디스크에 없는 영상입니다" in dialogs.warnings[0]
    assert player.cap_a is None


def test_open_frame_in_missing_folder_reports_missing_file(player, dialogs, tmp_path):
    assert player.open_file("A", frame(tmp_path / "nowhere", "a", 1)) is False

    assert len(dialogs.warnings) == 1 and "디스크에 없는 영상입니다" in dialogs.warnings[0]


def test_open_frame_reports_an_unreadable_folder_loudly(player, dialogs, tmp_path, monkeypatch):
    folder = tmp_path / "shot"
    make_seq(str(folder), "a", range(1, 4))
    path = frame(folder, "a", 1)

    def denied(path="."):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(os, "scandir", denied)

    assert player.open_file("A", path) is False

    assert len(dialogs.criticals) == 1
    assert "PermissionError" in dialogs.criticals[0] and "Traceback" in dialogs.criticals[0]  # 스택 트레이스째
    assert player.cap_a is None


def test_open_movie_does_no_extra_folder_read(player, tmp_path, monkeypatch):
    mov = write_test_video(str(tmp_path / "movs" / "scene-0001.mov"))  # 프레임처럼 보이는 이름이어도 이미지 확장자가 아님
    calls = spy_scandir(monkeypatch)

    assert player.open_file("A", mov) is True

    assert calls == []


def test_open_seq_identity_does_not_run_the_frame_resolver(player, tmp_path, monkeypatch):
    identity = make_seq(str(tmp_path / "shot"), "tk1", range(1, 5))
    monkeypatch.setattr(player_playback, "resolve_frame_path",
                        lambda path: pytest.fail("이미 .seq인 경로에 프레임 해석기를 불렀습니다"))

    assert player.open_file("A", identity) is True


def test_open_frame_does_not_touch_the_media_player_property(player, tmp_path, monkeypatch):
    from tests.test_sequence_open import forbid_media_player_property

    make_seq(str(tmp_path / "shot"), "tk1", range(1, 5))
    forbid_media_player_property(monkeypatch)

    assert player.open_file("A", frame(tmp_path / "shot", "tk1", 2)) is True


# ---------------------------------------------------------------- Open Video A / B 대화상자


def record_dialog(monkeypatch, answer=""):
    seen = []

    def fake(*args, **kwargs):
        seen.append((args, kwargs))
        return answer, ""

    monkeypatch.setattr(player_playback.QFileDialog, "getOpenFileName", staticmethod(fake))
    return seen


def dialog_filter(args, kwargs):
    """getOpenFileName(parent, caption, directory, filter, ...)에 넘긴 필터 문자열 (안 넘겼으면 None)."""
    if "filter" in kwargs:
        return kwargs["filter"]
    return args[3] if len(args) > 3 else None


@pytest.mark.parametrize("side", ["A", "B"])
def test_open_dialog_lets_the_user_pick_a_sequence_frame(player, tmp_path, monkeypatch, side):
    """Open Video A/B 대화상자는 필터가 없어(모든 파일) 프레임 이미지도 고를 수 있음 — 필터를 넣게 되면 이미지 확장자를 빼면 안 됨."""
    seen = record_dialog(monkeypatch)

    assert player.open_file(side) is False  # 취소

    assert len(seen) == 1
    args, kwargs = seen[0]
    assert args[1] == f"Open Video {side}"
    shown = dialog_filter(args, kwargs)
    assert shown in (None, "") or all(f"*.{ext}" in shown.lower() for ext in SEQ_EXTENSIONS)


@pytest.mark.parametrize("side", ["A", "B"])
def test_picking_a_frame_in_the_dialog_opens_the_whole_sequence(player, tmp_path, monkeypatch, side):
    identity = make_seq(str(tmp_path / "shot"), "EX01_tk1", range(1, 7))
    record_dialog(monkeypatch, answer=frame(tmp_path / "shot", "EX01_tk1", 5))

    assert player.open_file(side) is True

    cap, name = (player.cap_a, player.filename_a) if side == "A" else (player.cap_b, player.filename_b)
    assert isinstance(cap, ImageSequenceCapture) and name == virtual(identity)


# ---------------------------------------------------------------- 끌어다 놓기: 프레임 파일


def drop_files(player, target, files):
    """파일(들)을 실제 QDropEvent로 끌어다 놓음. target: "video"(영상 영역), "sidebar"(Mov 목록), "window"(PlayerSidebarMixin.dropEvent —
    실제 창에서는 닿지 않는 핸들러, 아래 test_window_drop_handler_logic_is_unreachable_on_the_real_window 하나만 씀)."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in files])
    event = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    if target == "video":
        player.videoWidget.dropEvent(event)
    elif target == "window":
        PlayerSidebarMixin.dropEvent(SimpleNamespace(parent=lambda: player), event)  # 대역: 실제 최상위 창은 parent()가 None이라 이 핸들러는 아무것도 안 함
    else:
        assert player.eventFilter(player.sidebar, event) is True


def seq_identities(player):
    return [os.path.basename(player.seq_sidebar.item(i).data(Qt.UserRole).identity) for i in range(player.seq_sidebar.count())]


def mov_names(player):
    return [player.sidebar.item(i).text() for i in range(player.sidebar.count())]


def shot_folder(tmp_path, name="shot"):
    """tk1(6장)·tk2(4장) 시퀀스와 한 장뿐인 lone이 든 폴더."""
    folder = tmp_path / name
    make_seq(str(folder), "tk1", range(1, 7))
    make_seq(str(folder), "tk2", range(1, 5))
    make_seq(str(folder), "lone", [1])
    return folder


def test_dropped_frame_opens_its_sequence_as_a(player, dialogs, tmp_path):
    """영상 영역에 프레임 한 장을 놓으면 mov를 놓을 때처럼 열림 (A) — 시퀀스 전체가, Seq 목록에 들어가고 Seq 탭에 선택된 채로."""
    folder = shot_folder(tmp_path)

    drop_files(player, "video", [frame(folder, "tk1", 3)])

    assert isinstance(player.cap_a, ImageSequenceCapture)
    assert player.filename_a == virtual(os.path.join(str(folder), "tk1.seq"))
    assert player.cap_b is None
    assert seq_identities(player) == ["tk1.seq", "tk2.seq"]  # 그 폴더의 시퀀스들 (한 장뿐인 lone은 시퀀스가 아님)
    assert player.sidebar_tabs.currentIndex() == 1
    selected = [item.data(Qt.UserRole).base for item in player.seq_sidebar.selectedItems()]
    assert selected == ["tk1"] and player.seq_sidebar.currentItem().data(Qt.UserRole).base == "tk1"
    assert player.sidebar.count() == 0  # 영상 목록은 그대로
    assert dialogs.messages == []  # 경고·안내 창 없음


def test_dropped_frames_of_one_sequence_open_it_once(player, dialogs, tmp_path):
    folder = shot_folder(tmp_path)

    drop_files(player, "video", [frame(folder, "tk1", n) for n in (1, 2, 3, 4, 5, 6)])

    assert player.filename_a == virtual(os.path.join(str(folder), "tk1.seq"))
    assert player.cap_b is None  # 같은 시퀀스의 프레임을 여럿 놓아도 한 시퀀스 (B로 같은 것을 또 열지 않음)
    assert seq_identities(player) == ["tk1.seq", "tk2.seq"]
    assert dialogs.messages == []


def test_dropped_frames_of_two_sequences_open_a_and_b_like_two_movies(player, dialogs, tmp_path):
    folder = shot_folder(tmp_path)

    drop_files(player, "video", [frame(folder, "tk2", 2), frame(folder, "tk1", 5)])

    assert player.filename_a == virtual(os.path.join(str(folder), "tk2.seq"))  # 놓은 차례
    assert player.filename_b == virtual(os.path.join(str(folder), "tk1.seq"))
    assert dialogs.messages == []


def test_dropped_frames_of_three_sequences_open_the_first_and_list_all(player, dialogs, tmp_path):
    folder = shot_folder(tmp_path)
    make_seq(str(folder), "tk3", range(1, 4))

    drop_files(player, "video", [frame(folder, "tk3", 1), frame(folder, "tk1", 1), frame(folder, "tk2", 1)])

    assert player.filename_a == virtual(os.path.join(str(folder), "tk3.seq"))
    assert player.cap_b is None
    assert seq_identities(player) == ["tk1.seq", "tk2.seq", "tk3.seq"]
    assert dialogs.messages == []


def test_dropped_frame_folder_is_read_once_for_many_frames(player, dialogs, tmp_path, monkeypatch):
    folder = shot_folder(tmp_path)
    reads = []
    real = sequence_source.list_frame_names
    monkeypatch.setattr(sequence_source, "list_frame_names", lambda f: (reads.append(f), real(f))[1])

    drop_files(player, "sidebar", [frame(folder, "tk1", n) for n in range(1, 7)] + [frame(folder, "tk2", 1)])

    assert len(reads) == 1


def test_dropped_mixed_movie_and_frame_keeps_the_movie_behavior(player, dialogs, tmp_path):
    """영상 파일이 함께 있으면 영상은 예전 그대로(A로 열림) — 시퀀스는 열지 않고 Seq 목록에만 넣고, 보던 Mov 탭은 그대로."""
    folder = shot_folder(tmp_path)
    mov = write_test_video(str(tmp_path / "movs" / "a.mov"))

    drop_files(player, "video", [frame(folder, "tk1", 2), mov])

    assert not isinstance(player.cap_a, ImageSequenceCapture)
    assert player.filename_a == virtual(mov)
    assert seq_identities(player) == ["tk1.seq", "tk2.seq"]
    assert player.sidebar_tabs.currentIndex() == 0
    assert dialogs.messages == []


def test_dropped_orphan_frame_is_ignored_as_before(player, dialogs, tmp_path):
    folder = shot_folder(tmp_path)

    drop_files(player, "video", [frame(folder, "lone", 1)])

    assert player.cap_a is None and player.filename_a == ""
    assert player.seq_sidebar.count() == 0 and player.sidebar_tabs.currentIndex() == 0
    assert dialogs.messages == []


def test_dropped_non_frame_file_is_ignored_without_reading_the_folder(player, dialogs, tmp_path, monkeypatch):
    note = tmp_path / "notes" / "readme.txt"
    note.parent.mkdir()
    note.write_text("x")
    calls = spy_scandir(monkeypatch)

    drop_files(player, "video", [note])

    assert calls == []
    assert player.cap_a is None and dialogs.messages == []


def test_dropped_nonexistent_frame_file_is_ignored(player, dialogs, tmp_path):
    drop_files(player, "video", [frame(tmp_path / "nowhere", "a", 1)])  # 놓은 파일이 디스크에 없음 (isfile이 아니라 분류되지 않음)

    assert player.cap_a is None and player.seq_sidebar.count() == 0 and dialogs.messages == []


def test_dropped_frame_survives_a_list_refresh(player, dialogs, tmp_path):
    """놓은 프레임의 폴더는 목록 다시 읽기(F5)가 읽는 곳으로 기억됨 — 다시 읽어도 Seq 항목이 사라지지 않음."""
    folder = shot_folder(tmp_path)
    drop_files(player, "video", [frame(folder, "tk1", 3)])

    refresh(player)

    assert seq_identities(player) == ["tk1.seq", "tk2.seq"]


def test_dropping_a_frame_of_an_already_listed_sequence_does_not_duplicate(player, dialogs, tmp_path):
    folder = shot_folder(tmp_path)
    player.load_videos_from_folder(str(folder))
    assert seq_identities(player) == ["tk1.seq", "tk2.seq"]

    drop_files(player, "video", [frame(folder, "tk2", 3)])

    assert seq_identities(player) == ["tk1.seq", "tk2.seq"]
    assert player.filename_a == virtual(os.path.join(str(folder), "tk2.seq"))
    assert player.seq_sidebar.currentItem().data(Qt.UserRole).base == "tk2"


def test_dropped_frame_on_the_mov_list_only_fills_the_seq_list(player, dialogs, tmp_path):
    """Mov 목록에 놓은 프레임은 목록에 덧붙을 뿐 열지 않음 (Mov 목록에 놓은 영상 폴더처럼)."""
    folder = shot_folder(tmp_path)

    drop_files(player, "sidebar", [frame(folder, "tk1", 3)])

    assert player.cap_a is None and player.filename_a == ""
    assert seq_identities(player) == ["tk1.seq", "tk2.seq"]
    assert player.sidebar_tabs.currentIndex() == 1
    assert dialogs.messages == []


def test_dropped_frames_on_the_mov_list_append_to_existing_lists(player, dialogs, tmp_path):
    first = shot_folder(tmp_path, "first")
    second = tmp_path / "second"
    make_seq(str(second), "tk9", range(1, 4))
    player.load_videos_from_folder(str(first))

    drop_files(player, "sidebar", [frame(second, "tk9", 2)])

    assert seq_identities(player) == ["tk1.seq", "tk2.seq", "tk9.seq"]


def test_dropped_mixed_movie_and_frame_on_the_mov_list(player, dialogs, tmp_path):
    folder = shot_folder(tmp_path)
    mov = write_test_video(str(tmp_path / "movs" / "a.mov"))

    drop_files(player, "sidebar", [frame(folder, "tk1", 2), mov])

    assert mov_names(player) == ["a.mov"]  # 영상은 예전대로 Mov 목록에
    assert seq_identities(player) == ["tk1.seq", "tk2.seq"]
    assert player.sidebar_tabs.currentIndex() == 0
    assert dialogs.messages == [("information", "완료", "1개의 파일이 사이드바에 추가되었습니다.")]  # 영상 때문에 뜨던 예전 안내만


def test_dropped_orphan_frame_on_the_mov_list_stays_quiet(player, dialogs, tmp_path):
    folder = shot_folder(tmp_path)

    drop_files(player, "sidebar", [frame(folder, "lone", 1)])

    assert player.seq_sidebar.count() == 0 and player.sidebar_tabs.currentIndex() == 0 and dialogs.messages == []


@pytest.mark.parametrize("target", ["video", "sidebar"])
def test_dropped_folder_together_with_a_frame_keeps_the_folder_behavior(player, dialogs, tmp_path, target):
    """폴더와 프레임을 함께 놓으면 폴더는 예전 그대로이고 프레임의 시퀀스는 Seq 목록에 더해짐."""
    other = tmp_path / "other"
    make_seq(str(other), "tk9", range(1, 4))
    movies = tmp_path / "movies"
    write_test_video(str(movies / "z.mov"))

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(movies)), QUrl.fromLocalFile(frame(other, "tk9", 2))])
    event = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    if target == "video":
        player.videoWidget.dropEvent(event)
    else:
        assert player.eventFilter(player.sidebar, event) is True

    assert mov_names(player) == ["z.mov"]
    assert seq_identities(player) == ["tk9.seq"]
    assert player.sidebar_tabs.currentIndex() == 0


def test_window_drop_handler_logic_is_unreachable_on_the_real_window(player, dialogs, tmp_path):
    """PlayerSidebarMixin.dropEvent(메인 창 핸들러)는 self.parent()로 VideoPlayer를 찾는데 최상위 창은 parent()가 None이라 실제 창에서는
    본문이 한 번도 돌지 않음 (영상 파일을 놓아도 마찬가지 — 예전부터 있던 일이고 이번 변경에서 살리지 않음). 이 시험은 parent()가 창을 돌려주는
    대역으로 그 핸들러 안의 프레임 처리 논리만 지킴: 영상 영역과 같은 결과여야 코드가 어긋나지 않음. 실제 동작을 보장하는 시험이 아님."""
    folder = shot_folder(tmp_path)
    assert player.parent() is None  # 실제 창의 상태: 이 핸들러는 도달할 수 없음

    drop_files(player, "window", [frame(folder, "tk1", 3)])

    assert player.filename_a == virtual(os.path.join(str(folder), "tk1.seq"))
    assert seq_identities(player) == ["tk1.seq", "tk2.seq"]
    assert player.sidebar_tabs.currentIndex() == 1
    assert dialogs.messages == []


# ---------------------------------------------------------------- 많은 프레임을 한꺼번에 놓기 (폴더 목록당 묶기 한 번)


def test_folder_frames_resolves_exactly_like_sequence_of_frame():
    names = ["a-0001.png", "a-0002.png", "a-0001.tga", "a-0002.tga", "b-0001.tga", "b-0002.tga", "b-0004.tga",
             "lone-0001.tga", "t-001.tga", "t-0001.tga", "a.mov", ".h-0001.tga", ".h-0002.tga"]
    index = FolderFrames("/j", names)
    probes = names + ["b-0003.tga", "zzz-0001.tga", "a-0003.png", "readme.txt", "a-0001.TGA"]

    for name in probes:
        assert index.sequence_of(name) == sequence_of_frame("/j", names, name), name
    assert index.sequences == group_sequences("/j", names)


def spy_group_sequences(monkeypatch):
    calls = []
    real = sequence_scan.group_sequences
    monkeypatch.setattr(sequence_scan, "group_sequences", lambda *args: (calls.append(args[0]), real(*args))[1])
    return calls


@pytest.mark.parametrize("target", ["video", "sidebar"])
def test_dropping_hundreds_of_frames_groups_the_folder_once(player, dialogs, tmp_path, monkeypatch, target):
    """렌더 한 벌을 통째로 놓는 것이 자연스러운 동작: 프레임 수만큼 폴더 목록을 묶으면 GUI가 얼음 (프레임 5,000장 -> 30초 이상) —
    폴더를 한 번 읽고 한 번 묶은 뒤 프레임마다는 찾아보기만 함. 시간이 아니라 호출 횟수로 지킴."""
    folder = tmp_path / "render"
    make_seq(str(folder), "big_tk1", range(1, 401))
    make_seq(str(folder), "big_tk2", range(1, 4))
    reads = []
    real_list = sequence_source.list_frame_names
    monkeypatch.setattr(sequence_source, "list_frame_names", lambda f: (reads.append(f), real_list(f))[1])
    groupings = spy_group_sequences(monkeypatch)
    dropped = [frame(folder, "big_tk1", n, ) for n in range(1, 401)] + [frame(folder, "big_tk2", 2)]

    drop_files(player, target, dropped)

    assert len(reads) == 1  # 폴더를 한 번 읽음
    assert len(groupings) == 1  # 그리고 한 번 묶음 (프레임 401장이어도)
    assert seq_identities(player) == ["big_tk1.seq", "big_tk2.seq"]  # 같은 시퀀스는 한 항목, 놓은 차례대로 찾음
    assert [item.data(Qt.UserRole).count for item in map(player.seq_sidebar.item, range(2))] == [400, 3]
    assert dialogs.messages == []


def test_dropping_frames_from_two_folders_groups_each_folder_once(player, dialogs, tmp_path, monkeypatch):
    first, second = tmp_path / "one", tmp_path / "two"
    make_seq(str(first), "tk1", range(1, 31))
    make_seq(str(second), "tk2", range(1, 31))
    groupings = spy_group_sequences(monkeypatch)

    drop_files(player, "sidebar", [frame(first, "tk1", n) for n in range(1, 31)] + [frame(second, "tk2", n) for n in range(1, 31)])

    assert sorted(groupings) == sorted([str(first), str(second)])
    assert seq_identities(player) == ["tk1.seq", "tk2.seq"]
