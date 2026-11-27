"""Ecrã virtual em X11 com xrandr (experimental).

Aumenta o framebuffer e declara um monitor lógico com 'xrandr --setmonitor'.
A captura é feita com ximagesrc, recortando só esse rectângulo.
"""
import re
import shutil
import subprocess

from .base import ErroEcra, EcraVirtual

MONITOR_NAME = "DexLan-1"


def xrandr(*args, check=True):
    r = subprocess.run(["xrandr", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise ErroEcra(f"xrandr {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def tamanho_ecra():
    m = re.search(r"current (\d+) x (\d+)", xrandr("--query"))
    if not m:
        raise ErroEcra("não foi possível ler o tamanho do ecrã")
    return int(m.group(1)), int(m.group(2))


def listar_monitores():
    """[(nome, largura, altura, x, y)]"""
    monitors = []
    for line in xrandr("--listmonitors").splitlines()[1:]:
        m = re.search(r"\s([+*]*)(\S+)\s+(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)", line)
        if m:
            monitors.append((m.group(2), int(m.group(3)), int(m.group(4)),
                             int(m.group(5)), int(m.group(6))))
    return monitors


class EcraX11(EcraVirtual):
    name = "x11"
    description = "X11 com xrandr (experimental)"

    def __init__(self, spec):
        super().__init__(spec)
        self.original_size = None
        self.rect = None

    @classmethod
    def suportado(cls, env):
        if not env.x11_display:
            return False, "sem DISPLAY X11"
        if env.session_type == "wayland":
            return False, "sessão Wayland"
        if not shutil.which("xrandr"):
            return False, "xrandr não instalado"
        return True, "X11 com xrandr"

    def criar(self, on_ready):
        s = self.spec
        xrandr("--delmonitor", MONITOR_NAME, check=False)
        self.original_size = tamanho_ecra()
        monitors = listar_monitores()
        if monitors:
            minx = min(m[3] for m in monitors)
            miny = min(m[4] for m in monitors)
            maxx = max(m[3] + m[1] for m in monitors)
            maxy = max(m[4] + m[2] for m in monitors)
        else:
            minx, miny, (maxx, maxy) = 0, 0, self.original_size
        # em X11 não há coordenadas negativas: esquerda/acima ficam à direita
        x, y = (minx, maxy) if s.position == "below" else (maxx, miny)
        width = max(self.original_size[0], x + s.width)
        height = max(self.original_size[1], y + s.height)
        self.active = True
        xrandr("--fb", f"{width}x{height}")
        mm_w, mm_h = int(s.width * 0.2646), int(s.height * 0.2646)
        xrandr("--setmonitor", MONITOR_NAME, f"{s.width}/{mm_w}x{s.height}/{mm_h}+{x}+{y}", "none")
        self.rect = (x, y, s.width, s.height)
        on_ready(self.fonte_gst())

    def fonte_gst(self):
        x, y, w, h = self.rect
        return (f"ximagesrc startx={x} starty={y} endx={x + w - 1} endy={y + h - 1} "
                f"use-damage=false show-pointer=true ! video/x-raw,framerate={self.spec.fps}/1")

    def aplicar_posicao(self):
        return True, f"{MONITOR_NAME} em +{self.rect[0]}+{self.rect[1]}"

    def destruir(self):
        if not self.active:
            return
        xrandr("--delmonitor", MONITOR_NAME, check=False)
        if self.original_size:
            xrandr("--fb", f"{self.original_size[0]}x{self.original_size[1]}", check=False)
        self.active = False
