from __future__ import annotations

from typing import Dict, List, Optional
import re

from .config import LEGAL_DISCLAIMER, GEMINI_MODEL, logger
from .repository import get_grant_by_id, get_grants_by_ids, prepare_item, get_grant_summary_cache, upsert_grant_summary_cache
from .utils import strip_html, unique
from .detail_fetch import fetch_detail_bundle, merged_source_text, extract_budget_text, extract_deadline_text, extract_field_text
from .gemini_summary import summarize_grant_with_gemini
from hashlib import sha256

FUNDING_ALLOW_TERMS = [
    "補助金", "助成金", "委託", "委託費", "研究費", "支援", "公募", "募集", "提案募集",
    "SBIR", "事業化", "実証", "PoC", "概念実証", "スタートアップ", "基金", "開発費",
]

FUNDING_STRONG_ALLOW_TERMS = [
    "補助", "助成", "委託", "研究開発", "提案", "事業費", "実証", "PoC", "概念実証",
    "A-STEP", "SBIR", "D-Global", "START", "大学発新産業創出基金",
]

FUNDING_DENY_TERMS = [
    "データベース", "センター", "利用申請", "利用募集", "施設利用", "共用施設", "設備利用",
    "研究員募集", "採用", "公募説明会", "説明会", "イベント", "シンポジウム", "セミナー",
    "ワークショップ", "コンテスト", "表彰", "お知らせ", "ニュース", "データ公開", "登録受付",
    "NBDC", "バイオサイエンスデータベースセンター",
]

FUNDING_DENY_URL_TERMS = [
    "/event/", "/sympo/", "/seminar/", "/news/", "/press/",
]


def is_funding_support_candidate(title: str, detail: str = "", href: Optional[str] = None) -> bool:
    hay = f"{title} {detail}".lower()
    if any(term.lower() in hay for term in FUNDING_DENY_TERMS):
        return False
    if href:
        low = href.lower()
        if any(term in low for term in FUNDING_DENY_URL_TERMS):
            return False
    strong = any(term.lower() in hay for term in FUNDING_STRONG_ALLOW_TERMS)
    allow = any(term.lower() in hay for term in FUNDING_ALLOW_TERMS)
    return strong or allow


def funding_type_label(title: str, detail: str = "") -> str:
    hay = f"{title} {detail}".lower()
    if "補助" in hay:
        return "補助金"
    if "助成" in hay:
        return "助成金"
    if "委託" in hay:
        return "委託"
    if "sbir" in hay:
        return "SBIR"
    if "基金" in hay:
        return "基金・支援"
    return "研究開発支援"


def _text_list(*values: str) -> List[str]:
    out: List[str] = []
    for v in values:
        text = strip_html(v or "")
        if text:
            out.append(text)
    return out


def _infer_documents(item: Dict) -> List[str]:
    docs = ["公募要領", "申請フォーム", "事業概要", "会社概要"]
    text = f"{item.get('title') or ''} {item.get('detail') or ''} {item.get('use_purpose') or ''}".lower()
    if any(k in text for k in ["見積", "設備", "導入"]):
        docs.append("見積書")
    if any(k in text for k in ["研究", "実証", "poc", "試作"]):
        docs.append("研究開発計画")
    return docs


def _infer_expenses(item: Dict) -> List[str]:
    text = f"{item.get('detail') or ''} {item.get('use_purpose') or ''} {item.get('title') or ''}".lower()
    mapping = [
        ("人件費", ["人件費", "研究員", "開発者"]),
        ("設備費", ["設備", "装置", "機器", "導入"]),
        ("委託費", ["委託", "外注"]),
        ("試作費", ["試作", "プロトタイプ", "poc"]),
        ("実証費", ["実証", "フィールド", "検証"]),
        ("知財費", ["特許", "知財", "商標"]),
    ]
    hits = [label for label, kws in mapping if any(k in text for k in kws)]
    return hits or ["要確認"]



def _summarize_text(text: str, limit: int = 110) -> str:
    plain = strip_html(text or '')
    plain = re.sub(r'\s+', ' ', plain).strip()
    if not plain:
        return '要確認'
    return plain[:limit] + ('…' if len(plain) > limit else '')


def _infer_field(item: Dict) -> str:
    text = f"{item.get('title') or ''} {item.get('detail') or ''} {item.get('industry') or ''}".lower()
    mapping = [
        ('AI・ソフトウェア', ['ai', '人工知能', 'ソフトウェア', 'データ']),
        ('バイオ・医療', ['バイオ', '医療', '創薬', 'ヘルスケア', '医療機器']),
        ('アグリ・フードテック', ['農業', 'アグリ', 'food', '食品', 'フード']),
        ('エネルギー・GX', ['エネルギー', 'gx', '脱炭素', '水素', '再エネ']),
        ('宇宙', ['宇宙', '衛星', 'ロケット']),
        ('材料・化学', ['材料', '素材', '化学']),
        ('ロボティクス・製造', ['ロボ', '製造', 'ものづくり']),
        ('半導体・電子', ['半導体', '電子']),
    ]
    for label, kws in mapping:
        if any(k in text for k in kws):
            return label
    return '要確認'


def _infer_purpose(item: Dict) -> str:
    text = f"{item.get('title') or ''} {item.get('detail') or ''} {item.get('use_purpose') or ''}".lower()
    if any(k in text for k in ['実証', 'poc', '概念実証', '社会実装']):
        return 'PoCや実証、社会実装前の検証を進めたい事業向けです'
    if any(k in text for k in ['試作', 'プロトタイプ', '開発']):
        return '試作や研究開発を前に進めたい事業向けです'
    if any(k in text for k in ['設備', '装置', '機器']):
        return '研究開発に必要な設備や装置導入を含む事業向けです'
    return '研究開発や事業化に向けた取り組みを支える制度です'


def _budget_label(item: Dict) -> str:
    rate = item.get('subsidy_rate') or '要確認'
    max_limit = item.get('subsidy_max_limit')
    amount = f"上限{int(max_limit):,}円" if max_limit else '上限要確認'
    return f"{amount} / 補助率{rate}" if rate != '要確認' else amount

def _sanitize_summary_value(value, fallback='要確認'):
    if isinstance(value, list):
        cleaned = []
        for v in value:
            sv = _sanitize_summary_value(v, '')
            if sv and sv != '要確認' and sv not in cleaned:
                cleaned.append(sv)
        return cleaned
    text = strip_html(str(value or ''))
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return fallback
    if '目次' in text or '..........' in text or '……' in text:
        return fallback
    if len(text) > 180:
        text = text[:180].rstrip() + '…'
    return text


def _looks_meaningful(value):
    if isinstance(value, list):
        return any(_looks_meaningful(v) for v in value)
    text = str(value or '').strip()
    if not text or text == '要確認':
        return False
    bad = ['目次', '........', '……', '第1章', '第2章', '1.1.1']
    return not any(b in text for b in bad)


def _gemini_extract_summary(item: Dict, bundle: Dict[str, object], combined_text: str) -> Optional[Dict[str, object]]:
    if not GEMINI_API_KEY:
        return None
    source_text = (combined_text or '')[:18000]
    if len(source_text) < 300:
        return None
    prompt = f"""あなたは日本の研究開発公募要領を読むアナリストです。以下の公募資料テキストを読み、一覧比較しやすい形で日本語JSONを返してください。
ルール:
- 目次、ページ番号、章見出しだけを返さない
- 分からない項目は "要確認" とする
- 原文にない断定をしない
- なるべく短く、実務で使える表現にする
- 予算は上限や補助率が分かれば含める
- 締切は日付が分かればそれを返す
返すキー:
purpose, target_conditions, field, budget, deadline, eligible_expenses, required_documents, cautions, application_steps, overview

制度名: {item.get('title') or ''}

資料テキスト:
{source_text}
"""
    schema = {
        "type": "object",
        "properties": {
            "purpose": {"type": "string"},
            "target_conditions": {"type": "array", "items": {"type": "string"}},
            "field": {"type": "string"},
            "budget": {"type": "string"},
            "deadline": {"type": "string"},
            "eligible_expenses": {"type": "array", "items": {"type": "string"}},
            "required_documents": {"type": "array", "items": {"type": "string"}},
            "cautions": {"type": "array", "items": {"type": "string"}},
            "application_steps": {"type": "array", "items": {"type": "string"}},
            "overview": {"type": "string"}
        },
        "required": ["purpose", "target_conditions", "field", "budget", "deadline", "eligible_expenses", "required_documents", "cautions", "application_steps", "overview"],
        "additionalProperties": False
    }
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }
    url = f"{GEMINI_BASE_URL}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    try:
        req = Request(url, data=json.dumps(body).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with urlopen(req, timeout=45) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        candidates = payload.get('candidates') or []
        parts = (((candidates[0] or {}).get('content') or {}).get('parts') or []) if candidates else []
        raw = '\n'.join(part.get('text', '') for part in parts if isinstance(part, dict)).strip()
        raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.MULTILINE).strip()
        data = json.loads(raw)
    except Exception as exc:
        logger.info('gemini grant summary extraction failed: %s', exc)
        return None
    cleaned = {
        'purpose': _sanitize_summary_value(data.get('purpose')),
        'target_conditions': _sanitize_summary_value(data.get('target_conditions', [])),
        'field': _sanitize_summary_value(data.get('field')),
        'budget': _sanitize_summary_value(data.get('budget')),
        'deadline': _sanitize_summary_value(data.get('deadline')),
        'eligible_expenses': _sanitize_summary_value(data.get('eligible_expenses', [])),
        'required_documents': _sanitize_summary_value(data.get('required_documents', [])),
        'cautions': _sanitize_summary_value(data.get('cautions', [])),
        'application_steps': _sanitize_summary_value(data.get('application_steps', [])),
        'overview': _sanitize_summary_value(data.get('overview')),
    }
    meaningful_count = sum(1 for k,v in cleaned.items() if _looks_meaningful(v))
    return cleaned if meaningful_count >= 4 else None


def build_grant_summary(grant_id: str) -> Dict:
    item = get_grant_by_id(grant_id)
    if not item:
        raise ValueError("指定した制度が見つかりません")
    item = prepare_item(item)
    official_url = item.get("safe_public_url") or item.get("front_subsidy_detail_page_url")
    bundle = fetch_detail_bundle(official_url or "")
    combined_text = merged_source_text(item, bundle)
    source_text_hash = sha256((combined_text or "").encode("utf-8")).hexdigest()

    cached = get_grant_summary_cache(str(item.get("id") or ""), source_text_hash)
    fixed_ai_summary = cached.get("summary") if cached else None
    summary_source = "cache" if fixed_ai_summary else "rule_based"

    if not fixed_ai_summary:
        fixed_ai_summary = summarize_grant_with_gemini(combined_text, item.get("title") or "")
        if fixed_ai_summary:
            upsert_grant_summary_cache(str(item.get("id") or ""), fixed_ai_summary, source_text_hash, GEMINI_MODEL)
            summary_source = "gemini"

    overview = _summarize_text(bundle.get("html_text") or bundle.get("pdf_text") or item.get("detail_plain") or item.get("subsidy_catch_phrase") or item.get("use_purpose") or "", 180)
    purpose_candidates = []
    for key in ["目的", "趣旨", "概要", "事業概要", "狙い", "支援"]:
        purpose_candidates.extend([x for x in re.split(r'[。\n]', combined_text) if key in x][:1])
    purpose = _summarize_text(' / '.join(purpose_candidates) or _infer_purpose(item), 150)

    target_sentences = []
    for key in ["対象", "応募資格", "対象者", "提案者", "応募できる", "応募対象"]:
        target_sentences.extend([x for x in re.split(r'[。\n]', combined_text) if key in x][:2])
    target_conditions = unique(_text_list(*(target_sentences[:3] + [item.get("target_number_of_employees"), item.get("target_area_search"), item.get("industry")]))) or ["要確認"]
    target_conditions = target_conditions[:4]

    expenses = _infer_expenses({**item, 'detail': combined_text, 'use_purpose': combined_text})
    document_candidates = _infer_documents({**item, 'detail': combined_text, 'use_purpose': combined_text})

    cautions = []
    if item.get("status") == "closed":
        cautions.append("締切済みです")
    if item.get("status") == "upcoming":
        cautions.append("募集開始日を確認してください")
    if not item.get("subsidy_rate"):
        cautions.append("補助率は公式要領で確認してください")
    if not bundle.get('pdf_text'):
        cautions.append("詳細は公式ページや公募要領で再確認してください")

    notes = list(bundle.get('notes') or [])
    if summary_source == "cache":
        notes.append("保存済みのGemini要約を表示しています")
    elif summary_source == "gemini":
        notes.append("Geminiで詳細ページ・PDF本文から応募判断用に整理しました")
    else:
        notes.append("Gemini要約は未使用です。ルールベースで整理しています")
    pdf_note = ' / '.join(unique(notes)) if notes else '掲載テキストをもとに整理しています。'

    def ai_value(key: str, fallback):
        if fixed_ai_summary and _looks_meaningful(fixed_ai_summary.get(key)):
            return fixed_ai_summary.get(key)
        return fallback

    summary = {
        "overview": ai_value('overview', overview),
        "purpose": ai_value('purpose', purpose),
        "target_conditions": ai_value('target_companies', target_conditions),
        "field": ', '.join(fixed_ai_summary.get('fields') or []) if fixed_ai_summary and _looks_meaningful(fixed_ai_summary.get('fields')) else extract_field_text(combined_text, _infer_field(item)),
        "budget": ai_value('budget', extract_budget_text(combined_text, item.get('subsidy_rate'), item.get('subsidy_max_limit'))),
        "deadline": ai_value('deadline', extract_deadline_text(combined_text, item.get("acceptance_end_datetime") or item.get("project_end_deadline"))),
        "eligible_expenses": ai_value('eligible_expenses', expenses),
        "ineligible_or_unclear": ["対象外経費や細かな条件は公式要領で確認が必要です"],
        "required_documents": ai_value('required_documents', document_candidates),
        "application_steps": ai_value('preparation_tasks', ["制度概要を確認", "公募要領と応募資格を確認", "必要書類をそろえる", "提出前に条件を再確認する"]),
        "cautions": ai_value('cautions', unique(cautions) or ["対象条件・締切・必要書類は公式要領で再確認してください"]),
        "common_misses": ["地域要件の見落とし", "締切日の取り違え", "必要書類の不足", "研究フェーズと制度のずれ"],
        "suitable_for": ai_value('suitable_for', ["要確認"]),
        "not_suitable_for": ai_value('not_suitable_for', ["要確認"]),
        "rd_phase": ai_value('rd_phase', "unknown"),
        "expert_type_needed": ai_value('expert_type_needed', ["要確認"]),
        "first_questions_to_ask": ai_value('first_questions_to_ask', ["公式要領で応募資格・対象経費・締切を確認してください"]),
        "gemini_summary": fixed_ai_summary,
        "summary_source": summary_source,
    }
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "official_url": official_url,
        "pdf_url": bundle.get('pdf_url'),
        "pdf_note": pdf_note,
        "source_text_hash": source_text_hash,
        "legal_notice": LEGAL_DISCLAIMER.get("summary") or "最終確認は公式要領で行ってください。",
        "summary": summary,
    }

def build_compare(ids: List[str]) -> Dict:
    items = [prepare_item(x) for x in get_grants_by_ids(ids)]
    columns = []
    for item in items:
        columns.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "subsidy_rate": item.get("subsidy_rate") or "要確認",
            "subsidy_max_limit": item.get("subsidy_max_limit") or 0,
            "target_conditions": " / ".join([x for x in [item.get("target_number_of_employees"), item.get("target_area_search"), item.get("industry")] if x]) or "要確認",
            "eligible_expenses": _infer_expenses(item),
            "difficulty": "中" if item.get("detail_plain") else "要確認",
            "deadline": item.get("acceptance_end_datetime") or item.get("project_end_deadline"),
            "best_for": item.get("use_purpose") or item.get("industry") or "要確認",
            "cautions": build_grant_summary(item.get("id"))["summary"]["cautions"],
        })
    return {
        "columns": columns,
        "legal_notice": LEGAL_DISCLAIMER.get("summary_note") or "比較は参考情報です。最終確認は公式要領で行ってください。",
    }


def build_readiness_check(ids: List[str]) -> Dict:
    items = [prepare_item(x) for x in get_grants_by_ids(ids)]
    if not items:
        return {"selected_titles": [], "checklist": [], "next_actions": [], "legal_notice": LEGAL_DISCLAIMER.get("summary_note")}
    selected_titles = [item.get("title") or "名称未設定" for item in items]
    needs_equipment = any("設備" in (item.get("detail_plain") or "") or "設備" in (item.get("title") or "") for item in items)
    checklist = [
        {"name": "GビズID", "status": "確認必要", "note": "申請方式によって必要です"},
        {"name": "決算書", "status": "確認必要", "note": "直近決算資料を準備してください"},
        {"name": "会社概要", "status": "確認必要", "note": "事業内容が分かる資料を準備してください"},
        {"name": "事業計画書", "status": "未準備", "note": "研究開発の目的・進め方・成果見込みを整理してください"},
        {"name": "社内承認", "status": "確認必要", "note": "申請前の意思決定フローを確認してください"},
    ]
    if needs_equipment:
        checklist.append({"name": "見積書", "status": "未準備", "note": "設備導入がある場合は見積書を用意してください"})
    next_actions = ["公募要領を確認", "必要書類を集める", "研究開発計画を1枚で整理する"]
    return {
        "selected_titles": selected_titles,
        "checklist": checklist,
        "next_actions": next_actions,
        "legal_notice": LEGAL_DISCLAIMER.get("summary_note") or "準備チェックは参考情報です。最終確認は公式要領で行ってください。",
    }
