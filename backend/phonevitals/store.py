"""Local memory of the phones analysed on this computer.

Two uses, both offline:

- Recognising a phone seen before. The same IMEI turning up on a different
  device (another serial, another processor) is what cloned identities look
  like. The same device coming back with a different camera module, panel,
  battery or storage chip shows what was replaced in between.
- Reference units. A phone known to be genuine can be saved as the reference
  for its model; later units of that model are compared with it trait by
  trait, which catches what a generic catalogue cannot.

Identifiers never sit in the database in clear: IMEIs, serials and component
IDs are stored as salted SHA-256 hashes, with a salt generated for this
installation. Equality can be tested, values cannot be read back. Reference
traits are model characteristics (processor, sensors, resolution), not
identifiers, and are stored as they are.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def default_dir() -> Path:
    if os.environ.get("PHONEVITALS_DATA_DIR"):
        return Path(os.environ["PHONEVITALS_DATA_DIR"])
    if os.environ.get("SNAP_USER_COMMON"):
        # Survives snap refreshes, unlike the per-revision SNAP_USER_DATA.
        return Path(os.environ["SNAP_USER_COMMON"])
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "PhoneVitals"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PhoneVitals"
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "phonevitals"


# Component identifiers worth remembering: (label, path into the snapshot).
def _components(s: dict[str, Any]) -> dict[str, str]:
    comp = s.get("components") or {}
    out: dict[str, str] = {}
    for cam in comp.get("cameras") or []:
        if cam.get("module_id"):
            out[f"camera module ({cam.get('position', '?')})"] = cam["module_id"]
    panel = comp.get("panel") or {}
    for key in ("cell_id", "SVC_OCTA", "octa_id", "panel_serial"):
        if panel.get(key):
            out["display panel"] = panel[key]
            break
    if (comp.get("storage_chip") or {}).get("chip_serial"):
        out["storage chip"] = comp["storage_chip"]["chip_serial"]
    bat = s.get("battery") or {}
    if bat.get("serial_number"):
        out["battery"] = bat["serial_number"]
    return out


def traits(s: dict[str, Any]) -> dict[str, Any]:
    """Model characteristics a genuine unit of the model shares with others."""
    soc = (s.get("system") or {}).get("soc") or {}
    disp = s.get("display") or {}
    res = disp.get("resolution") or {}
    cameras = (s.get("cameras") or {}).get("cameras") or []
    nodes = (s.get("components") or {}).get("kernel_sensor_nodes") or {}
    return {
        "soc": soc.get("declared_model") or soc.get("platform"),
        "platform": soc.get("platform"),
        "core_layout": sorted(f"{c.get('count')}x {c.get('microarchitecture')}"
                              for c in soc.get("core_types") or []),
        "max_cpu_mhz": sorted(round((c.get("max_khz") or 0) / 1000)
                              for c in (s.get("cpu") or {}).get("clusters") or []),
        "resolution": f"{res.get('width')}x{res.get('height')}" if res else None,
        "max_refresh_hz": max(disp.get("refresh_rates") or [0]) or None,
        "camera_count": (s.get("cameras") or {}).get("count"),
        "camera_sensors": sorted(c.get("sensor") for c in
                                 (s.get("components") or {}).get("cameras") or [] if c.get("sensor")),
        "camera_arrays": sorted(f"{c['pixel_array']['width']}x{c['pixel_array']['height']}"
                                for c in cameras if c.get("pixel_array")),
        "sensor_chips": sorted(f"{v.get('vendor')} {v.get('name')}" for v in nodes.values()),
        "storage_type": (s.get("storage") or {}).get("type"),
        "ram_gb": (s.get("memory") or {}).get("nominal_gb"),
        "panel_type": ((s.get("components") or {}).get("panel") or {}).get("lcd_type"),
        "touch_controller": ((s.get("input") or {}).get("touchscreen") or {}).get("name"),
    }


# Traits that cannot differ between genuine units of one model, and the ones
# that legitimately vary with batches and suppliers.
STRICT_TRAITS = {"soc": "processor", "platform": "platform", "core_layout": "core layout",
                 "max_cpu_mhz": "maximum CPU frequencies", "resolution": "display resolution",
                 "camera_arrays": "camera sensor resolutions", "camera_count": "camera count"}
LOOSE_TRAITS = {"camera_sensors": "camera sensor parts", "sensor_chips": "sensor chips",
                "storage_type": "storage type", "ram_gb": "RAM", "panel_type": "panel type",
                "touch_controller": "touch controller", "max_refresh_hz": "refresh rate"}


def model_key(s: dict[str, Any]) -> str:
    eff = ((s.get("system") or {}).get("partitions") or {}).get("effective") or {}
    return f"{(eff.get('brand') or '').lower()}|{(eff.get('device') or '').lower()}"


class DeviceStore:
    def __init__(self, directory: Path | None = None):
        self.dir = directory or default_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.salt = self._salt()
        self.db = sqlite3.connect(self.dir / "devices.db")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sightings (
                id INTEGER PRIMARY KEY, seen_at TEXT NOT NULL, model TEXT,
                serial TEXT, soc TEXT, imeis TEXT, components TEXT,
                score INTEGER, verdict TEXT);
            CREATE INDEX IF NOT EXISTS sightings_serial ON sightings(serial);
            CREATE TABLE IF NOT EXISTS reference_units (
                model_key TEXT PRIMARY KEY, label TEXT, saved_at TEXT NOT NULL,
                traits TEXT NOT NULL);
        """)

    def _salt(self) -> bytes:
        path = self.dir / "salt"
        try:
            return path.read_bytes()
        except FileNotFoundError:
            salt = secrets.token_bytes(32)
            path.write_bytes(salt)
            os.chmod(path, 0o600)
            return salt

    def _h(self, kind: str, value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = f"{kind}:{str(value).strip().upper()}".encode()
        return hashlib.sha256(self.salt + text).hexdigest()[:32]

    # ------------------------------------------------------------ sightings

    def record(self, s: dict[str, Any]) -> dict[str, Any]:
        """Compare this analysis with the past ones, then remember it."""
        identity = s.get("identity") or {}
        serial = self._h("serial", (identity.get("serials") or {}).get("primary"))
        soc = self._h("soc", ((s.get("components") or {}).get("soc") or {}).get("chip_serial"))
        imeis = sorted(filter(None, (self._h("imei", i) for i in identity.get("imeis") or [])))
        components = {k: self._h("component", v) for k, v in _components(s).items()}
        summary = s.get("summary") or {}
        model = f"{summary.get('brand', '')} {summary.get('model', '')}".strip()

        rows = self.db.execute(
            "SELECT seen_at, model, serial, soc, imeis, components FROM sightings "
            "ORDER BY seen_at DESC").fetchall()
        same, elsewhere = [], []
        for seen_at, other_model, o_serial, o_soc, o_imeis, o_components in rows:
            same_device = (serial and o_serial == serial) or (soc and o_soc == soc)
            if same_device:
                same.append({"seen_at": seen_at, "components": json.loads(o_components or "{}")})
            elif imeis and set(imeis) & set(json.loads(o_imeis or "[]")):
                elsewhere.append({"seen_at": seen_at, "model": other_model})

        changed = []
        if same:
            last = same[0]["components"]
            changed = sorted(k for k, v in components.items() if k in last and last[k] != v)

        report = s.get("report") or {}
        self.db.execute(
            "INSERT INTO sightings (seen_at, model, serial, soc, imeis, components, score, verdict)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(UTC).isoformat(timespec="seconds"), model, serial, soc,
             json.dumps(imeis), json.dumps(components), report.get("score"), report.get("verdict")))
        self.db.commit()
        return {
            "seen_before": len(same),
            "first_seen": same[-1]["seen_at"] if same else None,
            "last_seen": same[0]["seen_at"] if same else None,
            "changed_components": changed,
            "imei_on_other_devices": elsewhere[:5],
        }

    # ----------------------------------------------------------- references

    def reference(self, s: dict[str, Any]) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT label, saved_at, traits FROM reference_units WHERE model_key = ?",
            (model_key(s),)).fetchone()
        if not row:
            return None
        label, saved_at, saved = row[0], row[1], json.loads(row[2])
        current = traits(s)
        differences = []
        for key, name in {**STRICT_TRAITS, **LOOSE_TRAITS}.items():
            ref, now = saved.get(key), current.get(key)
            # Only what both units actually reported is compared: a reading
            # that failed on one side is not a difference.
            if ref in (None, [], "") or now in (None, [], "") or ref == now:
                continue
            differences.append({"trait": key, "name": name, "reference": ref, "this": now,
                                "strict": key in STRICT_TRAITS})
        return {"label": label, "saved_at": saved_at, "differences": differences,
                "compared": sum(1 for k in {**STRICT_TRAITS, **LOOSE_TRAITS}
                                if saved.get(k) not in (None, [], "")
                                and current.get(k) not in (None, [], ""))}

    def save_reference(self, s: dict[str, Any], label: str = "") -> str:
        key = model_key(s)
        summary = s.get("summary") or {}
        label = label or f"{summary.get('brand', '')} {summary.get('model', '')}".strip()
        self.db.execute(
            "INSERT OR REPLACE INTO reference_units (model_key, label, saved_at, traits)"
            " VALUES (?, ?, ?, ?)",
            (key, label, datetime.now(UTC).isoformat(timespec="seconds"), json.dumps(traits(s))))
        self.db.commit()
        return key

    def delete_reference(self, key: str) -> None:
        self.db.execute("DELETE FROM reference_units WHERE model_key = ?", (key,))
        self.db.commit()

    def references(self) -> list[dict[str, Any]]:
        return [{"model_key": k, "label": label, "saved_at": at}
                for k, label, at in self.db.execute(
                    "SELECT model_key, label, saved_at FROM reference_units ORDER BY label")]
