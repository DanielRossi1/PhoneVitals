"""Functional tests: the automatic ones and the ones needing an operator.

An important distinction between the two groups.

Automatic: the PC starts them and measures the outcome by itself. Vibration is
commanded and verified by reading back that the service accepted it; sensors
are judged by watching whether the values change when they should.

Guided: these need an eye or a hand. No software can decide whether a pixel is
dead or a speaker crackles: it can only display the right pattern and record
what the operator saw. The program therefore sets up the condition, asks a
precise question, and files the answer alongside the objective data collected
in the meantime.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import math
import os
import re
import shlex
import statistics
import struct
import tempfile
import time
import uuid
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .adb import Adb, reap
from .live import (
    DEX_LOCAL, DEX_REMOTE, STREAM_LINE_LIMIT, PollingMonitor, agent_command, parse_json_line,
)

log = logging.getLogger(__name__)

REMOTE_DIR = "/data/local/tmp/pvtest"

# Gravitational acceleration at sea level. It varies by about 0.5% between
# equator and poles: irrelevant against the tolerance used here.
GRAVITY = 9.807

# Earth magnetic field strength in microtesla. It runs from about 25 uT near
# the magnetic equator to 65 uT at the poles; the bounds are widened because a
# workshop always has metal masses nearby.
EARTH_FIELD_MIN = 15.0
EARTH_FIELD_MAX = 90.0

SENSOR_TYPE = {
    "accelerometer": 1,
    "magnetic": 2,
    "gyroscope": 4,
    "light": 5,
    "pressure": 6,
    "proximity": 8,
}


def _as_number(value: Any, default: float, low: float, high: float) -> float:
    """A numeric parameter from the interface, clamped to a sane range."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number):
        return default
    return min(high, max(low, number))


# -------------------------------------------------------------------- images

def solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Generate a solid-colour PNG with no external dependencies.

    A minimal PNG is signature + IHDR + IDAT + IEND. Each image row is preceded
    by a filter byte (0 = no filter), and the whole thing is zlib compressed.
    For a flat colour that is a handful of lines, and it avoids dragging in an
    imaging library.
    """
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    r, g, b = rgb
    row = b"\x00" + bytes((r, g, b)) * width      # filter 0 + RGB pixels
    raw = row * height

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def gradient_png(width: int, height: int) -> bytes:
    """Grey gradient: reveals banding and panel non-uniformity."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    rows = []
    for y in range(height):
        level = int(255 * y / max(1, height - 1))
        rows.append(b"\x00" + bytes((level, level, level)) * width)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
        + chunk(b"IEND", b"")
    )


SCREEN_PATTERNS = [
    ("white", (255, 255, 255),
     "Look for dark spots or patches that are more yellow or blue. Dead pixels "
     "show up best on a white field, as does backlight non-uniformity."),
    ("black", (0, 0, 0),
     "Look for bright spots (pixels stuck on) and light halos at the edges. On "
     "OLED, black should be completely off and uniform."),
    ("red", (255, 0, 0),
     "Every pixel lights only its red subpixel: black dots here indicate failed "
     "red subpixels."),
    ("green", (0, 255, 0),
     "The same check on the green channel, the one the eye is most sensitive "
     "to: defects stand out more."),
    ("blue", (0, 0, 255),
     "Blue channel check, the subpixel that ages first on OLED."),
    ("gradient", None,
     "The gradient should be continuous. Hard bands or steps indicate a "
     "lower-grade panel or a driver other than the original."),
]


# ---------------------------------------------------------------------- model

@dataclass
class TestResult:
    test_id: str
    title: str
    kind: str                     # automatic | guided
    status: str = "pending"       # pending | running | passed | failed | inconclusive
    outcome_detail: str = ""
    measurements: dict[str, Any] = field(default_factory=dict)
    started_at: float | None = None
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.test_id,
            "title": self.title,
            "kind": self.kind,
            "status": self.status,
            "detail": self.outcome_detail,
            "measurements": self.measurements,
            "duration": (
                round(self.finished_at - self.started_at, 1)
                if self.started_at and self.finished_at else None
            ),
        }


class TestSuite:
    def __init__(self, adb: Adb, serial: str, snapshot: dict,
                 on_event: Callable):
        self.adb = adb
        self.serial = serial
        self.snapshot = snapshot
        self.on_event = on_event
        self.results: dict[str, TestResult] = {}
        self._patterns: dict[str, str] = {}
        self._pushed_patterns = False
        self._pushed_dex = False
        # Device settings changed by a test, with the value to put back.
        self._saved_settings: dict[str, str] = {}
        self._speaker_answered = asyncio.Event()

    async def _emit(self, payload: dict) -> None:
        res = self.on_event(payload)
        if asyncio.iscoroutine(res):
            await res

    async def _publish(self, result: TestResult) -> None:
        self.results[result.test_id] = result
        await self._emit({"type": "test_update", "test": result.to_dict()})

    # ----------------------------------------------------------- catalogue

    def catalogue(self) -> list[dict[str, Any]]:
        """List of tests available for *this* device.

        The catalogue is dynamic: there is no point offering the barometer test
        to a phone that does not have one.
        """
        has = (self.snapshot.get("sensors") or {}).get("has") or {}
        input_info = self.snapshot.get("input") or {}
        vib = self.snapshot.get("vibrator") or {}
        cams = (self.snapshot.get("cameras") or {}).get("count") or 0

        items = [
            # The three automatic ones come first: they produce a result
            # without asking anything, so they are worth running first.
            {"id": "sensor_physics", "title": "Inertial sensor calibration",
             "kind": "automatic",
             "available": has.get("accelerometer", False),
             "description": "Rest the phone and measure: gravity must come out "
                            "at 9.81 m/s\u00b2, the gyroscope at rest must read "
                            "zero, the magnetic field must be within Earth "
                            "values."},
            {"id": "vibration_imu", "title": "Vibration measured by the IMU",
             "kind": "automatic",
             "available": bool(vib.get("present")) and has.get("accelerometer", False),
             "description": "Command the motor and use the accelerometer to "
                            "measure whether the phone actually moved. No "
                            "confirmation needed: either the shaking is there or "
                            "it is not."},
            {"id": "wifi_scan", "title": "Wi-Fi reception",
             "kind": "automatic", "available": True,
             "description": "Run a scan: the networks found and their signal "
                            "strength prove the antenna receives, on both "
                            "bands."},
            {"id": "storage_speed", "title": "Storage write speed",
             "kind": "automatic", "available": True,
             "description": "Write 256 MB to internal storage and time it, "
                            "flushed to the chip: a worn or counterfeit memory "
                            "is far slower than its type should be."},
            {"id": "charging", "title": "Charging",
             "kind": "automatic", "available": True,
             "description": "With the USB cable in, check that current actually "
                            "flows into the battery: port, cable path and "
                            "charging circuit in one go."},
            {"id": "stress", "title": "Processor under load",
             "kind": "automatic", "available": True,
             "description": "Load every core for 30 seconds: each must reach its "
                            "rated frequency, the temperature is followed and "
                            "the phone must not restart."},
            {"id": "speaker", "title": "Loudspeaker",
             "kind": "automatic", "available": True, "needs": "microphone",
             "description": "The phone plays three tones and the computer's "
                            "microphone listens for them: hold the phone near "
                            "the computer, speaker facing it."},
            {"id": "microphone", "title": "Microphone",
             "kind": "automatic", "available": True, "needs": "speakers",
             "description": "The computer plays three tones and the phone records "
                            "them: the phone's microphone must pick each one up "
                            "above the room noise."},
            {"id": "bluetooth", "title": "Bluetooth radio",
             "kind": "automatic", "available": True,
             "description": "Switch Bluetooth on and check the radio comes up, then "
                            "put it back as it was."},
            {"id": "cellular", "title": "Mobile network",
             "kind": "automatic", "available": True,
             "description": "With a SIM inserted, check the phone registers on a "
                            "network and how strong the signal is."},
            {"id": "gnss", "title": "Satellite positioning",
             "kind": "automatic", "available": True,
             "description": "Switch the GNSS receiver on and wait for satellites "
                            "(up to 45 seconds; works best near a window)."},
            {"id": "camera", "title": "Cameras", "kind": "guided", "available": cams > 0,
             "description": "Take a picture with every camera and show them: check "
                            "each is sharp and clean, with no spots or cracks."},
            {"id": "vibration", "title": "Vibration", "kind": "guided",
             "available": bool(vib.get("present")),
             "description": "Drive the motor at different strengths and "
                            "durations; you confirm whether you feel it."},
            {"id": "buttons", "title": "Physical buttons", "kind": "guided",
             "available": bool(input_info.get("key_devices")),
             "description": "Press volume up, volume down and power: the raw "
                            "kernel events are read and shown on screen."},
            {"id": "touch", "title": "Touch grid", "kind": "guided",
             "available": bool(input_info.get("touchscreen")),
             "description": "Run a finger over the whole surface: the cells "
                            "reached are coloured in, revealing dead zones."},
            {"id": "multitouch", "title": "Multitouch", "kind": "guided",
             "available": bool(input_info.get("touchscreen")),
             "description": "Put several fingers down together: counts how many "
                            "distinct points the digitizer can track."},
            {"id": "screen", "title": "Pixels and screen uniformity",
             "kind": "guided", "available": True,
             "description": "Displays full-screen white, black, red, green, blue "
                            "and a gradient to find faulty pixels."},
            {"id": "imu", "title": "Accelerometer and gyroscope",
             "kind": "guided", "available": has.get("accelerometer", False),
             "description": "Rotate and shake the phone: checks that the values "
                            "react on all three axes."},
            {"id": "proximity", "title": "Proximity sensor",
             "kind": "guided", "available": has.get("proximity", False),
             "description": "Cover the sensor near the earpiece: the value must "
                            "change and come back."},
            {"id": "light", "title": "Light sensor", "kind": "guided",
             "available": has.get("light", False),
             "description": "Cover and uncover the sensor: the lux reading must "
                            "follow the ambient light."},
            {"id": "magnetometer", "title": "Compass", "kind": "guided",
             "available": has.get("magnetic_field", False),
             "description": "Rotate the phone horizontally: the magnetic field "
                            "must vary consistently."},
            {"id": "audio", "title": "Speakers and microphone",
             "kind": "guided", "available": True,
             "description": "Plays tones at different frequencies on each "
                            "speaker and checks the recording."},
            {"id": "torch", "title": "Flash", "kind": "guided",
             "available": cams > 0,
             "description": "Turns the flash on and off: you confirm whether it "
                            "lights up."},
        ]
        return items

    # ------------------------------------------------------ individual tests

    async def run(self, test_id: str, **params) -> dict[str, Any]:
        handler = {
            "sensor_physics": self._test_sensor_physics,
            "vibration_imu": self._test_vibration_imu,
            "wifi_scan": self._test_wifi_scan,
            "vibration": self._test_vibration,
            "screen": self._test_screen,
            "torch": self._test_torch,
            "buttons": self._test_buttons,
            "storage_speed": self._test_storage_speed,
            "charging": self._test_charging,
            "stress": self._test_stress,
            "speaker": self._test_speaker,
            "microphone": self._test_microphone,
            "bluetooth": self._test_bluetooth,
            "cellular": self._test_cellular,
            "gnss": self._test_gnss,
            "camera": self._test_camera,
        }.get(test_id)

        if handler is None:
            # Sensor- and touch-based tests are driven by the live stream the
            # server manages: only the opening is recorded here.
            result = TestResult(test_id, test_id, "guided", status="running",
                                started_at=time.time())
            await self._publish(result)
            return result.to_dict()

        try:
            return await handler(**params)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Without this the test would stay "running" in the interface
            # forever: the caller is a fire-and-forget task.
            log.exception("test %s failed", test_id)
            result = self.results.get(test_id) or TestResult(
                test_id, test_id, "automatic", started_at=time.time())
            result.status = "failed"
            result.outcome_detail = (
                f"The test could not be completed: {type(exc).__name__}: {exc}")
            result.finished_at = time.time()
            await self._publish(result)
            return result.to_dict()

    async def record_outcome(self, test_id: str, passed: bool, detail: str = "",
                             status: str | None = None) -> dict[str, Any]:
        """Record the operator's judgement on a guided test, or the interface's
        measurement for the loudspeaker test. `status` may only downgrade a
        verdict to "inconclusive"."""
        result = self.results.get(test_id) or TestResult(test_id, test_id, "guided")
        result.status = "inconclusive" if status == "inconclusive" else (
            "passed" if passed else "failed")
        result.outcome_detail = detail
        result.finished_at = time.time()
        if result.started_at is None:
            result.started_at = result.finished_at
        if test_id == "screen":
            await self._restore_settings()
        await self._publish(result)
        if test_id == "speaker":
            self._speaker_answered.set()
        return result.to_dict()

    # ------------------------------------------------------ device helpers

    async def _ensure_dex(self) -> bool:
        """Make sure the agent is on the phone, pushing it if it is not.

        A live session pushes and removes the same file on its own schedule,
        so presence is checked every time instead of being remembered. The
        suite removes the file on cleanup only if it ever had to push it.
        """
        if not os.path.isfile(DEX_LOCAL):
            return False
        present = await self.adb.shell(
            self.serial, f"[ -f {DEX_REMOTE} ] && echo yes", timeout=10)
        if "yes" in present.out:
            return True
        r = await self.adb.raw("-s", self.serial, "push", DEX_LOCAL, DEX_REMOTE,
                               timeout=60)
        self._pushed_dex = True
        return r.ok

    async def _change_setting(self, namespace: str, key: str, value: str) -> None:
        """Set a device setting, remembering the original for cleanup."""
        name = f"{namespace} {key}"
        if name not in self._saved_settings:
            old = await self.adb.text(self.serial, f"settings get {name}",
                                      timeout=10)
            if old and old != "null":
                self._saved_settings[name] = old
        await self.adb.shell(self.serial, f"settings put {name} {value}",
                             timeout=10)

    async def _restore_settings(self) -> None:
        saved, self._saved_settings = self._saved_settings, {}
        for name, value in saved.items():
            await self.adb.shell(
                self.serial, f"settings put {name} {shlex.quote(value)}",
                timeout=10)

    # ------------------------------------------------------- sensor capture

    # How long the agent may take to deliver its first sample.
    AGENT_STARTUP_S = 10.0

    async def _capture(self, types: list[int], seconds: float,
                       during: Callable[[], Awaitable[None]] | None = None,
                       ) -> dict[int, list[dict]]:
        """Record samples from the given sensors over an interval.

        Starts a copy of the agent dedicated to this measurement rather than
        hooking into the "Live" tab stream: that stream may be stopped, may
        have different sensors registered, and above all must not be disturbed
        by a test. Two agent processes coexist without trouble; they are two
        readers of the same HAL.

        `during` is a coroutine run while recording is in progress: the
        vibration test needs it, because it has to drive the motor and see the
        effect in the same trace.

        The clock starts at the first sample, not at launch: app_process takes
        from under one to a few seconds to bring the agent up, and that delay
        must neither eat into the measurement nor shift `during` relative to
        the trace. Sample times `t` and `during` share that origin.
        """
        samples: dict[int, list[dict]] = {t: [] for t in types}
        await self._ensure_dex()

        tag = f"pv-test-{uuid.uuid4().hex[:12]}"
        cmd = agent_command("sensors", ",".join(str(t) for t in types), tag)
        proc = await asyncio.create_subprocess_exec(
            self.adb.adb, "-s", self.serial, "shell", cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=STREAM_LINE_LIMIT,
        )
        assert proc.stdout and proc.stdin

        spawned = time.monotonic()
        started: float | None = None
        side_task: asyncio.Task | None = None

        try:
            while True:
                if started is None:
                    remaining = self.AGENT_STARTUP_S - (time.monotonic() - spawned)
                else:
                    remaining = seconds - (time.monotonic() - started)
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(proc.stdout.readline(),
                                                 timeout=max(0.2, remaining))
                except TimeoutError:
                    break
                except ValueError:
                    continue            # over-long line, already discarded
                if not raw:
                    break
                event = parse_json_line(raw)
                if not event or event.get("type") != "sensor":
                    continue
                kind = event.get("sensorType")
                values = event.get("values") or []
                if kind not in samples or not isinstance(values, list):
                    continue
                try:
                    # A null is a NaN on the phone side: dropping the sample
                    # is better than letting a fake zero into the statistics.
                    vector = [float(x) for x in values]
                except (TypeError, ValueError):
                    continue
                if started is None:
                    started = time.monotonic()
                    if during:
                        side_task = asyncio.create_task(during())
                samples[kind].append({"t": time.monotonic() - started,
                                      "v": vector})
        finally:
            if side_task:
                try:
                    await asyncio.wait_for(side_task, timeout=3)
                except Exception:
                    log.exception("side task of the sensor capture failed")
            await self._stop_agent(proc, tag)

        return samples

    async def _stop_agent(self, proc: asyncio.subprocess.Process, tag: str) -> None:
        """Ask a streaming agent to exit, and make sure it did on the phone."""
        try:
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.write(b"stop\n")
                await asyncio.wait_for(proc.stdin.drain(), timeout=2)
                proc.stdin.close()
            await asyncio.wait_for(proc.wait(), timeout=2)
            return
        except (ConnectionError, RuntimeError, TimeoutError):
            pass
        await reap(proc)
        # Killing the local adb client does not reliably kill the remote
        # process: find it by its tag. The bracket keeps pkill from matching
        # the shell that runs it.
        pattern = shlex.quote(f"[{tag[0]}]{tag[1:]}")
        await self.adb.shell(self.serial, f"pkill -f {pattern} 2>/dev/null; true",
                             timeout=8)

    @staticmethod
    def _magnitudes(samples: list[dict]) -> list[float]:
        out = []
        for s in samples:
            v = s["v"]
            if len(v) >= 3:
                out.append(math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2))
        return out

    @staticmethod
    def _rate_hz(samples: list[dict]) -> float:
        if len(samples) < 2:
            return 0.0
        span = samples[-1]["t"] - samples[0]["t"]
        return round((len(samples) - 1) / span, 1) if span > 0 else 0.0

    # -- inertial sensor calibration -----------------------------------------

    async def _test_sensor_physics(self, seconds: float = 5.0, **_) -> dict[str, Any]:
        """Check the sensors against known physical quantities.

        This is the most informative test in the program, because it does not
        ask "does the value move?" but "is the value right?". The difference
        matters: a disconnected sensor replaced by a simulated value moves
        perfectly well, but it does not reproduce 9.81 m/s^2.

        Three independent measurements:
        - the magnitude of the acceleration vector at rest *must* equal g;
        - the gyroscope at rest *must* read zero, and its departure from zero
          is the drift, a measurable defect;
        - the magnetic field *must* lie within the Earth range.
        A sensor that always returns the exact same number is not a sensor: it
        is a constant, and zero variance exposes it.

        Careful with false alarms: if the phone is moved during the
        measurement, the acceleration magnitude is not g, and inferring a fault
        from that would be wrong. That is why variance is examined *before* the
        mean, and if the phone was moving the test says so instead of failing.
        """
        result = TestResult("sensor_physics", "Inertial sensor calibration",
                            "automatic", status="running", started_at=time.time())
        await self._publish(result)

        wanted = [SENSOR_TYPE["accelerometer"], SENSOR_TYPE["gyroscope"],
                  SENSOR_TYPE["magnetic"]]
        seconds = _as_number(seconds, 5.0, 1.0, 60.0)
        samples = await self._capture(wanted, seconds)

        measures: dict[str, Any] = {}
        problems: list[str] = []
        notes: list[str] = []

        # -- accelerometer ------------------------------------------------
        accel = samples.get(SENSOR_TYPE["accelerometer"], [])
        mags = self._magnitudes(accel)
        if not mags:
            problems.append("the accelerometer produced no samples")
        else:
            mean = statistics.fmean(mags)
            spread = statistics.pstdev(mags) if len(mags) > 1 else 0.0
            measures["accelerometer"] = {
                "samples": len(accel),
                "rate_hz": self._rate_hz(accel),
                "mean_magnitude_ms2": round(mean, 3),
                "deviation_ms2": round(spread, 4),
                "error_vs_g_percent": round(abs(mean - GRAVITY) / GRAVITY * 100, 2),
            }

            if spread == 0.0 and len(mags) > 10:
                problems.append(
                    "the accelerometer always returns the same value: no real "
                    "sensor has exactly zero noise")
            elif spread > 0.8:
                notes.append(
                    "the phone was moving during the measurement, so the "
                    "comparison against gravity is not valid: rest it on a "
                    "steady surface and repeat")
            elif abs(mean - GRAVITY) / GRAVITY > 0.05:
                problems.append(
                    f"at rest the accelerometer reads {mean:.2f} m/s^2 instead "
                    f"of {GRAVITY:.2f}: it is out of calibration by "
                    f"{abs(mean - GRAVITY) / GRAVITY * 100:.1f}%")
            else:
                notes.append(
                    f"measured gravity ({mean:.2f} m/s^2) matches the expected "
                    f"value to within "
                    f"{abs(mean - GRAVITY) / GRAVITY * 100:.1f}%")

        # -- gyroscope ----------------------------------------------------
        gyro = samples.get(SENSOR_TYPE["gyroscope"], [])
        if mags := self._magnitudes(gyro):
            bias = statistics.fmean(mags)
            spread = statistics.pstdev(mags) if len(mags) > 1 else 0.0
            measures["gyroscope"] = {
                "samples": len(gyro),
                "rate_hz": self._rate_hz(gyro),
                "mean_drift_rad_s": round(bias, 5),
                "noise_rad_s": round(spread, 5),
            }
            if spread == 0.0 and len(mags) > 10:
                problems.append("the gyroscope returns a constant value")
            elif bias > 0.35:
                notes.append(
                    "the gyroscope reads rotation even at rest: either the "
                    "phone was moving, or it has significant drift")
            elif bias > 0.05:
                notes.append(
                    f"gyroscope drift at rest: {bias:.3f} rad/s, small but "
                    "measurable")
            else:
                notes.append("the gyroscope at rest reads zero as it should")

        # -- magnetometer -------------------------------------------------
        mag = samples.get(SENSOR_TYPE["magnetic"], [])
        if mags := self._magnitudes(mag):
            mean = statistics.fmean(mags)
            spread = statistics.pstdev(mags) if len(mags) > 1 else 0.0
            measures["magnetometer"] = {
                "samples": len(mag),
                "rate_hz": self._rate_hz(mag),
                "mean_field_ut": round(mean, 2),
                "noise_ut": round(spread, 3),
            }
            if spread == 0.0 and len(mags) > 10:
                problems.append("the magnetometer returns a constant value")
            elif not EARTH_FIELD_MIN <= mean <= EARTH_FIELD_MAX:
                problems.append(
                    f"the measured magnetic field ({mean:.1f} uT) is outside "
                    f"the Earth range ({EARTH_FIELD_MIN:.0f}-"
                    f"{EARTH_FIELD_MAX:.0f} uT): either the sensor is out of "
                    "calibration, or a magnet or metal mass is very close")
            else:
                notes.append(
                    f"the measured magnetic field ({mean:.1f} uT) is within "
                    "Earth values")

        result.measurements = measures
        result.finished_at = time.time()

        if not measures:
            result.status = "failed"
            result.outcome_detail = (
                "No samples received. The agent on the phone did not respond: "
                "check the Live tab for the reason."
            )
        elif problems:
            result.status = "failed"
            result.outcome_detail = "Anomalies: " + "; ".join(problems) + "."
        else:
            result.status = "passed"
            result.outcome_detail = " · ".join(n.capitalize() for n in notes) + "."

        await self._publish(result)
        return result.to_dict()

    # -- measured vibration ----------------------------------------------------

    async def _test_vibration_imu(self, **_) -> dict[str, Any]:
        """Drive the motor and measure its effect with the accelerometer.

        The guided vibration test can only say the *service* accepted the
        command: if the motor is disconnected, the service accepts it anyway.
        Here the accelerometer is recorded before and during the pulse and the
        agitation is compared. A spinning motor produces an oscillation at a
        couple of hundred hertz which the accelerometer, even sampling more
        slowly, turns into an unmistakable rise in variance.

        If the phone is held rather than resting, the reference measurement is
        already noisy and the ratio falls: that is why the absolute increase is
        considered too, not just the ratio.
        """
        result = TestResult("vibration_imu", "Vibration measured by the IMU",
                            "automatic", status="running", started_at=time.time())
        await self._publish(result)

        baseline_s, pulse_s = 1.5, 1.2
        # Seconds on the capture clock: when the accepted command was sent,
        # and when adb confirmed it.
        marks: dict[str, float] = {}

        async def fire() -> None:
            t0 = time.monotonic()
            # The initial silence is the reference: measure the quiet first,
            # then start the motor.
            await asyncio.sleep(baseline_s)
            for cmd in (f"cmd vibrator_manager synced oneshot {int(pulse_s * 1000)}",
                        f"cmd vibrator vibrate {int(pulse_s * 1000)}"):
                sent = time.monotonic() - t0
                r = await self.adb.shell(self.serial, cmd, timeout=10)
                if r.ok and "Error" not in r.out and "Unknown command" not in r.out:
                    marks["sent"] = sent
                    marks["acked"] = time.monotonic() - t0
                    break
            await self._emit({"type": "test_step", "test": "vibration_imu",
                              "step": "pulse sent", "accepted": "sent" in marks})

        # Generous tail: the pulse must fit in the trace even when the command
        # goes out late (a refused first attempt costs another round trip).
        total = baseline_s + pulse_s + 2.0
        samples = await self._capture([SENSOR_TYPE["accelerometer"]], total,
                                      during=fire)
        accel = samples.get(SENSOR_TYPE["accelerometer"], [])

        if len(accel) < 20:
            result.status = "failed"
            result.finished_at = time.time()
            result.outcome_detail = (
                "Not enough accelerometer samples to measure the vibration. "
                "Check that the agent is running."
            )
            await self._publish(result)
            return result.to_dict()

        # The pulse window is anchored to when the accepted command went out,
        # not to a theoretical time: when the modern vibrator command is
        # refused, the legacy one costs another adb round trip. The motor
        # starts somewhere between sending and acknowledgement -- but some
        # releases only acknowledge once the vibration is over, so a slow
        # acknowledgement says nothing about when the motor started and the
        # usual shell latency is assumed instead.
        sent = marks.get("sent", baseline_s)
        latency = marks.get("acked", sent) - sent
        quiet_end = sent - 0.15
        pulse_start = sent + (latency + 0.05 if latency < 0.4 else 0.3)
        pulse_end = sent + pulse_s

        def spread(lo: float, hi: float) -> tuple[float, int]:
            window = [s for s in accel if lo <= s["t"] <= hi]
            mags = self._magnitudes(window)
            if len(mags) < 3:
                return 0.0, len(mags)
            return statistics.pstdev(mags), len(mags)

        quiet, n_quiet = spread(0.0, quiet_end)
        during, n_during = spread(pulse_start, pulse_end)
        enough = n_quiet >= 5 and n_during >= 5

        ratio = (during / quiet) if quiet > 1e-4 else (during / 1e-4 if during else 0.0)
        delta = during - quiet

        result.measurements = {
            "total_samples": len(accel),
            "rate_hz": self._rate_hz(accel),
            "agitation_at_rest_ms2": round(quiet, 4),
            "agitation_during_ms2": round(during, 4),
            "rest_samples": n_quiet,
            "pulse_samples": n_during,
            "ratio": round(ratio, 1),
            "command_accepted": "sent" in marks,
        }
        result.finished_at = time.time()

        # Two criteria ORed together: the ratio catches the clean case (phone
        # resting), the absolute increase the one where it is held.
        detected = (ratio >= 3.0 and delta > 0.02) or delta > 0.25

        if detected:
            result.status = "passed"
            result.outcome_detail = (
                f"Vibration detected physically: the agitation measured by the "
                f"accelerometer goes from {quiet:.3f} to {during:.3f} m/s^2, "
                f"{ratio:.0f} times as much. The motor really moved - this is a "
                "measurement, not a verbal confirmation."
            )
        elif "sent" not in marks:
            result.status = "failed"
            result.outcome_detail = (
                "The vibration service refused the command: the motor was not "
                "even driven."
            )
        elif not enough:
            # Too few samples to tell a still motor from a missed window: a
            # verdict of "faulty" here would be a guess.
            result.status = "inconclusive"
            result.outcome_detail = (
                f"Not enough accelerometer samples fell inside the measurement "
                f"windows ({n_quiet} at rest, {n_during} during the pulse) to "
                "judge the motor. Repeat the test with the phone resting on a "
                "rigid surface."
            )
        else:
            result.status = "failed"
            result.outcome_detail = (
                f"The command was accepted but the accelerometer recorded no "
                f"shaking (from {quiet:.3f} to {during:.3f} m/s^2). Either the "
                "motor is disconnected or faulty, or the phone was held in a "
                "way that damped the vibration: rest it on a rigid surface and "
                "repeat."
            )

        await self._publish(result)
        return result.to_dict()

    # -- Wi-Fi reception -------------------------------------------------------

    # The columns ("BSSID  Frequency  RSSI  Age(sec)  SSID  Flags" on recent
    # releases) change between versions, so the fields recognisable by shape
    # are matched instead: a MAC, a frequency in MHz, a negative level.
    _BSSID_RE = re.compile(r"\b([0-9a-f]{2}(?::[0-9a-f]{2}){5})\b", re.I)
    _FREQ_RE = re.compile(r"\b(2[34]\d\d|5[0-9]\d\d|6[0-9]\d\d|7[01]\d\d)\b")
    _RSSI_RE = re.compile(r"(-\d{2,3})\b")
    _WIFI_OFF_RE = re.compile(r"^\s*wi-?fi is (?:disabled|off)\b", re.I | re.M)

    async def _test_wifi_scan(self, **_) -> dict[str, Any]:
        """Wi-Fi scan: objective proof that the receiver receives.

        A network listed with its signal strength means the antenna demodulated
        a beacon transmitted by equipment we did not touch. No association is
        needed, no password: reception alone is enough. And because the two
        bands use distinct radio chains, seeing networks on both verifies both.
        """
        result = TestResult("wifi_scan", "Wi-Fi reception", "automatic",
                            status="running", started_at=time.time())
        await self._publish(result)

        # Only the headline line counts: further down the status mentions
        # other things that are "disabled" while Wi-Fi itself is on, and the
        # radio would then be switched off at the end of the test.
        state = await self.adb.shell(self.serial, "cmd wifi status", timeout=15)
        was_off = bool(self._WIFI_OFF_RE.search(state.out))
        try:
            if was_off:
                await self.adb.shell(self.serial, "svc wifi enable", timeout=15)
                await asyncio.sleep(3.0)

            await self.adb.shell(self.serial, "cmd wifi start-scan", timeout=20)
            await asyncio.sleep(4.0)
            scan = await self.adb.shell(self.serial, "cmd wifi list-scan-results",
                                        timeout=25)
        finally:
            # Leave the radio as it was found.
            if was_off:
                await self.adb.shell(self.serial, "svc wifi disable", timeout=15)

        networks: list[dict[str, Any]] = []
        for line in scan.out.splitlines():
            bssid = self._BSSID_RE.search(line)
            freq = self._FREQ_RE.search(line)
            if not (bssid and freq):
                continue
            rssi = self._RSSI_RE.search(line)
            mhz = int(freq.group(1))
            networks.append({
                "bssid": bssid.group(1),
                "mhz": mhz,
                # The 6 GHz band starts at 5925 MHz (channel 1 is 5955).
                "band": ("2.4 GHz" if mhz < 2500
                         else "5 GHz" if mhz < 5925 else "6 GHz"),
                "rssi_dbm": int(rssi.group(1)) if rssi else None,
            })

        bands = sorted({n["band"] for n in networks})
        levels = [n["rssi_dbm"] for n in networks if n["rssi_dbm"] is not None]

        result.measurements = {
            "networks_found": len(networks),
            "bands": bands,
            "best_rssi_dbm": max(levels) if levels else None,
            "worst_rssi_dbm": min(levels) if levels else None,
            "wifi_was_off": was_off,
        }
        result.finished_at = time.time()

        if networks:
            result.status = "passed"
            strength = (f", strength from {max(levels)} to {min(levels)} dBm"
                        if levels else "")
            result.outcome_detail = (
                f"The receiver saw {len(networks)} networks on "
                f"{', '.join(bands)}{strength}. The antenna and receive chain "
                "work"
                + (" on each of these bands." if len(bands) > 1 else
                   ". No networks on the other band: there may simply be none "
                   "nearby, so this is not in itself a defect.")
            )
        else:
            result.status = "failed"
            result.outcome_detail = (
                "No networks found. There are three possible causes: Wi-Fi is "
                "off, the scan is blocked because location is disabled (Android "
                "requires it for scanning), or the receiver does not work. It is "
                "worth turning location on and repeating before concluding."
            )

        await self._publish(result)
        return result.to_dict()

    # -- vibration (guided) -------------------------------------------------

    async def _test_vibration(self, **_) -> dict[str, Any]:
        result = TestResult("vibration", "Vibration", "guided",
                            status="running", started_at=time.time())
        await self._publish(result)

        # The service name changed in Android 12: try the new one and fall
        # back to the old. (label, duration in ms, repetitions)
        sequences = [
            ("short pulse", 120, 1),
            ("long pulse", 600, 1),
            ("triple", 100, 3),
        ]

        accepted = []
        for label, ms, repeat in sequences:
            ok, response = False, ""
            for i in range(repeat):
                if i:
                    await asyncio.sleep(0.25)
                r = await self.adb.shell(
                    self.serial, f"cmd vibrator_manager synced oneshot {ms}",
                    timeout=12)
                ok = r.ok and "Error" not in r.out and "Unknown command" not in r.out
                if not ok:
                    r = await self.adb.shell(
                        self.serial, f"cmd vibrator vibrate {ms}", timeout=12)
                    ok = r.ok and "Error" not in r.out
                response = (r.out or r.err).strip()[:120]
                if not ok:
                    break
            accepted.append({"sequence": label, "accepted": ok,
                             "response": response})
            await self._emit({"type": "test_step", "test": "vibration",
                              "step": label, "accepted": ok})
            await asyncio.sleep(1.0)

        result.measurements = {"sequences": accepted}
        any_ok = any(a["accepted"] for a in accepted)
        if not any_ok:
            result.status = "failed"
            result.outcome_detail = (
                "The vibration service refused every command. The motor may be "
                "disconnected or absent."
            )
            result.finished_at = time.time()
        else:
            result.outcome_detail = (
                "A short, a long and a triple pulse were sent. The service "
                "accepted them, but only you can confirm the motor actually "
                "moved."
            )
        await self._publish(result)
        return result.to_dict()

    # -- screen -------------------------------------------------------------

    async def _push_patterns(self) -> None:
        """Generate the patterns at the real resolution and copy them across."""
        res = (self.snapshot.get("display") or {}).get("resolution") or {}
        w = _as_number(res.get("width"), 1080, 16, 16384)
        h = _as_number(res.get("height"), 2400, 16, 16384)
        # A full-resolution PNG is needlessly heavy to transfer: for a flat
        # colour a small image is enough, and the viewer scales it to full
        # screen without losing uniformity.
        sw, sh = max(2, int(w) // 4), max(2, int(h) // 4)

        # Flagged before anything is created, so cleanup also removes a
        # directory left half-filled by a failed push.
        self._pushed_patterns = True
        await self.adb.shell(self.serial, f"mkdir -p {REMOTE_DIR}", timeout=10)

        with tempfile.TemporaryDirectory(prefix="phonevitals-") as tmp:
            for name, rgb, _desc in SCREEN_PATTERNS:
                if name in self._patterns:
                    continue
                data = gradient_png(sw, sh) if rgb is None else solid_png(sw, sh, rgb)
                local = os.path.join(tmp, f"{name}.png")
                with open(local, "wb") as fh:
                    fh.write(data)
                remote = f"{REMOTE_DIR}/{name}.png"
                r = await self.adb.raw("-s", self.serial, "push", local, remote,
                                       timeout=30)
                if r.ok:
                    self._patterns[name] = remote

    async def _test_screen(self, pattern: str = "white", **_) -> dict[str, Any]:
        result = TestResult("screen", "Pixels and screen uniformity", "guided",
                            status="running", started_at=time.time())
        await self._publish(result)

        # The name ends up in a shell command: only known patterns pass.
        names = [n for n, _c, _d in SCREEN_PATTERNS]
        if pattern not in names:
            pattern = names[0]

        if pattern not in self._patterns:
            await self._push_patterns()
        remote = self._patterns.get(pattern, f"{REMOTE_DIR}/{pattern}.png")

        # Maximum brightness: defects are far easier to see. Automatic
        # brightness would override it, so that is switched off too; both are
        # put back when the operator gives the verdict, or on cleanup.
        await self._change_setting("system", "screen_brightness_mode", "0")
        await self._change_setting("system", "screen_brightness", "255")

        # Chain of attempts: opening an image full screen depends on which
        # gallery is installed, so several routes are tried and the one that
        # worked is reported.
        uri = shlex.quote(f"file://{remote}")
        attempts = [
            ("image viewer",
             f"am start -a android.intent.action.VIEW -d {uri} -t image/png "
             "--grant-read-uri-permission"),
            ("generic viewer",
             f"am start -a android.intent.action.VIEW -d {uri}"),
        ]

        opened_with = None
        for label, cmd in attempts:
            r = await self.adb.shell(self.serial, cmd, timeout=15)
            output = (r.out + r.err).lower()
            if r.ok and "error" not in output and "exception" not in output:
                opened_with = label
                break

        result.measurements = {
            "pattern": pattern,
            "opened_with": opened_with,
            "remote_path": remote,
        }

        if opened_with is None:
            result.status = "failed"
            result.outcome_detail = (
                "The pattern could not be opened full screen: no viewer accepted "
                "the file. On this device the screen test has to be done "
                "manually."
            )
            result.finished_at = time.time()
            await self._restore_settings()
        else:
            desc = next((d for n, _c, d in SCREEN_PATTERNS if n == pattern), "")
            result.outcome_detail = desc
        await self._publish(result)
        return result.to_dict()

    # -- torch -----------------------------------------------------------------

    async def _test_torch(self, **_) -> dict[str, Any]:
        result = TestResult("torch", "Flash", "guided",
                            status="running", started_at=time.time())
        await self._publish(result)

        await self._ensure_dex()

        # Camera service switches the torch off as soon as the process that
        # turned it on dies, and the agent exits right after the command: the
        # extra argument asks it to hold the light for that long first. Older
        # agent builds ignore it.
        hold_ms = 800
        blinks = 0
        for state in ("on", "off", "on", "off"):
            args = ("torch", state, str(hold_ms)) if state == "on" else ("torch", state)
            r = await self.adb.shell(self.serial, agent_command(*args), timeout=20)
            if '"type":"torch"' in r.out.replace(" ", ""):
                blinks += 1
            await self._emit({"type": "test_step", "test": "torch",
                              "step": f"torch {state}", "accepted": r.ok})
            await asyncio.sleep(0.8)

        result.measurements = {"commands_accepted": blinks}
        if blinks == 0:
            result.status = "failed"
            result.outcome_detail = (
                "Torch control did not respond. Check that the agent started "
                "correctly."
            )
            result.finished_at = time.time()
        else:
            result.outcome_detail = (
                "The flash was blinked twice. Can you confirm you saw it?"
            )
        await self._publish(result)
        return result.to_dict()

    # -- storage ---------------------------------------------------------------

    BENCH_FILE = "/data/local/tmp/pvbench"
    BENCH_MB = 256
    # Sequential write, flushed, below which a chip of that type is suspect.
    # UFS 2.x writes 150+ MB/s and eMMC 5.1 around 50-150 MB/s even on budget
    # phones; these floors leave room for a busy phone.
    MIN_WRITE_MBS = {"UFS": 60.0, "eMMC": 20.0}

    async def _test_storage_speed(self, **_) -> dict[str, Any]:
        result = TestResult("storage_speed", "Storage write speed", "automatic",
                            status="running", started_at=time.time())
        await self._publish(result)

        df = await self.adb.text(self.serial, "df -k /data/local/tmp | tail -1", timeout=10)
        fields = df.split()
        free_kb = int(fields[3]) if len(fields) > 3 and fields[3].isdigit() else None
        if free_kb is not None and free_kb < (self.BENCH_MB + 512) * 1024:
            return await self._finish(result, "inconclusive",
                                      f"Only {free_kb // 1024} MB free: the test needs "
                                      f"{self.BENCH_MB + 512} MB to run without "
                                      "disturbing the phone.")

        kind = (self.snapshot.get("storage") or {}).get("type") or ""
        floor = self.MIN_WRITE_MBS.get(kind, 20.0)
        speeds = []
        try:
            # Two runs: a phone installing an update in the background can
            # halve one measurement, rarely two in a row.
            for _ in range(2):
                speed = await self._write_speed()
                if speed is None:
                    break
                speeds.append(speed)
                if speed >= floor:
                    break
        finally:
            await self.adb.shell(self.serial, f"rm -f {self.BENCH_FILE}", timeout=15)

        if not speeds:
            return await self._finish(result, "inconclusive",
                                      "The write could not be timed on this device.")
        best = max(speeds)
        result.measurements = {"write_mb_s": round(best, 1), "runs": len(speeds),
                               "size_mb": self.BENCH_MB, "storage_type": kind or None,
                               "floor_mb_s": floor}
        if best >= floor:
            return await self._finish(result, "passed",
                                      f"{self.BENCH_MB} MB written and flushed at "
                                      f"{best:.0f} MB/s, normal for {kind or 'this storage'}.")
        return await self._finish(result, "failed",
                                  f"Only {best:.0f} MB/s writing {self.BENCH_MB} MB, twice: "
                                  f"{kind or 'storage'} should manage at least {floor:.0f}. A "
                                  "worn or counterfeit chip is the usual cause; close every "
                                  "app and repeat before concluding.")

    async def _write_speed(self) -> float | None:
        # Timed on the phone, so adb latency does not count; conv=fsync makes
        # the figure include reaching the flash, not just the page cache.
        cmd = (f"rm -f {self.BENCH_FILE}; s=$(date +%s%N); "
               f"dd if=/dev/zero of={self.BENCH_FILE} bs=1048576 count={self.BENCH_MB} "
               f"conv=fsync 2>/dev/null; e=$(date +%s%N); echo $((e - s))")
        started = time.monotonic()
        r = await self.adb.shell(self.serial, cmd, timeout=120)
        host_s = time.monotonic() - started
        ns = r.out.strip().splitlines()[-1] if r.out.strip() else ""
        # Toybox without %N support prints a literal "N": fall back to the
        # host's clock, which only adds the adb round trip.
        seconds = int(ns) / 1e9 if ns.isdigit() and int(ns) > 0 else host_s
        size = await self.adb.text(self.serial, f"stat -c %s {self.BENCH_FILE}", timeout=10)
        if not size.isdigit() or int(size) < self.BENCH_MB * 1048576 * 0.99 or seconds <= 0:
            return None
        return self.BENCH_MB / seconds

    async def _finish(self, result: TestResult, status: str, detail: str) -> dict[str, Any]:
        result.status = status
        result.outcome_detail = detail
        result.finished_at = time.time()
        await self._publish(result)
        return result.to_dict()

    # -- charging --------------------------------------------------------------

    async def _test_charging(self, **_) -> dict[str, Any]:
        result = TestResult("charging", "Charging", "automatic",
                            status="running", started_at=time.time())
        await self._publish(result)
        if not await self._ensure_dex():
            return await self._finish(result, "inconclusive", "The agent could not be started.")

        r = await self.adb.shell(self.serial, agent_command("battery", "8", "1000"), timeout=40)
        samples = [m for m in map(parse_json_line, r.out.splitlines())
                   if m and m.get("type") == "battery"]
        if not samples:
            return await self._finish(result, "inconclusive",
                                      "The battery service did not answer.")
        currents = [self._to_ma(s.get("current_now_ua")) for s in samples]
        currents = [c for c in currents if c is not None]
        state = self._battery_state(
            await self.adb.text(self.serial, "dumpsys battery", timeout=15))
        plugged, status = state["plugged"], state["status"]
        level = samples[-1].get("capacity_percent", state["level"])
        volts = state["voltage_v"] or 0
        avg_ma = statistics.fmean(currents) if currents else None
        counters = [s["charge_counter_uah"] for s in samples if isinstance(s.get("charge_counter_uah"), int)]
        gained_mah = (counters[-1] - counters[0]) / 1000 if len(counters) > 1 else None
        result.measurements = {"plugged": plugged, "status": status, "level": level,
                               "average_current_ma": round(avg_ma, 1) if avg_ma is not None else None,
                               "voltage_v": round(volts, 3) if volts else None,
                               "charge_gained_mah": gained_mah}

        source = {1: "a mains charger", 2: "USB", 4: "a wireless charger", 8: "a dock"}.get(plugged)
        if not plugged or plugged < 0:
            return await self._finish(result, "inconclusive",
                                      "The phone does not see a power source. It is connected "
                                      "to this computer, so the USB port or cable may not carry "
                                      "power: try another cable or port.")
        if status == 5:
            return await self._finish(result, "inconclusive",
                                      "The battery is full: nothing flows in. Repeat with the "
                                      "battery below 90%.")
        if avg_ma is not None and avg_ma > 30:
            watts = f", about {avg_ma * volts / 1000:.1f} W" if volts else ""
            return await self._finish(result, "passed",
                                      f"Charging from {source}: {avg_ma:.0f} mA flowing into the "
                                      f"battery at {volts:.2f} V{watts}.")
        if status == 4:
            return await self._finish(result, "inconclusive",
                                      f"Power from {source} is detected but the phone is not "
                                      f"charging{f' at {level}%' if level is not None else ''}. "
                                      "Battery protection (charging limited to 80-85%) does "
                                      "this; repeat with a lower charge level.")
        return await self._finish(result, "inconclusive" if status == 2 else "failed",
                                  f"Power from {source} is detected but no current reaches the "
                                  f"battery (average {avg_ma if avg_ma is not None else 0:.0f} mA). "
                                  + ("A computer port may supply less than the phone uses with the "
                                     "screen on: repeat with a wall charger." if status == 2 else
                                     "The phone reports it is discharging while plugged in: check "
                                     "the cable, then the port and the charging circuit."))

    @staticmethod
    def _to_ma(value: Any) -> float | None:
        """BatteryManager current in mA. The API says microamps, but several
        Samsung builds return milliamps; real currents in microamps are never
        below 10 mA in magnitude while the phone is on, so small values are
        read as milliamps -- the same rule the battery collector applies."""
        if not isinstance(value, (int, float)):
            return None
        return value / 1000 if abs(value) >= 10_000 else float(value)

    @staticmethod
    def _battery_state(text: str) -> dict[str, Any]:
        """Status, power source, level and voltage from `dumpsys battery`."""
        def field(name: str) -> str:
            m = re.search(rf"^\s*{re.escape(name)}:\s*(\S+)", text, re.M)
            return m.group(1) if m else ""
        plugged = sum(bit for name, bit in (("AC powered", 1), ("USB powered", 2),
                                             ("Wireless powered", 4), ("Dock powered", 8))
                      if field(name) == "true")
        status = field("status")
        level = field("level")
        voltage = field("voltage")
        return {
            "plugged": plugged,
            "status": int(status) if status.isdigit() else -1,
            "level": int(level) if level.isdigit() else None,
            "voltage_v": int(voltage) / 1000 if voltage.isdigit() else None,
        }

    # -- stress ----------------------------------------------------------------

    STRESS_S = 30
    STRESS_TAG = "pvstress"

    async def _test_stress(self, **_) -> dict[str, Any]:
        result = TestResult("stress", "Processor under load", "automatic",
                            status="running", started_at=time.time())
        await self._publish(result)

        if (await self.adb.text(self.serial, "settings get global low_power", timeout=10)) == "1":
            return await self._finish(result, "inconclusive",
                                      "Battery saver is on and caps the processor: turn it off "
                                      "and repeat.")

        cores = (self.snapshot.get("cpu") or {}).get("cores") or []
        rated = {f"cpu{c['index']}": c.get("max_khz") for c in cores
                 if isinstance(c.get("index"), int) and c.get("max_khz")}
        n = max(1, len(rated) or (self.snapshot.get("cpu") or {}).get("core_count") or 8)
        uptime_before = await self._uptime()

        before = PollingMonitor._shape(await self.adb.batch(self.serial, PollingMonitor.COMMANDS,
                                                             timeout=15))
        temp_start = max(before["thermal"].values(), default=None)

        loop = f"sh -c 'while :; do :; done' {self.STRESS_TAG}"
        script = (f"for i in $(seq 1 {n}); do {loop} & done; sleep {self.STRESS_S}; "
                  "kill $(jobs -p) 2>/dev/null; wait 2>/dev/null")
        load = asyncio.create_task(self.adb.shell(self.serial, script, timeout=self.STRESS_S + 30))
        peaks: dict[str, int] = {}
        late: dict[str, list[int]] = {}
        temps: list[float] = []
        try:
            started = time.monotonic()
            while not load.done():
                await asyncio.sleep(2)
                raw = await self.adb.batch(self.serial, PollingMonitor.COMMANDS, timeout=15)
                shaped = PollingMonitor._shape(raw)
                elapsed = time.monotonic() - started
                for name, khz in shaped["cpu_freq_khz"].items():
                    peaks[name] = max(peaks.get(name, 0), khz)
                    if elapsed > self.STRESS_S - 10:
                        late.setdefault(name, []).append(khz)
                if shaped["thermal"]:
                    temps.append(max(shaped["thermal"].values()))
                await self._emit({"type": "test_step", "test": "stress",
                                  "step": f"{min(int(elapsed), self.STRESS_S)} s"})
        finally:
            if not load.done():
                load.cancel()
            await self.adb.shell(self.serial,
                                 f"pkill -f '[{self.STRESS_TAG[0]}]{self.STRESS_TAG[1:]}'; true",
                                 timeout=10)

        uptime_after = await self._uptime()
        rebooted = (uptime_before is not None and uptime_after is not None
                    and uptime_after < uptime_before)
        reached = {name: peaks.get(name, 0) / khz for name, khz in rated.items() if khz}
        weak = sorted(name for name, ratio in reached.items() if ratio < 0.85)
        held = {name: statistics.fmean(v) / rated[name] for name, v in late.items()
                if v and rated.get(name)}
        top = max(rated.values(), default=0)
        big = [name for name, khz in rated.items() if khz == top]
        big_held = min((held[b] for b in big if b in held), default=None)

        result.measurements = {
            "cores": n, "duration_s": self.STRESS_S,
            "peak_ratio": {k: round(v, 2) for k, v in reached.items()},
            "sustained_ratio_big_cores": round(big_held, 2) if big_held is not None else None,
            "temperature_start_c": temp_start,
            "temperature_peak_c": max(temps, default=None),
            "rebooted": rebooted,
        }
        heat = (f" Temperature went from {temp_start:.0f} to {max(temps):.0f} °C."
                if temp_start is not None and temps else "")
        sustain = (f" In the last 10 s the fastest cores held {big_held * 100:.0f}% of their "
                   "rated speed." if big_held is not None else "")
        if rebooted:
            return await self._finish(result, "failed",
                                      "The phone restarted under load: a sign of a failing "
                                      "battery, power circuit or processor." + heat)
        if not reached:
            return await self._finish(result, "inconclusive",
                                      "The core frequencies could not be read on this device."
                                      + heat)
        if weak:
            return await self._finish(result, "failed",
                                      f"Cores {', '.join(weak)} never reached 85% of their rated "
                                      "frequency under full load. A throttled or limited "
                                      "processor, or a battery that cannot deliver the "
                                      "current." + heat + sustain)
        return await self._finish(result, "passed",
                                  f"All {len(reached)} cores reached their rated frequency and the "
                                  "phone stayed up." + heat + sustain)

    async def _uptime(self) -> float | None:
        text = await self.adb.text(self.serial, "cat /proc/uptime", timeout=10)
        try:
            return float(text.split()[0])
        except (ValueError, IndexError):
            return None

    # -- loudspeaker -----------------------------------------------------------

    TONES_HZ = (1000, 2500, 4000)
    TONE_MS = 1000

    async def _test_speaker(self, **_) -> dict[str, Any]:
        """Play tones on the phone; the interface listens with the computer's
        microphone and reports what it heard through record_outcome()."""
        result = TestResult("speaker", "Loudspeaker", "automatic",
                            status="running", started_at=time.time())
        self._speaker_answered.clear()
        await self._publish(result)
        if not await self._ensure_dex():
            return await self._finish(result, "inconclusive", "The agent could not be started.")

        restore = await self._raise_media_volume()
        await self._emit({"type": "test_step", "test": "speaker", "step": "listen",
                          "tones": list(self.TONES_HZ), "ms": self.TONE_MS})
        proc = await asyncio.create_subprocess_exec(
            self.adb.adb, "-s", self.serial, "shell",
            agent_command("tones", ",".join(str(t) for t in self.TONES_HZ), str(self.TONE_MS)),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=STREAM_LINE_LIMIT)
        assert proc.stdout
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(proc.stdout.readline(),
                                                 timeout=deadline - time.monotonic())
                except TimeoutError:
                    break
                if not raw:
                    break
                msg = parse_json_line(raw)
                if msg and msg.get("type") == "tone":
                    await self._emit({"type": "test_step", "test": "speaker", "step": "tone",
                                      "hz": msg.get("hz"), "ms": msg.get("ms")})
        finally:
            await reap(proc)
            if restore:
                await restore()
        await self._emit({"type": "test_step", "test": "speaker", "step": "done"})

        # The verdict comes from the interface, which did the listening.
        try:
            await asyncio.wait_for(self._speaker_answered.wait(), timeout=8)
        except TimeoutError:
            if self.results.get("speaker") is result and result.status == "running":
                return await self._finish(result, "inconclusive",
                                          "The tones were played but the computer reported no "
                                          "measurement: its microphone may be unavailable. "
                                          "Check by ear with the Speakers and microphone test.")
        return self.results["speaker"].to_dict()

    async def _raise_media_volume(self) -> Callable[[], Awaitable[None]] | None:
        """Set the media volume to about 70% and return how to put it back."""
        for tool in ("cmd media_session", "media"):
            out = await self.adb.text(self.serial, f"{tool} volume --stream 3 --get", timeout=10)
            m = re.search(r"volume is (\d+) in range \[(\d+)\.\.(\d+)\]", out)
            if not m:
                continue
            current, top = int(m.group(1)), int(m.group(3))
            await self.adb.shell(self.serial,
                                 f"{tool} volume --stream 3 --set {round(top * 0.7)}", timeout=10)

            async def restore(tool: str = tool, value: int = current) -> None:
                await self.adb.shell(self.serial, f"{tool} volume --stream 3 --set {value}",
                                     timeout=10)
            return restore
        return None

    # -- microphone ------------------------------------------------------------

    MIC_TONES_HZ = (700, 1500, 3000)
    MIC_RECORD_MS = 6000

    async def _test_microphone(self, **_) -> dict[str, Any]:
        """The phone records while the interface plays tones on the computer;
        the recording is analysed here."""
        result = TestResult("microphone", "Microphone", "automatic",
                            status="running", started_at=time.time())
        await self._publish(result)
        if not await self._ensure_dex():
            return await self._finish(result, "inconclusive", "The agent could not be started.")

        proc = await asyncio.create_subprocess_exec(
            self.adb.adb, "-s", self.serial, "shell",
            agent_command("record", str(self.MIC_RECORD_MS)),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=STREAM_LINE_LIMIT)
        assert proc.stdout
        pcm, rate, problem = b"", 16000, ""
        try:
            deadline = time.monotonic() + self.MIC_RECORD_MS / 1000 + 15
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(proc.stdout.readline(),
                                                 timeout=deadline - time.monotonic())
                except TimeoutError:
                    break
                if not raw:
                    break
                msg = parse_json_line(raw)
                if not msg:
                    continue
                if msg.get("type") == "recording":
                    await self._emit({"type": "test_step", "test": "microphone", "step": "play",
                                      "tones": list(self.MIC_TONES_HZ), "ms": 900, "gap_ms": 350,
                                      "delay_ms": 900})
                elif msg.get("type") == "audio":
                    rate = int(msg.get("rate") or 16000)
                    pcm = base64.b64decode(msg.get("pcm_b64") or "")
                    break
                elif msg.get("type") in ("error", "fatal"):
                    problem = str(msg.get("message") or "")
                    break
        finally:
            await reap(proc)
        await self._emit({"type": "test_step", "test": "microphone", "step": "done"})

        if len(pcm) < rate:
            return await self._finish(result, "inconclusive",
                                      "The microphone could not be recorded"
                                      + (f": {problem}" if problem else "") + ".")
        samples = struct.unpack(f"<{len(pcm) // 2}h", pcm[: len(pcm) // 2 * 2])
        analysis = _tone_margins(samples, rate, self.MIC_TONES_HZ, baseline_s=0.7)
        peak = max(abs(x) for x in samples)
        result.measurements = {"peak": peak, "margins_db": analysis, "rate": rate}
        heard = [hz for hz, margin in analysis.items() if margin >= 10]
        listing = ", ".join(f"{hz} Hz {m:+.0f} dB" for hz, m in analysis.items())
        if peak < 8:
            return await self._finish(result, "failed",
                                      "The microphone delivers digital silence: not even room "
                                      "noise reaches it. The microphone or its connection is "
                                      "faulty, or blocked by software.")
        if len(heard) >= 2:
            return await self._finish(result, "passed",
                                      f"The phone's microphone picked up the computer's tones: {listing} "
                                      "over the room noise.")
        return await self._finish(result, "inconclusive",
                                  f"The microphone works (it hears the room) but the tones were not "
                                  f"picked up clearly ({listing}). Check the computer's speakers are on "
                                  "and bring the phone's bottom edge close to them.")

    # -- bluetooth -------------------------------------------------------------

    async def _bt_state(self) -> str:
        out = await self.adb.text(self.serial, "dumpsys bluetooth_manager 2>/dev/null"
                                  " | grep -m1 -iE '^ *state:'", timeout=10)
        return out.split(":", 1)[-1].strip().upper() if ":" in out else ""

    async def _test_bluetooth(self, **_) -> dict[str, Any]:
        result = TestResult("bluetooth", "Bluetooth radio", "automatic",
                            status="running", started_at=time.time())
        await self._publish(result)
        before = await self._bt_state()
        if not before:
            return await self._finish(result, "inconclusive",
                                      "The Bluetooth service did not report its state.")
        if before == "ON":
            return await self._finish(result, "passed", "Bluetooth is on and the radio is up.")
        r = await self.adb.shell(self.serial, "cmd bluetooth_manager enable", timeout=15)
        if "Success" not in r.out:
            return await self._finish(result, "inconclusive",
                                      "Bluetooth could not be switched on from here: switch it on "
                                      "on the phone and repeat.")
        state, waited = before, 0.0
        try:
            while waited < 12:
                await asyncio.sleep(1)
                waited += 1
                state = await self._bt_state()
                if state == "ON":
                    break
        finally:
            await self.adb.shell(self.serial, "cmd bluetooth_manager disable", timeout=15)
        result.measurements = {"turned_on_after_s": waited if state == "ON" else None}
        if state == "ON":
            return await self._finish(result, "passed",
                                      f"The radio came up in {waited:.0f} s and was switched off "
                                      "again, as it was.")
        return await self._finish(result, "failed",
                                  f"Bluetooth was told to switch on but stayed in state {state or '?'} "
                                  "for 12 seconds: the radio or its firmware does not start.")

    # -- cellular --------------------------------------------------------------

    REG_STATES = {"0": "in service", "1": "out of service", "2": "emergency calls only",
                  "3": "radio off"}

    async def _test_cellular(self, **_) -> dict[str, Any]:
        result = TestResult("cellular", "Mobile network", "automatic",
                            status="running", started_at=time.time())
        await self._publish(result)
        raw = await self.adb.batch(self.serial, {
            "sim": "getprop gsm.sim.state",
            "airplane": "settings get global airplane_mode_on",
            "registry": "dumpsys telephony.registry 2>/dev/null | grep -E 'mServiceState=|mSignalStrength='"
                        " | head -8",
            "operator": "getprop gsm.operator.alpha",
            "network": "getprop gsm.network.type",
        }, timeout=20)
        sims = [x.strip() for x in raw.get("sim", "").split(",") if x.strip()]
        states = re.findall(r"mVoiceRegState=(\d)", raw.get("registry", ""))
        data = re.findall(r"mDataRegState=(\d)", raw.get("registry", ""))
        levels = [int(x) for x in re.findall(r"level=(\d)", raw.get("registry", ""))]
        result.measurements = {"sim_states": sims, "voice": states, "data": data,
                               "signal_level": max(levels, default=None)}
        if raw.get("airplane", "").strip() == "1":
            return await self._finish(result, "inconclusive",
                                      "Airplane mode is on: switch it off and repeat.")
        if not any(s == "READY" or s == "LOADED" for s in sims):
            return await self._finish(result, "inconclusive",
                                      "No working SIM is inserted ("
                                      + (", ".join(sims) or "no state") + "). Insert one to test "
                                      "the mobile radio.")
        if "0" in states or "0" in data:
            operator = raw.get("operator", "").strip(" ,") or "a network"
            level = max(levels, default=None)
            return await self._finish(result, "passed",
                                      f"Registered on {operator}"
                                      + (f" ({raw.get('network', '').strip(' ,')})" if raw.get("network", "").strip(" ,") else "")
                                      + (f", signal level {level} of 4." if level is not None else "."))
        if "2" in states:
            return await self._finish(result, "passed",
                                      "The radio receives a network but the SIM is not registered "
                                      "(emergency calls only): the hardware works; the SIM or its "
                                      "plan does not.")
        return await self._finish(result, "inconclusive",
                                  "The SIM is ready but the phone is not registered on any network. "
                                  "No coverage here, or the SIM is not active; if other phones have "
                                  "signal in the same spot, the antenna or modem is suspect.")

    # -- gnss ------------------------------------------------------------------

    GNSS_WAIT_S = 45

    async def _test_gnss(self, **_) -> dict[str, Any]:
        result = TestResult("gnss", "Satellite positioning", "automatic",
                            status="running", started_at=time.time())
        await self._publish(result)
        if not await self._ensure_dex():
            return await self._finish(result, "inconclusive", "The agent could not be started.")

        mode = await self.adb.text(self.serial, "settings get secure location_mode", timeout=10)
        switched = False
        if mode == "0":
            r = await self.adb.shell(self.serial, "cmd location set-location-enabled true",
                                     timeout=10)
            switched = r.ok

        tag = f"pv-test-{uuid.uuid4().hex[:12]}"
        proc = await asyncio.create_subprocess_exec(
            self.adb.adb, "-s", self.serial, "shell", agent_command("gnss", "", tag),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=STREAM_LINE_LIMIT)
        assert proc.stdout
        best: list[float] = []
        constellations: set[int] = set()
        fix = None
        note = ""
        started = time.monotonic()
        try:
            while time.monotonic() - started < self.GNSS_WAIT_S:
                try:
                    raw = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
                except TimeoutError:
                    continue
                if not raw:
                    break
                msg = parse_json_line(raw)
                if not msg:
                    continue
                if msg.get("type") == "gnss":
                    cn0 = [float(x.get("cn0") or 0) for x in msg.get("satellites") or []]
                    constellations |= {x.get("constellation") for x in msg.get("satellites") or []
                                       if (x.get("cn0") or 0) > 0}
                    if sum(1 for c in cn0 if c > 0) > sum(1 for c in best if c > 0):
                        best = cn0
                    await self._emit({"type": "test_step", "test": "gnss",
                                      "step": f"{sum(1 for c in cn0 if c > 0)} satellites heard"})
                    if sum(1 for c in cn0 if c >= 20) >= 4:
                        break
                elif msg.get("type") == "gnss_fix":
                    fix = msg
                    break
                elif msg.get("type") == "gnss_note":
                    note = str(msg.get("message") or "")
        finally:
            await self._stop_agent(proc, tag)
            if switched:
                await self.adb.shell(self.serial, "cmd location set-location-enabled false",
                                     timeout=10)
        heard = [c for c in best if c > 0]
        result.measurements = {"satellites_heard": len(heard),
                               "best_cn0": round(max(heard), 1) if heard else None,
                               "constellations": len(constellations), "fix": bool(fix),
                               "seconds": round(time.monotonic() - started)}
        if fix or heard:
            what = (f"{len(heard)} satellites heard from {len(constellations)} constellations, "
                    f"strongest {max(heard):.0f} dB-Hz" if heard else "a position fix")
            return await self._finish(result, "passed",
                                      f"The receiver works: {what}. Seeing satellites proves the "
                                      "antenna and receive chain, even without a fix.")
        return await self._finish(result, "inconclusive",
                                  (f"{note} " if note else "")
                                  + f"No satellite heard in {self.GNSS_WAIT_S} s. Indoors this is "
                                  "common: repeat by a window or outdoors before blaming the receiver.")

    # -- camera ----------------------------------------------------------------

    async def _test_camera(self, **_) -> dict[str, Any]:
        """Capture from every camera; the operator judges the pictures."""
        result = TestResult("camera", "Cameras", "guided", status="running",
                            started_at=time.time())
        await self._publish(result)
        if not await self._ensure_dex():
            return await self._finish(result, "inconclusive", "The agent could not be started.")
        r = await self.adb.shell(self.serial, agent_command("camera"), timeout=90)
        shots = [m for m in map(parse_json_line, r.out.splitlines())
                 if m and m.get("type") == "camera"]
        notes = []
        for shot in shots:
            if not shot.get("ok"):
                notes.append(f"camera {shot.get('id')} ({shot.get('facing')}): no picture, "
                             f"{shot.get('error')}")
            elif (shot.get("brightness") or 0) < 6 and (shot.get("contrast") or 0) < 6:
                notes.append(f"camera {shot.get('id')} ({shot.get('facing')}): black picture, "
                             "lens covered or phone face down?")
        result.measurements = {"photos": shots}
        result.outcome_detail = (
            f"{sum(1 for x in shots if x.get('ok'))} of {len(shots)} cameras returned a picture."
            + (" " + "; ".join(notes) + "." if notes else "")
            + " Look at each one, then answer.")
        await self._publish(result)
        return result.to_dict()

    # -- buttons ---------------------------------------------------------------

    # Keys a touchscreen reports with every touch: not physical buttons.
    _TOUCH_KEYS = ("BTN_TOUCH", "BTN_TOOL_")

    async def _test_buttons(self, duration: float = 15.0, **_) -> dict[str, Any]:
        """Listen for physical button events over a given interval."""
        result = TestResult("buttons", "Physical buttons", "guided",
                            status="running", started_at=time.time())
        await self._publish(result)

        duration = _as_number(duration, 15.0, 1.0, 120.0)
        proc = await asyncio.create_subprocess_exec(
            self.adb.adb, "-s", self.serial, "shell", "getevent -lq",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert proc.stdout

        # Lines look like "/dev/input/event0: EV_KEY  KEY_VOLUMEUP  DOWN".
        # Only presses are counted: every press is followed by an UP.
        seen: dict[str, int] = {}
        deadline = time.monotonic() + duration
        try:
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    raw = await asyncio.wait_for(proc.stdout.readline(),
                                                 timeout=max(0.3, remaining))
                except TimeoutError:
                    break
                except ValueError:
                    continue
                if not raw:
                    break
                parts = raw.decode("utf-8", "replace").split()
                if "EV_KEY" not in parts:
                    continue
                i = parts.index("EV_KEY")
                if len(parts) < i + 3:
                    continue
                token, value = parts[i + 1], parts[i + 2]
                if not token.startswith(("KEY_", "BTN_")):
                    continue
                if token.startswith(self._TOUCH_KEYS):
                    continue
                if value not in ("DOWN", "00000001"):
                    continue
                seen[token] = seen.get(token, 0) + 1
                await self._emit({
                    "type": "test_step", "test": "buttons",
                    "step": token, "accepted": True,
                    "count": seen[token],
                })
        finally:
            await reap(proc)

        result.measurements = {"keys": seen, "distinct": len(seen)}
        result.outcome_detail = (
            f"{len(seen)} distinct buttons detected: "
            + (", ".join(sorted(seen)) if seen else "none")
        )
        if not seen:
            result.status = "failed"
            result.outcome_detail += (
                ". No events received: either nothing was pressed, or the "
                "buttons do not generate events."
            )
            result.finished_at = time.time()
        await self._publish(result)
        return result.to_dict()

    # ---------------------------------------------------------------- cleanup

    async def cleanup(self) -> None:
        """Remove the test files from the phone and undo setting changes."""
        await self._restore_settings()
        # A stress or storage test interrupted mid-way (unplug, re-analysis)
        # must not leave busy loops or a 256 MB file behind.
        await self.adb.shell(
            self.serial,
            f"pkill -f '[{self.STRESS_TAG[0]}]{self.STRESS_TAG[1:]}'; rm -f {self.BENCH_FILE}; true",
            timeout=10)
        if self._pushed_patterns:
            await self.adb.shell(self.serial, f"rm -rf {REMOTE_DIR}", timeout=10)
            self._pushed_patterns = False
            self._patterns.clear()
        if self._pushed_dex:
            await self.adb.shell(self.serial, f"rm -f {DEX_REMOTE}", timeout=8)
            self._pushed_dex = False

    def summary(self) -> dict[str, Any]:
        results = [r.to_dict() for r in self.results.values()]
        return {
            "results": results,
            "passed": sum(1 for r in results if r["status"] == "passed"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "inconclusive": sum(1 for r in results if r["status"] == "inconclusive"),
            "pending": sum(1 for r in results if r["status"] in ("pending", "running")),
            "total": len(results),
        }


def _tone_margins(samples, rate: int, tones, baseline_s: float) -> dict[int, float]:
    """For each tone, how far it rose above its surroundings at its best
    sustained moment, compared with the same measure before any tone.

    Goertzel filters over 100 ms windows: the tone's energy against the mean
    of four neighbouring frequencies 120-240 Hz away. The best value held over
    three consecutive windows counts, so a click or a voice cannot pass.
    """
    window = rate // 10

    def power(seg, hz: float) -> float:
        k = 2 * math.cos(2 * math.pi * hz / rate)
        s1 = s2 = 0.0
        for x in seg:
            s1, s2 = x + k * s1 - s2, s1
        return s1 * s1 + s2 * s2 - k * s1 * s2

    out: dict[int, float] = {}
    for hz in tones:
        series = []
        for start in range(0, len(samples) - window, window):
            seg = samples[start:start + window]
            around = [power(seg, hz + d) for d in (-240, -120, 120, 240)]
            series.append((start / rate,
                           10 * math.log10((power(seg, hz) + 1) / (sum(around) / 4 + 1))))
        before = [v for t, v in series if t < baseline_s]
        after = [v for t, v in series if t >= baseline_s]
        held = lambda vs: max((min(vs[i:i + 3]) for i in range(len(vs) - 2)), default=0.0)  # noqa: E731
        out[hz] = round(held(after) - max(0.0, held(before)), 1)
    return out
