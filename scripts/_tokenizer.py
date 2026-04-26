"""Shared tokenizer + BM25 constants for build-index.py / search-fulltext.py.

Keep one source of truth so indexed and queried tokens stay in sync.
"""

from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]+|\d+")
# Match runs of CJK characters; non-CJK acts as a token boundary so we don't
# emit cross-phrase bigrams like "館情" from "図書館 と 情報学".
CJK_RUN = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]+")
STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "this", "that", "are", "was", "but",
        "you", "your", "have", "has", "had", "not", "all", "any", "can",
    }
)

BM25_K1 = 1.5
BM25_B = 0.75


def tokenize(text: str) -> list[str]:
    """ASCII word tokens + CJK 2-grams within each run."""
    text = text.lower()
    out: list[str] = []
    for m in TOKEN_RE.findall(text):
        if len(m) >= 2 and m not in STOPWORDS:
            out.append(m)
    for run in CJK_RUN.findall(text):
        for i in range(len(run) - 1):
            out.append(run[i : i + 2])
    return out
