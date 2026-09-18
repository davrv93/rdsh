#!/usr/bin/env bash
# Prepara un Redshift real: esquema, usuario de solo lectura y carga de datos.
#
#   WAREHOUSE_HOST=mi-wg.123456789012.us-east-1.redshift-serverless.amazonaws.com \
#   WAREHOUSE_PORT=5439 \
#   WAREHOUSE_DB=analytics \
#   WAREHOUSE_ADMIN_USER=optimiza_admin \
#   WAREHOUSE_ADMIN_PASSWORD='...' \
#   REDSHIFT_RO_PASSWORD='...' \
#   bash infra/bootstrap_redshift.sh
set -euo pipefail
cd "$(dirname "$0")/.."

: "${WAREHOUSE_HOST:?Falta WAREHOUSE_HOST}"
: "${WAREHOUSE_ADMIN_PASSWORD:?Falta WAREHOUSE_ADMIN_PASSWORD}"
export WAREHOUSE_PORT="${WAREHOUSE_PORT:-5439}"
export WAREHOUSE_DB="${WAREHOUSE_DB:-analytics}"
export WAREHOUSE_ADMIN_USER="${WAREHOUSE_ADMIN_USER:-optimiza_admin}"
export REDSHIFT_SCHEMA="${REDSHIFT_SCHEMA:-analytics}"
export REDSHIFT_USER="${REDSHIFT_USER:-optimiza_ro}"
RO_PASSWORD="${REDSHIFT_RO_PASSWORD:-Optimiza_ro_2025}"

echo "==> Creando esquema y usuario de solo lectura en ${WAREHOUSE_HOST}"
PGPASSWORD="${WAREHOUSE_ADMIN_PASSWORD}" psql \
  -h "${WAREHOUSE_HOST}" -p "${WAREHOUSE_PORT}" -U "${WAREHOUSE_ADMIN_USER}" -d "${WAREHOUSE_DB}" \
  -v ON_ERROR_STOP=1 <<SQL
CREATE SCHEMA IF NOT EXISTS ${REDSHIFT_SCHEMA};
CREATE USER ${REDSHIFT_USER} PASSWORD '${RO_PASSWORD}';
GRANT USAGE ON SCHEMA ${REDSHIFT_SCHEMA} TO ${REDSHIFT_USER};
SQL

echo "==> Cargando los datos (crea las tablas y otorga SELECT)"
docker compose run --rm --no-deps \
  -e WAREHOUSE_HOST -e WAREHOUSE_PORT -e WAREHOUSE_DB \
  -e WAREHOUSE_ADMIN_USER -e WAREHOUSE_ADMIN_PASSWORD \
  -e REDSHIFT_SCHEMA -e REDSHIFT_USER \
  warehouse-loader

echo
echo "Listo. Pon esto en tu .env:"
echo "  OPTIMIZA_SOURCE_MODE=redshift"
echo "  REDSHIFT_HOST=${WAREHOUSE_HOST}"
echo "  REDSHIFT_PORT=${WAREHOUSE_PORT}"
echo "  REDSHIFT_DB=${WAREHOUSE_DB}"
echo "  REDSHIFT_USER=${REDSHIFT_USER}"
echo "  REDSHIFT_PASSWORD=${RO_PASSWORD}"
echo "  REDSHIFT_SCHEMA=${REDSHIFT_SCHEMA}"
echo
echo "Después:  docker compose up -d app"
