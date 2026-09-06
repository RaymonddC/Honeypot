/**
 * Response Dashboard metric tiles (mockup .metrics/.metric) — cases in
 * progress · avg time-to-freeze · funds at risk · funds frozen · recovery
 * rate vs the 4.76% IASC baseline.
 */

import type { MetricTile } from "@/lib/response/types";

function Tile({ tile }: { tile: MetricTile }) {
  return (
    <div className="rounded-card border border-line bg-card p-[15px]">
      <div className="eyebrow">{tile.label}</div>
      <div
        className="mt-[9px] font-mono text-[26px] font-extrabold leading-none tracking-tight tnum"
        style={tile.color ? { color: tile.color } : undefined}
      >
        {tile.value}
        {tile.suffix && (
          <span className="text-[13px] font-bold text-muted"> {tile.suffix}</span>
        )}
      </div>
      {tile.delta && (
        <div
          className={`mt-[5px] text-[12px] ${
            tile.deltaUp ? "text-accent-bright" : "text-muted"
          }`}
        >
          {tile.delta}
        </div>
      )}
    </div>
  );
}

export function MetricTiles({ tiles }: { tiles: MetricTile[] }) {
  return (
    <div className="mb-3.5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {tiles.map((t) => (
        <Tile key={t.label} tile={t} />
      ))}
    </div>
  );
}
