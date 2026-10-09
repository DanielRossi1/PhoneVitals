"""Per-component identifiers, to recognise replaced parts.

A phone is not a monolithic object: cameras, digitizer, panel, fingerprint
reader and storage are modules with their own identity, which the driver
exposes in sysfs. The manufacturer uses it for service; we need it for a
different question -- is this part the one that left the factory, or was it
swapped?

What can and cannot be concluded. The presence of an identifier proves nothing
on its own: there is no public registry saying which camera module code was
fitted to a given serial number. What can be done, and what this module does,
is collect the identifiers and put them in the report so they are comparable --
between two units of the same model, or against the physical appearance of the
part. Where a judgement is possible it is given: a digitizer firmware the
driver flags as unrecognised, or a fingerprint reader the system lists but that
does not respond, are readable anomalies.

Many of these nodes are manufacturer-specific: Samsung is by far the most
generous, Google exposes almost nothing. Absence is never read as a problem.
"""

from __future__ import annotations

import re
from typing import Any

from .base import Collector, parse_kv, sysfs_files


class ComponentsCollector(Collector):
    name = "components"
    title = "Component identifiers"

    def commands(self) -> dict[str, str]:
        return {
            # -- cameras -------------------------------------------------------
            # Samsung exposes, per lens, the loaded firmware and the module
            # code, which identifies supplier and batch. A module replaced with
            # a salvaged one carries a code the phone does not expect, and in
            # that case the driver's "checkfw" field reports a mismatch.
            "comp.camera": sysfs_files([
                "/sys/class/camera/rear/rear_camfw",
                "/sys/class/camera/rear/rear_camfw_full",
                "/sys/class/camera/rear/rear_checkfw_user",
                "/sys/class/camera/rear/rear_checkfw_factory",
                "/sys/class/camera/rear/rear_sensorid",
                "/sys/class/camera/rear/rear_moduleid",
                "/sys/class/camera/rear/rear2_camfw",
                "/sys/class/camera/rear/rear2_moduleid",
                "/sys/class/camera/rear/rear3_camfw",
                "/sys/class/camera/rear/rear3_moduleid",
                "/sys/class/camera/rear/rear4_camfw",
                "/sys/class/camera/rear/rear4_moduleid",
                "/sys/class/camera/front/front_camfw",
                "/sys/class/camera/front/front_checkfw_user",
                "/sys/class/camera/front/front_sensorid",
                "/sys/class/camera/front/front_moduleid",
                "/sys/class/camera/camera/rear_camtype",
                "/sys/class/camera/camera/front_camtype",
            ]),

            # -- digitizer -----------------------------------------------------
            # `fw_version` reports two values: the firmware running on the
            # controller and the one in the update file shipped with the system.
            # If they differ, the touch controller is not the one this build
            # expects -- typical after a full glass replacement.
            "comp.touch": sysfs_files([
                "/sys/class/sec/tsp/fw_version",
                "/sys/class/sec/tsp/status",
                "/sys/class/sec/tsp/support_feature",
                "/sys/class/sec/tsp/prox_power_off",
                "/sys/class/sec/sec_touchscreen/fw_version",
                "/sys/class/sec/sec_touchscreen/status",
                "/sys/class/touchscreen/fw_version",
                "/sys/class/touchscreen/vendor",
                "/sys/class/touchscreen/product_id",
            ]),

            # -- panel ---------------------------------------------------------
            # SVC_OCTA is the display module service code: what a repair centre
            # reads to know which spare part to order, and it changes when the
            # panel is replaced.
            "comp.panel": sysfs_files([
                "/sys/class/lcd/panel/SVC_OCTA",
                "/sys/class/lcd/panel/SVC_OCTA_CHIPID",
                "/sys/class/lcd/panel/SVC_OCTA_DDI_CHIPID",
                "/sys/class/lcd/panel/lcd_type",
                "/sys/class/lcd/panel/window_type",
                "/sys/class/lcd/panel/manufacture_date",
                "/sys/class/lcd/panel/cell_id",
                "/sys/class/lcd/panel/octa_id",
            ]),

            # -- fingerprint reader --------------------------------------------
            "comp.fingerprint": sysfs_files([
                "/sys/class/fingerprint/fingerprint/name",
                "/sys/class/fingerprint/fingerprint/vendor",
                "/sys/class/fingerprint/fingerprint/adm",
                "/sys/class/fingerprint/fingerprint/sensortest",
                "/sys/class/fingerprint/fingerprint/type_check",
                "/sys/class/fingerprint/fingerprint/position",
            ]),

            # -- chip identity as read by the kernel ----------------------------
            # These are not system properties: the driver derives them from the
            # SoC registers at boot. Rewriting properties to pass one chip off
            # as another does not touch these, which stay truthful.
            "comp.soc0": sysfs_files([
                "/sys/devices/soc0/machine",
                "/sys/devices/soc0/family",
                "/sys/devices/soc0/soc_id",
                "/sys/devices/soc0/revision",
                "/sys/devices/soc0/raw_id",
                "/sys/devices/soc0/raw_version",
                "/sys/devices/soc0/platform_version",
                "/sys/devices/soc0/serial_number",
                "/sys/devices/soc0/vendor",
                "/sys/devices/soc0/accessory_chip",
                "/sys/devices/system/soc/soc0/machine",
                "/sys/devices/system/soc/soc0/soc_id",
                "/sys/bus/soc/devices/soc0/machine",
                "/sys/bus/soc/devices/soc0/family",
                "/sys/bus/soc/devices/soc0/soc_id",
                "/sys/bus/soc/devices/soc0/revision",
            ]),

            # -- storage --------------------------------------------------------
            # An eMMC CID contains the manufacturer code, product name,
            # revision, serial number and manufacturing date: it identifies the
            # individual chip fitted.
            "comp.mmc": sysfs_files([
                "/sys/class/mmc_host/mmc*/mmc*:*/cid",
                "/sys/class/mmc_host/mmc*/mmc*:*/name",
                "/sys/class/mmc_host/mmc*/mmc*:*/manfid",
                "/sys/class/mmc_host/mmc*/mmc*:*/oemid",
                "/sys/class/mmc_host/mmc*/mmc*:*/serial",
                "/sys/class/mmc_host/mmc*/mmc*:*/date",
                "/sys/class/mmc_host/mmc*/mmc*:*/fwrev",
                "/sys/class/mmc_host/mmc*/mmc*:*/hwrev",
            ]),

            # -- USB port -------------------------------------------------------
            # The negotiated speed says whether port and cable are working at
            # their class: an oxidised connector or damaged data pins make the
            # link fall back to a lower speed. So does a USB 2.0 cable or host
            # port, which is why a slow link is a hint and not a verdict.
            "comp.usb": sysfs_files([
                "/sys/class/udc/*/current_speed",
                "/sys/class/udc/*/maximum_speed",
                "/sys/class/udc/*/state",
            ]),

            # -- sensor inventory according to the kernel ------------------------
            # The framework list comes through the HAL; this comes from the
            # drivers. A sensor declared by the HAL but absent here is simulated.
            # Emits `sensorN.name=` / `sensorN.vendor=`.
            "comp.sensor_nodes": (
                "grep -sH . /sys/class/sensors/*/name /sys/class/sensors/*/vendor "
                "2>/dev/null | sed -e 's|^/sys/class/sensors/||' -e 's|/|.|' "
                "-e 's|:|=|'"
            ),
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        camera = parse_kv(raw.get("comp.camera", ""))
        touch = parse_kv(raw.get("comp.touch", ""))
        panel = parse_kv(raw.get("comp.panel", ""))
        finger = parse_kv(raw.get("comp.fingerprint", ""))
        soc0 = parse_kv(raw.get("comp.soc0", ""))
        mmc = parse_kv(raw.get("comp.mmc", ""))
        usb = parse_kv(raw.get("comp.usb", ""))

        sensor_nodes: dict[str, dict[str, str]] = {}
        for key, value in parse_kv(raw.get("comp.sensor_nodes", "")).items():
            node, _, attr = key.partition(".")
            if node and attr in ("name", "vendor"):
                sensor_nodes.setdefault(node, {})[attr] = value

        return {
            "cameras": self._describe_cameras(camera),
            "camera_raw": camera,
            "touch": self._describe_touch(touch),
            "panel": panel,
            "fingerprint": finger,
            "soc": self._describe_soc(soc0),
            "storage_chip": self._describe_mmc(mmc),
            "usb_link": self._describe_usb(usb),
            "kernel_sensor_nodes": sensor_nodes,
            "sources_available": sum(
                1 for d in (camera, touch, panel, finger, soc0, mmc, usb) if d),
        }

    # ---------------------------------------------------------------- cameras

    # "rear_camfw" looks like "S5KGW3 N N" or
    # "S5KGW3 A71XXU3BUC1 A71XXU3BUC1": the first field is the sensor.
    _FW_RE = re.compile(r"^(\S+)(?:\s+(\S+))?(?:\s+(\S+))?")

    def _describe_cameras(self, values: dict[str, str]) -> list[dict[str, Any]]:
        positions = {
            "rear": "rear main",
            "rear2": "rear 2",
            "rear3": "rear 3",
            "rear4": "rear 4",
            "front": "front",
        }
        out: list[dict[str, Any]] = []
        for prefix, label in positions.items():
            fw = values.get(f"{prefix}_camfw", "")
            module = values.get(f"{prefix}_moduleid", "")
            sensor_id = values.get(f"{prefix}_sensorid", "")
            check = values.get(f"{prefix}_checkfw_user", "")
            if not (fw or module or sensor_id):
                continue

            match = self._FW_RE.match(fw) if fw else None
            entry: dict[str, Any] = {
                "position": label,
                "sensor": match.group(1) if match else "",
                "firmware": match.group(2) if match and match.group(2) else "",
                "module_id": module,
                "sensor_id": sensor_id,
            }

            # The Samsung driver writes "NG" when the module firmware does not
            # match what the build expects, "OK" when it does.
            if check:
                entry["firmware_check"] = check
                entry["firmware_matches"] = check.strip().upper().startswith("OK")
            out.append(entry)
        return out

    # -------------------------------------------------------------- digitizer

    @staticmethod
    def _describe_touch(values: dict[str, str]) -> dict[str, Any]:
        if not values:
            return {}
        version = values.get("fw_version", "")
        # Typical format: "SE_ic 0x1234 / phone 0x1234" -- the first is what
        # runs on the controller, the second what the build expects.
        found = re.findall(r"0x[0-9a-fA-F]+", version)
        out: dict[str, Any] = {"raw": values}
        if version:
            out["firmware_version"] = version
        if len(found) >= 2:
            out["controller_firmware"] = found[0]
            out["expected_firmware"] = found[1]
            out["firmware_matches"] = found[0].lower() == found[1].lower()
        if values.get("status"):
            out["status"] = values["status"]
        return out

    # -------------------------------------------------------------------- SoC

    @staticmethod
    def _describe_soc(values: dict[str, str]) -> dict[str, Any]:
        if not values:
            return {}
        return {
            "machine": values.get("machine", ""),
            "family": values.get("family", ""),
            "soc_id": values.get("soc_id", ""),
            "revision": values.get("revision", ""),
            "platform_version": values.get("platform_version", ""),
            # The SoC serial number is unique per physical chip: two phones
            # cannot share it.
            "chip_serial": values.get("serial_number", ""),
            "raw": values,
        }

    # ---------------------------------------------------------------- storage

    # Codes of the main eMMC/UFS memory manufacturers, from the JEDEC registry.
    MANFID = {
        "0x000011": "Toshiba / Kioxia",
        "0x000013": "Micron",
        "0x000015": "Samsung",
        "0x000045": "SanDisk / Western Digital",
        "0x000070": "Kingston",
        "0x000090": "SK hynix",
        "0x0000fe": "Micron",
    }

    def _describe_mmc(self, values: dict[str, str]) -> dict[str, Any]:
        if not values:
            return {}
        out: dict[str, Any] = {"raw": values}
        for key, value in values.items():
            base = key.rsplit("_", 1)[-1]
            if base == "name":
                out["product"] = value
            elif base == "manfid":
                out["manufacturer_id"] = value
                out["manufacturer"] = self.MANFID.get(value.lower(), "")
            elif base == "serial":
                out["chip_serial"] = value
            elif base == "date":
                out["manufacture_date"] = value
            elif base == "fwrev":
                out["firmware_revision"] = value
        return out

    # -------------------------------------------------------------------- USB

    SPEEDS = {
        "low-speed": ("USB 1.0", 1.5),
        "full-speed": ("USB 1.1", 12.0),
        "high-speed": ("USB 2.0", 480.0),
        "super-speed": ("USB 3.0", 5000.0),
        "super-speed-plus": ("USB 3.1", 10000.0),
        "UNKNOWN": ("not negotiated", 0.0),
    }

    def _describe_usb(self, values: dict[str, str]) -> dict[str, Any]:
        if not values:
            return {}
        current = values.get("current_speed", "")
        maximum = values.get("maximum_speed", "")
        out: dict[str, Any] = {
            "current": current,
            "maximum": maximum,
            "state": values.get("state", ""),
        }
        label, mbps = self.SPEEDS.get(current, ("", 0.0))
        if label:
            out["current_label"] = label
            out["current_mbps"] = mbps
        top_label, top_mbps = self.SPEEDS.get(maximum, ("", 0.0))
        if top_label:
            out["maximum_label"] = top_label
        # If the controller can do more than it is doing, the bottleneck is in
        # the cable, the host port or the connector.
        if mbps and top_mbps and mbps < top_mbps:
            out["degraded"] = True
        return out
