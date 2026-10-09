<script>
  import Finding from './Finding.svelte';
  import Icon from './Icon.svelte';
  import Section from './Section.svelte';

  /** One category of findings: problems and notes in full, passed checks
   * folded away, since they are reassurance rather than something to act on. */
  let { group } = $props();
  let showPassed = $state(false);

  const open = $derived(group.items.filter((f) => f.severity !== 'ok'));
  const passed = $derived(group.items.filter((f) => f.severity === 'ok'));
  const issues = $derived(open.filter((f) => f.severity === 'critical' || f.severity === 'warning').length);
  const subtitle = $derived(
    [issues ? `${issues} to look at` : 'No issues', passed.length ? `${passed.length} passed` : '']
      .filter(Boolean).join(' · '),
  );
</script>

<Section title={group.title} {subtitle} flush>
  <div class="list">
    {#each open as f, i (i)}<Finding finding={f} />{/each}
    {#if passed.length}
      <button type="button" class="fold" aria-expanded={showPassed} onclick={() => (showPassed = !showPassed)}>
        <Icon name="ok" size={16} />
        <span>{showPassed ? 'Hide' : 'Show'} {passed.length} passed {passed.length === 1 ? 'check' : 'checks'}</span>
        <Icon name={showPassed ? 'down' : 'right'} size={14} />
      </button>
      {#if showPassed}
        {#each passed as f, i (i)}<Finding finding={f} />{/each}
      {/if}
    {/if}
  </div>
</Section>

<style>
  .list { border-top: 1px solid var(--border); }
  .fold {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 12px 18px;
    border: 0;
    border-top: 1px solid var(--border);
    background: var(--surface-2);
    color: var(--text-2);
    font: inherit;
    font-size: 13px;
    font-weight: 550;
    cursor: pointer;
  }
  .list > .fold:first-child { border-top: 0; }
  .fold :global(.icon:first-child) { color: var(--ok); }
  .fold:hover { color: var(--text); }
</style>
