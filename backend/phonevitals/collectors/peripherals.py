"""Peripherals: sensors, cameras, input, audio, biometrics, vibration.

This is the inventory of what the phone *claims* to have. Comparing it against
what it should have (specdb) and verifying it actually responds (guided tests
and the on-device agent) happen later: this module only takes stock, including
the chip vendor names, which are themselves a hint of authenticity.
"""

from __future__ import annotations

import re
from typing import Any

from .base import Collector, to_int

# Sensor type id, as in `android.sensor.X(N)` -> (readable name, key).
SENSOR_TYPES = {
    1: ("Accelerometer", "accelerometer"),
    2: ("Magnetometer", "magnetic_field"),
    3: ("Orientation (deprecated)", "orientation"),
    4: ("Gyroscope", "gyroscope"),
    5: ("Ambient light", "light"),
    6: ("Barometer", "pressure"),
    7: ("Temperature (deprecated)", "temperature"),
    8: ("Proximity", "proximity"),
    9: ("Gravity", "gravity"),
    10: ("Linear acceleration", "linear_acceleration"),
    11: ("Rotation vector", "rotation_vector"),
    12: ("Relative humidity", "relative_humidity"),
    13: ("Ambient temperature", "ambient_temperature"),
    14: ("Uncalibrated magnetometer", "magnetic_field_uncalibrated"),
    15: ("Game rotation vector", "game_rotation_vector"),
    16: ("Uncalibrated gyroscope", "gyroscope_uncalibrated"),
    17: ("Significant motion", "significant_motion"),
    18: ("Step detector", "step_detector"),
    19: ("Step counter", "step_counter"),
    20: ("Geomagnetic rotation vector", "geomagnetic_rotation_vector"),
    21: ("Heart rate", "heart_rate"),
    28: ("Uncalibrated accelerometer", "accelerometer_uncalibrated"),
    35: ("6DoF pose", "pose_6dof"),
    36: ("Motion detect", "motion_detect"),
}


class SensorCollector(Collector):
    name = "sensors"
    title = "Sensors"

    def commands(self) -> dict[str, str]:
        return {
            "sens.list": "dumpsys sensorservice",
            "sens.features": "pm list features",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        sensors = self._parse_sensors(raw.get("sens.list", ""))
        features = [
            line.split(":", 1)[1].strip()
            for line in raw.get("sens.features", "").splitlines()
            if line.startswith("feature:") and ":" in line
        ]

        # Group by family: the UI shows one accelerometer, not accelerometer
        # plus uncalibrated accelerometer plus gravity.
        by_type: dict[str, list[dict]] = {}
        for s in sensors:
            by_type.setdefault(s["type_name"], []).append(s)

        vendors = sorted({s["vendor"] for s in sensors if s.get("vendor")})

        return {
            "sensors": sensors,
            "count": len(sensors),
            "by_type": by_type,
            "vendors": vendors,
            "features": features,
            "has": {
                key: any(s["type_id"] == tid for s in sensors)
                for tid, (_, key) in SENSOR_TYPES.items()
            },
        }

    @staticmethod
    def _parse_sensors(text: str) -> list[dict[str, Any]]:
        """Parse the sensor list lines of dumpsys sensorservice.

        Typical format:
        0x00000001) LSM6DSO Accelerometer | STMicro | ver: 1 |
            type: android.sensor.accelerometer(1) | perm: n/a | flags: 0x...
        """
        sensors: list[dict[str, Any]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            m = re.match(r"^(0x[0-9a-fA-F]+)\)\s*(.+)$", line)
            if not m:
                continue
            handle, rest = m.group(1), m.group(2)
            fields = [f.strip() for f in rest.split("|")]
            if len(fields) < 3:
                continue

            name, vendor = fields[0], fields[1]
            type_id, type_uri = None, ""
            version = None
            for f in fields[2:]:
                if f.startswith("type:"):
                    tm = re.search(r"type:\s*(\S+?)\((\d+)\)", f)
                    if tm:
                        type_uri, type_id = tm.group(1), int(tm.group(2))
                elif f.startswith("ver:"):
                    version = to_int(f.split(":", 1)[1])

            label, key = SENSOR_TYPES.get(
                type_id or -1, (type_uri or "Unknown", "unknown")
            )
            sensors.append({
                "handle": handle,
                "name": name,
                "vendor": vendor,
                "version": version,
                "type_id": type_id,
                "type_uri": type_uri,
                "type_name": label,
                "type_key": key,
            })
        return sensors


class CameraCollector(Collector):
    name = "cameras"
    title = "Cameras"

    def commands(self) -> dict[str, str]:
        return {
            "cam.dumpsys": "dumpsys media.camera",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        dump = raw.get("cam.dumpsys", "")
        cameras = self._parse_cameras(dump)

        # The format of dumpsys media.camera varies a lot between
        # manufacturers. Some builds print a detailed "Camera N information:"
        # block, but many (Samsung and recent Pixel among them) omit it and
        # publish only the count and the id map. In that case the camera
        # count is still recoverable, while the detailed characteristics come
        # from the on-device agent, which asks CameraManager directly.
        declared = self._declared_count(dump)
        public_ids = re.findall(r'Device\s+(\S+)\s+maps to\s+"([^"]*)"', dump)

        if not cameras and public_ids:
            cameras = [
                {"id": mapped or dev, "facing": "undeclared",
                 "megapixels": None, "pixel_array": None,
                 "focal_lengths_mm": [], "apertures": [],
                 "detail_source": "list (characteristics not exposed by dumpsys)"}
                for dev, mapped in public_ids
            ]

        count = len(cameras) or declared or 0

        return {
            "cameras": cameras,
            "count": count,
            "declared_count": declared,
            "public_ids": [mapped or dev for dev, mapped in public_ids],
            "back_count": sum(1 for c in cameras if c.get("facing") == "rear"),
            "front_count": sum(1 for c in cameras if c.get("facing") == "front"),
            "details_available": bool(cameras and cameras[0].get("pixel_array")),
            "hal_version": self._hal(dump),
        }

    @staticmethod
    def _declared_count(dump: str) -> int | None:
        """Count declared by the service, independent of the dump format."""
        for pattern in (r"Number of camera devices:\s*(\d+)",
                        r"Number of normal camera devices:\s*(\d+)",
                        r"Number of public camera devices[^:]*:\s*(\d+)"):
            m = re.search(pattern, dump)
            if m:
                return int(m.group(1))
        return None

    @staticmethod
    def _hal(dump: str) -> str:
        m = re.search(r"Camera module API version:\s*(\S+)", dump)
        return m.group(1) if m else ""

    @classmethod
    def _parse_cameras(cls, dump: str) -> list[dict[str, Any]]:
        """Split the dump per camera and extract the key characteristics.

        Real megapixels are computed from android.sensor.info.pixelArraySize,
        the physical sensor matrix. That value comes from the camera module
        driver, not from marketing.
        """
        cameras: list[dict[str, Any]] = []
        blocks = re.split(r"Camera (\S+) information:", dump)
        # blocks = [prefix, id1, body1, id2, body2, ...]
        for i in range(1, len(blocks) - 1, 2):
            cam_id, body = blocks[i], blocks[i + 1]
            cameras.append(cls._parse_one(cam_id, body))
        return cameras

    @staticmethod
    def _metadata_value(body: str, tag: str) -> str:
        """Raw value text of one camera metadata entry.

        The service dumps metadata in the camera_metadata format, where the
        tag is followed by its numeric id and type, and the values sit in
        brackets on the next line:

            android.sensor.info.pixelArraySize (f0006): int32[2]
              [4080 3072 ]

        The id is hexadecimal and often contains decimal digits, so a pattern
        that grabs "the first numbers after the tag" reads the id instead of
        the value. A plain `tag: value` line is accepted as well.
        """
        m = re.search(
            re.escape(tag) + r"(?![\w.])"
            + r"(?:\s*\([0-9a-fA-F]+\))?\s*:?[ \t]*(?:[a-z]+\d*\[\d+\])?\s*"
            + r"(?:\[([^\]]*)\]|([^\n]*))",
            body)
        if not m:
            return ""
        return (m.group(1) if m.group(1) is not None else m.group(2) or "").strip()

    @classmethod
    def _parse_one(cls, cam_id: str, body: str) -> dict[str, Any]:
        def ints(tag: str) -> list[int]:
            return [int(n) for n in re.findall(r"-?\d+", cls._metadata_value(body, tag))]

        def floats(tag: str) -> list[float]:
            return [float(n) for n in
                    re.findall(r"-?\d+(?:\.\d+)?", cls._metadata_value(body, tag))]

        m = re.search(r"Facing:\s*(\w+)", body)
        facing_raw = (m.group(1) if m else
                      cls._metadata_value(body, "android.lens.facing")).upper()
        facing = {"BACK": "rear", "FRONT": "front",
                  "EXTERNAL": "external"}.get(facing_raw, facing_raw.lower())

        pixels = ints("android.sensor.info.pixelArraySize")
        w, h = (pixels[0], pixels[1]) if len(pixels) >= 2 else (None, None)
        active = ints("android.sensor.info.activeArraySize")
        phys = floats("android.sensor.info.physicalSize")
        focals = floats("android.lens.info.availableFocalLengths")
        apertures = floats("android.lens.info.availableApertures")
        level = cls._metadata_value(body, "android.info.supportedHardwareLevel")
        flash = cls._metadata_value(body, "android.flash.info.available")

        return {
            "id": cam_id,
            "facing": facing,
            "pixel_array": {"width": w, "height": h} if w and h else None,
            "megapixels": round(w * h / 1_000_000, 1) if w and h else None,
            "active_array": (
                {"left": active[0], "top": active[1],
                 "width": active[2], "height": active[3]}
                if len(active) >= 4 else None
            ),
            # Physical sensor size in millimetres.
            "physical_size_mm": (
                {"width": phys[0], "height": phys[1]} if len(phys) >= 2 else None
            ),
            "focal_lengths_mm": focals[:6],
            "apertures": apertures[:6],
            "hardware_level": level.split()[0] if level else "",
            "has_flash": bool(re.match(r"(?:true|1)\b", flash, re.I)),
        }


class InputCollector(Collector):
    name = "input"
    title = "Input devices"

    def commands(self) -> dict[str, str]:
        return {
            # getevent -pl lists every /dev/input device with name and
            # capabilities. Needed to know which device is the touchscreen
            # before opening a live stream on it.
            "in.getevent": "getevent -pl 2>/dev/null",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        devices = self._parse_getevent(raw.get("in.getevent", ""))
        touchscreen = next((d for d in devices if d["is_touchscreen"]), None)
        return {
            "devices": devices,
            "count": len(devices),
            "touchscreen": touchscreen,
            "key_devices": [d for d in devices if d["is_keys"]],
        }

    @staticmethod
    def _parse_getevent(text: str) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        section = ""

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            m = re.match(r"^add device \d+:\s*(\S+)", line)
            if m:
                if current:
                    devices.append(current)
                current = {
                    "path": m.group(1), "name": "", "events": set(),
                    "abs": {}, "keys": [],
                }
                section = ""
                continue
            if current is None:
                continue

            nm = re.match(r"^\s*name:\s*\"(.*)\"", line)
            if nm:
                current["name"] = nm.group(1)
                continue

            # A section header carries the first entry on the same line:
            #     ABS (0003): ABS_MT_SLOT : value 0, min 0, max 9, ...
            # so it is stripped off and the rest of the line parsed like a
            # continuation line. Skipping the whole line lost the first axis
            # (ABS_MT_SLOT on most touchscreens) and the first keys.
            sm = re.match(r"^\s{4}(\w+)(?:\s*\([0-9a-fA-F]+\))?\s*:?(.*)$", line)
            if sm and sm.group(1) in ("KEY", "ABS", "REL", "SW", "LED", "SND", "FF"):
                section = sm.group(1)
                current["events"].add(section)
                line = sm.group(2)

            # ABS lines with ranges:
            # "ABS_MT_POSITION_X : value 0, min 0, max 1439, ..."
            am = re.match(
                r"^\s*(ABS_\w+)\s*:\s*value\s*(-?\d+),\s*min\s*(-?\d+),\s*max\s*(-?\d+)",
                line)
            if am:
                current["abs"][am.group(1)] = {
                    "value": int(am.group(2)),
                    "min": int(am.group(3)),
                    "max": int(am.group(4)),
                }
                continue

            if section == "KEY":
                current["keys"].extend(re.findall(r"(KEY_\w+|BTN_\w+)", line))

        if current:
            devices.append(current)

        out = []
        for d in devices:
            abs_keys = d["abs"]
            is_touch = any(k.startswith("ABS_MT_POSITION") for k in abs_keys)
            out.append({
                "path": d["path"],
                "name": d["name"],
                "event_types": sorted(d["events"]),
                "abs_axes": abs_keys,
                "keys": sorted(set(d["keys"]))[:60],
                "key_count": len(set(d["keys"])),
                "is_touchscreen": is_touch,
                "is_keys": bool(d["keys"]) and not is_touch,
                "touch_max_x": abs_keys.get("ABS_MT_POSITION_X", {}).get("max"),
                "touch_max_y": abs_keys.get("ABS_MT_POSITION_Y", {}).get("max"),
                "max_slots": (abs_keys.get("ABS_MT_SLOT", {}).get("max") or 0) + 1
                             if "ABS_MT_SLOT" in abs_keys else None,
            })
        return out


class AudioCollector(Collector):
    name = "audio"
    title = "Audio"

    def commands(self) -> dict[str, str]:
        return {
            "aud.dumpsys": "dumpsys audio | head -150",
            "aud.cards": "cat /proc/asound/cards 2>/dev/null",
            "aud.pcm": "cat /proc/asound/pcm 2>/dev/null",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        dump = raw.get("aud.dumpsys", "")
        return {
            "cards": raw.get("aud.cards", "").strip(),
            "pcm_devices": [
                line.strip() for line in raw.get("aud.pcm", "").splitlines()
                if line.strip()
            ],
            "mode": self._find(dump, r"mode:\s*(\w+)"),
            "ringer_mode": self._find(dump, r"[Rr]inger mode:\s*(\w+)"),
            "output_devices": sorted(set(re.findall(
                r"\b(SPEAKER|EARPIECE|WIRED_HEADSET|WIRED_HEADPHONE|"
                r"BLUETOOTH_A2DP|BLUETOOTH_SCO|USB_HEADSET|USB_DEVICE|HDMI)\b", dump))),
            "has_speaker": "SPEAKER" in dump,
            "has_earpiece": "EARPIECE" in dump,
        }

    @staticmethod
    def _find(text: str, pattern: str) -> str:
        m = re.search(pattern, text)
        return m.group(1) if m else ""


class BiometricCollector(Collector):
    name = "biometrics"
    title = "Biometrics"

    def commands(self) -> dict[str, str]:
        return {
            "bio.fingerprint": "dumpsys fingerprint | head -60",
            "bio.face": "dumpsys face | head -40",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        fp = raw.get("bio.fingerprint", "")
        face = raw.get("bio.face", "")

        return {
            "fingerprint": {
                "present": bool(fp.strip()) and "Can't find service" not in fp,
                "sensors": self._sensors(fp),
                "enrolled": self._enrolled(fp),
                "hal": self._find(fp, r"HAL[^\n]*?:\s*([^\n]+)"),
            },
            "face": {
                "present": bool(face.strip()) and "Can't find service" not in face,
                "sensors": self._sensors(face),
                "enrolled": self._enrolled(face),
            },
        }

    @staticmethod
    def _sensors(text: str) -> list[str]:
        # The dump repeats the sensor id in every per-user and per-client
        # block: keep each id once, in order.
        return list(dict.fromkeys(re.findall(r"sensorId[=:\s]+(\d+)", text)))

    @staticmethod
    def _enrolled(text: str) -> int | None:
        m = re.search(r"(?:Enrolled|enrolled)[^\d]*(\d+)", text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _find(text: str, pattern: str) -> str:
        m = re.search(pattern, text)
        return m.group(1).strip() if m else ""


class VibratorCollector(Collector):
    name = "vibrator"
    title = "Vibration"

    def commands(self) -> dict[str, str]:
        return {
            "vib.dumpsys": "dumpsys vibrator_manager | head -40",
            "vib.legacy": "dumpsys vibrator | head -20",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        dump = raw.get("vib.dumpsys", "") or raw.get("vib.legacy", "")
        ids = re.findall(r"VibratorInfo\{?\s*id=(\d+)", dump)
        return {
            "present": bool(dump.strip()) and "Can't find service" not in dump,
            "vibrator_ids": ids,
            "count": len(ids) or (1 if dump.strip() else 0),
            # Linear resonant actuators support composite effects; older
            # eccentric-mass motors do not.
            "supports_effects": "PRIMITIVE" in dump.upper() or "COMPOSE" in dump.upper(),
            "resonant_frequency": self._find(dump, r"[Rr]esonant frequency[=:\s]+([\d.]+)"),
        }

    @staticmethod
    def _find(text: str, pattern: str) -> str:
        m = re.search(pattern, text)
        return m.group(1) if m else ""
