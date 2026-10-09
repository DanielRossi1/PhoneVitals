<script>
  import Icon from '../components/Icon.svelte';
  import { app, chooseBenchFolder, runAutomaticTests, setBench, startTest } from '../lib/app.svelte.js';
  import { STATUS, TEST_ICONS } from '../lib/tests.js';

  const available = $derived(app.tests.filter((t) => t.available));
  const done = $derived(available.filter((t) => ['passed', 'failed'].includes(app.results[t.id]?.status)));
  const failed = $derived(done.filter((t) => app.results[t.id]?.status === 'failed').length);
  const groups = $derived([
    { kind: 'automatic', title: 'Automatic', text: 'Measured by the computer: no judgement needed.' },
    { kind: 'guided', title: 'Guided', text: 'Need your eyes or hands: you confirm the outcome.' },
  ].map((g) => ({ ...g, tests: app.tests.filter((t) => t.kind === g.kind) })));
  const autoRunning = $derived(app.autoQueue.length > 0);
</script>

<div class="page">
  <section class="card summary">
    <div class="progress">
      <div class="nums"><b>{done.length}</b> of {available.length} tests done
        {#if failed}<span class="tag tag-crit">{failed} failed</span>{/if}</div>
      <div class="bar"><div class="fill" style="width:{available.length ? (done.length / available.length) * 100 : 0}%"></div></div>
    </div>
    <button type="button" class="btn btn-primary" onclick={runAutomaticTests} disabled={autoRunning}>
      <Icon name={autoRunning ? 'clock' : 'play'} size={15} />
      {autoRunning ? 'Running automatic tests…' : 'Run automatic tests'}
    </button>
  </section>

  {#if app.bench.available}
    <section class="card bench">
      <div class="bench-text">
        <h3>Bench mode</h3>
        <p>For one phone after another: when a phone is analysed, every automatic test runs
          and the PDF and JSON reports are saved in
          {#if app.bench.folder}<code>{app.bench.folder}</code>{:else}a folder you choose{/if}.
          Then connect the next phone.</p>
      </div>
      <button type="button" class="btn btn-sm" onclick={chooseBenchFolder}>
        {app.bench.folder ? 'Change folder' : 'Choose folder'}</button>
      <label class="toggle">
        <input type="checkbox" checked={app.bench.enabled} disabled={!app.bench.folder}
               onchange={(e) => setBench(e.currentTarget.checked)} />
        <span>{app.bench.enabled ? 'On' : 'Off'}</span>
      </label>
    </section>
  {/if}

  {#each groups as g (g.kind)}
    <section>
      <header class="group-head">
        <h3>{g.title}</h3>
        <p>{g.text}</p>
      </header>
      <div class="grid">
        {#each g.tests as t (t.id)}
          {@const r = app.results[t.id]}
          <!-- A guided test is "running" on the server from the moment it opens
               until the operator answers; once its dialog is closed without an
               answer it simply has not been done. -->
          {@const st = r?.status === 'running' && t.kind === 'guided' && app.dialog !== t.id ? null : STATUS[r?.status]}
          <article class="card test" class:off={!t.available}>
            <div class="top">
              <span class="ico tone-{st?.tone ?? 'none'}"><Icon name={TEST_ICONS[t.id] ?? 'tests'} size={18} /></span>
              <h4>{t.title}</h4>
              {#if st}<span class="tag tag-{st.tone}">{st.label}</span>{/if}
            </div>
            <p class="desc">{(r?.status === 'running' && app.progress_[t.id]) || r?.detail || t.description}</p>
            <div class="foot">
              {#if t.available}
                <button type="button" class="btn btn-sm" onclick={() => startTest(t.id)}
                        disabled={r?.status === 'running' && t.kind === 'automatic'}>
                  {#if r?.status === 'running' && t.kind === 'automatic'}Running…
                  {:else if ['passed', 'failed', 'inconclusive'].includes(r?.status)}<Icon name="refresh" size={13} /> Repeat
                  {:else}<Icon name="play" size={12} /> Start{/if}
                </button>
                {#if r?.duration}<span class="hint">{r.duration} s</span>{/if}
              {:else}
                <span class="hint">Not available on this device</span>
              {/if}
            </div>
          </article>
        {/each}
      </div>
    </section>
  {/each}
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 24px; }
  .summary { display: flex; align-items: center; gap: 24px; padding: 18px 20px; }
  .progress { flex: 1; min-width: 0; }
  .nums { display: flex; align-items: center; gap: 10px; color: var(--text-2); }
  .nums b { color: var(--text); font-size: 18px; }
  .bar { height: 6px; margin-top: 10px; border-radius: 6px; background: var(--surface-3); overflow: hidden; }
  .fill { height: 100%; background: var(--ok); border-radius: 6px; transition: width .4s var(--ease); }
  .group-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; }
  .group-head h3 { font-size: 15px; }
  .group-head p { font-size: 13px; color: var(--text-3); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
  .test { display: flex; flex-direction: column; gap: 8px; padding: 16px; }
  .test.off { opacity: .55; }
  .top { display: flex; align-items: center; gap: 10px; }
  h4 { flex: 1; font-size: 14px; }
  .ico {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    flex: none;
    border-radius: 9px;
    background: var(--surface-3);
    color: var(--text-2);
  }
  .ico.tone-ok { background: var(--ok-soft); color: var(--ok); }
  .ico.tone-crit { background: var(--crit-soft); color: var(--crit); }
  .ico.tone-info { background: var(--info-soft); color: var(--info); }
  .ico.tone-warn { background: var(--warn-soft); color: var(--warn); }
  .desc { flex: 1; font-size: 13px; color: var(--text-2); }
  .foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 4px; }
  .bench { display: flex; align-items: center; gap: 16px; padding: 14px 18px; }
  .bench-text { flex: 1; min-width: 0; }
  .bench h3 { font-size: 14px; }
  .bench p { margin-top: 2px; font-size: 13px; color: var(--text-2); }
  .bench code { overflow-wrap: anywhere; }
  .toggle { display: flex; align-items: center; gap: 6px; font-weight: 600; cursor: pointer; }
  .toggle input { width: 18px; height: 18px; accent-color: var(--accent); }
  @media (max-width: 640px) { .summary, .bench { flex-direction: column; align-items: stretch; } }
</style>
