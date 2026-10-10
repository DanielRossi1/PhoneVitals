/**
 * Live canvases, drawn by hand.
 *
 * With a dozen series updating at 50 Hz a charting library would cost more
 * than it is worth. Each view keeps its data whether or not a canvas is
 * attached, so switching to the Live page shows the recent past immediately;
 * drawing happens on demand, in one animation frame for all views, and only
 * for views that changed and are on screen.
 */

import { num } from './format.js';
import { palette } from './palette.js';
import { onThemeChange } from './theme.svelte.js';

const views = new Set();
let frame = 0;

function schedule() {
  if (!frame) frame = requestAnimationFrame(drawAll);
}

function drawAll() {
  frame = 0;
  for (const v of views) {
    if (v.dirty && v.canvas) v.render();
  }
}

function markAll() {
  for (const v of views) v.dirty = true;
  schedule();
}

const resizeObserver = new ResizeObserver(markAll);
onThemeChange(markAll);

// Moving the window to a monitor with a different scale factor changes the
// pixel ratio without changing any CSS size, so no ResizeObserver fires.
(function watchPixelRatio() {
  matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`)
    .addEventListener('change', () => { markAll(); watchPixelRatio(); }, { once: true });
})();

/** Match the backing store to the CSS size; null while not laid out. */
function fit(canvas) {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return null;
  const dpr = window.devicePixelRatio || 1;
  const bw = Math.round(w * dpr), bh = Math.round(h * dpr);
  if (canvas.width !== bw || canvas.height !== bh) {
    canvas.width = bw;
    canvas.height = bh;
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

class View {
  canvas = null;
  dirty = true;

  constructor() { views.add(this); }

  /** Svelte action: `<canvas use:view.attach>`. */
  attach = (canvas) => {
    this.canvas = canvas;
    resizeObserver.observe(canvas);
    this.touch();
    return {
      destroy: () => {
        resizeObserver.unobserve(canvas);
        if (this.canvas === canvas) this.canvas = null;
      },
    };
  };

  touch() {
    this.dirty = true;
    schedule();
  }

  render() {
    const f = fit(this.canvas);
    if (!f) return;
    this.dirty = false;
    f.ctx.clearRect(0, 0, f.w, f.h);
    this.draw(f.ctx, f.w, f.h, palette());
  }
}

/** Scrolling line chart over a fixed-size window of samples. */
export class LineChart extends View {
  constructor({ series = 3, capacity = 180, symmetric = true, minRange = 1, colors = null } = {}) {
    super();
    this.count = series;
    this.capacity = capacity;
    this.symmetric = symmetric;
    this.minRange = minRange;
    this.colors = colors;
    this.series = Array.from({ length: series }, () => []);
  }

  push(values) {
    for (let i = 0; i < this.count; i++) {
      const s = this.series[i];
      s.push(num(values[i]) ?? 0);
      if (s.length > this.capacity) s.shift();
    }
    this.touch();
  }

  clear() {
    this.series = Array.from({ length: this.count }, () => []);
    this.touch();
  }

  draw(ctx, w, h, p) {
    let max = this.minRange;
    for (const s of this.series) for (const v of s) max = Math.max(max, Math.abs(v));
    max *= 1.15;
    const mid = h / 2;
    const scale = this.symmetric ? mid / max : h / max;

    ctx.strokeStyle = p.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 1; i < 4; i++) {
      const y = Math.round((h * i) / 4) + 0.5;
      ctx.moveTo(0, y); ctx.lineTo(w, y);
    }
    ctx.stroke();
    if (this.symmetric) {
      ctx.strokeStyle = p.gridStrong;
      ctx.beginPath();
      ctx.moveTo(0, Math.round(mid) + 0.5); ctx.lineTo(w, Math.round(mid) + 0.5);
      ctx.stroke();
    }

    const colors = this.colors?.(p) ?? p.axes;
    const step = w / (this.capacity - 1);
    ctx.lineWidth = 1.75;
    ctx.lineJoin = 'round';
    this.series.forEach((s, si) => {
      if (s.length < 2) return;
      ctx.strokeStyle = colors[si % colors.length];
      ctx.beginPath();
      // Right-aligned: new samples enter from the right edge.
      const offset = this.capacity - s.length;
      for (let i = 0; i < s.length; i++) {
        const x = (offset + i) * step;
        const y = this.symmetric ? mid - s[i] * scale : h - s[i] * scale;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    });

    ctx.fillStyle = p.text3;
    ctx.font = p.mono;
    ctx.fillText(`${this.symmetric ? '±' : ''}${max.toFixed(1)}`, 6, 13);
  }
}

const TRAIL_MS = 4000;

/** What the digitizer reports: current fingers plus a fading trail. */
export class TouchView extends View {
  points = [];
  trails = [];
  maxX = 0;
  maxY = 0;
  /** Grid cells reached since the last reset, for the coverage test. */
  covered = new Set();
  static COLS = 8;
  static ROWS = 16;

  update(msg) {
    this.points = Array.isArray(msg.points) ? msg.points : [];
    this.maxX = num(msg.max_x) || this.maxX;
    this.maxY = num(msg.max_y) || this.maxY;
    const now = Date.now();
    for (const p of this.points) {
      const x = num(p.x), y = num(p.y);
      if (x === null || y === null) continue;
      this.trails.push({ x, y, t: now });
      if (this.maxX && this.maxY) {
        const c = Math.min(TouchView.COLS - 1, Math.floor((x / this.maxX) * TouchView.COLS));
        const r = Math.min(TouchView.ROWS - 1, Math.floor((y / this.maxY) * TouchView.ROWS));
        this.covered.add(r * TouchView.COLS + c);
      }
    }
    if (this.trails.length > 3000) this.trails.splice(0, 1500);
    this.touch();
  }

  resetCoverage() {
    this.covered = new Set();
    this.touch();
  }

  clear() {
    this.points = [];
    this.trails = [];
    this.maxX = this.maxY = 0;
    this.covered = new Set();
    this.touch();
  }

  draw(ctx, w, h, p) {
    // The drawable area keeps the phone's aspect ratio, otherwise dead zones
    // would appear in the wrong positions.
    const mx = this.maxX || 1080, my = this.maxY || 2400;
    const aspect = my / mx;
    let dw = w - 16, dh = dw * aspect;
    if (dh > h - 16) { dh = h - 16; dw = dh / aspect; }
    const ox = (w - dw) / 2, oy = (h - dh) / 2;
    const { COLS, ROWS } = TouchView;

    ctx.fillStyle = p.ok;
    ctx.globalAlpha = 0.14;
    for (const cell of this.covered) {
      const c = cell % COLS, r = Math.floor(cell / COLS);
      ctx.fillRect(ox + (dw * c) / COLS, oy + (dh * r) / ROWS, dw / COLS, dh / ROWS);
    }
    ctx.globalAlpha = 1;

    ctx.strokeStyle = p.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 1; i < COLS; i++) { const x = ox + (dw * i) / COLS; ctx.moveTo(x, oy); ctx.lineTo(x, oy + dh); }
    for (let i = 1; i < ROWS; i++) { const y = oy + (dh * i) / ROWS; ctx.moveTo(ox, y); ctx.lineTo(ox + dw, y); }
    ctx.stroke();

    ctx.strokeStyle = p.gridStrong;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(ox, oy, dw, dh, 10);
    ctx.stroke();

    const now = Date.now();
    this.trails = this.trails.filter((t) => now - t.t < TRAIL_MS);
    ctx.fillStyle = p.accent;
    for (const t of this.trails) {
      ctx.globalAlpha = 0.35 * (1 - (now - t.t) / TRAIL_MS);
      ctx.beginPath();
      ctx.arc(ox + (t.x / mx) * dw, oy + (t.y / my) * dh, 3.5, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    for (const pt of this.points) {
      const px = num(pt.x), py = num(pt.y);
      if (px === null || py === null) continue;
      const x = ox + (px / mx) * dw, y = oy + (py / my) * dh;
      ctx.fillStyle = p.ok;
      ctx.globalAlpha = 0.2;
      ctx.beginPath(); ctx.arc(x, y, 22, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
      ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2); ctx.fill();
    }

    // Touch events stop when the finger lifts: keep redrawing until the trail
    // has faded, otherwise it stays frozen half-transparent.
    if (this.trails.length) this.touch();
  }
}

/**
 * The stylus: strokes drawn as the digitizer reports them, line width
 * following pressure, plus the hover point while the pen is in range.
 */
export class PenView extends View {
  strokes = [];
  current = null;
  hover = null;
  maxX = 0;
  maxY = 0;
  maxPressure = 0;
  covered = new Set();
  stats = { pressureMin: null, pressureMax: 0, button: false, hovered: false, eraser: false };

  update(msg) {
    this.maxX = num(msg.max_x) || this.maxX;
    this.maxY = num(msg.max_y) || this.maxY;
    this.maxPressure = num(msg.max_pressure) || this.maxPressure;
    const x = num(msg.x), y = num(msg.y), pressure = num(msg.pressure) ?? 0;
    const st = this.stats;
    if (msg.button) st.button = true;
    if (msg.eraser) st.eraser = true;
    if (msg.in_range && !msg.contact) st.hovered = true;
    this.hover = msg.in_range && x !== null && y !== null ? { x, y } : null;

    if (msg.contact && x !== null && y !== null) {
      if (!this.current) {
        this.current = [];
        this.strokes.push(this.current);
      }
      this.current.push({ x, y, p: pressure });
      if (pressure > 0) {
        st.pressureMin = st.pressureMin === null ? pressure : Math.min(st.pressureMin, pressure);
        st.pressureMax = Math.max(st.pressureMax, pressure);
      }
      if (this.maxX && this.maxY) {
        const c = Math.min(TouchView.COLS - 1, Math.floor((x / this.maxX) * TouchView.COLS));
        const r = Math.min(TouchView.ROWS - 1, Math.floor((y / this.maxY) * TouchView.ROWS));
        this.covered.add(r * TouchView.COLS + c);
      }
    } else {
      this.current = null;
    }
    if (this.strokes.length > 400) this.strokes.splice(0, 200);
    this.touch();
  }

  clear() {
    this.strokes = [];
    this.current = null;
    this.hover = null;
    this.covered = new Set();
    this.stats = { pressureMin: null, pressureMax: 0, button: false, hovered: false, eraser: false };
    this.touch();
  }

  draw(ctx, w, h, p) {
    const mx = this.maxX || 1600, my = this.maxY || 2560;
    const aspect = my / mx;
    let dw = w - 16, dh = dw * aspect;
    if (dh > h - 16) { dh = h - 16; dw = dh / aspect; }
    const ox = (w - dw) / 2, oy = (h - dh) / 2;
    const { COLS, ROWS } = TouchView;
    const px = (v) => ox + (v / mx) * dw, py = (v) => oy + (v / my) * dh;

    ctx.fillStyle = p.ok;
    ctx.globalAlpha = 0.14;
    for (const cell of this.covered) {
      const c = cell % COLS, r = Math.floor(cell / COLS);
      ctx.fillRect(ox + (dw * c) / COLS, oy + (dh * r) / ROWS, dw / COLS, dh / ROWS);
    }
    ctx.globalAlpha = 1;
    ctx.strokeStyle = p.gridStrong;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(ox, oy, dw, dh, 10);
    ctx.stroke();

    const full = this.maxPressure || this.stats.pressureMax || 1;
    ctx.strokeStyle = p.accent;
    ctx.lineCap = 'round';
    for (const stroke of this.strokes) {
      for (let i = 1; i < stroke.length; i++) {
        const a = stroke[i - 1], b = stroke[i];
        ctx.lineWidth = 0.8 + 5 * Math.min(1, b.p / full);
        ctx.beginPath();
        ctx.moveTo(px(a.x), py(a.y));
        ctx.lineTo(px(b.x), py(b.y));
        ctx.stroke();
      }
    }
    if (this.hover) {
      ctx.strokeStyle = p.ok;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(px(this.hover.x), py(this.hover.y), 9, 0, Math.PI * 2);
      ctx.stroke();
    }
  }
}

// Constellations as defined by android.location.GnssStatus.
export const CONSTELLATIONS = {
  1: ['GPS', '#4c8dff'],
  2: ['SBAS', '#98a2b3'],
  3: ['GLONASS', '#f08c00'],
  4: ['QZSS', '#e64980'],
  5: ['BeiDou', '#2f9e44'],
  6: ['Galileo', '#ae3ec9'],
  7: ['NavIC', '#e8b200'],
};
export const UNKNOWN_CONSTELLATION = ['?', '#868e96'];

/**
 * Sky view: zenith at the centre, horizon at the edge -- the representation
 * receivers use. A satellite low on the horizon with a good signal says more
 * about the antenna than one overhead.
 */
export class SkyPlot extends View {
  sats = [];

  update(sats) {
    this.sats = sats;
    this.touch();
  }

  clear() { this.update([]); }

  draw(ctx, w, h, p) {
    const cx = w / 2, cy = h / 2;
    const radius = Math.max(20, Math.min(w, h) / 2 - 18);

    ctx.strokeStyle = p.grid;
    ctx.lineWidth = 1;
    for (const frac of [1, 2 / 3, 1 / 3]) {
      ctx.beginPath();
      ctx.arc(cx, cy, radius * frac, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.moveTo(cx - radius, cy); ctx.lineTo(cx + radius, cy);
    ctx.moveTo(cx, cy - radius); ctx.lineTo(cx, cy + radius);
    ctx.stroke();

    ctx.fillStyle = p.text3;
    ctx.font = p.mono;
    ctx.textAlign = 'center';
    ctx.fillText('N', cx, cy - radius - 6);
    ctx.fillText('S', cx, cy + radius + 13);
    ctx.fillText('E', cx + radius + 9, cy + 3);
    ctx.fillText('W', cx - radius - 9, cy + 3);
    ctx.textAlign = 'start';

    for (const s of this.sats) {
      const elev = Math.max(0, Math.min(90, num(s.elevation) ?? 0));
      const azim = ((num(s.azimuth) ?? 0) * Math.PI) / 180;
      const r = radius * (1 - elev / 90);
      const x = cx + r * Math.sin(azim), y = cy - r * Math.cos(azim);
      const [, color] = CONSTELLATIONS[s.constellation] || UNKNOWN_CONSTELLATION;
      // Dot size grows with signal-to-noise ratio.
      const cn0 = Math.max(0, Math.min(50, num(s.cn0) ?? 0));
      const dot = 3 + (cn0 / 50) * 5;
      ctx.fillStyle = color;
      ctx.globalAlpha = s.used ? 1 : 0.45;
      ctx.beginPath(); ctx.arc(x, y, dot, 0, Math.PI * 2); ctx.fill();
      if (s.used) {
        ctx.strokeStyle = color;
        ctx.globalAlpha = 0.5;
        ctx.beginPath(); ctx.arc(x, y, dot + 3, 0, Math.PI * 2); ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
  }
}

/** The live views of the app, shared by every page that shows them. */
export const live = {
  accel: new LineChart({ minRange: 12 }),
  gyro: new LineChart({ minRange: 2 }),
  mag: new LineChart({ minRange: 60 }),
  temp: new LineChart({ series: 1, symmetric: false, minRange: 50, capacity: 120,
                        colors: (p) => [p.temp] }),
  touch: new TouchView(),
  pen: new PenView(),
  sky: new SkyPlot(),
};

export function clearLive() {
  for (const v of Object.values(live)) v.clear();
}
