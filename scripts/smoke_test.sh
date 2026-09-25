#!/usr/bin/env bash
# API smoke test against a running stack. Usage:
#   API=http://localhost:8000 EMAIL=analyst@example.org PASSWORD=... scripts/smoke_test.sh
set -euo pipefail
API="${API:-http://localhost:8000}"
: "${EMAIL:?set EMAIL}" "${PASSWORD:?set PASSWORD}"

check() { printf '%-48s' "$1"; shift; if "$@" >/dev/null; then echo ok; else echo FAIL; exit 1; fi; }

check "liveness /health"            curl -sf "$API/health"
check "readiness /api/v1/ready"      curl -sf "$API/api/v1/ready"
check "metrics /metrics"             curl -sf "$API/metrics"
check "events require auth (401)"    bash -c "[ \$(curl -s -o /dev/null -w '%{http_code}' $API/api/v1/events) = 401 ]"

TOKEN=$(curl -sf -X POST "$API/api/v1/auth/login" -H 'content-type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
H="Authorization: Bearer $TOKEN"

check "status + freshness"            curl -sf -H "$H" "$API/api/v1/status"
check "events list"                   curl -sf -H "$H" "$API/api/v1/events?limit=5"
check "events geojson (viewport)"     curl -sf -H "$H" "$API/api/v1/events/geojson?bbox=68,6,98,36&limit=100"
check "facilities"                    curl -sf -H "$H" "$API/api/v1/facilities?limit=5"
check "data sources"                  curl -sf -H "$H" "$API/api/v1/sources"
check "analytics summary"             curl -sf -H "$H" "$API/api/v1/analytics/summary"
REF=$(curl -sf -H "$H" "$API/api/v1/events?limit=1&sort=observations" | python -c 'import sys,json;d=json.load(sys.stdin)["items"];print(d[0]["public_id"] if d else "")')
if [ -n "$REF" ]; then
  check "event bundle $REF"           curl -sf -H "$H" "$API/api/v1/events/$REF"
  check "similar events"              curl -sf -H "$H" "$API/api/v1/events/$REF/similar"
else
  echo "no events yet — run: python -m app.cli ingest && python -m app.cli process"
fi
echo "smoke test passed"
