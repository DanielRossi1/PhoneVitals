<script>
  /** Key/value rows. Long values (fingerprints, digests, lists) take the
   * full width instead of being squeezed into a narrow cell. */
  let { rows } = $props();

  function text(v) {
    return v !== null && typeof v === 'object' ? JSON.stringify(v) : String(v);
  }
</script>

<dl class="grid">
  {#each rows as [key, value] (key)}
    {@const t = text(value)}
    <div class="row" class:long={t.length > 34}>
      <dt>{key}</dt>
      <dd>{t}</dd>
    </div>
  {/each}
</dl>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    margin: 0;
    border-top: 1px solid var(--border);
  }
  .row {
    padding: 10px 18px;
    border-bottom: 1px solid var(--border);
    min-width: 0;
  }
  .row.long { grid-column: 1 / -1; }
  dt { font-size: 12px; color: var(--text-3); }
  dd {
    margin: 2px 0 0;
    font-family: var(--mono);
    font-size: 13px;
    overflow-wrap: anywhere;
  }
</style>
