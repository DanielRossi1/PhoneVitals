"""Cryptographic verification of the attestation certificate chain.

Parsing the attested fields (attestation.py) says what the secure environment
claims; this says whether the claim can be believed. Every certificate must be
signed by the next one, and the last must be one of Google's attestation
roots, shipped in data/attestation_roots.pem. A chain made up to confirm a
counterfeit can copy Google's root certificate -- it is public -- but cannot
produce the signatures that link it to the device key.

Google also publishes the attestation keys it has revoked, typically because
they leaked and are used to spoof devices. A copy of that list ships in
data/attestation_status.json; scripts/update_attestation_data.sh refreshes
both files, and the release workflow runs it, so a release is as current as
its build date. The program itself never goes online.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
ROOTS_FILE = DATA_DIR / "attestation_roots.pem"
STATUS_FILE = DATA_DIR / "attestation_status.json"


def _spki(cert: x509.Certificate) -> bytes:
    return cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


@lru_cache(maxsize=1)
def trusted_roots() -> frozenset[bytes]:
    """Public keys (SPKI DER) of Google's attestation roots."""
    try:
        pem = ROOTS_FILE.read_bytes()
        return frozenset(_spki(c) for c in x509.load_pem_x509_certificates(pem))
    except (OSError, ValueError):
        return frozenset()


@lru_cache(maxsize=1)
def revocations() -> tuple[dict[str, dict], str | None]:
    """Revoked certificate serials (lower-case hex) and the list's date."""
    try:
        entries = json.loads(STATUS_FILE.read_text(encoding="utf-8")).get("entries", {})
        stamp = datetime.fromtimestamp(STATUS_FILE.stat().st_mtime, UTC).date().isoformat()
        return {k.lower(): v for k, v in entries.items()}, stamp
    except (OSError, ValueError, AttributeError):
        return {}, None


def _signed_by(cert: x509.Certificate, issuer: x509.Certificate) -> bool:
    """Signature check only. Issuer names are not compared: some vendors
    encode them differently in the two certificates, and the signature is
    what cannot be faked."""
    key = issuer.public_key()
    data, sig = cert.tbs_certificate_bytes, cert.signature
    try:
        if isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(sig, data, ec.ECDSA(cert.signature_hash_algorithm))
        elif isinstance(key, rsa.RSAPublicKey):
            pss = isinstance(cert.signature_algorithm_parameters, padding.PSS)
            key.verify(sig, data, cert.signature_algorithm_parameters if pss else padding.PKCS1v15(),
                       cert.signature_hash_algorithm)
        elif isinstance(key, ed25519.Ed25519PublicKey):
            key.verify(sig, data)
        else:
            return False
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def verify_chain(chain_der: list[bytes]) -> dict[str, Any]:
    """Verify an attestation chain, leaf first."""
    try:
        certs = [x509.load_der_x509_certificate(d) for d in chain_der]
    except ValueError as exc:
        return {"checked": False, "error": f"unreadable certificate: {exc}"}
    if not certs:
        return {"checked": False, "error": "empty chain"}

    broken_at = None
    for i in range(len(certs) - 1):
        if not _signed_by(certs[i], certs[i + 1]):
            broken_at = i
            break
    root = certs[-1]
    root_self_signed = _signed_by(root, root)

    roots = trusted_roots()
    revoked_list, list_date = revocations()
    revoked = []
    for position, cert in enumerate(certs):
        entry = revoked_list.get(format(cert.serial_number, "x"))
        if entry:
            revoked.append({"position": position, "serial": format(cert.serial_number, "x"),
                            "status": entry.get("status"), "reason": entry.get("reason")})

    return {
        "checked": True,
        "length": len(certs),
        "signatures_valid": broken_at is None and root_self_signed,
        "broken_at": broken_at,
        "root_trusted": (_spki(root) in roots) if roots else None,
        "roots_available": bool(roots),
        "revoked": revoked,
        "revocation_list_date": list_date,
    }
