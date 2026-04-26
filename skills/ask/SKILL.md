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

## 設計思想 — Berrypicking

Bates (1989) の berrypicking モデルは「クエリは進化する、検索は単一戦略では完結しない」と説く。
このスキルは古典 IR の「単一クエリ → 単一結果集合」ではなく、6 戦略を組み合わせた探索を行う。

| Bates 戦略 | survey-any 上の実装 |
|---|---|
| Subject search | `mise run search <tag>` / fm-dump の jq フィルタ |
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

```bash
mise -C "$SURVEY_REPO" run fm-dump
```

各要素: `{topic, title, status, tags, related, created, path}`

jq でフィルタ:

```bash
mise -C "$SURVEY_REPO" run fm-dump | jq '.[] | select(.tags | index("unity"))'
mise -C "$SURVEY_REPO" run fm-dump | jq '.[] | select(.title | test("keyword"; "i"))'
```

タグ統制を考慮するなら `vocab/tags.yml` で preferred 形を確認するとヒット率が上がる。

### 3. 補助コマンド (戦略別)

```bash
mise -C "$SURVEY_REPO" run fm-tags                  # タグ一覧（使用頻度付き）
mise -C "$SURVEY_REPO" run search <tag>             # subject search
mise -C "$SURVEY_REPO" run fm-related <topic>       # area scanning
mise -C "$SURVEY_REPO" run cited-by <reference>     # citation searching (forward-chaining)
mise -C "$SURVEY_REPO" run cites <topic>            # footnote chasing (backward-chaining)
mise -C "$SURVEY_REPO" run list                     # 全トピック一覧
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

### 5. 回答

- トピック内のソースを引用して回答する
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
