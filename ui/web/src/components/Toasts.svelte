<script>
  import Icon from './Icon.svelte';
  import { app } from '../lib/app.svelte.js';

  const ICON = { ok: 'ok', crit: 'error', warn: 'alert', info: 'info' };
</script>

<div class="toasts" role="status" aria-live="polite">
  {#each app.toasts as t (t.id)}
    <div class="toast tone-{t.tone}">
      <Icon name={ICON[t.tone] ?? 'info'} size={16} />
      <span>{t.text}</span>
    </div>
  {/each}
</div>

<style>
  .toasts {
    position: fixed;
    right: 20px;
    bottom: 20px;
    z-index: 50;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 8px;
    pointer-events: none;
  }
  .toast {
    display: flex;
    align-items: center;
    gap: 10px;
    max-width: min(440px, calc(100vw - 40px));
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--surface);
    box-shadow: var(--shadow-lg);
    font-size: 13.5px;
    animation: rise .25s var(--ease);
  }
  .tone-ok :global(.icon) { color: var(--ok); }
  .tone-crit :global(.icon) { color: var(--crit); }
  .tone-warn :global(.icon) { color: var(--warn); }
  .tone-info :global(.icon) { color: var(--info); }
  @keyframes rise { from { opacity: 0; transform: translateY(8px); } }
</style>
