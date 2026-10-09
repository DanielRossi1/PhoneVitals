<script>
  import Icon from '../components/Icon.svelte';
  import { app, SENSOR, setLive } from '../lib/app.svelte.js';
  import { CONSTELLATIONS, live, UNKNOWN_CONSTELLATION } from '../lib/canvas.js';
  import { fixed, num } from '../lib/format.js';

  const r = $derived(app.live.readouts);
  const b = $derived(app.live.battery);
  const lux = $derived(num(r[SENSOR.LIGHT]?.[0]));
  const prox = $derived(num(r[SENSOR.PROXIMITY]?.[0]));
  // Logarithmic: ambient light runs from 0.1 lux (night) to 100000 lux (sun).
  const luxPct = $derived(lux === null ? 0 : Math.min(100, (Math.log10(Math.max(lux, 0.1)) + 1) * 20));
  const maxFreq = $derived(Math.max(1, ...app.live.cpu.map((c) => c.khz)));
  const agent = $derived(app.live.agent);
  const sensorCount = $derived(Array.isArray(agent?.info?.sensors) ? agent.info.sensors.length : 0);

  /** Action binding a canvas to one of the shared live views. */
  function attachView(node, view) {
    return view.attach(node);
  }

  function axes(v, unit) {
    return v ? `${fixed(v[0], 2)}  ${fixed(v[1], 2)}  ${fixed(v[2], 2)} ${unit}` : '—';
  }

  const CHARTS = [
    { key: 'accel', title: 'Accelerometer', type: SENSOR.ACCELEROMETER, unit: 'm/s²' },
    { key: 'gyro', title: 'Gyroscope', type: SENSOR.GYROSCOPE, unit: 'rad/s' },
    { key: 'mag', title: 'Magnetometer', type: SENSOR.MAGNETIC, unit: 'µT' },
  ];
</script>

<div class="page">
  <section class="card bar">
    <span class="state">
      <span class="dot" class:dot-ok={app.live.running} class:dot-pulse={app.live.running}></span>
      {app.live.running ? 'Streaming from the device' : 'Streams stopped'}
    </span>
    {#if agent?.ok}<span class="hint">{sensorCount} sensors through the on-device agent</span>{/if}
    <span class="spacer"></span>
    <button type="button" class="btn" class:btn-primary={!app.live.running} onclick={() => setLive(!app.live.running)}>
      <Icon name={app.live.running ? 'stop' : 'play'} size={14} />{app.live.running ? 'Stop' : 'Start streams'}
    </button>
  </section>

  {#if agent && !agent.ok}
    <div class="note note-warn"><Icon name="alert" />
      <div><strong>Live sensors unavailable.</strong> {agent.error || 'Unknown error.'}
        {#if agent.detail}<pre class="evidence">{agent.detail}</pre>{/if}
        <p>Touch, battery, temperatures and frequencies still work.</p></div>
    </div>
  {:else if agent?.ok}
    <p class="hint">Nothing was installed on the phone: the agent runs as a shell process and
      disappears when the session ends.</p>
  {/if}
  {#each app.live.problems as p (p.text)}
    <div class="note note-warn"><Icon name="alert" />
      <div><strong>The agent reported a problem:</strong> {p.text}
        {#if p.detail}<pre class="evidence">{p.detail}</pre>{/if}</div>
    </div>
  {/each}

  <div class="grid">
    {#each CHARTS as c (c.key)}
      <section class="card tile">
        <header><h3>{c.title}</h3><span class="legend"><i class="x"></i>X<i class="y"></i>Y<i class="z"></i>Z</span></header>
        <canvas class="chart" use:attachView={live[c.key]} aria-label="{c.title} chart, X Y Z axes"></canvas>
        <div class="now mono">{axes(r[c.type], c.unit)}</div>
      </section>
    {/each}

    <section class="card tile">
      <header><h3>Ambient light</h3></header>
      <div class="big" class:empty={lux === null}>{lux === null ? 'No data' : lux.toFixed(lux < 10 ? 1 : 0)}<small>lux</small></div>
      <div class="meter"><div style="width:{luxPct}%"></div></div>
    </section>

    <section class="card tile">
      <header><h3>Proximity</h3>
        {#if prox !== null}<span class="tag {prox < 3 ? 'tag-warn' : 'tag-ok'}">{prox < 3 ? 'Covered' : 'Clear'}</span>{/if}
      </header>
      <div class="big" class:empty={prox === null}>{prox === null ? 'No data' : prox.toFixed(1)}<small>cm</small></div>
    </section>

    <section class="card tile">
      <header><h3>Battery</h3>{#if b?.status}<span class="tag">{b.status}</span>{/if}</header>
      <div class="big" class:empty={b?.level == null}>{b?.level == null ? 'No data' : Math.round(b.level)}<small>%</small></div>
      <dl class="mini">
        {#if b?.voltage !== null && b?.voltage !== undefined}<div><dt>Voltage</dt><dd>{b.voltage.toFixed(3)} V</dd></div>{/if}
        {#if b?.current !== null && b?.current !== undefined}<div><dt>Current</dt><dd>{b.current.toFixed(0)} mA</dd></div>{/if}
        {#if b?.voltage != null && b?.current != null}<div><dt>Power</dt><dd>{((b.voltage * b.current) / 1000).toFixed(2)} W</dd></div>{/if}
        {#if b?.temperature !== null && b?.temperature !== undefined}<div><dt>Temperature</dt><dd>{b.temperature.toFixed(1)} °C</dd></div>{/if}
      </dl>
    </section>

    <section class="card tile wide">
      <header><h3>Temperature</h3><span class="hint">{app.live.tempMax === null ? '' : `hottest ${app.live.tempMax.toFixed(1)} °C`}</span></header>
      <canvas class="chart" use:live.temp.attach aria-label="Hottest temperature over time"></canvas>
      <div class="thermal">
        {#each app.live.thermal as t (t.name)}
          <div class:hot={t.t >= 45} class:veryhot={t.t >= 60}><span title={t.name}>{t.name}</span><b>{t.t.toFixed(1)}°</b></div>
        {/each}
      </div>
    </section>

    <section class="card tile">
      <header><h3>CPU frequencies</h3></header>
      <div class="cpu">
        {#each app.live.cpu as c (c.name)}
          <div class="row">
            <span class="lbl mono">{c.name}</span>
            <span class="track"><span style="width:{(c.khz / maxFreq) * 100}%"></span></span>
            <span class="val mono">{(c.khz / 1000).toFixed(0)} MHz</span>
          </div>
        {:else}
          <p class="hint">Waiting for data…</p>
        {/each}
      </div>
    </section>

    <section class="card tile tall">
      <header><h3>Touch</h3><span class="hint">{app.live.fingers} {app.live.fingers === 1 ? 'finger' : 'fingers'}</span></header>
      <canvas class="touchpad" use:live.touch.attach aria-label="Touch positions reported by the digitizer"></canvas>
      <p class="hint">Run a finger over the phone: coordinates come straight from the kernel.</p>
    </section>

    <section class="card tile wide tall">
      <header><h3>GNSS satellites</h3><span class="hint">{app.live.gnss.summary}</span></header>
      <div class="gnss">
        <canvas class="sky" use:live.sky.attach aria-label="Sky plot of the satellites in view"></canvas>
        <div class="sats">
          {#each app.live.gnss.sats as s, i (i)}
            {@const [name, color] = CONSTELLATIONS[s.constellation] ?? UNKNOWN_CONSTELLATION}
            {@const cn0 = Math.max(0, Math.min(50, num(s.cn0) ?? 0))}
            <div class="sat" class:used={s.used} title="{name} {s.svid} · {cn0.toFixed(0)} dB-Hz">
              <span class="lvl"><i style="height:{(cn0 / 50) * 100}%;background:{color}"></i></span>
              <span class="id">{s.svid}</span>
            </div>
          {/each}
        </div>
      </div>
      <p class="hint">{app.live.gnss.hint || 'Satellites in view appear here with their signal-to-noise ratio: seeing them proves the antenna receives, even without a fix.'}</p>
    </section>
  </div>
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 14px; }
  .bar { display: flex; align-items: center; gap: 14px; padding: 12px 16px; }
  .state { display: flex; align-items: center; gap: 10px; font-weight: 600; }
  .spacer { flex: 1; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
  .tile { display: flex; flex-direction: column; gap: 10px; padding: 14px 16px; min-width: 0; }
  .wide { grid-column: span 2; }
  @media (max-width: 760px) { .wide { grid-column: auto; } }
  header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  h3 { font-size: 13.5px; color: var(--text-2); }
  .legend { display: flex; align-items: center; gap: 4px; font-size: 11.5px; color: var(--text-3); }
  .legend i { width: 10px; height: 3px; border-radius: 2px; margin-left: 6px; }
  .legend .x { background: var(--axis-x); }
  .legend .y { background: var(--axis-y); }
  .legend .z { background: var(--axis-z); }
  .chart { width: 100%; height: 130px; }
  .now { font-size: 12px; color: var(--text-3); white-space: pre; }
  .big { font-size: 34px; font-weight: 700; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
  .big.empty { font-size: 15px; font-weight: 500; color: var(--text-3); padding: 12px 0 9px; }
  .big.empty small { display: none; }
  .big small { margin-left: 6px; font-size: 14px; font-weight: 600; color: var(--text-3); }
  .meter { height: 6px; border-radius: 6px; background: var(--surface-3); overflow: hidden; }
  .meter div { height: 100%; background: var(--warn); transition: width .3s; }
  .mini { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 14px; margin: 0; }
  .mini div { display: flex; justify-content: space-between; font-size: 12.5px; }
  .mini dt { color: var(--text-3); }
  .mini dd { margin: 0; font-family: var(--mono); }
  .thermal { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 4px 14px; }
  .thermal div { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; color: var(--text-2); }
  .thermal span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .thermal b { font-family: var(--mono); font-weight: 600; }
  .thermal .hot b { color: var(--warn); }
  .thermal .veryhot b { color: var(--crit); }
  .cpu { display: flex; flex-direction: column; gap: 7px; }
  .row { display: grid; grid-template-columns: 48px 1fr 78px; align-items: center; gap: 10px; font-size: 12px; }
  .lbl { color: var(--text-3); }
  .track { height: 6px; border-radius: 6px; background: var(--surface-3); overflow: hidden; }
  .track span { display: block; height: 100%; background: var(--accent); border-radius: 6px; transition: width .4s var(--ease); }
  .val { text-align: right; }
  .tall .touchpad { width: 100%; height: 340px; }
  .gnss { display: grid; grid-template-columns: minmax(200px, 1fr) 1fr; gap: 14px; align-items: center; }
  @media (max-width: 760px) { .gnss { grid-template-columns: 1fr; } }
  .sky { width: 100%; height: 280px; }
  .sats { display: flex; flex-wrap: wrap; gap: 4px; align-content: flex-start; }
  .sat { display: flex; flex-direction: column; align-items: center; gap: 3px; width: 22px; opacity: .55; }
  .sat.used { opacity: 1; }
  .lvl { position: relative; display: block; width: 10px; height: 60px; border-radius: 3px; background: var(--surface-3); overflow: hidden; }
  .lvl i { position: absolute; left: 0; right: 0; bottom: 0; }
  .id { font: 10px var(--mono); color: var(--text-3); }
</style>
