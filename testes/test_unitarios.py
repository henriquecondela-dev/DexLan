"""Testes que não precisam de ecrã nem de rede.
Correr: python3 -m unittest discover -s testes
"""
import os
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()

from dexlan import cabo, dependencias, descoberta, seguranca, desinstalar  # noqa: E402
from dexlan.ambiente import Ambiente  # noqa: E402
from dexlan.protocolo import Canal  # noqa: E402


class TesteProtocolo(unittest.TestCase):
    def test_json_e_video(self):
        a, b = socket.socketpair()
        ca, cb = Canal(a), Canal(b)
        ca.enviar_json(t="hello", n=1)
        ca.enviar_video(123456, b"\x00\x00\x00\x01video")
        self.assertEqual(cb.receber(), ("json", {"t": "hello", "n": 1}))
        self.assertEqual(cb.receber(), ("video", (123456, b"\x00\x00\x00\x01video")))
        ca.close()
        with self.assertRaises(ConnectionError):
            cb.receber()
        cb.close()


class TesteSeguranca(unittest.TestCase):
    def test_prova_depende_do_certificado(self):
        proof = seguranca.prova_codigo("123456", "nonce", "fpA")
        self.assertTrue(seguranca.verificar_prova("123456", "nonce", "fpA", proof))
        self.assertFalse(seguranca.verificar_prova("123456", "nonce", "fpB", proof))
        self.assertFalse(seguranca.verificar_prova("654321", "nonce", "fpA", proof))

    def test_receiver_guarda_so_o_hash(self):
        trust = seguranca.ConfiancaReceiver()
        token = trust.add("host-1", "portatil")
        self.assertTrue(seguranca.ConfiancaReceiver().autorizado("host-1", token))
        self.assertFalse(seguranca.ConfiancaReceiver().autorizado("host-1", "errado"))
        with open(os.path.join(seguranca.pasta_config(), "trusted_hosts.json")) as f:
            self.assertNotIn(token, f.read())
        trust.revogar("host-1")
        self.assertFalse(seguranca.ConfiancaReceiver().autorizado("host-1", token))

    def test_codigo_tem_6_digitos(self):
        for _ in range(50):
            pin = seguranca.novo_codigo()
            self.assertTrue(len(pin) == 6 and pin.isdigit())

    def test_nome_e_o_do_computador(self):
        self.assertEqual(seguranca.identidade()["name"], socket.gethostname())


class TesteDescoberta(unittest.TestCase):
    def test_descoberta_local(self):
        port = 47999
        descoberta.Respondedor(lambda: {"name": "teste", "id": "abc", "port": 1}, port=port).start()
        found = descoberta.procurar(timeout=1.5, port=port, extra_targets=["127.0.0.1"])
        self.assertTrue(any(r["id"] == "abc" and "127.0.0.1" in r["ips"] for r in found))


class TesteDependencias(unittest.TestCase):
    def test_comando_para_cada_distro(self):
        for pm in ("apt", "dnf", "pacman", "zypper", "apk"):
            cmd, pkgs = dependencias.comando_instalar(pm, ["gtksink", "webkit"])
            self.assertTrue(cmd and pkgs, pm)

    def test_dependencias_por_papel(self):
        env = Ambiente(session_type="wayland")
        self.assertIn("pipewiresrc", dependencias.necessarias("host", env))
        self.assertNotIn("gtksink", dependencias.necessarias("host", env))
        self.assertIn("gtksink", dependencias.necessarias("receiver", env))


class TesteCabo(unittest.TestCase):
    def test_link_local(self):
        self.assertTrue(cabo.e_link_local("169.254.49.121"))
        self.assertFalse(cabo.e_link_local("192.168.1.20"))
        self.assertFalse(cabo.e_link_local("lixo"))

    def test_validar_ip_manual(self):
        self.assertEqual(cabo.validar_endereco("192.168.50.1", "255.255.255.0"), 24)
        self.assertEqual(cabo.validar_endereco("10.0.0.1", "255.255.255.252"), 30)
        for endereco, mascara in (("192.168.50.0", "255.255.255.0"), ("192.168.50.255", "255.255.255.0"),
                              ("192.168.50.300", "255.255.255.0"), ("192.168.50.1", "255.0.255.0")):
            with self.assertRaises(cabo.ErroCabo):
                cabo.validar_endereco(endereco, mascara)

    def test_guardar_definicoes(self):
        cabo.guardar_definicoes(modo="manual", endereco="192.168.50.2", mascara="255.255.255.0")
        self.assertEqual(cabo.definicoes()["endereco"], "192.168.50.2")
        with self.assertRaises(cabo.ErroCabo):
            cabo.guardar_definicoes(modo="manual", endereco="abc", mascara="255.255.255.0")
        cabo.guardar_definicoes(modo="auto")

    def test_espera_pelo_dhcp_antes_de_activar(self):
        chamadas = []
        original = cabo.ativar
        cabo.ativar = lambda dev: chamadas.append(dev)
        try:
            auto = cabo.CaboAutomatico()
            st = {"placas": [{"placa": "eth0", "cabo_ligado": True, "ipv4": [], "dexlan": False}]}
            auto._talvez_ativar(st)
            self.assertEqual(chamadas, [])
            auto._desde["eth0"] -= cabo.ESPERA_DHCP + 1
            auto._talvez_ativar(st)
            self.assertEqual(chamadas, ["eth0"])
            router = {"placas": [{"placa": "eth1", "cabo_ligado": True, "ipv4": ["10.0.0.5/24"],
                                   "dexlan": False}]}
            auto._talvez_ativar(router)
            self.assertEqual(chamadas, ["eth0"])
        finally:
            cabo.ativar = original


class TesteDesinstalar(unittest.TestCase):
    def test_tudo_inclui_definicoes(self):
        seguranca.identidade()
        normal = [d for d, _ in desinstalar.plano(tudo=False)]
        tudo = [d for d, _ in desinstalar.plano(tudo=True)]
        self.assertFalse(any("preferências" in d for d in normal))
        self.assertTrue(any("preferências" in d for d in tudo))


if __name__ == "__main__":
    unittest.main()
