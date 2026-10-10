<script>
  import FindingGroup from '../components/FindingGroup.svelte';
  import Icon from '../components/Icon.svelte';
  import Section from '../components/Section.svelte';
  import Stat from '../components/Stat.svelte';
  import { app, send, startTest } from '../lib/app.svelte.js';
  import { componentCodes, hardwareGroups, INSPECTION, originRows } from '../lib/hardware.js';
  import SpecGrid from '../components/SpecGrid.svelte';
  import { groupsFor } from '../lib/report.js';
  import { STATUS } from '../lib/tests.js';

  const snap = $derived(app.snapshot);
  const groups = $derived(hardwareGroups(snap, app.results));
  const rows = $derived(groups.flatMap((g) => g.rows));
  const flagged = $derived(rows.filter((r) => ['warn', 'crit'].includes(r.status.tone)));
  const tested = $derived(rows.filter((r) => r.tests.some((id) => ['passed', 'failed'].includes(app.results[id]?.status))));
  const testable = $derived(rows.filter((r) => r.tests.length));
  const findingGroups = $derived(groupsFor(snap, 'hardware'));
  const available = $derived(new Set(app.tests.filter((t) => t.available).map((t) => t.id)));
  const titles = $derived(Object.fromEntries(app.tests.map((t) => [t.id, t.title])));

  const screen = $derived(snap?.display?.screen_part_status);
  const battery = $derived(snap?.battery?.part_status);
  const partTile = (status) => status === 'REPLACED' ? { value: 'Replaced', tone: 'warn' }
    : status === 'ORIGINAL' ? { value: 'Original', tone: 'ok' } : { value: 'Not reported', tone: 'none' };

  const codes = $derived(componentCodes(snap));
  const origin = $derived(originRows(snap));
  let copied = $state(false);
  async function copyCodes() {
    try {
      await navigator.clipboard.writeText(codes.map(([k, v]) => `${k}: ${v}`).join('\n'));
      copied = true;
      setTimeout(() => { copied = false; }, 2000);
    } catch { /* clipboard not available */ }
  }

  // The inspection is kept until the next device; ticked means "problem found".
  let ticked = $state({});
  let notes = $state('');
  const inspection = $derived(app.results.inspection);

  function saveInspection() {
    const found = INSPECTION.filter(([id]) => ticked[id]).map(([, label]) => label);
    const detail = (found.length
      ? `Problems found: ${found.join('; ')}.`
      : `No problems found in ${INSPECTION.length} checks.`)
      + (notes.trim() ? ` Notes: ${notes.trim()}` : '');
    send({ command: 'test_outcome', test: 'inspection', passed: found.length === 0, detail });
  }
</script>

<div class="page">
  <div class="stats">
    <Stat icon="monitor" label="Screen" {...partTile(screen)}
          detail={screen ? 'As the display driver reports it' : 'This device does not say'} />
    <Stat icon="battery" label="Battery" {...partTile(battery)}
          detail={battery ? 'As the battery service reports it' : 'This device does not say'} />
    <Stat icon="alert" label="Components to check" value={flagged.length}
          tone={flagged.length ? 'warn' : 'ok'}
          detail={flagged.map((r) => r.name).join(', ') || 'Nothing flagged'} />
    <Stat icon="tests" label="Components tested" value={`${tested.length}/${testable.length}`}
          tone={tested.length === testable.length && testable.length ? 'ok' : 'none'}
          detail="Through the functional tests" />
  </div>

  {#each findingGroups as g (g.category)}<FindingGroup group={g} />{/each}

  {#each groups as g (g.title)}
    <Section title={g.title} flush>
      <ul class="parts">
        {#each g.rows as r (r.id)}
          <li>
            <span class="ico tone-{r.status.tone}"><Icon name={r.icon} size={17} /></span>
            <div class="what">
              <b>{r.name}</b>
              <span class="id">{r.identity || '—'}</span>
              {#if r.note}<span class="note">{r.note}</span>{/if}
              {#each r.clues as c (c)}<span class="note warn">{c}</span>{/each}
              {#each r.tests.filter((id) => app.results[id]?.detail && app.results[id]?.status !== 'running') as id (id)}
                <span class="note">{titles[id] ?? id}: {app.results[id].detail}</span>
              {/each}
            </div>
            <span class="tag tag-{r.status.tone}">{r.status.label}</span>
            <div class="actions">
              {#each r.tests.filter((id) => available.has(id)) as id (id)}
                {@const st = STATUS[app.results[id]?.status]}
                <button type="button" class="btn btn-sm" title={titles[id]} onclick={() => startTest(id)}
                        disabled={app.results[id]?.status === 'running' && app.tests.find((t) => t.id === id)?.kind === 'automatic'}>
                  <Icon name={st ? 'refresh' : 'play'} size={12} /> {titles[id] ?? id}
                </button>
              {/each}
            </div>
          </li>
        {/each}
      </ul>
    </Section>
  {/each}

  {#if codes.length}
    {#snippet copy()}
      <button type="button" class="btn btn-sm" onclick={copyCodes}>
        <Icon name={copied ? 'ok' : 'copy'} size={13} /> {copied ? 'Copied' : 'Copy'}
      </button>
    {/snippet}
    <Section title="Component codes" flush actions={copy}
             subtitle="What the parts report about themselves: search them to match spare parts">
      <SpecGrid rows={codes} />
    </Section>
  {/if}

  {#if origin.length}
    <Section title="Origin" flush
             subtitle="The market the phone was built for, and where it is used now">
      <SpecGrid rows={origin} />
    </Section>
  {/if}

  <Section title="Original or aftermarket parts?"
           subtitle="What software can and cannot tell">
    <div class="explain">
      <p>A replaced part is certain only when the phone itself says so, as recent Android
        versions do for the screen and the battery. Whether a replacement is a genuine spare
        or an aftermarket copy no device reports: the clues are indirect, and they are
        collected above.</p>
      <ul>
        <li><b>Screen.</b> Aftermarket panels on OLED phones are often LCD or lower-grade OLED:
          no HDR, a lower refresh rate, a tint or a halo, a touch controller with a different
          name or firmware, and an under-display fingerprint reader that keeps failing.</li>
        <li><b>Battery.</b> Copies often report the design capacity as the full capacity, carry no
          manufacturing date, or measure well below their label in the capacity test.</li>
        <li><b>Cameras.</b> On Samsung the driver flags a module whose firmware does not match;
          elsewhere the pictures in the camera test are the judge.</li>
        <li><b>Your reference unit.</b> Saved on the Authenticity page, a known-genuine phone of
          the same model is compared part by part: panel, HDR formats, touch controller,
          fingerprint sensor, camera sensors.</li>
      </ul>
      <p>None of this proves a part genuine: a careful repair with original parts leaves no
        trace. A physical inspection, below, covers what software cannot see.</p>
    </div>
  </Section>

  <Section title="Physical inspection" subtitle="Tick what looks wrong, then save it into the report">
    <div class="inspect">
      {#each INSPECTION as [id, label, hint] (id)}
        <label class="check" class:bad={ticked[id]}>
          <input type="checkbox" bind:checked={ticked[id]} />
          <span><b>{label}</b><span class="hint">{hint}</span></span>
        </label>
      {/each}
      <textarea rows="2" placeholder="Notes (optional)" bind:value={notes} maxlength="600"></textarea>
      <div class="save">
        <button type="button" class="btn btn-primary" onclick={saveInspection} disabled={!snap}>
          <Icon name="ok" size={15} /> Save inspection
        </button>
        {#if inspection?.detail}
          <span class="tag tag-{inspection.status === 'passed' ? 'ok' : 'warn'}">{inspection.detail}</span>
        {/if}
      </div>
    </div>
  </Section>
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 16px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
  .parts { list-style: none; margin: 0; padding: 0; }
  .parts li {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: start;
    gap: 6px 14px;
    padding: 12px 18px;
    border-top: 1px solid var(--border);
  }
  .parts li:first-child { border-top: 0; }
  .ico { margin-top: 2px; color: var(--text-3); }
  .tone-ok { color: var(--ok); }
  .tone-warn { color: var(--warn); }
  .tone-crit { color: var(--crit); }
  .what { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .what b { font-size: 14px; }
  .id { font: 12.5px var(--mono); color: var(--text-2); overflow-wrap: anywhere; }
  .note { font-size: 12.5px; color: var(--text-3); }
  .note.warn { color: var(--warn); }
  .tag-none { background: var(--surface-3); color: var(--text-2); }
  .actions { grid-column: 2 / -1; display: flex; flex-wrap: wrap; gap: 6px; }
  .actions:empty { display: none; }
  .explain { padding: 0 2px; color: var(--text-2); font-size: 14px; display: flex; flex-direction: column; gap: 10px; }
  .explain ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; }
  .inspect { display: flex; flex-direction: column; gap: 8px; }
  .check {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    padding: 10px 12px;
    border-radius: 10px;
    background: var(--surface-2);
    cursor: pointer;
  }
  .check.bad { background: var(--warn-soft); }
  .check input { margin-top: 3px; }
  .check span { display: flex; flex-direction: column; gap: 2px; }
  .check .hint { font-size: 12.5px; color: var(--text-3); }
  textarea {
    font: inherit;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--surface);
    color: var(--text);
    resize: vertical;
  }
  .save { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  @media (max-width: 560px) {
    .parts li { grid-template-columns: auto 1fr; }
    .parts li > .tag { grid-column: 2; justify-self: start; }
  }
</style>
