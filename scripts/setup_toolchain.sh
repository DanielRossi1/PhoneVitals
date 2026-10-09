#!/usr/bin/env bash
# Downloads the whole toolchain locally into the project. No sudo, no
# system-wide installation: everything lives under .toolchain/ and can be
# removed with a single rm -rf.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TC="$ROOT/.toolchain"
DL="$TC/downloads"
mkdir -p "$DL"

log() { echo "[$(date +%H:%M:%S)] $*"; }
ok()  { echo "[$(date +%H:%M:%S)] OK   $*"; }
err() { echo "[$(date +%H:%M:%S)] FAIL $*"; }

# ---------------------------------------------------------------- platform-tools
if [ -x "$TC/platform-tools/adb" ]; then
  ok "platform-tools already present"
else
  log "downloading platform-tools (adb, fastboot)..."
  if curl -fsSL -o "$DL/pt.zip" \
      https://dl.google.com/android/repository/platform-tools-latest-linux.zip; then
    unzip -qo "$DL/pt.zip" -d "$TC" && ok "platform-tools -> $("$TC/platform-tools/adb" version | head -1)"
  else
    err "download platform-tools"
  fi
fi

# ---------------------------------------------------------------- node
# Only needed to install Electron with npm. A system Node 22+ is used as is.
system_node_major=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
if [ -x "$TC/node/bin/node" ]; then
  ok "node already present: $("$TC/node/bin/node" -v)"
elif [ "$system_node_major" -ge 22 ]; then
  ok "using system node $(node -v)"
else
  log "resolving latest node LTS version..."
  NV=$(curl -fsSL https://nodejs.org/dist/index.json | python3 -c \
       'import json,sys; print(next(r["version"] for r in json.load(sys.stdin) if r["lts"]))' \
       2>/dev/null)
  [ -z "${NV:-}" ] && NV="v22.20.0"
  log "node $NV"
  case "$(uname -m)" in
    aarch64) NODE_ARCH=arm64 ;;
    *)       NODE_ARCH=x64 ;;
  esac
  if curl -fsSL -o "$DL/node.tar.xz" "https://nodejs.org/dist/$NV/node-$NV-linux-$NODE_ARCH.tar.xz"; then
    mkdir -p "$TC/node"
    tar -xJf "$DL/node.tar.xz" -C "$TC/node" --strip-components=1 \
      && ok "node -> $("$TC/node/bin/node" -v), npm $("$TC/node/bin/npm" -v 2>/dev/null)"
  else
    err "download node"
  fi
fi

# ---------------------------------------------------------------- android sdk (d8 + android.jar)
# ---------------------------------------------------------------- jdk
# Needed to compile the agent and to run sdkmanager. A system JDK is used if
# present; otherwise Temurin 21 is downloaded into the toolchain.
if [ -x "$TC/jdk/bin/javac" ]; then
  ok "jdk already present: $("$TC/jdk/bin/javac" -version 2>&1)"
elif command -v javac >/dev/null; then
  ok "using system $(javac -version 2>&1)"
else
  log "downloading Temurin JDK 21..."
  case "$(uname -m)" in
    aarch64) JDK_ARCH=aarch64 ;;
    *)       JDK_ARCH=x64 ;;
  esac
  JDK_URL=$(curl -fsSL https://api.github.com/repos/adoptium/temurin21-binaries/releases/latest \
    | python3 -c 'import json,sys; print(next(a["browser_download_url"] for a in json.load(sys.stdin)["assets"] if a["name"].endswith(".tar.gz") and "jdk_'"$JDK_ARCH"'_linux_hotspot" in a["name"]))' \
    2>/dev/null)
  if [ -n "${JDK_URL:-}" ] && curl -fsSL -o "$DL/jdk.tar.gz" "$JDK_URL"; then
    rm -rf "$TC/jdk" && mkdir -p "$TC/jdk"
    tar -xzf "$DL/jdk.tar.gz" -C "$TC/jdk" --strip-components=1 \
      && ok "jdk -> $("$TC/jdk/bin/javac" -version 2>&1)"
  else
    err "download jdk"
  fi
fi
if [ -x "$TC/jdk/bin/javac" ]; then
  export JAVA_HOME="$TC/jdk" PATH="$TC/jdk/bin:$PATH"
elif command -v javac >/dev/null; then
  export JAVA_HOME="${JAVA_HOME:-$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")")}"
fi
SDK="$TC/android-sdk"
if [ -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]; then
  ok "cmdline-tools already present"
else
  log "downloading android command-line tools..."
  CLT_OK=0
  for u in \
    https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip \
    https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
    https://dl.google.com/android/repository/commandlinetools-linux-10406996_latest.zip ; do
    if curl -fsSL -o "$DL/clt.zip" "$u"; then CLT_OK=1; log "used $u"; break; fi
  done
  if [ "$CLT_OK" = "1" ]; then
    rm -rf "$DL/clt" && mkdir -p "$DL/clt"
    unzip -qo "$DL/clt.zip" -d "$DL/clt"
    mkdir -p "$SDK/cmdline-tools"
    rm -rf "$SDK/cmdline-tools/latest"
    mv "$DL/clt/cmdline-tools" "$SDK/cmdline-tools/latest"
    ok "cmdline-tools installed"
  else
    err "download cmdline-tools"
  fi
fi

if [ -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]; then
  log "accepting licences and installing platforms;android-34 + build-tools;34.0.0 ..."
  yes | "$SDK/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$SDK" --licenses >/dev/null 2>&1
  "$SDK/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$SDK" \
      "platforms;android-34" "build-tools;34.0.0" >"$TC/sdkmanager.log" 2>&1 \
    && ok "sdk components installed" || err "sdkmanager (see $TC/sdkmanager.log)"
  [ -f "$SDK/platforms/android-34/android.jar" ] && ok "android.jar present"
  [ -x "$SDK/build-tools/34.0.0/d8" ] && ok "d8 present"
fi

# ---------------------------------------------------------------- python venv
# The venv is checked by running it: one that was moved along with the project
# folder still exists but its scripts point at the old path.
if "$TC/venv/bin/python" -m pip --version >/dev/null 2>&1; then
  ok "venv already present"
else
  log "creating python venv..."
  # Ubuntu splits ensurepip into python3.12-venv, which would need sudo.
  # Create the venv without pip and bootstrap it with get-pip: same result,
  # zero system packages.
  rm -rf "$TC/venv"
  if python3 -m venv "$TC/venv" 2>/dev/null && "$TC/venv/bin/python" -m pip --version >/dev/null 2>&1; then
    ok "venv created (ensurepip available)"
  else
    python3 -m venv --without-pip "$TC/venv"
    curl -fsSL -o "$DL/get-pip.py" https://bootstrap.pypa.io/get-pip.py \
      && "$TC/venv/bin/python" "$DL/get-pip.py" -q >/dev/null 2>&1 \
      && ok "venv created (pip via bootstrap)" || err "bootstrap pip"
  fi
fi
if "$TC/venv/bin/python" -m pip --version >/dev/null 2>&1; then
  log "installing python dependencies..."
  "$TC/venv/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1
  "$TC/venv/bin/python" -m pip install -q -r "$ROOT/backend/requirements.txt" \
    >"$TC/pip.log" 2>&1 && ok "python deps installed" || err "pip (see $TC/pip.log)"
fi

log "=== SETUP COMPLETE ==="
