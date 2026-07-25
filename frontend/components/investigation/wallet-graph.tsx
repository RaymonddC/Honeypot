"use client";

/**
 * Transaction graph canvas — Cytoscape.js.
 * Risk-colored nodes (low/med/high/exchange), amount-sized directed edges,
 * peeling-chain path highlighted in red, hover tooltip, click → select.
 */

import cytoscape, { type Core, type EventObject } from "cytoscape";
import dagre from "cytoscape-dagre";
import { useEffect, useRef, useState } from "react";
import type { RiskLevel, WalletGraph as WalletGraphData } from "@/lib/investigation/types";
import { RISK_COLORS, RISK_LABELS } from "@/lib/investigation/types";

// Register the dagre layout once (guard survives HMR re-imports).
if (!(globalThis as { __ittuDagre?: boolean }).__ittuDagre) {
  cytoscape.use(dagre);
  (globalThis as { __ittuDagre?: boolean }).__ittuDagre = true;
}

interface Tooltip {
  x: number;
  y: number;
  address: string;
  risk: RiskLevel;
  score: number;
  volume?: string;
}

// Thin edges like the mockup (≈1, up to ~1.8 for the biggest flows); peel = 2.
const edgeWidth = (amount: number) => 1 + Math.min(0.8, amount / 90000);

/* eslint-disable @typescript-eslint/no-explicit-any */
const STYLE: any[] = [
  {
    selector: "node",
    style: {
      width: "data(size)",
      height: "data(size)",
      // Translucent risk-colored disc + crisp ring (the mockup's node look).
      // Cytoscape ignores alpha in gradient stops, so translucency comes from
      // background-opacity; no underlay (it renders as a rounded box).
      "background-color": "data(color)",
      "background-opacity": 0.2,
      "border-width": 2,
      "border-color": "data(color)",
      "transition-property": "border-width, border-color",
      "transition-duration": "0.2s",
      label: "data(label)",
      "font-size": 10,
      "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
      color: "rgba(255,255,255,.55)",
      "text-valign": "bottom",
      "text-halign": "center",
      "text-margin-y": 6,
      "overlay-opacity": 0,
    },
  },
  {
    selector: "node[risk='exchange']",
    style: { color: RISK_COLORS.exchange, "background-opacity": 0.3 },
  },
  {
    selector: "node[?isMain]",
    style: { "border-width": 2 },
  },
  {
    selector: "node.sel",
    style: {
      "border-width": 2,
      "border-style": "dashed",
      "border-color": "#34d399",
    },
  },
  {
    selector: "edge",
    style: {
      "curve-style": "bezier",
      width: "data(width)",
      "line-color": "rgba(255,255,255,.07)",
      "target-arrow-shape": "triangle",
      "target-arrow-color": "rgba(255,255,255,.28)",
      "arrow-scale": 0.75,
    },
  },
  {
    selector: "edge.adj",
    style: {
      "line-color": "rgba(255,255,255,.28)",
      "target-arrow-color": "rgba(255,255,255,.5)",
    },
  },
  {
    selector: "edge.peel",
    style: {
      width: 2,
      "line-color": "rgba(239,68,68,.85)",
      "target-arrow-color": "#ef4444",
    },
  },
  {
    selector: "edge.peel.adj",
    style: { "line-color": "rgba(239,68,68,.95)" },
  },
];

function withAlpha(hex: string, alpha: number): string {
  // Cytoscape's style parser rejects 8-digit hex (#rrggbbaa) and throws at init.
  // Emit spaceless rgba() so each stays a single token inside the
  // space-separated `background-gradient-stop-colors` list.
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

export function WalletGraph({
  graph,
  selectedId,
  onSelect,
}: {
  graph: WalletGraphData;
  selectedId: string | null;
  onSelect: (address: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [tip, setTip] = useState<Tooltip | null>(null);

  /* Build / rebuild the graph when data changes. */
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const ids = new Set(graph.nodes.map((n) => n.id));
    const elements = [
      ...graph.nodes.map((n) => {
        const color = RISK_COLORS[n.risk];
        return {
          data: {
            id: n.id,
            label: n.label ?? "",
            color,
            stops: `${color} ${color} ${withAlpha(color, n.risk === "exchange" ? 0.18 : 0.16)} ${withAlpha(color, n.risk === "exchange" ? 0.18 : 0.16)}`,
            size: n.size,
            risk: n.risk,
            score: n.score,
            volume: n.volume ?? "",
            isMain: n.isMain ? 1 : 0,
          },
          position: n.position ? { ...n.position } : undefined,
        };
      }),
      ...graph.edges
        .filter((e) => ids.has(e.source) && ids.has(e.target))
        .map((e) => ({
          data: {
            id: e.id,
            source: e.source,
            target: e.target,
            width: edgeWidth(e.amount),
          },
          classes: e.isPeel ? "peel" : "",
        })),
    ];

    const hasPositions = graph.nodes.every((n) => n.position);
    const cy = cytoscape({
      container,
      elements,
      style: STYLE,
      // Preset when the API sends coords; otherwise a left→right directed (dagre)
      // layout so the money-flow reads like the mockup, not a blob.
      layout: hasPositions
        ? { name: "preset", fit: true, padding: 36 }
        : ({
            name: "dagre",
            rankDir: "LR",
            nodeSep: 20,
            rankSep: 60,
            fit: true,
            padding: 40,
            animate: false,
          } as any),
      minZoom: 0.3,
      maxZoom: 3,
      wheelSensitivity: 0.2,
    });

    cy.on("tap", "node", (evt: EventObject) =>
      onSelectRef.current(evt.target.id()),
    );
    const showTip = (evt: EventObject) => {
      const d = evt.target.data();
      const p = evt.target.renderedPosition();
      container.style.cursor = "pointer";
      setTip({
        x: p.x,
        y: p.y - (d.size / 2) * cy.zoom(),
        address: d.label || d.id,
        risk: d.risk as RiskLevel,
        score: Number(d.score),
        volume: d.volume || undefined,
      });
    };
    cy.on("mouseover", "node", showTip);
    cy.on("drag", "node", showTip);
    cy.on("mouseout", "node", () => {
      container.style.cursor = "";
      setTip(null);
    });
    cy.on("pan zoom", () => setTip(null));

    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [graph]);

  /* Selection ring + adjacent-edge emphasis. */
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().removeClass("sel");
    cy.edges().removeClass("adj");
    if (selectedId) {
      const node = cy.getElementById(selectedId);
      if (node.nonempty()) {
        node.addClass("sel");
        node.connectedEdges().addClass("adj");
      }
    }
  }, [selectedId, graph]);

  const zoom = (factor: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.zoom({
      level: cy.zoom() * factor,
      renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
    });
  };

  return (
    <div
      className="relative h-[540px] overflow-hidden rounded-card border border-line"
      style={{
        background: "radial-gradient(120% 120% at 30% 20%, #0e1013, #0a0a0b)",
      }}
    >
      <div ref={containerRef} className="absolute inset-0" />

      {/* hint */}
      <div className="pointer-events-none absolute left-3 top-3 rounded-lg border border-line bg-black/55 px-2.5 py-1.5 text-[10.5px] text-muted">
        ◦ hover to preview · click to inspect · drag / scroll to navigate
      </div>

      {/* zoom tools */}
      <div className="absolute right-3 top-3 flex flex-col gap-1.5">
        {(
          [
            ["＋", "Zoom in", () => zoom(1.25)],
            ["－", "Zoom out", () => zoom(0.8)],
            ["⤢", "Fit graph", () => cyRef.current?.fit(undefined, 36)],
            [
              "⟳",
              "Reset view",
              () => {
                cyRef.current?.fit(undefined, 36);
              },
            ],
          ] as const
        ).map(([glyph, label, fn]) => (
          <button
            key={label}
            type="button"
            title={label}
            aria-label={label}
            onClick={fn}
            className="grid h-[30px] w-[30px] place-items-center rounded-lg border border-line bg-black/70 text-sm text-white/60 backdrop-blur-sm transition-colors hover:border-accent/30 hover:text-accent-bright"
          >
            {glyph}
          </button>
        ))}
      </div>

      {/* legend */}
      <div className="pointer-events-none absolute bottom-3 left-3 flex gap-3 rounded-lg border border-line bg-black/70 px-2.5 py-1.5 text-[10.5px] text-muted backdrop-blur-sm">
        {(["high", "medium", "low", "exchange"] as const).map((r) => (
          <span key={r} className="flex items-center gap-1.5">
            <i
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: RISK_COLORS[r] }}
            />
            {RISK_LABELS[r]}
          </span>
        ))}
      </div>

      {/* peeling-chain callout */}
      <div className="pointer-events-none absolute bottom-3 right-3 rounded-lg border border-risk-high/20 bg-black/70 px-2.5 py-1.5 font-mono text-[10px] font-bold text-risk-high backdrop-blur-sm">
        ◆ peeling chain → exchange
      </div>

      {/* hover tooltip */}
      {tip && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[115%] rounded-lg border border-white/10 bg-[#141518]/95 px-2.5 py-1.5 shadow-[0_8px_24px_rgba(0,0,0,.5)]"
          style={{ left: tip.x, top: tip.y }}
        >
          <div className="font-mono text-[11px] text-fg">{tip.address}</div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted">
            <i
              className="inline-block h-[7px] w-[7px] rounded-full"
              style={{ background: RISK_COLORS[tip.risk] }}
            />
            {tip.risk === "exchange"
              ? "Exchange"
              : `${RISK_LABELS[tip.risk]} · ${tip.score.toFixed(2)}`}
            {tip.volume ? ` · ${tip.volume}` : ""}
          </div>
        </div>
      )}
    </div>
  );
}
