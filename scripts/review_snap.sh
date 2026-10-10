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

# 0 clean, 3 warnings only (manual review at most), anything else is a
# rejection or a failure of the review itself.
case "$rc" in
  0) ;;
  3) echo "::warning::the store review reported warnings, see the log above" ;;
  *) echo "::error::the store review rejected the snap (exit $rc)"; exit 1 ;;
esac
