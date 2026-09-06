"use client";

/**
 * Honeypot chat transcript — scammer vs persona bubbles with inline
 * `◇ extracted · <type> · conf 0.xx` badges (mockup .chat / .msg / .extract),
 * session header eyebrow + mode tag, composer status line.
 */

import { useTranslations } from "next-intl";
import type { HpMessage, HpSession } from "@/lib/honeypot/types";
import { formatConf } from "@/lib/honeypot/types";

function Bubble({ msg }: { msg: HpMessage }) {
  const t = useTranslations("honeypot.chatTranscript");
  const isPersona = msg.sender === "persona";
  return (
    <div
      className={`max-w-[74%] rounded-xl border px-3 py-[9px] text-[12px] leading-relaxed ${
        isPersona
          ? "self-end rounded-br-[4px] border-accent/[.22] bg-accent/10 text-fg"
          : "self-start rounded-bl-[4px] border-line bg-elevated"
      }`}
    >
      <div
        className={`mb-[3px] text-[12px] uppercase tracking-[.06em] ${
          isPersona ? "text-accent-bright opacity-90" : "opacity-60"
        }`}
      >
        {msg.who}
      </div>
      {msg.text}
      {msg.extractions.map((ex, i) => (
        <div
          key={`${msg.id}-${ex.label}-${i}`}
          className="mt-[7px] flex items-center gap-1.5 border-t border-dashed border-accent/[.22] pt-[7px] font-mono text-[12px] text-accent-bright"
        >
          {t("extractedBadge", { label: ex.label, confidence: formatConf(ex.confidence) })}
        </div>
      ))}
    </div>
  );
}

export function ChatTranscript({
  session,
  messages,
  composerNote,
  heightClass = "h-[452px]",
}: {
  session: HpSession;
  messages: HpMessage[];
  /** Composer status line. Omit for a read-only embed (case view) — the
   *  footer is then hidden rather than showing a live-console status. */
  composerNote?: string;
  /** Height override so the transcript can embed in a tighter panel. */
  heightClass?: string;
}) {
  const t = useTranslations("honeypot.chatTranscript");
  return (
    <div className={`flex ${heightClass} flex-col rounded-card border border-line bg-card`}>
      {/* header */}
      <div className="flex items-center justify-between border-b border-line px-3.5 py-[11px]">
        <span className="eyebrow">
          {t("sessionEyebrow", { channel: session.channel, persona: session.persona })}
        </span>
        <span className="rounded-md border border-line bg-elevated px-2 py-0.5 text-[12px] text-muted">
          {session.modeTag}
        </span>
      </div>

      {/* stream */}
      <div
        role="log"
        aria-label={t("transcriptLogLabel", { channel: session.channel })}
        className="flex flex-1 flex-col gap-3 overflow-y-auto p-4"
      >
        {messages.map((m) => (
          <Bubble key={m.id} msg={m} />
        ))}
      </div>

      {/* composer status line (live console only — omitted on read-only embeds) */}
      {composerNote && (
        <div className="flex items-center gap-2.5 border-t border-line px-3.5 py-[11px] text-[12px] text-muted">
          <span className="text-accent-bright">◇</span> {composerNote}
        </div>
      )}
    </div>
  );
}
