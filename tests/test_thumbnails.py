"""썸네일 파일: Mac·Windows가 NAS의 같은 썸네일을 쓰고, 바뀐 영상만 새로 만들고, 저장 실패는 창으로 알림.

Windows 사용자 보고 (2026-10-15): 썸네일을 만든 작업으로 돌아와 썸네일 모드를 켜면 모두 처음부터 다시 만듦
(Windows는 Mac이 만든 썸네일 이름을 몰랐고, Mac이 만든 폴더에 쓰지 못한 저장 실패는 로그에만 남았음).
"""

import errno
import hashlib
import os
import stat
import sys
import time

import pytest
from PyQt5.QtWidgets import QApplication

from yesoncheck import paths, thumbnails
from yesoncheck.paths import PathMap
from tests.conftest import write_test_video
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

# 실제 NAS의 영상: Mac에서 만든 썸네일 파일이 <job>/.yesoncheck_thumb/5588e0d6ba56606ffae36e54b8d5283f.jpg로 있음
MAC_VIDEO = "/usadata2/Titmouse/FLORIDA/FL_Season01/FL_902/scene-A001/frames/FL_902_A001_TK1.mov"
MAC_THUMB_KEY = "5588e0d6ba56606ffae36e54b8d5283f"
UNC_VIDEO = "\\\\Mainnas\\usadata2\\Titmouse\\FLORIDA\\FL_Season01\\FL_902\\scene-A001\\frames\\FL_902_A001_TK1.mov"
NAS_MAP = {"version": 1, "shares": [{"mac": "/usadata2", "windows": ["\\\\Mainnas\\usadata2"]}]}


def md5(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


@pytest.fixture
def windows(monkeypatch):
    """Windows 동작을 흉내: Y:=\\\\Mainnas\\usadata2, C:=로컬 디스크. 변환표는 시험마다 activate."""
    remotes = {"Y:": "\\\\Mainnas\\usadata2"}
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda drive: remotes.get(drive))
    paths._cached_remote_name.cache_clear()
    yield remotes
    paths.activate(None)
    paths._cached_remote_name.cache_clear()


def test_mac_key_unchanged(monkeypatch):
    """Mac은 기존 이름 그대로 (NAS에 이미 있는 Mac 썸네일이 계속 쓰여야 함)."""
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    assert paths.thumbnail_key(MAC_VIDEO) == MAC_THUMB_KEY


def test_windows_unc_uses_mac_thumbnail_name(windows):
    paths.activate(PathMap.from_dict(NAS_MAP, "t"))
    assert paths.thumbnail_key(UNC_VIDEO) == MAC_THUMB_KEY
    # 서버·공유 이름의 대소문자와 구분자는 상관없음 (그 아래는 NAS의 이름 그대로)
    assert paths.thumbnail_key(UNC_VIDEO.replace("\\\\Mainnas\\usadata2", "//MAINNAS/USADATA2")) == MAC_THUMB_KEY


def test_windows_drive_letter_uses_mac_thumbnail_name(windows):
    paths.activate(PathMap.from_dict(NAS_MAP, "t"))
    rest = "\\Titmouse\\FLORIDA\\FL_Season01\\FL_902\\scene-A001\\frames\\FL_902_A001_TK1.mov"
    assert paths.thumbnail_key("Y:" + rest) == MAC_THUMB_KEY
    assert paths.thumbnail_key("y:" + rest.replace("\\", "/")) == MAC_THUMB_KEY


def test_windows_outside_path_map_keeps_old_key(windows):
    """변환표 밖 공유·로컬 디스크는 예전 이름 (path_key의 md5)."""
    paths.activate(PathMap.from_dict(NAS_MAP, "t"))
    other = "\\\\other\\share\\A.mov"
    local = "C:\\clips\\A.mov"
    assert paths.thumbnail_key(other) == md5(paths.path_key(other)) == md5("\\\\other\\share\\a.mov")
    assert paths.thumbnail_key(local) == md5(paths.path_key(local)) == md5("c:\\clips\\a.mov")


def test_windows_without_path_map_keeps_old_key(windows):
    paths.activate(None)
    assert paths.thumbnail_key(UNC_VIDEO) == md5(paths.path_key(UNC_VIDEO))
    assert paths.thumbnail_key("Y:\\x.mov") == paths.thumbnail_key("\\\\mainnas\\USADATA2\\X.mov")


def touch(path, mtime):
    with open(path, "wb") as fh:
        fh.write(b"x")
    os.utime(path, (mtime, mtime))
    return str(path)


def test_is_fresh_compares_modification_times(tmp_path):
    """영상보다 나중에 만든 썸네일만 그대로 씀 (같은 이름으로 다시 렌더링한 영상은 썸네일을 새로 만듦)."""
    video = touch(tmp_path / "a.mov", 1_700_000_000)
    thumb = str(tmp_path / "a.jpg")
    assert thumbnails.is_fresh(thumb, video) is False  # 썸네일 없음
    touch(thumb, 1_700_000_100)
    assert thumbnails.is_fresh(thumb, video) is True
    os.utime(thumb, (1_700_000_000, 1_700_000_000))
    assert thumbnails.is_fresh(thumb, video) is True  # 같은 시각
    os.utime(video, (1_700_000_200, 1_700_000_200))
    assert thumbnails.is_fresh(thumb, video) is False  # 영상이 더 새로움
    with pytest.raises(FileNotFoundError):
        thumbnails.is_fresh(thumb, str(tmp_path / "missing.mov"))


def test_thumbnail_path(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    folder = str(tmp_path / thumbnails.FOLDER_NAME)
    assert thumbnails.FOLDER_NAME == ".yesoncheck_thumb"
    assert thumbnails.thumbnail_path(folder, MAC_VIDEO) == os.path.join(folder, MAC_THUMB_KEY + ".jpg")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 권한 (Mac이 만든 폴더에 Windows 계정도 쓰게)")
def test_ensure_folder_opens_permissions(tmp_path):
    old_umask = os.umask(0o022)
    try:
        folder = thumbnails.ensure_folder(str(tmp_path / "job"))
        assert folder == os.path.join(str(tmp_path / "job"), ".yesoncheck_thumb")
        assert stat.S_IMODE(os.stat(folder).st_mode) == 0o777
        # 예전에 만든 0o755 폴더(내 것)도 고침
        existing = tmp_path / "old_job" / ".yesoncheck_thumb"
        existing.mkdir(parents=True)
        os.chmod(existing, 0o755)
        assert thumbnails.ensure_folder(str(tmp_path / "old_job")) == str(existing)
        assert stat.S_IMODE(os.stat(existing).st_mode) == 0o777
    finally:
        os.umask(old_umask)


def red_pixmap(width=7, height=5):
    from PyQt5.QtGui import QColor, QPixmap

    pixmap = QPixmap(width, height)
    pixmap.fill(QColor("red"))
    return pixmap


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 권한 (읽기 전용 파일을 쓰기 가능한 폴더에서 바꿈)")
def test_save_replaces_read_only_file(qapp, tmp_path):
    """다른 계정이 만든 썸네일(이 PC 계정은 쓸 수 없는 파일)도 폴더에 쓸 수 있으면 바꿈."""
    from PyQt5.QtGui import QPixmap

    thumb = tmp_path / "a.jpg"
    thumb.write_bytes(b"old")
    os.chmod(thumb, 0o444)
    thumbnails.save(red_pixmap(), str(thumb))
    assert thumb.read_bytes()[:2] == b"\xff\xd8"  # JPEG
    assert QPixmap(str(thumb)).size().width() == 7


def test_save_raises_when_folder_missing(qapp, tmp_path):
    target = str(tmp_path / "missing" / "a.jpg")
    with pytest.raises(OSError) as info:
        thumbnails.save(red_pixmap(), target)
    assert info.value.filename.startswith(target)  # 같은 폴더의 임시 파일 (썸네일 경로 + .pid.thread.tmp)


def test_save_write_failure_leaves_nothing(qapp, tmp_path, monkeypatch):
    """임시 파일을 연 뒤 쓰다 실패(디스크 가득 등) → 썸네일도 임시 파일도 남지 않음 (반쯤 쓴 JPEG를 다른 PC가 읽지 않게)."""
    real_open = open

    class FullDisk:
        def __init__(self, path, mode):
            self.path = path
            self.fh = real_open(path, mode)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.fh.close()

        def write(self, data):
            self.fh.write(data[:10])
            raise OSError(errno.ENOSPC, "No space left on device", self.path)

    monkeypatch.setattr(thumbnails, "open", FullDisk, raising=False)
    thumb = str(tmp_path / "a.jpg")
    with pytest.raises(OSError) as info:
        thumbnails.save(red_pixmap(), thumb)
    assert info.value.errno == errno.ENOSPC
    assert os.listdir(tmp_path) == []


def test_save_keeps_old_thumbnail_when_replace_fails(qapp, tmp_path, monkeypatch):
    thumb = tmp_path / "a.jpg"
    thumb.write_bytes(b"old")

    def cannot_replace(src, dst):
        raise PermissionError(errno.EACCES, "Permission denied", dst)

    monkeypatch.setattr(thumbnails.os, "replace", cannot_replace)
    with pytest.raises(PermissionError):
        thumbnails.save(red_pixmap(), str(thumb))
    assert thumb.read_bytes() == b"old"
    assert os.listdir(tmp_path) == ["a.jpg"]


def denied(pixmap, thumb_path):
    raise PermissionError(errno.EACCES, "Permission denied", thumb_path)


def run_worker(video, folder):
    """ThumbnailWorker를 이 스레드에서 실행 → (보낸 썸네일 [(영상, 폭)], 저장 실패 [(폴더, 내용)])."""
    from yesoncheck.workers import ThumbnailWorker

    ready, failed = [], []
    worker = ThumbnailWorker(video, 120, folder)
    worker.thumbnail_ready.connect(lambda path, pixmap: ready.append((path, pixmap.width())))
    worker.save_failed.connect(lambda where, message: failed.append((where, message)))
    worker.run()
    return ready, failed


def test_worker_reports_save_failure_and_still_shows_thumbnail(qapp, tmp_path, monkeypatch):
    video = write_test_video(str(tmp_path / "job" / "a.mov"))
    folder = thumbnails.ensure_folder(str(tmp_path / "job"))
    monkeypatch.setattr(thumbnails, "save", denied)
    ready, failed = run_worker(video, folder)
    assert ready == [(video, 120)]  # 이번 실행에서는 아이콘으로 보여 줌
    assert len(failed) == 1
    where, message = failed[0]
    assert where == folder
    assert thumbnails.thumbnail_path(folder, video) in message
    assert "Permission denied" in message


def test_worker_saves_qimage(qapp, tmp_path, monkeypatch):
    """워커 스레드에서는 QPixmap이 아니라 QImage를 저장 (QPixmap은 GUI 스레드 전용)."""
    from PyQt5.QtGui import QImage

    video = write_test_video(str(tmp_path / "job" / "a.mov"))
    folder = thumbnails.ensure_folder(str(tmp_path / "job"))
    real_save = thumbnails.save
    saved = []

    def recording_save(image, thumb_path):
        saved.append(type(image))
        real_save(image, thumb_path)

    monkeypatch.setattr(thumbnails, "save", recording_save)
    assert run_worker(video, folder) == ([(video, 120)], [])
    assert saved == [QImage]
    from PyQt5.QtGui import QPixmap

    assert QPixmap(thumbnails.thumbnail_path(folder, video)).width() == 120


def test_worker_reuses_fresh_thumbnail_and_remakes_stale_one(qapp, tmp_path):
    video = write_test_video(str(tmp_path / "job" / "a.mov"))
    folder = thumbnails.ensure_folder(str(tmp_path / "job"))
    thumb = thumbnails.thumbnail_path(folder, video)
    assert red_pixmap(7, 5).save(thumb, "JPG")
    base = time.time() - 1000
    os.utime(video, (base, base))
    os.utime(thumb, (base + 10, base + 10))
    assert run_worker(video, folder) == ([(video, 7)], [])  # 영상보다 새 썸네일 → 그대로 씀

    os.utime(video, (base + 20, base + 20))  # 같은 이름으로 다시 렌더링한 영상
    assert run_worker(video, folder) == ([(video, 120)], [])
    from PyQt5.QtGui import QPixmap

    assert QPixmap(thumb).width() == 120
    assert thumbnails.is_fresh(thumb, video)


def test_loader_emits_only_fresh_thumbnails(qapp, tmp_path):
    from yesoncheck.workers import ThumbnailLoaderWorker

    fresh = write_test_video(str(tmp_path / "job" / "fresh.mov"))
    stale = write_test_video(str(tmp_path / "job" / "stale.mov"))
    folder = thumbnails.ensure_folder(str(tmp_path / "job"))
    base = time.time() - 1000
    for video, thumb_time in ((fresh, base + 10), (stale, base - 10)):
        thumb = thumbnails.thumbnail_path(folder, video)
        assert red_pixmap().save(thumb, "JPG")
        os.utime(video, (base, base))
        os.utime(thumb, (thumb_time, thumb_time))
    loaded = []
    loader = ThumbnailLoaderWorker(folder, [fresh, stale])
    loader.thumbnail_loaded.connect(lambda path, pixmap: loaded.append(path))
    loader.run()
    assert loaded == [fresh]


def test_problem_dialog_once_per_folder(new_player, dialogs, tmp_path, monkeypatch):
    player = new_player(make_config(str(tmp_path), {}))
    folder_a = str(tmp_path / "A" / thumbnails.FOLDER_NAME)
    folder_b = str(tmp_path / "B" / thumbnails.FOLDER_NAME)
    player._report_thumbnail_problem(folder_a, "이유 1")
    player._report_thumbnail_problem(folder_a, "이유 2")
    player._report_thumbnail_problem(folder_b, "이유 3")
    warnings = [(title, text) for kind, title, text in dialogs.messages if kind == "warning"]
    assert [title for title, _text in warnings] == ["썸네일 저장 실패", "썸네일 저장 실패"]
    assert folder_a in warnings[0][1] and "이유 1" in warnings[0][1]
    assert folder_b in warnings[1][1] and "이유 3" in warnings[1][1]
    assert "권한" in warnings[0][1]


def test_problem_dialog_not_repeated_while_open(new_player, dialogs, tmp_path, monkeypatch):
    """창이 떠 있는 동안 다시 들어온 저장 실패 시그널은 창을 또 띄우지 않음."""
    from PyQt5.QtWidgets import QMessageBox

    player = new_player(make_config(str(tmp_path), {}))
    shown = []

    def warning(parent, title, text, *args, **kwargs):
        shown.append(text)
        if len(shown) == 1:
            player._report_thumbnail_problem("folder", "창이 떠 있는 동안 온 실패")
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning", warning)
    player._report_thumbnail_problem("folder", "첫 실패")
    assert len(shown) == 1


def wait_until(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, f"{timeout}초 안에 조건이 이루어지지 않았습니다"
        QApplication.processEvents()
        time.sleep(0.01)


def test_sidebar_reports_save_failure_once(new_player, dialogs, tmp_path, monkeypatch):
    """썸네일 워커의 저장 실패 → 창(작업 폴더마다 한 번), 아이콘은 이번 실행에서 보임."""
    videos = [write_test_video(str(tmp_path / "job" / f"{name}.mov")) for name in ("a", "b")]
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar(videos)
    folder = thumbnails.ensure_folder(str(tmp_path / "job"))
    player.current_thumbnail_folder = folder
    monkeypatch.setattr(thumbnails, "save", denied)
    for video in videos:
        player.generate_thumbnail(video)
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()
    warnings = [text for kind, _title, text in dialogs.messages if kind == "warning"]
    assert len(warnings) == 1
    assert folder in warnings[0] and "Permission denied" in warnings[0]
    assert all(not player.sidebar.item(i).icon().isNull() for i in range(player.sidebar.count()))


def test_job_thumbnail_folder_failure_is_reported(new_player, dialogs, work_area, monkeypatch):
    write_test_video(os.path.join(work_area.local, "S1", "job_01", "scene-001", "frames", "a.mov"))
    player = new_player(make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map))

    def cannot_create(parent_dir):
        raise PermissionError(errno.EACCES, "Permission denied", os.path.join(parent_dir, thumbnails.FOLDER_NAME))

    player.workComboBox.setCurrentText("SMOKE")
    player.seasonComboBox.setCurrentText("S1")
    monkeypatch.setattr(thumbnails, "ensure_folder", cannot_create)
    player.jobComboBox.setCurrentText("job_01")
    assert player.sidebar.count() == 1  # 썸네일 폴더가 없어도 목록은 보임
    assert player.current_thumbnail_folder is None
    warnings = [text for kind, _title, text in dialogs.messages if kind == "warning"]
    assert len(warnings) == 1
    assert os.path.join("job_01", thumbnails.FOLDER_NAME) in warnings[0] and "Permission denied" in warnings[0]


def test_no_thumbnail_folder_until_job_selected(new_player, dialogs, work_area):
    """작품·시즌을 고를 때 job 목록을 비우면 update_playlist가 빈 job으로 불림 → 작품·시즌 폴더에 썸네일 폴더를
    만들지 않음 (NAS에 /usadata2/Titmouse/FLORIDA/.yesoncheck_thumb 같은 폴더가 생겼었음)."""
    write_test_video(os.path.join(work_area.local, "S1", "job_01", "scene-001", "frames", "a.mov"))
    player = new_player(make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map))
    player.workComboBox.setCurrentText("SMOKE")
    player.seasonComboBox.setCurrentText("S1")
    assert not os.path.exists(os.path.join(work_area.local, thumbnails.FOLDER_NAME))
    assert not os.path.exists(os.path.join(work_area.local, "S1", thumbnails.FOLDER_NAME))
    assert player.current_thumbnail_folder is None
    assert not [m for m in dialogs.messages if m[1] == "썸네일 저장 실패"]

    player.jobComboBox.setCurrentText("job_01")
    assert os.path.isdir(os.path.join(work_area.local, "S1", "job_01", thumbnails.FOLDER_NAME))
    assert player.sidebar.count() == 1
    assert dialogs.errors() == []
