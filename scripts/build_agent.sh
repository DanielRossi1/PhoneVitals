#!/usr/bin/env bash
# Compile the Java agent and convert it to a .dex runnable by app_process.
# The resulting .dex lands in backend/data/ and is pushed to the phone
# only at the moment of use.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TC="${PHONEVITALS_TOOLCHAIN:-$ROOT/.toolchain}"
SDK="$TC/android-sdk"
API=34
BUILD_TOOLS="34.0.0"

ANDROID_JAR="$SDK/platforms/android-$API/android.jar"
D8="$SDK/build-tools/$BUILD_TOOLS/d8"
SRC="$ROOT/agent/src"
BUILD="$ROOT/agent/build"
OUT="$ROOT/backend/data"

[ -f "$ANDROID_JAR" ] || { echo "android.jar missing: $ANDROID_JAR" >&2; exit 1; }
[ -x "$D8" ]          || { echo "d8 missing: $D8" >&2; exit 1; }
# The JDK that setup_toolchain.sh downloads takes precedence over the system one.
[ -x "$TC/jdk/bin/javac" ] && export PATH="$TC/jdk/bin:$PATH" JAVA_HOME="$TC/jdk"
command -v javac >/dev/null || {
  echo "javac missing: run scripts/setup_toolchain.sh or install a JDK" >&2
  exit 1
}

rm -rf "$BUILD"
mkdir -p "$BUILD/classes" "$OUT"

echo "→ compiling Java sources (Java 8 bytecode, which d8 accepts for API 26)"
find "$SRC" -name '*.java' > "$BUILD/sources.txt"
javac \
  -source 8 -target 8 \
  -bootclasspath "$ANDROID_JAR" \
  -classpath "$ANDROID_JAR" \
  -d "$BUILD/classes" \
  -encoding UTF-8 \
  -nowarn \
  @"$BUILD/sources.txt"

echo "→ converting to dex"
# --min-api 26: covers Android 8.0 and up, the minimum on which app_process
# with an external classpath works reliably.
"$D8" \
  --min-api 26 \
  --lib "$ANDROID_JAR" \
  --output "$BUILD" \
  $(find "$BUILD/classes" -name '*.class')

mv "$BUILD/classes.dex" "$OUT/pvagent.dex"
echo "✓ agent ready: $OUT/pvagent.dex ($(du -h "$OUT/pvagent.dex" | cut -f1))"
