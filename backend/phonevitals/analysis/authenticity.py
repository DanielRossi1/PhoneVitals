"""Verification engine: authenticity, integrity, replaced components.

Rules are ordered by evidential strength, and the report says so explicitly.
There are three levels:

  PROVEN          arithmetic, or a comparison between values that must agree
                  by construction. Depends on no external database and is not
                  a matter of opinion. Examples: the Luhn check digit, identity
                  agreement across the five partitions, a build fingerprint
                  contradicting the declared model.

  MEASURED        a direct hardware reading by the kernel, compared against an
                  expected specification. Depends on how complete the catalogue
                  is, so a discrepancy is a suspicion to verify, not a verdict.

  CIRCUMSTANTIAL  usage statistics and absences. Useful to direct a manual
                  inspection, never sufficient on its own.

One thing the program never does: declare a device authentic. The absence of
anomalies is not proof of authenticity, only the absence of proof to the
contrary. The report states this plainly.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

# Weight on the final score. A critical finding counts several times a
# warning: an inter-partition inconsistency has no innocent explanation.
SEVERITY_WEIGHT = {
    "critical": 40,
    "warning": 12,
    "info": 0,
    "ok": 0,
}

STRENGTH_LABEL = {
    "proven": "Proven",
    "measured": "Measured",
    "circumstantial": "Circumstantial",
}


# Values a partition uses in place of the real model when it carries a generic
# image shared across several devices.
#
# This exists to avoid the most expensive mistake this engine can make. A
# genuine Pixel 8 straight from the factory declares model = "Generic System"
# in the system partition while vendor, odm and product say "Pixel 8": that is
# the separation Project Treble intends, where one system image serves several
# models and therefore cannot carry any one model's name. Comparing that
# placeholder against the real model reproduces exactly the counterfeit
# pattern -- system says one thing, vendor another -- on a perfectly
# authentic phone.
GENERIC_IDENTITY_VALUES = {
    "generic", "generic system", "generic_system", "generic system image",
    "gsi", "aosp", "mainline", "qssi", "android", "unknown", "n/a",
    "not set", "placeholder", "generic_system_google", "msmnile", "lahaina",
}


def _is_placeholder(value: str) -> bool:
    text = str(value).strip().lower()
    if not text:
        return True
    if text in GENERIC_IDENTITY_VALUES:
        return True
    # Covers variants such as "generic_system_arm64" or "aosp_shiba", which
    # change from build to build but always start the same way.
    return text.startswith(("generic", "aosp_", "gsi_", "qssi"))


def _version_key(release: str) -> tuple:
    """Order Android versions numerically. Without this "9" sorts above "13"."""
    parts = []
    for chunk in re.split(r"[._]", str(release)):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts) or (0,)


@dataclass
class Finding:
    severity: str                  # critical | warning | info | ok
    category: str                  # identity | integrity | components | ...
    title: str
    detail: str
    strength: str = "measured"     # proven | measured | circumstantial
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "detail": self.detail,
            "strength": self.strength,
            "strength_label": STRENGTH_LABEL.get(self.strength, self.strength),
            "evidence": self.evidence,
        }


class AuthenticityEngine:
    def __init__(self, snapshot: dict[str, Any], specdb=None):
        self.s = snapshot
        self.specdb = specdb
        self.findings: list[Finding] = []

    # ------------------------------------------------------------------ API

    def run(self) -> dict[str, Any]:
        self.findings = []

        self._check_attestation()
        self._check_partition_identity()
        self._check_fingerprint_coherence()
        self._check_model_vs_fingerprint()
        self._check_soc_coherence()
        self._check_verified_boot()
        self._check_build_signing()
        self._check_root()
        self._check_knox()
        self._check_serial_coherence()
        self._check_expected_specs()
        self._check_battery()
        self._check_storage_wear()
        self._check_security_patch()
        self._check_google_services()
        self._check_sensor_inventory()
        self._check_components()
        self._check_history()

        return self._report()

    # ------------------------------------------------------------- helpers

    def add(self, severity: str, category: str, title: str, detail: str,
            strength: str = "measured", **evidence) -> None:
        self.findings.append(Finding(
            severity=severity, category=category, title=title,
            detail=detail, strength=strength, evidence=evidence,
        ))

    def get(self, *path, default=None):
        """Tolerant nested access: any collector may have failed."""
        node: Any = self.s
        for key in path:
            if not isinstance(node, dict):
                return default
            node = node.get(key)
            if node is None:
                return default
        return node

    # --------------------------------------------------------------- rules

    def _check_attestation(self) -> None:
        """Compare what the software claims against what the TEE signs.

        System properties are editable text. Attestation fields are signed by
        a key burned into the chip at the factory and not extractable. When
        the two contradict each other the conclusion is firm: the software was
        rewritten to say something the hardware does not confirm.

        The converse is worth much less, and the report says so: without
        verifying the root of the chain, an entirely fabricated chain would be
        indistinguishable. But whoever fabricates a chain does it to confirm
        the counterfeit, not to expose it -- the evidential value lies in the
        disagreement.
        """
        att = self.get("attestation", default={}) or {}

        if not att.get("available"):
            reason = att.get("error") or "no reason reported"
            self.add(
                "info", "integrity",
                "Hardware attestation not obtained",
                "The secure environment could not be made to issue a certificate "
                "confirming the device identity. The strongest available check "
                "therefore goes unused, and the system properties have no "
                f"independent corroboration. Cause: {reason}",
                strength="circumstantial", detail_error=reason,
                attempts=att.get("attempts", []))
            return

        mode = att.get("security_mode") or att.get("security_level") or ""
        level = att.get("security_level", "")
        label = att.get("security_label", "")

        if level == "software":
            self.add(
                "warning", "integrity",
                "Software-only attestation",
                "The certificate was issued by the operating system rather than "
                "the secure environment: no hardware key backs it, so the "
                "document is worth exactly as much as the system properties it "
                "is supposed to confirm. This happens on emulators and on "
                "devices without Google certification.",
                strength="proven", security_level=level, label=label)
        else:
            self.add(
                "ok", "integrity",
                f"Attestation issued by the secure environment ({mode})",
                f"{label}. The key signing the certificate resides in hardware "
                "and is not readable by software, not even with root.",
                strength="proven", security_level=level, mode=mode,
                attestation_version=att.get("attestation_version"))

        # The challenge binds the certificate to this session.
        if att.get("challenge_matches") is False:
            self.add(
                "critical", "integrity",
                "The attestation certificate does not answer the request",
                "The device was asked to sign a random value generated for this "
                "session, and the certificate contains a different one. A "
                "certificate that does not answer the question asked is a replayed "
                "recording: it proves nothing about the device in front of you.",
                strength="proven",
                challenge_received=att.get("challenge_hex"))

        # Attested identity against declared identity.
        attested = att.get("attested_identity") or {}
        effective = self.get("system", "partitions", "effective", default={}) or {}

        comparable = {
            "brand": "brand",
            "manufacturer": "manufacturer",
            "model": "model",
            "device": "codename",
            "product": "product",
        }

        conflicts: dict[str, dict[str, str]] = {}
        agreements: dict[str, str] = {}
        for key, label_en in comparable.items():
            claimed = str(effective.get(key, "")).strip()
            proven = str(attested.get(key, "")).strip()
            if not claimed or not proven:
                continue
            if claimed.lower() == proven.lower():
                agreements[label_en] = proven
            else:
                conflicts[label_en] = {"declared": claimed, "attested": proven}

        if conflicts:
            rows = "; ".join(
                f"{field_name}: the software says \"{v['declared']}\", "
                f"the hardware signs \"{v['attested']}\""
                for field_name, v in conflicts.items())
            self.add(
                "critical", "identity",
                "The secure environment contradicts the declared identity",
                "The certificate signed by the chip reports an identity different "
                f"from the one written in the system properties. {rows}. On a "
                "genuine device the two agree by construction: they are written "
                "together at the factory and the second cannot be changed by "
                "software.",
                strength="proven", conflicts=conflicts)
        elif agreements:
            fields = ", ".join(f"{k} = {v}" for k, v in agreements.items())
            self.add(
                "ok", "identity",
                "Identity confirmed by the secure environment",
                f"The certificate signed by the chip agrees with the system "
                f"properties on {len(agreements)} fields: {fields}. Note the "
                "limits of this confirmation: the root of the chain has not been "
                "verified (see \"Attestation root\" below), so the match "
                "rules out trivial rebranding, not every form of tampering.",
                strength="measured", fields=agreements)
        else:
            self.add(
                "info", "identity",
                "Identity not among the attested fields",
                "The certificate is valid but does not carry brand, model and "
                "codename: attesting device identifiers is an optional feature "
                "many manufacturers do not enable. It remains fully usable for "
                "verified boot state and patch levels, but the identity "
                "comparison has to rest on the other checks.",
                strength="circumstantial")

        # Boot state according to the TEE.
        rot = att.get("root_of_trust") or {}
        state = rot.get("verified_boot_state")
        locked = rot.get("device_locked")

        if state and state != "verified":
            self.add(
                "critical" if state in ("unverified", "failed") else "warning",
                "integrity",
                "Verified boot is not intact, according to the hardware",
                f"{rot.get('verified_boot_label', state)}. This judgement does not "
                "come from a system property but from the secure environment, "
                "which signs it: it is the unforgeable version of the same "
                "information.",
                strength="proven", state=state,
                boot_key=rot.get("verified_boot_key_sha256"))
        elif state == "verified":
            self.add(
                "ok", "integrity",
                "Verified boot confirmed by the hardware",
                "The secure environment certifies that the boot chain is intact "
                "and signed with the manufacturer key.",
                strength="proven",
                boot_key=rot.get("verified_boot_key_sha256"))

        if locked is False:
            self.add(
                "critical", "integrity",
                "Bootloader unlocked, according to the hardware",
                "The certificate attests that the bootloader is unlocked. With an "
                "unlocked bootloader any partition can be replaced, and none of "
                "the software checks can be considered reliable any more.",
                strength="proven")

        # Patch level comparison.
        declared_patch = str(self.get("system", "os", "security_patch", default="") or "")
        attested_patch = str(att.get("os_patch_level", "") or "")
        if declared_patch and attested_patch:
            # Attestation reports year and month; the property also has the day.
            if declared_patch[:7] != attested_patch[:7]:
                self.add(
                    "warning", "integrity",
                    "Patch level disagrees between software and hardware",
                    f"The properties declare security patch {declared_patch}, the "
                    f"secure environment attests {attested_patch}. This can "
                    "indicate a partial update, or a version declared more recent "
                    "than the one actually installed.",
                    strength="proven", declared=declared_patch,
                    attested=attested_patch)

        # Hardware-signed identifiers.
        attested_ids = att.get("attested_ids") or {}
        if attested_ids:
            listing = ", ".join(f"{k}: {v}" for k, v in attested_ids.items())
            self.add(
                "ok", "identity",
                "Identifiers signed by the secure environment",
                f"The certificate includes hardware-attested identifiers "
                f"({listing}). This is the strongest form in which they can be "
                "obtained: they do not pass through the operating system.",
                strength="proven", identifiers=attested_ids)

            declared_serial = str(
                self.get("identity", "serials", "primary", default="") or "")
            attested_serial = str(attested_ids.get("serial", "") or "")
            if declared_serial and attested_serial and \
                    declared_serial.lower() != attested_serial.lower():
                self.add(
                    "critical", "identity",
                    "Serial number contradicted by the hardware",
                    f"The system declares serial number \"{declared_serial}\", "
                    f"the secure environment signs a different one: "
                    f"\"{attested_serial}\".",
                    strength="proven", declared=declared_serial,
                    attested=attested_serial)

        # Root of the chain, and whether the chain leading to it holds.
        chain = att.get("chain") or {}
        fingerprint = att.get("root_public_key_sha256", "")
        if chain.get("checked") and chain.get("signatures_valid") is False:
            self.add(
                "critical", "integrity",
                "Attestation chain does not verify",
                "At least one certificate in the attestation chain is not signed by "
                "the next one. A genuine secure environment cannot produce such a "
                "chain: it was assembled or altered, and the attested fields above "
                "cannot be trusted.",
                strength="proven", broken_at=chain.get("broken_at"))
        elif att.get("root_known") is True:
            self.add(
                "ok", "integrity",
                "Attestation chain signed by Google",
                "Every signature in the chain verifies, up to one of Google's "
                "hardware attestation roots. The attested fields come from a "
                "secure environment Google certified, not from software.",
                strength="proven", fingerprint=fingerprint)
        elif att.get("root_known") is False:
            self.add(
                "warning", "integrity",
                "Attestation root is not Google's",
                "The chain's signatures hold, but it ends on a root that is not one "
                "of Google's attestation roots. Certified Android devices chain to "
                "Google; a manufacturer's own root is possible on uncertified or "
                "older devices, a purpose-built one on a counterfeit.",
                strength="measured", fingerprint=fingerprint,
                subject=att.get("root_subject"))
        else:
            self.add(
                "info", "integrity",
                "Attestation root not verified",
                "Google's attestation roots are not available to this installation "
                "(data/attestation_roots.pem), so the chain was not checked. The "
                "attested fields remain useful as corroboration, but on their own "
                f"they do not prove authenticity. Observed fingerprint: {fingerprint}.",
                strength="circumstantial", fingerprint=fingerprint,
                subject=att.get("root_subject"))

        for entry in chain.get("revoked") or []:
            self.add(
                "warning", "integrity",
                "Attestation key revoked by Google",
                f"Certificate {entry['position'] + 1} of the chain (serial "
                f"{entry['serial']}) is on Google's revocation list "
                f"({entry.get('reason') or entry.get('status')}, list of "
                f"{chain.get('revocation_list_date') or 'unknown date'}). Leaked "
                "attestation keys are what spoofing tools use to pass integrity "
                "checks on modified phones.",
                strength="proven", **entry)

    def _check_partition_identity(self) -> None:
        """The five partitions must declare the same identity."""
        by_part = self.get("system", "partitions", "by_partition", default={}) or {}
        if len(by_part) < 2:
            self.add("info", "identity",
                     "Per-partition identity not available",
                     "The device exposes product properties for a single partition. "
                     "This is normal on Android 9 and earlier, where the "
                     "per-partition split does not yet exist.",
                     strength="proven", partitions=by_part)
            return

        # Only brand, manufacturer and model are declarations of commercial
        # identity, and on an official build they always agree.
        #
        # `device` and `name` diverge constantly on legitimate devices: many
        # manufacturers ship a generic system image shared across models, which
        # carries a codename of its own (for example "qssi", Qualcomm Single
        # System Image), while vendor and odm keep the real board name.
        # Comparing those would raise a counterfeit alarm on any recent
        # Qualcomm phone.
        IDENTITY_FIELDS = ("brand", "manufacturer", "model")
        CODENAME_FIELDS = ("device", "name")

        conflicts: dict[str, dict[str, str]] = {}
        placeholders: dict[str, dict[str, str]] = {}
        for field_name in IDENTITY_FIELDS:
            values = {
                part: entry[field_name]
                for part, entry in by_part.items()
                if entry.get(field_name)
            }
            real = {p: v for p, v in values.items() if not _is_placeholder(v)}
            generic = {p: v for p, v in values.items() if _is_placeholder(v)}
            if generic:
                placeholders[field_name] = generic

            distinct = {v.strip().lower() for v in real.values()}
            if len(distinct) > 1:
                conflicts[field_name] = real

        codename_variants: dict[str, dict[str, str]] = {}
        for field_name in CODENAME_FIELDS:
            values = {
                part: entry[field_name]
                for part, entry in by_part.items()
                if entry.get(field_name)
            }
            if len({v.strip().lower() for v in values.values()}) > 1:
                codename_variants[field_name] = values

        if placeholders and not conflicts:
            rows = "; ".join(
                f"{field_name}: " + ", ".join(f"{p} declares \"{v}\""
                                              for p, v in vals.items())
                for field_name, vals in placeholders.items())
            self.add(
                "info", "identity",
                "System partition with generic identity (normal)",
                "The system partition does not declare the real model but a "
                f"placeholder: {rows}. This is the behaviour Project Treble "
                "intends, separating the operating system from the device: one "
                "system image serves several models, so it cannot carry any one "
                "model's name. The real identity stays in vendor, odm and "
                "product, which agree with each other here.",
                strength="proven", placeholders=placeholders)

        if conflicts:
            lines = []
            for field_name, values in conflicts.items():
                rendered = ", ".join(f"{p} declares \"{v}\""
                                     for p, v in values.items())
                lines.append(f"Field {field_name}: {rendered}.")
            self.add(
                "critical", "identity",
                "The partitions declare different identities",
                "On a genuine phone the system, vendor, odm and product partitions "
                "all come from the same build and declare the same brand and "
                "model. Here they do not. "
                + " ".join(lines) +
                " Whoever rebrands a device normally changes only the system "
                "values, which are the ones shown in settings and read by apps, "
                "and leaves vendor and odm with the real manufacturer's data. "
                "This is the typical signature of counterfeiting.",
                strength="proven", conflicts=conflicts,
            )
        else:
            self.add(
                "ok", "identity",
                "Identity consistent across all partitions",
                f"The {len(by_part)} partitions declaring a product identity ("
                + ", ".join(sorted(by_part)) + ") report the same brand, "
                "manufacturer and model.",
                strength="proven", partitions=by_part,
            )

        if codename_variants:
            rendered = "; ".join(
                f"{field_name}: " + ", ".join(f"{p} → \"{v}\""
                                              for p, v in values.items())
                for field_name, values in codename_variants.items()
            )
            self.add(
                "info", "identity",
                "Different codenames across partitions (normal)",
                "The partitions use different codenames — " + rendered +
                ". This is not an anomaly: the system image is often shared "
                "across several models from the same manufacturer and carries a "
                "generic name (for example \"qssi\", Qualcomm's single "
                "system image), while vendor and odm keep the real board name. "
                "Brand, manufacturer and model, the fields that actually define "
                "identity, agree.",
                strength="proven", codenames=codename_variants,
            )

    @staticmethod
    def _parse_fingerprint(fp: str) -> dict[str, str]:
        """Split a fingerprint into its fields.

        The format is:
            brand/product/device:release/build-id/incremental:type/tags

        Not every field is present on every build, so parsing is tolerant and
        returns only what it can recognise.
        """
        out: dict[str, str] = {}
        fp = (fp or "").strip()
        if not fp:
            return out

        head, _, tail = fp.partition(":")
        parts = head.split("/")
        if parts:
            out["brand"] = parts[0]
        if len(parts) > 1:
            out["product"] = parts[1]
        if len(parts) > 2:
            out["device"] = parts[2]

        if tail:
            segments = tail.split("/")
            if segments:
                out["release"] = segments[0]
            if len(segments) > 1:
                out["build_id"] = segments[1]
            if len(segments) > 2:
                # The incremental is followed by ":type", which must be split off.
                out["incremental"] = segments[2].split(":")[0]
            if ":" in tail:
                trailer = tail.rsplit(":", 1)[-1]
                bits = trailer.split("/")
                if bits:
                    out["type"] = bits[0]
                if len(bits) > 1:
                    out["tags"] = bits[1]
        return out

    def _check_fingerprint_coherence(self) -> None:
        """Check fingerprint consistency across partitions.

        Be careful what gets compared. Comparing whole strings raises false
        alarms on every Treble device that has taken a major Android upgrade:
        system moves to the new release while vendor and odm stay on the one
        the phone shipped with, which is exactly the intended behaviour. The
        device name varies legitimately too, because the shared system image
        uses a generic name.

        What must agree on an official build is:
          - the brand, which identifies the manufacturer;
          - the incremental build number, which identifies the exact release
            all images came from;
          - the build type and signing tags.

        These three expose a firmware assembled from mismatched pieces without
        penalising a legitimate upgrade.

        The brand comparison must skip placeholders. A stock Pixel ships a
        system fingerprint of the form `Android/generic_system/generic:...`
        while every other partition says `google`. Treating "Android" as a
        declared brand reported a genuine Pixel 8 as critically counterfeit.
        """
        fps = self.get("system", "fingerprints", default={}) or {}
        if len(fps) < 2:
            return

        parsed = {name: self._parse_fingerprint(fp)
                  for name, fp in fps.items() if fp.strip()}
        if len(parsed) < 2:
            return

        def field_values(key: str) -> dict[str, str]:
            return {name: p[key] for name, p in parsed.items() if p.get(key)}

        all_brands = field_values("brand")
        brands = {k: v for k, v in all_brands.items() if not _is_placeholder(v)}
        generic_brands = {k: v for k, v in all_brands.items() if _is_placeholder(v)}
        incrementals = field_values("incremental")
        tags = field_values("tags")

        distinct_brands = {v.lower() for v in brands.values()}
        distinct_incr = set(incrementals.values())
        distinct_tags = {v.lower() for v in tags.values()}

        if len(distinct_brands) > 1:
            self.add(
                "critical", "identity",
                "Different brands in the partition fingerprints",
                "The partitions declare that they come from different "
                "manufacturers: "
                + ", ".join(f"{k} → \"{v}\"" for k, v in brands.items())
                + ". On an authentic device every image comes off a single "
                "manufacturer's build line. This is the signature of a firmware "
                "assembled from pieces of different origin.",
                strength="proven", fingerprints=fps,
            )
        elif len(distinct_incr) > 1:
            self.add(
                "critical", "identity",
                "Different incremental build numbers across partitions",
                "The partitions come from different releases: "
                + ", ".join(f"{k} → \"{v}\""
                            for k, v in incrementals.items())
                + ". The incremental number identifies the single official build "
                "all images come from. Different values indicate a recomposed "
                "firmware, not a version released by the manufacturer.",
                strength="proven", fingerprints=fps,
            )
        elif len(distinct_tags) > 1:
            self.add(
                "critical", "identity",
                "Different signing keys across partitions",
                "The partitions are signed with different keys: "
                + ", ".join(f"{k} → \"{v}\"" for k, v in tags.items())
                + ". At least one image is not signed by the manufacturer.",
                strength="proven", fingerprints=fps,
            )
        else:
            releases = field_values("release")
            distinct_releases = set(releases.values())
            incremental = next(iter(distinct_incr), "n/a")

            if generic_brands:
                self.add(
                    "info", "identity",
                    "Generic brand in the system fingerprint (normal)",
                    "The fingerprint of "
                    + ", ".join(f"{k} (\"{v}\")"
                                for k, v in generic_brands.items())
                    + " carries a generic brand instead of the manufacturer's. "
                    "This is how a shared Treble system image identifies itself "
                    "and is the factory state on stock Pixel firmware. The brand "
                    "comparison was made on the remaining partitions, which "
                    "agree.",
                    strength="proven", generic=generic_brands, real=brands,
                )

            if len(distinct_releases) > 1:
                newest = max(distinct_releases, key=_version_key)
                oldest = min(distinct_releases, key=_version_key)
                self.add(
                    "info", "identity",
                    "Partitions on different Android releases (normal)",
                    f"The system images are on Android {newest} while vendor and "
                    f"odm have stayed on Android {oldest}. This is how Project "
                    "Treble is meant to work: a major upgrade replaces the system "
                    "partition and leaves the vendor partition, which holds the "
                    "drivers, at the factory version. That they belong to the same "
                    f"official release is confirmed by build number "
                    f"\"{incremental}\", identical on every partition.",
                    strength="proven", fingerprints=fps,
                    releases=releases, incremental=incremental,
                )
            else:
                self.add(
                    "ok", "identity",
                    "Build fingerprints consistent",
                    "Brand, build number and signing keys agree across all "
                    f"partitions (build \"{incremental}\").",
                    strength="proven", fingerprints=fps,
                )

    def _check_model_vs_fingerprint(self) -> None:
        """The fingerprint carries brand and product name: they must match.

        If the declared model belongs to one manufacturer and the fingerprint
        to another, the contradiction is internal to the device and needs no
        external catalogue to detect.
        """
        fp = self.get("system", "build", "fingerprint", default="") or ""
        brand = (self.get("system", "partitions", "effective", "brand", default="") or "")
        model = (self.get("system", "partitions", "effective", "model", default="") or "")
        if not fp or "/" not in fp or not brand:
            return

        fp_brand = fp.split("/", 1)[0].strip().lower()
        # A generic brand in the fingerprint is a Treble placeholder, not a
        # contradiction.
        if _is_placeholder(fp_brand):
            return
        if fp_brand and brand.strip().lower() != fp_brand:
            self.add(
                "critical", "identity",
                "The fingerprint belongs to a different brand than the model",
                f"The device declares itself \"{brand} {model}\", but the "
                f"build fingerprint starts with \"{fp_brand}\". The "
                "fingerprint is generated by the manufacturer's build system and "
                "is consistent by construction: a mismatch indicates the brand and "
                "model properties were rewritten after compilation.",
                strength="proven", fingerprint=fp, declared_brand=brand,
            )

    def _check_soc_coherence(self) -> None:
        """The declared chip must be compatible with the real cores."""
        soc = self.get("system", "soc", default={}) or {}
        declared = (soc.get("declared_manufacturer") or "").strip()
        core_types = soc.get("core_types") or []
        hardware_line = (soc.get("hardware_line") or "").strip()
        platform = (soc.get("platform") or "").strip()

        if not core_types:
            return

        implementers = {c.get("implementer", "") for c in core_types}
        micro = ", ".join(
            f"{c['count']}x {c['microarchitecture']}" for c in core_types
        )

        # A strong, catalogue-free signal: the declared platform and the
        # kernel's Hardware line belong to different families.
        families = {
            "qualcomm": ("qcom", "msm", "sdm", "sm[0-9]", "kona", "lahaina",
                         "taro", "kalama", "pineapple", "snapdragon"),
            "mediatek": ("mt[0-9]{4}", "mediatek", "dimensity"),
            "exynos": ("exynos", "universal", "s5e[0-9]"),
            "google": ("gs[0-9]{3}", "tensor", "zuma", "gs201"),
            "unisoc": ("unisoc", "sc[0-9]{4}", "spreadtrum"),
            "kirin": ("kirin", "hi[0-9]{4}"),
        }

        def family_of(text: str) -> set[str]:
            low = text.lower()
            return {
                name for name, patterns in families.items()
                if any(re.search(p, low) for p in patterns)
            }

        declared_fams = family_of(f"{declared} {soc.get('declared_model', '')} {platform}")
        kernel_fams = family_of(f"{hardware_line} {soc.get('hardware', '')}")

        if declared_fams and kernel_fams and not (declared_fams & kernel_fams):
            self.add(
                "critical", "identity",
                "The declared chip does not match the one the kernel recognises",
                f"The system properties indicate a SoC of the "
                f"{'/'.join(sorted(declared_fams))} family (declared: "
                f"\"{declared} {soc.get('declared_model', '')}\", platform "
                f"\"{platform}\"), while the kernel identifies hardware of "
                f"the {'/'.join(sorted(kernel_fams))} family "
                f"(\"{hardware_line}\"). The Hardware line is written by "
                "the kernel from the processor registers: it is far harder to "
                "forge than a system property. A family mismatch indicates a "
                "device with a chip other than the one declared.",
                strength="proven",
                declared=declared, platform=platform, kernel=hardware_line,
            )
        else:
            # Modern arm64 kernels (Tensor among them) dropped the Hardware
            # line from /proc/cpuinfo, so its absence is normal and must not
            # read as a gap in the evidence.
            kernel_note = (
                f"kernel hardware line: \"{hardware_line}\""
                if hardware_line else
                "the kernel publishes no Hardware line in /proc/cpuinfo, which is "
                "normal on recent arm64 kernels"
            )
            self.add(
                "ok", "identity",
                "Core configuration consistent",
                f"The processor exposes {micro}, with implementer "
                f"{', '.join(sorted(i for i in implementers if i))}. "
                f"Declared platform: \"{platform or 'n/a'}\", {kernel_note}.",
                strength="measured", core_types=core_types,
            )

    def _check_verified_boot(self) -> None:
        vb = self.get("security", "verified_boot", default={}) or {}
        bl = self.get("security", "bootloader", default={}) or {}
        state = vb.get("state", "n/a")

        if vb.get("trusted"):
            self.add(
                "ok", "integrity",
                "Verified boot intact",
                vb.get("explanation", ""),
                strength="proven", state=state, locked=bl.get("locked"),
            )
        elif not vb.get("known"):
            self.add(
                "warning", "integrity",
                "Verified boot state not readable",
                vb.get("explanation", ""),
                strength="proven", state=state,
            )
        else:
            self.add(
                "critical", "integrity",
                f"Verified boot: {vb.get('label')}",
                vb.get("explanation", "") +
                " Consequently every value read from the system in this report, "
                "IMEI and specifications included, must be treated as declared by "
                "the installed software rather than verified by the hardware.",
                strength="proven", state=state, locked=bl.get("locked"),
            )

    def _check_build_signing(self) -> None:
        bs = self.get("security", "build_signing", default={}) or {}
        if not bs:
            return

        # If the two properties were not read, conclude nothing. This is the
        # engine's general principle, but here it cost a real false positive:
        # a line truncated by a `head` produced an empty build type, and a
        # perfectly genuine device -- locked bootloader, verified boot, Knox
        # fuse intact -- was declared compromised.
        if not bs.get("readable", bool(bs.get("type") and bs.get("tags"))):
            self.add(
                "info", "integrity",
                "Build signing not readable",
                "The properties indicating build type and signing keys were not "
                "read. The check did not run: nothing is inferred from it, in "
                "either direction.",
                strength="proven", **bs)
            return

        if bs.get("official"):
            self.add(
                "ok", "integrity",
                "Official production build",
                f"The build is of type \"{bs.get('type')}\" signed with "
                f"\"{bs.get('tags')}\": a version intended for the public, "
                "signed by the manufacturer.",
                strength="proven", **bs,
            )
        else:
            self.add(
                "critical", "integrity",
                "Unofficial build",
                f"The build is of type \"{bs.get('type') or 'n/a'}\" with "
                f"tags \"{bs.get('tags') or 'n/a'}\". A version intended "
                "for the public is always \"user\" + "
                "\"release-keys\". Different values indicate a custom ROM, "
                "an internal development build, or a firmware rebuilt by a third "
                "party: in every case the system properties may have been set at "
                "will."
                + (" The debuggable flag is also set, which never happens on "
                   "production firmware." if bs.get("debuggable") else ""),
                strength="proven", **bs,
            )

    def _check_root(self) -> None:
        root = self.get("security", "root", default={}) or {}
        if not root:
            return
        if root.get("detected"):
            parts = []
            if root.get("su_binaries"):
                parts.append("su binary present in " + ", ".join(root["su_binaries"]))
            if root.get("packages"):
                parts.append("root management apps installed: "
                             + ", ".join(root["packages"]))
            if root.get("root_shell"):
                parts.append("the adb shell itself runs as root (uid 0)")
            self.add(
                "critical", "integrity",
                "Device with root privileges",
                "Traces of administrative access were found: "
                + "; ".join(parts) + ". With root privileges any value read by "
                "this program may have been altered in memory, including IMEI, "
                "model and verified boot state.",
                strength="proven",
                **{k: v for k, v in root.items() if k != "shell_uid"},
            )
        else:
            self.add(
                "ok", "integrity",
                "No traces of root",
                "No su binaries or privilege management applications were found in "
                "the usual locations.",
                strength="circumstantial",
            )
        if root.get("system_writable"):
            self.add(
                "warning", "integrity",
                "System partition writable",
                "The system partition appears mounted read-write. On modern "
                "Android it is always read-only and integrity protected: if it is "
                "writable, the system has been modified.",
                strength="proven",
            )

    def _check_knox(self) -> None:
        knox = self.get("security", "knox")
        if not knox:
            return
        if knox.get("tripped"):
            self.add(
                "critical", "integrity",
                "Knox fuse blown (Samsung)",
                knox.get("explanation", "") +
                " The fuse is physical and does not reset by reflashing the "
                "original firmware: it is permanent proof that the device has run "
                "unofficial software.",
                strength="proven", **knox,
            )
        else:
            self.add(
                "ok", "integrity",
                "Knox fuse intact (Samsung)",
                knox.get("explanation", ""),
                strength="proven", **knox,
            )

    def _check_serial_coherence(self) -> None:
        serials = self.get("identity", "serials", default={}) or {}
        if not serials or serials.get("distinct_count", 0) == 0:
            return
        if not serials.get("consistent"):
            self.add(
                "warning", "identity",
                "Serial numbers disagree",
                "The serial number read from different sources does not match: "
                + ", ".join(f"{k} = \"{v}\""
                            for k, v in serials.get("values", {}).items())
                + ". The sources are independent (system properties, bootloader "
                "command line, USB descriptor) and on an intact device they report "
                "the same value.",
                strength="proven", **serials,
            )
        else:
            self.add(
                "ok", "identity",
                "Serial number consistent",
                f"Serial number \"{serials.get('primary')}\" agrees across "
                "system properties, bootloader and USB descriptor.",
                strength="proven", **serials,
            )

    def _check_expected_specs(self) -> None:
        """Comparison against the catalogue, if the model is known."""
        if not self.specdb:
            return
        model = self.get("system", "partitions", "effective", "model", default="")
        device = self.get("system", "partitions", "effective", "device", default="")
        brand = self.get("system", "partitions", "effective", "brand", default="")

        spec = self.specdb.lookup(brand=brand, model=model, device=device)
        if not spec:
            self.add(
                "info", "specifications",
                "Model not present in the catalogue",
                f"\"{brand} {model}\" (codename \"{device}\") is not "
                "in the local catalogue of expected specifications, so the measured "
                "values cannot be compared against factory ones. Every other check "
                "remains valid: they do not depend on the catalogue.",
                strength="measured", brand=brand, model=model, device=device,
            )
            return

        for issue in self.specdb.compare(spec, self.s):
            self.add(
                issue["severity"], "specifications", issue["title"], issue["detail"],
                strength="measured", **issue.get("evidence", {}),
            )

        until = spec.get("security_updates_until")
        if until:
            today = dt.date.today().strftime("%Y-%m")
            self.s.setdefault("support", {})["security_updates_until"] = until
            if until < today:
                self.add(
                    "info", "specifications", "Security updates have ended",
                    f"{spec['name']} was guaranteed security updates until {until}. "
                    "Updates after that are not promised: known vulnerabilities may "
                    "stay open, which matters for banking and work apps.",
                    strength="measured", until=until,
                )
            else:
                self.add(
                    "ok", "specifications", "Still supported with security updates",
                    f"The manufacturer guarantees security updates for "
                    f"{spec['name']} until at least {until}.",
                    strength="measured", until=until,
                )

    def _check_battery(self) -> None:
        bat = self.get("battery", default={}) or {}
        if not bat:
            return

        cycles = bat.get("cycle_count")
        health = bat.get("health_percent")
        design = bat.get("design_capacity_mah")
        full = bat.get("full_capacity_mah")
        mfg = (bat.get("manufacturing_date") or {}).get("iso")
        first_use = (bat.get("first_usage_date") or {}).get("iso")

        details = []
        if design:
            details.append(f"design capacity {design:.0f} mAh")
        # Without a health figure the full-charge value is the nominal echo
        # (see BatteryCollector._health), not a measurement.
        if full and health is not None:
            details.append(f"measured full-charge capacity {full:.0f} mAh")
        if cycles is not None:
            details.append(f"{cycles} charge cycles")
        if health is not None:
            details.append(f"estimated health {health:.0f}%")

        if health is not None and health < 80:
            self.add(
                "warning", "components",
                "Degraded battery",
                f"The battery holds about {health:.0f}% of its original capacity. "
                "Below 80% it is considered due for replacement: runtime is "
                "noticeably reduced and the phone may shut down early under load.",
                strength="measured", health_percent=health, cycles=cycles,
            )

        # The combination that exposes a replaced cell: few cycles but already
        # degraded, or the other way round.
        if cycles is not None and health is not None:
            if cycles < 50 and health < 90:
                self.add(
                    "warning", "components",
                    "Low cycle count but capacity already reduced",
                    f"The counter reads only {cycles} cycles, yet capacity has "
                    f"already fallen to {health:.0f}%. The two do not go together "
                    "on a new original cell. The usual explanations are: a cell "
                    "replaced with a non-original or shelf-aged one, or a counter "
                    "reset after replacement while the cell is the old one.",
                    strength="measured", cycles=cycles, health_percent=health,
                )
            elif cycles > 500:
                self.add(
                    "warning", "components",
                    "Battery with many cycles",
                    f"The battery has {cycles} full charge cycles. That is a figure "
                    "for a device used for at least a couple of years: "
                    "incompatible with a phone sold as new.",
                    strength="measured", cycles=cycles,
                )

        # Cell manufactured after the phone entered service.
        #
        # The anchor here is deliberately the gauge's own first-usage date and
        # NOT ro.build.date.utc. On any device that has taken an OTA, the build
        # date is the date of the *currently installed* firmware, not of
        # manufacture: comparing a 2023 cell against a 2026 build reported
        # "battery much older than the phone" on an untouched Pixel 8. The two
        # dates come from the same gauge and are directly comparable.
        if mfg and first_use:
            try:
                mfg_d = dt.date.fromisoformat(mfg)
                use_d = dt.date.fromisoformat(first_use)
                delta_days = (mfg_d - use_d).days
                if delta_days > 60:
                    self.add(
                        "warning", "components",
                        "Battery manufactured after the phone entered service",
                        f"The cell reports a manufacturing date of {mfg}, while the "
                        f"gauge records first use on {first_use} — about "
                        f"{delta_days // 30} months earlier. A cell cannot be built "
                        "after the phone it powers started being used: this is a "
                        "replacement.",
                        strength="proven",
                        battery_date=mfg, first_usage_date=first_use,
                    )
                elif delta_days < -1460:
                    self.add(
                        "warning", "components",
                        "Battery much older than its first use",
                        f"The cell is dated {mfg} but was first used on "
                        f"{first_use}, roughly {abs(delta_days) // 365} years "
                        "later. It may be a salvaged or long-shelved cell.",
                        strength="measured", battery_date=mfg,
                        first_usage_date=first_use,
                    )
            except (ValueError, OSError, OverflowError):
                pass

        if health is None and bat.get("health_note"):
            self.add(
                "info", "components",
                "Battery health cannot be measured",
                f"{bat['health_note']} Battery wear cannot be read from software "
                "on this device: judge it with a discharge test or the runtime "
                "the owner reports, not with a percentage.",
                strength="measured",
                design_mah=design, full_mah=full, cycles=cycles,
            )

        if details:
            self.add(
                "ok" if (health is None or health >= 80) else "info",
                "components", "Battery data read from the gauge",
                "The battery measurement chip reports: " + ", ".join(details) +
                (f", cell manufactured on {mfg}" if mfg else "") +
                (f", first used on {first_use}" if first_use else "") + ".",
                strength="measured",
                cycles=cycles, health_percent=health,
                design_mah=design, full_mah=full,
                manufacturing_date=mfg, first_usage_date=first_use,
                part_number=bat.get("part_number"),
                serial_number=bat.get("serial_number"),
            )
        elif bat.get("level_percent") is not None:
            self.add(
                "info", "components",
                "Extended battery data not available",
                "The device exposes neither a cycle counter nor a design capacity "
                "through sysfs. This is common on some models, where those values "
                "stay inside the gauge firmware and are not published to the "
                "operating system. Level, voltage and temperature remain readable.",
                strength="measured",
            )

    def _check_history(self) -> None:
        hist = self.get("history", default={}) or {}
        if not hist:
            return

        accounts = hist.get("accounts") or {}
        if accounts.get("read"):
            google = accounts.get("google") or 0
            if google:
                self.add(
                    "warning", "history",
                    "A Google account is still signed in",
                    f"{google} Google account{'s are' if google > 1 else ' is'} "
                    "signed in. After a factory reset, Factory Reset Protection "
                    "will ask for that account's password before the phone can be "
                    "used. The owner has to remove the account in Settings › "
                    "Accounts first: a reset alone does not lift the lock.",
                    strength="measured", google_accounts=google,
                )
            else:
                self.add(
                    "ok", "history", "No Google account signed in",
                    "No Google account is signed in, so Factory Reset Protection "
                    "will not lock the phone after a reset.",
                    strength="measured",
                )

        made = hist.get("manufactured")
        setup = hist.get("setup_date")
        boots = hist.get("boot_count")
        if made:
            self.add(
                "info", "history", f"Manufactured around {made['iso']}",
                f"The serial number encodes the production month: {made['iso']}. "
                "It dates the device itself, regardless of resets or software "
                "updates.",
                strength="circumstantial", **made,
            )
        if setup or boots is not None:
            parts = []
            if setup:
                when = setup["iso"] + (" (approximate)" if not setup.get("confident") else "")
                parts.append(f"first started on {when}, after its last factory reset")
            if boots is not None:
                parts.append(f"{boots} boots since then")
            self.add(
                "info", "history", "Time in use",
                "The phone was " + ", ".join(parts) + ". A phone sold as new should "
                "show a first start of a few days ago and a handful of boots.",
                strength="measured",
                setup_date=setup.get("iso") if setup else None, boot_count=boots,
            )
            if made and setup and setup["iso"][:7] < made["iso"]:
                self.add(
                    "warning", "history", "First started before it was made",
                    f"The system was first started on {setup['iso']}, before the "
                    f"production month in the serial number ({made['iso']}). One of "
                    "the two has been altered, or the clock was wrong at setup.",
                    strength="circumstantial",
                )

        control = hist.get("control") or {}
        if control.get("financed") or control.get("knox_guard_locked"):
            how = ("Android's Device Lock (financed device)" if control.get("financed")
                   else f"Samsung Knox Guard ({control.get('knox_guard')})")
            self.add(
                "warning", "history", "Under a financing lock",
                f"The phone is enrolled in {how}: whoever financed it can restrict or "
                "lock it remotely until it is paid off, and a factory reset does not "
                "remove the enrolment. Ask for proof the device is paid off.",
                strength="measured", lock=how,
            )
        elif control.get("owners"):
            self.add(
                "warning", "history", "Managed by an organisation",
                "A device or profile owner is set: an organisation's management app "
                "controls the phone and can restrict, wipe or lock it. Owners: "
                + "; ".join(control["owners"]) + ". It has to be released by that "
                "organisation; a reset may re-enrol it automatically.",
                strength="measured", owners=control["owners"],
            )
        elif control.get("read"):
            self.add(
                "ok", "history", "Not managed or financed",
                "No device owner, management profile or financing lock is set.",
                strength="measured",
            )

        log_errors = hist.get("log_errors") or {}
        storage_errors = sum(n for label, n in log_errors.items()
                             if label in ("storage I/O errors", "file system errors",
                                          "storage controller errors"))
        if storage_errors:
            self.add(
                "warning", "history", "Storage errors in the system log",
                f"The recent system log holds {storage_errors} storage error lines "
                f"({', '.join(f'{n} {l}' for l, n in log_errors.items() if 'storage' in l or 'file' in l)}). "
                "On a healthy chip there are none: run the storage test and back up.",
                strength="measured", log_errors=log_errors,
            )
        if log_errors.get("thermal shutdowns"):
            self.add(
                "warning", "history", "Thermal shutdowns",
                "The phone recently shut down to protect itself from overheating: "
                "a degraded battery, a blocked heat path or a faulty sensor.",
                strength="measured", log_errors=log_errors,
            )
        other = {l: n for l, n in log_errors.items()
                 if l not in ("storage I/O errors", "file system errors",
                              "storage controller errors", "thermal shutdowns")}
        if other:
            self.add(
                "info", "history", "Hardware errors in the system log",
                "The recent system log mentions: "
                + ", ".join(f"{n} {label}" for label, n in other.items())
                + ". Isolated entries are common; many of the same kind point at that part.",
                strength="circumstantial", log_errors=other,
            )

        files = hist.get("user_files") or {}
        if files.get("total"):
            where = ", ".join(f"{d} {n}" for d, n in files["by_folder"].items() if n)
            self.add(
                "info", "history", "Personal files still on the phone",
                f"{files['total']} files in shared storage ({where}). Before the phone "
                "changes hands it should be erased with a factory reset; the files "
                "were only counted, not opened.",
                strength="measured", **files,
            )

        crashes = hist.get("crashes") or {}
        counts = crashes.get("counts") or {}
        history = hist.get("boot_history") or []
        abnormal = [b["reason"] for b in history if b.get("abnormal")]
        hard = counts.get("system_server_watchdog", 0)
        if hard >= 3 or len(abnormal) >= 3:
            self.add(
                "warning", "history", "Repeated crashes or forced restarts",
                "The system recorded "
                + ", ".join(f"{n} {crashes['labels'].get(tag, tag)}" for tag, n in counts.items()
                            if tag == "system_server_watchdog")
                + (f"; recent restarts for: {', '.join(abnormal[:5])}" if abnormal else "")
                + ". Kernel panics and watchdog resets that keep coming back point "
                "to faulty memory, a failing board or a bad battery connection.",
                strength="measured", counts=counts, abnormal_boots=abnormal,
            )
        elif crashes.get("available") or history:
            noted = [f"{n} {crashes['labels'].get(tag, tag)}" for tag, n in counts.items()]
            self.add(
                "ok" if not (hard or abnormal) else "info", "history",
                "Crash history",
                ("Recorded since " + crashes["since"] + ": " if crashes.get("since") else "Recorded: ")
                + (", ".join(noted) if noted else "no crashes of note")
                + (f". Abnormal restarts: {', '.join(abnormal)}." if abnormal else ".")
                + " Occasional app crashes are normal; repeated kernel panics are not.",
                strength="measured", counts=counts, abnormal_boots=abnormal,
            )

    def _check_storage_wear(self) -> None:
        stor = self.get("storage", default={}) or {}
        health = stor.get("ufs_health") or {}
        if not health:
            return

        if health.get("available") is False and health.get("note"):
            self.add(
                "info", "components",
                "Storage wear not readable",
                health["note"],
                strength="proven",
                unreadable_fields=health.get("unreadable_fields", []),
            )
            return

        for label, key in (("SLC blocks", "life_time_a"),
                           ("MLC/TLC blocks", "life_time_b")):
            est = health.get(key)
            if not est or est.get("used_percent_max") is None:
                continue
            used = est["used_percent_max"]
            if used >= 80:
                self.add(
                    "warning", "components",
                    f"Internal storage heavily worn ({label})",
                    f"The UFS health descriptor indicates the {label} have "
                    f"consumed about {est['used_percent_range']} of their "
                    "estimated useful life. That is a level for a device used "
                    "intensively for years, incompatible with a new phone.",
                    strength="measured", indicator=key, **est,
                )
            elif used >= 20:
                self.add(
                    "info", "components",
                    f"Internal storage wear ({label})",
                    f"Useful life consumed: about {est['used_percent_range']}. "
                    "This is consistent with normal use.",
                    strength="measured", indicator=key, **est,
                )

        if health.get("eol_code") and health["eol_code"] >= 2:
            self.add(
                "critical" if health["eol_code"] >= 3 else "warning",
                "components", "Internal storage near end of life",
                f"The storage end-of-life status is: "
                f"{health.get('eol_description')}. The reserve blocks used to "
                "replace failed ones are running out; when they are gone the "
                "storage becomes read-only and the phone unusable.",
                strength="measured", eol=health.get("eol_code"),
            )

    def _check_security_patch(self) -> None:
        patch = self.get("system", "os", "security_patch", default="")
        if not patch:
            return
        try:
            patch_date = dt.date.fromisoformat(patch)
        except ValueError:
            return
        today = dt.date.today()
        months = (today.year - patch_date.year) * 12 + (today.month - patch_date.month)

        if months > 24:
            sev, desc = "warning", "very far behind"
        elif months > 12:
            sev, desc = "warning", "behind"
        elif months > 6:
            sev, desc = "info", "slightly behind"
        else:
            sev, desc = "ok", "up to date"

        self.add(
            sev, "integrity", f"Security level {desc}",
            f"The last security patch applied is dated {patch}, about "
            f"{months} months ago." + (
                " A device this far behind has known uncorrected "
                "vulnerabilities. On a phone sold as new, a very old patch "
                "indicates the firmware is not the current one, which happens "
                "with units left in storage, with firmware reinstalled by third "
                "parties, or with clones."
                if months > 12 else ""
            ),
            strength="measured", security_patch=patch, months_behind=months,
        )

    def _check_google_services(self) -> None:
        pkg = self.get("packages", default={}) or {}
        if not pkg:
            return
        brand = (self.get("system", "partitions", "effective", "brand",
                          default="") or "").lower()
        # Only brands that always ship Google-certified outside China.
        expects_gms = any(b in brand for b in ("google", "samsung", "motorola",
                                               "nokia", "sony", "oneplus", "oppo"))
        if pkg.get("has_play_services") and pkg.get("has_play_store"):
            self.add(
                "ok", "integrity", "Google services present",
                "Play Services and Play Store are installed"
                + (f" (GMS version {pkg['gms_version']})"
                   if pkg.get("gms_version") else "")
                + ". This is a requirement of Google certification, which clones "
                "rarely pass.",
                strength="circumstantial",
            )
        elif not pkg.get("system_count") and not pkg.get("third_party_count"):
            # The package list was not read at all (no system packages either).
            # An empty list does not imply Google services are missing --
            # often the GMS version was read from another source.
            self.add(
                "info", "integrity", "Application list not readable",
                "The system refused to enumerate the installed packages, so the "
                "presence of Google services was not verified this way."
                + (f" Another source still reports GMS version "
                   f"{pkg['gms_version']}, which indicates they are present."
                   if pkg.get("gms_version") else ""),
                strength="proven",
                gms_version=pkg.get("gms_version"),
            )
        elif expects_gms:
            self.add(
                "warning", "integrity", "Google services absent or incomplete",
                f"A \"{brand}\" device intended for the European market "
                "always ships with certified Google services. Their absence "
                "indicates an unofficial ROM, a model intended for the Chinese "
                "market, or an uncertified device.",
                strength="circumstantial",
                play_services=pkg.get("has_play_services"),
                play_store=pkg.get("has_play_store"),
            )

        if pkg.get("suspicious_packages"):
            self.add(
                "warning", "integrity", "Tampering applications installed",
                "Applications known to modify system behaviour or mask device "
                "state are present: " + ", ".join(pkg["suspicious_packages"]) +
                ". In their presence the collected data should be treated with "
                "caution.",
                strength="proven", packages=pkg["suspicious_packages"],
            )

    def _check_sensor_inventory(self) -> None:
        sens = self.get("sensors", default={}) or {}
        has = sens.get("has") or {}
        if not sens.get("count"):
            return

        # A mid-range or flagship phone always has at least these.
        essential = {
            "accelerometer": "accelerometer",
            "gyroscope": "gyroscope",
            "magnetic_field": "magnetometer",
            "light": "ambient light sensor",
            "proximity": "proximity sensor",
        }
        missing = [label for key, label in essential.items() if not has.get(key)]

        if missing:
            self.add(
                "warning", "components", "Basic sensors missing",
                "Not present: " + ", ".join(missing) + ". Mid-range and flagship "
                "phones fit all of them. A missing gyroscope in particular is a "
                "classic clone signature, because it is an expensive component "
                "that gets omitted while the declared specifications still list it.",
                strength="measured", missing=missing,
            )
        else:
            self.add(
                "ok", "components", "All basic sensors present",
                f"The device exposes {sens['count']} sensors, including "
                "accelerometer, gyroscope, magnetometer, ambient light and "
                "proximity. Declared vendors: "
                + ", ".join(sens.get("vendors", [])[:6]) + ".",
                strength="measured", count=sens["count"],
            )

    def _check_components(self) -> None:
        """Signs that individual modules were replaced.

        None of these checks can say "this part is original": there is no
        public registry linking a serial number to the camera module it left
        the factory with. What can be said is whether the *device itself*
        recognises the part fitted to it, and that is a question the driver
        answers.
        """
        comp = self.get("components", default={}) or {}
        if not comp:
            return

        # Cameras.
        cameras = comp.get("cameras") or []
        mismatched = [c for c in cameras if c.get("firmware_matches") is False]
        if mismatched:
            listing = ", ".join(
                f"{c['position']} ({c.get('sensor') or 'unknown sensor'})"
                for c in mismatched)
            self.add(
                "warning", "components",
                "Camera firmware mismatch",
                f"The driver reports that the firmware loaded on {listing} is not "
                "what this build expects. This happens when a module is replaced "
                "with one from another unit or from a different market variant. "
                "It is not proof of counterfeiting, but it is the typical trace "
                "of a repair with non-original parts.",
                strength="measured", modules=mismatched)
        elif cameras:
            confirmed = [c for c in cameras if c.get("firmware_matches") is True]
            if confirmed:
                self.add(
                    "ok", "components",
                    f"Camera modules recognised by the firmware ({len(confirmed)})",
                    "For each lens the driver confirms the loaded firmware is the "
                    "one the factory build expects.",
                    strength="measured", modules=confirmed)

        identified = [c for c in cameras if c.get("module_id")]
        if identified:
            self.add(
                "info", "components",
                "Camera module codes detected",
                "Each module exposes a code identifying its supplier and "
                "production batch. There is no public registry to compare it "
                "against, but it is the value that allows checking whether two "
                "units of the same model carry the same part, and it stays on "
                "record for any future comparison.",
                strength="circumstantial",
                modules={c["position"]: c["module_id"] for c in identified})

        # Digitizer.
        touch = comp.get("touch") or {}
        if touch.get("firmware_matches") is False:
            self.add(
                "warning", "components",
                "Touch firmware differs from the expected version",
                f"The digitizer controller runs version "
                f"{touch.get('controller_firmware')}, while the system expects "
                f"{touch.get('expected_firmware')}. This is what is seen after a "
                "glass replacement with a part carrying a controller from another "
                "batch.",
                strength="measured", touch=touch)
        elif touch.get("firmware_matches") is True:
            self.add(
                "ok", "components",
                "Touch firmware conforms",
                "The digitizer controller runs exactly the version the system "
                "expects.",
                strength="measured",
                version=touch.get("controller_firmware"))

        # Panel.
        panel = comp.get("panel") or {}
        service_code = panel.get("SVC_OCTA") or panel.get("octa_id")
        if service_code:
            self.add(
                "info", "components",
                "Display service code present",
                f"The display module declares service code "
                f"\"{service_code}\", the same one a service centre reads "
                "to identify the spare part. A replaced panel carries a code "
                "different from the factory one; without the original value it "
                "cannot be compared, but it belongs on record.",
                strength="circumstantial", panel=panel)
        else:
            # Pixel and most non-Samsung devices expose no /sys/class/lcd
            # service code. The panel still identifies itself over the display
            # link, and that part name is the closest available equivalent.
            product = self.get("display", "product_info", default={}) or {}
            if product.get("name"):
                self.add(
                    "info", "components",
                    "Display panel identified over the display link",
                    f"The panel reports part name \"{product['name']}\""
                    + (f", manufacturer id \"{product['manufacturerPnpId']}\""
                       if product.get("manufacturerPnpId") else "")
                    + ". This device exposes no service-code node, so this is the "
                    "identifier available for comparison against another unit of "
                    "the same model.",
                    strength="circumstantial", product_info=product)

        # Chip identity read by the kernel.
        soc0 = comp.get("soc") or {}
        machine = str(soc0.get("machine", "") or "")
        soc_id = str(soc0.get("soc_id", "") or "")
        if machine or soc_id:
            declared = " ".join(str(x) for x in (
                self.get("system", "soc", "declared_model", default=""),
                self.get("system", "soc", "platform", default=""),
                self.get("system", "soc", "hardware_line", default=""),
            )).lower().replace("-", "").replace(" ", "")
            # Deliberately permissive: the two names follow different
            # conventions (for example "SM7150" against "trinket"), and a strict
            # rule would raise false alarms across half the market. It flags
            # gross mismatches, it does not certify.
            matches = bool(machine) and machine.lower().replace(
                "-", "").replace(" ", "") in declared
            self.add(
                "ok" if matches else "info", "identity",
                "Chip identity read from the SoC registers",
                f"The kernel derives from hardware: machine "
                f"\"{machine or 'n/a'}\""
                f"{f', identifier {soc_id}' if soc_id else ''}. "
                + ("This matches the chip declared by the system properties."
                   if matches else
                   "It cannot be compared automatically against the declared "
                   "commercial name, because the two use different conventions: "
                   "the value stays on record for manual comparison."),
                strength="measured", kernel=soc0.get("raw", {}))

        chip_serial = soc0.get("chip_serial")
        if chip_serial:
            self.add(
                "info", "identity",
                "Processor serial number",
                f"The SoC exposes its own serial number ({chip_serial}), unique "
                "per chip and not modifiable by software. Two phones cannot share "
                "it: it is the most direct way to notice that two devices are "
                "actually the same one, or that a mainboard has been transplanted.",
                strength="proven", chip_serial=chip_serial)

        # Storage chip.
        chip = comp.get("storage_chip") or {}
        if chip.get("product") or chip.get("chip_serial"):
            self.add(
                "info", "components",
                "Storage chip identified",
                "The storage declares manufacturer, product and serial number of "
                "the individual chip: "
                f"{chip.get('manufacturer') or chip.get('manufacturer_id') or 'unknown manufacturer'}"
                f", {chip.get('product') or 'unknown model'}"
                f"{f', serial {chip['chip_serial']}' if chip.get('chip_serial') else ''}.",
                strength="proven", storage=chip)

        # USB port.
        #
        # A slower link is information, not a warning: the cable in the box of
        # most phones is USB 2.0, as are many computer ports, so a USB 3
        # controller running at high speed is the ordinary case. The reading
        # cannot tell that apart from worn data pins.
        usb = comp.get("usb_link") or {}
        if usb.get("degraded"):
            self.add(
                "info", "components",
                "USB link below the supported speed",
                f"The phone's controller can negotiate "
                f"{usb.get('maximum_label')}, but the current link runs at "
                f"{usb.get('current_label')}. The usual cause is a USB 2.0 "
                "cable or computer port; damaged or oxidised data pins in the "
                "phone's connector produce the same reading. Retry with a "
                "cable and port known to support the higher speed before "
                "suspecting the connector.",
                strength="measured", link=usb)
        elif usb.get("current_mbps"):
            self.add(
                "ok", "components",
                f"USB port at full speed ({usb['current_label']})",
                "The phone's connector negotiates the highest speed class the "
                "controller supports: the data pins are intact.",
                strength="measured", link=usb)

        # Sensors: HAL against drivers.
        nodes = comp.get("kernel_sensor_nodes") or {}
        if nodes:
            self.add(
                "info", "components",
                f"Sensors seen directly by the drivers ({len(nodes)})",
                "Besides the list the framework exposes to apps, the kernel shows "
                "the driver nodes behind the physical sensors. A sensor present in "
                "the first list but absent here is provided by software, not by a "
                "component.",
                strength="measured",
                nodes={k: v.get("name") for k, v in nodes.items()})

    # -------------------------------------------------------------- report

    def _report(self) -> dict[str, Any]:
        by_sev: dict[str, list[dict]] = {
            "critical": [], "warning": [], "info": [], "ok": [],
        }
        for f in self.findings:
            by_sev.setdefault(f.severity, []).append(f.to_dict())

        penalty = sum(SEVERITY_WEIGHT.get(f.severity, 0) for f in self.findings)
        score = max(0, 100 - penalty)

        verdict, headline = summarise(
            len(by_sev["critical"]), len(by_sev["warning"]))

        return {
            "score": score,
            "verdict": verdict,
            "headline": headline,
            "counts": {k: len(v) for k, v in by_sev.items()},
            "findings": [f.to_dict() for f in self.findings],
            "by_severity": by_sev,
            "by_category": self._group_by_category(),
            "disclaimer": DISCLAIMER,
        }

    def _group_by_category(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for f in self.findings:
            out.setdefault(f.category, []).append(f.to_dict())
        return out


# Printed on every report, the PDF included: what the report is, and what it is
# not. The program is an aid to understanding a phone, for instance before
# buying or selling it; it is not a certification.
DISCLAIMER = (
    "PhoneVitals is an aid to understanding the condition of a phone, for example "
    "before buying or selling it. Its results are indicative and are provided as "
    "is, without warranty of any kind: they are not a certification of "
    "authenticity, condition or value, and its authors accept no liability for "
    "decisions taken on the basis of them or for any damage arising from its use, "
    "including from the functional tests. This report lists the anomalies found: "
    "their absence does not prove the device is original, only that the checks "
    "performed found no contradictions. Whether an IMEI is reported stolen "
    "requires national registries, which this program does not query. A physical "
    "inspection remains irreplaceable for components the software does not expose."
)


def summarise(n_critical: int, n_warning: int) -> tuple[str, str]:
    """Map finding counts to a verdict and headline.

    Shared with the analyzer, which recounts after merging in the IMEI
    findings; keeping one implementation stops the two from drifting.
    """
    if n_critical:
        return "compromised", (
            f"{n_critical} serious anomalies detected. The device shows internal "
            "contradictions that cannot occur on an original, intact unit."
        )
    if n_warning >= 3:
        return "suspicious", (
            f"No serious anomalies, but {n_warning} findings worth investigating. "
            "The overall picture warrants a manual check."
        )
    if n_warning:
        return "caution", (
            f"No serious anomalies. {n_warning} minor findings, consistent with a "
            "used or repaired device."
        )
    return "no_anomalies", "No anomalies detected by the checks performed."
