#!/usr/bin/env bash
# Instala o DexLan para o utilizador actual (~/.local).
#
#   ./install.sh                         host e receiver
#   ./install.sh host | receiver         só o necessário para um deles
#   ./install.sh --uninstall             remove o programa
#   ./install.sh --uninstall --purge     remove também definições e emparelhamentos
set -euo pipefail
PAPEL="${1:-all}"
ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESTINO="${XDG_DATA_HOME:-$HOME/.local/share}/dexlan"
BIN="$HOME/.local/bin"
ATALHOS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

if [[ "$PAPEL" == "--uninstall" ]]; then
  shift
  PYTHONPATH="$ORIGEM" exec python3 -m dexlan uninstall "$@"
fi

echo "A copiar para $DESTINO"
mkdir -p "$DESTINO" "$BIN" "$ATALHOS"
rm -rf "$DESTINO/dexlan"
cp -r "$ORIGEM/dexlan" "$ORIGEM/dexlan.sh" "$ORIGEM/README.md" "$ORIGEM/LICENSE" "$DESTINO/"
chmod +x "$DESTINO/dexlan.sh"
ln -sf "$DESTINO/dexlan.sh" "$BIN/dexlan"

ICONE="$DESTINO/dexlan/ui/dexlan.svg"
cat > "$ATALHOS/dexlan.desktop" <<FIM
[Desktop Entry]
Type=Application
Name=DexLan
Comment=Estender o ecrã para outro computador
Exec=$BIN/dexlan app
Icon=$ICONE
Categories=Utility;Network;
FIM
cat > "$ATALHOS/dexlan-receiver.desktop" <<FIM
[Desktop Entry]
Type=Application
Name=DexLan Receiver
Comment=Usar este computador como ecrã de outro
Exec=$BIN/dexlan receiver
Icon=$ICONE
Categories=Utility;Network;
FIM

echo "A verificar dependências ($PAPEL)"
"$DESTINO/dexlan.sh" setup --role "$PAPEL" || true

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo; echo "Adiciona ~/.local/bin ao PATH:  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc" ;;
esac
echo
echo "Instalado. No menu de aplicações:"
echo "  DexLan            no computador principal"
echo "  DexLan Receiver   no computador que serve de ecrã"
