#!/usr/bin/env python3
"""The local device memory: sightings, changed parts, shared IMEIs,
reference units, and that no identifier is stored in clear."""

from __future__ import annotations

import copy
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from phonevitals.analysis.memory import memory_findings  # noqa: E402
from phonevitals.store import DeviceStore               # noqa: E402

IMEI = "490154203237518"
SERIAL = "R5CR8TEST01"

PHONE = {
    "summary": {"brand": "samsung", "model": "SM-A528B"},
    "identity": {"imeis": [IMEI], "serials": {"primary": SERIAL}},
    "system": {"partitions": {"effective": {"brand": "samsung", "device": "a52sxq"}},
               "soc": {"declared_model": "SM7325", "platform": "lahaina",
                       "core_types": [{"count": 4, "microarchitecture": "Cortex-A55"},
                                      {"count": 4, "microarchitecture": "Cortex-A78"}]}},
    "cpu": {"clusters": [{"max_khz": 1804800}, {"max_khz": 2400000}]},
    "display": {"resolution": {"width": 1080, "height": 2400}, "refresh_rates": [60, 120]},
    "components": {"soc": {"chip_serial": "1234500001"},
                   "cameras": [{"position": "rear main", "sensor": "CAMFW000001",
                                "module_id": "MODULE0000001"}],
                   "panel": {"cell_id": "panelcell000000001", "lcd_type": "SDC_TEST01"}},
    "report": {"score": 40, "verdict": "compromised"},
}


def check(condition: bool, message: str) -> bool:
    print(f"  {'ok' if condition else 'FAIL'}   {message}")
    return condition


def titles(memory):
    return [f["title"] for f in memory_findings(memory)]


def main() -> int:
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        store = DeviceStore(Path(tmp))
        first = store.record(PHONE)
        ok &= check(first["seen_before"] == 0, "a new phone has no history")

        repaired = copy.deepcopy(PHONE)
        repaired["components"]["cameras"][0]["module_id"] = "MODULE0000002"
        again = store.record(repaired)
        ok &= check(again["seen_before"] == 1 and again["changed_components"]
                    == ["camera module (rear main)"], "a replaced camera module is noticed")
        ok &= check("Components changed since the last analysis" in titles({"sightings": again}),
                    "and reported")

        clone = copy.deepcopy(PHONE)
        clone["identity"]["serials"]["primary"] = "CLONE0001"
        clone["components"]["soc"]["chip_serial"] = "1"
        seen = store.record(clone)
        ok &= check(seen["seen_before"] == 0 and len(seen["imei_on_other_devices"]) == 2,
                    "the same IMEI on another device is noticed")
        ok &= check("IMEI already seen on another device" in titles({"sightings": seen}),
                    "and reported")

        store.save_reference(PHONE)
        ok &= check(store.reference(PHONE)["differences"] == [],
                    "a phone matches its own reference")
        variant = copy.deepcopy(PHONE)
        variant["system"]["soc"]["declared_model"] = "MT6765"
        ref = store.reference(variant)
        ok &= check([d["trait"] for d in ref["differences"]] == ["soc"]
                    and ref["differences"][0]["strict"], "a different processor is a strict difference")
        missing = copy.deepcopy(PHONE)
        del missing["display"]
        ok &= check(store.reference(missing)["differences"] == [],
                    "a reading that failed is not a difference")

        raw = (Path(tmp) / "devices.db").read_bytes()
        ok &= check(all(v.encode() not in raw for v in (IMEI, SERIAL, "1234500001",
                                                        "MODULE0000001")),
                    "no identifier is stored in clear")
    print()
    print("RESULT: " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
