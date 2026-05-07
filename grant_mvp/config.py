from __future__ import annotations

import logging
import os
from pathlib import Path

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("grant_refactor")

from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("GRANT_MVP_DB_PATH", str(BASE_DIR / "grants.db"))).resolve()
STATIC_DIR = BASE_DIR / "static"
HOST = os.getenv("APP_HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", os.getenv("APP_PORT", "8000")))
JGRANTS_BASE_URL = os.getenv("JGRANTS_BASE_URL", "https://api.jgrants-portal.go.jp/exp").rstrip("/")
AUTO_REFRESH_ON_START = os.getenv("AUTO_REFRESH_ON_START", "1") == "1"
JGRANTS_REQUEST_TIMEOUT = max(5, int(os.getenv("JGRANTS_REQUEST_TIMEOUT", "20")))
JGRANTS_MAX_ITEMS = max(20, int(os.getenv("JGRANTS_MAX_ITEMS", "180")))
DISCOVERY_KEYWORDS = [
    "補助金", "助成金", "研究開発", "スタートアップ", "創業", "展示会", "販路開拓",
    "海外展開", "DX", "設備投資", "福岡", "北海道", "大学発"
]

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/models")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/responses")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages")

MIN_LIVE_KEYWORD_LEN = 2

FAST_MODE_DEFAULT = os.getenv("FAST_MODE_DEFAULT", "1") == "1"
ENABLE_LLM_PROFILE_IN_FAST_MODE = os.getenv("ENABLE_LLM_PROFILE_IN_FAST_MODE", "0") == "1"
ENABLE_LIVE_FETCH_IN_FAST_MODE = os.getenv("ENABLE_LIVE_FETCH_IN_FAST_MODE", "0") == "1"
ENABLE_LLM_RERANK_IN_FAST_MODE = os.getenv("ENABLE_LLM_RERANK_IN_FAST_MODE", "0") == "1"
NATIONAL_TERMS = ["全国", "日本全国", "国内全域"]
REGION_ALIASES = {
    "北海道": ["北海道"],
    "青森県": ["青森", "青森県"],
    "岩手県": ["岩手", "岩手県"],
    "宮城県": ["宮城", "宮城県", "仙台"],
    "秋田県": ["秋田", "秋田県"],
    "山形県": ["山形", "山形県"],
    "福島県": ["福島", "福島県"],
    "茨城県": ["茨城", "茨城県"],
    "栃木県": ["栃木", "栃木県"],
    "群馬県": ["群馬", "群馬県"],
    "埼玉県": ["埼玉", "埼玉県"],
    "千葉県": ["千葉", "千葉県"],
    "東京都": ["東京", "東京都"],
    "神奈川県": ["神奈川", "神奈川県", "横浜"],
    "新潟県": ["新潟", "新潟県"],
    "富山県": ["富山", "富山県"],
    "石川県": ["石川", "石川県", "金沢"],
    "福井県": ["福井", "福井県"],
    "山梨県": ["山梨", "山梨県"],
    "長野県": ["長野", "長野県"],
    "岐阜県": ["岐阜", "岐阜県"],
    "静岡県": ["静岡", "静岡県"],
    "愛知県": ["愛知", "愛知県", "名古屋"],
    "三重県": ["三重", "三重県"],
    "滋賀県": ["滋賀", "滋賀県"],
    "京都府": ["京都", "京都府"],
    "大阪府": ["大阪", "大阪府"],
    "兵庫県": ["兵庫", "兵庫県", "神戸"],
    "奈良県": ["奈良", "奈良県"],
    "和歌山県": ["和歌山", "和歌山県"],
    "鳥取県": ["鳥取", "鳥取県"],
    "島根県": ["島根", "島根県"],
    "岡山県": ["岡山", "岡山県"],
    "広島県": ["広島", "広島県"],
    "山口県": ["山口", "山口県"],
    "徳島県": ["徳島", "徳島県"],
    "香川県": ["香川", "香川県"],
    "愛媛県": ["愛媛", "愛媛県"],
    "高知県": ["高知", "高知県"],
    "福岡県": ["福岡", "福岡県"],
    "佐賀県": ["佐賀", "佐賀県"],
    "長崎県": ["長崎", "長崎県"],
    "熊本県": ["熊本", "熊本県"],
    "大分県": ["大分", "大分県"],
    "宮崎県": ["宮崎", "宮崎県"],
    "鹿児島県": ["鹿児島", "鹿児島県"],
    "沖縄県": ["沖縄", "沖縄県"],
}

INTENT_KEYWORDS = {
    "research": ["研究", "研究開発", "実証", "poc", "poC", "試作", "プロトタイプ", "ラボ"],
    "equipment": ["設備", "設備投資", "装置", "機械", "導入"],
    "marketing": ["販路", "販路開拓", "営業", "広告", "pr", "ブランディング", "マーケ"],
    "exhibition": ["展示会", "見本市", "出展"],
    "overseas_inspection": ["海外視察", "視察", "渡航", "市場調査", "現地調査"],
    "overseas_expansion": ["海外展開", "輸出", "越境", "海外営業"],
    "it": ["it", "dx", "システム", "ソフトウェア", "saas"],
    "sustainability": ["脱炭素", "省エネ", "カーボン", "循環", "再資源化"],
    "ip": ["知財", "知的財産", "特許", "商標", "意匠", "出願", "弁理士", "pct", "PCT", "外国出願", "先行技術調査"],
}
EXPENSE_KEYWORDS = {
    "travel": ["旅費", "渡航", "交通費", "宿泊"],
    "exhibition": ["展示会", "見本市", "出展", "小間", "ブース"],
    "marketing": ["広告", "pr", "広報", "販促", "マーケ"],
    "sales": ["販路", "営業", "商談", "市場調査"],
    "rd": ["研究", "試作", "実証", "開発"],
    "equipment": ["設備", "装置", "機械", "導入"],
    "ip": ["知財", "知的財産", "特許", "商標", "意匠", "出願", "弁理士", "pct", "PCT", "外国出願", "先行技術調査"],
}
SECTOR_KEYWORDS = {
    "space": ["宇宙", "衛星", "ロケット", "space"],
    "healthcare": ["ヘルスケア", "医療", "創薬", "バイオ"],
    "agri": ["農業", "アグリ", "畜産", "食品"],
    "energy": ["エネルギー", "蓄電", "再エネ"],
    "nuclear": ["原子力"],
    "deeptech": ["ディープテック", "先端技術", "先端", "高度技術"],
    "fintech": ["フィンテック", "金融サービス", "金融分野", "金融事業者", "金融機関"],
}
MEDIA_TERMS = ["コンテンツ", "アニメ", "ゲーム", "実写", "音楽", "映画", "映像", "IP新規創出", "著作権"]
IP_CONTENT_TERMS = ["新規IP", "コンテンツ", "アニメ", "ゲーム", "実写", "音楽", "映画", "映像"]
SMALL_RD_TERMS = ["小さな研究開発", "小規模研究開発", "試作", "PoC", "実証", "プロトタイプ"]
SMALL_COMPANY_TERMS = ["小規模", "中小企業", "創業", "スタートアップ", "ベンチャー"]
LARGE_PROJECT_TERMS = ["コンソーシアム", "大規模", "複数機関", "国家プロジェクト", "大型" ]
STARTUP_TERMS = ["スタートアップ", "創業", "ベンチャー", "シード", "アーリー"]
UNIVERSITY_TERMS = ["大学発", "産学", "共同研究", "研究機関", "大学" ]
STOPWORDS = {"です", "ます", "したい", "費用", "予算", "以上", "社員", "本社", "会社", "法人", "使える", "補助金", "助成金", "ありますか"}

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "company_phases": {"type": "array", "items": {"type": "string"}},
        "intents": {"type": "array", "items": {"type": "string"}},
        "background_intents": {"type": "array", "items": {"type": "string"}},
        "negative_intents": {"type": "array", "items": {"type": "string"}},
        "expense_types": {"type": "array", "items": {"type": "string"}},
        "region": {"type": ["string", "null"]},
        "employee_count": {"type": ["integer", "null"]},
        "entity_type": {"type": ["string", "null"]},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "sectors": {"type": "array", "items": {"type": "string"}},
        "budget_min": {"type": ["integer", "null"]},
        "is_startup": {"type": "boolean"},
        "university_origin": {"type": "boolean"},
        "rationale": {"type": "string"}
    },
    "required": ["company_phases", "intents", "background_intents", "negative_intents", "expense_types", "region", "employee_count", "entity_type", "keywords", "sectors", "budget_min", "is_startup", "university_origin", "rationale"],
    "additionalProperties": False,
}

GRANTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS grants (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    institution_name TEXT,
    system_name TEXT,
    subsidy_catch_phrase TEXT,
    detail TEXT,
    use_purpose TEXT,
    industry TEXT,
    target_area_search TEXT,
    target_area_detail TEXT,
    target_number_of_employees TEXT,
    subsidy_rate TEXT,
    subsidy_max_limit INTEGER,
    granttype TEXT,
    acceptance_start_datetime TEXT,
    acceptance_end_datetime TEXT,
    project_end_deadline TEXT,
    request_reception_presence TEXT,
    is_enable_multiple_request INTEGER,
    front_subsidy_detail_page_url TEXT,
    status TEXT,
    raw_json TEXT,
    content_hash TEXT,
    source TEXT,
    created_at TEXT,
    updated_at TEXT,
    last_synced_at TEXT
)
"""

LOGGER = logging.getLogger("grant_mvp")
if not LOGGER.handlers:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

LEGAL_DISCLAIMER = {
    "service_type": "information_and_preparation_support",
    "summary": "このサービスは補助金の情報整理と準備支援を行うもので、申請可否や採択を保証しません。最終確認は必ず公式要領や専門家で行ってください。",
    "no_guarantee": [
        "申請可否の断定はしません",
        "採択可能性を保証しません",
        "代理作成・代理提出は行いません",
    ],
}

SYNC_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grant_id TEXT,
    event_type TEXT,
    summary TEXT,
    payload TEXT,
    created_at TEXT
)
"""


GRANT_SUMMARIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS grant_summaries (
    grant_id TEXT PRIMARY KEY,
    summary_json TEXT NOT NULL,
    source_text_hash TEXT,
    model TEXT,
    created_at TEXT,
    updated_at TEXT
)
"""


LEADS_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_type TEXT NOT NULL,
    name TEXT,
    company TEXT,
    email TEXT NOT NULL,
    phone TEXT,
    role TEXT,
    message TEXT,
    grant_id TEXT,
    grant_title TEXT,
    source_page TEXT,
    status TEXT DEFAULT 'new',
    payload TEXT,
    created_at TEXT
)
"""


CONTRAST_MARKERS = ["ですが", "だが", "けれど", "けど", "ものの", "ただし", "一方で", "一方、", "ただ", "しかし"]
