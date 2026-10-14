"""TransNetV2Worker의 안전망(TRANSNETV2_AVAILABLE이 False일 때)이 사용자에게는 한국어 안내만,
개발자용 안내(TensorFlow·가중치 중 무엇이 없는지)는 로그에만 보내는지 확인.

이 안전망은 콤보박스에서 애니매틱2 항목을 숨겨도(tests/test_animatic2_availability.py) 여전히 남아 있어야
하는 마지막 방어선이다 — 예: 저장된 결과를 억지로 재생해 워커가 직접 불려도 개발자용 오류가 뜨지 않게.
"""

from tests.conftest import write_test_video

from yesoncheck import workers


def test_run_emits_korean_user_message_and_logs_developer_hint_separately(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(workers, "TRANSNETV2_AVAILABLE", False)
    missing = ["tensorflow 모듈 없음", "가중치 파일 없음: /x/transnetv2-weights/saved_model.pb"]
    monkeypatch.setattr(workers, "transnetv2_missing", lambda: missing)
    video = write_test_video(str(tmp_path / "v" / "a.mp4"))
    worker = workers.TransNetV2Worker(video)

    errors = []
    worker.error.connect(lambda msg: errors.append(msg))
    worker.run()

    assert len(errors) == 1, errors
    user_message = errors[0]
    assert user_message == (
        "이 빌드에는 Animatic2(TransNetV2) 씬 감지가 포함되지 않았습니다. "
        "Animatic (Auto Cut) 모드를 쓰세요."
    )
    # 개발자용 안내(무엇이 없는지·경로)는 대화상자(위 메시지)가 아니라 로그에만
    assert "TensorFlow" not in user_message and "가중치" not in user_message
    out = capsys.readouterr().out
    assert "이 빌드에는 TensorFlow 또는 TransNetV2 가중치가 없습니다" in out, out
    assert str(missing) in out, out
    # TransNetV2는 pip로 설치하지 않음 (코드·가중치를 저장소에 넣어 빌드에 포함) → pip 안내가 나오면 안 됨
    assert "pip install" not in out, out


def test_run_still_works_when_transnetv2_available(tmp_path, monkeypatch):
    """안전망 메시지만 바뀌었을 뿐, TRANSNETV2_AVAILABLE이 True면 가드를 지나 실제 감지를 시도해야 한다."""
    monkeypatch.setattr(workers, "TRANSNETV2_AVAILABLE", True)

    def fake_detect(*args, **kwargs):
        return [{
            "start_frame": 0, "end_frame": 9, "start_time": 0.0, "end_time": 0.4, "duration": 0.4,
            "text": "", "edited_text": "", "roi_preview": None, "detections": [],
        }]

    monkeypatch.setattr(workers, "detect_scene_cuts_transnetv2", fake_detect)
    video = write_test_video(str(tmp_path / "v" / "a.mp4"))
    worker = workers.TransNetV2Worker(video)

    completed = []
    errors = []
    worker.completed.connect(lambda r: completed.append(r))
    worker.error.connect(lambda m: errors.append(m))
    worker.run()

    assert errors == [], errors
    assert len(completed) == 1 and len(completed[0]["segments"]) == 1


def test_worker_passes_stop_flag_and_reports_stop_as_cancelled(tmp_path, monkeypatch):
    """감지 함수에 워커의 멈춤 상태를 넘기고, 감지가 '중지됨'으로 끝나면 오류가 아니라 취소(cancelled)로 알림."""
    from yesoncheck import transnetv2_detector

    seen = {}

    def fake_detect(*args, **kwargs):
        seen["should_stop"] = kwargs["should_stop"]
        raise transnetv2_detector.TransNetV2Stopped("애니매틱2 컷 감지 중지됨 (프레임 추출 중 20/300)")

    monkeypatch.setattr(workers, "TRANSNETV2_AVAILABLE", True)
    monkeypatch.setattr(workers, "detect_scene_cuts_transnetv2", fake_detect)
    video = write_test_video(str(tmp_path / "v" / "a.mp4"))
    worker = workers.TransNetV2Worker(video)
    completed, errors, statuses = [], [], []
    worker.completed.connect(lambda r: completed.append(r))
    worker.error.connect(lambda m: errors.append(m))
    worker.status.connect(lambda m: statuses.append(m))

    worker.stop()
    worker.run()

    assert seen["should_stop"]() is True  # 워커의 stop()을 따름
    assert errors == [], errors
    assert len(completed) == 1 and completed[0]["cancelled"] is True and completed[0]["segments"] == []
    assert any("중지됨" in s for s in statuses), statuses
