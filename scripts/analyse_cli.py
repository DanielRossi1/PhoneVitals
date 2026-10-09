#!/usr/bin/env python3
"""Run a complete analysis from the command line and print the report.

Exactly the same pipeline as the GUI: useful for diagnostics, for scripting,
and for checking behaviour on a real device without opening the interface.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import textwrap

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from phonevitals import __version__                  # noqa: E402
from phonevitals.adb import Adb, AdbError            # noqa: E402
from phonevitals.analyzer import Analyzer            # noqa: E402
from phonevitals.store import DeviceStore            # noqa: E402

MARK = {"critical": "CRITICAL", "warning": "WARNING", "info": "INFO", "ok": "OK"}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--serial", help="device serial")
    parser.add_argument("--no-imei", action="store_true",
                        help="skip identifier reading")
    parser.add_argument("--json", metavar="FILE", help="save the full snapshot")
    parser.add_argument("--quiet", action="store_true",
                        help="do not print progress")
    parser.add_argument("--no-memory", action="store_true",
                        help="do not compare with, or add to, the local device memory")
    args = parser.parse_args()

    try:
        adb = Adb()
    except AdbError as exc:
        print(exc, file=sys.stderr)
        return 1

    devices = await adb.list_devices()
    if not devices:
        print("No device connected.", file=sys.stderr)
        return 1

    if args.serial:
        # Never fall back to another phone: the report would be attributed
        # to the wrong device.
        device = next((d for d in devices if d.serial == args.serial), None)
        if device is None:
            print(f"Device {args.serial} not found. Connected: "
                  + ", ".join(d.serial for d in devices), file=sys.stderr)
            return 1
    else:
        device = next((d for d in devices if d.ready), devices[0])

    print(f"Device: {device.label}  ({device.serial}, state {device.state})")
    print(f"adb: {adb.adb}\n")

    def on_event(ev):
        if args.quiet:
            return
        if ev.get("type") == "progress":
            print(f"  {ev['percent']:3d}%  {ev.get('detail') or ev['step']}")
        elif ev.get("type") == "collector_error":
            print(f"  !! collector {ev['collector']}: {ev['error']}", file=sys.stderr)

    analyzer = Analyzer(adb, on_event=on_event,
                        store=None if args.no_memory else DeviceStore())
    snapshot = await analyzer.analyse(device, read_imei=not args.no_imei)

    if snapshot["meta"].get("blocked"):
        b = snapshot["meta"]["blocked"]
        print(f"\n{b['title']}\n{b['detail']}")
        return 2

    s, r = snapshot["summary"], snapshot["report"]

    print("\n" + "=" * 74)
    print(f"  {s['brand'].upper()} {s['model']}   ({s['device']})")
    print("=" * 74)
    for label, value in [
        ("Android", f"{s['android']} (API {s['sdk']}), patch {s['security_patch']}"),
        ("SoC", f"{s['soc']} · {s['cores']} cores"),
        ("Memory", f"{s['ram_gb']} GB RAM · {s['storage_gb']} GB {s['storage_type']}"
                   + (" (estimated)" if s.get("storage_estimated") else "")),
        ("Display", f"{s['resolution']} @ {s['refresh_max']} Hz"),
        ("Battery", f"{s['battery_level']}% · health "
                    + (f"{s['battery_health']}%" if s['battery_health'] is not None
                       else "not measurable")
                    + (f" · {s['battery_cycles']} cycles"
                       if s['battery_cycles'] is not None else "")),
        ("Sensors", f"{s['sensors']} · {s['cameras']} cameras"),
        ("Serial", s["serial"]),
        ("IMEI", ", ".join(s["imeis"]) or "not read"),
    ]:
        print(f"  {label:12} {value}")

    print(f"\n  Readings executed: {snapshot['meta']['commands_executed']}, "
          f"with output: {snapshot['meta']['commands_with_output']}")
    print(f"  Duration: {snapshot['meta']['duration_seconds']}s")
    if snapshot["errors"]:
        print(f"  Failed collectors: {list(snapshot['errors'])}")

    print("\n" + "=" * 74)
    print(f"  REPORT — {r['score']}/100 · {r['verdict']}")
    print("=" * 74)
    print(f"  {r['headline']}\n")
    for sev in ("critical", "warning", "info", "ok"):
        for f in r["by_severity"].get(sev, []):
            print(f"  [{MARK[sev]:10}] {f['title']}")
            for line in textwrap.wrap(f["detail"], 68):
                print(f"               {line}")
            print()

    for note in snapshot.get("identity", {}).get("notes", []):
        print(f"  NOTE: {note}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2, default=str)
        print(f"\n  snapshot saved to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
