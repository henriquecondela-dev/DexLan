"""Detecta a distribuição, o tipo de sessão (Wayland/X11) e o ambiente gráfico.
Só usa a biblioteca padrão, para funcionar antes de haver dependências instaladas."""
import os
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass
class Ambiente:
    distro_id: str = "unknown"
    distro_like: list = field(default_factory=list)
    distro_name: str = "Linux"
    package_manager: str | None = None
    session_type: str = "unknown"
    desktop: str = "unknown"
    wayland_display: str | None = None
    x11_display: str | None = None
    has_mutter_screencast: bool = False

    def resumo(self):
        return (f"{self.distro_name} | sessão {self.session_type} | {self.desktop} | "
                f"pacotes: {self.package_manager or '?'}")


def ler_os_release():
    data = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path) as f:
                for line in f:
                    if "=" in line:
                        key, value = line.rstrip().split("=", 1)
                        data[key] = value.strip('"')
            break
        except OSError:
            continue
    return data


def gestor_pacotes():
    for pm in ("apt-get", "dnf", "pacman", "zypper", "apk"):
        if shutil.which(pm):
            return "apt" if pm == "apt-get" else pm
    return None


def bus_tem_nome(name):
    """Verifica se um serviço existe no D-Bus da sessão."""
    if not (os.environ.get("DBUS_SESSION_BUS_ADDRESS") or os.environ.get("XDG_RUNTIME_DIR")):
        return False
    commands = []
    if shutil.which("busctl"):
        commands.append(["busctl", "--user", "--no-pager", "--no-legend", "list"])
    if shutil.which("gdbus"):
        commands.append(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
                         "--object-path", "/org/freedesktop/DBus",
                         "--method", "org.freedesktop.DBus.ListNames"])
    for cmd in commands:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
            if out:
                return name in out
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def detectar():
    rel = ler_os_release()
    env = Ambiente(
        distro_id=rel.get("ID", "unknown"),
        distro_like=rel.get("ID_LIKE", "").split(),
        distro_name=rel.get("PRETTY_NAME", "Linux"),
        package_manager=gestor_pacotes(),
        wayland_display=os.environ.get("WAYLAND_DISPLAY"),
        x11_display=os.environ.get("DISPLAY"),
        desktop=os.environ.get("XDG_CURRENT_DESKTOP") or "unknown",
    )
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session in ("", "unknown"):
        session = "wayland" if env.wayland_display else "x11" if env.x11_display else "tty"
    env.session_type = session
    env.has_mutter_screencast = bus_tem_nome("org.gnome.Mutter.ScreenCast")
    return env
