"""Catalogue of expected specifications per model.

This module compares what the kernel measures against what the model is
supposed to have. It is the check that exposes the "Pixel 8 Pro" clone with
four cores and 4 GB of RAM.

Stated limitation: the catalogue is compiled by hand and necessarily
incomplete. The module therefore behaves cautiously:

  - a model absent from the catalogue produces no verdict, only an
    informational note;
  - discrepancies are classified "warning" and never "critical", because a
    wrong catalogue entry would raise a false counterfeit alarm, which is the
    most damaging possible error;
  - RAM and storage accept several values, because nearly every model exists
    in multiple configurations;
  - every entry carries a `confidence` field, so the reader knows how much
    weight the comparison deserves.

The catalogue lives in backend/data/specs.json and is meant to be extended
without touching the code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SPECS_PATH = Path(__file__).resolve().parents[2] / "data" / "specs.json"


class SpecDatabase:
    def __init__(self, path: str | Path = SPECS_PATH):
        self.path = path
        self.entries: list[dict[str, Any]] = []
        self.error: str | None = None
        self.load()

    def load(self) -> None:
        if not Path(self.path).is_file():
            self.error = "specification catalogue not present"
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.entries = data.get("devices", [])
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.error = f"catalogue unreadable: {exc}"

    @property
    def size(self) -> int:
        return len(self.entries)

    # ---------------------------------------------------------------- lookup

    def lookup(self, brand: str = "", model: str = "",
               device: str = "") -> dict[str, Any] | None:
        """Look up by codename first, then by model.

        The board codename (`ro.product.device`, e.g. "husky", "dm3q") is far
        more stable than the commercial name, which changes by market and by
        carrier.
        """
        device_l = (device or "").strip().lower()
        model_l = (model or "").strip().lower()
        brand_l = (brand or "").strip().lower()

        if device_l:
            for entry in self.entries:
                if device_l in [d.lower() for d in entry.get("devices", [])]:
                    return entry

        if not model_l:
            return None

        # Exact matches across the whole catalogue first. Checking prefixes
        # entry by entry let "Pixel 8 Pro" stop at the earlier "Pixel 8" entry
        # and be measured against the wrong phone.
        for entry in self.entries:
            if model_l in (m.lower() for m in entry.get("models", [])):
                return entry

        # Prefix match, for part numbers: SM-S918B/DS -> SM-S918. Only for
        # catalogue models without spaces: in a commercial name the next word
        # or letter is a different phone ("Pixel 9" is not a "Pixel 9a" or a
        # "Pixel 9 Pro Fold"), and a wrong entry turns every spec difference
        # into a false warning. The longest matching part number wins.
        best: tuple[int, dict[str, Any]] | None = None
        for entry in self.entries:
            if brand_l and entry.get("brand", "").lower() not in brand_l:
                continue
            for m in (m.lower() for m in entry.get("models", [])):
                if " " in m or not model_l.startswith(m):
                    continue
                if best is None or len(m) > best[0]:
                    best = (len(m), entry)
        return best[1] if best else None

    # --------------------------------------------------------------- compare

    def compare(self, spec: dict[str, Any],
                snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """Compare the expected specification against the collected measurements."""
        issues: list[dict[str, Any]] = []
        name = spec.get("name", "unknown model")
        conf = spec.get("confidence", "medium")

        def measured(*path, default=None):
            node: Any = snapshot
            for key in path:
                if not isinstance(node, dict):
                    return default
                node = node.get(key)
                if node is None:
                    return default
            return node

        # -- core count ------------------------------------------------------
        expected_cores = spec.get("cpu_cores")
        actual_cores = measured("cpu", "core_count")
        if expected_cores and actual_cores:
            if actual_cores != expected_cores:
                issues.append({
                    "severity": "warning",
                    "title": "Core count differs from expected",
                    "detail": (
                        f"A {name} has a {expected_cores}-core processor, but the "
                        f"kernel exposes {actual_cores}. The count comes from the "
                        "directories the kernel creates for each physical core, so "
                        "it reflects the real silicon. "
                        f"(Catalogue entry confidence: {conf}.)"
                    ),
                    "evidence": {"expected": expected_cores, "measured": actual_cores},
                })
            else:
                issues.append({
                    "severity": "ok",
                    "title": "Core count conforms",
                    "detail": f"{actual_cores} cores, as expected for a {name}.",
                    "evidence": {"cores": actual_cores},
                })

        # -- RAM -------------------------------------------------------------
        expected_ram = spec.get("ram_gb") or []
        actual_ram = measured("memory", "nominal_gb")
        if expected_ram and actual_ram:
            if actual_ram not in expected_ram:
                issues.append({
                    "severity": "warning",
                    "title": "RAM outside the known configurations",
                    "detail": (
                        f"The kernel reports about {actual_ram} GB of RAM, while a "
                        f"{name} was produced in "
                        f"{', '.join(f'{r} GB' for r in expected_ram)} "
                        "configurations. Total RAM is measured by the kernel at "
                        "boot by counting the banks actually present. "
                        f"(Confidence: {conf}.)"
                    ),
                    "evidence": {"expected": expected_ram, "measured": actual_ram},
                })
            else:
                issues.append({
                    "severity": "ok",
                    "title": "RAM conforms",
                    "detail": f"{actual_ram} GB, a configuration expected for a {name}.",
                    "evidence": {"ram_gb": actual_ram},
                })

        # -- storage ---------------------------------------------------------
        #
        # Where SELinux denies /proc/partitions and /sys/block -- Pixel among
        # others -- the size is inferred from the /data filesystem rather than
        # read from the chip. That is an estimate, so a mismatch is reported as
        # informational: raising a counterfeit-flavoured warning off an indirect
        # figure is exactly the error this module exists to avoid.
        expected_storage = spec.get("storage_gb") or []
        actual_storage = measured("storage", "nominal_gb")
        estimated = bool(measured("storage", "nominal_estimated", default=False))
        source = measured("storage", "nominal_source", default="")
        if expected_storage and actual_storage:
            if estimated:
                basis = ("inferred from the size of the /data filesystem, because "
                         "the block device is not readable by the shell user")
            elif source == "storage_manager":
                basis = ("reported by Android's storage service, which reads the "
                         "memory chip's sector count with system privileges")
            else:
                basis = ("read from the number of sectors the memory chip "
                         "declares, not from system properties")
            if actual_storage not in expected_storage:
                issues.append({
                    "severity": "info" if estimated else "warning",
                    "title": "Storage outside the known configurations",
                    "detail": (
                        f"Physical storage measures about {actual_storage} GB, "
                        f"while a {name} exists in "
                        f"{', '.join(f'{s} GB' for s in expected_storage)} "
                        f"configurations. The value is {basis}: it is one of the "
                        "figures clones inflate most often. "
                        f"(Confidence: {conf}.)"
                    ),
                    "evidence": {"expected": expected_storage,
                                 "measured": actual_storage,
                                 "estimated": estimated},
                })
            else:
                issues.append({
                    "severity": "ok",
                    "title": "Storage conforms",
                    "detail": (
                        f"{actual_storage} GB, a configuration expected for a "
                        f"{name}. Value {basis}."
                    ),
                    "evidence": {"storage_gb": actual_storage,
                                 "estimated": estimated},
                })

        # -- screen resolution -----------------------------------------------
        expected_res = spec.get("resolution")
        actual_res = measured("display", "resolution")
        if expected_res and actual_res:
            ew, eh = expected_res.get("width"), expected_res.get("height")
            aw, ah = actual_res.get("width"), actual_res.get("height")
            # Set comparison: some devices report width and height swapped
            # depending on orientation.
            if {ew, eh} != {aw, ah}:
                issues.append({
                    "severity": "warning",
                    "title": "Screen resolution differs from expected",
                    "detail": (
                        f"The panel reports {aw}x{ah} pixels, while a {name} has "
                        f"a {ew}x{eh}. A difference can come from a panel replaced "
                        "with one of a different model, or from the device not "
                        "being the one declared. Worth verifying: some settings "
                        "deliberately reduce the working resolution. "
                        f"(Confidence: {conf}.)"
                    ),
                    "evidence": {"expected": expected_res, "measured": actual_res},
                })
            else:
                issues.append({
                    "severity": "ok",
                    "title": "Resolution conforms",
                    "detail": f"{aw}x{ah} pixels, as expected for a {name}.",
                    "evidence": {"resolution": actual_res},
                })

        # -- refresh rate ------------------------------------------------------
        expected_hz = spec.get("max_refresh_hz")
        actual_rates = measured("display", "refresh_rates") or []
        if expected_hz and actual_rates:
            actual_max = max(actual_rates)
            if actual_max < expected_hz - 5:
                issues.append({
                    "severity": "warning",
                    "title": "Refresh rate below expected",
                    "detail": (
                        f"The panel declares at most {actual_max:.0f} Hz, while a "
                        f"{name} reaches {expected_hz} Hz. This is the classic sign "
                        "of a panel replaced with a lower-tier one, or of a clone. "
                        f"(Confidence: {conf}.)"
                    ),
                    "evidence": {"expected_hz": expected_hz, "measured_hz": actual_max},
                })
            else:
                issues.append({
                    "severity": "ok",
                    "title": "Refresh rate conforms",
                    "detail": (
                        f"The panel reaches {actual_max:.0f} Hz, as expected for a "
                        f"{name}."
                    ),
                    "evidence": {"measured_hz": actual_max},
                })

        # -- cameras -----------------------------------------------------------
        expected_cams = spec.get("camera_count")
        actual_cams = measured("cameras", "count")
        if expected_cams and actual_cams and actual_cams < expected_cams:
            issues.append({
                "severity": "warning",
                "title": "Fewer cameras than expected",
                "detail": (
                    f"The system exposes {actual_cams} cameras, while a {name} has "
                    f"{expected_cams}. Clones often reproduce the external look "
                    "with extra dummy lenses, but the software only exposes the "
                    "ones actually connected. "
                    f"(Confidence: {conf}.)"
                ),
                "evidence": {"expected": expected_cams, "measured": actual_cams},
            })

        # -- SoC ---------------------------------------------------------------
        #
        # The comparison uses only the technical part numbers listed in
        # `soc_ids`, never the commercial name. Marketing name and part number
        # almost never coincide -- a Snapdragon 730 presents itself to the
        # system as SM7150 on platform sm6150 -- and searching for the word
        # "Snapdragon" inside "sm7150" would raise a false alarm on every
        # Qualcomm device. If the catalogue does not list the part numbers the
        # check is simply skipped: better no verdict than a wrong one.
        soc_ids = [s.lower() for s in (spec.get("soc_ids") or [])]
        declared_soc = (measured("system", "soc", "declared_model", default="") or "").lower()
        platform = (measured("system", "soc", "platform", default="") or "").lower()
        hardware = (measured("system", "soc", "hardware_line", default="") or "").lower()

        if soc_ids and (declared_soc or platform or hardware):
            haystack = f"{declared_soc} {platform} {hardware}".replace("-", "")
            if not any(sid.replace("-", "") in haystack for sid in soc_ids):
                issues.append({
                    "severity": "warning",
                    "title": "Chip differs from the one expected for the model",
                    "detail": (
                        f"A {name} has a {spec.get('soc') or '/'.join(soc_ids)} "
                        f"(expected part numbers: {', '.join(soc_ids)}), but the "
                        f"device declares \"{declared_soc or 'n/a'}\" on "
                        f"platform \"{platform or 'n/a'}\". "
                        f"(Confidence: {conf}.)"
                    ),
                    "evidence": {"expected_ids": soc_ids, "declared": declared_soc,
                                 "platform": platform, "kernel": hardware},
                })
            else:
                issues.append({
                    "severity": "ok",
                    "title": "Chip conforms to the model",
                    "detail": (
                        f"The device declares \"{declared_soc or platform}\", "
                        f"compatible with the {spec.get('soc')} expected for a {name}."
                    ),
                    "evidence": {"declared": declared_soc, "platform": platform},
                })

        # -- mobile radio ------------------------------------------------------
        # Tablets come in Wi-Fi-only and cellular versions with different part
        # numbers. A board from one version inside the other's identity is a
        # relabelled device.
        wifi_only = [m.lower() for m in spec.get("wifi_only_models") or []]
        model = str(measured("system", "partitions", "effective", "model", default="") or "")
        features = {str(f).split("=", 1)[0]
                    for f in measured("sensors", "features", default=[]) or []}
        if wifi_only and model and features:
            has_radio = "android.hardware.telephony" in features
            is_wifi_only = any(model.lower().startswith(m) for m in wifi_only)
            if is_wifi_only and has_radio:
                issues.append({
                    "severity": "warning",
                    "title": "Mobile radio on a Wi-Fi-only model",
                    "detail": (
                        f"{model} is the Wi-Fi-only version of the {name}, yet the "
                        "device declares a mobile radio. Either the board comes "
                        "from the cellular version and the model was changed in "
                        "software, or the identity was rewritten."
                    ),
                    "evidence": {"model": model, "telephony": True},
                })
            elif not is_wifi_only and not has_radio:
                issues.append({
                    "severity": "warning",
                    "title": "No mobile radio on a cellular model",
                    "detail": (
                        f"{model} is the cellular version of the {name}, yet the "
                        "device declares no mobile radio. Either the board comes "
                        "from the Wi-Fi-only version, or the radio is missing or "
                        "disabled."
                    ),
                    "evidence": {"model": model, "telephony": False},
                })
            else:
                issues.append({
                    "severity": "ok",
                    "title": "Mobile radio as expected for the model",
                    "detail": (
                        f"{model} is the {'Wi-Fi-only' if is_wifi_only else 'cellular'} "
                        f"version of the {name}, and the device "
                        f"{'has no' if is_wifi_only else 'declares a'} mobile radio."
                    ),
                    "evidence": {"model": model, "telephony": has_radio},
                })

        return issues
