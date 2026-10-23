"""이미지 시퀀스 캡처(ImageSequenceCapture): cv2.VideoCapture와 같은 의미 (read/set/get), 빠진 프레임, fps, 열기 오류."""

import os
import subprocess

import cv2
import numpy as np
import pytest
from PIL import Image

from yesoncheck import external_tools
from yesoncheck.sequence_source import ImageSequenceCapture, open_any_capture

POS = cv2.CAP_PROP_POS_FRAMES
COUNT = cv2.CAP_PROP_FRAME_COUNT
FPS = cv2.CAP_PROP_FPS
WIDTH = cv2.CAP_PROP_FRAME_WIDTH
HEIGHT = cv2.CAP_PROP_FRAME_HEIGHT

# 프레임을 서로 알아볼 수 있는 단색 (RGB) — h264는 손실이라 평균색의 가장 가까운 색으로 프레임을 식별한다
PALETTE = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255), (255, 255, 255), (0, 0, 0)]
SIZE = (64, 48)


def color_for(n):
    return PALETTE[n % len(PALETTE)]


def make_frame(path, color, size=SIZE):
    ext = os.path.splitext(path)[1][1:].lower()
    Image.new("RGB", size, color).save(path, format={"tga": "TGA", "png": "PNG"}[ext])


def make_seq(folder, base, nums, ext="tga", pad=4):
    """프레임 번호마다 color_for(번호) 단색인 시퀀스를 만들고 가상 경로(.seq)를 돌려줌."""
    os.makedirs(folder, exist_ok=True)
    for n in nums:
        make_frame(os.path.join(folder, f"{base}-{n:0{pad}d}.{ext}"), color_for(n))
    return os.path.join(folder, base + ".seq")


def identify(frame):
    """프레임 평균색(BGR)에서 가장 가까운 PALETTE 번호."""
    mean = frame.reshape(-1, 3).mean(axis=0)
    distances = [np.linalg.norm(mean - np.array(c[::-1])) for c in PALETTE]
    return int(np.argmin(distances))


def make_movie(path, fps, frames=3, color="red"):
    subprocess.run(
        [external_tools.ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=64x48:r={fps}",
         "-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
        check=True, capture_output=True)


def make_movie_from_frames(path, frames_pattern, fps):
    subprocess.run(
        [external_tools.ffmpeg_path(), "-y", "-v", "error", "-framerate", str(fps), "-i", frames_pattern,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "10", path],
        check=True, capture_output=True)


def test_cv2_semantics_parity(tmp_path):
    """같은 6프레임을 mov·mp4와 시퀀스로 만들어 같은 호출열을 돌리면 성공 여부·pos·프레임이 모두 같다."""
    seq_dir = str(tmp_path / "seq")
    numbers = range(1, 7)
    identity = make_seq(seq_dir, "EX01_tk1", numbers)
    png_dir = tmp_path / "png"
    png_dir.mkdir()
    for n in numbers:
        make_frame(str(png_dir / f"f{n:04d}.png"), color_for(n))

    def run(cap):
        """cap에 호출열을 돌려 [(호출, 결과)]를 모은다. 프레임은 식별 번호로."""
        log = []

        def read():
            ok, frame = cap.read()
            log.append(("read", ok, None if frame is None else identify(frame), cap.get(POS)))

        def seek(n):
            log.append(("set", n, cap.set(POS, n), cap.get(POS)))

        log.append(("props", cap.isOpened(), cap.get(COUNT), cap.get(POS), cap.get(WIDTH), cap.get(HEIGHT)))
        for _ in range(3):
            read()
        for n in (2, 0, 5, 6, 100, -1, 3.0, 2.7):  # 중간·처음·마지막·끝·끝 너머·음수·실수
            seek(n)
            read()
        seek(5)
        for _ in range(3):  # 끝을 넘겨 읽기: 실패, pos 그대로
            read()
        seek(0)
        for _ in range(8):  # 처음부터 끝까지 + 끝 너머
            read()
        log.append(("set-other", cap.set(FPS, 10.0)))
        log.append(("get-unknown", cap.get(9999)))
        return log

    results = {}
    for ext in ("mov", "mp4"):
        movie = str(tmp_path / f"parity.{ext}")
        make_movie_from_frames(movie, str(png_dir / "f%04d.png"), 24)
        video = cv2.VideoCapture(movie)
        assert video.isOpened()
        results[ext] = run(video)
        video.release()

    sequence = ImageSequenceCapture(identity)
    assert sequence.isOpened()
    sequence_log = run(sequence)
    sequence.release()

    assert results["mov"] == results["mp4"]  # 비교 기준(cv2) 자체가 컨테이너와 무관한지
    assert sequence_log == results["mov"]
    # 값의 형식도 같다: get은 float
    fresh = ImageSequenceCapture(identity)
    assert all(type(fresh.get(p)) is float for p in (FPS, COUNT, POS, WIDTH, HEIGHT, 9999))
    fresh.release()


def test_read_advances_pos_and_eof(tmp_path):
    cap = ImageSequenceCapture(make_seq(str(tmp_path), "EX01_tk1", range(1, 4)))
    assert cap.isOpened()
    assert cap.get(COUNT) == 3.0 and cap.get(POS) == 0.0
    for expected in range(3):
        ok, frame = cap.read()
        assert ok and identify(frame) == (expected + 1) % len(PALETTE)
        assert cap.get(POS) == expected + 1.0
    for _ in range(2):  # 끝을 넘겨 읽으면 실패하고 pos는 그대로
        assert cap.read() == (False, None)
        assert cap.get(POS) == 3.0
    assert cap.set(POS, 1) is True
    ok, frame = cap.read()
    assert ok and identify(frame) == 2 and cap.get(POS) == 2.0
    cap.release()


def test_read_returns_bgr_uint8_contiguous(tmp_path):
    cap = ImageSequenceCapture(make_seq(str(tmp_path), "EX01_tk1", range(1, 3)))
    ok, frame = cap.read()
    assert ok and frame.shape == (48, 64, 3) and frame.dtype == np.uint8 and frame.flags["C_CONTIGUOUS"]
    assert tuple(frame[0, 0]) == color_for(1)[::-1]  # BGR
    cap.release()


def test_each_read_returns_a_fresh_array(tmp_path):
    """cv2처럼 읽을 때마다 새 배열 (받은 쪽이 그려 넣어도 다음 읽기에 영향이 없음)."""
    cap = ImageSequenceCapture(make_seq(str(tmp_path), "EX01_tk1", range(1, 3)))
    _, first = cap.read()
    first[:] = 0
    cap.set(POS, 0)
    _, again = cap.read()
    assert identify(again) == 1 and again is not first
    cap.release()


def test_nonstandard_start_number(tmp_path):
    """0101부터 5장: 프레임 수 5, 인덱스 0이 0101."""
    cap = ImageSequenceCapture(make_seq(str(tmp_path), "EX01_tk1", range(101, 106)))
    assert cap.get(COUNT) == 5.0
    assert cap.set(POS, 0) is True
    ok, frame = cap.read()
    assert ok and identify(frame) == 101 % len(PALETTE)
    cap.set(POS, 4)
    ok, frame = cap.read()
    assert ok and identify(frame) == 105 % len(PALETTE)
    assert cap.read() == (False, None)
    cap.release()


def test_fps_from_paired_mov_then_fallback_24(tmp_path):
    folder = str(tmp_path)

    def fps_of(base, nums=range(1, 4)):
        cap = ImageSequenceCapture(make_seq(folder, base, nums))
        fps = cap.get(FPS)
        cap.release()
        return fps

    assert fps_of("NOPAIR") == 24.0  # 짝 영상 없음

    make_movie(os.path.join(folder, "MOVONLY.mov"), 30)
    assert fps_of("MOVONLY") == 30.0

    make_movie(os.path.join(folder, "MP4ONLY.mp4"), 25)
    assert fps_of("MP4ONLY") == 25.0  # mov가 없으면 mp4

    make_movie(os.path.join(folder, "BOTH.mov"), 30)
    make_movie(os.path.join(folder, "BOTH.mp4"), 25)
    assert fps_of("BOTH") == 30.0  # 둘 다 있으면 mov 우선

    with open(os.path.join(folder, "BROKEN.mov"), "wb") as f:
        f.write(b"not a movie")
    assert fps_of("BROKEN") == 24.0  # 짝 영상을 못 읽으면 24

    make_movie(os.path.join(folder, "OTHER_NAME.mov"), 30)
    assert fps_of("OTHER", nums=range(1, 4)) == 24.0  # 이름이 다른 영상은 짝이 아님


def test_missing_frame_holds_previous(tmp_path, capsys):
    """0001,0003: 인덱스 1(0002)은 파일이 없으니 직전 프레임(0001)을 돌려주고, 로그는 시퀀스당 한 번."""
    cap = ImageSequenceCapture(make_seq(str(tmp_path), "EX01_tk1", [1, 3]))
    assert cap.get(COUNT) == 3.0
    capsys.readouterr()
    frames = []
    for _ in range(3):
        ok, frame = cap.read()
        assert ok
        frames.append(identify(frame))
    assert frames == [1, 1, 3]
    assert cap.get(POS) == 3.0
    cap.set(POS, 1)
    cap.read()  # 같은 빠진 프레임을 또 읽어도
    printed = capsys.readouterr().out
    assert printed.count("빠진") == 1 and "EX01_tk1" in printed
    cap.release()


def test_missing_frame_after_seek_uses_nearest_earlier(tmp_path):
    """빠진 구간으로 곧바로 탐색해도 읽은 이력과 무관하게 그 구간 바로 앞 프레임이 나온다."""
    cap = ImageSequenceCapture(make_seq(str(tmp_path), "EX01_tk1", [1, 2, 6]))
    cap.set(POS, 5)
    ok, last = cap.read()  # 0006
    assert ok and identify(last) == 6
    for index in (4, 3, 2):  # 0005·0004·0003 모두 빠짐: 0002 프레임
        cap.set(POS, index)
        ok, frame = cap.read()
        assert ok and identify(frame) == 2
    cap.release()


def test_korean_space_path(tmp_path):
    folder = str(tmp_path / "한 글 시퀀스")
    make_movie_path = os.path.join(folder, "한글 테이크.mov")
    identity = make_seq(folder, "한글 테이크", range(1, 4))
    make_movie(make_movie_path, 30)
    cap = ImageSequenceCapture(identity)
    assert cap.isOpened() and cap.get(COUNT) == 3.0 and cap.get(FPS) == 30.0
    ok, frame = cap.read()
    assert ok and identify(frame) == 1
    cap.release()


def test_uppercase_extension_and_three_digit_pad(tmp_path):
    """실제 파일 이름으로 찾으므로 `.TGA` 확장자·3자리 번호도 읽는다."""
    folder = str(tmp_path)
    for n in (1, 2, 3):
        make_frame(os.path.join(folder, f"EX01_tk1-{n:03d}.TGA"), color_for(n))
    cap = ImageSequenceCapture(os.path.join(folder, "EX01_tk1.seq"))
    assert cap.isOpened() and cap.get(COUNT) == 3.0
    ok, frame = cap.read()
    assert ok and identify(frame) == 1
    cap.release()


def test_other_sequences_in_folder_are_not_mixed_in(tmp_path):
    """base 자체에 '-'가 있거나 접두어가 같은 시퀀스가 같은 폴더에 있어도 자기 프레임만 읽는다."""
    folder = str(tmp_path)
    make_seq(folder, "scene-09B_tk1", [1, 2])
    make_seq(folder, "scene", [10, 11, 12])
    cap = ImageSequenceCapture(os.path.join(folder, "scene-09B_tk1.seq"))
    assert cap.get(COUNT) == 2.0
    assert [identify(cap.read()[1]) for _ in range(2)] == [1, 2]
    cap.release()
    cap = ImageSequenceCapture(os.path.join(folder, "scene.seq"))
    assert cap.get(COUNT) == 3.0
    assert [identify(cap.read()[1]) for _ in range(3)] == [10 % len(PALETTE), 11 % len(PALETTE), 12 % len(PALETTE)]
    cap.release()


def test_same_base_two_extensions_opens_first_group_and_says_so(tmp_path, capsys):
    """같은 base에 확장자가 다른 묶음이 둘이면(가상 경로가 같음) group_sequences 순서의 첫 묶음을 열고 로그를 남긴다."""
    folder = str(tmp_path)
    make_seq(folder, "EX01_tk1", [1, 2])
    make_seq(folder, "EX01_tk1", [5, 6, 7], ext="png")
    cap = ImageSequenceCapture(os.path.join(folder, "EX01_tk1.seq"))
    assert cap.get(COUNT) == 3.0  # png 5~7 (정렬에서 png가 tga보다 앞)
    assert identify(cap.read()[1]) == 5
    assert "여러" in capsys.readouterr().out
    cap.release()


def test_frame_width_height_props(tmp_path):
    folder = str(tmp_path)
    for n in (1, 2):
        make_frame(os.path.join(folder, f"EX01_tk1-{n:04d}.png"), color_for(n), size=(80, 36))
    cap = ImageSequenceCapture(os.path.join(folder, "EX01_tk1.seq"))
    assert cap.get(WIDTH) == 80.0 and cap.get(HEIGHT) == 36.0
    assert type(cap.get(WIDTH)) is float
    cap.release()


def test_frame_with_different_size_holds_last_good_frame(tmp_path, capsys):
    """첫 프레임과 해상도가 다른 프레임은 직전 정상 프레임을 돌려주고 한 번만 알린다."""
    folder = str(tmp_path)
    make_seq(folder, "EX01_tk1", [1, 3])
    make_frame(os.path.join(folder, "EX01_tk1-0002.tga"), color_for(2), size=(32, 24))
    cap = ImageSequenceCapture(os.path.join(folder, "EX01_tk1.seq"))
    capsys.readouterr()
    ok, first = cap.read()
    ok2, odd = cap.read()
    ok3, third = cap.read()
    assert ok and ok2 and ok3
    assert identify(first) == 1 and identify(odd) == 1 and identify(third) == 3
    assert odd.shape == first.shape and odd is not first
    cap.set(POS, 1)
    cap.read()
    assert capsys.readouterr().out.count("해상도") == 1
    cap.release()


def test_open_unknown_base_not_opened(tmp_path, capsys):
    make_seq(str(tmp_path), "EX01_tk1", range(1, 4))
    cap = ImageSequenceCapture(str(tmp_path / "EX99_tk1.seq"))
    assert cap.isOpened() is False
    assert cap.read() == (False, None)
    assert cap.get(COUNT) == 0.0 and cap.get(FPS) == 0.0 and cap.get(POS) == 0.0
    assert cap.set(POS, 0) is False
    cap.release()
    assert "EX99_tk1" in capsys.readouterr().out  # 왜 열리지 않았는지 로그에 남음


def test_single_file_is_not_a_sequence(tmp_path):
    make_seq(str(tmp_path), "EX01_tk1", [1])
    assert ImageSequenceCapture(str(tmp_path / "EX01_tk1.seq")).isOpened() is False


def test_unreadable_folder_raises_not_swallowed(tmp_path):
    with pytest.raises(FileNotFoundError):
        ImageSequenceCapture(str(tmp_path / "없는 폴더" / "EX01_tk1.seq"))


def test_non_sequence_path_rejected(tmp_path):
    with pytest.raises(ValueError):
        ImageSequenceCapture(str(tmp_path / "EX01_tk1.mov"))


def test_corrupt_existing_frame_raises_and_does_not_advance(tmp_path):
    """파일이 있는데 디코드가 안 되면 숨기지 않고 ValueError (빠진 프레임의 직전 프레임 유지는 파일이 없을 때만)."""
    identity = make_seq(str(tmp_path), "EX01_tk1", range(1, 4))
    with open(str(tmp_path / "EX01_tk1-0002.tga"), "wb") as f:
        f.write(b"garbage")
    cap = ImageSequenceCapture(identity)
    assert cap.read()[0] is True
    with pytest.raises(ValueError, match="EX01_tk1-0002.tga"):
        cap.read()
    assert cap.get(POS) == 1.0
    cap.release()


def test_release_clears_state_and_is_repeatable(tmp_path):
    cap = ImageSequenceCapture(make_seq(str(tmp_path), "EX01_tk1", range(1, 4)))
    cap.read()
    cap.release()
    assert cap.isOpened() is False
    assert cap.read() == (False, None)
    assert cap.get(COUNT) == 0.0 and cap.get(POS) == 0.0 and cap.get(FPS) == 0.0
    assert cap.set(POS, 0) is False
    assert not cap._names and not cap._numbers  # 파일 목록은 release로 버림
    cap.release()  # 두 번 불러도 괜찮음 (cv2처럼)


def test_open_any_capture_dispatch(tmp_path):
    identity = make_seq(str(tmp_path), "EX01_tk1", range(1, 4))
    cap = open_any_capture(identity)
    assert isinstance(cap, ImageSequenceCapture) and cap.isOpened()
    cap.release()

    movie = str(tmp_path / "EX01_tk1.mov")
    make_movie(movie, 30)
    cap = open_any_capture(movie)
    assert isinstance(cap, cv2.VideoCapture) and cap.isOpened()
    cap.release()
