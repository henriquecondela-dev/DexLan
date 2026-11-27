"""Ecrã virtual no GNOME (Wayland) através do Mutter.

org.gnome.Mutter.ScreenCast.Session.RecordVirtual cria um monitor virtual dentro
do desktop e devolve uma video PipeWire com a imagem dele. Com "is-platform" o
GNOME trata-o como um monitor normal (aparece nas definições, recebe janelas).
A resolução é a que o GStreamer pedir no capsfilter.
Quando a sessão termina (ou o processo morre) o Mutter remove o monitor sozinho.
"""
import time

from .base import ErroEcra, EcraVirtual

BUS = "org.gnome.Mutter.ScreenCast"
SC_PATH = "/org/gnome/Mutter/ScreenCast"
SC_IFACE = "org.gnome.Mutter.ScreenCast"
SESSION_IFACE = "org.gnome.Mutter.ScreenCast.Session"
STREAM_IFACE = "org.gnome.Mutter.ScreenCast.Stream"
DC_BUS = "org.gnome.Mutter.DisplayConfig"
DC_PATH = "/org/gnome/Mutter/DisplayConfig"
CURSOR_EMBEDDED = 1


def gio():
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    return Gio, GLib


class DisplayConfig:
    """Lista e posiciona monitores (org.gnome.Mutter.DisplayConfig)."""

    def __init__(self, bus):
        self.bus = bus
        self.Gio, self.GLib = gio()

    def state(self):
        res = self.bus.call_sync(DC_BUS, DC_PATH, DC_BUS, "GetCurrentState", None, None,
                                 self.Gio.DBusCallFlags.NONE, 5000, None)
        return res.unpack()

    def monitores(self):
        _, monitors, logical, _ = self.state()
        result = []
        for (spec, modes, props) in monitors:
            connector = spec[0]
            current = next((m for m in modes if m[6].get("is-current")), None)
            entry = {"connector": connector, "display_name": props.get("display-name", connector),
                     "mode_id": current[0] if current else None,
                     "width": current[1] if current else 0, "height": current[2] if current else 0,
                     "x": None, "y": None, "primary": False, "scale": 1.0, "transform": 0}
            for (x, y, scale, transform, primary, mons, _) in logical:
                if any(m[0] == connector for m in mons):
                    entry.update(x=x, y=y, primary=primary, scale=scale, transform=transform)
            result.append(entry)
        return result

    def posicionar(self, connector, position):
        serial = self.state()[0]
        monitors = self.monitores()
        target = next((m for m in monitors if m["connector"] == connector), None)
        if not target or target["mode_id"] is None:
            raise ErroEcra(f"monitor {connector} não encontrado")
        others = [m for m in monitors if m["connector"] != connector and m["x"] is not None]

        def size(m):
            return int(m["width"] / m["scale"]), int(m["height"] / m["scale"])

        minx = min((m["x"] for m in others), default=0)
        miny = min((m["y"] for m in others), default=0)
        maxx = max((m["x"] + size(m)[0] for m in others), default=0)
        maxy = max((m["y"] + size(m)[1] for m in others), default=0)
        tw, th = size(target)
        x, y = {"right": (maxx, miny), "left": (minx - tw, miny),
                "above": (minx, miny - th), "below": (minx, maxy)}.get(position, (maxx, miny))
        placed = [(m, m["x"], m["y"]) for m in others] + [(target, x, y)]
        # o Mutter quer coordenadas a partir de (0,0)
        ox = min(p[1] for p in placed)
        oy = min(p[2] for p in placed)
        config = [(px - ox, py - oy, m["scale"], m["transform"], m["primary"],
                   [(m["connector"], m["mode_id"], {})]) for m, px, py in placed]
        args = self.GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (serial, 1, config, {}))
        self.bus.call_sync(DC_BUS, DC_PATH, DC_BUS, "ApplyMonitorsConfig", args, None,
                           self.Gio.DBusCallFlags.NONE, 5000, None)


class EcraGnome(EcraVirtual):
    name = "gnome"
    description = "GNOME / Mutter (Wayland)"

    def __init__(self, spec):
        super().__init__(spec)
        self.bus = None
        self.session_path = None
        self.stream_path = None
        self.node_id = None
        self.connector = None
        self._signal = None
        self._before = set()

    @classmethod
    def suportado(cls, env):
        if env.session_type != "wayland":
            return False, "a sessão não é Wayland"
        if not env.has_mutter_screencast:
            return False, "não é GNOME (sem org.gnome.Mutter.ScreenCast)"
        return True, "GNOME Wayland"

    def criar(self, on_ready):
        Gio, GLib = gio()
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        try:
            self._before = {m["connector"] for m in DisplayConfig(self.bus).monitores()}
        except GLib.Error:
            self._before = set()

        def call(path, iface, method, args, reply):
            return self.bus.call_sync(BUS, path, iface, method, args,
                                      GLib.VariantType(reply) if reply else None,
                                      Gio.DBusCallFlags.NONE, 10000, None)
        try:
            (self.session_path,) = call(SC_PATH, SC_IFACE, "CreateSession",
                                        GLib.Variant("(a{sv})", ({},)), "(o)").unpack()
            props = {"cursor-mode": GLib.Variant("u", CURSOR_EMBEDDED),
                     "is-platform": GLib.Variant("b", True)}
            (self.stream_path,) = call(self.session_path, SESSION_IFACE, "RecordVirtual",
                                       GLib.Variant("(a{sv})", (props,)), "(o)").unpack()
        except GLib.Error as e:
            raise ErroEcra(f"o Mutter recusou criar o ecrã virtual: {e.message}")

        def stream_added(conn, sender, path, iface, signal, params):
            (self.node_id,) = params.unpack()
            self.active = True
            on_ready(self.fonte_gst())

        self._signal = self.bus.signal_subscribe(BUS, STREAM_IFACE, "PipeWireStreamAdded",
                                                 self.stream_path, None,
                                                 Gio.DBusSignalFlags.NONE, stream_added)
        call(self.session_path, SESSION_IFACE, "Start", None, None)

    def fonte_gst(self):
        s = self.spec
        return (f"pipewiresrc path={self.node_id} always-copy=true do-timestamp=true "
                f"keepalive-time={int(1000 / max(1, s.fps))} ! "
                f"video/x-raw,max-framerate={s.fps}/1,width={s.width},height={s.height}")

    def encontrar_conector(self, timeout=5.0):
        config = DisplayConfig(self.bus)
        end = time.time() + timeout
        while time.time() < end:
            new = [m for m in config.monitores() if m["connector"] not in self._before]
            if new:
                self.connector = new[0]["connector"]
                return new[0]
            time.sleep(0.2)
        return None

    def aplicar_posicao(self):
        if not self.encontrar_conector():
            return False, "o ecrã virtual ainda não apareceu"
        try:
            DisplayConfig(self.bus).posicionar(self.connector, self.spec.position)
            return True, f"{self.connector} posicionado ({self.spec.position})"
        except Exception as e:  # noqa: BLE001
            return False, f"posição por omissão ({e})"

    def destruir(self):
        if not (self.bus and self.session_path):
            return
        Gio, GLib = gio()
        try:
            if self._signal:
                self.bus.signal_unsubscribe(self._signal)
            self.bus.call_sync(BUS, self.session_path, SESSION_IFACE, "Stop", None, None,
                               Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error:
            pass
        self.session_path = None
        self.active = False
