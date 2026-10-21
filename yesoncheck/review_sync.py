"""OCR 검토 창 ↔ 웹 보고서 실시간 동기화 서버.

창마다 서버를 따로 만든다 — 127.0.0.1의 빈 포트(운영체제가 고름)와 무작위 토큰. 보고서는 그 창이 알려 준 주소
(`ws://127.0.0.1:포트/?token=토큰`)로만 접속하므로, 여러 창이 떠 있어도 다른 창의 검토와 이어지지 않는다.
토큰이 맞지 않는 접속은 바로 닫고 기록한다. 메시지 규약(종류·내용)은 여기서 다루지 않고 받은 JSON 객체를
`message_received`로 넘기기만 한다.
"""

import json
import secrets

from PyQt5.QtCore import QObject, QUrlQuery, pyqtSignal
from PyQt5.QtNetwork import QHostAddress
from PyQt5.QtWebSockets import QWebSocketProtocol, QWebSocketServer


class ReviewSyncServer(QObject):
    """한 OCR 검토 창의 WebSocket 서버."""

    message_received = pyqtSignal(object, dict)  # (보낸 QWebSocket, JSON 객체)
    client_connected = pyqtSignal(object)  # 토큰이 맞아 받아들인 QWebSocket

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = None
        self._token = None
        self._clients = []

    def start(self) -> str:
        """듣기를 시작하고 보고서가 접속할 주소를 돌려준다. 듣지 못하면 RuntimeError(Qt가 알려 준 이유)."""
        if self._server is not None:
            raise RuntimeError("이미 듣고 있습니다")
        server = QWebSocketServer("OCR Review Sync", QWebSocketServer.NonSecureMode, self)
        if not server.listen(QHostAddress.LocalHost, 0):
            reason = server.errorString()
            server.deleteLater()
            raise RuntimeError(reason)
        self._server = server
        self._token = secrets.token_urlsafe(16)
        server.newConnection.connect(self._on_new_connection)
        return f"ws://127.0.0.1:{server.serverPort()}/?token={self._token}"

    def has_clients(self) -> bool:
        return bool(self._clients)

    def send(self, client, text):
        client.sendTextMessage(text)

    def broadcast(self, text):
        for client in list(self._clients):
            client.sendTextMessage(text)

    def close(self):
        """접속을 모두 닫고 듣기를 멈춘다. 시작하지 않았거나 이미 닫았으면 아무것도 하지 않는다."""
        if self._server is None:
            return
        for client in list(self._clients):
            client.close()
        self._clients.clear()
        self._server.close()
        self._server = None
        print("[WebSocket] 서버 종료")

    def _on_new_connection(self):
        server = self._server
        while server is not None and server.hasPendingConnections():
            client = server.nextPendingConnection()
            if not self._token_matches(client):
                where = f"{client.peerAddress().toString()}:{client.peerPort()}"
                print(f"[WebSocket] 토큰이 맞지 않는 접속을 닫음: {where}")
                client.disconnected.connect(client.deleteLater)
                client.close(QWebSocketProtocol.CloseCodePolicyViolated, "bad token")
                continue
            self._clients.append(client)
            client.textMessageReceived.connect(lambda text, c=client: self._on_text(c, text))
            client.disconnected.connect(lambda c=client: self._on_disconnected(c))
            self.client_connected.emit(client)

    def _token_matches(self, client) -> bool:
        given = QUrlQuery(client.requestUrl()).queryItemValue("token")
        return secrets.compare_digest(given.encode("utf-8"), self._token.encode("utf-8"))

    def _on_text(self, client, text):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"[WebSocket] 웹 보고서가 보낸 글을 JSON으로 읽지 못함: {e}")
            return
        if not isinstance(data, dict):
            print(f"[WebSocket] 웹 보고서가 보낸 JSON이 객체가 아님: {type(data).__name__}")
            return
        self.message_received.emit(client, data)

    def _on_disconnected(self, client):
        if client in self._clients:
            self._clients.remove(client)
        client.deleteLater()
