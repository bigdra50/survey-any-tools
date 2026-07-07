---
name: ask
description: |
  survey-any リポジトリに蓄積された既存調査を検索・参照して質問に回答するスキル。
  ghq でリポジトリパスを自動解決し、mise タスク経由でトピックを横断検索、
  該当する topics/references をソース付きで回答する。
  Bates の berrypicking モデルに沿って、単発検索ではなく複数戦略で動線を提示する。
  Use when: ユーザーが既存リサーチの内容について質問したとき、または既存知識を引きたいとき。
  「〜について教えて」「〜の内容は?」「〜ってどうだった?」「前に調べた〜」
  「〜のトピックある?」「〜のナレッジ検索」「survey-any確認」「調査結果参照」
  「〜について何か知ってる?」「リサーチノート検索」など。
  新規調査（/survey）や整理（/inbox-organize）とは別。
license: MIT
---

# Ask

survey-any の蓄積知識を berrypicking 戦略で検索・参照し回答する。

前提: `ghq`, `mise`, `jq` がインストール済みであること。

## 補助要素の境界

- **本文の `mise -C "$SURVEY_REPO" run ...` が正典**。`scripts/query.sh` は薄いラッパーで、本文と等価な経路のみ提供する（差分が出たら本文を優先）。
- **動線提示はリンク列挙のみ**。`cited-by` 等の補助コマンドは「ユーザーが次に叩く想定のコマンド」として名前を列挙するだけで、回答生成中には実行しない。
- **sources 空・補助コマンド未対応の topic** では related フィールドや fm-related の重複度を fallback として使う。動線カテゴリごとの fallback は §4 末尾参照。

## 設計思想 — Berrypicking

Bates (1989) の berrypicking モデルは「クエリは進化する、検索は単一戦略では完結しない」と説く。
このスキルは古典 IR の「単一クエリ → 単一結果集合」ではなく、6 戦略を組み合わせた探索を行う。

| Bates 戦略 | survey-any 上の実装 |
|---|---|
| Subject search | `mise run fm \| jq '.[] \| select(.tags \| index("<tag>"))'` |
| Footnote chasing | `mise run cites <topic>` で sources を辿る |
| Citation searching | `mise run cited-by <ref>` で reference → topics 後向き |
| Author searching | reference frontmatter の `author:` を grep |
| Area scanning | `mise run fm-related <topic>` でタグ近接 |
| Journal run | tag 一覧を時系列で走査 |

詳細は `topics/bates-berrypicking-pkb-application/`。

## Workflow

### 1. パス解決

```bash
SURVEY_REPO=$(ghq list --full-path | grep 'survey-any$' | head -1)
```

空ならエラー終了し、ユーザーに `ghq get` を促す。

### 2. 初期検索 (Subject search)

タグベースのマッチング (`fm` がプリミティブ。タグ検索・トピック一覧などはここから合成する):

```bash
mise -C "$SURVEY_REPO" run fm
```

各要素: `{topic, title, status, tags, related, created, path}`

jq でフィルタ:

```bash
mise -C "$SURVEY_REPO" run fm | jq '.[] | select(.tags | index("unity"))'
mise -C "$SURVEY_REPO" run fm | jq '.[] | select(.title | test("keyword"; "i"))'
mise -C "$SURVEY_REPO" run fm | jq -r '.[] | "\(.status)\t\(.title)\t\(.path)"'  # 一覧
```

タグ統制を考慮するなら `vocab/tags.yml` で preferred 形を確認するとヒット率が上がる。

BM25 全文検索 (タイトル + 本文。英語と日本語の両方をサポート):

```bash
mise -C "$SURVEY_REPO" run build-index           # 初回 / topic 追加後に再構築
mise -C "$SURVEY_REPO" run search-fulltext "berrypicking 個人ナレッジ" --top 10
mise -C "$SURVEY_REPO" run search-fulltext "..." --kind topic    # topic のみ
```

タグでヒットしないテーマでも本文の語彙でヒットするので、subject search が空振ったら fulltext を試す。

### 3. 補助コマンド (戦略別)

```bash
mise -C "$SURVEY_REPO" run fm-tags                                              # タグ一覧（使用頻度付き）
mise -C "$SURVEY_REPO" run fm | jq '.[] | select(.tags | index("<tag>"))'       # subject search
mise -C "$SURVEY_REPO" run fm-related <topic>                                   # area scanning
mise -C "$SURVEY_REPO" run cited-by <reference>                                 # citation searching (forward-chaining)
mise -C "$SURVEY_REPO" run cites <topic>                                        # footnote chasing (backward-chaining)
mise -C "$SURVEY_REPO" run fm | jq -r '.[] | "\(.status)\t\(.title)\t\(.path)"' # 全トピック一覧
```

### 4. 内容読み込みと動線提示

該当する `$SURVEY_REPO/topics/<topic>/README.md` を Read で読む。

berrypicking の本質は「読みながらクエリを進化させる」こと。回答時に次の動線を 2-3 件提示する:

- More like this — `fm-related <topic>` の上位
- Cited by — reference を引用している他 topic (`cited-by <reference>`)
- Area scan — 同じ broader タグ (vocab/tags.yml の broader/narrower)

`sources:` フィールドに references が記載されている場合、
必要に応じて `$SURVEY_REPO/references/<name>.md` も読んで根拠にする。
references 末尾の `<!-- backlinks:start -->` 領域には自動生成された "Cited by" がある。

動線カテゴリごとの fallback (データ欠損時):

- `sources:` が空 → Footnote chasing は frontmatter `related` フィールドに置き換える
- reference に backlinks が無い → Cited by はスキップ、Area scan を 1 件増やす
- fm-related の重複度が低い → Area scan は broader タグ (vocab/tags.yml) を辿る

### 5. 探索ログの記録 (任意 — 実行条件あり)

以下のいずれかに該当するときのみ記録する (毎回ではない):

- ヒットゼロのクエリだった (Kuhlthau の Exploration phase 相当 — `/survey` のネタとして残す価値が高い)
- berrypicking 戦略を 2 回以上切り替えた (進化したクエリの軌跡を残す)
- ユーザーが follow-up を明示的に出した (会話の継続性が確認できた)

それ以外はスキップしてよい (記録自体のオーバーヘッドを避ける)。

berrypicking trace を `memory/seeking-trace.jsonl` に追記する。
1 ステップ = 1 JSON 行。複数ターンで進化したクエリは 1 ステップずつ記録する。

```bash
mise -C "$SURVEY_REPO" run trace \\
  --query "..." \\
  --hits topic-a,topic-b \\
  --picked topic-a \\
  --next "..." \\
  --strategy subject  # subject|footnote-chasing|citation-searching|author|area-scan|journal-run
```

ヒットゼロのクエリ (= 不確実性が高い段階。Kuhlthau の Exploration phase) も
記録すると、後で `/survey` の有力なネタリストになる。

このログは `.gitignore` 対象 (個人の探索履歴) なので共有はされない。

### 6. 回答

- トピック内のソースを引用して回答する
- 引用する reference に `strength:` frontmatter があれば、信頼度を 1 行添える
  （例:「（根拠: single-author-preprint、示唆レベルとして扱う）」）。無ければこの行は省略する
- 該当なしなら「既存の調査に含まれていない」と明示する
- 追加調査が有益な場合は `/survey` の利用を提案する
- 回答末尾に「次に辿れる動線」セクションを付ける (複数戦略が立つ場合は推奨)

例:

```
[本文回答]

## 次に辿れる動線
- More like this: <topic-A>, <topic-B>
- Cited by: <topic-C> (`<reference-X>` 経由)
- Area scan: <broader-tag> 配下に <topic-D>, <topic-E>
```

これにより利用者は次のクエリを見つけやすくなる (= berrypicking の継続)。
