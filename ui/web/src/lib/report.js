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
  components: 'health',
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
