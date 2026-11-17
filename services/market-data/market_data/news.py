"""News: RSS ingestion helpers, lexicon sentiment, ticker tagging and a deterministic offline generator."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from algo_common.timeutils import now_ist
from market_data.universe import EQUITIES, INDICES

POSITIVE = {
    "surge", "surges", "soar", "soars", "rally", "rallies", "jump", "jumps", "gain", "gains", "rise", "rises", "beat", "beats", "record",
    "upgrade", "upgrades", "outperform", "bullish", "profit", "growth", "strong", "robust", "wins", "win", "order", "orders", "approval",
    "expands", "expansion", "dividend", "buyback", "bonus", "inflows", "high", "highs", "positive", "boost", "boosts", "recovery",
}
NEGATIVE = {
    "fall", "falls", "plunge", "plunges", "slump", "slumps", "drop", "drops", "decline", "declines", "miss", "misses", "loss", "losses",
    "downgrade", "downgrades", "bearish", "weak", "probe", "penalty", "fine", "fraud", "default", "outflows", "low", "lows", "cut",
    "cuts", "concern", "concerns", "pressure", "selloff", "sell-off", "slowdown", "negative", "resigns", "raid", "ban", "crash",
}
_NEG_PHRASES = ("lower than expected", "below estimates", "margin pressure", "profit booking", "weak guidance")
_POS_PHRASES = ("higher than expected", "above estimates", "record high", "all-time high", "strong guidance")


def sentiment(text: str) -> tuple[str, float]:
    """Lexicon sentiment in [-1, 1] with a neutral band (offline fallback for the AI summariser)."""
    low = text.lower()
    words = re.findall(r"[a-z-]+", low)
    pos = sum(w in POSITIVE for w in words) + 2 * sum(p in low for p in _POS_PHRASES)
    neg = sum(w in NEGATIVE for w in words) + 2 * sum(p in low for p in _NEG_PHRASES)
    if pos == neg == 0:
        return "neutral", 0.0
    score = (pos - neg) / (pos + neg)
    label = "positive" if score > 0.2 else "negative" if score < -0.2 else "neutral"
    return label, round(score, 3)


_NAME_INDEX: list[tuple[re.Pattern[str], str]] | None = None


def tag_tickers(text: str) -> list[str]:
    """Canonical symbols mentioned by ticker or company name."""
    global _NAME_INDEX
    if _NAME_INDEX is None:
        idx = []
        for a in EQUITIES:
            names = {a.tradingsymbol, a.name, a.name.replace(" Ltd", "").replace(" Limited", "")}
            short = a.name.split(" ")[0]
            if len(short) > 4 and short.lower() not in {"tata", "state", "bajaj", "hindustan", "indian", "power", "adani", "mahindra"}:
                names.add(short)
            idx.append((re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")\b"), a.symbol))
        _NAME_INDEX = idx
    found = [sym for rx, sym in _NAME_INDEX if rx.search(text)]
    if re.search(r"\b(Nifty|Sensex)\b", text):
        found.append("NSE_INDEX:NIFTY" if "Nifty" in text else "BSE_INDEX:SENSEX")
    return list(dict.fromkeys(found))[:8]


@dataclass
class Article:
    source: str
    url: str
    title: str
    summary: str = ""
    published_at: datetime = field(default_factory=now_ist)
    category: str = "news"
    tickers: list[str] = field(default_factory=list)
    sentiment: str = "neutral"
    sentiment_score: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "url": self.url, "title": self.title, "summary": self.summary,
                "published_at": self.published_at.isoformat(), "category": self.category, "tickers": self.tickers,
                "sentiment": self.sentiment, "sentiment_score": self.sentiment_score}


def enrich(a: Article) -> Article:
    text = f"{a.title}. {a.summary}"
    a.sentiment, a.sentiment_score = sentiment(text)
    if not a.tickers:
        a.tickers = tag_tickers(text)
    return a


def parse_feed(raw: bytes | str, source: str) -> list[Article]:
    import feedparser

    feed = feedparser.parse(raw)
    out: list[Article] = []
    for e in feed.entries[:60]:
        link = getattr(e, "link", None)
        title = re.sub(r"\s+", " ", getattr(e, "title", "")).strip()
        if not link or not title:
            continue
        summary = re.sub(r"<[^>]+>", " ", getattr(e, "summary", "") or "")
        summary = re.sub(r"\s+", " ", summary).strip()[:800]
        ts = now_ist()
        if getattr(e, "published_parsed", None):
            ts = datetime(*e.published_parsed[:6], tzinfo=UTC)  # feedparser normalises to UTC
        out.append(enrich(Article(source=source, url=link, title=title, summary=summary, published_at=ts)))
    return out


# ---------------------------------------------------------------- offline generator

_TEMPLATES = [
    ("{name} shares rise after strong quarterly results beat estimates", "results"),
    ("{name} wins large order, stock gains in early trade", "news"),
    ("Brokerage upgrades {name} to outperform on margin recovery", "news"),
    ("{name} board to consider dividend and bonus issue", "announcement"),
    ("{name} slips as quarterly profit misses estimates on margin pressure", "results"),
    ("{name} under pressure after regulator imposes penalty", "news"),
    ("{name} announces capacity expansion plan worth crores", "announcement"),
    ("Analysts see limited upside for {name} after recent rally", "news"),
    ("{name} shares fall as promoter sells stake via block deal", "news"),
    ("{name} hits 52-week high on robust volume", "news"),
]
_MACRO = [
    ("Nifty ends flat as banks offset IT weakness; India VIX eases", "economy"),
    ("FIIs turn net buyers for third straight session; DIIs book profits", "economy"),
    ("RBI keeps repo rate unchanged, retains neutral stance", "economy"),
    ("India's GST collections rise on strong festive demand", "economy"),
    ("Rupee weakens against dollar on crude oil surge", "economy"),
    ("Sensex, Nifty slump as global cues turn negative", "economy"),
    ("Manufacturing PMI rises to multi-month high", "economy"),
    ("Crude oil prices drop on demand concerns; OMC stocks gain", "economy"),
]


def _h(*p: object) -> int:
    return int(hashlib.sha1("|".join(map(str, p)).encode()).hexdigest()[:8], 16)  # noqa: S324


def mock_articles(symbol: str | None = None, count: int = 12, day: datetime | None = None) -> list[Article]:
    """Deterministic per day, so refreshes don't reshuffle the feed."""
    now = day or now_ist()
    key = now.strftime("%Y%m%d")
    pool = [a for a in EQUITIES if symbol is None or a.symbol == symbol] or EQUITIES[:1]
    out: list[Article] = []
    for i in range(count):
        if symbol is None and i % 3 == 2:
            title, cat = _MACRO[_h(key, "m", i) % len(_MACRO)]
            tickers = ["NSE_INDEX:NIFTY"] if "Nifty" in title or "Sensex" in title else []
        else:
            a = pool[_h(key, "s", i) % len(pool)]
            tpl, cat = _TEMPLATES[_h(key, a.symbol, i) % len(_TEMPLATES)]
            title, tickers = tpl.format(name=a.name), [a.symbol]
        ts = now.replace(second=0, microsecond=0) - timedelta(minutes=17 * i + _h(key, i) % 13)
        url = f"https://news.example.invalid/{key}/{_h(title, i):x}"
        src = ["Market Wire", "Business Desk", "Exchange Feed", "Street Journal"][_h(url) % 4]
        out.append(enrich(Article(source=src, url=url, title=title, summary=f"{title}. (Sample headline generated offline — configure NEWS_RSS_FEEDS for live news.)",
                                  published_at=ts, category=cat, tickers=tickers)))
    return out


INDEX_NAMES = [a.tradingsymbol for a in INDICES]


# ---------------------------------------------------------------- economic calendar (indicative)

_RBI_MPC_MONTHS = (2, 4, 6, 8, 10, 12)  # bi-monthly policy meetings; decision on the final day
_FOMC_MONTHS = (1, 3, 5, 6, 7, 9, 10, 12)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d + timedelta(days=7 * (n - 1))


def _weekday_on_or_before(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def economic_calendar(start: date, days: int = 45) -> list[dict[str, Any]]:
    """Indicative schedule of recurring macro events that move Indian markets.

    Dates follow the usual release pattern (e.g. CPI on the 12th, RBI MPC decisions in the first week of
    even months, GDP at the end of the quarter's second month); always verify against official calendars."""
    end = start + timedelta(days=days)
    out: list[dict[str, Any]] = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        evs: list[tuple[date, str, str, str]] = [
            (_weekday_on_or_before(date(y, m, 12)), "India CPI inflation (YoY)", "IN", "high"),
            (_weekday_on_or_before(date(y, m, 14)), "India WPI inflation", "IN", "medium"),
            (_weekday_on_or_before(date(y, m, 28)), "India IIP / core sector output", "IN", "medium"),
            (_nth_weekday(y, m, 4, 1) if m != 1 else _nth_weekday(y, m, 4, 2), "US non-farm payrolls", "US", "high"),
            (_weekday_on_or_before(date(y, m, 13)), "US CPI", "US", "high"),
            (date(y, m, 1) if date(y, m, 1).weekday() < 5 else _nth_weekday(y, m, 0, 1), "GST collections & auto sales", "IN", "medium"),
        ]
        if m in _RBI_MPC_MONTHS:
            evs.append((_nth_weekday(y, m, 2, 1) + timedelta(days=2), "RBI monetary policy decision", "IN", "high"))
        if m in _FOMC_MONTHS:
            evs.append((_nth_weekday(y, m, 2, 3), "US FOMC rate decision", "US", "high"))
        if m in (2, 5, 8, 11):
            evs.append((_weekday_on_or_before(date(y, m, 28)), "India GDP (quarterly)", "IN", "high"))
        if m == 2:
            evs.append((date(y, 2, 1), "Union Budget", "IN", "high"))
        for d, title, country, impact in evs:
            if start <= d <= end:
                out.append({"date": d.isoformat(), "title": title, "country": country, "impact": impact, "indicative": True})
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return sorted(out, key=lambda e: (e["date"], e["country"] != "IN"))
