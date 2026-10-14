"""회귀 시험: Windows 사용자가 'Animatic2 (TransNetV2)' 모드를 골랐다가 개발자용 pip 안내
오류("OCR 오류: TransNetV2가 설치되지 않았습니다 ...")를 본 문제.

TransNetV2(선택적 딥러닝 의존성)가 없는 빌드/환경에서는:
1. OCR 분석 방식 콤보박스에 '애니매틱2 (TransNetV2)' 항목 자체가 보이지 않아야 한다
   (다른 항목·순서는 그대로, data()로 고르므로 인덱스가 밀려도 매핑은 안전해야 한다).
2. 저장된 결과 파일이 'animatic2'를 가리켜도 '애니매틱 (Auto Cut)'으로 자동 대체하고 로그를 남겨야 한다.
3. 그래도 워커가 직접 불리면(안전망) 사용자에게 개발자용 pip 안내가 아니라 한국어 안내가 떠야 한다
   (그 메시지 자체는 tests/test_workers_transnetv2_guard.py에서 확인).

TRANSNETV2_AVAILABLE이 True인 개발 환경(실제로 transnetv2가 설치된 경우)에서는 항목이 그대로 보여야 하므로
두 방향 모두 monkeypatch로 시험한다. baseline인 p310에는 transnetv2가 없으므로(실제 상태) 몽키패치 없는
시험으로 실제 상태도 함께 확인한다.
"""

import json
import time

import pytest
from PyQt5.QtWidgets import QApplication, QFileDialog

from tests.conftest import write_test_video
from tests.test_work_paths_ui import combo_items, make_config, new_player  # noqa: F401 (new_player: fixture)

from yesoncheck import player_base, workers

PATTERN = "### WW#_#WW - #### W"


class _NoRunMixin:
    """실제 OCR/컷 감지(cv2·PaddleOCR 등 무거운 작업)를 돌리지 않고 즉시 끝나는 가짜 워커."""

    def run(self):
        pass


class FakeSceneDetectWorker(_NoRunMixin, workers.SceneDetectWorker):
    pass


class FakeTransNetV2Worker(_NoRunMixin, workers.TransNetV2Worker):
    pass


class FakeOCRWorker(_NoRunMixin, workers.OCRWorker):
    pass


@pytest.fixture
def fake_workers(monkeypatch):
    """player_base의 지연 import(`from .workers import X`)가 가짜를 받도록 workers 모듈 속성을 바꿔치기."""
    monkeypatch.setattr(workers, "SceneDetectWorker", FakeSceneDetectWorker)
    monkeypatch.setattr(workers, "TransNetV2Worker", FakeTransNetV2Worker)
    monkeypatch.setattr(workers, "OCRWorker", FakeOCRWorker)


def _wait_finished(worker, timeout=2.0):
    deadline = time.monotonic() + timeout
    while worker is not None and worker.isRunning() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert worker is None or not worker.isRunning(), "가짜 워커 스레드가 시간 안에 끝나지 않았습니다"


def _select_and_run(player, mode):
    """콤보박스에서 data()==mode인 항목을 고르고 분석을 시작해, 실제로 만들어진 워커를 돌려준다."""
    index = player.ocrModeComboBox.findData(mode)
    assert index >= 0, f"'{mode}' 항목을 콤보박스에서 찾을 수 없습니다: {combo_items(player.ocrModeComboBox)}"
    player.ocrModeComboBox.setCurrentIndex(index)
    player.run_ocr_analysis()
    worker = player.ocr_worker
    assert worker is not None, f"'{mode}' 선택 후 워커가 만들어지지 않았습니다"
    _wait_finished(worker)
    if player.ocr_progress_dialog is not None:
        player.ocr_progress_dialog.close()
    return worker


def _prepare_player(new_player, tmp_path):
    player = new_player(make_config(str(tmp_path), {}))
    video = write_test_video(str(tmp_path / "v" / "a.mp4"))
    player.filename_a = video
    player.ocr_roi = (0.1, 0.1, 0.5, 0.5)  # OCR류 모드(ROI 필요) 통과용
    player.ocrPatternLineEdit.setText(PATTERN)  # All 모드 통과용
    return player


# ---------------------------------------------------------------------------
# 1) 콤보박스에 항목이 보이는지/안 보이는지
# ---------------------------------------------------------------------------

def test_animatic2_hidden_in_real_p310_environment(new_player, dialogs, tmp_path):
    """몽키패치 없이: p310에는 transnetv2가 설치되어 있지 않으므로(실제 상태) 항목이 보이면 안 된다."""
    assert player_base._transnetv2_available() is False, "이 시험은 TransNetV2가 없는 실제 환경을 전제로 합니다"
    player = _prepare_player(new_player, tmp_path)
    texts = combo_items(player.ocrModeComboBox)
    assert "TransNetV2" not in " ".join(texts), texts
    assert player.ocrModeComboBox.findData("animatic2") == -1
    assert player.ocrModeComboBox.findData("animatic") >= 0


def test_animatic2_hidden_when_unavailable_monkeypatched(new_player, dialogs, tmp_path, monkeypatch):
    monkeypatch.setattr(player_base, "_transnetv2_available", lambda: False)
    player = _prepare_player(new_player, tmp_path)
    assert player.ocrModeComboBox.findData("animatic2") == -1
    texts = combo_items(player.ocrModeComboBox)
    assert texts == ["Titmouse", "King", "Bento", "All (사용자 패턴)", "애니매틱 (Auto Cut)"], texts


def test_animatic2_present_when_available_monkeypatched(new_player, dialogs, tmp_path, monkeypatch):
    monkeypatch.setattr(player_base, "_transnetv2_available", lambda: True)
    player = _prepare_player(new_player, tmp_path)
    index = player.ocrModeComboBox.findData("animatic2")
    assert index >= 0
    assert player.ocrModeComboBox.itemText(index) == "애니매틱2 (TransNetV2)"
    texts = combo_items(player.ocrModeComboBox)
    assert texts == [
        "Titmouse", "King", "Bento", "All (사용자 패턴)", "애니매틱 (Auto Cut)", "애니매틱2 (TransNetV2)",
    ], texts


# ---------------------------------------------------------------------------
# 2) 남은 항목을 고르면 올바른 모드/워커로 이어지는지 (인덱스가 아니라 data() 매핑 확인)
# ---------------------------------------------------------------------------

def test_selecting_each_remaining_item_starts_the_right_mode_when_unavailable(
    new_player, dialogs, tmp_path, monkeypatch, fake_workers,
):
    monkeypatch.setattr(player_base, "_transnetv2_available", lambda: False)
    player = _prepare_player(new_player, tmp_path)
    assert player.ocrModeComboBox.findData("animatic2") == -1  # 목록에 없음을 재확인

    worker = _select_and_run(player, "titmouse")
    assert isinstance(worker, FakeOCRWorker) and worker.ocr_mode == "titmouse"

    worker = _select_and_run(player, "king")
    assert isinstance(worker, FakeOCRWorker) and worker.ocr_mode == "king"

    worker = _select_and_run(player, "bento")
    assert isinstance(worker, FakeOCRWorker) and worker.ocr_mode == "bento"

    worker = _select_and_run(player, "all")
    assert isinstance(worker, FakeOCRWorker) and worker.ocr_mode == "all" and worker.pattern == PATTERN

    worker = _select_and_run(player, "animatic")
    assert isinstance(worker, FakeSceneDetectWorker)
    assert not isinstance(worker, FakeTransNetV2Worker)


def test_selecting_animatic2_starts_transnetv2_worker_when_available(
    new_player, dialogs, tmp_path, monkeypatch, fake_workers,
):
    monkeypatch.setattr(player_base, "_transnetv2_available", lambda: True)
    player = _prepare_player(new_player, tmp_path)

    worker = _select_and_run(player, "animatic")
    assert isinstance(worker, FakeSceneDetectWorker)

    worker = _select_and_run(player, "animatic2")
    assert isinstance(worker, FakeTransNetV2Worker)
    assert worker.detect_gradual_transitions is True

    # 나머지 항목들도 여전히 올바르게 매핑됨 (animatic2 추가가 다른 매핑을 밀어내지 않음)
    worker = _select_and_run(player, "king")
    assert isinstance(worker, FakeOCRWorker) and worker.ocr_mode == "king"


# ---------------------------------------------------------------------------
# 3) 저장된(기억된) 결과가 animatic2를 가리킬 때의 대체 동작
# ---------------------------------------------------------------------------

def _write_saved_result(tmp_path, video_path, ocr_mode):
    json_path = tmp_path / "result.json"
    json_path.write_text(
        json.dumps({"video_path": video_path, "ocr_mode": ocr_mode, "segments": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    return json_path


def test_load_ocr_result_falls_back_to_animatic_when_unavailable(
    new_player, dialogs, tmp_path, monkeypatch, capsys,
):
    monkeypatch.setattr(player_base, "_transnetv2_available", lambda: False)
    player = _prepare_player(new_player, tmp_path)
    json_path = _write_saved_result(tmp_path, player.filename_a, "animatic2")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(json_path), "JSON Files (*.json)"))

    player.load_ocr_result()

    assert player.pending_ocr_metadata["ocr_mode"] == "animatic"
    out = capsys.readouterr().out
    assert "애니매틱2" in out and "애니매틱 (Auto Cut)" in out, out  # 대체했다는 로그 (침묵하지 않음)
    assert dialogs.errors() == []  # 크래시도, 조용히 무시도 아님 — 안내 대화상자(정보)만


def test_load_ocr_result_keeps_animatic2_when_available(new_player, dialogs, tmp_path, monkeypatch):
    monkeypatch.setattr(player_base, "_transnetv2_available", lambda: True)
    player = _prepare_player(new_player, tmp_path)
    json_path = _write_saved_result(tmp_path, player.filename_a, "animatic2")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(json_path), "JSON Files (*.json)"))

    player.load_ocr_result()

    assert player.pending_ocr_metadata["ocr_mode"] == "animatic2"
    assert dialogs.errors() == []
