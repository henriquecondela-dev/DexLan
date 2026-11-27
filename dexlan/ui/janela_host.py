"""Janela do host: o visual está em web/host, aqui fica só a lógica."""
import ipaddress
import json
import os
import queue
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gdk, GLib, Gst, Gtk  # noqa: E402

from .. import CONTROL_PORT, __version__  # noqa: E402
from .. import ambiente, cabo, descoberta, desinstalar, ecra, seguranca, video  # noqa: E402
from ..host import Cancelado, ErroAutenticacao, EventosHost, OpcoesHost, SessaoHost  # noqa: E402
from .pagina import PaginaWeb, por_icone  # noqa: E402


def caminho_preferencias():
    return os.path.join(seguranca.pasta_config(), "preferencias.json")


def ler_preferencias():
    try:
        with open(caminho_preferencias()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def guardar_preferencias(prefs):
    with open(caminho_preferencias(), "w") as f:
        json.dump(prefs, f, indent=2)


# posição na página -> posição usada pelo motor
POSICOES = {"direita": "right", "esquerda": "left", "cima": "above", "baixo": "below"}
DA_POSICAO = {v: k for k, v in POSICOES.items()}


def estado_cabo(st):
    ip = st["activa"]["ipv4"][0] if st.get("activa") else None
    return {"disponivel": st["disponivel"], "texto": cabo.descrever(st), "ip": ip,
            "definicoes": st["definicoes"]}


class EventosJanela(EventosHost):
    def __init__(self, janela):
        self.janela = janela
        self.codigos = queue.Queue()

    def log(self, msg):
        print(f"[host] {msg}", flush=True)

    def state(self, state, detail=""):
        GLib.idle_add(self.janela.ao_mudar_estado, state)

    def stats(self, s):
        GLib.idle_add(self.janela.pagina.enviar, "numeros",
                      {"fps": s["fps"], "kbps": s["kbps"],
                       "rtt": s["rtt_ms"] if s["connected"] else None})

    def stopped(self, reason, error=False):
        GLib.idle_add(self.janela.ao_parar, reason)

    def ask_pin(self, ip, left):
        GLib.idle_add(self.janela.pagina.enviar, "vista",
                      {"nome": "codigo", "alvo": self.janela.alvo["nome"], "restantes": left})
        return self.codigos.get()


class JanelaHost:
    def __init__(self):
        self.env = ambiente.detectar()
        self.prefs = ler_preferencias()
        self.sessao = None
        self.alvo = None
        self.parado_pelo_utilizador = False
        self.sair_depois_de_parar = False
        self.eventos = EventosJanela(self)
        self.ultimo_cabo = None

        self.win = Gtk.Window(title="DexLan")
        self.win.set_default_size(440, 700)
        por_icone(self.win)
        self.win.connect("delete-event", self.ao_fechar)
        self.pagina = PaginaWeb("host", self.ao_receber_accao)
        self.win.add(self.pagina.view)
        self.win.show_all()

        self.cabo_auto = cabo.CaboAutomatico(
            on_change=lambda st: GLib.idle_add(self.ao_mudar_cabo, st))
        self.cabo_auto.start()

    # ---------- acções vindas da página

    def ao_receber_accao(self, accao, dados):
        funcao = getattr(self, f"do_{accao}", None)
        if funcao:
            funcao(**dados)

    def do_pronto(self):
        try:
            ecra.escolher(self.env)
            erro_ecra = None
        except ecra.ErroEcra as e:
            erro_ecra = str(e).splitlines()[0]
        self.pagina.enviar("inicio", {
            "nomeHost": seguranca.identidade()["name"],
            "tamanhoLocal": self.tamanho_local(),
            "versao": __version__,
            "sistema": f"{self.env.distro_name} ({self.env.desktop}, {self.env.session_type})",
            "prefs": self.prefs,
            "hwDisponivel": video.tem("vah264enc") or video.tem("vah264lpenc"),
            "erroEcra": erro_ecra,
        })
        self.do_procurar()

    def do_procurar(self):
        self.pagina.enviar("a_procurar", True)

        def trabalho():
            encontrados = descoberta.procurar(timeout=2.0)
            conhecidos = seguranca.ReceiversConhecidos().data
            dispositivos = []
            for r in encontrados:
                ip = next((i for i in r["ips"] if self.via_de(i) == "cabo"), r["ip"])
                dispositivos.append({"id": r.get("id"), "nome": r["name"], "ip": ip,
                                     "porta": r.get("port", CONTROL_PORT), "via": self.via_de(ip),
                                     "emparelhado": r.get("id") in conhecidos})
            dispositivos.sort(key=lambda d: d["nome"].lower())
            GLib.idle_add(self.pagina.enviar, "dispositivos", dispositivos)
            GLib.idle_add(self.pagina.enviar, "a_procurar", False)
        threading.Thread(target=trabalho, daemon=True).start()

    def do_preferencias(self, **mudancas):
        self.prefs.update(mudancas)
        guardar_preferencias(self.prefs)

    def do_ligar(self, alvo, posicao, resolucao, qualidade, hw):
        ip, _, porta = alvo["ip"].partition(":")
        self.alvo = {"ip": ip, "porta": int(alvo.get("porta") or porta or CONTROL_PORT),
                     "nome": alvo.get("nome") or ip}
        self.do_preferencias(posicao=posicao, resolucao=resolucao, qualidade=qualidade, hw=hw)
        opcoes = OpcoesHost(resolution=resolucao, bitrate=int(qualidade), position=POSICOES.get(posicao, "right"), hw=hw)
        try:
            self.sessao = SessaoHost(opcoes, self.env, self.eventos)
        except ecra.ErroEcra as e:
            self.pagina.enviar("vista", {"nome": "inicio", "erro": str(e)})
            return
        self.parado_pelo_utilizador = False
        self.pagina.enviar("vista", {"nome": "a_ligar", "alvo": self.alvo["nome"], "ip": ip})
        sessao = self.sessao
        endereco = (ip, self.alvo["porta"])

        def trabalho():
            try:
                boas_vindas = sessao.autenticar(endereco)
            except Cancelado:
                GLib.idle_add(self.voltar_ao_inicio, None)
            except ErroAutenticacao as e:
                GLib.idle_add(self.voltar_ao_inicio, f"Não foi possível ligar: {e}.")
            except OSError:
                GLib.idle_add(self.voltar_ao_inicio, f"Sem resposta de {ip}. O receiver está aberto?")
            else:
                GLib.idle_add(self.iniciar_sessao, boas_vindas)
        threading.Thread(target=trabalho, daemon=True).start()

    def do_codigo(self, codigo):
        self.eventos.codigos.put(codigo)

    def do_cancelar(self):
        self.eventos.codigos.put(None)
        if self.sessao and not self.sessao.running:
            sessao, self.sessao = self.sessao, None
            if sessao.ch:
                sessao.ch.close()
            self.voltar_ao_inicio(None)

    def do_parar(self):
        if self.sessao:
            self.parado_pelo_utilizador = True
            self.sessao.parar("pedido do utilizador")

    def do_cabo(self, ativo=None, modo=None, endereco=None, mascara=None, aplicar=False):
        try:
            if ativo is not None:
                cabo.guardar_definicoes(ativo=ativo)
            if aplicar:
                cabo.guardar_definicoes(modo=modo, endereco=endereco or "", mascara=mascara or "")
        except cabo.ErroCabo as e:
            self.pagina.enviar("resultadoCabo", {"erro": str(e)})
            return
        if not aplicar:
            self.cabo_auto.atualizar()
            return

        def trabalho():
            try:
                cabo.reaplicar()
                resultado = {}
            except cabo.ErroCabo as e:
                resultado = {"erro": str(e)}
            GLib.idle_add(self.pagina.enviar, "resultadoCabo", resultado)
            self.cabo_auto.atualizar()
        threading.Thread(target=trabalho, daemon=True).start()

    def do_esquecer(self):
        seguranca.ReceiversConhecidos().revogar()
        self.do_procurar()

    def do_desinstalar(self, tudo):
        if self.sessao and self.sessao.running:
            self.sessao.parar("desinstalação")
        desinstalar.executar(tudo, log=lambda m: print(m, flush=True))
        Gtk.main_quit()

    # ---------- eventos do motor

    def iniciar_sessao(self, boas_vindas):
        if self.sessao is None:
            return False
        self.alvo["nome"] = boas_vindas["name"]
        try:
            self.sessao.iniciar()
        except ecra.ErroEcra as e:
            self.sessao = None
            self.voltar_ao_inicio(f"Não foi possível criar o ecrã virtual: {e}")
            return False
        spec = self.sessao.ecra.spec
        self.pagina.enviar("vista", {"nome": "activo", "alvo": boas_vindas["name"],
                                     "tamanho": [spec.width, spec.height],
                                     "posicao": DA_POSICAO.get(spec.position, "direita"), "via": self.via()})
        return False

    def via_de(self, ip):
        """'cabo' se o IP estiver na rede do cabo, senão 'rede'."""
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return "rede"
        if addr.is_link_local:
            return "cabo"
        st = self.ultimo_cabo
        if st and st.get("activa") and addr in ipaddress.ip_interface(st["activa"]["ipv4"][0]).network:
            return "cabo"
        return "rede"

    def via(self):
        return self.via_de(self.alvo["ip"]) if self.alvo else "rede"

    def ao_mudar_estado(self, state):
        if state in ("active", "reconnecting"):
            estado = "activo" if state == "active" else "a_religar"
            self.pagina.enviar("sessao", {"estado": estado, "via": self.via()})
        return False

    def ao_parar(self, motivo):
        self.sessao = None
        if self.sair_depois_de_parar:
            Gtk.main_quit()
        elif self.parado_pelo_utilizador:
            self.voltar_ao_inicio(None)
        else:
            self.voltar_ao_inicio(f"A ligação terminou: {motivo}.")
        return False

    def ao_mudar_cabo(self, st):
        ip_antigo = estado_cabo(self.ultimo_cabo)["ip"] if self.ultimo_cabo else None
        self.ultimo_cabo = st
        novo = estado_cabo(st)
        self.pagina.enviar("cabo", novo)
        # o IP do cabo mudou: procurar de novo (o outro lado pode demorar uns segundos)
        if novo["ip"] != ip_antigo and not self.sessao:
            GLib.timeout_add_seconds(2, lambda: (self.do_procurar(), False)[1])
        return False

    def voltar_ao_inicio(self, erro):
        self.pagina.enviar("vista", {"nome": "inicio", "erro": erro})
        self.do_procurar()
        return False

    def ao_fechar(self, *_):
        if self.sessao and self.sessao.running:
            self.sair_depois_de_parar = True
            self.sessao.parar("janela fechada")
            return True
        Gtk.main_quit()
        return False

    def tamanho_local(self):
        try:
            mon = Gdk.Display.get_default().get_monitor(0)
            g = mon.get_geometry()
            return [g.width * mon.get_scale_factor(), g.height * mon.get_scale_factor()]
        except Exception:  # noqa: BLE001
            return [1366, 768]


def main(args=None):
    Gst.init(None)
    GLib.set_prgname("dexlan")
    GLib.set_application_name("DexLan")
    JanelaHost()
    Gtk.main()
    return 0
