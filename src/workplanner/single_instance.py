"""Nur eine laufende Instanz: ein zweiter Start holt die erste nach vorn und beendet sich."""
from __future__ import annotations

from typing import Callable

from PySide6.QtNetwork import QLocalServer, QLocalSocket

NAME = "WorkPlanner-single-instance"


def notify_running_instance(name: str = NAME) -> bool:
    """True, wenn bereits eine Instanz läuft (sie wurde aufgefordert, ihr Fenster zu zeigen)."""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(300):
        return False
    sock.write(b"show")
    sock.waitForBytesWritten(300)
    sock.waitForReadyRead(1000)  # auf die Bestätigung warten, sonst kann die Meldung beim Trennen verloren gehen
    sock.disconnectFromServer()
    return True


class InstanceServer:
    """Lauscht auf „show“ von später gestarteten Instanzen und ruft `on_show` auf."""

    def __init__(self, on_show: Callable[[], None], name: str = NAME):
        self._on_show = on_show
        self._socks: list[QLocalSocket] = []  # Verbindungen gehören dem Server (Qt); hier nur Verweise
        QLocalServer.removeServer(name)  # Überbleibsel eines abgestürzten Starts entfernen
        self.server = QLocalServer()
        self.listening = self.server.listen(name)
        self.server.newConnection.connect(self._connection)

    def _connection(self) -> None:
        sock = self.server.nextPendingConnection()
        if sock is None:
            return
        self._socks.append(sock)
        sock.readyRead.connect(self._ready)
        sock.disconnected.connect(self._gone)
        self._ready()  # die Nachricht kann schon da sein, bevor das Signal verbunden war

    def _ready(self) -> None:
        for sock in self._socks:
            if sock.bytesAvailable():
                sock.readAll()
                self._on_show()
                sock.write(b"ok")
                sock.flush()

    def _gone(self) -> None:
        self._socks = [s for s in self._socks if s.state() != QLocalSocket.UnconnectedState]

    def close(self) -> None:
        for sock in self._socks:
            sock.abort()
        self._socks.clear()
        self.server.close()
