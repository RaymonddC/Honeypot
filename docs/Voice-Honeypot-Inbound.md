# ITTU — Voice Honeypot: Inbound (the one that needs no authorisation)

**Status:** strategy + seeding guide, written 2026-09-05 after the decision to
proceed without law-enforcement authorisation. Companion to
[`Voice-Honeypot-Outbound.md`](Voice-Honeypot-Outbound.md), which describes the
dialing subsystem — built, and **gated on Polri** (see `app/core/gated.py`).

> ⚖️ **Not legal advice.** The reasoning below is why inbound is a *different and
> much weaker* permission problem than outbound, not a claim that it needs none.
> Call recording in particular deserves a lawyer's sentence, not mine.

---

## 1. The distinction the whole pivot rests on

|  | Inbound | Outbound |
|---|---|---|
| Who initiates | the scammer calls **us** | we call **them** |
| Our position | a **party to our own conversation** | contacting someone who has not contacted us |
| Permission | a phone number | **Polri authorisation** |
| Built? | answer webhook ✅, media bridge ⏳ | fully built, refuses in LIVE ✅ |

**A honeypot is passive by definition.** Something attractive is left where an
attacker will find it, and you wait. The outbound dialer is the part that is not
really a honeypot — it is cold-calling — and nearly the entire permission burden
of this product sits there.

Treating the two as one thing made ITTU look like it needed Polri before it could
do anything at all. It does not. It needs a phone number.

**What this preserves:** the actual differentiator — *evidence from the
perpetrator's own conversation* rather than from a victim's report — survives the
pivot intact. Everything downstream (extraction, syndicate clustering, TRACE,
TAKEDOWN, UNCOVER) is fed the same way whichever direction the call came from.

---

## 2. Seeding: where a published number actually gets found

Ranked by how clean each is while operating without institutional cover.

### 2.1 Victim hand-off — best, and free

Someone being scammed *right now* gives the scammer a honeypot number instead of
their own: *"pakai nomor ini saja."* The scammer then initiates.

Why it is the strongest channel:

- the scammer chose to call, so we are plainly reactive;
- a real person consented to the redirect, and can say so;
- it arrives **mid-scam**, which is when the account and wallet details are being
  handed over — the highest-value moment in the whole conversation;
- it costs nothing and needs no partner.

This is a natural feature of the public-facing app: *"sedang ditelepon penipu?
berikan nomor ini."* It also gives the public layer something to offer on day one
that does not depend on a database it does not yet have.

### 2.2 Recycled numbers — cheapest start, zero effort

Indonesian numbers churn constantly. A number previously belonging to someone who
was targeted **already receives scam traffic**, with no seeding at all. Buy a
batch, point them at the answer webhook, and listen.

Start here. It needs no partner, no permission and no product work, and within a
fortnight it answers the question that decides everything else: *is inbound
volume real?* It also de-risks the media-bridge build before you pay for it.

### 2.3 Reply to their advertisement — reactive by construction

Scam investment ads, job offers and marketplace listings invite contact.
Responding with a honeypot number keeps the sequence the right way round: **they
made the offer, we answered.**

⚖️ **The line:** replying to an existing offer is reactive. *Posting* a fake offer
to attract an approach is not — it may induce contact that was not otherwise
going to happen, which is precisely what the agent's own guardrail forbids
(`channels.py`: "strictly reactive: never initiates"). Keep the code's rule as the
product's rule.

### 2.4 Harvestable public listings

Scrapers collect numbers from classifieds, job boards and business directories. A
genuine listing carrying a honeypot contact number is picked up by the same
scripts that feed scam operations.

Slower than the above, and the same line applies: the listing should be real
enough not to be itself a deception.

### 2.5 Telco partnership

Ask a carrier for numbers with known high scam-call volume. This needs a
relationship, but it is a **commercial** conversation rather than an authorisation
— it does not belong in the Polri-gated column.

---

## 3. What "answering" requires that is already built

| Piece | Status |
|---|---|
| `POST /api/telephony/voice` — Twilio's answer webhook | built, signature-verified, fails closed |
| `X-Twilio-Signature` verification | built, tested against Twilio's published vector |
| TwiML that answers and opens a media stream | built (`build_stream_twiml`, `wss://` enforced) |
| μ-law codec, frame parsing, turn-taking | built (`media_stream.py`, checked against the stdlib) |
| Persona, multi-turn agent, extraction, clustering | built |
| **WebSocket media bridge** | **not built** — the remaining phase-5 work |
| A Twilio number | **not bought** |

So inbound is two items away, and neither is an approval.

---

## 4. Lines to hold

These are the product's rules, not just the lawyer's:

1. **Reactive only.** The agent replies; it never initiates, never solicits, never
   proposes a transaction. Already enforced in the system prompt and asserted by
   tests — keep the seeding strategy on the same side of that line.
2. **No inducement.** Reply to offers; do not manufacture them (§2.3).
3. ⚖️ **Recording.** We are a party to the call, which is a far better position
   than intercepting one — but whether disclosure is required is a question for
   counsel, and the answer belongs here once it exists.
4. **Authorisation is still worth recording.** Even without Polri, log who
   authorised deploying a number and on what basis. It costs little now and is
   the difference between "we ran a honeypot" and "we ran a honeypot, and here is
   the decision to do so" when someone eventually asks. See
   `Ecosystem-Strategy.md` §7.2.

---

## 5. Recommended sequence

1. **Buy 5–10 recycled numbers**, point them at the answer webhook, measure
   inbound volume for two weeks. No build required.
2. If volume is real → **build the media bridge** (phase 5's remaining half) and
   let the agent hold conversations.
3. **Ship victim hand-off** in the public app — the highest-value channel, and it
   gives that app a reason to exist before it has a database.
4. Keep the outbound dialer built and gated. If authorisation ever arrives it is
   a flag, not a project.

See also: [`Live-Voice-Calls.md`](Live-Voice-Calls.md) (media bridge design),
[`Ecosystem-Strategy.md`](Ecosystem-Strategy.md) (the pivot and its reasoning),
`backend/app/core/gated.py` (what is off, and who can switch it on).
