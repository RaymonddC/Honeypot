import type { NextConfig } from "next";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

// The repo root has its own package-lock.json (the dev orchestrator that runs
// backend + frontend together), so Next.js would otherwise infer the *repo root*
// as the workspace root and warn about multiple lockfiles. Pin the root to this
// frontend directory so module/env resolution is unambiguous.
const nextConfig: NextConfig = {
  turbopack: {
    root: dirname(fileURLToPath(import.meta.url)),
  },
};

export default nextConfig;
