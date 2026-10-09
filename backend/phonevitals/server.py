"""Local server: WebSocket to the UI, session orchestration.

Listens on the loopback interface only, but loopback is not a trust boundary:
any web page open in the user's browser can make requests to 127.0.0.1, and
WebSocket handshakes are not subject to CORS. Since this socket can drive a
phone (inject key events, run commands, read identifiers), every API call and
the WebSocket require a per-launch session token:

- the launcher passes the token in PHONEVITALS_TOKEN and opens `/?token=...`;
- that first request sets an HttpOnly, SameSite=Strict cookie and redirects to
  a clean URL, so the token never lingers in the address bar or in history;
- /api/* and /ws then require the cookie. Cross-site pages never send a
  SameSite=Strict cookie, and the Host check defeats DNS rebinding.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any, Coroutine
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .adb import Adb, AdbError, Device, DeviceWatcher
from .analyzer import Analyzer
from .live import AgentSession, PollingMonitor, TouchMonitor
from .testsuite import TestSuite

log = logging.getLogger("phonevitals")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.environ.get("PHONEVITALS_UI_DIR") or os.path.join(
    os.path.dirname(BASE), "ui", "dist")

VERSION = __version__
COOKIE = "phonevitals_session"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
WS_UNAUTHORISED = 4401

# Settings the UI may change. Anything else in a "settings" message is ignored.
SETTINGS_DEFAULTS = {"auto_analyse": True, "auto_live": True}


def _json(payload: Any, status_code: int = 200) -> Response:
    # Snapshots may carry values json cannot encode natively (dates, bytes);
    # the WebSocket path already stringifies them, so HTTP does the same.
    return Response(json.dumps(payload, default=str, ensure_ascii=False),
                    status_code=status_code, media_type="application/json")


def _host_of(value: str | None) -> str:
    """Host part of a Host header or an Origin URL, without port or brackets."""
    if not value:
        return ""
    if "://" not in value:
        value = f"//{value}"
    return (urlsplit(value).hostname or "").lower()


def _report_filename(snapshot: dict) -> str:
    model = (snapshot.get("summary") or {}).get("model") or "device"
    model = re.sub(r"[^A-Za-z0-9._-]+", "_", str(model)).strip("._") or "device"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{model}-{stamp}.json"


class Session:
    """State of an analysis session on a single device."""

    def __init__(self, adb: Adb | None, settings: dict[str, Any], demo: bool = False,
                 store: Any = None):
        self.adb = adb
        self.settings = settings
        self.demo = demo
        self.store = store
        self.device: Device | None = None
        self.snapshot: dict[str, Any] | None = None

        self.agent: AgentSession | None = None
        self.gnss: AgentSession | None = None
        self.touch: TouchMonitor | None = None
        self.poller: PollingMonitor | None = None
        self.suite: TestSuite | None = None

        self.clients: set[WebSocket] = set()
        self._live_running = False
        self._live_lock = asyncio.Lock()
        self._analysis: asyncio.Task | None = None
        self._imei: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self.demo_live = None
        if demo:
            from .demo import DemoLive
            self.demo_live = DemoLive(self._sink)

    # --------------------------------------------------------------- tasks

    def spawn(self, coro: Coroutine) -> asyncio.Task:
        """Start a background task and keep a reference to it.

        The event loop holds only weak references to tasks, so a task nobody
        stores can be garbage-collected before it finishes.
        """
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("background task failed", exc_info=task.exception())

    @property
    def analyzing(self) -> bool:
        return self._analysis is not None and not self._analysis.done()

    # ------------------------------------------------------------ broadcast

    async def broadcast(self, payload: dict) -> None:
        if not self.clients:
            return
        message = json.dumps(payload, default=str)
        for ws in list(self.clients):
            try:
                await ws.send_text(message)
            except Exception:
                self.clients.discard(ws)

    def _sink(self, payload: dict) -> Any:
        return self.broadcast(payload)

    # -------------------------------------------------------------- analysis

    def request_analysis(self, read_imei: bool = True, delay: float = 0.0) -> None:
        if self.analyzing:
            return
        if self.demo:
            self._analysis = self.spawn(self._demo_analyse())
            return
        if not self.device or not self.device.ready:
            return
        self._analysis = self.spawn(self._analyse(read_imei, delay))

    async def _demo_analyse(self) -> None:
        from .demo import DemoTestSuite, build_demo_snapshot
        await self.broadcast({"type": "analysis_started", "serial": "DEMO00000000"})
        for step, percent, detail in [
            ("connection", 4, "Checking device state"),
            ("collection", 14, "Running 101 readings on the device"),
            ("analysis", 48, "Interpreting: battery"),
            ("identity", 68, "Reading the IMEI with the *#06# code"),
            ("attestation", 77, "Requesting hardware attestation from the TEE"),
            ("verification", 90, "Running authenticity checks"),
        ]:
            await self.broadcast({"type": "progress", "step": step,
                                  "percent": percent, "detail": detail})
            await asyncio.sleep(0.7)
        self.snapshot = build_demo_snapshot()
        self.suite = DemoTestSuite(None, "DEMO00000000", self.snapshot, self._sink)
        await self.broadcast({"type": "analysis_complete", "snapshot": self.snapshot,
                              "tests": self.suite.catalogue()})

    async def _analyse(self, read_imei: bool, delay: float) -> None:
        device = self.device
        assert device is not None and self.adb is not None
        if delay:
            # Immediately after USB enumeration the device may not have its
            # services ready yet.
            await asyncio.sleep(delay)

        await self.stop_live()
        await self._drop_suite()
        self.snapshot = None
        # A session cut short by unplugging the phone cannot stop its agent
        # processes, and they keep running on the device. Nothing of ours runs
        # at this point, so any agent process found now is such a leftover.
        await self.adb.shell(device.serial,
                             "pkill -f '[c]om.phonevitals.agent.Agent'", timeout=10)
        await self.broadcast({"type": "analysis_started", "serial": device.serial})
        try:
            analyzer = Analyzer(self.adb, on_event=self._sink, store=self.store)
            snapshot = await analyzer.analyse(device, read_imei=read_imei)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("analysis failed")
            await self.broadcast({"type": "analysis_failed",
                                  "error": f"{type(exc).__name__}: {exc}"})
            return

        if self.device is not device:
            return                              # unplugged while analysing
        self.snapshot = snapshot
        self.suite = TestSuite(self.adb, device.serial, snapshot, self._sink)
        await self.broadcast({
            "type": "analysis_complete",
            "snapshot": snapshot,
            "tests": self.suite.catalogue(),
        })
        if self.settings.get("auto_live") and not (snapshot.get("meta") or {}).get("blocked"):
            await self.start_live()

    def request_imei_reread(self) -> None:
        if self.analyzing or not self.device or not self.snapshot:
            return
        if self._imei is not None and not self._imei.done():
            return
        self._imei = self.spawn(_reread_imei(self))

    # ----------------------------------------------------------------- live

    async def start_live(self) -> None:
        async with self._live_lock:
            if self.demo_live:
                if not self._live_running:
                    await self.demo_live.start()
                    self._live_running = True
                    await self.broadcast({"type": "live_started"})
                return
            if self._live_running or not self.device or not self.snapshot:
                return
            if self.adb is None:
                return
            self._live_running = True
            serial = self.device.serial

            # Sensors through the agent. If app_process refuses the dex, say so
            # clearly instead of leaving the section empty without explanation.
            self.agent = AgentSession(self.adb, serial, self._sink)
            probe = await self.agent.probe()
            await self.broadcast({"type": "agent_status", **probe})
            if probe.get("ok"):
                await self.agent.start()

                # GNSS satellites: a separate process of the same agent,
                # because the receiver has to stay on while the sensors
                # stream. It shares the .dex with the sensor session.
                self.gnss = AgentSession(self.adb, serial, self._sink,
                                         command="gnss", owns_dex=False)
                self.gnss.pushed = True
                try:
                    await self.gnss.start()
                except Exception:
                    log.exception("GNSS stream failed to start")
                    self.gnss = None

            touchscreen = (self.snapshot.get("input") or {}).get("touchscreen")
            if touchscreen and touchscreen.get("path"):
                self.touch = TouchMonitor(
                    self.adb, serial, touchscreen["path"], self._sink,
                    max_x=touchscreen.get("touch_max_x") or 0,
                    max_y=touchscreen.get("touch_max_y") or 0,
                )
                await self.touch.start()

            self.poller = PollingMonitor(self.adb, serial, self._sink, interval=1.0)
            await self.poller.start()

            await self.broadcast({"type": "live_started"})

    async def stop_live(self, cleanup: bool = True) -> None:
        async with self._live_lock:
            was_running = self._live_running
            self._live_running = False
            if self.demo_live:
                await self.demo_live.stop()
            for monitor in (self.poller, self.touch):
                if monitor:
                    try:
                        await monitor.stop()
                    except Exception:
                        log.exception("failed to stop monitor")
            # The GNSS stream must stop before the sensor one: the latter
            # removes the .dex from the phone.
            for agent in (self.gnss, self.agent):
                if agent:
                    try:
                        await agent.stop(cleanup=cleanup)
                    except Exception:
                        log.exception("failed to stop agent")
            self.poller = self.touch = self.agent = self.gnss = None
            if was_running:
                await self.broadcast({"type": "live_stopped"})

    async def _drop_suite(self) -> None:
        if self.suite:
            try:
                await self.suite.cleanup()
            except Exception:
                log.exception("test suite cleanup failed")
        self.suite = None

    async def teardown(self) -> None:
        for task in (self._analysis, self._imei):
            if task is not None and not task.done():
                task.cancel()
        self._analysis = self._imei = None
        await self.stop_live(cleanup=True)
        await self._drop_suite()
        self.snapshot = None
        self.device = None

    async def close(self) -> None:
        device = self.device
        await self.teardown()
        # On exit nothing of ours may stay on the phone, whatever session
        # started it (a test capture interrupted mid-way included).
        if device and device.ready and self.adb:
            await self.adb.shell(device.serial,
                                 "pkill -f '[c]om.phonevitals.agent.Agent'", timeout=10)
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


def _device_payload(device: Device) -> dict:
    return {
        "serial": device.serial, "state": device.state,
        "model": device.model, "product": device.product,
        "device": device.device, "usb": device.usb,
        "label": device.label, "ready": device.ready,
    }


def create_app(demo: bool = False, token: str | None = None,
               on_shutdown_request: Callable[[], None] | None = None) -> FastAPI:
    token = token or os.environ.get("PHONEVITALS_TOKEN") or ""
    if not token:
        raise ValueError("a session token is required (PHONEVITALS_TOKEN)")

    try:
        adb: Adb | None = Adb()
        adb_error = None
    except AdbError as exc:
        adb = None
        adb_error = str(exc)

    settings: dict[str, Any] = dict(SETTINGS_DEFAULTS)
    store = None
    if not demo:
        try:
            from .store import DeviceStore
            store = DeviceStore()
        except Exception:
            log.exception("local device memory unavailable")
    session = Session(adb, settings, demo=demo, store=store)
    # Demo mode shows sample data only and never touches a connected phone.
    watcher = DeviceWatcher(adb) if adb and not demo else None

    if demo:
        from .demo import DemoTestSuite, build_demo_snapshot
        session.snapshot = build_demo_snapshot()
        # Simulated outcomes: in demo mode no command reaches a real device.
        session.suite = DemoTestSuite(None, "DEMO00000000",
                                      session.snapshot, session._sink)

    # ------------------------------------------------------------- USB events

    async def on_device_change(event: str, device: Device) -> None:
        await session.broadcast({"type": f"device_{event}",
                                 "device": _device_payload(device)})

        current = session.device
        if event == "detached":
            if current and current.serial == device.serial:
                await session.teardown()
                await session.broadcast({"type": "device_gone"})
                adopt_next(exclude=device.serial)
            return

        # One device at a time: a second phone plugged in while the first is
        # being examined is announced to the UI but does not take over.
        if current and current.serial != device.serial:
            return

        session.device = device
        if device.ready:
            if settings["auto_analyse"] and not session.snapshot:
                session.request_analysis(delay=1.0)
        else:
            # Unauthorised, offline (e.g. rebooting during a test): the live
            # streams would only spin against a dead transport.
            await session.stop_live(cleanup=False)
            await session.broadcast({
                "type": "device_blocked",
                "info": Analyzer._explain_state(device.state),
            })

    def adopt_next(exclude: str) -> None:
        """After the examined phone leaves, move on to another one if present."""
        if not watcher or session.device:
            return
        for device in watcher.devices:
            if device.serial != exclude:
                session.spawn(on_device_change("changed", device))
                return

    if watcher:
        watcher.on_change(on_device_change)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if watcher and adb:
            try:
                await adb.start_server()
            except Exception:
                log.exception("adb start-server failed")
            watcher.start()
        if demo and settings["auto_live"]:
            await session.start_live()
        try:
            yield
        finally:
            if watcher:
                watcher.stop()
            await session.close()

    app = FastAPI(title="PhoneVitals", version=VERSION, docs_url=None,
                  redoc_url=None, openapi_url=None, lifespan=lifespan)

    # ----------------------------------------------------------------- auth

    expected = token.encode()

    def matches(value: str | None) -> bool:
        return hmac.compare_digest((value or "").encode(), expected)

    def authorised(cookies: dict[str, str]) -> bool:
        return matches(cookies.get(COOKIE))

    def bearer(request: Request) -> bool:
        header = request.headers.get("authorization", "")
        return header.startswith("Bearer ") and matches(header[7:])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if _host_of(request.headers.get("host")) not in LOOPBACK_HOSTS:
            return _json({"error": "forbidden host"}, 403)

        path = request.url.path
        offered = request.query_params.get("token")
        if offered is not None:
            if not matches(offered):
                return _json({"error": "invalid token"}, 401)
            response = RedirectResponse(path, status_code=303)
            response.set_cookie(COOKIE, token, httponly=True, samesite="strict",
                                path="/")
            return response

        # The launcher authenticates with the token in a header; the page
        # with the cookie it was given.
        if path.startswith("/api/") and path != "/api/health" \
                and not (authorised(request.cookies) or bearer(request)):
            return _json({"error": "unauthorised"}, 401)

        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    # ---------------------------------------------------------------- HTTP

    @app.get("/api/health")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True, "version": VERSION})

    @app.post("/api/shutdown")
    async def shutdown() -> Response:
        """Stop the server gracefully, so the session can clean up the phone.
        Used by the launcher on every platform: Windows has no SIGTERM."""
        if on_shutdown_request is None:
            return _json({"error": "not available"}, 404)
        on_shutdown_request()
        return _json({"stopping": True})

    @app.get("/api/status")
    async def status() -> Response:
        return _json({
            "version": VERSION,
            "adb_available": adb is not None,
            "adb_error": adb_error,
            "adb_path": adb.adb if adb else None,
            "devices": [
                {"serial": d.serial, "state": d.state, "label": d.label}
                for d in (watcher.devices if watcher else [])
            ],
            "has_snapshot": bool(session.snapshot),
            "analyzing": session.analyzing,
        })

    @app.get("/api/snapshot")
    async def snapshot() -> Response:
        if not session.snapshot:
            return _json({"error": "no analysis available"}, 404)
        return _json(session.snapshot)

    @app.get("/api/report")
    async def report() -> Response:
        """The full report, for the UI to save wherever the user chooses.

        The server does not write it to disk itself: once installed, the
        program directory is read-only, and the user should pick the place.
        """
        if not session.snapshot:
            return _json({"error": "no analysis available"}, 404)
        payload = dict(session.snapshot)
        if session.suite:
            payload["tests"] = session.suite.summary()
        # Fingerprint of the canonical JSON (sorted keys, compact): printed on
        # the PDF, it ties the two exports together and shows later edits.
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, default=str)
        return _json({"filename": _report_filename(session.snapshot),
                      "report": payload,
                      "sha256": hashlib.sha256(canonical.encode()).hexdigest(),
                      "version": VERSION})

    # ----------------------------------------------------------- WebSocket

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        origin = ws.headers.get("origin")
        if _host_of(ws.headers.get("host")) not in LOOPBACK_HOSTS or \
                (origin is not None and _host_of(origin) not in LOOPBACK_HOSTS):
            await ws.close(code=1008)
            return

        await ws.accept()
        if not authorised(ws.cookies):
            await ws.close(code=WS_UNAUTHORISED, reason="unauthorised")
            return

        if adb is None and not demo:
            await ws.send_text(json.dumps({
                "type": "fatal",
                "message": adb_error or "adb not available",
            }))
            await ws.close()
            return

        session.clients.add(ws)
        try:
            # Initial state, so a UI reloaded mid-session finds everything
            # again without re-running the analysis.
            await ws.send_text(json.dumps({
                "type": "hello",
                "version": VERSION,
                "adb": adb.adb if adb else None,
                "devices": [
                    {"serial": d.serial, "state": d.state, "label": d.label,
                     "ready": d.ready, "model": d.model, "usb": d.usb}
                    for d in (watcher.devices if watcher else [])
                ],
                "snapshot": session.snapshot,
                "tests": session.suite.catalogue() if session.suite else [],
                "live": session._live_running,
                "settings": {**settings, "demo": demo},
            }, default=str))
            if session.demo_live and session.demo_live.running:
                for past in session.demo_live.history():
                    await ws.send_text(json.dumps(past))

            while True:
                raw = await ws.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                try:
                    await handle_command(session, message, ws)
                except Exception as exc:
                    log.exception("command failed: %r", message.get("command"))
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "command": message.get("command"),
                        "error": f"{type(exc).__name__}: {exc}",
                    }))
        except WebSocketDisconnect:
            pass
        finally:
            session.clients.discard(ws)

    # -------------------------------------------------------------- static

    if os.path.isdir(UI_DIR):
        app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")

    return app


async def handle_command(session: Session, message: dict, ws: WebSocket) -> None:
    """Execute a command sent by the UI."""
    command = message.get("command")

    if command == "analyse":
        session.request_analysis(read_imei=bool(message.get("read_imei", True)))

    elif command == "reread_imei":
        # Repeats only the identity probe, typically after the operator has
        # unlocked the screen.
        session.request_imei_reread()

    elif command == "start_live":
        session.spawn(session.start_live())

    elif command == "stop_live":
        session.spawn(session.stop_live())

    elif command == "run_test":
        params = message.get("params") or {}
        if session.suite and isinstance(params, dict):
            session.spawn(session.suite.run(str(message.get("test", "")), **params))

    elif command == "test_outcome":
        if session.suite:
            session.spawn(session.suite.record_outcome(
                str(message.get("test", "")),
                bool(message.get("passed")),
                str(message.get("detail", "")),
                status="inconclusive" if message.get("status") == "inconclusive" else None,
            ))

    elif command == "settings":
        changes = message.get("settings") or {}
        if isinstance(changes, dict):
            for key in SETTINGS_DEFAULTS:
                if key in changes:
                    session.settings[key] = bool(changes[key])
        await session.broadcast({"type": "settings", "settings": session.settings})

    elif command in ("save_reference", "delete_reference"):
        await _change_reference(session, command, message)

    elif command == "ping":
        await ws.send_text(json.dumps({"type": "pong", "t": time.time()}))


async def _change_reference(session: Session, command: str, message: dict) -> None:
    """Save or forget the reference unit for this model, then re-compare."""
    from .analysis.memory import memory_findings
    from .store import model_key
    snapshot, store = session.snapshot, session.store
    if not snapshot or store is None:
        return
    if command == "save_reference":
        store.save_reference(snapshot, str(message.get("label", ""))[:80])
    else:
        store.delete_reference(model_key(snapshot))
    memory = snapshot.setdefault("memory", {})
    memory["reference"] = store.reference(snapshot)
    report = snapshot["report"]
    report["findings"] = [f for f in report["findings"]
                          if (f.get("evidence") or {}).get("source") != "local memory"]
    report["findings"].extend(memory_findings(memory))
    snapshot["report"] = Analyzer._recount(report)
    await session.broadcast({"type": "report_updated", "report": snapshot["report"],
                             "memory": memory})


async def _reread_imei(session: Session) -> None:
    from .analysis.authenticity import AuthenticityEngine
    from .analysis.imei import analyse_imeis
    from .analysis.specdb import SpecDatabase
    from .collectors.identity import IdentityProbe

    device, snapshot = session.device, session.snapshot
    assert device and snapshot and session.adb
    await session.broadcast({"type": "imei_rereading"})
    try:
        probe = IdentityProbe(
            session.adb, device.serial,
            on_progress=lambda m: session.broadcast(
                {"type": "progress", "step": "identity", "percent": 50,
                 "detail": m}),
        )
        identity = await probe.run()
        if session.snapshot is not snapshot:
            return                      # device changed or re-analysed meanwhile
        if identity.get("evidence"):
            snapshot["evidence"] = identity.pop("evidence")
        snapshot["identity"] = identity

        effective = (snapshot.get("system", {})
                     .get("partitions", {}).get("effective", {}))
        snapshot["imei_analysis"] = analyse_imeis(
            identity.get("imeis", []),
            device_brand=effective.get("brand", ""),
            device_model=effective.get("model", ""),
        )
        snapshot.setdefault("summary", {})["imeis"] = identity.get("imeis", [])

        # Regenerate the report as well, otherwise the newly read IMEI shows in
        # the header while the findings still reflect the state before the
        # read -- including the IMEI checks the operator unlocked the screen for.
        from .analysis.memory import memory_findings
        engine = AuthenticityEngine(snapshot, specdb=SpecDatabase())
        report = engine.run()
        report["findings"].extend(memory_findings(snapshot.get("memory") or {}))
        for f in snapshot["imei_analysis"]["findings"]:
            report["findings"].append({
                "severity": f["severity"],
                "category": "identity",
                "title": f["title"],
                "detail": f["detail"],
                "strength": "proven",
                "strength_label": "Proven",
                "evidence": {},
            })
        snapshot["report"] = Analyzer._recount(report)

        await session.broadcast({
            "type": "imei_updated",
            "identity": identity,
            "evidence": snapshot.get("evidence", []),
            "imei_analysis": snapshot["imei_analysis"],
            "summary": snapshot["summary"],
            "report": snapshot["report"],
        })
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("IMEI re-read failed")
        await session.broadcast({"type": "imei_failed", "error": str(exc)})
