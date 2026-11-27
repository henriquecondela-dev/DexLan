"""Desinstalação.

Normal: remove o programa, o comando, os atalhos e o arranque automático.
--tudo: remove também as definições, os emparelhamentos, o perfil do cabo e as
regras da firewall. Os pacotes do sistema ficam (o GNOME também os usa).
"""
import os
import shutil
import subprocess

from . import CONTROL_PORT, DISCOVERY_PORT


def pasta_dados():
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def pasta_config_base():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def plano(tudo=False):
    """[(descrição, caminho ou None)] do que vai ser apagado."""
    apps = os.path.join(pasta_dados(), "applications")
    itens = [
        ("programa", os.path.join(pasta_dados(), "dexlan")),
        ("comando dexlan", os.path.expanduser("~/.local/bin/dexlan")),
        ("atalho DexLan", os.path.join(apps, "dexlan.desktop")),
        ("atalho DexLan Receiver", os.path.join(apps, "dexlan-receiver.desktop")),
        ("arranque automático", os.path.join(pasta_config_base(), "autostart", "dexlan-receiver.desktop")),
    ]
    if tudo:
        itens += [
            ("preferências e emparelhamentos", os.path.join(pasta_config_base(), "dexlan")),
            ("perfil de rede DexLan-cabo", None),
            ("regras da firewall", None),
        ]
    return [(desc, caminho) for desc, caminho in itens if caminho is None or os.path.lexists(caminho)]


def limpar_firewall():
    from . import dependencias
    tipo, _ = dependencias.estado_firewall()
    if tipo == "ufw":
        regras = [["ufw", "--force", "delete", "allow", f"{DISCOVERY_PORT}/udp"],
                 ["ufw", "--force", "delete", "allow", f"{CONTROL_PORT}/tcp"],
                 ["ufw", "--force", "delete", "allow", "proto", "udp", "from", "any", "port",
                  str(DISCOVERY_PORT)]]
    elif tipo == "firewalld":
        regras = [["firewall-cmd", "--permanent", f"--remove-port={DISCOVERY_PORT}/udp"],
                 ["firewall-cmd", "--permanent", f"--remove-port={CONTROL_PORT}/tcp"],
                 ["firewall-cmd", "--reload"]]
    else:
        return
    for regra in regras:
        subprocess.run(dependencias.como_root(regra), capture_output=True)


def executar(tudo=False, log=print):
    ok = True
    for desc, caminho in plano(tudo):
        try:
            if desc.startswith("perfil de rede"):
                from . import cabo
                if shutil.which("nmcli"):
                    cabo.desativar()
                    cabo.remover()
            elif desc.startswith("regras"):
                limpar_firewall()
            elif os.path.isdir(caminho) and not os.path.islink(caminho):
                shutil.rmtree(caminho)
            else:
                os.remove(caminho)
            log(f"removido: {desc}")
        except Exception as e:  # noqa: BLE001
            ok = False
            log(f"erro ao remover {desc}: {e}")
    log("Os pacotes do sistema (GStreamer, GTK, ...) não foram removidos.")
    return ok
