<script>
  import Icon from '../components/Icon.svelte';
  import StateLayout from './StateLayout.svelte';
  import { app } from '../lib/app.svelte.js';

  const PHASES = [
    { step: 'connection', label: 'Connecting to the device' },
    { step: 'collection', label: 'Reading the hardware and the system' },
    { step: 'analysis', label: 'Interpreting the readings' },
    { step: 'identity', label: 'Reading the identifiers' },
    { step: 'attestation', label: 'Asking the secure chip to attest' },
    { step: 'verification', label: 'Running the authenticity checks' },
  ];

  const current = $derived(PHASES.findIndex((p) => p.step === app.progress.step));
  let showLog = $state(false);

  function phaseState(i) {
    if (app.progress.step === 'done' || (current >= 0 && i < current)) return 'done';
    if (i === current) return 'active';
    return 'todo';
  }
</script>

<StateLayout>
  <div class="box">
    <h1>Analysing the device</h1>
    <p class="detail" aria-live="polite">{app.progress.detail || 'Starting…'}</p>

    <div class="bar" role="progressbar" aria-label="Analysis progress" aria-valuemin="0"
         aria-valuemax="100" aria-valuenow={app.progress.percent}>
      <div class="fill" style="width:{app.progress.percent}%"></div>
    </div>
    <div class="pct">{app.progress.percent}%</div>

    <ol class="phases card">
      {#each PHASES as p, i (p.step)}
        {@const st = phaseState(i)}
        <li class={st}>
          <span class="mark">
            {#if st === 'done'}<Icon name="ok" size={18} />
            {:else if st === 'active'}<span class="spinner"></span>
            {:else}<span class="empty"></span>{/if}
          </span>
          {p.label}
        </li>
      {/each}
    </ol>

    <button type="button" class="btn btn-ghost btn-sm" onclick={() => (showLog = !showLog)}
            aria-expanded={showLog}>
      <Icon name={showLog ? 'down' : 'right'} size={14} /> Details
    </button>
    {#if showLog}
      <pre class="evidence log">{app.progress.log.map((l) => `${String(l.percent).padStart(3)}%  ${l.detail}`).join('\n')}</pre>
    {/if}
  </div>
</StateLayout>

<style>
  .box { display: flex; flex-direction: column; align-items: center; width: min(520px, 100%); }
  h1 { font-size: 24px; }
  .detail { margin-top: 8px; min-height: 1.5em; color: var(--text-2); text-align: center; }
  .bar { width: 100%; height: 6px; margin-top: 22px; border-radius: 6px; background: var(--surface-3); overflow: hidden; }
  .fill { height: 100%; border-radius: 6px; background: var(--accent); transition: width .4s var(--ease); }
  .pct { margin-top: 6px; align-self: flex-end; font-size: 12px; color: var(--text-3); font-variant-numeric: tabular-nums; }
  .phases { width: 100%; margin: 18px 0 12px; padding: 8px 0; list-style: none; }
  li { display: flex; align-items: center; gap: 12px; padding: 8px 18px; color: var(--text-3); }
  li.active { color: var(--text); font-weight: 600; }
  li.done { color: var(--text-2); }
  .mark { display: grid; place-items: center; width: 18px; height: 18px; }
  li.done .mark { color: var(--ok); }
  .empty { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--border-strong); }
  .spinner {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: 2px solid var(--accent-soft);
    border-top-color: var(--accent);
    animation: spin .8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .log { width: 100%; max-height: 200px; }
</style>
