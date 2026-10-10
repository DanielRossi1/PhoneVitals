/** Presentation of the functional tests: icons and the operator's script. */

export const TEST_ICONS = {
  sensor_physics: 'compass',
  vibration_imu: 'vibrate',
  wifi_scan: 'wifi',
  storage_speed: 'storage',
  charging: 'battery',
  battery_capacity: 'battery',
  stress: 'chip',
  speaker: 'speaker',
  microphone: 'speaker',
  bluetooth: 'wifi',
  cellular: 'phone',
  gnss: 'compass',
  camera: 'eye',
  vibration: 'vibrate',
  buttons: 'buttons',
  touch: 'touch',
  multitouch: 'touch',
  pen: 'touch',
  screen: 'eye',
  imu: 'live',
  proximity: 'phone',
  light: 'sun',
  magnetometer: 'compass',
  audio: 'speaker',
  torch: 'flash',
};

export const STATUS = {
  passed: { label: 'Passed', tone: 'ok', icon: 'ok' },
  failed: { label: 'Failed', tone: 'crit', icon: 'error' },
  running: { label: 'Running', tone: 'info', icon: 'clock' },
  inconclusive: { label: 'Inconclusive', tone: 'warn', icon: 'alert' },
  skipped: { label: 'Skipped', tone: 'none', icon: 'right' },
};

/** What to ask the operator during a guided test. `sensors` lists the
 * readings shown live inside the dialog. */
export const FLOWS = {
  vibration: {
    instruction: 'Hold the phone in your hand. The motor runs at several strengths and '
      + 'durations: confirm whether you felt every pulse.',
  },
  torch: {
    instruction: 'Look at the back of the phone: the flash lights up for a moment. '
      + 'Confirm whether it did.',
  },
  buttons: {
    instruction: 'Press each physical button once. The raw kernel events are read for '
      + 'fifteen seconds and ticked off below as they arrive.',
  },
  screen: {
    instruction: 'Pick a colour to show it full screen on the phone, then inspect the panel '
      + 'closely and from different angles for dead pixels, tint or banding. Mid grey shows '
      + 'burn-in best.',
  },
  touch: {
    instruction: 'Run a finger over the whole screen, edges included, as if colouring it in. '
      + 'Cells that stay empty in the map do not respond to touch.',
    touch: true,
  },
  pen: {
    instruction: 'Write over the whole screen with the stylus, lightly and then firmly, and '
      + 'press its side button. The line must follow the tip without gaps and grow wider '
      + 'with pressure; hovering just above the glass shows a ring.',
    pen: true,
  },
  multitouch: {
    instruction: 'Place two fingers on the screen, then three, four and five. The counter '
      + 'must follow the number of fingers.',
    touch: true,
  },
  imu: {
    instruction: 'Lift the phone, rotate it slowly about all three axes, then shake it. '
      + 'Every axis must move: one that stays at zero does not respond.',
    sensors: [1, 4],
  },
  proximity: {
    instruction: 'Cover the top of the screen, above the earpiece, then uncover it. '
      + 'The distance must drop when covered and rise again.',
    sensors: [8],
  },
  light: {
    instruction: 'Cover the top of the screen and uncover it, ideally facing a light. '
      + 'The lux reading must follow.',
    sensors: [5],
  },
  magnetometer: {
    instruction: 'Hold the phone flat and turn it slowly through a full circle. The values '
      + 'must change smoothly. Metal objects and magnets nearby distort the reading.',
    sensors: [2],
  },
  camera: {
    instruction: 'Every camera took a picture. Look at each: it must be sharp where '
      + 'something is in focus, with no spots, haze, cracks or colour cast. A black '
      + 'picture usually means the lens was covered.',
  },
  audio: {
    instruction: 'Manual check: play some audio on the phone and listen to every speaker, '
      + 'then record a voice memo and play it back.',
  },
};

export const SENSOR_INFO = {
  1: ['Accelerometer', 'm/s²'],
  2: ['Magnetometer', 'µT'],
  4: ['Gyroscope', 'rad/s'],
  5: ['Light', 'lux'],
  8: ['Proximity', 'cm'],
};

export const SCREEN_PATTERNS = {
  white: '#fff', black: '#000', red: '#f00', green: '#0f0', blue: '#00f', grey: '#808080',
  gradient: 'linear-gradient(#000,#fff)',
};

export const KEYS = [
  ['KEY_VOLUMEUP', 'Volume up'],
  ['KEY_VOLUMEDOWN', 'Volume down'],
  ['KEY_POWER', 'Power'],
];
