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

  const snap = $derived(app.snapshot);
  const s = $derived(snap?.summary ?? {});
  const v = $derived(verdict(snap));
  const todo = $derived(attention(snap));

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
  const age = $derived.by(() => {
    const setup = s.setup_date;
    const made = s.manufactured;
    const boots = num(s.boot_count);
    if (!setup && !made) return { value: null, detail: 'Not recorded on this device', tone: 'none' };
    const days = setup?.days_ago;
    const value = days == null ? monthName(made.iso)
      : days < 31 ? plural(days, 'day') : days < 730 ? plural(Math.round(days / 30.4), 'month')
      : `${(days / 365).toFixed(1)} years`;
    const detail = [setup ? 'in use since the last reset' : 'manufactured',
                    boots !== null && plural(boots, 'boot')].filter(Boolean).join(' · ');
    return { value, detail, tone: 'info' };
  });

  const tests = $derived.by(() => {
    const results = Object.values(app.results);
    const passed = results.filter((r) => r.status === 'passed').length;
    const failed = results.filter((r) => r.status === 'failed').length;
    const available = app.tests.filter((t) => t.available).length;
    return {
      value: `${passed + failed}/${available}`,
      detail: failed ? `${failed} failed` : passed ? `${passed} passed` : 'None run yet',
      tone: failed ? 'crit' : passed && passed === available ? 'ok' : 'info',
    };
  });

  const device = $derived([
    ['Model', `${cap(s.brand)} ${s.model ?? ''}`.trim()],
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
    <Stat icon="clock" label="Age" onclick={() => navigate('health')}
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

  {#if v.disclaimer}<p class="hint disclaimer">{v.disclaimer}</p>{/if}
</div>

<style>
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
  @media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } }
  @media (max-width: 640px) { .hero { flex-direction: column; align-items: flex-start; } }
</style>
