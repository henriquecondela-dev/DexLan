"""Descoberta de receivers por broadcast UDP (porta 47800).

O host envia "discover" para a rede e cada receiver responde com o nome e o id.
Não usa Avahi para não depender de mais um serviço.
"""
import ipaddress
import json
import socket
import subprocess
import threading
import time

from . import APP_ID, DISCOVERY_PORT, PROTOCOL_VERSION

PROBE = json.dumps({"app": APP_ID, "t": "discover", "v": PROTOCOL_VERSION}).encode()


class Respondedor(threading.Thread):
    """Corre no receiver e responde aos pedidos de descoberta."""

    def __init__(self, info, port=DISCOVERY_PORT):
        super().__init__(daemon=True)
        self.info = info
        self.port = port

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.port))
        while True:
            try:
                data, addr = sock.recvfrom(2048)
                msg = json.loads(data)
                if msg.get("app") == APP_ID and msg.get("t") == "discover":
                    reply = dict(self.info(), app=APP_ID, t="announce", v=PROTOCOL_VERSION)
                    sock.sendto(json.dumps(reply).encode(), addr)
            except (ValueError, OSError):
                continue


def enderecos_broadcast():
    addresses = {"255.255.255.255"}
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            if "brd" in parts:
                addresses.add(parts[parts.index("brd") + 1])
    except OSError:
        pass
    return addresses


def procurar(timeout=2.0, port=DISCOVERY_PORT, extra_targets=()):
    """Devolve [{name, id, ip, ips, port}]. 'ips' tem todos os endereços que responderam."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", 0))
    sock.settimeout(0.2)
    targets = list(enderecos_broadcast()) + list(extra_targets)
    found = {}
    end = time.time() + timeout
    next_probe = 0.0
    while time.time() < end:
        if time.time() >= next_probe:
            for target in targets:
                try:
                    sock.sendto(PROBE, (target, port))
                except OSError:
                    pass
            next_probe = time.time() + 0.7
        try:
            data, addr = sock.recvfrom(2048)
            msg = json.loads(data)
        except (socket.timeout, ValueError):
            continue
        except OSError:
            break
        if msg.get("app") != APP_ID or msg.get("t") != "announce":
            continue
        entry = found.setdefault(msg.get("id", addr[0]), dict(msg, ips=[]))
        if addr[0] not in entry["ips"]:
            entry["ips"].append(addr[0])
        # o mesmo receiver pode responder pelo Wi-Fi e pelo cabo: preferir o cabo
        link_local = [ip for ip in entry["ips"] if ipaddress.ip_address(ip).is_link_local]
        entry["ip"] = (link_local or entry["ips"])[0]
    sock.close()
    return list(found.values())
