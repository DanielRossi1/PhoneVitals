'use strict';

/**
 * The page's only bridge to the desktop: saving reports through the system
 * file dialog, and the bench-mode folder. Everything else goes through the
 * backend.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('phonevitals', {
  saveReport: (filename, contents) =>
    ipcRenderer.invoke('phonevitals:save-report', filename, contents),
  saveReportPdf: () => ipcRenderer.invoke('phonevitals:save-pdf'),
  benchFolder: (choose = false) => ipcRenderer.invoke('phonevitals:bench-folder', Boolean(choose)),
  saveBench: (base, json) => ipcRenderer.invoke('phonevitals:save-bench', base, json),
});
