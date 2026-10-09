"""Android Key Attestation.

This is the strongest authenticity check a phone can offer through software,
and it is worth understanding why before reading the code.

Everything else PhoneVitals collects is a *claim made by software*: system
properties are lines of text in a file, and whoever rebrands a phone rewrites
them in minutes. Attestation is different. The device generates a key pair
inside the secure environment and returns a certificate signed by a key
injected at the factory by the chip vendor, not extractable even with root.
Inside that certificate is an extension describing the device state *as the
secure environment sees it*: brand, model, codename, verified boot state,
whether the bootloader is locked, the patch level.

If the properties say one thing and the secure environment says another, that
phone is not what it claims to be. Making the two agree on a clone would
require breaking the TEE, a problem of a completely different order from
rewriting a text file.

This module reads the fields: the DER is parsed by hand, about a hundred
lines. Whether the chain can be believed -- every signature valid, up to one
of Google's attestation roots, no revoked key -- is checked separately in
attestation_chain.py. Without that, agreement between attested fields and
system properties would be worth little: a fabricated chain is made to
confirm the counterfeit. A contradiction, on the other hand, is strong proof
of tampering even unverified, because no forger fabricates evidence against
himself.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Any

# ─────────────────────────────── DER ───────────────────────────────

CLASS_UNIVERSAL = 0
CLASS_CONTEXT = 2

TAG_BOOLEAN = 1
TAG_INTEGER = 2
TAG_BITSTRING = 3
TAG_OCTETSTRING = 4
TAG_NULL = 5
TAG_OID = 6
TAG_ENUMERATED = 10
TAG_UTF8STRING = 12
TAG_SEQUENCE = 16
TAG_SET = 17
TAG_PRINTABLESTRING = 19
TAG_UTCTIME = 23
TAG_GENERALIZEDTIME = 24


class DerError(ValueError):
    """Malformed DER. Never a caller error."""


class Tlv:
    """A DER element: class, tag number, and raw content."""

    __slots__ = ("cls", "constructed", "tag", "value", "end")

    def __init__(self, cls: int, constructed: bool, tag: int,
                 value: bytes, end: int):
        self.cls = cls
        self.constructed = constructed
        self.tag = tag
        self.value = value
        self.end = end

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"Tlv(cls={self.cls}, tag={self.tag}, len={len(self.value)})"


def read_tlv(data: bytes, offset: int = 0) -> Tlv:
    if offset >= len(data):
        raise DerError("read past end of buffer")

    first = data[offset]
    cls = (first >> 6) & 0x03
    constructed = bool(first & 0x20)
    tag = first & 0x1F
    pos = offset + 1

    # Long-form tag: the number continues in base 128 with the high bit as a
    # continuation flag. This is genuinely needed: AuthorizationList fields go
    # up to 723.
    if tag == 0x1F:
        tag = 0
        while True:
            if pos >= len(data):
                raise DerError("truncated tag")
            byte = data[pos]
            pos += 1
            tag = (tag << 7) | (byte & 0x7F)
            if not byte & 0x80:
                break

    if pos >= len(data):
        raise DerError("missing length")
    length_byte = data[pos]
    pos += 1

    if length_byte == 0x80:
        raise DerError("indefinite length: not allowed in DER")
    if length_byte & 0x80:
        count = length_byte & 0x7F
        if count > 8 or pos + count > len(data):
            raise DerError("invalid length")
        length = int.from_bytes(data[pos:pos + count], "big")
        pos += count
    else:
        length = length_byte

    if pos + length > len(data):
        raise DerError("truncated content")

    return Tlv(cls, constructed, tag, data[pos:pos + length], pos + length)


def children(data: bytes) -> list[Tlv]:
    """Elements contained in a constructed value."""
    out: list[Tlv] = []
    offset = 0
    while offset < len(data):
        item = read_tlv(data, offset)
        out.append(item)
        offset = item.end
    return out


def der_int(value: bytes) -> int:
    return int.from_bytes(value, "big", signed=True) if value else 0


def der_oid(value: bytes) -> str:
    if not value:
        return ""
    first = value[0]
    parts = [str(first // 40), str(first % 40)]
    acc = 0
    for byte in value[1:]:
        acc = (acc << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(str(acc))
            acc = 0
    return ".".join(parts)


def der_time(item: Tlv) -> str:
    """UTCTime or GeneralizedTime as ISO, without depending on strptime."""
    text = item.value.decode("ascii", "replace").rstrip("Z")
    if item.tag == TAG_UTCTIME and len(text) >= 10:
        year = int(text[0:2])
        # RFC 5280: 00-49 means 2000-2049, 50-99 means 1950-1999.
        full = 2000 + year if year < 50 else 1900 + year
        rest = text[2:]
    elif len(text) >= 12:
        full = int(text[0:4])
        rest = text[4:]
    else:
        return text
    if len(rest) < 8:
        return str(full)
    return (f"{full:04d}-{rest[0:2]}-{rest[2:4]}"
            f" {rest[4:6]}:{rest[6:8]}:{rest[8:10] or '00'} UTC")


# ─────────────────────────── X.509 certificate ───────────────────────────

OID_ATTESTATION = "1.3.6.1.4.1.11129.2.1.17"
OID_PROVISIONING_INFO = "1.3.6.1.4.1.11129.2.1.30"

NAME_OIDS = {
    "2.5.4.3": "CN",
    "2.5.4.6": "C",
    "2.5.4.7": "L",
    "2.5.4.8": "ST",
    "2.5.4.10": "O",
    "2.5.4.11": "OU",
    "2.5.4.5": "serialNumber",
}

SIGNATURE_OIDS = {
    "1.2.840.113549.1.1.11": "RSA with SHA-256",
    "1.2.840.113549.1.1.12": "RSA with SHA-384",
    "1.2.840.113549.1.1.13": "RSA with SHA-512",
    "1.2.840.10045.4.3.2": "ECDSA with SHA-256",
    "1.2.840.10045.4.3.3": "ECDSA with SHA-384",
}


def _parse_name(value: bytes) -> str:
    """RDNSequence in readable form: "CN=..., O=..."."""
    bits: list[str] = []
    for rdn in children(value):
        for atv in children(rdn.value):
            parts = children(atv.value)
            if len(parts) < 2:
                continue
            key = NAME_OIDS.get(der_oid(parts[0].value), der_oid(parts[0].value))
            text = parts[1].value.decode("utf-8", "replace")
            bits.append(f"{key}={text}")
    return ", ".join(bits)


def parse_certificate(der: bytes) -> dict[str, Any]:
    """Extract from the certificate only what the report needs."""
    cert = read_tlv(der)
    top = children(cert.value)
    if len(top) < 3:
        raise DerError("certificate lacks the three expected components")

    tbs = children(top[0].value)
    signature_oid = der_oid(children(top[1].value)[0].value) if top[1].value else ""

    index = 0
    version = 1
    if tbs and tbs[0].cls == CLASS_CONTEXT and tbs[0].tag == 0:
        version = der_int(children(tbs[0].value)[0].value) + 1
        index = 1

    serial = tbs[index].value
    index += 1
    index += 1                                   # inner AlgorithmIdentifier
    issuer = _parse_name(tbs[index].value)
    index += 1
    validity = children(tbs[index].value)
    index += 1
    subject = _parse_name(tbs[index].value)
    index += 1
    spki = tbs[index]
    index += 1

    extensions: dict[str, bytes] = {}
    for item in tbs[index:]:
        if item.cls == CLASS_CONTEXT and item.tag == 3:
            for ext in children(children(item.value)[0].value):
                fields = children(ext.value)
                oid = der_oid(fields[0].value)
                payload = fields[-1].value
                extensions[oid] = payload

    # The public key digest identifies the certificate stably: it is what gets
    # compared to recognise a root.
    spki_der = _reencode(spki)

    return {
        "version": version,
        "serial_hex": binascii.hexlify(serial).decode(),
        "issuer": issuer,
        "subject": subject,
        "not_before": der_time(validity[0]) if validity else "",
        "not_after": der_time(validity[1]) if len(validity) > 1 else "",
        "signature_algorithm": SIGNATURE_OIDS.get(signature_oid, signature_oid),
        "public_key_sha256": hashlib.sha256(spki_der).hexdigest(),
        "self_signed": issuer == subject,
        "extensions": extensions,
    }


def _reencode(item: Tlv) -> bytes:
    """Rebuild the DER encoding of an already-parsed element."""
    if item.tag < 0x1F:
        identifier = bytes([(item.cls << 6) | (0x20 if item.constructed else 0)
                            | item.tag])
    else:
        parts = []
        tag = item.tag
        parts.append(tag & 0x7F)
        tag >>= 7
        while tag:
            parts.append((tag & 0x7F) | 0x80)
            tag >>= 7
        identifier = bytes([(item.cls << 6)
                            | (0x20 if item.constructed else 0) | 0x1F])
        identifier += bytes(reversed(parts))

    length = len(item.value)
    if length < 0x80:
        header = bytes([length])
    else:
        encoded = length.to_bytes((length.bit_length() + 7) // 8, "big")
        header = bytes([0x80 | len(encoded)]) + encoded
    return identifier + header + item.value


# ───────────────────────── attestation extension ─────────────────────────

SECURITY_LEVELS = {
    0: ("software", "Software — no hardware guarantee"),
    1: ("tee", "TEE — secure environment inside the processor"),
    2: ("strongbox", "StrongBox — separate security chip"),
}

VERIFIED_BOOT_STATES = {
    0: ("verified", "Verified: boot chain intact and signed by the manufacturer"),
    1: ("self_signed", "Self-signed: a user-supplied key has been installed"),
    2: ("unverified", "Unverified: bootloader unlocked"),
    3: ("failed", "Failed: boot verification did not succeed"),
}

# AuthorizationList fields the report cares about. The numbers are from the
# Keymint schema; the rest are deliberately ignored.
AUTH_FIELDS = {
    704: "root_of_trust",
    705: "os_version",
    706: "os_patch_level",
    709: "attestation_application_id",
    710: "brand",
    711: "device",
    712: "product",
    713: "serial",
    714: "imei",
    715: "meid",
    716: "manufacturer",
    717: "model",
    718: "vendor_patch_level",
    719: "boot_patch_level",
    720: "device_unique_attestation",
    723: "second_imei",
}

IDENTITY_FIELDS = ("brand", "device", "product", "manufacturer", "model")


def _decode_os_version(raw: int) -> str:
    """MMmmpp -> "13.0.0". Zero means "not declared"."""
    if raw <= 0:
        return ""
    major, rest = divmod(raw, 10000)
    minor, patch = divmod(rest, 100)
    return f"{major}.{minor}.{patch}"


def _decode_patch(raw: int) -> str:
    """YYYYMM or YYYYMMDD, depending on the field."""
    text = str(raw)
    if len(text) == 6:
        return f"{text[0:4]}-{text[4:6]}"
    if len(text) == 8:
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text if raw else ""


def _parse_root_of_trust(value: bytes) -> dict[str, Any]:
    items = children(value)
    out: dict[str, Any] = {}
    if items:
        out["verified_boot_key_sha256"] = hashlib.sha256(items[0].value).hexdigest()
        out["verified_boot_key_hex"] = binascii.hexlify(items[0].value).decode()
    if len(items) > 1:
        out["device_locked"] = items[1].value not in (b"", b"\x00")
    if len(items) > 2:
        code = der_int(items[2].value)
        key, label = VERIFIED_BOOT_STATES.get(code, ("unknown", f"code {code}"))
        out["verified_boot_state"] = key
        out["verified_boot_label"] = label
    if len(items) > 3 and items[3].value:
        out["verified_boot_hash"] = binascii.hexlify(items[3].value).decode()
    return out


def _parse_authorization_list(value: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in children(value):
        if item.cls != CLASS_CONTEXT:
            continue
        name = AUTH_FIELDS.get(item.tag)
        if not name:
            continue

        # Explicitly tagged fields hold a single inner element.
        try:
            inner = children(item.value)
        except DerError:
            continue
        if not inner:
            out[name] = True                      # NULL markers
            continue
        node = inner[0]

        if name == "root_of_trust":
            out[name] = _parse_root_of_trust(node.value)
        elif name == "os_version":
            out[name] = _decode_os_version(der_int(node.value))
        elif name.endswith("patch_level"):
            out[name] = _decode_patch(der_int(node.value))
        elif name == "device_unique_attestation":
            out[name] = True
        elif name == "attestation_application_id":
            out[name] = _describe_application_id(node.value)
        else:
            out[name] = node.value.decode("utf-8", "replace").strip("\x00")
    return out


def _describe_application_id(value: bytes) -> str:
    """Name of the package that requested the attestation.

    It should read `com.android.shell`: that is the package any command
    launched from adb runs under, including our agent.
    """
    # AttestationApplicationId ::= SEQUENCE {
    #     package_infos      SET OF AttestationPackageInfo,
    #     signature_digests  SET OF OCTET STRING }
    # AttestationPackageInfo ::= SEQUENCE { name OCTET STRING, version INTEGER }
    try:
        outer = children(read_tlv(value).value)
        if not outer:
            return ""
        names = []
        for entry in children(outer[0].value):
            fields = children(entry.value)
            if fields:
                names.append(fields[0].value.decode("utf-8", "replace"))
        return ", ".join(names)
    except DerError:
        return ""


def parse_key_description(value: bytes) -> dict[str, Any]:
    # The extension content is an OCTET STRING which itself contains the
    # `KeyDescription` SEQUENCE: it must be opened before descending.
    items = children(read_tlv(value).value)
    if len(items) < 8:
        raise DerError("incomplete attestation extension")

    level_code = der_int(items[1].value)
    keymint_level = der_int(items[3].value)

    software = _parse_authorization_list(items[6].value)
    enforced = _parse_authorization_list(items[7].value)

    return {
        "attestation_version": der_int(items[0].value),
        "security_level": SECURITY_LEVELS.get(
            level_code, ("unknown", f"code {level_code}"))[0],
        "security_label": SECURITY_LEVELS.get(
            level_code, ("unknown", f"code {level_code}"))[1],
        "keymint_version": der_int(items[2].value),
        "keymint_security_level": SECURITY_LEVELS.get(
            keymint_level, ("unknown", f"code {keymint_level}"))[0],
        "challenge_hex": binascii.hexlify(items[4].value).decode(),
        "software_enforced": software,
        "hardware_enforced": enforced,
    }


# ─────────────────────────── complete analysis ───────────────────────────

def analyse(payload: dict[str, Any], expected_challenge: str = "",
            known_roots: dict[str, str] | None = None) -> dict[str, Any]:
    """Turn the agent response into a block ready for the report.

    Never raises: any problem becomes an `error` field, because attestation is
    one source among many and its failure must not stop the analysis.
    """
    result: dict[str, Any] = {
        "available": False,
        "error": None,
        "attempts": payload.get("attempts", []),
    }

    if not payload.get("ok"):
        result["error"] = _summarise_failure(payload)
        return result

    chain_b64 = payload.get("chain") or []
    certificates: list[dict[str, Any]] = []
    description: dict[str, Any] | None = None

    try:
        for encoded in chain_b64:
            der = base64.b64decode(encoded)
            info = parse_certificate(der)
            extensions = info.pop("extensions", {})
            if OID_ATTESTATION in extensions and description is None:
                description = parse_key_description(extensions[OID_ATTESTATION])
            info["has_attestation_extension"] = OID_ATTESTATION in extensions
            certificates.append(info)
    # DerError and binascii.Error are ValueErrors. IndexError and TypeError
    # cover a structurally valid DER that lacks the elements a certificate
    # must have (a truncated TBSCertificate, an empty AlgorithmIdentifier),
    # and a chain entry that is not a string.
    except (ValueError, IndexError, TypeError) as exc:
        result["error"] = f"Certificate chain unreadable: {exc}"
        return result

    if description is None:
        result["error"] = (
            "The chain contains no attestation extension: the device generated "
            "the key but does not certify its hardware origin."
        )
        result["certificates"] = certificates
        return result

    result["available"] = True
    result["certificates"] = certificates
    result["security_mode"] = payload.get("security_mode")
    result.update(description)

    # The challenge binds this attestation to this session. If it does not
    # match, the chain may be a replayed recording.
    if expected_challenge:
        result["challenge_matches"] = (
            description["challenge_hex"].lower() == expected_challenge.lower())

    hardware = description["hardware_enforced"]
    software = description["software_enforced"]

    # Identity fields sit among the hardware-enforced ones; some manufacturers
    # put part of them among the software-enforced.
    identity = {}
    for field in IDENTITY_FIELDS:
        value = hardware.get(field) or software.get(field)
        if value:
            identity[field] = value
    result["attested_identity"] = identity

    root_of_trust = hardware.get("root_of_trust") or software.get("root_of_trust") or {}
    result["root_of_trust"] = root_of_trust

    result["os_version"] = hardware.get("os_version") or software.get("os_version") or ""
    result["os_patch_level"] = (hardware.get("os_patch_level")
                                or software.get("os_patch_level") or "")
    result["vendor_patch_level"] = hardware.get("vendor_patch_level", "")
    result["boot_patch_level"] = hardware.get("boot_patch_level", "")
    result["requesting_package"] = (hardware.get("attestation_application_id")
                                    or software.get("attestation_application_id") or "")

    # Hardware-attested identifiers: where present they outrank any reading
    # from Settings, because the TEE signs them.
    for field in ("serial", "imei", "second_imei", "meid"):
        if hardware.get(field):
            result.setdefault("attested_ids", {})[field] = hardware[field]

    # Root of the chain: it is recognised, not verified. See the note at the
    # top of the module for why.
    if certificates:
        root = certificates[-1]
        result["root_public_key_sha256"] = root["public_key_sha256"]
        result["root_subject"] = root["subject"]
        result["root_self_signed"] = root["self_signed"]
        if known_roots:
            result["root_known"] = root["public_key_sha256"] in known_roots
            result["root_label"] = known_roots.get(root["public_key_sha256"], "")
        else:
            result["root_known"] = None

    return result


def _summarise_failure(payload: dict[str, Any]) -> str:
    """Turn the failure into a sentence that says what to do about it."""
    errors = [a.get("error", "") for a in payload.get("attempts", [])
              if not a.get("ok")]
    joined = " | ".join(e for e in errors if e)
    low = joined.lower()

    if "strongbox" in low and len(errors) == 1:
        return joined

    if "keystore" in low or "keystoreexception" in low:
        return (
            "The hardware keystore refused the request from the shell process. "
            "On some devices the SELinux policy does not grant shell the use of "
            f"the keystore. Detail: {joined}"
        )
    if "unsupported" in low or "nosuchalgorithm" in low:
        return (
            "The device does not offer key attestation: this is normal on older "
            f"or non Google-certified devices. Detail: {joined}"
        )
    return joined or "The agent did not return a certificate chain."
