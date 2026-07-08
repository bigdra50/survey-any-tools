---
name: list-topics
description: |
  調査トピックの一覧表示・フィルタリングを行うスキル。
  Use when: 「トピック一覧」「何を調べた?」「リスト見せて」「〜タグのトピック」
  「完了したトピック」「in-progressのトピック」など、トピックの一覧や検索を求めたとき。
---

# List Topics

リクエストに応じて適切な mise task を実行する。

## パス解決

前提: `ghq`, `mise`, `jq` がインストール済み。content リポジトリを解決してから実行する。

```bash
SURVEY_REPO=$(ghq list --full-path | grep 'survey-any$' | head -1)
```

空なら `ghq get bigdra50/survey-any` をユーザーに促す。`survey-any$` の末尾 `$` により `survey-any-tools`（ツール repo）は除外される。

## プリミティブ

`fm` が frontmatter を JSON 配列で出力する単一プリミティブ。一覧・検索・フィルタは `jq` と合成する。

```bash
mise -C "$SURVEY_REPO" run fm
```

## 全件一覧

```bash
mise -C "$SURVEY_REPO" run fm | jq -r '.[] | "\(.status)\t\(.title)\t\(.path)"'
```

## タグで検索

```bash
mise -C "$SURVEY_REPO" run fm | jq '.[] | select(.tags | index("<tag>"))'
```

## 詳細フィルタリング

```bash
mise -C "$SURVEY_REPO" run fm | jq '<filter>'
```

フィルタ例:
- ステータス: `.[] | select(.status == "done")`
- タグ: `.[] | select(.tags | index("robotics"))`
- 複合: `.[] | select(.status == "in-progress" and (.tags | index("unity")))`

## タグ一覧

```bash
mise -C "$SURVEY_REPO" run fm-tags
```

## 関連トピック

```bash
mise -C "$SURVEY_REPO" run fm-related <topic>
```

## 外部資料一覧（references/）

```bash
ls "$SURVEY_REPO/references/"
```

特定タグの references を探す:

```bash
rg "tags:.*<tag>" "$SURVEY_REPO/references/"
```
