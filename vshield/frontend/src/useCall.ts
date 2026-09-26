import { useCallback, useEffect, useRef, useState } from "react";
import { AudioEngine } from "./audio";
import type { ChallengeMsg, ChallengeResultMsg, ChallengeVerdictMsg, ScoreMsg, ServerMsg, TranscriptMsg } from "./types";

export type CallStatus = "idle" | "connecting" | "live" | "ending" | "ended" | "error";

export interface StartOptions {
  /** analyse this stream instead of mic/clips (two-person calls: the other person's audio) */
  stream?: MediaStream;
  room?: string;
  target?: string;
}

export interface ChallengeState extends ChallengeMsg {
  result?: ChallengeResultMsg;
  verdict?: ChallengeVerdictMsg;
}

export interface CallState {
  status: CallStatus;
  error: string | null;
  session: string | null;
  enrolled: string | null;
  caller: string | null;
  scores: ScoreMsg[];
  latest: ScoreMsg | null;
  transcripts: TranscriptMsg[];
  challenges: ChallengeState[];
  level: number;
  streamT: number;
}

const initial: CallState = {
  status: "idle",
  error: null,
  session: null,
  enrolled: null,
  caller: null,
  scores: [],
  latest: null,
  transcripts: [],
  challenges: [],
  level: 0,
  streamT: 0,
};

const wsUrl = (path: string) => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;

export function useCall() {
  const [state, setState] = useState<CallState>(initial);
  const ws = useRef<WebSocket | null>(null);
  const engine = useRef<AudioEngine | null>(null);
  const samples = useRef(0);
  const recorder = useRef<{ chunks: ArrayBuffer[]; left: number; done: (c: ArrayBuffer[]) => void } | null>(null);

  const teardown = useCallback(async () => {
    const e = engine.current;
    engine.current = null;
    await e?.close().catch(() => {});
  }, []);

  const onMessage = useCallback(
    (msg: ServerMsg) => {
      setState((s) => {
        switch (msg.type) {
          case "ready":
            return { ...s, status: "live", session: msg.session, enrolled: msg.enrolled, caller: msg.caller };
          case "score":
            return { ...s, latest: msg, scores: [...s.scores, msg] };
          case "transcript":
            return { ...s, transcripts: [...s.transcripts, msg] };
          case "challenge":
            return { ...s, challenges: [...s.challenges, msg] };
          case "challenge_result":
          case "challenge_verdict": {
            const challenges = s.challenges.slice();
            const last = challenges[challenges.length - 1];
            if (last)
              challenges[challenges.length - 1] =
                msg.type === "challenge_result" ? { ...last, result: msg } : { ...last, verdict: msg };
            return { ...s, challenges };
          }
          case "ended":
            return { ...s, status: "ended" };
          case "error":
            return { ...s, status: "error", error: msg.message };
        }
      });
      if (msg.type === "ended" || msg.type === "error") {
        ws.current?.close();
        void teardown();
      }
    },
    [teardown],
  );

  const start = useCallback(
    async (callerId: string, enrollment: string, opts: StartOptions = {}) => {
      setState({ ...initial, status: "connecting" });
      samples.current = 0;
      try {
        // AudioContext must be created from the click handler (autoplay policy)
        const eng = await AudioEngine.create((pcm, rms) => {
          const sock = ws.current;
          if (sock?.readyState === WebSocket.OPEN) {
            sock.send(pcm);
            samples.current += pcm.byteLength / 2;
          }
          const rec = recorder.current;
          if (rec) {
            rec.chunks.push(pcm.slice(0));
            rec.left -= pcm.byteLength / 2;
            if (rec.left <= 0) {
              recorder.current = null;
              rec.done(rec.chunks);
            }
          }
          setState((s) => ({ ...s, level: rms, streamT: samples.current / 16000 }));
        });
        engine.current = eng;
        if (opts.stream) eng.attachStream(opts.stream);
        const q = new URLSearchParams({ caller_id: callerId, enrollment, room: opts.room ?? "", target: opts.target ?? "" });
        const sock = new WebSocket(wsUrl(`/ws/call?${q}`));
        sock.binaryType = "arraybuffer";
        sock.onmessage = (e) => onMessage(JSON.parse(e.data));
        sock.onerror = () => setState((s) => ({ ...s, status: "error", error: "Connection to the V-Shield server failed" }));
        sock.onclose = () =>
          setState((s) => (s.status === "live" || s.status === "ending" ? { ...s, status: "ended" } : s));
        ws.current = sock;
      } catch (err) {
        await teardown();
        setState((s) => ({ ...s, status: "error", error: (err as Error).message }));
      }
    },
    [onMessage, teardown],
  );

  const stop = useCallback(() => {
    engine.current?.stopClip();
    engine.current?.stopMic();
    const sock = ws.current;
    if (sock?.readyState === WebSocket.OPEN) {
      sock.send(JSON.stringify({ type: "stop" }));
      setState((s) => ({ ...s, status: "ending" }));
    } else {
      void teardown();
      setState((s) => ({ ...s, status: "ended" }));
    }
  }, [teardown]);

  const challenge = useCallback(() => {
    ws.current?.send(JSON.stringify({ type: "challenge" }));
  }, []);

  useEffect(
    () => () => {
      ws.current?.close();
      void teardown();
    },
    [teardown],
  );

  /** Capture the next `seconds` of the analysed audio (e.g. to enroll a caller's voice). */
  const record = useCallback(
    (seconds: number) =>
      new Promise<ArrayBuffer[]>((done) => {
        recorder.current = { chunks: [], left: seconds * 16000, done };
      }),
    [],
  );

  return { state, start, stop, challenge, record, engine };
}
