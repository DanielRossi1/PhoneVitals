"""Real-time data streams from the phone.

Three independent sources, each with its own lifecycle, so that the failure of
one does not take down the others:

  AgentSession    sensors (accelerometer, gyroscope, magnetometer, light,
                  proximity, barometer...) through the .dex agent started with
                  app_process. This is the only way to read the sensors: there
                  is no shell command equivalent.

  TouchMonitor    finger coordinates read from getevent on the digitizer input
                  device. Nothing is needed on the phone: getevent is part of
                  Android and the stream is readable from the shell.

  PollingMonitor  battery, temperatures, clock frequencies, signal strength.
                  These are instantaneous readings, so they are sampled at
                  intervals rather than pushed by the device.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import time
import uuid
from collections.abc import Callable
from typing import Any

from .adb import Adb, reap

log = logging.getLogger(__name__)

DEX_LOCAL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "pvagent.dex",
)
DEX_REMOTE = "/data/local/tmp/pvagent.dex"
AGENT_CLASS = "com.phonevitals.agent.Agent"

# asyncio's default 64 KiB line limit is within reach of a GNSS status line on
# a multi-constellation, dual-frequency receiver, and exceeding it makes
# readline() raise.
STREAM_LINE_LIMIT = 1 << 20


def agent_command(command: str, *args: str) -> str:
    """Shell command line that runs the agent with the given arguments."""
    words = [command, *args]
    return (f"CLASSPATH={DEX_REMOTE} app_process / {AGENT_CLASS} "
            + " ".join(shlex.quote(w) for w in words))


def parse_json_line(raw: bytes | str) -> dict[str, Any] | None:
    """One agent output line as a dict, or None for anything else."""
    line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        payload = json.loads(line)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


async def _deliver(sink: Callable, payload: dict) -> None:
    """Hand one event to the sink; a failing sink must not end the stream."""
    try:
        res = sink(payload)
        if asyncio.iscoroutine(res):
            await res
    except Exception:
        log.exception("live event sink failed on %s", payload.get("type"))


class AgentSession:
    """Starts the agent on the phone and reads its JSON stream.

    On intrusiveness: the only trace left on the device is the .dex file in
    /data/local/tmp, which is adb's working directory. No package is
    installed, nothing appears in the app list, and `stop()` removes the file.
    """

    def __init__(self, adb: Adb, serial: str, on_event: Callable,
                 command: str = "sensors", owns_dex: bool = True):
        self.adb = adb
        self.serial = serial
        self.on_event = on_event
        # The same agent serves two different streams -- sensors and GNSS
        # satellites -- which are two distinct processes on the phone. Only the
        # first owns the .dex file and removes it on shutdown, otherwise the
        # second would have it pulled from under it.
        self.command = command
        self.owns_dex = owns_dex
        self.proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None
        self._stderr_reader: asyncio.Task | None = None
        self.pushed = False
        self.last_error: str | None = None
        self.running = False
        # Passed to the agent as an extra, ignored argument so that this
        # process -- and only this one -- can be found with `pkill -f`. The
        # test suite and the attestation probe run the same class with the
        # same command at the same time.
        self._tag = f"pv-{command}-{uuid.uuid4().hex[:12]}"
        # Bumped by stop(): a start() still in flight sees the change and
        # backs out instead of leaving an orphan stream behind.
        self._generation = 0
        self._spawned = False
        self._cleanup_on_stop = True

    async def _emit(self, payload: dict) -> None:
        await _deliver(self.on_event, payload)

    async def _abandon_start(self) -> bool:
        """Undo what a start() overtaken by stop() did after stop() ran."""
        if self._spawned:
            await self._kill_remote()
            self._spawned = False
        if self._cleanup_on_stop and self.owns_dex and self.pushed:
            await self.adb.shell(self.serial, f"rm -f {DEX_REMOTE}", timeout=8)
            self.pushed = False
        return False

    async def push(self) -> bool:
        if not os.path.isfile(DEX_LOCAL):
            self.last_error = (
                f"The agent has not been built ({DEX_LOCAL} does not exist). "
                "Run scripts/build_agent.sh."
            )
            return False

        r = await self.adb.raw("-s", self.serial, "push", DEX_LOCAL, DEX_REMOTE,
                               timeout=60)
        if not r.ok:
            self.last_error = f"Copying the agent failed: {r.err.strip() or r.out.strip()}"
            # adb push writes straight to the destination path, so a copy
            # that failed half way leaves a truncated file behind.
            if self.owns_dex:
                await self.adb.shell(self.serial, f"rm -f {DEX_REMOTE}", timeout=8)
            return False
        self.pushed = True
        return True

    async def probe(self) -> dict[str, Any]:
        """Run the agent in `info` mode and collect its inventory.

        This also proves app_process accepts our dex on this device: if it
        fails here, streaming will not start either.
        """
        if not self.pushed and not await self.push():
            return {"ok": False, "error": self.last_error}

        r = await self.adb.shell(self.serial, agent_command("info"), timeout=40)

        for line in r.out.splitlines():
            payload = parse_json_line(line)
            if payload is None:
                continue
            if payload.get("type") == "info":
                return {"ok": True, "info": payload}
            if payload.get("type") in ("fatal", "error"):
                return {"ok": False, "error": payload.get("message"),
                        "detail": payload.get("trace", "")}

        return {
            "ok": False,
            "error": ("The agent timed out." if r.timed_out
                      else "The agent produced no recognisable output."),
            "detail": (r.err or r.out).strip()[:800],
        }

    async def start(self, sensor_types: list[int] | None = None) -> bool:
        if self.running:
            return True
        generation = self._generation
        if not self.pushed and not await self.push():
            await self._emit({"type": "agent_error", "message": self.last_error})
            return False
        if generation != self._generation:
            return await self._abandon_start()

        # The sensor list is always passed, possibly empty, so that the tag
        # lands in the same position for every command.
        types = ",".join(str(t) for t in sensor_types) if sensor_types else ""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.adb.adb, "-s", self.serial, "shell",
                agent_command(self.command, types, self._tag),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STREAM_LINE_LIMIT,
            )
        except OSError as exc:
            self.last_error = f"cannot run adb: {exc}"
            await self._emit({"type": "agent_error", "message": self.last_error})
            return False
        self._spawned = True
        if generation != self._generation:
            await reap(proc)
            return await self._abandon_start()

        self.proc = proc
        self.running = True
        self._reader = asyncio.create_task(self._read_stdout(proc, generation))
        self._stderr_reader = asyncio.create_task(self._read_stderr(proc))
        return True

    async def _read_stdout(self, proc: asyncio.subprocess.Process,
                           generation: int) -> None:
        assert proc.stdout
        try:
            while True:
                try:
                    raw = await proc.stdout.readline()
                except ValueError:
                    # Line over the limit: the reader has already discarded
                    # it, so skip it and keep the stream alive.
                    continue
                if not raw:
                    break
                payload = parse_json_line(raw)
                if payload is not None:
                    await self._emit(payload)
        finally:
            self.running = False

        if generation == self._generation:
            # EOF without stop(): the agent died or the phone went away.
            await reap(proc, grace=2)
            await self._emit({
                "type": "agent_error",
                "message": f"The {self.command} agent exited "
                           f"(code {proc.returncode}).",
            })

    async def _read_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr
        chunks: list[str] = []
        while True:
            try:
                raw = await proc.stderr.readline()
            except ValueError:
                continue
            if not raw:
                break
            text = raw.decode("utf-8", "replace").strip()
            # Java exceptions land here: the first lines are forwarded
            # because they are the only useful diagnostic if the agent fails
            # to start. The rest is drained and dropped, so the pipe never
            # fills up and blocks the agent.
            if text and len(chunks) < 12:
                chunks.append(text)
                self.last_error = "\n".join(chunks)
                await self._emit({"type": "agent_stderr", "line": text})

    async def _kill_remote(self) -> None:
        # The agent runs as a shell process: when the adb channel closes it can
        # be left orphaned, so it is killed explicitly. The bracket keeps the
        # pattern from matching the `sh -c` that runs pkill itself.
        pattern = shlex.quote(f"[{self._tag[0]}]{self._tag[1:]}")
        await self.adb.shell(
            self.serial, f"pkill -f {pattern} 2>/dev/null; true", timeout=8)

    async def stop(self, cleanup: bool = True) -> None:
        self._generation += 1
        self._cleanup_on_stop = cleanup
        self.running = False
        proc, self.proc = self.proc, None
        if proc:
            try:
                if proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.write(b"stop\n")
                    await asyncio.wait_for(proc.stdin.drain(), timeout=2)
                    proc.stdin.close()
            except (ConnectionError, RuntimeError, TimeoutError):
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except TimeoutError:
                pass
            await reap(proc)

        tasks = [t for t in (self._reader, self._stderr_reader) if t]
        self._reader = self._stderr_reader = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        if self._spawned:
            await self._kill_remote()
            self._spawned = False

        if cleanup and self.owns_dex and self.pushed:
            await self.adb.shell(self.serial, f"rm -f {DEX_REMOTE}", timeout=8)
            self.pushed = False


class TouchMonitor:
    """Live touch coordinates read from getevent.

    getevent -lt emits one line per event with symbolic names. The Linux
    multitouch protocol uses slots: ABS_MT_SLOT selects the current finger,
    ABS_MT_TRACKING_ID of -1 lifts it, and SYN_REPORT closes the update packet.
    Finger state is reconstructed from that sequence.
    """

    # getevent only prefixes lines with "<device>: " when it watches every
    # device; given a single device path, as here, the prefix is absent.
    LINE = re.compile(
        r"^\[\s*([\d.]+)\]\s+(?:(\S+):\s+)?(\S+)\s+(\S+)\s+(\S+)")

    def __init__(self, adb: Adb, serial: str, device_path: str,
                 on_event: Callable, max_x: int = 0, max_y: int = 0):
        self.adb = adb
        self.serial = serial
        self.device_path = device_path
        self.on_event = on_event
        self.max_x = max_x
        self.max_y = max_y
        self.proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task | None = None
        self.running = False
        self._generation = 0

        self._slot = 0
        self._points: dict[int, dict[str, Any]] = {}

    async def _emit(self, payload: dict) -> None:
        await _deliver(self.on_event, payload)

    async def start(self) -> bool:
        if self.running or not self.device_path:
            return self.running

        generation = self._generation
        try:
            proc = await asyncio.create_subprocess_exec(
                self.adb.adb, "-s", self.serial, "shell",
                f"getevent -lt {shlex.quote(self.device_path)}",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            log.exception("cannot start getevent")
            return False
        if generation != self._generation:
            await reap(proc)
            return False
        self.proc = proc
        self.running = True
        self._task = asyncio.create_task(self._read(proc))
        return True

    async def _read(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout
        try:
            while True:
                try:
                    raw = await proc.stdout.readline()
                except ValueError:
                    continue
                if not raw:
                    break
                try:
                    await self._handle(raw.decode("utf-8", "replace").strip())
                except Exception:
                    log.exception("touch event handling failed")
        finally:
            self.running = False

    async def _handle(self, line: str) -> None:
        m = self.LINE.match(line)
        if not m:
            return
        _ts, _dev, etype, code, value = m.groups()

        if etype == "EV_SYN" and code == "SYN_REPORT":
            active = [dict(p) for p in self._points.values() if p.get("down")]
            await self._emit({
                "type": "touch",
                "points": active,
                "count": len(active),
                "max_x": self.max_x,
                "max_y": self.max_y,
            })
            return

        if etype != "EV_ABS":
            return

        try:
            # getevent -l prints values in hexadecimal.
            v = int(value, 16)
        except ValueError:
            return

        if code == "ABS_MT_SLOT":
            self._slot = v
            return

        point = self._points.setdefault(self._slot,
                                        {"slot": self._slot, "down": False})

        if code == "ABS_MT_TRACKING_ID":
            # 0xffffffff is -1 in two's complement: finger lifted.
            if v in (0xFFFFFFFF, -1):
                point["down"] = False
                point.pop("x", None)
                point.pop("y", None)
            else:
                point["down"] = True
                point["tracking_id"] = v
        elif code == "ABS_MT_POSITION_X":
            point["x"] = v
            point["down"] = True
        elif code == "ABS_MT_POSITION_Y":
            point["y"] = v
            point["down"] = True
        elif code in ("ABS_MT_PRESSURE", "ABS_PRESSURE"):
            point["pressure"] = v
        elif code == "ABS_MT_TOUCH_MAJOR":
            point["size"] = v

    async def stop(self) -> None:
        self._generation += 1
        self.running = False
        proc, self.proc = self.proc, None
        if proc:
            await reap(proc)
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._points.clear()
        self._slot = 0


class PollingMonitor:
    """Samples at intervals the values that have no push stream."""

    # One grep per group rather than one cat per value: at 1 Hz the process
    # spawn cost of a dozen cats is the dominant term, and on a Pixel the
    # battery node alone made a poll cycle take most of a second.
    COMMANDS = {
        "battery": (
            "grep -sH . /sys/class/power_supply/battery/capacity "
            "/sys/class/power_supply/battery/current_now "
            "/sys/class/power_supply/battery/voltage_now "
            "/sys/class/power_supply/battery/temp "
            "/sys/class/power_supply/battery/status "
            "2>/dev/null | sed -e 's|^.*/||' -e 's|:|=|'"
        ),
        "thermal": (
            "grep -sH . /sys/class/thermal/thermal_zone*/type "
            "/sys/class/thermal/thermal_zone*/temp 2>/dev/null | "
            "sed -e 's|^/sys/class/thermal/||' -e 's|/|.|' -e 's|:|=|'"
        ),
        # Fallback for devices where SELinux closes /sys/class/thermal to the
        # shell user, Pixel included: the thermal HAL publishes the same
        # sensors here, already in degrees Celsius.
        "thermal_service": (
            "dumpsys thermalservice 2>/dev/null | grep -m40 'Temperature{'"
        ),
        "cpu_freq": (
            "grep -sH . /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq "
            "2>/dev/null | sed -e 's|^/sys/devices/system/cpu/||' "
            "-e 's|/cpufreq/scaling_cur_freq||' -e 's|:|=|'"
        ),
        "meminfo": "grep -E 'MemAvailable|MemFree' /proc/meminfo",
        "loadavg": "cat /proc/loadavg",
        "wifi_rssi": "cmd wifi status 2>/dev/null | grep -m1 -oE 'RSSI: -?[0-9]+'",
        "signal": "dumpsys telephony.registry 2>/dev/null | grep -m1 -oE 'mLevel=[0-9]+'",
    }

    # WifiInfo.INVALID_RSSI: what the framework reports when not associated.
    INVALID_RSSI = -127

    def __init__(self, adb: Adb, serial: str, on_event: Callable,
                 interval: float = 1.0):
        self.adb = adb
        self.serial = serial
        self.on_event = on_event
        self.interval = interval
        self._task: asyncio.Task | None = None
        self.running = False

    async def _emit(self, payload: dict) -> None:
        await _deliver(self.on_event, payload)

    async def _loop(self) -> None:
        while self.running:
            started = time.monotonic()
            try:
                raw = await self.adb.batch(
                    self.serial, self.COMMANDS, timeout=15,
                    chunk=len(self.COMMANDS))
                await self._emit({"type": "metrics", **self._shape(raw)})
            except Exception:
                log.exception("metrics poll failed")
            # Constant interval regardless of how long the reading took: over
            # slow USB a read can take most of a second.
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(0.2, self.interval - elapsed))

    @classmethod
    def _shape(cls, raw: dict[str, str]) -> dict[str, Any]:
        battery = {}
        for line in raw.get("battery", "").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                battery.setdefault(k.strip(), v.strip())

        def num(key: str) -> float | None:
            try:
                return float(battery.get(key, "").strip().split()[0])
            except (ValueError, IndexError):
                return None

        current = num("current_now")
        voltage = num("voltage_now")
        temp = num("temp")

        if current is None:
            current_ma = None
        elif abs(current) > 10000:          # microamps, the usual unit
            current_ma = round(current / 1000, 1)
        else:                               # some kernels report milliamps
            current_ma = round(current, 1)

        if voltage is None or voltage <= 0:
            voltage_v = None
        elif voltage > 100_000:             # microvolts
            voltage_v = round(voltage / 1_000_000, 3)
        else:                               # millivolts
            voltage_v = round(voltage / 1000, 3)

        thermal: dict[str, float] = {}
        by_zone: dict[str, dict[str, str]] = {}
        for line in raw.get("thermal", "").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            zone, _, attr = key.strip().partition(".")
            if zone and attr:
                by_zone.setdefault(zone, {})[attr] = value.strip()
        for attrs in by_zone.values():
            name, value = attrs.get("type"), attrs.get("temp")
            if not name or value is None:
                continue
            try:
                v = float(value)
            except ValueError:
                continue
            thermal[name] = round(v / 1000 if abs(v) > 200 else v, 1)

        if not thermal:
            for m in re.finditer(
                r"Temperature\{mValue=(-?[\d.]+),\s*mType=-?\d+,\s*mName=([^,}]+)",
                raw.get("thermal_service", ""),
            ):
                try:
                    thermal.setdefault(m.group(2).strip(), round(float(m.group(1)), 1))
                except ValueError:
                    continue

        freqs = {}
        for line in raw.get("cpu_freq", "").splitlines():
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            try:
                freqs[name.strip()] = int(value.strip())
            except ValueError:
                continue

        rssi_m = re.search(r"-?\d+", raw.get("wifi_rssi", ""))
        rssi = int(rssi_m.group()) if rssi_m else None
        if rssi is not None and rssi <= cls.INVALID_RSSI:
            rssi = None
        level_m = re.search(r"\d+", raw.get("signal", ""))

        return {
            "timestamp": time.time(),
            "battery": {
                "level": num("capacity"),
                "current_ma": current_ma,
                "voltage_v": voltage_v,
                # power_supply `temp` is in tenths of a degree Celsius.
                "temperature_c": round(temp / 10, 1) if temp is not None else None,
                "status": battery.get("status") or None,
            },
            "thermal": thermal,
            "cpu_freq_khz": freqs,
            "loadavg": raw.get("loadavg", "").strip(),
            "wifi_rssi_dbm": rssi,
            "signal_level": int(level_m.group()) if level_m else None,
        }

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.running = False
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
