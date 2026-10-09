#!/usr/bin/env bash
# Refresh Google's attestation roots and revocation list in backend/data.
# The program never goes online: these files ship with it, and the release
# workflow runs this script so every release carries a current copy.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/backend/data"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

curl -fsSL -o "$TMP/root.json" https://android.googleapis.com/attestation/root
curl -fsSL -o "$TMP/status.json" https://android.googleapis.com/attestation/status

PY_BIN="$(command -v python3 || command -v python)"
"$PY_BIN" - "$TMP" "$DATA" <<'PY'
import json, sys
tmp, data = sys.argv[1], sys.argv[2]
roots = json.load(open(f"{tmp}/root.json"))
if not roots or not all("BEGIN CERTIFICATE" in r for r in roots):
    sys.exit("unexpected root list format")
status = json.load(open(f"{tmp}/status.json"))
if "entries" not in status:
    sys.exit("unexpected revocation list format")
with open(f"{data}/attestation_roots.pem", "w") as fh:
    fh.write("\n".join(r.strip() for r in roots) + "\n")
with open(f"{data}/attestation_status.json", "w") as fh:
    json.dump(status, fh, separators=(",", ":"), sort_keys=True)
print(f"{len(roots)} roots, {len(status['entries'])} revoked keys")
PY
