"""Signal C — call & request context: what is being asked, how, and by whom.

Speech is transcribed locally (faster-whisper) on an async lane, one utterance
at a time, so it never blocks the <0.5 s audio scoring loop. Rules flag money
movement, amounts, urgency, secrecy, call-back avoidance, credential requests
and new beneficiaries in English, Hinglish (romanised) and Devanagari, then
combine with the caller's CRM record.

Context is call-level: once a risky request is made it stays on the record for
the rest of the call. Transcripts are held in memory only and never logged.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import numpy as np

from ..config import CFG, ROOT

# ----------------------------------------------------------------- lexicon
# (category, weight, patterns). ASCII patterns get word boundaries; Devanagari
# patterns match as substrings (Python's \b is unreliable around matras).
LEXICON: list[tuple[str, float, list[str]]] = [
    ("transfer", 0.30, [
        r"transfer\w*", r"wire[ds]?", r"remit\w*", r"neft", r"rtgs", r"imps", r"upi",
        r"send (?:the )?(?:money|payment|funds|amount)", r"make (?:a |the )?payment",
        r"pay", r"payments?", r"release (?:the )?(?:payment|funds)",
        r"pais[ae] bhej\w*", r"bhej (?:do|dijiye|dena)", r"transfer kar\w*", r"payment kar\w*",
        "भेज", "ट्रांसफर", "पैसे", "भुगतान", "पेमेंट",
    ]),
    ("urgency", 0.20, [
        r"urgent\w*", r"immediately", r"right now", r"right away", r"asap",
        r"as soon as possible", r"within (?:the next )?\w+ minutes", r"today itself", r"no delay",
        r"(?:very|extremely|really) (?:important|urgent)", r"now,? (?:transfer|pay|send)",
        r"(?:transfer|pay|send)\w*[^.]{0,25}(?<![a-z])now",
        r"abhi", r"turant", r"jaldi", r"fauran", r"isi waqt",
        "अभी", "तुरंत", "जल्दी", "फौरन",
    ]),
    ("secrecy", 0.25, [
        r"confidential", r"(?:don'?t|do not) tell", r"keep (?:this|it) (?:between us|quiet|confidential)",
        r"no one (?:else )?(?:should|must|needs to) know", r"top secret", r"hush",
        r"(?:not|don'?t|never)[^.]{0,20}(?<![a-z])tell (?:anyone|anybody)", r"tell (?:no one|nobody)",
        r"kisi ko (?:mat|nahi|na)", r"kisi ko bhi (?:mat|nahi)",
        "किसी को मत", "किसी को नहीं", "गुप्त",
    ]),
    ("callback_avoid", 0.30, [
        r"(?:don'?t|do not|no need to) (?:call|phone|ring)(?: me)?(?: back)?",
        r"(?:can'?t|cannot|won'?t be able to) (?:talk|take calls)", r"in a meeting",
        r"no time to (?:verify|check|confirm)", r"(?:don'?t|do not) (?:verify|confirm|check)",
        r"call ?back mat\w*", r"phone mat\w*", r"call mat\w*",
        "कॉल बैक मत", "फोन मत", "कॉल मत",
    ]),
    ("credential", 0.45, [
        r"otp", r"one[- ]time password", r"password", r"pin", r"cvv", r"card number",
        r"login (?:details|credentials)", r"net ?banking (?:id|password)",
        "ओटीपी", "पासवर्ड", "पिन",
    ]),
    ("new_beneficiary", 0.25, [
        r"new (?:vendor|account|beneficiary|supplier|bank account)", r"different account",
        r"changed? (?:our|the|their) (?:bank )?account", r"this account instead",
        r"naya account", r"naye account", r"dusre account",
        "नया अकाउंट", "नए अकाउंट", "नए खाते", "नया खाता",
    ]),
    ("unusual_payment", 0.35, [
        r"gift ?cards?", r"crypto\w*", r"bitcoin", r"usdt",
    ]),
    ("threat", 0.30, [
        r"(?:digital )?arrest(?:ed)?", r"police", r"cbi", r"enforcement directorate", r"customs",
        r"narcotics", r"(?:drugs?|contraband) (?:were |was )?found", r"legal action", r"fir", r"(?:arrest )?warrant",
        r"case (?:has been |is )?(?:filed|registered)", r"money laundering",
        r"(?:account|card|sim|number|pan) (?:will be |has been |is being |is )?(?:blocked|suspended|frozen|deactivated)",
        r"giraftaar\w*", "गिरफ्तार", "पुलिस", "केस दर्ज",
    ]),
    ("remote_access", 0.40, [
        # Whisper often hears AnyDesk as "any disk"
        r"any ?d[ei]sk", r"team ?viewer", r"quick ?support", r"rust ?desk", r"screen ?shar\w*",
        r"share (?:your|the) screen", r"(?:install|download) (?:this|an|the|our) app", r"remote (?:access|control)",
    ]),
    ("lure", 0.20, [
        r"lottery", r"you(?:'ve| have)? won", r"prize", r"refund", r"cash ?back", r"lucky draw",
        r"reward points?", r"kbc", r"free gift", r"(?:job|work from home) offer",
    ]),
    ("kyc", 0.25, [
        r"kyc", r"(?:update|verify|complete|link) (?:your )?(?:kyc|pan|aadhaar|aadhar|details)",
        r"aadhaa?r", r"pan card", r"account (?:verification|update)", "केवाईसी", "आधार",
    ]),
    ("stay_on_line", 0.25, [
        r"(?:don'?t|do not) (?:hang up|disconnect|cut the call|put the phone down)",
        r"stay on the (?:line|call)", r"(?:don'?t|do not) (?:talk|speak) to anyone",
        r"phone mat kaat\w*", r"call mat kaat\w*", "फोन मत काट",
    ]),
    ("authority_claim", 0.10, [
        r"this is (?:the )?(?:ceo|cfo|md|director|chairman|your boss)", r"i'?m (?:the )?(?:ceo|cfo|md)",
        r"main (?:ceo|cfo|md|boss)\w*", r"(?:ceo|cfo|md) (?:bol|baat kar) raha", r"on behalf of the (?:ceo|cfo|md)",
        r"(?:this is|i am|i'?m|my name is) (?:\w+ )?(?:inspector|officer|constable|sub[- ]inspector|agent|executive)",
        r"(?:inspector|officer) \w+ (?:from|of)",
        r"(?:calling|speaking) from (?:the )?(?:cbi|police|cyber ?cell|customs|rbi|reserve bank|income tax|trai|"
        r"sbi|hdfc|icici|axis|your bank|bank|head office|fedex|dhl|courier)",
        r"from (?:the )?(?:cbi|cyber ?cell|crime branch|narcotics bureau|income tax department|reserve bank)",
        "सीईओ",
    ]),
]

COMBO_BONUS = 0.20          # transfer + (urgency | secrecy | callback_avoid)

# The classic phone-scam script, in order. "Heading into scam territory" = reaching
# stages before the ask; the dashboard shows these and fusion escalates on them.
STAGES: list[tuple[str, set[str]]] = [
    ("hook", {"authority_claim", "lure", "kyc"}),
    ("pressure", {"urgency", "threat"}),
    ("isolation", {"secrecy", "callback_avoid", "stay_on_line"}),
    ("ask", {"transfer", "credential", "new_beneficiary", "unusual_payment", "remote_access"}),
]
HIGH_AMOUNT_INR = 100_000   # ≥ ₹1 lakh
W_AMOUNT_HIGH, W_AMOUNT_ANY = 0.30, 0.10
W_UNUSUAL_FOR_CALLER = 0.25
W_UNKNOWN_CALLER = 0.10

MULT = {
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7,
    "thousand": 1e3, "k": 1e3, "million": 1e6, "hazar": 1e3, "hazaar": 1e3, "hajar": 1e3,
    "लाख": 1e5, "करोड़": 1e7, "करोड": 1e7, "हज़ार": 1e3, "हजार": 1e3,
}
NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15, "twenty": 20,
    "twenty five": 25, "twenty-five": 25, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "das": 10,
    "pandrah": 15, "bees": 20, "pachees": 25, "pachchees": 25, "pachis": 25, "tees": 30,
    "chalis": 40, "pachaas": 50, "pachas": 50, "sau": 100,
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "दस": 10, "पंद्रह": 15,
    "बीस": 20, "पच्चीस": 25, "तीस": 30, "चालीस": 40, "पचास": 50, "सौ": 100,
}
DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_num = r"\d[\d,]*(?:\.\d+)?"
_words = "|".join(sorted((re.escape(w) for w in NUM_WORDS), key=len, reverse=True))
_mults = "|".join(sorted((re.escape(m) for m in MULT), key=len, reverse=True))
AMOUNT_RES = [
    re.compile(rf"(?P<num>{_num}|{_words})\s*(?P<mult>{_mults})(?![a-z])", re.I),
    re.compile(rf"(?:₹|\brs\.?|\binr)\s*(?P<num>{_num})", re.I),
    re.compile(rf"(?P<num>{_num})\s*(?:rupees|रुपये|रुपए)", re.I),
]

WHISPER_PROMPT = ("Transfer, payment, lakh, crore, rupees, NEFT, RTGS, OTP, urgent, "
                  "abhi, turant, jaldi, account, vendor.")
HALLUCINATIONS = {"thank you.", "thanks for watching!", "thank you for watching.", "you", "."}


def _compile(p: str) -> re.Pattern:
    if p.isascii():
        return re.compile(rf"(?<![a-z])(?:{p})(?![a-z])", re.I)
    return re.compile(re.escape(p))


COMPILED = [(cat, w, [_compile(p) for p in pats]) for cat, w, pats in LEXICON]


def _to_number(tok: str) -> float | None:
    tok = tok.strip().lower().translate(DEV_DIGITS)
    if tok in NUM_WORDS:
        return float(NUM_WORDS[tok])
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def parse_amounts(text: str) -> list[tuple[float, tuple[int, int]]]:
    text = text.translate(DEV_DIGITS)
    found, taken = [], []
    for rx in AMOUNT_RES:
        for m in rx.finditer(text):
            if any(s <= m.start() < e for s, e in taken):
                continue
            n = _to_number(m.group("num"))
            if n is None:
                continue
            mult_tok = m.groupdict().get("mult")
            mult = MULT.get(mult_tok.lower(), 1.0) if mult_tok else 1.0
            found.append((n * mult, m.span()))
            taken.append(m.span())
    return found


def analyse_text(text: str) -> dict:
    """Flags + highlight spans for one utterance."""
    hits: dict[str, float] = {}
    spans: list[dict] = []
    for cat, w, rxs in COMPILED:
        for rx in rxs:
            for m in rx.finditer(text):
                hits[cat] = max(hits.get(cat, 0.0), w)
                spans.append({"start": m.start(), "end": m.end(), "kind": cat})
    amounts = parse_amounts(text)
    for value, (s, e) in amounts:
        spans.append({"start": s, "end": e, "kind": "amount"})
    return {"hits": hits, "amounts": [a for a, _ in amounts], "spans": spans}


# ----------------------------------------------------------------- per call
def load_crm() -> dict:
    try:
        return json.loads(CFG.crm_path.read_text())
    except FileNotFoundError:
        return {"callers": {}}


@dataclass
class ContextState:
    caller_id: str = ""
    crm: dict = field(default_factory=load_crm)
    flags: dict = field(default_factory=dict)       # category -> weight (call-level)
    max_amount: float = 0.0
    utterances: int = 0
    stages: list = field(default_factory=list)      # scam-script stages, in the order reached

    @property
    def caller(self) -> dict | None:
        return self.crm.get("callers", {}).get(self.caller_id)

    def add_utterance(self, text: str) -> dict:
        res = analyse_text(text)
        self.utterances += 1
        for cat, w in res["hits"].items():
            self.flags[cat] = max(self.flags.get(cat, 0.0), w)
        if res["amounts"]:
            self.max_amount = max(self.max_amount, max(res["amounts"]))
        # stages use the raw flags: a spoofed caller ID mustn't hide an authority claim
        for name, cats in STAGES:
            reached = bool(cats & self.flags.keys()) or (name == "ask" and self.max_amount >= HIGH_AMOUNT_INR)
            if reached and name not in self.stages:
                self.stages.append(name)
        return res

    def score(self) -> dict:
        terms = dict(self.flags)
        if self.max_amount >= HIGH_AMOUNT_INR:
            terms["amount_high"] = W_AMOUNT_HIGH
        elif self.max_amount > 0:
            terms["amount"] = W_AMOUNT_ANY
        if "transfer" in terms and ({"urgency", "secrecy", "callback_avoid"} & terms.keys()):
            terms["pressure_combo"] = COMBO_BONUS

        caller = self.caller
        if caller is None:
            if self.caller_id:
                terms["unknown_caller"] = W_UNKNOWN_CALLER
            if "authority_claim" in terms:
                terms["authority_claim"] = self.crm.get("unknown_caller_claims_executive_boost", 0.35)
        else:
            terms.pop("authority_claim", None)  # a registered exec saying who they are is normal
            if ("transfer" in terms or self.max_amount > 0) and \
                    self.max_amount > caller.get("max_usual_amount_inr", 0):
                terms["unusual_for_caller"] = W_UNUSUAL_FOR_CALLER

        c = 1.0 - float(np.prod([1.0 - w for w in terms.values()])) if terms else 0.0
        return {"C": c, "terms": {k: round(v, 2) for k, v in terms.items()},
                "stages": list(self.stages), "max_amount_inr": self.max_amount,
                "caller": caller["name"] if caller else ("unknown" if self.caller_id else None)}


# ----------------------------------------------------------------- ASR lane
class ASR:
    def __init__(self, cfg=CFG):
        from faster_whisper import WhisperModel
        self.language = cfg.asr_language or None
        self.task = cfg.asr_task
        self.model = WhisperModel(cfg.asr_model, device="cpu", compute_type="int8",
                                  cpu_threads=cfg.asr_threads,
                                  download_root=str(ROOT / "models" / "cache" / "whisper"))

    def transcribe(self, audio: np.ndarray) -> tuple[str, str | None]:
        segments, info = self.model.transcribe(
            audio.astype(np.float32), language=self.language, task=self.task, beam_size=1,
            vad_filter=False, condition_on_previous_text=False, without_timestamps=True,
            initial_prompt=WHISPER_PROMPT,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        if text.lower() in HALLUCINATIONS or text.strip() == WHISPER_PROMPT:
            text = ""
        return text, getattr(info, "language", None)
