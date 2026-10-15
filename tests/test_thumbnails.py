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
from PyQt5.QtCore import Qt
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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 권한 비트")
def test_share_folder_keeps_setgid_and_sticky_bits(tmp_path):
    existing = tmp_path / "job" / thumbnails.FOLDER_NAME
    existing.mkdir(parents=True)
    os.chmod(existing, 0o3755)  # setgid + sticky
    assert stat.S_IMODE(os.stat(existing).st_mode) == 0o3755
    thumbnails.ensure_folder(str(tmp_path / "job"))
    assert stat.S_IMODE(os.stat(existing).st_mode) == 0o3777


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 권한 비트")
def test_share_folder_chmods_once_per_folder(tmp_path, monkeypatch):
    """Mac의 SMB 마운트는 chmod 뒤에도 0o700으로 보여, 작업을 열 때마다 chmod하지 않게 이번 실행에서 폴더마다 한 번만."""
    calls = []
    monkeypatch.setattr(thumbnails.os, "chmod", lambda path, mode: calls.append((path, mode)))  # 권한이 바뀌지 않는 마운트
    old_umask = os.umask(0o022)
    try:
        first = thumbnails.ensure_folder(str(tmp_path / "job"))
        second = thumbnails.ensure_folder(str(tmp_path / "job"))
    finally:
        os.umask(old_umask)
    assert first == second
    assert calls == [(first, 0o777)]


def cannot_chmod(path, mode):
    raise PermissionError(errno.EPERM, "Operation not permitted", path)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 권한 (Mac에서만 chmod)")
def test_ensure_folder_chmod_failure_is_not_fatal(qapp, tmp_path, monkeypatch):
    """권한을 바꾸지 못해도 폴더는 쓸 수 있음 → 폴더를 돌려주고 이유는 share_problem으로 (한 번만 시도)."""
    calls = []

    def failing_chmod(path, mode):
        calls.append(path)
        cannot_chmod(path, mode)

    monkeypatch.setattr(thumbnails.os, "chmod", failing_chmod)
    old_umask = os.umask(0o022)
    try:
        folder = thumbnails.ensure_folder(str(tmp_path / "job"))
        assert thumbnails.ensure_folder(str(tmp_path / "job")) == folder
    finally:
        os.umask(old_umask)
    assert os.path.isdir(folder) and len(calls) == 1
    assert "Operation not permitted" in thumbnails.share_problem(folder)
    assert thumbnails.share_problem(str(tmp_path / "other")) is None
    thumbnails.save(red_pixmap(), os.path.join(folder, "a.jpg"))
    assert os.path.isfile(os.path.join(folder, "a.jpg"))


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
    assert info.value.filename.startswith(target)  # 같은 폴더의 임시 파일 (썸네일 경로 + .<uuid>.tmp)


def test_save_temp_name_is_unique(qapp, tmp_path, monkeypatch):
    """임시 파일 이름은 저장마다 다름 (uuid): pid·스레드 번호는 NAS 폴더를 함께 쓰는 다른 PC와 겹칠 수 있음."""
    import re

    real_replace = os.replace
    sources = []

    def recording_replace(src, dst):
        sources.append(src)
        real_replace(src, dst)

    monkeypatch.setattr(thumbnails.os, "replace", recording_replace)
    thumb = str(tmp_path / "a.jpg")
    thumbnails.save(red_pixmap(), thumb)
    thumbnails.save(red_pixmap(), thumb)
    assert len(sources) == 2 and sources[0] != sources[1]
    for src in sources:
        assert re.fullmatch(re.escape(thumb) + r"\.[0-9a-f]{32}\.tmp", src), src
    assert os.listdir(tmp_path) == ["a.jpg"]


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


def test_worker_save_failure_keeps_original_error(qapp, tmp_path, monkeypatch, capsys):
    """바꾸기가 실패한 뒤 임시 파일 지우기도 실패하면 올라오는 것은 지우기 오류 → 먼저 난 원래 오류도 창·로그에."""
    video = write_test_video(str(tmp_path / "job" / "a.mov"))
    folder = thumbnails.ensure_folder(str(tmp_path / "job"))

    def cannot_replace(src, dst):
        raise PermissionError(errno.EACCES, "replace denied", dst)

    def cannot_remove(path):
        raise PermissionError(errno.EPERM, "cleanup denied", path)

    monkeypatch.setattr(thumbnails.os, "replace", cannot_replace)
    monkeypatch.setattr(thumbnails.os, "remove", cannot_remove)
    ready, failed = run_worker(video, folder)
    assert ready == [(video, 120)]
    message = failed[0][1]
    assert "cleanup denied" in message and "replace denied" in message
    assert "replace denied" in capsys.readouterr().out


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
    loader = ThumbnailLoaderWorker([(video, thumbnails.thumbnail_path(folder, video)) for video in (fresh, stale)])
    loader.thumbnail_loaded.connect(lambda path, pixmap: loaded.append(path))
    loader.run()
    assert loaded == [fresh]


SAVE_FAILED = "썸네일 저장 실패"
FOLDER_PROBLEM = "썸네일 폴더 문제"
VIDEO_PROBLEM = "영상 확인 실패"


def thumbnail_warnings(dialogs, title=None):
    """썸네일 문제 창 [(제목, 내용)] (title을 주면 그 제목만)."""
    titles = (title,) if title else (SAVE_FAILED, FOLDER_PROBLEM, VIDEO_PROBLEM)
    return [(t, text) for kind, t, text in dialogs.messages if kind == "warning" and t in titles]


def test_problem_dialog_once_per_folder_and_title(new_player, dialogs, tmp_path, monkeypatch):
    """창은 (폴더, 제목)마다 한 번: "썸네일 폴더 문제"를 알린 폴더라도 나중의 "썸네일 저장 실패"는 따로 알림."""
    player = new_player(make_config(str(tmp_path), {}))
    folder_a = str(tmp_path / "A" / thumbnails.FOLDER_NAME)
    folder_b = str(tmp_path / "B" / thumbnails.FOLDER_NAME)
    player._report_thumbnail_problem(folder_a, FOLDER_PROBLEM, "이유 1")
    player._report_thumbnail_problem(folder_a, FOLDER_PROBLEM, "이유 2")  # 같은 폴더·제목 → 창 없음
    player._report_thumbnail_problem(folder_a, SAVE_FAILED, "이유 3")
    player._report_thumbnail_problem(folder_a, SAVE_FAILED, "이유 4")
    player._report_thumbnail_problem(folder_b, FOLDER_PROBLEM, "이유 5")
    warnings = thumbnail_warnings(dialogs)
    assert [title for title, _text in warnings] == [FOLDER_PROBLEM, SAVE_FAILED, FOLDER_PROBLEM]
    assert folder_a in warnings[0][1] and "이유 1" in warnings[0][1]
    assert folder_a in warnings[1][1] and "이유 3" in warnings[1][1]
    assert folder_b in warnings[2][1] and "이유 5" in warnings[2][1]
    assert "권한" in warnings[0][1]


def test_problem_dialog_not_repeated_while_open(new_player, dialogs, tmp_path, monkeypatch):
    """창이 떠 있는 동안 다시 들어온 저장 실패 시그널은 창을 또 띄우지 않음."""
    from PyQt5.QtWidgets import QMessageBox

    player = new_player(make_config(str(tmp_path), {}))
    shown = []

    def warning(parent, title, text, *args, **kwargs):
        shown.append(text)
        if len(shown) == 1:
            player._report_thumbnail_problem("folder", SAVE_FAILED, "창이 떠 있는 동안 온 실패")
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning", warning)
    player._report_thumbnail_problem("folder", SAVE_FAILED, "첫 실패")
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
    warnings = thumbnail_warnings(dialogs)
    assert len(warnings) == 1
    title, text = warnings[0]
    assert title == SAVE_FAILED
    assert folder in text and "Permission denied" in text and "화면에만" in text
    assert all(not player.sidebar.item(i).icon().isNull() for i in range(player.sidebar.count()))


def open_job_with_folder_failure(new_player, work_area, monkeypatch):
    """job_01의 썸네일 폴더만 만들지 못하는 작품(job_01·job_02)을 열고 job_01을 고름 → (창, job_01 영상)."""
    video = write_test_video(os.path.join(work_area.local, "S1", "job_01", "scene-001", "frames", "a.mov"))
    write_test_video(os.path.join(work_area.local, "S1", "job_02", "scene-001", "frames", "b.mov"))
    player = new_player(make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map))
    real_ensure_folder = thumbnails.ensure_folder

    def job_01_fails(parent_dir):
        if os.path.basename(os.path.normpath(parent_dir)) == "job_01":
            raise PermissionError(errno.EACCES, "Permission denied", os.path.join(parent_dir, thumbnails.FOLDER_NAME))
        return real_ensure_folder(parent_dir)

    monkeypatch.setattr(thumbnails, "ensure_folder", job_01_fails)
    player.workComboBox.setCurrentText("SMOKE")
    player.seasonComboBox.setCurrentText("S1")
    player.jobComboBox.setCurrentText("job_01")
    return player, video


def test_job_folder_failure_reported_when_thumbnails_used(new_player, dialogs, work_area, monkeypatch, tmp_path):
    """job을 열 때 썸네일 폴더를 만들지 못하면 로그만 → 썸네일 모드를 켤 때 창 한 번. 썸네일은 화면에만 (다른 폴더로 대신하지 않음)."""
    player, video = open_job_with_folder_failure(new_player, work_area, monkeypatch)
    assert player.sidebar.count() == 1  # 썸네일 폴더가 없어도 목록은 보임
    assert player.current_thumbnail_folder is None
    assert thumbnail_warnings(dialogs) == []  # 작업을 열 때는 창 없음

    earlier_drop = tmp_path / "earlier_drop"  # 전에 끌어다 놓은 폴더 (그곳에 대신 저장하면 안 됨)
    earlier_drop.mkdir()
    player.selected_folder_path = str(earlier_drop)
    player.switch_to_thumbnail_mode()
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()

    warnings = thumbnail_warnings(dialogs)
    assert len(warnings) == 1
    title, text = warnings[0]
    assert title == FOLDER_PROBLEM
    assert os.path.join("job_01", thumbnails.FOLDER_NAME) in text and "Permission denied" in text and "화면에만" in text
    assert not player.sidebar.item(0).icon().isNull()  # 화면에는 보임
    assert not os.path.exists(earlier_drop / thumbnails.FOLDER_NAME)
    assert not os.path.exists(os.path.join(os.path.dirname(video), thumbnails.FOLDER_NAME))
    player.switch_to_thumbnail_mode()  # 다시 켜도 창은 폴더마다 한 번
    wait_until(lambda: not player.thumbnail_workers)
    assert len(thumbnail_warnings(dialogs)) == 1


def test_job_folder_problem_cleared_by_next_folder(new_player, dialogs, work_area, monkeypatch, tmp_path):
    """다른 job을 열거나 폴더를 불러오면 미뤄 둔 썸네일 폴더 문제는 지움 (그 폴더에 저장)."""
    player, _video = open_job_with_folder_failure(new_player, work_area, monkeypatch)
    assert player._thumbnail_folder_problem is not None
    player.jobComboBox.setCurrentText("job_02")
    assert player._thumbnail_folder_problem is None
    assert player.current_thumbnail_folder.endswith(os.path.join("job_02", thumbnails.FOLDER_NAME))

    player.jobComboBox.setCurrentText("job_01")
    assert player._thumbnail_folder_problem is not None
    other = tmp_path / "other"
    write_test_video(str(other / "c.mov"))
    player.load_videos_from_folder(str(other))  # 폴더 선택·북마크
    assert player._thumbnail_folder_problem is None
    assert player.current_thumbnail_folder == str(other / thumbnails.FOLDER_NAME)


def test_fallback_folder_failure_does_not_escape(new_player, dialogs, tmp_path, monkeypatch):
    """job이 아닌 영상(끌어다 놓은 폴더)의 썸네일 폴더를 만들지 못해도 예외가 썸네일 모드로 새지 않음 → 창 한 번, 화면에만."""
    video = write_test_video(str(tmp_path / "dropped" / "a.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([video])
    player.selected_folder_path = str(tmp_path / "dropped")

    def cannot_create(parent_dir):
        raise PermissionError(errno.EACCES, "Permission denied", os.path.join(parent_dir, thumbnails.FOLDER_NAME))

    monkeypatch.setattr(thumbnails, "ensure_folder", cannot_create)
    player.switch_to_thumbnail_mode()
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()
    warnings = thumbnail_warnings(dialogs)
    assert [title for title, _text in warnings] == [FOLDER_PROBLEM]
    assert "Permission denied" in warnings[0][1]
    assert player.current_thumbnail_folder is None
    assert not player.sidebar.item(0).icon().isNull()


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
    assert thumbnail_warnings(dialogs) == []

    player.jobComboBox.setCurrentText("job_01")
    assert os.path.isdir(os.path.join(work_area.local, "S1", "job_01", thumbnails.FOLDER_NAME))
    assert player.sidebar.count() == 1
    assert dialogs.errors() == []


def test_unreadable_fresh_thumbnail_is_regenerated(new_player, dialogs, tmp_path):
    """영상보다 새것이지만 읽을 수 없는(깨진) 썸네일도 썸네일 모드에서 다시 만듦 (예전에는 건너뛰어 계속 빈 아이콘)."""
    from PyQt5.QtGui import QPixmap

    video = write_test_video(str(tmp_path / "job" / "a.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([video])
    folder = thumbnails.ensure_folder(str(tmp_path / "job"))
    player.current_thumbnail_folder = folder
    thumb = thumbnails.thumbnail_path(folder, video)
    with open(thumb, "wb") as fh:
        fh.write(b"not a jpeg")
    newer = os.path.getmtime(video) + 10
    os.utime(thumb, (newer, newer))
    assert thumbnails.is_fresh(thumb, video)

    player.generate_thumbnails_for_all_items()
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()
    assert QPixmap(thumb).width() == 120
    assert not player.sidebar.item(0).icon().isNull()
    assert dialogs.errors() == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 권한 (Mac에서만 chmod)")
def test_job_chmod_failure_keeps_folder_and_reports_on_use(new_player, dialogs, work_area, monkeypatch):
    """job 썸네일 폴더의 권한을 바꾸지 못해도 그 폴더를 쓰고 저장함. 창은 썸네일을 쓸 때 "썸네일 폴더 문제" 한 번."""
    video = write_test_video(os.path.join(work_area.local, "S1", "job_01", "scene-001", "frames", "a.mov"))
    player = new_player(make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map))
    monkeypatch.setattr(thumbnails.os, "chmod", cannot_chmod)
    old_umask = os.umask(0o022)
    try:
        player.workComboBox.setCurrentText("SMOKE")
        player.seasonComboBox.setCurrentText("S1")
        player.jobComboBox.setCurrentText("job_01")
    finally:
        os.umask(old_umask)
    folder = os.path.join(work_area.local, "S1", "job_01", thumbnails.FOLDER_NAME)
    assert player.current_thumbnail_folder == folder
    assert thumbnail_warnings(dialogs) == []  # 작업을 열 때는 창 없음

    player.generate_thumbnail(video)
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()
    assert os.path.isfile(thumbnails.thumbnail_path(folder, video))  # 이 PC에서는 저장됨
    warnings = thumbnail_warnings(dialogs)
    assert [title for title, _text in warnings] == [FOLDER_PROBLEM]
    assert "권한을 바꾸지 못했" in warnings[0][1] and "Operation not permitted" in warnings[0][1]


def test_unreadable_thumbnail_folder_does_not_break_thumbnail_mode(new_player, dialogs, tmp_path, monkeypatch):
    """썸네일 파일을 확인하지 못하면(권한 등) 썸네일 모드가 멈추지 않음 → "썸네일 폴더 문제" 창 한 번, 새로 만듦."""
    videos = [write_test_video(str(tmp_path / "job" / f"{name}.mov")) for name in ("a", "b")]
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar(videos)
    folder = thumbnails.ensure_folder(str(tmp_path / "job"))
    player.current_thumbnail_folder = folder
    real_getmtime = os.path.getmtime

    def thumbnails_unreadable(path):
        if str(path).endswith(".jpg"):
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return real_getmtime(path)

    monkeypatch.setattr(thumbnails.os.path, "getmtime", thumbnails_unreadable)
    player.generate_thumbnails_for_all_items()
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()
    warnings = thumbnail_warnings(dialogs)
    assert [title for title, _text in warnings] == [FOLDER_PROBLEM]
    assert "확인하지 못해" in warnings[0][1] and "Permission denied" in warnings[0][1]
    assert all(not player.sidebar.item(i).icon().isNull() for i in range(player.sidebar.count()))
    assert all(os.path.isfile(thumbnails.thumbnail_path(folder, video)) for video in videos)


def test_video_removed_during_check_is_skipped(new_player, dialogs, tmp_path, monkeypatch):
    """목록을 만든 뒤 영상이 없어지면(isfile 다음) 그 영상만 건너뜀 (예외도 창도 없음)."""
    gone = write_test_video(str(tmp_path / "job" / "a.mov"))
    kept = write_test_video(str(tmp_path / "job" / "b.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([gone, kept])
    folder = thumbnails.ensure_folder(str(tmp_path / "job"))
    player.current_thumbnail_folder = folder
    assert red_pixmap().save(thumbnails.thumbnail_path(folder, gone), "JPG")  # 영상의 수정 시각까지 확인하게
    real_getmtime = os.path.getmtime

    def removed_while_checking(path):
        if path == gone and os.path.exists(gone):
            os.remove(gone)
        return real_getmtime(path)

    monkeypatch.setattr(thumbnails.os.path, "getmtime", removed_while_checking)
    player.generate_thumbnails_for_all_items()
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()
    assert thumbnail_warnings(dialogs) == []
    assert not player.sidebar.item(1).icon().isNull()  # b는 만듦
    from PyQt5.QtGui import QPixmap

    assert QPixmap(thumbnails.thumbnail_path(folder, gone)).width() == 7  # a는 건드리지 않음
    assert player.generate_thumbnail(gone) is False
    assert player.thumbnail_workers == []


def test_no_job_thumbnails_stay_in_memory(new_player, dialogs, work_area, tmp_path):
    """job을 고르지 않은 동안(작품만 바꿈) 목록의 썸네일은 화면에만 — 전에 연 폴더나 영상 폴더에 저장하지 않음.

    TJS_Animatic은 시즌이 없어 작품을 고르면 빈 job으로 모든 job의 영상을 보여 줌. 리뷰어 재현: TJS_921/a.mov의 썸네일이
    전에 연 Desktop_clips/.yesoncheck_thumb에, TJS_922의 것이 TJS_921/.yesoncheck_thumb에 저장됐음.
    """
    clips = tmp_path / "Desktop_clips"
    write_test_video(str(clips / "c.mov"))
    works = os.path.join(work_area.local, "works")
    for job, name in (("TJS_921", "a"), ("TJS_922", "b")):
        write_test_video(os.path.join(works, job, f"{name}.mov"))
    player = new_player(make_config(work_area.local, {"TJS_Animatic": work_area.stored + "/works"}, work_area.path_map))
    player.load_videos_from_folder(str(clips))  # 이번 실행에서 먼저 연 폴더
    clips_thumbs = clips / thumbnails.FOLDER_NAME
    assert os.listdir(clips_thumbs) == []

    player.workComboBox.setCurrentText("TJS_Animatic")
    assert player.sidebar.count() == 2  # 빈 job: 모든 job의 영상
    player.switch_to_thumbnail_mode()
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()
    assert os.listdir(clips_thumbs) == []
    for root, dirs, _files in os.walk(works):
        assert thumbnails.FOLDER_NAME not in dirs, root
    assert thumbnail_warnings(dialogs) == []
    assert all(not player.sidebar.item(i).icon().isNull() for i in range(player.sidebar.count()))  # 화면에는 보임


def test_folder_loads_clear_job_thumbnail_state(new_player, dialogs, tmp_path, monkeypatch):
    """폴더 선택·북마크·사이드바에 끌어다 놓기는 자기 썸네일 폴더를 정하므로 job의 미뤄 둔 문제·'화면에만' 상태를 지움."""
    from PyQt5.QtCore import QMimeData, QPointF, Qt, QUrl
    from PyQt5.QtGui import QDropEvent

    player = new_player(make_config(str(tmp_path), {}))
    monkeypatch.setattr(player, "save_bookmarks", lambda: None)  # 끌어다 놓은 폴더를 사용자의 북마크 파일에 쓰지 않게
    folder = tmp_path / "clips"
    write_test_video(str(folder / "c.mov"))

    def leave_job_state():
        player._thumbnail_folder_problem = ("job/.yesoncheck_thumb", FOLDER_PROBLEM, "이유")
        player._thumbnail_memory_only = True

    def job_state():
        return player._thumbnail_folder_problem, player._thumbnail_memory_only

    leave_job_state()
    player.load_videos_from_folder(str(folder))  # 폴더 선택
    assert job_state() == (None, False)

    leave_job_state()
    player.setup_thumbnail_folder_for_bookmark(str(folder))  # 북마크
    assert job_state() == (None, False)

    leave_job_state()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(folder))])
    drop = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    assert player.eventFilter(player.sidebar, drop) is True  # 사이드바에 끌어다 놓기
    assert job_state() == (None, False)
    assert player.current_thumbnail_folder == str(folder / thumbnails.FOLDER_NAME)


def video_stat_times_out(monkeypatch, video):
    """video만 os.stat이 시간 초과 (끊긴 공유처럼). os.path.isfile은 이 오류를 숨기고 False를 돌려줌."""
    real_stat = os.stat

    def stat_(path, *args, **kwargs):
        if os.fspath(path) == video:
            raise TimeoutError(errno.ETIMEDOUT, "Operation timed out", video)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat_)


def test_unreadable_video_is_reported_in_thumbnail_mode(new_player, dialogs, tmp_path, monkeypatch):
    """영상을 확인하지 못하면(없어진 것 말고: 권한·시간 초과·끊긴 공유) 조용히 건너뛰지 않고 "영상 확인 실패" 창 한 번."""
    bad = write_test_video(str(tmp_path / "job" / "a.mov"))
    good = write_test_video(str(tmp_path / "job" / "b.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([bad, good])
    folder = thumbnails.ensure_folder(str(tmp_path / "job"))
    player.current_thumbnail_folder = folder
    video_stat_times_out(monkeypatch, bad)
    player.generate_thumbnails_for_all_items()
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()
    warnings = thumbnail_warnings(dialogs)
    assert [title for title, _text in warnings] == [VIDEO_PROBLEM]
    assert bad in warnings[0][1] and "timed out" in warnings[0][1]
    assert not player.sidebar.item(1).icon().isNull()  # 다른 영상은 만듦
    monkeypatch.undo()
    assert not os.path.exists(thumbnails.thumbnail_path(folder, bad))


def test_generate_thumbnail_reports_unreadable_video(new_player, dialogs, tmp_path, monkeypatch):
    """썸네일이 있는 영상의 수정 시각을 읽지 못함 → 없어진 것으로 보지 않고 알림, 워커는 띄우지 않음."""
    video = write_test_video(str(tmp_path / "job" / "a.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([video])
    folder = thumbnails.ensure_folder(str(tmp_path / "job"))
    player.current_thumbnail_folder = folder
    assert red_pixmap().save(thumbnails.thumbnail_path(folder, video), "JPG")
    video_stat_times_out(monkeypatch, video)
    assert player.generate_thumbnail(video) is False
    assert player.thumbnail_workers == []
    warnings = thumbnail_warnings(dialogs)
    assert [title for title, _text in warnings] == [VIDEO_PROBLEM]
    assert video in warnings[0][1] and "timed out" in warnings[0][1]


def test_thumbnail_mode_checks_each_video_once(new_player, dialogs, tmp_path, monkeypatch):
    """썸네일 모드를 켜면 영상마다 NAS의 썸네일을 한 번만 확인 (예전에는 switch_to_thumbnail_mode가 같은 확인을 먼저 한 번 더)."""
    video = write_test_video(str(tmp_path / "job" / "a.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([video])
    folder = thumbnails.ensure_folder(str(tmp_path / "job"))
    player.current_thumbnail_folder = folder
    assert red_pixmap().save(thumbnails.thumbnail_path(folder, video), "JPG")  # 영상보다 새 썸네일
    real_is_fresh = thumbnails.is_fresh
    checked = []

    def counting_is_fresh(thumb_path, video_path):
        checked.append(video_path)
        return real_is_fresh(thumb_path, video_path)

    monkeypatch.setattr(thumbnails, "is_fresh", counting_is_fresh)
    player.switch_to_thumbnail_mode()
    assert checked == [video]
    assert not player.sidebar.item(0).icon().isNull()
    assert player.thumbnail_workers == []


def stat_fails_under(monkeypatch, root, error):
    """root 아래 경로만 os.stat이 error(errno, 설명)를 냄 (끊긴 공유처럼)."""
    real_stat = os.stat
    error_type, code, text = error
    prefix = os.path.join(str(root), "")

    def stat_(path, *args, **kwargs):
        name = os.fspath(path)
        if name.startswith(prefix):
            raise error_type(code, text, name)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat_)


def test_unreachable_share_is_not_a_vanished_video(new_player, dialogs, tmp_path, monkeypatch, capsys):
    """Windows는 끊긴 SMB 공유(ERROR_BAD_NETPATH·BAD_NET_NAME)를 FileNotFoundError로 올림 (Mac autofs도 그럴 수 있음).

    영상의 폴더도 확인하지 못하면 "없어진 영상"이 아니라 "영상 확인 실패"로 알림 (두 오류 모두)."""
    share = tmp_path / "share"
    video = write_test_video(str(share / "job" / "a.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([video])
    stat_fails_under(monkeypatch, share, (FileNotFoundError, errno.ENOENT, "The network path was not found"))
    player.generate_thumbnails_for_all_items()
    warnings = thumbnail_warnings(dialogs)
    assert [title for title, _text in warnings] == [VIDEO_PROBLEM]
    text = warnings[0][1]
    assert video in text and os.path.dirname(video) in text and text.count("The network path was not found") == 2


def test_video_removed_from_reachable_folder_only_logs(new_player, dialogs, tmp_path, monkeypatch, capsys):
    video = write_test_video(str(tmp_path / "job" / "a.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([video])
    os.remove(video)  # 폴더는 그대로, 영상만 없어짐
    player.generate_thumbnails_for_all_items()
    assert thumbnail_warnings(dialogs) == []
    assert "영상이 없어져 썸네일을 건너뜀" in capsys.readouterr().out


def test_unreadable_videos_without_thumbnail_folder_one_dialog(new_player, dialogs, work_area, monkeypatch):
    """job을 고르지 않은 목록(여러 job의 영상, 썸네일 폴더 없음)에서 영상들을 확인하지 못해도 창은 한 번 (영상 폴더마다가 아니라)."""
    works = os.path.join(work_area.local, "works")
    for job in ("TJS_921", "TJS_922", "TJS_923"):
        write_test_video(os.path.join(works, job, "a.mov"))
    player = new_player(make_config(work_area.local, {"TJS_Animatic": work_area.stored + "/works"}, work_area.path_map))
    player.workComboBox.setCurrentText("TJS_Animatic")
    assert player.sidebar.count() == 3 and player.current_thumbnail_folder is None
    # 앱이 보는 경로로 끊김을 흉내 냄 (Windows CI: 파일은 로컬 경로로 만들었지만 앱은 변환표의 UNC로 목록을 만듦)
    listed_works = os.path.dirname(os.path.dirname(player.sidebar.item(0).data(Qt.UserRole)))
    stat_fails_under(monkeypatch, listed_works, (TimeoutError, errno.ETIMEDOUT, "Operation timed out"))
    player.switch_to_thumbnail_mode()
    warnings = thumbnail_warnings(dialogs)
    assert [title for title, _text in warnings] == [VIDEO_PROBLEM]
    assert "Operation timed out" in warnings[0][1] and "TJS_921" in warnings[0][1]


def drop_folder(player, target, folder):
    """폴더를 실제 QDropEvent로 끌어다 놓음. target: "video"(영상 영역 CustomVideoWidget) 또는 "sidebar"(사이드바 eventFilter)."""
    from PyQt5.QtCore import QMimeData, QPointF, QUrl
    from PyQt5.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(folder))])
    event = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    if target == "video":
        player.videoWidget.dropEvent(event)
    else:
        assert player.eventFilter(player.sidebar, event) is True


def open_smoke_work(new_player, work_area, monkeypatch, select_job):
    """작품 SMOKE·시즌 S1을 고르고 select_job이면 job_01까지 (북마크 파일은 쓰지 않게 가짜로)."""
    write_test_video(os.path.join(work_area.local, "S1", "job_01", "scene-001", "frames", "a.mov"))
    player = new_player(make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map))
    monkeypatch.setattr(player, "save_bookmarks", lambda: None)
    player.workComboBox.setCurrentText("SMOKE")
    player.seasonComboBox.setCurrentText("S1")
    if select_job:
        player.jobComboBox.setCurrentText("job_01")
        assert player.current_thumbnail_folder
    else:
        assert player._thumbnail_memory_only
    return player


def listed_path(player, name):
    """사이드바 항목이 가진(앱이 쓰는) 영상 경로."""
    found = [player.sidebar.item(i).data(Qt.UserRole) for i in range(player.sidebar.count())
             if os.path.basename(player.sidebar.item(i).data(Qt.UserRole)) == name]
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize("select_job", [True, False], ids=["after_job", "no_job"])
@pytest.mark.parametrize("target", ["video", "sidebar"])
def test_dropped_folder_thumbnails_saved_in_that_folder(new_player, dialogs, work_area, tmp_path, monkeypatch,
                                                        target, select_job):
    """끌어다 놓은 폴더의 썸네일은 그 폴더의 .yesoncheck_thumb에 (전에 고른 job 폴더나 '화면에만'이 아니라).

    사용자 보고 N3: 영상 영역에 폴더를 끌어다 놓으면 썸네일 폴더를 정하지 않아 전에 고른 job 폴더에 저장됐음.
    """
    player = open_smoke_work(new_player, work_area, monkeypatch, select_job)
    job_thumbs = player.current_thumbnail_folder  # 앱이 쓰는 경로 (job을 고르지 않았으면 None)
    job_before = os.listdir(job_thumbs) if job_thumbs else None
    dropped = tmp_path / "X_dropped"
    write_test_video(str(dropped / "c.mov"))

    drop_folder(player, target, dropped)
    assert os.path.samefile(player.current_thumbnail_folder, dropped / thumbnails.FOLDER_NAME)
    player.switch_to_thumbnail_mode()
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()

    dropped_video = listed_path(player, "c.mov")
    assert os.path.isfile(thumbnails.thumbnail_path(player.current_thumbnail_folder, dropped_video))
    if job_thumbs:
        assert not os.path.exists(thumbnails.thumbnail_path(job_thumbs, dropped_video))
        if target == "video":  # 영상 영역은 목록을 바꿈 → job 폴더는 그대로 (사이드바는 덧붙여 job 영상은 job 폴더에)
            assert os.listdir(job_thumbs) == job_before
    else:
        for root, dirs, _files in os.walk(os.path.join(work_area.local, "S1")):
            assert thumbnails.FOLDER_NAME not in dirs, root
    assert thumbnail_warnings(dialogs) == []


@pytest.mark.parametrize("target", ["video", "sidebar"])
def test_dropped_folder_thumbnail_folder_failure(new_player, dialogs, work_area, tmp_path, monkeypatch, target):
    """끌어다 놓은 폴더의 썸네일 폴더를 만들지 못해도 예외·창 없이 받아들이고, 썸네일 모드에서 "썸네일 폴더 문제" 한 번.
    썸네일은 화면에만 (전에 고른 job 폴더에 저장하지 않음)."""
    player = open_smoke_work(new_player, work_area, monkeypatch, select_job=True)
    job_thumbs = player.current_thumbnail_folder
    job_before = os.listdir(job_thumbs)
    dropped = tmp_path / "X_dropped"
    write_test_video(str(dropped / "c.mov"))
    real_ensure_folder = thumbnails.ensure_folder

    def dropped_folder_fails(parent_dir):
        if os.path.basename(os.path.normpath(parent_dir)) == "X_dropped":  # 앱이 넘기는 경로 그대로 판단
            raise PermissionError(errno.EACCES, "Permission denied", os.path.join(parent_dir, thumbnails.FOLDER_NAME))
        return real_ensure_folder(parent_dir)

    monkeypatch.setattr(thumbnails, "ensure_folder", dropped_folder_fails)
    drop_folder(player, target, dropped)  # 예외 없음
    assert player.current_thumbnail_folder is None
    assert thumbnail_warnings(dialogs) == []  # 끌어다 놓을 때는 창 없음

    player.switch_to_thumbnail_mode()
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()
    warnings = thumbnail_warnings(dialogs)
    assert [title for title, _text in warnings] == [FOLDER_PROBLEM]
    text = warnings[0][1]
    assert os.path.join("X_dropped", thumbnails.FOLDER_NAME) in text and "Permission denied" in text and "화면에만" in text
    assert not os.path.exists(thumbnails.thumbnail_path(job_thumbs, listed_path(player, "c.mov")))
    if target == "video":  # 영상 영역은 목록을 바꿈 → job 폴더는 그대로 (사이드바는 덧붙여 job 영상은 job 폴더에)
        assert os.listdir(job_thumbs) == job_before
    assert not (dropped / thumbnails.FOLDER_NAME).exists()
    assert all(not player.sidebar.item(i).icon().isNull() for i in range(player.sidebar.count()))


def open_tjs_work(new_player, work_area, monkeypatch, job=None):
    """TJS_Animatic(시즌 없음, job TJS_921에 a.mov)을 고르고 job이면 그 job까지 → (창, 작품 폴더의 로컬 경로)."""
    works = os.path.join(work_area.local, "works")
    write_test_video(os.path.join(works, "TJS_921", "a.mov"))
    player = new_player(make_config(work_area.local, {"TJS_Animatic": work_area.stored + "/works"}, work_area.path_map))
    monkeypatch.setattr(player, "save_bookmarks", lambda: None)  # 끌어다 놓은 폴더를 사용자의 북마크 파일에 쓰지 않게
    player.workComboBox.setCurrentText("TJS_Animatic")
    if job:
        player.jobComboBox.setCurrentText(job)
    return player, works


def append_dropped_folder(player, tmp_path, name="other"):
    """c.mov가 든 폴더를 사이드바에 끌어다 놓아 목록에 덧붙임 → (그 폴더의 썸네일 폴더(앱 경로), c.mov(앱 경로))."""
    dropped = tmp_path / name
    write_test_video(str(dropped / "c.mov"))
    drop_folder(player, "sidebar", dropped)
    return player.current_thumbnail_folder, listed_path(player, "c.mov")


def thumbnail_width(path):
    from PyQt5.QtGui import QPixmap

    return QPixmap(path).width()


def turn_on_thumbnail_mode(player):
    player.switch_to_thumbnail_mode()
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()


def test_appended_folder_keeps_each_video_thumbnail_folder(new_player, dialogs, work_area, tmp_path, monkeypatch):
    """재검토 L1: job TJS_921을 고른 뒤 other/를 사이드바에 끌어다 놓으면(덧붙임) 영상마다 들어온 곳의 썸네일 폴더를 씀.

    예전에는 둘 다 other/.yesoncheck_thumb에 저장해 TJS_921의 (Mac과 함께 쓰는) 썸네일을 쓰지 않고 엉뚱한 곳에 중복을 만들었음.
    """
    player, _works = open_tjs_work(new_player, work_area, monkeypatch, job="TJS_921")
    job_thumbs = player.current_thumbnail_folder
    a = listed_path(player, "a.mov")
    assert red_pixmap(7, 5).save(thumbnails.thumbnail_path(job_thumbs, a), "JPG")  # 영상보다 새 썸네일 (예: Mac이 만든 것)
    other_thumbs, c = append_dropped_folder(player, tmp_path)
    assert not os.path.samefile(other_thumbs, job_thumbs)

    turn_on_thumbnail_mode(player)
    assert thumbnail_width(thumbnails.thumbnail_path(job_thumbs, a)) == 7  # 다시 만들지 않고 그대로 씀
    assert thumbnail_width(thumbnails.thumbnail_path(other_thumbs, c)) == 120
    assert not os.path.exists(thumbnails.thumbnail_path(other_thumbs, a))
    assert not os.path.exists(thumbnails.thumbnail_path(job_thumbs, c))
    assert all(not player.sidebar.item(i).icon().isNull() for i in range(player.sidebar.count()))
    assert thumbnail_warnings(dialogs) == []


def test_memory_only_videos_stay_in_memory_after_folder_append(new_player, dialogs, work_area, tmp_path, monkeypatch):
    """job을 고르지 않은 목록(화면에만) + 사이드바에 폴더를 덧붙임 → 원래 영상은 어디에도 쓰지 않고 새 영상은 그 폴더에."""
    player, works = open_tjs_work(new_player, work_area, monkeypatch)
    assert player._thumbnail_memory_only
    a = listed_path(player, "a.mov")
    other_thumbs, c = append_dropped_folder(player, tmp_path)

    turn_on_thumbnail_mode(player)
    assert os.path.isfile(thumbnails.thumbnail_path(other_thumbs, c))
    assert not os.path.exists(thumbnails.thumbnail_path(other_thumbs, a))
    for root, dirs, _files in os.walk(works):
        assert thumbnails.FOLDER_NAME not in dirs, root
    assert all(not player.sidebar.item(i).icon().isNull() for i in range(player.sidebar.count()))
    assert thumbnail_warnings(dialogs) == []


def test_job_folder_problem_kept_after_folder_append(new_player, dialogs, work_area, tmp_path, monkeypatch):
    """썸네일 폴더를 만들지 못한 job + 사이드바에 폴더를 덧붙임 → job 폴더 문제 창 한 번, 덧붙인 영상은 그 폴더에 저장."""
    real_ensure_folder = thumbnails.ensure_folder

    def job_fails(parent_dir):
        if os.path.basename(os.path.normpath(parent_dir)) == "TJS_921":
            raise PermissionError(errno.EACCES, "Permission denied", os.path.join(parent_dir, thumbnails.FOLDER_NAME))
        return real_ensure_folder(parent_dir)

    monkeypatch.setattr(thumbnails, "ensure_folder", job_fails)
    player, works = open_tjs_work(new_player, work_area, monkeypatch, job="TJS_921")
    assert player.current_thumbnail_folder is None and player._thumbnail_folder_problem is not None
    a = listed_path(player, "a.mov")
    other_thumbs, c = append_dropped_folder(player, tmp_path)

    turn_on_thumbnail_mode(player)
    warnings = thumbnail_warnings(dialogs)
    assert [title for title, _text in warnings] == [FOLDER_PROBLEM]
    assert os.path.join("TJS_921", thumbnails.FOLDER_NAME) in warnings[0][1]
    assert os.path.isfile(thumbnails.thumbnail_path(other_thumbs, c))
    assert not os.path.exists(thumbnails.thumbnail_path(other_thumbs, a))
    for root, dirs, _files in os.walk(works):
        assert thumbnails.FOLDER_NAME not in dirs, root
    assert all(not player.sidebar.item(i).icon().isNull() for i in range(player.sidebar.count()))


def test_regenerate_uses_each_video_thumbnail_folder(new_player, dialogs, work_area, tmp_path, monkeypatch):
    """"썸네일 재생성"은 영상마다 자기 썸네일 폴더에서 지우고 다시 만듦 (덧붙인 영상도, 원래 영상도)."""
    player, _works = open_tjs_work(new_player, work_area, monkeypatch, job="TJS_921")
    job_thumbs = player.current_thumbnail_folder
    a = listed_path(player, "a.mov")
    other_thumbs, c = append_dropped_folder(player, tmp_path)
    assert red_pixmap(7, 5).save(thumbnails.thumbnail_path(job_thumbs, a), "JPG")
    assert red_pixmap(7, 5).save(thumbnails.thumbnail_path(other_thumbs, c), "JPG")

    player.sidebar.selectAll()
    player.regenerate_selected_thumbnails()
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()
    assert thumbnail_width(thumbnails.thumbnail_path(job_thumbs, a)) == 120
    assert thumbnail_width(thumbnails.thumbnail_path(other_thumbs, c)) == 120
    assert not os.path.exists(thumbnails.thumbnail_path(other_thumbs, a))
    assert not os.path.exists(thumbnails.thumbnail_path(job_thumbs, c))


def test_background_loader_reads_each_video_thumbnail_folder(new_player, dialogs, work_area, tmp_path, monkeypatch):
    """백그라운드 썸네일 불러오기도 영상마다 자기 썸네일 폴더에서 읽음."""
    player, _works = open_tjs_work(new_player, work_area, monkeypatch, job="TJS_921")
    job_thumbs = player.current_thumbnail_folder
    a = listed_path(player, "a.mov")
    other_thumbs, c = append_dropped_folder(player, tmp_path)
    player.thumbnail_loading_timer.stop()
    for folder, video, width in ((job_thumbs, a, 7), (other_thumbs, c, 9),  # 자기 폴더의 썸네일
                                 (other_thumbs, a, 13), (job_thumbs, c, 11)):  # 남의 폴더에 있는 같은 영상의 썸네일 (읽으면 안 됨)
        assert red_pixmap(width, 5).save(thumbnails.thumbnail_path(folder, video), "JPG")
    loaded = []
    monkeypatch.setattr(player, "on_background_thumbnail_loaded",
                        lambda path, pixmap: loaded.append((os.path.basename(path), pixmap.width())))
    player.start_background_thumbnail_loading()
    wait_until(lambda: player.thumbnail_loader_worker is None)
    assert sorted(loaded) == [("a.mov", 7), ("c.mov", 9)]


def test_duplicate_video_keeps_its_thumbnail_context(new_player, dialogs, work_area, tmp_path, monkeypatch):
    """이미 목록에 있는 영상을 다시 넣으면(그 job 폴더를 끌어다 놓음) 원래 항목의 자리(여기서는 화면에만)를 그대로 씀."""
    player, _works = open_tjs_work(new_player, work_area, monkeypatch)
    a = listed_path(player, "a.mov")
    job_folder = os.path.dirname(a)  # 앱이 쓰는 경로
    drop_folder(player, "sidebar", job_folder)
    assert player.sidebar.count() == 2
    dropped_thumbs = player.current_thumbnail_folder
    assert os.path.samefile(dropped_thumbs, os.path.join(job_folder, thumbnails.FOLDER_NAME))

    turn_on_thumbnail_mode(player)
    assert os.listdir(dropped_thumbs) == []
    assert thumbnail_warnings(dialogs) == []


def record_worker_starts(monkeypatch):
    """사이드바가 띄우는 썸네일 워커의 영상 경로를 차례로 기록하는 목록."""
    import yesoncheck.player_sidebar as sidebar_module

    real_worker = sidebar_module.ThumbnailWorker
    started = []

    def counting_worker(file_path, *args):
        started.append(file_path)
        return real_worker(file_path, *args)

    monkeypatch.setattr(sidebar_module, "ThumbnailWorker", counting_worker)
    return started


@pytest.mark.parametrize("how", ["thumbnail_mode", "add_files", "regenerate"])
def test_switching_job_during_thumbnail_loop_stops_cleanly(new_player, dialogs, work_area, tmp_path, monkeypatch, how):
    """썸네일을 만드는 동안(이벤트 처리 중) 다른 job을 고르면 예전 목록의 항목이 지워짐 → 예외·오류 창 없이 멈추고,
    예전 목록의 나머지는 만들지 않으며 새 job 폴더에 쓰지 않음 (리뷰어 재현 F1: RuntimeError … QListWidgetItem has been deleted)."""
    from PyQt5.QtCore import QTimer

    for name in ("a", "b", "c"):
        write_test_video(os.path.join(work_area.local, "S1", "job_01", "scene-001", "frames", f"{name}.mov"))
    write_test_video(os.path.join(work_area.local, "S1", "job_02", "scene-001", "frames", "d.mov"))
    player = new_player(make_config(work_area.local, {"SMOKE": work_area.stored}, work_area.path_map))
    player.workComboBox.setCurrentText("SMOKE")
    player.seasonComboBox.setCurrentText("S1")
    player.jobComboBox.setCurrentText("job_01")
    old_thumbs = player.current_thumbnail_folder
    if how != "thumbnail_mode":
        turn_on_thumbnail_mode(player)  # job_01의 썸네일을 먼저 다 만들어 둠
    if how == "add_files":
        extra = [write_test_video(str(tmp_path / "extra" / f"{name}.mov")) for name in ("e", "f", "g")]
    old_videos = [player.sidebar.item(i).data(Qt.UserRole) for i in range(player.sidebar.count())]
    if how == "add_files":
        old_videos += extra
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc))  # 슬롯 안에서 난 예외도 기록
    real_generate = player.generate_thumbnail
    calls = []

    def generate_then_switch_job(*args, **kwargs):
        if not calls:  # 첫 썸네일을 만드는 중에 사용자가 다른 job을 고름
            QTimer.singleShot(0, lambda: player.jobComboBox.setCurrentText("job_02"))
        calls.append(args[0])
        return real_generate(*args, **kwargs)

    monkeypatch.setattr(player, "generate_thumbnail", generate_then_switch_job)
    started = record_worker_starts(monkeypatch)
    if how == "thumbnail_mode":
        player.switch_to_thumbnail_mode()
    elif how == "add_files":
        player.add_files_to_sidebar(extra)
    else:
        player.sidebar.selectAll()
        player.regenerate_selected_thumbnails()
    wait_until(lambda: not player.thumbnail_workers)
    QApplication.processEvents()

    assert errors == []
    assert dialogs.errors() == []
    assert [os.path.basename(player.sidebar.item(i).data(Qt.UserRole)) for i in range(player.sidebar.count())] == ["d.mov"]
    new_thumbs = player.current_thumbnail_folder
    assert not os.path.samefile(new_thumbs, old_thumbs)
    assert not any(os.path.exists(thumbnails.thumbnail_path(new_thumbs, video)) for video in old_videos)
    assert len(started) == 1  # 예전 목록은 처음 것만: 바뀐 뒤로는 워커를 띄우지 않음 (기다리던 것도 만들지 않음)


def test_duplicate_video_generated_once_with_both_icons(new_player, dialogs, tmp_path, monkeypatch):
    """같은 영상이 목록에 두 번 있으면 썸네일은 한 번만 만들고 두 항목 모두에 아이콘 (재검토 F2)."""
    video = write_test_video(str(tmp_path / "job" / "a.mov"))
    player = new_player(make_config(str(tmp_path), {}))
    player.add_files_to_sidebar([video])
    player.add_files_to_sidebar([video])
    assert player.sidebar.count() == 2
    started = record_worker_starts(monkeypatch)
    turn_on_thumbnail_mode(player)
    assert started == [video]
    assert all(not player.sidebar.item(i).icon().isNull() for i in range(2))
