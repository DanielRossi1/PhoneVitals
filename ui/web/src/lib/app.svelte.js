/**
 * Application state and the connection to the backend.
 *
 * The backend pushes everything over one WebSocket: device events, analysis
 * progress, the snapshot, live streams and test results. This module turns
 * those messages into reactive state; components only read it and call the
 * actions at the bottom.
 */

import { clearLive, live } from './canvas.js';
import { fixed, num } from './format.js';
import { playTones, speakerOutcome, startListening } from './listen.js';

const WS_UNAUTHORISED = 4401;
export const SESSION_EXPIRED = 'Session expired — restart PhoneVitals';

export const SENSOR = {
  ACCELEROMETER: 1, MAGNETIC: 2, GYROSCOPE: 4, LIGHT: 5,
  PRESSURE: 6, PROXIMITY: 8, GRAVITY: 9, LINEAR_ACCEL: 10,
  ROTATION: 11, STEP_COUNTER: 19,
};

function emptyLive() {
  return {
    running: false,
    agent: null,                // agent_status message
    problems: [],               // errors the agent reported while streaming
    readouts: {},               // sensorType -> values
    battery: null,
    thermal: [],
    tempMax: null,
    cpu: [],
    fingers: 0,
    gnss: { sats: [], used: 0, seen: false, summary: '', hint: '' },
  };
}

export const app = $state({
  connection: 'connecting',     // connecting | online | offline | expired | fatal
  fatal: '',
  version: '',
  devices: [],
  screen: 'waiting',            // waiting | blocked | analysing | dashboard
  blocked: { title: '', detail: '' },
  progress: { percent: 0, step: '', detail: '', log: [] },
  snapshot: null,
  tests: [],
  results: {},
  progress_: {},               // test id -> short progress text while it runs
  live: emptyLive(),
  dialog: null,                 // id of the guided test being run
  keysPressed: [],
  autoQueue: [],                // automatic tests still to run in sequence
  page: 'overview',
  toasts: [],
  bench: { available: false, enabled: false, folder: null, busy: false },
});

// --------------------------------------------------------------- bench mode

// One phone after another: analyse, run every automatic test, save the PDF
// and the JSON into a chosen folder, wait for the next phone.
const BENCH_KEY = 'phonevitals.bench';

export async function initBench() {
  if (typeof window.phonevitals?.benchFolder !== 'function') return;
  app.bench.available = true;
  app.bench.folder = await window.phonevitals.benchFolder(false);
  try {
    app.bench.enabled = localStorage.getItem(BENCH_KEY) === 'on' && Boolean(app.bench.folder);
  } catch {
    app.bench.enabled = false;
  }
}

export async function chooseBenchFolder() {
  app.bench.folder = await window.phonevitals.benchFolder(true);
}

export function setBench(on) {
  app.bench.enabled = on && Boolean(app.bench.folder);
  try { localStorage.setItem(BENCH_KEY, app.bench.enabled ? 'on' : 'off'); } catch { /* session only */ }
}

function benchAfterAnalysis() {
  if (!app.bench.enabled || app.bench.busy) return;
  app.bench.busy = true;
  app.page = 'tests';
  runAutomaticTests();
  if (!app.autoQueue.length) benchSave();
}

async function benchSave() {
  try {
    const res = await fetch('/api/report', { cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error || `HTTP ${res.status}`);
    const saved = await window.phonevitals.saveBench(data.filename,
                                                    JSON.stringify(data.report, null, 2));
    toast(`Bench: report saved in ${saved.folder}. Connect the next phone.`, 'ok', 8000);
  } catch (err) {
    toast(`Bench: saving failed: ${err.message || err}`, 'crit', 8000);
  } finally {
    app.bench.busy = false;
  }
}

// Raw sensor values arrive at ~50 Hz per sensor: keep the latest outside the
// reactive state and publish them a few times a second, which is all a
// readout needs.
const latest = {};
let publishTimer = 0;

function publishReadouts() {
  publishTimer = 0;
  app.live.readouts = { ...latest };
}

// ------------------------------------------------------------------ socket

let ws = null;
let helloReceived = false;
let reconnectDelay = 500;
let reconnectTimer = 0;

export function connect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = 0;
  // Same origin as the page: the session cookie set when the page was loaded
  // is sent with the upgrade request.
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${proto}//${location.host}/ws`);
  ws = socket;
  helloReceived = false;

  socket.addEventListener('message', (ev) => {
    if (ws !== socket) return;
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg && typeof msg === 'object') handle(msg);
  });
  // `error` is always followed by `close`, which handles reconnection.
  socket.addEventListener('close', (ev) => {
    if (ws !== socket) return;
    ws = null;
    if (ev.code === WS_UNAUTHORISED) {
      sessionExpired();
      return;
    }
    if (app.connection !== 'fatal') app.connection = 'offline';
    scheduleReconnect();
  });
}

function scheduleReconnect() {
  if (app.connection === 'expired' || reconnectTimer) return;
  // Growing backoff with jitter: no point hammering a dead backend, but it
  // must come back quickly after a restart.
  const delay = reconnectDelay * (0.8 + Math.random() * 0.4);
  reconnectDelay = Math.min(reconnectDelay * 1.6, 5000);
  reconnectTimer = setTimeout(connect, delay);
}

export function sessionExpired() {
  app.connection = 'expired';
  clearTimeout(reconnectTimer);
  reconnectTimer = 0;
  if (ws) {
    const s = ws;
    ws = null;
    s.close();
  }
  app.dialog = null;
}

export function send(payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(payload));
    return true;
  }
  toast(app.connection === 'expired' ? SESSION_EXPIRED : 'Not connected to the local service',
        'crit');
  return false;
}

// --------------------------------------------------------------- messages

function handle(msg) {
  switch (msg.type) {
    case 'hello': return onHello(msg);

    case 'fatal':
      // The on-device agent's own crash reports use the same type.
      if (helloReceived) agentProblem(msg.message || msg.exception || 'The agent stopped', msg.trace);
      else {
        app.connection = 'fatal';
        app.fatal = msg.message || 'The local service cannot run.';
        resetSession();
        app.screen = 'waiting';
      }
      return;

    case 'device_attached':
    case 'device_changed': {
      const d = msg.device || {};
      upsertDevice(d);
      if (d.ready && app.screen === 'blocked') app.screen = app.snapshot ? 'dashboard' : 'waiting';
      return;
    }

    case 'device_detached':
      app.devices = app.devices.filter((d) => d.serial !== msg.device?.serial);
      return;

    case 'device_blocked': {
      const info = msg.info || {};
      app.blocked = { title: info.title || 'Device not ready', detail: info.detail || '' };
      app.screen = 'blocked';
      return;
    }

    case 'device_gone':
      resetSession();
      app.screen = 'waiting';
      return;

    case 'analysis_started':
      resetSession({ live: false });
      app.progress = { percent: 0, step: '', detail: 'Starting…', log: [] };
      app.screen = 'analysing';
      return;

    case 'progress': return onProgress(msg);

    case 'analysis_complete':
      app.results = {};
      applySnapshot(msg.snapshot, msg.tests);
      benchAfterAnalysis();
      return;

    case 'analysis_failed':
      toast(`Analysis failed: ${msg.error || 'unknown error'}`, 'crit');
      app.screen = app.snapshot ? 'dashboard' : 'waiting';
      return;

    case 'live_started': app.live.running = true; return;
    case 'live_stopped': app.live.running = false; return;
    case 'agent_status': app.live.agent = msg; return;

    case 'agent_error':
    case 'error':
      agentProblem(msg.message || msg.error || 'unknown error');
      return;

    case 'sensor': return onSensor(msg);

    case 'touch':
      live.touch.update(msg);
      app.live.fingers = num(msg.count) ?? (Array.isArray(msg.points) ? msg.points.length : 0);
      return;

    case 'gnss': return onGnss(msg);
    case 'gnss_note': app.live.gnss.hint = String(msg.message || ''); return;
    case 'gnss_fix': return onGnssFix(msg);
    case 'gnss_event': return onGnssEvent(msg);
    case 'metrics': return onMetrics(msg);

    case 'test_update':
      if (msg.test?.id) {
        app.results[msg.test.id] = msg.test;
        if (msg.test.status !== 'running') {
          delete app.progress_[msg.test.id];
          advanceAutoQueue(msg.test.id);
        }
      }
      return;

    case 'test_step':
      if (msg.test === 'buttons' && typeof msg.step === 'string'
          && !app.keysPressed.includes(msg.step)) {
        app.keysPressed = [...app.keysPressed, msg.step];
      } else if (msg.test === 'speaker') {
        onSpeakerStep(msg);
      } else if (msg.test === 'stress' && typeof msg.step === 'string') {
        app.progress_.stress = `Under load: ${msg.step} of 30 s`;
      } else if (msg.test === 'microphone' && msg.step === 'play') {
        app.progress_.microphone = 'Playing tones on this computer…';
        const tones = Array.isArray(msg.tones) ? msg.tones.map(Number).filter(Boolean) : [];
        playTones(tones, { ms: num(msg.ms) ?? 900, gapMs: num(msg.gap_ms) ?? 350,
                           delayMs: num(msg.delay_ms) ?? 900 })
          .catch((err) => toast(`Could not play the test tones: ${err.message}`, 'warn'));
      } else if (msg.test === 'gnss' && typeof msg.step === 'string') {
        app.progress_.gnss = `Listening for satellites: ${msg.step}`;
      }
      return;

    case 'imei_rereading': toast('Reading the identifiers again…'); return;

    case 'imei_updated': {
      const s = app.snapshot;
      if (!s) return;
      if (msg.identity) s.identity = msg.identity;
      if (msg.evidence) s.evidence = msg.evidence;
      if (msg.imei_analysis) s.imei_analysis = msg.imei_analysis;
      if (msg.summary) s.summary = msg.summary;
      if (msg.report) s.report = msg.report;
      toast('Identifiers updated', 'ok');
      return;
    }

    case 'imei_failed':
      toast(`IMEI read failed: ${msg.error || 'unknown error'}`, 'crit');
      return;

    case 'report_updated':
      if (app.snapshot) {
        app.snapshot.report = msg.report;
        app.snapshot.memory = msg.memory;
      }
      return;

    case 'settings':
      return;
  }
}

function onHello(msg) {
  helloReceived = true;
  // Only a session that got this far resets the backoff: a server that
  // accepts and immediately closes must not be retried every 500 ms.
  reconnectDelay = 500;
  app.connection = 'online';
  app.fatal = '';
  app.version = msg.version || '';
  app.devices = Array.isArray(msg.devices) ? msg.devices : [];

  if (msg.snapshot) {
    // A different snapshot after a reconnect means a different session.
    if (snapshotKey(msg.snapshot) !== snapshotKey(app.snapshot)) {
      resetSession({ live: Boolean(app.snapshot) });
    }
    applySnapshot(msg.snapshot, msg.tests);
  } else if (app.snapshot) {
    // After a backend restart the dashboard belongs to a session that no
    // longer exists.
    resetSession();
    app.screen = 'waiting';
  }
  app.live.running = Boolean(msg.live);
}

function upsertDevice(d) {
  if (!d.serial) return;
  const others = app.devices.filter((x) => x.serial !== d.serial);
  app.devices = [...others, d];
}

function snapshotKey(s) {
  if (!s) return '';
  const meta = s.meta || {};
  return `${meta.serial ?? ''}|${meta.finished_at ?? ''}`;
}

function applySnapshot(snapshot, tests) {
  if (!snapshot || typeof snapshot !== 'object') return;
  app.snapshot = snapshot;
  app.tests = Array.isArray(tests) ? tests : [];
  app.screen = 'dashboard';
}

/** Forget everything tied to the current device. `live: false` keeps the
 * live view, for a re-analysis during which the streams keep running. */
function resetSession({ live: resetLive = true } = {}) {
  app.dialog = null;
  app.bench.busy = false;
  app.snapshot = null;
  app.tests = [];
  app.results = {};
  app.progress_ = {};
  app.autoQueue = [];
  if (resetLive) {
    clearLive();
    for (const k of Object.keys(latest)) delete latest[k];
    app.live = emptyLive();
  }
}

function onProgress(msg) {
  const percent = Math.round(Math.max(0, Math.min(100, num(msg.percent) ?? 0)));
  const detail = String(msg.detail || msg.step || '');
  // A client that connects mid-analysis gets progress without having seen
  // `analysis_started`. With a snapshot on screen this is the IMEI re-read,
  // which must not take over the dashboard.
  if (!app.snapshot && app.screen !== 'analysing') app.screen = 'analysing';
  const log = app.progress.log.length > 200 ? app.progress.log.slice(-200) : app.progress.log;
  app.progress = {
    percent,
    step: String(msg.step || ''),
    detail,
    log: [...log, { percent, step: String(msg.step || ''), detail }],
  };
}

function agentProblem(message, detail) {
  const text = String(message);
  if (app.live.problems.some((p) => p.text === text)) return;
  app.live.problems = [...app.live.problems, { text, detail: detail ? String(detail) : '' }].slice(-3);
}

// ------------------------------------------------------------------- live

function onSensor(msg) {
  const v = Array.isArray(msg.values) ? msg.values : [];
  latest[msg.sensorType] = v;
  switch (msg.sensorType) {
    case SENSOR.ACCELEROMETER: live.accel.push(v); break;
    case SENSOR.GYROSCOPE: live.gyro.push(v); break;
    case SENSOR.MAGNETIC: live.mag.push(v); break;
  }
  if (!publishTimer) publishTimer = setTimeout(publishReadouts, 120);
}

function onMetrics(msg) {
  const b = msg.battery || {};
  app.live.battery = {
    level: num(b.level),
    voltage: num(b.voltage_v),
    current: num(b.current_ma),
    temperature: num(b.temperature_c),
    status: b.status ? String(b.status) : '',
  };

  const thermal = Object.entries(msg.thermal || {})
    .map(([name, t]) => ({ name: String(name), t: num(t) }))
    .filter((x) => x.t !== null)
    .sort((a, b) => b.t - a.t);
  if (thermal.length) {
    live.temp.push([thermal[0].t]);
    app.live.tempMax = thermal[0].t;
    app.live.thermal = thermal.slice(0, 12);
  }

  const cpuIndex = (name) => parseInt(name.replace(/\D+/g, ''), 10) || 0;
  app.live.cpu = Object.entries(msg.cpu_freq_khz || {})
    .map(([name, khz]) => ({ name: String(name), khz: num(khz) }))
    .filter((x) => x.khz !== null)
    .sort((a, b) => cpuIndex(a.name) - cpuIndex(b.name));
}

function onGnss(msg) {
  const sats = Array.isArray(msg.satellites) ? msg.satellites : [];
  live.sky.update(sats);
  const used = num(msg.used) ?? 0;
  app.live.gnss = {
    ...app.live.gnss,
    sats: [...sats].sort((a, b) => (num(b.cn0) ?? 0) - (num(a.cn0) ?? 0)).slice(0, 32),
    used,
    seen: true,
    summary: `${sats.length} in view · ${used} used in fix`,
  };
}

function onGnssFix(msg) {
  // A computed fix already proves the receiver works, even when the
  // individual satellites are not listed.
  if (app.live.gnss.seen) return;
  const accuracy = Math.round(num(msg.accuracy_m) ?? 0);
  const altitude = Math.round(num(msg.altitude_m) ?? 0);
  app.live.gnss.summary = `Fix obtained, ±${accuracy} m`;
  app.live.gnss.hint = `The receiver returned a fix with an accuracy of about ${accuracy} m, `
    + `altitude ${altitude} m. Android does not provide the per-satellite list to `
    + 'background processes: a system limitation, not a fault of the phone.';
}

function onGnssEvent(msg) {
  if (msg.event === 'status_refused') {
    app.live.gnss.hint = 'The system refused registration for satellite status: '
      + 'the receiver cannot be queried from here.';
  } else if (msg.event === 'first_fix') {
    app.live.gnss.hint = `First fix in ${fixed((num(msg.ttff_ms) ?? 0) / 1000, 1)} s: `
      + 'the GNSS receiver works.';
  }
}

// -------------------------------------------------------------- speaker

// The phone plays, this computer listens: the verdict is measured here and
// sent back to be recorded with the other results.
let listening = null;

function onSpeakerStep(msg) {
  if (msg.step === 'listen') {
    app.progress_.speaker = 'Listening with the computer microphone…';
    const tones = Array.isArray(msg.tones) ? msg.tones.map(Number).filter(Boolean) : [];
    listening = startListening(tones).catch((err) => ({ error: err }));
  } else if (msg.step === 'tone') {
    app.progress_.speaker = `Playing ${num(msg.hz) ?? '?'} Hz…`;
    listening?.then((l) => l.tonesStarted?.());
  } else if (msg.step === 'done' && listening) {
    const pending = listening;
    listening = null;
    pending.then(async (l) => {
      const outcome = l.error
        ? { status: 'inconclusive', passed: false,
            detail: `The computer microphone could not be used (${l.error.message || l.error}). `
                    + 'Check by ear with the Speakers and microphone test.' }
        : speakerOutcome(await l.stop());
      send({ command: 'test_outcome', test: 'speaker', ...outcome });
    });
  }
}

// ---------------------------------------------------------------- actions

export function reanalyse() {
  if (send({ command: 'analyse' })) toast('Analysis started');
}

export function saveReference() {
  if (send({ command: 'save_reference' })) toast('Saved as the reference for this model', 'ok');
}

export function forgetReference() {
  if (send({ command: 'delete_reference' })) toast('Reference removed');
}

export function rereadImei() {
  send({ command: 'reread_imei' });
}

export function setLive(on) {
  send({ command: on ? 'start_live' : 'stop_live' });
}

export function runTest(id, params) {
  return send(params ? { command: 'run_test', test: id, params } : { command: 'run_test', test: id });
}

/** Start a test. Guided ones open the dialog; automatic ones just run, since
 * asking the operator would overwrite a measurement with an opinion. */
export function startTest(id) {
  const meta = app.tests.find((t) => t.id === id);
  if (!meta?.available) return;
  if (!runTest(id)) return;
  if (meta.kind === 'automatic') return;
  app.keysPressed = [];
  if (id === 'touch' || id === 'multitouch') live.touch.resetCoverage();
  app.dialog = id;
}

/** Run every available automatic test, one after another: they share the
 * sensors and the vibration motor, so running them together would spoil the
 * measurements. */
export function runAutomaticTests() {
  const ids = app.tests.filter((t) => t.kind === 'automatic' && t.available).map((t) => t.id);
  if (!ids.length || app.autoQueue.length) return;
  app.autoQueue = ids;
  if (!runTest(ids[0])) app.autoQueue = [];
}

function advanceAutoQueue(finishedId) {
  if (app.autoQueue[0] !== finishedId) return;
  const rest = app.autoQueue.slice(1);
  app.autoQueue = rest;
  if (rest.length && !runTest(rest[0])) app.autoQueue = [];
  if (!app.autoQueue.length && app.bench.busy) benchSave();
}

/** Close the guided-test dialog, recording the operator's verdict unless
 * `passed` is null (skipped). */
export function finishTest(passed) {
  const id = app.dialog;
  if (id && passed !== null) {
    const sent = send({
      command: 'test_outcome',
      test: id,
      passed,
      detail: passed ? 'Confirmed by the operator.' : 'The operator reported a malfunction.',
    });
    // Keep the dialog open so the verdict is not silently lost.
    if (!sent) return;
  }
  app.dialog = null;
}

/**
 * Fetch the report and let the user save it. Inside Electron the preload
 * offers the native save dialog; in a plain browser the file is downloaded.
 */
export async function exportReport() {
  const res = await fetch('/api/report', { headers: { Accept: 'application/json' }, cache: 'no-store' });
  if (res.status === 401) {
    sessionExpired();
    return;
  }
  let data = null;
  try { data = await res.json(); } catch { /* error bodies may not be JSON */ }
  if (!res.ok || !data?.report) throw new Error(data?.error || `the service answered ${res.status}`);

  const filename = safeFilename(data.filename);
  const text = JSON.stringify(data.report, null, 2);
  if (typeof window.phonevitals?.saveReport === 'function') {
    const result = await window.phonevitals.saveReport(filename, text);
    if (result?.saved) toast(`Report saved to ${result.saved}`, 'ok', 6000);
  } else {
    const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: filename, hidden: true });
    document.body.append(a);
    a.click();
    a.remove();
    // Revoking straight away can cancel the download before it starts.
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  }
}

/** The printable report as PDF: produced by the desktop app from the `#print`
 * page; in a browser that page opens and offers the print dialog instead. */
export async function exportPdf() {
  if (typeof window.phonevitals?.saveReportPdf === 'function') {
    const result = await window.phonevitals.saveReportPdf();
    if (result?.saved) toast(`Report saved to ${result.saved}`, 'ok', 6000);
  } else {
    window.open(`${location.origin}${location.pathname}#print`, '_blank');
  }
}

function safeFilename(name) {
  const base = String(name || '').split(/[\\/]/).pop().replace(/[\u0000-\u001f<>:"|?*]/g, '_').trim();
  const clean = base && !/^\.+$/.test(base) ? base : 'phonevitals-report.json';
  return clean.toLowerCase().endsWith('.json') ? clean : `${clean}.json`;
}

// ----------------------------------------------------------------- toasts

let toastId = 0;

export function toast(text, tone = 'info', ms = 3500) {
  const id = ++toastId;
  app.toasts = [...app.toasts.slice(-2), { id, text, tone }];
  setTimeout(() => { app.toasts = app.toasts.filter((t) => t.id !== id); }, ms);
}

const PAGE_IDS = ['overview', 'authenticity', 'health', 'tests', 'live', 'specs', 'raw'];

/** Pages are reflected in the URL hash, so a reload stays on the same page. */
export function navigate(page) {
  if (!PAGE_IDS.includes(page)) return;
  app.page = page;
  if (location.hash.slice(1) !== page) history.replaceState(null, '', `#${page}`);
}

function pageFromHash() {
  const page = location.hash.slice(1);
  if (PAGE_IDS.includes(page)) app.page = page;
}

pageFromHash();
addEventListener('hashchange', pageFromHash);
