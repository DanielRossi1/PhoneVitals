#!/usr/bin/env bash
# Regenerate the five store screenshots in docs/screenshots from demo mode:
# simulated data only, so no real IMEI, serial or network name can leak.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/docs/screenshots}"
LOG=$(mktemp)
mkdir -p "$OUT"
export DISPLAY="${DISPLAY:-:0}"
export PHONEVITALS_TOKEN="shots-$RANDOM$RANDOM"

(cd "$ROOT/ui" && PATH="$ROOT/.toolchain/node/bin:$PATH" npm run --silent build) || exit 1

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

STEPS=$(python3 - "$OUT" <<'PY'
import json, sys
out = sys.argv[1]
theme = lambda t: {"js": f"document.documentElement.dataset.theme = {json.dumps(t)}"}
page = lambda p: {"js": f"location.hash = {json.dumps(p)}"}
click = lambda text: {"js": "[...document.querySelectorAll('button')]"
                      f".find((b) => b.textContent.includes({json.dumps(text)}))?.click()"}
open_test = lambda title: {"js": "[...document.querySelectorAll('.test')]"
                           f".find((t) => t.textContent.includes({json.dumps(title)}))"
                           "?.querySelector('button').click()"}
# Every automatic test has finished: the run button is enabled again and
# none of them is still running.
passed = ("!document.querySelector('.summary button')?.disabled"
          " && [...document.querySelectorAll('.test .tag')].filter((t) => t.textContent.includes('Passed')).length >= 11")
print(json.dumps([
    {"wait": "!!document.querySelector('.topbar h1')"},
    theme("dark"), page("overview"), {"sleep": 1200}, {"shot": f"{out}/1-overview.png"},
    page("live"), {"sleep": 30000}, {"shot": f"{out}/2-live-sensors.png"},
    theme("light"), page("tests"), {"sleep": 500}, click("Run automatic tests"),
    {"wait": passed, "timeout": 120000}, {"sleep": 800}, {"shot": f"{out}/3-tests.png"},
    page("authenticity"), {"sleep": 1000}, {"shot": f"{out}/4-authenticity.png"},
    theme("dark"), page("tests"), {"sleep": 500}, open_test("Accelerometer and gyroscope"),
    {"sleep": 1800}, {"shot": f"{out}/5-guided-test.png"},
]))
PY
)

URL="http://$ADDR/?token=$PHONEVITALS_TOKEN" STEPS="$STEPS" \
  "$ROOT/ui/node_modules/.bin/electron" "$ROOT/scripts/store_screenshots" --no-sandbox 2>&1 \
  | grep -E "^(saved|step failed)"
