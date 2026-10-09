<script>
  import Icon from '../components/Icon.svelte';
  import { app, toast } from '../lib/app.svelte.js';

  let filter = $state('');

  const SKIP = new Set(['report', 'summary', 'imei_analysis', 'evidence']);
  const groups = $derived(
    Object.entries(app.snapshot ?? {})
      .filter(([k]) => !SKIP.has(k))
      .map(([key, value]) => {
        const text = JSON.stringify(value, null, 2) ?? String(value);
        return { key, text, haystack: `${key}\n${text}`.toLowerCase() };
      }),
  );
  const shown = $derived.by(() => {
    const f = filter.trim().toLowerCase();
    return f ? groups.filter((g) => g.haystack.includes(f)) : groups;
  });

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast('Copied to the clipboard', 'ok');
    } catch {
      toast('Copy not allowed here', 'warn');
    }
  }
</script>

<div class="page">
  <div class="toolbar">
    <label class="search">
      <Icon name="search" size={16} />
      <input type="search" bind:value={filter} placeholder="Filter by key or value…"
             aria-label="Filter raw data by key or value" />
    </label>
    <span class="hint" aria-live="polite">{shown.length} of {groups.length} sections</span>
  </div>

  <div class="card list">
    {#each shown as g (g.key)}
      <details open={Boolean(filter.trim())}>
        <summary>
          <Icon name="right" size={14} class="chev" />
          <span class="key">{g.key}</span>
          <span class="size">{(g.text.length / 1024).toFixed(1)} KB</span>
          <button type="button" class="btn btn-ghost btn-sm" onclick={(e) => { e.preventDefault(); copy(g.text); }}
                  aria-label="Copy {g.key}"><Icon name="copy" size={14} /></button>
        </summary>
        <pre>{g.text}</pre>
      </details>
    {/each}
  </div>
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 16px; }
  .toolbar { display: flex; align-items: center; gap: 14px; }
  .search { position: relative; display: block; flex: 1; max-width: 420px; }
  .search :global(.icon) { position: absolute; left: 11px; top: 9px; color: var(--text-3); }
  .search input { width: 100%; padding-left: 34px; }
  .list { overflow: hidden; }
  details + details { border-top: 1px solid var(--border); }
  summary {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px 8px 16px;
    cursor: pointer;
    list-style: none;
  }
  summary::-webkit-details-marker { display: none; }
  summary:hover { background: var(--surface-2); }
  summary :global(.chev) { color: var(--text-3); transition: transform .15s; }
  details[open] summary :global(.chev) { transform: rotate(90deg); }
  .key { flex: 1; font-family: var(--mono); font-weight: 600; font-size: 13px; }
  .size { font-size: 12px; color: var(--text-3); }
  pre {
    margin: 0;
    padding: 12px 18px 16px 40px;
    max-height: 520px;
    overflow: auto;
    background: var(--surface-2);
    border-top: 1px solid var(--border);
    font: 12px/1.55 var(--mono);
    color: var(--text-2);
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>
