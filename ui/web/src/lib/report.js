/** Reading the report: findings by page, verdict, and what needs a look. */

import { num } from './format.js';

export const SEVERITY_RANK = { critical: 0, warning: 1, info: 2, ok: 3 };

export const SEVERITY = {
  critical: { label: 'Serious', tone: 'crit', icon: 'error' },
  warning: { label: 'To verify', tone: 'warn', icon: 'alert' },
  info: { label: 'Note', tone: 'info', icon: 'info' },
  ok: { label: 'Passed', tone: 'ok', icon: 'ok' },
};

export const VERDICTS = {
  no_anomalies: { label: 'No anomalies', tone: 'ok' },
  caution: { label: 'Caution', tone: 'warn' },
  suspicious: { label: 'Suspicious', tone: 'warn' },
  modified: { label: 'Modified', tone: 'warn' },
  compromised: { label: 'Compromised', tone: 'crit' },
};

export const CATEGORIES = {
  identity: 'Device identity',
  integrity: 'Platform integrity',
  components: 'Component condition',
  specifications: 'Specifications',
  history: 'History and usage',
};

/** Which page each finding category lives on. */
const PAGE_OF = {
  identity: 'authenticity',
  integrity: 'authenticity',
  components: 'hardware',
  specifications: 'health',
  history: 'health',
};

export function pageOf(finding) {
  return PAGE_OF[finding?.category] ?? 'health';
}

export function findings(snapshot) {
  const list = snapshot?.report?.findings;
  return Array.isArray(list) ? list.filter((f) => f && typeof f === 'object') : [];
}

export const bySeverity = (a, b) => (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9);

/** Findings of one page, grouped by category, most serious first. */
export function groupsFor(snapshot, page) {
  const groups = {};
  for (const f of findings(snapshot)) {
    if (pageOf(f) !== page) continue;
    (groups[f.category] ??= []).push(f);
  }
  return Object.entries(groups).map(([category, items]) => ({
    category,
    title: CATEGORIES[category] ?? category,
    items: items.sort(bySeverity),
  }));
}

/** Count of serious and to-verify findings on a page, for the sidebar. */
export function issueCount(snapshot, page) {
  return findings(snapshot).filter(
    (f) => pageOf(f) === page && (f.severity === 'critical' || f.severity === 'warning'),
  ).length;
}

export function attention(snapshot) {
  return findings(snapshot)
    .filter((f) => f.severity === 'critical' || f.severity === 'warning')
    .sort(bySeverity);
}

export function verdict(snapshot) {
  const r = snapshot?.report || {};
  const score = num(r.score);
  return {
    score: score === null ? null : Math.max(0, Math.min(100, Math.round(score))),
    ...(VERDICTS[r.verdict] ?? { label: 'Not available', tone: 'none' }),
    headline: r.headline || '',
    counts: r.counts || {},
    disclaimer: r.disclaimer || '',
  };
}

/** How sure a finding is, in words a reader can weigh. */
export const STRENGTHS = {
  proven: { label: 'Certain', hint: 'Read straight from the hardware or signed by it: it cannot be faked by software.' },
  measured: { label: 'Measured', hint: 'Read or measured on the device: reliable, unless the software itself was altered.' },
  circumstantial: { label: 'Indication', hint: 'A clue that fits the explanation given, not proof of it.' },
};

const SMALL_WORDS = /^(id|sku|usb|imei|tac|soc|cpu|gpu|ram|ufs|nfc|hdr|ok|uid|tee)$/i;

/** A finding's evidence as label/value rows instead of raw JSON. */
export function evidenceRows(evidence) {
  if (!evidence || typeof evidence !== 'object') return [];
  const label = (key) => key.replace(/_/g, ' ').replace(/\b\w+/g,
    (w, i) => (SMALL_WORDS.test(w) ? w.toUpperCase() : i === 0 ? w[0].toUpperCase() + w.slice(1) : w));
  const value = (v) => {
    if (v === true) return 'yes';
    if (v === false) return 'no';
    if (v === null || v === undefined || v === '') return '—';
    if (Array.isArray(v)) {
      const items = v.map((x) => (x && typeof x === 'object' ? Object.values(x).filter((y) => y !== null && y !== '').join(' ') : String(x)));
      return items.length > 8 ? `${items.slice(0, 8).join(', ')} and ${items.length - 8} more` : items.join(', ') || '—';
    }
    if (typeof v === 'object') {
      return Object.entries(v).filter(([, x]) => x !== null && x !== '')
        .map(([k, x]) => `${k.replace(/_/g, ' ')}: ${typeof x === 'object' ? JSON.stringify(x) : x}`).join(' · ');
    }
    return String(v);
  };
  return Object.entries(evidence).map(([k, v]) => [label(k), value(v)]);
}

