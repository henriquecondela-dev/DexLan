"""Mensagens entre host e receiver numa ligação TLS.

Cada mensagem: tipo (1 byte) + tamanho (4 bytes) + dados
  b'J' controlo, dados em JSON
  b'V' vídeo, 8 bytes de tempo (µs) + H.264
"""
import json
import socket
import struct
import threading

HEADER = struct.Struct(">cI")
MAX_FRAME = 16 * 1024 * 1024


class ProtocolError(Exception):
    pass


class Canal:
    def __init__(self, sock):
        self.sock = sock
        self._lock = threading.Lock()

    def _send(self, kind, payload):
        with self._lock:
            self.sock.sendall(HEADER.pack(kind, len(payload)) + payload)

    def enviar_json(self, **msg):
        self._send(b"J", json.dumps(msg).encode())

    def enviar_video(self, pts_us, data):
        self._send(b"V", struct.pack(">Q", pts_us) + data)

    def _receber_exato(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("ligação fechada")
            buf += chunk
        return bytes(buf)

    def receber(self):
        """Devolve ("json", dict) ou ("video", (pts_us, bytes))."""
        kind, size = HEADER.unpack(self._receber_exato(HEADER.size))
        if size > MAX_FRAME:
            raise ProtocolError("mensagem demasiado grande")
        payload = self._receber_exato(size)
        if kind == b"J":
            return "json", json.loads(payload)
        if kind == b"V":
            return "video", (struct.unpack(">Q", payload[:8])[0], payload[8:])
        raise ProtocolError(f"tipo desconhecido: {kind!r}")

    def receber_json(self, expect=None):
        kind, msg = self.receber()
        if kind != "json":
            raise ProtocolError("esperava uma mensagem de controlo")
        if expect and msg.get("t") != expect:
            raise ProtocolError(f"esperava '{expect}', chegou '{msg.get('t')}'")
        return msg

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
