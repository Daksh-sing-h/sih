export type Band = "low" | "medium" | "high" | "critical";
export type SignalKey = "A" | "S" | "B" | "C";

export interface Span {
  start: number;
  end: number;
  kind: string;
}

export interface ScoreMsg {
  type: "score";
  t: number;
  speech: boolean;
  reason: "audio" | "context" | "challenge" | "final";
  R: number;
  band: Band;
  action: string;
  contributions: Partial<Record<SignalKey | "rules", number>>;
  rules: string[];
  signals: Record<SignalKey, number | null>;
  details: {
    A?: { mean_p: number; threshold: number; p_window: number; mode: string };
    S?: { S: number | null; cos: number | null };
    B?: { b_voice?: number | null; b_latency?: number | null; z?: Record<string, number> };
    C?: { C: number; terms: Record<string, number>; stages: string[]; max_amount_inr: number; caller: string | null };
  };
  proc_ms: number | null;
  proc_ms_p95: number | null;
  skipped: number;
  enrolled: string | null;
}

export interface TranscriptMsg {
  type: "transcript";
  t0: number;
  t1: number;
  text: string;
  lang: string | null;
  spans: Span[];
  asr_ms: number;
}

export interface ChallengeMsg {
  type: "challenge";
  phrase: string;
  issued_at: number;
  pushed?: boolean;
}

export interface ChallengeResultMsg {
  type: "challenge_result";
  latency_s: number;
  slow: boolean;
}

export interface ChallengeVerdictMsg {
  type: "challenge_verdict";
  matched: boolean;
  match: number;
  heard: string;
}

export interface ReadyMsg {
  type: "ready";
  session: string;
  enrolled: string | null;
  caller: string | null;
}

export type ServerMsg =
  | ScoreMsg
  | TranscriptMsg
  | ChallengeMsg
  | ChallengeResultMsg
  | ChallengeVerdictMsg
  | ReadyMsg
  | { type: "ended"; session: string }
  | { type: "error"; message: string };

export interface Caller {
  id: string;
  name: string;
  registered: boolean;
}

export interface Enrollment {
  id: string;
  name: string;
  created: string;
  windows: number;
}

export interface AppConfig {
  callers: Caller[];
  enrollments: Enrollment[];
  weights: Record<SignalKey, number>;
}

export interface DemoClip {
  file: string;
  label: string;
  kind: "genuine" | "synthetic" | "reply";
  note?: string;
}

export interface PeerProfile {
  id: string;
  name: string;
  caller_id: string;
}

/** True once there is real evidence: a scored speech window or something they *said*.
 *  (An unknown caller ID alone is not enough to show a verdict.) */
export function hasEvidence(m: ScoreMsg | null): m is ScoreMsg {
  if (!m) return false;
  const { A, S, B } = m.signals;
  const said = Object.keys(m.details.C?.terms ?? {}).some((t) => t !== "unknown_caller");
  return A !== null || S !== null || B !== null || said;
}
