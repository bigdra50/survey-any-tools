# ADR 0001: コンテンツとツールの分離

- Status: Accepted (2026-07-08)
- Date: 2026-07-08
- Deciders: bigdra50
- 関連: [tasks/reader-centered-design-2026-07.md](../../tasks/reader-centered-design-2026-07.md), [tasks/improvement-plan-2026-07.md](../../tasks/improvement-plan-2026-07.md)

## Context and Problem Statement

survey-any は 1 リポジトリに「汎用ツール」と「個人コンテンツ」が同居している。

```
survey-any (現状: 全部入り1 repo)
├─ ツール層(汎用・再生成可能・公開可)     ← apm で配布(SKILL.md のみ)
│   .apm/skills/  mise.toml  scripts/*.py(17)  templates/  vocab/(schema)  viewer/
├─ コンテンツ層(個人データ・正本・private) ← ghq で取得
│   topics/  references/  courses/  inbox/  memory/  INDEX.md  wiki/
└─ vocab/tags.yml は中間(データに応じ増える)
```

この密結合が具体的な歪みを生んでいる:

1. **再現性の穴**: apm パッケージは `.apm/skills/` の SKILL.md のみ配布する。mise.toml・scripts・topics/references は含まない。一方 SKILL.md は `ghq list | grep survey-any$` で ghq clone された repo 本体を解決し `mise -C "$SURVEY_REPO" run <task>` を呼ぶ。つまり **apm install だけでは動かず、ghq get も必須**だが README にその記載がなかった（2026-07-08 に暫定追記済み）。
2. **履歴汚染**: scripts の改修と調査データの追加が同じコミット履歴に混ざる（本件を含む複数セッションで実際に混在した）。
3. **公開性の不能**: ツールは公開したいがコンテンツは private、を 1 repo では切り分けられない。
4. **他者利用の障壁**: 「知識ベース運用ツールだけ欲しい」利用者が、個人調査データごと clone せざるを得ない。

CLAUDE.md（グローバル）の設計原則「コントラクト層（API/型）を厳密に定義し、実装層は再生成可能に保つ」は、**ツール（再生成可能）とコンテンツ（正本データ）の分離**を要求している。現状はこの原則に反する。

## Decision Drivers

- 再現性: 別マシンで最小手順・確実に再現できること
- 配布の標準性: ツールが標準的な経路（pip/uv/apm）で配布・更新できること
- 履歴の純粋性: ツールの改修とコンテンツの成長が別履歴になること
- 公開/private の分離: ツールは公開、コンテンツは private を可能にすること
- 移行の安全性: big-bang でなく段階移行できること

## 現状の技術的事実（移行設計の前提）

- **scripts の root 解決**: 全 17 ファイルが `ROOT = Path(__file__).resolve().parent.parent`（自スクリプト位置から repo root を推定）で統一。→ 共通モジュール 1 箇所に集約すれば注入方式に変えられる。
- **コンテンツ参照**: scripts は `ROOT / "topics"`, `/ "references"`, `/ "courses"`, `/ "memory"`, `/ "inbox"`, `/ "vocab"`, `/ "templates"` をハードコード。
- **mise タスク 30 個**: すべて「ツールのロジックがコンテンツに作用する」形。CLI 化すればそのままサブコマンドになる。
- **viewer**: `content.config.ts` が `base: "../topics"` 等の相対パスでコンテンツを参照（5 コレクション）。
- **層の帰属**:
  - ツール = `scripts/`, `mise.toml`, `templates/`, `viewer/`, `.apm/skills/`, `vocab/{relation-types,strength-levels,maturity-levels}.yml`（スキーマ）
  - コンテンツ = `topics/`, `references/`, `courses/`, `inbox/`, `memory/`, `wiki/`, `INDEX.md`（生成物）, `vocab/tags.yml`（データに応じ増える語彙）
  - 論点: `vocab/tags.yml` はツール（統制語彙の定義）とコンテンツ（実タグはデータ依存）の中間。分離時にどちらへ置くか要決定（本 ADR の Open Question）。

## Considered Options

### Option A: 2 リポジトリ分割

`survey-tools`（公開, apm+ghq）と `survey-content`（private, ghq/ローカル）に分ける。

- スキルは content repo を cwd/ghq で解決し、content 側の `mise.toml` が tools 側のタスクを include（mise は他ファイルの task を取り込める）または tools の scripts を相対参照する。
- Pros: repo 分割だけで scripts のリファクタは軽い。
- Cons: スキル/mise が「tools パス」と「content パス」の 2 つを解決する必要が残る。密結合が repo 境界に移るだけで、パス解決の複雑さは消えない。

### Option B: ツールを CLI 化（推奨）

`scripts/` を `survey-any` CLI（`uv tool install survey-any`）にパッケージ化する。コンテンツは素の git repo（or 任意ディレクトリ）。

- CLI がコンテンツルートを解決する（優先順: `--root` > `SURVEY_ANY_ROOT` env > cwd 上方探索）。
- スキルは `ghq list | grep` の複雑なパス解決から解放され、`survey-any <cmd>` を呼ぶだけ。
- 配布が標準経路に乗る: スキル定義 = apm、CLI = uv tool、コンテンツ = 素の git repo。
- Pros: 最もクリーン。パス解決が CLI に一元化。scripts は既に stdlib のみ＝パッケージ化が容易。ビューアも `survey-any serve` に統合できる。
- Cons: scripts の root 解決を注入方式に変えるリファクタが必要（ただし共通パターンなので集約は 1 箇所）。viewer の content base も env 化が必要。

### Option C: submodule / subtree

コンテンツを submodule 化。

- Pros: 移行の見た目は小さい。
- Cons: submodule の運用が複雑（更新・detached HEAD・CI）。密結合の本質的解決にならない。却下。

## Decision Outcome

**推奨: Option B（CLI 化）**。理由:

- scripts が既に stdlib のみで書かれており、CLI パッケージ化の障壁が最も低い。
- パス解決を CLI に一元化することで、Option A に残る「2 パス問題」を根本的に消せる。
- 配布が pip/uv という標準経路に乗り、apm はスキル定義だけを担う本来の役割に戻る。
- コンテンツが「ツールに依存しない素の Markdown リポジトリ」になり、公開/private・他者利用・履歴純粋性のすべてを満たす。

Accepted（2026-07-08、下記 Resolved Questions で 3 論点を確定）。Phase 1（挙動不変の root 一元化）から段階着手する。

## Migration Plan（段階移行・big-bang を避ける）

各フェーズは単独で動作し、途中でも既存運用を壊さない。

1. **Phase 1: root 解決の一元化（無害な準備）**
   全 scripts の `ROOT = Path(__file__)...parent.parent` を共通モジュール `_root.py` の `content_root()`（`--root` > `SURVEY_ANY_ROOT` > cwd 上方探索、fallback で従来の repo 内パス）に置換。この時点では挙動不変。
2. **Phase 2: CLI エントリポイント追加（mise と併存）**
   `pyproject.toml` で `survey-any` コンソールスクリプトを定義（`scripts/` → `survey_any/` パッケージへ再配置）。`survey-any doctor` 等が動くようにする。mise.toml は当面 CLI を呼ぶ薄いラッパーに。
3. **Phase 3: コンテンツ repo 分離**
   `topics/ references/ courses/ inbox/ memory/ wiki/ vocab/tags.yml` を `survey-content` repo（private）へ移す（**tags.yml は可変辞書＝コンテンツ側、`relation-types/strength-levels/maturity-levels.yml` は固定 enum＝CLI にバンドル**。content 側でのオーバーライドは将来余地として残す）。pre-commit hook（link-papers/backlinks/index）も content 側へ。viewer の `content.config.ts` base を `SURVEY_ANY_ROOT` 由来に変更。
4. **Phase 4: 配布経路の切り替え**
   スキル SKILL.md を `survey-any <cmd>`（CLI）ベースに更新。ビューアは **`survey-any serve` として CLI に統合**（独立 repo にしない）。CLI は **git+uv（`uv tool install git+...`）で private 配布**（PyPI 公開しない）。README/CLAUDE を「uv tool install（ツール）+ content repo clone（データ）」に。apm パッケージはスキル定義のみに純化。

## Consequences

**Good:**
- 別マシン再現が「① uv tool install survey-any ② content repo を clone ③ cwd で `/survey`」の明快な手順になる。
- ツール改修とコンテンツ成長が別履歴・別バージョンになる。
- ツールを公開、コンテンツを private にできる。他者がツールだけ使える。

**Bad / リスク:**
- 一時的にツール（CLI）とコンテンツ（repo）の 2 系統バージョンを管理する必要。
- viewer のデプロイ（Cloudflare Pages）で content パス解決の再設計が要る。
- 移行中は mise 経路と CLI 経路が併存し、二重メンテの期間が生じる。

## Resolved Questions（2026-07-08 確定）

1. **`vocab/tags.yml` の帰属 → コンテンツ側**。tags.yml は調査テーマに追従して増える可変辞書で利用者固有のため content repo に置く。検証ロジック（tags-validate）はツールだが、辞書はコンテンツ。対して `relation-types/strength-levels/maturity-levels.yml` は survey-any 手法の固定 enum スキーマ＝全利用者共通のため CLI にバンドルする（content でのオーバーライド余地は残す）。
2. **ビューア → CLI 統合**（`survey-any serve`）。独立 repo にはしない。content root は `SURVEY_ANY_ROOT` で注入。
3. **CLI 配布 → git+uv（private）**。PyPI 公開はしない。`uv tool install git+<repo>` で導入する。
