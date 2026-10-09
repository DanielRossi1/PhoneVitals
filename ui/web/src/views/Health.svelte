<script>
  import FindingGroup from '../components/FindingGroup.svelte';
  import Section from '../components/Section.svelte';
  import SpecGrid from '../components/SpecGrid.svelte';
  import Stat from '../components/Stat.svelte';
  import { app } from '../lib/app.svelte.js';
  import { num, plural } from '../lib/format.js';
  import { groupsFor } from '../lib/report.js';
  import { historyRows, specSections } from '../lib/specs.js';

  const snap = $derived(app.snapshot);
  const groups = $derived(groupsFor(snap, 'health'));
  const sections = $derived(specSections(snap).filter((s) => ['battery', 'memory', 'display'].includes(s.id)));
  const history = $derived(historyRows(snap));

  const bat = $derived(snap?.battery ?? {});
  const health = $derived(num(bat.health_percent));
  const cycles = $derived(num(bat.cycle_count));
  const ufs = $derived(snap?.storage?.ufs_health ?? {});
  const wear = $derived(ufs.life_time_b?.used_percent_range ?? ufs.life_time_a?.used_percent_range ?? null);
  const hottest = $derived(snap?.thermal?.hottest ?? null);
  const throttling = $derived(snap?.thermal?.throttling_status?.text ?? '');
</script>

<div class="page">
  <div class="stats">
    {#if health === null}
      <Stat icon="battery" label="Battery health" value="Unknown" tone="warn"
            detail={bat.health_note || 'Not exposed by this device'} />
    {:else}
      <Stat icon="battery" label="Battery health" unit="%" value={Math.round(health)}
            tone={health >= 80 ? 'ok' : health >= 70 ? 'warn' : 'crit'}
            detail={[cycles !== null && plural(cycles, 'cycle'),
                     num(bat.full_capacity_mah) && `${Math.round(num(bat.full_capacity_mah))} of ${Math.round(num(bat.design_capacity_mah) ?? 0)} mAh`]
                    .filter(Boolean).join(' · ')} />
    {/if}
    <Stat icon="storage" label="Storage wear" value={wear}
          tone={ufs.eol_code > 1 ? 'warn' : wear ? 'ok' : 'none'}
          detail={ufs.eol_description || 'Health descriptor not exposed'} />
    <Stat icon="health" label="Hottest sensor" unit="°C"
          value={num(hottest?.celsius) === null ? null : num(hottest.celsius).toFixed(1)}
          tone={num(hottest?.celsius) === null ? 'none' : num(hottest.celsius) >= 60 ? 'crit' : num(hottest.celsius) >= 45 ? 'warn' : 'ok'}
          detail={[hottest?.type, throttling].filter(Boolean).join(' · ')} />
  </div>

  {#each groups as g (g.category)}<FindingGroup group={g} />{/each}

  {#if history.length}
    <Section title="History" subtitle="Age, time in use, restarts and accounts" flush>
      <SpecGrid rows={history} />
    </Section>
  {/if}

  {#each sections as sec (sec.id)}
    <Section title={sec.title} flush><SpecGrid rows={sec.rows} /></Section>
  {/each}
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 16px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
</style>
