"""Embedding providers. The default hashing embedder is deterministic, offline and dependency-free."""

from __future__ import annotations

import hashlib
import itertools
import math
from abc import ABC, abstractmethod
from collections import Counter
from functools import lru_cache

import httpx

from ai_agent.rag.text import tokenize
from algo_common.settings import get_settings


class Embedder(ABC):
    name: str = "base"
    dim: int = 384

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalise(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _fit(v: list[float], dim: int) -> list[float]:
    """Truncate or zero-pad to the column dimension, then re-normalise."""
    return _normalise((v + [0.0] * dim)[:dim])


class HashingEmbedder(Embedder):
    """Signed feature hashing of stemmed unigrams + bigrams (+ char 4-grams for robustness to inflections/typos)."""

    name = "hashing"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        toks = tokenize(text)
        feats: Counter[str] = Counter()
        for t in toks:
            feats["u:" + t] += 1.0
            if len(t) > 5:
                for i in range(len(t) - 3):
                    feats["c:" + t[i:i + 4]] += 0.15
        for a, b in itertools.pairwise(toks):
            feats[f"b:{a}_{b}"] += 0.7
        v = [0.0] * self.dim
        for f, w in feats.items():
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
            sign = -1.0 if (h >> 63) & 1 else 1.0  # signed hashing keeps collisions unbiased
            weight = 1.0 + math.log(w) if w >= 1 else w  # sub-linear term frequency
            v[h % self.dim] += sign * weight
        return _normalise(v)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class OpenAICompatEmbedder(Embedder):
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str, dim: int) -> None:
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=30.0, max_retries=1)
        self.model, self.dim = model, dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            res = await self.client.embeddings.create(model=self.model, input=texts[i:i + 64], dimensions=self.dim)
            out += [_fit(list(d.embedding), self.dim) for d in res.data]
        return out


class OllamaEmbedder(Embedder):
    name = "ollama"

    def __init__(self, base_url: str, model: str, dim: int) -> None:
        self.base_url, self.model, self.dim = base_url.rstrip("/"), model, dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(f"{self.base_url}/api/embed", json={"model": self.model, "input": texts})
            r.raise_for_status()
            return [_fit(list(v), self.dim) for v in r.json()["embeddings"]]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    s = get_settings()
    if s.embedding_provider == "openai_compat" and s.llm_primary_base_url and s.llm_primary_api_key:
        return OpenAICompatEmbedder(s.llm_primary_base_url, s.llm_primary_api_key.get_secret_value(), s.embedding_model, s.embedding_dim)
    if s.embedding_provider == "ollama":
        return OllamaEmbedder(s.ollama_base_url, s.embedding_model, s.embedding_dim)
    return HashingEmbedder(s.embedding_dim)
