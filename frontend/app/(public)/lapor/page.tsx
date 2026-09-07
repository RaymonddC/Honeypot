import { Suspense } from "react";
import type { Metadata } from "next";
import { LaporScreen } from "./lapor-screen";

export const metadata: Metadata = {
  title: "Laporkan penipu — CekScam",
  description:
    "Laporkan rekening, nomor, atau alamat kripto yang dipakai penipu. Anda tidak perlu sampai kehilangan uang untuk melapor.",
};

export default function LaporPage() {
  // LaporScreen reads ?v= (carried over from a check) via useSearchParams, which
  // opts the subtree out of static prerendering; Next requires the boundary to
  // be explicit or the production build fails on this page.
  return (
    <Suspense fallback={<div className="min-h-[60vh]" />}>
      <LaporScreen />
    </Suspense>
  );
}
