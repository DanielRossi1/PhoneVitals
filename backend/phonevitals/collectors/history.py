"""The phone's past: age, time in use, restarts, crashes, accounts.

None of this is stored in one place. It is pieced together from traces the
system leaves for its own purposes:

- manufacturing month, from the serial number where the manufacturer encodes
  it (Samsung does);
- first boot after the last factory reset, from the install time the package
  manager records for the system apps on that boot;
- boots since that reset, from a counter the framework keeps in settings;
- why the phone restarted, from the boot reasons the bootloader passes and
  AOSP's bootstat keeps a history of;
- what crashed, from the system's DropBox, which files kernel panics, system
  watchdogs and framework crashes by tag;
- whether a Google account is still signed in, which matters to whoever buys
  the phone: after a reset, Factory Reset Protection asks for that account.
  Only the number of accounts of each type leaves the phone, never a name;
- whether someone else still controls it: an organisation's device owner, a
  financing lock (Android's Device Lock, Samsung Knox Guard);
- hardware errors the system logged (storage I/O, modem restarts...);
- whether personal files are still there, counted, never read.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .base import Collector, parse_props, to_int

# Samsung serials (e.g. R5CR8TEST01): the fourth character is the year and
# the fifth the month (1-9, then A-C). Only the year letters observed on
# phones of known age are listed; others are left undecoded rather than
# guessed.
SAMSUNG_YEARS = {"M": 2019, "N": 2020, "R": 2021, "T": 2022, "W": 2023,
                 "X": 2024, "Y": 2025}
SAMSUNG_MONTHS = {**{str(i): i for i in range(1, 10)}, "A": 10, "B": 11, "C": 12}

# Substrings of a boot reason that mean the phone did not restart because
# someone asked it to.
ABNORMAL_BOOT = ("panic", "watchdog", "wdog", "hw_reset", "hard", "thermal",
                 "kernel", "crash", "abnormal", "oom", "brownout", "undervoltage")

# Log lines that point at hardware, normalised to a label. Matched on the
# phone, so only the counts come back.
LOG_ERRORS = {
    "i/o error": "storage I/O errors",
    "ext4-fs error": "file system errors",
    "f2fs": "file system errors",
    "ufshcd": "storage controller errors",
    "mmc": "storage controller errors",
    "subsystem restart": "modem or DSP restarts",
    "modem": "modem crashes",
    "thermal shutdown": "thermal shutdowns",
    "sensor": "sensor timeouts",
    "camera": "camera failures",
}
_LOG_PATTERN = ("(I/O error|EXT4-fs error|f2fs[^:]*error|ufshcd[^:]*(error|fail)|"
                "mmc[0-9][^:]*error|subsystem restart|modem[^:]*crash|thermal shutdown|"
                "sensor[^:]*timeout|camera[^:]*died)")

# Shared storage folders where personal files end up.
USER_DIRS = ("DCIM", "Pictures", "Download", "Documents", "Movies", "Music",
             "Recordings", "WhatsApp", "Android/media")

# DropBox tags worth counting, and what they mean to a buyer.
# SYSTEM_LAST_KMSG is not counted: it is filed after any boot that kept the
# previous kernel log, which includes every update through recovery, so it
# says nothing about a crash. Panics show up in the boot reasons instead.
CRASH_TAGS = {
    "SYSTEM_RESTART": "framework restarts",
    "system_server_watchdog": "system watchdog resets",
    "system_server_crash": "system server crashes",
    "SYSTEM_TOMBSTONE": "native process crashes",
    "system_app_anr": "system app freezes",
}


class HistoryCollector(Collector):
    name = "history"
    title = "Usage history"

    def commands(self) -> dict[str, str]:
        return {
            "hist.boot_count": "settings get global boot_count 2>/dev/null",
            "hist.boot_history": "getprop persist.sys.boot.reason.history",
            # Per day: packages first installed, and how many distinct
            # seconds they span. The first boot after a reset installs the
            # system apps over a minute or so; a build that stamps its own
            # placeholder date puts them all on the very same second.
            "hist.install_days": "dumpsys package packages 2>/dev/null"
                                 " | grep -E '^ +firstInstallTime=' | sed 's/.*=//'"
                                 " | awk '{d=substr($0,1,10); n[d]++; if (!seen[$0]++) u[d]++}"
                                 " END {for (d in n) print n[d], u[d], d}' | sort -k3 | head -60",
            "hist.dropbox": "dumpsys dropbox 2>/dev/null"
                            " | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2} '"
                            " | awk '{print $1, $3}' | sort | uniq -c",
            # Device Owner Type 1 is a financed device (DevicePolicyManager).
            "hist.owners": "dpm list-owners 2>/dev/null; dumpsys device_policy 2>/dev/null"
                           " | grep -iE 'Device Owner Type|Enabled Device Admins|admin=' | head -8",
            # adbd logs every command it runs, this one included: without
            # dropping its lines, the pattern below would find itself in the
            # log of the previous analysis and report errors that never were.
            "hist.log_errors": "logcat -d -t 60000 -b main,system,crash,kernel 2>/dev/null"
                               " | grep -v -e ' adbd ' -e 'adbd  ' -e '__PV_' -e 'grep -'"
                               f" | grep -oiE '{_LOG_PATTERN}' | tr 'A-Z' 'a-z'"
                               " | sort | uniq -c | head -20",
            "hist.user_files": "for d in " + " ".join(USER_DIRS) + "; do"
                               " echo \"$d $(find /sdcard/$d -type f 2>/dev/null | wc -l)\"; done",
            # The account name is cut away on the phone: only types and counts
            # come back.
            "hist.accounts": "dumpsys account 2>/dev/null"
                             " | grep -oE 'Account \\{name=[^,]*, type=[A-Za-z0-9._-]+\\}'"
                             " | sort -u | sed 's/.*type=//; s/}$//' | sort | uniq -c;"
                             " echo accounts-read",
        }

    def parse(self, raw: dict[str, str]) -> dict[str, Any]:
        props = parse_props(raw.get("sys.props", ""))
        return {
            "manufactured": self._manufactured(props),
            "setup_date": self._setup_date(raw.get("hist.install_days", "")),
            "boot_count": self._boot_count(raw.get("hist.boot_count", "")),
            "boot_reason": props.get("sys.boot.reason") or props.get("ro.boot.bootreason") or None,
            "boot_history": self._boot_history(raw.get("hist.boot_history", "")),
            "crashes": self._crashes(raw.get("hist.dropbox", "")),
            "accounts": self._accounts(raw.get("hist.accounts", "")),
            "control": self._control(raw.get("hist.owners", ""), props),
            "region": {k: v for k, v in {
                "sales_code": props.get("ro.csc.sales_code") or props.get("ro.boot.sales_code"),
                "carrier_id": props.get("ro.boot.carrierid"),
                "country": props.get("ro.csc.country_code"),
            }.items() if v} or None,
            "log_errors": self._log_errors(raw.get("hist.log_errors", "")),
            "user_files": self._user_files(raw.get("hist.user_files", "")),
        }

    @staticmethod
    def _control(text: str, props: dict[str, str]) -> dict[str, Any]:
        # `dpm list-owners` names device and profile owners; device admins
        # (Find My Device and the like) are ordinary and only counted.
        owners = [line.strip() for line in text.splitlines()
                  if "owner" in line.lower() and "owner type" not in line.lower()
                  and "no owners" not in line.lower()]
        admins = sum(1 for line in text.splitlines() if "admin=" in line)
        m = re.search(r"Device Owner Type:\s*(-?\d+)", text)
        owner_type = int(m.group(1)) if m else None
        kg_state = props.get("knox.kg.state") or ""
        return {
            "read": bool(text.strip()) or owner_type is not None,
            "owners": owners[:5],
            "device_admins": admins,
            "financed": owner_type == 1,
            "knox_guard": kg_state or None,
            "knox_guard_locked": kg_state.lower() in ("active", "locked"),
        }

    @staticmethod
    def _log_errors(text: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for line in text.splitlines():
            m = re.match(r"\s*(\d+)\s+(.+)$", line)
            if not m:
                continue
            label = next((v for k, v in LOG_ERRORS.items() if k in m.group(2)), None)
            if label:
                out[label] = out.get(label, 0) + int(m.group(1))
        return out

    @staticmethod
    def _user_files(text: str) -> dict[str, Any] | None:
        counts = {}
        for line in text.splitlines():
            m = re.match(r"(\S+)\s+(\d+)$", line.strip())
            if m:
                counts[m.group(1)] = int(m.group(2))
        if not counts:
            return None
        return {"by_folder": counts, "total": sum(counts.values())}

    @staticmethod
    def _manufactured(props: dict[str, str]) -> dict[str, Any] | None:
        brand = (props.get("ro.product.brand") or props.get("ro.product.system.brand") or "").lower()
        serial = props.get("ro.serialno") or props.get("ro.boot.serialno") or ""
        if brand != "samsung" or len(serial) != 11 or not serial.isalnum():
            return None
        year = SAMSUNG_YEARS.get(serial[3].upper())
        month = SAMSUNG_MONTHS.get(serial[4].upper())
        if not year or not month:
            return None
        return {"year": year, "month": month, "iso": f"{year}-{month:02d}",
                "source": "serial number (Samsung convention)"}

    @staticmethod
    def _setup_date(text: str) -> dict[str, Any] | None:
        days = []
        for line in text.splitlines():
            m = re.match(r"\s*(\d+)\s+(\d+)\s+(\d{4}-\d{2}-\d{2})$", line)
            if not m:
                continue
            count, distinct, day = int(m.group(1)), int(m.group(2)), m.group(3)
            # A clock not yet set at first boot stamps 1970 or 2009, and some
            # builds stamp their system apps with one placeholder instant (seen:
            # 200 packages at 2021-01-01, same second, on a phone set up in
            # 2026). Neither is a day the phone was used.
            if day < "2012-01-01" or (count >= 20 and distinct == 1):
                continue
            days.append((day, count))
        if not days:
            return None
        # The first boot installs dozens of packages on the same day; a lone
        # early date is more likely an app with a stale timestamp.
        bulk = [d for d in days if d[1] >= 20]
        day, count = min(bulk or days)
        try:
            age_days = (date.today() - date.fromisoformat(day)).days
        except ValueError:
            age_days = None
        return {"iso": day, "packages": count, "days_ago": age_days,
                "confident": bool(bulk)}

    @staticmethod
    def _boot_count(text: str) -> int | None:
        value = to_int(text.strip())
        return value if value is not None and value >= 0 else None

    @staticmethod
    def _boot_history(text: str) -> list[dict[str, Any]]:
        """`persist.sys.boot.reason.history`: newest first, `reason,epoch`."""
        entries = []
        for line in text.replace("\\n", "\n").splitlines():
            line = line.strip()
            if not line:
                continue
            reason, _, stamp = line.rpartition(",")
            if not reason or not stamp.isdigit():
                reason, stamp = line, ""
            entries.append({
                "reason": reason,
                "epoch": int(stamp) if stamp else None,
                "abnormal": any(k in reason.lower() for k in ABNORMAL_BOOT),
            })
        return entries

    @staticmethod
    def _crashes(text: str) -> dict[str, Any]:
        counts: dict[str, int] = {}
        days: list[str] = []
        for line in text.splitlines():
            m = re.match(r"\s*(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(\S+)$", line)
            if not m:
                continue
            count, day, tag = int(m.group(1)), m.group(2), m.group(3)
            days.append(day)
            if tag in CRASH_TAGS:
                counts[tag] = counts.get(tag, 0) + count
        return {
            "counts": counts,
            "labels": {tag: CRASH_TAGS[tag] for tag in counts},
            "since": min(days) if days else None,
            "available": bool(days),
        }

    @staticmethod
    def _accounts(text: str) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for line in text.splitlines():
            m = re.match(r"\s*(\d+)\s+(\S+)$", line)
            if m:
                by_type[m.group(2)] = int(m.group(1))
        # The marker tells "no accounts" apart from a command that never ran.
        return {"by_type": by_type, "google": by_type.get("com.google", 0),
                "read": "accounts-read" in text}
