# 研究開発資金ナビ β版

NEDO / JST / AMED / Jグランツなどの研究開発系公募を、研究開発型スタートアップ・中小企業向けに探しやすくするMVPです。

この版では、単なる補助金検索ではなく、次の流れを検証します。

- 探す: 研究開発フェーズ、技術分野、支援種別、地域、金額帯で検索する
- 読む: 公募詳細・PDFをもとに「やさしく読む」で要点を整理する
- 比べる: 気になる公募をウォッチリストに保存し、比較する
- 準備する: 応募準備チェックで必要書類や確認事項を洗い出す
- 相談する: 専門家相談、公募ウォッチ自動化パック、専門家掲載希望につなげる

## 1. セットアップ

このプロジェクトは、ローカルのPython環境を汚さないように `venv` を使って起動することを推奨します。

```bash
cd grant_mvp_next_gemini_connected

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

Windowsの場合は、仮想環境の有効化だけ以下に置き換えてください。

```powershell
.venv\Scripts\activate
```

## 2. 起動方法

```bash
python3 server.py
```

ブラウザで以下を開きます。

```text
http://127.0.0.1:8000
```

終了するときは、ターミナルで `Ctrl + C` を押してください。

仮想環境を抜ける場合は以下です。

```bash
deactivate
```

## 2.5. Web公開

最短の公開先は Render です。このリポジトリには `render.yaml` を入れているので、GitHubにpushしてRenderでBlueprintとして読み込むと、次の設定で起動できます。

- Build Command: `pip install -r requirements.txt`
- Start Command: `python server.py`
- Health Check Path: `/api/health`
- Host: `0.0.0.0`
- Port: Renderが設定する `PORT` を自動利用

公開時に設定する環境変数の目安です。

```text
GEMINI_API_KEY=...
ADMIN_TOKEN=任意の長い文字列
AUTO_REFRESH_ON_START=0
FAST_MODE_DEFAULT=1
```

`ADMIN_TOKEN` を設定すると、`/api/leads` と `/api/refresh` は `X-Admin-Token` ヘッダーなしでは見られません。公開環境では必ず設定してください。

初回公開は同梱の `grant_mvp/grants.snapshot.db` を使って起動します。最新データに更新したい場合は、管理者だけが `POST /api/refresh` を実行してください。

Dockerで公開する場合は、同梱の `Dockerfile` を使えます。

## 3. APIキー設定

LLM要約・再ランキングを使う場合は、起動前にAPIキーを設定します。未設定でも、ルールベースの検索・表示は動きます。

### Geminiを使う場合

```bash
export GEMINI_API_KEY="..."
export GEMINI_MODEL="gemini-2.5-flash"
python3 server.py
```

### OpenAIを使う場合

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4.1-mini"
python3 server.py
```

### Anthropicを使う場合

```bash
export ANTHROPIC_API_KEY="..."
export ANTHROPIC_MODEL="claude-sonnet-4-5"
python3 server.py
```

優先順位は次です。

1. Gemini
2. OpenAI
3. Anthropic
4. ヒューリスティック

## 4. よく使う環境変数

```bash
export APP_HOST="127.0.0.1"
export APP_PORT="8000"
export JGRANTS_BASE_URL="https://api.jgrants-portal.go.jp/exp"
export AUTO_REFRESH_ON_START="1"
export AUTO_REFRESH_MAX_AGE_HOURS="24"
export JGRANTS_REQUEST_TIMEOUT="20"
export JGRANTS_MAX_ITEMS="180"
```

高速モード関連です。

```bash
export FAST_MODE_DEFAULT="1"
export ENABLE_LLM_PROFILE_IN_FAST_MODE="0"
export ENABLE_LIVE_FETCH_IN_FAST_MODE="0"
export ENABLE_LLM_RERANK_IN_FAST_MODE="0"
```

初期検証では高速モードのままで問題ありません。起動時の定期更新で最新化し、通常検索はキャッシュを使うと表示が速くなります。検索時にライブ取得を行うと最新候補を拾いやすくなりますが、表示速度は落ちます。

## 5. 主な画面機能

### 研究開発向け検索（チャットUI）

チャット形式で1ステップずつ条件を選ぶと、公募を絞り込めます。

1. 研究フェーズ（アイデア / PoC / 試作 / 実証 / 事業化）
2. 技術分野（AI・バイオ・エネルギー・材料など）
3. 支援タイプ（試作を進めたい / スタートアップ向けを優先など）
4. 予算規模
5. 拠点地域
6. 補足（任意）

各ステップで選択肢から選ぶか、テキストで自由入力できます。選択肢に合わない場合は「スキップ」も可能です。最終ステップ後に自動で検索が実行されます。

対象ソース: Jグランツ / NEDO / JST / AMED

検索結果カードには「なぜおすすめ？」として、内部スコア理由をわかりやすい言葉で最大5件表示します。

### やさしく読む

検索結果カードの「やさしく読む」ボタンから、各公募の要点をカード形式で表示します。

- これは何？
- 何のためのお金？
- もらえる金額 / 応募締切 / 対象フェーズ（タグ表示）
- こんな会社に合いそう
- 合わないかもしれない会社
- 誰が応募できる？
- 何に使えるお金？
- 用意するもの
- まずやること
- 相談するならこの人
- 確認しておきたいこと
- 気をつけること

情報がない項目は非表示になります。全項目が不明の場合は「詳細は公式要領でご確認ください。」と表示されます。

### ウォッチリスト

ログインなしで、ブラウザの `localStorage` に気になる公募を保存します。

初期MVPでは、ユーザーが保存・比較・準備チェックまで進むかを見るため、ログイン機能は入れていません。

### 比較・準備チェック

ウォッチリストに保存した公募をまとめて比較し、応募準備の確認に使えます。

### 事業導線

検索ツールを収益化につなげるため、以下のCTAを入れています。

- 専門家に相談する
- 公募ウォッチ自動化パックについて相談する
- 専門家として掲載したい
- β版フィードバックを送る

## 6. API一覧

### 基本API

- `GET /api/health`
- `GET /api/meta`
- `GET /api/news`
- `GET /api/legal`
- `GET /api/grants?query=...&status=...&limit=100`
- `POST /api/refresh`
- `POST /api/recommend`

### 研究開発向け検索

- `GET /api/rd-meta`
- `POST /api/rd-search`

`POST /api/rd-search` の例です。

```json
{
  "rd_phase": "prototype",
  "tech_domain": "agri",
  "support_type": "development",
  "budget_range": "5m_30m",
  "region_text": "東京都",
  "free_text": "食品残渣を活用したバイオ素材の試作開発を進めたい",
  "sources": ["jgrants", "nedo", "jst", "amed"],
  "include_closed": false,
  "fast_mode": true
}
```

### 要約・比較・準備チェック

- `GET /api/grant-summary?id=...`
- `POST /api/compare`
- `POST /api/readiness-check`

`POST /api/compare` の例です。

```json
{
  "ids": ["grant_id_1", "grant_id_2"]
}
```

### リード取得API

- `POST /api/lead`
- `GET /api/leads?lead_type=...&limit=100`

`POST /api/lead` の例です。

```json
{
  "lead_type": "consultation",
  "name": "山田 太郎",
  "email": "taro@example.com",
  "company": "株式会社サンプル",
  "message": "NEDO公募について相談したいです",
  "grant_id": "grant_id_1",
  "grant_title": "公募タイトル",
  "source_page": "grant_detail"
}
```

`lead_type` は以下に対応します。

- `consultation`: 専門家相談
- `automation_pack`: 公募ウォッチ自動化パック相談
- `expert_listing`: 専門家掲載希望
- `feedback`: β版フィードバック

注意: `GET /api/leads` はβ版の簡易確認用です。公開運用する前に、管理者認証を追加してください。

## 7. データと保存先

SQLite DBはプロジェクト内に作成されます。

```text
grant_mvp/grants.db
```

主な保存内容です。

- `grants`: 公募情報
- `sync_events`: Jグランツ同期イベント
- `leads`: 相談・掲載希望・フィードバックなどのリード

ウォッチリストはDBではなく、ブラウザの `localStorage` に保存しています。

## 8. この版の割り切り

- 申請可否や採択可能性は断定しません
- 適合率は参考指標です
- 最終判断は必ず公式ページ・公募要領で確認してください
- PDF本文取得はページ構造やPDF形式に依存します
- 外部サイトのHTML構造変更により、NEDO / JST / AMEDの取得が失敗する可能性があります
- ログイン、決済、メール送信、管理者認証は未実装です
- ウォッチリストはブラウザ単位の保存です

## 9. よくあるエラー

### `ModuleNotFoundError` が出る

仮想環境を有効化し、依存関係を入れてください。

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### `Address already in use` が出る

8000番ポートがすでに使われています。別ポートで起動してください。

```bash
export APP_PORT="8001"
python3 server.py
```

### 検索結果が少ない / 外部取得されない

高速モードでは、検索時の外部取得を省略する設定があります。必要に応じて以下を設定してください。

```bash
export ENABLE_LIVE_FETCH_IN_FAST_MODE="1"
python3 server.py
```

### LLM要約が動かない

APIキーが設定されているか確認してください。

```bash
echo $GEMINI_API_KEY
```

未設定でも、ルールベースの要約・検索は動きます。

## 10. 次に実装するとよいもの

- 管理者認証付きのリード一覧画面
- メール通知
- 専門家掲載ページ
- 分野別LP: アグリテック、フードテック、バイオ、GX、素材など
- ウォッチ条件保存
- 締切通知
- 公募比較PDF / Markdown出力
- 公開運用前の利用規約・プライバシーポリシー

## 11. 注意書き

本サービスは研究開発資金探索を支援するβ版です。申請可否、採択、制度適合を保証するものではありません。必ず公式情報を確認し、必要に応じて専門家へ相談してください。

## Gemini要約キャッシュ

`/api/grant-summary?id=...` は、詳細ページ/PDF本文をもとに Gemini で応募判断用JSONを生成します。
生成結果は SQLite の `grant_summaries` テーブルに保存され、同じ公募本文から再度要約する場合は Gemini を再実行せずキャッシュを返します。

保存される主な項目:

- overview
- purpose
- target_companies
- suitable_for
- not_suitable_for
- rd_phase
- fields
- budget
- deadline
- eligible_expenses
- required_documents
- preparation_tasks
- cautions
- expert_type_needed
- first_questions_to_ask

Gemini APIキーが未設定、または要約に失敗した場合は、既存のルールベース要約にフォールバックします。

```bash
export GEMINI_API_KEY="..."
export GEMINI_MODEL="gemini-2.5-flash"
```
