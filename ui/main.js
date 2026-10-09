'use strict';

/**
 * Electron main process.
 *
 * Starts the Python backend, waits for it to announce its port, and opens the
 * window on its page. No application logic here.
 */

const {
  app, BrowserWindow, dialog, ipcMain, nativeTheme, screen, session, shell,
} = require('electron');
const { spawn } = require('node:child_process');
const crypto = require('node:crypto');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');

const ROOT = path.resolve(__dirname, '..');
const DEV = process.argv.includes('--dev');

// How the backend is started:
// - installers (dmg, exe, deb): a self-contained executable in resources/;
// - the snap: its launcher points PHONEVITALS_PYTHON/_BACKEND at the bundled
//   interpreter and script;
// - a source checkout: the local toolchain's Python and backend/main.py.
const FROZEN_BACKEND = app.isPackaged ? path.join(process.resourcesPath, 'backend',
  process.platform === 'win32' ? 'phonevitals-backend.exe' : 'phonevitals-backend') : null;
const PYTHON = process.env.PHONEVITALS_PYTHON || firstExisting([
  path.join(ROOT, '.toolchain', 'venv', 'bin', 'python'),
  path.join(ROOT, '.toolchain', 'venv', 'Scripts', 'python.exe'),
]) || (process.platform === 'win32' ? 'python' : 'python3');
const BACKEND = process.env.PHONEVITALS_BACKEND
  || path.join(ROOT, 'backend', 'main.py');

// PHONEVITALS_BACKEND_URL points at an already-running backend instead of
// starting one, including its `?token=` (the backend prints it on startup).
// Used during development and for automated screenshots.
const EXTERNAL_BACKEND = process.env.PHONEVITALS_BACKEND_URL || null;

const STARTUP_TIMEOUT_MS = 30_000;
const LOG_LINES = 400;

let backend = null;
let backendToken = null;
let baseUrl = null;
let win = null;
let quitting = false;
const backendLog = [];

function firstExisting(candidates) {
  return candidates.find((p) => fs.existsSync(p)) || null;
}

function log(line) {
  const text = String(line).trimEnd();
  if (!text) return;
  backendLog.push(text);
  if (backendLog.length > LOG_LINES) backendLog.shift();
  if (DEV) console.log('[backend]', text);
}

/**
 * The Chromium sandbox on Linux requires chrome-sandbox to be owned by root
 * with the setuid bit, which a source checkout cannot have without sudo, and
 * which a snap cannot have at all (there, confinement plays that role).
 *
 * Without it we carry on without the sandbox. The concession is contained:
 * the window loads only pages served by our own backend on 127.0.0.1, with
 * contextIsolation on and nodeIntegration off, and navigation elsewhere is
 * blocked, so it never executes third-party code.
 */
function configureSandbox() {
  // The setuid helper only exists on Linux; elsewhere the sandbox just works.
  if (process.platform !== 'linux') return;
  if (process.env.SNAP) {
    app.commandLine.appendSwitch('no-sandbox');
    return;
  }
  const sandboxPath = path.join(path.dirname(process.execPath), 'chrome-sandbox');
  try {
    const st = fs.statSync(sandboxPath);
    if (st.uid === 0 && (st.mode & 0o4000) !== 0) return;
    log(`chrome-sandbox is not setuid root: starting without the Chromium `
        + `sandbox. To enable it: sudo chown root:root ${sandboxPath} && `
        + `sudo chmod 4755 ${sandboxPath}`);
  } catch {
    // No chrome-sandbox next to the binary: nothing to configure.
  }
  app.commandLine.appendSwitch('no-sandbox');
}

/**
 * Spawn the backend on a free port and resolve with its URL, including the
 * one-time token the page exchanges for a session cookie.
 */
function startBackend() {
  return new Promise((resolve, reject) => {
    const frozen = FROZEN_BACKEND && fs.existsSync(FROZEN_BACKEND);
    if (!frozen && path.isAbsolute(PYTHON) && !fs.existsSync(PYTHON)) {
      reject(new Error(`Python interpreter not found at ${PYTHON}.\n\n`
        + 'Run scripts/setup_toolchain.sh from the project folder first.'));
      return;
    }

    const token = crypto.randomBytes(32).toString('base64url');
    const env = { ...process.env, PYTHONUNBUFFERED: '1', PHONEVITALS_TOKEN: token,
                  PHONEVITALS_VERSION: app.getVersion() };
    if (frozen) env.PHONEVITALS_UI_DIR = path.join(process.resourcesPath, 'web');
    const child = frozen
      ? spawn(FROZEN_BACKEND, ['--port', '0'],
          { cwd: path.dirname(FROZEN_BACKEND), env, stdio: ['ignore', 'pipe', 'pipe'] })
      : spawn(PYTHON, [BACKEND, '--port', '0'],
          { cwd: path.dirname(BACKEND), env, stdio: ['ignore', 'pipe', 'pipe'] });
    backend = child;
    backendToken = token;

    const timer = setTimeout(() => {
      reject(new Error('The backend did not start within '
        + `${STARTUP_TIMEOUT_MS / 1000} seconds.`));
    }, STARTUP_TIMEOUT_MS);

    readline.createInterface({ input: child.stdout }).on('line', (line) => {
      const match = /^PHONEVITALS_LISTENING (\S+)$/.exec(line);
      if (match) {
        clearTimeout(timer);
        resolve(`http://${match[1]}/?token=${token}`);
      } else {
        log(line);
      }
    });
    readline.createInterface({ input: child.stderr }).on('line', log);

    child.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });

    child.on('exit', (code, signal) => {
      clearTimeout(timer);
      if (backend === child) backend = null;
      if (quitting) return;
      const reason = signal ? `signal ${signal}` : `exit code ${code}`;
      reject(new Error(`The backend stopped during startup (${reason}).`));
      if (win) {
        dialog.showErrorBox('The backend stopped',
          `${reason}.\n\nLast lines:\n${backendLog.slice(-15).join('\n')}`);
        app.quit();
      }
    });
  });
}

/**
 * Shut the backend down and give it time to clean up: it removes the agent
 * from the phone and stops the adb child processes it started.
 *
 * It is asked through its API first, which works on every platform (Windows
 * has no SIGTERM, and kill() there ends the process without any cleanup);
 * a signal and finally a hard kill follow if it does not go.
 */
function stopBackend() {
  const child = backend;
  backend = null;
  if (!child || child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
  return new Promise((resolve) => {
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    child.once('exit', finish);
    if (baseUrl && backendToken) {
      const req = http.request(new URL('/api/shutdown', baseUrl), {
        method: 'POST', headers: { Authorization: `Bearer ${backendToken}` }, timeout: 1500,
      });
      req.on('error', () => {});
      req.end();
    }
    setTimeout(() => { try { child.kill('SIGTERM'); } catch { /* gone */ } }, 3000).unref();
    setTimeout(() => { try { child.kill('SIGKILL'); } catch { /* gone */ } finish(); }, 6000).unref();
  });
}

/**
 * Initial window size.
 *
 * A window larger than the screen is born oversized, and if its minimum is
 * larger than the usable area the window manager will not let it shrink. So
 * start from what the screen allows, leaving room for panels and decorations,
 * and keep the minimums low because the interface is fluid.
 */
function windowGeometry() {
  const area = screen.getPrimaryDisplay().workAreaSize;
  const width = Math.max(640, Math.min(1440, area.width - 40));
  const height = Math.max(480, Math.min(940, area.height - 60));
  return {
    width,
    height,
    minWidth: Math.min(720, width),
    minHeight: Math.min(520, height),
  };
}

function isAppUrl(url) {
  try {
    return new URL(url).origin === new URL(baseUrl).origin;
  } catch {
    return false;
  }
}

function openExternally(url) {
  try {
    const { protocol } = new URL(url);
    if (protocol === 'https:' || protocol === 'http:') shell.openExternal(url);
  } catch {
    // Not a URL: ignore.
  }
}

function createWindow() {
  win = new BrowserWindow({
    ...windowGeometry(),
    // Matches the page background, so the window does not flash on load.
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#0c1016' : '#f4f5f8',
    // Shown in the taskbar on Linux; installers embed their own icon.
    icon: path.join(__dirname, 'assets', 'icon.png'),
    show: false,
    autoHideMenuBar: true,
    title: 'PhoneVitals',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
      // The loudspeaker test opens the microphone when the phone starts
      // playing, not inside the click that launched it.
      autoplayPolicy: 'no-user-gesture-required',
    },
  });

  win.once('ready-to-show', () => win.show());
  win.on('closed', () => { win = null; });

  // Links that leave the app open in the system browser; nothing else may
  // replace the page or open new windows.
  win.webContents.setWindowOpenHandler(({ url }) => {
    openExternally(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    if (isAppUrl(url)) return;
    event.preventDefault();
    openExternally(url);
  });

  // Keyboard zoom. On a small laptop panel some tabs are dense, and being
  // able to shrink everything a couple of steps beats any size chosen up
  // front. The menu bar is hidden, so the shortcuts are handled here.
  win.webContents.on('before-input-event', (event, input) => {
    if ((!input.control && !input.meta) || input.type !== 'keyDown') return;
    const wc = win.webContents;
    if (input.key === '+' || input.key === '=') {
      wc.setZoomLevel(Math.min(wc.getZoomLevel() + 0.5, 4));
    } else if (input.key === '-' || input.key === '_') {
      wc.setZoomLevel(Math.max(wc.getZoomLevel() - 0.5, -4));
    } else if (input.key === '0') {
      wc.setZoomLevel(0);
    } else {
      return;
    }
    event.preventDefault();
  });

  if (DEV) win.webContents.openDevTools({ mode: 'detach' });
  setupScreenshot();

  win.loadURL(baseUrl);
}

/**
 * --screenshot=<file>[,<seconds>[,<WIDTHxHEIGHT>]] captures the window and
 * exits, so rendering can be checked without watching it. PHONEVITALS_TAB
 * selects a page first (overview, authenticity, health, tests, live, specs,
 * raw) and PHONEVITALS_THEME a theme (light, dark). capturePage is used rather than an external X tool,
 * which fails on Chromium surfaces.
 */
function setupScreenshot() {
  const arg = process.argv.find((a) => a.startsWith('--screenshot='));
  if (!arg) return;
  const [file, delay, size] = arg.slice('--screenshot='.length).split(',');
  const waitMs = (parseFloat(delay) || 3) * 1000;
  const sleep = (ms) => new Promise((r) => { setTimeout(r, ms); });

  win.webContents.once('did-finish-load', async () => {
    await sleep(waitMs);
    try {
      if (size && /^\d+x\d+$/.test(size)) {
        const [w, h] = size.split('x').map(Number);
        win.setMinimumSize(Math.min(320, w), Math.min(320, h));
        win.setSize(w, h);
        await sleep(500);
      }
      const theme = process.env.PHONEVITALS_THEME;
      if (theme) {
        await win.webContents.executeJavaScript(
          `document.documentElement.dataset.theme = ${JSON.stringify(theme)}`);
      }
      const tab = process.env.PHONEVITALS_TAB;
      if (tab) {
        await win.webContents.executeJavaScript(`location.hash = ${JSON.stringify(tab)}`);
        await sleep(700);
      }
      const image = await win.webContents.capturePage();
      fs.writeFileSync(file, image.toPNG());
      console.log(`screenshot saved: ${file}`);
    } catch (err) {
      console.error(`capture failed: ${err.message}`);
    }
    app.quit();
  });
}

/** Save a report where the user chooses, through the system file dialog. */
ipcMain.handle('phonevitals:save-report', async (event, filename, contents) => {
  if (!win || !isAppUrl(event.senderFrame?.url ?? '')) {
    throw new Error('Request not allowed.');
  }
  if (typeof filename !== 'string' || typeof contents !== 'string') {
    throw new Error('Invalid report.');
  }
  const name = path.basename(filename).replace(/[^\w.-]+/g, '_') || 'report.json';
  const { canceled, filePath } = await dialog.showSaveDialog(win, {
    title: 'Save report',
    defaultPath: path.join(app.getPath('documents'), name),
    filters: [{ name: 'JSON report', extensions: ['json'] }],
  });
  if (canceled || !filePath) return { cancelled: true };
  await fs.promises.writeFile(filePath, contents, 'utf8');
  return { saved: filePath };
});

/**
 * Print the `#print` page to PDF in a hidden window of the same session (so
 * it carries the session cookie) and save it where the user chooses.
 */
async function renderReportPdf() {
  const origin = new URL(baseUrl).origin;
  const printer = new BrowserWindow({
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  try {
    await printer.loadURL(`${origin}/#print`);
    const deadline = Date.now() + 20_000;
    while (!(await printer.webContents.executeJavaScript(
      "!!document.querySelector('[data-print-ready]') || !!document.querySelector('.error')"))) {
      if (Date.now() > deadline) throw new Error('the report did not render in time');
      await new Promise((r) => { setTimeout(r, 200); });
    }
    const failed = await printer.webContents.executeJavaScript(
      "document.querySelector('.error')?.textContent || ''");
    if (failed) throw new Error(failed);
    const title = await printer.webContents.executeJavaScript('document.title');
    const pdf = await printer.webContents.printToPDF({
      pageSize: 'A4', printBackground: true, preferCSSPageSize: true,
    });
    return { pdf, name: `${String(title).replace(/[^\w.-]+/g, '_') || 'phonevitals-report'}.pdf` };
  } finally {
    printer.destroy();
  }
}

// Bench mode writes reports without asking each time, but only into the
// folder the user picked through the system dialog; it is remembered here.
const benchFile = () => path.join(app.getPath('userData'), 'bench.json');
let benchFolder = null;

function loadBenchFolder() {
  try {
    const saved = JSON.parse(fs.readFileSync(benchFile(), 'utf8')).folder;
    if (typeof saved === 'string' && fs.statSync(saved).isDirectory()) benchFolder = saved;
  } catch {
    // Never chosen, or gone since.
  }
}

ipcMain.handle('phonevitals:bench-folder', async (event, choose) => {
  if (!win || !isAppUrl(event.senderFrame?.url ?? '')) throw new Error('Request not allowed.');
  if (choose) {
    const { canceled, filePaths } = await dialog.showOpenDialog(win, {
      title: 'Folder for the bench reports',
      defaultPath: benchFolder || app.getPath('documents'),
      properties: ['openDirectory', 'createDirectory'],
    });
    if (!canceled && filePaths[0]) {
      benchFolder = filePaths[0];
      await fs.promises.writeFile(benchFile(), JSON.stringify({ folder: benchFolder }));
    }
  }
  return benchFolder;
});

ipcMain.handle('phonevitals:save-bench', async (event, base, json) => {
  if (!win || !isAppUrl(event.senderFrame?.url ?? '')) throw new Error('Request not allowed.');
  if (!benchFolder) throw new Error('No bench folder chosen.');
  if (typeof base !== 'string' || typeof json !== 'string') throw new Error('Invalid report.');
  const name = path.basename(base).replace(/[^\w.-]+/g, '_').replace(/\.json$/i, '') || 'report';
  const jsonPath = path.join(benchFolder, `${name}.json`);
  const pdfPath = path.join(benchFolder, `${name}.pdf`);
  await fs.promises.writeFile(jsonPath, json, 'utf8');
  const { pdf } = await renderReportPdf();
  await fs.promises.writeFile(pdfPath, pdf);
  return { folder: benchFolder, files: [jsonPath, pdfPath] };
});

ipcMain.handle('phonevitals:save-pdf', async (event) => {
  if (!win || !isAppUrl(event.senderFrame?.url ?? '')) throw new Error('Request not allowed.');
  const { pdf, name } = await renderReportPdf();
  const { canceled, filePath } = await dialog.showSaveDialog(win, {
    title: 'Save PDF report',
    defaultPath: path.join(app.getPath('documents'), name),
    filters: [{ name: 'PDF report', extensions: ['pdf'] }],
  });
  if (canceled || !filePath) return { cancelled: true };
  await fs.promises.writeFile(filePath, pdf);
  return { saved: filePath };
});

if (!app.requestSingleInstanceLock()) {
  // Another instance already owns the adb session: focus it and leave.
  app.quit();
} else {
  configureSandbox();

  app.on('second-instance', () => {
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.focus();
  });

  app.whenReady().then(async () => {
    loadBenchFolder();
    // The page needs the clipboard and, for the loudspeaker test, the
    // microphone (audio only); never the camera, notifications and the like.
    const allowed = (permission, origin, mediaTypes = []) => {
      if (permission === 'clipboard-sanitized-write') return true;
      return permission === 'media' && isAppUrl(origin || '')
        && mediaTypes.length > 0 && mediaTypes.every((t) => t === 'audio');
    };
    session.defaultSession.setPermissionRequestHandler((wc, permission, callback, details) =>
      callback(allowed(permission, details.requestingUrl || wc.getURL(), details.mediaTypes)));
    session.defaultSession.setPermissionCheckHandler((_wc, permission, origin, details) =>
      allowed(permission, origin, details?.mediaType ? [details.mediaType] : ['audio']));

    try {
      baseUrl = EXTERNAL_BACKEND || await startBackend();
    } catch (err) {
      dialog.showErrorBox('PhoneVitals could not start',
        `${err.message}\n\nLast backend lines:\n${backendLog.slice(-20).join('\n')}`);
      quitting = true;
      stopBackend();
      app.quit();
      return;
    }
    createWindow();
  });
}

app.on('window-all-closed', () => app.quit());

// Quitting waits for the backend to finish its cleanup on the phone.
let backendStopped = false;
app.on('will-quit', (event) => {
  quitting = true;
  if (backendStopped || !backend) return;
  event.preventDefault();
  stopBackend().finally(() => {
    backendStopped = true;
    app.quit();
  });
});

process.on('exit', () => {
  try { backend?.kill(); } catch { /* gone */ }
});
// Termination from the terminal (Ctrl-C, kill): without these handlers
// Electron exits and leaves the backend orphaned.
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(signal, () => {
    quitting = true;
    app.quit();
  });
}
