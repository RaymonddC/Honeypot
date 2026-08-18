# ITTU — Wallet risk scoring: the rules, and what justifies them

**Status:** specification of what the code does **today**, plus an honest register of
what is and isn't justified. Written because the scoring decides *who gets frozen*, and
"why was this wallet scored high?" is the first question defence counsel asks.

The existing `reasoning[]` output explains **which rules fired**. It does not explain
**why those are the rules** — that is what this document is for.

> **Read §4 first if you read nothing else.** Working through the formula's implications
> surfaced a probable defect: a sanctioned wallet with no detected patterns currently
> scores **LOW**.

Implementation: `backend/app/takedown/scoring.py`. Version string on every score:
`takedown-0.1.0/iforest-c0.05+5typologies`.

---

## 1. How a score is produced

Three independent signals combine into one band:

```
  Isolation Forest (anomaly triage, 0..1)          ─┐
  5 deterministic typology detectors (0..5 fired)  ─┼─► composite score ─► low | medium | high
  Attribution tags (scam / sanctioned / mixer)     ─┘
```

```python
score = 0.25 * iso_score + 0.75 * min(fired / 2, 1.0)
if "scam" or "sanctioned" in tags:  score = min(score + 0.25, 1.0)
if "mixer" in tags:                 score = min(score + 0.15, 1.0)

band = "high" if score >= 0.6 else "medium" if score >= 0.3 else "low"
confidence = min(0.5 + 0.15 * fired + 0.1 * (has_tags), 0.95)
```

**One override:** a known exchange address with **no** patterns fired returns `low` with
confidence `0.9`, reasoned as "cash-out destination (subpoena target), not a suspect
wallet". This is the one rule with a clearly articulated rationale in the code, and it is
sound: exchange deposit addresses aggregate thousands of unrelated users.

---

## 2. The constants, and where they came from

**Every value below is an unvalidated default.** They are plausible and internally
consistent, but no record exists of them being derived from labelled data, practitioner
input, or literature. Marking them honestly is the point of this table — retrofitting a
justification would be worse than admitting the gap.

| Constant | Value | What it means | Provenance |
|---|---|---|---|
| `PEEL_FORWARD_SHARE` | 0.7 | a hop forwards ≥70% of inflow | unvalidated default |
| `PEEL_MIN_HOPS` | 2 | ≥2 chained hops before it counts | unvalidated default |
| `RAPID_INOUT_MIN` | 0.95 | near-pure pass-through | unvalidated default |
| `RAPID_RELAY_MIN` | 0.5 | ≥half of inflow forwarded ≤5 min | unvalidated default |
| `STRUCTURING_MIN_CLUSTER` | 3 | ≥3 similar-amount transfers | unvalidated default |
| `STRUCTURING_TOLERANCE` | 0.05 | amounts within ±5% | unvalidated default |
| `FAN_OUT_MIN` | 10 | 1 wallet → 10+ outputs | unvalidated default |
| `CYCLE_LENGTH_BOUND` | 6 | max cycle length searched | **performance bound**, not a risk judgement |
| IF `contamination` | 0.05 | assumes ~5% of wallets are anomalous | unvalidated default |
| IF weight / pattern weight | 0.25 / 0.75 | deterministic signal dominates | **defensible** — see §3 |
| scam/sanctioned uplift | +0.25 | attribution bump | unvalidated |
| mixer uplift | +0.15 | attribution bump | unvalidated |
| band cut-offs | 0.6 / 0.3 | high / medium | unvalidated |

**The one weighting that is defensible on principle:** 0.25 IF + 0.75 detectors. The
Isolation Forest is *triage*, not evidence — it cannot explain itself to a court, and its
score depends on the population of the specific investigation, so the same wallet can
score differently in two cases. Letting it dominate would make the output unexplainable.
Keeping it a minority input, with deterministic detectors carrying the weight, is the
right shape. The exact split (0.25 vs 0.2 or 0.3) is still arbitrary.

---

## 3. What the bands should mean operationally

Currently undefined — the code emits `low|medium|high` and nothing states what an
investigator should *do*. Proposed, to be confirmed with Bareskrim/PPATK practice:

| Band | Meaning | Action |
|---|---|---|
| **high** | multiple independent laundering typologies, or one plus attribution | eligible for a freeze request; still requires human confirmation |
| **medium** | one typology, or strong attribution alone | investigate further; **not** sufficient for a freeze on its own |
| **low** | no typology fired | record only |

**No band should auto-action anything.** Entity confirmation is already
human-in-the-loop and audited (`entity.reviewed`); freezing follows a human decision.
That is what makes the score an input to a case rather than a verdict.

---

## 4. Implications nobody checked — including a probable defect

Working the formula through by hand:

| Anomaly | Patterns fired | Tags | Score | Band |
|---|---|---|---|---|
| 0.0 | 0 | — | 0.000 | LOW |
| 1.0 | 0 | — | 0.250 | LOW |
| 0.0 | 1 | — | 0.375 | MEDIUM |
| 1.0 | 1 | — | 0.625 | HIGH |
| 0.0 | 2 | — | 0.750 | HIGH |
| 0.0 | **3+** | — | **0.750** | HIGH |
| 0.0 | 0 | **sanctioned** | **0.250** | **LOW** ⚠️ |
| 0.0 | 0 | mixer | 0.150 | LOW ⚠️ |
| 0.0 | 1 | sanctioned | 0.625 | HIGH |

**⚠️ Finding 1 — a sanctioned wallet with no detected patterns scores LOW.**
Verified against the real code path, not just the formula:

```python
>>> tag = AddressTagOut(address="T-SANCTIONED", tag="OFAC SDN",
...                     category="sanctioned", source="ofac", confidence=1.0)
>>> composite_risk(iso_score=0.0, patterns=[], tags=[tag])
('low', 0.6, ["Attribution: tagged 'OFAC SDN' (sanctioned, source=ofac, confidence=1.0)."])
```

Note the output **contradicts itself**: the reasoning states the wallet is on the OFAC
SDN list while the band returned is `low`. An investigator reading the band alone gets
the opposite of what the evidence says.

Sanctions status is a *legal fact*, not a probabilistic risk signal to be averaged with
anomaly scores. In most regimes, transacting with a sanctioned address is itself an
offence regardless of whether it launders in a recognisable pattern. A system that files
such an address as "low risk" is wrong in a way that matters, and the same applies to a
known mixer (0.15 → LOW). **Recommendation:** attribution of `sanctioned` should set a
floor on the band, not add a fraction to a score.

**⚠️ Finding 2 — pattern count saturates at 2.** `min(fired / 2, 1.0)` means a wallet
firing all five detectors scores *identically* to one firing two. Deliberate (avoiding
runaway scores), but it discards signal exactly where confidence is highest. Worth
revisiting alongside the band cut-offs. Note `confidence` does keep climbing with
`fired`, so the distinction survives — just not in the band.

**Finding 3 — attribution alone cannot reach HIGH.** Sanctioned + mixer + maximum anomaly
reaches 0.65; sanctioned alone cannot. Consistent with "detectors carry the weight", but
it interacts badly with Finding 1.

---

## 5. What validation would require

None of the above is settled until it is checked against reality:

1. **A labelled set** — wallets with known outcomes (confirmed fraud, confirmed benign,
   exchange, mixer). Sources: closed Bareskrim cases, public sanctions lists, known
   exchange deposit addresses.
2. **Report precision/recall per band**, not overall accuracy. In this domain a false
   HIGH (an innocent account frozen) and a false LOW (a mule missed) have very different
   costs, and one aggregate number hides both.
3. **Sensitivity check** — re-run with each threshold at ±20% and see which ones actually
   move the outcome. Thresholds that change nothing can be simplified away; ones that
   swing results need the strongest justification.
4. **Record the result against `MODEL_VERSION`**, so a score produced months ago can be
   traced to the rules and evidence in force at the time — the same reasoning as the
   audit trail's snapshots.

---

## 6. Governance

- **`MODEL_VERSION` must change whenever any constant here changes.** It is already
  stamped on every `WalletScore`, so historic scores stay attributable — but only if it
  is actually bumped. Treat it as part of the change, not an afterthought.
- **Config vs constants:** these live in code today. Tunable config would let an operator
  quietly change what triggers a freeze with no review; code + version bump + this
  document keeps a change reviewable. **Recommendation: keep them constants** until
  there's a concrete need, then make the tunables explicit and audited.
- **Owner:** unassigned. Someone must own these numbers before a real deployment — an
  unowned threshold is one nobody can defend under questioning.

---

## 7. Open decisions

- [ ] **Finding 1** — should `sanctioned` set a band floor rather than add +0.25? (My
      recommendation: yes.)
- [ ] Confirm the §3 band→action mapping with actual investigator practice.
- [ ] Assign an owner for the constants.
- [ ] Decide whether `wallet_risk_scores.wallet_id` should become NOT NULL (a related
      product decision recorded in `Backlog.md`).
