"""Identidade, TLS e emparelhamento.

- O receiver tem um certificado TLS próprio; tudo vai cifrado.
- 1.ª ligação: o receiver mostra um código de 6 dígitos e o host envia
  HMAC(código, nonce + impressão digital do certificado). Assim a prova
  não serve a um atacante no meio com outro certificado.
- Depois fica um token: o receiver guarda só o hash, o host guarda o token
  (ficheiro com permissões 600, como as chaves SSH).
"""
import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import uuid


def pasta_config():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, "dexlan")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def ler(name, default):
    try:
        with open(os.path.join(pasta_config(), name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def guardar(name, data):
    path = os.path.join(pasta_config(), name)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def identidade():
    ident = ler("identity.json", None)
    if not ident:
        ident = {"id": str(uuid.uuid4()), "name": socket.gethostname()}
        guardar("identity.json", ident)
    ident["name"] = socket.gethostname()  # o nome segue sempre o do computador
    return ident


# ---------- TLS

def garantir_certificado():
    cert = os.path.join(pasta_config(), "receiver-cert.pem")
    key = os.path.join(pasta_config(), "receiver-key.pem")
    if os.path.exists(cert) and os.path.exists(key):
        return cert, key
    if not shutil.which("openssl"):
        raise RuntimeError("openssl não encontrado (corre 'dexlan setup')")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt",
                    "ec_paramgen_curve:prime256v1", "-nodes", "-days", "3650",
                    "-subj", f"/CN=dexlan-{socket.gethostname()}",
                    "-keyout", key, "-out", cert], check=True, capture_output=True)
    os.chmod(key, 0o600)
    return cert, key


def impressao_der(der):
    return hashlib.sha256(der).hexdigest()


def impressao_certificado(path):
    with open(path) as f:
        return impressao_der(ssl.PEM_cert_to_DER_cert(f.read()))


def contexto_servidor(cert, key):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


def contexto_cliente():
    # sem autoridade certificadora: a confiança vem do código + certificado guardado
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ---------- código de emparelhamento

def novo_codigo():
    return f"{secrets.randbelow(1_000_000):06d}"


def prova_codigo(pin, nonce, fingerprint):
    return hmac.new(pin.encode(), (nonce + fingerprint).encode(), hashlib.sha256).hexdigest()


def verificar_prova(pin, nonce, fingerprint, proof):
    return hmac.compare_digest(prova_codigo(pin, nonce, fingerprint), proof)


def sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


class ConfiancaReceiver:
    """Hosts autorizados (lado do receiver)."""
    FILE = "trusted_hosts.json"

    def __init__(self):
        self.data = ler(self.FILE, {})

    def autorizado(self, host_id, token):
        entry = self.data.get(host_id)
        return bool(entry and token and hmac.compare_digest(entry["token_sha256"], sha(token)))

    def add(self, host_id, name):
        token = secrets.token_hex(32)
        self.data[host_id] = {"name": name, "token_sha256": sha(token)}
        guardar(self.FILE, self.data)
        return token

    def revogar(self, host_id=None):
        if host_id is None:
            self.data = {}
        else:
            self.data.pop(host_id, None)
        guardar(self.FILE, self.data)


class ReceiversConhecidos:
    """Receivers emparelhados (lado do host)."""
    FILE = "known_receivers.json"

    def __init__(self):
        self.data = ler(self.FILE, {})

    def get(self, receiver_id):
        return self.data.get(receiver_id)

    def add(self, receiver_id, name, fingerprint, token):
        self.data[receiver_id] = {"name": name, "fingerprint": fingerprint, "token": token}
        guardar(self.FILE, self.data)

    def revogar(self, receiver_id=None):
        if receiver_id is None:
            self.data = {}
        else:
            self.data.pop(receiver_id, None)
        guardar(self.FILE, self.data)
