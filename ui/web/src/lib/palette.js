import { onThemeChange } from './theme.svelte.js';

/** Theme colours for canvas drawing, read from the CSS tokens. */

let cache = null;

onThemeChange(() => { cache = null; });

export function palette() {
  if (cache) return cache;
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  cache = {
    text3: v('--text-3'),
    grid: v('--grid'),
    gridStrong: v('--grid-strong'),
    surface: v('--surface'),
    accent: v('--accent'),
    ok: v('--ok'),
    axes: [v('--axis-x'), v('--axis-y'), v('--axis-z')],
    temp: v('--temp'),
    mono: '10px ui-monospace, monospace',
  };
  return cache;
}
