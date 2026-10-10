<script>
  import Icon from './Icon.svelte';
  import { SEVERITY } from '../lib/report.js';

  let { finding } = $props();
  let open = $state(false);

  const sev = $derived(SEVERITY[finding.severity] ?? SEVERITY.info);
  const hasEvidence = $derived(
    finding.evidence && typeof finding.evidence === 'object' && Object.keys(finding.evidence).length > 0,
  );
</script>

<article class="finding">
  <span class="sev tone-{sev.tone}" title={sev.label}><Icon name={sev.icon} size={18} /></span>
  <div class="body">
    <header>
      <h4>{finding.title}</h4>
      {#if finding.strength_label}
        <span class="strength strength-{finding.strength}">{finding.strength_label}</span>
      {/if}
      {#if finding.modification}
        <span class="strength" title="Follows from software the owner installed, not from tampering">Modification</span>
      {/if}
    </header>
    <p>{finding.detail}</p>
    {#if hasEvidence}
      <button type="button" class="toggle" aria-expanded={open} onclick={() => (open = !open)}>
        <Icon name={open ? 'down' : 'right'} size={14} />
        {open ? 'Hide evidence' : 'Show evidence'}
      </button>
      {#if open}
        <pre class="evidence">{JSON.stringify(finding.evidence, null, 2)}</pre>
      {/if}
    {/if}
  </div>
</article>

<style>
  .finding {
    display: flex;
    gap: 14px;
    padding: 16px 18px;
    border-top: 1px solid var(--border);
  }
  .finding:first-child { border-top: 0; }
  .sev { margin-top: 1px; color: var(--text-3); }
  .tone-ok { color: var(--ok); }
  .tone-warn { color: var(--warn); }
  .tone-crit { color: var(--crit); }
  .tone-info { color: var(--info); }
  .body { min-width: 0; flex: 1; }
  header { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 4px; }
  h4 { font-size: 14px; }
  p { color: var(--text-2); font-size: 13.5px; }
  .strength {
    font-size: 10.5px;
    font-weight: 650;
    letter-spacing: .06em;
    text-transform: uppercase;
    padding: 2px 7px;
    border-radius: 5px;
    background: var(--surface-3);
    color: var(--text-3);
  }
  .strength-proven { background: var(--accent-soft); color: var(--accent); }
  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 8px;
    padding: 2px 0;
    border: 0;
    background: none;
    color: var(--text-3);
    font: inherit;
    font-size: 12.5px;
    cursor: pointer;
  }
  .toggle:hover { color: var(--text); }
</style>
