<script>
  import Icon from '../components/Icon.svelte';
  import StateLayout from './StateLayout.svelte';
  import { app } from '../lib/app.svelte.js';
</script>

<StateLayout>
  <div class="box">
    <span class="ico"><Icon name="lock" size={30} stroke={1.8} /></span>
    <h1>{app.blocked.title || 'Device not ready'}</h1>
    {#if app.blocked.detail}<p>{app.blocked.detail}</p>{/if}
    <div class="wait"><span class="dot dot-warn dot-pulse"></span>Waiting for the device to become available…</div>
  </div>
</StateLayout>

<style>
  .box { display: flex; flex-direction: column; align-items: center; text-align: center; max-width: 560px; }
  .ico {
    display: grid;
    place-items: center;
    width: 72px;
    height: 72px;
    margin-bottom: 20px;
    border-radius: 22px;
    background: var(--warn-soft);
    color: var(--warn);
  }
  h1 { font-size: 24px; }
  p { margin-top: 10px; color: var(--text-2); font-size: 14.5px; white-space: pre-line; }
  .wait { display: flex; align-items: center; gap: 10px; margin-top: 24px; font-size: 13px; color: var(--text-3); }
</style>
