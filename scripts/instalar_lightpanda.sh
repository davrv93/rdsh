#!/usr/bin/env bash
# Descarga el binario de Lightpanda para este sistema en ./bin/lightpanda.
#
#   bash scripts/instalar_lightpanda.sh
#
# Lightpanda es el navegador que usa el motor de pruebas unitarias del frontend.
# No se versiona en el repositorio porque pesa ~80 MB.
set -euo pipefail
cd "$(dirname "$0")/.."

SISTEMA="$(uname -s)"
ARQUITECTURA="$(uname -m)"
BASE="https://github.com/lightpanda-io/browser/releases/download/nightly"

case "${SISTEMA}-${ARQUITECTURA}" in
  Darwin-arm64)  ARCHIVO="lightpanda-aarch64-macos" ;;
  Linux-x86_64)  ARCHIVO="lightpanda-x86_64-linux" ;;
  Linux-aarch64) ARCHIVO="lightpanda-aarch64-linux" ;;
  *)
    echo "Sin binario para ${SISTEMA}-${ARQUITECTURA}."
    echo "Alternativas: usar Docker (docker compose --profile test up lightpanda)"
    echo "o correr el motor con Chromium (MOTOR_PRUEBAS=chromium npm run test:unit)."
    exit 1
    ;;
esac

mkdir -p bin
echo "==> Descargando ${ARCHIVO}"
curl -fL --progress-bar -o bin/lightpanda "${BASE}/${ARCHIVO}"
chmod +x bin/lightpanda
# macOS marca los binarios descargados; sin esto Gatekeeper los bloquea
xattr -d com.apple.quarantine bin/lightpanda 2>/dev/null || true

echo "==> Instalado: $(./bin/lightpanda version)"
echo "Ahora: npm run test:unit"
