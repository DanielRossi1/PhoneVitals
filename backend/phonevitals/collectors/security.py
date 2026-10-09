"""Platform integrity: Verified Boot, bootloader, root, encryption.

This is the collector that establishes whether everything else can be
trusted.

The chain is this: the bootloader verifies each partition against a signature
before starting it (Android Verified Boot). If the bootloader is locked and
the state is `green`, the running software is exactly what the manufacturer
signed, so the system properties we read are reliable.

If instead the bootloader is unlocked or the state is `orange`/`yellow`,
anyone may have rewritten the partitions: at that point every collected value,
IMEI included, must be treated as declared by software rather than proven. It
does not mean the phone is fake, but it radically changes the weight of the
evidence, and the report has to say so clearly.
"""

from __future__ import annotations

import re
from typing import Any

from .base import Collector, parse_props

# Locations where an `su` binary is found on a rooted device.
SU_PATHS = (
    "/system/bin/su", "/system/xbin/su", "/sbin/su", "/su/bin/su",
    "/system/sbin/su", "/vendor/bin/su", "/data/local/tmp/su",
    "/data/local/bin/su", "/data/local/xbin/su", "/debug_ramdisk/su",
)

# Typical root and masking framework packages.
#
# Only packages that actually grant or hide root belong here. A plain terminal
# emulator does not: com.termux was listed once and produced a "tampering
# applications installed" warning on a clean, unrooted device. Naming an
# innocent app as evidence of tampering is the same class of error as a false
# counterfeit alarm.
ROOT_PACKAGES = (
    "com.topjohnwu.magisk", "com.noshufou.android.su", "eu.chainfire.supersu",
    "com.koushikdutta.superuser", "me.phh.superuser", "com.kingroot.kinguser",
    "com.kingo.root", "com.zachspong.temprootremovejb", "io.github.huskydg.magisk",
    "io.github.vvb2060.magisk", "me.weishu.kernelsu", "me.bmax.apatch",
)

# Virtualisation and spoofing apps that can alter the collected data.
SPOOF_PACKAGES = (
    "com.android.vending.billing.InAppBillingService.COIN",
    "de.robv.android.xposed.installer", "org.lsposed.manager",
    "com.lbe.parallel", "com.excelliance.dualaid", "io.va.exposed",
)


class SecurityCollector(Collector):
    name = "security"
    title = "Integrity and security"

    def commands(self) -> dict[str, str]:
        su_test = "; ".join(
            f'[ -e {p} ] && echo "su:{p}"' for p in SU_PATHS
        )
        root_alternatives = "|".join(re.escape(p) for p in ROOT_PACKAGES)
        return {
            # The properties that decide a verdict are read on their own, with
            # an exact match and no line limit.
            #
            # They all used to sit in a single grep closed by `head -80`, and on
            # a Samsung -- which has dozens of ro.boot.* properties -- the cut
            # fell exactly between ro.build.tags and ro.build.type. The result
            # was an empty build type, which the rule read as "unofficial": an
            # accusation of counterfeit ROM born from a truncated line. Missing
            # data must never be able to become an anomaly.
            "sec.props_exact": (
                "getprop | grep -E "
                "'^\\[(ro\\.build\\.tags|ro\\.build\\.type|ro\\.secure|"
                "ro\\.debuggable|ro\\.adb\\.secure|ro\\.crypto\\.state|"
                "ro\\.crypto\\.type)\\]'"
            ),
            "sec.props": (
                "getprop | grep -E "
                "'^\\[(ro\\.boot|ro\\.warranty|ro\\.oem|"
                "persist\\.sys\\.sb|vendor\\.boot)' | head -200"
            ),
            "sec.verifiedboot": "getprop ro.boot.verifiedbootstate",
            "sec.locked": "getprop ro.boot.flash.locked",
            "sec.verity": "getprop ro.boot.veritymode",
            "sec.vbmeta_digest": "getprop ro.boot.vbmeta.digest",
            "sec.vbmeta_state": "getprop ro.boot.vbmeta.device_state",
            "sec.warranty": "getprop ro.boot.warranty_bit",
            "sec.warranty2": "getprop ro.warranty_bit",
            "sec.selinux": "getenforce",
            "sec.crypto_state": "getprop ro.crypto.state",
            "sec.crypto_type": "getprop ro.crypto.type",
            "sec.su": su_test + "; true",
            "sec.which_su": "which su 2>/dev/null; command -v su 2>/dev/null",
            "sec.id": "id",
            "sec.packages_root": (
                "pm list packages --user 0 2>/dev/null | grep -E "
                f"'^package:({root_alternatives})[[:space:]]*$'"
            ),
            "sec.oem_unlock": "settings get global oem_unlock_supported 2>/dev/null",
            "sec.oem_unlock_allowed": "settings get global oem_unlock_allowed 2>/dev/null",
            "sec.dev_options": "settings get global development_settings_enabled 2>/dev/null",
            "sec.adb_enabled": "settings get global adb_enabled 2>/dev/null",
            "sec.unknown_sources": "settings get secure install_non_market_apps 2>/dev/null",
            "sec.mount": "cat /proc/mounts 2>/dev/null | grep -E ' (/system|/vendor|/) ' | head -10",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        props = parse_props(raw.get("sec.props", ""))
        props.update(parse_props(raw.get("sec.props_exact", "")))

        vbstate = raw.get("sec.verifiedboot", "").strip().lower()
        locked = raw.get("sec.locked", "").strip()
        verity = raw.get("sec.verity", "").strip().lower()

        su_found = [
            line.split(":", 1)[1]
            for line in raw.get("sec.su", "").splitlines()
            if line.startswith("su:")
        ]
        which_su = raw.get("sec.which_su", "").strip()
        # Only exact package names count as evidence, here as in the grep. A
        # substring match would accuse a clean phone that merely has a root
        # *detector* installed (several carry "magisk" in their package name),
        # the same class of error as the Termux case above.
        root_pkgs = [
            pkg for pkg in (
                line.replace("package:", "").strip()
                for line in raw.get("sec.packages_root", "").splitlines())
            if pkg in ROOT_PACKAGES
        ]

        # A read-write /system is anomalous on modern Android, where it is a
        # verified read-only partition.
        mounts = raw.get("sec.mount", "")
        system_rw = bool(re.search(r"\s/system\s.*\brw\b", mounts)) or \
                    bool(re.search(r"\s/\s.*\brw,", mounts))

        # adbd running as root (`adb root`, only possible on debuggable
        # builds) is root access too, even with no su binary anywhere.
        shell_id = raw.get("sec.id", "").strip()
        root_shell = bool(re.match(r"uid=0\b", shell_id))
        rooted = bool(su_found or which_su or root_pkgs or root_shell)

        return {
            "verified_boot": self._verified_boot(vbstate, locked, verity),
            "bootloader": {
                "locked": locked == "1" or locked.lower() == "true",
                "locked_raw": locked,
                "oem_unlock_supported": raw.get("sec.oem_unlock", "").strip() == "1",
                "oem_unlock_allowed": raw.get("sec.oem_unlock_allowed", "").strip() == "1",
                "vbmeta_digest": raw.get("sec.vbmeta_digest", "").strip(),
                "vbmeta_device_state": raw.get("sec.vbmeta_state", "").strip(),
            },
            "knox": self._knox(raw, props),
            "root": {
                "detected": rooted,
                "su_binaries": su_found,
                "which_su": which_su or None,
                "packages": root_pkgs,
                "system_writable": system_rw,
                "shell_uid": shell_id,
                "root_shell": root_shell,
            },
            "selinux": {
                "mode": raw.get("sec.selinux", "").strip() or "n/a",
                "enforcing": raw.get("sec.selinux", "").strip().lower() == "enforcing",
            },
            "encryption": {
                "state": raw.get("sec.crypto_state", "").strip(),
                "type": raw.get("sec.crypto_type", "").strip(),
                "encrypted": raw.get("sec.crypto_state", "").strip() == "encrypted",
                "file_based": raw.get("sec.crypto_type", "").strip() == "file",
            },
            "build_signing": {
                "tags": props.get("ro.build.tags", ""),
                "type": props.get("ro.build.type", ""),
                "debuggable": props.get("ro.debuggable", "") == "1",
                "secure": props.get("ro.secure", "") == "1",
                # A public official build is `release-keys` + `user`.
                "official": props.get("ro.build.tags", "") == "release-keys"
                            and props.get("ro.build.type", "") == "user",
                # Distinguishes "read and different from what it should be"
                # from "not read at all". Without this the two situations lead
                # to the same conclusion, which is wrong.
                "readable": bool(props.get("ro.build.tags")
                                 and props.get("ro.build.type")),
            },
            "settings": {
                "developer_options": raw.get("sec.dev_options", "").strip() == "1",
                "adb_enabled": raw.get("sec.adb_enabled", "").strip() == "1",
                "unknown_sources": raw.get("sec.unknown_sources", "").strip() == "1",
            },
            "props": props,
        }

    @staticmethod
    def _verified_boot(state: str, locked: str, verity: str) -> dict[str, Any]:
        """Translate the Verified Boot state and explain its consequences."""
        meanings = {
            "green": (
                "Intact",
                "The bootloader is locked and every partition is signed by the "
                "manufacturer. The running software is the original one: the "
                "collected data is reliable.",
                True,
            ),
            "yellow": (
                "Signed with a custom key",
                "The bootloader is locked but the partitions are signed with a "
                "key loaded by the user, not the manufacturer's. The system has "
                "been replaced with a third-party one.",
                False,
            ),
            "orange": (
                "Bootloader unlocked",
                "The bootloader is unlocked: any software may have been "
                "installed and no partition is verified. Everything read from "
                "the system, IMEI included, is a claim made by software and not "
                "evidence.",
                False,
            ),
            "red": (
                "Verification failed",
                "Partition verification failed: the software has been tampered "
                "with. The device is not in a trustworthy state.",
                False,
            ),
        }
        label, explanation, trusted = meanings.get(state, (
            "Not available",
            "The device does not expose the Verified Boot state. On some models "
            "the property is not readable without privileges; on others its "
            "absence indicates a modified system.",
            False,
        ))
        return {
            "state": state or "n/a",
            "label": label,
            "explanation": explanation,
            "trusted": trusted,
            "verity_mode": verity or "n/a",
            "known": state in meanings,
        }

    @staticmethod
    def _knox(raw: dict[str, str], props: dict[str, str]) -> dict[str, Any] | None:
        """Samsung Knox warranty bit.

        It is a hardware fuse: once blown by loading unofficial software it
        does not come back, not even by reflashing the original ROM. It reads 0
        on a never-tampered phone, 1 after any unofficial flash. On non-Samsung
        devices the property simply does not exist.
        """
        bit = (raw.get("sec.warranty", "").strip()
               or raw.get("sec.warranty2", "").strip()
               or props.get("ro.boot.warranty_bit", "")
               or props.get("ro.warranty_bit", ""))
        if not bit:
            return None
        tripped = bit.strip() == "1"
        return {
            "warranty_bit": bit.strip(),
            "tripped": tripped,
            "explanation": (
                "The Knox fuse is blown: unofficial software was loaded onto this "
                "device at some point. This is irreversible and voids the warranty."
                if tripped else
                "The Knox fuse is intact: there is no record of unofficial "
                "software ever having been loaded."
            ),
        }


class PackagesCollector(Collector):
    name = "packages"
    title = "Applications"

    def commands(self) -> dict[str, str]:
        return {
            "pkg.system_count": "pm list packages --user 0 -s 2>/dev/null | wc -l",
            "pkg.third_count": "pm list packages --user 0 -3 2>/dev/null | wc -l",
            "pkg.disabled": "pm list packages --user 0 -d 2>/dev/null | wc -l",
            "pkg.third": "pm list packages --user 0 -3 2>/dev/null | head -200",
            "pkg.gms": (
                "pm list packages --user 0 2>/dev/null | grep -E "
                "'com.google.android.gms|com.android.vending|"
                "com.google.android.gsf' | head -10"
            ),
            "pkg.gms_version": "dumpsys package com.google.android.gms | grep -m2 versionName",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        third = [
            line.replace("package:", "").strip()
            for line in raw.get("pkg.third", "").splitlines() if line.strip()
        ]
        gms = [
            line.replace("package:", "").strip()
            for line in raw.get("pkg.gms", "").splitlines() if line.strip()
        ]

        suspicious = sorted(
            set(third) & set(ROOT_PACKAGES + SPOOF_PACKAGES)
        )

        return {
            "system_count": self._n(raw.get("pkg.system_count")),
            "third_party_count": self._n(raw.get("pkg.third_count")),
            "disabled_count": self._n(raw.get("pkg.disabled")),
            "third_party": third,
            "google_services": gms,
            # The absence of Google services on a device claiming to be a Pixel
            # or a European-market Samsung is highly suspicious.
            "has_play_services": "com.google.android.gms" in gms,
            "has_play_store": "com.android.vending" in gms,
            "gms_version": self._version(raw.get("pkg.gms_version", "")),
            "suspicious_packages": suspicious,
        }

    @staticmethod
    def _n(text: str | None) -> int | None:
        try:
            return int((text or "").strip().split()[0])
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _version(text: str) -> str:
        m = re.search(r"versionName=(\S+)", text)
        return m.group(1) if m else ""
