"""알림 띠의 '업데이트'를 누른 뒤 (offscreen): 작업 중 묻기·여유 공간·받기 진행·취소·실패 창·도우미에 넘기고 끝내기,
그리고 다시 켜진 앱의 결과 알림 (handle_update_startup).

NAS는 임시 폴더, GitHub는 시험용 HTTP 서버 — 인터넷에 닿지 않는다. 도우미(launch_helper_mac/windows)·Mac dmg 준비
(stage_mac)·앱 위치(running_app_location)·앱 끝내기(QApplication.quit)는 가짜로 바꿔 끼움 (hdiutil·실제 도우미를
돌리지 않음). 플랫폼은 build_info.platform_key를 바꿔 정함 — Mac·Windows 경로를 두 CI 모두에서 시험.
"""

import hashlib
import os
import threading
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QApplication, QMessageBox

from yesoncheck import build_info, player_base, update_install, updates
from yesoncheck.update_install import Pending, ok_marker_path, read_pending, write_pending
from tests.test_fast_startup import wait_until
from tests.test_update_ui import _settle, check_now, error, fake_check, found, player_with_build  # noqa: F401 (fixture)
from tests.test_work_paths_ui import new_player  # noqa: F401 (fixture)

INSTALLER = bytes(range(256)) * 4096 * 3  # 3 MB → 받기는 1 MB씩 세 번 (중간에 멈추는 시험)
OFFER_TEXT = "⬆ 새 버전 1.1.1이 나왔습니다 · 지금 1.1.0"
ASSET_NAMES = {"windows": "YesonCheck_Setup_{v}.exe", "mac-x86_64": "YesonCheck_Autocut_Intel_{v}.dmg"}


def now():
    return update_install.timestamp()


def published(source, location, version, key, data=INSTALLER, sha256=None):
    """version의 latest.json(이 플랫폼 항목 하나)을 읽은 결과. 설치 파일 내용은 data (sha256을 정하면 그 값으로 적음)."""
    name = ASSET_NAMES[key].format(v=version)
    entry = updates.FileEntry(name, len(data), sha256 or hashlib.sha256(data).hexdigest())
    manifest = updates.Manifest(updates.Version.parse(version), "c" * 40, "2026-10-20T10:00:00+09:00", "- 시험",
                                {key: entry})
    return updates.SourceResult(source, location, manifest, None, None)


def on_nas(nas_dir, version, key, data=INSTALLER, sha256=None):
    with open(os.path.join(nas_dir, ASSET_NAMES[key].format(v=version)), "wb") as fh:
        fh.write(data)
    return published("NAS", nas_dir, version, key, data, sha256)


class FakeHelpers:
    """launch_helper_mac/windows 대신: 부른 값을 남김 (raises를 정하면 그 예외를 올림)."""

    def __init__(self):
        self.calls = []
        self.raises = None

    @property
    def called(self):
        return bool(self.calls)

    @property
    def args(self):
        return self.calls[-1]

    def windows(self, installer, install_dir, target):
        self._record("windows", installer=installer, install_dir=install_dir, target=target)

    def mac(self, staged_app, app_path, target):
        self._record("mac", staged_app=staged_app, app_path=app_path, target=target)

    def _record(self, kind, **kwargs):
        if self.raises is not None:
            raise self.raises
        self.calls.append(SimpleNamespace(kind=kind, **kwargs))


class DownloadSpy:
    """update_install.download를 감쌈: 부른 위치를 남기고, gate를 정하면 처음 받은 조각 뒤에 그 Event가 set될 때까지
    기다림 (받는 중인 상태를 시험). raises를 정하면 받지 않고 그 예외를, raises_after_gate는 gate 뒤에 그 예외를 올림.
    finished: 받기가 끝남 (성공·실패 모두)."""

    def __init__(self, real):
        self._real = real
        self.calls = []
        self.gate = None
        self.raises = None
        self.raises_after_gate = None
        self.entered = threading.Event()
        self.finished = threading.Event()

    def __call__(self, location, entry, dest_dir, progress, cancelled):
        self.calls.append(location)

        def progress_then_wait(done, total):
            progress(done, total)
            self.entered.set()
            if self.gate is not None:
                assert self.gate.wait(10), "시험의 gate가 10초 안에 열리지 않음"
            if self.raises_after_gate is not None:
                raise self.raises_after_gate

        try:
            if self.raises is not None:
                raise self.raises
            return self._real(location, entry, dest_dir, progress_then_wait, cancelled)
        finally:
            self.finished.set()


class FakeStage:
    """update_install.stage_mac 대신 (hdiutil 없이): 앱 옆 숨김 이름의 폴더를 '준비한 앱'으로 만듦. gate를 정하면
    준비 중에 그 Event를 기다림, raises를 정하면 (gate 뒤) 그 예외를 올림."""

    def __init__(self):
        self.calls = []
        self.gate = None
        self.raises = None
        self.entered = threading.Event()

    def __call__(self, dmg_path, app_path, target_version):
        self.calls.append((dmg_path, app_path, target_version))
        assert os.path.isfile(dmg_path)
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(10), "시험의 gate가 10초 안에 열리지 않음"
        if self.raises is not None:
            raise self.raises
        staged = os.path.join(os.path.dirname(app_path), f".{os.path.basename(app_path)}.update-{target_version}")
        os.makedirs(os.path.join(staged, "Contents"))
        return staged


class FakeJob:
    """실행 중인 작업 (stop_running_jobs가 멈춤)."""

    def __init__(self):
        self.running = True
        self.stopped = False
        self.on_stop = None  # 멈출 때 부름 (그때의 창 상태를 시험)

    def isRunning(self):
        return self.running

    def blockSignals(self, block):
        pass

    def stop(self):
        self.stopped = True
        if self.on_stop is not None:
            self.on_stop()

    def wait(self, ms):
        self.running = False
        return True


def fake_running_worker(player, attr):
    job = FakeJob()
    setattr(player, attr, job)
    return job


@pytest.fixture
def fake_helpers(monkeypatch):
    fake = FakeHelpers()
    monkeypatch.setattr(update_install, "launch_helper_windows", fake.windows)
    monkeypatch.setattr(update_install, "launch_helper_mac", fake.mac)
    return fake


@pytest.fixture
def quits(monkeypatch):
    calls = []
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: calls.append("quit")))
    return calls


@pytest.fixture
def downloads(monkeypatch):
    spy = DownloadSpy(update_install.download)
    monkeypatch.setattr(update_install, "download", spy)
    return spy


@pytest.fixture
def fake_stage(monkeypatch):
    fake = FakeStage()
    monkeypatch.setattr(update_install, "stage_mac", fake)
    return fake


@pytest.fixture
def nas_dir(tmp_path):
    folder = tmp_path / "nas" / "updates"
    folder.mkdir(parents=True)
    return str(folder)


@pytest.fixture
def make_offer_player(player_with_build, fake_helpers, downloads, quits, tmp_state_dir, monkeypatch):
    """key 플랫폼의 빌드된 1.1.0 창이 results를 확인해 알림 띠를 보인 상태. 앱 위치는 app_path, 여유 공간 확인은 1 byte."""

    def make(key, results, app_path):
        monkeypatch.setattr(build_info, "platform_key", lambda: key)
        monkeypatch.setitem(update_install.NEEDED_BYTES, key, 1)  # 시험 컴퓨터의 남은 공간과 상관없이
        monkeypatch.setattr(update_install, "running_app_location", lambda: app_path)
        player = player_with_build("1.1.0", results)
        check_now(player)
        assert player.update_banner.mode() == "offer", player.update_banner.full_text()
        return player

    return make


def apps_root(tmp_path):
    """가짜 설치 폴더·Mac 앱을 둘 곳. tmp_state_dir가 tmp_path를 LOCALAPPDATA·HOME으로 쓰므로 업데이트 상태·기록 폴더
    (Windows tmp_path/YesonCheck/…, Mac tmp_path/Library/…)와 겹치지 않는 따로 된 폴더 아래에."""
    return tmp_path / "apps"


@pytest.fixture
def install_dir(tmp_path):
    folder = apps_root(tmp_path) / "YesonCheck"
    folder.mkdir(parents=True)  # exist_ok 없이 — 상태 폴더와 겹치면 바로 드러나게
    return str(folder)


@pytest.fixture
def player_offer(make_offer_player, nas_dir, install_dir):
    """Windows: NAS에 1.1.1 설치 파일."""
    return make_offer_player("windows", [on_nas(nas_dir, "1.1.1", "windows")], install_dir)


@pytest.fixture
def mac_app(tmp_path):
    app = apps_root(tmp_path) / "Applications" / "YesonCheck_Autocut_Intel.app"
    app.mkdir(parents=True)
    return str(app)


@pytest.fixture
def player_offer_mac(make_offer_player, nas_dir, mac_app, fake_stage):
    """Mac(Intel): NAS에 1.1.1 dmg."""
    return make_offer_player("mac-x86_64", [on_nas(nas_dir, "1.1.1", "mac-x86_64")], mac_app)


def download_started(downloads):
    return bool(downloads.calls)


def downloads_dir():
    return os.path.join(update_install.state_dir(), "downloads")


def downloaded_files():
    folder = downloads_dir()
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def part_files(state_dir):
    return [os.path.join(root, name) for root, _dirs, names in os.walk(state_dir) for name in names
            if name.endswith(".part")]


def update_log():
    with open(update_install.log_path(), encoding="utf-8") as fh:
        return fh.read()


class BrokenLog:
    """update_install.log 대신: match가 들어 있는 줄(None이면 모든 줄)에서 OSError — 업데이트 기록을 쓰지 못함."""

    def __init__(self, real, match=None):
        self._real = real
        self.match = match

    def __call__(self, line):
        if self.match is None or self.match in line:
            raise OSError("시험용 기록 쓰기 실패")
        self._real(line)


@pytest.fixture
def broken_log(monkeypatch):
    def install(match=None):
        broken = BrokenLog(update_install.log, match)
        monkeypatch.setattr(update_install, "log", broken)
        return broken

    return install


def wait_offer_again(player):
    wait_until(lambda: player._update_run is None and player.update_banner.mode() == "offer")
    _settle()


# ---- '업데이트'를 누르면 ----


def test_busy_jobs_ask_first(player_offer, dialogs, downloads, fake_helpers):
    fake_running_worker(player_offer, "merge_worker")
    dialogs.answer_question(QMessageBox.No)
    player_offer.start_update()
    assert dialogs.questions[0].endswith("진행 중인 작업(영상 병합)을 멈추고 업데이트할까요?")
    assert not download_started(downloads)
    assert player_offer.update_banner.mode() == "offer" and player_offer.update_banner.full_text() == OFFER_TEXT
    assert not fake_helpers.called and read_pending() is None
    assert "영상 병합" in update_log()


def test_running_job_labels_lists_running_jobs(player_offer):
    assert player_offer.running_job_labels() == []
    fake_running_worker(player_offer, "merge_worker")
    fake_running_worker(player_offer, "ocr_worker")
    stopped = fake_running_worker(player_offer, "annotation_export_worker")
    stopped.running = False
    assert player_offer.running_job_labels() == ["OCR 분석·컷 감지", "영상 병합"]


def test_success_hands_off_and_quits(player_offer, fake_helpers, quits, downloads, tmp_state_dir, install_dir,
                                     dialogs, nas_dir):
    os.makedirs(downloads_dir(), exist_ok=True)
    with open(os.path.join(downloads_dir(), "YesonCheck_Setup_1.1.0.exe.part"), "wb") as fh:  # 지난번에 남은 것
        fh.write(b"old")
    started = now()
    player_offer.update_banner.update_button.click()
    assert player_offer.update_banner.mode() == "progress"
    wait_until(lambda: fake_helpers.called)
    pending = read_pending()
    assert pending.target == "1.1.1" and fake_helpers.args.target == "1.1.1"
    assert (pending.previous, pending.platform_key) == ("1.1.0", "windows")
    assert pending.started >= started and len(pending.started) == len(started)  # log_tail_since가 비교하는 형식
    installer = os.path.join(downloads_dir(), "YesonCheck_Setup_1.1.1.exe")
    assert fake_helpers.args.kind == "windows"
    assert fake_helpers.args.installer == installer and fake_helpers.args.install_dir == install_dir
    with open(installer, "rb") as fh:
        assert fh.read() == INSTALLER
    assert downloaded_files() == ["YesonCheck_Setup_1.1.1.exe"]  # 지난번 것은 지움
    assert downloads.calls == [os.path.join(nas_dir, "YesonCheck_Setup_1.1.1.exe")]
    assert player_offer.isHidden()  # 창 닫힘 → 앱 종료 요청
    assert quits == ["quit"]
    assert dialogs.messages == []
    log = update_log()
    for step in ("시작", "받기 시작", "받기 끝", "업데이트 기록", "도우미", "앱을 끝냄"):
        assert step in log, step


def test_busy_jobs_yes_updates_and_close_stops_them(player_offer, dialogs, fake_helpers, quits):
    merge = fake_running_worker(player_offer, "merge_worker")
    visible_when_stopped = []
    merge.on_stop = lambda: visible_when_stopped.append(player_offer.isVisible())
    player_offer.start_update()  # 대답은 기본 Yes
    assert len(dialogs.questions) == 1
    wait_until(lambda: fake_helpers.called)
    assert len(dialogs.questions) == 1  # 이미 멈추기로 한 작업은 다시 묻지 않음
    assert merge.stopped and player_offer.isHidden() and quits == ["quit"]
    assert visible_when_stopped == [False]  # 작업이 멈추기를 기다리는 동안 멈춘 창이 보이지 않게 먼저 숨김


def test_progress_shown_and_cancel_restores_offer(player_offer, downloads, fake_helpers, tmp_state_dir, quits):
    downloads.gate = threading.Event()
    player_offer.start_update()
    wait_until(lambda: downloads.entered.is_set())
    _settle()
    banner = player_offer.update_banner
    assert banner.mode() == "progress" and banner.full_text().startswith("1.1.1 받는 중 (NAS)…")
    assert banner.progress_bar.isVisible() and banner.cancel_button.isVisible()
    assert banner.progress_bar.value() == 1000 // 3
    run = player_offer._update_run
    assert run.download.parent() is None and run.download in type(run.download)._running
    banner.cancel_button.click()
    assert banner.full_text() == "취소하는 중…"
    downloads.gate.set()
    wait_offer_again(player_offer)
    assert banner.full_text() == OFFER_TEXT and player_offer.update_offer is run.offer
    assert not part_files(tmp_state_dir) and downloaded_files() == []
    assert read_pending() is None and not fake_helpers.called and quits == []
    assert "취소" in update_log()


def test_cancel_after_download_finished_does_not_hand_off(player_offer, downloads, fake_helpers, quits):
    """다 받은 뒤 결과 신호가 처리되기 전에 '취소'를 누름 → 넘기지 않고 받은 파일을 지움."""
    player_offer.start_update()
    download = player_offer._update_run.download
    assert download.wait(10000)  # 이벤트를 처리하지 않고 기다림 → ready가 대기열에 있음
    player_offer.update_banner.cancel_button.click()
    wait_offer_again(player_offer)
    assert not fake_helpers.called and read_pending() is None and quits == []
    assert downloaded_files() == []


def test_download_failure_dialog_keeps_offer(make_offer_player, nas_dir, install_dir, dialogs, fake_helpers,
                                             tmp_state_dir, quits):
    wrong = "0" * 64
    player = make_offer_player("windows", [on_nas(nas_dir, "1.1.1", "windows", sha256=wrong)], install_dir)
    player.start_update()
    wait_until(lambda: dialogs.criticals)
    _settle()
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("critical", "업데이트 실패")
    assert wrong in text and hashlib.sha256(INSTALLER).hexdigest() in text  # 기대·실제 sha256
    assert "NAS" in text and os.path.join(nas_dir, "YesonCheck_Setup_1.1.1.exe") in text
    assert player.update_banner.mode() == "offer" and player.update_banner.full_text() == OFFER_TEXT
    assert read_pending() is None and not fake_helpers.called and quits == []
    assert not part_files(tmp_state_dir) and downloaded_files() == []
    assert update_log().count(wrong) == 1  # 받기 스레드가 한 번 (창 쪽은 이유를 다시 적지 않음)


def test_unexpected_download_error_shows_traceback(player_offer, downloads, dialogs, fake_helpers):
    downloads.raises = RuntimeError("시험용 받기 오류")
    player_offer.start_update()
    wait_until(lambda: dialogs.criticals)
    _settle()
    [text] = dialogs.criticals
    assert "Traceback" in text and "RuntimeError: 시험용 받기 오류" in text
    assert player_offer.update_banner.mode() == "offer" and not fake_helpers.called


def test_github_failure_does_not_switch_to_nas(make_offer_player, nas_dir, install_dir, http_server, dialogs,
                                               downloads, fake_helpers, quits):
    """GitHub에서 받다 실패하면 NAS로 저절로 바꾸지 않고 창 — 다시 '업데이트'를 누르면 다시 받음."""
    github = published("GitHub", http_server.url, "1.1.2", "windows")
    player = make_offer_player("windows", [on_nas(nas_dir, "1.1.1", "windows"), github], install_dir)
    url = f"{http_server.url}/download/v1.1.2/YesonCheck_Setup_1.1.2.exe"
    player.start_update()
    wait_until(lambda: dialogs.criticals)
    _settle()
    [text] = dialogs.criticals
    assert "GitHub" in text and url in text and "404" in text
    assert downloads.calls == [url]  # NAS의 1.1.1로 바꿔 받지 않음
    assert player.update_banner.full_text() == "⬆ 새 버전 1.1.2이 나왔습니다 · 지금 1.1.0"
    http_server.serve("/download/v1.1.2/YesonCheck_Setup_1.1.2.exe", INSTALLER)
    player.update_banner.update_button.click()
    wait_until(lambda: fake_helpers.called)
    assert fake_helpers.args.target == "1.1.2" and read_pending().target == "1.1.2"
    assert downloads.calls == [url, url] and quits == ["quit"]


def test_not_enough_space_shows_failure(player_offer, dialogs, downloads, monkeypatch):
    monkeypatch.setitem(update_install.NEEDED_BYTES, "windows", 10 ** 18)
    player_offer.start_update()
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("critical", "업데이트 실패") and "여유 공간이 모자랍니다" in text
    assert not download_started(downloads) and player_offer.update_banner.mode() == "offer"


def test_helper_launch_failure_keeps_app_running(player_offer, fake_helpers, dialogs, quits):
    fake_helpers.raises = OSError("시험용 도우미 실행 실패")
    player_offer.start_update()
    wait_until(lambda: dialogs.criticals)
    _settle()
    [text] = dialogs.criticals
    assert "Traceback" in text and "OSError: 시험용 도우미 실행 실패" in text
    assert read_pending() is None  # 넘기지 못했으니 기록을 지움
    assert player_offer.isVisible() and quits == []
    assert player_offer.update_banner.mode() == "offer"


def test_helper_failure_and_record_not_cleared_shows_both(player_offer, fake_helpers, dialogs, quits, monkeypatch):
    """도우미를 못 띄운 데다 기록도 못 지움 → 둘 다 창에 (도우미 오류는 기록을 지우기 전에 업데이트 기록에 남김)."""
    fake_helpers.raises = OSError("시험용 도우미 실행 실패")
    logged_before_clear = []

    def broken_clear():
        logged_before_clear.append("시험용 도우미 실행 실패" in update_log())
        raise PermissionError("시험용 기록 지우기 실패")

    monkeypatch.setattr(update_install, "clear_pending", broken_clear)
    player_offer.start_update()
    wait_until(lambda: dialogs.criticals)
    _settle()
    [text] = dialogs.criticals
    assert "OSError: 시험용 도우미 실행 실패" in text and "PermissionError: 시험용 기록 지우기 실패" in text
    assert logged_before_clear == [True]
    assert player_offer.isVisible() and quits == [] and player_offer.update_banner.mode() == "offer"


def test_log_failure_at_start_shows_failure_and_does_not_download(player_offer, broken_log, dialogs, downloads,
                                                                  capsys):
    """시작할 때 업데이트 기록을 쓸 수 없으면 (도우미·다시 켜진 앱의 실패 창도 같은 기록을 씀) 받지 않고 실패 창."""
    broken_log()
    player_offer.start_update()
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("critical", "업데이트 실패") and "OSError: 시험용 기록 쓰기 실패" in text
    assert not download_started(downloads) and player_offer.update_banner.mode() == "offer"
    assert "시험용 기록 쓰기 실패" in capsys.readouterr().err  # 실패 창의 기록 줄도 못 씀 → stderr에 줄과 이유


def test_log_failure_after_helper_still_quits(player_offer, broken_log, fake_helpers, quits, capsys):
    broken_log(match="도우미를 띄움")
    player_offer.start_update()
    wait_until(lambda: fake_helpers.called)
    assert player_offer.isHidden() and quits == ["quit"]
    err = capsys.readouterr().err
    assert "도우미를 띄움" in err and "시험용 기록 쓰기 실패" in err


def test_log_failure_when_closing_still_releases_download(player_offer, downloads, broken_log, fake_helpers,
                                                          tmp_state_dir, quits, capsys):
    """창을 닫을 때 업데이트 기록을 못 써도 받기 스레드를 놓고(release_worker) 진행 중인 작업도 멈춤."""
    merge = fake_running_worker(player_offer, "merge_worker")  # 멈추기로 함 (기본 Yes)
    downloads.gate = threading.Event()
    player_offer.start_update()
    wait_until(lambda: downloads.entered.is_set())
    download = player_offer._update_run.download
    broken_log()
    player_offer.close()
    try:
        assert download in player_base._RELEASED_WORKERS and download.is_cancelled()
        assert merge.stopped  # 창 닫기의 뒤쪽 정리도 돎
    finally:
        downloads.gate.set()
    assert player_base.wait_for_released_workers(5) == []
    assert not part_files(tmp_state_dir) and read_pending() is None and not fake_helpers.called
    assert "창을 닫음" in capsys.readouterr().err


def test_failure_after_close_is_logged(player_offer_mac, fake_stage, tmp_state_dir):
    """창을 닫은 뒤(결과 신호가 막힘)의 실패도 받기 스레드가 업데이트 기록에 남김."""
    fake_stage.gate = threading.Event()
    fake_stage.raises = update_install.UpdateError("시험용 준비 실패")
    player_offer_mac.start_update()
    wait_until(lambda: fake_stage.entered.is_set())
    player_offer_mac.close()
    fake_stage.gate.set()
    assert player_base.wait_for_released_workers(5) == []
    assert "시험용 준비 실패" in update_log()


def test_thread_log_failure_prints_both_to_stderr(player_offer, downloads, broken_log, dialogs, capsys):
    downloads.gate = threading.Event()
    player_offer.start_update()
    wait_until(lambda: downloads.entered.is_set())
    broken_log()
    downloads.raises_after_gate = update_install.UpdateError("시험용 받기 실패")
    downloads.gate.set()
    wait_until(lambda: dialogs.criticals)
    _settle()
    assert "시험용 받기 실패" in dialogs.criticals[0]
    err = capsys.readouterr().err
    assert "시험용 받기 실패" in err and "OSError: 시험용 기록 쓰기 실패" in err


def test_log_failure_in_check_result_does_not_escape_the_slot(player_with_build, broken_log, dialogs, capsys):
    """확인 결과 슬롯(3시간마다의 자동 확인)이 업데이트 기록을 쓰지 못해도 예외가 슬롯 밖으로 나가지 않음 — Mac(excepthook
    없음)에서는 나가면 PyQt가 앱을 끝냄. 결과는 그대로 띠에, 줄과 이유는 stderr에. 슬롯을 직접 불러 확인 (나가면 여기서 실패)."""
    player = player_with_build("1.1.0")
    broken_log()
    results = [found("NAS", "1.1.1"), error("GitHub", "GitHub 응답 오류: HTTP 500")]
    current = updates.Version.parse("1.1.0")
    offer = updates.choose_offer(current, build_info.platform_key(), results)
    player._update_check_current = current  # 확인이 돌던 상태 (start_update_check가 정함)
    player._on_update_checked(updates.CheckResult(results, offer))
    assert player.update_banner.mode() == "offer" and player.update_banner.full_text() == OFFER_TEXT
    assert [m[1] for m in dialogs.messages] == ["업데이트 확인 실패"]  # 오류 창은 그대로
    player.update_banner.show_progress(1, 4, "1.1.1 받는 중…")  # 받는 중: '띠는 그대로 둠' 기록 줄
    player._update_check_current = current
    player._on_update_checked(updates.CheckResult(results, offer))
    assert player.update_banner.mode() == "progress"
    err = capsys.readouterr().err
    assert "새 버전 1.1.1 (NAS)" in err and "받는 중이라" in err and "OSError: 시험용 기록 쓰기 실패" in err


def test_log_failure_in_check_failure_does_not_escape_the_slot(player_with_build, broken_log, dialogs, capsys):
    player = player_with_build("1.1.0")
    broken_log()
    player._on_update_check_failed("Traceback (most recent call last):\nRuntimeError: 시험용 확인 오류")
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("warning", "업데이트 확인 실패") and "RuntimeError: 시험용 확인 오류" in text
    err = capsys.readouterr().err
    assert "예상치 못한 오류" in err and "OSError: 시험용 기록 쓰기 실패" in err


def test_log_failure_when_auto_check_comes_during_a_check(player_with_build, fake_check, broken_log, capsys):
    """확인 중에 온 자동 확인(3시간 타이머의 슬롯)이 '끝나면 다시' 기록을 쓰지 못해도 예외가 나가지 않고 다시 확인함."""
    player = player_with_build("1.1.0", [found("NAS", "1.1.1")])
    fake_check.gate = threading.Event()
    player.start_update_check(manual=False)
    assert fake_check.entered.wait(5)
    broken_log()
    player.start_update_check(manual=False)  # 타이머 슬롯과 같은 부름
    fake_check.gate.set()
    wait_until(lambda: len(fake_check.calls) == 2 and not player.update_check_running)
    assert "끝나면 다시 확인" in capsys.readouterr().err


def test_new_job_during_download_asks_before_hand_off(player_offer, downloads, dialogs, fake_helpers, quits):
    """받는 동안 시작한 작업은 멈추기로 한 적이 없음 → 넘기기 전에 다시 물음 (아니오: 넘기지 않고 받은 파일을 지움)."""
    downloads.gate = threading.Event()
    player_offer.start_update()
    assert dialogs.questions == []  # 누를 때는 작업이 없었음
    wait_until(lambda: downloads.entered.is_set())
    export = fake_running_worker(player_offer, "ocr_export_worker")
    dialogs.answer_question(QMessageBox.No)
    downloads.gate.set()
    wait_offer_again(player_offer)
    assert dialogs.questions == ["진행 중인 작업(OCR 구간 내보내기)을 멈추고 업데이트할까요?"]
    assert not fake_helpers.called and read_pending() is None and quits == []
    assert downloaded_files() == [] and not export.stopped


def test_close_during_download_leaves_no_pending(player_offer, downloads, fake_helpers, tmp_state_dir, quits):
    downloads.gate = threading.Event()
    player_offer.start_update()
    wait_until(lambda: downloads.entered.is_set())
    download = player_offer._update_run.download
    player_offer.close()
    try:
        assert download in player_base._RELEASED_WORKERS  # 끝날 때까지 붙잡아 둠
        assert download.is_cancelled()
    finally:
        downloads.gate.set()
    assert downloads.finished.wait(10)
    assert player_base.wait_for_released_workers(5) == []
    _settle()
    assert read_pending() is None and not part_files(tmp_state_dir) and not fake_helpers.called
    assert downloaded_files() == [] and quits == []


# ---- Mac ----


def test_mac_refuses_translocated(player_offer_mac, dialogs, downloads, monkeypatch):
    monkeypatch.setattr(update_install, "running_app_location", lambda: "/Volumes/X/YesonCheck_Autocut_Intel.app")
    player_offer_mac.start_update()
    assert "응용 프로그램 폴더" in dialogs.warnings[0] and not download_started(downloads)
    assert dialogs.messages[0][1] == "업데이트할 수 없음"
    assert player_offer_mac.update_banner.mode() == "offer"


def test_mac_refuses_before_asking_about_jobs(player_offer_mac, dialogs, downloads, monkeypatch):
    monkeypatch.setattr(update_install, "running_app_location",
                        lambda: "/private/var/folders/x/AppTranslocation/1/d/YesonCheck_Autocut_Intel.app")
    fake_running_worker(player_offer_mac, "merge_worker")
    player_offer_mac.start_update()
    assert dialogs.questions == [] and len(dialogs.warnings) == 1 and not download_started(downloads)


def test_mac_stages_then_hands_off(player_offer_mac, fake_stage, fake_helpers, quits, mac_app, dialogs):
    fake_stage.gate = threading.Event()
    player_offer_mac.start_update()
    wait_until(lambda: fake_stage.entered.is_set())
    _settle()
    banner = player_offer_mac.update_banner
    assert banner.mode() == "progress" and banner.full_text() == "준비 중…"
    fake_stage.gate.set()
    wait_until(lambda: fake_helpers.called)
    dmg = os.path.join(downloads_dir(), "YesonCheck_Autocut_Intel_1.1.1.dmg")
    assert fake_stage.calls == [(dmg, mac_app, "1.1.1")]
    staged = os.path.join(os.path.dirname(mac_app), ".YesonCheck_Autocut_Intel.app.update-1.1.1")
    assert fake_helpers.args.kind == "mac"
    assert (fake_helpers.args.staged_app, fake_helpers.args.app_path, fake_helpers.args.target) == (staged, mac_app,
                                                                                                    "1.1.1")
    assert downloaded_files() == []  # 새 앱을 꺼낸 dmg는 지움
    pending = read_pending()
    assert (pending.target, pending.previous, pending.platform_key) == ("1.1.1", "1.1.0", "mac-x86_64")
    assert player_offer_mac.isHidden() and quits == ["quit"] and dialogs.messages == []


def test_mac_close_while_staging_removes_staged_app(player_offer_mac, fake_stage, fake_helpers, quits, mac_app):
    fake_stage.gate = threading.Event()
    player_offer_mac.start_update()
    wait_until(lambda: fake_stage.entered.is_set())
    player_offer_mac.close()
    fake_stage.gate.set()
    assert player_base.wait_for_released_workers(5) == []
    staged = os.path.join(os.path.dirname(mac_app), ".YesonCheck_Autocut_Intel.app.update-1.1.1")
    assert not os.path.exists(staged) and downloaded_files() == []
    assert not fake_helpers.called and read_pending() is None and quits == []


# ---- 다시 켜진 앱 ----


def test_startup_ok_shows_message(tmp_state_dir, player_with_build, dialogs):
    write_pending(Pending("1.1.1", "1.1.0", "windows", now()))
    p = player_with_build("1.1.1")
    p.handle_update_startup()
    assert p.update_banner.full_text() == "1.1.1로 업데이트했습니다" and p.update_banner.mode() == "message"
    assert os.path.exists(ok_marker_path())
    assert read_pending() is None and dialogs.messages == []
    assert "1.1.1로 업데이트했습니다" in update_log()


def test_startup_failed_shows_log(tmp_state_dir, player_with_build, dialogs):
    write_pending(Pending("1.1.1", "1.1.0", "windows", now()))
    update_install.log("설치 실패: 예시")
    p = player_with_build("1.1.0")
    p.handle_update_startup()
    assert "설치 실패: 예시" in dialogs.criticals[0]
    [(kind, title, text)] = dialogs.messages
    assert title == "업데이트 실패" and "1.1.1" in text and update_install.log_path() in text
    assert read_pending() is None and not os.path.exists(ok_marker_path())


def test_startup_failed_shows_helper_output_missing_from_log(tmp_state_dir, player_with_build, dialogs):
    """도우미가 기록을 쓰기 전에 실패했으면(PowerShell이 모듈을 불러오지 못함 등) 그 이유는 도우미 출력에만 있음 → 실패 창에
    기록과 함께 보임 (기록과 같은 줄은 다시 보이지 않음)."""
    write_pending(Pending("1.1.1", "1.1.0", "windows", now()))
    update_install.log("업데이트 1.1.1: 도우미를 띄움")
    with open(update_install.log_path(), encoding="utf-8") as fh:
        logged = fh.read().splitlines()[-1]
    error = "New-Object : The 'New-Object' command was found in the module 'Microsoft.PowerShell.Utility', but the module could not be loaded."
    with open(update_install.helper_console_path(), "w", encoding="utf-8") as fh:
        fh.write(f"{logged}\n{error}\n")
    p = player_with_build("1.1.0")
    p.handle_update_startup()
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("critical", "업데이트 실패")
    assert error in text and update_install.helper_console_path() in text and text.count(logged) == 1
    assert error in update_log()  # 출력 파일은 다음 업데이트에서 새로 쓰므로 기록에도 남김


def test_startup_corrupt_record_shows_dialog(tmp_state_dir, player_with_build, dialogs):
    with open(os.path.join(tmp_state_dir, update_install.PENDING_FILE_NAME), "w", encoding="utf-8") as fh:
        fh.write("{깨진")
    p = player_with_build("1.1.1")
    p.handle_update_startup()
    [(kind, title, text)] = dialogs.messages
    assert (kind, title) == ("critical", "업데이트 실패") and "업데이트 기록을 읽지 못했습니다" in text
    assert read_pending() is None  # 보인 뒤 지움 (켤 때마다 같은 창이 뜨지 않게)


def test_startup_without_record_or_in_source_run_does_nothing(tmp_state_dir, player_with_build, dialogs, monkeypatch):
    p = player_with_build("1.1.1")
    p.handle_update_startup()
    assert dialogs.messages == [] and p.update_banner.mode() == "hidden"
    write_pending(Pending("1.1.1", "1.1.0", "windows", now()))
    monkeypatch.setattr(build_info, "current", lambda: None)
    p.handle_update_startup()
    assert dialogs.messages == [] and read_pending() is not None  # 소스 실행은 기록을 건드리지 않음
    assert not os.path.exists(ok_marker_path())
