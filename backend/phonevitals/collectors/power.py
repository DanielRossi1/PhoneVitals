"""Battery and thermals.

The battery is the most frequently replaced component, and fortunately also
the one that leaves the most traces. The gauge -- the chip that measures
charge -- keeps in sysfs the cycle count, the measured maximum capacity
against the design figure, and on many recent models the cell manufacturing
date and the date of first use.

Two combinations are interesting:
  - very low cycles but already degraded capacity, or a cell manufacturing
    date well after the phone: the cell was replaced, often with a
    non-original one;
  - very high cycles on a phone sold as new: it is a refurbished unit.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .base import (
    Collector, parse_colon_kv, parse_kv, sysfs_dump, to_float, to_int,
)


class BatteryCollector(Collector):
    name = "battery"
    title = "Battery"

    def commands(self) -> dict[str, str]:
        return {
            "bat.dumpsys": "dumpsys battery",
            "bat.sysfs": sysfs_dump("/sys/class/power_supply/battery"),
            # On some chipsets the gauge sits in a separate node.
            "bat.bms": sysfs_dump("/sys/class/power_supply/bms"),
            "bat.supplies": "ls /sys/class/power_supply/ 2>/dev/null",
            "bat.usb": sysfs_dump("/sys/class/power_supply/usb"),
            "bat.wireless": sysfs_dump("/sys/class/power_supply/wireless"),
            # The framework's own estimate, learned from the charge counter
            # over full charges: a second opinion where the gauge has none.
            "bat.stats": "dumpsys batterystats --charged 2>/dev/null"
                         " | grep -m4 -E 'learned battery capacity|Estimated battery capacity'",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        fw = self._parse_dumpsys(raw.get("bat.dumpsys", ""))
        sysfs = parse_kv(raw.get("bat.sysfs", ""))
        bms = parse_kv(raw.get("bat.bms", ""))
        merged = {**bms, **sysfs}          # the battery node takes precedence

        design = self._uah(merged.get("charge_full_design"))
        full = self._uah(merged.get("charge_full"))

        cycles = self._cycles(merged)
        learned = self._learned(raw.get("bat.stats", ""))
        health_pct, health_source, health_note = self._health(
            merged, design, full, cycles, learned)

        return {
            "framework": fw,
            "level_percent": fw.get("level"),
            "status": fw.get("status_text"),
            "plugged": fw.get("plugged_text"),
            "health_text": fw.get("health_text"),
            "technology": merged.get("technology") or fw.get("technology"),
            "battery_type": merged.get("battery_type"),
            "temperature_c": self._temp_c(merged, fw),
            "voltage_v": self._voltage_v(merged, fw),
            "current_ma": self._current_ma(merged),
            "power_w": self._power_w(merged),
            "design_capacity_mah": round(design / 1000, 1) if design else None,
            "full_capacity_mah": round(full / 1000, 1) if full else None,
            "health_percent": health_pct,
            "health_source": health_source,
            "health_note": health_note,
            "cycle_count": cycles,
            "learned_capacity_mah": learned.get("last"),
            "manufacturing_date": self._date(merged.get("manufacturing_date")),
            "first_usage_date": self._date(merged.get("first_usage_date")),
            "part_number": merged.get("part_number"),
            "serial_number": merged.get("serial_number"),
            "supplies": [s for s in raw.get("bat.supplies", "").split() if s],
            "charger": self._charger(parse_kv(raw.get("bat.usb", ""))),
            "wireless_present": bool(parse_kv(raw.get("bat.wireless", ""))),
            "sysfs": merged,
        }

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _learned(text: str) -> dict[str, float]:
        """`Last/Min/Max learned battery capacity: N mAh` from batterystats."""
        out: dict[str, float] = {}
        for m in re.finditer(r"(Estimated|Last learned|Min learned|Max learned) "
                             r"battery capacity:\s*([\d.]+)\s*mAh", text):
            key = m.group(1).split()[0].lower()
            value = to_float(m.group(2))
            if value and value > 0:
                out[key] = value
        return out

    @staticmethod
    def _health(sysfs: dict[str, str], design: float | None, full: float | None,
                cycles: int | None, learned: dict[str, float] | None = None,
                ) -> tuple[float | None, str | None, str | None]:
        """Remaining capacity as a percentage of design, with its source.

        Returns (percent, source, note); percent is None when the device
        publishes nothing that measures wear, and the note says why. Reporting
        a healthy battery that was never measured is worse than reporting
        nothing: it is exactly what a worn cell would want to hide behind.
        """
        if design and full and full != design:
            return round(full / design * 100, 1), "charge_full / charge_full_design", None

        # A learned full-charge capacity never equals the design figure to the
        # microamp-hour: when the two match, the driver is simply echoing the
        # nominal value (many Samsung kernels do), and the ratio means nothing.
        nominal_only = bool(design and full and full == design)

        # Samsung fuel gauges keep their own wear estimate (ASOC, the figure
        # behind the battery status in Samsung Members). It is learned over
        # charge cycles, so it is only meaningful while the gauge has a
        # history: with no cycle count it may just be the reset default.
        asoc = to_float(sysfs.get("asoc") or sysfs.get("fg_asoc"))
        gauge_cycles = to_int(sysfs.get("fg_cycle"))
        has_history = (cycles or 0) > 0 or (gauge_cycles or 0) > 0
        if asoc is not None and 0 < asoc <= 100 and has_history:
            return asoc, "fuel gauge ASOC (Samsung)", None

        # Android's own estimate from the charge counter over full charges.
        # It is only a measurement when it differs from the design figure it
        # starts from, and is a plausible fraction of it.
        last = (learned or {}).get("last")
        design_mah = design / 1000 if design else (learned or {}).get("estimated")
        if last and design_mah and abs(last - design_mah) > 1 and 0.4 <= last / design_mah <= 1.1:
            return (round(min(100.0, last / design_mah * 100), 1),
                    "learned capacity (batterystats)", None)

        if asoc is not None and 0 < asoc <= 100:
            return None, None, (
                f"The fuel gauge reports {asoc:.0f}% but has no charge history "
                "(no cycle count), as after a gauge reset or a reflash, so that "
                "figure is its default rather than a measurement.")
        if nominal_only:
            return None, None, (
                "The gauge reports the design capacity as the full-charge "
                "capacity, so it publishes no measured value.")
        return None, None, None

    @staticmethod
    def _cycles(sysfs: dict[str, str]) -> int | None:
        """Cycle count, from whichever node the gauge driver publishes.

        Zero is a real reading -- a new cell -- and must survive. Some Samsung
        kernels leave `cycle_count` at 0 and keep the real figure in
        `battery_cycle`, so a positive value from any node wins over a zero.
        """
        readings = [to_int(sysfs.get(key))
                    for key in ("cycle_count", "battery_cycle", "batt_cycle")]
        readings = [n for n in readings if n is not None and n >= 0]
        positive = [n for n in readings if n > 0]
        if positive:
            return positive[0]
        return readings[0] if readings else None

    @staticmethod
    def _parse_dumpsys(text: str) -> dict[str, Any]:
        kv = parse_colon_kv(text)
        status_map = {1: "unknown", 2: "charging", 3: "discharging",
                      4: "not charging", 5: "full"}
        health_map = {1: "unknown", 2: "good", 3: "overheated",
                      4: "dead", 5: "over voltage",
                      6: "unspecified failure", 7: "cold"}
        plug_map = {0: "none", 1: "USB (AC)", 2: "USB", 4: "wireless", 8: "dock"}

        status = to_int(kv.get("status"))
        health = to_int(kv.get("health"))
        plugged = to_int(kv.get("plugged"))
        if plugged is None:
            # BatteryService's dump has no `plugged` line: it prints one
            # "<source> powered: true|false" line per source instead.
            sources = {"AC powered": 1, "USB powered": 2,
                       "Wireless powered": 4, "Dock powered": 8}
            if any(name in kv for name in sources):
                plugged = sum(bit for name, bit in sources.items()
                              if kv.get(name) == "true")

        return {
            "level": to_int(kv.get("level")),
            "scale": to_int(kv.get("scale")),
            "status": status,
            "status_text": status_map.get(status or 0, "n/a"),
            "health": health,
            "health_text": health_map.get(health or 0, "n/a"),
            "plugged": plugged,
            "plugged_text": (plug_map.get(plugged, "n/a")
                             if plugged is not None else "n/a"),
            "voltage_mv": to_int(kv.get("voltage")),
            "temperature_dc": to_int(kv.get("temperature")),
            "technology": kv.get("technology"),
            "present": kv.get("present") == "true",
            "charge_counter": to_int(kv.get("Charge counter")),
            "max_charging_current_ua": to_int(kv.get("Max charging current")),
            "max_charging_voltage_uv": to_int(kv.get("Max charging voltage")),
        }

    @staticmethod
    def _uah(value: str | None) -> float | None:
        """charge_full is in microamp-hours, but some kernels use mAh."""
        n = to_float(value)
        if n is None or n <= 0:
            return None
        # A phone battery is between 1000 and 12000 mAh. Below 100000 the
        # number is almost certainly already in mAh.
        return n if n > 100000 else n * 1000

    @staticmethod
    def _temp_c(sysfs: dict[str, str], fw: dict[str, Any]) -> float | None:
        # sysfs `temp` and dumpsys `temperature` are in tenths of a degree.
        t = to_float(sysfs.get("temp"))
        if t is None:
            t = fw.get("temperature_dc")
        if t is None:
            return None
        return round(float(t) / 10.0, 1)

    @staticmethod
    def _voltage_v(sysfs: dict[str, str], fw: dict[str, Any]) -> float | None:
        v = to_float(sysfs.get("voltage_now"))
        if v is not None:
            # voltage_now is in microvolts, but some kernels use millivolts.
            return round(v / 1_000_000, 3) if v > 100_000 else round(v / 1000, 3)
        mv = fw.get("voltage_mv")
        return round(mv / 1000, 3) if mv else None

    @staticmethod
    def _current_ma(sysfs: dict[str, str]) -> float | None:
        c = to_float(sysfs.get("current_now"))
        if c is None:
            return None
        # current_now is in microamps on Android kernels.
        ma = c / 1000 if abs(c) > 10000 else c
        return round(ma, 1)

    @staticmethod
    def _power_w(sysfs: dict[str, str]) -> float | None:
        v = to_float(sysfs.get("voltage_now"))
        c = to_float(sysfs.get("current_now"))
        if v is None or c is None:
            return None
        volts = v / 1_000_000 if v > 100_000 else v / 1000
        amps = c / 1_000_000 if abs(c) > 10000 else c / 1000
        return round(volts * amps, 2)

    @staticmethod
    def _date(value: str | None) -> dict[str, Any] | None:
        """Battery dates come in different formats per manufacturer.

        Pixel uses epoch seconds, others use YYYYMMDD. Both are tried and
        obviously out-of-range values are discarded.
        """
        if not value:
            return None
        v = value.strip()
        n = to_int(v)
        if n is None:
            return {"iso": None, "raw": v, "format": "unknown"}
        if n <= 0:
            return None

        if 19000101 <= n <= 21001231:
            try:
                d = datetime.strptime(str(n), "%Y%m%d")
                return {"iso": d.date().isoformat(), "raw": v, "format": "YYYYMMDD"}
            except ValueError:
                pass

        # Epoch seconds: accepted only between 2010 and 2100.
        if 1_262_304_000 <= n <= 4_102_444_800:
            d = datetime.fromtimestamp(n, tz=timezone.utc)
            return {"iso": d.date().isoformat(), "raw": v, "format": "epoch"}

        return {"iso": None, "raw": v, "format": "unknown"}

    @staticmethod
    def _charger(usb: dict[str, str]) -> dict[str, Any] | None:
        if not usb:
            return None
        return {
            "online": usb.get("online") == "1",
            "type": usb.get("usb_type") or usb.get("real_type") or usb.get("type"),
            "voltage_max_uv": to_int(usb.get("voltage_max")),
            "current_max_ua": to_int(usb.get("current_max")),
        }


class ThermalCollector(Collector):
    name = "thermal"
    title = "Thermal sensors"

    def commands(self) -> dict[str, str]:
        return {
            # Zone type and temperature in one pass, keyed by zone directory:
            # emits `thermal_zone0.type=...` and `thermal_zone0.temp=...`.
            "thermal.zones": (
                "grep -sH . /sys/class/thermal/thermal_zone*/type "
                "/sys/class/thermal/thermal_zone*/temp 2>/dev/null | "
                "sed -e 's|^/sys/class/thermal/||' -e 's|/|.|' -e 's|:|=|'"
            ),
            "thermal.service": "dumpsys thermalservice",
        }

    # android.os.Temperature type constants, as reported by thermalservice.
    HAL_TYPES = {
        -1: "unknown", 0: "CPU", 1: "GPU", 2: "battery", 3: "skin",
        4: "USB port", 5: "power amplifier", 6: "BCL voltage",
        7: "BCL current", 8: "BCL percentage", 9: "NPU",
    }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        by_zone: dict[str, dict[str, str]] = {}
        for key, value in parse_kv(raw.get("thermal.zones", "")).items():
            zone, _, attr = key.partition(".")
            if zone and attr:
                by_zone.setdefault(zone, {})[attr] = value

        zones = []
        for zone, attrs in by_zone.items():
            temp = to_float(attrs.get("temp"))
            if temp is None or not attrs.get("type"):
                continue
            # Kernels expose thousandths of a degree; a few use degrees.
            celsius = temp / 1000 if abs(temp) > 200 else temp
            zones.append({
                "zone": zone,
                "type": attrs["type"],
                "celsius": round(celsius, 1),
                "source": "sysfs",
            })

        svc = raw.get("thermal.service", "")

        # Fallback for devices where SELinux closes /sys/class/thermal to the
        # shell user -- Pixel among them, where the sysfs route returns nothing
        # at all. The thermal HAL publishes the same sensors through
        # thermalservice, already in degrees Celsius.
        if not zones:
            zones = self._from_service(svc)

        zones.sort(key=lambda z: -z["celsius"])

        status = None
        m = re.search(r"Thermal Status:\s*(\d+)", svc)
        if m:
            status_map = {
                0: "no throttling", 1: "light", 2: "moderate",
                3: "severe", 4: "critical", 5: "emergency", 6: "shutdown",
            }
            status = {
                "code": int(m.group(1)),
                "text": status_map.get(int(m.group(1)), "n/a"),
            }

        return {
            "zones": zones,
            "zone_count": len(zones),
            "hottest": zones[0] if zones else None,
            "throttling_status": status,
        }

    @classmethod
    def _from_service(cls, svc: str) -> list[dict[str, Any]]:
        zones: list[dict[str, Any]] = []
        seen: set[str] = set()
        for m in re.finditer(
            r"Temperature\{mValue=(-?[\d.]+),\s*mType=(-?\d+),\s*mName=([^,}]+)",
            svc,
        ):
            name = m.group(3).strip()
            value = to_float(m.group(1))
            if value is None or name in seen:
                continue
            seen.add(name)
            zones.append({
                "zone": name,
                "type": cls.HAL_TYPES.get(int(m.group(2)), "unknown"),
                "celsius": round(value, 1),
                "source": "thermalservice",
            })
        return zones


def merge_agent_facts(bat: dict[str, Any], facts: dict[str, Any]) -> None:
    """Fill the gaps sysfs left with what BatteryManager reported (Android 14+).

    The framework's state of health is what the system's own battery screen
    shows. It is still distrusted at exactly 100% when no cycle count exists
    to back it, the same default a reset gauge gives (see
    BatteryCollector._health).
    """
    if not facts:
        return
    bat["framework_facts"] = facts
    if bat.get("cycle_count") is None and facts.get("cycle_count") is not None:
        bat["cycle_count"] = facts["cycle_count"]
    for key in ("manufacturing_date", "first_usage_date"):
        if not bat.get(key) and facts.get(key):
            bat[key] = {"iso": facts[key], "raw": facts[key], "format": "BatteryManager"}

    soh = facts.get("state_of_health_percent")
    if soh is None or bat.get("health_percent") is not None:
        return
    if soh < 100 or bat.get("cycle_count") is not None:
        bat["health_percent"] = float(soh)
        bat["health_source"] = "state of health (Android battery service)"
        bat["health_note"] = None
    else:
        bat["health_note"] = (
            "Android reports a state of health of 100% but the device keeps no "
            "cycle count to back it, so it may be a default rather than a "
            "measurement.")
