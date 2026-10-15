"""썸네일 파일: <작업 폴더>/.yesoncheck_thumb/<paths.thumbnail_key(영상)>.jpg

NAS의 썸네일 폴더는 모든 Mac·Windows PC가 함께 쓴다 (PC마다 NAS 계정이 다를 수 있음).
썸네일 폴더를 만들고, 썸네일 경로를 정하고, 영상보다 새 썸네일인지 보고, 저장하는 일은 모두 여기서 한다.
오류(OSError)는 삼키지 않고 그대로 올린다 — 부른 쪽이 창·로그로 알린다.
"""

import os
import stat
import threading

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice

from yesoncheck import paths

FOLDER_NAME = ".yesoncheck_thumb"

_shared_folders = set()  # 이번 실행에서 share_folder가 확인한 썸네일 폴더 (폴더마다 chmod는 한 번만)


def ensure_folder(parent_dir):
    """parent_dir 아래 썸네일 폴더를 (없으면) 만들고 다른 계정도 쓸 수 있게 한 뒤 그 경로를 돌려준다."""
    folder = os.path.join(parent_dir, FOLDER_NAME)
    os.makedirs(folder, exist_ok=True)
    share_folder(folder)
    return folder


def share_folder(path):
    """(Mac) 내가 만든 썸네일 폴더에 0o777을 더함: 다른 NAS 계정을 쓰는 Windows PC도 썸네일을 저장할 수 있게.

    makedirs는 umask(보통 022) 때문에 0o755로 만든다. setgid·sticky 같은 다른 비트는 그대로 둔다.
    이번 실행에서 폴더마다 한 번만 한다: Mac의 SMB 마운트에서는 chmod가 성공해도 보이는 권한이 그대로(0o700으로
    합성)라서, 그러지 않으면 작업을 열 때마다 다시 chmod함 (chmod 뒤 권한은 확인하지 않음).
    """
    if paths.IS_WINDOWS or path in _shared_folders:
        return
    info = os.stat(path)
    mode = stat.S_IMODE(info.st_mode)
    if info.st_uid == os.getuid() and (mode & 0o777) != 0o777:
        os.chmod(path, mode | 0o777)
    _shared_folders.add(path)


def thumbnail_path(folder, video_path):
    """썸네일 폴더 안에서 영상의 썸네일 파일 경로."""
    return os.path.join(folder, f"{paths.thumbnail_key(video_path)}.jpg")


def is_fresh(thumb_path, video_path):
    """썸네일이 있고 영상보다 나중에(같거나) 만든 것이면 True. 영상이 바뀌었으면(다시 렌더링) False → 새로 만듦.

    썸네일이 없으면 False. 영상을 읽을 수 없으면 OSError (부르는 쪽이 영상이 있는지 먼저 확인함).
    """
    try:
        thumb_mtime = os.path.getmtime(thumb_path)
    except FileNotFoundError:
        return False
    return thumb_mtime >= os.path.getmtime(video_path)


def save(image, thumb_path):
    """image(QImage 또는 QPixmap)를 JPEG(품질 85)로 thumb_path에 저장. 실패하면 예외 (bool을 돌려주지 않음).

    같은 폴더의 임시 파일에 다 쓴 뒤 os.replace로 바꾼다: 다른 PC가 반쯤 쓴 JPEG를 읽지 않고, 실패하면 있던
    썸네일이 그대로 남는다. 다른 계정이 만든 파일(이 계정은 쓸 수 없음)도 폴더에 쓸 수 있으면 바꿀 수 있다.
    썸네일 폴더는 만들지 않는다 (ensure_folder가 함). 파일 오류는 OSError(errno·경로 포함)로 올라간다.
    """
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    encoded = image.save(buffer, "JPG", 85)
    buffer.close()
    if not encoded:
        raise RuntimeError(f"썸네일을 JPEG로 바꾸지 못했습니다 (Qt 이미지 플러그인 확인): {thumb_path}")
    # .jpg로 끝나지 않는 이름: 썸네일로 읽히지 않음. 프로세스·스레드마다 달라 여러 PC·워커가 겹쳐도 됨
    tmp_path = f"{thumb_path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_path, "wb") as fh:
            fh.write(bytes(data))
        os.replace(tmp_path, thumb_path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass  # 임시 파일을 만들기 전에 실패했거나 이미 바뀜
        raise
