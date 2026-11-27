"""Testa o ecrã virtual no GNOME sem rede: cria, mostra os monitores, posiciona e remove.

Uso: python3 testes/testar_ecra_gnome.py [LARGURAxALTURA] [right|left|above|below]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gi  # noqa: E402

gi.require_version("Gst", "1.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib, Gst  # noqa: E402

from dexlan.ecra.base import EspecEcra  # noqa: E402
from dexlan.ecra.gnome import DisplayConfig, EcraGnome  # noqa: E402

Gst.init(None)
largura, altura = map(int, (sys.argv[1] if len(sys.argv) > 1 else "1280x720").split("x"))
posicao = sys.argv[2] if len(sys.argv) > 2 else "right"

ecra = EcraGnome(EspecEcra(largura, altura, 30, posicao))
ecra.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
loop = GLib.MainLoop()
resultado = {"ok": False}


def mostrar(titulo):
    print(f"\n{titulo}")
    for m in DisplayConfig(ecra.bus).monitores():
        print(f"  {m['connector']:8} {m['width']}x{m['height']} em ({m['x']},{m['y']})")


def pronto(fonte):
    pipeline = Gst.parse_launch(fonte + " ! fakesink")
    pipeline.set_state(Gst.State.PLAYING)

    def verificar():
        mon = ecra.encontrar_conector()
        mostrar("Depois de criar:")
        resultado["ok"] = bool(mon and mon["width"] == largura and mon["height"] == altura)
        print("\nOK: o GNOME reconhece o ecrã virtual" if resultado["ok"] else "\nFALHOU")
        print(ecra.aplicar_posicao()[1])
        mostrar("Depois de posicionar:")
        GLib.timeout_add(1500, terminar, pipeline)
        return False
    GLib.timeout_add(1500, verificar)


def terminar(pipeline):
    pipeline.set_state(Gst.State.NULL)
    ecra.destruir()
    GLib.timeout_add(1000, lambda: (mostrar("Depois de remover:"), loop.quit())[1])
    return False


mostrar("Antes:")
ecra.criar(pronto)
GLib.timeout_add_seconds(20, loop.quit)
loop.run()
sys.exit(0 if resultado["ok"] else 1)
