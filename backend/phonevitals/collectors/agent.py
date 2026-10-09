"""Running one-shot agent commands during the analysis.

The batch collectors only have the shell; some facts need Java APIs, so the
same agent the live streams use is run once per question. `AgentOnPhone`
copies the .dex for the duration of a block and removes it afterwards -- but
only if it was the one to put it there: a live session may be using it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..adb import Adb
from ..live import DEX_LOCAL, DEX_REMOTE, agent_command, parse_json_line


class AgentOnPhone:
    def __init__(self, adb: Adb, serial: str):
        self.adb = adb
        self.serial = serial
        self.ready = False
        self._owns = False

    async def __aenter__(self) -> AgentOnPhone:
        if not Path(DEX_LOCAL).is_file():
            return self
        present = await self.adb.shell(
            self.serial, f"[ -f {DEX_REMOTE} ] && echo yes", timeout=10)
        if "yes" in present.out:
            self.ready = True
            return self
        push = await self.adb.raw("-s", self.serial, "push", DEX_LOCAL, DEX_REMOTE,
                                  timeout=60)
        self.ready = push.ok
        self._owns = push.ok
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owns:
            await self.adb.shell(self.serial, f"rm -f {DEX_REMOTE}", timeout=8)

    async def run(self, *args: str, timeout: float = 30.0) -> list[dict[str, Any]]:
        """Run one agent command and return the JSON messages it printed."""
        if not self.ready:
            return []
        result = await self.adb.shell(self.serial, agent_command(*args), timeout=timeout)
        return [m for m in map(parse_json_line, result.out.splitlines()) if m]


def _date(seconds: Any) -> str | None:
    try:
        value = int(seconds)
    except (TypeError, ValueError):
        return None
    # Health HALs report seconds since the epoch; anything before 2010 is a
    # placeholder rather than a date.
    if value < 1_262_304_000:
        return None
    return datetime.fromtimestamp(value, UTC).date().isoformat()


async def battery_facts(agent: AgentOnPhone) -> dict[str, Any]:
    """What BatteryManager reports beyond sysfs: Android 14's cycle count,
    state of health and cell dates, where the device provides them."""
    messages = [m for m in await agent.run("battery") if m.get("type") == "battery"]
    if not messages:
        return {}
    first = messages[0]
    facts: dict[str, Any] = {}
    cycles = first.get("cycle_count")
    if isinstance(cycles, int) and cycles >= 0:
        facts["cycle_count"] = cycles
    soh = first.get("state_of_health_percent")
    if isinstance(soh, (int, float)) and 0 < soh <= 100:
        facts["state_of_health_percent"] = soh
    for key, out in (("manufacturing_date_s", "manufacturing_date"),
                     ("first_usage_date_s", "first_usage_date")):
        iso = _date(first.get(key))
        if iso:
            facts[out] = iso
    if first.get("refused"):
        facts["refused"] = sorted(first["refused"])
    return facts
