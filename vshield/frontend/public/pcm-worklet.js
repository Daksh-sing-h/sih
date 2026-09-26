// Runs on the audio thread. Collects mono samples at the AudioContext rate
// (the app creates a 16 kHz context, so no resampling is needed here), and
// posts 100 ms chunks of little-endian int16 PCM plus an RMS level.
// It keeps emitting when nothing is playing (silence), because a real call is
// a continuous stream and challenge-response timing depends on it.
class PcmSender extends AudioWorkletProcessor {
  constructor() {
    super();
    this.chunk = Math.round(sampleRate / 10);
    this.buf = new Float32Array(this.chunk);
    this.n = 0;
  }

  process(inputs) {
    const input = inputs[0];
    const frames = input && input.length ? input[0].length : 128;
    for (let i = 0; i < frames; i++) {
      let s = 0;
      if (input && input.length) {
        for (let c = 0; c < input.length; c++) s += input[c][i];
        s /= input.length;
      }
      this.buf[this.n++] = s;
      if (this.n === this.chunk) this.flush();
    }
    return true;
  }

  flush() {
    const pcm = new Int16Array(this.chunk);
    let sq = 0;
    for (let i = 0; i < this.chunk; i++) {
      const v = Math.max(-1, Math.min(1, this.buf[i]));
      pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
      sq += v * v;
    }
    this.port.postMessage({ pcm: pcm.buffer, rms: Math.sqrt(sq / this.chunk) }, [pcm.buffer]);
    this.n = 0;
  }
}

registerProcessor("pcm-sender", PcmSender);
