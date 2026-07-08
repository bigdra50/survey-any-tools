---
name: organize
description: |
  トピック間の関連付け整理とメタデータ整備を行うスキル。
  frontmatter の related フィールド更新と INDEX.md 再生成を行う。
  Use when: 「整理して」「関連付けて」「organize」「メタデータ更新」「INDEX更新」と依頼されたとき。
---

# Organize

## パス解決

前提: `ghq`, `mise`, `jq` がインストール済み。content リポジトリを解決してから実行する。

```bash
SURVEY_REPO=$(ghq list --full-path | grep 'survey-any$' | head -1)
```

空なら `ghq get bigdra50/survey-any` をユーザーに促す。`survey-any$` の末尾 `$` により `survey-any-tools`（ツール repo）は除外される。

## Workflow

### 1. 現状把握

```bash
mise -C "$SURVEY_REPO" run fm
```

全トピックの frontmatter から以下を分析する:
- `related` が空のトピック
- tags 重複度が高いのに related で未リンクのペア

### 2. 関連付け提案

`mise -C "$SURVEY_REPO" run fm-related <topic>` で未リンクペアを洗い出し、
AskUserQuestion でユーザーに確認する。

### 3. frontmatter 更新

承認されたペアについて、双方の README.md の `related` を更新する。
related は双方向（A→B を追加したら B→A も追加）。

### 4. INDEX.md 再生成

```bash
mise -C "$SURVEY_REPO" run index
```

### 5. topics ↔ references の紐付け確認

topics の `sources:` に記載された reference が `references/` に存在するか確認する。
逆に、references/ にあるが どの topics からも参照されていない孤立ファイルがないか確認する。

```bash
# topics の sources フィールドから参照されている reference 名を抽出
rg "^  - " "$SURVEY_REPO"/topics/*/README.md | grep -v "^--"

# references/ 内のファイル一覧
ls "$SURVEY_REPO/references/"
```

### 6. タグ正規化（任意）

`mise -C "$SURVEY_REPO" run fm-tags` で表記ゆれや類似タグを確認し、統一を提案する。
