#!/usr/bin/env bash
# Check that the backend starts, serves the interface, and enforces the
# session token on the API and the WebSocket.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.toolchain/venv/bin/python"
LOG=$(mktemp)
export PHONEVITALS_TOKEN="smoke-$RANDOM$RANDOM"

"$PY" "$ROOT/backend/main.py" "$@" >"$LOG" 2>&1 &
PID=$!
trap 'kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null; rm -f "$LOG"' EXIT

ADDR=""
for _ in $(seq 1 60); do
  ADDR=$(sed -n 's/^PHONEVITALS_LISTENING //p' "$LOG")
  [ -n "$ADDR" ] && break
  sleep 0.5
done
[ -n "$ADDR" ] || { echo "backend did not start:"; cat "$LOG"; exit 1; }
URL="http://$ADDR"
COOKIE="phonevitals_session=$PHONEVITALS_TOKEN"

echo "=== listening on $ADDR ==="
echo
echo "=== access control ==="
curl -s -o /dev/null -w "  /api/health  (no token)  →  HTTP %{http_code}  (expect 200)\n" "$URL/api/health"
curl -s -o /dev/null -w "  /api/status  (no token)  →  HTTP %{http_code}  (expect 401)\n" "$URL/api/status"
curl -s -o /dev/null -w "  /api/status  (foreign Host)  →  HTTP %{http_code}  (expect 403)\n" \
  -H "Host: example.com" -b "$COOKIE" "$URL/api/status"
curl -s -o /dev/null -w "  /?token=…  →  HTTP %{http_code}  (expect 303)\n" "$URL/?token=$PHONEVITALS_TOKEN"
echo
echo "=== /api/status ==="
curl -s -b "$COOKIE" "$URL/api/status"; echo
echo
echo "=== static resources ==="
# The bundle names carry a content hash: take them from the page itself.
assets=$(curl -s "$URL/" | grep -o 'assets/[^"]*' | sort -u)
[ -n "$assets" ] || echo "  no assets referenced: is ui/dist built? (cd ui && npm run build)"
for path in "" $assets; do
  curl -s -o /dev/null -w "  /$path  →  HTTP %{http_code}  %{size_download} bytes\n" "$URL/$path"
done
echo
echo "=== /api/report ==="
curl -s -o /dev/null -w "  HTTP %{http_code}  (404 without an analysis, 200 with --demo)\n" \
  -b "$COOKIE" "$URL/api/report"
echo
echo "=== WebSocket ==="
"$PY" - "$ADDR" "$COOKIE" <<'PY'
import asyncio, json, sys
import websockets

async def main(addr, cookie):
    uri = f"ws://{addr}/ws"
    async with websockets.connect(uri) as ws:
        try:
            await asyncio.wait_for(ws.recv(), timeout=8)
            print("  without cookie: NOT REJECTED")
        except websockets.ConnectionClosed as exc:
            print(f"  without cookie: closed with code {exc.rcvd.code} (expect 4401)")
    async with websockets.connect(uri, additional_headers={"Cookie": cookie}) as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
        print(f"  first message: type={msg.get('type')}")
        print(f"  adb: {msg.get('adb')}")
        print(f"  devices: {msg.get('devices')}")
        await ws.send(json.dumps({"command": "ping"}))
        pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
        print(f"  ping reply: type={pong.get('type')}")

asyncio.run(main(sys.argv[1], sys.argv[2]))
PY
echo
echo "=== backend log ==="
grep -v '^PHONEVITALS_LISTENING' "$LOG" | sed 's/^/  /' | head -20
grep -qv '^PHONEVITALS_LISTENING' "$LOG" || echo "  (no errors)"
