#!/usr/bin/env bash
# Lançador do DexLan: escolhe um Python com PyGObject e instala o que faltar.
set -euo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
PASTA="$(dirname "$SELF")"
export DEXLAN_LAUNCHER="$SELF"
export PYTHONPATH="$PASTA${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1

procurar_python() {
  local py
  for py in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c "import gi" >/dev/null 2>&1; then
      echo "$py"
      return 0
    fi
  done
  return 1
}

papel_de() {
  case "$1" in
    app|host) echo host ;;
    receiver) echo receiver ;;
  esac
}

PY="$(procurar_python || true)"
PAPEL="$(papel_de "${1:-}")"

if [[ -z "$PY" ]]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 não encontrado. Instala-o com o gestor de pacotes da distribuição." >&2
    exit 1
  fi
  PY=python3
  if [[ -n "$PAPEL" ]]; then
    echo "Faltam dependências. A verificar o sistema..."
    python3 -m dexlan setup --role "$PAPEL" || exit 1
    PY="$(procurar_python)" || { echo "PyGObject continua em falta." >&2; exit 1; }
  fi
fi

if [[ -n "$PAPEL" ]] && ! "$PY" -m dexlan doctor --role "$PAPEL" >/dev/null 2>&1; then
  "$PY" -m dexlan doctor --role "$PAPEL" || true
  resposta=S
  [[ -t 0 ]] && read -r -p "Instalar o que falta agora? [S/n] " resposta
  [[ "$resposta" =~ ^[nN] ]] && exit 1
  "$PY" -m dexlan setup --role "$PAPEL" -y || exit 1
  PY="$(procurar_python)"
fi

exec "$PY" -m dexlan "$@"
