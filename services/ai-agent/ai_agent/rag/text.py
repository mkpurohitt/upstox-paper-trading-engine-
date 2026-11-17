"""Tokenisation, token counting and semantic chunking."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

STOPWORDS = frozenset(
    "a an and are as at be but by can do does for from has have how i if in into is it its me my of on or our so than that the "
    "their them then there these they this to was we what when where which while who why will with you your about explain tell "
    "please give show".split()
)
_WORD = re.compile(r"[a-z0-9][a-z0-9&/.%-]*[a-z0-9%]|[a-z0-9]")


def _stem(w: str) -> str:
    """Tiny suffix stripper; the same function is applied to documents and queries, so consistency matters more than linguistics."""
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith("sses"):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    for suf in ("ations", "ation", "ings", "ing", "edly", "ed", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    out: list[str] = []
    for t in _WORD.findall(text.lower()):
        parts = [t, *(p for p in re.split(r"[-/]", t) if p and p != t)] if ("-" in t or "/" in t) else [t]
        out.extend(_stem(p) for p in parts if keep_stopwords or p not in STOPWORDS)
    return out


def count_tokens(text: str) -> int:
    """Approximate BPE token count (≈1.3 tokens per word, punctuation counted)."""
    return int(len(re.findall(r"\w+", text)) * 1.3 + len(re.findall(r"[^\w\s]", text)) * 0.3) + 1


@dataclass
class Chunk:
    content: str
    token_count: int
    meta: dict[str, Any] = field(default_factory=dict)


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'*\[-])")


def _sections(text: str) -> list[tuple[list[str], list[str]]]:
    """Split markdown into (heading_path, paragraphs)."""
    path: list[str] = []
    out: list[tuple[list[str], list[str]]] = []
    paras: list[str] = []
    buf: list[str] = []

    def flush_para() -> None:
        if buf:
            p = "\n".join(buf).strip()
            if p:
                paras.append(p)
            buf.clear()

    for line in text.replace("\r\n", "\n").split("\n"):
        m = _HEADING.match(line)
        if m:
            flush_para()
            if paras:
                out.append((list(path), list(paras)))
                paras.clear()
            level = len(m.group(1))
            path[:] = [*path[: level - 1], m.group(2).strip()]
            continue
        if not line.strip():
            flush_para()
        else:
            buf.append(line)
    flush_para()
    if paras:
        out.append((list(path), list(paras)))
    return out


def semantic_chunks(text: str, *, title: str | None = None, target_tokens: int = 800, overlap_tokens: int = 100) -> list[Chunk]:
    """Heading-aware chunking: never mixes sections, packs paragraphs (then sentences) up to ~target tokens,
    and carries ~overlap tokens of trailing sentences into the next chunk of the same section."""
    chunks: list[Chunk] = []
    for path, paras in _sections(text):
        trail = path[1:] if title and path and path[0].strip().lower() == title.strip().lower() else path
        heading = " › ".join([*([title] if title else []), *trail])
        units: list[str] = []
        for p in paras:
            if count_tokens(p) <= target_tokens:
                units.append(p)
            else:
                units.extend(s for s in _SENT.split(p) if s.strip())
        cur: list[str] = []
        cur_tok = 0
        for u in units:
            ut = count_tokens(u)
            if cur and cur_tok + ut > target_tokens:
                chunks.append(_mk(cur, heading, path))
                # overlap: trailing sentences of the previous chunk
                tail: list[str] = []
                tt = 0
                for s in reversed(_SENT.split(" ".join(cur))):
                    st = count_tokens(s)
                    if tt + st > overlap_tokens:
                        break
                    tail.insert(0, s)
                    tt += st
                cur, cur_tok = ([" ".join(tail)] if tail else []), tt
            cur.append(u)
            cur_tok += ut
        if cur:
            chunks.append(_mk(cur, heading, path))
    # merge tiny trailing chunks into their predecessor within the same heading
    merged: list[Chunk] = []
    for c in chunks:
        if merged and c.token_count < 60 and merged[-1].meta.get("heading") == c.meta.get("heading") \
                and merged[-1].token_count + c.token_count <= target_tokens * 1.2:
            prev = merged[-1]
            prev.content += "\n\n" + c.content.split("\n", 1)[-1]
            prev.token_count = count_tokens(prev.content)
        else:
            merged.append(c)
    for i, c in enumerate(merged):
        c.meta["ordinal"] = i
    return merged


def _mk(units: list[str], heading: str, path: list[str]) -> Chunk:
    body = "\n\n".join(units).strip()
    content = f"{heading}\n{body}" if heading else body
    return Chunk(content=content, token_count=count_tokens(content), meta={"heading": heading, "section": path[-1] if path else None})


def best_snippet(content: str, query: str, max_chars: int = 260) -> str:
    """The sentence (window) of `content` that best matches the query terms (markdown emphasis stripped)."""
    body = content.split("\n", 1)[-1] if "\n" in content else content
    body = re.sub(r"\*\*|__|`", "", body)
    sents = [s.strip() for s in _SENT.split(" ".join(body.split())) if s.strip()]
    if not sents:
        return body[:max_chars]
    q = set(tokenize(query))
    best = max(range(len(sents)), key=lambda i: (len(q & set(tokenize(sents[i]))), -i))
    snip = sents[best]
    if len(snip) < 120 and best + 1 < len(sents):
        snip += " " + sents[best + 1]
    return snip if len(snip) <= max_chars else snip[: max_chars - 1].rsplit(" ", 1)[0] + "…"
