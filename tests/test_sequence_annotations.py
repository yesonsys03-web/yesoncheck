"""이미지 시퀀스의 주석: 가상 경로(`<폴더>/<base>.seq`)가 정체성이라 주석 파일 이름이 정해지고, 재렌더(번호·확장자 변경)에도 같은 파일을
읽으며, 주석 굽기 내보내기는 시퀀스를 프레임 단위로 읽어 영상(.mov)으로 만든다 (소리 없음).

프레임은 번호마다 서로 다른 단색이다 (손실 없는 TGA/PNG) — 출력 mov는 h264(손실)라 색이 아닌 '주석이 그려졌는가'만 본다.
대화상자는 실제로 띄우지 않는다 (conftest의 dialogs·monkeypatch).
"""

import json
import os

import cv2
import pytest
from PyQt5.QtWidgets import QCheckBox, QDialog, QFileDialog

from tests.test_sequence_capture import make_seq
from tests.test_sequence_open import virtual
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck import external_tools, frame_annotations as fa
from yesoncheck.annotation_export import AnnotationExportWorker
from yesoncheck.frame_annotations import FrameAnnotationStore


@pytest.fixture
def player(new_player, dialogs, tmp_path):  # noqa: F811
    return new_player(make_config(str(tmp_path), {}))


def rect_item(color="#ff3333"):
    return {"type": "rect", "norm_x1": 0.1, "norm_y1": 0.1, "norm_x2": 0.9, "norm_y2": 0.9, "color": color, "stroke_width": 3}


def text_item(text="note"):
    return {"type": "text", "text": text, "norm_x1": 0.1, "norm_y1": 0.2, "color": "#ff3333"}


def annotation_ids(store):
    return sorted(item["id"] for items in store.annotations.values() for item in items)


# ---------------------------------------------------------------- 주석 파일 경로


def test_annotation_path_for_seq_identity():
    identity = os.path.join(os.sep, "d", "EX01_tk1.seq")
    expected = os.path.join(os.sep, "d", ".yesoncheck", "EX01_tk1_seq_annotations.json")
    assert fa.annotation_file_path(identity) == expected


def test_annotation_path_seq_base_may_contain_dots_and_dashes():
    identity = os.path.join(os.sep, "d", "scene-09B.v2_tk1.seq")
    expected = os.path.join(os.sep, "d", ".yesoncheck", "scene-09B.v2_tk1_seq_annotations.json")
    assert fa.annotation_file_path(identity) == expected


def test_annotation_path_mov_unchanged():
    mov = os.path.join(os.sep, "d", "EX01_tk1.mov")
    folder = os.path.join(os.sep, "d", ".yesoncheck")
    assert fa.annotation_file_path(mov) == os.path.join(folder, "EX01_tk1_annotations.json")
    assert fa.annotation_file_path(os.path.join(os.sep, "d", "clip.mp4")) == os.path.join(folder, "clip_annotations.json")
    # ".seq"가 이름 중간에 있을 뿐 시퀀스의 가상 경로가 아닌 영상은 그대로
    assert fa.annotation_file_path(os.path.join(os.sep, "d", "x.seq.mov")) == os.path.join(folder, "x.seq_annotations.json")


def test_seq_and_mov_with_same_base_do_not_share_an_annotation_file():
    """같은 폴더의 EX01_tk1.mov와 EX01_tk1 시퀀스는 별개의 영상이라 주석 파일이 겹치면 안 된다."""
    folder = os.path.join(os.sep, "d")
    assert fa.annotation_file_path(os.path.join(folder, "EX01_tk1.mov")) != fa.annotation_file_path(
        os.path.join(folder, "EX01_tk1.seq"))


# ---------------------------------------------------------------- 제안 파일명


def test_export_suggested_name_seq():
    identity = os.path.join(os.sep, "d", "EX01_tk1.seq")
    assert fa.annotation_export_suggested_name(identity) == "EX01_tk1_annotated.mov"


def test_export_suggested_name_mov_unchanged():
    assert fa.annotation_export_suggested_name(os.path.join(os.sep, "d", "a.mov")) == "a_annotated.mov"
    assert fa.annotation_export_suggested_name(os.path.join(os.sep, "d", "a.mp4")) == "a_annotated.mp4"
    assert fa.annotation_export_suggested_name(os.path.join(os.sep, "d", "noext")) == "noext_annotated.mp4"


def test_export_default_path_seq_is_a_mov_beside_the_frames_not_a_seq_file():
    identity = os.path.join(os.sep, "d", "EX01_tk1.seq")
    assert fa.annotation_export_default_path(identity) == os.path.join(os.sep, "d", "EX01_tk1_annotated.mov")
    assert fa.annotation_export_default_path(os.path.join(os.sep, "d", "a.mp4")) == os.path.join(os.sep, "d", "a_annotated.mp4")


# ---------------------------------------------------------------- 재렌더에도 주석 유지


def rerender(folder, base, numbers, ext):
    """같은 폴더·이름의 시퀀스를 다른 번호·확장자로 다시 렌더: 이미지 프레임만 바뀌고 .yesoncheck 주석 폴더는 그대로."""
    for name in os.listdir(folder):
        if os.path.isfile(os.path.join(folder, name)):
            os.remove(os.path.join(folder, name))
    return make_seq(folder, base, numbers, ext=ext)


@pytest.mark.parametrize("new_numbers, new_ext", [(range(101, 106), "tga"), (range(1, 6), "png"), (range(0, 5), "png")])
def test_annotations_survive_renumber(tmp_path, new_numbers, new_ext):
    """0001-0005로 주석을 저장한 시퀀스를 0101-0105(또는 다른 확장자)로 다시 렌더해도 같은 주석 파일을 읽는다."""
    folder = str(tmp_path / "shots")
    identity = make_seq(folder, "EX01_tk1", range(1, 6))
    first = FrameAnnotationStore()
    first.set_video(identity, 24.0)
    item = first.add(2, text_item("fix the pose"))
    saved_to = first.save()
    assert saved_to == os.path.join(folder, ".yesoncheck", "EX01_tk1_seq_annotations.json")

    rerendered = rerender(folder, "EX01_tk1", new_numbers, new_ext)
    assert rerendered == identity  # 정체성은 시작 번호·확장자와 무관

    reopened = FrameAnnotationStore()
    reopened.set_video(rerendered, 24.0)
    assert fa.annotation_file_path(rerendered) == saved_to
    assert reopened.load() is True
    assert annotation_ids(reopened) == [item["id"]]


def test_player_reopens_renumbered_sequence_with_its_annotations(player, tmp_path):
    """창에서 시퀀스를 열어 주석을 단 뒤, 프레임 번호가 달라진 같은 시퀀스를 다시 열면 그 주석이 자동으로 불러와진다."""
    folder = str(tmp_path / "shots")
    identity = make_seq(folder, "EX01_tk1", range(1, 6))
    assert player.open_file("A", identity)
    item = player.annotation_store.add(1, text_item("keep me"))
    assert player.auto_save_annotations() is True
    annotation_file = os.path.join(folder, ".yesoncheck", "EX01_tk1_seq_annotations.json")
    assert os.path.exists(annotation_file)

    rerender(folder, "EX01_tk1", range(101, 106), "tga")
    assert player.open_file("A", identity)

    assert annotation_ids(player.annotation_store) == [item["id"]]
    assert "자동 로드" in player.annotationStatusLabel.text()


# ---------------------------------------------------------------- 자동 저장·프레임 인덱스 (기존 경로가 시퀀스에서도 동작)


def test_annotation_autosave_and_frame_index_on_sequence(player, tmp_path):
    folder = str(tmp_path / "shots")
    identity = make_seq(folder, "EX01_tk1", range(1, 7))
    assert player.open_file("A", identity)
    assert player.filename_a == virtual(identity)
    assert player.get_current_frame_index() == 0

    player.seek_to_frame(4)  # 1부터 세는 4번째 프레임 -> 현재 프레임 인덱스 3 (cap_a의 위치에서 읽음)
    assert player.get_current_frame_index() == 3

    player.on_annotation_shape_finished(dict(rect_item()))  # 화면에서 도형을 그린 것과 같은 길
    annotation_file = os.path.join(folder, ".yesoncheck", "EX01_tk1_seq_annotations.json")
    assert os.path.exists(annotation_file)  # 자동 저장이 시퀀스 경로에 쓴 파일
    assert player.annotation_store.total_count() == 1
    with open(annotation_file, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["video_path"] == virtual(identity)
    assert list(saved["annotations"]) == ["3"]  # 앵커 프레임 = cap_a의 위치에서 읽은 인덱스
    assert os.listdir(os.path.join(folder, ".yesoncheck")) == ["EX01_tk1_seq_annotations.json"]

    other = FrameAnnotationStore()
    other.set_video(identity, 24.0)
    assert other.load() is True
    assert annotation_ids(other) == annotation_ids(player.annotation_store)


# ---------------------------------------------------------------- 굽기 내보내기


def run_worker(worker):
    result = {}
    worker.completed.connect(lambda path: result.update(done=path))
    worker.error.connect(lambda message: result.update(error=message))
    worker.status.connect(lambda message: result.setdefault("status", []).append(message))
    worker.run()  # 같은 스레드에서 직접 돌려, 신호가 바로 전달됨
    return result


def count_frames(path):
    cap = cv2.VideoCapture(path)
    assert cap.isOpened()
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    return frames


def mark_strength(frame, y=4):
    """프레임 위쪽 테두리 근처 한 줄(주석 사각형이 지나는 곳)이 단색 바탕에서 얼마나 벗어났는지 (색 이름과 무관하게 '그려졌는가')."""
    row = frame[y, 20:44].astype(int)
    background = frame[24, 32].astype(int)
    return float(abs(row - background).sum(axis=1).mean())


@pytest.mark.parametrize("include_audio", [True, False])
def test_burnin_export_works_on_sequence(qapp, tmp_path, include_audio):
    """작은 시퀀스를 굽기 내보내기하면 출력 mov의 프레임 수가 같고, 주석을 단 프레임에만 주석이 그려진다."""
    identity = make_seq(str(tmp_path / "shots"), "EX01_tk1", range(1, 6))  # 프레임 0..4: 초록·파랑·노랑·청록·분홍
    out = str(tmp_path / "out" / "EX01_tk1_annotated.mov")
    worker = AnnotationExportWorker(identity, {0: [rect_item()]}, out, external_tools.ffmpeg_path(),
                                    include_audio=include_audio, export_mode="balanced")

    result = run_worker(worker)

    assert "error" not in result, result.get("error")
    assert result["done"] == out
    frames = count_frames(out)
    assert len(frames) == 5
    assert mark_strength(frames[0]) > 200  # 주석을 단 프레임 0: 테두리가 바탕과 뚜렷이 다름
    assert all(mark_strength(frame) < 40 for frame in frames[1:])  # 나머지는 단색 그대로 (h264 손실 여유)
    assert "5프레임 처리, 1프레임에 주석 적용" in result["status"][-1]


def test_burnin_export_of_sequence_without_annotations_keeps_frame_count(qapp, tmp_path):
    identity = make_seq(str(tmp_path / "shots"), "EX01_tk1", range(1, 4))
    out = str(tmp_path / "out.mov")
    result = run_worker(AnnotationExportWorker(identity, {}, out, external_tools.ffmpeg_path(), include_audio=True))
    assert "error" not in result, result.get("error")
    assert len(count_frames(out)) == 3


def test_export_command_for_sequence_never_hands_the_virtual_path_to_ffmpeg(tmp_path):
    """가상 경로(.seq)는 진짜 파일이 아니라 ffmpeg가 열 수 없다 — 시퀀스는 소리 입력(-i <경로>)이 없고 -an."""
    seq_cmd = AnnotationExportWorker(str(tmp_path / "a.seq"), {}, "out.mov", "ffmpeg", include_audio=True)._build_ffmpeg_cmd(64, 48, 24.0)
    assert str(tmp_path / "a.seq") not in seq_cmd
    assert seq_cmd.count("-i") == 1 and "-an" in seq_cmd and "-c:a" not in seq_cmd and "1:a:0?" not in seq_cmd

    mov_cmd = AnnotationExportWorker(str(tmp_path / "a.mov"), {}, "out.mov", "ffmpeg", include_audio=True)._build_ffmpeg_cmd(64, 48, 24.0)
    assert mov_cmd.count("-i") == 2 and str(tmp_path / "a.mov") in mov_cmd  # mov는 그대로: 소리 입력이 있음
    assert "1:a:0?" in mov_cmd and "-an" not in mov_cmd and "aac" in mov_cmd
    mov_silent = AnnotationExportWorker(str(tmp_path / "a.mov"), {}, "out.mov", "ffmpeg", include_audio=False)._build_ffmpeg_cmd(64, 48, 24.0)
    assert mov_silent.count("-i") == 2 and "-an" in mov_silent  # 소리를 빼도 mov는 입력이 둘 (예전 그대로)


def test_burnin_export_of_unopenable_sequence_surfaces_the_error(qapp, tmp_path):
    """폴더를 읽을 수 없는 시퀀스는 생성자 예외가 삼켜지지 않고 error 신호로 올라온다 (완료도 출력 파일도 없음)."""
    identity = str(tmp_path / "missing_folder" / "EX01_tk1.seq")
    out = str(tmp_path / "out.mov")

    result = run_worker(AnnotationExportWorker(identity, {}, out, external_tools.ffmpeg_path()))

    assert "done" not in result
    assert "missing_folder" in result["error"]
    assert not os.path.exists(out)


def test_burnin_export_of_sequence_with_too_few_frames_reports_not_opened(qapp, tmp_path):
    identity = make_seq(str(tmp_path / "shots"), "EX01_tk1", range(1, 2))  # 1장뿐 -> 시퀀스가 아님 (isOpened False)
    result = run_worker(AnnotationExportWorker(identity, {}, str(tmp_path / "out.mov"), external_tools.ffmpeg_path()))
    assert "done" not in result
    assert identity in result["error"]


# ---------------------------------------------------------------- 창: 제안 경로·소리 상자


def test_export_dialog_for_sequence_suggests_mov_and_has_no_audio_choice(player, tmp_path, monkeypatch):
    identity = make_seq(str(tmp_path / "shots"), "EX01_tk1", range(1, 4))
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    assert player.open_file("A", identity)
    player.annotation_export_dir = str(export_dir)
    player.annotation_store.add(0, text_item())
    seen = {}

    def fake_save_dialog(parent, title, start, filters):
        seen["save"] = (title, start, filters)
        return str(export_dir / "chosen.mov"), ""  # 사용자가 고른 곳 (원본 폴더여도 막지 않음 — 기존 mov와 같음)

    def fake_exec(dialog):
        box = dialog.findChild(QCheckBox)
        seen["audio"] = (box.text(), box.isChecked(), box.isEnabled())
        return QDialog.Rejected

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save_dialog)
    monkeypatch.setattr(QDialog, "exec_", fake_exec)

    player.export_annotated_video()

    assert seen["save"] == ("주석 포함 영상 저장", str(export_dir / "EX01_tk1_annotated.mov"),
                            "Video Files (*.mp4 *.mov);;All Files (*)")
    assert seen["audio"] == ("오디오 포함", False, False)  # 시퀀스는 소리가 없어 고를 수 없음


def test_export_dialog_for_mov_keeps_the_audio_choice(player, tmp_path, monkeypatch):
    from tests.conftest import write_test_video

    mov = write_test_video(str(tmp_path / "movs" / "a.mp4"))
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    assert player.open_file("A", mov)
    player.annotation_export_dir = str(export_dir)
    player.annotation_store.add(0, text_item())
    seen = {}

    def fake_save_dialog(parent, title, start, filters):
        seen["start"] = start
        return str(export_dir / "chosen.mp4"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save_dialog)

    def fake_exec(dialog):
        box = dialog.findChild(QCheckBox)
        seen["audio"] = (box.isChecked(), box.isEnabled())
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec_", fake_exec)

    player.export_annotated_video()

    assert seen["start"] == str(export_dir / "a_annotated.mp4")
    assert seen["audio"] == (True, True)
