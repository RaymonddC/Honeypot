"use client";

/**
 * Bridge View Sankey — d3-sankey computes the layout, rendered as plain SVG.
 * QRIS merchants → mule accounts → exchange deposits → USDT wallets → foreign,
 * with per-link gradients along the amber (fiat) → cyan/sky/blue (crypto)
 * ramp, mockup-faithful (760×430, 14px nodes, sparse stage labels).
 */

import { useId, useMemo } from "react";
import {
  sankey,
  sankeyJustify,
  sankeyLinkHorizontal,
  type SankeyLink,
  type SankeyNode,
} from "d3-sankey";
import type {
  BridgeSankeyData,
  BridgeSankeyNode,
} from "@/lib/bridge/types";
import { FOREIGN_COLOR, STAGE_COLORS } from "@/lib/bridge/types";

const W = 760;
const H = 430;

type LinkDatum = { source: string; target: string; value: number };
type LaidNode = SankeyNode<BridgeSankeyNode, LinkDatum>;
type LaidLink = SankeyLink<BridgeSankeyNode, LinkDatum>;

function nodeColor(n: LaidNode): string {
  if (n.color) return n.color;
  if (/foreign/i.test(n.name)) return FOREIGN_COLOR;
  return STAGE_COLORS[Math.min(n.depth ?? 0, STAGE_COLORS.length - 1)];
}

export function SankeyChart({ data }: { data: BridgeSankeyData }) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");

  const layout = useMemo(() => {
    try {
      const generator = sankey<BridgeSankeyNode, LinkDatum>()
        .nodeId((d) => d.id)
        .nodeWidth(14)
        .nodePadding(28)
        .nodeAlign(sankeyJustify)
        .extent([
          [28, 16],
          [W - 28, H - 16],
        ]);
      return generator({
        nodes: data.nodes.map((d) => ({ ...d })),
        links: data.links.map((d) => ({ ...d })),
      });
    } catch {
      return null; // malformed graph (cycle / dangling ref) — render empty
    }
  }, [data]);

  if (!layout) {
    return (
      <div className="grid h-[430px] place-items-center text-[11px] text-muted">
        No bridge flows to render.
      </div>
    );
  }

  const linkPath = sankeyLinkHorizontal<BridgeSankeyNode, LinkDatum>();
  const nodes = layout.nodes as LaidNode[];
  const links = layout.links as LaidLink[];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      className="h-[430px]"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="Fiat-to-crypto fund flow: QRIS merchants through mule accounts and exchange deposits to USDT wallets and foreign destinations"
    >
      <defs>
        {links.map((l, i) => {
          const s = l.source as LaidNode;
          const t = l.target as LaidNode;
          return (
            <linearGradient
              key={i}
              id={`${uid}-g${i}`}
              gradientUnits="userSpaceOnUse"
              x1={s.x1 ?? 0}
              x2={t.x0 ?? 0}
            >
              <stop offset="0" stopColor={nodeColor(s)} stopOpacity={0.5} />
              <stop offset="1" stopColor={nodeColor(t)} stopOpacity={0.5} />
            </linearGradient>
          );
        })}
      </defs>

      {/* links */}
      {links.map((l, i) => (
        <path
          key={i}
          d={linkPath(l) ?? undefined}
          fill="none"
          stroke={`url(#${uid}-g${i})`}
          strokeWidth={Math.max(1, l.width ?? 1)}
          strokeOpacity={0.9}
        >
          <title>
            {`${(l.source as LaidNode).name} → ${(l.target as LaidNode).name} · ${l.value.toLocaleString("en-US")}`}
          </title>
        </path>
      ))}

      {/* nodes */}
      {nodes.map((n) => (
        <g key={n.id}>
          <rect
            x={n.x0}
            y={n.y0}
            width={(n.x1 ?? 0) - (n.x0 ?? 0)}
            height={Math.max(1, (n.y1 ?? 0) - (n.y0 ?? 0))}
            rx={3}
            fill={nodeColor(n)}
          >
            <title>{`${n.name} · ${(n.value ?? 0).toLocaleString("en-US")}`}</title>
          </rect>
          {n.label && (
            <text
              x={(n.x0 ?? 0) > W * 0.78 ? (n.x0 ?? 0) - 8 : (n.x1 ?? 0) + 8}
              y={(n.y0 ?? 0) + 13}
              textAnchor={(n.x0 ?? 0) > W * 0.78 ? "end" : "start"}
              fill="rgba(255,255,255,.62)"
              fontSize={10.5}
              fontWeight={600}
            >
              {n.label}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}
