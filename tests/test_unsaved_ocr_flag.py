"""'OCR 저장'을 누르지 않은 OCR·애니매틱 검토 결과가 있는지 (offscreen).

업데이트 확인 창이 "닫으면 저장 안 한 결과는 사라집니다"에 쓸 표시 하나: 결과가 만들어지면 켜지고,
'OCR 저장'이 파일을 쓴 뒤·결과를 비울 때(영상 바꿈) 꺼진다.
"""

import json
import os

from PyQt5.QtWidgets import QApplication, QFileDialog

from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)


def _segment(start, end, text):
    return {
        "start_frame": start, "end_frame": end, "start_time": start / 24.0, "end_time": end / 24.0,
        "duration": (end - start) / 24.0, "text": text, "edited_text": text, "roi_preview": None, "detections": [],
    }


def _result(*segments):
    return {"segments": list(segments), "fps": 24.0, "total_frames": 240}


def _close_review(player):
    # 검토 창을 닫으면 편집 중인 구간이 saved_edited_segments로 남음 (저장은 거기서 읽음)
    player.ocr_review_dialog.close()
    QApplication.processEvents()


def test_flag_set_by_results_and_cleared_by_save_and_reset(qapp, new_player, dialogs, tmp_state_dir, tmp_path,
                                                            monkeypatch):
    player = new_player(make_config(str(tmp_path), {}))
    assert player.has_unsaved_ocr_results() is False  # 새 창

    # 분석이 끝나 결과가 생김 → 저장 안 한 결과
    player.on_ocr_completed(_result(_segment(0, 48, "FL_001"), _segment(48, 96, "FL_002")))
    assert player.has_unsaved_ocr_results() is True
    _close_review(player)
    assert player.has_unsaved_ocr_results() is True  # 검토 창을 닫아도 저장한 것은 아님

    # 'OCR 저장'을 취소하면 그대로, 파일을 쓰면 꺼짐
    video = str(tmp_path / "scene.mov")
    player._current_ocr_video_path = video
    out = str(tmp_path / "scene_ocr_result.json")
    chosen = [""]
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (chosen[0], ""))
    player.save_ocr_result()
    assert player.has_unsaved_ocr_results() is True and not os.path.exists(out)
    chosen[0] = out
    player.save_ocr_result()
    assert os.path.exists(out) and len(json.load(open(out, encoding="utf-8"))["segments"]) == 2
    assert player.has_unsaved_ocr_results() is False
    assert dialogs.errors() == []

    # 선택 구간을 더 분석해 결과가 보태짐 → 다시 켜짐
    player.on_ocr_analysis_range_completed(_result(_segment(96, 144, "FL_003")))
    assert player.has_unsaved_ocr_results() is True
    _close_review(player)

    # 영상이 바뀌어 결과를 비움 → 꺼짐
    player.reset_ocr_state()
    assert player.has_unsaved_ocr_results() is False
