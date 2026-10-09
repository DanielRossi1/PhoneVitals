<script>
  /** A titled card. */
  let { title, subtitle = '', actions = null, children, flush = false } = $props();
</script>

<section class="card section">
  <header>
    <div>
      <h3>{title}</h3>
      {#if subtitle}<p>{subtitle}</p>{/if}
    </div>
    {#if actions}<div class="actions">{@render actions()}</div>{/if}
  </header>
  <div class:pad={!flush}>{@render children()}</div>
</section>

<style>
  .section { overflow: hidden; }
  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    padding: 16px 18px 12px;
  }
  h3 { font-size: 14.5px; }
  p { margin-top: 2px; font-size: 12.5px; color: var(--text-3); }
  .actions { display: flex; gap: 8px; flex: none; }
  .pad { padding: 0 18px 18px; }
</style>
