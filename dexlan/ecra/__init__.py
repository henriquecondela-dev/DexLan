from .base import ErroEcra, EspecEcra, EcraVirtual
from .gnome import EcraGnome
from .teste import EcraTeste
from .x11 import EcraX11

BACKENDS = [EcraGnome, EcraX11]
ALL = {b.name: b for b in BACKENDS + [EcraTeste]}

__all__ = ["ErroEcra", "EspecEcra", "EcraVirtual", "BACKENDS", "ALL", "verificar_todos", "escolher"]


def verificar_todos(env):
    return [(b, *b.suportado(env)) for b in BACKENDS]


def escolher(env, forced=None):
    if forced:
        backend = ALL.get(forced)
        if not backend:
            raise ErroEcra(f"backend desconhecido: {forced}")
        ok, why = backend.suportado(env)
        if not ok:
            raise ErroEcra(f"backend '{forced}' não funciona aqui: {why}")
        return backend
    for backend in BACKENDS:
        if backend.suportado(env)[0]:
            return backend
    reasons = "; ".join(f"{b.name}: {why}" for b, _, why in verificar_todos(env))
    raise ErroEcra(f"Este ambiente não permite criar um ecrã virtual ({reasons}).")
