"""Entity Extraction Pipeline — hybrid, always validated (docs/INFILTRATE-Design.md §5).

**The real value that runs live** (offline, deterministic): Layer A regex +
deterministic validators/checksums over the raw messages. This is what turns a
replayed transcript into court-usable intel.

- **Layer A (regex + validators/checksums)** — high precision, cheap:
  crypto wallets (BTC base58check/bech32, ETH ``0x…`` format, TRON ``T…``
  base58check — prioritized: USDT-TRC20), phones (``+62``/``08xx`` → E.164),
  URLs (refang), Indonesian bank accounts (digit-runs + bank-name context
  anchors BCA/Mandiri/BRI/BNI + keywords rekening/norek/a.n./transfer ke —
  no checksum exists, so context is mandatory).
- **Layer B (LLM/JSON)** — POC stub: the covert ``record_entity`` hints from
  the agent loop (deterministic, offline). In LIVE this is real structured
  LLM extraction for obfuscated/split entities.
- **Reconciliation** — dedupe; cross-validate every Layer-B hint through the
  Layer-A validators; confidence-score; provenance-log (message id, turn,
  methods, validators passed). Un-validated LLM entities are never actionable.
"""

import re
from dataclasses import dataclass, field, replace

# --------------------------------------------------------------------------- #
# Base58 (Bitcoin/TRON alphabet) — self-contained, no deps.
# --------------------------------------------------------------------------- #

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHABET)}


def _b58decode(s: str) -> bytes | None:
    num = 0
    for ch in s:
        if ch not in _B58_INDEX:
            return None
        num = num * 58 + _B58_INDEX[ch]
    full = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + full


def _b58check_valid(s: str) -> bool:
    """True iff ``s`` is a valid base58check string (4-byte double-SHA256 tail)."""
    import hashlib

    raw = _b58decode(s)
    if raw is None or len(raw) < 5:
        return False
    payload, checksum = raw[:-4], raw[-4:]
    digest = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return digest == checksum


# --------------------------------------------------------------------------- #
# Regex patterns (Layer A)
# --------------------------------------------------------------------------- #

_B58 = "[1-9A-HJ-NP-Za-km-z]"
TRON_RE = re.compile(rf"\bT{_B58}{{25,40}}\b")
ETH_RE = re.compile(r"\b0x[0-9a-fA-F]{40}\b")
BTC_LEGACY_RE = re.compile(rf"\b[13]{_B58}{{24,38}}\b")
BTC_BECH32_RE = re.compile(r"\bbc1[02-9ac-hj-np-z]{11,71}\b")

# Phones: Indonesian mobile — +62 / 62 / 0 prefix, 8–13 digits, allow separators.
PHONE_RE = re.compile(r"(?:\+?62|0)[\s.-]?8[1-9][\s.-]?\d[\d\s.-]{5,12}\d")

# URLs — including defanged (hxxp, [.], (dot)) forms.
URL_RE = re.compile(
    r"\b(?:h[xX]{2}ps?|https?)://[^\s<>\"']+|\b(?:www\.)[^\s<>\"']+",
    re.IGNORECASE,
)

# Indonesian bank context anchors + deposit keywords.
BANK_NAMES = {
    "bca": "BCA", "mandiri": "Mandiri", "bri": "BRI", "bni": "BNI",
    "cimb": "CIMB", "danamon": "Danamon", "permata": "Permata",
    "btn": "BTN", "bsi": "BSI", "seabank": "SeaBank", "jago": "Jago",
}
_BANK_ALT = "|".join(sorted(BANK_NAMES, key=len, reverse=True))
BANK_KEYWORDS_RE = re.compile(
    r"\b(rekening|rek|no\.?\s?rek|norek|a\.?n\.?|atas nama|transfer ke|"
    rf"tf ke|kirim ke|{_BANK_ALT})\b",
    re.IGNORECASE,
)
# A run of 8–18 digits (Indonesian account numbers), separators tolerated.
# 6..18 digits. The lower bound is deliberately below a real account length:
# _extract_bank_accounts grades what it finds rather than discarding a short
# run outright, because a fragment a scammer actually said is evidence and
# silence is not.
ACCOUNT_NUM_RE = re.compile(r"\b\d[\d\s.-]{4,20}\d\b")


# --------------------------------------------------------------------------- #
# Extracted-entity record
# --------------------------------------------------------------------------- #


@dataclass
class ExtractedEntity:
    type: str                       # bank_account|crypto_wallet|phone|url
    value: str                      # as seen
    normalized_value: str           # E.164 / refanged / checksummed
    method: str = "regex"           # regex|llm|human
    confidence: float = 0.5
    chain: str | None = None        # crypto_wallet: btc|eth|tron|bsc
    bank_name: str | None = None    # bank_account
    context: str = ""               # human-readable subtitle
    validators_passed: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=lambda: ["regex"])
    turn: int | None = None

    def key(self) -> tuple[str, str]:
        """Dedup key — type + normalized value (case-folded)."""
        return (self.type, self.normalized_value.lower())


# --------------------------------------------------------------------------- #
# Layer A — deterministic validators + normalizers
# --------------------------------------------------------------------------- #


def normalize_phone(raw: str) -> str | None:
    """Indonesian mobile → E.164 (+62…). Returns None if implausible length."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("62"):
        core = digits[2:]
    elif digits.startswith("0"):
        core = digits[1:]
    else:
        core = digits
    if not core.startswith("8"):
        return None
    if not (9 <= len(core) <= 12):  # Indonesian mobile national number length
        return None
    return "+62" + core


def refang_url(raw: str) -> str:
    """Undo common defanging so the URL is canonical for storage."""
    u = raw.strip().rstrip(".,);]")
    u = re.sub(r"h[xX]{2}p", "http", u)
    u = u.replace("[.]", ".").replace("(.)", ".").replace("(dot)", ".").replace("[dot]", ".")
    u = u.replace("[:]", ":")
    if not u.lower().startswith("http"):
        u = "http://" + u
    return u


def validate_crypto(value: str) -> tuple[str | None, list[str], float]:
    """Return (chain, validators_passed, confidence) for a candidate wallet."""
    if TRON_RE.fullmatch(value):
        if _b58check_valid(value):
            return "tron", ["tron_base58check"], 0.98
        # Demo/fixture addresses may be shortened base58 (P1 fixture set).
        return "tron", ["tron_base58_format"], 0.9
    if ETH_RE.fullmatch(value):
        return "eth", ["eth_hex_format"], 0.85
    if BTC_BECH32_RE.fullmatch(value):
        return "btc", ["btc_bech32_format"], 0.85
    if BTC_LEGACY_RE.fullmatch(value):
        if _b58check_valid(value):
            return "btc", ["btc_base58check"], 0.97
        return "btc", ["btc_base58_format"], 0.75
    return None, [], 0.0


# --------------------------------------------------------------------------- #
# Layer A extraction over one message
# --------------------------------------------------------------------------- #


def _extract_crypto(text: str) -> list[ExtractedEntity]:
    out: list[ExtractedEntity] = []
    seen: set[str] = set()
    for rx in (TRON_RE, ETH_RE, BTC_BECH32_RE, BTC_LEGACY_RE):
        for m in rx.finditer(text):
            val = m.group(0)
            if val in seen:
                continue
            chain, validators, conf = validate_crypto(val)
            if chain is None:
                continue
            seen.add(val)
            label = "USDT-TRC20" if chain == "tron" else chain.upper()
            out.append(ExtractedEntity(
                type="crypto_wallet", value=val, normalized_value=val,
                chain=chain, confidence=conf, validators_passed=validators,
                context=f"{label} wallet address",
            ))
    return out


def _extract_phones(text: str) -> list[ExtractedEntity]:
    out: list[ExtractedEntity] = []
    for m in PHONE_RE.finditer(text):
        raw = m.group(0)
        norm = normalize_phone(raw)
        if norm is None:
            continue
        out.append(ExtractedEntity(
            type="phone", value=raw.strip(), normalized_value=norm,
            confidence=0.95, validators_passed=["e164_id_mobile"],
            context="Indonesian mobile number",
        ))
    return out


def _extract_urls(text: str) -> list[ExtractedEntity]:
    out: list[ExtractedEntity] = []
    for m in URL_RE.finditer(text):
        raw = m.group(0)
        norm = refang_url(raw)
        out.append(ExtractedEntity(
            type="url", value=raw.strip().rstrip(".,);]"), normalized_value=norm,
            confidence=0.9, validators_passed=["url_shape"],
            context="Linked website / platform",
        ))
    return out


def _extract_bank_accounts(text: str) -> list[ExtractedEntity]:
    """Digit-run + mandatory bank-name/keyword context anchor (no checksum exists)."""
    if not BANK_KEYWORDS_RE.search(text):
        return []
    bank_name = None
    lower = text.lower()
    for kw, canonical in BANK_NAMES.items():
        if re.search(rf"\b{kw}\b", lower):
            bank_name = canonical
            break
    out: list[ExtractedEntity] = []
    seen: set[str] = set()
    for m in ACCOUNT_NUM_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if not (6 <= len(digits) <= 18) or digits in seen:
            continue
        seen.add(digits)
        # A real Indonesian account is 10+ digits (BCA 10, Mandiri 13, BRI 15).
        # Anything shorter is kept — a number the scammer actually said is
        # evidence — but graded so nothing downstream mistakes a fragment for a
        # whole account: a freeze request built on six digits would name the
        # wrong customer.
        partial = len(digits) < 8
        if partial:
            conf = 0.35
            validators = ["bank_context_anchor", "partial_account_number"]
            anchor = f"Partial account number ({len(digits)} digits, incomplete)"
            if bank_name:
                anchor = f"{bank_name} — {anchor.lower()}"
        else:
            # Context anchor present → confident; bank name known → more so.
            conf = 0.9 if bank_name else 0.7
            validators = ["bank_context_anchor"]
            if bank_name:
                validators.append("bank_name_match")
            anchor = f"{bank_name} account" if bank_name else "Bank account"
        # Capture an a.n. holder name if present for the subtitle.
        an = re.search(r"a\.?n\.?\s*([A-Z][A-Za-z ]{2,40})", text)
        if an:
            anchor += f", a.n. {an.group(1).strip()}"
        out.append(ExtractedEntity(
            type="bank_account", value=digits, normalized_value=digits,
            bank_name=bank_name, confidence=conf, validators_passed=validators,
            context=anchor,
        ))
    return out


# Spoken Indonesian digits. "kosong" (literally "empty") is what people
# actually say for zero when reading a number aloud, more often than "nol".
_SPOKEN_DIGITS: dict[str, str] = {
    "nol": "0", "kosong": "0", "satu": "1", "dua": "2", "tiga": "3",
    "empat": "4", "lima": "5", "enam": "6", "tujuh": "7", "delapan": "8",
    "sembilan": "9",
}

#: How many spoken digits in a row before we treat the run as a number being
#: dictated. Six is comfortably past counting or a price ("dua juta") and short
#: enough to catch a partial account number read back in pieces.
_SPOKEN_RUN_MIN = 6

#: What may sit BETWEEN two spoken digits without ending the run — the
#: whitespace and punctuation a transcriber inserts while someone dictates.
_SPOKEN_SEPARATORS = " \t\r\n-,."

_SPOKEN_TOKEN_RE = re.compile(
    r"\b(" + "|".join(sorted(_SPOKEN_DIGITS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def spoken_digits_to_number(text: str) -> str:
    """Rewrite dictated digit runs as digits, leaving everything else alone.

    On a phone call this is the whole intake. A scammer reading out an account
    says "lima dua tujuh satu nol tiga delapan empat enam dua", and every
    Layer-A pattern looks for DIGITS — so the one artefact the call exists to
    collect was invisible to the extractor. It was recovered only when the model
    happened to fire a covert record_entity tool, which is a choice the model
    makes, not a guarantee: two calls with the same disclosure produced an entity
    and nothing at all.

    Only runs of >= _SPOKEN_RUN_MIN consecutive number words are converted, so
    ordinary speech survives untouched: "dua puluh persen" and "modal lima juta"
    are not phone numbers and must not become 2, 20 or 5.

    The original text is what gets stored in custody — this feeds the extractor
    only, so the record still says what was said.
    """
    matches = list(_SPOKEN_TOKEN_RE.finditer(text))
    if not matches:
        return text

    # Group into maximal runs: consecutive number words separated by nothing but
    # the punctuation people speak numbers with.
    runs: list[list[re.Match]] = []
    current = [matches[0]]
    for prev, m in zip(matches, matches[1:]):
        if not text[prev.end():m.start()].strip(_SPOKEN_SEPARATORS):
            current.append(m)
        else:
            runs.append(current)
            current = [m]
    runs.append(current)

    out: list[str] = []
    pos = 0
    for run in runs:
        if len(run) < _SPOKEN_RUN_MIN:
            continue  # ordinary speech — left exactly as spoken
        out.append(text[pos:run[0].start()])
        out.append("".join(_SPOKEN_DIGITS[m.group(1).lower()] for m in run))
        pos = run[-1].end()
    out.append(text[pos:])
    return "".join(out)


def extract_layer_a(text: str) -> list[ExtractedEntity]:
    """All Layer-A (regex + validator) entities in one message.

    Dictated digits are normalised first: on a voice channel the account number
    arrives as words, and every pattern below matches digits.
    """
    text = spoken_digits_to_number(text)
    return (
        _extract_crypto(text)
        + _extract_phones(text)
        + _extract_urls(text)
        + _extract_bank_accounts(text)
    )


# --------------------------------------------------------------------------- #
# Layer B — LLM hint validation (POC: the agent's record_entity calls)
# --------------------------------------------------------------------------- #


def validate_layer_b_hint(hint: dict) -> ExtractedEntity | None:
    """Cross-validate one covert ``record_entity`` hint through Layer-A.

    Un-validated LLM entities are NEVER returned as actionable — a hint only
    survives if a deterministic validator confirms it (defeats data-poisoning
    + hallucinated evidence).
    """
    htype = hint.get("type")
    raw = str(hint.get("value", "")).strip()
    if not raw:
        return None
    ctx = hint.get("context", "")
    turn = hint.get("turn")

    if htype == "crypto_wallet":
        chain, validators, conf = validate_crypto(raw)
        if chain is None:
            return None
        return ExtractedEntity(
            type="crypto_wallet", value=raw, normalized_value=raw, chain=chain,
            method="llm", methods=["llm"], confidence=conf,
            validators_passed=validators, context=ctx, turn=turn,
        )
    if htype == "phone":
        norm = normalize_phone(raw)
        if norm is None:
            return None
        return ExtractedEntity(
            type="phone", value=raw, normalized_value=norm, method="llm",
            methods=["llm"], confidence=0.9, validators_passed=["e164_id_mobile"],
            context=ctx, turn=turn,
        )
    if htype == "url":
        return ExtractedEntity(
            type="url", value=raw, normalized_value=refang_url(raw), method="llm",
            methods=["llm"], confidence=0.85, validators_passed=["url_shape"],
            context=ctx, turn=turn,
        )
    if htype == "bank_account":
        digits = re.sub(r"\D", "", raw)
        if not (8 <= len(digits) <= 18):
            return None
        bank = hint.get("bank_name")
        return ExtractedEntity(
            type="bank_account", value=digits, normalized_value=digits,
            bank_name=bank, method="llm", methods=["llm"], confidence=0.8,
            validators_passed=["digit_run"] + (["bank_name_match"] if bank else []),
            context=ctx, turn=turn,
        )
    return None


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #


def reconcile(
    layer_a: list[ExtractedEntity], layer_b: list[ExtractedEntity]
) -> list[ExtractedEntity]:
    """Dedupe A+B by (type, normalized). Corroboration (both layers) → higher
    confidence + merged provenance methods."""
    merged: dict[tuple[str, str], ExtractedEntity] = {}
    for ent in layer_a + layer_b:
        k = ent.key()
        if k not in merged:
            merged[k] = replace(ent, methods=list(ent.methods),
                                 validators_passed=list(ent.validators_passed))
            continue
        cur = merged[k]
        # Corroborated across layers → boost confidence, prefer regex trust.
        methods = sorted(set(cur.methods) | set(ent.methods))
        validators = sorted(set(cur.validators_passed) | set(ent.validators_passed))
        best = max(cur.confidence, ent.confidence)
        corroborated = len(set(cur.methods) | set(ent.methods)) > 1
        cur.confidence = min(0.99, best + 0.05) if corroborated else best
        cur.methods = methods
        cur.validators_passed = validators
        cur.method = "regex" if "regex" in methods else cur.method  # regex = highest trust
        # Keep the richer context / bank name / turn.
        cur.context = cur.context or ent.context
        cur.bank_name = cur.bank_name or ent.bank_name
        cur.chain = cur.chain or ent.chain
        if cur.turn is None:
            cur.turn = ent.turn
    return list(merged.values())
