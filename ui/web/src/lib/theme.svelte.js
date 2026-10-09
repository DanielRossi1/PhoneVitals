/** Light/dark theme: follows the desktop unless the user picks one. */

const KEY = 'phonevitals.theme';
const listeners = new Set();

export const theme = $state({ choice: 'system', dark: false });

function read() {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

const media = matchMedia('(prefers-color-scheme: dark)');

function apply() {
  const root = document.documentElement;
  if (theme.choice === 'system') root.removeAttribute('data-theme');
  else root.dataset.theme = theme.choice;
  theme.dark = theme.choice === 'dark' || (theme.choice === 'system' && media.matches);
  for (const fn of listeners) fn();
}

export function initTheme() {
  theme.choice = read();
  apply();
  media.addEventListener('change', apply);
}

export function setTheme(choice) {
  theme.choice = choice;
  try {
    if (choice === 'system') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch {
    // Storage unavailable: the choice lasts for this session only.
  }
  apply();
}

/** Called after every theme change, for canvases to repaint. */
export function onThemeChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
