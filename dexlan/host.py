"""Motor do host: liga ao receiver, cria o ecrã virtual, envia o vídeo e limpa no fim.

Comunica através de EventosHost, por isso serve tanto o terminal (EventosTerminal)
como a janela (ui/host_app.py).
"""
import os
import queue
import signal
import socket
import sys
import threading
import time
from dataclasses import dataclass

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

from . import CONTROL_PORT, PROTOCOL_VERSION  # noqa: E402
from . import descoberta, ecra, ambiente, seguranca, video  # noqa: E402
from .protocolo import Canal  # noqa: E402


class ErroAutenticacao(Exception):
    pass


class Cancelado(ErroAutenticacao):
    pass


@dataclass
class OpcoesHost:
    resolution: str = "auto"   # auto = ecrã do receiver, ou LARGURAxALTURA
    fps: int = 30
    bitrate: int = 6000        # kbit/s
    position: str = "right"
    backend: str | None = None
    hw: bool = False
    grace: int = 30            # segundos à espera de religar
    max_queue: int = 6


class EventosHost:
    """O que o motor comunica para fora."""

    def log(self, msg): ...
    def state(self, state, detail=""): ...       # connecting|pairing|starting|active|reconnecting|stopped
    def stats(self, s: dict): ...               # {fps, kbps, rtt_ms, dropped, connected}
    def stopped(self, reason, error=False): ...

    def ask_pin(self, receiver_ip, attempts_left):
        """Devolve o código ou None para cancelar (corre numa thread)."""
        return None


# ---------------------------------------------------------------- ligação
def ligar_e_autenticar(ip, port, ask_pin=None, interactive=True, timeout=5):
    """Liga ao receiver e autentica. Devolve (canal, mensagem welcome)."""
    ident = seguranca.identidade()
    known = seguranca.ReceiversConhecidos()
    raw = socket.create_connection((ip, port), timeout=timeout)
    tls = seguranca.contexto_cliente().wrap_socket(raw)
    fp = seguranca.impressao_der(tls.getpeercert(binary_form=True))
    tls.settimeout(180 if interactive else 10)
    ch = Canal(tls)

    entry_id, entry = next(((k, v) for k, v in known.data.items() if v["fingerprint"] == fp),
                           (None, None))
    ch.enviar_json(t="hello", v=PROTOCOL_VERSION, id=ident["id"], name=ident["name"],
                 token=entry["token"] if entry else None)
    msg = ch.receber_json()
    if msg.get("t") in ("busy", "error"):
        ch.close()
        raise ErroAutenticacao(msg.get("msg", msg["t"]))

    token = entry["token"] if entry else None
    if msg.get("t") == "pair_required":
        if not interactive or ask_pin is None:
            ch.close()
            raise ErroAutenticacao("o receiver pede novo emparelhamento (PIN)")
        left = 3
        while True:
            pin = ask_pin(ip, left)
            if pin is None:
                ch.close()
                raise Cancelado("emparelhamento cancelado")
            ch.enviar_json(t="pair", proof=seguranca.prova_codigo(pin.strip(), msg["nonce"], fp))
            r = ch.receber_json()
            if r.get("t") == "paired":
                token = r["token"]
                break
            left = r.get("left", 0)
            if left <= 0:
                ch.close()
                raise ErroAutenticacao("código errado 3 vezes; o receiver recusou a ligação")
        msg = ch.receber_json()

    if msg.get("t") != "welcome":
        ch.close()
        raise ErroAutenticacao(f"resposta inesperada: {msg.get('t')}")
    if entry_id and entry_id != msg["id"]:
        known.revogar(entry_id)
    known.add(msg["id"], msg["name"], fp, token)
    tls.settimeout(10)
    return ch, msg


# ---------------------------------------------------------------- sessão
class SessaoHost:
    def __init__(self, opts: OpcoesHost, env, events: EventosHost):
        self.opts = opts
        self.env = env
        self.ev = events
        self.backend = ecra.escolher(env, opts.backend)
        self.ch = None
        self.addr = None
        self.welcome = None
        self.pipeline = None
        self.ecra = None
        self.q = queue.Queue(maxsize=opts.max_queue)
        self.waiting_key = True
        self.running = False
        self.finished = False
        self.sent = self.sent_bytes = self.dropped = 0
        self.rtt_ms = None
        self.reconnect_deadline = None
        self._tick_id = None
        self._ticks = 0

    # ---------- autenticar (bloqueante)
    def autenticar(self, addr):
        self.addr = addr
        self.ev.state("connecting", f"{addr[0]}")
        self.ch, self.welcome = ligar_e_autenticar(*addr, ask_pin=self._ask_pin)
        return self.welcome

    def _ask_pin(self, ip, left):
        self.ev.state("pairing", ip)
        return self.ev.ask_pin(ip, left)

    # ---------- arrancar (thread principal)
    def iniciar(self):
        w, h = self.resolucao()
        spec = ecra.EspecEcra(w, h, self.opts.fps, self.opts.position)
        self.ecra = self.backend(spec)
        self.running = True
        self.ev.state("starting", self.ecra.descrever())
        try:
            self.ecra.criar(lambda src: GLib.idle_add(self._start_pipeline, src))
        except Exception:
            self._cleanup()
            raise
        threading.Thread(target=self._sender, daemon=True).start()
        threading.Thread(target=self._reader, args=(self.ch,), daemon=True).start()
        self._tick_id = GLib.timeout_add(1000, self._tick)

    def resolucao(self):
        if self.opts.resolution == "auto":
            w, h = self.welcome["screen"]
            if w * h > 1920 * 1080:
                w, h = 1920, int(1920 * h / w)
        else:
            w, h = map(int, self.opts.resolution.lower().split("x"))
        return w - w % 2, h - h % 2

    def _start_pipeline(self, src):
        if not self.running:
            return False
        s = self.ecra.spec
        try:
            enc, desc = video.pipeline_host(src, s.width, s.height, s.fps, self.opts.bitrate,
                                             self.opts.hw)
            self.pipeline = Gst.parse_launch(desc)
        except Exception as e:  # noqa: BLE001
            self.parar(f"não foi possível iniciar o vídeo: {e}", error=True)
            return False
        self.ev.log(f"codificador: {enc} · {self.opts.bitrate} kbit/s")
        self.pipeline.get_by_name("sink").connect("new-sample", self._on_sample)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        self.pipeline.set_state(Gst.State.PLAYING)
        self._send_start()
        threading.Thread(target=self._position, daemon=True).start()
        return False

    def _position(self):
        time.sleep(1.5)
        ok, msg = self.ecra.aplicar_posicao()
        self.ev.log(("✔ " if ok else "⚠ ") + msg)
        if self.running:
            GLib.idle_add(self.ev.state, "active", self.ecra.descrever())

    def _send_start(self):
        s = self.ecra.spec
        if self.ch:
            self.ch.enviar_json(t="start", w=s.width, h=s.height, fps=s.fps)
            self.waiting_key = True
            if self.pipeline:
                video.pedir_keyframe(self.pipeline)

    def _on_error(self, _bus, msg):
        err, dbg = msg.parse_error()
        self.ev.log(f"erro no pipeline: {err.message}\n{dbg}")
        self.parar(f"erro no vídeo: {err.message}", error=True)

    # ---------- vídeo
    def _on_sample(self, sink):
        sample = sink.emit("pull-sample")
        buf = sample.get_buffer()
        is_key = not buf.has_flags(Gst.BufferFlags.DELTA_UNIT)
        if self.ch is None:  # a religar: descartar
            self.waiting_key = True
            return Gst.FlowReturn.OK
        if self.waiting_key and not is_key:
            self.dropped += 1
            return Gst.FlowReturn.OK
        ok, info = buf.map(Gst.MapFlags.READ)
        data = bytes(info.data)
        buf.unmap(info)
        try:
            self.q.put_nowait((buf.pts // 1000 if buf.pts != Gst.CLOCK_TIME_NONE else 0, data))
            self.waiting_key = False
        except queue.Full:
            # a rede não acompanha: descartar até à próxima keyframe e pedir uma
            self.dropped += 1
            self.waiting_key = True
            video.pedir_keyframe(self.pipeline)
        return Gst.FlowReturn.OK

    def _sender(self):
        while self.running:
            try:
                pts, data = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            ch = self.ch
            if ch is None:
                continue
            try:
                ch.enviar_video(pts, data)
                self.sent += 1
                self.sent_bytes += len(data)
            except OSError:
                self._connection_lost(ch, "falha ao enviar")

    def _reader(self, ch):
        try:
            while self.running and ch is self.ch:
                kind, msg = ch.receber()
                if kind != "json":
                    continue
                t = msg.get("t")
                if t == "pong" and msg.get("ts"):
                    self.rtt_ms = (time.monotonic() - msg["ts"]) * 1000
                elif t == "ready" and self.pipeline:
                    video.pedir_keyframe(self.pipeline)
                elif t == "bye":
                    self.parar("o receiver fechou a ligação")
                    return
        except (OSError, ValueError, ConnectionError) as e:
            self._connection_lost(ch, str(e) or e.__class__.__name__)

    # ---------- falhas de rede e reconexão
    def _connection_lost(self, ch, why):
        if ch is not self.ch or not self.running:
            return
        self.ch = None
        try:
            ch.close()
        except OSError:
            pass
        self.reconnect_deadline = time.monotonic() + self.opts.grace
        self.ev.log(f"⚠ ligação perdida ({why}); o monitor fica activo {self.opts.grace}s")
        GLib.idle_add(self.ev.state, "reconnecting", why)
        threading.Thread(target=self._reconnect, daemon=True).start()

    def _reconnect(self):
        while self.running and time.monotonic() < self.reconnect_deadline:
            time.sleep(2)
            try:
                ch, _ = ligar_e_autenticar(*self.addr, interactive=False, timeout=3)
            except ErroAutenticacao as e:
                self.ev.log(f"religação recusada: {e}")
                break
            except OSError:
                continue
            with self.q.mutex:
                self.q.queue.clear()
            self.ch = ch
            self._send_start()
            threading.Thread(target=self._reader, args=(ch,), daemon=True).start()
            self.ev.log("✔ religado ao receiver")
            GLib.idle_add(self.ev.state, "active", self.ecra.descrever())
            return
        if self.running:
            self.parar("o receiver deixou de responder", error=True)

    # ---------- estatísticas
    def _tick(self):
        ch = self.ch
        if ch:
            try:
                ch.enviar_json(t="ping", ts=time.monotonic())
            except OSError:
                pass
        self._ticks += 1
        if self._ticks % 2 == 0:
            self.ev.stats({"fps": self.sent / 2, "kbps": self.sent_bytes * 8 / 2000,
                           "rtt_ms": self.rtt_ms, "dropped": self.dropped,
                           "connected": ch is not None})
            self.sent = self.sent_bytes = 0
        return self.running

    # ---------- parar (pode ser chamado de qualquer thread)
    def parar(self, why="pedido do utilizador", error=False):
        GLib.idle_add(self._do_stop, why, error)

    def _do_stop(self, why, error):
        if self.finished:
            return False
        # limpar primeiro e só depois avisar: um aviso que falhe não pode impedir a limpeza
        self._cleanup()
        for fn, a in ((self.ev.log, (f"terminado ({why})",)), (self.ev.state, ("stopped", why)),
                      (self.ev.stopped, (why, error))):
            _safe(fn, *a)
        return False

    def _cleanup(self):
        if self.finished:
            return
        self.finished = True
        self.running = False
        steps = []
        if self._tick_id:
            steps.append(lambda: GLib.source_remove(self._tick_id))
        if self.ch:
            ch = self.ch
            steps += [lambda: ch.enviar_json(t="bye"), ch.close]
        if self.pipeline:
            steps.append(lambda: self.pipeline.set_state(Gst.State.NULL))
        if self.ecra:
            steps.append(self.ecra.destruir)
        for step in steps:
            _safe(step)
        self._tick_id = self.ch = self.pipeline = None
        if self.ecra:
            _safe(self.ev.log, "✔ monitor virtual removido — configuração original reposta")


def _safe(fn, *a):
    try:
        fn(*a)
    except Exception as e:  # noqa: BLE001
        try:
            print(f"[host] aviso: {e}", file=sys.stderr, flush=True)
        except Exception:  # noqa: BLE001
            pass


# ================================================================ terminal
def _print(msg, end="\n"):
    try:
        print(f"\r\033[K[host] {msg}", end=end, flush=True)
    except (OSError, ValueError):
        pass


class EventosTerminal(EventosHost):
    def __init__(self, first_pin=None):
        self.first_pin = first_pin
        self.ao_parar = None

    def log(self, msg):
        _print(msg)

    def state(self, state, detail=""):
        text = {"connecting": f"a ligar a {detail}...",
                "starting": f"a criar monitor virtual {detail}...",
                "active": "✔ monitor virtual activo — arrasta janelas para ele. Ctrl+C para terminar.",
                "reconnecting": "a tentar religar..."}.get(state)
        if text:
            _print(text)

    def stats(self, s):
        rtt = f"{s['rtt_ms']:.1f} ms" if s["rtt_ms"] is not None else "—"
        _print(f"{'ligado' if s['connected'] else 'a religar'} · {s['fps']:.0f} fps · "
               f"{s['kbps']:.0f} kbit/s · RTT {rtt} · descartados {s['dropped']}", end="")

    def stopped(self, reason, error=False):
        if self.ao_parar:
            self.ao_parar()

    def ask_pin(self, ip, left):
        if left < 3:
            print(f"  ✘ PIN errado. Tentativas restantes: {left}")
        else:
            print(f"\n  O receiver em {ip} está a mostrar um PIN de 6 dígitos no ecrã.")
        if self.first_pin:
            pin, self.first_pin = self.first_pin, None
            return pin
        try:
            return input("  Escreve o PIN: ")
        except EOFError:
            return None


def escolher_receiver(args):
    if args.connect:
        ip, _, port = args.connect.partition(":")
        return ip, int(port or CONTROL_PORT)
    _print("à procura de receivers na rede local...")
    found = descoberta.procurar(timeout=args.discover_timeout)
    if not found:
        raise SystemExit(
            "Nenhum receiver encontrado.\n"
            "  • O receiver está aberto no outro computador? ('dexlan receiver')\n"
            "  • Os dois estão na mesma rede?  • Firewall? (UDP 47800, TCP 47801)\n"
            "  • Tenta ligar directamente:  dexlan host --connect IP_DO_RECEIVER")
    if len(found) == 1 or args.yes:
        r = found[0]
    else:
        print("\nReceivers encontrados:")
        for i, r in enumerate(found, 1):
            print(f"  {i}) {r['name']}  ({r['ip']})")
        r = found[int(input("Escolhe o número: ")) - 1]
    _print(f"receiver: {r['name']} ({r['ip']})")
    return r["ip"], int(r.get("port", CONTROL_PORT))


def opcoes_dos_args(args) -> OpcoesHost:
    return OpcoesHost(resolution=args.resolution, fps=args.fps, bitrate=args.bitrate,
                       position=args.position, backend=args.backend, hw=args.hw,
                       grace=args.grace, max_queue=args.max_queue)


def main(args):
    Gst.init(None)
    env = ambiente.detectar()
    _print(env.resumo())
    events = EventosTerminal(first_pin=args.pin)
    loop = GLib.MainLoop()
    events.ao_parar = loop.quit
    try:
        session = SessaoHost(opcoes_dos_args(args), env, events)
        _print(f"backend de monitor virtual: {session.backend.name} — {session.backend.description}")
        addr = escolher_receiver(args)
        welcome = session.autenticar(addr)
        _print(f"autenticado com '{welcome['name']}' (ecrã {welcome['screen'][0]}x{welcome['screen'][1]})")
        session.iniciar()
        presses = {"n": 0}

        def on_signal():
            presses["n"] += 1
            if presses["n"] == 1:
                session.parar("pedido do utilizador")
            else:  # 2.º Ctrl+C: sair já (o Mutter remove o ecrã quando o processo morre)
                os._exit(130)
            return True
        for s in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, s, on_signal)
        loop.run()
    except ecra.ErroEcra as e:
        print(f"\n✘ {e}", file=sys.stderr)
        return 2
    except ErroAutenticacao as e:
        print(f"\n✘ autenticação falhou: {e}", file=sys.stderr)
        return 3
    except OSError as e:
        print(f"\n✘ erro de rede: {e}", file=sys.stderr)
        return 4
    return 0
