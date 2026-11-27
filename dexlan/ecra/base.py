from dataclasses import dataclass


class ErroEcra(RuntimeError):
    pass


@dataclass
class EspecEcra:
    width: int = 1280
    height: int = 720
    fps: int = 30
    position: str = "right"  # right | left | above | below


class EcraVirtual:
    """Base dos ecrãs virtuais. Cada sistema gráfico tem a sua implementação."""
    name = "base"
    description = ""

    def __init__(self, spec):
        self.spec = spec
        self.active = False

    @classmethod
    def suportado(cls, env):
        """Devolve (suportado, motivo)."""
        raise NotImplementedError

    def criar(self, on_ready):
        """Cria o ecrã e chama on_ready(fonte_gstreamer) quando estiver pronto."""
        raise NotImplementedError

    def aplicar_posicao(self):
        return True, ""

    def destruir(self):
        raise NotImplementedError

    def descrever(self):
        return f"{self.spec.width}x{self.spec.height}@{self.spec.fps} ({self.spec.position})"
