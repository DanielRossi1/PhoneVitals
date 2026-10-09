#!/usr/bin/env bash
# Start the app in demo mode and capture every tab, to check interface
# rendering without a phone. Optional arguments: output directory,
# WIDTHxHEIGHT, and theme (light or dark).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTDIR="${1:-${TMPDIR:-/tmp}/phonevitals-shots}"
SIZE="${2:-}"
export PHONEVITALS_THEME="${3:-}"
LOG=$(mktemp)

mkdir -p "$OUTDIR"
export DISPLAY="${DISPLAY:-:0}"
export PATH="$ROOT/.toolchain/node/bin:$PATH"
export PHONEVITALS_TOKEN="demo-$RANDOM$RANDOM"

"$ROOT/.toolchain/venv/bin/python" "$ROOT/backend/main.py" --demo >"$LOG" 2>&1 &
BACKEND=$!
trap 'kill "$BACKEND" 2>/dev/null; wait "$BACKEND" 2>/dev/null; rm -f "$LOG"' EXIT

ADDR=""
for _ in $(seq 1 60); do
  ADDR=$(sed -n 's/^PHONEVITALS_LISTENING //p' "$LOG")
  [ -n "$ADDR" ] && break
  sleep 0.5
done
[ -n "$ADDR" ] || { echo "backend did not start:"; cat "$LOG"; exit 1; }

cd "$ROOT/ui"
for tab in overview authenticity health tests live specs raw; do
  PHONEVITALS_BACKEND_URL="http://$ADDR/?token=$PHONEVITALS_TOKEN" \
  PHONEVITALS_TAB="$tab" \
  "$ROOT/ui/node_modules/.bin/electron" . --no-sandbox \
      --screenshot="$OUTDIR/$tab.png,3${SIZE:+,$SIZE}" >/dev/null 2>&1
  echo "  ✓ $tab"
done

echo "screenshots in $OUTDIR"
