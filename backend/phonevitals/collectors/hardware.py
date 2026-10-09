"""Measured hardware: CPU, RAM, storage, display.

These collectors read the real values from the kernel instead of trusting
system properties. A phone claiming to be a Pixel 8 Pro while exposing 4
cores and 3.6 GB of RAM gives itself away here, not in getprop.
"""

from __future__ import annotations

import re
from typing import Any

from .base import Collector, parse_colon_kv, parse_kv, sysfs_dump, to_float, to_int


def _count_cpu_list(text: str) -> int | None:
    """Count the CPUs in a kernel cpu list such as `0-7` or `0-3,6-7`."""
    total = 0
    for chunk in text.strip().split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        first, _, last = chunk.partition("-")
        start, end = to_int(first), to_int(last or first)
        if start is None or end is None or end < start:
            return None
        total += end - start + 1
    return total or None


class CpuCollector(Collector):
    name = "cpu"
    title = "Processor"

    def commands(self) -> dict[str, str]:
        return {
            "cpu.present": "cat /sys/devices/system/cpu/present",
            "cpu.online": "cat /sys/devices/system/cpu/online",
            # One grep instead of three cats per core: on a 9-core Tensor the
            # subshell loop cost 2.3 s for data a single pass returns instantly.
            # Emits `cpu0.cpuinfo_max_freq=1800000`.
            "cpu.freqs": (
                "grep -sH . "
                "/sys/devices/system/cpu/cpu[0-9]*/cpufreq/cpuinfo_max_freq "
                "/sys/devices/system/cpu/cpu[0-9]*/cpufreq/cpuinfo_min_freq "
                "/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor "
                "2>/dev/null | sed -e 's|^/sys/devices/system/cpu/||' "
                "-e 's|/cpufreq/|.|' -e 's|:|=|'"
            ),
            "cpu.loadavg": "cat /proc/loadavg",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        per_core: dict[str, dict[str, str]] = {}
        for key, value in parse_kv(raw.get("cpu.freqs", "")).items():
            cpu, _, attr = key.partition(".")
            if cpu and attr:
                per_core.setdefault(cpu, {})[attr] = value

        cores = [
            {
                "id": cpu,
                "index": to_int(cpu.replace("cpu", "")),
                "max_khz": to_int(attrs.get("cpuinfo_max_freq")),
                "min_khz": to_int(attrs.get("cpuinfo_min_freq")),
                "governor": attrs.get("scaling_governor") or None,
            }
            for cpu, attrs in per_core.items()
        ]
        cores.sort(key=lambda c: c["index"] if c["index"] is not None else 999)

        # cpufreq nodes are not a complete census. Kernels before 4.x remove
        # the cpufreq link of a core when it goes offline, and MediaTek kernels
        # hotplug idle cores away, so the nodes alone can undercount a phone
        # that is simply idle. The present mask lists every core the kernel
        # knows is physically there.
        present = raw.get("cpu.present", "").strip()
        core_count = max(len(cores), _count_cpu_list(present) or 0)

        # Clusters are groups of cores sharing the same maximum frequency.
        clusters: dict[int, int] = {}
        for c in cores:
            if c["max_khz"]:
                clusters[c["max_khz"]] = clusters.get(c["max_khz"], 0) + 1

        return {
            "cores": cores,
            "core_count": core_count,
            "present": present,
            "online": raw.get("cpu.online", "").strip(),
            "clusters": [
                {"max_khz": khz, "count": n}
                for khz, n in sorted(clusters.items(), reverse=True)
            ],
            "max_khz": max(clusters) if clusters else None,
            "loadavg": raw.get("cpu.loadavg", "").strip(),
        }


class MemoryCollector(Collector):
    name = "memory"
    title = "Memory"

    def commands(self) -> dict[str, str]:
        return {
            "mem.info": "cat /proc/meminfo",
            "mem.zram": "cat /proc/swaps",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        info = parse_colon_kv(raw.get("mem.info", ""))
        total_kb = to_int(info.get("MemTotal", ""))
        avail_kb = to_int(info.get("MemAvailable", ""))
        free_kb = to_int(info.get("MemFree", ""))

        return {
            "total_kb": total_kb,
            "total_bytes": total_kb * 1024 if total_kb else None,
            "nominal_gb": self._nominal_gb(total_kb),
            "available_kb": avail_kb,
            "free_kb": free_kb,
            "swap_total_kb": to_int(info.get("SwapTotal", "")),
            "swap_free_kb": to_int(info.get("SwapFree", "")),
            "zram": bool(raw.get("mem.zram", "").strip().count("zram")),
            "raw": info,
        }

    @staticmethod
    def _nominal_gb(total_kb: int | None) -> int | None:
        """Round MemTotal up to the nearest commercial RAM size.

        The kernel reserves a slice of RAM for itself and its subsystems, so
        MemTotal is always below the nominal figure. Rounding is what makes
        the value comparable against a catalogue entry.
        """
        if not total_kb:
            return None
        gb = total_kb / 1024 / 1024
        for candidate in (1, 2, 3, 4, 6, 8, 12, 16, 18, 24, 32):
            # Kernel overhead rarely exceeds 12% of the total.
            if candidate * 0.86 <= gb <= candidate * 1.02:
                return candidate
        return round(gb)


class StorageCollector(Collector):
    name = "storage"
    title = "Storage"

    # Where the UFS descriptor directories live. The layout varies a lot:
    # some kernels expose them under the SCSI device, others under the UFS
    # controller in /sys/devices/platform. Pixel (Tensor) uses a single-level
    # platform path such as /sys/devices/platform/13200000.ufs, which a
    # two-level glob silently misses.
    UFS_DESCRIPTOR_PATHS = (
        "/sys/class/scsi_device/*/device",
        "/sys/devices/platform/*ufs*",
        "/sys/devices/platform/*/*ufs*",
        "/sys/devices/platform/soc/*ufs*",
    )

    @classmethod
    def _descriptor_probe(cls, descriptor: str) -> str:
        """Dump a UFS descriptor directory, distinguishing three states.

        On many devices the files exist but read back empty because SELinux
        denies the shell user. Telling "absent" apart from "present but
        unreadable" matters: in the second case the data is there and only
        needs more privilege, and the report should say so rather than imply
        the device does not expose it at all.
        """
        paths = " ".join(f"{base}/{descriptor}" for base in cls.UFS_DESCRIPTOR_PATHS)
        return (
            f'for h in {paths}; do '
            f'[ -d "$h" ] || continue; '
            f'echo "__dir__=$h"; '
            f'for f in "$h"/*; do [ -f "$f" ] || continue; '
            f'v=$(cat "$f" 2>/dev/null); '
            f'if [ -n "$v" ]; then echo "$(basename $f)=$v"; '
            f'else echo "__unreadable__=$(basename $f)"; fi; done; done'
        )

    def commands(self) -> dict[str, str]:
        return {
            "stor.df_k": "df -k /data 2>/dev/null",
            "stor.partitions": "cat /proc/partitions",
            # The SCSI descriptor exposes vendor, model and revision of the
            # actual memory chip.
            "stor.scsi": (
                'for d in /sys/class/scsi_device/*/device; do '
                '[ -d "$d" ] || continue; '
                'echo "dev=$(basename $(dirname $d))"; '
                'for f in vendor model rev state; do '
                '[ -f "$d/$f" ] && echo "  $f=$(cat $d/$f 2>/dev/null | tr -d \'\\n\')"; '
                'done; done'
            ),
            # Estimated remaining life of the SLC and MLC blocks plus the
            # end-of-life flag. Reveals heavily used storage inside a phone
            # sold as new.
            "stor.ufs_health": self._descriptor_probe("health_descriptor"),
            "stor.ufs_string": self._descriptor_probe("string_descriptors"),
            "stor.ufs_present": (
                'ls -d /sys/devices/platform/*ufs* /sys/devices/platform/*/*ufshc '
                '/sys/devices/platform/soc/*ufshc /sys/class/scsi_device/0:0:0:0 '
                '2>/dev/null | head -3'
            ),
            # On cheaper devices the storage is eMMC and the data lives
            # elsewhere. CID carries the chip serial and manufacturing date.
            # The card directory is named after its address (mmc0:0001), so
            # it has to be globbed.
            "stor.mmc": sysfs_dump("/sys/class/mmc_host/mmc0/mmc0:*"),
            # A microSD card is a block device too, and can be larger than the
            # internal storage: skip anything whose card type says SD.
            "stor.block_size": (
                'for b in /sys/block/sd* /sys/block/mmcblk0; do '
                '[ -d "$b" ] || continue; '
                '[ "$(cat $b/device/type 2>/dev/null)" = SD ] && continue; '
                'echo "$(basename $b)=$(cat $b/size 2>/dev/null)"; done'
            ),
            # /proc/partitions stays readable on some devices where sysfs is
            # closed by SELinux. Sizes are in 1 KiB blocks.
            "stor.proc_disks": 'grep -E " (sd[a-z]|mmcblk[0-9])$" /proc/partitions',
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        scsi = self._parse_scsi(raw.get("stor.scsi", ""))
        health_text = raw.get("stor.ufs_health", "")
        health_raw = parse_kv(health_text)
        mmc = parse_kv(raw.get("stor.mmc", ""))
        # mmc0 is the internal eMMC on eMMC phones but the microSD slot on
        # some UFS ones; the card type tells them apart (MMC, SD, SDIO).
        if mmc.get("type", "MMC").upper() != "MMC":
            mmc = {}
        blocks = parse_kv(raw.get("stor.block_size", ""))
        ufs_present = bool(raw.get("stor.ufs_present", "").strip())

        unreadable = [
            line.split("=", 1)[1]
            for line in health_text.splitlines()
            if line.startswith("__unreadable__=")
        ]
        directory_found = any(
            line.startswith("__dir__=") for line in health_text.splitlines()
        )
        health = {
            k: v for k, v in health_raw.items()
            if k not in ("__unreadable__", "__dir__")
        }

        # /sys/block/*/size is in 512-byte sectors.
        physical_bytes = None
        for sectors in blocks.values():
            n = to_int(sectors)
            if n and (physical_bytes is None or n * 512 > physical_bytes):
                physical_bytes = n * 512

        # /proc/partitions is in 1 KiB blocks and is the fallback when sysfs
        # is closed. It cannot tell a microSD card from internal storage: with
        # UFS present only its sd* LUNs count, otherwise only mmcblk0, the
        # first (internal) eMMC host.
        proc_disks = self._parse_proc_disks(raw.get("stor.proc_disks", ""))
        internal = ([d for d in proc_disks if d["name"].startswith("sd")]
                    or [d for d in proc_disks if d["name"] == "mmcblk0"])
        if internal:
            largest = max(d["bytes"] for d in internal)
            if physical_bytes is None or largest > physical_bytes:
                physical_bytes = largest

        data_total, data_used, data_avail = self._parse_df(raw.get("stor.df_k", ""))

        # Last resort, used on Pixel and any device where SELinux denies both
        # /proc/partitions and /sys/block: infer the commercial size from the
        # /data filesystem. It is an estimate, not a measurement, and is
        # flagged as such so no rule treats it as hard evidence.
        nominal = self._nominal_gb(physical_bytes)
        nominal_source = "block_device" if nominal else None
        if nominal is None and data_total:
            nominal = self._nominal_gb(data_total)
            nominal_source = "estimated_from_data_partition" if nominal else None

        if scsi or ufs_present or any(d["name"].startswith("sd") for d in proc_disks):
            storage_type = "UFS"
        elif mmc or any(d["name"].startswith("mmcblk") for d in proc_disks):
            storage_type = "eMMC"
        else:
            storage_type = "unknown"

        return {
            "type": storage_type,
            "devices": scsi,
            "disks": proc_disks,
            "ufs_health": self._decode_ufs_health(health, unreadable, directory_found),
            "ufs_strings": self._descriptor_values(raw.get("stor.ufs_string", "")),
            "emmc": self._decode_mmc(mmc),
            "physical_bytes": physical_bytes,
            "nominal_gb": nominal,
            "nominal_source": nominal_source,
            "nominal_estimated": nominal_source == "estimated_from_data_partition",
            "data_total_bytes": data_total,
            "data_used_bytes": data_used,
            "data_available_bytes": data_avail,
            "partitions_raw": raw.get("stor.partitions", ""),
        }

    @staticmethod
    def _descriptor_values(text: str) -> dict[str, str]:
        return {
            k: v for k, v in parse_kv(text).items()
            if k not in ("__unreadable__", "__dir__")
        }

    @staticmethod
    def _parse_scsi(text: str) -> list[dict[str, str]]:
        devices, current = [], None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("dev="):
                if current:
                    devices.append(current)
                current = {"id": stripped[4:]}
            elif current is not None and "=" in stripped:
                k, v = stripped.split("=", 1)
                current[k.strip()] = v.strip()
        if current:
            devices.append(current)
        return [d for d in devices if d.get("model") or d.get("vendor")]

    @staticmethod
    def _parse_proc_disks(text: str) -> list[dict[str, Any]]:
        disks: list[dict[str, Any]] = []
        for line in text.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            blocks_1k = to_int(parts[2])
            if blocks_1k is None:
                continue
            disks.append({
                "name": parts[3],
                "blocks_1k": blocks_1k,
                "bytes": blocks_1k * 1024,
            })
        return sorted(disks, key=lambda d: -d["bytes"])

    @staticmethod
    def _decode_ufs_health(health: dict[str, str],
                           unreadable: list[str] | None = None,
                           directory_found: bool = False) -> dict[str, Any] | None:
        """Translate the UFS health descriptor into readable percentages.

        life_time_est_a/b are banded: 0x01 means 0-10% of life consumed, 0x02
        10-20%, and so on up to 0x0B, which means the estimated useful life
        has been exceeded.
        """
        if not health:
            if unreadable or directory_found:
                return {
                    "available": False,
                    "unreadable_fields": sorted(set(unreadable or [])),
                    "note": (
                        "The UFS health descriptor is present on the device but "
                        "not readable by the shell user: SELinux reserves access "
                        "to the system. Storage wear therefore cannot be verified "
                        "without root privileges."
                    ),
                    "life_time_a": None, "life_time_b": None,
                    "eol_code": None, "eol_description": "not readable",
                    "raw": {},
                }
            return None

        def est(key: str) -> dict[str, Any] | None:
            v = health.get(key)
            if v is None:
                return None
            n = to_int(v.replace("0x", ""), None)
            if n is None:
                try:
                    n = int(v, 16)
                except ValueError:
                    return None
            if n <= 0:
                return {"code": n, "used_percent_range": "not available"}
            if n >= 0x0B:
                return {"code": n, "used_percent_range": "over 100% (end of life)",
                        "used_percent_max": 100}
            return {
                "code": n,
                "used_percent_range": f"{(n - 1) * 10}-{n * 10}%",
                "used_percent_max": n * 10,
            }

        eol = health.get("eol_info") or health.get("bPreEOLInfo")
        eol_code = to_int(eol, None)
        if eol_code is None and eol:
            try:
                eol_code = int(eol, 16)
            except ValueError:
                eol_code = None
        eol_map = {
            1: "Normal (less than 80% of the reserved blocks consumed)",
            2: "Warning (over 80% of the reserved blocks consumed)",
            3: "Critical (over 90%, storage near end of life)",
        }

        return {
            "available": True,
            "life_time_a": (est("life_time_est_a") or est("bDeviceLifeTimeEstA")
                            or est("life_time_estimation_a")),
            "life_time_b": (est("life_time_est_b") or est("bDeviceLifeTimeEstB")
                            or est("life_time_estimation_b")),
            "eol_code": eol_code,
            "eol_description": eol_map.get(eol_code or 0, "not available"),
            "raw": health,
        }

    @staticmethod
    def _decode_mmc(mmc: dict[str, str]) -> dict[str, Any] | None:
        if not mmc:
            return None
        return {
            "name": mmc.get("name"),
            "manfid": mmc.get("manfid"),
            "oemid": mmc.get("oemid"),
            "serial": mmc.get("serial"),
            "date": mmc.get("date"),
            "hwrev": mmc.get("hwrev"),
            "fwrev": mmc.get("fwrev"),
            "life_time": mmc.get("life_time"),
            "pre_eol_info": mmc.get("pre_eol_info"),
            "raw": mmc,
        }

    @staticmethod
    def _parse_df(text: str) -> tuple[int | None, int | None, int | None]:
        for line in text.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 4:
                total, used, avail = to_int(parts[1]), to_int(parts[2]), to_int(parts[3])
                return (
                    total * 1024 if total else None,
                    used * 1024 if used else None,
                    avail * 1024 if avail else None,
                )
        return None, None, None

    @staticmethod
    def _nominal_gb(physical_bytes: int | None) -> int | None:
        if not physical_bytes:
            return None
        gb = physical_bytes / 1000 / 1000 / 1000  # manufacturers use base 10
        for candidate in (16, 32, 64, 128, 256, 512, 1024):
            if candidate * 0.88 <= gb <= candidate * 1.05:
                return candidate
        return round(gb)


class DisplayCollector(Collector):
    name = "display"
    title = "Display"

    def commands(self) -> dict[str, str]:
        return {
            "disp.size": "wm size",
            "disp.density": "wm density",
            "disp.dumpsys": "dumpsys display",
            "disp.surface": "dumpsys SurfaceFlinger --display-id",
            # The panel identifies itself in sysfs. Samsung exposes lcd_type
            # and the module code; on Pixel the panel shows up among the DRM
            # nodes. A module replaced with a third-party one often carries a
            # different identifier from the factory part.
            "disp.panel": (
                'for p in /sys/class/lcd/panel/lcd_type '
                '/sys/class/lcd/panel/SVC_OCTA '
                '/sys/class/lcd/panel/SVC_OCTA_CHIPID '
                '/sys/class/lcd/panel/window_type '
                '/sys/class/backlight/panel0-backlight/device/panel_name '
                '/sys/class/backlight/panel0-backlight/device/serial_number '
                '/sys/devices/virtual/graphics/fb0/panel_name; do '
                '[ -f "$p" ] && echo "$(basename $p)=$(cat $p 2>/dev/null)"; done'
            ),
            "disp.drm": (
                'for d in /sys/class/drm/card*/; do '
                '[ -d "$d" ] || continue; '
                'n=$(basename $d); '
                's=$(cat $d/status 2>/dev/null); '
                '[ -n "$s" ] && echo "$n=$s"; done'
            ),
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        size = self._parse_wm(raw.get("disp.size", ""))
        density = self._parse_wm(raw.get("disp.density", ""))
        dump = raw.get("disp.dumpsys", "")
        modes = self._modes(dump)

        return {
            "physical_size": size.get("Physical size"),
            "override_size": size.get("Override size"),
            "physical_density": to_int(density.get("Physical density")),
            "override_density": to_int(density.get("Override density")),
            "resolution": self._resolution(size.get("Physical size", "")),
            "modes": modes,
            "refresh_rates": self._refresh_rates(dump, modes),
            "panel": parse_kv(raw.get("disp.panel", "")),
            "product_info": self._product_info(dump),
            "drm_connectors": parse_kv(raw.get("disp.drm", "")),
            "hdr_types": self._hdr(dump),
            "display_ids": raw.get("disp.surface", "").strip(),
        }

    @staticmethod
    def _parse_wm(text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in text.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
        return out

    @staticmethod
    def _resolution(text: str) -> dict[str, int] | None:
        m = re.match(r"(\d+)x(\d+)", text.strip())
        if not m:
            return None
        return {"width": int(m.group(1)), "height": int(m.group(2))}

    # Mode records grew fields over time. Android 13 emits
    #   {id=1, width=1440, height=3088, fps=120.000}
    # while Android 14+ inserts parentModeId, sfModeId and flags:
    #   {id=1, parentModeId=-1, sfModeId=0, flags=, width=1080, ...}
    # Anchoring width directly to id made every mode invisible on recent
    # devices, which silently disabled the refresh-rate check.
    _MODE_RE = re.compile(
        r"\{id=(\d+),[^{}]*?width=(\d+),\s*height=(\d+),\s*fps=([\d.]+)"
    )

    @classmethod
    def _modes(cls, dump: str) -> list[dict[str, Any]]:
        modes, seen = [], set()
        for m in cls._MODE_RE.finditer(dump):
            fps = round(float(m.group(4)), 1)
            key = (m.group(2), m.group(3), fps)
            if key in seen:
                continue
            seen.add(key)
            modes.append({
                "id": int(m.group(1)),
                "width": int(m.group(2)),
                "height": int(m.group(3)),
                "fps": fps,
            })
        return sorted(modes, key=lambda x: (-x["width"], -x["fps"]))

    @classmethod
    def _refresh_rates(cls, dump: str, modes: list[dict[str, Any]]) -> list[float]:
        rates = {m["fps"] for m in modes}
        # Independent fallback: the framework publishes the supported rates as
        # a plain list, which survives changes to the mode record format.
        m = re.search(r"mSupportedRefreshRates=\[([^\]]*)\]", dump)
        if m:
            for chunk in m.group(1).split(","):
                value = to_float(chunk.strip())
                if value:
                    rates.add(round(value, 1))
        return sorted(rates, reverse=True)

    @staticmethod
    def _product_info(dump: str) -> dict[str, str]:
        """Panel identity as reported over the display link.

        Pixel exposes no lcd_type node, but deviceProductInfo carries the
        panel part name and the manufacturer PnP id, which is the closest
        equivalent for spotting a replaced module.
        """
        m = re.search(r"deviceProductInfo=DeviceProductInfo\{([^}]*)\}", dump)
        if not m:
            return {}
        out: dict[str, str] = {}
        for key in ("name", "manufacturerPnpId", "productId", "modelYear"):
            km = re.search(rf"\b{key}=([^,}}]*)", m.group(1))
            if km and km.group(1).strip() not in ("", "null"):
                out[key] = km.group(1).strip()
        return out

    @staticmethod
    def _hdr(dump: str) -> list[str]:
        m = re.search(r"mSupportedHdrTypes=\[([^\]]*)\]", dump)
        if not m or not m.group(1).strip():
            return []
        names = {"1": "Dolby Vision", "2": "HDR10", "3": "HLG", "4": "HDR10+"}
        return [names.get(t.strip(), t.strip()) for t in m.group(1).split(",") if t.strip()]
