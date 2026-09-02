"use client";

/**
 * Bridge View Sankey — d3-sankey computes the layout, rendered as plain SVG.
 * QRIS merchants → mule accounts → exchange deposits → USDT wallets → foreign,
 * with per-link gradients along the amber (fiat) → cyan/sky/blue (crypto) ramp.
 *
 * UX: hover any node or link to isolate that path — everything else dims. Node
 * labels are cleaned (wallet-address tags dropped, long names clipped) and
 * volumes shown compact ("137.4M"), placed left/right so they never collide.
 */

import { useId, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  sankey,
  sankeyJustify,
  sankeyLinkHorizontal,
  type SankeyLink,
  type SankeyNode,
} from "d3-sankey";
import type { BridgeSankeyData, BridgeSankeyNode } from "@/lib/bridge/types";
import { FOREIGN_COLOR, STAGE_COLORS } from "@/lib/bridge/types";

const W = 820;
const H = 460;

type LinkDatum = { source: string; target: string; value: number };
type LaidNode = SankeyNode<BridgeSankeyNode, LinkDatum>;
type LaidLink = SankeyLink<BridgeSankeyNode, LinkDatum>;

function nodeColor(n: LaidNode): string {
  if (n.color) return n.color;
  if (/foreign/i.test(n.name)) return FOREIGN_COLOR;
  return STAGE_COLORS[Math.min(n.depth ?? 0, STAGE_COLORS.length - 1)];
}

/** Compact money: 137,376,718 → "137.4M". */
function compact(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${(v / 1e9).toFixed(1).replace(/\.0$/, "")}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(1).replace(/\.0$/, "")}M`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1).replace(/\.0$/, "")}K`;
  return String(Math.round(v));
}

const fmtFull = (v: number) => v.toLocaleString("en-US");

/** Inline label: drop a trailing wallet-address tag "(TBQg…Sw3d)", clip length. */
function displayName(name: string): string {
  let s = name.replace(/\s*\((?:0x)?[A-Za-z0-9]*…[A-Za-z0-9]*\)\s*$/u, "").trim();
  if (s.length > 22) s = `${s.slice(0, 21).trimEnd()}…`;
  return s;
}

// Right margin reserved for the final column's labels (they read left→right too).
const RIGHT_PAD = 150;

export function SankeyChart({ data }: { data: BridgeSankeyData }) {
  const t = useTranslations("bridge.sankeyChart");
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const [hoverLink, setHoverLink] = useState<number | null>(null);

  const layout = useMemo(() => {
    try {
      const generator = sankey<BridgeSankeyNode, LinkDatum>()
        .nodeId((d) => d.id)
        .nodeWidth(15)
        .nodePadding(30)
        .nodeAlign(sankeyJustify)
        .extent([
          [16, 18],
          [W - RIGHT_PAD, H - 18],
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
      <div className="grid h-[460px] place-items-center text-[11px] text-muted">
        {t("empty")}
      </div>
    );
  }

  const linkPath = sankeyLinkHorizontal<BridgeSankeyNode, LinkDatum>();
  const nodes = layout.nodes as LaidNode[];
  const links = layout.links as LaidLink[];
  const anyHover = hoverNode !== null || hoverLink !== null;

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
      className="h-[460px]"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={t("ariaLabel")}
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
            strokeOpacity={anyHover ? (active ? 0.95 : 0.06) : 0.7}
            style={{ transition: "stroke-opacity .15s", cursor: "pointer" }}
            onMouseEnter={() => setHoverLink(i)}
            onMouseLeave={() => setHoverLink(null)}
          >
            <title>
              {`${(l.source as LaidNode).name} → ${(l.target as LaidNode).name} · ${fmtFull(l.value)}`}
            </title>
          </path>
        );
      })}

      {/* nodes */}
      {nodes.map((n) => {
        const dim = nodeDim(n.id);
        const x0 = n.x0 ?? 0;
        const x1 = n.x1 ?? 0;
        const y0 = n.y0 ?? 0;
        const y1 = n.y1 ?? 0;
        const midY = (y0 + y1) / 2;
        const h = y1 - y0;
        // Every label sits to the RIGHT of its node — each in its own column
        // lane, so labels never share a gap or collide. The final column labels
        // into the reserved right margin.
        const labelX = x1 + 8;
        const showValue = h >= 13;
        const name = displayName(n.name);
        return (
          <g
            key={n.id}
            style={{ transition: "opacity .15s", opacity: dim ? 0.24 : 1, cursor: "pointer" }}
            onMouseEnter={() => setHoverNode(n.id)}
            onMouseLeave={() => setHoverNode(null)}
          >
            <rect
              x={x0}
              y={y0}
              width={x1 - x0}
              height={Math.max(1, h)}
              rx={3}
              fill={nodeColor(n)}
            >
              <title>{`${n.name} · ${fmtFull(n.value ?? 0)}`}</title>
            </rect>
            <text
              x={labelX}
              y={showValue ? midY - 4.5 : midY + 3.5}
              textAnchor="start"
              fill="rgba(255,255,255,.78)"
              fontSize={10.5}
              fontWeight={600}
            >
              {name}
            </text>
            {showValue && (
              <text
                x={labelX}
                y={midY + 7.5}
                textAnchor="start"
                fill="rgba(255,255,255,.42)"
                fontSize={9}
                fontWeight={600}
                fontFamily="ui-monospace, monospace"
              >
                {compact(n.value ?? 0)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
