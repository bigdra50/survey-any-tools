---
name: survey-knowledge
description: |
  survey-any リポジトリに蓄積された調査知識をグローバル検索・参照するスキル。
  ghq でリポジトリパスを自動解決し、mise タスク経由でトピックを横断検索する。
  Use when: 作業中に過去の調査結果を参照したいとき。
  「前に調べた〜」「〜のトピックある?」「〜のナレッジ検索」「survey-any確認」「調査結果参照」
  「〜について何か知ってる?」「リサーチノート検索」など、既存の調査知識を引きたいとき。
  新規調査の実行ではなく、蓄積済み知識の検索・参照に使う。
license: MIT
---

# Survey Knowledge

survey-any リポジトリの調査知識にグローバルアクセスするスキル。

前提: `ghq`, `mise`, `jq` がインストール済みであること。

## パス解決

最初に survey-any リポジトリのローカルパスを取得する:

```bash
SURVEY_REPO=$(ghq list --full-path | grep 'survey-any$' | head -1)
```

以降のコマンドは全てこのパスを使用する。

## Workflow

### 1. トピック検索

fm-dump でメタデータJSON配列を取得し、質問に関連するトピックを特定する。

```bash
mise -C "$SURVEY_REPO" run fm-dump
```

各要素: `{topic, title, status, tags, related, created, path}`

jq でフィルタ:
```bash
mise -C "$SURVEY_REPO" run fm-dump | jq '.[] | select(.tags | index("unity"))'
mise -C "$SURVEY_REPO" run fm-dump | jq '.[] | select(.title | test("keyword"; "i"))'
```

### 2. 補助コマンド

```bash
mise -C "$SURVEY_REPO" run fm-tags              # タグ一覧（使用頻度付き）
mise -C "$SURVEY_REPO" run search <tag>          # タグでトピック検索
mise -C "$SURVEY_REPO" run fm-related <topic>    # 関連トピック（タグ重複度順）
mise -C "$SURVEY_REPO" run list                  # 全トピック一覧
```

### 3. 内容読み込み

該当トピックを Read ツールで読み込む: `$SURVEY_REPO/topics/<topic>/README.md`

複数トピックにまたがる質問は関連トピックも併せて読む。

### 4. 回答

- トピック内のソースを引用して回答する
- 該当なしなら「既存の調査に含まれていない」と明示する
- 追加調査が有益な場合は survey-any リポジトリでの `/survey` 利用を提案する
