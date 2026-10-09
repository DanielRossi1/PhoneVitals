<script>
  /**
   * The printable report: what a customer or a buyer receives. Rendered from
   * the same export the JSON comes from, so the fingerprint at the bottom
   * identifies both.
   */
  import { onMount } from 'svelte';
  import { cap, num, plural, present } from '../lib/format.js';
  import { bySeverity, findings, SEVERITY, verdict } from '../lib/report.js';
  import { historyRows, monthName } from '../lib/specs.js';
  import { STATUS } from '../lib/tests.js';

  let data = $state(null);
  let error = $state('');

  onMount(async () => {
    // Styles below are global (they must reach <html> and <body>), and a
    // component's CSS ships in the bundle even when it is not shown: the
    // class keeps them to this page.
    document.documentElement.classList.add('print-mode');
    document.documentElement.dataset.theme = 'light';
    try {
      const res = await fetch('/api/report', { cache: 'no-store' });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`);
      data = body;
    } catch (err) {
      error = err.message || String(err);
    }
  });

  $effect(() => {
    if (!data) return;
    document.title = data.filename.replace(/\.json$/, '');
    // The desktop app prints this page itself; in a browser, open the dialog.
    if (!window.phonevitals) setTimeout(() => window.print(), 400);
  });

  const r = $derived(data?.report);
  const s = $derived(r?.summary ?? {});
  const v = $derived(verdict(r));
  const all = $derived(findings(r).sort(bySeverity));
  const issues = $derived(all.filter((f) => f.severity === 'critical' || f.severity === 'warning'));
  const notes = $derived(all.filter((f) => f.severity === 'info'));
  const passed = $derived(all.filter((f) => f.severity === 'ok'));
  const tests = $derived((r?.tests?.results ?? []).filter((t) => t.status !== 'running'));
  const att = $derived(r?.attestation ?? {});
  const facts = $derived([
    ['Model', `${cap(s.brand)} ${s.model ?? ''}`.trim()],
    ['Codename', s.device],
    ['Serial number', s.serial],
    ['IMEI', (s.imeis ?? []).join(', ') || 'not read'],
    ['Android', present(s.android) ? `${s.android} (API ${s.sdk ?? '?'})` : null],
    ['Security patch', s.security_patch && `${s.security_patch}${s.security_updates_until ? ` · supported until ${s.security_updates_until}` : ''}`],
    ['Processor', [s.soc, s.cores && `${s.cores} cores`].filter(Boolean).join(' · ')],
    ['Memory / storage', [present(s.ram_gb) && `${s.ram_gb} GB RAM`, present(s.storage_gb) && `${s.storage_gb} GB ${s.storage_type ?? ''}`].filter(Boolean).join(' · ')],
    ['Battery health', num(s.battery_health) !== null
      ? `${Math.round(s.battery_health)}%${num(s.battery_cycles) !== null ? ` · ${plural(s.battery_cycles, 'cycle')}` : ''}`
      : 'not measurable on this device'],
    ['Manufactured', s.manufactured ? monthName(s.manufactured.iso) : null],
    ['Hardware attestation', att.available
      ? [att.security_label, att.chain?.signatures_valid && att.chain?.root_trusted ? 'chain signed by Google' : null,
         att.root_of_trust?.device_locked === true ? 'bootloader locked' : att.root_of_trust?.device_locked === false ? 'bootloader unlocked' : null]
        .filter(Boolean).join(' · ')
      : 'not obtained'],
  ].filter(([, val]) => present(val)));
  const history = $derived(historyRows(r));
  const evidence = $derived((r?.evidence ?? []).filter((e) => e?.png_b64));
  const generated = $derived(r?.meta?.finished_at ? new Date(r.meta.finished_at) : new Date());
</script>

{#if error}
  <p class="error">The report could not be loaded: {error}</p>
{:else if r}
  <article class="sheet" data-print-ready>
    <header class="top">
      <div>
        <div class="brand">PhoneVitals · device diagnostic report</div>
        <h1>{cap(s.brand)} {s.model}</h1>
        <div class="when">Analysed on {generated.toLocaleString('en-GB', { dateStyle: 'long', timeStyle: 'short' })}
          {#if r.meta?.demo} · <strong>demonstration data</strong>{/if}</div>
      </div>
      <div class="score tone-{v.tone}">
        <span class="n">{v.score ?? '—'}</span>
        <span class="l">{v.label}</span>
      </div>
    </header>

    <p class="headline">{v.headline}</p>

    <section>
      <h2>Device</h2>
      <dl class="facts">
        {#each facts as [k, val] (k)}<div><dt>{k}</dt><dd>{val}</dd></div>{/each}
      </dl>
    </section>

    <section>
      <h2>Findings that need attention</h2>
      {#if issues.length}
        {#each issues as f, i (i)}
          <div class="finding sev-{SEVERITY[f.severity]?.tone}">
            <div class="ft"><span class="badge">{SEVERITY[f.severity]?.label}</span>{f.title}</div>
            <p>{f.detail}</p>
          </div>
        {/each}
      {:else}
        <p class="muted">None. That is the absence of evidence against the device, not proof of authenticity.</p>
      {/if}
    </section>

    {#if tests.length}
      <section>
        <h2>Functional tests</h2>
        <table>
          <tbody>
            {#each tests as t (t.id)}
              <tr><td class="tn">{t.title}</td>
                <td class="ts tone-{STATUS[t.status]?.tone}">{STATUS[t.status]?.label ?? t.status}</td>
                <td>{t.detail}</td></tr>
            {/each}
          </tbody>
        </table>
      </section>
    {/if}

    {#if history.length}
      <section>
        <h2>History</h2>
        <dl class="facts">
          {#each history as [k, val] (k)}<div><dt>{k}</dt><dd>{val}</dd></div>{/each}
        </dl>
      </section>
    {/if}

    {#if notes.length}
      <section>
        <h2>Notes</h2>
        {#each notes as f, i (i)}
          <div class="finding sev-info"><div class="ft">{f.title}</div><p>{f.detail}</p></div>
        {/each}
      </section>
    {/if}

    {#if passed.length}
      <section>
        <h2>Checks passed ({passed.length})</h2>
        <ul class="passed">{#each passed as f, i (i)}<li>{f.title}</li>{/each}</ul>
      </section>
    {/if}

    {#if evidence.length}
      <section class="evidence">
        <h2>Evidence</h2>
        {#each evidence as e (e.id)}
          <figure><img src="data:image/png;base64,{e.png_b64}" alt={e.title} />
            <figcaption>{e.title}</figcaption></figure>
        {/each}
      </section>
    {/if}

    <footer>
      <p>{v.disclaimer}</p>
      <p class="fp">Report fingerprint (SHA-256 of the JSON export, canonical form):
        <code>{data.sha256}</code></p>
      <p>Generated by PhoneVitals {data.version ? `v${data.version}` : ''} · {data.filename}</p>
    </footer>
  </article>
{/if}

<style>
  /* app.css loads after this component and would set the theme background. */
  :global(html.print-mode), :global(html.print-mode body) { overflow: auto; background: #fff !important; }
  .sheet {
    max-width: 820px;
    margin: 0 auto;
    padding: 28px 32px;
    color: #111;
    font-size: 12px;
    line-height: 1.45;
  }
  .top { display: flex; justify-content: space-between; gap: 24px; border-bottom: 2px solid #111; padding-bottom: 14px; }
  .brand { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: #555; }
  h1 { margin: 4px 0 2px; font-size: 24px; }
  .when { color: #555; }
  .score { display: flex; flex-direction: column; align-items: center; justify-content: center;
           min-width: 120px; padding: 8px 14px; border-radius: 10px; border: 2px solid currentColor; }
  .score .n { font-size: 30px; font-weight: 800; line-height: 1; }
  .score .l { margin-top: 4px; font-weight: 700; font-size: 12px; }
  .tone-ok { color: #15803d; }
  .tone-warn { color: #b45309; }
  .tone-crit { color: #c81e1e; }
  .tone-none, .tone-info { color: #444; }
  .headline { margin: 12px 0 4px; font-size: 13px; }
  section { margin-top: 18px; break-inside: auto; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .06em; border-bottom: 1px solid #ccc;
       padding-bottom: 4px; margin-bottom: 8px; }
  .facts { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 24px; margin: 0; }
  .facts div { display: flex; gap: 8px; break-inside: avoid; }
  dt { min-width: 130px; color: #555; }
  dd { margin: 0; font-weight: 600; overflow-wrap: anywhere; }
  .finding { padding: 6px 0 6px 10px; border-left: 3px solid #999; margin-bottom: 6px; break-inside: avoid; }
  .finding p { margin: 2px 0 0; color: #333; }
  .ft { font-weight: 700; }
  .badge { display: inline-block; margin-right: 8px; padding: 0 6px; border-radius: 4px; font-size: 10px;
           text-transform: uppercase; letter-spacing: .05em; background: #eee; }
  .sev-crit { border-color: #c81e1e; }
  .sev-crit .badge { background: #fdeaea; color: #c81e1e; }
  .sev-warn { border-color: #b45309; }
  .sev-warn .badge { background: #fdf3e2; color: #b45309; }
  .sev-info { border-color: #2563eb; }
  .muted { color: #555; }
  table { width: 100%; border-collapse: collapse; }
  td { padding: 4px 6px; border-bottom: 1px solid #e5e5e5; vertical-align: top; }
  .tn { width: 26%; font-weight: 600; }
  .ts { width: 12%; font-weight: 700; }
  .passed { columns: 2; margin: 0; padding-left: 18px; }
  .evidence figure { display: inline-block; margin: 0 16px 0 0; text-align: center; }
  .evidence img { max-height: 320px; border: 1px solid #ccc; border-radius: 6px; }
  figcaption { font-size: 10.5px; color: #555; }
  footer { margin-top: 22px; padding-top: 10px; border-top: 1px solid #ccc; font-size: 10.5px; color: #444; }
  .fp code { font-size: 9.5px; overflow-wrap: anywhere; }
  .error { padding: 40px; }
  @page { size: A4; margin: 14mm 12mm; }
  @media print { .sheet { padding: 0; max-width: none; } }
</style>
