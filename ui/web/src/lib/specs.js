/** The snapshot as titled sections of key/value rows. Rows whose value is
 * missing are dropped: a collector that failed leaves gaps, not wrong text. */

import { bytes, cap, flag, list, num, present } from './format.js';

const gb = (kb) => (num(kb) ? `${(num(kb) / 1024 / 1024).toFixed(2)} GB` : null);
const withUnit = (v, unit) => (present(v) ? `${v} ${unit}` : null);

function section(id, title, rows) {
  return { id, title, rows: rows.filter(([, v]) => present(v)) };
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                'September', 'October', 'November', 'December'];

/** "2021-08" as "August 2021". */
export function monthName(iso) {
  const m = /^(\d{4})-(\d{2})/.exec(iso || '');
  return m ? `${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]}` : null;
}

/** The phone's past, as key/value rows. */
export function historyRows(s) {
  const h = s?.history;
  if (!h) return [];
  const crashes = h.crashes || {};
  const accounts = h.accounts || {};
  const abnormal = list(h.boot_history).filter((b) => b.abnormal).map((b) => b.reason);
  return [
    ['Manufactured', h.manufactured ? `${monthName(h.manufactured.iso)} (from the serial number)` : null],
    ['First started', h.setup_date
      ? `${h.setup_date.iso}${h.setup_date.days_ago != null ? ` · ${h.setup_date.days_ago} days ago` : ''}`
        + (h.setup_date.confident ? '' : ' · approximate')
      : null],
    ['Boots since then', h.boot_count],
    ['Last boot reason', h.boot_reason],
    ['Abnormal restarts', h.boot_history?.length ? (abnormal.length ? abnormal.join(', ') : 'none recorded') : null],
    ...Object.entries(crashes.counts || {}).map(([tag, n]) =>
      [cap((crashes.labels || {})[tag] || tag), `${n}${crashes.since ? ` since ${crashes.since}` : ''}`]),
    ['Google accounts', accounts.read ? (accounts.google ? `${accounts.google} signed in` : 'none') : null],
    ['Management', h.control?.read
      ? (h.control.financed ? 'financing lock (Device Lock)'
        : h.control.knox_guard_locked ? `Knox Guard: ${h.control.knox_guard}`
        : h.control.owners?.length ? h.control.owners.join('; ') : 'none')
      : null],
    ['Device admins', h.control?.read ? h.control.device_admins : null],
    ['Region', h.region ? [h.region.sales_code && `sales code ${h.region.sales_code}`,
                           h.region.carrier_id && `carrier ${h.region.carrier_id}`,
                           h.region.country].filter(Boolean).join(' · ') : null],
    ['Hardware errors in log', h.log_errors
      ? (Object.entries(h.log_errors).map(([l, n]) => `${n} ${l}`).join(', ') || 'none')
      : null],
    ['Personal files', h.user_files ? (h.user_files.total ? `${h.user_files.total} in shared storage` : 'none') : null],
    ['Analysed here before', s.memory?.sightings
      ? (s.memory.sightings.seen_before
        ? `${s.memory.sightings.seen_before} time(s), first on ${s.memory.sightings.first_seen.slice(0, 10)}`
        : 'no, first time')
      : null],
    ['Other accounts', accounts.read
      ? Object.entries(accounts.by_type || {}).filter(([t]) => t !== 'com.google')
        .map(([t, n]) => `${t} (${n})`).join(', ') || 'none'
      : null],
  ].filter(([, v]) => present(v));
}

export function specSections(s) {
  if (!s) return [];
  const sys = s.system || {}, os = sys.os || {}, build = sys.build || {}, soc = sys.soc || {};
  const cpu = s.cpu || {}, mem = s.memory || {}, stor = s.storage || {};
  const disp = s.display || {}, bat = s.battery || {}, sens = s.sensors || {};
  const cams = s.cameras || {}, tel = s.telephony || {}, wifi = s.wifi || {};
  const conn = s.connectivity || {}, security = s.security || {}, pkg = s.packages || {};
  const res = disp.resolution || {};
  const eff = (sys.partitions || {}).effective || {};
  const ufs = stor.ufs_health || {};
  const signal = tel.signal || {};
  const boot = security.bootloader || {};
  const enc = security.encryption || {};

  let wifiState;
  if (wifi.connected) wifiState = wifi.ssid ? `connected to ${wifi.ssid}` : 'connected';
  else wifiState = flag(wifi.enabled, 'on', 'off');

  return [
    section('identification', 'Identification', [
      ['Brand', cap(eff.brand)], ['Manufacturer', eff.manufacturer],
      ['Model', eff.model], ['Codename', eff.device],
      ['Board', build.board], ['Platform', soc.platform],
    ]),
    section('os', 'Operating system', [
      ['Android', os.android_release], ['API level', os.sdk],
      ['Security patch', os.security_patch],
      ['Vendor patch', os.vendor_security_patch],
      ['Build', build.display_id || build.id],
      ['Build type', `${build.type || ''} ${build.tags || ''}`.trim()],
      ['Build date', build.date],
      ['Fingerprint', build.fingerprint],
      ['Kernel', (sys.kernel || {}).release],
      ['Bootloader', build.bootloader], ['Baseband', build.baseband],
      ['Initial API', os.first_api_level],
      ['One UI', os.oneui],
    ]),
    section('cpu', 'Processor', [
      ['Declared SoC', `${soc.declared_manufacturer || ''} ${soc.declared_model || ''}`.trim()],
      ['Kernel hardware line', soc.hardware_line],
      ['Total cores', cpu.core_count],
      ...list(soc.core_types).map((c, i) => [`Cluster ${i + 1}`,
        `${c.count ?? '?'}× ${c.microarchitecture || '?'}${c.implementer ? ` (${c.implementer})` : ''}`]),
      ...list(cpu.clusters).map((c, i) => [`Cluster ${i + 1} frequency`,
        num(c.max_khz) ? `${c.count ?? '?'}× ${(num(c.max_khz) / 1000).toFixed(0)} MHz` : null]),
      ['Supported ABIs', list(sys.abis).join(', ')],
    ]),
    section('memory', 'Memory and storage', [
      ['Total RAM', gb(mem.total_kb)],
      ['Nominal RAM', withUnit(mem.nominal_gb, 'GB')],
      ['Swap / zRAM', gb(mem.swap_total_kb)],
      ['Storage type', stor.type],
      ['Physical capacity', withUnit(stor.nominal_gb, 'GB')],
      ['Data partition', bytes(stor.data_total_bytes)],
      ['Free space', bytes(stor.data_available_bytes)],
      ...list(stor.devices).map((d, i) => [`Chip ${i + 1}`,
        `${d.vendor || ''} ${d.model || ''} rev ${d.rev || '?'}`.trim()]),
      ['SLC wear', (ufs.life_time_a || {}).used_percent_range],
      ['MLC/TLC wear', (ufs.life_time_b || {}).used_percent_range],
      ['End-of-life status', ufs.eol_description],
    ]),
    section('display', 'Display', [
      ['Resolution', res.width ? `${res.width} × ${res.height}` : null],
      ['Density', withUnit(disp.physical_density, 'dpi')],
      ['Refresh rates', list(disp.refresh_rates).map((r) => `${r} Hz`).join(', ')],
      ['Video modes', list(disp.modes).length || null],
      ['HDR', list(disp.hdr_types).join(', ')],
      ...Object.entries(disp.panel || {}).map(([k, v]) => [`Panel · ${k}`, v]),
    ]),
    section('battery', 'Battery', [
      ['Level', withUnit(bat.level_percent, '%')],
      ['State', bat.status], ['Power source', bat.plugged],
      ['Health (framework)', bat.health_text],
      ['Technology', bat.technology], ['Cell type', bat.battery_type],
      ['Design capacity', bat.design_capacity_mah ? `${bat.design_capacity_mah} mAh` : null],
      ['Current capacity', bat.full_capacity_mah ? `${bat.full_capacity_mah} mAh` : null],
      ['Estimated health', withUnit(bat.health_percent, '%')],
      ['Charge cycles', bat.cycle_count],
      ['Cell manufacturing date', (bat.manufacturing_date || {}).iso],
      ['First use', (bat.first_usage_date || {}).iso],
      ['Service part code', bat.part_number], ['Cell serial', bat.serial_number],
      ['Voltage', bat.voltage_v ? `${bat.voltage_v} V` : null],
      ['Temperature', bat.temperature_c ? `${bat.temperature_c} °C` : null],
    ]),
    section('cameras', 'Cameras', [
      ['Total', cams.count], ['Rear', cams.back_count], ['Front', cams.front_count],
      ...list(cams.cameras).map((c) => [
        `Camera ${c.id ?? '?'} (${c.facing || '?'})`,
        [c.megapixels && `${c.megapixels} MP`,
         c.pixel_array && `${c.pixel_array.width}×${c.pixel_array.height}`,
         list(c.focal_lengths_mm).length && `f=${c.focal_lengths_mm.join('/')} mm`,
         list(c.apertures).length && `ƒ/${c.apertures.join(' ƒ/')}`,
        ].filter(Boolean).join(' · '),
      ]),
    ]),
    section('sensors', 'Sensors', [
      ['Total', sens.count],
      ['Vendors', list(sens.vendors).join(', ')],
      ...Object.entries(sens.by_type || {}).map(([type, items]) =>
        [type, list(items).map((x) => `${x.name} (${x.vendor})`).join(', ')]),
    ]),
    section('radio', 'Radio and connectivity', [
      ['Baseband', tel.baseband], ['Carrier', tel.operator],
      ['SIMs present', tel.sim_count],
      ['SIM state', list(tel.sim_states).map((x) => x.text).filter(Boolean).join(', ')],
      ['Network', tel.network_type],
      ['Signal', signal.level_text],
      ['LTE RSRP', signal.lte_rsrp_dbm ? `${signal.lte_rsrp_dbm} dBm` : null],
      ['Wi-Fi', wifiState],
      ['Wi-Fi RSSI', wifi.rssi_dbm ? `${wifi.rssi_dbm} dBm` : null],
      ['Wi-Fi standards', list(wifi.standards).join(', ')],
      ['Wi-Fi bands', list(wifi.bands_supported).join(', ')],
      ['Bluetooth', flag((conn.bluetooth || {}).present, 'present', 'absent')],
      ['NFC', flag((conn.nfc || {}).present, 'present', 'absent')],
      ['Location providers', list((conn.location || {}).providers).join(', ')],
    ]),
    section('security', 'Security', [
      ['Verified boot', (security.verified_boot || {}).label],
      ['Bootloader', flag(boot.locked, 'locked', 'unlocked')],
      ['vbmeta digest', boot.vbmeta_digest],
      ['SELinux', (security.selinux || {}).mode],
      ['Encryption', flag(enc.encrypted, enc.type ? `active (${enc.type})` : 'active', 'inactive')],
      ['Knox warranty bit', (security.knox || {}).warranty_bit],
      ['Root detected', flag((security.root || {}).detected, 'yes', 'no')],
      ['System apps', pkg.system_count], ['Third-party apps', pkg.third_party_count],
      ['Play Services', pkg.gms_version],
    ]),
  ].filter((sec) => sec.rows.length);
}
