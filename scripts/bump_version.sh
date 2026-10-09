#!/usr/bin/env bash
# Set a new version everywhere it is recorded, and open its changelog entry.
#
#   ./scripts/bump_version.sh 0.2.0      explicit version
#   ./scripts/bump_version.sh minor      major | minor | patch from the current
#
# VERSION is the single source of truth; this keeps ui/package.json and its
# lock file in step, and moves the "Unreleased" notes of CHANGELOG.md under the
# new version. It does not commit or tag: review, commit, then tag v<version>
# and publish a GitHub release (see README, Releasing).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
current="$(cat "$ROOT/VERSION")"
arg="${1:?usage: bump_version.sh <x.y.z|major|minor|patch>}"

IFS=. read -r major minor patch <<<"$current"
case "$arg" in
  major) next="$((major + 1)).0.0" ;;
  minor) next="$major.$((minor + 1)).0" ;;
  patch) next="$major.$minor.$((patch + 1))" ;;
  *)     next="$arg" ;;
esac
[[ "$next" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "not a version: $next" >&2; exit 1; }

echo "$next" > "$ROOT/VERSION"
python3 - "$ROOT" "$next" <<'PY'
import json, re, sys, datetime
root, version = sys.argv[1], sys.argv[2]
for name in ("ui/package.json", "ui/package-lock.json"):
    path = f"{root}/{name}"
    data = json.load(open(path))
    data["version"] = version
    if "packages" in data:
        data["packages"][""]["version"] = version
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
changelog = f"{root}/CHANGELOG.md"
text = open(changelog).read()
today = datetime.date.today().isoformat()
if f"## [{version}]" not in text:
    text = text.replace("## [Unreleased]\n", f"## [Unreleased]\n\n## [{version}] - {today}\n", 1)
    open(changelog, "w").write(text)
PY
echo "$current -> $next"
