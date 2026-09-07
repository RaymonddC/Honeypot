import { Suspense } from "react";
import type { Metadata } from "next";
import { CekScreen } from "./cek-screen";

// Server component only so it can export `metadata`; all the copy lives in
// CekScreen, which must be a client component to reach the locale (see the note
// atop app/login/login-screen.tsx).
export const metadata: Metadata = {
  title: "CekScam — cek rekening & nomor sebelum transfer",
  description:
    "Cek nomor rekening bank, nomor telepon, atau e-wallet sebelum Anda transfer. Laporkan penipu dan bantu memutus jaringannya.",
};

export default function CekPage() {
  // CekScreen reads ?q= via useSearchParams so a result is linkable. That opts
  // the subtree out of static prerendering, and Next requires the boundary to
  // be explicit — without it the production build fails on this page even
  // though `next dev` renders it fine. The fallback is the page's own dark
  // ground so there is no flash before hydration.
  return (
    <Suspense fallback={<div className="min-h-screen bg-bg" />}>
      <CekScreen />
    </Suspense>
  );
}
