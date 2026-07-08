---
name: preview
description: |
  survey-any の Astro viewer (viewer/) をローカルでビルドし、Cloudflare Pages 互換のサーバ
  (wrangler pages dev + D1 + Functions) を起動してブラウザ確認するスキル。
  Use when: 「preview」「プレビュー」「viewer 見たい」「ローカルで表示」「ローカルサーバ起動」
  「ローカルで確認」「ブラウザで見たい」「8788」「local preview」と依頼されたとき。
  本番反映 (Cloudflare Pages へ deploy) は別。preview はローカル確認のみ。
---

# Preview

survey-any の viewer をローカルでビルドし、`wrangler pages dev` で配信する。
内部処理は `mise run preview` (= `cd viewer && bun install && bun run build && wrangler pages dev dist`)。
既定ポートは `8788`。

## パス解決

前提: `ghq`, `mise`, `bun`, `wrangler` がインストール済み。viewer は content リポジトリ側にあるため、まず content を解決する。

```bash
SURVEY_REPO=$(ghq list --full-path | grep 'survey-any$' | head -1)
```

空なら `ghq get bigdra50/survey-any` をユーザーに促す。`survey-any$` の末尾 `$` により `survey-any-tools`（ツール repo）は除外される。以降 `mise -C "$SURVEY_REPO" run ...` で実行する。

## Workflow

### 1. 既起動チェック (二重起動の回避)

8788 が既に LISTEN なら再ビルドせず URL を案内して終了する。

```bash
lsof -nP -iTCP:8788 -sTCP:LISTEN
```

注: sandbox がローカル接続/プロセス照会を遮断する環境では、この確認は
`dangerouslyDisableSandbox` での読み取り実行が必要なことがある。

### 2. ビルド & サーバ起動 (バックグラウンド)

`mise -C "$SURVEY_REPO" run preview` をバックグラウンドで起動する (サーバは起動したまま常駐するため)。

```bash
mise -C "$SURVEY_REPO" run preview
```

出力に `Ready on http://localhost:8788` が出れば準備完了。
サーバは常駐し completion 通知が来ないため、出力ファイルを監視して
「Ready 行」か「ビルド失敗」のどちらかを待つ:

```bash
# 成功/失敗のどちらかで 1 回だけ抜ける until ループ (Bash run_in_background 推奨)
until rg -q "Ready on http|exited with code|InvalidContentEntryDataError" "<output-file>"; do sleep 1; done
```

### 3. build 失敗時のトラブルシュート

`astro build` はコンテンツ frontmatter を zod スキーマ
(`viewer/src/content.config.ts`) で検証するため、違反があると
`InvalidContentEntryDataError` で停止する (最初の 1 件で止まる)。
エラーの該当ファイル・フィールドを見て直す。よくある enum 違反:

| フィールド | 許可値 | 対処 |
|---|---|---|
| `references.read_depth` | `full` / `abstract` / `overview` | enum 外なら正値に。新レベルが要るなら下記 3 箇所に追加 |
| `topics.status` | `done` / `in-progress` / `memo` / `archived` | 〃 |
| `wiki.status` | `stub` / `draft` / `mature` | 〃 |
| `courses.status` | `draft` / `published` / `archived` | 〃 |
| `date` / `retrieved` / `created` / `updated` | パース可能な日付 | ISO8601 か `YYYY-MM-DD` |

enum 自体を拡張する場合は SoT を揃える (viewer は content 側、Python schema と survey-paper 手引きはツール側 survey-any-tools):

1. `viewer/src/content.config.ts` の zod `z.enum([...])`（content 側）
2. ツール側 survey-any-tools の `survey_any/_schema.py` の対応する `frozenset({...})`
3. 値の意味を文書化しているスキル (例: read_depth は survey-any-tools の `.apm/skills/survey-paper/SKILL.md`)

拡張後は drift を確認する (フィールド名の照合。enum 値は対象外だが整合確認に有効):

```bash
mise -C "$SURVEY_REPO" run check-schema
```

違反ファイルを直したら Step 2 を再実行する。

### 4. 到達確認 & URL 案内

起動後、確認したいページの URL を案内する。

- トップ: `http://localhost:8788/`
- 特定 topic: `http://localhost:8788/topics/<topic-name>/`
- 特定 reference: `http://localhost:8788/references/<name>/`
- タグ: `http://localhost:8788/tags/<tag>/`

HTTP 到達確認に `curl` する場合、sandbox がローカル接続を遮断する環境では
読み取り目的で一時的に sandbox 無効化が要る:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8788/topics/<topic-name>/
```

### 5. 停止

バックグラウンドの preview を止めたいときは、起動した background task を
`TaskStop` で停止する (または該当 `workerd` プロセスを終了)。
明示依頼が無い限り、起動したサーバは止めず常駐させたままにしてよい。

## deploy との違い

| タスク | 用途 | 反映先 |
|---|---|---|
| `mise -C "$SURVEY_REPO" run preview` | ローカル確認 | `localhost:8788` (wrangler pages dev) |
| `mise -C "$SURVEY_REPO" run deploy` | 本番デプロイ | Cloudflare Pages |

preview は読み取り確認のみ。deploy はユーザーが明示したときだけ実行する
(外向きの公開操作のため)。
