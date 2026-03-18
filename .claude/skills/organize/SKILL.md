---
name: organize
description: |
  トピック間の関連付け整理とメタデータ整備を行うスキル。
  frontmatter の related フィールド更新と INDEX.md 再生成を行う。
  Use when: 「整理して」「関連付けて」「organize」「メタデータ更新」「INDEX更新」と依頼されたとき。
---

# Organize

## Workflow

### 1. 現状把握

```bash
mise run fm-dump
```

全トピックの frontmatter から以下を分析する:
- `related` が空のトピック
- tags 重複度が高いのに related で未リンクのペア

### 2. 関連付け提案

`mise run fm-related <topic>` で未リンクペアを洗い出し、
AskUserQuestion でユーザーに確認する。

### 3. frontmatter 更新

承認されたペアについて、双方の README.md の `related` を更新する。
related は双方向（A→B を追加したら B→A も追加）。

### 4. INDEX.md 再生成

```bash
mise run index
```

### 5. タグ正規化（任意）

`mise run fm-tags` で表記ゆれや類似タグを確認し、統一を提案する。
