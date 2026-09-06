# ITTU — Ecosystem Strategy & Review

**Status:** review of the proposed three-layer ecosystem, written 2026-09-05 against the
codebase as built. The strategy is the product owner's; this document records what it
would take to execute, what is already true, and the specific places where the plan and
the code currently disagree.

> **Not legal advice.** The regulatory sections name statutes and describe risk so the
> right questions reach a lawyer early. Every item marked ⚖️ needs a qualified opinion
> before the corresponding code is written — not after.

---

## 1. The proposal, in one page

| Layer | Audience | Product | Purpose |
|---|---|---|---|
| **1 — Public (B2C)** | citizens | "CekScam by ITTU" — check bank / e-wallet / crypto before transferring; report scammers | build the database and prove traction |
| **2 — Investigator (B2G/B2B)** | PPATK, OJK, banks, exchanges | the four ITTU modules | the actual product |
| **3 — Regulator (B2G)** | OJK / IASC | ITTU output feeds the IASC pipeline | distribution and legitimacy |

**Network effect:** more B2C users → richer honeypot database → more accurate risk scores →
more efficient investigators → more scammers caught → public trust → more B2C users.

**Positioning:** CekRekening is static and has no crypto; IASC is manual intake; GetContact
is community tagging with no intelligence layer. ITTU proposes to be proactive, crypto-aware
and automated.

### What is strongest about it

The insight that **B2C is not a revenue line — it is evidence of traction** is correct and
is the part most worth protecting. "100,000 checks per month from the public" is a stronger
argument in a PPATK meeting than any deck.

The differentiator is real and precisely stated: conventional systems wait for a victim's
report; ITTU produces **evidence from the perpetrator's own conversation**. That is a
defensible position in a way that account-checking is not — checking is a feature any
incumbent can copy in a quarter.

---

## 2. What is already built (Layer 2)

Unusually for a strategy document, the honeypot flow describes code that exists. Steps 2–5
map onto shipped modules:

| Flow step | Status |
|---|---|
| Persona deployment, multi-turn agent | built (`app/infiltrate/agent.py`, `channels.py`) |
| NER extraction — accounts, wallets, URLs, numbers | built (`intel.entities`, review workflow) |
| Crime classification | built (`intel.crime_classifications`) |
| Syndicate clustering | built (`intel.syndicates`, `syndicate_members`) |
| Feed to TRACE / TAKEDOWN / UNCOVER | built |
| Chain of custody — SHA-256 + timestamps | built, and hash-chained per agency (`core.audit_log`) |
| Docker isolation | built (compose + Render blueprint) |

The gap between Layer 2 as drawn and Layer 2 as built is small. Layers 1 and 3 do not exist.

---

## 3. ⚖️ Three risks that could stop the project

### 3.1 Layer 1 carries legal exposure the plan does not mention

A **private** application that publicly labels a bank account as fraudulent, on the strength
of user reports, is exposed under:

- **UU ITE Pasal 27A** (defamation) — the accused account holder is identifiable;
- **UU PDP (No. 27/2022)** — the reports contain personal data of people who are *not users*
  and have not consented. "Legitimate interest" is a thin basis for publishing an accusation,
  and administrative penalties reach **2% of annual revenue**.

This is the structural reason **CekRekening is operated by Kominfo**: a government body has
statutory cover a startup does not. One wrongly-flagged merchant unable to receive payments
is a lawsuit and a press cycle, and the reputational damage lands on the same brand that is
asking PPATK for trust.

**The premium tier sharpens the problem.** "Notify me if a saved number enters the scam
database" requires ingesting the user's **contact list** — precisely the practice that made
GetContact notorious, and materially harder to justify under PDP than when GetContact did it.

**Recommendation:** obtain a written PDP/ITE opinion **before** Layer 1 is built, and see
§5.1 for a lower-risk way to launch it.

### 3.2 Auto-deploy contradicts Polri supervision — inside the same document

The trigger step says:

> *Auto-detection: nomor muncul 3x+ dalam 24 jam = **auto-deploy honeypot***

The constraints say:

> *Honeypot harus di bawah **supervisi Polri** — agar bukti valid di pengadilan*

**These cannot both hold.** An automated trigger — fired by reports from a *public app* —
that launches a deception operation against a citizen with no human authorisation is the
most legally dangerous element in the design, and it is drawn as a normal step.

It also undermines the evidentiary argument the honeypot exists for: if no accountable
officer authorised the engagement, the resulting evidence is exactly what a defence lawyer
will attack.

**Recommendation:** auto-detection raises a **triage item for a human to authorise**. It
never deploys. The triage queue built in phase 6 is already the right shape for this — the
change is to the diagram, not the architecture.

### 3.3 Layer 3 is an institutional negotiation, not an integration

"Output masuk ke IASC otomatis" reads as an API task. IASC is **OJK's own system**. Accepting
automated writes from a third party requires an MoU, a security review, and a governance
decision inside OJK. Realistically **12–24 months** from first conversation, and it cannot be
scheduled by the engineering team.

**Recommendation:** treat IASC as a distribution goal, not a milestone with a date. Start the
conversation early; do not plan revenue against it.

---

## 4. Where the plan contradicts the code — and the code is right

The flow states:

> *Jika threshold terpenuhi: **Draft LTKM otomatis dibuat**, Notifikasi ke PPATK/OJK/Polri,
> tanpa menunggu korban melapor*

and Layer 2 is summarised as *"otomasi LTKM, pemblokiran, dan notifikasi multi-lembaga"*.

**The system deliberately does not do this,** and the capability model separates the two acts
precisely so it cannot happen by accident:

```
action.generate   draft the freeze request / LTKM   — reversible, nothing leaves
dispatch.send     send it to another agency         — irreversible, human-gated
```

Filing an LTKM is a **regulated act with legal consequences for a false report**. Auto-filing
on a threshold means the first false positive is a wrongly-frozen account and a regulator
asking who authorised it — with the honest answer being "a threshold".

**The accurate claim is stronger, not weaker:** *"draft otomatis, keputusan kirim tetap pada
manusia."* To a bank's compliance officer, "we automate the paperwork and leave you the
decision" is a selling point; "we file automatically" is a reason to refuse the meeting.

**Recommendation:** change the wording everywhere it appears. Nothing in the code needs to
change.

---

## 5. Business model — reality check

| Claim | Assessment |
|---|---|
| **B2C freemium**, Rp 20–50k/mo | Right that revenue is not the point. The premium feature as specified is the PDP-riskiest part of the whole plan (§3.1) |
| **B2B API**, Rp 5–20jt/mo | **Strongest item, and under-prioritised.** No procurement cycle, no public accusation risk, and fintechs have a real pre-transaction screening need. Move earlier |
| **B2B SaaS banks**, Rp 50–200jt/mo × 79 | Aggressive. Banks buy fraud tooling from established vendors (NICE Actimize, Feedzai) with references and audit history. Realistic entry is **1–3 pilots** at a fraction of that, used as proof rather than revenue |
| **B2G license**, Rp 2–5M/yr, 6–18 months | DIPA is planned roughly **T-2**. From first conversation, 24+ months is the honest figure. The revenue is real; the timeline is not |

### 5.1 The sequencing problem

B2C is first *in order to build the database*. But the honeypot — the thing that makes the
database worth having — needs **Polri authorisation**, which needs institutional traction,
which the B2C layer was supposed to provide. So CekScam launches with **no proprietary
intelligence**: a worse CekRekening, without the government's legal cover.

**Ask directly: what does CekScam offer in month one?** If the answer is "user reports", the
product is GetContact with legal exposure and no moat.

**Lead with crypto.** It is the one check that can be delivered immediately and that
CekRekening cannot do at all — TAKEDOWN already scores real TRON addresses against live
chain data. It also **sidesteps most of §3.1**, because a wallet address is not a person:
publishing a risk score for `TR7NHq…` accuses no identifiable individual, where publishing
one for a named bank account does.

---

## 6. Recommendations, in order

1. **Lead Layer 1 with crypto wallet checking.** Add bank-account checking only once §3.1 has
   a legal answer. Immediate capability, real market gap, far lower exposure.
2. **Auto-detection creates a triage item, never auto-deploys.** One word in the diagram; an
   enormous difference in legal posture and in evidentiary strength.
3. **Say "draft otomatis, kirim manual"** in every deck and document. It matches the code and
   it is the better sales line.
4. **Move the B2B API forward**, alongside or ahead of B2C. It is the fastest honest revenue
   and it carries none of the public-accusation risk.
5. **Get the PDP/ITE opinion before writing Layer 1.**
6. **Treat IASC as a goal without a date.** Start the conversation now; plan nothing around it.

---

## 7. Decisions needed — with a recommendation for each

Each of these is the product owner's call. A recommendation is given anyway: an
open question with no proposed answer moves nothing, and disagreeing with a
concrete proposal is faster than composing one from scratch.

### 7.1 What does CekScam offer in month one?

**Recommendation: do not launch consumer checking first.** With crypto now hidden
(`ITTU_CRYPTO_ENABLED=false`), the cold-start problem is unavoidable — a checking
service is only as good as its database, and on day one there is no database.
CekRekening has years of reports; matching it from zero, without Kominfo's legal
cover, is the weakest possible opening.

Invert it: **B2B API first**, sold on honeypot-derived intelligence the platform
generates itself, then open the consumer layer once there is something worth
checking against. Same network effect, started from the end that does not depend
on strangers arriving first.

> **Question that would change this:** is there a data source that seeds the
> database on day one — a bank partner's fraud list, an existing report corpus,
> a scraped public dataset with a lawful basis? If yes, consumer-first works and
> this recommendation is wrong.

### 7.2 Who authorises each honeypot engagement, and where is that recorded?

**Recommendation: model authorisation as an audited action, and make it a
precondition for a LIVE session.** Concretely: a `honeypot.engagement_authorised`
entry naming the officer, the target, and the stated basis (which report or
case), written to the same hash-chained trail as everything else — then a LIVE
session refuses to start without one.

This is a small build on top of what exists, and it is the **single strongest
evidentiary improvement available**. Today the system can prove what the persona
said and that the record was not altered; it cannot prove that anyone authorised
the engagement, which is the first thing a defence lawyer will ask. It also
resolves §3.2 properly: auto-detection can raise the request, and a human grants
it.

> **Question that would change the shape:** does Polri authorisation come
> per-target, per-campaign, or as a standing authority for a unit? Per-target
> means one record per session; standing authority means one record referenced by
> many, with an expiry — a different data model, same principle.

### 7.3 Is there a relationship with Polri, OJK or PPATK today?

**Recommendation: assume cold, and sequence accordingly** — B2B API to fintechs
first. It needs no procurement, no authorisation, and no institutional trust, and
it produces both revenue and a usage story to bring to the first regulator
meeting. "We screen 40,000 transactions a month for three fintechs" opens a door
that a deck does not.

If a relationship already exists, that inverts: run a Layer 2 pilot with the
named unit immediately, because a live pilot with a real agency is worth more
than any amount of B2C traction.

> **Question:** is there a named contact at any of the three, today, who would
> take a meeting? The entire sequencing in §5.1 turns on this one answer.

### 7.4 Does the premium tier survive a PDP review?

**Recommendation: drop the contact-list feature and re-price the tier.** "Notify
me if a saved number enters the database" requires ingesting the user's address
book — third-party personal data, from people who are not users and have not
consented. It is the highest-exposure feature in the plan and it is attached to
the lowest-revenue line, which is a poor trade.

Replace it with paid features that touch only the user's own data: higher check
volume, a personal check history, saved watchlists **the user types in
themselves**, and an API key for small businesses. Same buyer, similar price,
none of the exposure.

> **Question that would change this:** is the notification actually what people
> would pay for, or is it a guess? If user research says the address-book feature
> is the whole value, the tier needs a lawful basis designed in from the start —
> not a retrofit.

### 7.5 Now that crypto is hidden, is §5.1 still the plan?

Hiding crypto (`ITTU_CRYPTO_ENABLED=false`, 2026-09-05) **overrides the
recommendation in §5.1**, which argued for leading with crypto because a wallet
address is not a person.

**Recommendation: keep crypto hidden for the public layer, but keep building it
behind the flag.** The honeypot continues extracting wallet addresses either way,
so the data accrues while the surface stays closed — and TAKEDOWN can be switched
on for a B2G or B2B audience, where the defamation exposure does not apply,
without waiting for a consumer decision.

> **Question:** is crypto hidden because of regulatory uncertainty, because the
> demo audience does not care, or because the data is not ready? Each implies a
> different re-enable trigger, and without one the flag stays off by inertia.

## 8. What this changes in the codebase

Nothing yet. This document exists so the strategy and the system stop disagreeing in public.
The one code-adjacent item is that **honeypot engagement authorisation is not modelled** — if
a human must authorise each deployment (§3.2), that decision should be an audited action with
a named actor, in the same trail as everything else.

See also: [`Voice-Honeypot-Outbound.md`](Voice-Honeypot-Outbound.md) §0 (Polri gating),
[`Security-Evidence.md`](Security-Evidence.md) §5 (honeypot dual-use controls),
[`Backlog.md`](Backlog.md) (the RBAC entry describes the generate/send split).
