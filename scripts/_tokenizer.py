"""Shared tokenizer + BM25 constants for build-index.py / search-fulltext.py.

Keep one source of truth so indexed and queried tokens stay in sync.
"""

from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]+|\d+")
# Match runs of CJK *letters*; anything else acts as a token boundary so we
# don't emit cross-phrase bigrams like "館情" from "図書館 と 情報学".
# Written with explicit escapes: a previous literal range used 豈 (U+8C48, a
# homoglyph of compatibility ideograph U+F900), silently extending the class
# to U+8C48-U+FAFF and matching Hangul. Punctuation inside the kana blocks
# (・ U+30FB, ゠ U+30A0, ゛゜ U+309B-C, combining marks) is excluded so every
# bigram survives FTS5 unicode61 as a single term (see check-tokenizer-drift).
CJK_RUN = re.compile(
    "["
    "\u3041-\u3096"  # hiragana (small-a .. ke)
    "\u309d-\u309f"  # hiragana iteration marks + digraph
    "\u30a1-\u30fa"  # katakana (small-a .. vo)
    "\u30fc-\u30ff"  # prolonged sound mark + iteration marks + digraph
    "\u3400-\u9fff"  # CJK ext A + unified ideographs
    "\uf900-\ufaff"  # CJK compatibility ideographs
    "]+"
)

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
