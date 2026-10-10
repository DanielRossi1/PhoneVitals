"""Shared infrastructure for the collectors.

A collector declares the shell commands it needs and knows how to interpret
their output. All commands from all collectors end up in a single batch, so
adding a collector costs no extra round-trips.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


class Collector:
    name: str = "base"
    title: str = ""

    def commands(self) -> dict[str, str]:
        """Required shell commands, with keys already namespaced."""
        return {}

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        """Turn raw output into structured data."""
        return {}


# --------------------------------------------------------------- shell helpers

# Reading sysfs one `cat` at a time is dominated by process spawn cost, not by
# the driver. On a Pixel the battery power_supply directory holds ~120 nodes:
# a per-file cat loop took 15.9 s, while a single grep over the same files took
# 0.25 s and returned the same values. One grep, one sed, no subshell per file.
_TO_KV = r"sed -e 's|^.*/||' -e 's|:|=|'"


def sysfs_dump(path: str) -> str:
    """Read every readable file in a sysfs directory as `name=value` lines.

    Unreadable and write-only nodes are skipped silently; many sysfs entries
    are one or the other.
    """
    return f"grep -sH . {path}/* 2>/dev/null | {_TO_KV}"


def sysfs_files(paths: Iterable[str]) -> str:
    """Same, for an explicit list of files that may or may not exist."""
    joined = " ".join(paths)
    return f"grep -sH . {joined} 2>/dev/null | {_TO_KV}"


def first_line(path: str) -> str:
    return f"cat {path} 2>/dev/null | head -1"


# ---------------------------------------------------------------- parse helpers

_PROP_RE = re.compile(r"^\[([^\]]*)\]:\s*\[(.*)\]$")


def parse_props(text: str) -> dict[str, str]:
    """Parse `getprop` output of the form [key]: [value]."""
    props: dict[str, str] = {}
    for line in text.splitlines():
        m = _PROP_RE.match(line.strip())
        if m:
            props[m.group(1)] = m.group(2)
    return props


def parse_kv(text: str, sep: str = "=") -> dict[str, str]:
    """Parse `key=value` lines (the output of sysfs_dump).

    First occurrence wins: a multi-line sysfs file yields one line per line of
    content, and the first is the value proper.
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or sep not in line:
            continue
        k, v = line.split(sep, 1)
        k, v = k.strip(), v.strip()
        if k and v and k not in out:
            out[k] = v
    return out


def parse_colon_kv(text: str) -> dict[str, str]:
    """Parse `key: value` lines (dumpsys, /proc/meminfo, cpuinfo)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if k:
            out[k] = v
    return out


def to_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(str(value).strip().split()[0])
    except (ValueError, IndexError, AttributeError, TypeError):
        return default


def to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(str(value).strip().split()[0])
    except (ValueError, IndexError, AttributeError, TypeError):
        return default


def human_bytes(n: int | float | None) -> str:
    if n is None:
        return "n/a"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def human_hz(khz: int | float | None) -> str:
    """sysfs frequencies are in kHz."""
    if not khz:
        return "n/a"
    mhz = float(khz) / 1000.0
    if mhz >= 1000:
        return f"{mhz / 1000:.2f} GHz"
    return f"{mhz:.0f} MHz"


# Thermal zones that do not hold a temperature: Qualcomm's limits-management
# zones (lmh-dcvs-*) report their fixed trip point, and the battery
# current-limit zones (bcl, ibat, vbat, soc, socd) report current, voltage or
# charge.
_NOT_A_TEMPERATURE = re.compile(
    r"^(lmh-|bcl|socd?$)|(ibat|vbat|bcl)|-lvl\d", re.IGNORECASE)


def is_temperature_zone(zone_type: str) -> bool:
    return not _NOT_A_TEMPERATURE.search(zone_type or "")

