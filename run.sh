#!/usr/bin/env bash
# Start PhoneVitals from a source checkout.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TC="$ROOT/.toolchain"
ELECTRON="$ROOT/ui/node_modules/.bin/electron"

missing=0
check() {
  if [ -e "$2" ]; then
    echo "  ✓ $1"
  else
    echo "  ✗ $1 not found ($2)"
    missing=1
  fi
}

echo "Checking the environment:"
if [ -x "$TC/platform-tools/adb" ] || command -v adb >/dev/null; then
  echo "  ✓ adb"
else
  echo "  ✗ adb not found (neither in $TC/platform-tools nor on PATH)"
  missing=1
fi
check "Python environment" "$TC/venv/bin/python"
check "Electron"           "$ELECTRON"
check "Svelte toolchain"   "$ROOT/ui/node_modules/.bin/vite"
check "on-device agent"    "$ROOT/backend/data/pvagent.dex"

if [ "$missing" = "1" ]; then
  echo
  echo "Incomplete environment. Run, in order:"
  echo "  ./scripts/setup_toolchain.sh     # adb, node, android sdk, python"
  echo "  ./scripts/build_agent.sh         # builds the .dex agent (needs a JDK)"
  echo "  (cd ui && PATH=../.toolchain/node/bin:\$PATH npm ci)"
  exit 1
fi

if [ ! -f /etc/udev/rules.d/51-android-phonevitals.rules ]; then
  echo
  echo "Note: the udev rule for USB access is not installed."
  echo "      Without it, adb may see the phone as \"no permissions\"."
  echo "      To install it (once):"
  echo "        sudo ./scripts/install_udev_rules.sh"
fi

# Electron refuses to start if chrome-sandbox is present but not setuid root,
# and the check runs before any of our code, so the switch has to be on the
# command line. Setting the bit needs sudo; see ui/main.js for why running
# without it is acceptable here.
ELECTRON_ARGS=()
SANDBOX_BIN="$ROOT/ui/node_modules/electron/dist/chrome-sandbox"
if [ -e "$SANDBOX_BIN" ]; then
  owner=$(stat -c '%u' "$SANDBOX_BIN" 2>/dev/null || echo 1)
  perms=$(stat -c '%a' "$SANDBOX_BIN" 2>/dev/null || echo 0)
  if [ "$owner" != "0" ] || [ "${perms:0:1}" != "4" ]; then
    ELECTRON_ARGS+=("--no-sandbox")
  fi
fi

echo
echo "Starting PhoneVitals…"

# The Electron shim starts with `#!/usr/bin/env node`: on a machine without a
# system-wide Node it needs the local one on PATH.
export PATH="$TC/node/bin:$PATH"

# Build the interface when it is missing or older than its sources.
if [ ! -f "$ROOT/ui/dist/index.html" ] || \
   [ -n "$(find "$ROOT/ui/web" -newer "$ROOT/ui/dist/index.html" -type f -print -quit)" ]; then
  echo "Building the interface…"
  (cd "$ROOT/ui" && npm run --silent build) || exit 1
fi

cd "$ROOT/ui"
exec "$ELECTRON" . "${ELECTRON_ARGS[@]}" "$@"
