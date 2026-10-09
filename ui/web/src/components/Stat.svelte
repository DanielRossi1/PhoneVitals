<script>
  import Icon from './Icon.svelte';

  /** Headline number with a label and a one-line explanation. */
  let { icon, label, value, unit = '', detail = '', tone = 'none', onclick = null } = $props();
</script>

{#snippet content()}
  <div class="head">
    <span class="ico"><Icon name={icon} size={16} /></span>
    <span class="label">{label}</span>
  </div>
  <div class="value">{value ?? '—'}{#if unit && value !== null && value !== undefined}<small>{unit}</small>{/if}</div>
  {#if detail}<div class="detail">{detail}</div>{/if}
{/snippet}

{#if onclick}
  <button type="button" class="card stat clickable tone-{tone}" {onclick}>{@render content()}</button>
{:else}
  <div class="card stat tone-{tone}">{@render content()}</div>
{/if}

<style>
  .stat {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 16px 18px;
    min-width: 0;
    text-align: left;
    font: inherit;
    color: inherit;
  }
  .clickable { cursor: pointer; transition: border-color .15s, transform .15s var(--ease); }
  .clickable:hover { border-color: var(--border-strong); transform: translateY(-1px); }
  .head { display: flex; align-items: center; gap: 8px; color: var(--text-2); font-size: 13px; font-weight: 550; }
  .ico {
    display: grid;
    place-items: center;
    width: 28px;
    height: 28px;
    border-radius: 8px;
    background: var(--surface-3);
    color: var(--text-2);
  }
  .tone-ok .ico { background: var(--ok-soft); color: var(--ok); }
  .tone-warn .ico { background: var(--warn-soft); color: var(--warn); }
  .tone-crit .ico { background: var(--crit-soft); color: var(--crit); }
  .tone-info .ico { background: var(--info-soft); color: var(--info); }
  .value {
    font-size: 26px;
    font-weight: 700;
    letter-spacing: -.02em;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  small { margin-left: 3px; font-size: 14px; font-weight: 600; color: var(--text-3); }
  .detail { font-size: 12.5px; color: var(--text-3); }
</style>
