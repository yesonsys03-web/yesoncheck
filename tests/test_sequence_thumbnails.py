"""Seq 목록의 썸네일: 짝 mov(<base>.mov, 없으면 <base>.mp4)의 기존 썸네일을 그대로 읽어 씀 (이미지 디코드 0회, 요구사항 ⑨).

- Seq 목록은 읽기 전용 경량 경로 (SeqThumbnailLoaderWorker): 뒤 스레드가 짝 영상을 찾고 디스크의 썸네일을 읽어 아이콘만 붙임.
  만들기 반복·진행바 없음. 전역 표시 모드(List/Thumb)를 따름. Mov 목록의 썸네일 기계장치는 그대로.
- 짝 mov가 없을 때만 ThumbnailWorker가 첫 프레임을 decode_frame으로 디코드해 만듦 (새로움 기준 = 첫 프레임 파일 mtime).
- 시퀀스 프레임은 tests.test_sequence_capture.make_seq가 만든 작은 TGA. 예시 이름만 씀 (공개 저장소).
"""

import errno
import os
import time

import cv2
import pytest
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import QApplication

from tests.conftest import write_test_video
from tests.test_sequence_capture import color_for, make_seq
from tests.test_sidebar_refresh import choose, refresh, wait_refreshed
from tests.test_thumbnails import red_pixmap, wait_until
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import sequence_source, sidebar_sequences, thumbnail_workers, thumbnails
from yesoncheck.sequence_scan import group_sequences
from yesoncheck.sidebar_items import THUMBNAIL_CONTEXT_ROLE, ThumbnailContext

FAKE_MOVIE = b"not a movie: the Seq path must never open it"


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


# ---------------------------------------------------------------- 도우미


def seq_in(folder, base=None):
    """folder의 시퀀스 (base를 주면 그 이름의 것)."""
    found = group_sequences(str(folder), sorted(os.listdir(folder)))
    return next(seq for seq in found if base in (None, seq.base))


def make_shot(folder, base="tk1", nums=range(1, 7), movie="mov", real_movie=False):
    """folder에 시퀀스 <base>와 짝 영상(movie: 확장자, None이면 없음)을 만듦. 짝 영상은 기본이 가짜 바이트 (열면 안 되므로)."""
    folder = str(folder)
    make_seq(folder, base, nums)
    if movie is not None:
        path = os.path.join(folder, f"{base}.{movie}")
        if real_movie:
            write_test_video(path)
        else:
            with open(path, "wb") as fh:
                fh.write(FAKE_MOVIE)
    return folder


def put_thumbnail(thumb_folder, key_path, width=7, height=5, mtime=None):
    """key_path의 썸네일 파일을 만듦 (빨강 width x height JPEG)."""
    thumb = thumbnails.thumbnail_path(thumb_folder, key_path)
    assert red_pixmap(width, height).save(thumb, "JPG")
    if mtime is not None:
        os.utime(thumb, (mtime, mtime))
    return thumb


def run_loader(jobs):
    """SeqThumbnailLoaderWorker를 이 스레드에서 실행 → (읽은 [(identity, 폭)], 만들어야 할 [identity], 실패 [(폴더, 내용)])."""
    loaded, missing, failed = [], [], []
    worker = thumbnail_workers.SeqThumbnailLoaderWorker(jobs)
    worker.image_loaded.connect(lambda identity, image: loaded.append((identity, image.width())))
    worker.needs_generation.connect(missing.append)
    worker.failed.connect(lambda folder, detail: failed.append((folder, detail)))
    worker.run()
    return loaded, missing, failed


def run_generation(seq, thumb_folder, size=120):
    """폴백 생성: ThumbnailWorker(가상 경로, seq=...)를 이 스레드에서 실행 → (보낸 [(경로, QPixmap)], 실패 [내용])."""
    ready, failed = [], []
    worker = thumbnail_workers.ThumbnailWorker(seq.identity, size, thumb_folder, seq)
    worker.thumbnail_ready.connect(lambda path, pixmap: ready.append((path, pixmap)))
    worker.failed.connect(failed.append)
    worker.run()
    return ready, failed


def pump(ms=50):
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)


def jpgs(folder):
    return sorted(name for name in os.listdir(folder) if name.endswith(".jpg"))


def close_to(color, expected, tolerance=12):
    """color(QColor)가 expected(RGB 튜플)에 가까운지 (JPEG 손실 허용)."""
    return all(abs(a - b) <= tolerance for a, b in zip((color.red(), color.green(), color.blue()), expected))


def center_color(pixmap):
    image = pixmap.toImage()
    return QColor(image.pixel(image.width() // 2, image.height() // 2))


class DecodeCounter:
    """sequence_source.decode_frame 호출을 세고 진짜로도 부름 (워커가 모듈 속성으로 찾으므로 한 곳만 바꾸면 됨)."""

    def __init__(self, monkeypatch):
        self.calls = []
        real = sequence_source.decode_frame

        def counting(data, ext):
            self.calls.append(ext)
            return real(data, ext)

        monkeypatch.setattr(sequence_source, "decode_frame", counting)


class HangingLoader(thumbnail_workers.SeqThumbnailLoaderWorker):
    """멈추라는 알림이 올 때까지 도는 읽기 워커 (끊긴 NAS를 읽는 중인 것처럼)."""

    def run(self):
        while self._is_running:
            self.msleep(5)


def forbid_video_capture(monkeypatch):
    """영상(cv2.VideoCapture)을 열면 실패 — 영상도 디코드하지 않음을 보임."""
    def boom(*args, **kwargs):
        raise AssertionError(f"cv2.VideoCapture를 열면 안 됨: {args}")

    monkeypatch.setattr(cv2, "VideoCapture", boom)


# ---------------------------------------------------------------- 짝 영상 찾기


def test_pairing_prefers_mov_then_mp4_like_fps_pairing(tmp_path):
    """fps를 읽는 짝 영상(Task 4)과 같은 규칙: <base>.mov가 먼저, 없으면 <base>.mp4, 둘 다 없으면 None."""
    folder = tmp_path / "pairs"
    for name in ("both.mov", "both.mp4", "only_mp4.mp4", "upper.MOV", "other.mov", "not_a_pair-0001.mov"):
        os.makedirs(folder, exist_ok=True)
        (folder / name).write_bytes(FAKE_MOVIE)
    found = sequence_source.paired_movies(str(folder), {"both", "only_mp4", "upper", "none", "partial"})
    assert found == {
        "both": str(folder / "both.mov"),
        "only_mp4": str(folder / "only_mp4.mp4"),
        "upper": str(folder / "upper.MOV"),  # 확장자 대소문자는 가리지 않음 (fps 짝 찾기와 같음)
        "none": None,
        "partial": None,
    }


def test_pairing_agrees_with_the_fps_pairing_order(tmp_path):
    """두 영상이 다 있을 때 fps를 읽는 쪽이 고르는 영상(.mov)과 썸네일을 읽는 영상이 같다."""
    folder = tmp_path / "pairs"
    os.makedirs(folder)
    for name in ("tk1.mov", "tk1.mp4"):
        (folder / name).write_bytes(FAKE_MOVIE)
    _frames, paired = sequence_source._list_folder(str(folder), "tk1")
    fps_choice = next(ext for ext in sequence_source.PAIRED_MOVIE_EXTS if ext in paired)
    thumbnail_choice = sequence_source.paired_movies(str(folder), {"tk1"})["tk1"]
    assert os.path.splitext(thumbnail_choice)[1][1:] == fps_choice == "mov"


def test_pairing_does_not_pair_folders_named_like_a_movie(tmp_path):
    (tmp_path / "tk1.mov").mkdir()
    assert sequence_source.paired_movies(str(tmp_path), {"tk1"}) == {"tk1": None}


# ---------------------------------------------------------------- 썸네일 경로 = 짝 mov의 썸네일 경로


def test_seq_thumbnail_path_equals_paired_mov_thumbnail(qapp, tmp_path):
    """Seq 항목의 썸네일 파일은 짝 mov의 썸네일 파일 그 자체: 같은 키(md5)라 새 파일이 생기지 않고 NAS를 같이 쓰는 PC도 그대로 읽음."""
    job = make_shot(tmp_path / "job", real_movie=True)
    movie = os.path.join(job, "tk1.mov")
    seq = seq_in(job)
    thumb_folder = thumbnails.ensure_folder(job)

    # 기존 Mov 흐름(ThumbnailWorker)이 영상의 썸네일을 만듦
    mov_worker = thumbnail_workers.ThumbnailWorker(movie, 120, thumb_folder)
    mov_worker.run()
    made = jpgs(thumb_folder)
    assert made == [os.path.basename(thumbnails.thumbnail_path(thumb_folder, movie))]

    key_path, source = thumbnail_workers.seq_thumbnail_files(seq, movie)
    assert (key_path, source) == (movie, movie)
    assert thumbnails.thumbnail_path(thumb_folder, key_path) == thumbnails.thumbnail_path(thumb_folder, movie)

    loaded, missing, failed = run_loader([(seq, thumb_folder)])
    assert loaded == [(seq.identity, 120)] and missing == [] and failed == []
    assert jpgs(thumb_folder) == made  # 새 썸네일 파일을 만들지 않음


def test_seq_without_movie_is_keyed_by_its_virtual_path_and_first_frame(qapp, tmp_path):
    job = make_shot(tmp_path / "job", movie=None)
    seq = seq_in(job)
    key_path, source = thumbnail_workers.seq_thumbnail_files(seq, None)
    assert key_path == seq.identity
    assert source == os.path.join(job, "tk1-0001.tga")


# ---------------------------------------------------------------- 디코드 0회


def test_existing_mov_thumbnail_reused_without_decode(qapp, tmp_path, monkeypatch):
    """짝 mov의 썸네일이 있으면 디스크의 jpg를 읽기만 함: 프레임 디코드 0회, 영상 열기 0회 (짝 영상은 열 수 없는 가짜 파일)."""
    job = make_shot(tmp_path / "job")
    seq = seq_in(job)
    thumb_folder = thumbnails.ensure_folder(job)
    put_thumbnail(thumb_folder, os.path.join(job, "tk1.mov"), width=40, height=30)
    counter = DecodeCounter(monkeypatch)
    forbid_video_capture(monkeypatch)

    loaded, missing, failed = run_loader([(seq, thumb_folder)])

    assert loaded == [(seq.identity, 40)] and missing == [] and failed == []
    assert counter.calls == []


def test_paired_mp4_thumbnail_is_reused_too(qapp, tmp_path, monkeypatch):
    job = make_shot(tmp_path / "job", movie="mp4")
    seq = seq_in(job)
    thumb_folder = thumbnails.ensure_folder(job)
    put_thumbnail(thumb_folder, os.path.join(job, "tk1.mp4"), width=40, height=30)
    counter = DecodeCounter(monkeypatch)
    assert run_loader([(seq, thumb_folder)]) == ([(seq.identity, 40)], [], [])
    assert counter.calls == []


def test_paired_movie_without_thumbnail_is_left_to_the_mov_tab(qapp, tmp_path, monkeypatch):
    """짝 mov가 있는데 썸네일이 아직 없으면 Seq 쪽은 아무것도 만들지 않음 (생성은 Mov 탭의 일 — 만들기 반복·진행바가 없는 경량 경로)."""
    job = make_shot(tmp_path / "job")
    seq = seq_in(job)
    thumb_folder = thumbnails.ensure_folder(job)
    counter = DecodeCounter(monkeypatch)
    forbid_video_capture(monkeypatch)

    assert run_loader([(seq, thumb_folder)]) == ([], [], [])
    assert counter.calls == [] and jpgs(thumb_folder) == []


def test_stale_paired_thumbnail_is_not_shown(qapp, tmp_path):
    """다시 렌더링한 영상(썸네일보다 새 영상)의 옛 썸네일은 보여 주지 않음 — Mov 탭이 새로 만든 뒤에 읽음."""
    job = make_shot(tmp_path / "job")
    seq = seq_in(job)
    thumb_folder = thumbnails.ensure_folder(job)
    movie = os.path.join(job, "tk1.mov")
    base = time.time() - 1000
    os.utime(movie, (base, base))
    put_thumbnail(thumb_folder, movie, mtime=base - 10)
    assert run_loader([(seq, thumb_folder)]) == ([], [], [])
    os.utime(movie, (base - 20, base - 20))
    assert run_loader([(seq, thumb_folder)])[0] == [(seq.identity, 7)]


# ---------------------------------------------------------------- 짝 mov가 없으면 첫 프레임 디코드 폴백


def test_no_paired_mov_falls_back_to_first_frame_decode(qapp, tmp_path, monkeypatch):
    """짝 영상이 없는 시퀀스: 읽기 경로는 '만들어야 함'만 알리고, ThumbnailWorker가 가장 작은 번호의 프레임 파일을 decode_frame으로
    디코드해 가상 경로의 키로 저장함 (영상은 열지 않음)."""
    job = make_shot(tmp_path / "job", nums=range(101, 107), movie=None)  # 시작 번호가 0001이 아님
    seq = seq_in(job)
    thumb_folder = thumbnails.ensure_folder(job)
    counter = DecodeCounter(monkeypatch)
    forbid_video_capture(monkeypatch)

    assert run_loader([(seq, thumb_folder)]) == ([], [seq.identity], [])
    assert counter.calls == []  # 읽기 경로는 디코드하지 않음

    ready, failed = run_generation(seq, thumb_folder)

    assert failed == []
    assert counter.calls == ["tga"]  # 첫 프레임 한 장만
    assert [path for path, _pixmap in ready] == [seq.identity]
    pixmap = ready[0][1]
    assert pixmap.width() == 120 and close_to(center_color(pixmap), color_for(101))  # 0101번 프레임의 색
    saved = thumbnails.thumbnail_path(thumb_folder, seq.identity)
    assert jpgs(thumb_folder) == [os.path.basename(saved)]
    assert close_to(center_color(QPixmap(saved)), color_for(101))
    # 만든 뒤에는 읽기 경로가 그대로 씀 (디코드 없이)
    assert run_loader([(seq, thumb_folder)]) == ([(seq.identity, 120)], [], [])
    assert counter.calls == ["tga"]


def test_generation_failure_is_reported_with_stack_trace(qapp, tmp_path):
    """첫 프레임이 깨졌으면 삼키지 않고 스택 트레이스째 failed 신호로."""
    job = make_shot(tmp_path / "job", movie=None)
    seq = seq_in(job)
    with open(os.path.join(job, "tk1-0001.tga"), "wb") as fh:
        fh.write(b"broken")
    thumb_folder = thumbnails.ensure_folder(job)
    ready, failed = run_generation(seq, thumb_folder)
    assert ready == [] and len(failed) == 1
    assert "Traceback" in failed[0] and "ValueError" in failed[0] and seq.identity in failed[0]
    assert jpgs(thumb_folder) == []


def test_corrupt_thumbnail_of_a_sequence_without_movie_is_remade(qapp, tmp_path):
    job = make_shot(tmp_path / "job", movie=None)
    seq = seq_in(job)
    thumb_folder = thumbnails.ensure_folder(job)
    thumb = thumbnails.thumbnail_path(thumb_folder, seq.identity)
    with open(thumb, "wb") as fh:
        fh.write(b"not a jpeg")
    assert run_loader([(seq, thumb_folder)]) == ([], [seq.identity], [])  # 읽을 수 없음 → 만들어야 함
    ready, failed = run_generation(seq, thumb_folder)
    assert failed == [] and ready[0][1].width() == 120
    assert QPixmap(thumb).width() == 120


# ---------------------------------------------------------------- 새로움: 첫 프레임 파일의 mtime


def test_seq_thumb_freshness_uses_first_frame_mtime(qapp, tmp_path, monkeypatch):
    """시퀀스의 '원본 mtime'은 첫 프레임 파일의 것 (폴더 mtime은 프레임을 다시 렌더링해도 안 바뀜; 다른 프레임도 상관없음)."""
    job = make_shot(tmp_path / "job", movie=None)
    seq = seq_in(job)
    thumb_folder = thumbnails.ensure_folder(job)
    thumb = put_thumbnail(thumb_folder, seq.identity, mtime=None)
    first = os.path.join(job, "tk1-0001.tga")
    last = os.path.join(job, "tk1-0006.tga")
    base = time.time() - 1000
    os.utime(thumb, (base, base))

    os.utime(first, (base - 10, base - 10))  # 첫 프레임이 썸네일보다 오래됨
    os.utime(last, (base + 500, base + 500))  # 다른 프레임이 새것이어도
    os.utime(job, (base + 500, base + 500))  # 폴더가 새것이어도
    assert run_loader([(seq, thumb_folder)]) == ([(seq.identity, 7)], [], [])  # 썸네일을 그대로 씀
    counter = DecodeCounter(monkeypatch)
    ready, _failed = run_generation(seq, thumb_folder)
    assert (ready[0][1].width(), counter.calls) == (7, [])  # 워커도 새 썸네일을 그대로 씀 (디코드 없음)

    os.utime(first, (base + 10, base + 10))  # 첫 프레임을 다시 렌더링함
    assert run_loader([(seq, thumb_folder)]) == ([], [seq.identity], [])
    ready, failed = run_generation(seq, thumb_folder)
    assert failed == [] and ready[0][1].width() == 120 and counter.calls == ["tga"]
    assert thumbnails.is_fresh(thumb, first)


def test_first_frame_path_finds_the_real_name_on_case_sensitive_filesystems(tmp_path, monkeypatch):
    """확장자 대소문자가 다른 프레임(.TGA)은 대소문자를 가리는 파일 시스템(NFS 마운트)에서 소문자 이름으로 열리지 않음 → 폴더에서 실제 이름을 찾음."""
    folder = str(tmp_path / "caps")
    make_seq(folder, "tk1", [1, 2, 3])
    for n in (1, 2, 3):
        os.rename(os.path.join(folder, f"tk1-{n:04d}.tga"), os.path.join(folder, f"tk1-{n:04d}.TGA"))
    seq = seq_in(folder)
    assert seq.ext == "tga"
    real_stat = os.stat
    lowercase = os.path.join(folder, "tk1-0001.tga")

    def case_sensitive_stat(path, *args, **kwargs):
        if os.fspath(path) == lowercase:
            raise FileNotFoundError(2, "No such file or directory", lowercase)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(sequence_source.os, "stat", case_sensitive_stat)
    assert sequence_source.first_frame_path(seq) == os.path.join(folder, "tk1-0001.TGA")
    monkeypatch.undo()
    assert os.path.basename(sequence_source.first_frame_path(seq)).lower() == "tk1-0001.tga"


def test_first_frame_path_raises_when_the_first_frame_is_gone(tmp_path):
    folder = str(tmp_path / "gone")
    make_seq(folder, "tk1", [1, 2, 3])
    seq = seq_in(folder)
    os.remove(os.path.join(folder, "tk1-0001.tga"))
    with pytest.raises(FileNotFoundError):
        sequence_source.first_frame_path(seq)


# ---------------------------------------------------------------- 한글·공백 경로 [Review Focus 2]


def test_korean_space_path_thumbnail(qapp, tmp_path, monkeypatch):
    """한글·공백이 섞인 폴더·이름: 짝 mov 썸네일 재사용(디코드 0회)과 첫 프레임 폴백(바이트로 읽어 디코드 — Windows 안전)이 모두 됨."""
    job = os.path.join(str(tmp_path), "한 글 작품", "샷 폴더 01")
    make_shot(job, base="샷 컷_tk1")
    make_shot(job, base="샷 컷_tk2", movie=None)
    seq_with_movie = seq_in(job, "샷 컷_tk1")
    seq_alone = seq_in(job, "샷 컷_tk2")
    thumb_folder = thumbnails.ensure_folder(job)
    movie = os.path.join(job, "샷 컷_tk1.mov")
    counter = DecodeCounter(monkeypatch)
    forbid_video_capture(monkeypatch)

    assert thumbnail_workers.seq_thumbnail_files(seq_with_movie, movie)[0] == movie
    put_thumbnail(thumb_folder, movie, width=40, height=30)
    assert run_loader([(seq_with_movie, thumb_folder)]) == ([(seq_with_movie.identity, 40)], [], [])
    assert counter.calls == []

    assert run_loader([(seq_alone, thumb_folder)]) == ([], [seq_alone.identity], [])
    ready, failed = run_generation(seq_alone, thumb_folder)
    assert failed == [] and ready[0][0] == seq_alone.identity and ready[0][1].width() == 120
    assert counter.calls == ["tga"]
    assert os.path.exists(thumbnails.thumbnail_path(thumb_folder, seq_alone.identity))


# ---------------------------------------------------------------- 읽기 실패는 삼키지 않음


def test_loader_reports_unreadable_folder_with_stack_trace_and_goes_on(qapp, tmp_path):
    job = make_shot(tmp_path / "job")
    seq = seq_in(job)
    thumb_folder = thumbnails.ensure_folder(job)
    put_thumbnail(thumb_folder, os.path.join(job, "tk1.mov"), width=40, height=30)
    gone = group_sequences(str(tmp_path / "removed"), ["x-0001.tga", "x-0002.tga"])[0]  # 폴더가 사라진 시퀀스

    loaded, missing, failed = run_loader([(gone, thumb_folder), (seq, thumb_folder)])

    assert loaded == [(seq.identity, 40)]  # 한 곳의 실패가 나머지를 막지 않음
    assert missing == []
    assert len(failed) == 1
    folder, detail = failed[0]
    assert folder == thumb_folder
    assert "Traceback" in detail and "FileNotFoundError" in detail and str(tmp_path / "removed") in detail


def test_loader_reports_a_vanished_first_frame_with_stack_trace(qapp, tmp_path):
    """읽는 사이 첫 프레임 파일이 사라진 시퀀스도 스택 트레이스째 알리고 나머지는 이어서 읽음."""
    job = make_shot(tmp_path / "job", movie=None)
    other = make_shot(tmp_path / "job", base="tk2", movie="mov")
    seq, with_movie = seq_in(job, "tk1"), seq_in(job, "tk2")
    thumb_folder = thumbnails.ensure_folder(job)
    put_thumbnail(thumb_folder, os.path.join(other, "tk2.mov"), width=40, height=30)
    os.remove(os.path.join(job, "tk1-0001.tga"))

    loaded, missing, failed = run_loader([(seq, thumb_folder), (with_movie, thumb_folder)])

    assert loaded == [(with_movie.identity, 40)] and missing == []
    assert len(failed) == 1
    assert failed[0][0] == thumb_folder
    assert "Traceback" in failed[0][1] and "FileNotFoundError" in failed[0][1] and seq.identity in failed[0][1]


def test_loader_stop_ends_the_pass(qapp, tmp_path):
    job = make_shot(tmp_path / "job")
    seq = seq_in(job)
    thumb_folder = thumbnails.ensure_folder(job)
    put_thumbnail(thumb_folder, os.path.join(job, "tk1.mov"))
    worker = thumbnail_workers.SeqThumbnailLoaderWorker([(seq, thumb_folder)])
    loaded = []
    worker.image_loaded.connect(lambda identity, image: loaded.append(identity))
    worker.stop()
    worker.run()
    assert loaded == []


# ---------------------------------------------------------------- 창: 전역 표시 모드를 따름


def shot_in_player(player, tmp_path, **options):
    """작업 폴더를 불러옴 (Mov 목록 + Seq 목록, 썸네일 폴더 = <폴더>/.yesoncheck_thumb) → 폴더. 짝 영상은 열 수 있는 진짜 영상."""
    options.setdefault("real_movie", True)
    folder = make_shot(tmp_path / "shot", **options)
    player.load_videos_from_folder(folder)
    return folder


def seq_icon_loaded(player, row=0):
    return not player.seq_sidebar.item(row).icon().isNull()


def seq_work_done(player):
    return not player._seq_thumbnail_workers and not player._seq_generation_queue


def test_list_mode_loads_no_seq_thumbnails(player, tmp_path, monkeypatch):
    folder = shot_in_player(player, tmp_path)
    put_thumbnail(player.current_thumbnail_folder, os.path.join(folder, "tk1.mov"))
    assert player.is_thumbnail_mode is False
    player._load_seq_thumbnails()
    assert player._seq_thumbnail_workers == [] and not seq_icon_loaded(player)


def test_thumb_button_shows_paired_mov_thumbnails_without_decoding(player, tmp_path, monkeypatch):
    """Thumb 단추 → Mov 쪽은 늘 하던 대로, Seq 목록은 짝 mov의 디스크 썸네일을 뒤 스레드로 읽어 아이콘만 붙임 (디코드 0회)."""
    folder = shot_in_player(player, tmp_path)
    put_thumbnail(player.current_thumbnail_folder, os.path.join(folder, "tk1.mov"), width=40, height=30)
    counter = DecodeCounter(monkeypatch)
    forbid_video_capture(monkeypatch)

    player.thumbnailModeButton.click()

    wait_until(lambda: seq_icon_loaded(player) and seq_work_done(player))
    assert counter.calls == []
    assert player.seq_sidebar.item(0).icon().availableSizes()[0] == QSize(40, 30)
    assert player.seq_sidebar.iconSize() == QSize(player.thumbnail_size, player.thumbnail_size)
    assert player.seq_sidebar.spacing() == 10
    assert jpgs(player.current_thumbnail_folder) == [
        os.path.basename(thumbnails.thumbnail_path(player.current_thumbnail_folder, os.path.join(folder, "tk1.mov")))]


def test_list_button_clears_seq_icons(player, tmp_path):
    folder = shot_in_player(player, tmp_path)
    put_thumbnail(player.current_thumbnail_folder, os.path.join(folder, "tk1.mov"))
    player.thumbnailModeButton.click()
    wait_until(lambda: seq_icon_loaded(player) and seq_work_done(player))

    player.listModeButton.click()

    assert not seq_icon_loaded(player)
    assert player.seq_sidebar.spacing() == 0
    assert player._seq_thumbnail_workers == [] and player._seq_generation_queue == []


def test_mov_generation_then_seq_reuses_what_the_mov_tab_made(player, tmp_path):
    """통합: Mov 탭이 영상의 썸네일을 만들고 (기존 흐름), Seq 목록은 그 파일을 그대로 읽음 — 새 썸네일 파일이 늘지 않음."""
    folder = shot_in_player(player, tmp_path)
    thumb_folder = player.current_thumbnail_folder

    player.thumbnailModeButton.click()
    wait_until(lambda: not player.thumbnail_workers)  # Mov 탭의 만들기가 끝남
    assert len(jpgs(thumb_folder)) == 1
    player.sidebar_tabs.setCurrentIndex(1)  # Seq 탭을 보면 그 사이 생긴 썸네일도 읽음

    wait_until(lambda: seq_icon_loaded(player) and seq_work_done(player))
    assert len(jpgs(thumb_folder)) == 1
    assert player.seq_sidebar.item(0).icon().availableSizes()[0].width() == player.thumbnail_size


def test_tab_switch_in_thumbnail_mode_rereads_thumbnails_in_background(player, tmp_path):
    """Mov 탭이 썸네일을 만든 뒤(또는 다른 PC가 바꾼 뒤) Seq 탭을 보면 새 썸네일을 읽어 아이콘을 바꿈."""
    folder = shot_in_player(player, tmp_path)
    player.thumbnailModeButton.click()
    wait_until(lambda: not player.thumbnail_workers and seq_work_done(player))  # Mov 탭의 만들기와 첫 읽기가 끝남
    movie = os.path.join(folder, "tk1.mov")
    put_thumbnail(player.current_thumbnail_folder, movie, width=33, height=22)  # 그 뒤에 바뀐 썸네일

    player.sidebar_tabs.setCurrentIndex(1)

    wait_until(lambda: seq_icon_loaded(player) and seq_work_done(player)
               and player.seq_sidebar.item(0).icon().availableSizes()[0] == QSize(33, 22))


def test_pass_started_while_the_mov_tab_is_still_making_thumbnails_is_repeated_after(player, tmp_path, monkeypatch):
    """Thumb 단추 직후처럼 Mov 탭이 아직 썸네일을 만드는 중에 시작한 읽기는, 그 사이 생기는 짝 영상 썸네일을 놓치지 않게
    만들기가 끝난 뒤 한 번 더 읽음 (끝나길 기다리는 동안 디스크를 읽지 않음)."""
    import yesoncheck.sidebar_sequences as sidebar_sequences

    monkeypatch.setattr(sidebar_sequences, "SEQ_FOLLOWUP_MS", 20)
    folder = shot_in_player(player, tmp_path)
    movie = os.path.join(folder, "tk1.mov")
    player.is_thumbnail_mode = True
    busy = object()  # Mov 탭의 만드는 중인 워커 (목록에 있는지만 봄)
    player.thumbnail_workers.append(busy)
    try:
        player._load_seq_thumbnails()
        wait_until(lambda: seq_work_done(player))
        assert not seq_icon_loaded(player)  # 짝 영상의 썸네일이 아직 없음
        put_thumbnail(player.current_thumbnail_folder, movie, width=33, height=22)  # Mov 탭이 만들어 냄
        pump(150)
        assert player._seq_thumbnail_timer.isActive() and player._seq_thumbnail_workers == []  # 아직 만드는 중: 기다리기만
        assert not seq_icon_loaded(player)
    finally:
        player.thumbnail_workers.remove(busy)  # Mov 탭의 만들기가 끝남

    wait_until(lambda: seq_icon_loaded(player) and seq_work_done(player))
    assert player.seq_sidebar.item(0).icon().availableSizes()[0] == QSize(33, 22)
    assert not player._seq_thumbnail_timer.isActive()  # 한 번 더 읽은 뒤에는 또 예약하지 않음


def test_pass_started_while_the_mov_tab_is_idle_is_not_repeated(player, tmp_path):
    shot_in_player(player, tmp_path)
    player.is_thumbnail_mode = True
    player._load_seq_thumbnails()
    assert not player._seq_thumbnail_timer.isActive()
    wait_until(lambda: seq_work_done(player))


def test_tab_switch_in_list_mode_starts_nothing(player, tmp_path):
    shot_in_player(player, tmp_path)
    player.sidebar_tabs.setCurrentIndex(1)
    assert player._seq_thumbnail_workers == []


def test_new_seq_list_in_thumbnail_mode_gets_icons(player, tmp_path):
    """썸네일 모드에서 목록이 바뀌면 (다른 폴더를 불러옴·다시 읽기) 새 항목의 썸네일도 읽음."""
    player.thumbnailModeButton.click()
    folder = shot_in_player(player, tmp_path)
    put_thumbnail(player.current_thumbnail_folder, os.path.join(folder, "tk1.mov"), width=40, height=30)
    player._set_seq_items([])
    player._set_seq_items([seq_in(folder)])
    wait_until(lambda: seq_icon_loaded(player) and seq_work_done(player))


def test_sequence_only_folder_makes_first_frame_thumbnails_in_thumbnail_mode(player, tmp_path, monkeypatch):
    """짝 영상이 없는 폴더(시퀀스만): 썸네일 모드에서 첫 프레임으로 만들어 그 폴더의 .yesoncheck_thumb에 저장 (한 번에 하나씩)."""
    folder = str(tmp_path / "only")
    make_seq(folder, "tk1", range(1, 7))
    make_seq(folder, "tk2", range(1, 4))
    forbid_video_capture(monkeypatch)
    player.thumbnailModeButton.click()

    player.load_videos_from_folder(folder)

    wait_until(lambda: seq_icon_loaded(player, 0) and seq_icon_loaded(player, 1) and seq_work_done(player))
    thumb_folder = os.path.join(folder, thumbnails.FOLDER_NAME)
    expected = sorted(os.path.basename(thumbnails.thumbnail_path(thumb_folder, seq.identity))
                      for seq in (seq_in(folder, "tk1"), seq_in(folder, "tk2")))
    assert jpgs(thumb_folder) == expected
    assert player.seq_sidebar.item(0).icon().availableSizes()[0].width() == player.thumbnail_size


def test_sequence_only_folder_writes_into_its_own_thumbnail_folder_not_the_previous_jobs(player, tmp_path):
    """영상이 있는 폴더(job처럼)를 연 다음 시퀀스만 든 폴더를 고르면, 첫 프레임 썸네일은 전에 연 폴더의 .yesoncheck_thumb가 아니라
    고른 폴더의 .yesoncheck_thumb에 저장됨 (전에 연 폴더의 썸네일 폴더가 남아 엉뚱한 곳에 쓰던 문제)."""
    shot_in_player(player, tmp_path)
    previous = player.current_thumbnail_folder
    player.thumbnailModeButton.click()
    wait_until(lambda: not player.thumbnail_workers and seq_work_done(player))
    before = jpgs(previous)
    only = str(tmp_path / "only")
    make_seq(only, "tk1", range(1, 7))

    player.load_videos_from_folder(only)

    wait_until(lambda: seq_icon_loaded(player) and seq_work_done(player))
    own = os.path.join(only, thumbnails.FOLDER_NAME)
    assert jpgs(own) == [os.path.basename(thumbnails.thumbnail_path(own, seq_in(only).identity))]
    assert jpgs(previous) == before  # 전에 연 폴더의 썸네일 폴더는 그대로
    assert player.seq_sidebar.item(0).data(THUMBNAIL_CONTEXT_ROLE) == ThumbnailContext(folder=own)


def test_sequence_only_folder_forgets_the_previous_jobs_thumbnail_folder_problem(player, tmp_path):
    """전에 연 폴더의 썸네일 폴더 문제(그 폴더는 화면에만 저장)가 시퀀스만 든 새 폴더의 항목에 남지 않음."""
    only = str(tmp_path / "only")
    make_seq(only, "tk1", range(1, 7))
    player.current_thumbnail_folder = None
    player._thumbnail_folder_problem = (str(tmp_path / "gone" / thumbnails.FOLDER_NAME), "썸네일 폴더 문제", "만들지 못함")

    player.load_videos_from_folder(only)

    assert player.seq_sidebar.item(0).data(THUMBNAIL_CONTEXT_ROLE) == ThumbnailContext(pending_base=only)
    assert player._thumbnail_folder_problem is None


def test_job_with_only_sequences_uses_the_jobs_thumbnail_folder(new_player, dialogs, work_area):
    """job 목록 경로는 영상이 없어도 job을 열 때마다 썸네일 폴더를 job 것으로 새로 정함 — 전에 연 곳의 것이 남지 않음 (남지 않는 까닭을 시험으로)."""
    frames = os.path.join(work_area.local, "S1", "job_01", "scene-001", "frames")
    make_seq(frames, "FL_001_tk1", range(1, 7))
    player = new_player(make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map))
    stale = os.path.join(work_area.local, "elsewhere", thumbnails.FOLDER_NAME)
    player.current_thumbnail_folder = stale
    player._thumbnail_folder_problem = None
    player.workComboBox.setCurrentText("SMOKE")
    player.seasonComboBox.setCurrentText("S1")

    player.jobComboBox.setCurrentText("job_01")

    assert player.sidebar.count() == 0 and player.seq_sidebar.count() == 1
    # 앱이 보는 경로로 견줌: Windows CI에서는 파일을 로컬 경로로 만들지만 앱은 같은 공유를 UNC로 읽음 (같은 폴더인지는 samefile로)
    job_thumbs = os.path.join(player.current_job_path, thumbnails.FOLDER_NAME)
    assert os.path.samefile(job_thumbs, os.path.join(work_area.local, "S1", "job_01", thumbnails.FOLDER_NAME))
    assert player.current_thumbnail_folder == job_thumbs != stale
    assert player.seq_sidebar.item(0).data(THUMBNAIL_CONTEXT_ROLE) == ThumbnailContext(folder=job_thumbs)


def test_refresh_gives_new_sequences_the_recorded_context_of_their_source_job(new_player, dialogs, work_area, monkeypatch):
    """job을 고를 때 job 폴더를 확인하지 못해(NAS 끊김) 그 job만 기억해 둔 채 일찍 끝나면, 전에 연 job의 썸네일 폴더가 그대로 남음.
    연결이 돌아와 새로고침이 시퀀스를 찾으면 Mov 항목처럼 그 job이 기억한 자리를 쓰므로 첫 프레임 썸네일은 그 job의 .yesoncheck_thumb에
    저장됨 (전에 연 job의 것이 아니라)."""
    first = os.path.join(work_area.local, "S1", "job_01", "scene-001", "frames")
    write_test_video(os.path.join(first, "FL_001.mov"))
    second = os.path.join(work_area.local, "S1", "job_02", "scene-001", "frames")
    make_seq(second, "FL_002_tk1", range(1, 7))
    player = new_player(make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map))
    player.workComboBox.setCurrentText("SMOKE")
    player.seasonComboBox.setCurrentText("S1")
    player.jobComboBox.setCurrentText("job_01")
    first_thumbs = player.current_thumbnail_folder
    # 앱이 보는 경로(Windows CI에서는 UNC)로 견주고, 로컬 경로의 그 폴더와 같은지는 samefile로
    assert first_thumbs == os.path.join(player.current_job_path, thumbnails.FOLDER_NAME)
    assert os.path.samefile(first_thumbs, os.path.join(work_area.local, "S1", "job_01", thumbnails.FOLDER_NAME))
    first_jpgs = jpgs(first_thumbs)
    real_stat = os.stat
    down = {"on": True}

    def stat(path, *args, **kwargs):
        if down["on"] and os.path.basename(os.path.normpath(os.fspath(path))) == "job_02":
            raise TimeoutError(errno.ETIMEDOUT, "Operation timed out", os.fspath(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    choose(player, "job_02")
    wait_refreshed(player)
    assert player.seq_sidebar.count() == 0
    assert player.current_thumbnail_folder == first_thumbs  # 일찍 끝나 전에 연 job의 썸네일 폴더가 남아 있음

    down["on"] = False
    player.thumbnailModeButton.click()
    refresh(player)  # 연결이 돌아옴: 시퀀스가 목록에 들어옴

    wait_until(lambda: seq_icon_loaded(player) and seq_work_done(player))
    own = os.path.join(work_area.local, "S1", "job_02", thumbnails.FOLDER_NAME)  # 로컬 경로: 폴더 안을 읽기만 함
    app_identity = player.seq_sidebar.item(0).data(Qt.UserRole).identity  # 썸네일 이름은 앱이 보는 경로로 지어짐
    assert jpgs(own) == [os.path.basename(thumbnails.thumbnail_path(own, app_identity))]
    assert jpgs(first_thumbs) == first_jpgs  # 전에 연 job의 썸네일 폴더는 그대로
    context = player.seq_sidebar.item(0).data(THUMBNAIL_CONTEXT_ROLE)
    assert context == ThumbnailContext(folder=context.folder)  # 문제·미정 없이 폴더만
    assert os.path.samefile(context.folder, own) and not os.path.samefile(context.folder, first_thumbs)  # job_02 것 (앱이 보는 경로)


def test_refresh_gives_sequences_that_appear_in_an_empty_folder_that_folders_context(player, tmp_path):
    """영상도 시퀀스도 없던 폴더를 연 뒤(썸네일 폴더 초기화 없음) 그 폴더에 시퀀스가 생겨 새로고침이 찾으면, 전에 연 폴더가 아니라 그 폴더의
    .yesoncheck_thumb에 저장됨."""
    shot_in_player(player, tmp_path)
    previous = player.current_thumbnail_folder
    player.thumbnailModeButton.click()
    wait_until(lambda: not player.thumbnail_workers and seq_work_done(player))
    before = jpgs(previous)
    empty = str(tmp_path / "empty")
    os.makedirs(empty)
    player.load_videos_from_folder(empty)  # 영상도 시퀀스도 없음 (경고 창은 가로채임)
    assert player.current_thumbnail_folder == previous  # 초기화하지 않음
    make_seq(empty, "tk1", range(1, 7))

    refresh(player)

    wait_until(lambda: seq_icon_loaded(player) and seq_work_done(player))
    own = os.path.join(empty, thumbnails.FOLDER_NAME)
    assert jpgs(own) == [os.path.basename(thumbnails.thumbnail_path(own, seq_in(empty).identity))]
    assert jpgs(previous) == before
    assert player.seq_sidebar.item(0).data(THUMBNAIL_CONTEXT_ROLE) == ThumbnailContext(folder=own)


def test_refresh_keeps_the_context_of_sequences_already_in_the_list(player, tmp_path):
    """이미 목록에 있는 시퀀스는 다시 읽어도 그 항목의 자리 그대로 (출처가 기억한 자리는 새 시퀀스에만 — Mov 항목의 규칙)."""
    folder = shot_in_player(player, tmp_path)
    own = player.current_thumbnail_folder
    kept = ThumbnailContext(folder=str(tmp_path / "kept" / thumbnails.FOLDER_NAME))
    player.seq_sidebar.item(0).setData(THUMBNAIL_CONTEXT_ROLE, kept)  # 이 항목은 다른 자리를 기억함
    player.current_thumbnail_folder = str(tmp_path / "elsewhere" / thumbnails.FOLDER_NAME)
    make_seq(folder, "tk9", range(1, 4))  # 새 시퀀스가 생김 -> 목록이 바뀌어 다시 만들어짐

    refresh(player)

    contexts = {player.seq_sidebar.item(i).data(Qt.UserRole).base: player.seq_sidebar.item(i).data(THUMBNAIL_CONTEXT_ROLE)
                for i in range(player.seq_sidebar.count())}
    assert set(contexts) == {"tk1", "tk9"}
    assert contexts["tk1"] == kept  # 이미 있던 것: 그 항목의 자리
    assert contexts["tk9"] == ThumbnailContext(folder=own)  # 새것: 이 폴더를 불러올 때 기억한 출처의 자리 (지금 상태의 자리가 아님)


def test_fallback_generation_waits_for_thumbnail_mode(player, tmp_path):
    """목록 모드에서는 읽지도 만들지도 않음 (폴더에 .yesoncheck_thumb도 만들지 않음)."""
    folder = str(tmp_path / "only")
    make_seq(folder, "tk1", range(1, 7))
    player.load_videos_from_folder(folder)
    pump()
    assert player._seq_thumbnail_workers == [] and player._seq_generation_queue == []
    assert not os.path.exists(os.path.join(folder, thumbnails.FOLDER_NAME))


def test_list_button_stops_running_and_queued_seq_thumbnail_work(player):
    """목록 모드로 바꾸면 읽던 일은 멈추고(결과 버림) 만들 대기열은 비움 — 목록 모드에서 아이콘이 붙거나 파일이 만들어지지 않게."""
    from yesoncheck import worker_lifecycle

    player.thumbnailModeButton.click()
    worker = HangingLoader([])
    player._start_seq_worker(worker)
    player._seq_generation_queue.append(("x.seq", "x.seq", None, ThumbnailContext()))
    player._seq_thumbnail_timer.start(10_000)  # Mov 탭을 기다리는 중
    wait_until(worker.isRunning)

    player.listModeButton.click()

    assert not player._seq_thumbnail_timer.isActive()
    assert worker._is_running is False and worker.signalsBlocked()
    assert player._seq_thumbnail_workers == [] and player._seq_generation_queue == []
    assert worker_lifecycle.wait_for_released_workers(5) == []


def test_missing_thumbnail_is_queued_once(player, tmp_path):
    """탭을 오가며 다시 읽어 같은 시퀀스를 또 알려도 만들 대기열에는 한 번."""
    folder = str(tmp_path / "only")
    for base in ("a", "b"):
        make_seq(folder, base, range(1, 4))
    player.load_videos_from_folder(folder)  # 목록 모드: 읽기·만들기 없음
    player.thumbnailModeButton.click()
    player._stop_seq_thumbnail_work()
    a, b = (seq.identity for seq in (seq_in(folder, "a"), seq_in(folder, "b")))

    player._on_seq_thumbnail_missing(a)  # 바로 만들기 시작
    player._on_seq_thumbnail_missing(b)  # 기다림
    player._on_seq_thumbnail_missing(b)  # 이미 기다리는 중

    assert [job[0] for job in player._seq_generation_queue] == [b]
    wait_until(lambda: seq_work_done(player))
    assert len(jpgs(os.path.join(folder, thumbnails.FOLDER_NAME))) == 2


# ---------------------------------------------------------------- 항목의 썸네일 자리 (ThumbnailContext)


def test_seq_items_remember_their_thumbnail_context(player, tmp_path):
    """Mov 항목처럼 넣을 때의 썸네일 자리를 기억 — 나중에 다른 폴더를 불러와도, 같은 시퀀스를 다시 읽어도 안 바뀜 (재검토 L1)."""
    folder = shot_in_player(player, tmp_path)
    old_thumb_folder = player.current_thumbnail_folder
    item = player.seq_sidebar.item(0)
    assert item.data(THUMBNAIL_CONTEXT_ROLE) == ThumbnailContext(folder=old_thumb_folder)

    player.current_thumbnail_folder = str(tmp_path / "elsewhere" / thumbnails.FOLDER_NAME)  # 다른 job을 고른 뒤
    seq = seq_in(folder)
    other = group_sequences(str(tmp_path / "other"), ["z-0001.tga", "z-0002.tga"])[0]
    player._set_seq_items([seq, other])
    contexts = {player.seq_sidebar.item(i).data(Qt.UserRole).base: player.seq_sidebar.item(i).data(THUMBNAIL_CONTEXT_ROLE)
                for i in range(player.seq_sidebar.count())}
    assert contexts["tk1"] == ThumbnailContext(folder=old_thumb_folder)  # 이미 있던 시퀀스는 그 자리 그대로
    assert contexts["z"] == ThumbnailContext(folder=player.current_thumbnail_folder)  # 새 시퀀스는 지금의 자리


def test_unresolved_context_reads_the_would_be_folder_without_creating_it(player, tmp_path):
    """아직 정하지 않은 자리(pending_base)에서도 읽기는 폴더를 만들지 않음 (읽기 전용 경로: 만드는 것은 첫 프레임 폴백뿐)."""
    folder = make_shot(tmp_path / "shot")  # 짝 영상이 있어 폴백 생성도 없음
    player.thumbnailModeButton.click()
    player.current_thumbnail_folder = None
    player._thumbnail_folder_problem = None
    player.selected_folder_path = folder
    player._set_seq_items([seq_in(folder)])
    item = player.seq_sidebar.item(0)
    assert item.data(THUMBNAIL_CONTEXT_ROLE) == ThumbnailContext(pending_base=folder)
    assert player._seq_thumbnail_folder(item) == os.path.join(folder, thumbnails.FOLDER_NAME)

    wait_until(lambda: seq_work_done(player))

    assert not os.path.exists(os.path.join(folder, thumbnails.FOLDER_NAME))
    assert item.data(THUMBNAIL_CONTEXT_ROLE) == ThumbnailContext(pending_base=folder)


# ---------------------------------------------------------------- 다시 만들기 (Task 11의 메뉴가 부를 메서드)


def test_regenerate_paired_movie_thumbnail(player, tmp_path):
    """짝 mov가 있으면 그 영상의 썸네일을 지우고 영상에서 다시 만듦 (기존 ThumbnailWorker 흐름) — Seq 아이콘도 새로 붙음."""
    folder = shot_in_player(player, tmp_path)
    movie = os.path.join(folder, "tk1.mov")
    thumb = put_thumbnail(player.current_thumbnail_folder, movie, width=7, height=5)  # 옛 썸네일
    player.thumbnailModeButton.click()
    wait_until(lambda: seq_icon_loaded(player) and seq_work_done(player) and not player.thumbnail_workers)
    assert player.seq_sidebar.item(0).icon().availableSizes()[0] == QSize(7, 5)

    player.regenerate_seq_thumbnails([player.seq_sidebar.item(0)])

    wait_until(lambda: seq_work_done(player) and QPixmap(thumb).width() == player.thumbnail_size)
    wait_until(lambda: player.seq_sidebar.item(0).icon().availableSizes()[0].width() == player.thumbnail_size)
    assert jpgs(player.current_thumbnail_folder) == [os.path.basename(thumb)]  # 같은 파일을 바꿈
    # Mov 목록의 아이콘도 새 썸네일
    assert player.sidebar.item(0).icon().availableSizes()[0].width() == player.thumbnail_size


def test_regenerate_without_movie_decodes_the_first_frame_again(player, tmp_path, monkeypatch):
    folder = str(tmp_path / "only")
    make_seq(folder, "tk1", range(1, 7))
    player.thumbnailModeButton.click()
    player.load_videos_from_folder(folder)
    wait_until(lambda: seq_icon_loaded(player) and seq_work_done(player))
    seq = seq_in(folder)
    thumb = thumbnails.thumbnail_path(os.path.join(folder, thumbnails.FOLDER_NAME), seq.identity)
    assert red_pixmap(7, 5).save(thumb, "JPG")  # 옛 썸네일 (새것이라 그대로 쓰일 것)
    counter = DecodeCounter(monkeypatch)

    player.regenerate_seq_thumbnails([player.seq_sidebar.item(0)])

    wait_until(lambda: seq_work_done(player))
    assert counter.calls == ["tga"]
    assert QPixmap(thumb).width() == player.thumbnail_size


def test_regenerate_makes_the_thumbnail_in_list_mode_too(player, tmp_path):
    """목록 모드에서도 파일은 다시 만들고, 아이콘은 붙이지 않음 (목록 모드는 아이콘이 없음)."""
    folder = shot_in_player(player, tmp_path)
    movie = os.path.join(folder, "tk1.mov")
    thumb = put_thumbnail(player.current_thumbnail_folder, movie, width=7, height=5)

    player.regenerate_seq_thumbnails([player.seq_sidebar.item(0)])

    wait_until(lambda: seq_work_done(player) and QPixmap(thumb).width() == player.thumbnail_size)
    assert not seq_icon_loaded(player)


def test_regenerate_several_runs_one_at_a_time(player, tmp_path, monkeypatch):
    folder = str(tmp_path / "only")
    for base in ("a", "b", "c"):
        make_seq(folder, base, range(1, 4))
    player.load_videos_from_folder(folder)
    tracked_when_started = []
    real = thumbnail_workers.ThumbnailWorker

    def counting(*args, **kwargs):
        tracked_when_started.append(len(player._seq_thumbnail_workers))  # 새 워커를 만들 때 아직 도는 워커
        return real(*args, **kwargs)

    monkeypatch.setattr(sidebar_sequences, "ThumbnailWorker", counting)

    player.regenerate_seq_thumbnails([player.seq_sidebar.item(i) for i in range(3)])
    wait_until(lambda: seq_work_done(player))

    assert tracked_when_started == [0, 0, 0]
    assert len(jpgs(os.path.join(folder, thumbnails.FOLDER_NAME))) == 3


# ---------------------------------------------------------------- 문제 알림·정리


def test_loader_failure_is_shown_once_per_folder(player, dialogs, tmp_path):
    from tests.test_thumbnails import VIDEO_PROBLEM

    folder = shot_in_player(player, tmp_path)
    player._on_seq_thumbnails_failed(player.current_thumbnail_folder, "Traceback ... FileNotFoundError: x")
    player._on_seq_thumbnails_failed(player.current_thumbnail_folder, "Traceback ... again")
    warnings = [(title, text) for kind, title, text in dialogs.messages if kind == "warning" and title == VIDEO_PROBLEM]
    assert len(warnings) == 1
    assert "FileNotFoundError" in warnings[0][1] and player.current_thumbnail_folder in warnings[0][1]


def test_closing_the_player_stops_and_holds_running_seq_thumbnail_work(player):
    """창을 닫을 때 도는 Seq 썸네일 워커는 멈추라고 알리고 결과를 버리며, 끝날 때까지 붙잡아 둠 (실행 중인 QThread가 파괴되지 않게)."""
    from yesoncheck import worker_lifecycle

    worker = HangingLoader([])
    player._start_seq_worker(worker)
    player._seq_generation_queue.append(("x.seq", "x.seq", None, ThumbnailContext()))
    player._seq_thumbnail_timer.start(10_000)
    wait_until(worker.isRunning)

    player.close()

    assert not player._seq_thumbnail_timer.isActive()
    assert worker._is_running is False
    assert player._seq_thumbnail_workers == [] and player._seq_generation_queue == [] and player._seq_generating is None
    assert worker.signalsBlocked()
    assert worker_lifecycle.wait_for_released_workers(5) == []  # 멈추라는 알림을 받아 곧 끝남
    assert not worker.isRunning()


def test_nothing_starts_after_the_player_is_closed(player, tmp_path):
    """창을 닫기 전에 보낸 신호가 닫은 뒤에 도착해도 새 워커를 띄우지 않음 (닫은 창에 붙잡는 이 없는 스레드가 생기지 않게)."""
    folder = str(tmp_path / "only")
    make_seq(folder, "tk1", range(1, 4))
    player.load_videos_from_folder(folder)
    identity = seq_in(folder).identity
    player.is_thumbnail_mode = True
    player.close()

    player._on_seq_thumbnail_missing(identity)
    assert player._seq_generation_queue == []
    player._load_seq_thumbnails()
    player._seq_generation_queue.append((identity, identity, seq_in(folder), ThumbnailContext()))
    player._pump_seq_generation()

    assert player._seq_thumbnail_workers == [] and player._seq_generating is None


def test_changing_the_mov_list_stops_seq_thumbnail_work(player):
    """job을 바꾸거나 폴더를 불러와 Mov 목록을 비우면 (Seq 목록도 비움) 지난 목록의 읽기·만들기도 멈춤."""
    from yesoncheck import worker_lifecycle

    worker = HangingLoader([])
    player._start_seq_worker(worker)
    player._seq_generation_queue.append(("x.seq", "x.seq", None, ThumbnailContext()))
    wait_until(worker.isRunning)

    player.sidebar.clear()

    assert worker._is_running is False
    assert player._seq_thumbnail_workers == [] and player._seq_generation_queue == []
    assert worker_lifecycle.wait_for_released_workers(5) == []
