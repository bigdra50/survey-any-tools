#!/usr/bin/env python3
"""Detect drift between scripts/_tokenizer.py and viewer/functions/lib/tokenizer.ts.

The Python tokenizer produces the indexed tokens (sync-content), the TS port
produces the query tokens (/api/search). Any divergence silently degrades
search recall, so this check compares both implementations token-by-token on
edge cases plus a sample of the real corpus, and verifies that FTS5's
unicode61 tokenizer (as configured in migrations/0002) preserves each
pre-tokenized token as a single term.

Exit codes:
  0 — no drift
  1 — drift detected (or harness failure)
  2 — usage / internal error
  3 — skipped (bun not installed)
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tokenizer import tokenize  # noqa: E402
from _root import content_root  # noqa: E402

ROOT = content_root()
HARNESS = ROOT / "scripts" / "tokenizer-harness.ts"
CORPUS_SAMPLE_SIZE = 20
CORPUS_TRUNCATE_CHARS = 3000
FTS5_TOKENIZE = "unicode61 tokenchars '-_'"

EDGE_CASES: list[str] = [
    "",
    "   \n\t  ",
    "hello world hello",
    "MixedCASE Text LOWERing",
    "foo-bar baz_qux snake_case_name",
    "a-b c_d",  # 3-char hyphen/underscore tokens
    "the and for with from this that",  # all stopwords
    "a I x 9",  # single chars / single digit dropped
    "42 007 12345",
    "2026-07-07 v0.1.0",
    "１２３ ４５ ６",  # full-width digits (Unicode Nd)
    "図書館情報学",
    "図書館 と 情報学",
    "図書館と情報学",  # と joins the CJK run
    "トークナイザーの検証",  # long vowel mark ー is in the katakana block
    "ひらがな カタカナ 漢字 mixed English",
    "Unity で XR開発 を行う",
    "㐀㐁 ext-A pair",
    "豈 single compatibility ideograph",
    "図 单 one-char runs",
    "한국어 Korean is outside the CJK ranges",
    "αβγ Greek letters",
    "café naïve résumé",
    "İstanbul lowering edge",
    "ｶﾀｶﾅ halfwidth forms are outside the ranges",
    "🚀 rocket 図鑑 emoji boundary",
    "under_score-and-hyphen mix9",
    "BM25 k1 b075 scoring",
    "quote\"inside and 'single'",
    "tabs\tand\nnewlines 分割",
]


def load_corpus_sample() -> list[str]:
    """First N topic/reference bodies (truncated) as realistic drift inputs."""
    paths = sorted(ROOT.glob("topics/*/README.md"))[: CORPUS_SAMPLE_SIZE // 2]
    paths += sorted(ROOT.glob("references/*.md"))[: CORPUS_SAMPLE_SIZE - len(paths)]
    return [p.read_text(encoding="utf-8")[:CORPUS_TRUNCATE_CHARS] for p in paths]


def run_ts_tokenizer(texts: list[str]) -> list[list[str]] | None:
    """Tokenize via bun harness; None means the harness itself failed."""
    proc = subprocess.run(
        ["bun", str(HARNESS)],
        input=json.dumps(texts),
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
    )
    if proc.returncode != 0:
        print(f"harness failed (rc={proc.returncode}): {proc.stderr.strip()[:500]}", file=sys.stderr)
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print(f"harness output is not JSON: {exc}", file=sys.stderr)
        return None


def compare_tokenizers(texts: list[str], ts_results: list[list[str]]) -> int:
    drift = 0
    for text, ts_tokens in zip(texts, ts_results):
        py_tokens = tokenize(text)
        if py_tokens != ts_tokens:
            drift += 1
            preview = text[:60].replace("\n", "\\n")
            print(f"DRIFT on {preview!r}")
            print(f"  py: {py_tokens[:20]}")
            print(f"  ts: {ts_tokens[:20]}")
    return drift


def verify_fts5_round_trip(texts: list[str]) -> int:
    """Every pre-tokenized token must survive unicode61 as a single FTS5 term."""
    tokens = sorted({t for text in texts for t in tokenize(text)})
    if not tokens:
        return 0
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute(f'CREATE VIRTUAL TABLE t USING fts5(tokens, tokenize = "{FTS5_TOKENIZE}")')
        conn.execute("CREATE VIRTUAL TABLE tv USING fts5vocab(t, 'row')")
    except sqlite3.OperationalError as exc:
        print(f"note: local sqlite3 lacks FTS5 ({exc}); round-trip sub-check skipped")
        return 0
    conn.execute("INSERT INTO t VALUES (?)", (" ".join(tokens),))
    stored = {row[0] for row in conn.execute("SELECT term FROM tv")}
    missing = [t for t in tokens if t not in stored]
    for t in missing[:10]:
        print(f"FTS5 SPLIT: token {t!r} does not survive unicode61 as one term")
    return len(missing)


def main() -> int:
    if shutil.which("bun") is None:
        print("SKIP: bun is not installed (tokenizer drift check needs the TS harness)")
        return 3

    texts = EDGE_CASES + load_corpus_sample()
    ts_results = run_ts_tokenizer(texts)
    if ts_results is None or len(ts_results) != len(texts):
        return 1

    drift = compare_tokenizers(texts, ts_results)
    split = verify_fts5_round_trip(texts)

    if drift or split:
        print(f"FAIL: {drift} drifting input(s), {split} FTS5-split token(s)")
        return 1
    print(f"ok: {len(texts)} inputs tokenized identically (py == ts), FTS5 round-trip clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
