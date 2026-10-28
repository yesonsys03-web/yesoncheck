"""GL 뷰포트 — Mac 풀스크린 재생 FPS(라스터 CPU 확대 블릿이 병목, 풀 13.5→24.8fps 실측 2026-10-28)용.

뷰포트 선택 규칙(viewport_mode): cocoa만 기본 GL. Windows는 풀스크린 저하가 없고(사용자 실측 2026-10-28),
offscreen(시험·CI)은 QOpenGLWidget을 지원하지 않음(컨텍스트 생성 실패 실측). YESONCHECK_VIEWPORT=gl|raster로
명시해서 바꿀 수 있고 그 밖의 값은 ValueError — 조용한 폴백 금지.

GL을 붙일 때 보존해야 하는 것(실측): setViewport()가 새 뷰포트의 마우스 추적을 꺼 두므로 다시 켜야 하고
(와이프 선 커서·호버), 드래그 앤 드롭은 뷰포트를 거쳐 뷰 핸들러에 닿아야 함.
"""

import pytest
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QGraphicsView, QOpenGLWidget

from tests.test_sequence_frame_open import deliver_drag
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)
from yesoncheck.video_widget import CustomVideoWidget, viewport_mode


# ---------------------------------------------------------------- 선택 규칙 (순수 함수)


def test_viewport_mode_is_gl_on_cocoa():
    assert viewport_mode("cocoa", {}) == "gl"


@pytest.mark.parametrize("platform", ["windows", "offscreen", "xcb", "minimal", ""])
def test_viewport_mode_is_raster_everywhere_else(platform):
    assert viewport_mode(platform, {}) == "raster"


@pytest.mark.parametrize("platform", ["cocoa", "windows", "offscreen"])
def test_viewport_mode_env_toggle_wins(platform):
    assert viewport_mode(platform, {"YESONCHECK_VIEWPORT": "raster"}) == "raster"
    assert viewport_mode(platform, {"YESONCHECK_VIEWPORT": "gl"}) == "gl"


def test_viewport_mode_rejects_unknown_toggle_value():
    with pytest.raises(ValueError) as error:
        viewport_mode("cocoa", {"YESONCHECK_VIEWPORT": "auto"})
    assert "YESONCHECK_VIEWPORT" in str(error.value)


def test_viewport_forced_sees_the_toggle():
    from yesoncheck.video_widget import viewport_forced

    assert viewport_forced({}) is False
    assert viewport_forced({"YESONCHECK_VIEWPORT": "raster"}) is True


# ---------------------------------------------------------------- GL 적용 (offscreen에서 토글로 강제)
# offscreen은 GL 컨텍스트가 없어 Qt가 'QOpenGLWidget is not supported …' 경고를 내지만
# 위젯 구조(뷰포트 종류·설정·이벤트 전달)는 그대로 확인할 수 있음.


@pytest.fixture
def gl_widget(qapp, monkeypatch):
    monkeypatch.setenv("YESONCHECK_VIEWPORT", "gl")
    widget = CustomVideoWidget()
    widget.resize(400, 300)
    widget.video_item.setPixmap(QPixmap(320, 240))
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


def test_gl_widget_viewport_is_opengl(gl_widget):
    assert isinstance(gl_widget.viewport(), QOpenGLWidget)


def test_gl_widget_uses_full_viewport_update(gl_widget):
    # GL 뷰포트는 부분 갱신이 안 됨 — 전체 갱신이어야 잔상이 없음 (Qt 문서, 스파이크와 같음)
    assert gl_widget.viewportUpdateMode() == QGraphicsView.FullViewportUpdate


def test_gl_widget_viewport_keeps_mouse_tracking(gl_widget):
    # setViewport()가 새 뷰포트의 마우스 추적을 꺼 둠(실측) — 와이프 선 커서 등 기존 동작 보존
    assert gl_widget.viewport().hasMouseTracking()


def test_gl_widget_viewport_accepts_drops(gl_widget):
    assert gl_widget.viewport().acceptDrops()


def test_gl_widget_keeps_overlay_labels_above_viewport(gl_widget):
    """setViewport()는 새 뷰포트를 자식 맨 끝(쌓임 맨 위)에 둠 — 줌 라벨·주석 배지가 그 아래로 깔리면
    Qt5가 GL 위젯 자리의 형제를 지워(백킹 스토어 hole punch) 라벨이 화면에서 사라짐 (cocoa 실측)."""
    from PyQt5.QtWidgets import QWidget

    kids = [c for c in gl_widget.children() if isinstance(c, QWidget)]
    assert kids.index(gl_widget.zoom_label) > kids.index(gl_widget.viewport())
    assert kids.index(gl_widget.annotation_mode_label) > kids.index(gl_widget.viewport())


def test_gl_widget_viewport_declares_opaque_paint(gl_widget):
    # FullViewportUpdate라 매 페인트가 뷰포트 전체를 덮음 — 불투명 선언이 없으면 창 전체 스타일시트
    # 폴리시 뒤 풀스크린 FPS가 24.8→16으로 떨어짐 (cocoa 실측 2026-10-28, GL을 쓰는 이유가 사라짐)
    from PyQt5.QtCore import Qt

    assert gl_widget.viewport().testAttribute(Qt.WA_OpaquePaintEvent)


def test_gl_widget_drop_reaches_view_handler(gl_widget, monkeypatch, tmp_path):
    """드롭이 GL 뷰포트를 거쳐 뷰의 dropEvent에 닿는다 (영상 영역에 파일 놓기)."""
    seen = []
    monkeypatch.setattr(CustomVideoWidget, "dropEvent", lambda self, event: seen.append(event))

    enter, _drop = deliver_drag(gl_widget, [tmp_path / "a.mov"])

    assert enter.isAccepted()
    assert len(seen) == 1


def test_gl_widget_requests_msaa_for_vector_items(qapp, monkeypatch):
    # GL2 페인트 엔진은 QPainter.Antialiasing을 MSAA로만 처리 — 샘플 0이면 와이프 선·ROI·주석 미리보기가 계단짐.
    # offscreen은 show에서 컨텍스트 생성이 실패하며 요청 포맷을 지우므로(4→0 실측) 띄우기 전의 요청 값을 봄.
    # 실제 적용 값은 cocoa 실기로 확인 (2026-10-28).
    monkeypatch.setenv("YESONCHECK_VIEWPORT", "gl")
    widget = CustomVideoWidget()
    try:
        assert widget.viewport().format().samples() == 4
    finally:
        widget.close()


def _fake_platform(monkeypatch, platform):
    """위젯이 보는 QApplication.platformName만 바꿈 — 실제 연결부(platformName → viewport_mode)를 그대로 태움."""
    from types import SimpleNamespace

    from yesoncheck import video_widget as module

    monkeypatch.setattr(module, "QApplication", SimpleNamespace(platformName=lambda: platform))


def test_cocoa_default_installs_gl_when_context_ok(qapp, monkeypatch):
    """cocoa 기본 + 컨텍스트 확인 통과 → GL (연결부까지 — viewport_mode를 바꿔치기하지 않음)."""
    from yesoncheck import video_widget as module

    _fake_platform(monkeypatch, "cocoa")
    monkeypatch.setattr(module, "gl_context_available", lambda: True)

    widget = CustomVideoWidget()
    try:
        assert isinstance(widget.viewport(), QOpenGLWidget)
        assert widget.viewport_fallback_reason is None
    finally:
        widget.close()


def test_cocoa_default_falls_back_loudly_when_gl_context_fails(qapp, monkeypatch, capsys):
    """cocoa 기본 GL인데 컨텍스트를 못 만들면: 기록에 바로 남기고 사유를 남겨 raster로 계속 — 위젯은 오류 창을
    띄우지 않음 (창은 app.launch가 스플래시를 닫은 뒤 show_viewport_fallback으로 — 위젯 생성 중 모달은
    splash.finish의 processEvents 안에서 열려 시작 순서를 멈춤, 검토 실측)."""
    from yesoncheck import error_window

    _fake_platform(monkeypatch, "cocoa")
    from yesoncheck import video_widget as module

    monkeypatch.setattr(module, "gl_context_available", lambda: False)
    shown = []
    monkeypatch.setattr(error_window, "show_window", lambda text: shown.append(text))

    widget = CustomVideoWidget()
    try:
        qapp.processEvents()
        assert not isinstance(widget.viewport(), QOpenGLWidget)
        assert widget.viewport_fallback_reason  # 창으로 알릴 사유가 남음
        assert "실패" in capsys.readouterr().out  # 기록에는 바로 남음 (성공 로그와 구분되는 문구)
        assert shown == []  # 위젯은 창을 띄우지 않음
    finally:
        widget.close()


def test_player_show_viewport_fallback_shows_reason(new_player, dialogs, tmp_path, qapp, monkeypatch):  # noqa: F811
    """app.launch가 스플래시를 닫은 뒤 부르는 show_viewport_fallback — 사유가 있으면 오류 창, 없으면 조용."""
    from yesoncheck import error_window

    shown = []
    monkeypatch.setattr(error_window, "show_window", lambda text: shown.append(text))
    player = new_player(make_config(str(tmp_path), {}))

    player.show_viewport_fallback()
    assert shown == []  # offscreen 기본 raster — 폴백 아님

    player.videoWidget.viewport_fallback_reason = "OpenGL 실패 사유"
    player.show_viewport_fallback()
    assert shown == ["OpenGL 실패 사유"]

    player.show_viewport_fallback()
    assert shown == ["OpenGL 실패 사유"]  # 꺼내며 비움 — 두 번 불려도 창은 한 번 (show_user_file_problems와 같은 방식)


def test_forced_gl_skips_context_probe(qapp, monkeypatch):
    """토글로 강제한 GL은 컨텍스트 확인 없이 그대로 GL — 디버깅·시험용 강제는 말 그대로 강제."""
    from yesoncheck import video_widget as module

    monkeypatch.setenv("YESONCHECK_VIEWPORT", "gl")
    monkeypatch.setattr(module, "gl_context_available",
                        lambda: pytest.fail("강제 GL인데 컨텍스트 확인을 함"))

    widget = CustomVideoWidget()
    try:
        assert isinstance(widget.viewport(), QOpenGLWidget)
    finally:
        widget.close()


def test_gl_choice_is_logged(qapp, monkeypatch, capsys):
    # 조용한 전환 금지 — GL을 골랐으면 창 기록(stdout)에 남아야 함
    monkeypatch.setenv("YESONCHECK_VIEWPORT", "gl")
    widget = CustomVideoWidget()
    try:
        assert "GL(QOpenGLWidget) 사용" in capsys.readouterr().out  # 폴백 로그와 구분되는 성공 문구
    finally:
        widget.close()


# ---------------------------------------------------------------- 테마 배경 (GL은 스타일시트 배경 칠을 받지 않음)
# WA_OpaquePaintEvent가 스타일시트 배경 칠(매 프레임 CPU 전체 칠 — 바로 그 병목)을 생략하므로,
# 영상 주변 여백 색은 backgroundBrush로 GPU가 칠함. 색은 main_window_styles의 테마 배경과 짝
# (시트는 해시로 얼어 있어 값이 어긋날 일 없음 — tests/test_stylesheet_freeze.py).


def test_gl_widget_paints_dark_theme_background_by_default(gl_widget):
    assert gl_widget.backgroundBrush().color().name() == "#232323"


def test_gl_widget_theme_background_switches(gl_widget):
    gl_widget.apply_theme_background("light")
    assert gl_widget.backgroundBrush().color().name() == "#fafafa"
    gl_widget.apply_theme_background("dark")
    assert gl_widget.backgroundBrush().color().name() == "#232323"


def test_gl_widget_rejects_unknown_theme(gl_widget):
    with pytest.raises(ValueError):
        gl_widget.apply_theme_background("sepia")


def test_raster_widget_theme_background_is_a_no_op(qapp):
    widget = CustomVideoWidget()
    try:
        before = widget.backgroundBrush()
        widget.apply_theme_background("light")
        assert widget.backgroundBrush() == before  # raster는 스타일시트가 칠함 — 동작 그대로
    finally:
        widget.close()


def test_player_theme_switch_updates_gl_background(new_player, dialogs, tmp_path, qapp, monkeypatch):  # noqa: F811
    monkeypatch.setenv("YESONCHECK_VIEWPORT", "gl")
    player = new_player(make_config(str(tmp_path), {}))
    assert isinstance(player.videoWidget.viewport(), QOpenGLWidget)

    player.set_light_theme()
    assert player.videoWidget.backgroundBrush().color().name() == "#fafafa"
    player.set_dark_theme()
    assert player.videoWidget.backgroundBrush().color().name() == "#232323"


# ---------------------------------------------------------------- 기본(offscreen) 동작 보존


def test_offscreen_default_keeps_raster_viewport(qapp):
    """토글이 없으면 offscreen(시험·CI)은 지금 그대로 — 뷰포트·갱신 모드·마우스 추적 불변, 폴백 아님."""
    widget = CustomVideoWidget()
    try:
        assert not isinstance(widget.viewport(), QOpenGLWidget)
        assert widget.viewportUpdateMode() == QGraphicsView.MinimalViewportUpdate
        assert widget.viewport().hasMouseTracking()
        assert widget.viewport_fallback_reason is None  # raster가 기본인 곳은 폴백이 아님 — 알림 없음
    finally:
        widget.close()
