#!/usr/bin/env python3
"""Sync repo content into the D1 `documents` (+ `documents_fts`) tables.

Feeds the read-only content API (/api/search, /api/fm, /api/content/*).
Collects topics / references / wiki / courses / lessons, diffs against the
synced state by content hash, and applies only the delta via
`wrangler d1 execute --file`.

Robustness decisions:
  - String payloads (title / frontmatter / body / tokens) are emitted as
    hex blob casts `CAST(X'..' AS TEXT)` so the generated SQL contains no
    quotes, newlines, or semicolons inside literals — immune to statement
    splitting and escaping bugs.
  - Long payloads are chunked (`UPDATE .. SET col = col || ..`) to stay
    under D1's 100KB-per-statement limit.
  - D1 cannot run explicit transactions, so per-document statement order is
    "DELETE fts row -> upsert documents -> INSERT fts FROM documents":
    idempotent, and a partial failure self-heals on re-run (or --full).

Usage:
  python3 -m survey_any sync-content --local [--dry-run] [--full]
  python3 -m survey_any sync-content --remote [--dry-run] [--full]

Env:
  WRANGLER_BIN  wrangler invocation (default "wrangler"; e.g. "npx -y wrangler@4")
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Final, TypedDict

from survey_any._frontmatter import parse_frontmatter, split_frontmatter
from survey_any._tokenizer import tokenize
from survey_any._root import content_root

ROOT: Final[Path] = content_root()
DB_NAME: Final[str] = "survey-any-progress"

# Hex literal doubles the byte count; 35KB payload -> ~70KB statement,
# comfortably under D1's 100KB-per-statement limit.
MAX_CHUNK_UTF8_BYTES: Final[int] = 35_000

# key/name/path are interpolated as plain quoted literals -> keep them boring.
_SAFE_LITERAL_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._:/-]+$")


class DocumentPayload(TypedDict):
    key: str
    kind: str
    name: str
    path: str
    title: str
    frontmatter: str
    body: str
    tokens: str
    content_hash: str


def build_document(kind: str, path: Path, name: str) -> DocumentPayload:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    fm = parse_frontmatter(text)
    _, body = split_frontmatter(text)
    title_value = fm.get("title", name)
    title = title_value if isinstance(title_value, str) else name
    return {
        "key": f"{kind}:{name}",
        "kind": kind,
        "name": name,
        "path": str(path.relative_to(ROOT)),
        "title": title,
        "frontmatter": json.dumps(fm, ensure_ascii=False),
        "body": body,
        "tokens": " ".join(tokenize(f"{title}\n{body}")),
        "content_hash": hashlib.sha256(raw).hexdigest(),
    }


def collect_documents() -> list[DocumentPayload]:
    docs: list[DocumentPayload] = []
    for p in sorted((ROOT / "topics").glob("*/README.md")):
        docs.append(build_document("topic", p, p.parent.name))
    for p in sorted((ROOT / "references").glob("*.md")):
        docs.append(build_document("reference", p, p.stem))
    for p in sorted((ROOT / "wiki").glob("*.md")):
        docs.append(build_document("wiki", p, p.stem))
    for p in sorted((ROOT / "courses").glob("*/README.md")):
        docs.append(build_document("course", p, p.parent.name))
    for p in sorted((ROOT / "courses").glob("*/[0-9][0-9]-*.md")):
        docs.append(build_document("lesson", p, f"{p.parent.name}/{p.stem}"))
    return docs


# --------------------------------------------------------------------------- #
# SQL generation
# --------------------------------------------------------------------------- #


def chunk_by_utf8_bytes(text: str, limit: int) -> list[str]:
    """Split on codepoint boundaries so each chunk encodes to <= limit bytes."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for ch in text:
        ch_len = len(ch.encode("utf-8"))
        if size + ch_len > limit and current:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(ch)
        size += ch_len
    if current:
        chunks.append("".join(current))
    return chunks or [""]


def hex_text_literal(text: str) -> str:
    """Quote-free TEXT literal; '' stays ''."""
    if not text:
        return "''"
    return f"CAST(X'{text.encode('utf-8').hex()}' AS TEXT)"


def safe_literal(value: str, field: str, key: str) -> str:
    if not _SAFE_LITERAL_RE.match(value):
        raise ValueError(f"{key}: {field} {value!r} contains characters outside [A-Za-z0-9._:/-]")
    return f"'{value}'"


def upsert_statements(doc: DocumentPayload, now: int) -> list[str]:
    key = safe_literal(doc["key"], "key", doc["key"])
    kind = safe_literal(doc["kind"], "kind", doc["key"])
    name = safe_literal(doc["name"], "name", doc["key"])
    path = safe_literal(doc["path"], "path", doc["key"])
    content_hash = safe_literal(doc["content_hash"], "content_hash", doc["key"])

    # The INSERT carries only short columns; every long payload is appended in
    # its own UPDATE so no single statement exceeds one chunk (~70KB as hex).
    stmts = [
        f"DELETE FROM documents_fts WHERE key = {key};",
        "INSERT OR REPLACE INTO documents"
        " (key, kind, name, path, title, frontmatter, body, tokens, content_hash, synced_at)"
        f" VALUES ({key}, {kind}, {name}, {path}, {hex_text_literal(doc['title'])},"
        f" '', '', '', {content_hash}, {now});",
    ]
    for column in ("frontmatter", "body", "tokens"):
        for chunk in chunk_by_utf8_bytes(doc[column], MAX_CHUNK_UTF8_BYTES):
            if not chunk:
                continue
            stmts.append(
                f"UPDATE documents SET {column} = {column} || {hex_text_literal(chunk)} WHERE key = {key};"
            )
    stmts.append(
        "INSERT INTO documents_fts (tokens, key, kind)"
        f" SELECT tokens, key, kind FROM documents WHERE key = {key};"
    )
    return stmts


def delete_statements(key: str) -> list[str]:
    lit = safe_literal(key, "key", key)
    return [
        f"DELETE FROM documents_fts WHERE key = {lit};",
        f"DELETE FROM documents WHERE key = {lit};",
    ]


# --------------------------------------------------------------------------- #
# wrangler
# --------------------------------------------------------------------------- #


def wrangler_base() -> list[str]:
    return shlex.split(os.environ.get("WRANGLER_BIN", "wrangler"))


def run_wrangler_d1(args: list[str], env_flag: str) -> str:
    argv = wrangler_base() + ["d1", "execute", DB_NAME, env_flag, *args]
    proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip()[-2000:]
        raise RuntimeError(f"wrangler failed (rc={proc.returncode}): {tail}")
    return proc.stdout


def query_json(command: str, env_flag: str) -> list[dict]:
    out = run_wrangler_d1(["--json", "--command", command], env_flag)
    payload = json.loads(out)
    return payload[0].get("results", [])


def fetch_synced_hashes(env_flag: str) -> dict[str, str]:
    rows = query_json("SELECT key, content_hash FROM documents", env_flag)
    return {row["key"]: row["content_hash"] for row in rows}


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync content into D1 documents/documents_fts")
    scope = p.add_mutually_exclusive_group(required=True)
    scope.add_argument("--local", action="store_true", help="target the local D1 (miniflare)")
    scope.add_argument("--remote", action="store_true", help="target the production D1")
    p.add_argument("--dry-run", action="store_true", help="write the SQL file but do not execute")
    p.add_argument("--full", action="store_true", help="wipe and re-insert everything (recovery)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env_flag = "--local" if args.local else "--remote"

    docs = collect_documents()
    print(f"collected {len(docs)} documents")

    statements: list[str] = []
    if args.full:
        statements += ["DELETE FROM documents_fts;", "DELETE FROM documents;"]
        changed = docs
        removed: list[str] = []
    else:
        synced = fetch_synced_hashes(env_flag)
        local_keys = {d["key"] for d in docs}
        changed = [d for d in docs if synced.get(d["key"]) != d["content_hash"]]
        removed = sorted(k for k in synced if k not in local_keys)

    if not changed and not removed:
        print("up to date — nothing to sync")
        return 0

    now = int(time.time())
    for doc in changed:
        statements += upsert_statements(doc, now)
    for key in removed:
        statements += delete_statements(key)

    sql = "\n".join(statements) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".sql", prefix="sync-content-", delete=False
    ) as f:
        f.write(sql)
        sql_path = f.name
    print(
        f"{len(changed)} upsert(s), {len(removed)} removal(s), "
        f"{len(statements)} statement(s), {len(sql) / 1_000_000:.1f}MB -> {sql_path}"
    )

    if args.dry_run:
        print("dry-run: not executed")
        return 0

    run_wrangler_d1(["--file", sql_path, "-y"], env_flag)
    os.unlink(sql_path)

    counts = query_json(
        "SELECT (SELECT COUNT(*) FROM documents) AS docs,"
        " (SELECT COUNT(*) FROM documents_fts) AS fts",
        env_flag,
    )[0]
    print(f"synced: documents={counts['docs']} documents_fts={counts['fts']}")
    if counts["docs"] != counts["fts"]:
        print("WARNING: documents / documents_fts row counts differ — re-run with --full", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
