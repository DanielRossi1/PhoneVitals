<script>
  import Icon from '../components/Icon.svelte';
  import Section from '../components/Section.svelte';
  import SpecGrid from '../components/SpecGrid.svelte';
  import { app, navigate } from '../lib/app.svelte.js';
  import { specSections } from '../lib/specs.js';

  let filter = $state('');

  const all = $derived(specSections(app.snapshot));
  const shown = $derived.by(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return all;
    return all
      .map((s) => ({
        ...s,
        rows: s.title.toLowerCase().includes(f)
          ? s.rows
          : s.rows.filter(([k, v]) => `${k} ${typeof v === 'object' ? JSON.stringify(v) : v}`.toLowerCase().includes(f)),
      }))
      .filter((s) => s.rows.length);
  });
  const errors = $derived(Object.keys(app.snapshot?.errors ?? {}));
</script>

<div class="page">
  <div class="toolbar">
    <label class="search">
      <Icon name="search" size={16} />
      <input type="search" bind:value={filter} placeholder="Filter specifications…"
             aria-label="Filter specifications" />
    </label>
  </div>

  {#if errors.length}
    <div class="note note-info"><Icon name="info" />
      <span>Some data could not be collected ({errors.join(', ')}): those rows are missing.
        <button type="button" class="link" onclick={() => navigate('raw')}>See the raw data</button>.</span>
    </div>
  {/if}

  {#each shown as sec (sec.id)}
    <Section title={sec.title} flush><SpecGrid rows={sec.rows} /></Section>
  {:else}
    <p class="hint">Nothing matches “{filter}”.</p>
  {/each}
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 16px; }
  .toolbar { position: sticky; top: -24px; z-index: 2; margin: -8px 0 0; padding: 8px 0; background: var(--bg); }
  .search { position: relative; display: block; max-width: 420px; }
  .search :global(.icon) { position: absolute; left: 11px; top: 9px; color: var(--text-3); }
  .search input { width: 100%; padding-left: 34px; }
  .link { padding: 0; border: 0; background: none; color: var(--accent); font: inherit; cursor: pointer; text-decoration: underline; }
</style>
