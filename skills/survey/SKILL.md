---
name: survey
description: |
  新規調査を実行するスキル。テーマを受け取り、既存トピックとの関連を判断した上で、
  既存トピックへの追記または新規トピック作成を行い、survey-any リポジトリに記録する。
  ghq でリポジトリパスを自動解決するため、どのプロジェクトで作業中でも呼び出せる。
  Use when: ユーザーが「〜について調べて」「〜を調査して」「〜をサーベイして」と依頼したとき、
  または research / survey / investigate といった調査系のリクエストがあったとき。
  既存調査の参照は /ask、論文サーベイは /survey-paper、断片メモの捕獲は /survey-capture を使う。
license: MIT
---

# Survey

新規の一般調査を実行し、survey-any に成果物を記録する。

前提: `ghq`, `mise`, `jq` がインストール済みであること。

## Workflow

### 1. パス解決

```bash
SURVEY_REPO=$(ghq list --full-path | grep 'survey-any$' | head -1)
```

以降のコマンドは `mise -C "$SURVEY_REPO"` または `cd "$SURVEY_REPO"` 後に実行する。

### 2. 既存トピックの探索

```bash
mise -C "$SURVEY_REPO" run fm
```

出力JSONを確認し、依頼テーマと関連するトピックがあるか判断する。
判断材料: tags の重複、タイトルの類似性、テーマの包含関係。

必要に応じて `mise -C "$SURVEY_REPO" run fm-related <topic>` で特定トピックとの関連度を確認する。

### 3. 方針決定

| 状況 | 対応 |
|------|------|
| 既存トピックの深掘り・補足 | 既存 README.md に追記 |
| 既存トピックのサブテーマで独立性あり | 既存ディレクトリ内にサブファイル追加 (`topics/{parent}/subtopic.md`) |
| 関連するが別の問い | 新規トピック作成 + `related` で相互リンク |
| 既存と無関係 | 新規トピック作成 |

迷う場合は AskUserQuestion でユーザーに確認する。

### 4. トピック作成・更新

Step 3 の判断結果に応じて以下を実行する。各分岐で必要な操作はすべてこの表に網羅されている。自前で frontmatter スキーマを設計しないこと。

| Step 3 の選択 | 手順 |
|---|---|
| 既存トピックの深掘り・補足 | `topics/<existing>/README.md` を直接編集。frontmatter の `updated:` を当日 (UTC) に更新。本文末尾または該当セクションに追記。新規 reference を追加した場合は `sources:` も更新 |
| 既存トピックのサブテーマで独立性あり | `topics/<existing>/<subtopic-slug>.md` を新規作成 (mise タスクなし、エディタで直接作成)。frontmatter は最低限 `title`, `parent: <existing-topic>`, `status`, `tags`, `created`, `updated` を入れる。親 README に「サブトピック」セクションを設けて相対リンクを追加し、親の `updated:` も更新 |
| 関連するが別の問い | `mise -C "$SURVEY_REPO" run new <kind> <topic-name>` で新規作成。新旧両方の README の `related:` で相互リンク (双方向) |
| 既存と無関係 | `mise -C "$SURVEY_REPO" run new <kind> <topic-name>` で新規作成 |

`<kind>` の選択基準 (`mise run new <kind> <name>` の `<kind>` 部分):

| kind | 用途 | 目安 (半開区間で重複なく定義) |
|---|---|---|
| memo | 走り書き〜短文。短く完結する技術調査 | セクション数 < 4 かつ reference < 3 |
| report | 構造的なレポート。複数ソース統合 | セクション数 ≥ 4 または reference ≥ 3 |
| notebook | データ可視化・コード実行記録 | 数値計算・グラフ・統計処理がある場合のみ (`.ipynb`) |

実在する mise タスクは `mise run new <kind> <name>` の 1 つのみ。`new-report` `new-notebook` `new-reference` などの flat タスクは存在しない。`<kind>` の指定は必須 (省略不可)。

### 5. 調査実行

WebSearch / WebFetch で情報収集する。

外部 IO 失敗時の失敗ラダー (上から順に試行し、ヒットしたら以降はスキップ):

1. **同 URL を 1 回だけ再試行** — 一時的なネットワークエラー / 過渡的 503 の救済
2. **`https://r.jina.ai/<URL>` で再取得** — SPA や JS rendering 必須サイト、軽度の bot 検出を回避できる場合がある (Jina Reader が headless ブラウザでレンダリング後 Markdown 化)
3. **`https://web.archive.org/web/2*/<URL>`** — 元サイト消滅・地域制限・本格的な bot wall に対する最後の手段
4. **WebSearch スニペットで代替** — 上記すべてに失敗した場合の exit。本文中で `(未確認)` と注記し、reference には登録しない

各段の使い分け診断 (本格的にラダーを駆け降りる前に判断するためのヒント):

| 失敗種別 | 推奨ステップ |
|---|---|
| 429 (rate limit) | 1 → 2 (Jina の cache hit に賭ける) |
| 403 (Cloudflare bot wall) | 2 → 3 (Jina で UA 偽装 → Archive) |
| 動的 SPA (空 HTML) | 2 (Jina Reader が JS 実行) |
| 404 / リンク切れ | 3 (Archive のスナップショット) |
| auth wall | 4 (代替不能) |

探索回数の目安: 1 テーマあたり WebSearch 3 回 + WebFetch 5 回まで (ラダーの段は WebFetch 回数にカウント)。

`r.jina.ai` 経由で取得した内容を references に記録する場合、frontmatter の `retrieved` の隣 (またはノート行) に `via: r.jina.ai` を明記する (Jina 側のキャッシュ起源・rendering 副作用を識別するため)。

#### topics/ と references/ の振り分け

| 内容 | 書き出し先 |
|------|-----------|
| 外部資料（記事・スライド・論文）の客観的な内容記録 | `references/{name}.md` |
| 自分の考察・複数情報の統合・所感 | `topics/{topic}/README.md` |

外部資料が見つかった場合:
1. `mise -C "$SURVEY_REPO" run new reference <name>` で references/ にファイルを作成
2. frontmatter（title, type, author, organization, url, date, retrieved, tags）を記入
3. 本文には客観的な内容記録のみ。自分の意見は含めない
4. topics 側の README.md の `sources:` フィールドに reference 名を追加

topics/README.md への記述:
- frontmatter の `title`, `status`, `tags` を記入
- 関連トピックがあれば `related` に記入
- 外部資料の要約ではなく、自分の分析・統合・所感を書く
- references に記録済みの資料は `sources:` で参照し、本文での重複記載を避ける

### 6. 完了処理

```bash
mise -C "$SURVEY_REPO" run index
```

berrypicking trace を 1 行記録する (新規調査の発端を残すため):

```bash
mise -C "$SURVEY_REPO" run trace \\
  --query "<ユーザーが投げた調査テーマ>" \\
  --hits "<検索で参照した既存トピック群 (comma)>" \\
  --picked "<新規作成 or 追記したトピック>" \\
  --strategy subject
```

引数の意味と空値の扱い:
- `--hits`: Step 2 の `mise run fm` 出力の中で、テーマと意味的に近接していると判断した既存トピックを comma 区切りで列挙する。完全新規テーマで該当ゼロなら `--hits ""` (空文字) で OK
- `--picked`: 今回新規作成または追記した topic 名 1 つ (サブファイル追加の場合は親 topic 名)
- `--strategy`: Bates の 6 berrypicking 戦略のいずれか。ユーザー依頼が「テーマ X について調べて」なら通常 `subject`、「この論文の引用を辿って」なら `footnote`、「この著者の他の仕事」なら `author` 等

`memory/seeking-trace.jsonl` への 1 行追記。`.gitignore` 対象 (個人ローカル)。
将来の retrieval reward / 自動 related 候補生成のシードになる。

### 7. 完了報告

ユーザーに以下を伝える:
- 作成・更新したトピックのパス（`$SURVEY_REPO/topics/...`）
- 作成した references のリスト
- 次のアクション候補（関連トピックの深掘り提案など）

git commit は行わない（ユーザーが必要に応じて実施）。
