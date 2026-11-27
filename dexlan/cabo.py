"""Ligação directa por cabo de rede (RJ45) entre os dois computadores.

Usa um perfil do NetworkManager chamado "DexLan-cabo":
  - automático: endereço 169.254.x.y escolhido sozinho (link-local)
  - manual: IP e máscara definidos pelo utilizador

O perfil nunca vira a rota principal, por isso o Wi-Fi continua a dar internet.
"""
import getpass
import ipaddress
import json
import os
import shutil
import subprocess
import threading
import time

from . import seguranca

PERFIL = "DexLan-cabo"
TYPES = tuple(os.environ.get("DEXLAN_CABLE_TYPES", "ethernet").split(","))
ESPERA_DHCP = 8  # segundos sem endereço antes de assumir cabo directo
PADRAO = {"ativo": True, "modo": "auto", "endereco": "192.168.50.1", "mascara": "255.255.255.0"}


class ErroCabo(RuntimeError):
    pass


# ---------- definições

def _ficheiro_definicoes():
    return os.path.join(seguranca.pasta_config(), "cabo.json")


def definicoes():
    try:
        with open(_ficheiro_definicoes()) as f:
            return {**PADRAO, **json.load(f)}
    except (OSError, ValueError):
        return dict(PADRAO)


def guardar_definicoes(**mudancas):
    cfg = {**definicoes(), **mudancas}
    if cfg["modo"] == "manual":
        validar_endereco(cfg["endereco"], cfg["mascara"])
    with open(_ficheiro_definicoes(), "w") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def validar_endereco(endereco, mascara):
    """Valida IP e máscara. Devolve o prefixo (ex.: 24)."""
    try:
        ip = ipaddress.IPv4Address(endereco)
    except ValueError:
        raise ErroCabo(f"IP inválido: {endereco}")
    try:
        prefixo = ipaddress.IPv4Network(f"0.0.0.0/{mascara}").prefixlen
    except ValueError:
        raise ErroCabo(f"máscara inválida: {mascara}")
    net = ipaddress.IPv4Network(f"{endereco}/{prefixo}", strict=False)
    if prefixo < 31 and ip in (net.network_address, net.broadcast_address):
        raise ErroCabo("esse IP é o endereço de rede ou de broadcast, escolhe outro")
    return prefixo


def e_link_local(ip):
    try:
        return ipaddress.ip_address(ip).is_link_local
    except ValueError:
        return False


# ---------- NetworkManager

def _nmcli(*args, check=True, timeout=30):
    try:
        r = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise ErroCabo("NetworkManager (nmcli) não está instalado")
    except subprocess.TimeoutExpired:
        raise ErroCabo("o NetworkManager não respondeu")
    if check and r.returncode != 0:
        raise ErroCabo((r.stderr or r.stdout).strip() or "erro no nmcli")
    return r.stdout


def disponivel():
    if not shutil.which("nmcli"):
        return False, "NetworkManager não encontrado"
    try:
        if _nmcli("-t", "-f", "RUNNING", "general", timeout=5).strip() != "running":
            return False, "o NetworkManager não está a correr"
    except ErroCabo as e:
        return False, str(e)
    return True, "ok"


def _tem_cabo(dev):
    try:
        with open(f"/sys/class/net/{dev}/carrier") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def _ipv4(dev):
    out = _nmcli("-g", "IP4.ADDRESS", "device", "show", dev, check=False, timeout=5)
    return [a for a in out.replace("|", "\n").split() if "." in a]  # com prefixo: 1.2.3.4/24


def placas():
    out = _nmcli("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", timeout=5)
    found = []
    for line in out.splitlines():
        parts = line.replace("\\:", "\0").split(":")
        if len(parts) < 4:
            continue
        dev, kind, state, conn = (p.replace("\0", ":") for p in parts[:4])
        if kind in TYPES and state != "unmanaged":
            found.append({"placa": dev, "cabo_ligado": _tem_cabo(dev), "estado": state,
                          "ligacao": conn, "ipv4": _ipv4(dev), "dexlan": conn == PERFIL})
    return found


def estado():
    ok, why = disponivel()
    cfg = definicoes()
    if not ok:
        return {"disponivel": False, "motivo": why, "placas": [], "activa": None, "definicoes": cfg}
    devs = placas()
    active = next((d for d in devs if d["dexlan"] and d["ipv4"]), None)
    return {"disponivel": True, "motivo": why, "placas": devs, "activa": active, "definicoes": cfg}


def perfil_existe():
    out = _nmcli("-t", "-f", "NAME", "connection", "show", check=False, timeout=5)
    return PERFIL in out.splitlines()


def _opcoes_perfil(dev, cfg):
    common = ["connection.interface-name", dev, "connection.autoconnect", "no",
              "connection.permissions", f"user:{getpass.getuser()}",
              "ipv4.never-default", "yes", "ipv6.method", "link-local", "ipv6.never-default", "yes"]
    if cfg["modo"] == "manual":
        prefix = validar_endereco(cfg["endereco"], cfg["mascara"])
        return common + ["ipv4.method", "manual", "ipv4.addresses", f"{cfg['endereco']}/{prefix}"]
    return common + ["ipv4.method", "link-local", "ipv4.addresses", ""]


def ativar(dev, wait=20):
    """Liga o modo cabo na placa 'dev' e devolve o IP obtido."""
    cfg = definicoes()
    args = _opcoes_perfil(dev, cfg)
    if perfil_existe():
        _nmcli("connection", "modify", PERFIL, *args)
    else:
        _nmcli("connection", "add", "type", "ethernet", "con-name", PERFIL, "ifname", dev, *args)
    _nmcli("connection", "up", PERFIL, "ifname", dev, timeout=wait + 15)
    end = time.time() + wait
    while time.time() < end:
        for addr in _ipv4(dev):
            ip = addr.split("/")[0]
            if cfg["modo"] == "manual" and ip == cfg["endereco"]:
                return addr
            if cfg["modo"] == "auto" and e_link_local(ip):
                return addr
        time.sleep(0.5)
    raise ErroCabo("o perfil ligou mas não obteve endereço")


def reaplicar():
    """Aplica as definições já, se o cabo estiver ligado."""
    st = estado()
    dev = (st["activa"] or next((d for d in st["placas"] if d["cabo_ligado"]), None) or {}).get("placa")
    if not dev:
        return None
    return ativar(dev)


def desativar():
    _nmcli("connection", "down", PERFIL, check=False)


def remover():
    if shutil.which("nmcli") and perfil_existe():
        _nmcli("connection", "delete", PERFIL, check=False)


def descrever(st):
    if not st["disponivel"]:
        return f"Indisponível: {st['motivo']}"
    if st["activa"]:
        return f"Ligado por cabo em {st['activa']['placa']}"
    if not st["placas"]:
        return "Este computador não tem placa de rede com fio"
    plugged = [d for d in st["placas"] if d["cabo_ligado"]]
    if not plugged:
        return "Cabo desligado"
    if any(d["ipv4"] for d in plugged):
        return "Cabo ligado a uma rede com router"
    if not st["definicoes"]["ativo"]:
        return "Cabo ligado (configuração automática desligada)"
    return "Cabo ligado, a configurar…"


class CaboAutomatico(threading.Thread):
    """Vigia o cabo e liga o perfil quando há cabo mas ninguém dá endereço."""

    def __init__(self, on_change=None, interval=2.0):
        super().__init__(daemon=True)
        self.on_change = on_change
        self.interval = interval
        self._desde = {}
        self._failed = set()
        self._last = None
        self.wake = threading.Event()

    def run(self):
        while True:
            try:
                st = estado()
                if st["disponivel"] and st["definicoes"]["ativo"]:
                    self._talvez_ativar(st)
                    st = estado()
                self._emit(st)
            except ErroCabo:
                pass
            self.wake.wait(self.interval)
            self.wake.clear()

    def _talvez_ativar(self, st):
        now = time.time()
        for d in st["placas"]:
            dev = d["placa"]
            if not d["cabo_ligado"]:
                self._desde.pop(dev, None)
                self._failed.discard(dev)
            elif d["ipv4"] or dev in self._failed:
                self._desde.pop(dev, None)
            elif now - self._desde.setdefault(dev, now) >= ESPERA_DHCP:
                try:
                    ativar(dev)
                except ErroCabo:
                    self._failed.add(dev)
                self._desde.pop(dev, None)

    def _emit(self, st):
        key = json.dumps([st["disponivel"], st["definicoes"],
                          [(d["placa"], d["cabo_ligado"], d["ipv4"]) for d in st["placas"]]])
        if key != self._last:
            self._last = key
            if self.on_change:
                self.on_change(st)

    def atualizar(self):
        self._last = None
        self.wake.set()
