"""Demonstration mode, to see and check the interface without a phone.

A sample snapshot, simulated live streams and simulated test outcomes. It
serves to check that every page renders, to show someone without a device at
hand what a report looks like, and to take screenshots that contain no real
identifiers. The data is fabricated and the mode is flagged explicitly in the
report, so it cannot be mistaken for a real analysis.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from .testsuite import TestResult, TestSuite

Sink = Callable[[dict], Awaitable[None]]


def _fake_digest(label: str) -> str:
    """A stable, realistic-looking digest that matches no real key."""
    return hashlib.sha256(f"phonevitals demo {label}".encode()).hexdigest()


def _identity(brand: str, manufacturer: str, model: str, device: str) -> dict:
    return {"brand": brand, "manufacturer": manufacturer,
            "model": model, "device": device, "name": device}


def build_demo_snapshot() -> dict[str, Any]:
    from .analysis.authenticity import AuthenticityEngine
    from .analysis.imei import analyse_imeis, luhn_check_digit
    from .analysis.specdb import SpecDatabase
    from .analyzer import Analyzer

    today = datetime.now(UTC).date()
    patch = (today - timedelta(days=40)).replace(day=5).isoformat()
    build_utc = int(time.time()) - 55 * 24 * 3600
    battery_made = (today - timedelta(days=95)).isoformat()

    fingerprint = ("google/husky/husky:14/AP1A.240405.002/"
                   "11480754:user/release-keys")

    snapshot: dict[str, Any] = {
        "meta": {
            "serial": "DEMO00000000",
            "adb_state": "device",
            "usb_path": "1-2",
            "demo": True,
            "started_at": datetime.now(UTC).isoformat(),
            "commands_executed": 107,
            "commands_with_output": 98,
        },
        "errors": {},
        "system": {
            "props": {},
            "props_count": 1284,
            "build": {
                "fingerprint": fingerprint,
                "id": "AP1A.240405.002",
                "display_id": "AP1A.240405.002",
                "type": "user", "tags": "release-keys",
                "date": "Fri Apr  5 12:00:00 UTC 2024",
                "date_utc": build_utc,
                "bootloader": "husky-1.0-11577491",
                "baseband": "g5300g-240301-240314-B-11526499",
                "hardware": "zuma", "board": "husky",
            },
            "os": {
                "android_release": "14", "sdk": 34,
                "security_patch": patch,
                "vendor_security_patch": patch,
                "first_api_level": 34, "treble": True, "vndk": "34",
            },
            "kernel": {"release": "5.15.149-android14-11",
                       "full": "Linux version 5.15.149-android14-11"},
            "soc": {
                "declared_manufacturer": "Google",
                "declared_model": "Tensor G3",
                "platform": "zuma", "hardware": "zuma",
                "hardware_line": "Zuma",
                "core_types": [
                    {"implementer": "ARM", "implementer_id": "0x41",
                     "part_id": "0xd46", "microarchitecture": "Cortex-A510",
                     "count": 4},
                    {"implementer": "ARM", "implementer_id": "0x41",
                     "part_id": "0xd4d", "microarchitecture": "Cortex-A715",
                     "count": 4},
                    {"implementer": "ARM", "implementer_id": "0x41",
                     "part_id": "0xd4e", "microarchitecture": "Cortex-X3",
                     "count": 1},
                ],
                "core_count_cpuinfo": 9,
            },
            "partitions": {
                "by_partition": {
                    p: _identity("google", "Google", "Pixel 8 Pro", "husky")
                    for p in ("system", "vendor", "odm", "product", "system_ext")
                },
                "effective": _identity("google", "Google", "Pixel 8 Pro", "husky"),
            },
            "fingerprints": {
                p: fingerprint
                for p in ("system", "vendor", "odm", "product", "system_ext", "build")
            },
            "abis": ["arm64-v8a", "armeabi-v7a", "armeabi"],
            "uptime_seconds": 184320.0,
        },
        "cpu": {
            "core_count": 9,
            "cores": [
                {"id": f"cpu{i}", "index": i,
                 "max_khz": 1900000 if i < 4 else (2370000 if i < 8 else 2910000),
                 "min_khz": 324000, "governor": "sched_pixel"}
                for i in range(9)
            ],
            "clusters": [
                {"max_khz": 2910000, "count": 1},
                {"max_khz": 2370000, "count": 4},
                {"max_khz": 1900000, "count": 4},
            ],
            "max_khz": 2910000,
            "loadavg": "1.42 1.18 0.94 2/1893 28471",
        },
        "memory": {
            "total_kb": 11841232, "total_bytes": 11841232 * 1024,
            "nominal_gb": 12, "available_kb": 5218440, "free_kb": 412308,
            "swap_total_kb": 4194300, "swap_free_kb": 3980112, "zram": True,
            "raw": {},
        },
        "storage": {
            "type": "UFS",
            "devices": [{"id": "0:0:0:0", "vendor": "SAMSUNG",
                         "model": "KLUFG8RHDB-B0E1", "rev": "0300",
                         "state": "running"}],
            "ufs_health": {
                "life_time_a": {"code": 1, "used_percent_range": "0-10%",
                                "used_percent_max": 10},
                "life_time_b": {"code": 1, "used_percent_range": "0-10%",
                                "used_percent_max": 10},
                "eol_code": 1,
                "eol_description": "Normal (under 80% of the reserve blocks consumed)",
                "raw": {},
            },
            "physical_bytes": 256_060_514_304,
            "nominal_gb": 256,
            "data_total_bytes": 234_819_784_704,
            "data_used_bytes": 88_243_912_704,
            "data_available_bytes": 146_575_872_000,
            "partitions_raw": "",
        },
        "display": {
            "physical_size": "1344x2992", "physical_density": 480,
            "resolution": {"width": 1344, "height": 2992},
            "modes": [
                {"id": 1, "width": 1344, "height": 2992, "fps": 120.0},
                {"id": 2, "width": 1344, "height": 2992, "fps": 60.0},
            ],
            "refresh_rates": [120.0, 60.0],
            "panel": {"panel_name": "google-samsung-shiba"},
            "drm_connectors": {"card0-DSI-1": "connected"},
            "hdr_types": ["Dolby Vision", "HDR10", "HLG", "HDR10+"],
        },
        "battery": {
            "framework": {}, "level_percent": 78, "status": "discharging",
            "plugged": "none", "health_text": "good",
            "technology": "Li-ion", "battery_type": "SWD-ATL",
            "temperature_c": 31.4, "voltage_v": 4.012, "current_ma": -412.0,
            "power_w": -1.65,
            "design_capacity_mah": 5050.0, "full_capacity_mah": 4787.0,
            "health_percent": 94.8, "health_source": "charge_full / charge_full_design",
            "cycle_count": 137,
            "manufacturing_date": {"iso": battery_made, "raw": battery_made,
                                   "format": "YYYYMMDD"},
            "first_usage_date": {"iso": (today - timedelta(days=88)).isoformat(),
                                 "raw": "", "format": "epoch"},
            "part_number": "GMSB3", "serial_number": "DEMOBAT0001",
            "supplies": ["battery", "usb", "wireless", "main-charger"],
            "charger": {"online": False, "type": "USB", "voltage_max_uv": 9000000,
                        "current_max_ua": 3000000},
            "wireless_present": True, "sysfs": {},
        },
        "thermal": {
            "zones": [
                {"zone": "thermal_zone0", "type": "battery", "celsius": 31.4},
                {"zone": "thermal_zone1", "type": "cpu-big", "celsius": 44.2},
                {"zone": "thermal_zone2", "type": "gpu", "celsius": 41.8},
                {"zone": "thermal_zone3", "type": "skin-therm", "celsius": 35.1},
            ],
            "zone_count": 4,
            "hottest": {"zone": "thermal_zone1", "type": "cpu-big", "celsius": 44.2},
            "throttling_status": {"code": 0, "text": "no throttling"},
        },
        "sensors": {
            "count": 34,
            "vendors": ["Bosch", "STMicroelectronics", "Google", "AMS"],
            "sensors": [], "by_type": {
                "Accelerometer": [{"name": "BMI323 Accelerometer", "vendor": "Bosch"}],
                "Gyroscope": [{"name": "BMI323 Gyroscope", "vendor": "Bosch"}],
                "Magnetometer": [{"name": "MMC5633 Magnetometer", "vendor": "MEMSIC"}],
                "Ambient light": [{"name": "TCS3708 Light", "vendor": "AMS"}],
                "Proximity": [{"name": "TCS3708 Proximity", "vendor": "AMS"}],
                "Barometer": [{"name": "BMP390 Pressure", "vendor": "Bosch"}],
            },
            "features": [],
            "has": {"accelerometer": True, "gyroscope": True,
                    "magnetic_field": True, "light": True, "proximity": True,
                    "pressure": True},
        },
        "cameras": {
            "count": 5, "back_count": 3, "front_count": 1,
            "hal_version": "2.5",
            "cameras": [
                {"id": "0", "facing": "rear", "megapixels": 50.3,
                 "pixel_array": {"width": 8192, "height": 6144},
                 "focal_lengths_mm": [6.9], "apertures": [1.68],
                 "hardware_level": "LEVEL_3", "has_flash": True},
                {"id": "1", "facing": "front", "megapixels": 10.5,
                 "pixel_array": {"width": 3840, "height": 2748},
                 "focal_lengths_mm": [2.2], "apertures": [2.2],
                 "hardware_level": "FULL", "has_flash": False},
                {"id": "2", "facing": "rear", "megapixels": 48.0,
                 "pixel_array": {"width": 8000, "height": 6000},
                 "focal_lengths_mm": [19.2], "apertures": [2.8],
                 "hardware_level": "LEVEL_3", "has_flash": True},
                {"id": "3", "facing": "rear", "megapixels": 48.0,
                 "pixel_array": {"width": 8000, "height": 6000},
                 "focal_lengths_mm": [2.95], "apertures": [1.95],
                 "hardware_level": "LEVEL_3", "has_flash": True},
                {"id": "4", "facing": "rear", "megapixels": 50.3,
                 "pixel_array": {"width": 8192, "height": 6144},
                 "focal_lengths_mm": [6.9], "apertures": [1.68],
                 "hardware_level": "LEVEL_3", "has_flash": True},
            ],
        },
        "input": {
            "count": 6,
            "touchscreen": {
                "path": "/dev/input/event4", "name": "syna_tcm_touch",
                "is_touchscreen": True, "touch_max_x": 1343,
                "touch_max_y": 2991, "max_slots": 10,
                "abs_axes": {}, "keys": [], "event_types": ["ABS", "KEY"],
            },
            "key_devices": [
                {"path": "/dev/input/event0", "name": "gpio-keys",
                 "keys": ["KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_POWER"],
                 "key_count": 3, "is_keys": True, "is_touchscreen": False,
                 "abs_axes": {}, "event_types": ["KEY"]},
            ],
            "devices": [],
        },
        "audio": {
            "cards": " 0 [monaco]: monaco - monaco",
            "pcm_devices": [], "mode": "MODE_NORMAL", "ringer_mode": "NORMAL",
            "output_devices": ["SPEAKER", "EARPIECE", "BLUETOOTH_A2DP", "USB_HEADSET"],
            "has_speaker": True, "has_earpiece": True,
        },
        "biometrics": {
            "fingerprint": {"present": True, "sensors": ["0"], "enrolled": 2,
                            "hal": "goodix"},
            "face": {"present": True, "sensors": ["1"], "enrolled": 1},
        },
        "vibrator": {"present": True, "vibrator_ids": ["0"], "count": 1,
                     "supports_effects": True, "resonant_frequency": "145.8"},
        "telephony": {
            "sim_states": [{"raw": "READY", "text": "ready"}],
            "sim_count": 1, "sim_present": True,
            "operator": "TIM", "operator_numeric": "22201",
            "baseband": "g5300g-240301-240314-B-11526499",
            "network_type": "LTE",
            "signal": {"lte_rsrp_dbm": -91, "lte_rsrq_db": -11,
                       "level": 3, "level_text": "good"},
            "service_state": {"voice": "IN_SERVICE", "data": "IN_SERVICE"},
            "features": [], "props": {},
        },
        "wifi": {
            "enabled": True, "connected": True, "ssid": "Home network",
            "rssi_dbm": -47, "frequency_mhz": 5180, "link_speed_mbps": 1201,
            "bands_supported": ["2.4 GHz", "5 GHz", "6 GHz"],
            "standards": ["Wi-Fi 6 (11ax)", "Wi-Fi 6E", "Wi-Fi 5 (11ac)"],
            "interfaces": ["wlan0"], "features": [], "status_raw": "",
        },
        "connectivity": {
            "bluetooth": {"present": True, "enabled": True, "name": "Pixel 8 Pro",
                          "address": "", "le_supported": True, "version": "5.3"},
            "nfc": {"present": True, "enabled": True, "hce": True},
            "location": {"providers": ["fused", "gps", "network", "passive"],
                         "gnss_hardware": "Broadcom BCM47765",
                         "gps_feature": True},
            "features": [],
        },
        "security": {
            "verified_boot": {
                "state": "green", "label": "Intact",
                "explanation": ("The bootloader is locked and every partition "
                                "is signed by the manufacturer. The running "
                                "software is the original one: the collected "
                                "data is reliable."),
                "trusted": True, "verity_mode": "enforcing", "known": True,
            },
            "bootloader": {"locked": True, "locked_raw": "1",
                           "oem_unlock_supported": True,
                           "oem_unlock_allowed": False,
                           "vbmeta_digest": "6f2c1a8e94b3d5f7a1c8e2b4d6f8a0c2",
                           "vbmeta_device_state": "locked"},
            "knox": None,
            "root": {"detected": False, "su_binaries": [], "which_su": None,
                     "packages": [], "system_writable": False,
                     "shell_uid": "uid=2000(shell) gid=2000(shell)"},
            "selinux": {"mode": "Enforcing", "enforcing": True},
            "encryption": {"state": "encrypted", "type": "file",
                           "encrypted": True, "file_based": True},
            "build_signing": {"tags": "release-keys", "type": "user",
                              "debuggable": False, "secure": True,
                              "official": True},
            "settings": {"developer_options": True, "adb_enabled": True,
                         "unknown_sources": False},
            "props": {},
        },
        "packages": {
            "system_count": 214, "third_party_count": 63, "disabled_count": 4,
            "third_party": [], "google_services": [
                "com.google.android.gms", "com.android.vending",
                "com.google.android.gsf"],
            "has_play_services": True, "has_play_store": True,
            "gms_version": "24.15.18", "suspicious_packages": [],
        },
    }

    # The example IMEI used throughout public documentation: it passes the
    # Luhn check, so validation shows as it would on a real phone, yet it
    # belongs to no device -- which matters for screenshots of the demo.
    base = "49015420" + "323751"
    imei = base + luhn_check_digit(base)
    snapshot["identity"] = {
        "serials": {
            "values": {"ro": "3A0Y1XK9", "boot": "3A0Y1XK9",
                       "usb_transport": "3A0Y1XK9"},
            "primary": "3A0Y1XK9", "consistent": True, "distinct_count": 1,
        },
        "imeis": [imei], "meid": None, "sources": ["settings"],
        "screen": {"screen_on": True, "unlocked": True, "source": "nfc"},
        "notes": [],
    }
    snapshot["imei_analysis"] = analyse_imeis(
        [imei], device_brand="google", device_model="Pixel 8 Pro")

    # Demonstration hardware attestation. The values reproduce the shape of a
    # real certificate -- a Pixel also includes the identity among the attested
    # fields, which many other manufacturers do not.
    snapshot["attestation"] = {
        "available": True,
        "security_mode": "strongbox",
        "security_level": "strongbox",
        "security_label": "StrongBox — separate security chip",
        "attestation_version": 4,
        "keymint_version": 300,
        "challenge_matches": True,
        "requesting_package": "com.android.shell",
        "attested_identity": {"brand": "google", "manufacturer": "Google",
                              "model": "Pixel 8 Pro", "device": "husky",
                              "product": "husky"},
        "root_of_trust": {
            "verified_boot_state": "verified",
            "verified_boot_label": "Verified: boot chain intact and signed by "
                                   "the manufacturer",
            "device_locked": True,
            "verified_boot_key_sha256": _fake_digest("boot key"),
        },
        "os_version": "14.0.0",
        # Derived from the declared patch: a fixed date would drift away from
        # it and the demo would report a software/hardware mismatch.
        "os_patch_level": patch[:7],
        "vendor_patch_level": patch,
        "boot_patch_level": patch,
        "root_public_key_sha256": _fake_digest("attestation root"),
        "root_subject": "serialNumber=f92009e853b6b045",
        "root_self_signed": True,
        "root_known": True,
        "root_label": "Google hardware attestation root",
        "roots_file_present": True,
        "chain": {"checked": True, "length": 5, "signatures_valid": True, "broken_at": None,
                  "root_trusted": True, "roots_available": True, "revoked": [],
                  "revocation_list_date": today.isoformat()},
    }

    snapshot["history"] = {
        "manufactured": None,
        "setup_date": {"iso": (today - timedelta(days=88)).isoformat(), "packages": 214,
                       "days_ago": 88, "confident": True},
        "boot_count": 41,
        "boot_reason": "reboot,ota",
        "boot_history": [{"reason": r, "epoch": None, "abnormal": False}
                         for r in ("reboot,ota", "reboot,userrequested", "reboot,ota")],
        "crashes": {"counts": {"SYSTEM_TOMBSTONE": 2}, "labels": {
            "SYSTEM_TOMBSTONE": "native process crashes"},
            "since": (today - timedelta(days=4)).isoformat(), "available": True},
        "accounts": {"by_type": {}, "google": 0, "read": True},
    }

    snapshot["components"] = {
        "cameras": [
            {"position": "rear main", "sensor": "IMX989",
             "module_id": "DEMOCAM0001", "firmware_check": "OK",
             "firmware_matches": True},
            {"position": "front", "sensor": "IMX712",
             "module_id": "DEMOCAM0002", "firmware_check": "OK",
             "firmware_matches": True},
        ],
        "touch": {"controller_firmware": "0x3a12", "expected_firmware": "0x3a12",
                  "firmware_matches": True},
        "panel": {"SVC_OCTA": "DEMOPANEL001", "lcd_type": "SDC_AMB681AZ01"},
        "soc": {"machine": "ZUMA", "family": "Tensor", "soc_id": "0x9445",
                "chip_serial": "1000000001", "raw": {}},
        "storage_chip": {"manufacturer": "SK hynix", "product": "H28U74301AMR",
                         "chip_serial": "0x00000001"},
        "usb_link": {"current": "high-speed", "current_label": "USB 2.0",
                     "maximum": "high-speed", "maximum_label": "USB 2.0",
                     "current_mbps": 480.0},
        "kernel_sensor_nodes": {
            "accelerometer_sensor": {"name": "LSM6DSO", "vendor": "STMicro"},
            "proximity_sensor": {"name": "TMD3719", "vendor": "AMS"},
        },
        "fingerprint": {"name": "GF_HAS", "vendor": "Goodix"},
        "sources_available": 7,
    }

    engine = AuthenticityEngine(snapshot, specdb=SpecDatabase())
    report = engine.run()
    for f in snapshot["imei_analysis"]["findings"]:
        report["findings"].append({
            "severity": f["severity"], "category": "identity",
            "title": f["title"], "detail": f["detail"],
            "strength": "proven", "strength_label": "Proven",
            "evidence": {},
        })
    report = Analyzer._recount(report)
    report["disclaimer"] = (
        "DEMONSTRATION MODE — no device is connected. The data shown is sample "
        "data and only illustrates what the report looks like. "
    ) + report["disclaimer"]
    snapshot["report"] = report
    snapshot["summary"] = Analyzer._summary(snapshot)
    snapshot["meta"]["duration_seconds"] = 8.4
    snapshot["meta"]["finished_at"] = datetime.now(UTC).isoformat()
    snapshot["meta"]["catalog"] = {"specs_loaded": SpecDatabase().size,
                                   "specs_error": None}
    return snapshot


# ---------------------------------------------------------------- live demo

# Sensors the demo agent pretends to stream, as the real agent describes them.
_DEMO_SENSORS = [
    {"name": "BMI323 Accelerometer", "vendor": "Bosch", "type": 1},
    {"name": "BMI323 Gyroscope", "vendor": "Bosch", "type": 4},
    {"name": "MMC5633 Magnetometer", "vendor": "MEMSIC", "type": 2},
    {"name": "TCS3708 Light", "vendor": "AMS", "type": 5},
    {"name": "TCS3708 Proximity", "vendor": "AMS", "type": 8},
]

_THERMAL = {"battery": 31.4, "cpu-big": 44.2, "cpu-mid": 41.0, "cpu-little": 38.6,
            "gpu": 41.8, "skin-therm": 35.1, "modem": 37.9, "charger": 33.0}
_CPU_MAX = [1704000] * 4 + [2367000] * 4 + [2910000]


class DemoLive:
    """Plausible live streams for demo mode: slow phone motion, a passing
    finger, satellites drifting across the sky. Nothing here comes from a
    device; it exists so the Live page can be seen and documented."""

    def __init__(self, sink: Sink):
        self.sink = sink
        self._task: asyncio.Task | None = None
        rng = random.Random(7)
        self._sats = [
            {"constellation": c, "svid": svid, "elevation": rng.uniform(8, 82),
             "azimuth": rng.uniform(0, 360), "base_cn0": rng.uniform(22, 44)}
            for c, svid in [(1, 3), (1, 8), (1, 14), (1, 17), (1, 22), (1, 30),
                            (3, 5), (3, 15), (3, 21), (5, 11), (5, 23), (5, 34),
                            (6, 4), (6, 9), (6, 19), (6, 26), (4, 194), (2, 123)]
        ]

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        await self.sink({"type": "agent_status", "ok": True,
                         "info": {"type": "info", "sensors": _DEMO_SENSORS}})
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        t0 = time.monotonic()
        tick = 0
        rng = random.Random(1)
        while True:
            t = time.monotonic() - t0
            n = lambda s: rng.gauss(0, s)  # noqa: E731
            await self.sink({"type": "sensor", "sensorType": 1, "values": [
                0.6 * math.sin(t * 0.7) + n(0.04), 9.6 + 0.4 * math.cos(t * 0.5) + n(0.04),
                1.4 * math.sin(t * 0.35) + n(0.04)]})
            await self.sink({"type": "sensor", "sensorType": 4, "values": [
                0.25 * math.cos(t * 0.7) + n(0.01), 0.12 * math.sin(t * 1.1) + n(0.01),
                0.18 * math.cos(t * 0.35) + n(0.01)]})
            await self.sink({"type": "sensor", "sensorType": 2, "values": [
                22 + 6 * math.sin(t * 0.3) + n(0.4), -18 + 5 * math.cos(t * 0.3) + n(0.4),
                -38 + n(0.4)]})
            if tick % 5 == 0:
                await self.sink({"type": "sensor", "sensorType": 5,
                                 "values": [310 + 40 * math.sin(t * 0.2) + n(4)]})
                await self.sink({"type": "sensor", "sensorType": 8, "values": [5.0]})
                await self.sink(self._touch(t))
            if tick % 25 == 0:
                await self.sink(self._metrics(t, rng))
                await self.sink(self._gnss(t, rng))
            tick += 1
            await asyncio.sleep(0.04)

    def history(self) -> list[dict]:
        """Two minutes of past metrics for a newly connected page, so the
        temperature chart (one point per second) does not start empty."""
        rng = random.Random(2)
        return [self._metrics(-back, rng) for back in range(120, 0, -1)]

    @staticmethod
    def _touch(t: float) -> dict:
        # One finger sweeping the screen in a slow figure of eight, with a
        # short lift every few seconds.
        lifted = (t % 6) > 5
        points = [] if lifted else [{
            "slot": 0, "id": 1,
            "x": int(672 + 520 * math.sin(t * 0.9)),
            "y": int(1496 + 1250 * math.sin(t * 0.45)),
        }]
        return {"type": "touch", "points": points, "count": len(points),
                "max_x": 1343, "max_y": 2991}

    @staticmethod
    def _metrics(t: float, rng: random.Random) -> dict:
        thermal = {k: round(v + 1.2 * math.sin(t / 9 + i) + rng.gauss(0, 0.15), 1)
                   for i, (k, v) in enumerate(_THERMAL.items())}
        freqs = {f"cpu{i}": int(m * rng.choice([0.35, 0.55, 0.7, 0.85, 1.0]))
                 for i, m in enumerate(_CPU_MAX)}
        return {"type": "metrics", "timestamp": time.time(),
                "battery": {"level": 78, "current_ma": round(-412 + rng.gauss(0, 25), 1),
                            "voltage_v": round(4.012 + rng.gauss(0, 0.003), 3),
                            "temperature_c": thermal["battery"], "status": "Discharging"},
                "thermal": thermal, "cpu_freq_khz": freqs, "wifi_rssi": -47, "signal": 3}

    def _gnss(self, t: float, rng: random.Random) -> dict:
        sats = []
        for s in self._sats:
            cn0 = max(0.0, s["base_cn0"] + rng.gauss(0, 1.2))
            sats.append({"constellation": s["constellation"], "svid": s["svid"],
                         "cn0": round(cn0, 1), "elevation": s["elevation"],
                         "azimuth": (s["azimuth"] + t * 0.2) % 360,
                         "used": cn0 > 30})
        return {"type": "gnss", "count": len(sats),
                "used": sum(1 for s in sats if s["used"]), "satellites": sats}


# --------------------------------------------------------------- test demo

_DEMO_OUTCOMES = {
    "sensor_physics": ("passed", "Measured gravity (9.79 m/s^2) matches the expected value "
                       "to within 0.2% · The gyroscope at rest reads zero as it should · "
                       "The measured magnetic field (46.3 uT) is within Earth values.",
                       2.5),
    "vibration_imu": ("passed", "Vibration detected physically: the agitation measured by "
                      "the accelerometer goes from 0.007 to 0.112 m/s^2, 16 times as much.",
                      3.0),
    "wifi_scan": ("passed", "The receiver saw 11 networks on 2.4 GHz and 5 GHz, strength "
                  "from -38 to -88 dBm. The antenna and receive chain work.", 2.0),
    "storage_speed": ("passed", "256 MB written and flushed at 412 MB/s, normal for UFS.", 2.0),
    "charging": ("passed", "Charging from USB: 812 mA flowing into the battery at 4.08 V, "
                 "about 3.3 W.", 2.5),
    "stress": ("passed", "All 9 cores reached their rated frequency and the phone stayed up. "
               "Temperature went from 34 to 47 °C. In the last 10 s the fastest cores held "
               "82% of their rated speed.", 4.0),
    "microphone": ("passed", "The phone's microphone picked up the computer's tones: 700 Hz +38 dB, "
                   "1500 Hz +41 dB, 3000 Hz +33 dB over the room noise.", 7.0),
    "bluetooth": ("passed", "The radio came up in 2 s and was switched off again, as it was.", 3.0),
    "cellular": ("passed", "Registered on a network (LTE), signal level 3 of 4.", 1.5),
    "gnss": ("passed", "The receiver works: 14 satellites heard from 4 constellations, strongest "
             "41 dB-Hz.", 6.0),
    "speaker": ("passed", "Heard all three tones through the computer's microphone: "
                "1000 Hz +31 dB, 2500 Hz +36 dB, 4000 Hz +28 dB over the background.", 3.5),
}


class DemoTestSuite(TestSuite):
    """The real catalogue with simulated outcomes: automatic tests "measure"
    after a short delay and guided ones wait for the operator, as on a phone."""

    async def run(self, test_id: str, **params) -> dict[str, Any]:
        meta = next((t for t in self.catalogue() if t["id"] == test_id), None)
        if meta is None:
            return {}
        result = TestResult(test_id, meta["title"], meta["kind"], status="running",
                            started_at=time.time())
        await self._publish(result)
        outcome = _DEMO_OUTCOMES.get(test_id)
        if outcome:
            status, detail, delay = outcome
            await asyncio.sleep(delay)
            result.status, result.outcome_detail = status, detail
            result.finished_at = time.time()
            await self._publish(result)
        return result.to_dict()

    async def record_outcome(self, test_id: str, passed: bool, detail: str = "",
                             status: str | None = None) -> dict[str, Any]:
        result = self.results.get(test_id) or TestResult(test_id, test_id, "guided",
                                                         started_at=time.time())
        result.status = "inconclusive" if status == "inconclusive" else (
            "passed" if passed else "failed")
        result.outcome_detail = detail
        result.finished_at = time.time()
        await self._publish(result)
        return result.to_dict()

    async def cleanup(self) -> None:
        return None
