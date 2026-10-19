"""새 버전 알림 띠·업데이트 확인 일정·Help → '업데이트 확인…' (offscreen).

확인 자체(updates.check)는 가짜로 바꿔 끼움 — 시험은 NAS·인터넷에 닿지 않는다. 빌드된 앱처럼 보이게
build_info.current를 가짜 BuildInfo로 바꾸고, 업데이트 기록(update.log)은 tmp_state_dir 아래에 남긴다.
"""

import threading
import time

import pytest
from PyQt5.QtWidgets import QApplication

from yesoncheck import build_info, paths, updates
from yesoncheck.build_info import BuildInfo
from tests.test_fast_startup import wait_until
from tests.test_work_paths_ui import make_config, new_player  # noqa: F401 (new_player: fixture)

BANNER_TEXT = "⬆ 새 버전 1.1.1이 나왔습니다 · 지금 1.1.0"
SOURCE_RUN_NOTICE = "소스에서 실행 중 — 업데이트하지 않음"
NAS_NOT_YET = "NAS에 아직 배포된 버전이 없음 (/Volumes/Mainnas/.yesoncheck/updates/latest.json)"
GITHUB_UNREACHABLE = "GitHub에 닿지 못함 (인터넷 연결 없음 또는 시간 초과): 시험"


def _settle():
    for _ in range(5):
        QApplication.processEvents()


def manifest(version, notes="- 새로고침이 썸네일도 다시 만듦\n- 작품 → 시즌 → job 순서"):
    files = {key: updates.FileEntry(f"YesonCheck_{key}_{version}", 1234, "a" * 64) for key in build_info.PLATFORM_KEYS}
    return updates.Manifest(updates.Version.parse(version), "c" * 40, "2026-10-20T10:00:00+09:00", notes, files)


def found(source, version, **kwargs):
    location = "/Volumes/Mainnas/.yesoncheck/updates" if source == "NAS" else "http://203.0.113.5/releases"
    return updates.SourceResult(source, location, manifest(version, **kwargs), None, None)


def expected(source, text):
    return updates.SourceResult(source, "", None, text, None)


def error(source, text):
    return updates.SourceResult(source, "/Volumes/Mainnas/.yesoncheck/updates", None, None, text)


class FakeCheck:
    """updates.check 대신: results를 돌려주고(고르기는 진짜 choose_offer) 부른 값을 calls에 남김.
    gate를 정하면 그 Event가 set될 때까지 기다림, sleep_s만큼 잠, raises를 정하면 그 예외를 올림."""

    def __init__(self):
        self.results = []
        self.calls = []
        self.gate = None
        self.entered = threading.Event()
        self.sleep_s = 0
        self.raises = None

    def __call__(self, current, platform_key, config_dir, base_url):
        self.calls.append((current, platform_key, config_dir, base_url))
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(10), "시험의 gate가 10초 안에 열리지 않음"
        if self.sleep_s:
            time.sleep(self.sleep_s)
        if self.raises is not None:
            raise self.raises
        results = list(self.results)
        return updates.CheckResult(results, updates.choose_offer(current, platform_key, results))


@pytest.fixture
def fake_check(monkeypatch):
    fake = FakeCheck()
    monkeypatch.setattr(updates, "check", fake)
    return fake


def _built_app(monkeypatch, version):
    monkeypatch.setattr(build_info, "current",
                        lambda: BuildInfo(version, "0" * 40, "2026-10-20T10:00:00+09:00", build_info.platform_key()))
    monkeypatch.setenv("YESONCHECK_UPDATE_URL", "off")


@pytest.fixture
def player_with_build(new_player, fake_check, dialogs, tmp_state_dir, tmp_path, monkeypatch):
    """빌드된 앱(version)처럼 보이는 창 — 확인 결과는 results (fake_check.results를 바꿔 다음 확인 결과를 정함)."""

    def make(version, results=()):
        _built_app(monkeypatch, version)
        fake_check.results = list(results)
        player = new_player(make_config(str(tmp_path), {}))
        player.show()
        _settle()
        return player

    return make


def check_now(player, manual=False):
    player.start_update_check(manual=manual)
    wait_until(lambda: not player.update_check_running)
    _settle()


def help_action(player, text):
    [help_menu] = [action.menu() for action in player.menuBar().actions() if action.text() == "&Help"]
    [action] = [action for action in help_menu.actions() if action.text() == text]
    return action


def update_log():
    from yesoncheck import update_install

    with open(update_install.log_path(), encoding="utf-8") as fh:
        return fh.read()


def test_offer_shows_banner_with_exact_text(player_with_build, fake_check, dialogs):
    player = player_with_build("1.1.0", [found("NAS", "1.1.1"), expected("GitHub", GITHUB_UNREACHABLE)])
    assert not player.update_banner.isVisible() and player.update_offer is None
    check_now(player)
    banner = player.update_banner
    assert banner.isVisible()
    assert banner.full_text() == BANNER_TEXT
    assert banner.text_label.toolTip() == BANNER_TEXT  # 줄여 그려져도 툴팁에 전체
    assert [b.text() for b in (banner.notes_button, banner.update_button, banner.later_button)] == ["바뀐 점", "업데이트", "나중에"]
    assert all(b.isVisible() for b in (banner.notes_button, banner.update_button, banner.later_button))
    assert not banner.cancel_button.isVisible() and not banner.progress_bar.isVisible()
    assert player.update_offer.manifest.version == updates.Version.parse("1.1.1")
    assert player.update_offer.result.source == "NAS"
    [(current, platform_key, config_dir, base_url)] = fake_check.calls
    assert str(current) == "1.1.0" and platform_key == build_info.platform_key()
    assert config_dir == player.work_paths_config_dir is not None
    assert base_url is None  # YESONCHECK_UPDATE_URL=off
    assert dialogs.messages == []


def test_later_hides_until_bigger_version(player_with_build, fake_check, dialogs):
    player = player_with_build("1.1.0", [found("NAS", "1.1.1")])
    check_now(player)
    player.update_banner.later_button.click()
    _settle()
    assert not player.update_banner.isVisible()
    check_now(player)  # 같은 1.1.1 → 이번 실행 동안 다시 보이지 않음
    assert not player.update_banner.isVisible()
    fake_check.results = [found("NAS", "1.1.1"), found("GitHub", "1.1.2")]
    check_now(player)  # 더 큰 번호 → 다시 보임
    assert player.update_banner.isVisible()
    assert player.update_banner.full_text() == "⬆ 새 버전 1.1.2이 나왔습니다 · 지금 1.1.0"
    assert player.update_offer.result.source == "GitHub"
    assert dialogs.messages == []


def test_manual_check_shows_dismissed_offer_again(player_with_build, fake_check, dialogs):
    """'나중에'로 숨긴 버전도 Help → 업데이트 확인…을 누르면 다시 보임 (업데이트할 수 있는 곳은 띠뿐)."""
    player = player_with_build("1.1.0", [found("NAS", "1.1.1"), expected("GitHub", GITHUB_UNREACHABLE)])
    check_now(player)
    player.update_banner.later_button.click()
    check_now(player, manual=True)
    assert player.update_banner.isVisible() and player.update_banner.full_text() == BANNER_TEXT
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("information", "업데이트 확인")
    assert "1.1.1" in text and GITHUB_UNREACHABLE in text


def test_check_result_leaves_progress_banner_alone(player_with_build, fake_check, dialogs):
    """받는 중(띠가 진행을 보임)에 끝난 확인은 띠를 바꾸지 않음 — 새 버전이 있어도, 없어도."""
    player = player_with_build("1.1.0", [found("NAS", "1.1.2")])
    player.update_banner.show_progress(1, 4, "1.1.1 받는 중…")
    check_now(player)
    assert player.update_banner.mode() == "progress" and player.update_banner.full_text() == "1.1.1 받는 중…"
    fake_check.results = [expected("NAS", NAS_NOT_YET)]
    check_now(player)
    assert player.update_banner.mode() == "progress" and player.update_banner.isVisible()


def test_auto_check_expected_problems_are_silent(player_with_build, fake_check, dialogs):
    player = player_with_build("1.1.0", [expected("NAS", NAS_NOT_YET), expected("GitHub", GITHUB_UNREACHABLE)])
    check_now(player)
    assert dialogs.messages == []
    assert not player.update_banner.isVisible() and player.update_offer is None
    log = update_log()  # 예상된 실패는 로그에만 (Mac도 파일로)
    assert NAS_NOT_YET in log and GITHUB_UNREACHABLE in log


def test_auto_check_errors_dialog_once_per_run(player_with_build, fake_check, dialogs):
    problem = "latest.json의 files.windows.sha256이 올바르지 않습니다 (소문자 64자리 16진수여야 함): 'x'\n둘째 줄"
    player = player_with_build("1.1.0", [error("NAS", problem), expected("GitHub", GITHUB_UNREACHABLE)])
    check_now(player)
    check_now(player)  # 같은 문제 → 창은 한 번만
    errors = dialogs.errors()
    assert len(errors) == 1, dialogs.messages
    kind, title, text = errors[0]
    assert (kind, title) == ("warning", "업데이트 확인 실패")
    assert problem in text and "NAS" in text and GITHUB_UNREACHABLE not in text
    assert problem in update_log()
    fake_check.results = [error("NAS", problem), error("GitHub", problem)]  # 같은 글이라도 다른 곳 → 새 문제
    check_now(player)
    fake_check.results = [error("NAS", "PermissionError: [Errno 13] Permission denied: 'latest.json'")]
    check_now(player)  # 첫 줄이 다른 문제 → 새 창
    assert [m[1] for m in dialogs.errors()] == ["업데이트 확인 실패"] * 3
    assert "GitHub" in dialogs.errors()[1][2] and "Permission denied" in dialogs.errors()[2][2]


def test_auto_check_shows_each_different_traceback(player_with_build, fake_check, dialogs):
    """트레이스백은 첫 줄이 늘 'Traceback (most recent call last):' → 마지막 줄(예외)로 같은 문제인지 가림."""
    first = 'Traceback (most recent call last):\n  File "x.py", line 1, in <module>\nKeyError: \'files\''
    second = 'Traceback (most recent call last):\n  File "x.py", line 2, in <module>\nTypeError: 시험'
    player = player_with_build("1.1.0", [error("GitHub", first)])
    check_now(player)
    check_now(player)
    fake_check.results = [error("GitHub", second)]
    check_now(player)
    texts = [m[2] for m in dialogs.errors()]
    assert len(texts) == 2 and first in texts[0] and second in texts[1]


def test_manual_check_shows_expected_problems(player_with_build, fake_check, dialogs):
    player = player_with_build("1.1.0", [expected("NAS", NAS_NOT_YET), expected("GitHub", GITHUB_UNREACHABLE)])
    check_now(player, manual=True)
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("information", "업데이트 확인")
    assert NAS_NOT_YET in text and GITHUB_UNREACHABLE in text
    assert "1.1.0" in text  # 지금 버전
    assert not player.update_banner.isVisible()


def test_manual_check_shows_errors_and_found_versions(player_with_build, fake_check, dialogs):
    problem = "GitHub 응답 오류: HTTP 503"
    player = player_with_build("1.1.0", [found("NAS", "1.1.0"), error("GitHub", problem)])
    check_now(player, manual=True)
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("warning", "업데이트 확인")  # 오류가 있으면 경고 창
    assert problem in text and "1.1.0" in text
    check_now(player)  # 수동 확인 창에서 이미 보인 문제 → 자동 확인은 다시 띄우지 않음
    assert len(dialogs.messages) == 1


def test_manual_check_while_running_waits_for_result(player_with_build, fake_check, dialogs):
    player = player_with_build("1.1.0", [expected("NAS", NAS_NOT_YET), expected("GitHub", GITHUB_UNREACHABLE)])
    fake_check.gate = threading.Event()
    player.start_update_check(manual=False)
    assert fake_check.entered.wait(5)
    player.start_update_check(manual=True)  # 실행 중 → 새로 시작하지 않고 결과를 기다렸다가 창
    player.start_update_check(manual=False)  # 실행 중 → 건너뜀
    _settle()
    assert dialogs.messages == []
    fake_check.gate.set()
    wait_until(lambda: not player.update_check_running)
    _settle()
    assert len(fake_check.calls) == 1
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("information", "업데이트 확인") and NAS_NOT_YET in text


def test_check_does_not_block_gui(player_with_build, fake_check):
    player = player_with_build("1.1.0", [expected("NAS", NAS_NOT_YET)])
    fake_check.sleep_s = 2
    started = time.monotonic()
    player.start_update_check(manual=False)
    assert time.monotonic() - started < 0.2
    assert player.update_check_running
    check = player._update_check
    assert check.parent() is None and check in type(check)._running  # 창과 함께 파괴되지 않게 붙잡음
    wait_until(lambda: not player.update_check_running)
    wait_until(lambda: check not in type(check)._running)


def test_unexpected_check_exception_shows_traceback(player_with_build, fake_check, dialogs):
    player = player_with_build("1.1.0")
    fake_check.raises = RuntimeError("시험용 예상 못 한 오류")
    check_now(player)
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("warning", "업데이트 확인 실패")
    assert "Traceback" in text and "RuntimeError: 시험용 예상 못 한 오류" in text
    assert not player.update_check_running and not player.update_banner.isVisible()


def test_source_run_never_auto_checks(qapp, new_player, fake_check, dialogs, tmp_path, monkeypatch):
    from yesoncheck.player_update import UpdateCheck

    monkeypatch.setattr(build_info, "current", lambda: None)
    player = new_player(make_config(str(tmp_path), {}))
    running_before = set(UpdateCheck._running)
    player.start_update_check(manual=False)
    _settle()
    assert fake_check.calls == [] and UpdateCheck._running == running_before
    assert not player.update_check_running and not player._update_check_timer.isActive()
    assert dialogs.messages == []
    help_action(player, "업데이트 확인…").trigger()  # 수동 확인: 안내만
    assert dialogs.messages == [("information", "업데이트 확인", SOURCE_RUN_NOTICE)]
    assert fake_check.calls == []


def test_auto_check_starts_after_shared_config_load_and_repeats(qapp, fake_check, dialogs, tmp_state_dir, tmp_path,
                                                                 monkeypatch):
    from yesoncheck.main_window import VideoPlayer

    config = make_config(str(tmp_path), {})
    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", config)
    _built_app(monkeypatch, "1.1.0")
    fake_check.results = [expected("NAS", NAS_NOT_YET)]
    # 공유 설정 문제 알림(Windows는 변환표 자동 설정 창)은 이 시험의 대상이 아님 → 불렸는지만 (확인보다 먼저)
    resolved = []
    monkeypatch.setattr(VideoPlayer, "resolve_shared_config_problem",
                        lambda self, works_not_opening=None: resolved.append(list(fake_check.calls)))
    player = VideoPlayer(load_shared_config=False)
    try:
        player.show()
        _settle()
        assert fake_check.calls == []  # 공유 설정을 불러오기 전에는 확인하지 않음
        player.start_shared_config_load()
        wait_until(lambda: not player.shared_config_loading and fake_check.calls)
        wait_until(lambda: not player.update_check_running)
        assert resolved == [[]]  # 문제 알림이 끝난 뒤에 확인 시작
        assert fake_check.calls[0][2] == player.work_paths_config_dir == config
        timer = player._update_check_timer
        assert timer.isActive() and timer.interval() == player.UPDATE_CHECK_INTERVAL_MS == 3 * 60 * 60 * 1000
        timer.timeout.emit()  # 3시간 뒤
        wait_until(lambda: len(fake_check.calls) == 2 and not player.update_check_running)
        assert dialogs.messages == []
    finally:
        player.close()
        paths.activate(None)  # (Windows) 불러온 공유 설정이 켠 변환표를 다음 시험에 남기지 않음 (new_player처럼)


def test_close_while_checking_releases_thread_and_ignores_result(player_with_build, fake_check, dialogs):
    from yesoncheck import player_base

    player = player_with_build("1.1.0", [found("NAS", "1.1.1"), error("GitHub", "GitHub 응답 오류: HTTP 500")])
    fake_check.gate = threading.Event()
    player.start_update_check(manual=False)
    assert fake_check.entered.wait(5)
    check = player._update_check
    player.close()
    try:
        assert check in player_base._RELEASED_WORKERS  # 끝날 때까지 붙잡아 둠 (앱이 끝나기 전에 기다림)
        assert not player._update_check_timer.isActive()
    finally:
        fake_check.gate.set()
    assert player_base.wait_for_released_workers(5) == []
    _settle()
    assert dialogs.messages == [] and not player.update_banner.isVisible() and player.update_offer is None


def test_banner_does_not_widen_window(player_with_build):
    player = player_with_build("1.1.0")
    banner = player.update_banner
    before = player.minimumSizeHint().width()
    long_version = "1.1.1" + "9" * 40
    banner.show_offer(long_version, "1.1.0")
    _settle()
    assert player.minimumSizeHint().width() <= before
    full = f"⬆ 새 버전 {long_version}이 나왔습니다 · 지금 1.1.0"
    assert banner.full_text() == full and banner.text_label.toolTip() == full
    player.resize(player.minimumSizeHint())
    _settle()
    shown = banner.text_label.displayed_text()
    assert shown != full and shown.endswith("…")  # 좁으면 …로 줄임
    banner.show_progress(5, 10, "1.1.1 받는 중… " + "가" * 80)
    _settle()
    assert player.minimumSizeHint().width() <= before
    banner.show_message("1.1.1로 업데이트했습니다 " + "나" * 80)
    _settle()
    assert player.minimumSizeHint().width() <= before


def test_notes_button_shows_manifest_notes(player_with_build, fake_check, dialogs):
    notes = "- 업데이트 알림 띠\n- '바뀐 점' 버튼"
    player = player_with_build("1.1.0", [found("GitHub", "1.1.1", notes=notes)])
    check_now(player)
    player.update_banner.notes_button.click()
    [(kind, title, text)] = dialogs.messages
    assert kind == "information" and "1.1.1" in title and "바뀐 점" in title
    assert text == notes
    assert player.update_banner.isVisible()  # 바뀐 점을 봐도 띠는 그대로


def test_banner_modes_and_signals(qapp):
    from yesoncheck.update_banner import UpdateBanner

    banner = UpdateBanner()
    emitted = []
    for name in ("notes_clicked", "update_clicked", "later_clicked", "cancel_clicked"):
        getattr(banner, name).connect(lambda name=name: emitted.append(name))
    assert banner.isHidden() and banner.mode() == "hidden"  # 만든 뒤에는 숨김 (보일 것이 있을 때만)
    banner.show_offer("1.1.1", "1.1.0")
    assert banner.isVisible() and banner.mode() == "offer"
    for button in (banner.notes_button, banner.update_button, banner.later_button):
        button.click()
    assert emitted == ["notes_clicked", "update_clicked", "later_clicked"]
    banner.show_progress(3, 4, "1.1.1 받는 중… 3 / 4 MB")
    assert banner.mode() == "progress" and banner.full_text() == "1.1.1 받는 중… 3 / 4 MB"
    assert banner.progress_bar.isVisible() and banner.cancel_button.isVisible()
    assert not any(b.isVisible() for b in (banner.notes_button, banner.update_button, banner.later_button))
    assert banner.progress_bar.value() == 750 and banner.progress_bar.maximum() == 1000
    banner.cancel_button.click()
    assert emitted[-1] == "cancel_clicked"
    banner.show_message("1.1.1로 업데이트했습니다", hide_after_ms=50)
    assert banner.mode() == "message" and banner.isVisible()
    assert not any(b.isVisible() for b in (banner.cancel_button, banner.update_button, banner.progress_bar))
    wait_until(lambda: not banner.isVisible(), timeout=5)
    assert banner.mode() == "hidden"
    banner.show_offer("1.1.1", "1.1.0")
    banner.hide_banner()
    assert not banner.isVisible() and banner.mode() == "hidden"


def test_update_check_thread_runs_injected_check(qapp):
    from yesoncheck.player_update import UpdateCheck

    seen = []
    results = [expected("NAS", NAS_NOT_YET)]

    def fake(current, platform_key, config_dir, base_url):
        seen.append((str(current), platform_key, config_dir, base_url))
        return updates.CheckResult(results, None)

    check = UpdateCheck(updates.Version.parse("1.1.0"), "windows", "/Volumes/Mainnas/.yesoncheck", None, check=fake)
    got = []
    check.done.connect(got.append)
    assert check.parent() is None
    check.start()
    assert check in UpdateCheck._running
    wait_until(lambda: got and check not in UpdateCheck._running)
    assert seen == [("1.1.0", "windows", "/Volumes/Mainnas/.yesoncheck", None)]
    assert got[0].results == results and got[0].offer is None
