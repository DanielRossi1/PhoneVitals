"""Test of the DER reader for the attestation extension.

No phone required: a `KeyDescription` is built by hand with the same encoding
Keymint produces, and it is checked that it reads back identically. The
delicate part is the long-tag form -- AuthorizationList fields go up to 723,
and a parser that only handles tags below 31 skips them silently, returning a
plausible but empty result, which is the worst way to be wrong.
"""

from __future__ import annotations

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phonevitals.analysis import attestation as att   # noqa: E402


# ──────────────────────────── test encoding ─────────────────────────────

def enc_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def tlv(identifier: bytes, body: bytes) -> bytes:
    return identifier + enc_len(len(body)) + body


def context_tag(number: int) -> bytes:
    """Constructed context-specific tag, in the long form above 30."""
    if number < 0x1F:
        return bytes([0xA0 | number])
    parts = [number & 0x7F]
    number >>= 7
    while number:
        parts.append((number & 0x7F) | 0x80)
        number >>= 7
    return bytes([0xBF]) + bytes(reversed(parts))


def integer(value: int) -> bytes:
    if value == 0:
        return tlv(b"\x02", b"\x00")
    body = value.to_bytes((value.bit_length() + 8) // 8, "big")
    return tlv(b"\x02", body)


def enumerated(value: int) -> bytes:
    return tlv(b"\x0a", bytes([value]))


def octets(data: bytes) -> bytes:
    return tlv(b"\x04", data)


def boolean(value: bool) -> bytes:
    return tlv(b"\x01", b"\xff" if value else b"\x00")


def sequence(*parts: bytes) -> bytes:
    return tlv(b"\x30", b"".join(parts))


def tagged(number: int, body: bytes) -> bytes:
    return tlv(context_tag(number), body)


def build_key_description() -> bytes:
    root_of_trust = sequence(
        octets(bytes(range(32))),                 # verified boot key
        boolean(True),                            # bootloader locked
        enumerated(0),                            # state: verified
        octets(b"\xaa" * 32),                     # boot hash
    )

    hardware = sequence(
        tagged(704, root_of_trust),
        tagged(705, integer(130000)),             # Android 13.0.0
        tagged(706, integer(202402)),             # patch 2024-02
        tagged(710, octets(b"samsung")),
        tagged(711, octets(b"a71")),
        tagged(712, octets(b"a71naeea")),
        tagged(713, octets(b"RZ8R1TEST01")),
        tagged(714, octets(b"490154200000000")),
        tagged(716, octets(b"samsung")),
        tagged(717, octets(b"SM-A715F")),
        tagged(718, integer(20240201)),
        tagged(719, integer(20240201)),
    )

    application_id = octets(sequence(
        tlv(b"\x31", sequence(octets(b"com.android.shell"), integer(2000))),
        tlv(b"\x31", b""),
    ))
    software = sequence(tagged(709, application_id))

    return sequence(
        integer(300),                             # attestation version
        enumerated(1),                            # security level: TEE
        integer(300),
        enumerated(1),
        octets(bytes.fromhex("0badc0de")),        # challenge
        octets(b""),                              # uniqueId
        software,
        hardware,
    )


# ──────────────────────────────── checks ────────────────────────────────

def check(condition: bool, message: str) -> bool:
    print(("  ok   " if condition else "  FAILED ") + message)
    return condition


def chain_checks() -> list[str]:
    """Chain verification with throwaway keys: a forged chain built on a
    root that is not Google's, and the same chain with one byte altered."""
    import datetime as dt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    from phonevitals.analysis.attestation_chain import verify_chain

    def cert(subject, issuer, key, signer, ca):
        now = dt.datetime(2026, 1, 1)
        return (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
                .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]))
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now).not_valid_after(now + dt.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
                .sign(signer, hashes.SHA256()))

    root_key, leaf_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    root = cert("fake root", "fake root", root_key, root_key, True)
    leaf = cert("leaf", "fake root", leaf_key, root_key, False)
    der = [c.public_bytes(serialization.Encoding.DER) for c in (leaf, root)]

    problems = []
    good = verify_chain(der)
    if not (good["signatures_valid"] and good["root_trusted"] is False):
        problems.append(f"a self-made chain must verify but not be trusted: {good}")
    tampered = bytearray(der[0])
    tampered[-3] ^= 0x01
    if verify_chain([bytes(tampered), der[1]])["signatures_valid"] is not False:
        problems.append("an altered certificate must fail verification")
    print("  ok   self-made chain: signatures hold, root not Google's" if not problems
          else "  FAIL chain verification")
    return problems


def main() -> int:
    parsed = att.parse_key_description(build_key_description())
    ok = True

    print("attestation extension")
    ok &= check(parsed["attestation_version"] == 300, "version read")
    ok &= check(parsed["security_level"] == "tee", "TEE security level")
    ok &= check(parsed["challenge_hex"] == "0badc0de", "challenge read back")

    hardware = parsed["hardware_enforced"]
    print("hardware-enforced fields")
    ok &= check(hardware.get("brand") == "samsung", "brand attested")
    ok &= check(hardware.get("model") == "SM-A715F", "model attested")
    ok &= check(hardware.get("device") == "a71", "codename attested")
    ok &= check(hardware.get("serial") == "RZ8R1TEST01", "serial attested")
    ok &= check(hardware.get("imei") == "490154200000000", "IMEI attested")
    ok &= check(hardware.get("os_version") == "13.0.0", "Android version")
    ok &= check(hardware.get("os_patch_level") == "2024-02", "patch level")
    ok &= check(hardware.get("vendor_patch_level") == "2024-02-01",
                "vendor patch with day")

    rot = hardware.get("root_of_trust", {})
    print("root of trust")
    ok &= check(rot.get("device_locked") is True, "bootloader locked")
    ok &= check(rot.get("verified_boot_state") == "verified", "verified boot")
    ok &= check(len(rot.get("verified_boot_key_sha256", "")) == 64,
                "boot key fingerprint")

    print("software-enforced fields")
    ok &= check("com.android.shell" in
                parsed["software_enforced"].get("attestation_application_id", ""),
                "requesting package recognised")

    # A parser that ignores the long-tag form would return an empty
    # dictionary without flagging anything: this is the check that exposes it.
    print("robustness")
    ok &= check(len(hardware) >= 12, "no long-tag field lost")

    print("chain verification")
    ok &= not chain_checks()

    # A chain that is valid DER but lacks the elements a certificate must
    # have used to escape as IndexError, although analyse() promises never to
    # raise: attestation is one source among many.
    truncated = sequence(sequence(tagged(0, integer(2))), sequence(),
                         tlv(b"\x03", b"\x00"))
    try:
        result = att.analyse(
            {"ok": True, "chain": [base64.b64encode(truncated).decode()]})
        ok &= check(result["available"] is False and bool(result["error"]),
                    "truncated certificate reported, not raised")
    except Exception as exc:  # noqa: BLE001 - the point is that nothing escapes
        ok &= check(False, f"truncated certificate raised {type(exc).__name__}")

    print()
    print("RESULT: " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
