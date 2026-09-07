/**
 * Response Dashboard metric tiles (mockup .metrics/.metric) — cases in
 * progress · avg time-to-freeze · funds at risk · funds frozen · recovery
 * rate vs the 4.76% IASC baseline.
 */

"use client";

import { useTranslations } from "next-intl";
import type { MetricTile } from "@/lib/response/types";

function Tile({ tile }: { tile: MetricTile }) {
  // Label and delta are resolved HERE, from the tile's key — the data layer
  // deliberately carries no display text (see buildTiles in lib/response/api.ts).
  const t = useTranslations("response.tiles");
  return (
    <div className="rounded-card border border-line bg-card p-[15px]">
      {/* Two lines' worth of space is reserved whether the label needs it or
          not, so the figures stay on a common baseline across the row. Without
          it a longer translation ("Rata-rata waktu ke pemblokiran" vs "Avg
          time-to-freeze") wraps and drops that one tile's number out of line. */}
      <div className="eyebrow flex min-h-[2.2em] items-start">
        {t(`${tile.key}.label`)}
      </div>
      <div
        className="mt-[9px] text-[26px] font-extrabold leading-none tracking-tight tnum"
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
          {t(`${tile.key}.delta.${tile.delta.key}`, tile.delta.values)}
        </div>
      )}
    </div>
  );
}

export function MetricTiles({ tiles }: { tiles: MetricTile[] }) {
  return (
    <div className="mb-3.5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {tiles.map((tile) => (
        <Tile key={tile.key} tile={tile} />
      ))}
    </div>
  );
}
