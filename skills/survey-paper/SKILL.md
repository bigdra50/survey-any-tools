---
name: survey-paper
description: |
  学術論文の再帰的サーベイスキル。survey-any リポジトリに記録する。
  6項目サーベイフォーマットで各論文をまとめ、引用・被引用を芋づる式に探索して飽和するまで続ける。
  subagent で並列処理しコンテキストを節約する。ghq でリポジトリパスを自動解決。
  Use when: 「論文サーベイ」「paper survey」「学術調査」「文献調査」「論文を網羅的に」と依頼されたとき。
  /survey との違い: /survey は記事・スライド含む一般調査。本スキルは学術論文に特化し、
  6項目サーベイ + 再帰的引用探索 + 飽和判定を行う。
license: MIT
model: claude-opus-4-7
effort: max
---

# Paper Survey

学術論文の再帰的サーベイ。6項目サーベイで各論文をまとめ、引用グラフを飽和するまで探索する。

前提: `ghq`, `mise`, `jq`, `curl`, `python3` がインストール済みであること。

## Workflow

### 0. パス解決

```bash
SURVEY_REPO=$(ghq list --full-path | grep 'survey-any$' | head -1)
```

以降の作業はすべて `$SURVEY_REPO` 基準で行う。

### 1. シード論文の発見

ユーザーから受け取ったテーマ・キーワード・論文URLをもとに初期論文を探す。

検索ソース（優先順位）:
1. WebSearch で Google Scholar / arXiv / 各分野リポジトリを横断検索
2. Semantic Scholar API で構造化された書誌情報を取得

```bash
# Semantic Scholar 検索
curl -s "https://api.semanticscholar.org/graph/v1/paper/search?query=<QUERY>&limit=10&fields=title,authors,year,citationCount,openAccessPdf,externalIds,abstract" | jq '.'

# arXiv ID がわかっている場合
curl -s "https://api.semanticscholar.org/graph/v1/paper/arXiv:<ARXIV_ID>?fields=title,authors,year,citationCount,openAccessPdf,externalIds,abstract,references.title,references.externalIds,references.citationCount,citations.title,citations.externalIds,citations.citationCount"
```

Semantic Scholar API のレート制限: 認証なしで 1 req/sec。429 が返ったら数秒待ってリトライする。

### 2. 既存トピックとの関連確認

```bash
mise -C "$SURVEY_REPO" run fm
```

関連トピックがあれば、そのディレクトリ内にサーベイ結果を統合するか、新規トピックを作るか判断する。
迷う場合は AskUserQuestion で確認。

### 3. トピック作成

```bash
mise -C "$SURVEY_REPO" run new-report <topic-name>
```

### 4. 論文の読み込みと6項目サーベイまとめ

各論文について subagent を起動し、以下のフローを並列実行する。

#### 4a. 論文本文の取得（優先順位）

| 優先度 | 方法 | 条件 |
|--------|------|------|
| 1 | Semantic Scholar `openAccessPdf` → curl でダウンロード → Read (pages指定) | openAccessPdf が存在 |
| 2 | ar5iv HTML (`https://ar5iv.labs.arxiv.org/html/<arxiv_id>`) → WebFetch | arXiv ID が存在 |
| 3 | arXiv PDF (`https://arxiv.org/pdf/<arxiv_id>`) → curl + Read | arXiv ID が存在 |
| 4 | WebFetch でアブストラクトページ | URL が存在 |
| 5 | Semantic Scholar のアブストラクトのみ | 上記すべて不可 |

Read でPDFを読む場合: 1回20ページまで。長い論文は `pages: "1-20"`, `pages: "21-40"` と分割する。

#### 4b. 6項目サーベイで reference 作成

```bash
mise -C "$SURVEY_REPO" run new-paper-reference <name>
```

テンプレートの各セクションを埋める:

| セクション | 記入内容 |
|-----------|---------|
| どんなもの？ | 論文の目的と提案手法を2-3文で |
| 先行研究と比べてどこがすごい？ | 差別化ポイント、新規性 |
| 技術や手法のキモはどこ？ | コアアルゴリズム、アーキテクチャ、理論的貢献 |
| どうやって有効だと検証した？ | 実験設定、ベースライン、定量結果 |
| 議論はある？ | 限界、未解決課題、著者自身の言及 |
| 次に読むべき論文は？ | 引用先から重要なものをピックアップ |

frontmatter も埋める:
- `read_depth`: `full`（本文読了）/ `overview`（構成・要点は把握、詳細未読）/ `abstract`（アブストラクトのみ）
- `arxiv_id`, `doi`: リンク解決の照合キーになるため、取得できたものは必ず記入する
- `semantic_scholar_id`: 取得できたら記入
- `citation_count`: Semantic Scholar から取得

#### 4c. subagent の使い方

1本の論文 = 1 subagent。`model: "opus"` を指定して起動する。
プロンプトには `$SURVEY_REPO` の解決結果（絶対パス）を埋め込む。

```
論文「{title}」を読んで6項目サーベイでまとめてください。

論文情報:
- Semantic Scholar ID: {paper_id}
- arXiv ID: {arxiv_id} (あれば)
- openAccessPdf: {pdf_url} (あれば)

手順:
1. 論文本文を取得（優先順位: openAccessPdf → ar5iv HTML → arXiv PDF → abstract）
2. `mise -C {SURVEY_REPO_ABSOLUTE_PATH} run new-paper-reference {ref_name}` で reference ファイルを作成
3. 6項目サーベイの6項目を埋める
4. frontmatter のメタデータを埋める
5. Semantic Scholar API で引用（references）と被引用（citations）の両方を取得し、
   次に読むべき論文リストを作成する（各エントリに arXiv ID があれば必ず含める）
   - references: この論文が参照している先行研究（過去方向）
   - citations: この論文を引用している後続研究（未来方向・最新事例への到達に必須）
   各論文の {title, arxiv_id, semantic_scholar_id, citationCount, openAccessPdf, year} を
   JSONで返す

作業ディレクトリ: {SURVEY_REPO_ABSOLUTE_PATH}
```

subagent の返却値から「次に読むべき論文リスト」を収集し、次のイテレーションに回す。

### 5. 再帰的探索

```
explored = {}        # 読了済み論文の集合
frontier = [seeds]   # 未探索の論文キュー

while frontier is not empty:
    batch = frontier から未探索分を取り出す（最大5本を並列）
    
    for each paper in batch:
        subagent で 4a-4c を実行
        explored に追加
        
        次の候補を frontier に追加（explored にないもののみ）:
          - references（引用先）: 理論的基盤・先行研究（過去方向）
          - citations（被引用）: 後続研究・最新事例・応用（未来方向）
        
        citations の優先度付け:
          - citationCount が高いもの（影響力のある後続研究）
          - year が新しいもの（最新の発展）
    
    飽和判定:
        新たに frontier に追加された論文が 0 本 → 飽和、終了
        ユーザーに中間報告し、続行確認
```

飽和判定の補助基準:
- 引用数が少ない論文（< 5）ばかりになった場合も飽和とみなしてよい
- 明らかに分野が異なる論文が増えてきた場合はユーザーに確認

各イテレーションの開始時に進捗を報告する:
```
[進捗] 読了: {n}本 / 未探索: {m}本 / 今回の新規発見: {k}本
```

### 6. 論文間リンク解決

飽和後、「次に読むべき論文は？」セクションのエントリを既存 reference にリンクする。

#### 6a. 機械的リンク (arXiv ID / DOI 照合)

```bash
mise -C "$SURVEY_REPO" run link-papers
```

既存 reference の frontmatter から arXiv ID・DOI を収集し、「次に読むべき論文」中の ID と照合してリンクを挿入する。

#### 6b. LLM によるリンク補完

`mise run link-papers` 後に残った未リンクエントリ（`[→]` がない行）を処理する。

1. 未リンクエントリを収集する:
```bash
python3 -c "
import re, pathlib, sys
repo = sys.argv[1]
for f in sorted(pathlib.Path(repo + '/references').glob('*.md')):
    text = f.read_text()
    in_sec = False
    for i, line in enumerate(text.splitlines(), 1):
        if '次に読むべき論文' in line: in_sec = True; continue
        if in_sec and line.startswith('#'): in_sec = False
        if in_sec and line.strip().startswith('-') and '[→]' not in line:
            print(f'{f.name}:{i}: {line.strip()[:120]}')
" "$SURVEY_REPO"
```

2. 各未リンクエントリについて、タイトル・著者名のキーワードで references/ 内を検索:
```bash
rg -l "タイトルのキーワード" "$SURVEY_REPO/references/"
```

3. 候補が見つかったら frontmatter の title・author を確認し、同一論文と判断できればリンクを追加する。
   曖昧な場合はリンクしない（誤リンクより未リンクのほうがよい）。

#### 6c. 飽和判定の検証

`mise run link-papers` の末尾に「未調査だが複数回言及されている論文」レポートが出力される。
2回以上言及されている未調査論文がある場合、飽和判定が甘かった可能性がある。

対応方針:
- 3回以上言及: サーベイ範囲内の重要論文である可能性が高い。ユーザーに追加調査を提案する。
- 2回言及: 判断はユーザーに委ねる。数が多ければ上位のみ提案。
- テーマと明らかに無関係な論文（基盤モデル等の汎用論文）は除外してよい。

### 7. サーベイマップ生成

すべての論文を読み終えたら、`$SURVEY_REPO/topics/{topic}/README.md` に統合:

- 分野の全体像と主要な研究の流れ
- 論文間の関係性（引用構造、手法の発展系譜）
- 自分の考察・所感
- 各 reference ファイルへのリンク（`sources:` フィールド）

```bash
mise -C "$SURVEY_REPO" run index
```

### 8. 検索ソース詳細

| ソース | 用途 | アクセス方法 |
|--------|------|-------------|
| Semantic Scholar | 書誌情報・引用グラフ・OA PDF探索 | REST API (認証不要) |
| Google Scholar | 初期検索・幅広い発見 | WebSearch |
| arXiv | CS/Physics/Math の OA 論文 | PDF直接DL + Read, ar5iv HTML |
| PubMed | 医学・生命科学 | WebSearch or E-utilities API |
| CORE | OA論文の全文取得補完 | WebSearch |
| DOAJ | OAジャーナル | WebSearch |

### Semantic Scholar API リファレンス

```bash
# キーワード検索
curl -s "https://api.semanticscholar.org/graph/v1/paper/search?query=<QUERY>&limit=10&fields=title,authors,year,citationCount,openAccessPdf,externalIds,abstract"

# 論文詳細 + 引用/被引用
curl -s "https://api.semanticscholar.org/graph/v1/paper/<PAPER_ID>?fields=title,authors,year,abstract,citationCount,openAccessPdf,externalIds,references.title,references.externalIds,references.citationCount,citations.title,citations.externalIds,citations.citationCount"

# PAPER_ID の形式: Semantic Scholar ID, arXiv:<id>, DOI:<doi>, PMID:<pmid>
```
