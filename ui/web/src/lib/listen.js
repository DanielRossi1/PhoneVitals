/**
 * Hearing the phone's loudspeaker through the computer's microphone.
 *
 * The phone plays known tones; this measures, for each of those frequencies,
 * how far the spectrum rises above its immediate surroundings. The same
 * measure is taken before the first tone, so a frequency that was already
 * loud in the room (a fan, mains hum harmonics) does not count as heard.
 *
 * Timing is deliberately not trusted: between the phone announcing a tone
 * and its sound leaving the speaker sit adb, the audio buffer and the room.
 * Each frequency is judged on its best sustained moment over the whole run,
 * which is only high when that tone actually played.
 */

const FRAME_MS = 40;
const SMOOTH = 5;           // frames: ~200 ms must stay above the background
const HEARD_DB = 10;        // margin over the pre-tone background

export async function startListening(tones) {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('no microphone access in this environment');
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
  });
  const ctx = new AudioContext();
  // Created outside a click handler, the context may start suspended; a
  // suspended graph delivers no samples and every frequency reads flat.
  await ctx.resume();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 8192;
  analyser.smoothingTimeConstant = 0;
  ctx.createMediaStreamSource(stream).connect(analyser);

  const spectrum = new Float32Array(analyser.frequencyBinCount);
  const hzPerBin = ctx.sampleRate / analyser.fftSize;
  const bin = (hz) => Math.round(hz / hzPerBin);
  let phase = 'baseline';
  const series = { baseline: Object.fromEntries(tones.map((t) => [t, []])),
                   playing: Object.fromEntries(tones.map((t) => [t, []])) };
  let loudest = -Infinity;
  let frames = 0;
  let changing = false;
  let previous = null;

  function prominence(hz) {
    const c = bin(hz);
    let peak = -Infinity;
    for (let i = c - 3; i <= c + 3; i++) peak = Math.max(peak, spectrum[i]);
    const around = [];
    const near = bin(100), far = bin(400);
    for (let i = c - far; i <= c + far; i++) {
      if (Math.abs(i - c) >= near && i > 0 && i < spectrum.length) around.push(spectrum[i]);
    }
    around.sort((a, b) => a - b);
    return peak - around[Math.floor(around.length / 2)];
  }

  const timer = setInterval(() => {
    analyser.getFloatFrequencyData(spectrum);
    frames++;
    for (const v of spectrum) if (v > loudest && Number.isFinite(v)) loudest = v;
    // A live microphone never yields the same spectrum twice in a row.
    if (previous && !changing && spectrum.some((v, i) => v !== previous[i])) changing = true;
    previous = spectrum.slice(0, 256);
    for (const hz of tones) {
      // Before audio flows the spectrum reads -Infinity everywhere, and
      // -Infinity minus -Infinity is NaN, which would poison every min/max.
      const p = prominence(hz);
      if (Number.isFinite(p)) series[phase][hz].push(p);
    }
  }, FRAME_MS);

  return {
    /** The first tone was announced: what follows is no longer background. */
    tonesStarted() { phase = 'playing'; },

    async stop() {
      clearInterval(timer);
      for (const track of stream.getTracks()) track.stop();
      await ctx.close();
      const sustained = (values) => {
        let best = -Infinity;
        for (let i = 0; i + SMOOTH <= values.length; i++) {
          best = Math.max(best, Math.min(...values.slice(i, i + SMOOTH)));
        }
        return best;
      };
      const results = tones.map((hz) => {
        const before = Math.max(0, sustained(series.baseline[hz]));
        const during = sustained(series.playing[hz]);
        const margin = during - before;
        return { hz, margin: Number.isFinite(margin) ? margin : 0, heard: margin >= HEARD_DB };
      });
      return { results, silentInput: frames < 10 || !changing || loudest < -110 };
    },
  };
}

/** Turn the measurement into the test outcome the backend records. */
export function speakerOutcome({ results, silentInput }) {
  const heard = results.filter((r) => r.heard);
  const list = results.map((r) => `${r.hz} Hz ${r.margin >= 0 ? '+' : ''}${r.margin.toFixed(0)} dB`)
    .join(', ');
  if (silentInput) {
    return { status: 'inconclusive', passed: false,
             detail: 'The computer microphone delivered no signal: it may be muted, in use, '
                     + 'or not allowed (in the snap: snap connect phonevitals:audio-record). '
                     + 'Check by ear with the Speakers and microphone test.' };
  }
  if (heard.length === results.length) {
    return { passed: true, detail: `Heard all ${results.length} tones through the computer's `
                                   + `microphone: ${list} over the background.` };
  }
  if (heard.length) {
    return { passed: true, detail: `Heard ${heard.length} of ${results.length} tones (${list}). `
                                   + 'Missing ones are often a limit of the computer microphone; '
                                   + 'a damaged speaker usually sounds distorted, so also listen.' };
  }
  return { status: 'inconclusive', passed: false,
           detail: `No tone rose above the background (${list}). Either the speaker is silent, `
                   + 'or the phone was too far from the computer or muted: bring it closer, '
                   + 'repeat, and check by ear.' };
}

/**
 * Play tones on the computer's speakers for the phone's microphone test:
 * after `delayMs`, each tone for `ms` with `gapMs` of silence in between.
 */
export async function playTones(tones, { ms = 900, gapMs = 350, delayMs = 900 } = {}) {
  const ctx = new AudioContext();
  await ctx.resume();
  let at = ctx.currentTime + delayMs / 1000;
  for (const hz of tones) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = hz;
    // Short ramps: a hard start or stop is a click, broadband energy that
    // would show up at every frequency.
    gain.gain.setValueAtTime(0, at);
    gain.gain.linearRampToValueAtTime(0.5, at + 0.02);
    gain.gain.setValueAtTime(0.5, at + ms / 1000 - 0.02);
    gain.gain.linearRampToValueAtTime(0, at + ms / 1000);
    osc.connect(gain).connect(ctx.destination);
    osc.start(at);
    osc.stop(at + ms / 1000);
    at += (ms + gapMs) / 1000;
  }
  setTimeout(() => ctx.close(), (at - ctx.currentTime) * 1000 + 500);
}
