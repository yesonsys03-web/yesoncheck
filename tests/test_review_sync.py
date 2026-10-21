"""웹 보고서 실시간 동기화: 창마다 빈 포트와 토큰 (review_sync), 보고서 HTML의 접속 주소 (web_info),
OCR 검토 창이 서버를 쓰는 방식 (player_review)."""

import base64
import json
import os
import re
import socket
import time
from urllib.parse import parse_qs, urlparse

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QUrl
from PyQt5.QtWebSockets import QWebSocket, QWebSocketProtocol
from PyQt5.QtWidgets import QApplication

from yesoncheck import review_sync, web_info


def wait_until(cond, timeout=10.0):
    """cond()가 참이 될 때까지 Qt 이벤트를 돌린다. 참이 되었는지를 돌려준다 (기본 10초 — 느린 Windows CI)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return cond()


class Page:
    """웹 보고서 쪽 흉내: QWebSocket 클라이언트가 받은 글과 닫힘을 기록."""

    def __init__(self, url):
        self.texts = []
        self.is_open = False
        self.closed = False
        self.sock = QWebSocket()
        self.sock.connected.connect(lambda: setattr(self, "is_open", True))
        self.sock.disconnected.connect(lambda: setattr(self, "closed", True))
        self.sock.textMessageReceived.connect(self.texts.append)
        self.sock.open(QUrl(url))

    def send(self, obj):
        self.sock.sendTextMessage(obj if isinstance(obj, str) else json.dumps(obj))

    def close(self):
        self.sock.close()
        wait_until(lambda: self.closed, 1.0)


@pytest.fixture
def servers(qapp):
    made = []

    def make():
        server = review_sync.ReviewSyncServer()
        made.append(server)
        return server

    yield make
    for server in made:
        server.close()


@pytest.fixture
def pages(qapp):
    made = []

    def make(url):
        page = Page(url)
        made.append(page)
        return page

    yield make
    for page in made:
        page.sock.abort()


def port_and_token(url):
    parts = urlparse(url)
    return parts.port, parse_qs(parts.query)["token"][0]


def with_token(url, token):
    return re.sub(r"token=[^&]*", f"token={token}", url)


def test_two_servers_get_different_ports(servers):
    url_a = servers().start()
    url_b = servers().start()

    for url in (url_a, url_b):
        assert re.fullmatch(r"ws://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_-]{20,}", url), url
    port_a, token_a = port_and_token(url_a)
    port_b, token_b = port_and_token(url_b)
    assert port_a != port_b
    assert token_a != token_b


def test_listen_failure_raises_with_reason(servers, monkeypatch):
    monkeypatch.setattr(review_sync.QWebSocketServer, "listen", lambda self, *a: False)
    monkeypatch.setattr(review_sync.QWebSocketServer, "errorString", lambda self: "주소를 쓸 수 없음")

    with pytest.raises(RuntimeError, match="주소를 쓸 수 없음"):
        servers().start()


def test_right_token_receives_messages(servers, pages):
    server = servers()
    received = []
    connected = []
    server.message_received.connect(lambda client, msg: received.append((client, msg)))
    server.client_connected.connect(connected.append)
    page = pages(server.start())
    assert wait_until(lambda: page.is_open)
    assert wait_until(lambda: len(connected) == 1)

    page.send({"type": "segments_update", "segments": [{"text": "A"}], "selected_index": 0})
    page.send({"type": "request_sync"})

    assert wait_until(lambda: len(received) == 2)
    assert [msg["type"] for _, msg in received] == ["segments_update", "request_sync"]
    assert received[0][1]["segments"] == [{"text": "A"}]
    assert all(client is connected[0] for client, _ in received)
    assert not page.closed


def test_server_sends_to_one_client_and_broadcasts(servers, pages):
    server = servers()
    connected = []
    server.client_connected.connect(connected.append)
    url = server.start()
    page_1, page_2 = pages(url), pages(url)
    assert wait_until(lambda: len(connected) == 2 and server.has_clients())

    server.send(connected[0], "only-first")
    server.broadcast("everyone")

    assert wait_until(lambda: len(page_1.texts) + len(page_2.texts) == 3)
    assert sorted(page_1.texts + page_2.texts) == ["everyone", "everyone", "only-first"]


def raw_upgrade(port, path):
    """QWebSocket 없이 소켓으로 WebSocket 업그레이드를 청하고, 서버가 연결을 끊을 때까지 받은 바이트를 (응답 머리, 그 뒤)로.
    받은 차례 그대로 보므로 서버가 보낸 닫기 프레임을 플랫폼과 상관없이 확인할 수 있음 — QWebSocket 클라이언트의 closeCode()는
    Windows CI에서 1008이 아니었음 (받은 바이트를 queued로 처리해 끊김을 먼저 보면 닫기 프레임을 읽지 않는 것으로 보임)."""
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        sock.sendall(request.encode("ascii"))
        sock.setblocking(False)
        data = bytearray()

        def ended():
            try:
                chunk = sock.recv(4096)
            except BlockingIOError:
                return False
            data.extend(chunk)
            return not chunk

        assert wait_until(ended), f"서버가 연결을 끊지 않음 (받은 것: {bytes(data)!r})"
    finally:
        sock.close()
    head, sep, rest = bytes(data).partition(b"\r\n\r\n")
    assert sep, f"업그레이드 응답이 끝나지 않음: {bytes(data)!r}"
    return head, rest


@pytest.mark.parametrize("path", ["/?token=not-the-token", "/"])
def test_bad_token_gets_policy_violation_close_frame(servers, path, capsys):
    """토큰이 틀리거나 없으면 서버가 닫기 프레임(1008 PolicyViolated, "bad token")만 보내고 TCP 연결을 끊음 (웹 보고서가 보는 것)."""
    server = servers()
    received, connected = [], []
    server.message_received.connect(lambda client, msg: received.append(msg))
    server.client_connected.connect(connected.append)
    port, _ = port_and_token(server.start())

    head, rest = raw_upgrade(port, path)

    assert head.startswith(b"HTTP/1.1 101"), head
    reason = b"bad token"
    code = int(QWebSocketProtocol.CloseCodePolicyViolated).to_bytes(2, "big")
    assert rest == bytes([0x88, 2 + len(reason)]) + code + reason  # FIN+닫기, 마스크 없음, 길이, 1008, 이유 — 그 뒤 끊김
    assert received == [] and connected == [] and not server.has_clients()
    assert "토큰이 맞지 않는 접속을 닫음" in capsys.readouterr().out


def test_wrong_token_connection_closed(servers, pages, capsys):
    """틀린 토큰의 보고서: 끊기고, 보낸 글은 닿지 않고, 서버가 모두에게 보내는 글도 받지 않음 (닫기 코드는
    test_bad_token_gets_policy_violation_close_frame)."""
    server = servers()
    received, connected = [], []
    server.message_received.connect(lambda client, msg: received.append(msg))
    server.client_connected.connect(connected.append)
    url = server.start()

    page = pages(with_token(url, "not-the-token"))
    assert wait_until(lambda: page.closed)
    page.send({"type": "request_sync"})  # 이미 닫힌 뒤: 아무 데도 닿지 않음
    good = pages(url)
    assert wait_until(lambda: len(connected) == 1 and good.is_open)
    server.broadcast("everyone")
    assert wait_until(lambda: good.texts == ["everyone"])
    wait_until(lambda: bool(received) or bool(page.texts), 0.3)

    assert received == [] and page.texts == []
    assert len(connected) == 1 and server.has_clients()  # 받아들인 것은 맞는 토큰의 보고서 하나
    log = capsys.readouterr()
    assert "토큰이 맞지 않는 접속을 닫음" in log.out
    assert "not-the-token" not in log.out + log.err  # 받은 값을 기록에 남기지 않음


def test_missing_token_connection_closed(servers, pages, capsys):
    server = servers()
    port, _ = port_and_token(server.start())

    page = pages(f"ws://127.0.0.1:{port}/")

    assert wait_until(lambda: page.closed)
    assert not server.has_clients()
    assert "토큰이 맞지 않는 접속을 닫음" in capsys.readouterr().out


def test_other_windows_token_is_rejected(servers, pages):
    """창 B의 보고서(토큰 B)가 창 A의 포트로 접속해도 받아 주지 않는다."""
    server_a, server_b = servers(), servers()
    url_a, url_b = server_a.start(), server_b.start()
    received_a = []
    server_a.message_received.connect(lambda client, msg: received_a.append(msg))
    _, token_b = port_and_token(url_b)

    page = pages(with_token(url_a, token_b))

    assert wait_until(lambda: page.closed)
    assert received_a == []
    assert not server_a.has_clients()


def test_bad_json_is_logged_and_connection_kept(servers, pages, capsys):
    server = servers()
    received = []
    server.message_received.connect(lambda client, msg: received.append(msg))
    page = pages(server.start())
    assert wait_until(lambda: page.is_open)

    page.send("{not json")
    page.send("[1, 2]")  # JSON이지만 객체가 아님
    page.send({"type": "request_sync"})

    assert wait_until(lambda: len(received) == 1)
    assert received == [{"type": "request_sync"}]
    assert not page.closed
    log = capsys.readouterr()
    assert (log.out + log.err).count("[WebSocket]") >= 2


def test_close_disconnects_clients_and_stops_listening(servers, pages):
    server = servers()
    url = server.start()
    page = pages(url)
    assert wait_until(lambda: page.is_open)

    server.close()

    assert wait_until(lambda: page.closed)
    assert not server.has_clients()
    late = pages(url)
    assert not wait_until(lambda: late.is_open, 0.5)
    server.close()  # 두 번 불러도 괜찮음


# ----------------------------------------------------------------- 보고서 HTML

SEGMENTS = [
    {"start_frame": 0, "end_frame": 23, "start_time": 0.0, "end_time": 1.0, "duration": 1.0,
     "text": "A", "edited_text": "A"},
]


def html_for(ws_url):
    return web_info._generate_html(SEGMENTS, "clip", 24.0, 24, "titmouse", None, ws_url=ws_url)


def test_report_html_uses_given_ws_url():
    url = "ws://127.0.0.1:54321/?token=abc_DEF-123"

    html = html_for(url)

    assert f"const WS_URL = {json.dumps(url)};" in html
    assert "8765" not in html
    assert "localhost" not in html
    assert "new WebSocket(WS_URL)" in html


def test_report_html_without_ws_url_does_not_connect():
    html = html_for(None)

    assert "const WS_URL = null;" in html
    assert "8765" not in html
    assert "ws://" not in html
    assert "실시간 동기화 꺼짐" in html
    # 접속은 WS_URL이 있을 때만
    assert re.search(r"if \(WS_URL !== null\) \{\s*connectWebSocket\(\);", html)


def test_generate_web_report_passes_ws_url(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    url = "ws://127.0.0.1:50000/?token=tok"

    path = web_info.generate_web_report(SEGMENTS, None, 24.0, 24, ws_url=url)
    with open(path, encoding="utf-8") as fh:
        assert f"const WS_URL = {json.dumps(url)};" in fh.read()

    path = web_info.generate_web_report(SEGMENTS, None, 24.0, 24)  # 기본값: 끔
    with open(path, encoding="utf-8") as fh:
        assert "const WS_URL = null;" in fh.read()


# ------------------------------------------------------------- OCR 검토 창

REVIEW_SEGMENTS = [
    {"start_frame": 0, "end_frame": 23, "start_time": 0.0, "end_time": 1.0, "duration": 1.0,
     "text": "A", "edited_text": "A", "roi_preview": None, "detections": []},
    {"start_frame": 24, "end_frame": 47, "start_time": 1.0, "end_time": 2.0, "duration": 1.0,
     "text": "B", "edited_text": "B", "roi_preview": None, "detections": []},
]


@pytest.fixture
def make_review(qapp, dialogs):
    from yesoncheck.player_review import OCRReviewDialog

    made = []

    def make():
        dialog = OCRReviewDialog(None, [dict(s) for s in REVIEW_SEGMENTS], fps=24, total_frames=48,
                                 ocr_mode="titmouse")
        made.append(dialog)
        return dialog

    yield make
    for dialog in made:
        dialog.close()
        sip.delete(dialog)  # deleteLater()로 미루면 다음 시험의 스타일 바꾸기에서 죽음 — 바로 지움


def test_two_review_windows_each_listen_on_their_own_port(make_review, dialogs):
    first, second = make_review(), make_review()
    QApplication.processEvents()

    assert first.sync_url and second.sync_url
    assert port_and_token(first.sync_url)[0] != port_and_token(second.sync_url)[0]
    assert port_and_token(first.sync_url)[1] != port_and_token(second.sync_url)[1]
    assert dialogs.warnings == []


def test_review_window_serves_its_own_segments(make_review, pages):
    dialog = make_review()
    page = pages(dialog.sync_url)

    page.send({"type": "request_sync"})

    assert wait_until(lambda: any(json.loads(t)["type"] == "full_sync" for t in page.texts))
    sync = json.loads(page.texts[-1])
    assert [seg["text"] for seg in sync["segments"]] == ["A", "B"]


def test_review_window_ignores_other_windows_token(make_review, pages):
    first, second = make_review(), make_review()
    page = pages(with_token(first.sync_url, port_and_token(second.sync_url)[1]))

    assert wait_until(lambda: page.closed)
    assert page.texts == []


def test_review_window_listen_failure_shows_warning(make_review, dialogs, monkeypatch):
    def refuse(self):
        raise RuntimeError("Address already in use")

    monkeypatch.setattr(review_sync.ReviewSyncServer, "start", refuse)

    dialog = make_review()
    assert wait_until(lambda: bool(dialogs.warnings))

    assert dialog.sync_url is None
    assert len(dialogs.warnings) == 1
    assert "Address already in use" in dialogs.warnings[0]
    assert "실시간" in dialogs.warnings[0]


def test_review_window_report_uses_its_own_url(make_review, monkeypatch):
    from yesoncheck import player_review

    calls = []
    monkeypatch.setattr(player_review.web_info, "generate_web_report",
                        lambda **kwargs: calls.append(kwargs) or "/tmp/report.html")
    monkeypatch.setattr(player_review.web_info, "open_web_report", lambda path: True)
    dialog = make_review()

    dialog.export_to_web()

    assert calls[0]["ws_url"] == dialog.sync_url
    assert calls[0]["ws_url"].startswith("ws://127.0.0.1:")


def test_review_window_report_without_server_has_no_ws_url(make_review, dialogs, monkeypatch):
    from yesoncheck import player_review

    def refuse(self):
        raise RuntimeError("busy")

    monkeypatch.setattr(review_sync.ReviewSyncServer, "start", refuse)
    calls = []
    monkeypatch.setattr(player_review.web_info, "generate_web_report",
                        lambda **kwargs: calls.append(kwargs) or "/tmp/report.html")
    monkeypatch.setattr(player_review.web_info, "open_web_report", lambda path: True)
    dialog = make_review()

    dialog.export_to_web()

    assert calls[0]["ws_url"] is None


def test_review_message_handler_logs_traceback_without_dialog(make_review, dialogs, capsys):
    dialog = make_review()
    capsys.readouterr()

    # row_index가 숫자가 아니면 처리 중 TypeError
    dialog.on_text_message_received(None, {"type": "split_segment", "row_index": "x", "split_frame": 1})

    log = capsys.readouterr()
    assert "Traceback" in log.out + log.err
    assert "not supported between" in log.out + log.err  # row_index < rowCount() 의 TypeError
    assert dialogs.messages == []
