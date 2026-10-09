<script>
  import Icon from './Icon.svelte';
  import { setTheme, theme } from '../lib/theme.svelte.js';

  const OPTIONS = [
    { id: 'system', icon: 'monitor', label: 'Follow the system' },
    { id: 'light', icon: 'sun', label: 'Light' },
    { id: 'dark', icon: 'moon', label: 'Dark' },
  ];
</script>

<div class="switch" role="radiogroup" aria-label="Theme">
  {#each OPTIONS as o (o.id)}
    <button type="button" role="radio" aria-checked={theme.choice === o.id} title={o.label}
            aria-label={o.label} class:on={theme.choice === o.id} onclick={() => setTheme(o.id)}>
      <Icon name={o.icon} size={15} />
    </button>
  {/each}
</div>

<style>
  .switch {
    display: inline-flex;
    padding: 3px;
    gap: 2px;
    border-radius: 9px;
    background: var(--surface-3);
  }
  button {
    display: grid;
    place-items: center;
    width: 30px;
    height: 26px;
    border: 0;
    border-radius: 7px;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
  }
  button:hover { color: var(--text); }
  .on { background: var(--surface); color: var(--text); box-shadow: var(--shadow); }
</style>
