"""Radios: cellular, WiFi, Bluetooth, NFC, GNSS.

On what is obtainable without privileges: signal strength, network type, SIM
state and baseband version are readable. IMEI and IMSI are not -- they are
protected by READ_PRIVILEGED_PHONE_STATE (see collectors/identity.py for the
alternative route).
"""

from __future__ import annotations

import re
from typing import Any

from .base import Collector, parse_props, to_int


class TelephonyCollector(Collector):
    name = "telephony"
    title = "Telephony"

    def commands(self) -> dict[str, str]:
        return {
            "tel.registry": "dumpsys telephony.registry | head -120",
            "tel.props": "getprop | grep -E '^\\[(gsm|ril|telephony)\\.' | head -80",
            "tel.sim": "getprop gsm.sim.state",
            "tel.operator": "getprop gsm.operator.alpha",
            "tel.numeric": "getprop gsm.operator.numeric",
            "tel.baseband": "getprop gsm.version.baseband",
            "tel.radio": "getprop gsm.version.ril-impl",
            "tel.network": "getprop gsm.network.type",
            "tel.features": "pm list features | grep -iE 'telephony|cdma|gsm'",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        reg = raw.get("tel.registry", "")
        props = parse_props(raw.get("tel.props", ""))

        sim_states = [
            s.strip() for s in raw.get("tel.sim", "").split(",") if s.strip()
        ]
        state_map = {
            "ABSENT": "no SIM", "READY": "ready", "PIN_REQUIRED": "PIN required",
            "PUK_REQUIRED": "PUK required", "NETWORK_LOCKED": "carrier locked",
            "UNKNOWN": "unknown", "NOT_READY": "not ready",
            "PERM_DISABLED": "permanently disabled",
            "CARD_IO_ERROR": "read error", "LOADED": "loaded",
        }

        return {
            "sim_states": [
                {"raw": s, "text": state_map.get(s.upper(), s)} for s in sim_states
            ],
            "sim_count": len(sim_states),
            "sim_present": any(s.upper() in ("READY", "LOADED") for s in sim_states),
            "operator": raw.get("tel.operator", "").strip(),
            "operator_numeric": raw.get("tel.numeric", "").strip(),
            "baseband": raw.get("tel.baseband", "").strip(),
            "ril_impl": raw.get("tel.radio", "").strip(),
            "network_type": raw.get("tel.network", "").strip(),
            "signal": self._signal(reg),
            "service_state": self._service_state(reg),
            "features": [
                line.split(":", 1)[1].strip()
                for line in raw.get("tel.features", "").splitlines()
                if ":" in line
            ],
            "props": props,
        }

    @staticmethod
    def _signal(reg: str) -> dict[str, Any]:
        """Extract signal strength from the registry dump.

        SignalStrength publishes a block for every technology, and the ones
        not in use carry Integer.MAX_VALUE (unavailable) and level 0. The
        first *valid* value of each field is taken, not the first one: on a
        dual-SIM phone, or simply because the GSM block comes before the LTE
        one, the first occurrence is usually a placeholder. The 0-4 level is
        the highest across technologies, which is what the signal bars show.

        NR blocks are formatted `ssRsrp = -95` with spaces around the equals
        sign, unlike the LTE ones.
        """
        out: dict[str, Any] = {}
        # Restrict the search to the signal strength dump where there is one,
        # so unrelated `level=` fields elsewhere in the registry cannot match.
        lines = [line for line in reg.splitlines() if "SignalStrength" in line]
        text = "\n".join(lines) if lines else reg

        def grab(name: str, key: str) -> None:
            for m in re.finditer(rf"\b{name}\s*=\s*(-?\d+)", text):
                val = int(m.group(1))
                # 2147483647 is Integer.MAX_VALUE, 99 the legacy "unknown".
                if val not in (2147483647, -2147483648, 99):
                    out[key] = val
                    return

        grab("rsrp", "lte_rsrp_dbm")
        grab("rsrq", "lte_rsrq_db")
        grab("rssnr", "lte_rssnr_db")
        grab("ssRsrp", "nr_rsrp_dbm")
        grab("ssRsrq", "nr_rsrq_db")
        grab("rssi", "rssi_dbm")

        levels_seen = [int(m.group(1)) for m in re.finditer(
            r"\b(?:mLevel|level)\s*=\s*([0-4])\b", text)]
        if levels_seen:
            out["level"] = max(levels_seen)
            levels = {0: "none", 1: "poor", 2: "weak", 3: "good", 4: "excellent"}
            out["level_text"] = levels[out["level"]]
        return out

    @staticmethod
    def _service_state(reg: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        m = re.search(r"mVoiceRegState=(\d+)\((\w+)\)", reg)
        if m:
            out["voice"] = m.group(2)
        m = re.search(r"mDataRegState=(\d+)\((\w+)\)", reg)
        if m:
            out["data"] = m.group(2)
        m = re.search(r"getRadioTechnology=(\w+)", reg)
        if m:
            out["radio_technology"] = m.group(1)
        return out


class WifiCollector(Collector):
    name = "wifi"
    title = "WiFi"

    def commands(self) -> dict[str, str]:
        return {
            "wifi.status": "cmd wifi status 2>/dev/null",
            "wifi.dumpsys": "dumpsys wifi | head -80",
            "wifi.iface": "ip -o link show 2>/dev/null | head -20",
            "wifi.features": "pm list features | grep -i wifi",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        status = raw.get("wifi.status", "")
        dump = raw.get("wifi.dumpsys", "")

        connected = bool(re.search(r"^\s*Wifi is connected to", status,
                                   re.I | re.M))
        ssid = self._find(status, r'connected to "([^"]*)"') or \
               self._find(status, r"SSID:\s*\"?([^\",\n]+)")
        rssi = self._find(status, r"RSSI:\s*(-?\d+)")
        freq = self._find(status, r"(\d{4,5})MHz") or \
               self._find(status, r"Frequency:\s*(\d+)")
        link = self._find(status, r"Link speed:\s*(\d+)")

        bands = []
        for label, pattern in (("2.4 GHz", r"24[Gg]hz|2\.4"), ("5 GHz", r"5[Gg]hz"),
                               ("6 GHz", r"6[Gg]hz")):
            if re.search(pattern, dump):
                bands.append(label)

        standards = []
        for label, pattern in (("Wi-Fi 6 (11ax)", r"11ax|WIFI_STANDARD_11AX"),
                               ("Wi-Fi 6E", r"6[Gg]hz.*11ax|WIFI_STANDARD_11AX.*6"),
                               ("Wi-Fi 7 (11be)", r"11be|WIFI_STANDARD_11BE"),
                               ("Wi-Fi 5 (11ac)", r"11ac|WIFI_STANDARD_11AC")):
            if re.search(pattern, dump):
                standards.append(label)

        return {
            # Anchored to the start of the line: when Wi-Fi is off, Pixel
            # still prints "Wifi scanning is only available when wifi is
            # enabled", which a substring test reads as "enabled".
            "enabled": bool(re.search(r"^\s*Wi-?Fi is enabled\b",
                                      status + "\n" + dump, re.I | re.M)),
            "connected": connected,
            "ssid": ssid or None,
            "rssi_dbm": to_int(rssi),
            "frequency_mhz": to_int(freq),
            "link_speed_mbps": to_int(link),
            "bands_supported": bands,
            "standards": standards,
            "interfaces": [
                line.split(":", 2)[1].strip()
                for line in raw.get("wifi.iface", "").splitlines()
                if ":" in line and len(line.split(":", 2)) > 1
            ],
            "features": [
                line.split(":", 1)[1].strip()
                for line in raw.get("wifi.features", "").splitlines() if ":" in line
            ],
            "status_raw": status.strip()[:2000],
        }

    @staticmethod
    def _find(text: str, pattern: str) -> str:
        m = re.search(pattern, text)
        return m.group(1).strip() if m else ""


class ConnectivityCollector(Collector):
    name = "connectivity"
    title = "Bluetooth, NFC and location"

    def commands(self) -> dict[str, str]:
        return {
            "conn.bt": "dumpsys bluetooth_manager | head -60",
            "conn.nfc": "dumpsys nfc | head -40",
            "conn.location": "dumpsys location | head -80",
            "conn.features": "pm list features | grep -iE 'bluetooth|nfc|location|gps'",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        bt = raw.get("conn.bt", "")
        nfc = raw.get("conn.nfc", "")
        loc = raw.get("conn.location", "")
        features = [
            line.split(":", 1)[1].strip()
            for line in raw.get("conn.features", "").splitlines() if ":" in line
        ]

        return {
            "bluetooth": {
                "present": "Can't find service" not in bt and bool(bt.strip()),
                "enabled": bool(re.search(r"enabled:\s*true|state:\s*ON", bt, re.I)),
                "name": self._find(bt, r"name:\s*(.+)"),
                "address": self._find(bt, r"address:\s*([0-9A-Fa-f:]{17})"),
                "le_supported": "android.hardware.bluetooth_le" in features,
                "version": self._find(bt, r"Bluetooth Version:\s*(\S+)"),
            },
            "nfc": {
                "present": "Can't find service" not in nfc and bool(nfc.strip()),
                "enabled": bool(re.search(r"mState=(?:on|ON)", nfc)),
                "hce": "android.hardware.nfc.hce" in features,
            },
            "location": {
                "providers": sorted(set(re.findall(
                    r"^\s*(gps|network|passive|fused)\s", loc, re.M))),
                "gnss_hardware": self._find(loc, r"GnssHardwareModelName[=:\s]+(.+)"),
                "gps_feature": "android.hardware.location.gps" in features,
            },
            "features": features,
        }

    @staticmethod
    def _find(text: str, pattern: str) -> str:
        m = re.search(pattern, text, re.M)
        return m.group(1).strip() if m else ""
