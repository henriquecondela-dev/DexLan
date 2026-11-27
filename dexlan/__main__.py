"""Linha de comandos do DexLan.

  dexlan app                        janela principal (host)
  dexlan receiver                   usar este computador como ecrã
  dexlan host --connect IP          host sem janela
  dexlan doctor | setup             verificar / instalar dependências
  dexlan cable status|auto|manual IP MASK|on|off|remove|watch
  dexlan trust list|forget          dispositivos emparelhados
  dexlan monitors                   listar monitores
  dexlan uninstall [--purge]        desinstalar
"""
import argparse
import importlib.util
import os
import subprocess
import sys
import time

from . import CONTROL_PORT, __version__, ambiente, dependencias

OK, ERRO, AVISO = "\033[32m✔\033[0m", "\033[31m✘\033[0m", "\033[33m!\033[0m"
# papel na linha de comandos -> papel interno
PAPEIS = {"host": "host", "receiver": "receiver", "all": "todos"}


def cmd_verificar(args):
    env = ambiente.detectar()
    papel = PAPEIS[args.role]
    caps, hw = dependencias.verificar(papel, env)
    print(f"DexLan {__version__} ({args.role})")
    print(f"  {env.resumo()}")
    for cap, ok in caps.items():
        print(f"  {OK if ok else ERRO} {dependencias.DESCRICAO[cap]}")
    if papel in ("host", "todos"):
        print(f"  {OK if hw else AVISO} codificação pela placa gráfica (VA-API)"
              f"{'' if hw else ': não disponível, opcional'}")
        if caps.get("python-gi") and caps.get("gstreamer"):
            from . import ecra
            for backend, ok, motivo in ecra.verificar_todos(env):
                print(f"  {OK if ok else AVISO} ecrã virtual '{backend.name}': {motivo}")
    from . import cabo
    cabo_ok, motivo = cabo.disponivel()
    print(f"  {OK if cabo_ok else AVISO} cabo de rede: "
          f"{cabo.descrever(cabo.estado()) if cabo_ok else motivo + ' (opcional)'}")
    firewall, activa = dependencias.estado_firewall()
    if activa:
        print(f"  {AVISO} firewall {firewall} activa: 'dexlan setup' abre as portas "
              f"47800/udp e {CONTROL_PORT}/tcp")
    faltam = [c for c, ok in caps.items() if not ok]
    if faltam:
        print(f"\nEm falta: {', '.join(faltam)}. Corre: dexlan setup --role {args.role}")
        return 1
    print("\nTudo pronto.")
    return 0


def cmd_instalar(args):
    env = ambiente.detectar()
    papel = PAPEIS[args.role]
    caps, _ = dependencias.verificar(papel, env)
    faltam = [c for c, ok in caps.items() if not ok]
    if faltam:
        if not env.package_manager:
            print("Gestor de pacotes não reconhecido. Instala à mão:", ", ".join(faltam))
            return 1
        _, pacotes = dependencias.comando_instalar(env.package_manager, faltam)
        print(f"Vou instalar com {env.package_manager}: {' '.join(pacotes)}")
        if not args.yes and input("Continuar? [S/n] ").strip().lower() in ("n", "nao", "não"):
            return 1
        if not dependencias.instalar(env.package_manager, faltam):
            print("A instalação falhou.")
            return 1
    else:
        print("Dependências já instaladas.")
    firewall, activa = dependencias.estado_firewall()
    if activa and (args.yes or input(f"Abrir as portas na firewall {firewall}? [S/n] ").strip().lower()
                   not in ("n", "nao", "não")):
        dependencias.abrir_firewall(firewall, papel)
    if papel in ("receiver", "todos"):
        from . import seguranca
        seguranca.garantir_certificado()
    # verificar num processo novo (este já tem a lista de plugins antiga em memória)
    lancador = os.environ.get("DEXLAN_LAUNCHER")
    cmd = [lancador] if lancador else [sys.executable, "-m", "dexlan"]
    return subprocess.run(cmd + ["doctor", "--role", args.role]).returncode


def cmd_cabo(args):
    from . import cabo
    try:
        if args.action == "status":
            st = cabo.estado()
            cfg = st["definicoes"]
            print(cabo.descrever(st))
            extra = f" ({cfg['endereco']} / {cfg['mascara']})" if cfg["modo"] == "manual" else ""
            print(f"  modo: {cfg['modo']}{extra}")
            for p in st["placas"]:
                print(f"  {p['placa']:12} cabo {'ligado' if p['cabo_ligado'] else 'desligado':10} "
                      f"{','.join(p['ipv4']) or 'sem IP':20} {'[DexLan]' if p['dexlan'] else ''}")
        elif args.action == "auto":
            cabo.guardar_definicoes(modo="auto", ativo=True)
            print("Modo automático (169.254.x.x).", aplicar_cabo(cabo))
        elif args.action == "manual":
            if len(args.values) != 2:
                print("Uso: dexlan cable manual IP MASCARA   (ex.: 192.168.50.1 255.255.255.0)")
                return 1
            ip, mascara = args.values
            cabo.guardar_definicoes(modo="manual", endereco=ip, mascara=mascara, ativo=True)
            print(f"Modo manual: {ip} / {mascara}.", aplicar_cabo(cabo))
        elif args.action == "on":
            placa = args.values[0] if args.values else None
            if not placa:
                st = cabo.estado()
                com_cabo = [p for p in st["placas"] if p["cabo_ligado"]] or st["placas"]
                placa = com_cabo[0]["placa"] if com_cabo else None
            if not placa:
                print("Nenhuma placa de rede com fio encontrada.")
                return 1
            print(f"Ligado por cabo: {cabo.ativar(placa)}")
        elif args.action == "off":
            cabo.desativar()
            print("Modo cabo desligado.")
        elif args.action == "remove":
            cabo.remover()
            print("Perfil DexLan-cabo removido.")
        elif args.action == "watch":
            print("A vigiar o cabo (Ctrl+C para sair)…")
            cabo.CaboAutomatico(on_change=lambda st: print(time.strftime("%H:%M:%S"),
                                                           cabo.descrever(st), flush=True)).start()
            while True:
                time.sleep(1)
    except cabo.ErroCabo as e:
        print(f"Erro: {e}")
        return 1
    except KeyboardInterrupt:
        pass
    return 0


def aplicar_cabo(cabo):
    try:
        ip = cabo.reaplicar()
        return f"Aplicado: {ip}." if ip else "Será aplicado quando ligares o cabo."
    except cabo.ErroCabo as e:
        return f"Não foi possível aplicar agora: {e}"


def cmd_confianca(args):
    from . import seguranca
    hosts, receivers = seguranca.ConfiancaReceiver(), seguranca.ReceiversConhecidos()
    if args.action == "list":
        print("Receivers conhecidos:")
        for k, v in receivers.data.items():
            print(f"  {k}  {v['name']}")
        print("Hosts autorizados:")
        for k, v in hosts.data.items():
            print(f"  {k}  {v['name']}")
    else:
        receivers.revogar(args.id)
        hosts.revogar(args.id)
        print("Emparelhamentos esquecidos.")
    return 0


def cmd_monitores(args):
    env = ambiente.detectar()
    if not env.has_mutter_screencast:
        os.execvp("xrandr", ["xrandr", "--listmonitors"])
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
    from .ecra.gnome import DisplayConfig
    for m in DisplayConfig(Gio.bus_get_sync(Gio.BusType.SESSION, None)).monitores():
        print(f"{m['connector']:10} {m['width']}x{m['height']} +{m['x']}+{m['y']}"
              f"{'  (principal)' if m['primary'] else ''}")
    return 0


def cmd_desinstalar(args):
    from . import desinstalar
    itens = desinstalar.plano(args.purge)
    if not itens:
        print("O DexLan não está instalado.")
        return 0
    print("Vai ser removido:")
    for desc, caminho in itens:
        print(f"  - {desc}" + (f" ({caminho})" if caminho else ""))
    if not args.yes and input("Continuar? [s/N] ").strip().lower() not in ("s", "sim", "y"):
        return 1
    return 0 if desinstalar.executar(args.purge) else 1


def criar_parser():
    p = argparse.ArgumentParser(prog="dexlan", description="Usa outro computador Linux como ecrã estendido.")
    p.add_argument("--version", action="version", version=f"DexLan {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    for nome, ajuda in (("doctor", "verificar o sistema"), ("setup", "instalar dependências")):
        s = sub.add_parser(nome, help=ajuda)
        s.add_argument("--role", choices=list(PAPEIS), default="all")
        if nome == "setup":
            s.add_argument("-y", "--yes", action="store_true", help="não fazer perguntas")

    sub.add_parser("app", help="janela principal")

    r = sub.add_parser("receiver", help="usar este computador como ecrã")
    r.add_argument("--name", help="nome mostrado na rede (por omissão o nome do computador)")
    r.add_argument("--port", type=int, default=CONTROL_PORT)
    r.add_argument("--windowed", action="store_true", help="não entrar em ecrã inteiro")
    r.add_argument("--no-cable", dest="sem_cabo", action="store_true", help="não configurar o cabo de rede")
    r.add_argument("--forget-hosts", action="store_true")

    h = sub.add_parser("host", help="host sem janela")
    h.add_argument("--connect", metavar="IP[:PORTA]")
    h.add_argument("--resolution", default="auto", help="LARGURAxALTURA ou auto")
    h.add_argument("--fps", type=int, default=30)
    h.add_argument("--bitrate", type=int, default=6000, help="kbit/s")
    h.add_argument("--position", choices=["right", "left", "above", "below"], default="right")
    h.add_argument("--backend", choices=["gnome", "x11", "test"])
    h.add_argument("--hw", action="store_true", help="codificar com a placa gráfica (VA-API)")
    h.add_argument("--pin")
    h.add_argument("--grace", type=int, default=30, help="segundos à espera de religar")
    h.add_argument("--max-queue", type=int, default=6, help=argparse.SUPPRESS)
    h.add_argument("--discover-timeout", type=float, default=2.5, help=argparse.SUPPRESS)
    h.add_argument("-y", "--yes", action="store_true", help="usar o primeiro receiver encontrado")

    c = sub.add_parser("cable", help="ligação por cabo de rede")
    c.add_argument("action", choices=["status", "auto", "manual", "on", "off", "remove", "watch"])
    c.add_argument("values", nargs="*", help="manual: IP MASCARA | on: placa")

    t = sub.add_parser("trust", help="dispositivos emparelhados")
    t.add_argument("action", choices=["list", "forget"])
    t.add_argument("id", nargs="?")

    sub.add_parser("monitors", help="listar monitores")

    u = sub.add_parser("uninstall", help="desinstalar")
    u.add_argument("--purge", action="store_true", help="apagar também definições e emparelhamentos")
    u.add_argument("-y", "--yes", action="store_true")
    return p


COMANDOS = {"doctor": cmd_verificar, "setup": cmd_instalar, "cable": cmd_cabo,
            "trust": cmd_confianca, "monitors": cmd_monitores, "uninstall": cmd_desinstalar}


def main(argv=None):
    args = criar_parser().parse_args(argv)
    if args.cmd in COMANDOS:
        return COMANDOS[args.cmd](args)
    if importlib.util.find_spec("gi") is None:
        print("Faltam dependências. Corre: dexlan setup")
        return 1
    if args.cmd == "receiver":
        from . import receiver
        return receiver.main(args)
    if args.cmd == "host":
        from . import host
        return host.main(args)
    from .ui import janela_host
    return janela_host.main(args)


if __name__ == "__main__":
    sys.exit(main())
