"use client";

/**
 * Bridge View Sankey — d3-sankey computes the layout, rendered as plain SVG.
 * QRIS merchants → mule accounts → exchange deposits → USDT wallets → foreign,
 * with per-link gradients along the amber (fiat) → cyan/sky/blue (crypto) ramp.
 *
 * UX: hover any node or link to isolate that path — everything else dims, so a
 * single money trail is easy to follow. Node volumes are labelled inline.
 */

import { useId, useMemo, useState } from "react";
import {
  sankey,
  sankeyJustify,
  sankeyLinkHorizontal,
  type SankeyLink,
  type SankeyNode,
} from "d3-sankey";
import type { BridgeSankeyData, BridgeSankeyNode } from "@/lib/bridge/types";
import { FOREIGN_COLOR, STAGE_COLORS } from "@/lib/bridge/types";

const W = 780;
const H = 440;

type LinkDatum = { source: string; target: string; value: number };
type LaidNode = SankeyNode<BridgeSankeyNode, LinkDatum>;
type LaidLink = SankeyLink<BridgeSankeyNode, LinkDatum>;

function nodeColor(n: LaidNode): string {
  if (n.color) return n.color;
  if (/foreign/i.test(n.name)) return FOREIGN_COLOR;
  return STAGE_COLORS[Math.min(n.depth ?? 0, STAGE_COLORS.length - 1)];
}

const fmt = (v: number) => v.toLocaleString("en-US");

export function SankeyChart({ data }: { data: BridgeSankeyData }) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const [hoverLink, setHoverLink] = useState<number | null>(null);

  const layout = useMemo(() => {
    try {
      const generator = sankey<BridgeSankeyNode, LinkDatum>()
        .nodeId((d) => d.id)
        .nodeWidth(16)
        .nodePadding(26)
        .nodeAlign(sankeyJustify)
        .extent([
          [24, 14],
          [W - 24, H - 14],
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
      <div className="grid h-[440px] place-items-center text-[11px] text-muted">
        No bridge flows to render.
      </div>
    );
  }

  const linkPath = sankeyLinkHorizontal<BridgeSankeyNode, LinkDatum>();
  const nodes = layout.nodes as LaidNode[];
  const links = layout.links as LaidLink[];
  const anyHover = hoverNode !== null || hoverLink !== null;

  // Which nodes belong to the currently-isolated path.
  const activeNodes = new Set<string>();
  if (hoverNode) {
    activeNodes.add(hoverNode);
    for (const l of links) {
      const s = (l.source as LaidNode).id;
      const t = (l.target as LaidNode).id;
      if (s === hoverNode) activeNodes.add(t);
      if (t === hoverNode) activeNodes.add(s);
    }
  } else if (hoverLink !== null) {
    const l = links[hoverLink];
    activeNodes.add((l.source as LaidNode).id);
    activeNodes.add((l.target as LaidNode).id);
  }

  const linkActive = (l: LaidLink, i: number) => {
    if (!anyHover) return true;
    if (hoverLink !== null) return hoverLink === i;
    return (l.source as LaidNode).id === hoverNode || (l.target as LaidNode).id === hoverNode;
  };
  const nodeDim = (id: string) => anyHover && !activeNodes.has(id);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      className="h-[440px]"
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
              <stop offset="0" stopColor={nodeColor(s)} stopOpacity={0.55} />
              <stop offset="1" stopColor={nodeColor(t)} stopOpacity={0.55} />
            </linearGradient>
          );
        })}
      </defs>

      {/* links */}
      {links.map((l, i) => {
        const active = linkActive(l, i);
        return (
          <path
            key={i}
            d={linkPath(l) ?? undefined}
            fill="none"
            stroke={`url(#${uid}-g${i})`}
            strokeWidth={Math.max(1.5, l.width ?? 1)}
            strokeOpacity={anyHover ? (active ? 0.95 : 0.07) : 0.72}
            style={{ transition: "stroke-opacity .15s", cursor: "pointer" }}
            onMouseEnter={() => setHoverLink(i)}
            onMouseLeave={() => setHoverLink(null)}
          >
            <title>
              {`${(l.source as LaidNode).name} → ${(l.target as LaidNode).name} · ${fmt(l.value)}`}
            </title>
          </path>
        );
      })}

      {/* nodes */}
      {nodes.map((n) => {
        const dim = nodeDim(n.id);
        const leftHalf = (n.x0 ?? 0) <= W * 0.72;
        const labelX = leftHalf ? (n.x1 ?? 0) + 9 : (n.x0 ?? 0) - 9;
        const anchor = leftHalf ? "start" : "end";
        const midY = ((n.y0 ?? 0) + (n.y1 ?? 0)) / 2;
        const tall = (n.y1 ?? 0) - (n.y0 ?? 0) > 26;
        return (
          <g
            key={n.id}
            style={{ transition: "opacity .15s", opacity: dim ? 0.28 : 1, cursor: "pointer" }}
            onMouseEnter={() => setHoverNode(n.id)}
            onMouseLeave={() => setHoverNode(null)}
          >
            <rect
              x={n.x0}
              y={n.y0}
              width={(n.x1 ?? 0) - (n.x0 ?? 0)}
              height={Math.max(1, (n.y1 ?? 0) - (n.y0 ?? 0))}
              rx={3}
              fill={nodeColor(n)}
            >
              <title>{`${n.name} · ${fmt(n.value ?? 0)}`}</title>
            </rect>
            {/* name label (only where the mock provides one — keeps it sparse) */}
            {n.label && (
              <text
                x={labelX}
                y={tall ? midY - 3 : midY + 3.5}
                textAnchor={anchor}
                fill="rgba(255,255,255,.72)"
                fontSize={10.5}
                fontWeight={600}
              >
                {n.label}
              </text>
            )}
            {/* volume label — always shown, so amounts are readable at a glance */}
            <text
              x={labelX}
              y={n.label && tall ? midY + 10 : n.label ? midY + 3.5 : midY + 3.5}
              textAnchor={anchor}
              fill="rgba(255,255,255,.40)"
              fontSize={9}
              fontWeight={600}
              fontFamily="ui-monospace, monospace"
            >
              {n.label && !tall ? "" : fmt(n.value ?? 0)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
