import type { Band } from "../types";

const BANDS: [number, number, Band][] = [
  [0, 30, "low"],
  [30, 60, "medium"],
  [60, 80, "high"],
  [80, 100, "critical"],
];

const CX = 130;
const CY = 128;
const R = 104;

function point(v: number, r = R) {
  const a = Math.PI * (1 - v / 100);
  return [CX + r * Math.cos(a), CY - r * Math.sin(a)];
}

function arc(v0: number, v1: number) {
  const [x0, y0] = point(v0);
  const [x1, y1] = point(v1);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${R} ${R} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

export function Gauge({ value, band, live }: { value: number | null; band: Band | null; live: boolean }) {
  const v = Math.max(0, Math.min(100, value ?? 0));
  const [dx, dy] = point(v);
  return (
    <div className={`gauge ${band ?? "none"}`}>
      <svg viewBox="0 0 260 150" role="img" aria-label={`Risk ${value ?? "not scored"} of 100`}>
        {BANDS.map(([a, b, name]) => (
          <path key={name} d={arc(a + 0.6, b - 0.6)} className={`track band-${name}`} />
        ))}
        {value !== null && v > 0.8 && <path d={arc(0.6, Math.max(0.8, v - 0.2))} className={`fill band-${band}`} />}
        {value !== null && <circle cx={dx} cy={dy} r={10} className={`marker band-${band}`} />}
        {[0, 30, 60, 80, 100].map((t) => {
          const [x, y] = point(t, R + 17);
          return (
            <text key={t} x={x} y={y} className="tick" textAnchor="middle" dominantBaseline="middle">
              {t}
            </text>
          );
        })}
      </svg>
      <div className="gauge-readout">
        <span className="gauge-value">{value === null ? "–" : Math.round(v)}</span>
        <span className="gauge-band">{band ? band.toUpperCase() : live ? "LISTENING…" : "NO CALL"}</span>
      </div>
    </div>
  );
}
