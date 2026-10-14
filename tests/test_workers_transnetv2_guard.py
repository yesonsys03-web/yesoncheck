"""TransNetV2Worker의 안전망(TRANSNETV2_AVAILABLE이 False일 때)이 사용자에게는 한국어 안내만,
개발자용 pip 설치 안내는 로그에만 보내는지 확인.

이 안전망은 콤보박스에서 애니매틱2 항목을 숨겨도(tests/test_animatic2_availability.py) 여전히 남아 있어야
하는 마지막 방어선이다 — 예: 저장된 결과를 억지로 재생해 워커가 직접 불려도 개발자용 오류가 뜨지 않게.
"""

from tests.conftest import write_test_video

from yesoncheck import workers


def test_run_emits_korean_user_message_and_logs_pip_hint_separately(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(workers, "TRANSNETV2_AVAILABLE", False)
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
    # 개발자용 pip 안내는 대화상자(위 메시지)가 아니라 로그에만
    assert "pip install" not in user_message
    out = capsys.readouterr().out
    assert "pip install git+https://github.com/soCzech/TransNetV2.git" in out


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
