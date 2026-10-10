/**
 * The questions a buyer or seller actually asks, answered in plain words
 * from the report. Each answer links to the page with the details.
 */

import { num } from './format.js';
import { findings } from './report.js';

const has = (all, title) => all.some((f) => f.title === title);
const starts = (all, prefix) => all.find((f) => f.title?.startsWith(prefix));

export function glance(s) {
  if (!s?.report) return [];
  const all = findings(s);
  const serious = (cat) => all.filter((f) => f.category === cat && f.severity === 'critical'
                                            && !f.modification);
  const verdict = s.report.verdict;

  // Is it what it claims to be?
  const fake = [...serious('identity'), ...serious('integrity')];
  const confirmed = has(all, 'Identity confirmed by the secure environment')
    || has(all, 'Attestation chain signed by Google');
  const genuine = fake.length && verdict !== 'modified'
    ? { answer: 'Doubtful', tone: 'crit', text: `${fake.length} contradictions in its identity: see Authenticity.` }
    : confirmed
      ? { answer: 'Yes', tone: 'ok', text: 'Confirmed by the security chip, which cannot be faked.' }
      : { answer: 'No contradictions', tone: 'info', text: 'Nothing points to a fake, but the security chip could not confirm it.' };

  // Which software does it run?
  const rom = starts(all, 'Custom ROM: ');
  const software = rom
    ? { answer: rom.title.replace('Custom ROM: ', ''), tone: 'info',
        text: 'A system installed in place of the manufacturer\'s. Legitimate, but not the original.' }
    : verdict === 'modified'
      ? { answer: 'Modified', tone: 'warn', text: 'Unlocked or modified by its owner: see Authenticity.' }
      : has(all, 'Official production build')
        ? { answer: 'Original', tone: 'ok', text: 'The manufacturer\'s own system, signed by them.' }
        : { answer: 'Not verified', tone: 'none', text: 'The system type could not be read.' };

  // Has it been opened?
  const replaced = all.filter((f) => /^The (screen|battery) has been replaced$/.test(f.title))
    .map((f) => f.title.split(' ')[1]);
  const clues = all.filter((f) => f.category === 'components' && f.severity === 'warning'
                                 && !/has been replaced$/.test(f.title));
  const opened = replaced.length
    ? { answer: 'Yes', tone: 'warn', text: `The phone reports a replaced ${replaced.join(' and ')}.` }
    : clues.length
      ? { answer: 'Possibly', tone: 'warn', text: `${clues.length} signs of a repair: see Hardware check.` }
      : { answer: 'No signs', tone: 'ok', text: 'No replaced or missing part found. Check it by eye too.' };

  // Battery.
  const h = num(s.summary?.battery_health);
  const cycles = num(s.summary?.battery_cycles);
  const battery = h === null
    ? { answer: 'Not measurable', tone: 'none', text: 'This phone does not report it: the capacity test on the Tests page estimates it.' }
    : { answer: h >= 85 ? 'Good' : h >= 80 ? 'Fair' : 'Worn', tone: h >= 80 ? 'ok' : h >= 70 ? 'warn' : 'crit',
        text: `${Math.round(h)}% of its original capacity${cycles !== null ? `, ${cycles} charge cycles` : ''}.`
              + (h < 80 ? ' Usually replaced below 80%.' : '') };

  // Can it change hands?
  const google = num(s.history?.accounts?.google) ?? 0;
  const locked = all.find((f) => /financing lock|managed/i.test(f.title) && f.severity !== 'ok');
  const files = has(all, 'Personal files still on the phone');
  const blockers = [google && `${google} Google account${google > 1 ? 's' : ''}`,
                    files && 'personal files', locked && 'a management lock'].filter(Boolean);
  const handover = locked
    ? { answer: 'Locked', tone: 'crit', text: 'Someone else still controls it: see History.' }
    : blockers.length
      ? { answer: 'Not yet', tone: 'warn', text: `Still holds ${blockers.join(', ')}: remove the accounts, then reset it.` }
      : { answer: 'Ready', tone: 'ok', text: 'No accounts or personal files left on it.' };

  // Where is it from?
  const p = s.provenance ?? {};
  const elsewhere = all.some((f) => f.title?.startsWith('Made for the') && /another market/.test(f.detail ?? ''));
  const origin = p.market
    ? { answer: p.market === 'Global' ? 'Global model' : p.market, tone: elsewhere ? 'warn' : 'ok',
        text: elsewhere ? 'Built for another market: check warranty and mobile bands.'
                        : (p.sim_countries?.length ? `Used with a SIM from ${p.sim_countries.join(', ')}.` : 'The market it was built for.') }
    : { answer: 'Not stated', tone: 'none', text: 'This phone carries no market code.' };

  return [
    { id: 'genuine', icon: 'shield', question: 'Is it genuine?', page: 'authenticity', ...genuine },
    { id: 'software', icon: 'chip', question: 'Which system?', page: 'authenticity', ...software },
    { id: 'opened', icon: 'search', question: 'Opened or repaired?', page: 'hardware', ...opened },
    { id: 'battery', icon: 'battery', question: 'Battery', page: 'health', ...battery },
    { id: 'handover', icon: 'lock', question: 'Ready to hand over?', page: 'health', ...handover },
    { id: 'origin', icon: 'compass', question: 'Where is it from?', page: 'hardware', ...origin },
  ];
}
