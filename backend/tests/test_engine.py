"""Check that the rules fire on the cases they must recognise.

The synthetic cases are purpose-built: a consistent Pixel 8 Pro, and a clone
claiming to be a Pixel 8 Pro while vendor and odm confess a rebranded MediaTek.
If the engine cannot separate those two it is useless.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phonevitals.analysis.authenticity import AuthenticityEngine
from phonevitals.analysis.specdb import SpecDatabase

# The dates in the "clean" fixture are relative to today: a recently updated
# device. Pinning them to an absolute date would make the test fail over time
# because the fixture aged, not because the engine regressed.
_TODAY = _dt.date.today()
RECENT_PATCH = (_TODAY - _dt.timedelta(days=45)).replace(day=5).isoformat()
RECENT_BUILD_UTC = int(time.time()) - 60 * 24 * 3600
RECENT_BATTERY_DATE = (_TODAY - _dt.timedelta(days=75)).isoformat()


def _identity(brand, manufacturer, model, device):
    return {"brand": brand, "manufacturer": manufacturer,
            "model": model, "device": device, "name": device}


GENUINE = {
    "system": {
        "build": {
            "fingerprint": "google/husky/husky:14/AP1A.240405.002/11480754:user/release-keys",
            "date_utc": RECENT_BUILD_UTC,
        },
        "os": {"android_release": "14", "sdk": 34, "security_patch": RECENT_PATCH},
        "soc": {
            "declared_manufacturer": "Google", "declared_model": "Tensor G3",
            "platform": "zuma", "hardware": "zuma", "hardware_line": "Zuma",
            "core_types": [
                {"implementer": "ARM", "part_id": "0xd05",
                 "microarchitecture": "Cortex-A510", "count": 4},
                {"implementer": "ARM", "part_id": "0xd4d",
                 "microarchitecture": "Cortex-A715", "count": 4},
                {"implementer": "ARM", "part_id": "0xd4e",
                 "microarchitecture": "Cortex-X3", "count": 1},
            ],
        },
        "partitions": {
            "by_partition": {
                p: _identity("google", "Google", "Pixel 8 Pro", "husky")
                for p in ("system", "vendor", "odm", "product", "system_ext")
            },
            "effective": _identity("google", "Google", "Pixel 8 Pro", "husky"),
        },
        "fingerprints": {
            p: "google/husky/husky:14/AP1A.240405.002/11480754:user/release-keys"
            for p in ("system", "vendor", "odm", "product", "build")
        },
    },
    "cpu": {"core_count": 9},
    "memory": {"nominal_gb": 12},
    "storage": {"nominal_gb": 256, "ufs_health": {
        "life_time_a": {"code": 1, "used_percent_range": "0-10%", "used_percent_max": 10},
        "eol_code": 1, "eol_description": "Normal",
    }},
    "display": {"resolution": {"width": 1344, "height": 2992},
                "refresh_rates": [120.0, 60.0]},
    "battery": {"cycle_count": 120, "health_percent": 94.0,
                "design_capacity_mah": 5050, "full_capacity_mah": 4747,
                "level_percent": 78,
                "manufacturing_date": {"iso": RECENT_BATTERY_DATE}},
    "sensors": {"count": 32, "vendors": ["Bosch", "STMicro"], "has": {
        "accelerometer": True, "gyroscope": True, "magnetic_field": True,
        "light": True, "proximity": True}},
    "cameras": {"count": 5},
    "security": {
        "verified_boot": {"state": "green", "label": "Intact", "trusted": True,
                          "known": True, "explanation": "Bootloader locked."},
        "bootloader": {"locked": True},
        "build_signing": {"tags": "release-keys", "type": "user",
                          "official": True, "debuggable": False, "secure": True},
        "root": {"detected": False, "su_binaries": [], "packages": [],
                 "system_writable": False},
        "knox": None,
    },
    "packages": {"has_play_services": True, "has_play_store": True,
                 "system_count": 210, "third_party_count": 38,
                 "gms_version": "24.15.18", "suspicious_packages": []},
    "identity": {"serials": {"values": {"ro": "1A2B3C4D"}, "primary": "1A2B3C4D",
                             "consistent": True, "distinct_count": 1}},
}

# Clone: system rebranded as Pixel, vendor/odm still MediaTek.
COUNTERFEIT = {
    "system": {
        "build": {
            "fingerprint": "Redmi/lancelot/lancelot:11/RP1A.200720.011:user/release-keys",
            "date_utc": 1650000000,
        },
        "os": {"android_release": "14", "sdk": 34, "security_patch": "2021-06-01"},
        "soc": {
            "declared_manufacturer": "Google", "declared_model": "Tensor G3",
            "platform": "zuma", "hardware": "mt6765",
            "hardware_line": "MT6765",
            "core_types": [
                {"implementer": "ARM", "part_id": "0xd03",
                 "microarchitecture": "Cortex-A53", "count": 4},
            ],
        },
        "partitions": {
            "by_partition": {
                "system": _identity("google", "Google", "Pixel 8 Pro", "husky"),
                "product": _identity("google", "Google", "Pixel 8 Pro", "husky"),
                "vendor": _identity("Redmi", "Xiaomi", "M2003J15SC", "lancelot"),
                "odm": _identity("Redmi", "Xiaomi", "M2003J15SC", "lancelot"),
            },
            "effective": _identity("google", "Google", "Pixel 8 Pro", "husky"),
        },
        "fingerprints": {
            "system": "google/husky/husky:14/AP1A.240405.002/11480754:user/release-keys",
            "vendor": "Redmi/lancelot/lancelot:11/RP1A.200720.011:user/release-keys",
            "build": "Redmi/lancelot/lancelot:11/RP1A.200720.011:user/release-keys",
        },
    },
    "cpu": {"core_count": 4},
    "memory": {"nominal_gb": 4},
    "storage": {"nominal_gb": 64, "ufs_health": {}},
    "display": {"resolution": {"width": 720, "height": 1600},
                "refresh_rates": [60.0]},
    "battery": {"cycle_count": 8, "health_percent": 71.0,
                "design_capacity_mah": 5000, "full_capacity_mah": 3550,
                "level_percent": 55},
    "sensors": {"count": 9, "vendors": ["mtk"], "has": {
        "accelerometer": True, "gyroscope": False, "magnetic_field": False,
        "light": True, "proximity": True}},
    "cameras": {"count": 2},
    "security": {
        "verified_boot": {"state": "orange", "label": "Bootloader unlocked",
                          "trusted": False, "known": True,
                          "explanation": "Bootloader unlocked."},
        "bootloader": {"locked": False},
        "build_signing": {"tags": "test-keys", "type": "userdebug",
                          "official": False, "debuggable": True, "secure": False},
        "root": {"detected": True, "su_binaries": ["/system/xbin/su"],
                 "packages": ["com.topjohnwu.magisk"], "system_writable": True},
        "knox": None,
    },
    "packages": {"has_play_services": False, "has_play_store": False,
                 "system_count": 154, "third_party_count": 12,
                 "suspicious_packages": ["com.topjohnwu.magisk"]},
    "identity": {"serials": {"values": {"ro": "ABC", "boot": "XYZ"},
                             "primary": "ABC", "consistent": False,
                             "distinct_count": 2}},
}


# Real case: a Samsung Galaxy A71 that shipped with Android 11 and was updated
# to 13. system/product/system_ext move to Android 13, vendor/odm stay on 11:
# this is how Project Treble is meant to work. The incremental build number
# stays the same across all partitions, and that is what proves they come from
# the same official release.
# An earlier version of the engine reported this case as a serious anomaly.
# This test case stops that defect from coming back.
_A71_SYSTEM = ("samsung/a71naxx/qssi:13/TP1A.220624.014/"
               "A715FXXSBDXB1:user/release-keys")
_A71_VENDOR = ("samsung/a71naxx/a71:11/RP1A.200720.012/"
               "A715FXXSBDXB1:user/release-keys")

TREBLE_UPGRADED = {
    "system": {
        "build": {
            "fingerprint": ("samsung/a71naeea/a71:13/TP1A.220624.014/"
                            "A715FXXSBDXB1:user/release-keys"),
            "date_utc": RECENT_BUILD_UTC,
        },
        "os": {"android_release": "13", "sdk": 33, "security_patch": RECENT_PATCH},
        "soc": {
            "declared_manufacturer": "Qualcomm", "declared_model": "SM6150",
            "platform": "sm6150", "hardware": "qcom",
            "hardware_line": "Qualcomm Technologies, Inc SDMMAGPIE",
            "core_types": [
                {"implementer": "Qualcomm", "part_id": "0x805",
                 "microarchitecture": "Kryo-4xx-Silver", "count": 6},
                {"implementer": "Qualcomm", "part_id": "0x804",
                 "microarchitecture": "Kryo-4xx-Gold", "count": 2},
            ],
        },
        "partitions": {
            "by_partition": {
                p: _identity("samsung", "samsung", "SM-A715F", "a71")
                for p in ("system", "vendor", "odm", "product", "system_ext")
            },
            "effective": _identity("samsung", "samsung", "SM-A715F", "a71"),
        },
        "fingerprints": {
            "system": _A71_SYSTEM, "product": _A71_SYSTEM,
            "system_ext": _A71_SYSTEM, "vendor": _A71_VENDOR,
            "odm": _A71_VENDOR, "bootimage": _A71_VENDOR,
        },
    },
    "cpu": {"core_count": 8},
    "memory": {"nominal_gb": 6},
    "storage": {"nominal_gb": 128, "ufs_health": {}},
    "display": {"resolution": {"width": 1080, "height": 2400},
                "refresh_rates": [60.0]},
    "battery": {"cycle_count": 295, "health_percent": 100.0,
                "design_capacity_mah": 4400, "full_capacity_mah": 4400,
                "level_percent": 62},
    "sensors": {"count": 37, "vendors": ["Samsung", "TDK-Invensense"], "has": {
        "accelerometer": True, "gyroscope": True, "magnetic_field": True,
        "light": True, "proximity": True}},
    "cameras": {"count": 4},
    "security": {
        "verified_boot": {"state": "green", "label": "Intact", "trusted": True,
                          "known": True, "explanation": "Bootloader locked."},
        "bootloader": {"locked": True},
        "build_signing": {"tags": "release-keys", "type": "user",
                          "official": True, "debuggable": False, "secure": True},
        "root": {"detected": False, "su_binaries": [], "packages": [],
                 "system_writable": False},
        "knox": {"warranty_bit": "0", "tripped": False,
                 "explanation": "Knox fuse intact."},
    },
    "packages": {"has_play_services": True, "has_play_store": True,
                 "system_count": 240, "third_party_count": 51,
                 "gms_version": "26.09.31", "suspicious_packages": []},
    "identity": {"serials": {"values": {"ro": "RZ8R1TEST01"},
                             "primary": "RZ8R1TEST01",
                             "consistent": True, "distinct_count": 1}},
}


# ─────────── CASE 4: the TEE contradicts the system properties ───────────
#
# The most careful clone rewrites every property consistently with the others:
# checks that compare the software against itself do not catch it. What it
# cannot rewrite is the certificate signed by the secure environment, which
# keeps declaring the device it really is.
ATTESTATION_LIES = {
    "system": {
        "partitions": {
            "by_partition": {
                p: {"brand": "samsung", "manufacturer": "samsung",
                    "model": "SM-S928B", "device": "e3q"}
                for p in ("system", "vendor", "odm", "product", "system_ext")
            },
            "effective": {"brand": "samsung", "manufacturer": "samsung",
                          "model": "SM-S928B", "device": "e3q"},
        },
        "build": {"fingerprint": "samsung/e3qxxx/e3q:14/UP1A.231005.007/"
                                 "S928BXXU1AXK5:user/release-keys",
                  "type": "user", "tags": "release-keys"},
        "os": {"android_release": "14", "sdk": 34,
               "security_patch": RECENT_PATCH},
        "soc": {"declared_model": "Snapdragon 8 Gen 3", "platform": "pineapple"},
    },
    "security": {
        "verified_boot": {"state": "green", "label": "Intact", "trusted": True,
                          "known": True, "explanation": "Bootloader locked."},
        "bootloader": {"locked": True},
        "build_signing": {"tags": "release-keys", "type": "user",
                          "official": True, "readable": True,
                          "debuggable": False, "secure": True},
        "root": {"detected": False, "su_binaries": [], "packages": [],
                 "system_writable": False},
        "knox": {"warranty_bit": "0", "tripped": False,
                 "explanation": "Knox fuse intact."},
    },
    "packages": {"has_play_services": True, "has_play_store": True,
                 "system_count": 220, "third_party_count": 40,
                 "gms_version": "26.09.31", "suspicious_packages": []},
    "identity": {"serials": {"values": {"ro": "R5CR8TEST01"},
                             "primary": "R5CR8TEST01",
                             "consistent": True, "distinct_count": 1}},
    "attestation": {
        "available": True,
        "security_mode": "tee",
        "security_level": "tee",
        "security_label": "TEE — secure environment inside the processor",
        "attestation_version": 4,
        "challenge_matches": True,
        # The chip signs the real model: an A52s sold as an S24 Ultra.
        "attested_identity": {"brand": "samsung", "manufacturer": "samsung",
                              "model": "SM-A528B", "device": "a52sxq"},
        "root_of_trust": {"verified_boot_state": "verified",
                          "verified_boot_label": "Verified",
                          "device_locked": True},
        "os_patch_level": RECENT_PATCH[:7],
        "root_known": None,
    },
}


# ───────── CASE 5: stock Pixel with a generic system fingerprint ─────────
#
# Regression case, taken from a real Pixel 8 (shiba) on stock firmware. The
# system partition fingerprint is `Android/generic_system/generic:...` while
# every other partition says `google`: that is the factory state of a Treble
# system image, not a rebrand.
#
# An earlier version of the engine compared those brands literally and reported
# "Different brands in the partition fingerprints" as a critical anomaly,
# scoring an untouched Pixel 8 at 0/100. Samsung never triggered it because its
# system fingerprint carries the real brand.
_PIXEL_STOCK = ("google/shiba/shiba:15/AP4A.250105.002/"
                "12ikbuild:user/release-keys")
_PIXEL_GENERIC = ("Android/generic_system/generic:15/AP4A.250105.002/"
                  "12ikbuild:user/release-keys")

PIXEL_GENERIC_SYSTEM = {
    "system": {
        "build": {"fingerprint": _PIXEL_STOCK, "date_utc": RECENT_BUILD_UTC},
        "os": {"android_release": "15", "sdk": 35, "security_patch": RECENT_PATCH},
        "soc": {
            "declared_manufacturer": "Google", "declared_model": "Tensor G3",
            "platform": "zuma", "hardware": "shiba", "hardware_line": "",
            "core_types": [
                {"implementer": "ARM", "part_id": "0xd46",
                 "microarchitecture": "Cortex-A510", "count": 4},
                {"implementer": "ARM", "part_id": "0xd4d",
                 "microarchitecture": "Cortex-A715", "count": 4},
                {"implementer": "ARM", "part_id": "0xd4e",
                 "microarchitecture": "Cortex-X3", "count": 1},
            ],
        },
        "partitions": {
            "by_partition": {
                "system": _identity("Android", "Android", "Generic System",
                                    "generic"),
                "vendor": _identity("google", "Google", "Pixel 8", "shiba"),
                "odm": _identity("google", "Google", "Pixel 8", "shiba"),
                "product": _identity("google", "Google", "Pixel 8", "shiba"),
                "system_ext": _identity("google", "Google", "Pixel 8", "shiba"),
            },
            "effective": _identity("google", "Google", "Pixel 8", "shiba"),
        },
        "fingerprints": {
            "system": _PIXEL_GENERIC, "vendor": _PIXEL_STOCK,
            "odm": _PIXEL_STOCK, "product": _PIXEL_STOCK,
            "system_ext": _PIXEL_STOCK, "build": _PIXEL_STOCK,
        },
    },
    "cpu": {"core_count": 9},
    "memory": {"nominal_gb": 8},
    # Storage inferred from /data, as on a real Pixel where SELinux denies
    # both /proc/partitions and /sys/block.
    "storage": {"nominal_gb": 128, "nominal_estimated": True,
                "ufs_health": {}},
    "display": {"resolution": {"width": 1080, "height": 2400},
                "refresh_rates": [120.0, 60.0]},
    "battery": {"cycle_count": 460, "health_percent": 95.1,
                "design_capacity_mah": 4550, "full_capacity_mah": 4328,
                "level_percent": 58,
                # Cell built shortly before first use: entirely normal, and
                # the pair the engine must not misread as a replacement.
                "manufacturing_date": {"iso": "2023-11-28"},
                "first_usage_date": {"iso": "2024-02-14"}},
    "sensors": {"count": 46, "vendors": ["Invensense", "AMS"], "has": {
        "accelerometer": True, "gyroscope": True, "magnetic_field": True,
        "light": True, "proximity": True}},
    "cameras": {"count": 2},
    "security": {
        "verified_boot": {"state": "green", "label": "Intact", "trusted": True,
                          "known": True, "explanation": "Bootloader locked."},
        "bootloader": {"locked": True},
        "build_signing": {"tags": "release-keys", "type": "user",
                          "official": True, "readable": True,
                          "debuggable": False, "secure": True},
        "root": {"detected": False, "su_binaries": [], "packages": [],
                 "system_writable": False},
        "knox": None,
    },
    "packages": {"has_play_services": True, "has_play_store": True,
                 "system_count": 230, "third_party_count": 45,
                 "gms_version": "26.24.34", "suspicious_packages": []},
    "identity": {"serials": {"values": {"ro": "0A1B2C3D4E5F6G"},
                             "primary": "0A1B2C3D4E5F6G",
                             "consistent": True, "distinct_count": 1}},
}


def titles(report):
    return [f["title"] for f in report["findings"]]


def check_dual_sim() -> list[str]:
    """Regression: a second IMEI is normal, not evidence of tampering.

    The two values are synthetic, on the 49015420 test TAC, laid out the way
    a dual-SIM Pixel 8 reports its pair: same TAC, consecutive serial numbers. Earlier versions raised a critical for the
    plurality itself, and raised the brand mismatch once per IMEI -- which,
    since the verdict is decided by counting findings by severity, gave one
    fact double weight.
    """
    import phonevitals.analysis.imei as imei_mod

    problems = []
    pair = ["490154201767409", "490154201767417"]

    report = imei_mod.analyse_imeis(pair, "google", "Pixel 8")
    sev = {f["title"]: f["severity"] for f in report["findings"]}
    print(f"\n{'=' * 70}\nCASE 6 — dual-SIM handset, two IMEIs\n{'=' * 70}")
    for f in report["findings"]:
        print(f"  [{f['severity'].upper():8}] {f['title']}")

    if any(s == "critical" for s in sev.values()):
        problems.append(
            "two valid IMEIs on a dual-SIM phone produced a critical finding")
    if "TAC consistent across slots" not in sev:
        problems.append("matching TACs across slots were not recognised")

    # Different TACs: worth a look, but not proof of a rewrite.
    differing = imei_mod.analyse_imeis(
        ["490154201767409", "490154211767415"], "google", "Pixel 8")
    dsev = {f["title"]: f["severity"] for f in differing["findings"]}
    if dsev.get("The IMEIs of this phone carry different TACs") != "warning":
        problems.append(
            "differing TACs are treated as proof of tampering; the GSMA does "
            "not guarantee one TAC per handset")

    # One brand mismatch must be reported once, not once per slot.
    class _StubDb:
        loaded, size, error = True, 1, None

        def lookup(self, tac):
            return imei_mod.TacEntry(tac=tac, brand="Oppo", model="A78")

    saved = imei_mod._DB
    imei_mod._DB = _StubDb()
    try:
        mismatch = imei_mod.analyse_imeis(pair, "google", "Pixel 8")
    finally:
        imei_mod._DB = saved
    n = sum(1 for f in mismatch["findings"]
            if f["title"] == "The IMEI belongs to another brand")
    if n != 1:
        problems.append(
            f"a single brand mismatch was reported {n} times on a dual-SIM "
            "phone, inflating the verdict")

    # A forged IMEI must still be caught: this is arithmetic, not convention.
    forged = imei_mod.analyse_imeis(["490154201767403"], "google", "Pixel 8")
    if not any(f["severity"] == "critical" for f in forged["findings"]):
        problems.append("an IMEI failing the Luhn check was no longer critical")

    return problems


def check_catalogue_and_links() -> list[str]:
    """Regressions on rules that used to raise false alarms on genuine phones.

    - The catalogue matched models entry by entry, by prefix in both
      directions: a Pixel 8 Pro whose codename was not listed could be
      measured against the Pixel 8 entry, and any spec difference became a
      warning.
    - A TAC registered by a parent company (Xiaomi for a Redmi, HMD Global
      for a Nokia) was reported as "the IMEI belongs to another brand".
    - A USB 3 phone on the USB 2.0 cable from its own box was warned about,
      and a link that was never negotiated was reported as "full speed".
    """
    import phonevitals.analysis.imei as imei_mod

    problems = []
    print(f"\n{'=' * 70}\nCASE 7 — catalogue lookup, TAC brands, USB link\n{'=' * 70}")

    db = SpecDatabase()
    pro = db.lookup(brand="google", model="Pixel 8 Pro", device="unlisted")
    if not pro or pro.get("name") != "Google Pixel 8 Pro":
        problems.append("a Pixel 8 Pro was matched to "
                        f"{(pro or {}).get('name')!r}, not to its own entry")
    if db.lookup(brand="google", model="Pixel 9a", device="unlisted"):
        problems.append("an unlisted Pixel 9a was matched to another model's entry")
    s23 = db.lookup(brand="samsung", model="SM-S911B/DS", device="unlisted")
    if not s23 or s23.get("name") != "Samsung Galaxy S23":
        problems.append("a Samsung part number no longer matches its prefix entry")

    class _StubDb:
        loaded, size, error = True, 1, None

        def __init__(self, brand):
            self.brand = brand

        def lookup(self, tac):
            return imei_mod.TacEntry(tac=tac, brand=self.brand, model="")

    saved = imei_mod._DB
    try:
        for tac_brand, device_brand in (("Xiaomi", "Redmi"), ("HMD Global", "Nokia")):
            imei_mod._DB = _StubDb(tac_brand)
            result = imei_mod.analyse_imeis(["490154201767409"], device_brand, "")
            if any(f["severity"] == "critical" for f in result["findings"]):
                problems.append(f"a {tac_brand} TAC on a {device_brand} phone was "
                                "reported as another brand")
    finally:
        imei_mod._DB = saved

    def usb_findings(link):
        snapshot = {"components": {"usb_link": link}}
        report = AuthenticityEngine(snapshot).run()
        return [f for f in report["findings"] if "USB" in f["title"]]

    slow = usb_findings({"current": "high-speed", "maximum": "super-speed-plus",
                         "current_label": "USB 2.0", "current_mbps": 480.0,
                         "maximum_label": "USB 3.1", "degraded": True})
    if any(f["severity"] in ("warning", "critical") for f in slow):
        problems.append("a USB 2.0 link on a USB 3 phone raised a warning")
    unknown = usb_findings({"current": "UNKNOWN", "maximum": "super-speed",
                            "current_label": "not negotiated",
                            "current_mbps": 0.0, "maximum_label": "USB 3.0"})
    if any(f["severity"] == "ok" for f in unknown):
        problems.append("a link that was never negotiated was reported as full speed")

    for problem in problems:
        print(f"  [FAILED  ] {problem}")
    if not problems:
        print("  [OK      ] all regressions hold")
    return problems


def check_tablet_and_custom_rom() -> list[str]:
    """A tablet on a custom ROM: named for what it is, judged as a tablet.

    Modelled on a Galaxy Tab S5e running LineageOS 22 (all identifiers made
    up): no proximity sensor, which every tablet lacks, an Android patch from
    this year over a vendor layer frozen years earlier.
    """
    import copy

    problems = []
    print(f"\n{'=' * 70}\nCASE 8 — tablet on a custom ROM\n{'=' * 70}")
    tab = copy.deepcopy(GENUINE)
    tab["system"]["form_factor"] = "tablet"
    tab["system"].setdefault("props", {}).update({
        "ro.lineage.build.version": "22.2",
        "ro.lineage.releasetype": "NIGHTLY",
        "ro.product.first_api_level": "28",
        "ro.vendor.build.security_patch": "2022-11-01",
    })
    tab["system"]["os"]["security_patch"] = "2026-09-01"
    tab.pop("attestation", None)
    has = tab.setdefault("sensors", {}).setdefault("has", {})
    has.update({"accelerometer": True, "light": True, "proximity": False})
    tab["sensors"]["count"] = tab["sensors"].get("count") or 20
    report = AuthenticityEngine(tab, specdb=SpecDatabase()).run()
    found = titles(report)
    if "Basic sensors missing" in found:
        problems.append("a tablet without a proximity sensor was reported as missing one")
    if "Custom ROM: LineageOS 22.2" not in found:
        problems.append("the custom ROM was not named")
    if "Firmware not updated since 2022-11" not in found:
        problems.append("a vendor layer 46 months behind the system was not reported")
    phone_words = [f["title"] for f in report["findings"]
                   if re.search(r"\b[Tt]he phone\b", f["title"] + f["detail"])]
    if phone_words:
        problems.append("a tablet is still called a phone in: " + ", ".join(phone_words))

    # The same tablet with its secure environment vouching for the hardware:
    # unlocked and reflashed by its owner, which is a modification, not fraud.
    tab["security"].update({
        "verified_boot": {"state": "orange", "label": "Bootloader unlocked",
                          "trusted": False, "known": True, "explanation": ""},
        "bootloader": {"locked": False},
        "build_signing": {"tags": "release-keys", "type": "userdebug",
                          "official": False, "debuggable": True, "readable": True},
        "knox": {"tripped": True, "explanation": ""},
    })
    tab["attestation"] = {
        "available": True, "security_mode": "tee", "security_level": "tee",
        "security_label": "TEE", "challenge_matches": True, "root_known": True,
        "chain": {"checked": True, "signatures_valid": True},
        "root_of_trust": {"verified_boot_state": "unverified", "device_locked": False},
    }
    modified = AuthenticityEngine(tab, specdb=SpecDatabase()).run()
    if modified["verdict"] != "modified":
        problems.append(f"an owner-modified original was judged {modified['verdict']}")
    if modified["score"] < 50:
        problems.append(f"modifications counted once each: score {modified['score']}")
    unanchored = copy.deepcopy(tab)
    unanchored["attestation"]["root_known"] = None
    if AuthenticityEngine(unanchored, specdb=SpecDatabase()).run()["verdict"] != "compromised":
        problems.append("without a verified attestation root a modified device "
                        "must stay compromised: nothing tells it from a clone")
    print(f"  modified tablet: {modified['score']}/100 ({modified['verdict']})")

    # A Wi-Fi-only part number on a board with a mobile radio.
    relabelled = copy.deepcopy(tab)
    relabelled["system"].setdefault("partitions", {}).setdefault("effective", {}).update(
        {"brand": "samsung", "model": "SM-T720", "device": "gts4lvwifi"})
    relabelled["sensors"]["features"] = ["android.hardware.telephony", "android.hardware.wifi"]
    spec = SpecDatabase().lookup("samsung", "SM-T720", "gts4lvwifi")
    radio = [i["title"] for i in SpecDatabase().compare(spec, relabelled)] if spec else []
    if "Mobile radio on a Wi-Fi-only model" not in radio:
        problems.append("a mobile radio inside a Wi-Fi-only model was not reported")

    for problem in problems:
        print(f"  FAILED {problem}")
    if not problems:
        print("  ok   tablet sensors, custom ROM, vendor patch, wording, modified verdict")
    return problems


def run(snapshot, label):
    engine = AuthenticityEngine(snapshot, specdb=SpecDatabase())
    report = engine.run()
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print(f"score {report['score']}/100 · verdict: {report['verdict']}")
    print(f"{report['headline']}\n")
    for sev in ("critical", "warning", "info", "ok"):
        for f in report["by_severity"][sev]:
            mark = {"critical": "[CRITICAL]", "warning": "[WARNING]",
                    "info": "[INFO]", "ok": "[OK]"}[sev]
            print(f"  {mark:12} {f['title']}  ({f['strength_label']})")
    return report


def main() -> int:
    genuine = run(GENUINE, "CASE 1 — consistent Pixel 8 Pro")
    fake = run(COUNTERFEIT, "CASE 2 — rebranded clone")

    failures = []

    if genuine["counts"]["critical"] != 0:
        failures.append(
            f"the consistent device produced {genuine['counts']['critical']} "
            "serious anomalies (false positives)")
    if genuine["score"] < 90:
        failures.append(f"score too low on the clean case: {genuine['score']}")

    must_catch = [
        "The partitions declare different identities",
        "Different brands in the partition fingerprints",
        "The declared chip does not match the one the kernel recognises",
        "Device with root privileges",
        "Unofficial build",
        "Basic sensors missing",
    ]
    found = titles(fake)
    for expected in must_catch:
        if expected not in found:
            failures.append(f"rule did not fire on the clone: \"{expected}\"")

    if fake["verdict"] != "compromised":
        failures.append(f"wrong verdict on the clone: {fake['verdict']}")

    # Third case: regression on the Treble false positive.
    treble = run(TREBLE_UPGRADED, "CASE 3 — upgraded Treble (real A71 data)")
    treble_titles = titles(treble)
    if treble["counts"]["critical"] != 0:
        failures.append(
            "a legitimate Treble upgrade produced serious anomalies: "
            + ", ".join(f["title"] for f in treble["by_severity"]["critical"]))
    if "Partitions on different Android releases (normal)" not in treble_titles:
        failures.append("the Treble mismatch was not recognised and explained")

    # Fourth case: the clone that is perfect in software, contradicted by the chip.
    liar = run(ATTESTATION_LIES, "CASE 4 — consistent properties, TEE disagrees")
    liar_titles = titles(liar)
    if "The secure environment contradicts the declared identity" not in liar_titles:
        failures.append(
            "hardware attestation failed to expose a false identity that is "
            "consistent across all partitions")
    if liar["counts"]["critical"] == 0:
        failures.append(
            "the disagreeing-attestation case produced no serious anomaly")
    # Control: without the attestation that device would pass clean.
    import copy
    blind = copy.deepcopy(ATTESTATION_LIES)
    blind.pop("attestation")
    blind_report = AuthenticityEngine(blind, specdb=SpecDatabase()).run()
    if blind_report["counts"]["critical"] != 0:
        failures.append(
            "the control without attestation should come out clean: the case "
            "does not isolate the contribution of attestation")

    # Fifth case: regression on the generic Treble system fingerprint.
    pixel = run(PIXEL_GENERIC_SYSTEM,
                "CASE 5 — stock Pixel, generic system fingerprint")
    pixel_titles = titles(pixel)
    if pixel["counts"]["critical"] != 0:
        failures.append(
            "a stock Pixel produced serious anomalies: "
            + ", ".join(f["title"] for f in pixel["by_severity"]["critical"]))
    if "Different brands in the partition fingerprints" in pixel_titles:
        failures.append(
            "the generic system fingerprint was read as a brand conflict: "
            "the Treble placeholder is being compared as a declared brand")
    if "Generic brand in the system fingerprint (normal)" not in pixel_titles:
        failures.append(
            "the generic system fingerprint was not recognised and explained")
    if "Battery manufactured after the phone entered service" in pixel_titles:
        failures.append(
            "a cell built before first use was reported as a replacement")

    # Sixth case: dual-SIM and eSIM handsets legitimately hold several IMEIs.
    failures.extend(check_dual_sim())

    # Seventh case: rules that used to raise false alarms on genuine phones.
    failures.extend(check_catalogue_and_links())

    # Eighth case: a tablet running a custom ROM.
    failures.extend(check_tablet_and_custom_rom())

    print(f"\n{'=' * 70}")
    if failures:
        print("RESULT: FAILED")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: PASSED — the engine separates the cases as expected.")
    print(f"  clean   {genuine['score']}/100 ({genuine['verdict']})")
    print(f"  clone   {fake['score']}/100 ({fake['verdict']}), "
          f"{fake['counts']['critical']} serious anomalies")
    print(f"  pixel   {pixel['score']}/100 ({pixel['verdict']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
