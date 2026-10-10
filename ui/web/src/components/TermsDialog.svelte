<script>
  import Icon from './Icon.svelte';
  import { app } from '../lib/app.svelte.js';
  import { TERMS, TERMS_UPDATED } from '../lib/terms.js';

  let dialog;

  $effect(() => {
    if (app.terms && dialog && !dialog.open) dialog.showModal();
    else if (!app.terms && dialog?.open) dialog.close();
  });
</script>

<dialog bind:this={dialog} onclose={() => (app.terms = false)} aria-labelledby="terms-title">
  <header>
    <h2 id="terms-title">Terms of use</h2>
    <button type="button" class="btn btn-ghost close" aria-label="Close" onclick={() => (app.terms = false)}>
      <Icon name="close" size={16} />
    </button>
  </header>
  {#snippet spans(parts)}{#each parts as part, i (i)}{#if part.bold}<strong>{part.text}</strong>{:else}{part.text}{/if}{/each}{/snippet}
  <div class="body">
    <p class="hint">Last updated {TERMS_UPDATED}.</p>
    {#each TERMS as block, i (i)}
      {#if block.type === 'heading'}<h3>{block.text}</h3>
      {:else if block.type === 'list'}
        <ul>{#each block.items as item, j (j)}<li>{@render spans(item)}</li>{/each}</ul>
      {:else if block.type === 'rule'}<hr />
      {:else}<p>{@render spans(block.text)}</p>{/if}
    {/each}
  </div>
</dialog>

<style>
  dialog {
    width: min(680px, calc(100vw - 32px));
    max-height: calc(100vh - 48px);
    padding: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    color: var(--text);
    box-shadow: var(--shadow-lg);
  }
  dialog::backdrop { background: var(--overlay); backdrop-filter: blur(2px); }
  header {
    position: sticky;
    top: 0;
    display: flex;
    align-items: center;
    padding: 18px 22px 12px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
  }
  h2 { flex: 1; font-size: 18px; }
  .close { width: 32px; padding: 0; }
  .body { padding: 14px 22px 22px; display: flex; flex-direction: column; gap: 9px; }
  h3 { font-size: 14px; margin-top: 10px; }
  p, li { color: var(--text-2); font-size: 13.5px; line-height: 1.55; }
  ul { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 3px; }
  strong { color: var(--text); }
  hr { width: 100%; border: 0; border-top: 1px solid var(--border); margin: 6px 0; }
</style>
