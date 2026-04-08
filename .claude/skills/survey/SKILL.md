---
name: survey
description: |
  新規調査を実行するスキル。テーマを受け取り、既存トピックとの関連を判断した上で、
  既存トピックへの追記または新規トピック作成を行う。
  Use when: ユーザーが「〜について調べて」「〜を調査して」「〜をサーベイして」と依頼したとき、
  または research / survey / investigate といった調査系のリクエストがあったとき。
---

# Survey

## Workflow

### 1. 既存トピックの探索

```bash
mise run fm-dump
```

出力JSONを確認し、依頼テーマと関連するトピックがあるか判断する。
判断材料: tags の重複、タイトルの類似性、テーマの包含関係。

必要に応じて `mise run fm-related <topic>` で特定トピックとの関連度を確認する。

### 2. 方針決定

| 状況 | 対応 |
|------|------|
| 既存トピックの深掘り・補足 | 既存 README.md に追記 |
| 既存トピックのサブテーマで独立性あり | 既存ディレクトリ内にサブファイル追加 (`topics/{parent}/subtopic.md`) |
| 関連するが別の問い | 新規トピック作成 + `related` で相互リンク |
| 既存と無関係 | 新規トピック作成 |

迷う場合は AskUserQuestion でユーザーに確認する。

### 3. トピック作成

新規作成時のテンプレート選択:

```bash
mise run new <topic-name>          # メモ（デフォルト）
mise run new-report <topic-name>   # 構造的なレポート
mise run new-notebook <topic-name> # データ可視化・コード実行記録が必要な場合
```

### 4. 調査実行

WebSearch / WebFetch で情報収集する。

#### topics/ と references/ の振り分け

| 内容 | 書き出し先 |
|------|-----------|
| 外部資料（記事・スライド・論文）の客観的な内容記録 | `references/{name}.md` |
| 自分の考察・複数情報の統合・所感 | `topics/{topic}/README.md` |

外部資料が見つかった場合:
1. `mise run new-reference <name>` で references/ にファイルを作成
2. frontmatter（title, type, author, organization, url, date, retrieved, tags）を記入
3. 本文には客観的な内容記録のみ。自分の意見は含めない
4. topics 側の README.md の `sources:` フィールドに reference 名を追加

topics/README.md への記述:
- frontmatter の `title`, `status`, `tags` を記入
- 関連トピックがあれば `related` に記入
- 外部資料の要約ではなく、自分の分析・統合・所感を書く
- references に記録済みの資料は `sources:` で参照し、本文での重複記載を避ける

### 5. 完了処理

```bash
mise run index
```
