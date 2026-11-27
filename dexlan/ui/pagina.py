"""Ponte entre o Python e as páginas HTML (WebKitGTK).

Página -> Python:  enviar("accao", {...})          chama funcao(accao, dados)
Python -> Página:  pagina.enviar("evento", {...}) chama window.receber(evento, dados)
"""
import json
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import GLib, WebKit2  # noqa: E402

PASTA_WEB = os.path.join(os.path.dirname(__file__), "web")
ICONE = os.path.join(os.path.dirname(__file__), "dexlan.svg")


class PaginaWeb:
    def __init__(self, pagina, funcao):
        self.funcao = funcao
        self.pronta = False
        self.fila = []
        manager = WebKit2.UserContentManager()
        manager.register_script_message_handler("dexlan")
        manager.connect("script-message-received::dexlan", self._on_message)
        self.view = WebKit2.WebView.new_with_user_content_manager(manager)
        settings = self.view.get_settings()
        settings.set_allow_file_access_from_file_urls(True)
        settings.set_enable_developer_extras(bool(os.environ.get("DEXLAN_DEV")))
        self.view.connect("context-menu", lambda *_: not os.environ.get("DEXLAN_DEV"))
        path = os.path.join(PASTA_WEB, pagina, "index.html")
        self.view.load_uri(GLib.filename_to_uri(path, None))

    def _on_message(self, _manager, result):
        try:
            msg = json.loads(result.get_js_value().to_string())
        except ValueError:
            return
        if msg.get("accao") == "pronto":
            self.pronta = True
            for evento, dados in self.fila:
                self.enviar(evento, dados)
            self.fila.clear()
        self.funcao(msg.get("accao"), msg.get("dados") or {})

    def enviar(self, evento, dados=None):
        if not self.pronta:
            self.fila.append((evento, dados))
            return
        script = f"window.receber({json.dumps(evento)}, {json.dumps(dados)})"
        self.view.evaluate_javascript(script, -1, None, None, None, None, None)


def por_icone(window):
    try:
        window.set_icon_from_file(ICONE)
    except GLib.Error:
        pass
