"""Identifier extraction: IMEI, MEID, serial number.

Why all this indirection. Up to Android 9, `service call iphonesubinfo 1` from
the shell was enough. From Android 10 the IMEI is protected by
READ_PRIVILEGED_PHONE_STATE, a signature permission the shell user does not
hold: the call returns null. It cannot be worked around without root or a
system app.

What is *not* protected is the screen. The phone shows the IMEI to anyone
looking at it, and `uiautomator` reads the view tree including the texts. So
the route is: bring up a screen that shows the IMEI (the *#06# dialog, or
Settings as a fallback), read the tree, extract the digits. This is not a
security bypass, it is the same information an operator would read off the
display, automated.

Two physical requirements remain that no software can remove: the screen must
be on and unlocked.
"""

from __future__ import annotations

import asyncio
import base64
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from collections.abc import Callable, Iterator
from typing import Any

from ..adb import Adb
from ..analysis.imei import luhn_check_digit, luhn_valid

# Isolated runs of 14-17 digits. Only IMEI (15) and IMEISV (16) are used; the
# wider match keeps a longer number from being read as an IMEI-sized slice of
# itself. MEID is hexadecimal and handled separately.
DIGIT_RUN = re.compile(r"(?<!\d)(\d{14,17})(?!\d)")

# Labels to tap on the way down to the IMEI screen. Samsung buries the IMEI
# under "Status information"; Pixel shows it directly in "About phone", and on
# recent builds behind a "SIM status" or "IMEI" entry.
#
# These are match data, not source language: they are compared against the menu
# entries the phone actually renders, so they have to be spelt the way the
# phone's own locale spells them. The Italian entries are here because Italian
# handsets label these screens that way, and translating them would break
# exactly the devices they exist for. Add other locales rather than replacing
# these.
DRILL_LABELS = (
    "imei", "stato", "status", "informazioni sullo stato", "status information",
    "informazioni sul telefono", "phone information", "sim status",
    "stato della sim", "informazioni imei", "imei information",
    "about phone", "device identifiers", "identificativi dispositivo",
)

# Properties that on some chipsets still hold the IMEI in the clear. They are
# not guaranteed to exist and are not trustworthy on their own, but where they
# are present they serve as a cross-check against the screen reading.
IMEI_PROPS = (
    "ril.serialnumber", "ro.ril.oem.imei", "ro.ril.oem.imei1", "ro.ril.oem.imei2",
    "persist.radio.imei", "persist.radio.imei1", "persist.radio.imei2",
    "gsm.imei", "ril.imei", "ril.imei1", "ril.imei2", "vendor.gsm.imei",
)

# Enough deletes to empty any dialpad field: it keeps whatever was left in it.
_CLEAR_FIELD = " ".join(["KEYCODE_DEL"] * 20)


class IdentityProbe:
    """Interactive probe: takes several steps, reading the screen between them."""

    def __init__(self, adb: Adb, serial: str,
                 on_progress: Callable[[str], Any] | None = None):
        self.adb = adb
        self.serial = serial
        self.on_progress = on_progress
        self._screen_size: tuple[int, int] | None = None
        self._ui_not_idle = False

    async def _say(self, message: str) -> None:
        if self.on_progress:
            res = self.on_progress(message)
            if asyncio.iscoroutine(res):
                await res

    # ------------------------------------------------------------------ state

    async def screen_state(self) -> dict[str, Any]:
        """Determine whether the screen is on and whether it is unlocked.

        The NFC service exposes mScreenState in a very compact form
        (OFF_LOCKED / ON_LOCKED / ON_UNLOCKED) that answers both questions in a
        single read. If NFC is absent, fall back to power/window, which exist
        everywhere but are more verbose.
        """
        nfc = await self.adb.text(self.serial,
                                  "dumpsys nfc | grep -m1 mScreenState", timeout=8)
        m = re.search(r"mScreenState=(\w+)", nfc)
        if m:
            state = m.group(1).upper()
            return {
                "raw": state,
                "screen_on": state.startswith("ON"),
                "unlocked": state.endswith("UNLOCKED"),
                "source": "nfc",
            }

        power = await self.adb.text(
            self.serial, "dumpsys power | grep -m2 -E 'mWakefulness|mHoldingDisplay'",
            timeout=8)
        screen_on = "Awake" in power or "mHoldingDisplaySuspendBlocker=true" in power

        window = await self.adb.text(
            self.serial,
            "dumpsys window 2>/dev/null | grep -m2 -E "
            "'mDreamingLockscreen|isStatusBarKeyguard|keyguardShowing'",
            timeout=8)
        locked = bool(re.search(r"(mDreamingLockscreen|keyguardShowing)=true", window)) \
                 or "isStatusBarKeyguard=true" in window

        return {
            "raw": power.strip()[:120],
            "screen_on": screen_on,
            "unlocked": screen_on and not locked,
            "source": "power+window",
        }

    async def wake(self) -> None:
        """Turn the screen on without unlocking it (we never touch the PIN)."""
        await self.adb.shell(self.serial, "input keyevent KEYCODE_WAKEUP", timeout=8)
        await asyncio.sleep(0.4)

    async def screen_size(self) -> tuple[int, int]:
        """Physical screen size, cached.

        The scroll gesture used to be hardcoded to 540/1600/700, which assumes
        a 1080x1920-ish panel. On anything taller or wider the swipe either
        misses the list or scrolls the wrong amount, so the coordinates are
        derived from the real size instead.
        """
        if self._screen_size:
            return self._screen_size
        text = await self.adb.text(self.serial, "wm size", timeout=8)
        m = re.search(r"Physical size:\s*(\d+)x(\d+)", text)
        if not m:
            m = re.search(r"(\d+)x(\d+)", text)
        self._screen_size = (
            (int(m.group(1)), int(m.group(2))) if m else (1080, 1920)
        )
        return self._screen_size

    async def _scroll_down(self) -> None:
        width, height = await self.screen_size()
        x = width // 2
        await self.adb.shell(
            self.serial,
            f"input swipe {x} {int(height * 0.70)} {x} {int(height * 0.30)} 250",
            timeout=10)

    # --------------------------------------------------------------- gathering

    async def run(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "serials": await self._serials(),
            "imeis": [],
            "meid": None,
            "sources": [],
            "screen": await self.screen_state(),
            "notes": [],
        }

        # 1. Cheap routes: properties and binder. These work on older Android
        #    and on some recent chipsets, and cost one round-trip.
        await self._say("Trying the direct routes (system properties, binder)")
        direct = await self._direct()
        if direct["imeis"]:
            result["imeis"].extend(direct["imeis"])
            result["sources"].append(direct["source"])
        result["direct_probe"] = direct

        # 2. If the direct routes are not enough, go through the screen.
        if not result["imeis"]:
            screen = result["screen"]
            if not screen["screen_on"]:
                await self._say("Screen is off: turning it on")
                await self.wake()
                result["screen"] = screen = await self.screen_state()

            if not screen["unlocked"]:
                result["notes"].append(
                    "The screen is locked. The IMEI is not readable over ADB on "
                    "Android 10 and later: the phone must be unlocked so it can "
                    "be read from Settings. Unlock it and re-run this section."
                )
                result["needs_unlock"] = True
                return result

            # 2a. *#06# first. It is defined by 3GPP TS 22.030 and every phone
            #     implements it, it lists all slots on one screen, and it needs
            #     none of the language-dependent label matching the Settings
            #     route relies on. It is also the only route that works on
            #     Pixel, whose device-info screens never go idle.
            await self._say("Reading the IMEI with the *#06# code")
            mmi = await self._from_mmi()
            result["mmi_probe"] = mmi
            if mmi["imeis"]:
                result["imeis"].extend(mmi["imeis"])
                result["sources"].append("*#06#")
            if mmi.get("meid"):
                result["meid"] = mmi["meid"]
            if mmi.get("evidence"):
                result["evidence"] = [mmi.pop("evidence")]

            # 2b. Fallback: walk Settings. Slower and dependent on the phone's
            #     interface language, but it survives skins that swallow the
            #     MMI code.
            if not result["imeis"]:
                await self._say("Reading the IMEI from Settings")
                ui = await self._from_settings()
                result["ui_probe"] = ui
                if ui["imeis"]:
                    result["imeis"].extend(ui["imeis"])
                    result["sources"].append("settings")
                if ui.get("meid"):
                    result["meid"] = ui["meid"]
                if ui.get("unavailable") == "settings_never_idle":
                    result["notes"].append(
                        "The Settings device-info screens could not be read: "
                        "they keep emitting UI events, so uiautomator never "
                        "reaches the idle state it requires before dumping. "
                        "This is normal on Pixel."
                    )

            await self._restore()

        unique = list(dict.fromkeys(result["imeis"]))
        result["imeis"] = unique

        if not unique and not result.get("needs_unlock"):
            result["notes"].append(
                "The IMEI could not be read automatically. You can enter it by "
                "hand (dial *#06# on the phone, or read it off the SIM tray) and "
                "it will still be validated."
            )
        return result

    # ----------------------------------------------------------------- routes

    async def _serials(self) -> dict[str, Any]:
        """Serial number from several independent sources.

        `ro.serialno` comes from system properties, `ro.boot.serialno` is passed
        by the bootloader on the kernel command line, and the USB transport
        serial is reported by the device itself at descriptor level. Three
        different origins: if they disagree, something in the chain was
        rewritten.
        """
        out = await self.adb.batch(self.serial, {
            "ro": "getprop ro.serialno",
            "boot": "getprop ro.boot.serialno",
            "vendor": "getprop ro.vendor.boot.serialno",
        }, timeout=20)
        usb = (await self.adb.raw("-s", self.serial, "get-serialno",
                                  timeout=10)).out.strip()

        values = {k: v.strip() for k, v in out.items() if v.strip()}
        # Over `adb connect` the transport "serial" is host:port (or an mDNS
        # service name), an address rather than a property of the device:
        # comparing it would report a disagreement on every wireless session.
        if usb and ":" not in usb and "._adb" not in usb:
            values["usb_transport"] = usb

        # Compared case-insensitively: the bootloader and the property store
        # frequently disagree on casing for the same serial, which is not a
        # discrepancy worth reporting.
        distinct = {v.upper() for v in values.values() if v and v != "unknown"}
        return {
            "values": values,
            "primary": values.get("ro") or values.get("boot") or usb,
            "consistent": len(distinct) <= 1,
            "distinct_count": len(distinct),
        }

    async def _direct(self) -> dict[str, Any]:
        cmds = {p: f"getprop {p}" for p in IMEI_PROPS}
        # Transaction 1 of iphonesubinfo is getDeviceId. On Android 10+ it
        # returns null, but it works on earlier versions and on some forks.
        cmds["binder"] = "service call iphonesubinfo 1 2>/dev/null"
        cmds["binder_s"] = "service call iphonesubinfo 3 i32 0 2>/dev/null"

        raw = await self.adb.batch(self.serial, cmds, timeout=30)

        imeis: list[str] = []
        source = ""
        for key, value in raw.items():
            if key.startswith("binder"):
                found = self._decode_binder(value)
            else:
                found = [m for m in DIGIT_RUN.findall(value.strip()) if len(m) == 15]
            if found:
                imeis.extend(found)
                source = source or ("binder" if key.startswith("binder")
                                    else f"prop:{key}")

        return {
            "imeis": list(dict.fromkeys(imeis)),
            "source": source or "none",
            "raw": {k: v.strip()[:200] for k, v in raw.items() if v.strip()},
        }

    @staticmethod
    def _decode_binder(output: str) -> list[str]:
        """Decode the hexadecimal output of `service call`.

        The format is `Result: Parcel(00000000 0000000f '....' ...)` where the
        UTF-16 characters sit in the ASCII column between quotes; the digits
        are extracted from there.
        """
        chunks = re.findall(r"'([^']*)'", output)
        text = "".join(chunks).replace(".", "").replace(" ", "")
        digits = re.sub(r"\D", "", text)
        return [digits] if len(digits) == 15 else []

    async def _from_settings(self) -> dict[str, Any]:
        """Open About phone and navigate until the IMEI digits are found."""
        await self.adb.shell(
            self.serial,
            "am start -a android.settings.DEVICE_INFO_SETTINGS "
            "--activity-clear-task --activity-clear-top",
            timeout=15)
        await asyncio.sleep(1.6)

        never_idle = {"imeis": [], "meid": None,
                      "unavailable": "settings_never_idle"}
        visited_labels: set[str] = set()
        for depth in range(4):
            drilled = False
            tree = await self._dump_ui()
            for scroll in range(6):
                if tree is None:
                    if self._ui_not_idle:
                        return never_idle
                    break

                imeis, meid = self._extract_from_tree(tree)
                if imeis:
                    return {"imeis": imeis, "meid": meid, "depth": depth,
                            "scrolls": scroll}

                target = self._find_drill_target(tree, visited_labels)
                if target:
                    visited_labels.add(target["label"])
                    await self.adb.shell(
                        self.serial,
                        f"input tap {target['x']} {target['y']}", timeout=10)
                    await asyncio.sleep(1.3)
                    drilled = True
                    break  # descend from the new screen

                # Nothing to tap and no digits: scroll and try again. The dump
                # taken to see whether the scroll moved anything is the one the
                # next pass examines.
                before = self._tree_signature(tree)
                await self._scroll_down()
                await asyncio.sleep(0.9)
                tree = await self._dump_ui()
                if tree is None and self._ui_not_idle:
                    return never_idle
                if tree is None or self._tree_signature(tree) == before:
                    break  # bottom of the page reached

            if not drilled:
                # No new entry to descend into: going deeper would only repeat
                # the same screen.
                break

        return {"imeis": [], "meid": None}

    async def _from_mmi(self) -> dict[str, Any]:
        """Type *#06# on the dialpad, which pops up the dialog listing the IMEIs.

        The code has to be *typed*, not passed as a `tel:` URI. The dialer
        recognises MMI sequences from a TextWatcher on the input field, and a
        number placed there by an intent does not trigger it: ACTION_DIAL only
        prefills the field, and ACTION_CALL hands *#06# to the network, which
        answers "invalid MMI code". Sending the digits as key events makes the
        dialer react exactly as it would to a finger.

        This route matters more than it looks. On Pixel the Settings screens
        that carry the IMEI never reach the idle state uiautomator waits for,
        so they cannot be dumped at all; the dialer settles normally and its
        dialog dumps fine. Here it is the only route that works.
        """
        await self.adb.shell(self.serial, "am start -a android.intent.action.DIAL",
                             timeout=15)
        await asyncio.sleep(1.8)

        # A stale prefix left in the field turns the sequence into something
        # the dialer no longer recognises.
        await self.adb.shell(self.serial, f"input keyevent {_CLEAR_FIELD}",
                             timeout=20)
        await asyncio.sleep(0.5)

        await self.adb.shell(
            self.serial,
            "input keyevent KEYCODE_STAR KEYCODE_POUND KEYCODE_0 KEYCODE_6 "
            "KEYCODE_POUND",
            timeout=15)
        await asyncio.sleep(2.5)

        tree = await self._dump_ui()
        if tree is None:
            return {"imeis": [], "meid": None}
        imeis, meid = self._extract_from_tree(tree)
        out: dict[str, Any] = {"imeis": imeis, "meid": meid}
        if imeis:
            # The dialog as the operator would have seen it: evidence for the
            # report that the IMEI came from the phone's own screen.
            shot = await self.adb.raw("-s", self.serial, "exec-out", "screencap -p",
                                      timeout=20, binary=True)
            if isinstance(shot.out, (bytes, bytearray)) and shot.out[:8] == b"\x89PNG\r\n\x1a\n":
                out["evidence"] = {
                    "id": "imei_dialog",
                    "title": "IMEI dialog (*#06#) as shown on the phone",
                    "taken_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "png_b64": base64.b64encode(shot.out).decode(),
                }
        return out

    async def _restore(self) -> None:
        """Return the phone to the home screen.

        BACK first, so the *#06# dialog is dismissed and the dialpad left empty
        instead of holding the typed code for whoever picks the phone up next.
        """
        await self.adb.shell(
            self.serial,
            f"input keyevent KEYCODE_BACK {_CLEAR_FIELD} KEYCODE_HOME",
            timeout=20)

    # -------------------------------------------------------------------- ui

    async def _dump_ui(self) -> ET.Element | None:
        """Fetch the current view tree.

        uiautomator writes to a file; it is read back and deleted immediately
        so as to leave nothing on the phone longer than necessary.

        `uiautomator dump` exits 0 even when it fails, printing the reason on
        stdout, so the exit status cannot be used to detect failure -- the
        output has to be inspected instead. The failure that matters is
        "could not get idle state": uiautomator refuses to dump until the
        foreground app stops emitting accessibility events, and some screens
        never stop. It is recorded on the instance so the caller can give up on
        this route immediately rather than retrying a screen that will never
        become dumpable.
        """
        path = "/data/local/tmp/pv_ui.xml"
        r = await self.adb.shell(
            self.serial, f"rm -f {path}; uiautomator dump {path} 2>&1", timeout=25)

        if "could not get idle state" in r.out.lower():
            self._ui_not_idle = True
            return None
        if "dumped to" not in r.out.lower():
            return None

        xml = await self.adb.text(self.serial, f"cat {path}", timeout=20)
        await self.adb.shell(self.serial, f"rm -f {path}", timeout=8)

        if not xml.strip().startswith("<"):
            return None
        try:
            return ET.fromstring(xml)
        except ET.ParseError:
            return None

    @staticmethod
    def _iter_nodes(tree: ET.Element) -> Iterator[ET.Element]:
        yield from tree.iter("node")

    @classmethod
    def _extract_from_tree(cls, tree: ET.Element) -> tuple[list[str], str | None]:
        """Look for 15-digit runs in the view texts.

        Important filter: many screens contain other long digit sequences
        (build numbers, timestamps). Only an exact length of 15 is accepted,
        and candidates failing the Luhn check are discarded *only* if at least
        one valid candidate was found -- so a genuinely counterfeit IMEI (which
        fails Luhn) is never silently hidden.
        """
        candidates: list[str] = []
        meid: str | None = None

        for node in cls._iter_nodes(tree):
            for attr in ("text", "content-desc"):
                value = node.get(attr, "") or ""
                if not value:
                    continue
                for run in DIGIT_RUN.findall(value.replace(" ", "").replace("-", "")):
                    if len(run) == 15:
                        candidates.append(run)
                    elif len(run) == 16:
                        # IMEISV: the first 14 digits plus 2 of software version.
                        candidates.append(run[:14] + luhn_check_digit(run[:14]))
                if re.search(r"\bMEID\b", value, re.I):
                    mm = re.search(r"([0-9A-Fa-f]{14})", value)
                    if mm:
                        meid = mm.group(1)

        unique = list(dict.fromkeys(candidates))
        valid = [c for c in unique if luhn_valid(c)]
        return (valid if valid else unique), meid

    @classmethod
    def _find_drill_target(cls, tree: ET.Element,
                           visited: set[str]) -> dict[str, Any] | None:
        """Find a tappable entry leading towards the IMEI."""
        for node in cls._iter_nodes(tree):
            label = (node.get("text", "") or node.get("content-desc", "")).strip()
            if not label or label.lower() in visited:
                continue
            low = label.lower()
            if not any(k in low for k in DRILL_LABELS):
                continue

            # The tappable view may be the node itself or an ancestor; the
            # bounds of the node holding the text are enough to centre the tap.
            bounds = node.get("bounds", "")
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not m:
                continue
            x1, y1, x2, y2 = map(int, m.groups())
            if x2 - x1 < 5 or y2 - y1 < 5:
                continue
            return {
                "label": low,
                "x": (x1 + x2) // 2,
                "y": (y1 + y2) // 2,
            }
        return None

    @staticmethod
    def _tree_signature(tree: ET.Element) -> str:
        """Signature of the visible texts, to tell whether a scroll did anything."""
        texts = [n.get("text", "") for n in tree.iter("node") if n.get("text")]
        return "|".join(texts[:40])
