<script>
  import FindingGroup from '../components/FindingGroup.svelte';
  import Icon from '../components/Icon.svelte';
  import Section from '../components/Section.svelte';
  import SpecGrid from '../components/SpecGrid.svelte';
  import { app, forgetReference, rereadImei, saveReference } from '../lib/app.svelte.js';
  import { present } from '../lib/format.js';
  import { groupsFor } from '../lib/report.js';

  const snap = $derived(app.snapshot);
  const groups = $derived(groupsFor(snap, 'authenticity'));
  const identity = $derived(snap?.identity ?? {});
  const imeis = $derived(Array.isArray(snap?.imei_analysis?.imeis) ? snap.imei_analysis.imeis : []);
  const notes = $derived(Array.isArray(identity.notes) ? identity.notes : []);
  const evidence = $derived((snap?.evidence ?? []).filter((e) => e?.png_b64));
  const memory = $derived(snap?.memory);
  const reference = $derived(memory?.reference);
  const modelName = $derived(`${snap?.summary?.brand ?? ''} ${snap?.summary?.model ?? ''}`.trim());
  let confirming = $state(false);

  const SERIAL_LABELS = {
    ro: 'System property (ro.serialno)',
    boot: 'Bootloader (ro.boot.serialno)',
    vendor: 'Vendor partition',
    usb_transport: 'USB descriptor',
  };
  const serials = $derived(identity.serials ?? {});
  const serialRows = $derived(
    Object.entries(serials.values ?? {})
      .filter(([, val]) => present(val))
      .map(([k, val]) => [SERIAL_LABELS[k] ?? k, val]),
  );

  const att = $derived(snap?.attestation);
  const attRows = $derived.by(() => {
    if (!att?.available) return [];
    const rows = [
      ['Security level', att.security_label],
      ['Attestation version', att.attestation_version],
      ['KeyMint version', att.keymint_version],
      ['Requested by', att.requesting_package],
      ['Android according to the TEE', att.os_version],
      ['Patch according to the TEE', att.os_patch_level],
      ['Vendor patch according to the TEE', att.vendor_patch_level],
      ['Bootloader patch', att.boot_patch_level],
    ];
    for (const [k, val] of Object.entries(att.attested_identity ?? {})) rows.push([`Attested ${k}`, val]);
    for (const [k, val] of Object.entries(att.attested_ids ?? {})) rows.push([`Signed identifier · ${k}`, val]);
    return rows.filter(([, val]) => present(val));
  });
  const attBadges = $derived.by(() => {
    if (!att?.available) return [];
    const rot = att.root_of_trust ?? {};
    const chain = att.chain ?? {};
    const chainBadge = chain.checked && chain.roots_available
      ? [[Boolean(chain.signatures_valid && chain.root_trusted), 'Chain signed by Google',
          chain.signatures_valid === false ? 'Chain does not verify' : 'Root is not Google\'s']]
      : [];
    return [
      ...chainBadge,
      [att.security_level !== 'software', 'Backed by hardware', 'Software only'],
      [rot.verified_boot_state === 'verified', 'Verified boot', 'Boot not verified'],
      [rot.device_locked === true, 'Bootloader locked', 'Bootloader unlocked'],
      [att.challenge_matches !== false, 'Fresh for this session', 'Replayed certificate'],
    ];
  });
  const attNoIdentity = $derived(
    att?.available && !Object.keys(att.attested_identity ?? {}).length
      && !Object.keys(att.attested_ids ?? {}).length,
  );
</script>

<div class="page">
  {#each groups as g (g.category)}<FindingGroup group={g} />{/each}

  <Section title="IMEI" subtitle="Structure, check digit and type allocation code">
    {#snippet actions()}
      <button type="button" class="btn btn-sm" onclick={rereadImei}>
        <Icon name="refresh" size={14} /> Read again
      </button>
    {/snippet}

    {#if identity.needs_unlock}
      <div class="note note-warn"><Icon name="lock" />
        <div><strong>Unlock the phone screen.</strong> On Android 10 and later the IMEI is
          protected by a permission reserved to the system; the only way left is to read it
          from the screen, which has to be unlocked. Then press “Read again”.</div>
      </div>
    {:else if !imeis.length}
      <div class="note note-info"><Icon name="info" />No IMEI was read automatically.</div>
    {/if}

    {#each evidence as e (e.id)}
      <figure class="evidence-shot">
        <img src="data:image/png;base64,{e.png_b64}" alt={e.title} />
        <figcaption>{e.title} · {e.taken_at?.replace('T', ' ').slice(0, 16)}</figcaption>
      </figure>
    {/each}

    <div class="imeis">
      {#each imeis as p, i (i)}
        {@const good = p.luhn_valid && p.valid}
        {@const tac = p.tac_info ?? {}}
        <div class="imei">
          <div class="imei-head">
            <span class="digits">{p.digits || p.input}</span>
            <span class="tag {good ? 'tag-ok' : 'tag-crit'}">{good ? 'Valid structure' : 'Invalid structure'}</span>
          </div>
          <div class="parts">
            <div><span>TAC (model)</span><b>{p.tac || '—'}</b></div>
            <div><span>Serial</span><b>{p.serial_number || '—'}</b></div>
            <div><span>Check digit</span><b>{p.check_digit ?? '—'}</b></div>
          </div>
          {#each Array.isArray(p.problems) ? p.problems : [] as problem, j (j)}
            <div class="note note-crit"><Icon name="error" />{problem}</div>
          {/each}
          {#if tac.found === true}
            <div class="note note-ok"><Icon name="ok" />
              <span>The TAC is assigned to <strong>{tac.brand} {tac.model}</strong>.</span></div>
          {:else if tac.note}
            <div class="note note-info"><Icon name="info" />{tac.note}</div>
          {/if}
        </div>
      {/each}
    </div>
  </Section>

  <Section title="Hardware attestation" subtitle="What the secure chip signs, compared with what the software declares">
    {#if !att?.available}
      <div class="note note-warn"><Icon name="alert" />
        <div><strong>Not obtained.</strong> The secure environment did not issue a certificate,
          so the strongest check available goes unused and the system properties have no
          independent corroboration.
          {#if att?.error}<pre class="evidence">{att.error}</pre>{/if}
        </div>
      </div>
    {:else}
      <div class="badges">
        {#each attBadges as [good, yes, no] (yes)}
          <span class="tag {good ? 'tag-ok' : 'tag-crit'}"><Icon name={good ? 'ok' : 'error'} size={13} />{good ? yes : no}</span>
        {/each}
      </div>
      <div class="flush"><SpecGrid rows={attRows} /></div>
      {#if attNoIdentity}
        <div class="note note-info"><Icon name="info" />
          This device does not include brand, model and serial among the attested fields. It is
          optional and many manufacturers leave it off: the certificate still vouches for the boot
          state and patch levels, but the identity comparison rests on the other checks.</div>
      {/if}
      {#if !att.roots_file_present}
        <div class="note note-info"><Icon name="info" />
          <span>The chain was not checked: Google's attestation roots
            (<code>data/attestation_roots.pem</code>) are missing from this installation.
            Agreement with the system properties is worth less without it.</span></div>
      {/if}
      {#if att.chain?.revoked?.length}
        <div class="note note-warn"><Icon name="alert" />
          <span>A key in this chain is on Google's revocation list
            ({att.chain.revoked.map((r) => r.reason || r.status).join(', ')}).</span></div>
      {/if}
    {/if}
  </Section>

  <Section title="Serial number" subtitle="The same value, read from independent sources">
    {#if serialRows.length}
      <div class="flush"><SpecGrid rows={serialRows} /></div>
      {#if serials.consistent === true}
        <div class="note note-ok"><Icon name="ok" />All sources agree, as they must on an intact device.</div>
      {:else if serials.consistent === false}
        <div class="note note-warn"><Icon name="alert" />The sources disagree: at least one value was rewritten.</div>
      {/if}
    {:else}
      <div class="note note-info"><Icon name="info" />No serial number could be read.</div>
    {/if}
  </Section>

  {#if memory}
    <Section title="Reference unit"
             subtitle="Your own known-genuine phone of this model, to compare others with">
      {#if reference}
        <p class="ref">
          Compared with <strong>{reference.label}</strong>, saved on {reference.saved_at.slice(0, 10)}:
          {reference.differences.length
            ? `${reference.differences.length} of ${reference.compared} traits differ (see the findings above).`
            : `all ${reference.compared} traits match.`}
        </p>
        <button type="button" class="btn btn-sm" onclick={forgetReference}>Forget this reference</button>
      {:else if confirming}
        <div class="note note-warn"><Icon name="alert" />
          <div>Save only a phone you know is genuine: every later {modelName} will be judged
            against it.
            <div class="row">
              <button type="button" class="btn btn-sm btn-primary"
                      onclick={() => { saveReference(); confirming = false; }}>Save as reference</button>
              <button type="button" class="btn btn-sm btn-ghost" onclick={() => (confirming = false)}>Cancel</button>
            </div>
          </div>
        </div>
      {:else}
        <p class="ref">No reference for {modelName || 'this model'} yet. Once one is saved, every
          later unit of the model is compared with it trait by trait: processor, cores,
          frequencies, resolution, cameras, sensor chips.</p>
        <button type="button" class="btn btn-sm" onclick={() => (confirming = true)}>
          Save this phone as the reference…</button>
      {/if}
    </Section>
  {/if}

  {#if notes.length}
    <div class="note note-info"><Icon name="info" /><div>{#each notes as n, i (i)}<p>{n}</p>{/each}</div></div>
  {/if}
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 16px; }
  .note + .note, .imeis + .note { margin-top: 10px; }
  .imeis { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
  .imeis:not(:empty) { margin-top: 2px; }
  .imei { padding: 16px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface-2); }
  .imei .note { margin-top: 10px; }
  .imei-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
  .digits { font: 600 20px var(--mono); letter-spacing: .04em; }
  .parts { display: flex; gap: 22px; margin-top: 12px; }
  .parts div { display: flex; flex-direction: column; }
  .parts span { font-size: 11.5px; color: var(--text-3); }
  .parts b { font-family: var(--mono); font-weight: 600; }
  .badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
  .flush { margin: 0 -18px 14px; }
  .flush:last-child { margin-bottom: -18px; }
  .ref { margin-bottom: 12px; color: var(--text-2); }
  .evidence-shot { float: right; margin: 0 0 12px 16px; text-align: center; }
  .evidence-shot img {
    display: block;
    max-height: 260px;
    border: 1px solid var(--border);
    border-radius: 10px;
  }
  .evidence-shot figcaption { margin-top: 6px; max-width: 160px; font-size: 11.5px; color: var(--text-3); }
  @media (max-width: 760px) { .evidence-shot { float: none; margin: 0 0 12px; } }
  .row { display: flex; gap: 8px; margin-top: 10px; }
</style>
