from .base import EcraVirtual


class EcraTeste(EcraVirtual):
    """Não cria ecrã: envia uma imagem de teste. Serve para testar a rede."""
    name = "test"
    description = "imagem de teste"

    @classmethod
    def suportado(cls, env):
        return True, "sempre disponível"

    def criar(self, on_ready):
        self.active = True
        s = self.spec
        on_ready(f"videotestsrc is-live=true pattern=ball ! timeoverlay font-desc=\"Sans 36\" ! "
                 f"video/x-raw,width={s.width},height={s.height},framerate={s.fps}/1")

    def destruir(self):
        self.active = False
