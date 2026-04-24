---
name: ask
description: |
  survey-any リポジトリに蓄積された既存調査を検索・参照して質問に回答するスキル。
  ghq でリポジトリパスを自動解決し、mise タスク経由でトピックを横断検索、
  該当する topics/references をソース付きで回答する。
  Use when: ユーザーが既存リサーチの内容について質問したとき、または既存知識を引きたいとき。
  「〜について教えて」「〜の内容は?」「〜ってどうだった?」「前に調べた〜」
  「〜のトピックある?」「〜のナレッジ検索」「survey-any確認」「調査結果参照」
  「〜について何か知ってる?」「リサーチノート検索」など。
  新規調査（/survey）や整理（/inbox-organize）とは別。
license: MIT
---

# Ask

survey-any の蓄積知識を検索・参照して回答する。

前提: `ghq`, `mise`, `jq` がインストール済みであること。

## Workflow

### 1. パス解決

```bash
SURVEY_REPO=$(ghq list --full-path | grep 'survey-any$' | head -1)
```

空ならエラー終了し、ユーザーに `ghq get` を促す。

### 2. 関連トピック検索

```bash
mise -C "$SURVEY_REPO" run fm-dump
```

各要素: `{topic, title, status, tags, related, created, path}`

jq でフィルタ:
```bash
mise -C "$SURVEY_REPO" run fm-dump | jq '.[] | select(.tags | index("unity"))'
mise -C "$SURVEY_REPO" run fm-dump | jq '.[] | select(.title | test("keyword"; "i"))'
```

### 3. 補助コマンド

```bash
mise -C "$SURVEY_REPO" run fm-tags              # タグ一覧（使用頻度付き）
mise -C "$SURVEY_REPO" run search <tag>          # タグでトピック検索
mise -C "$SURVEY_REPO" run fm-related <topic>    # 関連トピック（タグ重複度順）
mise -C "$SURVEY_REPO" run list                  # 全トピック一覧
```

### 4. 内容読み込み

該当する `$SURVEY_REPO/topics/<topic>/README.md` を Read で読む。
複数トピックにまたがる質問は関連トピックも併せて読む。

トピックの `sources:` フィールドに references が記載されている場合、
必要に応じて `$SURVEY_REPO/references/<name>.md` も読んで回答の根拠にする。

### 5. 回答

- トピック内のソースを引用して回答する
- 該当なしなら「既存の調査に含まれていない」と明示する
- 追加調査が有益な場合は `/survey` の利用を提案する
