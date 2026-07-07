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

トピック数が140件超のため `fm` の全件 dump からいきなり始めない。まず絞り込みで当たりを付ける:

```bash
mise -C "$SURVEY_REPO" run search-fulltext "<調査テーマのキーワード>" --top 10 --kind topic
mise -C "$SURVEY_REPO" run fm-tags   # テーマに近い統制タグを確認
```

ヒットが出た範囲でのみ `fm` を絞り込んで詳細確認する:

```bash
mise -C "$SURVEY_REPO" run fm | jq --arg t "<タグ>" '.[] | select(.tags | index($t))'
```

出力を確認し、依頼テーマと関連するトピックがあるか判断する。
判断材料: tags の重複、タイトルの類似性、テーマの包含関係。

必要に応じて `mise -C "$SURVEY_REPO" run fm-related <topic>` で特定トピックとの関連度を確認する。
全件 dump (`mise run fm` 単体) は上記で手がかりが得られなかった場合の最終手段に留める。

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

WebSearch / WebFetch で情報収集する。調査手法は場当たりにせず、以下の方法論に沿う（根拠は topics/systematic-inquiry-pkb-application）。survey-paper の体系性（引用グラフ探索・飽和判定）に対応する backbone を一般 web 調査にも効かせる。

#### 5-0. 調査手法（検索 → 停止 → 裏取り → 統合）

**検索戦略**（単一の曖昧クエリを投げない）:

- **facet 分解（building blocks）**: テーマを独立ファセット（対象・手法・期間・地域等）に分け、各内は同義語で広げ、ファセット間は AND で組む。3-5 のクエリバリエーションを機械的に生成する
- **pearl growing / snowballing**: 良質な 1 ヒットが出たら単発で終わらせず、そのページの参考文献・被引用・外部リンク・言及を辿って展開する（Bates の BIBBLE=先にまとめ記事を探す / TRACE=良ヒットから検索語を拡張）

**停止判定**（回数でなく飽和で止める）:

- 「WebSearch 3 回」の固定回数でなく、**直近の数ソースが新しい主張・観点を追加しなくなったら停止**（理論的飽和）。新概念が出続けるなら続行、出なくなったら終了
- ただし「新規が出ない」だけで機械的に止めない（Saunders 2018 の警鐘）。重要度の高いテーマは「重要主張の深さ（反例・条件・数値）が尽きたか」まで確認する
- 目安の上限は残す（暴走防止）が、飽和が先に来たら早く止め、飽和しなければ上限まで粘る

**裏取り（triangulation）**:

- **重要な主張・数値は独立した 2 ソース以上で収束確認する**。単一ソースだけの主張は本文で「単一ソース」と明示し strength を下げる
- ソースの取得手法も変える（WebSearch 要約 vs WebFetch 一次資料 vs 公式 API）と食い違いを検出しやすい（例: 被引用数は DB 間で桁違いに矛盾することがある）
- 大きなテーマは fan-out subagent の並列調査で独立視点を作る（investigator triangulation の疑似実装）

**統合（要約の寄せ集めにしない）**:

- 集めた情報を (1) コード化（何が言われているか断片化）→ (2) 記述的テーマ（似た主張をまとめる）→ (3) **分析的テーマ（ソースを横断した、どのソースにも単独では書かれていない洞察・仮説）** の 3 段で統合する（thematic synthesis）
- 第 3 段の有無が「統合」と「要約の寄せ集め」の分岐。これが maturity: integrated への条件

**読解のトリアージ**:

- 全ソースを等しく精読しない。1st スキャン（関連判定）→ 2nd 要点抽出 → 3rd 精読、と重要度でコストを傾斜配分する（Keshav three-pass）
- 収集後のソース評価に CRAAP（Currency/Relevance/Authority/Accuracy/Purpose）を使い strength 判定を補強する

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

探索回数は固定でなく 5-0 の飽和判定で決める。WebSearch 3 回 + WebFetch 5 回程度は**暴走防止の上限の目安**であって到達目標ではない。飽和が先に来たら早く止め、新概念が出続けるなら（重要テーマなら）上限まで粘る (ラダーの段は WebFetch 回数にカウント)。

`r.jina.ai` 経由で取得した内容を references に記録する場合、frontmatter の `retrieved` の隣 (またはノート行) に `via: r.jina.ai` を明記する (Jina 側のキャッシュ起源・rendering 副作用を識別するため)。

#### 図表画像の取得と同梱（積極的に行う）

調査で発見した図表（アーキテクチャ図・結果グラフ・比較表の画像・スクリーンショット等）は、テキスト説明で済ませず**画像として同梱する**。二重符号化（R8）で理解と保持が上がり、後で読み返す自分・エージェント・他者に効く。自作の ASCII/mermaid 図とは別枠で、一次資料の図をそのまま引用する。

手順:

1. **取得**: WebFetch はテキストしか返さないので、画像は URL を直接ダウンロードする（`curl -sL <img-url> -o <path>`）。図の URL は WebFetch/Jina で得た HTML の `<img src>` や、記事・スライドの画像リンクから拾う
2. **同梱先**: `topics/<topic>/assets/<file>` または `references/assets/<ref-name>/<file>`（scratchpad や外部 URL 直貼りは消える・切れる・最適化されないので不可。viewer は同梱画像を webp 自動最適化する）
3. **貼り付け**: Markdown 相対参照 `![説明](./assets/<file>)`。直後にキャプションで**出典を必ず明記**（`*図: <何の図か>（出典: [<タイトル>](<URL>) Fig.N）*`）
4. **ライセンス**: viewer は public デプロイされうる。arXiv 論文図は多くが再利用可だが CC BY 等ライセンスと出典明記が原則。判断がつかない図・明確に All Rights Reserved の素材は、貼らずに URL リンク＋自作図で代替する
5. ファイル名は内容が分かる kebab-case にする（`droid-scene-diversity-vs-success.png` 等）

WebSearch で「<テーマ> figure / architecture / benchmark results」を検索すると図に辿り着きやすい。

#### topics/ と references/ の振り分け

| 内容 | 書き出し先 |
|------|-----------|
| 外部資料（記事・スライド・論文）の客観的な内容記録 | `references/{name}.md` |
| 自分の考察・複数情報の統合・所感 | `topics/{topic}/README.md` |

外部資料が見つかった場合:
1. `mise -C "$SURVEY_REPO" run new reference <name>` で references/ にファイルを作成
2. frontmatter（title, type, author, organization, url, date, retrieved, tags）を記入
3. **新規 reference には `strength:` を必須で付ける**（R3。エビデンス強度の統制語彙。強い順:
   `meta-analysis / replicated / peer-reviewed / preprint / single-author-preprint / official-docs / blog / anecdote`）。
   判定に迷う場合は著者数・査読有無・一次情報かで判断する
4. 本文には客観的な内容記録のみ。自分の意見は含めない
5. topics 側の README.md の `sources:` フィールドに reference 名を追加

topics/README.md への記述:
- frontmatter の `title`, `status`, `tags` を記入
- 関連トピックがあれば `related` に記入
- **`maturity:` を付ける**（R5。SOLO 分類。`collected`(事実を集めた) → `connected`(並べて比較した) →
  `integrated`(矛盾を解消し統合した) → `generalized`(他領域へ一般化した)。`status` とは直交する軸で、
  「調べただけ」か「統合まで到達したか」を区別する）
- **`recall:` に核心を問う自問を 2-3 問置く**（R4。検索練習効果。答えは本文中にある状態にする。
  例:「FAKTUAL と Geometric Entropy の結論はなぜ両立するか?」）
- 既存トピックと関連が言える場合は `related`（無型）に加えて **`relations:` で型付きリンクにする**（R2）。
  「なぜ関連か」を一言で言えない相手には付けない
  ```yaml
  relations:
    - to: <topic-slug>
      type: contrasts   # extends | contrasts | refutes | applies | analogous | prereq
      note: 結論が対立して見えるが文脈が異なる
  ```
- 外部資料の要約ではなく、自分の分析・統合・所感を書く（統合は 5-0 の 3 段階＝コード化→記述的テーマ→**分析的テーマ**まで到達させる。分析的テーマ＝ソース横断の新しい洞察があって初めて maturity: integrated を名乗れる）
- 調べ残した角度・未確認の主張（gap）を「限界」等に 1-2 行残す（何を調べ、何を調べていないかを読者に示す。PRISMA 的な最小カバレッジ記録）
- references に記録済みの資料は `sources:` で参照し、本文での重複記載を避ける
- 重要な主張・数値は独立 2 ソース以上で裏取りし（triangulation）、根拠の `strength:` を一言添える（単一ソースなら「単一ソース」と明示し弱める。例:「〜（単著プレプリント、示唆レベル）」）
- 図を入れる（R8。二重符号化）。2 種を使い分ける:
  - **自作の図**（構造・因果・対立の主張）: ASCII / mermaid でその場に描く
  - **一次資料の図**（発見したアーキ図・結果グラフ等）: 上記「図表画像の取得と同梱」に従い出典付きで貼る。
    テキストで説明できる図でも、原図があるなら積極的に同梱する

#### 本文の段階開示（R1）

本文冒頭は以下の 3 層構造に固定する。読者は最初に全体像を掴んでから詳細に降りる方が定着する:

1. **位置づけ** 1-2 文（既知トピックとの関係を明示する。「〜の一種」「〜と対比される」等）
2. **結論の要約**（箇条書き。本文を読まなくても核心が伝わる分量。必須）
3. 調査内容の本文（詳細はここから）

### 6. 完了処理

```bash
mise -C "$SURVEY_REPO" run index
```

`mise -C "$SURVEY_REPO" run doctor` タスクが存在する場合は続けて実行し、ERROR が出たら（sources 参照切れ・
related の片方向・strength/maturity 欠落など）その場で修正してから次に進む（存在しない場合はスキップ可）。

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
