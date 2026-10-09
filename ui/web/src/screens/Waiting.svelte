<script>
  import Icon from '../components/Icon.svelte';
  import StateLayout from './StateLayout.svelte';
  import { app, SESSION_EXPIRED } from '../lib/app.svelte.js';

  const STEPS = [
    { title: 'Turn on developer options', text: 'Settings › About phone › tap Build number seven times.' },
    { title: 'Enable USB debugging', text: 'Settings › System › Developer options › USB debugging.' },
    { title: 'Allow this computer', text: 'When the phone asks “Allow USB debugging?”, tap Allow.' },
    { title: 'Keep the screen unlocked', text: 'Only needed to read the IMEI, which Android 10+ shows nowhere else.' },
  ];

  const status = $derived.by(() => {
    switch (app.connection) {
      case 'online': {
        const ready = app.devices.find((d) => d.ready);
        if (ready) return { tone: 'ok', text: `${ready.label || ready.serial} connected — starting the analysis…` };
        const other = app.devices[0];
        if (other) return { tone: 'warn', text: `${other.label || other.serial}: ${other.state}` };
        return { tone: 'ok', text: 'Ready — waiting for a phone' };
      }
      case 'expired': return { tone: 'crit', text: SESSION_EXPIRED };
      case 'fatal': return { tone: 'crit', text: 'The local service cannot run' };
      case 'offline': return { tone: 'crit', text: 'Connection to the local service lost — retrying…' };
      default: return { tone: 'none', text: 'Connecting to the local service…' };
    }
  });
</script>

<StateLayout>
  <div class="hero">
    <div class="art" aria-hidden="true">
      <span class="ring"></span><span class="ring r2"></span>
      <span class="phone"><Icon name="usb" size={34} stroke={1.7} /></span>
    </div>
    <h1>Connect an Android phone</h1>
    <p class="lede">Plug it in over USB. The analysis starts by itself and takes a few seconds.</p>

    <div class="status tone-{status.tone}" aria-live="polite">
      <span class="dot" class:dot-ok={status.tone === 'ok'} class:dot-warn={status.tone === 'warn'}
            class:dot-crit={status.tone === 'crit'} class:dot-pulse={status.tone !== 'crit'}></span>
      {status.text}
    </div>

    {#if app.fatal}
      <div class="note note-crit fatal"><Icon name="error" />{app.fatal}</div>
    {/if}
  </div>

  <ol class="steps">
    {#each STEPS as step, i (step.title)}
      <li class="card">
        <span class="n">{i + 1}</span>
        <div>
          <h3>{step.title}</h3>
          <p>{step.text}</p>
        </div>
      </li>
    {/each}
  </ol>
  <p class="hint foot">No root needed, nothing is installed on the phone. Keep the bootloader locked:
    unlocking it destroys the integrity evidence this tool checks.</p>
  <p class="hint foot terms">PhoneVitals helps you understand the condition of a phone, for example
    before buying or selling it. Its results are indicative and provided as is, without warranty:
    they are not a certification, and the authors accept no liability for decisions based on them
    or for any damage arising from its use. Some tests heat the phone, vibrate it or change a
    setting for a few seconds; use them at your own risk.</p>
</StateLayout>

<style>
  .hero { display: flex; flex-direction: column; align-items: center; text-align: center; max-width: 560px; }
  .art { position: relative; display: grid; place-items: center; width: 120px; height: 120px; margin-bottom: 20px; }
  .phone {
    position: relative;
    display: grid;
    place-items: center;
    width: 72px;
    height: 72px;
    border-radius: 22px;
    background: var(--accent-soft);
    color: var(--accent);
  }
  .ring {
    position: absolute;
    inset: 24px;
    border-radius: 50%;
    border: 2px solid var(--accent);
    opacity: 0;
    animation: ripple 2.8s var(--ease) infinite;
  }
  .r2 { animation-delay: 1.4s; }
  @keyframes ripple {
    0% { transform: scale(.7); opacity: .5; }
    100% { transform: scale(1.6); opacity: 0; }
  }
  h1 { font-size: 26px; letter-spacing: -.02em; }
  .lede { margin-top: 8px; color: var(--text-2); font-size: 15px; }
  .status {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    margin-top: 22px;
    padding: 8px 14px;
    border-radius: 999px;
    background: var(--surface);
    border: 1px solid var(--border);
    font-size: 13px;
    color: var(--text-2);
  }
  .fatal { margin-top: 16px; text-align: left; }
  .steps {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
    width: min(960px, 100%);
    margin: 40px 0 0;
    padding: 0;
    list-style: none;
  }
  .steps li { display: flex; gap: 12px; padding: 16px; }
  .n {
    display: grid;
    place-items: center;
    width: 26px;
    height: 26px;
    flex: none;
    border-radius: 50%;
    background: var(--surface-3);
    font-size: 12.5px;
    font-weight: 700;
    color: var(--text-2);
  }
  h3 { font-size: 13.5px; margin-bottom: 3px; }
  .steps p { font-size: 12.5px; color: var(--text-3); }
  .foot { margin-top: 20px; max-width: 620px; text-align: center; }
  .terms { margin-top: 8px; font-size: 11.5px; }
</style>
