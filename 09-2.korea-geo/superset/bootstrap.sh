#!/usr/bin/env bash
# Superset 초기화 + 기동. 컨테이너 시작 시 1회 실행돼도 idempotent 하도록 || true 처리.
set -e

echo "[bootstrap] superset db upgrade ..."
superset db upgrade

echo "[bootstrap] create-admin (${ADMIN_USERNAME:-admin}) ..."
superset fab create-admin \
  --username "${ADMIN_USERNAME:-admin}" \
  --firstname Admin --lastname User \
  --email admin@example.com \
  --password "${ADMIN_PASSWORD:-admin}" || true

echo "[bootstrap] superset init (roles/perms) ..."
superset init

echo "[bootstrap] starting gunicorn on :8088 ..."
exec gunicorn \
  --bind 0.0.0.0:8088 \
  --workers 3 \
  --timeout 120 \
  --limit-request-line 0 \
  --limit-request-field_size 0 \
  "superset.app:create_app()"
