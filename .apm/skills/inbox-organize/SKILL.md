---
name: inbox-organize
description: |
  inbox/ に溜まった未整理のキャプチャを既存トピックに昇格・統合するスキル。
  各エントリを既存 topics/ や references/ と突合し、追記・新規作成・破棄に振り分ける。
  Use when: 「inbox整理して」「キャプチャを整理」「inbox消化」「inbox-organize」と依頼されたとき、
  または inbox/ に unprocessed なエントリが溜まっているとき。
  新規調査の実行 (/survey) やキャプチャ (/survey-capture) とは別の整理専用スキル。
license: MIT
---

# Inbox Organize

inbox/ の未整理キャプチャを既存の topics/ と references/ に昇格させる。

前提: survey-any リポジトリが cwd であること（plugin 経由で呼び出されても ghq で解決する）。

## Workflow

### 1. リポジトリパスの解決

cwd が survey-any でない場合は ghq で解決する:

```bash
if [ ! -f ".claude-plugin/plugin.json" ] || ! grep -q '"name": "survey-any"' .claude-plugin/plugin.json; then
  SURVEY_REPO=$(ghq list --full-path | grep 'survey-any$' | head -1)
  cd "$SURVEY_REPO"
fi
```

### 2. 未処理エントリの列挙

```bash
rg -l '^status: unprocessed' inbox/*.md 2>/dev/null
```

該当がなければ「inbox は空です」と報告して終了。

### 3. 既存知識ベースの取得

```bash
mise run fm
```

全トピックのメタデータ（tags, title, status 等）を把握する。

### 4. 各エントリの振り分け

各 unprocessed ファイルについて、以下の手順で処理する:

#### 4-1. 内容の把握

Read でファイル全体を読む。特に注目する項目:
- `title`, `tags`, 本文（`## 内容`, `## 次アクション`）

#### 4-2. 振り分け判断

| 状況 | アクション |
|------|-----------|
| 既存トピックの深掘り・補足 | 既存 `topics/{topic}/README.md` に追記 |
| 外部資料の客観的記録（URL付き記事・論文等） | `references/{name}.md` として新規作成 |
| 既存と関連するが独立した問い | 新規 `topics/{topic}/` 作成 + `related` で相互リンク |
| 既存と無関係な新規テーマ | 新規 `topics/{topic}/` 作成 |
| 既知の内容で価値なし | `discarded` としてマーク |

判断が曖昧な場合は AskUserQuestion でユーザーに確認する。

#### 4-3. 昇格実行

**既存トピックに追記する場合:**
- Edit で `topics/{topic}/README.md` に新規セクションを追加
- inbox 側の本文・ソースを反映
- 追記箇所に `<!-- from inbox/<filename> -->` 等のコメントは入れない（ノイズ）

**新規トピック作成の場合:**
```bash
mise run new memo <topic-name>   # or `mise run new report <topic-name>`
```
その後、生成された `topics/{topic}/README.md` の frontmatter（tags, related）と本文を埋める。

**references 作成の場合:**
```bash
mise run new reference <name>    # or `mise run new paper <name>`
```
frontmatter と客観的内容記録を埋める。必要なら topics 側の `sources:` も更新。

#### 4-4. inbox frontmatter 更新

昇格または破棄したら、inbox ファイルの frontmatter を以下に更新:

```yaml
status: promoted          # または discarded
promoted_to: topics/foo/  # または references/foo.md、discarded の場合は null のまま
```

inbox ファイル本体は削除しない（監査・トレース用途で保持）。

### 5. 完了処理

全エントリ処理後:

```bash
mise run index
```

INDEX.md を再生成する。

### 6. サマリ報告

ユーザーに処理結果を報告:
- 処理件数（promoted / discarded / pending）
- 新規作成されたトピック・reference の一覧
- 追記された既存トピックの一覧

## 注意

- 1回の実行で全件処理する必要はない。ユーザーが「ここまでで一旦止めて」と言ったら途中終了してよい
- 既存の `.claude/skills/organize/` とは別物（あちらはトピック間の related 整備、こちらは inbox の消化）
- git commit は行わない（ユーザーが必要に応じて実施）
