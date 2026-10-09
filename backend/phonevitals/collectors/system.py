"""System identity: build, OS, kernel, SoC, cross-partition consistency.

The important part is `partitions`. Android builds the device identity from
five independent partitions (system, vendor, odm, product, system_ext), each
with its own brand/manufacturer/model triple and its own build fingerprint. On
a genuine phone these agree, because they all come out of the same official
build.

Whoever rebrands a counterfeit almost always changes only `ro.product.system.*`
-- what apps read and what appears in settings -- and leaves vendor and odm
with the original manufacturer's values. The discrepancy is the signature of
counterfeiting, and it is very hard to hide completely without recompiling the
whole ROM.
"""

from __future__ import annotations

import re
from typing import Any

from .base import Collector, parse_props, to_int

# The five partitions that declare a product identity.
PARTITIONS = ("system", "vendor", "odm", "product", "system_ext")
IDENTITY_KEYS = ("brand", "manufacturer", "model", "device", "name")

# Fingerprint properties per partition. `bootimage` is not a product partition
# but carries a fingerprint anyway, and is one of the first to diverge when a
# foreign kernel or boot image is grafted in.
FINGERPRINT_PROPS = {
    "system": "ro.system.build.fingerprint",
    "vendor": "ro.vendor.build.fingerprint",
    "odm": "ro.odm.build.fingerprint",
    "product": "ro.product.build.fingerprint",
    "system_ext": "ro.system_ext.build.fingerprint",
    "bootimage": "ro.bootimage.build.fingerprint",
}

# ARM identifiers: implementer -> name, part number -> microarchitecture.
# These tell us which cores are really inside the phone, regardless of what
# the system properties claim.
ARM_IMPLEMENTERS = {
    "0x41": "ARM", "0x42": "Broadcom", "0x43": "Cavium", "0x44": "DEC",
    "0x46": "Fujitsu", "0x48": "HiSilicon", "0x49": "Infineon",
    "0x4d": "Motorola/Freescale", "0x4e": "NVIDIA", "0x50": "APM",
    "0x51": "Qualcomm", "0x53": "Samsung", "0x56": "Marvell",
    "0x61": "Apple", "0x66": "Faraday", "0x69": "Intel", "0x70": "Phytium",
    "0xc0": "Ampere",
}

ARM_PARTS = {
    "0xd03": "Cortex-A53", "0xd04": "Cortex-A35", "0xd05": "Cortex-A55",
    "0xd06": "Cortex-A65", "0xd07": "Cortex-A57", "0xd08": "Cortex-A72",
    "0xd09": "Cortex-A73", "0xd0a": "Cortex-A75", "0xd0b": "Cortex-A76",
    "0xd0c": "Neoverse-N1", "0xd0d": "Cortex-A77", "0xd0e": "Cortex-A76AE",
    "0xd40": "Neoverse-V1", "0xd41": "Cortex-A78", "0xd42": "Cortex-A78AE",
    "0xd43": "Cortex-A65AE", "0xd44": "Cortex-X1", "0xd46": "Cortex-A510",
    "0xd47": "Cortex-A710", "0xd48": "Cortex-X2", "0xd49": "Neoverse-N2",
    "0xd4a": "Neoverse-E1", "0xd4b": "Cortex-A78C", "0xd4c": "Cortex-X1C",
    "0xd4d": "Cortex-A715", "0xd4e": "Cortex-X3", "0xd4f": "Neoverse-V2",
    "0xd80": "Cortex-A520", "0xd81": "Cortex-A720", "0xd82": "Cortex-X4",
    "0xd84": "Neoverse-V3", "0xd85": "Cortex-X925", "0xd87": "Cortex-A725",
    "0xd8e": "Neoverse-N3",
    # Qualcomm custom Kryo cores (older Snapdragon 8xx).
    "0x201": "Kryo-Silver", "0x205": "Kryo-Gold", "0x211": "Kryo-2xx-Silver",
    "0x800": "Kryo-2xx-Gold", "0x801": "Kryo-2xx-Silver",
    "0x802": "Kryo-3xx-Gold", "0x803": "Kryo-3xx-Silver",
    "0x804": "Kryo-4xx-Gold", "0x805": "Kryo-4xx-Silver",
}


class SystemCollector(Collector):
    name = "system"
    title = "System and build"

    def commands(self) -> dict[str, str]:
        return {
            "sys.props": "getprop",
            "sys.cpuinfo": "cat /proc/cpuinfo",
            "sys.version": "cat /proc/version",
            "sys.uptime": "cat /proc/uptime",
            "sys.cmdline": "cat /proc/cmdline",
            # Serial number from three independent origins. These live here
            # rather than in the identity probe because they must always be
            # collected, including when IMEI reading is not requested or not
            # possible.
            "sys.serialno": "getprop ro.serialno",
            "sys.boot_serialno": "getprop ro.boot.serialno",
            "sys.vendor_serialno": "getprop ro.vendor.boot.serialno",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        props = parse_props(raw.get("sys.props", ""))
        cpuinfo = raw.get("sys.cpuinfo", "")

        return {
            "props": props,
            "props_count": len(props),
            "build": self._build(props),
            "os": self._os(props),
            "kernel": self._kernel(raw.get("sys.version", ""),
                                   raw.get("sys.cmdline", "")),
            "soc": self._soc(props, cpuinfo),
            "partitions": self._partitions(props),
            "fingerprints": self._fingerprints(props),
            "uptime_seconds": self._uptime(raw.get("sys.uptime", "")),
            "abis": [a for a in props.get("ro.product.cpu.abilist", "").split(",") if a],
            "ab_slot": props.get("ro.boot.slot_suffix", "") or None,
            "serials": self._serials(raw),
        }

    @staticmethod
    def _serials(raw: dict[str, str]) -> dict[str, str]:
        """Serial number from the sources readable over shell.

        `ro.serialno` comes from system properties, `ro.boot.serialno` is
        passed by the bootloader on the kernel command line. The third
        corroboration, the USB descriptor, is added by the orchestrator
        because it is a property of the transport, not of the device.
        """
        out: dict[str, str] = {}
        for key, prop in (("ro", "sys.serialno"),
                          ("boot", "sys.boot_serialno"),
                          ("vendor", "sys.vendor_serialno")):
            value = raw.get(prop, "").strip()
            if value and value != "unknown":
                out[key] = value
        return out

    # ------------------------------------------------------------------ parts

    @staticmethod
    def _build(props: dict[str, str]) -> dict[str, Any]:
        return {
            "fingerprint": props.get("ro.build.fingerprint", ""),
            "id": props.get("ro.build.id", ""),
            "display_id": props.get("ro.build.display.id", ""),
            "incremental": props.get("ro.build.version.incremental", ""),
            "type": props.get("ro.build.type", ""),
            "tags": props.get("ro.build.tags", ""),
            "date": props.get("ro.build.date", ""),
            # Note this is the date of the *installed* firmware, not of
            # manufacture: on any device that has taken an OTA the two are
            # years apart. It is not a proxy for the age of the hardware.
            "date_utc": to_int(props.get("ro.build.date.utc")),
            "host": props.get("ro.build.host", ""),
            "user": props.get("ro.build.user", ""),
            "description": props.get("ro.build.description", ""),
            "bootloader": props.get("ro.bootloader", ""),
            "baseband": props.get("gsm.version.baseband", "")
                        or props.get("ro.baseband", ""),
            "hardware": props.get("ro.hardware", ""),
            "board": props.get("ro.product.board", ""),
        }

    @staticmethod
    def _os(props: dict[str, str]) -> dict[str, Any]:
        sdk = to_int(props.get("ro.build.version.sdk"))
        return {
            "android_release": props.get("ro.build.version.release", ""),
            "sdk": sdk,
            "codename": props.get("ro.build.version.codename", ""),
            "security_patch": props.get("ro.build.version.security_patch", ""),
            "vendor_security_patch": props.get(
                "ro.vendor.build.security_patch", ""),
            "first_api_level": to_int(props.get("ro.product.first_api_level")),
            "treble": props.get("ro.treble.enabled", "") == "true",
            "vndk": props.get("ro.vndk.version", ""),
            # Manufacturer skins: One UI on Samsung, and so on.
            "oneui": props.get("ro.build.version.oneui", ""),
            "miui": props.get("ro.miui.ui.version.name", ""),
        }

    @staticmethod
    def _kernel(version: str, cmdline: str) -> dict[str, Any]:
        m = re.match(r"Linux version (\S+)", version.strip())
        return {
            "release": m.group(1) if m else "",
            "full": version.strip().split("\n")[0] if version.strip() else "",
            "cmdline": cmdline.strip(),
        }

    @staticmethod
    def _soc(props: dict[str, str], cpuinfo: str) -> dict[str, Any]:
        """Chip identity, declared and real.

        `declared` comes from properties, which can be rewritten.
        `hardware_line` and the cores come from /proc/cpuinfo, which reflects
        what the silicon actually answers: much harder to fake, because the
        kernel populates it from the CPU registers.

        Recent arm64 kernels (Tensor included) no longer emit a Hardware line
        at all, so an empty value means "not published", not "missing".
        """
        hardware_line = ""
        for line in cpuinfo.splitlines():
            if line.lower().startswith("hardware"):
                hardware_line = line.split(":", 1)[-1].strip()
                break

        # Group cores by (implementer, part): a modern big.LITTLE shows 2-3
        # distinct clusters.
        cores: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in cpuinfo.splitlines():
            line = line.strip()
            if not line:
                if current:
                    cores.append(current)
                    current = {}
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                current[k.strip().lower()] = v.strip()
        if current:
            cores.append(current)

        clusters: dict[tuple[str, str], int] = {}
        for core in cores:
            impl = core.get("cpu implementer", "")
            part = core.get("cpu part", "")
            if impl or part:
                clusters[(impl, part)] = clusters.get((impl, part), 0) + 1

        core_types = [
            {
                "implementer": ARM_IMPLEMENTERS.get(impl.lower(), impl),
                "implementer_id": impl,
                "part_id": part,
                "microarchitecture": ARM_PARTS.get(part.lower(), f"unknown ({part})"),
                "count": count,
            }
            for (impl, part), count in sorted(clusters.items(), key=lambda x: -x[1])
        ]

        return {
            "declared_manufacturer": props.get("ro.soc.manufacturer", ""),
            "declared_model": props.get("ro.soc.model", ""),
            "platform": props.get("ro.board.platform", ""),
            "hardware": props.get("ro.hardware", ""),
            "chipname": props.get("ro.hardware.chipname", ""),
            "hardware_line": hardware_line,
            "core_types": core_types,
            # Only blocks that describe a processor: older kernels end the file
            # with a separate Hardware/Revision/Serial block.
            "core_count_cpuinfo": sum(
                1 for core in cores if core.get("processor", "").isdigit()),
        }

    @staticmethod
    def _partitions(props: dict[str, str]) -> dict[str, Any]:
        """Extract the identity declared by each partition."""
        table: dict[str, dict[str, str]] = {}
        for part in PARTITIONS:
            entry: dict[str, str] = {}
            for key in IDENTITY_KEYS:
                # Android 10+ uses ro.product.<partition>.<field>.
                val = props.get(f"ro.product.{part}.{key}", "")
                if val:
                    entry[key] = val
            if entry:
                table[part] = entry

        # The "effective" values an app sees: what the framework resolves,
        # typically from system.
        effective = {
            key: props.get(f"ro.product.{key}", "")
            for key in IDENTITY_KEYS
        }
        return {"by_partition": table, "effective": effective}

    @staticmethod
    def _fingerprints(props: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for part, prop in FINGERPRINT_PROPS.items():
            val = props.get(prop, "")
            if val:
                out[part] = val
        if props.get("ro.build.fingerprint"):
            out["build"] = props["ro.build.fingerprint"]
        return out

    @staticmethod
    def _uptime(text: str) -> float | None:
        try:
            return float(text.split()[0])
        except (ValueError, IndexError):
            return None
