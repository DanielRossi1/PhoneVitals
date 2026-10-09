<script>
  /** Score from 0 to 100 as a ring, coloured by verdict. */
  let { score = null, tone = 'none', size = 96, stroke = 8 } = $props();

  const r = $derived((size - stroke) / 2);
  const c = $derived(2 * Math.PI * r);
  const offset = $derived(c * (1 - (score ?? 0) / 100));
</script>

<div class="ring tone-{tone}" style="width:{size}px;height:{size}px" role="img"
     aria-label={score === null ? 'Score not available' : `Score ${score} out of 100`}>
  <svg viewBox="0 0 {size} {size}" aria-hidden="true">
    <circle class="track" cx={size / 2} cy={size / 2} {r} stroke-width={stroke} />
    <circle class="fill" cx={size / 2} cy={size / 2} {r} stroke-width={stroke}
            stroke-dasharray={c} stroke-dashoffset={offset} />
  </svg>
  <span class="value" style="font-size:{size * 0.3}px">{score ?? '—'}</span>
</div>

<style>
  .ring { position: relative; flex: none; display: grid; place-items: center; }
  svg { position: absolute; inset: 0; transform: rotate(-90deg); }
  circle { fill: none; }
  .track { stroke: var(--surface-3); }
  .fill {
    stroke: var(--text-3);
    stroke-linecap: round;
    transition: stroke-dashoffset .8s var(--ease);
  }
  .tone-ok .fill { stroke: var(--ok); }
  .tone-warn .fill { stroke: var(--warn); }
  .tone-crit .fill { stroke: var(--crit); }
  .value { font-weight: 700; letter-spacing: -.03em; font-variant-numeric: tabular-nums; }
</style>
