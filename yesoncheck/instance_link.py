"""창 사이 연결: 다른 YesonCheck 창(프로세스)이 이 창의 상태를 묻고 정상 종료를 요청 (QLocalServer·QLocalSocket).

- 서버(InstanceServer): 창마다 하나, 이름 `yesoncheck-{사용자}-{pid}`. 사용자 부분은 ASCII — Mac은 uid, Windows는
  사용자 이름(USERNAME)의 sha1 앞 8자리(Windows의 이름은 이름 있는 파이프 \\\\.\\pipe\\… — 한글 이름도 짧은 ASCII로).
  이 사용자만 접속할 수 있게(UserAccessOption). Mac은 죽은 창이 남긴 소켓 파일을 듣기 전에 지움.
- 규약: 한 줄에 JSON 하나(UTF-8). `{"op":"status"}` → `{"ok":true,"status":{…}}`, `{"op":"close"}` → `{"ok":true}`
  뒤 이벤트 루프에서 close_handler(닫기 버튼과 같은 정상 종료). 알 수 없는 요청은 `{"ok":false,"error":…}`.
- 클라이언트(query_status·request_close): 기다리는 함수 — 업데이트하는 창의 GUI 스레드에서 창 몇 개에 차례로 부름.
  연결·보내기·답 받기를 합쳐 timeout_ms 안에 끝나고, 답이 없으면(GUI 스레드가 멈춘 창 등) InstanceLinkError.
"""

import hashlib
import json
import os
import sys
import time
from collections.abc import Callable

from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

_MAX_LINE_BYTES = 1024 * 1024  # 요청 한 줄의 최대 크기 (넘으면 끊음)


class InstanceLinkError(Exception):
    """다른 창에 연결하지 못했거나, 정해진 시간 안에 답하지 않았거나, 오류로 답함."""


def _user_tag() -> str:
    if sys.platform == "win32":
        return hashlib.sha1(os.environ["USERNAME"].casefold().encode("utf-8")).hexdigest()[:8]
    return str(os.getuid())


def server_name(pid: int | None = None) -> str:
    """창의 서버 이름 `yesoncheck-{사용자}-{pid}` (pid를 주지 않으면 이 프로세스)."""
    return f"yesoncheck-{_user_tag()}-{os.getpid() if pid is None else pid}"


class InstanceServer(QObject):
    """이 창의 서버: status_provider()로 상태를 답하고, 닫기 요청에는 답한 뒤 close_handler()를 부름."""

    def __init__(self, status_provider: Callable[[], dict], close_handler: Callable[[], None], parent=None):
        super().__init__(parent)
        self._status_provider = status_provider
        self._close_handler = close_handler
        self._server = None

    def start(self) -> str:
        """듣기를 시작하고 접속할 전체 이름(Mac 소켓 파일 경로, Windows \\\\.\\pipe\\…)을 돌려줌.
        듣지 못하면 InstanceLinkError (Qt가 알려 준 이유)."""
        if self._server is not None:
            raise RuntimeError("이미 듣고 있습니다")
        name = server_name()
        QLocalServer.removeServer(name)  # Mac: 같은 pid였던 죽은 창이 남긴 소켓 파일 (Windows는 할 일 없음)
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.UserAccessOption)
        if not server.listen(name):
            reason = server.errorString()
            server.deleteLater()
            raise InstanceLinkError(f"창 사이 연결 서버를 열지 못했습니다 ({name}): {reason}")
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return server.fullServerName()

    def close(self):
        """듣기를 멈춤 (Mac 소켓 파일도 지움). 시작하지 않았거나 이미 닫았으면 아무것도 안 함."""
        server, self._server = self._server, None
        if server is not None:
            server.close()

    def _on_new_connection(self):
        while self._server is not None and self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            buffer = bytearray()
            socket.readyRead.connect(lambda s=socket, b=buffer: self._on_ready_read(s, b))
            socket.disconnected.connect(socket.deleteLater)

    def _on_ready_read(self, socket, buffer):
        buffer += bytes(socket.readAll())
        while True:
            end = buffer.find(b"\n")
            if end < 0:
                if len(buffer) > _MAX_LINE_BYTES:
                    print(f"[창 연결] 요청이 너무 깁니다 ({len(buffer)}바이트) — 연결을 끊음", flush=True)
                    socket.abort()
                return
            line = bytes(buffer[:end])
            del buffer[:end + 1]
            self._handle(socket, line)

    def _handle(self, socket, line):
        try:
            request = json.loads(line.decode("utf-8"))
            op = request["op"]
        except (ValueError, KeyError, TypeError) as exc:  # ValueError: UnicodeDecodeError·JSONDecodeError
            op = None
            problem = f"{type(exc).__name__}: {exc}"
        else:
            problem = None
        if op == "status":
            try:
                status = self._status_provider()
            except Exception as exc:
                # 묻는 창에는 오류로 답하고, 이 창에서는 그대로 올림 (excepthook — 오류 창·기록)
                self._reply(socket, {"ok": False, "error": f"상태를 만들지 못했습니다: {type(exc).__name__}: {exc}"})
                raise
            self._reply(socket, {"ok": True, "status": status})
        elif op == "close":
            print("[창 연결] 다른 창의 업데이트가 이 창을 닫습니다", flush=True)
            self._reply(socket, {"ok": True})
            QTimer.singleShot(0, self._close_handler)
        else:
            error = f"알 수 없는 요청: {line[:200].decode('utf-8', 'replace')}"
            if problem:
                error += f" ({problem})"
            print(f"[창 연결] {error}", flush=True)
            self._reply(socket, {"ok": False, "error": error})

    @staticmethod
    def _reply(socket, message):
        socket.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        socket.flush()


def query_status(server_name: str, timeout_ms: int = 3000) -> dict:
    """그 창의 상태(VideoPlayer.instance_status). 답이 없거나 오류면 InstanceLinkError."""
    status = _request(server_name, {"op": "status"}, timeout_ms).get("status")
    if not isinstance(status, dict):
        raise InstanceLinkError(f"창이 상태 대신 다른 것을 답했습니다 ({server_name}): {status!r}")
    return status


def request_close(server_name: str, timeout_ms: int = 3000) -> None:
    """그 창에 정상 종료(닫기 버튼과 같음)를 요청 — 창이 받았다고 답하면 돌아옴 (닫히기를 기다리지는 않음)."""
    _request(server_name, {"op": "close"}, timeout_ms)


def _request(server_name, request, timeout_ms):
    """요청 한 줄을 보내고 답 한 줄을 받음 — 모두 합쳐 timeout_ms 안에. ok가 아니면 InstanceLinkError."""
    deadline = time.monotonic() + timeout_ms / 1000

    def remaining_ms():
        return max(0, int((deadline - time.monotonic()) * 1000))

    def no_answer(socket):
        return InstanceLinkError(
            f"창이 {timeout_ms / 1000:g}초 안에 답하지 않았습니다 ({server_name}): {socket.errorString()}")

    socket = QLocalSocket()
    try:
        socket.connectToServer(server_name)
        if not socket.waitForConnected(remaining_ms()):
            raise InstanceLinkError(f"창에 연결하지 못했습니다 ({server_name}): {socket.errorString()}")
        if socket.write(json.dumps(request).encode("utf-8") + b"\n") < 0:
            raise InstanceLinkError(f"창에 요청을 보내지 못했습니다 ({server_name}): {socket.errorString()}")
        while socket.bytesToWrite() > 0:
            wait_ms = remaining_ms()  # 0이면 기다리지 않음 (-1을 넘기면 끝없이 기다림)
            if wait_ms <= 0 or not socket.waitForBytesWritten(wait_ms):
                raise no_answer(socket)
        data = bytearray()
        while b"\n" not in data:
            if socket.bytesAvailable() == 0:
                wait_ms = remaining_ms()
                if wait_ms <= 0 or not socket.waitForReadyRead(wait_ms):
                    data += bytes(socket.readAll())  # 끊기며 함께 온 답 (있으면)
                    if b"\n" in data:
                        break
                    raise no_answer(socket)
            data += bytes(socket.readAll())
    finally:
        socket.abort()
    line = bytes(data[:data.index(b"\n")])
    try:
        reply = json.loads(line.decode("utf-8"))
    except ValueError as exc:
        raise InstanceLinkError(f"창의 답을 읽지 못했습니다 ({server_name}): {line[:200]!r}") from exc
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        error = reply.get("error") if isinstance(reply, dict) else None
        raise InstanceLinkError(f"창이 오류로 답했습니다 ({server_name}): {error or reply!r}")
    return reply
