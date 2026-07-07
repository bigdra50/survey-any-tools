#!/usr/bin/env python3
"""Content-root resolution for survey-any scripts.

すべての scripts が持っていた `ROOT = Path(__file__).resolve().parent.parent`
を 1 箇所へ集約する。将来コンテンツをツールから分離する（ADR 0001）際、
ルート解決の変更点をこのモジュールだけに閉じ込めるための土台。

解決順序（`content_root`）:
  1. 引数 `explicit`（`--root` 相当）を絶対パス化して返す
  2. 環境変数 `SURVEY_ANY_ROOT` があればそのパスを絶対パス化して返す
  3. `Path(__file__).resolve().parent.parent`（＝ scripts/ の親。従来値）に
     `topics/` があればそれを返す（＝従来の ROOT 解決と完全に同一の結果）
  4. 上記が `topics/` を持たない異常時のみ、cwd から上方へ `topics/` を持つ
     最初の祖先を探索するフォールバック
  5. さらに見つからなければ 3. の `__file__` ベースパスをそのまま返す

Phase 1: env 未設定時は常に 3. の `__file__` ベース解決で確定し、従来の
`ROOT = Path(__file__).resolve().parent.parent` と完全に同一の値を返す
（cwd に無関係な `topics/` ディレクトリがあっても影響を受けない）。
cwd 上方探索は Phase 3 で本番化する（現状は 3. が失敗したときの保険としてのみ存在）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

ENV_VAR: Final[str] = "SURVEY_ANY_ROOT"
MARKER_DIR: Final[str] = "topics"

# scripts/_root.py → scripts/ → repo root（従来 ROOT と一致する fallback）
_FALLBACK_ROOT: Final[Path] = Path(__file__).resolve().parent.parent


def _ancestor_with_marker(start: Path, marker: str = MARKER_DIR) -> Path | None:
    """`start` とその祖先を上方に辿り、`marker/` を持つ最初のディレクトリを返す。

    Args:
        start: 探索の起点（絶対パス化して扱う）。
        marker: 存在を確認するサブディレクトリ名。

    Returns:
        `marker/` を含む最も近い祖先。見つからなければ None。
    """
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / marker).is_dir():
            return candidate
    return None


def content_root(explicit: Path | None = None) -> Path:
    """コンテンツルート（topics/references/... の親）を解決する。

    解決順序は module docstring を参照。純粋関数ではなく、環境変数と cwd を
    読む副作用がある（副次的にファイルシステムを stat する）。

    Args:
        explicit: 明示指定されたルート（CLI の `--root` 相当）。あれば最優先。

    Returns:
        解決された絶対パスのルート。どの経路でも必ず値を返す（fallback あり）。
    """
    if explicit is not None:
        return Path(explicit).resolve()

    env_value = os.environ.get(ENV_VAR)
    if env_value:
        return Path(env_value).resolve()

    if (_FALLBACK_ROOT / MARKER_DIR).is_dir():
        return _FALLBACK_ROOT

    found = _ancestor_with_marker(Path.cwd())
    if found is not None:
        return found

    return _FALLBACK_ROOT
