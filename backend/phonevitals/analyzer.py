"""Orchestrator: from USB connection to finished report.

The flow is deliberately linear and tolerant of partial failure. Any collector
that raises is recorded as failed and the analysis continues: a dumpsys that
times out on one particular model must not cost the other hundred readings.
"""

from __future__ import annotations

import asyncio
import platform
import time
import traceback
from datetime import UTC, datetime
from typing import Any

from .adb import Adb, Device
from .analysis.authenticity import AuthenticityEngine, assess
from .analysis.imei import analyse_imeis
from .analysis.memory import memory_findings
from .analysis.specdb import SpecDatabase
from .collectors.agent import AgentOnPhone, battery_facts
from .collectors.attestation import AttestationProbe
from .collectors.history import HistoryCollector
from .collectors.base import Collector
from .collectors.components import ComponentsCollector
from .collectors.hardware import (
    CpuCollector, DisplayCollector, MemoryCollector, StorageCollector,
)
from .collectors.identity import IdentityProbe
from .collectors.peripherals import (
    AudioCollector, BiometricCollector, CameraCollector, InputCollector,
    SensorCollector, VibratorCollector,
)
from .collectors.power import BatteryCollector, ThermalCollector, merge_agent_facts
from .collectors.radio import (
    ConnectivityCollector, TelephonyCollector, WifiCollector,
)
from .collectors.security import PackagesCollector, SecurityCollector
from .collectors.system import SystemCollector, form_factor

# The order only matters for the progress bar: every command ends up in the
# same batch regardless.
COLLECTORS: list[type[Collector]] = [
    SystemCollector,
    CpuCollector,
    MemoryCollector,
    StorageCollector,
    DisplayCollector,
    BatteryCollector,
    ThermalCollector,
    SensorCollector,
    CameraCollector,
    InputCollector,
    AudioCollector,
    BiometricCollector,
    VibratorCollector,
    TelephonyCollector,
    WifiCollector,
    ConnectivityCollector,
    SecurityCollector,
    PackagesCollector,
    ComponentsCollector,
    HistoryCollector,
]


class Analyzer:
    def __init__(self, adb: Adb, on_event=None, store=None):
        self.adb = adb
        self.on_event = on_event
        # phonevitals.store.DeviceStore, to compare with earlier analyses; None skips it.
        self.store = store
        self.specdb = SpecDatabase()

    async def _emit(self, kind: str, **payload) -> None:
        if self.on_event:
            res = self.on_event({"type": kind, **payload})
            if asyncio.iscoroutine(res):
                await res

    async def _progress(self, step: str, percent: int, detail: str = "") -> None:
        await self._emit("progress", step=step, percent=percent, detail=detail)

    # -------------------------------------------------------------- analysis

    async def analyse(self, device: Device, read_imei: bool = True) -> dict[str, Any]:
        started = time.time()
        serial = device.serial

        snapshot: dict[str, Any] = {
            "meta": {
                "serial": serial,
                "adb_state": device.state,
                "usb_path": device.usb,
                "started_at": datetime.now(UTC).isoformat(),
                "host": platform.node(),
            },
            "errors": {},
        }

        # -- 1. check the device is usable -----------------------------------
        await self._progress("connection", 3, "Checking device state")
        if not device.ready:
            snapshot["meta"]["blocked"] = self._explain_state(device.state)
            return snapshot

        boot = await self.adb.text(serial, "getprop sys.boot_completed", timeout=10)
        if boot.strip() != "1":
            await self._progress("connection", 5, "Waiting for boot to complete")
            await self.adb.wait_ready(serial, timeout=45)

        # -- 2. bulk collection ------------------------------------------------
        await self._progress("collection", 8, "Preparing collection commands")
        instances = [cls() for cls in COLLECTORS]

        all_commands: dict[str, str] = {}
        for collector in instances:
            try:
                all_commands.update(collector.commands())
            except Exception:
                snapshot["errors"][collector.name] = "commands could not be generated"

        await self._progress(
            "collection", 12,
            f"Running {len(all_commands)} readings on the device")

        raw = await self.adb.batch(serial, all_commands, timeout=120, chunk=25)
        snapshot["meta"]["commands_executed"] = len(all_commands)
        snapshot["meta"]["commands_with_output"] = sum(
            1 for v in raw.values() if v.strip())

        # -- 3. interpretation --------------------------------------------------
        total = len(instances)
        for i, collector in enumerate(instances):
            pct = 15 + int(45 * (i + 1) / total)
            await self._progress("analysis", pct, f"Interpreting: {collector.title}")
            try:
                snapshot[collector.name] = collector.parse(raw)
            except Exception as exc:
                snapshot[collector.name] = {}
                snapshot["errors"][collector.name] = f"{type(exc).__name__}: {exc}"
                await self._emit(
                    "collector_error", collector=collector.name,
                    error=str(exc), trace=traceback.format_exc(limit=3))

        snapshot.setdefault("system", {})["form_factor"] = form_factor(snapshot)

        # -- 4. identifiers (multi-step, needs an unlocked screen) -------------
        if read_imei:
            await self._progress("identity", 65, "Extracting identifiers")
            try:
                probe = IdentityProbe(
                    self.adb, serial,
                    on_progress=lambda m: self._progress("identity", 70, m),
                )
                snapshot["identity"] = await probe.run()
            except Exception as exc:
                snapshot["identity"] = {"imeis": [], "notes": [
                    f"Identifier extraction failed: {exc}"
                ]}
                snapshot["errors"]["identity"] = str(exc)
        else:
            snapshot["identity"] = {"imeis": [], "skipped": True, "notes": [
                "IMEI reading not requested."
            ]}

        # Serial numbers are collected by the system collector so they are
        # available even when the identity probe does not run. Here they are
        # completed with the USB transport serial, which is a property of how
        # the device presents itself on the bus rather than of the device, and
        # therefore a genuinely independent corroboration.
        # Screenshots are kept apart from the readings: large, and of no use in
        # the raw data view.
        snapshot["evidence"] = snapshot["identity"].pop("evidence", [])

        if not snapshot["identity"].get("serials"):
            snapshot["identity"]["serials"] = self._merge_serials(
                snapshot.get("system", {}).get("serials", {}), serial)

        # -- 4b. hardware attestation -------------------------------------------
        # Runs after the identity probe because it shares the agent file on the
        # phone, and before the authenticity engine, which uses it to
        # corroborate the system properties.
        await self._progress("attestation", 76,
                             "Requesting hardware attestation from the TEE")
        # One copy of the agent serves both questions.
        async with AgentOnPhone(self.adb, serial) as agent:
            try:
                snapshot["attestation"] = await AttestationProbe(self.adb, serial).run()
            except Exception as exc:
                snapshot["attestation"] = {
                    "available": False,
                    "error": f"Attestation not obtained: {type(exc).__name__}: {exc}",
                }
                snapshot["errors"]["attestation"] = str(exc)

            await self._progress("attestation", 79, "Asking Android about the battery")
            try:
                merge_agent_facts(snapshot.setdefault("battery", {}),
                                  await battery_facts(agent))
            except Exception as exc:
                snapshot["errors"]["battery_facts"] = f"{type(exc).__name__}: {exc}"

        # If the secure environment signed the IMEI, that outranks any reading
        # from Settings -- and above all it works with the screen locked, which
        # is the one limit the normal route cannot get around.
        self._adopt_attested_ids(snapshot)

        # -- 5. IMEI validation --------------------------------------------------
        await self._progress("verification", 82, "Validating identifiers")
        effective = snapshot.get("system", {}).get("partitions", {}).get("effective", {})
        snapshot["imei_analysis"] = analyse_imeis(
            snapshot["identity"].get("imeis", []),
            device_brand=effective.get("brand", ""),
            device_model=effective.get("model", ""),
        )

        # -- 6. authenticity engine ----------------------------------------------
        await self._progress("verification", 90, "Running authenticity checks")
        engine = AuthenticityEngine(snapshot, specdb=self.specdb)
        report = engine.run()

        # IMEI anomalies join the overall report.
        for f in snapshot["imei_analysis"]["findings"]:
            report["findings"].append({
                "severity": f["severity"],
                "category": "identity",
                "title": f["title"],
                "detail": f["detail"],
                "strength": "proven",
                "strength_label": "Proven",
                "evidence": {},
            })
        snapshot["report"] = report

        # Earlier analyses on this computer and the reference unit, if any.
        if self.store is not None:
            try:
                snapshot["memory"] = {"sightings": self.store.record(snapshot),
                                      "reference": self.store.reference(snapshot)}
                report["findings"].extend(memory_findings(snapshot["memory"]))
            except Exception as exc:
                snapshot["errors"]["memory"] = f"{type(exc).__name__}: {exc}"
        report = self._recount(report)
        snapshot["report"] = report

        # -- 7. header summary ----------------------------------------------------
        snapshot["summary"] = self._summary(snapshot)
        snapshot["meta"]["duration_seconds"] = round(time.time() - started, 1)
        snapshot["meta"]["finished_at"] = datetime.now(UTC).isoformat()
        snapshot["meta"]["catalog"] = {
            "specs_loaded": self.specdb.size,
            "specs_error": self.specdb.error,
        }

        await self._progress("done", 100, "Analysis complete")
        return snapshot

    # --------------------------------------------------------------- utility

    @staticmethod
    def _adopt_attested_ids(snapshot: dict[str, Any]) -> None:
        """Bring TEE-signed identifiers into the identity section.

        Worth noting what this solves: on Android 10 and later the IMEI can
        only be read from Settings, and that needs an unlocked screen. When the
        secure environment attests it, it arrives signed and without touching
        the phone. Not every device includes it -- attesting identifiers is
        optional -- but where it exists it is the best source there is.
        """
        att = snapshot.get("attestation") or {}
        ids = att.get("attested_ids") or {}
        if not ids:
            return

        identity = snapshot.setdefault("identity", {})
        known = list(identity.get("imeis") or [])
        added = []
        for key in ("imei", "second_imei"):
            value = str(ids.get(key, "")).strip()
            if value.isdigit() and len(value) == 15 and value not in known:
                known.append(value)
                added.append(value)

        if added:
            identity["imeis"] = known
            identity.setdefault("notes", []).append(
                f"{len(added)} IMEI(s) obtained from hardware attestation: they "
                "are signed by the phone's secure environment, so they do not pass "
                "through the operating system and do not require an unlocked "
                "screen."
            )
            identity["attested_imeis"] = added
            identity.pop("needs_unlock", None)

        serial = str(ids.get("serial", "")).strip()
        if serial:
            serials = identity.setdefault("serials", {})
            values = serials.setdefault("values", {})
            values["attestation"] = serial
            distinct = {v.upper() for v in values.values() if v and v != "unknown"}
            serials["consistent"] = len(distinct) <= 1
            serials["distinct_count"] = len(distinct)

    @staticmethod
    def _merge_serials(from_props: dict[str, str], usb_serial: str) -> dict[str, Any]:
        values = dict(from_props)
        # Over `adb connect` the serial is an address, not the device's serial
        # (same rule as IdentityProbe._serials).
        if usb_serial and ":" not in usb_serial and "._adb" not in usb_serial:
            values["usb_transport"] = usb_serial
        distinct = {v.upper() for v in values.values() if v and v != "unknown"}
        return {
            "values": values,
            "primary": values.get("ro") or values.get("boot") or usb_serial,
            "consistent": len(distinct) <= 1,
            "distinct_count": len(distinct),
        }

    @staticmethod
    def _explain_state(state: str) -> dict[str, str]:
        messages = {
            "unauthorized": (
                "USB debugging not authorised",
                "The phone detected the connection but has not been granted "
                "permission yet. Unlock the screen: a dialog will appear asking "
                "\"Allow USB debugging?\". Tap Allow, and it is worth "
                "ticking \"Always allow from this computer\"."
            ),
            "offline": (
                "Device unreachable",
                "The device is connected but not responding. Try unplugging and "
                "reconnecting the cable, or changing USB port. If it persists, "
                "turn USB debugging off and on again in Developer options."
            ),
            "recovery": (
                "Device in recovery mode",
                "The phone booted into recovery, where most of the data is not "
                "accessible. Reboot it normally."
            ),
            "no permissions": (
                "No permission to access the USB device",
                "The computer sees the phone but this user is not allowed to "
                "open its USB interface. Install a udev rule for Android devices "
                "(your distribution's android-udev rules, or "
                "scripts/install_udev_rules.sh from a source checkout), then "
                "unplug and reconnect the cable."
            ),
            "authorizing": (
                "Authorisation in progress",
                "The phone is checking this computer's adb key. Wait a moment, "
                "and confirm the dialog on the phone if one appears."
            ),
            "sideload": (
                "Device in sideload mode",
                "The phone is waiting for an update package. Reboot it normally."
            ),
        }
        title, detail = messages.get(state, (
            f"Unusable state: {state}",
            "The device is not in a state that allows data to be read."
        ))
        return {"state": state, "title": title, "detail": detail}

    @staticmethod
    def _recount(report: dict[str, Any]) -> dict[str, Any]:
        """Recompute counts and verdict after adding the IMEI findings."""
        by_sev: dict[str, list] = {"critical": [], "warning": [], "info": [], "ok": []}
        for f in report["findings"]:
            by_sev.setdefault(f["severity"], []).append(f)

        report["counts"] = {k: len(v) for k, v in by_sev.items()}
        report["by_severity"] = by_sev

        by_cat: dict[str, list] = {}
        for f in report["findings"]:
            by_cat.setdefault(f["category"], []).append(f)
        report["by_category"] = by_cat

        report["score"], report["verdict"], report["headline"] = assess(report["findings"])
        return report

    @staticmethod
    def _summary(s: dict[str, Any]) -> dict[str, Any]:
        """The few values that go in the header, ready for the UI."""
        eff = s.get("system", {}).get("partitions", {}).get("effective", {})
        os_info = s.get("system", {}).get("os", {})
        soc = s.get("system", {}).get("soc", {})
        mem = s.get("memory", {})
        stor = s.get("storage", {})
        disp = s.get("display", {})
        bat = s.get("battery", {})
        res = disp.get("resolution") or {}

        return {
            "form_factor": s.get("system", {}).get("form_factor", "phone"),
            "brand": eff.get("brand", ""),
            "model": eff.get("model", ""),
            "device": eff.get("device", ""),
            "manufacturer": eff.get("manufacturer", ""),
            "android": os_info.get("android_release", ""),
            "sdk": os_info.get("sdk"),
            "security_patch": os_info.get("security_patch", ""),
            "soc": soc.get("declared_model") or soc.get("platform", ""),
            "cores": s.get("cpu", {}).get("core_count"),
            "ram_gb": mem.get("nominal_gb"),
            "storage_gb": stor.get("nominal_gb"),
            "storage_estimated": stor.get("nominal_estimated", False),
            "storage_type": stor.get("type"),
            "resolution": f"{res.get('width')}x{res.get('height')}" if res else "",
            "refresh_max": max(disp.get("refresh_rates") or [0]) or None,
            "battery_health": bat.get("health_percent"),
            "battery_cycles": bat.get("cycle_count"),
            "battery_level": bat.get("level_percent"),
            "manufactured": (s.get("history") or {}).get("manufactured"),
            "setup_date": (s.get("history") or {}).get("setup_date"),
            "boot_count": (s.get("history") or {}).get("boot_count"),
            "security_updates_until": (s.get("support") or {}).get("security_updates_until"),
            "imeis": s.get("identity", {}).get("imeis", []),
            "serial": s.get("identity", {}).get("serials", {}).get("primary", ""),
            "sensors": s.get("sensors", {}).get("count"),
            "cameras": s.get("cameras", {}).get("count"),
        }
