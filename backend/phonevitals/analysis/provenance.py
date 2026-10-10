"""Where a device was meant to be sold, and where it has been used.

Only codes the device carries are read: the hardware model number, which on
many phones differs by market, Samsung's sales code (CSC) and firmware
region, and the country of the SIM and of the network. None of them tells
where a particular unit was bought; together they tell which market it was
built for, and whether it is now far from it.
"""

from __future__ import annotations

import re
from typing import Any

# Samsung sales codes (ro.csc.sales_code) for the markets they serve. Only
# codes whose meaning is well established are listed; others are shown raw.
CSC_COUNTRIES = {
    "ITV": "Italy", "TIM": "Italy", "VOM": "Italy", "WIN": "Italy", "HUI": "Italy",
    "XEF": "France", "DBT": "Germany", "BTU": "United Kingdom", "EVR": "United Kingdom",
    "XEU": "United Kingdom and Ireland", "PHE": "Spain", "XEO": "Poland", "XEH": "Hungary",
    "ATO": "Austria", "AUT": "Switzerland", "NEE": "Nordic countries", "PHN": "Netherlands",
    "ROM": "Romania", "BGL": "Bulgaria", "CRO": "Croatia", "XEZ": "Czech Republic",
    "TPL": "Portugal", "EUX": "Europe", "XAA": "United States", "TMB": "United States",
    "ATT": "United States", "VZW": "United States", "XAR": "Canada", "KOO": "South Korea",
    "INS": "India", "XSA": "Australia", "XNZ": "New Zealand", "TUR": "Turkey",
    "SER": "Russia", "SEK": "Ukraine", "CHC": "China", "TGY": "Hong Kong", "BRI": "Taiwan",
    "ZTO": "Brazil", "XSP": "Singapore", "XME": "Malaysia", "THL": "Thailand",
    "XXV": "Vietnam", "XTC": "Philippines", "XSG": "United Arab Emirates", "KSA": "Saudi Arabia",
}

# Asus market SKUs (ro.build.asus.sku).
ASUS_MARKETS = {"WW": "Global", "CN": "China", "JP": "Japan", "TW": "Taiwan"}

# ISO 3166 codes the radio reports (gsm.*.iso-country), as names.
COUNTRY_NAMES = {
    "it": "Italy", "fr": "France", "de": "Germany", "gb": "United Kingdom", "es": "Spain",
    "pt": "Portugal", "nl": "Netherlands", "be": "Belgium", "ch": "Switzerland",
    "at": "Austria", "pl": "Poland", "ro": "Romania", "gr": "Greece", "ie": "Ireland",
    "se": "Sweden", "no": "Norway", "dk": "Denmark", "fi": "Finland", "us": "United States",
    "ca": "Canada", "jp": "Japan", "kr": "South Korea", "cn": "China", "hk": "Hong Kong",
    "tw": "Taiwan", "in": "India", "au": "Australia", "br": "Brazil", "tr": "Turkey",
    "ru": "Russia", "ua": "Ukraine", "ae": "United Arab Emirates", "sm": "San Marino",
    "va": "Vatican City", "mt": "Malta", "si": "Slovenia", "hr": "Croatia", "hu": "Hungary",
    "cz": "Czech Republic", "sk": "Slovakia",
}


def _countries(value: str) -> list[str]:
    """`it,` or `it,fr` (one per SIM slot) as distinct country names."""
    out = []
    for code in (value or "").split(","):
        code = code.strip().lower()
        if code:
            name = COUNTRY_NAMES.get(code, code.upper())
            if name not in out:
                out.append(name)
    return out


def provenance(snapshot: dict[str, Any], spec: dict[str, Any] | None = None) -> dict[str, Any]:
    props = (snapshot.get("system") or {}).get("props") or {}
    sku = props.get("ro.boot.hardware.sku") or props.get("ro.boot.product.hardware.sku") or ""
    if sku.lower() in ("unknown", "none", "default"):
        sku = ""
    csc = props.get("ro.csc.sales_code") or props.get("ro.boot.sales_code") or ""
    markets = (spec or {}).get("markets") or {}
    market = markets.get(sku) if sku else None
    if not market and csc:
        market = CSC_COUNTRIES.get(csc.upper())
    # Asus names the market in its SKU (WW_ASUS_A002: worldwide).
    asus_sku = (props.get("ro.build.asus.sku") or props.get("ro.config.versatility") or "").upper()
    if not market and asus_sku:
        market = ASUS_MARKETS.get(asus_sku)
    # Samsung firmware names carry the region right after the model
    # (T725XXS3DWA1: model T725, region XX, the open European firmware).
    region = None
    bootloader = props.get("ro.bootloader") or ""
    model = (props.get("ro.product.model") or "").replace("SM-", "")
    if (props.get("ro.product.brand") or "").lower() == "samsung" and model \
            and bootloader.startswith(model):
        region = bootloader[len(model):len(model) + 2] or None
    # The countries a market name stands for, when it names countries at all
    # ("United States and Canada" does, "Global" or "Europe" does not).
    names = set(COUNTRY_NAMES.values())
    pieces = [m.strip() for m in (market or "").split(" and ")]
    market_countries = pieces if market and all(p in names for p in pieces) else None
    return {
        "hardware_model": sku or None,
        "market": market,
        "market_countries": market_countries,
        "market_source": ("model number" if sku and markets.get(sku)
                          else "sales code" if csc and CSC_COUNTRIES.get(csc.upper())
                          else "Asus SKU" if market else None),
        "customer_id": props.get("ro.config.CID") or None,
        "sales_code": csc or None,
        "warranty_region": props.get("ro.boot.warranty.sku") or None,
        "board_revision": props.get("ro.boot.hardware.revision") or props.get("ro.revision") or None,
        "firmware_region": region,
        "firmware_locale": props.get("ro.product.locale") or None,
        "language": props.get("persist.sys.locale") or None,
        "time_zone": props.get("persist.sys.timezone") or None,
        "sim_countries": _countries(props.get("gsm.sim.operator.iso-country", "")),
        "network_countries": _countries(props.get("gsm.operator.iso-country", "")),
    }


def board_date(snapshot: dict[str, Any]) -> dict[str, str] | None:
    """When the mainboard was made, from the dates that travel with it.

    The battery's dates are left out on purpose: a replaced battery would make
    the phone look as young as the battery.
    """
    made = (snapshot.get("history") or {}).get("manufactured")
    if made and made.get("iso"):
        return {"iso": made["iso"], "source": "serial number"}
    props = (snapshot.get("system") or {}).get("props") or {}
    m = re.match(r"(\d{4})[.\-/]?(\d{2})", props.get("ril.rfcal_date", "") or "")
    if m and 1 <= int(m.group(2)) <= 12:
        return {"iso": f"{m.group(1)}-{m.group(2)}", "source": "factory radio calibration"}
    chip = (snapshot.get("storage") or {}).get("chip_date")
    if chip:
        return {"iso": chip, "source": "storage chip production"}
    return None

