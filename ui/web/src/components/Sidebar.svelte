<script>
  import Icon from './Icon.svelte';
  import ThemeSwitch from './ThemeSwitch.svelte';
  import { app, navigate } from '../lib/app.svelte.js';
  import { cap } from '../lib/format.js';
  import { issueCount } from '../lib/report.js';
  import { PAGES } from '../lib/pages.js';


  const s = $derived(app.snapshot?.summary ?? {});
  const name = $derived(`${cap(s.brand)} ${s.model ?? ''}`.trim() || 'Device');
  const testsDone = $derived(
    Object.values(app.results).filter((r) => r.status === 'passed' || r.status === 'failed').length,
  );
  const testsAvailable = $derived(app.tests.filter((t) => t.available).length);

  function badge(id) {
    if (id === 'authenticity' || id === 'health') {
      const n = issueCount(app.snapshot, id);
      return n ? { text: String(n), tone: 'warn' } : null;
    }
    if (id === 'tests' && testsAvailable) return { text: `${testsDone}/${testsAvailable}`, tone: 'muted' };
    return null;
  }
</script>

<aside class="sidebar">
  <div class="brand">
    <img class="logo" src="./icon.png" alt="" width="30" height="30" />
    <span>PhoneVitals</span>
  </div>

  <div class="device">
    <div class="avatar">{(s.brand || '?').charAt(0).toUpperCase()}</div>
    <div class="meta">
      <div class="name" title={name}>{name}</div>
      <div class="sub">
        {[s.android && `Android ${s.android}`, s.serial].filter(Boolean).join(' · ')}
      </div>
    </div>
  </div>

  <nav aria-label="Sections">
    {#each PAGES as p (p.id)}
      {@const b = badge(p.id)}
      <button type="button" class="item" class:active={app.page === p.id}
              aria-current={app.page === p.id ? 'page' : undefined} onclick={() => navigate(p.id)}>
        <Icon name={p.icon} size={17} />
        <span class="label">{p.label}</span>
        {#if p.id === 'live' && app.live.running}
          <span class="live-dot" title="Streams active"></span>
        {:else if b}
          <span class="badge badge-{b.tone}">{b.text}</span>
        {/if}
      </button>
    {/each}
  </nav>

  <footer>
    <div class="conn">
      <span class="dot" class:dot-ok={app.connection === 'online'}
            class:dot-crit={app.connection !== 'online' && app.connection !== 'connecting'}></span>
      {app.connection === 'online' ? 'Connected' : app.connection === 'connecting' ? 'Connecting…' : 'Offline'}
      {#if app.version}<span class="ver">v{app.version}</span>{/if}
    </div>
    <ThemeSwitch />
  </footer>
</aside>

<style>
  .sidebar {
    display: flex;
    flex-direction: column;
    width: var(--sidebar-w);
    flex: none;
    height: 100%;
    padding: 16px 12px;
    background: var(--sidebar);
    border-right: 1px solid var(--border);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 8px 16px;
    font-weight: 700;
    font-size: 15px;
    letter-spacing: -.01em;
  }
  .logo { width: 30px; height: 30px; flex: none; }
  .device {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px;
    margin-bottom: 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
  }
  .avatar {
    display: grid;
    place-items: center;
    width: 36px;
    height: 36px;
    flex: none;
    border-radius: 10px;
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 700;
  }
  .meta { min-width: 0; }
  .name { font-weight: 600; font-size: 13.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sub { font-size: 12px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  nav { display: flex; flex-direction: column; gap: 2px; flex: 1; }
  .item {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 36px;
    padding: 0 10px;
    border: 0;
    border-radius: 8px;
    background: transparent;
    color: var(--text-2);
    font: inherit;
    font-weight: 550;
    text-align: left;
    cursor: pointer;
  }
  .item:hover { background: var(--surface-3); color: var(--text); }
  .item.active { background: var(--accent-soft); color: var(--accent); }
  .label { flex: 1; }
  .badge {
    min-width: 22px;
    height: 20px;
    padding: 0 7px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 650;
    line-height: 20px;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }
  .badge-warn { background: var(--warn-soft); color: var(--warn); }
  .badge-muted { background: var(--surface-3); color: var(--text-3); }
  .live-dot {
    width: 8px;
    height: 8px;
    margin-right: 6px;
    border-radius: 50%;
    background: var(--ok);
    box-shadow: 0 0 0 3px var(--ok-soft);
    animation: pulse 1.6s infinite;
  }
  footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 12px 6px 0;
    border-top: 1px solid var(--border);
  }
  .conn { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-3); }
  .ver { opacity: .7; }

  @media (max-width: 860px) {
    .sidebar { width: 64px; padding: 12px 8px; }
    .brand span:last-child, .device .meta, .label, .badge, .conn { display: none; }
    .brand { justify-content: center; padding: 4px 0 14px; }
    .device { justify-content: center; padding: 6px; }
    .item { justify-content: center; padding: 0; }
    .live-dot { position: absolute; margin: -14px 0 0 18px; }
    footer { flex-direction: column; padding-top: 10px; }
    footer :global(.switch) { flex-direction: column; }
  }
</style>
