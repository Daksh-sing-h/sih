import { useEffect, useRef, useState } from "react";
import type { ScoreMsg, TranscriptMsg } from "../types";
import type { ChallengeState } from "../useCall";

const H = 150;
const PAD = { l: 34, r: 12, t: 10, b: 22 };
const STRIPES: [number, number, string][] = [
  [0, 30, "low"],
  [30, 60, "medium"],
  [60, 80, "high"],
  [80, 100, "critical"],
];

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(800);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export function Timeline({
  scores,
  transcripts,
  challenges,
  now,
}: {
  scores: ScoreMsg[];
  transcripts: TranscriptMsg[];
  challenges: ChallengeState[];
  now: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const tMax = Math.max(30, now, scores.at(-1)?.t ?? 0);
  const iw = Math.max(10, width - PAD.l - PAD.r);
  const ih = H - PAD.t - PAD.b;
  const x = (t: number) => PAD.l + (t / tMax) * iw;
  const y = (r: number) => PAD.t + (1 - r / 100) * ih;
  const pts = scores.map((s) => `${x(s.t).toFixed(1)},${y(s.R).toFixed(1)}`).join(" ");
  const step = tMax > 120 ? 30 : tMax > 60 ? 15 : 5;

  return (
    <div className="timeline" ref={ref}>
      <svg width={width} height={H} role="img" aria-label="Risk score over the call">
        {STRIPES.map(([a, b, name]) => (
          <rect key={name} x={PAD.l} width={iw} y={y(b)} height={y(a) - y(b)} className={`stripe band-${name}`} />
        ))}
        {[0, 30, 60, 80, 100].map((r) => (
          <text key={r} x={PAD.l - 6} y={y(r)} className="axis" textAnchor="end" dominantBaseline="middle">
            {r}
          </text>
        ))}
        {Array.from({ length: Math.floor(tMax / step) + 1 }, (_, i) => i * step).map((t) => (
          <text key={t} x={x(t)} y={H - 6} className="axis" textAnchor="middle">
            {t}s
          </text>
        ))}
        {transcripts.map((tr, i) => (
          <rect key={i} x={x(tr.t0)} width={Math.max(2, x(tr.t1) - x(tr.t0))} y={PAD.t + ih - 4} height={4}
                className={tr.spans.length ? "utt risky" : "utt"}>
            <title>{tr.text}</title>
          </rect>
        ))}
        {challenges.map((c, i) => (
          <g key={i} className="challenge-mark">
            <line x1={x(c.issued_at)} x2={x(c.issued_at)} y1={PAD.t} y2={PAD.t + ih} />
            <text x={x(c.issued_at) + 4} y={PAD.t + 10}>challenge</text>
          </g>
        ))}
        {scores.length > 1 && <polyline points={pts} className="risk-line" />}
        {scores.length > 0 && (
          <circle cx={x(scores.at(-1)!.t)} cy={y(scores.at(-1)!.R)} r={4} className={`risk-dot band-${scores.at(-1)!.band}`} />
        )}
      </svg>
    </div>
  );
}
