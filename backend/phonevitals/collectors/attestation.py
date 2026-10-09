"""Collection of the hardware key attestation.

This is not a `Collector` like the others: it cannot be expressed as shell
commands to put in the batch, because it requires running Java code on the
phone. It therefore follows the same shape as the identity probe -- an object
with an async `run()`, invoked separately by the orchestrator.

The rationale for the whole operation is in `analysis/attestation.py`.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from pathlib import Path
from typing import Any

from ..adb import Adb
from ..analysis import attestation as parser
from ..analysis.attestation_chain import verify_chain

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEX_LOCAL = str(_DATA_DIR / "pvagent.dex")
DEX_REMOTE = "/data/local/tmp/pvagent.dex"
AGENT_CLASS = "com.phonevitals.agent.Agent"

class AttestationProbe:
    """Asks the phone for an attestation certificate and interprets it."""

    def __init__(self, adb: Adb, serial: str):
        self.adb = adb
        self.serial = serial

    async def run(self) -> dict[str, Any]:
        if not Path(DEX_LOCAL).is_file():
            return {
                "available": False,
                "error": "The agent is not built: run scripts/build_agent.sh.",
            }

        # Only remove the agent afterwards if this probe is what put it there.
        # A live session pushes the same file and keeps using it; deleting it
        # underneath would break the next command it runs.
        present = await self.adb.shell(
            self.serial, f"[ -f {DEX_REMOTE} ] && echo yes", timeout=10)
        owns_dex = "yes" not in present.out

        push = await self.adb.raw("-s", self.serial, "push",
                                  DEX_LOCAL, DEX_REMOTE, timeout=60)
        if not push.ok:
            return {
                "available": False,
                "error": f"Copying the agent failed: "
                         f"{(push.err or push.out).strip()[:200]}",
            }

        try:
            return await self._attest()
        finally:
            if owns_dex:
                await self.adb.shell(self.serial, f"rm -f {DEX_REMOTE}",
                                     timeout=8)

    async def _attest(self) -> dict[str, Any]:
        # The challenge is random on every run: it binds the certificate to
        # this session. A previously recorded certificate replayed now would
        # contain a different challenge, and that shows.
        challenge = secrets.token_hex(16)
        cmd = (f"CLASSPATH={DEX_REMOTE} app_process / {AGENT_CLASS} "
               f"attest {challenge}")
        result = await self.adb.shell(self.serial, cmd, timeout=90)

        payload = None
        for line in result.out.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if candidate.get("type") == "attestation":
                payload = candidate
                break
            if candidate.get("type") in ("fatal", "error"):
                return {
                    "available": False,
                    "error": candidate.get("message", "agent error"),
                    "detail": candidate.get("trace", ""),
                }

        if payload is None:
            return {
                "available": False,
                "error": "The agent did not return a readable attestation.",
                "detail": (result.err or result.out).strip()[:600],
            }

        analysis = parser.analyse(payload, expected_challenge=challenge)
        try:
            chain = verify_chain([base64.b64decode(c) for c in payload.get("chain") or []])
        except (binascii.Error, TypeError) as exc:
            chain = {"checked": False, "error": str(exc)}
        analysis["chain"] = chain
        analysis["roots_file_present"] = bool(chain.get("roots_available"))
        # A root counts as known only through a chain whose signatures hold:
        # a copied root certificate at the end of a forged chain must not.
        if chain.get("checked") and chain.get("root_trusted") is not None:
            analysis["root_known"] = bool(chain["signatures_valid"] and chain["root_trusted"])
            analysis["root_label"] = "Google hardware attestation root" if analysis["root_known"] else ""
        return analysis
