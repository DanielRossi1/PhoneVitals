"""Asynchronous layer over adb.

Three design points worth knowing:

1. Every command has a timeout. A phone that hangs during a dumpsys must not
   freeze the whole analysis: the collector fails on its own and the rest
   continues.

2. `batch()` runs N shell commands in a single `adb shell` invocation,
   separating the outputs with markers. A full analysis performs ~150
   readings: one at a time that is ~150 USB round-trips (tens of seconds); in
   batches of 40 it is 4 round-trips.

3. Those batches are then dispatched concurrently. adb multiplexes several
   shell channels over one USB connection, so the round-trip latency of one
   chunk overlaps with the execution of the next.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import shutil
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)


class AdbError(RuntimeError):
    pass


@dataclass
class Result:
    rc: int
    out: str
    err: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.rc == 0 and not self.timed_out

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class Device:
    serial: str
    state: str                      # device | unauthorized | offline | recovery | sideload | no permissions ...
    model: str = ""
    product: str = ""
    device: str = ""
    transport: str = ""
    usb: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "device"

    @property
    def label(self) -> str:
        return self.model.replace("_", " ") or self.serial


_DEV_LINE = re.compile(r"^(\S+)\s+(\S+)(?:\s+(.*))?$")

# Every state `adb devices` can print (adb's ConnectionStateToString). Any
# other line -- the header, "* daemon started", version-mismatch notices that
# some adb releases print on stdout -- is not a device.
_STATES = {
    "device", "offline", "unauthorized", "authorizing", "connecting",
    "bootloader", "recovery", "rescue", "sideload", "host", "detached",
    "unknown",
}


async def reap(proc: asyncio.subprocess.Process, grace: float = 5.0) -> None:
    """Kill a child process if it is still running and wait for it to exit."""
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace)
    except TimeoutError:
        log.warning("adb child %s did not exit after SIGKILL", proc.pid)


class Adb:
    # How many shell invocations may be in flight at once. adb handles the
    # multiplexing; the cap keeps a slow device from being swamped and keeps
    # the failure of one chunk from cascading.
    MAX_CONCURRENCY = 4

    def __init__(self, adb_path: str | None = None):
        self.adb = adb_path or self._locate()
        self._server_started = False

    @staticmethod
    def _locate() -> str:
        """Find adb: $PHONEVITALS_ADB, then the dev toolchain, then $PATH."""
        override = os.environ.get("PHONEVITALS_ADB")
        if override and os.path.isfile(override) and os.access(override, os.X_OK):
            return override

        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        local = os.path.join(repo, ".toolchain", "platform-tools", "adb")
        if os.path.isfile(local) and os.access(local, os.X_OK):
            return local

        found = shutil.which("adb")
        if found:
            return found

        # Where the usual installers put it, for a desktop app started without
        # the user's shell PATH (macOS launches apps with a minimal one).
        home = os.path.expanduser("~")
        candidates = {
            "darwin": ["/opt/homebrew/bin/adb", "/usr/local/bin/adb",
                       f"{home}/Library/Android/sdk/platform-tools/adb"],
            "win32": [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk",
                                   "platform-tools", "adb.exe"),
                      os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet",
                                   "Links", "adb.exe")],
        }.get(sys.platform, [])
        for path in candidates:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path

        hint = (f" (PHONEVITALS_ADB is set to {override!r}, which is not an "
                "executable file)") if override else ""
        how = {
            "darwin": "brew install android-platform-tools",
            "win32": "winget install Google.PlatformTools",
        }.get(sys.platform, "sudo apt install adb")
        raise AdbError(
            f"adb not found{hint}. Install Android platform-tools ({how}), or "
            "point PHONEVITALS_ADB at the adb binary."
        )

    # ------------------------------------------------------------------ core

    async def raw(self, *args: str, timeout: float = 20.0,
                  binary: bool = False) -> Result:
        """Run adb with the given arguments.

        On timeout the child is killed and whatever it had printed so far is
        returned with `timed_out` set: `batch()` salvages the sections that
        completed before the command that hung.
        """
        try:
            # stdin is closed: otherwise `adb shell` forwards whatever the
            # backend's own stdin carries (a terminal, for the CLI) to the
            # remote command.
            proc = await asyncio.create_subprocess_exec(
                self.adb, *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            return Result(rc=-1, out=b"" if binary else "",  # type: ignore[arg-type]
                          err=f"cannot run adb: {exc}")

        out_buf, err_buf = bytearray(), bytearray()

        async def drain(stream: asyncio.StreamReader, buf: bytearray) -> None:
            while chunk := await stream.read(65536):
                buf.extend(chunk)

        timed_out = False
        try:
            async with asyncio.timeout(timeout):
                await asyncio.gather(drain(proc.stdout, out_buf),
                                     drain(proc.stderr, err_buf))
                await proc.wait()
        except TimeoutError:
            timed_out = True
        finally:
            # Also reached on cancellation: the child must not outlive us.
            await reap(proc)

        err = err_buf.decode("utf-8", "replace")
        if timed_out:
            err = (err + f"\ntimed out after {timeout}s").lstrip()
        rc = -1 if timed_out else (proc.returncode or 0)
        if binary:
            return Result(rc, bytes(out_buf), err, timed_out)  # type: ignore[arg-type]
        return Result(rc, out_buf.decode("utf-8", "replace"), err, timed_out)

    async def start_server(self) -> None:
        if not self._server_started:
            r = await self.raw("start-server", timeout=30)
            self._server_started = r.ok

    async def shell(self, serial: str, cmd: str, timeout: float = 20.0) -> Result:
        return await self.raw("-s", serial, "shell", cmd, timeout=timeout)

    async def text(self, serial: str, cmd: str, timeout: float = 20.0,
                   default: str = "") -> str:
        """Like shell() but returns cleaned stdout only, or `default` on failure."""
        r = await self.shell(serial, cmd, timeout)
        if not r.ok:
            return default
        return r.out.strip()

    async def pull_binary(self, serial: str, remote: str,
                          timeout: float = 30.0) -> bytes:
        """Read a file from the device as raw bytes, without touching disk."""
        r = await self.raw("-s", serial, "exec-out", f"cat {shlex.quote(remote)}",
                           timeout=timeout, binary=True)
        if not r.ok or not isinstance(r.out, (bytes, bytearray)):
            return b""
        return bytes(r.out)

    # ----------------------------------------------------------------- batch

    async def batch(self, serial: str, commands: dict[str, str],
                    timeout: float = 90.0, chunk: int = 40) -> dict[str, str]:
        """Run many shell commands in a few invocations, dispatched concurrently.

        Returns {key: stdout}. A command that fails yields an empty string and
        does not raise: collectors must degrade, not die.
        """
        results: dict[str, str] = {k: "" for k in commands}
        items = list(commands.items())
        groups = [items[i:i + chunk] for i in range(0, len(items), chunk)]
        if not groups:
            return results

        semaphore = asyncio.Semaphore(self.MAX_CONCURRENCY)

        async def run_group(group: list[tuple[str, str]]) -> dict[str, str]:
            async with semaphore:
                return await self._run_group(serial, group, timeout)

        for chunk_result in await asyncio.gather(
            *(run_group(g) for g in groups), return_exceptions=True
        ):
            if isinstance(chunk_result, dict):
                results.update(chunk_result)
            elif isinstance(chunk_result, BaseException):
                log.warning("adb batch chunk failed: %r", chunk_result)

        return results

    async def _run_group(self, serial: str, group: list[tuple[str, str]],
                         timeout: float) -> dict[str, str]:
        out: dict[str, str] = {}
        # Unique marker per invocation: if a command's output happened to
        # contain the marker, the split would break apart.
        mark = f"__PV_{uuid.uuid4().hex[:12]}__"
        script = "".join(
            f"echo {shlex.quote(mark + key)}; {cmd} 2>/dev/null; "
            for key, cmd in group
        )
        script += f"echo {shlex.quote(mark + 'END')}"

        r = await self.shell(serial, script, timeout=timeout)

        # Output arrives as: mark+key \n body \n mark+key2 \n body2 ...
        # A section counts only if another marker follows it. On a clean run
        # every section is closed by the next key or by END; after a timeout
        # the sections before the command that hung are still complete, and
        # only the truncated one is dropped.
        wanted = {key for key, _ in group}
        parts = r.out.split(mark)
        for part in parts[1:-1]:
            key, _, body = part.partition("\n")
            key = key.strip()
            if key in wanted:
                out[key] = body.rstrip("\r\n")
        return out

    # --------------------------------------------------------------- devices

    async def list_devices(self) -> list[Device]:
        """Devices adb currently sees; an empty list if adb itself fails."""
        try:
            return await self.query_devices()
        except AdbError:
            return []

    async def query_devices(self) -> list[Device]:
        """Like list_devices(), but raises AdbError when the answer is unusable.

        "No devices" and "adb did not answer" are different things: the
        watcher must not report every phone as unplugged because the adb
        server was restarting.
        """
        await self.start_server()
        r = await self.raw("devices", "-l", timeout=15)
        if not r.ok:
            raise AdbError(f"adb devices failed: {(r.err or r.out).strip()[:200]}")
        # A server that has only just been spawned has not finished
        # enumerating USB yet, and lists nothing.
        if "daemon not running" in r.out + r.err:
            raise AdbError("adb server was restarting")
        return self._parse_devices(r.out)

    @staticmethod
    def _parse_devices(text: str) -> list[Device]:
        devices: list[Device] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(("*", "List of devices")):
                continue
            m = _DEV_LINE.match(line)
            if not m:
                continue
            serial, state, rest = m.group(1), m.group(2), (m.group(3) or "")
            # Without udev rules adb prints e.g. "no permissions (user in
            # plugdev group; are your udev rules wrong?); see [...] usb:1-2".
            if state == "no" and rest.startswith("permissions"):
                state = "no permissions"
            elif state not in _STATES:
                continue
            attrs = dict(
                kv.split(":", 1) for kv in rest.split() if ":" in kv
            )
            devices.append(Device(
                serial=serial,
                state=state,
                model=attrs.get("model", ""),
                product=attrs.get("product", ""),
                device=attrs.get("device", ""),
                transport=attrs.get("transport_id", ""),
                usb=attrs.get("usb", ""),
            ))
        return devices

    async def wait_ready(self, serial: str, timeout: float = 60.0) -> bool:
        """Wait for the device to reach state `device` with boot completed."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for d in await self.list_devices():
                if d.serial == serial and d.ready:
                    boot = await self.text(serial, "getprop sys.boot_completed",
                                           timeout=5)
                    if boot.strip() == "1":
                        return True
            await asyncio.sleep(0.5)
        return False


Listener = Callable[[str, Device], Awaitable[None] | None]


class DeviceWatcher:
    """Polls `adb devices` and emits attach/detach events.

    Polling is used instead of `adb track-devices` because it survives an adb
    server restart: if adb dies, the next cycle simply finds it again without
    having to rebuild a connection to the host socket.
    """

    def __init__(self, adb: Adb, interval: float = 1.0):
        self.adb = adb
        self.interval = interval
        self._known: dict[str, Device] = {}
        self._listeners: list[Listener] = []
        self._task: asyncio.Task | None = None

    def on_change(self, callback: Listener) -> None:
        """callback(event, device) with event in {attached, changed, detached}."""
        self._listeners.append(callback)

    async def _emit(self, event: str, device: Device) -> None:
        for cb in self._listeners:
            try:
                res = cb(event, device)
                if asyncio.iscoroutine(res):
                    await res
            except asyncio.CancelledError:
                # Only propagate if it is the watcher itself being stopped;
                # a listener cancelling its own work must not end the loop.
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    raise
                log.warning("device listener %r was cancelled", cb)
            except Exception:
                log.exception("device listener %r failed on %s %s",
                              cb, event, device.serial)

    async def _poll_once(self) -> None:
        try:
            current = {d.serial: d for d in await self.adb.query_devices()}
        except AdbError as exc:
            # Keep the last known state: adb not answering does not mean
            # the phones were unplugged.
            log.debug("device poll skipped: %s", exc)
            return

        previous, self._known = self._known, current

        for serial, dev in current.items():
            prev = previous.get(serial)
            if prev is None:
                await self._emit("attached", dev)
            elif prev.state != dev.state:
                await self._emit("changed", dev)

        for serial, dev in previous.items():
            if serial not in current:
                await self._emit("detached", dev)

    async def _loop(self) -> None:
        while True:
            try:
                await self._poll_once()
            except Exception:
                log.exception("device watcher cycle failed")
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="device-watcher")

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    @property
    def devices(self) -> list[Device]:
        return list(self._known.values())
