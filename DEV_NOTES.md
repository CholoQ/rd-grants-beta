# DEV_NOTES — 助成金ナビ β (grant_mvp)

> Claude Code で作業を始める前に、このファイルを必ず読んでください。

---

## プロジェクトの目的

研究開発型企業が、NEDO / JST / AMED / Jグランツ の4データソースを横断して補助金・助成金を探せるβ版ツール。

- チャット形式で絞り込み条件を入力し、自社に合う公募を発見できる
- 難しい公募要件を「やさしく読む」機能で要点整理できる
- 専門家への相談導線（リード獲得）を持つ

---

## 現在の主要機能

| 機能 | 説明 |
|------|------|
| チャット式絞り込み検索 | 6ステップ（研究フェーズ→技術分野→支援タイプ→予算→地域→補足）で条件を入力し POST /api/rd-search を呼ぶ |
| やさしく読む | 結果カードの「やさしく読む」ボタンで GET /api/grant-summary を呼び、Gemini要約を表示する |
| ウォッチリスト | localStorage に最大50件保存。ページ再読み込みでも維持される |
| 比較・準備チェック | ウォッチリストのIDを POST /api/compare / /api/readiness-check に渡してサイドパネルに結果表示 |
| 専門家相談導線 | `data-lead-type` 属性を持つボタンがダイアログを開き、POST /api/lead で保存する |

---

## 重要なファイル構成

```
grant_mvp_next_gemini_connected/
├── server.py                  # エントリポイント（grant_mvp.app.main を呼ぶだけ）
├── DEV_NOTES.md               # このファイル
├── grant_mvp/
│   ├── app.py                 # HTTPサーバー本体（ルーティング）
│   ├── config.py              # 環境変数・DBスキーマ・定数定義
│   ├── rd_scheme.py           # /api/rd-search と /api/rd-meta のロジック
│   ├── features.py            # compare / readiness-check / grant-summary のロジック
│   ├── ranking.py             # /api/recommend のロジック（旧フロー）
│   ├── repository.py          # SQLite CRUD
│   ├── gemini_summary.py      # Gemini API 呼び出し
│   ├── jgrants.py / nedo.py / jst.py / amed.py  # データソース別クローラー
│   ├── grants.db              # SQLiteデータベース
│   └── static/
│       ├── index.html         # フロントエンド HTML（フレームワークなし）
│       ├── style.css          # スタイル（全スタイルここに集約）
│       └── app.js             # フロントエンド JS（フレームワークなし、519行）
```

---

## 触ってはいけないID・クラス・属性（app.js が依存）

### HTML ID（削除・変更禁止）

| ID | 役割 |
|----|------|
| `#search` | ページ内リンクアンカー（「助成金を探す」ボタンの遷移先） |
| `#chatMessages` | チャット吹き出しの描画コンテナ |
| `#chatProgress` | ステップ表示テキスト |
| `#chatTextInput` | チャット自由入力欄 |
| `#chatSendBtn` | 送信ボタン（clickイベント登録済み） |
| `#chatInput` | 入力行ラッパー（hidden切り替えで表示制御） |
| `#results` | 検索結果リストの描画コンテナ |
| `#resultMeta` | 件数・ソース内訳テキスト |
| `#showWatchlist` | ウォッチリスト表示ボタン（clickイベント登録済み） |
| `#sideOutput` | 比較・準備チェック結果の表示エリア |
| `#runCompare` | 比較実行ボタン |
| `#runReadiness` | 準備チェック実行ボタン |
| `#leadDialog` | 相談フォームダイアログ |
| `#leadForm` | フォーム本体（submitイベント登録済み） |
| `#leadTitle` | ダイアログタイトル（JSで書き換え） |
| `#leadDescription` | ダイアログ説明文（JSで書き換え） |
| `#leadStatus` | 送信結果メッセージ表示 |

### CSSクラス（削除・rename禁止）

| クラス | 役割 |
|--------|------|
| `.result-card` | 結果カード（クリックイベントの祖先セレクタ） |
| `.details` | やさしく読む展開エリア（`hidden`切り替え） |
| `.result-actions` | ボタン群ラッパー |
| `.chat-msg--bot` / `.chat-msg--user` | 吹き出し方向制御 |
| `.chat-bubble` | 吹き出し本体 |
| `.chat-chips` | 選択肢チップ行 |
| `.chip-btn` / `.chip-btn--skip` | チップボタン（clickイベント対象） |
| `.layout` | 2カラムレイアウト（スクロール先として `.layout` を参照） |
| `.sum-*` 全般 | Gemini要約HTML（`renderSummaryHtml()` で生成） |
| `.match-reasons` | おすすめ理由ブロック（`renderItems()` で生成） |

### data属性（削除禁止）

| 属性 | 役割 |
|------|------|
| `data-action="summary"` | やさしく読むボタン識別子 |
| `data-action="watch"` | ウォッチ保存ボタン識別子 |
| `data-action="consult"` | 相談ボタン識別子 |
| `data-lead-type` | 相談ダイアログ種別（consultation / automation_pack / expert_listing / feedback） |
| `data-value="__reset__"` | 再検索チップ識別子 |
| `data-value="__skip__"` | スキップチップ識別子 |
| `data-id` | result-card の grant ID |

### 触ってはいけないAPI（バックエンド変更禁止）

```
GET  /api/rd-meta          → チャット選択肢の取得
POST /api/rd-search        → メイン検索（body: {rd_phase, tech_domain, support_type, budget_range, region_text, free_text, sources, fast_mode}）
GET  /api/grant-summary    → やさしく読む（?id=）
POST /api/lead             → 相談フォーム送信
POST /api/compare          → 比較表生成（body: {ids}）
POST /api/readiness-check  → 準備チェック（body: {ids}）
```

---

## これまでの主な変更

### 2026-05-05 — フロントエンド リデザイン着手（フレンドリーアシスタント コンセプト）

**ステップ1 完了：** `style.css` カラーパレット変更
- `--bg` クリーム寄りに（`#f6f3ee` → `#fdf8f3`）
- `--accent` コーラルに（`#965f2f` → `#f5694c`）
- `--accent-2` ミントに（`#2f6f63` → `#3aaa8c`）
- 新変数追加：`--accent-3`（ライトブルー）、`--accent-warm`（オレンジ）、`--radius-card`

**ステップ2 完了：** ナビゲーションヘッダーの追加
- `index.html` の `<body>` 直後に `<nav class="site-nav">` を追加
- `style.css` 末尾に `.site-nav` 系スタイルを追加（展開形式）
- 新クラス：`.button--ghost`、`.button--primary-warm`
- 「無料で相談する」は `data-lead-type="feedback"` で既存 `openLead()` に接続済み

**ステップ3 完了：** ヒーローセクションの再構成
- `<header class="hero">` の内容を「フレンドリーアシスタント」コンセプトに刷新
- 左：新コピー（`どの助成金が合うか、一緒に探しましょう。`）＋安心ポイント3つ
- 右：装飾チャットプレビューカード（`.hcp-*` クラス、JSなし・視覚のみ）
- `<aside class="notice">` を `<aside class="hero__preview">` に置き換え（JSイベントなし）
- `data-lead-type` ボタンは維持、`href="#search"` も維持
- 880px以下でプレビューカード非表示

**ステップ4 完了：** 検索結果カードの視認性向上
- CSS追加のみ（HTML・JS変更なし）
- `.result-card` にホバーアニメーション追加
- `.pill` を温かみのある茶系、`.pill--score` を緑系に変更
- `.match-reasons` を緑の枠付きボックスに、`li::before` を `✓` マークに
- `.result-actions` ボタンを3色に色分け（コーラル / ミント / ブルー）
- `.details` を緑系の薄い背景カードに（`white-space: pre-wrap` は意図的に除外）

**ステップ5 完了：** チャットUIの見た目強化
- CSS追加のみ（HTML・JS変更なし）
- チャットヘッダーに温かいグラデーション背景
- `#chatProgress` テキストをミント色（`--accent-2`）に
- ボット吹き出しに薄いシャドウ、ユーザー吹き出しにコーラルシャドウ
- チップボタンにシャドウ＋ホバー時シャドウ強調
- 入力欄フォーカス時にミント色グロー
- 送信ボタン（`.chat-send-btn`）をコーラル色で統一

**ステップ6 完了：** サイドパネル＆レイアウト全体の整理
- 検索結果見出しを「あなたにおすすめの助成金・補助金」に変更
- サイドパネルの「次の収益導線」→「サポートメニュー」に変更（ユーザー向け表現に）
- ミニカード3枚にアイコン（🔔👩‍💼📊）追加、テキストを簡潔化
- `#runCompare`, `#runReadiness`, `#sideOutput`, `data-lead-type` は完全維持
- CSS: `main` padding増加、`.layout` gap拡張、`.side-panel`・`.mini-card`・`.side-output` 整理

**ステップ7 完了：** 信頼訴求エリアの追加
- `</main>` 直後に `.trust-banner` セクションを追加
- 5項目：掲載制度数 / 毎月更新 / 利用企業数 / 会員登録無料 / SSL対応
- **⚠️ 公開前要対応：** 「掲載制度数 1,200+」「利用企業数 3,000+」は現在ダミー値。公開前に実績ベースの数値へ差し替えること
- 差し替え箇所：`index.html` の `.trust-stat__num` テキスト（HTMLコメントで案内済み）
- 720px以下で区切り線非表示・ラップ表示

**ステップ8 完了：** モバイル対応の最終調整
- CSS追加のみ
- 620px以下：main/hero/chat/result-card のpadding縮小、lead font-size 15px、section-title h2 18px
- 380px以下：ナビの「ログイン」ボタン非表示（「無料で相談する」のみ残す）

---

## Claude Code で作業するときのルール

1. **作業開始前にこのファイルを読む**
2. 既存APIのパス・レスポンス形式を変更しない
3. 上記ID・クラス・data属性を削除・rename しない
4. `app.js` のファイル全体Overwrite（Write tool）は禁止。Edit tool で差分のみ変更する
5. 変更は1ステップずつ、ファイル種別（CSS / HTML / JS）ごとに分ける
6. 各差分は以下の形式で提示する：
   - 変更目的 / 変更対象ファイル / **安全度：高・中・低** / 差分の概要 / 壊れる可能性がある箇所 / 確認ポイント
7. 安全度「低」の場合は代替案を提示する
8. 作業後はこのファイルの「これまでの主な変更」セクションを更新する

---

## 動作確認手順

```bash
# 起動
cd /Users/chol/Downloads/grant_mvp_next_gemini_connected
python server.py

# ブラウザで確認
open http://127.0.0.1:8000
```

### 最低限チェックする動作フロー

1. ページ読み込み → チャットの最初のステップが表示されること
2. チップ選択 → 次のステップに進むこと（全6ステップ）
3. 検索完了 → 結果カードが表示されること
4. 「やさしく読む」クリック → 要約が展開されること
5. 「ウォッチに保存」→ 「ウォッチリストを見る」で確認できること
6. 「専門家に相談」→ ダイアログが開くこと
7. フォーム送信 → 「送信しました」が表示されること

---

## 次にやる候補

- [x] ステップ1：CSSカラーパレット刷新
- [x] ステップ2：ナビゲーションヘッダーの追加
- [x] ステップ3：ヒーローセクションの再構成
- [x] ステップ4：結果カードの視認性向上
- [x] ステップ5：チャットUIの見た目強化
- [x] ステップ6：サイドパネル＆レイアウト全体の整理
- [x] ステップ7：信頼訴求エリアの追加
- [x] ステップ8：モバイル対応の最終調整

**ステップA 完了：** ロゴ・ナビリンク変更
- ロゴを「みつけろ！R&D助成金」ブランドに刷新（`logo-mark` バッジ + `logo-text-group` + `logo-sub` 副題）
- ナビリンクを4項目に変更：助成金を探す / やさしく知る / 活用事例 / よくある質問
- CTA「無料で相談する」→「無料相談をする」に変更（`data-lead-type="feedback"` 維持）
- 新クラス：`.logo-mark`、`.logo-text-group`、`.site-nav__logo .logo-text`（スコープ限定）、`.site-nav__logo .logo-sub`

**ステップB 完了：** ヒーロー見出し・キャラクターSVG化
- h1を「どの助成金が合うの？迷ったら、私に聞いてくださいね！」に変更
- `hero__preview` 内をインラインSVG女性キャラクター（ミント×コーラル）に置き換え
- キャラクターは装飾のみ（JSなし、`aria-hidden="true"`）、880px以下で非表示
- 右上に吹き出し `.hero-speech-bubble`（NEDO・JST・AMED・Jグランツ横断検索の説明）
- `href="#search"` / `data-lead-type` ボタンは維持

**ステップD 完了：** ヒーローキャラクター画像の404修正
- `grant_mvp/static/images/` を新設し、プロジェクトルートの `images/assistant.png` を `grant_mvp/static/images/assistant.png` にコピー
- HTML（`index.html:50` の `src="images/assistant.png"`）・CSS・JS は未変更
- `serve_static` の PNG MIME 追加は未実施（現状ブラウザで画像表示OK確認済みのため保留）
- ⚠️ 旧位置のプロジェクトルート `images/assistant.png` は残存。整理する場合は別ステップで検討

**ステップE 完了：** ヒーロープレビューの見た目調整
- `style.css` のみ4ブロック編集（HTML/JS無変更）
- `.hero__preview` gap: 12px → 24px（β版注意カードとの余白を確保）
- `.hero-character-wrap` に min-height: 320px / padding-top: 8px 追加
- `.hero-character-image` width: 260px → 300px（要件 280〜320px 内）
- `.hero-speech-bubble` top: 16px → -8px / right: 0 → -12px（画像の右上外側へ移動、顔と重ならない位置）

**ステップC 完了：** サイドバー再構成
- 「サポートメニュー」3ミニカード → 「やさしく読む」「はじめての方へ」2パネルに変更
- 「やさしく読む」：ミント色カード、AI要点整理機能の説明
- 「はじめての方へ」：ウォーム色カード、3ステップガイド + 無料相談CTAボタン（`data-lead-type="feedback"`）
- 比較する・準備チェック・自動化相談・専門家掲載を `.side-actions` として下部に小さく残存
- `#sideOutput`・`#runCompare`・`#runReadiness`・`data-lead-type` は完全維持
- 新クラス：`.side-feature-card`・`--mint`・`--warm`、`.side-steps`、`.side-actions`

---

---

## SNS投稿候補生成（grant_mvp.social_posts）

サイト流入向けに、X / LinkedIn の投稿候補を `posts.csv` に下書き（draft）保存するモジュール。**SNS API は使わない・自動投稿はしない**。

### ファイル構成

```
grant_mvp/social_posts/
├── __init__.py      # 定数・CSVスキーマ・enum
├── __main__.py      # CLIエントリ（python -m grant_mvp.social_posts）
├── store.py         # posts.csv の読み書き・重複検出ヘルパ
├── safety.py        # 禁止語・公式確認文言・LinkedIn免責文
├── templates.py     # X / LinkedIn テンプレート
├── filters.py       # DBから公募抽出（read-only）
└── generator.py     # オーケストレーション
```

### 運用コマンド

```bash
# CSV初期化（初回のみ）
python -m grant_mvp.social_posts --init

# dry-run（書き込まず候補を確認）
python -m grant_mvp.social_posts --theme deadline_near --dry-run

# 通常生成（posts.csv に draft 追記）
python -m grant_mvp.social_posts --theme deadline_near

# X だけ・上限指定
python -m grant_mvp.social_posts --theme deadline_near --sns x --max-per-theme 1
```

### posts.csv スキーマ（13列・UTF-8 BOM付き）

```
id, created_at, sns, theme, grant_id, title, body, char_count,
site_url, source_url, body_hash, generation_method, status
```

- `generation_method`: 現状すべて `template`（将来 `gemini` を入れる差し込み口）
- `status`: 初期値 `draft`（将来 `approved` `posted` を入れる余地）

### 環境変数（任意）

| 変数 | 既定値 | 用途 |
|------|-------|------|
| `GRANT_MVP_SITE_URL` | `https://example.com/` | 投稿に挿入するサイトURL（**本番URL未定・差し替え必要**） |
| `GRANT_MVP_POSTS_CSV` | `<root>/posts.csv` | CSVパス上書き |
| `GRANT_MVP_DEADLINE_NEAR_DAYS` | 14 | 締切間近の閾値 |
| `GRANT_MVP_COOLDOWN_DAYS` | 30 | (grant_id, sns) のクールダウン |
| `GRANT_MVP_MAX_PER_THEME` | 2 | 1回あたり/テーマあたりの上限 |

### 重複・抑制ロジック（generator.py 内の判定順）

1. `per_sns_count` 上限到達 → スキップ
2. 直近 `recent_window`(=5)件で `(theme, grant_id)` 一致 → `skipped_recent_theme_duplicate`
3. `(grant_id, sns)` の最新投稿が `cooldown_days`(=30) 以内 → `skipped_cooldown`
4. テンプレレンダリング → 失敗時 `skipped_error`
5. `safety.validate()` で禁止語 / 公式確認文言 / 免責文 → 失敗時 `skipped_safety`
6. `body_hash` が posts.csv 内既存と完全一致 → `skipped_duplicate`

### 安全ガード（safety.py）

- 禁止語: 「絶対採択」「採択保証」「100%採択」「裏ワザ」など
- 公式確認文言: 「公式ページでご確認」等が必須
- LinkedIn 免責文: 採択を保証しない旨＋公式確認の文言が必須

### 触ってはいけないこと

- 既存ファイル（`app.py` `repository.py` `config.py` など）の改変
- `grants.db` のスキーマ（読み取りのみ）
- `posts.csv` の列構成（追加・削除しない）
- `__init__.py` の `CSV_FIELDS`（変更すると既存CSVが破損する）

### 現在対応しているテーマ

- ✅ `deadline_near`（締切が近い公募）
- ✅ `poc` / `ip` / `startup` / `sme`（S4-1/2/3 完了、2026-05-07）
- ⏳ `today`（filters.py には実装済み。直近24hに同期されたレコードが現状0件のため generator 接続は保留。後日 hours=48 化を検討）
- ✅ `howto` 助成金の選び方（S5 完了、2026-05-07。固定ノウハウ文5本・DB非依存）

### 実装ステップ履歴

| ステップ | 内容 | 状態 |
|---------|------|------|
| **S1** | ディレクトリ・CSVスキーマ・CLIスケルトン（`--init` / `--dry-run`） | ✅ 完了 |
| **S2** | `safety.py`（禁止語・公式確認・免責文）+ `templates.py`（X/LinkedInテンプレ、deadline_nearのみ） | ✅ 完了 |
| **S3** | `filters.py`（DB抽出）+ `generator.py`（end-to-end）。重複は body_hash 完全一致のみ（案A） | ✅ 完了 |
| **S6** | `(grant_id, sns)` cooldown ＋ 直近5件 `(theme, grant_id)` 重複チェック | ✅ 完了 |
| **S6.1** | `recent_theme_grant_ids(n=0)` で全件返るバグの修正（`if n <= 0: return set()`） | ✅ 完了 |
| **S4-1** | `filters.py` に find_today / find_poc / find_ip / find_startup / find_sme を追加（仮置きキーワード、case-insensitive、受付中のみ） | ✅ 完了（2026-05-07） |
| **S4-2** | `templates.py` に poc / ip / startup / sme の X / LinkedIn テンプレを追加（共通ヘルパ `_build_x_simple` / `_build_linkedin_simple` 経由） | ✅ 完了（2026-05-07） |
| **S4-3** | `generator.py` に `generate_simple_theme()` ＋ `SIMPLE_THEMES` を追加し、`__main__.py` の dispatch に4テーマ分岐を接続。実書き込み確認まで実施（posts.csv 15→23行） | ✅ 完了（2026-05-07） |
| **S4-4** | `today` テーマの generator 接続（hours閾値・件数を見て判断） | ⏳ 保留 |
| **S5** | `howto` 固定ノウハウ文5本（DB非依存）。`templates.py` に `HOWTO_POSTS` + `render_howto_x/linkedin`、`generator.py` に `generate_howto()`、`__main__.py` に dispatch 追加。実書き込み確認まで実施（X 2件 + LinkedIn 2件、posts.csv 23→27行、generation_method=template / status=draft、skipped_safety=skipped_error=0） | ✅ 完了（2026-05-07） |

### 既知の制限

- `SITE_URL` が仮値 `https://example.com/`。本番URL確定後に環境変数または `__init__.py` で差し替え必要
- 異なる公募間で `subsidy_catch_phrase` が同一の場合（NEDOの定型文など）、X用テンプレが衝突して `skipped_duplicate` が発生することがある（cooldown/recent で実質的に抑制されている）
- `today` は `last_synced_at` の直近24h内で抽出する仕様（filters.py 実装済み）。現状DBに該当レコードがなく `find_today() = 0件`。閾値を48h化するか、別定義（前日 sync_events を使う等）にするかは未決
- S4 の仮置きキーワード（POC/IP/STARTUP/SME）は精度未検証。後で `target_number_of_employees` や target_conditions 系カラムも参照候補
- S4 テンプレの LinkedIn 用 lead 文言は `「{テーマ名}｜注目の公募」` 固定。テーマ別に表現を磨く余地あり
- `howto` は固定文5本のため、同一本文は `body_hash` で再生成されない（重複としてスキップ）。追加投稿したい場合は `--max-per-theme` を増やすか、`HOWTO_POSTS` に新しい本文を追加すること。なお `howto` では cooldown / recent_theme は非適用（`grant_id=""` 共有による誤抑制を避ける目的）

---

### 今後の改善候補

- [ ] ナビにハンバーガーメニューを追加（880px以下でリンクが非表示のため）
- [ ] 信頼訴求バナーの数値を実績ベースに差し替え（**公開前必須**）
- [ ] `<title>` を「助成金ナビ β」から正式サービス名に変更
- [ ] OGP / meta description の整備
- [ ] チャット完了後の「条件を変えて再検索」をより目立つ位置に表示
- [ ] 「やさしく読む」展開エリアにスムーズアニメーション追加

---

## Render デプロイ手順（β版）

### 前提
- `grant_mvp/grants.snapshot.db` がリポジトリに含まれていること（`scripts/build_snapshot.py` で生成）
- 元 `grant_mvp/grants.db` は `.gitignore` で除外済み
- `.python-version` で Python バージョンを固定（3.11.9）

### 手順
1. リポジトリを GitHub に push
2. Render Dashboard → New → Web Service → 該当リポジトリ選択
3. 設定:
   - Runtime: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python server.py`
   - Health Check Path: `/api/health`
4. Environment Variables:
   - `GRANT_MVP_DB_PATH=grant_mvp/grants.snapshot.db`
   - `AUTO_REFRESH_ON_START=0`
   - （任意）`GEMINI_API_KEY=...`、`LOG_LEVEL=INFO`
5. Deploy 実行
6. `https://<service>.onrender.com/api/health` で `{"ok": true, ...}` 確認

### snapshot DB 更新フロー
1. ローカルで `grant_mvp/grants.db` を最新化
2. `python scripts/build_snapshot.py` を実行
3. `grant_mvp/grants.snapshot.db` を commit & push
4. Render が auto-deploy（または手動 Deploy）

### 既知の制約
- Free プランは 15 分アイドルで sleep。初回アクセスは数秒遅延
- snapshot DB は読み取り中心。`leads` テーブルへの書き込みは可能だが、再デプロイで snapshot ファイルが上書きされるため永続化されない（β版では受容、本番化時は外部DBへ移行）
- **β版では lead 保存は永続化されない**
- 問い合わせを本格的に受ける前に、外部DB / Google Sheets / Airtable / Supabase などへの移行が必要
- 公開直後は、問い合わせ導線を別途 Googleフォームやメールに逃がす選択肢もある
