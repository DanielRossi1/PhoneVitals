/** Formatting helpers. Every value from the phone is untrusted: numbers go
 * through num() before being formatted, and text is rendered by Svelte, which
 * escapes it. */

/** Finite number or null. */
export function num(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function fixed(v, digits, fallback = '—') {
  const n = num(v);
  return n === null ? fallback : n.toFixed(digits);
}

export function cap(s) {
  if (!s) return '';
  const t = String(s);
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function bytes(n) {
  let v = num(n);
  if (!v) return null;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${units[i]}`;
}

export function present(v) {
  return v !== null && v !== undefined && v !== '' && v !== 'n/d' && v !== 'n/a';
}

/** Yes/no for a boolean field, or null when the field is missing: a collector
 * that failed must leave the row out, not report "absent" or "unlocked". */
export function flag(v, yes, no) {
  if (v === true) return yes;
  if (v === false) return no;
  return null;
}

export const list = (v) => (Array.isArray(v) ? v : []);

/** Whole days between an ISO date and today, or null. */
export function daysSince(iso) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.floor((Date.now() - t) / 86_400_000);
}

export function plural(n, one, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}
