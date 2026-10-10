#!/usr/bin/env bash
# Run the Snap Store's automated review on a built snap, the same checks the
# store applies on upload, so a rejection shows up in CI instead of at release.
# Usage: scripts/review_snap.sh phonevitals_<version>_<arch>.snap
set -euo pipefail
SNAP_FILE="$1"

command -v review-tools.snap-review >/dev/null || sudo snap install review-tools

# review-tools is confined and only reads files under the home directory.
DIR="$HOME/snap-review"
mkdir -p "$DIR"
cp "$SNAP_FILE" "$DIR/"

set +e
review-tools.snap-review "$DIR/$(basename "$SNAP_FILE")"
rc=$?
set -e
rm -rf "$DIR"

# Any finding fails: the store holds an upload with warnings for manual
# review, and that blocks every later upload until someone acts on it.
if [ "$rc" -ne 0 ]; then
  echo "::error::the store review would not approve the snap automatically (exit $rc)"
  exit 1
fi
