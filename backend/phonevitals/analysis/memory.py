"""Findings from the local memory: earlier sightings and reference units."""

from __future__ import annotations

from typing import Any


def _finding(severity: str, category: str, title: str, detail: str,
             strength: str, **evidence) -> dict[str, Any]:
    return {"severity": severity, "category": category, "title": title, "detail": detail,
            "strength": strength, "strength_label": strength.capitalize(),
            "evidence": {"source": "local memory", **evidence}}


def memory_findings(memory: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen = memory.get("sightings") or {}
    if seen.get("imei_on_other_devices"):
        others = "; ".join(f"{o['model'] or 'a device'} on {o['seen_at'][:10]}"
                           for o in seen["imei_on_other_devices"])
        out.append(_finding(
            "warning", "identity", "IMEI already seen on another device",
            f"An IMEI of this phone was read before from a different device ({others}): "
            "different serial number and processor. Two phones cannot share an IMEI; "
            "one of them carries a copied identity.",
            "measured", other_devices=seen["imei_on_other_devices"]))
    if seen.get("seen_before"):
        changed = seen.get("changed_components") or []
        out.append(_finding(
            "warning" if changed else "info", "history",
            "Components changed since the last analysis" if changed else "Analysed here before",
            f"This phone was analysed on this computer {seen['seen_before']} time(s), first on "
            f"{seen['first_seen'][:10]}, last on {seen['last_seen'][:10]}."
            + (f" Since then these parts have a different identifier: {', '.join(changed)}. "
               "They were replaced in between." if changed else
               " Its components are the same as last time."),
            "proven" if changed else "measured", changed=changed))

    ref = memory.get("reference")
    if ref:
        strict = [d for d in ref["differences"] if d["strict"]]
        loose = [d for d in ref["differences"] if not d["strict"]]
        describe = lambda ds: "; ".join(f"{d['name']}: {d['this']} instead of {d['reference']}"
                                        for d in ds)
        if strict:
            out.append(_finding(
                "warning", "specifications", "Differs from your reference unit",
                f"Compared with the reference unit \"{ref['label']}\" saved on "
                f"{ref['saved_at'][:10]}: {describe(strict)}. Genuine units of one model "
                "share these, so this phone is a different model or variant than it claims.",
                "measured", differences=strict))
        if loose:
            out.append(_finding(
                "info", "specifications", "Parts differ from the reference unit",
                f"{describe(loose)}. Manufacturers source these from several suppliers, so "
                "a difference is common; it matters together with other findings.",
                "circumstantial", differences=loose))
        if not ref["differences"]:
            out.append(_finding(
                "ok", "specifications", "Matches your reference unit",
                f"All {ref['compared']} traits compared match the reference unit "
                f"\"{ref['label']}\" saved on {ref['saved_at'][:10]}.",
                "measured"))
    return out
