// Browser audio → one continuous 16 kHz mono stream, fed by the mic and/or clips.

export const SAMPLE_RATE = 16000;

type ChunkHandler = (pcm: ArrayBuffer, rms: number) => void;

export class AudioEngine {
  private micStream: MediaStream | null = null;
  private micSource: MediaStreamAudioSourceNode | null = null;
  private clip: AudioBufferSourceNode | null = null;
  private external: MediaStreamAudioSourceNode | null = null;

  private constructor(
    readonly ctx: AudioContext,
    private readonly input: GainNode,
    private readonly node: AudioWorkletNode,
  ) {}

  static async create(onChunk: ChunkHandler): Promise<AudioEngine> {
    // A 16 kHz context makes the browser resample mic input and decoded clips for us.
    const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
    await ctx.audioWorklet.addModule("/pcm-worklet.js");
    const node = new AudioWorkletNode(ctx, "pcm-sender", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCount: 1,
      channelCountMode: "explicit",
      channelInterpretation: "speakers",
    });
    node.port.onmessage = (e) => onChunk(e.data.pcm, e.data.rms);
    const input = ctx.createGain();
    input.connect(node);
    // the worklet only runs while it's pulled by the destination; keep it silent
    const sink = ctx.createGain();
    sink.gain.value = 0;
    node.connect(sink).connect(ctx.destination);
    if (ctx.state === "suspended") await ctx.resume();
    return new AudioEngine(ctx, input, node);
  }

  /** Analyse an existing stream (e.g. the other person's audio in a two-person call). */
  attachStream(stream: MediaStream) {
    this.external?.disconnect();
    this.external = this.ctx.createMediaStreamSource(stream);
    this.external.connect(this.input);
  }

  get micOn() {
    return this.micStream !== null;
  }

  async startMic() {
    if (this.micStream) return;
    // raw audio: browser noise suppression would change what the detector hears
    this.micStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    this.micSource = this.ctx.createMediaStreamSource(this.micStream);
    if (!this.clip) this.micSource.connect(this.input);
  }

  stopMic() {
    this.micSource?.disconnect();
    this.micStream?.getTracks().forEach((t) => t.stop());
    this.micStream = null;
    this.micSource = null;
  }

  /** Play a clip into the call (and through the speakers). Mic is muted while it plays. */
  async play(data: ArrayBuffer, onEnded?: () => void): Promise<number> {
    this.stopClip();
    const buffer = await this.ctx.decodeAudioData(data);
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.input);
    src.connect(this.ctx.destination);
    this.micSource?.disconnect();
    src.onended = () => {
      if (this.clip === src) {
        this.clip = null;
        if (this.micSource) this.micSource.connect(this.input);
      }
      onEnded?.();
    };
    this.clip = src;
    src.start();
    return buffer.duration;
  }

  stopClip() {
    if (this.clip) {
      const c = this.clip;
      this.clip = null;
      c.stop();
      c.disconnect();
      if (this.micSource) this.micSource.connect(this.input);
    }
  }

  async close() {
    this.stopClip();
    this.stopMic();
    this.external?.disconnect();
    this.node.port.onmessage = null;
    await this.ctx.close();
  }
}

/** 16-bit mono WAV from int16 chunks (used to upload enrollment recordings). */
export function encodeWav(chunks: ArrayBuffer[], sampleRate = SAMPLE_RATE): Blob {
  const dataLen = chunks.reduce((n, c) => n + c.byteLength, 0);
  const header = new DataView(new ArrayBuffer(44));
  const str = (o: number, s: string) => [...s].forEach((ch, i) => header.setUint8(o + i, ch.charCodeAt(0)));
  str(0, "RIFF");
  header.setUint32(4, 36 + dataLen, true);
  str(8, "WAVE");
  str(12, "fmt ");
  header.setUint32(16, 16, true);
  header.setUint16(20, 1, true);
  header.setUint16(22, 1, true);
  header.setUint32(24, sampleRate, true);
  header.setUint32(28, sampleRate * 2, true);
  header.setUint16(32, 2, true);
  header.setUint16(34, 16, true);
  str(36, "data");
  header.setUint32(40, dataLen, true);
  return new Blob([header.buffer, ...chunks], { type: "audio/wav" });
}

/**
 * What *you* send into a two-person call: your mic, or (for the demo) a clip,
 * the way an attacker feeds a cloned voice in. Works without a mic too.
 */
export class OutgoingAudio {
  private clip: AudioBufferSourceNode | null = null;
  private muted = false;

  private constructor(
    readonly ctx: AudioContext,
    readonly dest: MediaStreamAudioDestinationNode,
    private readonly micGain: GainNode,
    private readonly analyser: AnalyserNode,
    private readonly micStream: MediaStream | null,
    readonly micError: string | null,
  ) {}

  static async create(): Promise<OutgoingAudio> {
    const ctx = new AudioContext();
    const dest = ctx.createMediaStreamDestination();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    analyser.connect(dest);
    const micGain = ctx.createGain();
    micGain.connect(analyser);
    let micStream: MediaStream | null = null;
    let micError: string | null = null;
    try {
      // a real call needs echo cancellation (people use speakers)
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      ctx.createMediaStreamSource(micStream).connect(micGain);
    } catch (e) {
      micError = (e as Error).message || "microphone unavailable";
    }
    if (ctx.state === "suspended") await ctx.resume();
    return new OutgoingAudio(ctx, dest, micGain, analyser, micStream, micError);
  }

  get stream() {
    return this.dest.stream;
  }

  get hasMic() {
    return this.micStream !== null;
  }

  setMuted(m: boolean) {
    this.muted = m;
    this.micGain.gain.value = m || this.clip ? 0 : 1;
  }

  level(): number {
    const buf = new Float32Array(this.analyser.fftSize);
    this.analyser.getFloatTimeDomainData(buf);
    let sq = 0;
    for (const v of buf) sq += v * v;
    return Math.sqrt(sq / buf.length);
  }

  /** Send a clip into the call instead of your mic (mic is muted while it plays). */
  async playClip(data: ArrayBuffer, onEnded?: () => void) {
    this.stopClip();
    const buffer = await this.ctx.decodeAudioData(data);
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.analyser);
    this.clip = src;
    this.micGain.gain.value = 0;
    src.onended = () => {
      if (this.clip === src) {
        this.clip = null;
        this.micGain.gain.value = this.muted ? 0 : 1;
      }
      onEnded?.();
    };
    src.start();
  }

  stopClip() {
    const c = this.clip;
    this.clip = null;
    c?.stop();
    c?.disconnect();
    this.micGain.gain.value = this.muted ? 0 : 1;
  }

  async close() {
    this.stopClip();
    this.micStream?.getTracks().forEach((t) => t.stop());
    await this.ctx.close();
  }
}
