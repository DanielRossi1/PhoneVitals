<script>
  import Icon from '../components/Icon.svelte';
  import ScoreRing from '../components/ScoreRing.svelte';
  import Section from '../components/Section.svelte';
  import SpecGrid from '../components/SpecGrid.svelte';
  import Stat from '../components/Stat.svelte';
  import { app, navigate } from '../lib/app.svelte.js';
  import { cap, daysSince, num, plural, present } from '../lib/format.js';
  import { monthName } from '../lib/specs.js';
  import { attention, issueCount, pageOf, SEVERITY, verdict } from '../lib/report.js';
  import { glance } from '../lib/glance.js';
  import { TERMS_NOTICE } from '../lib/terms.js';

  const snap = $derived(app.snapshot);
  const s = $derived(snap?.summary ?? {});
  const v = $derived(verdict(snap));
  const todo = $derived(attention(snap));
  const answers = $derived(glance(snap));

  const authIssues = $derived(issueCount(snap, 'authenticity'));
  const battery = $derived.by(() => {
    const h = num(s.battery_health);
    if (h === null) {
      return { value: 'Unknown', unit: '', tone: 'warn',
               detail: 'Not measurable from software on this device' };
    }
    return {
      value: Math.round(h),
      unit: '%',
      tone: h >= 80 ? 'ok' : h >= 70 ? 'warn' : 'crit',
      detail: num(s.battery_cycles) !== null ? plural(num(s.battery_cycles), 'charge cycle') : 'Cycle count not exposed',
    };
  });
  const storage = $derived.by(() => {
    const ufs = snap?.storage?.ufs_health ?? {};
    const wear = ufs.life_time_b?.used_percent_range ?? ufs.life_time_a?.used_percent_range;
    return {
      value: num(s.storage_gb) !== null ? `${s.storage_gb} GB` : null,
      detail: [s.storage_type, wear && `wear ${wear}`].filter(Boolean).join(' · ') || 'Wear not exposed',
      tone: ufs.eol_code > 1 ? 'warn' : wear ? 'ok' : 'none',
    };
  });
  const patch = $derived.by(() => {
    const days = daysSince(s.security_patch);
    const until = s.security_updates_until;
    const ended = until && until < new Date().toISOString().slice(0, 7);
    const age = days === null ? 'Unknown' : days < 1 ? 'Current' : `${plural(days, 'day')} old`;
    return {
      value: s.security_patch || null,
      detail: until ? `${age} · ${ended ? 'support ended' : 'supported until'} ${until}` : age,
      tone: days === null ? 'none' : ended ? 'warn' : days <= 120 ? 'ok' : days <= 365 ? 'warn' : 'crit',
    };
  });
  // Age of the device itself, from the mainboard: the production month in a
  // Samsung serial, the factory radio calibration, the soldered storage chip.
  // Never from the battery, which may have been replaced. The first start
  // after the last reset is something else: a reset or a new system restarts
  // that clock.
  const span = (days) => days < 31 ? plural(days, 'day') : days < 730
    ? plural(Math.round(days / 30.4), 'month') : `${(days / 365).toFixed(1)} years`;
  const age = $derived.by(() => {
    const setup = s.setup_date;
    const boots = num(s.boot_count);
    const board = s.board_date;
    const origin = board?.iso ? { iso: `${board.iso}-15`, source: board.source } : null;
    const reset = setup?.days_ago != null ? `reset ${span(setup.days_ago)} ago` : null;
    if (origin) {
      const days = daysSince(origin.iso);
      return { label: 'Device age', value: days === null ? monthName(origin.iso.slice(0, 7)) : span(days),
               detail: [`made ${monthName(origin.iso.slice(0, 7))}, from the ${origin.source}`, reset,
                        boots !== null && plural(boots, 'boot')].filter(Boolean).join(' · '),
               tone: 'info' };
    }
    if (setup?.days_ago != null) {
      return { label: 'Since last reset', value: span(setup.days_ago),
               detail: ['the device age is not recorded', boots !== null && plural(boots, 'boot')]
                 .filter(Boolean).join(' · '), tone: 'info' };
    }
    return { label: 'Device age', value: null, detail: 'Not recorded on this device', tone: 'none' };
  });

  const tests = $derived.by(() => {
    const results = Object.values(app.results);
    const passed = results.filter((r) => r.status === 'passed').length;
    const failed = results.filter((r) => r.status === 'failed').length;
    const available = app.tests.filter((t) => t.available && t.id !== 'inspection').length;
    return {
      value: `${passed + failed}/${available}`,
      detail: failed ? `${failed} failed` : passed ? `${passed} passed` : 'None run yet',
      tone: failed ? 'crit' : passed && passed === available ? 'ok' : 'info',
    };
  });

  const device = $derived([
    ['Model', `${cap(s.brand)} ${s.model ?? ''}`.trim()],
    ['Type', s.form_factor && s.form_factor !== 'phone' ? cap(s.form_factor) : null],
    ['Codename', s.device],
    ['Android', present(s.android) ? `${s.android} (API ${s.sdk ?? '?'})` : null],
    ['Processor', [s.soc, s.cores && `${s.cores} cores`].filter(Boolean).join(' · ')],
    ['Memory', present(s.ram_gb) ? `${s.ram_gb} GB` : null],
    ['Storage', present(s.storage_gb) ? `${s.storage_gb} GB ${s.storage_type ?? ''}`.trim() : null],
    ['Display', present(s.resolution) ? `${s.resolution}${s.refresh_max ? ` @ ${s.refresh_max} Hz` : ''}` : null],
    ['Sensors · cameras', present(s.sensors) ? `${s.sensors} · ${s.cameras ?? '?'}` : null],
    ['Serial number', s.serial],
    ['IMEI', Array.isArray(s.imeis) && s.imeis.length ? s.imeis.join(', ') : 'Not read'],
  ].filter(([, val]) => present(val)));

  const PILLS = [
    ['critical', 'serious', 'crit'],
    ['warning', 'to verify', 'warn'],
    ['info', 'notes', 'info'],
    ['ok', 'passed', 'ok'],
  ];
</script>

<div class="page">
  <section class="card hero tone-{v.tone}">
    <ScoreRing score={v.score} tone={v.tone} size={116} stroke={9} />
    <div class="verdict">
      <div class="eyebrow">Verdict</div>
      <h2>{v.label}</h2>
      {#if v.headline}<p>{v.headline}</p>{/if}
      <div class="pills">
        {#each PILLS as [key, label, tone] (key)}
          {#if num(v.counts[key])}
            <span class="tag tag-{tone}">{num(v.counts[key])} {label}</span>
          {/if}
        {/each}
      </div>
    </div>
  </section>

  {#if answers.length}
    <section class="glance" aria-label="In short">
      {#each answers as a (a.id)}
        <button type="button" class="card answer tone-{a.tone}" onclick={() => navigate(a.page)}>
          <span class="q"><Icon name={a.icon} size={15} /> {a.question}</span>
          <b>{a.answer}</b>
          <span class="why">{a.text}</span>
        </button>
      {/each}
    </section>
  {/if}

  <div class="stats">
    <Stat icon="shield" label="Authenticity" onclick={() => navigate('authenticity')}
          value={authIssues ? plural(authIssues, 'issue') : 'Consistent'}
          tone={authIssues ? 'warn' : 'ok'}
          detail={authIssues ? 'Open the checks to see why' : 'Identity and integrity agree'} />
    <Stat icon="battery" label="Battery health" unit={battery.unit} onclick={() => navigate('health')}
          value={battery.value} tone={battery.tone} detail={battery.detail} />
    <Stat icon="storage" label="Storage" onclick={() => navigate('health')}
          value={storage.value} tone={storage.tone} detail={storage.detail} />
    <Stat icon="patch" label="Security patch" onclick={() => navigate('specs')}
          value={patch.value} tone={patch.tone} detail={patch.detail} />
    <Stat icon="clock" label={age.label} onclick={() => navigate('health')}
          value={age.value} tone={age.tone} detail={age.detail} />
    <Stat icon="tests" label="Functional tests" onclick={() => navigate('tests')}
          value={tests.value} tone={tests.tone} detail={tests.detail} />
  </div>

  <div class="cols">
    <Section title="Needs your attention"
             subtitle={todo.length ? 'Serious findings first. Open one to see the evidence.' : ''} flush>
      {#if todo.length}
        <ul class="todo">
          {#each todo as f, i (i)}
            {@const sev = SEVERITY[f.severity]}
            <li>
              <button type="button" onclick={() => navigate(pageOf(f))}>
                <span class="sev tone-{sev.tone}"><Icon name={sev.icon} size={18} /></span>
                <span class="txt"><b>{f.title}</b><span>{f.detail}</span></span>
                <Icon name="right" size={16} />
              </button>
            </li>
          {/each}
        </ul>
      {:else}
        <div class="clear">
          <span class="ok"><Icon name="ok" size={22} /></span>
          <div>
            <b>Nothing needs attention</b>
            <p>No check found an anomaly. That is the absence of evidence against the
              device, not proof of authenticity.</p>
          </div>
        </div>
      {/if}
    </Section>

    <Section title="Device" flush>
      <SpecGrid rows={device} />
    </Section>
  </div>

  <p class="hint disclaimer">{#if v.disclaimer}{v.disclaimer} {/if}{TERMS_NOTICE}
    <button type="button" class="link" onclick={() => (app.terms = true)}>Read the terms</button></p>
</div>

<style>
  .glance { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; }
  .answer {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 14px 16px;
    text-align: left;
    font: inherit;
    color: inherit;
    cursor: pointer;
    border-left: 3px solid var(--border-strong);
    transition: transform .12s var(--ease);
  }
  .answer:hover { transform: translateY(-1px); }
  .answer .q { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-3); }
  .answer b { font-size: 19px; line-height: 1.25; }
  .answer .why { font-size: 13px; color: var(--text-2); }
  .answer.tone-ok { border-left-color: var(--ok); }
  .answer.tone-ok b { color: var(--ok); }
  .answer.tone-warn { border-left-color: var(--warn); }
  .answer.tone-warn b { color: var(--warn); }
  .answer.tone-crit { border-left-color: var(--crit); }
  .answer.tone-crit b { color: var(--crit); }
  .answer.tone-info { border-left-color: var(--info); }
  .page { display: flex; flex-direction: column; gap: 16px; }
  .hero {
    display: flex;
    align-items: center;
    gap: 28px;
    padding: 24px 28px;
    background:
      radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, var(--hero) 12%, transparent), transparent 60%),
      var(--surface);
    --hero: var(--text-3);
  }
  .hero.tone-ok { --hero: var(--ok); }
  .hero.tone-warn { --hero: var(--warn); }
  .hero.tone-crit { --hero: var(--crit); }
  .verdict { min-width: 0; }
  h2 { margin-top: 2px; font-size: 26px; letter-spacing: -.02em; color: var(--hero); }
  .tone-none h2 { color: var(--text); }
  .verdict p { margin-top: 4px; color: var(--text-2); font-size: 14.5px; max-width: 70ch; }
  .pills { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
  .cols { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: 16px; align-items: start; }
  .todo { margin: 0; padding: 0; list-style: none; border-top: 1px solid var(--border); }
  .todo li + li { border-top: 1px solid var(--border); }
  .todo button {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    width: 100%;
    padding: 14px 18px;
    border: 0;
    background: none;
    color: var(--text-3);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .todo button:hover { background: var(--surface-2); }
  .sev { margin-top: 1px; }
  .tone-crit { color: var(--crit); }
  .tone-warn { color: var(--warn); }
  .txt { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .txt b { color: var(--text); font-weight: 600; }
  .txt span {
    color: var(--text-2);
    font-size: 13px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .clear { display: flex; gap: 14px; padding: 4px 18px 20px; }
  .clear .ok { color: var(--ok); }
  .clear p { margin-top: 2px; color: var(--text-2); font-size: 13px; }
  .disclaimer { max-width: 100ch; }
  .link { padding: 0; border: 0; background: none; color: var(--accent); font: inherit; cursor: pointer; }
  .link:hover { text-decoration: underline; }
  @media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } }
  @media (max-width: 640px) { .hero { flex-direction: column; align-items: flex-start; } }
</style>
