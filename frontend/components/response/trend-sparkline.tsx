"use client";

/**
 * Time-to-freeze trend sparkline — hand-rolled SVG ported from the mockup's
 * #trendsvg renderer: faint gridlines, accent gradient area fill, 2px line,
 * glowing end dot + latest-value label.
 */

import type { ReactElement } from "react";
import { useTranslations } from "next-intl";

const W = 640;
const H = 180;
const PAD = 8;

export function TrendSparkline({
  data,
  nowLabel,
}: {
  /** Minutes per case/period, oldest → newest. */
  data: number[];
  /** Label at the last point, e.g. "27 min". */
  nowLabel: string;
}) {
  const t = useTranslations("response.trendSparkline");
  if (data.length < 2) {
    return (
      <div className="grid h-[180px] place-items-center text-[12px] text-muted">
        {t("empty")}
      </div>
    );
  }

  const max = Math.max(...data);
  const pts: Array<[number, number]> = data.map((v, i) => [
    PAD + (i * (W - 2 * PAD)) / (data.length - 1),
    H - PAD - (max > 0 ? (v / max) * (H - 2 * PAD) : 0),
  ]);
  const line = pts
    .map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");
  const last = pts[pts.length - 1];
  const area = `${line} L${last[0].toFixed(1)},${H - PAD} L${pts[0][0].toFixed(1)},${H - PAD} Z`;

  const gridlines: ReactElement[] = [45, 90, 135].map((y) => (
    <line
      key={y}
      x1={PAD}
      x2={W - PAD}
      y1={y}
      y2={y}
      stroke="rgba(255,255,255,.04)"
    />
  ));

  return (
    <svg
      width="100%"
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={t("ariaLabel", { nowLabel })}
    >
      <defs>
        <linearGradient id="ttf-area" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#0099ff" stopOpacity=".28" />
          <stop offset="1" stopColor="#0099ff" stopOpacity="0" />
        </linearGradient>
      </defs>
      {gridlines}
      <path d={area} fill="url(#ttf-area)" />
      <path
        d={line}
        fill="none"
        stroke="#0099ff"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <circle
        cx={last[0]}
        cy={last[1]}
        r="4"
        fill="#0099ff"
        style={{ filter: "drop-shadow(0 0 6px #0099ff)" }}
      />
      <text
        x={last[0] - 6}
        y={last[1] - 10}
        textAnchor="end"
        fill="#0099ff"
        fontSize="11"
        fontWeight="700"
        fontFamily="var(--font-mono)"
      >
        {nowLabel}
      </text>
    </svg>
  );
}
