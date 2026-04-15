#!/bin/bash
# Smoke test for the monitoring stack.
# Starts stack, verifies data flow, tears down.
set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$COMPOSE_DIR"

cleanup() {
    echo "[cleanup] Stopping stack..."
    docker compose down --timeout 10 2>/dev/null || true
}
trap cleanup EXIT

echo "=== Monitoring Stack Smoke Test ==="

echo "[1/7] Starting stack..."
docker compose up -d

echo "[2/7] Waiting for TimescaleDB..."
for i in $(seq 1 30); do
    if docker exec breakpoint-timescaledb pg_isready -U vector -d monitoring &>/dev/null; then
        echo "  TimescaleDB ready"
        break
    fi
    [ "$i" -eq 30 ] && { echo "FAIL: TimescaleDB not ready"; exit 1; }
    sleep 2
done

echo "[3/7] Waiting for Ingest service..."
for i in $(seq 1 20); do
    if curl -sf http://localhost:8087/health &>/dev/null; then
        echo "  Ingest ready"
        break
    fi
    [ "$i" -eq 20 ] && { echo "FAIL: Ingest not ready"; exit 1; }
    sleep 2
done

echo "[4/7] Waiting for Grafana..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:3333/api/health &>/dev/null; then
        echo "  Grafana ready"
        break
    fi
    [ "$i" -eq 30 ] && { echo "FAIL: Grafana not ready"; exit 1; }
    sleep 2
done

echo "[5/7] Waiting for Vector..."
for i in $(seq 1 20); do
    if curl -sf http://localhost:8686/health &>/dev/null; then
        echo "  Vector ready"
        break
    fi
    [ "$i" -eq 20 ] && { echo "FAIL: Vector not ready"; exit 1; }
    sleep 2
done

echo "[6/7] Waiting for data (30s)..."
sleep 30

METRIC_COUNT=$(docker exec breakpoint-timescaledb psql -U vector -d monitoring -t \
    -c "SELECT count(*) FROM metrics;" 2>/dev/null | tr -d ' ')
echo "  Metrics rows: $METRIC_COUNT"
[ "${METRIC_COUNT:-0}" -gt 0 ] || { echo "FAIL: No metrics in database"; exit 1; }

echo "[7/7] Checking Grafana datasource..."
DS_COUNT=$(curl -sf http://localhost:3333/api/datasources \
    -H "Authorization: Basic $(echo -n admin:$(grep '^GRAFANA_ADMIN_PASSWORD=' .env | cut -d= -f2-) | base64)" \
    2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
[ "${DS_COUNT:-0}" -gt 0 ] || { echo "FAIL: No datasources in Grafana"; exit 1; }
echo "  Datasources: $DS_COUNT"

echo ""
echo "=== SMOKE TEST PASSED ==="
