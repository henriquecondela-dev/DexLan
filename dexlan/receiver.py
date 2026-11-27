"""DexLan Receiver: corre no computador que serve de ecrã.

Recebe o vídeo do host e mostra-o em ecrã inteiro. A página de espera
(nome, código, rede) está em ui/web/receiver.
Teclas: F11 ecrã inteiro, Esc sair do ecrã inteiro, i números, Ctrl+Q sair.
"""
import os
import secrets
import socket
import ssl
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gdk, GLib, Gst, Gtk  # noqa: E402

from . import CONTROL_PORT, PROTOCOL_VERSION, __version__  # noqa: E402
from . import cabo, descoberta, seguranca, video  # noqa: E402
from .protocolo import Canal  # noqa: E402
from .ui.pagina import PaginaWeb, por_icone  # noqa: E402

DEV = bool(os.environ.get("DEXLAN_DEV"))
VIRTUAL = ("lo", "docker", "br-", "veth", "virbr", "vmnet", "vboxnet", "tun", "tap", "wg")


def ips_locais():
    """IPs das placas reais (sem Docker, bridges virtuais nem VPN)."""
    ips = []
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            if "inet" in parts and not parts[1].startswith(VIRTUAL):
                ips.append(parts[parts.index("inet") + 1].split("/")[0])
    except OSError:
        pass
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            ips.append(s.getsockname()[0])
            s.close()
        except OSError:
            pass
    return ips


class AppReceiver:
    def __init__(self, name=None, port=CONTROL_PORT, windowed=False, usar_cabo=True):
        self.ident = seguranca.identidade()
        self.name = name or socket.gethostname()
        self.port = port
        self.windowed = windowed
        self.usar_cabo = usar_cabo
        self.cert, self.key = seguranca.garantir_certificado()
        self.fingerprint = seguranca.impressao_certificado(self.cert)
        self.trust = seguranca.ConfiancaReceiver()
        self.busy = threading.Lock()
        self.pipeline = None
        self.appsrc = None
        self.frames = 0
        self.bytes = 0
        self.info_text = ""
        self.cabo_auto = None
        self.criar_janela()

    # ---------- janela

    def criar_janela(self):
        self.win = Gtk.Window(title=f"DexLan Receiver: {self.name}")
        self.win.set_default_size(1024, 600)
        por_icone(self.win)
        self.win.connect("destroy", lambda *_: self.quit())
        self.win.connect("key-press-event", self.on_key)

        self.pagina = PaginaWeb("receiver", self.ao_receber_accao)
        self.video = Gtk.Overlay()
        self.video.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0, 0, 0, 1))
        self.stats = Gtk.Label(xalign=0)
        self.stats.set_halign(Gtk.Align.START)
        self.stats.set_valign(Gtk.Align.START)
        self.stats.set_margin_start(12)
        self.stats.set_margin_top(12)
        self.stats.set_no_show_all(True)
        self.video.add_overlay(self.stats)
        self.video_widget = None

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self.pagina.view, "page")
        self.stack.add_named(self.video, "video")
        self.win.add(self.stack)
        self.win.show_all()
        GLib.timeout_add(1000, self.tick)

    def ui(self, fn, *args):
        GLib.idle_add(lambda: (fn(*args), False)[1])

    def status(self, title, text="", pin=""):
        self.ui(self.pagina.enviar, "estado", {"titulo": title, "texto": text, "codigo": pin})

    def a_espera(self):
        self.status("Pronto para servir de ecrã",
                    f"No outro computador, abre o DexLan e escolhe {self.name}.")

    def enviar_rede(self, st=None):
        st = st or (cabo.estado() if self.usar_cabo else None)
        dados = {"enderecos": ips_locais()}
        if st:
            dados["cabo"] = {"disponivel": st["disponivel"], "texto": cabo.descrever(st),
                             "ip": st["activa"]["ipv4"][0] if st.get("activa") else None,
                             "definicoes": st["definicoes"]}
        self.ui(self.pagina.enviar, "rede", dados)

    def ao_receber_accao(self, accao, dados):
        if accao == "pronto":
            self.pagina.enviar("inicio", {"nome": self.name, "versao": __version__,
                                    "cabo": self.usar_cabo})
            self.a_espera()
            threading.Thread(target=self.enviar_rede, daemon=True).start()
        elif accao == "cabo":
            threading.Thread(target=self.mudar_cabo, kwargs=dados, daemon=True).start()
        elif accao == "ecra_inteiro":
            self.alternar_ecra_inteiro()
        elif accao == "sair":
            self.quit()

    def mudar_cabo(self, ativo=None, modo=None, endereco=None, mascara=None, aplicar=False):
        try:
            if ativo is not None:
                cabo.guardar_definicoes(ativo=ativo)
            if aplicar:
                cabo.guardar_definicoes(modo=modo, endereco=endereco or "", mascara=mascara or "")
                cabo.reaplicar()
            resultado = {}
        except cabo.ErroCabo as e:
            resultado = {"erro": str(e)}
        self.ui(self.pagina.enviar, "resultadoCabo", resultado)
        if self.cabo_auto:
            self.cabo_auto.atualizar()

    def alternar_ecra_inteiro(self):
        if self.win.get_window().get_state() & Gdk.WindowState.FULLSCREEN:
            self.win.unfullscreen()
        else:
            self.win.fullscreen()

    def on_key(self, _w, ev):
        key = Gdk.keyval_name(ev.keyval)
        if key == "F11":
            self.alternar_ecra_inteiro()
        elif key == "Escape":
            self.win.unfullscreen()
        elif key in ("i", "I") and self.stack.get_visible_child_name() == "video":
            self.stats.set_visible(not self.stats.get_visible())
        elif key in ("q", "Q") and ev.state & Gdk.ModifierType.CONTROL_MASK:
            self.quit()
        return False

    def esconder_cursor(self, hidden):
        gw = self.win.get_window()
        if gw:
            cursor = Gdk.Cursor.new_for_display(gw.get_display(), Gdk.CursorType.BLANK_CURSOR)
            gw.set_cursor(cursor if hidden else None)

    def tick(self):
        if self.pipeline:
            fps, self.frames = self.frames, 0
            mbps, self.bytes = self.bytes * 8 / 1e6, 0
            self.stats.set_markup(f'<span background="#000000c0" foreground="#ffffff"> '
                                  f'{GLib.markup_escape_text(self.info_text)}  |  '
                                  f'{fps} imagens/s  |  {mbps:.1f} Mbit/s </span>')
        return True

    def tamanho_ecra(self):
        ecra = Gdk.Display.get_default()
        gw = self.win.get_window()
        mon = ecra.get_monitor_at_window(gw) if gw else ecra.get_monitor(0)
        g = mon.get_geometry()
        return g.width * mon.get_scale_factor(), g.height * mon.get_scale_factor()

    # ---------- vídeo

    def iniciar_video(self, info, done):
        try:
            decoder, desc = video.pipeline_receiver()
            self.pipeline = Gst.parse_launch(desc)
            self.appsrc = self.pipeline.get_by_name("src")
            probe = self.pipeline.get_by_name("probe")
            probe.set_property("signal-handoffs", True)
            probe.connect("handoff", lambda *_: setattr(self, "frames", self.frames + 1))
            if self.video_widget:
                self.video.remove(self.video_widget)
            self.video_widget = self.pipeline.get_by_name("view").props.widget
            self.video.add(self.video_widget)
            self.video_widget.show()
            self.stack.set_visible_child_name("video")
            self.info_text = f"{info['host']}  {info['w']}x{info['h']}  {decoder}"
            self.pipeline.set_state(Gst.State.PLAYING)
            if not self.windowed:
                self.win.fullscreen()
                self.esconder_cursor(True)
        finally:
            done.set()

    def parar_video(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            self.appsrc = None
        self.esconder_cursor(False)
        self.stack.set_visible_child_name("page")
        self.win.unfullscreen()

    def empurrar_video(self, data):
        src = self.appsrc
        if src is not None:
            self.bytes += len(data)
            src.emit("push-buffer", Gst.Buffer.new_wrapped(data))

    # ---------- rede

    def anunciar(self):
        return {"name": self.name, "id": self.ident["id"], "port": self.port}

    def servir(self):
        ctx = seguranca.contexto_servidor(self.cert, self.key)
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("", self.port))
        srv.listen(4)
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=self.atender, args=(ctx, conn, addr), daemon=True).start()

    def atender(self, ctx, raw, addr):
        try:
            raw.settimeout(120)
            tls = ctx.wrap_socket(raw, server_side=True)
        except (ssl.SSLError, OSError):
            raw.close()
            return
        ch = Canal(tls)
        if not self.busy.acquire(blocking=False):
            try:
                ch.enviar_json(t="busy", msg="este receiver já está a ser usado")
            finally:
                ch.close()
            return
        host = None
        try:
            host = self.sessao(ch, addr)
        except Exception as e:  # noqa: BLE001
            print(f"[receiver] sessão terminou: {e}", flush=True)
        finally:
            ch.close()
            self.ui(self.parar_video)
            self.busy.release()
            if host:
                self.status(f"{host} deixou de usar este ecrã", "Pronto para a próxima ligação.")
                GLib.timeout_add_seconds(5, lambda: (self.a_espera() if not self.busy.locked() else None,
                                                     False)[1])
            else:
                self.a_espera()

    def sessao(self, ch, addr):
        hello = ch.receber_json("hello")
        if hello.get("v") != PROTOCOL_VERSION:
            ch.enviar_json(t="error", msg="versão do DexLan diferente nos dois computadores")
            return None
        host = hello.get("name", addr[0])
        if not self.trust.autorizado(hello.get("id", ""), hello.get("token")):
            if not self.emparelhar(ch, hello.get("id", ""), host):
                return None
        w, h = self.tamanho_ecra()
        ch.enviar_json(t="welcome", id=self.ident["id"], name=self.name, screen=[w, h],
                     version=__version__)
        ch.sock.settimeout(15)
        self.status(f"Ligado a {host}", "A preparar a imagem…")
        print(f"[receiver] ligado a {host} ({addr[0]})", flush=True)
        while True:
            kind, msg = ch.receber()
            if kind == "video":
                self.empurrar_video(msg[1])
            elif msg.get("t") == "start":
                done = threading.Event()
                self.ui(self.iniciar_video, {"host": host, "w": msg["w"], "h": msg["h"]}, done)
                done.wait(10)
                ch.enviar_json(t="ready")
            elif msg.get("t") == "ping":
                ch.enviar_json(t="pong", ts=msg.get("ts"))
            elif msg.get("t") == "bye":
                return host

    def emparelhar(self, ch, host_id, host):
        pin = seguranca.novo_codigo()
        nonce = secrets.token_hex(16)
        self.status(f"{host} quer usar este ecrã",
                    f"Escreve este código em {host}. Se não foste tu, ignora.", pin)
        if DEV:
            print(f"[receiver] código: {pin}", flush=True)
        ch.enviar_json(t="pair_required", nonce=nonce)
        for left in (2, 1, 0):
            msg = ch.receber_json("pair")
            if seguranca.verificar_prova(pin, nonce, self.fingerprint, msg.get("proof", "")):
                ch.enviar_json(t="paired", token=self.trust.add(host_id, host))
                return True
            ch.enviar_json(t="pair_failed", left=left)
            time.sleep(1)
        self.status("Ligação recusada", f"O código foi escrito errado 3 vezes em {host}.")
        time.sleep(2)
        return False

    # ---------- arranque

    def run(self):
        if self.usar_cabo:
            self.cabo_auto = cabo.CaboAutomatico(on_change=self.enviar_rede)
            self.cabo_auto.start()
        descoberta.Respondedor(self.anunciar).start()
        threading.Thread(target=self.servir, daemon=True).start()
        print(f"[receiver] {self.name} pronto em {', '.join(ips_locais())}:{self.port}", flush=True)
        Gtk.main()

    def quit(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        Gtk.main_quit()
        os._exit(0)


def main(args):
    Gst.init(None)
    GLib.set_prgname("dexlan-receiver")
    if args.forget_hosts:
        seguranca.ConfiancaReceiver().revogar()
        print("Hosts autorizados esquecidos.")
        return 0
    AppReceiver(name=args.name, port=args.port, windowed=args.windowed,
                usar_cabo=not args.sem_cabo).run()
    return 0
