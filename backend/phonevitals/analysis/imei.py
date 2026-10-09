"""IMEI validation.

A methodological warning, because it is easy to manufacture false certainty
here.

What is *provable* offline:
  - the structure: 15 digits, of which 8 are TAC, 6 the serial number, 1 the
    check digit;
  - the check digit, computed with the Luhn algorithm. That is arithmetic, not
    opinion. An IMEI that fails it was never assigned to anyone: it is made up.
What is *conventional but not guaranteed*, and therefore never on its own a
verdict:
  - that the IMEIs of one handset share a TAC. They usually do, and their
    serial numbers usually sit next to each other, but the GSMA allocates TACs
    per model *variant* and a manufacturer holding several blocks may take the
    second IMEI from a different one. Treated as something to check, not as
    proof of tampering.

Finding more than one IMEI is not itself suspicious: a dual-SIM handset, or one
with an eSIM, is assigned one IMEI per radio stack by design.

What is *not* provable without an external source:
  - which brand and model a TAC corresponds to. That is a table assigned by the
    GSMA and has to be downloaded; it cannot be derived by computation.
  - whether an IMEI is reported stolen or blocked. That requires querying a
    registry (GSMA Device Check, national CEIRs).

If the TAC database is absent the module says so explicitly instead of
guessing. An invented brand/model match would produce false counterfeit
alarms, which is the worst error this program can make.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TAC_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "tac.csv"

# Brands that share TAC allocations. The GSMA registers a TAC under the name of
# the company that applied for it, which is often the parent or the original
# maker rather than the brand on the box: Redmi and POCO phones appear as
# Xiaomi, Nokia phones as HMD Global, early Realme and Honor models as Oppo and
# Huawei. Comparing names literally would call those genuine phones
# counterfeit.
BRAND_FAMILIES = (
    {"xiaomi", "redmi", "poco", "blackshark"},
    {"huawei", "honor"},
    {"oppo", "realme", "oneplus"},
    {"vivo", "iqoo"},
    {"hmd", "hmd global", "nokia"},
    {"motorola", "lenovo"},
    {"tcl", "alcatel"},
    {"zte", "nubia"},
    {"transsion", "tecno", "infinix", "itel"},
)


def same_maker(tac_brand: str, device_brand: str) -> bool:
    """Whether a TAC registrant and a device brand can be the same company."""
    a, b = tac_brand.strip().lower(), device_brand.strip().lower()
    if not a or not b or a in b or b in a:
        return True
    return any(
        any(name in a for name in family) and any(name in b for name in family)
        for family in BRAND_FAMILIES
    )


# --------------------------------------------------------------------- Luhn

def luhn_valid(imei: str) -> bool:
    """Verify the Luhn check digit over 15 digits."""
    digits = re.sub(r"\D", "", imei or "")
    if len(digits) != 15:
        return False
    return luhn_check_digit(digits[:14]) == digits[14]


def luhn_check_digit(first14: str) -> str:
    """Compute the 15th digit from the first 14.

    Digits in even positions counting from the right are doubled, the digits of
    any two-digit result are summed, and the check digit is the one that brings
    the total to the next multiple of 10.
    """
    total = 0
    for i, ch in enumerate(reversed(first14)):
        d = int(ch)
        if i % 2 == 0:          # even position counting from the right
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


# ----------------------------------------------------------------- database

@dataclass
class TacEntry:
    tac: str
    brand: str = ""
    model: str = ""
    name: str = ""
    extra: dict[str, str] = field(default_factory=dict)


class TacDatabase:
    """Local TAC database, loaded from CSV if present.

    Expected format (header required, extra columns ignored):
        tac,brand,model,name
    """

    def __init__(self, path: str | Path = TAC_DB_PATH):
        self.path = path
        self._entries: dict[str, TacEntry] = {}
        self.loaded = False
        self.error: str | None = None
        self.load()

    def load(self) -> None:
        if not Path(self.path).is_file():
            self.error = "TAC database not present"
            return
        try:
            with open(self.path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    digits = re.sub(r"\D", "", row.get("tac") or "")
                    if not digits:
                        continue
                    tac = digits.zfill(8)[:8]
                    self._entries[tac] = TacEntry(
                        tac=tac,
                        brand=(row.get("brand") or "").strip(),
                        model=(row.get("model") or "").strip(),
                        name=(row.get("name") or "").strip(),
                    )
            self.loaded = True
            self.error = None
        except (OSError, csv.Error, UnicodeDecodeError) as exc:
            self.error = f"TAC database unreadable: {exc}"

    def lookup(self, tac: str) -> TacEntry | None:
        return self._entries.get(tac)

    @property
    def size(self) -> int:
        return len(self._entries)


_DB: TacDatabase | None = None


def get_db() -> TacDatabase:
    global _DB
    if _DB is None:
        _DB = TacDatabase()
    return _DB


# ------------------------------------------------------------------ analysis

def parse_imei(imei: str) -> dict[str, Any]:
    """Decompose and validate a single IMEI."""
    digits = re.sub(r"\D", "", imei or "")

    result: dict[str, Any] = {
        "input": imei,
        "digits": digits,
        "length": len(digits),
        "valid": False,
        "problems": [],
    }

    if not digits:
        result["problems"].append("No digits recognised.")
        return result

    if len(digits) != 15:
        result["problems"].append(
            f"An IMEI has 15 digits, this one has {len(digits)}."
        )
        return result

    tac = digits[:8]
    serial = digits[8:14]
    check = digits[14]
    expected = luhn_check_digit(digits[:14])

    result.update({
        "tac": tac,
        "serial_number": serial,
        "check_digit": check,
        "expected_check_digit": expected,
        "luhn_valid": check == expected,
        "reporting_body": tac[:2],
    })

    if check != expected:
        result["problems"].append(
            f"The check digit does not add up: it is {check} but should be "
            f"{expected}. A genuinely assigned IMEI always passes this check, "
            "so this number was invented or mistranscribed."
        )
        return result

    # One or two distinct digits: formally valid only by coincidence, and the
    # typical values of fake or wiped firmware.
    if len(set(digits)) <= 2:
        result["problems"].append(
            "The number consists of one or two repeated digits: it is a "
            "placeholder value, not a real IMEI."
        )

    db = get_db()
    if db.loaded:
        entry = db.lookup(tac)
        if entry:
            result["tac_info"] = {
                "brand": entry.brand,
                "model": entry.model,
                "name": entry.name,
                "found": True,
            }
        else:
            result["tac_info"] = {
                "found": False,
                "note": (
                    "The TAC does not appear in the local database. This may "
                    "mean the database is incomplete, or that the code was "
                    "never assigned."
                ),
            }
    else:
        result["tac_info"] = {
            "found": None,
            "note": (
                f"Brand/model correspondence not verified: {db.error}. "
                "Populate backend/data/tac.csv to enable this check."
            ),
        }

    result["valid"] = not result["problems"]
    return result


def analyse_imeis(imeis: list[str], device_brand: str = "",
                  device_model: str = "") -> dict[str, Any]:
    """Analyse the set of IMEIs found and compare them against the device."""
    parsed = [parse_imei(i) for i in imeis]
    findings: list[dict[str, str]] = []

    valid = [p for p in parsed if p.get("luhn_valid")]
    invalid = [p for p in parsed if p["length"] == 15 and not p.get("luhn_valid")]

    for p in invalid:
        findings.append({
            "severity": "critical",
            "title": "IMEI with an incorrect check digit",
            "detail": p["problems"][0] if p["problems"] else "",
        })

    # TAC consistency across slots.
    #
    # More than one IMEI is not an anomaly and is never reported as one: a
    # dual-SIM handset, or one with an eSIM, is assigned one IMEI per radio
    # stack by design. What is worth looking at is whether they agree.
    tacs = {p["tac"] for p in valid if p.get("tac")}
    if len(tacs) > 1:
        findings.append({
            "severity": "warning",
            "title": "The IMEIs of this phone carry different TACs",
            "detail": (
                f"{len(tacs)} different TACs were read ({', '.join(sorted(tacs))}). "
                "Slots of one handset usually share a TAC, because it identifies "
                "the model -- but this is a convention, not a rule the GSMA "
                "enforces: manufacturers hold several TAC blocks for one model "
                "and the second IMEI is sometimes allocated from another block. "
                "Worth checking against the label under the battery or on the SIM "
                "tray; on its own it does not establish that anything was "
                "rewritten."
            ),
        })
    elif len(tacs) == 1 and len(valid) > 1:
        findings.append({
            "severity": "ok",
            "title": "TAC consistent across slots",
            "detail": (
                f"All {len(valid)} IMEIs share TAC {next(iter(tacs))}, as expected "
                "on a genuine multi-SIM or eSIM device."
            ),
        })

    # Brand declared by the TAC against the device brand.
    #
    # Evaluated once per distinct TAC rather than once per IMEI. Both slots of a
    # dual-SIM phone normally carry the same TAC, so iterating over the IMEIs
    # raised the identical finding twice -- and since the verdict is decided by
    # counting findings by severity, one fact was pushing the device towards
    # "compromised" with double the weight it deserved.
    seen_tacs: set[str] = set()
    for p in valid:
        tac = p.get("tac") or ""
        if tac in seen_tacs:
            continue
        info = p.get("tac_info") or {}
        if not info.get("found"):
            continue
        seen_tacs.add(tac)
        tac_brand = (info.get("brand") or "").strip().lower()
        dev_brand = (device_brand or "").strip().lower()
        if not same_maker(tac_brand, dev_brand):
            findings.append({
                "severity": "critical",
                "title": "The IMEI belongs to another brand",
                "detail": (
                    f"TAC {tac} is assigned to \"{info.get('brand')} "
                    f"{info.get('model')}\", but the device declares itself "
                    f"\"{device_brand} {device_model}\". On an authentic phone "
                    "the IMEI matches the model."
                ),
            })
        elif tac_brand and dev_brand:
            findings.append({
                "severity": "ok",
                "title": "IMEI consistent with the model",
                "detail": (
                    f"TAC {tac} is assigned to \"{info.get('brand')} "
                    f"{info.get('model')}\", in line with the detected device."
                ),
            })

    if valid and not invalid:
        findings.insert(0, {
            "severity": "ok",
            "title": "IMEI structure valid",
            "detail": (
                f"{len(valid)} of {len(parsed)} IMEIs pass the Luhn check: the "
                "check digit is mathematically correct."
            ),
        })

    return {
        "imeis": parsed,
        "valid_count": len(valid),
        "invalid_count": len(invalid),
        "distinct_tacs": sorted(tacs) if tacs else [],
        "findings": findings,
        "database": {
            "loaded": get_db().loaded,
            "size": get_db().size,
            "error": get_db().error,
        },
    }
