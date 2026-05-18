---
name: course
description: |
  調査済み内容を土台に学習コース (courses/) を作成するスキル。
  テーマを受け取り、既存 topics/references を検索し、AskUserQuestion で学習者の理解度を
  診断してから、必要に応じて /survey または /survey-paper で追加情報を収集し、
  理解度と学習目標に合わせた順序付きレッスン群を生成する。
  ghq で survey-any リポジトリのパスを自動解決するため、どのプロジェクトで作業中でも呼び出せる。
  Use when: ユーザーが「〜の学習コース作って」「〜を習得したい」「〜のチュートリアルほしい」
  「〜を体系的に学べるコース」「learning course」「カリキュラム作成」と依頼したとき。
  既存調査の参照は /ask、新規調査は /survey、論文サーベイは /survey-paper を使う。
license: MIT
---

# Course

既存の survey-any 知識を起点に、学習者の理解度に合わせた学習コースを courses/ 以下に生成する。

前提: `ghq`, `mise`, `jq` がインストール済みであること。

## Workflow

### 1. パス解決

```bash
SURVEY_REPO=$(ghq list --full-path | grep 'survey-any$' | head -1)
```

空ならエラー終了し、ユーザーに `ghq get` を促す。
以降のコマンドは `mise -C "$SURVEY_REPO"` 経由、または `cd "$SURVEY_REPO"` 後に実行する。

### 2. テーマの確認

ユーザー入力から以下を整理する。不明確な場合は AskUserQuestion で確認する。

- コースのテーマ（例: "Unity XR 入門"）
- 学習者像（自分自身か / 他人向けか、既存スキル）
- 学習目標（コース修了時に何ができればゴールか）

### 3. 既存資料の棚卸し

```bash
mise -C "$SURVEY_REPO" run fm | jq '.[] | {topic, title, tags, status}'
mise -C "$SURVEY_REPO" run fm-tags
```

テーマに関連する topics・references を特定する。

```bash
# タグで絞り込む例
mise -C "$SURVEY_REPO" run fm | jq --arg t "unity" '
  .[] | select(.tags | index($t))
'
# references のタグも確認
for f in "$SURVEY_REPO"/references/*.md; do
  tags=$(sed -n 's/^tags: *\[\(.*\)\]/\1/p' "$f" | head -1)
  [ -n "$tags" ] && echo "$(basename "$f"): $tags"
done
```

ヒットしたトピックの README.md を Read で読み、カバー範囲（何が書かれているか）を把握する。

### 4. 理解度診断（AskUserQuestion）

学習者の現在地を測らないとコース設計はできない。
既存資料からキーとなる概念を 3〜4 個抽出し、**AskUserQuestion で理解度クイズを出す**。

#### 4a. 診断設計の原則

- 質問数は 3〜4 問。多すぎると離脱する
- 各質問は 2〜4 択の単一選択（multiSelect: false）
- 各選択肢は「知識レベルを示す答え」にする。「わからない」も必ず選択肢に含める
- カバー範囲が広い場合は「どこから学びたいか」を先に聞いて診断範囲を絞る

#### 4b. 診断項目の例

テーマ: "Unity XR 入門" の場合
- Q1「XR Interaction Toolkit の XRRayInteractor の役割は?」
  - 選択肢: A. 正解の説明 / B. 部分的に正しい / C. 誤った説明 / D. わからない
- Q2「OpenXR の役割について正しいのは?」
  - 選択肢: A〜D
- Q3「Quest ビルドで必要な設定を 1 つ挙げよ」
  - 選択肢: A〜D

#### 4c. 診断結果の集計

正答数・誤答パターンから現在地を 3 レベルに分類する。

| レベル | 判定基準 | コース構成への反映 |
|--------|----------|--------------------|
| beginner | 「わからない」が過半数 | 前提概念の導入レッスンから開始。用語集を厚めに |
| intermediate | 正答 / 部分正答が半分前後 | 前提は軽く復習、実装レッスンに重点を置く |
| advanced | ほぼ正答 | 前提をスキップ。応用・ハマりどころ・比較検討に集中 |

### 5. 不足情報の洗い出し

診断結果を踏まえて、学習者が到達すべきゴールと既存資料のギャップを比較する。

不足判定の基準:
- ゴールに必要な概念で、どの topics/references にも言及されていない
- 既存資料が古すぎる（frontmatter の `created` が目安）
- レベルに対して既存資料の粒度が合わない（beginner 向け説明がない等）

不足があれば、AskUserQuestion でユーザーに追加調査の是非を確認してから実施する。

| 不足種別 | 呼び出すスキル |
|---------|---------------|
| 一般トピックの追加調査 | `/survey` |
| 学術論文の深掘り | `/survey-paper` |
| 単発の外部資料を記録だけしたい | `mise run new reference <name>` で直接追加 |

追加調査で生成された topics/references を再度 `fm` で確認し、カバレッジが満たされたかチェックする。
満たされないまま 2 巡しても解消しない場合、「現時点で足りる範囲のコースを作る」方針にユーザー合意を取る。

### 6. カリキュラム設計

診断結果と利用可能な資料を突き合わせ、以下を決める。

- コース名 (kebab-case・英数字。例: `unity-xr-intro`)
- difficulty: `beginner` / `intermediate` / `advanced`
- レッスン数と各レッスンの主題（原則 5〜10 本、1 本 15〜45 分）
- 各レッスンが依拠する topics/references
- 各レッスンの objectives（3 項目以内）

レッスン分割のガイドライン:
1. 前提知識のウォームアップ → 中核概念 → 実践 → 応用・比較 の順
2. 1 レッスンに 1 つのコア概念を載せる。詰め込みすぎない
3. 依拠する topics/references が同一のレッスンはまとめてよい
4. 各レッスンの末尾に「理解度チェック」と「次のレッスンへの橋渡し」を置く

設計案をユーザーに提示し、AskUserQuestion で合意を取る。
項目: 「このレッスン順で OK か?」「追加したいテーマは?」「削りたいレッスンは?」

### 7. コース生成

```bash
mise -C "$SURVEY_REPO" run new-course <course-name>
```

README.md の frontmatter を埋める:
- title, status (`draft` で開始), tags, difficulty, prerequisites
- estimated_hours（各レッスンの estimated_minutes 合計を時間換算）
- objectives, sources.topics, sources.references

README.md 本文には以下を記述する。
- 概要、対象読者、学習目標、前提知識
- コース構成（レッスンへのリンク一覧 + 各レッスンの 1 行要約）
- 参考資料（sources の topics / references をリンク形式で列挙）

### 8. レッスン執筆

各レッスンについて順番にファイルを作成する。

```bash
mise -C "$SURVEY_REPO" run new-lesson <course-name> <slug>
```

レッスン本文のルール:
- 既存 topics/references にある内容は **要点のみ抜粋** し、詳細は本文中でリンクに誘導する
- 自分の推測・伝聞は書かない。根拠は sources 経由で追える状態にする
- 各レッスンは前提のレッスンに存在しない概念を新たに導入しない限り理解できること
- 末尾に 2〜3 問の「理解度チェック」問題を置く（答えはレッスン内から参照できる）

レッスン数が多い場合、Agent (`general-purpose`) を並列で起動し、レッスンごとに執筆させる。
その際のプロンプトには以下を必ず含める:
- `$SURVEY_REPO` の絶対パス
- 対象ファイルの絶対パス（例: `$SURVEY_REPO/courses/<name>/03-foo.md`）
- 依拠する topics/references の絶対パス
- レッスンの objectives と estimated_minutes
- 前後のレッスンタイトル（接続用）

### 9. 仕上げ

```bash
# README.md の lessons 一覧・sources を最終確認
# frontmatter の estimated_hours を再計算
mise -C "$SURVEY_REPO" run index
```

### 10. 完了報告

ユーザーに以下を伝える:
- 作成したコースのパス (`$SURVEY_REPO/courses/<name>/`)
- レッスン一覧（タイトルと推定時間）
- 追加で調査した topics/references のリスト（あれば）
- viewer で確認するなら `mise run deploy` または `cd viewer && bun run dev`

git commit は行わない（ユーザーが必要に応じて実施）。

## 禁止事項

- 理解度診断をスキップして beginner 決め打ちでコースを作らない（ユーザーが明示的にスキップ指示した場合を除く）
- 既存 topics/references をコピペしてレッスン本文に貼り付けない（リンクと要約に留める）
- 日本語やスペースをディレクトリ名・ファイル名に使わない
- `status: published` で作成しない。初期は必ず `draft`
