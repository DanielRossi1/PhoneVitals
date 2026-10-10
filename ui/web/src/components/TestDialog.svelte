<script>
  import Icon from './Icon.svelte';
  import { app, finishTest, runTest, setLive } from '../lib/app.svelte.js';
  import { live } from '../lib/canvas.js';
  import { fixed, forDevice } from '../lib/format.js';
  import { FLOWS, KEYS, SCREEN_PATTERNS, SENSOR_INFO, TEST_ICONS } from '../lib/tests.js';

  let dialog;
  let pattern = $state('white');

  const id = $derived(app.dialog);
  const meta = $derived(app.tests.find((t) => t.id === id));
  const flow = $derived(FLOWS[id] ?? {});
  const needsLive = $derived(Boolean(flow.sensors || flow.touch || flow.pen));

  $effect(() => {
    if (id && dialog && !dialog.open) {
      pattern = 'white';
      dialog.showModal();
      // Focus the dialog itself rather than its first button, so no answer
      // is preselected and the instruction is what gets read first.
      dialog.focus();
    } else if (!id && dialog?.open) {
      dialog.close();
    }
  });

  function showPattern(p) {
    pattern = p;
    runTest('screen', { pattern: p });
  }

  function readout(type) {
    const v = app.live.readouts[type];
    const [label, unit] = SENSOR_INFO[type] ?? [String(type), ''];
    if (!v) return [{ label, value: 'waiting for data…' }];
    if (v.length >= 3) {
      return ['X', 'Y', 'Z'].map((axis, i) => ({ label: `${label} ${axis}`, value: `${fixed(v[i], 3)} ${unit}` }));
    }
    return [{ label, value: `${fixed(v[0], 2)} ${unit}` }];
  }
</script>

<dialog bind:this={dialog} aria-labelledby="test-title" tabindex="-1"
        oncancel={(e) => { e.preventDefault(); finishTest(null); }}>
  {#if id}
    <header>
      <span class="ico"><Icon name={TEST_ICONS[id] ?? 'tests'} size={20} /></span>
      <h2 id="test-title">{meta?.title ?? id}</h2>
      <button type="button" class="btn btn-ghost btn-sm close" aria-label="Skip this test"
              onclick={() => finishTest(null)}><Icon name="close" size={16} /></button>
    </header>

    <p class="instruction">{forDevice(flow.instruction ?? meta?.description ?? '', app.snapshot?.summary?.form_factor)}</p>

    {#if needsLive && !app.live.running}
      <div class="note note-warn"><Icon name="alert" />
        <div>This test reads the live streams, which are stopped.
          <button type="button" class="btn btn-sm" onclick={() => setLive(true)}>Start streams</button></div>
      </div>
    {/if}

    {#if id === 'screen'}
      <div class="swatches" role="group" aria-label="Test colour">
        {#each Object.entries(SCREEN_PATTERNS) as [p, bg] (p)}
          <button type="button" class="swatch" class:on={pattern === p} style="background:{bg}"
                  aria-pressed={pattern === p} aria-label={p} title={p} onclick={() => showPattern(p)}></button>
        {/each}
      </div>
    {:else if id === 'buttons'}
      <ul class="keys">
        {#each KEYS as [key, label] (key)}
          {@const hit = app.keysPressed.includes(key)}
          <li class:hit><Icon name={hit ? 'ok' : 'clock'} size={18} />{label}</li>
        {/each}
      </ul>
    {:else if id === 'camera'}
      {@const result = app.results.camera}
      {#if !result?.measurements?.photos}
        <p class="hint">Taking pictures with every camera…</p>
      {:else}
        <p class="hint">{result.detail}</p>
        <div class="photos">
          {#each result.measurements.photos as p (p.id)}
            <figure class:bad={!p.ok}>
              {#if p.jpeg_b64}<img src="data:image/jpeg;base64,{p.jpeg_b64}" alt="Camera {p.id}" />
              {:else}<div class="none">no picture</div>{/if}
              <figcaption>{p.facing} · camera {p.id}
                {#if p.ok}<br /><span class="hint">brightness {p.brightness} · contrast {p.contrast} · sharpness {p.sharpness}</span>{/if}
              </figcaption>
            </figure>
          {/each}
        </div>
      {/if}
    {:else if flow.pen}
      {@const pen = app.live.pen}
      <div class="touch">
        <canvas use:live.pen.attach aria-label="Strokes reported by the pen digitizer"></canvas>
        <div class="readout pen" aria-live="off">
          <div><span>Pressure</span><b>{pen && pen.maxPressure
            ? `${Math.round((pen.pressure / pen.maxPressure) * 100)}% · peak ${Math.round((pen.pressureMax / pen.maxPressure) * 100)}%`
            : (pen?.pressure ?? '—')}</b></div>
          <div><span>Hover</span><b>{pen?.hovered ? 'seen' : '—'}</b></div>
          <div><span>Side button</span><b>{pen?.button ? 'pressed' : '—'}</b></div>
        </div>
      </div>
    {:else if flow.touch}
      <div class="touch">
        <canvas use:live.touch.attach aria-label="Touch positions reported by the digitizer"></canvas>
        <div class="fingers"><b>{app.live.fingers}</b> {app.live.fingers === 1 ? 'finger' : 'fingers'} down</div>
      </div>
    {:else if flow.sensors}
      <div class="readout" aria-live="off">
        {#each flow.sensors.flatMap(readout) as row (row.label)}
          <div><span>{row.label}</span><b>{row.value}</b></div>
        {/each}
      </div>
    {/if}

    <footer>
      <button type="button" class="btn btn-crit" onclick={() => finishTest(false)}>
        <Icon name="error" size={16} /> Does not work
      </button>
      <span class="spacer"></span>
      <button type="button" class="btn btn-ghost" onclick={() => finishTest(null)}>Skip</button>
      <button type="button" class="btn btn-ok" onclick={() => finishTest(true)}>
        <Icon name="ok" size={16} /> Works
      </button>
    </footer>
  {/if}
</dialog>

<style>
  dialog {
    width: min(640px, calc(100vw - 32px));
    max-height: calc(100vh - 48px);
    padding: 22px 24px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    color: var(--text);
    box-shadow: var(--shadow-lg);
  }
  dialog[open] { animation: pop .2s var(--ease); }
  dialog:focus { outline: none; }
  dialog::backdrop { background: var(--overlay); backdrop-filter: blur(2px); }
  @keyframes pop { from { opacity: 0; transform: translateY(8px) scale(.98); } }
  header { display: flex; align-items: center; gap: 12px; }
  .ico {
    display: grid;
    place-items: center;
    width: 38px;
    height: 38px;
    border-radius: 11px;
    background: var(--accent-soft);
    color: var(--accent);
  }
  h2 { flex: 1; font-size: 18px; }
  .close { width: 32px; padding: 0; }
  .instruction { margin: 14px 0 16px; color: var(--text-2); }
  .note { margin-bottom: 14px; }
  .note .btn { margin-left: 8px; }
  .swatches { display: flex; flex-wrap: wrap; gap: 10px; }
  .swatch {
    width: 52px;
    height: 52px;
    border: 1px solid var(--border-strong);
    border-radius: 12px;
    cursor: pointer;
    transition: transform .12s var(--ease);
  }
  .swatch:hover { transform: translateY(-2px); }
  .swatch.on { outline: 3px solid var(--accent); outline-offset: 2px; }
  .keys { display: flex; flex-direction: column; gap: 8px; margin: 0; padding: 0; list-style: none; }
  .keys li {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-radius: 10px;
    background: var(--surface-2);
    color: var(--text-3);
  }
  .keys li.hit { background: var(--ok-soft); color: var(--ok); font-weight: 600; }
  .touch { display: flex; flex-direction: column; align-items: center; gap: 8px; }
  .photos { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px;
            max-height: 52vh; overflow: auto; margin-top: 8px; }
  .photos figure { margin: 0; }
  .photos img { width: 100%; border-radius: 8px; border: 1px solid var(--border); display: block; }
  .photos .none { display: grid; place-items: center; aspect-ratio: 4 / 3; border-radius: 8px;
                  background: var(--crit-soft); color: var(--crit); font-size: 12px; }
  .photos figcaption { margin-top: 4px; font-size: 12px; color: var(--text-2); }
  .touch canvas { width: 100%; height: min(46vh, 380px); }
  .fingers { color: var(--text-2); }
  .fingers b { font-size: 20px; color: var(--text); }
  .readout {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 8px;
  }
  .readout div {
    display: flex;
    flex-direction: column;
    padding: 10px 12px;
    border-radius: 10px;
    background: var(--surface-2);
  }
  .readout.pen { width: 100%; }
  .readout span { font-size: 12px; color: var(--text-3); }
  .readout b { font: 600 16px var(--mono); font-variant-numeric: tabular-nums; }
  footer { display: flex; align-items: center; gap: 8px; margin-top: 22px; }
  .spacer { flex: 1; }
</style>
