---
name: survey-capture
description: |
  外部セッション中に得た知見・学び・断片メモを survey-any リポジトリの inbox/ に捕獲するスキル。
  整理は後で survey-any 側の /inbox-organize で実施する前提で、ここでは素早く記録だけ残す。
  Use when: 作業中に「これは survey-any に残しておきたい」と感じたとき。
  「キャプチャして」「survey-any に残して」「inbox に入れて」「後で整理する前提でメモして」
  など、現在の作業の文脈を止めずに記録したいとき。
  新規調査の実行（/survey）や整理作業（/inbox-organize）とは別。
license: MIT
---

# Survey Capture

外部セッションから survey-any の inbox に書き込むための軽量キャプチャスキル。

前提: `ghq`, `mise` がインストール済みであること。

## Workflow

### 1. パス解決と現在 cwd の取得

```bash
SURVEY_REPO=$(ghq list --full-path | grep 'survey-any$' | head -1)
SOURCE_CWD=$(pwd)
```

`SURVEY_REPO` が空ならエラー終了し、ユーザーに `ghq get` を促す。

### 2. slug の決定

ユーザーの依頼内容から短い kebab-case の slug を決める（例: `unity-gc-spike`, `api-rate-limit-pattern`）。
迷う場合はユーザーに確認する。

ルール:
- 英数字とハイフンのみ
- 10〜40文字程度
- 日本語・スペース禁止

### 3. inbox ファイルの生成

```bash
mise -C "$SURVEY_REPO" run new inbox "<slug>" "$SOURCE_CWD"
```

出力される `inbox/YYYY-MM-DD-HHMMSS-<slug>.md` のパスを控える。

### 4. 本文の記入

Edit ツールで以下を埋める:

- `title`: 1行の要約（日本語可）
- `tags`: 暫定タグ。既存タグと揃える必要はない（organize 時に正規化）
- `# {title}` の見出しを実タイトルに置換
- `## 文脈`: どの作業中の気づきか、何を探していたか
- `## 内容`: 記録したい事実・リンク・コマンド・コード片など
- `## 次アクション`: 追記先の候補トピック、追加調査の方向性など（わかる範囲で）

### 5. 完了報告

ユーザーに以下を伝える:

- 生成されたファイルパス（`<SURVEY_REPO>/inbox/...`）
- 後で `/inbox-organize` で整理できる旨

## 注意

- このスキルでは `mise run index` を実行しない（inbox は INDEX 対象外）
- topics/ や references/ に直接書かない。昇格は organize フェーズの責務
- 既存トピックへの追記を「その場で」やりたい場合は、このスキルではなく survey-any リポジトリで `/survey-any:survey` を使う
- git commit は行わない（ユーザーが必要に応じて実施）
