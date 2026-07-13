# ITTU — Demo Runbook (run-of-show)

A tight, timed walkthrough for presenting ITTU live. Target: **~5 minutes**.
Live: frontend `honeypot-brown.vercel.app` · backend `honeypot-aa88.onrender.com`.

---

## 0. The 20-second pitch (say this first)
> "In Indonesia, investment-scam calls drain pensioners' savings every day — the
> victim loses the money, the scammer vanishes, and by the time police get a
> report the trail is cold. **ITTU flips it.** Our AI *answers the scam call*,
> plays a confused grandmother, and bait the scammer into revealing their crypto
> wallet and mule bank account — then that intel flows automatically into a full
> forensic investigation and a ready-to-sign freeze order. Infiltrate → Trace →
> Takedown → Uncover. Let me show you."

---

## 1. Pre-flight checklist (do this BEFORE you present)
- [ ] **Warm the backend** — open `honeypot-aa88.onrender.com/health` ~60s before (free tier cold-starts ~30–60s). *(UptimeRobot removes this risk if set up.)*
- [ ] **Use Google Chrome** (or Edge) — live-mic + Indonesian voice only work there.
- [ ] **Confirm the 9Router VPS is up** so the persona improvises for real. If it's down, ITTU *gracefully falls back to the scripted persona* — the demo still works, just less dynamic. (Tell: the reply's `model` shows `poc-interactive-stall-1` when scripted vs `anthropic/claude-…` when live.)
- [ ] **Log in** as the demo investigator (Budi Santoso · Bareskrim Polri) so you land in the console.
- [ ] Have two tabs ready: **`/honeypot/call`** (the call) and **`/investigation`** (the graph).
- [ ] Silence notifications, set browser zoom ~100–110%, mic unmuted.

---

## 2. Run-of-show (timed beats)

### Beat 1 — The honeypot call · `0:00–2:00`  ⭐ THE WOW
**Screen:** `/honeypot/call` in Chrome.
1. Frame it: *"A scam call comes in. Normally a person picks up. Here, our AI persona — Bu Sari, a 54-year-old retired teacher — answers."*
2. Set **Call mode → Live mic** (Control Panel or the header toggle). Click **Start call**.
3. **Play the scammer** — say these into the mic, one at a time, waiting for Bu Sari to reply between each (escalating script below).
4. **Point out live**, as it happens:
   - Bu Sari **improvising** in Bahasa (stalling, playing confused — she even name-drops **OJK**, the regulator).
   - **Captions** revealing line-by-line; the **waveform** on the active speaker.
   - Entities **popping into the side panel** the moment the wallet/account are said.
   - The **custody card**: "hash-chained", crime class → *investment scam*.
5. At the disclosure turn, hit **"Take over"** — *"a human investigator can barge in at any moment."*

**Your lines to say (as the scammer):**
1. "Halo Bu, saya dari tim ProfitMax Investa, investasi dijamin untung 10 persen per hari."
2. "Ibu cukup transfer 5 juta ke rekening BCA **5271038462** untuk aktivasi akun VIP."
3. "Atau lebih cepat, kirim USDT ke wallet **TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6** sekarang ya Bu."
4. "Ayo Bu buruan, kesempatan terbatas, jangan sampai hangus!"

> **The point to land:** "In 90 seconds, with zero human effort, we captured a crypto wallet and a mule bank account from a live scammer — evidence, hash-chained for court."

### Beat 2 — Investigation · `2:00–3:00`
**Screen:** `/investigation` (the wallet from the call is the same fixture).
1. *"That exact wallet the scammer just disclosed — here it is on the blockchain."*
2. Show the **graph**: risk-colored nodes, the **peeling chain in red flowing to an exchange** (how they launder + cash out).
3. Click the wallet → the **detail card** (risk gauge, the 12 features, detected typologies).
4. Open **Glass Box** → *"this isn't a black box — every risk score comes with its reasoning, so it holds up in court."*

### Beat 3 — Bridge / Trace · `3:00–3:45`
**Screen:** `/bridge`.
1. *"Crypto is only half the trail. ITTU correlates the on-chain flow with fiat bank transfers."*
2. Show the **Sankey / split-screen**: the crypto side ↔ the fiat side, correlated by amount + timing.
3. Point at the **mule cluster** — *"these accounts move as one syndicate."*

### Beat 4 — Response / Takedown · `3:45–4:30`
**Screen:** `/actions` (Action Panel) → `/response` (dashboard).
1. *"Now the investigator acts."* Generate a **freeze order** + **LTKM report** (auto-filled from the case).
2. Dispatch it → show it land on the **Response dashboard**.
3. *"From a scam call to a signed freeze order — one continuous, evidenced workflow."*

### Beat 5 — Close · `4:30–5:00`
> "Every scam call becomes an investigation instead of a loss. The AI never sleeps,
> the evidence is court-ready, and it's built to scale — swap the voice, the LLM,
> or the blockchain provider with one config change. That's ITTU: turning the
> hunted into the hunters."

---

## 3. Fallback playbook (if something misbehaves)
| If… | Do this |
|---|---|
| **9Router is down / rate-limited** (persona goes scripted) | Lean in: *"notice it never breaks — resilient by design; even offline it stays in character and still extracts the intel."* It still captures entities + custody. |
| **Mic / voice doesn't work** (wrong browser) | Use the **"type as the scammer"** text box — same `/turn` pipeline, just typed. Or switch **Call mode → Scripted replay** for a hands-free canned run. |
| **Backend cold-start lag** | Talk over it (the pitch in §0) while it warms; or open the **`/honeypot` console** first — it's pre-seeded, renders instantly. |
| **Deployed backend flaky** | The frontend has an **offline/mock mode** — every screen renders on demo data with an `● offline` badge. The demo survives with no backend. |
| **Graph looks slightly off** | It's cosmetic — pivot to the **Glass Box reasoning**, which is the real substance. |

---

## 4. Differentiators (drop these if asked "what's novel?")
- **End-to-end thread** — most tools do *one* of detect/trace/report. ITTU is infiltrate → investigate → freeze, as one flow.
- **Custody hash-chain** — every message + entity is SHA-256 chained → tamper-evident, court-admissible.
- **Glass Box** — explainable risk scoring, not a black box.
- **Provider-abstracted / scalable** — browser-TTS → ElevenLabs, 9Router → any OpenAI-compatible LLM, TRONSCAN → any chain: all a one-line env/adapter swap (POC/LIVE MODE pattern).
- **Indonesia-native** — Bahasa persona, OJK / Bareskrim Polri context, BCA rails, LTKM reporting.

## 5. Likely judge questions → answers
- **"Is the AI real or scripted?"** → Real LLM (Claude Haiku via our gateway); improvises live. A deterministic scripted persona is the *fallback* so a provider outage never breaks a demo or an operation.
- **"Is engaging scammers legal?"** → In production it runs under **law-enforcement (Polri) authorization** — lawful recording, engagement, evidence chain. The POC demo doesn't engage real suspects.
- **"Where's the data from?"** → On-chain: **TRONSCAN** live (USDT-TRC20). Fiat: synthetic now; a bank/PPATK feed for LIVE.
- **"How does it scale?"** → The adapter/MODE architecture — every external boundary (chain, LLM, voice, channel) is behind an interface; swap provider = env var + one adapter class.
- **"What's the moat?"** → The infiltration-to-investigation pipeline + court-ready custody, tuned for the Indonesian financial-crime context.

---
*Keep this open on a second screen during the demo. Rehearse Beat 1 twice — the
live call is the moment that wins the room.*
