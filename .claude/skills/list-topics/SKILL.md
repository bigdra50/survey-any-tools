---
name: list-topics
description: |
  調査トピックの一覧表示・フィルタリングを行うスキル。
  Use when: 「トピック一覧」「何を調べた?」「リスト見せて」「〜タグのトピック」
  「完了したトピック」「in-progressのトピック」など、トピックの一覧や検索を求めたとき。
---

# List Topics

リクエストに応じて適切な mise task を実行する。

## 全件一覧

```bash
mise run list
```

## タグで検索

```bash
mise run search <tag>
```

## 詳細フィルタリング

```bash
mise run fm-dump | jq '<filter>'
```

フィルタ例:
- ステータス: `.[] | select(.status == "done")`
- タグ: `.[] | select(.tags | index("robotics"))`
- 複合: `.[] | select(.status == "in-progress" and (.tags | index("unity")))`

## タグ一覧

```bash
mise run fm-tags
```

## 関連トピック

```bash
mise run fm-related <topic>
```

## 外部資料一覧（references/）

```bash
ls references/
```

特定タグの references を探す:

```bash
rg "tags:.*<tag>" references/
```
