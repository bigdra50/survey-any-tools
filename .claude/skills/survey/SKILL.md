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

WebSearch / WebFetch で情報収集し、README.md に記述する。

必須:
- frontmatter の `title`, `status`, `tags` を記入
- ソースは URL または書籍情報を記録（CLAUDE.md のソース記録ルールに従う）
- 関連トピックがあれば `related` に記入

### 5. 完了処理

```bash
mise run index
```
