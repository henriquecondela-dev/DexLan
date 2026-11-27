# Como funciona


## Ecrã virtual

No GNOME o Mutter tem a API D-Bus `org.gnome.Mutter.ScreenCast`. O método
`Session.RecordVirtual` com `is-platform = true` cria um monitor virtual que o desktop
trata como um monitor normal, e devolve uma stream PipeWire com a imagem dele.

- A resolução é a que o GStreamer pede no `capsfilter`.
- A posição é definida com `org.gnome.Mutter.DisplayConfig.ApplyMonitorsConfig`.
- Quando a sessão termina, ou o programa fecha, o Mutter remove o monitor sozinho.

Em X11 usa-se `xrandr --setmonitor` e a captura é feita com `ximagesrc`.

Não é o mesmo que o *Ambiente de Trabalho Remoto* do GNOME (RDP): aí o outro computador
controla uma sessão. Aqui o outro computador só mostra a imagem.

## Vídeo

`pipewiresrc` → H.264 (`x264enc` com `tune=zerolatency`, ou VA-API) → rede → `avdec_h264` → janela.

Se a rede não acompanhar, o host descarta imagens até à próxima keyframe e pede uma nova.
Assim a imagem não acumula atraso nem fica corrompida.

## Rede

| | |
|---|---|
| Descoberta | broadcast UDP na porta 47800 |
| Ligação | TCP + TLS na porta 47801 (controlo e vídeo) |
| Emparelhamento | código de 6 dígitos mostrado no receiver; a prova (HMAC) inclui a impressão digital do certificado |
| Depois | token guardado (no receiver só o hash) |
| Queda de rede | o ecrã virtual fica activo 30 s enquanto tenta religar |

## Cabo directo

Perfil `DexLan-cabo` no NetworkManager:

- **automático:** `ipv4.method link-local`, endereços `169.254.x.x`;
- **manual:** `ipv4.method manual` com o IP e a máscara escolhidos;
- `never-default`: não passa a ser a rota da internet;
- `autoconnect no`: só é activado pelo DexLan;
- `permissions user:<utilizador>`: não precisa de administrador.

O perfil é activado quando há cabo ligado e, passados 8 segundos, ninguém deu endereço
(ou seja, do outro lado não há router).

## Interface

As janelas são páginas HTML (`dexlan/ui/web`) mostradas com WebKitGTK.

- A página fala com o Python com `enviar("accao", dados)`.
- O Python responde com `window.receber("evento", dados)`.
- O vídeo do receiver é mostrado pelo GStreamer numa janela GTK (`gtksink`).

## Limitações

- A API do Mutter é interna do GNOME e pode mudar entre versões.
- Em redes Wi-Fi fracas o vídeo pode atrasar; o cabo resolve.
- O modo X11 depende do gestor de janelas aceitar monitores do `xrandr --setmonitor`.
