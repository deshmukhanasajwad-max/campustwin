#!/bin/sh
# Container entrypoint.
# - DATABASE_URL set  -> use that external PostgreSQL (persistent; recommended for production).
# - DATABASE_URL unset -> start a PostgreSQL inside the container so the app works out of the box.
#   Data in this mode lives on the container's disk and is reset on every redeploy/restart.
set -e
if [ -z "$DATABASE_URL" ]; then
  echo "[start] DATABASE_URL not set - starting embedded PostgreSQL (data is NOT persistent)"
  CL=$(pg_lsclusters -h | head -n 1)
  if [ -z "$CL" ]; then
    pg_createcluster "$(ls /usr/lib/postgresql | sort -V | tail -n 1)" main
    CL=$(pg_lsclusters -h | head -n 1)
  fi
  VER=$(echo "$CL" | awk '{print $1}'); NAME=$(echo "$CL" | awk '{print $2}')
  pg_ctlcluster "$VER" "$NAME" start -- -o "-c shared_buffers=32MB -c max_connections=30 -c fsync=off"
  i=0; until pg_isready -q -h localhost -p 5432 || [ $i -ge 40 ]; do i=$((i+1)); sleep 1; done
  su postgres -c "psql -qtAc \"SELECT 1 FROM pg_roles WHERE rolname='campustwin'\"" | grep -q 1 \
    || su postgres -c "psql -qc \"CREATE USER campustwin WITH PASSWORD 'campustwin'\""
  su postgres -c "psql -qtAc \"SELECT 1 FROM pg_database WHERE datname='campustwin'\"" | grep -q 1 \
    || su postgres -c "psql -qc \"CREATE DATABASE campustwin OWNER campustwin ENCODING 'UTF8' TEMPLATE template0\""
  export DATABASE_URL="postgresql+psycopg2://campustwin:campustwin@localhost:5432/campustwin"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
