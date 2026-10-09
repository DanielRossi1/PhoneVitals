'use strict';

/**
 * Minimal Electron driver for the store screenshots: loads the page, then runs
 * STEPS, a JSON list of {wait: "<js expr>", timeout?} | {js: "<js>"} |
 * {sleep: ms} | {shot: "<file.png>"}.
 */

const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');

const url = process.env.URL;
const steps = JSON.parse(process.env.STEPS || '[]');
const sleep = (ms) => new Promise((r) => { setTimeout(r, ms); });

app.whenReady().then(async () => {
  const width = Number(process.env.W || 1440);
  const height = Number(process.env.H || 900);
  const win = new BrowserWindow({ width, height, useContentSize: true, resizable: false,
    webPreferences: { autoplayPolicy: 'no-user-gesture-required' } });
  win.webContents.on('console-message', (e) => { const m = e.message ?? ''; if (String(m).startsWith('RESULT')) console.log(m); });
  await win.loadURL(url);
  const run = (js) => win.webContents.executeJavaScript(js);
  for (const step of steps) {
    try {
      if (step.wait) {
        const deadline = Date.now() + (step.timeout || 60000);
        while (!(await run(step.wait))) {
          if (Date.now() > deadline) throw new Error(`timed out waiting for ${step.wait}`);
          await sleep(250);
        }
      }
      if (step.js) await run(step.js);
      if (step.sleep) await sleep(step.sleep);
      if (step.shot) {
        // Window managers may maximise or tile the window meanwhile: store
        // screenshots need the exact size.
        if (win.isMaximized()) win.unmaximize();
        if (win.isFullScreen()) win.setFullScreen(false);
        win.setContentSize(width, height);
        await sleep(400);
        fs.writeFileSync(step.shot, (await win.webContents.capturePage()).toPNG());
        console.log(`saved ${step.shot}`);
      }
    } catch (err) {
      console.error(`step failed: ${JSON.stringify(step)}: ${err.message}`);
      process.exitCode = 1;
    }
  }
  app.quit();
});
