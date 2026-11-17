"""Input/output guardrails for the copilot.

* prompt-injection detection (user turns) and neutralisation (tool output, RAG chunks, dashboard context)
* refusal of market-abuse requests (SEBI PFUTP / insider-trading regulations)
* PII / secret redaction before anything reaches an LLM provider (DPDP Act)
* advice filter when ADVICE_ENABLED=false (no SEBI IA/RA registration)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_INPUT_CHARS = 4000
DISCLAIMER = ("Educational information only — not investment advice or a recommendation to buy or sell any security. "
              "Trading involves risk of loss.")

_INJECTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above|earlier|your) (instructions|rules|prompts?|guidelines)|"
    r"disregard (all |the |your )?(previous |prior |system )?(instructions|rules|prompt)|"
    r"forget (all |your )?(previous |prior )?(instructions|rules)|"
    r"(reveal|show|print|repeat|output|leak) (me )?(your|the) (system|hidden|initial|developer) (prompt|instructions|message)|"
    r"\byou are now\b|\bdeveloper mode\b|\bjailbreak|\bDAN\b|act as an? (unfiltered|unrestricted|uncensored)|"
    r"pretend (that )?you have no (rules|restrictions)|override (your|the) (safety|guardrails|rules)|"
    r"</?(system|untrusted|knowledge|dashboard_context)>",
    re.I,
)
_EXFIL = re.compile(r"(reveal|show|print|repeat|output|leak|what is) (me )?(your|the) (system|hidden|initial|developer) (prompt|instructions)", re.I)
_ABUSE = re.compile(
    r"\bspoof(ing)?\b|\blayering\b|front[- ]?run|pump (and|&|n) dump|circular trad|wash trad|"
    r"insider (info|information|tip)|unpublished price sensitive|\bupsi\b|manipulat\w* (the )?(price|market|stock)|"
    r"rig (the )?(price|market)|corner (the )?market|operator (stock|tip)|evade (sebi|surveillance|stt|tax)|"
    r"bypass (the )?(risk|kill switch|rate limit|sebi)|fake (orders|volume)",
    re.I,
)
_ADVICE_REQ = re.compile(
    r"should i (buy|sell|invest|hold|exit|short|add|book)|is \S+( \S+)? a good (buy|investment|stock|time)|"
    r"(recommend|suggest) (me )?(a |some |any )?(stock|share|option|trade)s?|which (stock|share)s? (to|should)|"
    r"best (stock|share|option)s? to (buy|invest|trade)|\btips?\b for (tomorrow|today|intraday)|target price|"
    r"will \S+( \S+)? (go up|rise|fall|crash|rally)|multibagger|sure[- ]?shot|guaranteed (profit|return)",
    re.I,
)
_ADVICE_DIRECTIVE = re.compile(
    r"\b(?:you should|i (?:would )?recommend(?: that you)?|i suggest(?: that)? you|my recommendation is to) "
    r"(buy|sell|short|go long|go short|accumulate|exit)\b", re.I)
_ADVICE_RATING = re.compile(r"\b(strong buy|strong sell|buy now|sell now)\b", re.I)
_ADVICE_GUARANTEE = re.compile(r"\bguaranteed (profit|return)s?\b", re.I)
_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_AADHAAR = re.compile(r"\b[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\b")
_SECRET = re.compile(r"\b(sk|pk|rk|xox[bpa])-[A-Za-z0-9_-]{16,}|\b[A-Za-z0-9_-]{32,}\b|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

ABUSE_REPLY = (
    "I can't help with that. Practices like spoofing, layering, front-running, circular/wash trading, pump-and-dump schemes or "
    "trading on unpublished price-sensitive information are prohibited under SEBI's PFUTP and Insider Trading Regulations and can lead "
    "to penalties and prosecution. I'm happy to help with legitimate approaches instead — for example backtesting a rules-based "
    "strategy, analysing order-flow data that is public (OI, FII/DII flows, bulk deals), or setting up risk limits."
)
EXFIL_REPLY = ("I can't share my internal instructions, but I'm happy to explain what I can do: market data, option analytics, "
               "screeners, strategy drafting and backtests, portfolio analysis and NSE data — all for educational purposes.")


@dataclass
class Verdict:
    text: str
    blocked: bool = False
    reply: str | None = None
    flags: list[str] = field(default_factory=list)


def redact(text: str) -> tuple[str, list[str]]:
    flags = []
    out = text
    for rx, label in ((_PAN, "PAN"), (_AADHAAR, "AADHAAR"), (_SECRET, "SECRET"), (_PHONE, "PHONE"), (_EMAIL, "EMAIL")):
        if rx.search(out):
            out = rx.sub(f"[{label} REDACTED]", out)
            flags.append(f"redacted_{label.lower()}")
    return out, flags


def is_advice_request(text: str) -> bool:
    return bool(_ADVICE_REQ.search(text))


def check_input(text: str) -> Verdict:
    t = (text or "").strip()
    flags: list[str] = []
    if len(t) > MAX_INPUT_CHARS:
        t = t[:MAX_INPUT_CHARS]
        flags.append("truncated")
    t, red = redact(t)
    flags += red
    if _ABUSE.search(t):
        return Verdict(t, blocked=True, reply=ABUSE_REPLY, flags=[*flags, "market_abuse"])
    if _INJECTION.search(t):
        flags.append("prompt_injection")
        if _EXFIL.search(t):
            return Verdict(t, blocked=True, reply=EXFIL_REPLY, flags=flags)
    if is_advice_request(t):
        flags.append("advice_request")
    return Verdict(t, flags=flags)


def neutralise(text: str) -> str:
    """Defang instruction-like content inside untrusted data (tool output, documents, news, dashboard context)."""
    return _INJECTION.sub("[removed: instruction-like text]", text)


def wrap_untrusted(label: str, text: str) -> str:
    return f"<untrusted source=\"{label}\">\n{neutralise(text)}\n</untrusted>"


def filter_output(text: str, advice_enabled: bool) -> tuple[str, list[str]]:
    """Rewrite personalised buy/sell directives into neutral language when advice is disabled."""
    if advice_enabled:
        return text, []
    hits = bool(_ADVICE_DIRECTIVE.search(text) or _ADVICE_RATING.search(text) or _ADVICE_GUARANTEE.search(text))
    if not hits:
        return text, []
    out = _ADVICE_DIRECTIVE.sub(lambda m: f"one possible approach (not a recommendation) is to {m.group(1).lower()}", text)
    out = _ADVICE_RATING.sub("[rating removed]", out)
    out = _ADVICE_GUARANTEE.sub("no guaranteed returns", out)
    return out + "\n\n_" + DISCLAIMER + "_", ["advice_softened"]
