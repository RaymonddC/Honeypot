/**
 * Honeypot chat transcript — scammer vs persona bubbles with inline
 * `◇ extracted · <type> · conf 0.xx` badges (mockup .chat / .msg / .extract),
 * session header eyebrow + mode tag, composer status line.
 */

import type { HpMessage, HpSession } from "@/lib/honeypot/types";
import { formatConf } from "@/lib/honeypot/types";

function Bubble({ msg }: { msg: HpMessage }) {
  const isPersona = msg.sender === "persona";
  return (
    <div
      className={`max-w-[74%] rounded-xl border px-3 py-[9px] text-xs leading-relaxed ${
        isPersona
          ? "self-end rounded-br-[4px] border-accent/[.22] bg-accent/10 text-fg"
          : "self-start rounded-bl-[4px] border-line bg-elevated"
      }`}
    >
      <div
        className={`mb-[3px] text-[9.5px] uppercase tracking-[.06em] ${
          isPersona ? "text-accent-bright opacity-90" : "opacity-60"
        }`}
      >
        {msg.who}
      </div>
      {msg.text}
      {msg.extractions.map((ex) => (
        <div
          key={`${msg.id}-${ex.label}`}
          className="mt-[7px] flex items-center gap-1.5 border-t border-dashed border-accent/[.22] pt-[7px] font-mono text-[10px] text-accent-bright"
        >
          ◇ extracted · {ex.label} · conf {formatConf(ex.confidence)}
        </div>
      ))}
    </div>
  );
}

export function ChatTranscript({
  session,
  messages,
  composerNote,
}: {
  session: HpSession;
  messages: HpMessage[];
  composerNote: string;
}) {
  return (
    <div className="flex h-[452px] flex-col rounded-card border border-line bg-card">
      {/* header */}
      <div className="flex items-center justify-between border-b border-line px-3.5 py-[11px]">
        <span className="eyebrow">
          Session · {session.channel} · persona &ldquo;{session.persona}&rdquo;
        </span>
        <span className="rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10.5px] text-white/60">
          {session.modeTag}
        </span>
      </div>

      {/* stream */}
      <div
        role="log"
        aria-label={`Scam session transcript · ${session.channel}`}
        className="flex flex-1 flex-col gap-3 overflow-y-auto p-4"
      >
        {messages.map((m) => (
          <Bubble key={m.id} msg={m} />
        ))}
      </div>

      {/* composer status line */}
      <div className="flex items-center gap-2.5 border-t border-line px-3.5 py-[11px] text-[11px] text-muted">
        <span className="text-accent-bright">◇</span> {composerNote}
      </div>
    </div>
  );
}
