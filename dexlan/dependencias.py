"""Verifica e instala as dependências.

Verifica capacidades (ex.: existe o elemento 'x264enc'?) em vez de nomes de pacotes,
porque os nomes mudam de distro para distro. Só usa a biblioteca padrão.
"""
import os
import shutil
import subprocess
import sys

PACOTES = {
    "python-gi": {"apt": ["python3-gi"], "dnf": ["python3-gobject"], "pacman": ["python-gobject"],
                  "zypper": ["python3-gobject"], "apk": ["py3-gobject3"]},
    "gstreamer": {"apt": ["gir1.2-gstreamer-1.0", "gir1.2-gst-plugins-base-1.0",
                          "gstreamer1.0-plugins-base", "gstreamer1.0-tools"],
                  "dnf": ["gstreamer1", "gstreamer1-plugins-base"],
                  "pacman": ["gstreamer", "gst-plugins-base"],
                  "zypper": ["typelib-1_0-Gst-1_0", "gstreamer-plugins-base"],
                  "apk": ["gstreamer", "gst-plugins-base"]},
    "h264parse": {"apt": ["gstreamer1.0-plugins-bad"], "dnf": ["gstreamer1-plugins-bad-free"],
                  "pacman": ["gst-plugins-bad"], "zypper": ["gstreamer-plugins-bad"],
                  "apk": ["gst-plugins-bad"]},
    "h264-encoder": {"apt": ["gstreamer1.0-plugins-ugly"], "dnf": ["gstreamer1-plugin-openh264"],
                     "pacman": ["gst-plugins-ugly"], "zypper": ["gstreamer-plugins-ugly"],
                     "apk": ["gst-plugins-ugly"]},
    "h264-decoder": {"apt": ["gstreamer1.0-libav"], "dnf": ["gstreamer1-plugin-libav"],
                     "pacman": ["gst-libav"], "zypper": ["gstreamer-plugins-libav"],
                     "apk": ["gst-libav"]},
    "gtk3": {"apt": ["gir1.2-gtk-3.0"], "dnf": ["gtk3"], "pacman": ["gtk3"],
             "zypper": ["typelib-1_0-Gtk-3_0"], "apk": ["gtk+3.0"]},
    "webkit": {"apt": ["gir1.2-webkit2-4.1"], "dnf": ["webkit2gtk4.1"], "pacman": ["webkit2gtk-4.1"],
               "zypper": ["typelib-1_0-WebKit2-4_1"], "apk": ["webkit2gtk-4.1"]},
    "gtksink": {"apt": ["gstreamer1.0-gtk3"], "dnf": ["gstreamer1-plugins-good-gtk"],
                "pacman": ["gst-plugins-good"], "zypper": ["gstreamer-plugins-good-gtk"],
                "apk": ["gst-plugins-good-gtk"]},
    "pipewiresrc": {"apt": ["gstreamer1.0-pipewire"], "dnf": ["pipewire-gstreamer"],
                    "pacman": ["gst-plugin-pipewire"], "zypper": ["gstreamer-plugin-pipewire"],
                    "apk": ["pipewire-gstreamer"]},
    "x11-capture": {"apt": ["gstreamer1.0-plugins-good", "gstreamer1.0-x", "x11-xserver-utils"],
                    "dnf": ["gstreamer1-plugins-good", "xrandr"],
                    "pacman": ["gst-plugins-good", "xorg-xrandr"],
                    "zypper": ["gstreamer-plugins-good", "xrandr"],
                    "apk": ["gst-plugins-good", "xrandr"]},
    "openssl": {pm: ["openssl"] for pm in ("apt", "dnf", "pacman", "zypper", "apk")},
}

DESCRICAO = {
    "python-gi": "Python GObject",
    "gstreamer": "GStreamer",
    "h264parse": "h264parse",
    "h264-encoder": "codificador H.264",
    "h264-decoder": "descodificador H.264",
    "gtk3": "GTK 3",
    "webkit": "WebKitGTK (interface)",
    "gtksink": "gtksink (vídeo na janela)",
    "pipewiresrc": "pipewiresrc (captura no GNOME Wayland)",
    "x11-capture": "ximagesrc + xrandr (X11)",
    "openssl": "openssl",
}


def testar():
    """Testa o que existe neste Python/GStreamer."""
    res = {"openssl": shutil.which("openssl") is not None}
    try:
        import gi
    except ImportError:
        res["python-gi"] = False
        return res
    res["python-gi"] = True
    try:
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)

        def tem(e):
            return Gst.ElementFactory.find(e) is not None
        res["gstreamer"] = all(tem(e) for e in ("videoconvert", "videoscale", "appsrc", "appsink"))
        res["h264parse"] = tem("h264parse")
        res["h264-encoder"] = tem("x264enc") or tem("openh264enc")
        res["h264-decoder"] = tem("avdec_h264") or tem("openh264dec")
        res["gtksink"] = tem("gtksink")
        res["pipewiresrc"] = tem("pipewiresrc")
        res["x11-capture"] = tem("ximagesrc") and shutil.which("xrandr") is not None
        res["hw-encoder"] = tem("vah264enc") or tem("vah264lpenc")
    except (ValueError, ImportError):
        res["gstreamer"] = False
    for cap, (lib, version) in {"gtk3": ("Gtk", "3.0"), "webkit": ("WebKit2", "4.1")}.items():
        try:
            gi.require_version(lib, version)
            res[cap] = True
        except ValueError:
            res[cap] = False
    return res


def necessarias(papel, env):
    req = ["python-gi", "gstreamer", "h264parse", "gtk3", "webkit"]
    if papel in ("host", "todos"):
        req.append("h264-encoder")
        if env.session_type == "wayland" or papel == "todos":
            req.append("pipewiresrc")
        if env.session_type == "x11" or papel == "todos":
            req.append("x11-capture")
    if papel in ("receiver", "todos"):
        req += ["h264-decoder", "gtksink", "openssl"]
    return req


def verificar(papel, env):
    res = testar()
    return {cap: bool(res.get(cap)) for cap in necessarias(papel, env)}, res.get("hw-encoder", False)


def comando_instalar(pm, caps):
    pkgs = []
    for cap in caps:
        for pkg in PACOTES[cap].get(pm, []):
            if pkg not in pkgs:
                pkgs.append(pkg)
    base = {"apt": ["apt-get", "install", "-y"], "dnf": ["dnf", "install", "-y"],
            "pacman": ["pacman", "-S", "--needed", "--noconfirm"],
            "zypper": ["zypper", "--non-interactive", "install"], "apk": ["apk", "add"]}[pm]
    return (base + pkgs if pkgs else None), pkgs


def como_root(cmd):
    if os.geteuid() == 0:
        return cmd
    if not sys.stdin.isatty() and shutil.which("pkexec"):  # aberto pelo menu: password numa janela
        return ["pkexec"] + cmd
    if shutil.which("sudo"):
        return ["sudo"] + cmd
    if shutil.which("pkexec"):
        return ["pkexec"] + cmd
    raise RuntimeError("é preciso sudo ou pkexec para instalar")


def instalar(pm, caps):
    cmd, _ = comando_instalar(pm, caps)
    if not cmd:
        return False
    if pm == "apt":
        subprocess.run(como_root(["apt-get", "update"]), check=False)
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    return subprocess.run(como_root(cmd), env=env).returncode == 0


def estado_firewall():
    """('ufw' | 'firewalld' | None, activa?)"""
    if shutil.which("ufw"):
        try:
            out = subprocess.run(como_root(["ufw", "status"]), capture_output=True, text=True,
                                 timeout=10).stdout
            return "ufw", "Status: active" in out
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            return "ufw", False
    if shutil.which("firewall-cmd"):
        r = subprocess.run(["firewall-cmd", "--state"], capture_output=True, text=True)
        return "firewalld", r.stdout.strip() == "running"
    return None, False


def abrir_firewall(kind, papel):
    from . import CONTROL_PORT, DISCOVERY_PORT
    if kind == "ufw":
        cmds = []
        if papel in ("receiver", "todos"):
            cmds += [["ufw", "allow", f"{DISCOVERY_PORT}/udp"], ["ufw", "allow", f"{CONTROL_PORT}/tcp"]]
        if papel in ("host", "todos"):  # respostas da descoberta vêm da porta 47800
            cmds.append(["ufw", "allow", "proto", "udp", "from", "any", "port", str(DISCOVERY_PORT)])
    else:
        cmds = [["firewall-cmd", "--permanent", f"--add-port={DISCOVERY_PORT}/udp"],
                ["firewall-cmd", "--permanent", f"--add-port={CONTROL_PORT}/tcp"],
                ["firewall-cmd", "--reload"]]
    for cmd in cmds:
        subprocess.run(como_root(cmd), check=False)
