<script>
  import { onMount } from 'svelte';
  import Icon from './components/Icon.svelte';
  import Sidebar from './components/Sidebar.svelte';
  import TestDialog from './components/TestDialog.svelte';
  import Toasts from './components/Toasts.svelte';
  import Analysing from './screens/Analysing.svelte';
  import Blocked from './screens/Blocked.svelte';
  import Waiting from './screens/Waiting.svelte';
  import Authenticity from './views/Authenticity.svelte';
  import Health from './views/Health.svelte';
  import Live from './views/Live.svelte';
  import Overview from './views/Overview.svelte';
  import PrintReport from './views/PrintReport.svelte';
  import Raw from './views/Raw.svelte';
  import Specs from './views/Specs.svelte';
  import Tests from './views/Tests.svelte';
  import { app, connect, exportPdf, exportReport, initBench, reanalyse, SESSION_EXPIRED, toast } from './lib/app.svelte.js';
  import { PAGES } from './lib/pages.js';

  const VIEWS = {
    overview: Overview, authenticity: Authenticity, health: Health, tests: Tests,
    live: Live, specs: Specs, raw: Raw,
  };

  let exporting = $state(false);
  let main = $state();

  const page = $derived(PAGES.find((p) => p.id === app.page) ?? PAGES[0]);
  const View = $derived(VIEWS[page.id]);
  const demo = $derived(Boolean(app.snapshot?.meta?.demo));

  // `#print` is the printable report, rendered on its own for the PDF export.
  const printMode = location.hash === '#print';

  onMount(() => {
    if (printMode) return;
    initBench();
    connect();
  });

  $effect(() => {
    app.page;
    main?.scrollTo({ top: 0 });
  });

  async function onExport(kind) {
    if (exporting) return;
    exporting = true;
    try {
      await (kind === 'pdf' ? exportPdf() : exportReport());
    } catch (err) {
      toast(`Save failed: ${err?.message || err}`, 'crit', 6000);
    } finally {
      exporting = false;
    }
  }
</script>

{#if printMode}
  <PrintReport />
{:else}
{#if app.connection === 'expired' || (app.connection === 'offline' && app.screen === 'dashboard')}
  <div class="banner" role="alert">
    <Icon name="alert" size={16} />
    {app.connection === 'expired' ? SESSION_EXPIRED : 'Connection to the local service lost — retrying…'}
  </div>
{/if}

{#if app.screen === 'dashboard' && app.snapshot}
  <div class="shell">
    <Sidebar />
    <div class="column">
      <header class="topbar">
        <div class="titles">
          <h1>{page.label}</h1>
          <p>{page.subtitle}</p>
        </div>
        {#if demo}<span class="tag tag-info">Demo data</span>{/if}
        <div class="actions">
          <button type="button" class="btn" onclick={reanalyse}>
            <Icon name="refresh" size={15} /><span>Re-analyse</span>
          </button>
          <button type="button" class="btn" onclick={() => onExport('json')} disabled={exporting}
                  title="All the collected data, as JSON">
            <Icon name="data" size={15} /><span>JSON</span>
          </button>
          <button type="button" class="btn btn-primary" onclick={() => onExport('pdf')} disabled={exporting}
                  aria-busy={exporting}>
            <Icon name="download" size={15} /><span>PDF report</span>
          </button>
        </div>
      </header>
      <main class="scroll" bind:this={main}>
        <div class="content"><View /></div>
      </main>
    </div>
  </div>
{:else if app.screen === 'analysing'}
  <Analysing />
{:else if app.screen === 'blocked'}
  <Blocked />
{:else}
  <Waiting />
{/if}

<TestDialog />
<Toasts />
{/if}

<style>
  .shell { display: flex; height: 100%; }
  .column { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .topbar {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 18px 28px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--bg);
  }
  .titles { flex: 1; min-width: 0; }
  h1 { font-size: 20px; letter-spacing: -.02em; }
  .titles p { font-size: 13px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .actions { display: flex; gap: 8px; }
  main { flex: 1; }
  .content { max-width: 1280px; margin: 0 auto; padding: 24px 28px 48px; }
  .banner {
    position: fixed;
    top: 12px;
    left: 50%;
    z-index: 60;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    border-radius: 999px;
    background: var(--crit);
    color: #fff;
    font-size: 13px;
    font-weight: 600;
    box-shadow: var(--shadow-lg);
  }
  @media (max-width: 760px) {
    .actions span { display: none; }
    .topbar, .content { padding-left: 16px; padding-right: 16px; }
  }
</style>
