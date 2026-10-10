/**
 * Hardware check: every component the device exposes, with what it reports
 * about itself, what the device says about replacement, the clues found by
 * the analysis and the outcome of the tests that exercise it.
 */

import { findings } from './report.js';

const list = (v) => (Array.isArray(v) ? v : []);
const join = (...parts) => parts.filter((p) => p !== null && p !== undefined && p !== '').join(' · ');

// Physical sensors worth a row of their own; fused and virtual ones
// (gravity, rotation vector, step counter...) are computed from these.
const SENSORS = [
  ['Accelerometer', 'Accelerometer', ['sensor_physics', 'imu', 'vibration_imu']],
  ['Gyroscope', 'Gyroscope', ['sensor_physics', 'imu']],
  ['Magnetometer', 'Compass (magnetometer)', ['sensor_physics', 'magnetometer']],
  ['Ambient light', 'Ambient light sensor', ['light']],
  ['Proximity', 'Proximity sensor', ['proximity']],
  ['Barometer', 'Barometer', []],
  ['Relative humidity', 'Humidity sensor', []],
  ['Ambient temperature', 'Temperature sensor', []],
  ['Heart rate', 'Heart rate sensor', []],
  ['Hinge angle', 'Hinge angle sensor', []],
];

// Kernel modules named after the chip they drive: touch, fingerprint, Wi-Fi,
// NFC, haptics, charging and power, sensors.
const CHIP_DRIVER = /^(goodix|fpc|syna|fts|sec_ts|stm_ts|nfc_sec|ilitek|novatek|nt3\d|himax|focaltech|bcmdhd|qca|cnss|wlan$|st21nfc|nxp|pn5|sec_nfc|cs40l|cs35l|aw8|tas2|max77|bq2|smb\d|pca94|rt94|sx9|stmvl|vl53|lsm6|icm4|bmi|mmc5|ak09|tmd|apds|qm35)/i;

/** Finding titles that point at a component, matched by keyword. */
const CLUE_WORDS = {
  display: /screen|display|panel|burn/i,
  touch: /touch|digitizer/i,
  fingerprint: /fingerprint/i,
  battery: /battery|cell/i,
  cameras: /camera/i,
};

function statusOf(row, results) {
  const runs = row.tests.map((id) => results[id]?.status).filter(Boolean);
  if (row.replaced) return { label: 'Replaced', tone: 'warn' };
  if (runs.includes('failed')) return { label: 'Failed', tone: 'crit' };
  if (row.clues.length) return { label: 'Check', tone: 'warn' };
  if (row.present === false) return { label: 'Not fitted', tone: 'none' };
  if (runs.includes('passed')) return { label: 'Works', tone: 'ok' };
  if (row.original) return { label: 'Original', tone: 'ok' };
  if (row.tests.length) return { label: 'Not tested', tone: 'none' };
  return { label: 'Present', tone: 'none' };
}

export function hardwareGroups(s, results = {}) {
  if (!s) return [];
  const all = findings(s).filter((f) => f.category === 'components'
    && (f.severity === 'warning' || f.severity === 'critical'));
  const cluesFor = (key) => all.filter((f) => CLUE_WORDS[key]?.test(f.title)).map((f) => f.title);

  const disp = s.display ?? {};
  const res = disp.resolution ?? {};
  const touch = s.input?.touchscreen ?? null;
  const stylus = s.input?.stylus ?? null;
  const bat = s.battery ?? {};
  const audio = s.audio ?? {};
  const vib = s.vibrator ?? {};
  const fp = s.biometrics?.fingerprint ?? {};
  const fpChip = s.components?.fingerprint ?? {};
  const cams = list(s.cameras?.cameras);
  const camParts = list(s.components?.cameras);
  const conn = s.connectivity ?? {};
  const tel = s.telephony ?? {};
  const stor = s.storage ?? {};
  const soc = s.system?.soc ?? {};
  const byType = s.sensors?.by_type ?? {};

  const groups = [
    { title: 'Display and input', rows: [
      { id: 'display', icon: 'monitor', name: 'Display',
        identity: join(disp.product_info?.name, res.width && `${res.width}x${res.height}`,
                       list(disp.refresh_rates).length && `${Math.max(...disp.refresh_rates)} Hz`,
                       list(disp.hdr_types).length ? list(disp.hdr_types).join('/') : null),
        replaced: disp.screen_part_status === 'REPLACED',
        original: disp.screen_part_status === 'ORIGINAL',
        note: disp.screen_part_status === 'REPLACED' ? 'The phone reports the screen was replaced'
          : disp.screen_part_status === 'ORIGINAL' ? 'The phone recognises the original screen' : '',
        clues: cluesFor('display'), tests: ['screen'] },
      { id: 'touch', icon: 'touch', name: 'Touch digitizer', present: Boolean(touch),
        identity: join(touch?.name, touch?.hardware_id, touch?.max_slots && `${touch.max_slots} points`),
        clues: cluesFor('touch'), tests: ['touch', 'multitouch'] },
      ...(stylus ? [{ id: 'pen', icon: 'touch', name: 'Stylus digitizer', identity: stylus.name,
                      clues: [], tests: ['pen'] }] : []),
      { id: 'buttons', icon: 'buttons', name: 'Physical buttons',
        present: list(s.input?.key_devices).length > 0,
        identity: [...new Set(list(s.input?.key_devices).flatMap((d) => list(d.keys))
          .filter((k) => /KEY_(POWER|VOLUME)/.test(k)))].map((k) => k.replace('KEY_', '').toLowerCase()).join(', '),
        clues: [], tests: ['buttons'] },
      { id: 'fingerprint', icon: 'fingerprint', name: 'Fingerprint reader', present: Boolean(fp.present),
        identity: join([fpChip.vendor, fpChip.name].filter(Boolean).join(' '),
                       fp.stats && `${fp.stats.accept} accepted, ${fp.stats.reject} rejected`),
        clues: cluesFor('fingerprint'), tests: [] },
    ] },
    { title: 'Power', rows: [
      { id: 'battery', icon: 'battery', name: 'Battery',
        identity: join(bat.design_capacity_mah && `${Math.round(bat.design_capacity_mah)} mAh design`,
                       bat.health_percent != null && `${Math.round(bat.health_percent)}% health`,
                       bat.cycle_count != null && `${bat.cycle_count} cycles`,
                       bat.manufacturing_date?.iso && `made ${bat.manufacturing_date.iso}`),
        replaced: bat.part_status === 'REPLACED', original: bat.part_status === 'ORIGINAL',
        note: bat.part_status === 'REPLACED' ? 'The phone reports the battery was replaced'
          : bat.part_status === 'ORIGINAL' ? 'The phone recognises the original battery'
          : bat.pairing === 'paired' ? 'Paired to this phone: not taken from another unit'
          : bat.pairing === 'mismatch' ? 'Paired to a different phone: taken from another unit' : '',
        clues: cluesFor('battery'), tests: ['charging', 'battery_capacity'] },
      { id: 'usb', icon: 'usb', name: 'USB-C port',
        identity: join(s.components?.usb_link?.current_label ?? s.components?.usb_link?.current,
                       s.components?.usb_port?.contaminant && `contaminants ${s.components.usb_port.contaminant}`),
        clues: s.components?.usb_port?.contaminant === 'detected' ? ['Liquid or debris detected in the port'] : [],
        tests: ['charging'] },
      { id: 'soc', icon: 'chip', name: 'Processor', identity: join(soc.declared_model || soc.platform,
                                                                   s.cpu?.core_count && `${s.cpu.core_count} cores`,
                                                                   s.components?.gpu),
        clues: [], tests: ['stress'] },
      { id: 'storage', icon: 'storage', name: 'Storage', identity: join(stor.nominal_gb && `${stor.nominal_gb} GB`, stor.type),
        clues: [], tests: ['storage_speed'] },
    ] },
    { title: 'Cameras', rows: cams.map((c, i) => {
      const part = camParts[i] ?? {};
      return {
        id: `camera-${c.id}`, icon: 'eye', name: `Camera ${c.id} (${c.facing ?? '?'})`,
        identity: join(c.megapixels && `${c.megapixels} MP`, part.sensor, c.has_flash && 'flash'),
        clues: part.firmware_matches === false ? ['The driver reports a firmware mismatch for this module'] : [],
        tests: ['camera', ...(c.has_flash ? ['torch'] : [])],
      };
    }) },
    { title: 'Audio and haptics', rows: [
      { id: 'speaker', icon: 'speaker', name: 'Loudspeaker', present: audio.has_speaker ?? null,
        identity: list(audio.output_devices).filter((d) => /SPEAKER|EARPIECE/.test(d)).join(', ').toLowerCase(),
        clues: [], tests: ['speaker', 'audio'] },
      { id: 'mic', icon: 'speaker', name: 'Microphones',
        identity: audio.builtin_mics ? `${audio.builtin_mics} built in` : '',
        note: s.components?.privacy?.microphone_blocked ? 'Blocked by the privacy switch: tests will record silence' : '',
        clues: [], tests: ['microphone'] },
      { id: 'vibration', icon: 'vibrate', name: 'Vibration motor', present: Boolean(vib.present),
        identity: vib.supports_effects ? 'haptic effects' : '', clues: [], tests: ['vibration_imu', 'vibration'] },
    ] },
    { title: 'Sensors', rows: SENSORS.filter(([type]) => list(byType[type]).length).map(([type, name, tests]) => {
      const first = byType[type].find((x) => x.vendor && !/^AOSP$/i.test(x.vendor)) ?? byType[type][0] ?? {};
      return { id: `sensor-${type}`, icon: 'compass', name,
               identity: join(first.vendor, first.name), clues: [], tests };
    }) },
    { title: 'Radios', rows: [
      { id: 'wifi', icon: 'wifi', name: 'Wi-Fi', identity: list(s.wifi?.bands_supported).join(', '),
        clues: [], tests: ['wifi_scan'] },
      { id: 'bluetooth', icon: 'wifi', name: 'Bluetooth', present: conn.bluetooth?.present ?? null,
        identity: conn.bluetooth?.version ? `version ${conn.bluetooth.version}` : '', clues: [], tests: ['bluetooth'] },
      { id: 'cellular', icon: 'phone', name: 'Mobile modem', present: list(tel.features).length ? true : null,
        identity: join(tel.baseband?.split(',')[0], tel.sim_count && `${tel.sim_count} SIM slots`),
        clues: [], tests: ['cellular'] },
      { id: 'gnss', icon: 'compass', name: 'Satellite positioning', present: conn.location?.gnss_hardware ?? null,
        identity: '', clues: [], tests: ['gnss'] },
      { id: 'nfc', icon: 'wifi', name: 'NFC', present: conn.nfc?.present ?? null, identity: '', clues: [], tests: [] },
    ] },
  ];

  for (const g of groups) {
    for (const row of g.rows) row.status = statusOf(row, results);
  }
  return groups.filter((g) => g.rows.length);
}

/** What software cannot see: looked at by hand, ticked when something is wrong. */
export const INSPECTION = [
  ['water', 'Water contact indicator', 'Red or pink instead of white. On most phones it sits in the SIM tray slot.'],
  ['frame', 'Glue, gaps or lifted glass along the frame', 'Uneven gaps, glue residue, or the screen or back lifting at a corner.'],
  ['back', 'Back cover', 'Creaks when pressed, sits unevenly, or a colour slightly different from the frame.'],
  ['screws', 'Screws and clips', 'Scratched or stripped screw heads, prised marks on the frame edge.'],
  ['screen', 'Screen look', 'Yellow or green tint, uneven brightness, a halo around the camera hole, colours shifting at an angle.'],
  ['camera', 'Camera glass', 'Dust or haze inside the lens, a lens ring not flush with the back.'],
  ['ports', 'Ports and grilles', 'Green or white corrosion in the USB port, speaker or microphone holes.'],
  ['labels', 'Markings', 'Model and IMEI printed on the SIM tray or box differ from the report.'],
];

/**
 * The codes components report about themselves, for matching against spare
 * parts: panel and touch controller names, sensor chips, camera modules,
 * battery and storage part numbers.
 */
export function componentCodes(s) {
  if (!s) return [];
  const rows = [];
  const add = (part, code) => { if (code !== null && code !== undefined && String(code).trim()) rows.push([part, String(code).trim()]); };
  const disp = s.display ?? {};
  const panel = s.components?.panel ?? {};
  add('Display panel', join(disp.product_info?.name, disp.product_info?.manufacturerPnpId
                              && `vendor ${disp.product_info.manufacturerPnpId}`));
  for (const [key, label] of [['lcd_type', 'Panel type code'], ['SVC_OCTA', 'Panel service code'],
                              ['window_type', 'Panel window type'], ['manufacture_date', 'Panel made'],
                              ['cell_id', 'Panel cell ID'], ['octa_id', 'Panel OCTA ID']]) add(label, panel[key]);
  // The bootloader picks the panel driver by the ID it reads from the display
  // chip (Pixel: ro.boot.primary_panel_drv = panel-google-<name>.<id>).
  for (const [key, value] of Object.entries(s.system?.props ?? {})) {
    if (/^ro\.boot\.[\w.]*(panel|lcd|lcm)/i.test(key)) add(`Panel (${key.replace(/^ro\.boot\./, '')})`, value);
  }
  const touch = s.input?.touchscreen;
  add('Touch controller', join(touch?.name, touch?.hardware_id && `ID ${touch.hardware_id}`));
  add('Touch firmware', s.components?.touch?.fw_version);
  if (s.input?.stylus) add('Stylus digitizer', s.input.stylus.name);
  const fpChip = s.components?.fingerprint ?? {};
  add('Fingerprint sensor', [fpChip.vendor, fpChip.name].filter(Boolean).join(' '));
  const camParts = list(s.components?.cameras);
  if (camParts.length) {
    for (const c of camParts) {
      add(`Camera ${c.position ?? ''}`.trim(), join(c.sensor, c.module_id && `module ${c.module_id}`,
                                                    c.firmware && c.firmware !== c.sensor && `firmware ${c.firmware}`));
    }
  } else {
    for (const c of list(s.cameras?.cameras)) {
      add(`Camera ${c.id} (${c.facing ?? '?'})`, c.pixel_array && `${c.pixel_array.width}x${c.pixel_array.height} sensor`);
    }
  }
  const byType = s.sensors?.by_type ?? {};
  for (const [type, name] of SENSORS) {
    const chip = list(byType[type]).find((x) => x.vendor && !/^AOSP$/i.test(x.vendor));
    if (chip) add(name, `${chip.vendor} ${chip.name}`);
  }
  const bat = s.battery ?? {};
  add('Battery part number', bat.part_number);
  add('Battery serial', bat.serial_number);
  add('Battery made', bat.manufacturing_date?.iso);
  for (const d of list(s.storage?.devices)) add('Storage chip', join(d.vendor, d.model, d.rev && `rev ${d.rev}`));
  const ufs = s.storage?.ufs_strings ?? {};
  add('Storage chip', join(ufs.manufacturer_name, ufs.product_name, ufs.product_revision));
  const emmc = s.storage?.emmc ?? {};
  add('Storage chip', join(emmc.name, emmc.manfid && `manufacturer ${emmc.manfid}`,
                           emmc.fwrev && `firmware ${emmc.fwrev}`, emmc.date && `made ${emmc.date}`));
  const soc = s.system?.soc ?? {};
  const socRegs = s.components?.soc ?? {};
  add('Processor', join(soc.declared_model, soc.platform, socRegs.soc_id && `id ${socRegs.soc_id}`,
                        socRegs.revision && `rev ${socRegs.revision}`));
  add('GPU', s.components?.gpu);
  add('Modem firmware', (s.telephony?.baseband ?? '').split(',')[0]);
  // Drivers that name a chip. One system image often carries the drivers of a
  // whole device family, so these say what the firmware supports, not what is
  // fitted.
  const chips = list(s.components?.kernel_modules).filter((m) => CHIP_DRIVER.test(m));
  if (chips.length) add('Chip drivers loaded', chips.join(', '));
  add('Board revision', s.provenance?.board_revision);
  return rows.filter(([, v], i, all) => all.findIndex(([, w]) => w === v) === i);
}

/** Market and origin codes, as rows. */
export function originRows(s) {
  const p = s?.provenance ?? {};
  return [
    ['Built for', p.market && `${p.market} (from the ${p.market_source})`],
    ['Hardware model number', p.hardware_model],
    ['Samsung sales code', p.sales_code],
    ['Firmware region', p.firmware_region],
    ['Warranty region code', p.warranty_region],
    ['Board revision', p.board_revision],
    ['SIM country', list(p.sim_countries).join(', ')],
    ['Network country', list(p.network_countries).join(', ')],
    ['Language and time zone', join(p.language, p.time_zone)],
  ].filter(([, v]) => v);
}
