from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

from .config import (
    logger as LOGGER,
    ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL, EXPENSE_KEYWORDS, GEMINI_API_KEY,
    GEMINI_BASE_URL, GEMINI_MODEL, INTENT_KEYWORDS, IP_CONTENT_TERMS, LARGE_PROJECT_TERMS,
    LEGAL_DISCLAIMER, MEDIA_TERMS, MIN_LIVE_KEYWORD_LEN, NATIONAL_TERMS, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL,
    SECTOR_KEYWORDS, SMALL_COMPANY_TERMS, STARTUP_TERMS, STOPWORDS, UNIVERSITY_TERMS,
    FAST_MODE_DEFAULT, ENABLE_LIVE_FETCH_IN_FAST_MODE, ENABLE_LLM_PROFILE_IN_FAST_MODE, ENABLE_LLM_RERANK_IN_FAST_MODE
)
from .models import ParsedProfile
from .profile_parser import parse_profile, _extract_openai_text
from .repository import db, upsert_grants
from .utils import contains_any, strip_html, unique
from .jgrants import JGrantsClient, ensure_live_cache_for_query

def build_searchable_text(item: Dict[str, Any]) -> str:
    parts = [
        item.get("title") or "", item.get("detail") or "", item.get("use_purpose") or "", item.get("industry") or "",
        item.get("target_area_search") or "", item.get("target_area_detail") or "", item.get("granttype") or "",
        item.get("system_name") or "", item.get("subsidy_catch_phrase") or "", item.get("target_number_of_employees") or "",
    ]
    return strip_html(" ".join(str(p) for p in parts)).lower()


def present_labels(searchable: str, mapping: Dict[str, List[str]]) -> List[str]:
    hits = []
    for label, terms in mapping.items():
        if contains_any(searchable, terms):
            hits.append(label)
    return unique(hits)


def parse_subsidy_rate_fraction(rate_text: Optional[str]) -> Optional[float]:
    if not rate_text:
        return None
    text = str(rate_text)
    frac = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if frac:
        num = int(frac.group(1)); den = int(frac.group(2))
        return num / den if den else None
    pct = re.search(r"(\d+)\s*%", text)
    if pct:
        return int(pct.group(1)) / 100.0
    return None


def employee_count_matches(target_text: str, employee_count: Optional[int]) -> bool:
    if employee_count is None or not target_text:
        return True
    text = strip_html(target_text)
    if "制約なし" in text or "問わない" in text:
        return True
    nums = [int(x) for x in re.findall(r"\d+", text)]
    return employee_count <= max(nums) if nums else True


def region_match(item: Dict[str, Any], region: Optional[str]) -> Tuple[bool, str]:
    if not region:
        return True, "地域指定なし"
    area = f"{item.get('target_area_search') or ''} {item.get('target_area_detail') or ''}"
    if any(term in area for term in NATIONAL_TERMS):
        return True, "全国対象"
    if region in area:
        return True, f"{region} 対象"
    return False, f"{region} と地域不一致"


def expense_labels(item: Dict[str, Any], searchable: str) -> List[str]:
    labels: List[str] = []
    for label, terms in EXPENSE_KEYWORDS.items():
        if contains_any(searchable, terms):
            labels.append(label)
    for intent in present_labels(searchable, INTENT_KEYWORDS):
        if intent == "marketing":
            labels.extend(["marketing", "sales"])
        elif intent == "exhibition":
            labels.append("exhibition")
        elif intent == "overseas_inspection":
            labels.append("travel")
        elif intent == "research":
            labels.append("rd")
        elif intent == "equipment":
            labels.append("equipment")
        elif intent == "ip":
            labels.append("ip")
    return unique(labels)


def classify_budget_scale(max_limit: Optional[int]) -> Tuple[str, str]:
    if not max_limit:
        return "unknown", "不明"
    if max_limit < 5_000_000:
        return "small", "小型"
    if max_limit < 30_000_000:
        return "medium", "中型"
    if max_limit < 100_000_000:
        return "large", "大型"
    return "xlarge", "超大型"


def estimate_project_total(max_limit: Optional[int], subsidy_rate: Optional[str]) -> Optional[int]:
    frac = parse_subsidy_rate_fraction(subsidy_rate)
    if max_limit and frac and frac > 0:
        return int(max_limit / frac)
    return None


def safe_public_url(url: Optional[str]) -> Optional[str]:
    if not url or not isinstance(url, str):
        return None
    if not re.match(r"^https?://", url):
        return None
    return url


def prepare_item(item: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(item)
    item["detail_plain"] = strip_html(item.get("detail") or item.get("subsidy_catch_phrase") or "")
    item["safe_public_url"] = safe_public_url(item.get("front_subsidy_detail_page_url"))
    scale_key, scale_label = classify_budget_scale(item.get("subsidy_max_limit"))
    item["budget_scale_key"] = scale_key
    item["budget_scale_label"] = scale_label
    item["estimated_project_budget"] = estimate_project_total(item.get("subsidy_max_limit"), item.get("subsidy_rate"))
    return item


def component(name: str, score: int, reason: Optional[str] = None, caution: Optional[str] = None) -> Dict[str, Any]:
    return {"name": name, "score": max(0, min(100, int(score))), "reason": reason, "caution": caution}


def fit_label(percent: int) -> str:
    if percent >= 85:
        return "高"
    if percent >= 65:
        return "中"
    if percent >= 45:
        return "要確認"
    return "低"


def explain_match_label(percent: int) -> str:
    if percent >= 85:
        return "かなり近い候補"
    if percent >= 65:
        return "比較的近い候補"
    if percent >= 45:
        return "要件確認が必要な候補"
    return "一致度が低い候補"


def make_public_item(item: Dict[str, Any]) -> Dict[str, Any]:
    public_item = dict(item)
    score = int(public_item.get("fit_percent", 0))
    public_item["match_score"] = score
    public_item["match_level"] = public_item.get("fit_label") or fit_label(score)
    public_item["match_summary"] = explain_match_label(score)
    public_item["review_required"] = bool(public_item.get("is_low_confidence", False) or public_item["match_level"] == "要確認")
    public_item["legal_notice"] = "参考一致度です。申請可否や採択を保証しません。"
    return public_item


def build_recommendation_response(user_text: str, include_closed: bool = False, fast_mode: Optional[bool] = None) -> Dict[str, Any]:
    if fast_mode is None:
        fast_mode = FAST_MODE_DEFAULT

    if fast_mode and not ENABLE_LLM_PROFILE_IN_FAST_MODE:
        from .profile_parser import parse_profile_heuristic, postprocess_profile_from_text
        profile = postprocess_profile_from_text(parse_profile_heuristic(user_text), user_text)
        engine = "heuristic"
        diagnostics = [{"provider": "system", "severity": "info", "message": "高速モードのため入力解析はルールベースで実行しました"}]
    else:
        profile, engine, diagnostics = parse_profile(user_text)

    if fast_mode and not ENABLE_LIVE_FETCH_IN_FAST_MODE:
        live_fetch = {"skipped": True, "reason": "高速モードでは検索時の外部データ取得を行いません"}
    else:
        live_fetch = ensure_live_cache_for_query(user_text, profile)

    items = rank_grants(profile, user_text, include_closed=include_closed)

    if fast_mode and not ENABLE_LLM_RERANK_IN_FAST_MODE:
        diagnostics.append({"provider": "system", "severity": "info", "message": "高速モードのためLLM再ランキングを省略しました"})
        rerank_diagnostics = []
    else:
        items, rerank_diagnostics = llm_rerank(profile, items, engine)
    diagnostics.extend(rerank_diagnostics)

    public_items = [make_public_item(item) for item in items]
    return {
        "profile": asdict(profile),
        "engine": engine,
        "fast_mode": fast_mode,
        "llm_debug": {
            "used_llm": engine != "heuristic" and not (fast_mode and not ENABLE_LLM_PROFILE_IN_FAST_MODE),
            "provider": engine if engine != "heuristic" else None,
            "diagnostics": diagnostics,
        },
        "items": public_items,
        "live_fetch": live_fetch,
        "disclaimer": LEGAL_DISCLAIMER,
    }


def extract_live_keywords(profile: ParsedProfile, user_text: str) -> List[str]:
    tokens: List[str] = []
    if profile.region:
        tokens.append(profile.region)
    if profile.company_phases:
        phase_map = {"seed": ["創業", "スタートアップ"], "early": ["実証", "試作"], "growth": ["量産", "拡販"], "idea": ["構想"]}
        for phase in profile.company_phases:
            tokens.extend(phase_map.get(phase, []))
    for intent in profile.intents:
        tokens.extend(INTENT_KEYWORDS.get(intent, []))
    for expense in profile.expense_types:
        tokens.extend(EXPENSE_KEYWORDS.get(expense, []))
    for sector in profile.sectors:
        tokens.extend(SECTOR_KEYWORDS.get(sector, []))
    tokens.extend(profile.keywords)
    tokens.extend(re.findall(r"[一-龥ぁ-んァ-ヴA-Za-z0-9\-]{2,}", user_text))
    return unique([t for t in tokens if len(t) >= MIN_LIVE_KEYWORD_LEN and t not in STOPWORDS])[:12]


def sync_keywords_to_cache(keywords: List[str], source: str, *, max_items_per_keyword: int = 30) -> Dict[str, Any]:
    chosen = [k for k in unique(keywords) if len(k) >= MIN_LIVE_KEYWORD_LEN][:12]
    if not chosen:
        return {"inserted": 0, "updated": 0, "total_processed": 0, "source": source, "keywords": [], "warnings": []}
    client = JGrantsClient()
    warnings: List[str] = []
    all_rows: List[Dict[str, Any]] = []
    for keyword in chosen:
        try:
            all_rows.extend(client.search_subsidies(keyword, max_items=max_items_per_keyword, acceptance=1))
        except Exception as exc:
            warnings.append(f"{keyword}: {exc}")
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in all_rows:
        row_id = str(row.get("id") or "")
        if row_id and row_id not in seen:
            seen.add(row_id)
            deduped.append(row)
    result = upsert_grants(deduped, source) if deduped else {"inserted": 0, "updated": 0, "total_processed": 0}
    result.update({"source": source, "keywords": chosen, "warnings": warnings})
    return result


def evaluate_region(profile: ParsedProfile, item: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    ok, msg = region_match(item, profile.region)
    if not profile.region:
        return component("地域", 60, "地域指定なし"), True
    if ok:
        return component("地域", 100, msg), True
    return component("地域", 0, caution=msg), False


def evaluate_budget(profile: ParsedProfile, item: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    max_limit = item.get("subsidy_max_limit")
    if not profile.budget_min:
        return component("予算", 60, "予算下限指定なし"), True
    if max_limit is not None and max_limit < profile.budget_min:
        return component("予算", 0, caution="補助上限が希望予算を下回る"), False
    if max_limit is None:
        return component("予算", 45, caution="補助上限が不明"), True
    return component("予算", 100, f"補助上限 {max_limit:,}円"), True


def evaluate_size(profile: ParsedProfile, item: Dict[str, Any], searchable: str) -> Tuple[Dict[str, Any], bool]:
    if profile.employee_count is None:
        return component("規模", 60, "従業員数指定なし"), True
    target = item.get("target_number_of_employees") or ""
    if target and not employee_count_matches(target, profile.employee_count):
        return component("規模", 0, caution="従業員規模の条件に合わない可能性"), False
    score = 75
    reason = "規模条件に大きな矛盾はない"
    if profile.employee_count <= 5 and contains_any(searchable, SMALL_COMPANY_TERMS):
        score = 95
        reason = "小規模企業向けの制度"
    elif profile.employee_count <= 5 and contains_any(searchable, LARGE_PROJECT_TERMS):
        score = 30
        reason = "応募は可能でも小規模体制には重い可能性"
    return component("規模", score, reason=reason), True


def evaluate_intent(profile: ParsedProfile, searchable: str) -> Dict[str, Any]:
    if not profile.intents and not profile.expense_types:
        return component("用途", 58, "用途指定なし")

    grant_expenses = set(expense_labels({}, searchable))
    requested = unique(profile.intents)
    if not requested and profile.expense_types:
        reverse_map = {"rd": "research", "equipment": "equipment", "ip": "ip", "sales": "marketing", "marketing": "marketing", "exhibition": "exhibition", "travel": "overseas_inspection"}
        requested = unique([reverse_map[e] for e in profile.expense_types if e in reverse_map])

    scores: List[int] = []
    reasons: List[str] = []
    cautions: List[str] = []

    for intent in requested:
        score = 20
        if intent == "marketing":
            if any(x in grant_expenses for x in ["marketing", "sales", "exhibition"]):
                score = 96; reasons.append("販路開拓用途に合う")
            elif contains_any(searchable, ["販路", "商談", "営業", "プロモーション"]):
                score = 78; reasons.append("販路開拓寄り")
            else:
                score = 12; cautions.append("販路開拓費の記載が薄い")
        elif intent == "exhibition":
            if "exhibition" in grant_expenses:
                score = 98; reasons.append("展示会費に合う")
            elif any(x in grant_expenses for x in ["marketing", "sales"]):
                score = 55; cautions.append("販路開拓系だが展示会費は要確認")
            else:
                score = 8; cautions.append("展示会費の記載が薄い")
        elif intent == "overseas_inspection":
            if "travel" in grant_expenses:
                score = 94; reasons.append("旅費・視察費に合う可能性")
            elif contains_any(searchable, ["海外", "輸出", "越境"]):
                score = 55; cautions.append("海外関連だが視察費は要確認")
            else:
                score = 10; cautions.append("視察・旅費の記載が薄い")
        elif intent == "research":
            if "rd" in grant_expenses:
                score = 95; reasons.append("研究開発用途に合う")
            elif "equipment" in grant_expenses:
                score = 55; cautions.append("設備寄りで研究開発費は要確認")
            else:
                score = 10; cautions.append("研究開発費の記載が薄い")
        elif intent == "equipment":
            if "equipment" in grant_expenses:
                score = 95; reasons.append("設備用途に合う")
            else:
                score = 15; cautions.append("設備費の記載が薄い")
        elif intent == "overseas_expansion":
            if any(x in grant_expenses for x in ["sales", "marketing", "travel", "exhibition"]):
                score = 88; reasons.append("海外展開系に近い")
            elif contains_any(searchable, ["海外", "輸出", "越境"]):
                score = 60; cautions.append("海外関連だが対象経費は要確認")
            else:
                score = 15; cautions.append("海外展開費の記載が薄い")
        elif intent == "ip":
            patent_like = contains_any(searchable, ["特許", "商標", "意匠", "弁理士", "外国出願", "先行技術調査"])
            content_ip = contains_any(searchable, IP_CONTENT_TERMS)
            if "ip" in grant_expenses and patent_like and not content_ip:
                score = 98; reasons.append("知的財産関連費に合う")
            elif "ip" in grant_expenses and content_ip and not patent_like:
                score = 12; cautions.append("コンテンツIP寄りで特許等の知財費とはズレる")
            else:
                score = 0; cautions.append("知財関連費の記載が薄い")
        scores.append(score)

    expense_overlap = grant_expenses & set(profile.expense_types)
    if expense_overlap:
        reasons.append(f"対象経費一致: {', '.join(sorted(expense_overlap))}")
    elif profile.expense_types:
        cautions.append("対象経費の一致が弱い")

    base = int(round(sum(scores) / max(1, len(scores)))) if scores else 20

    # 背景用途・除外用途はマイナス評価
    negative = set(profile.negative_intents or [])
    if "research" in negative and ("rd" in grant_expenses or contains_any(searchable, ["研究開発", "試作", "実証"])):
        base = min(base, 28)
        cautions.append("研究開発は背景説明であり、今回ほしい費用ではない")
    if "ip" in negative and ("ip" in grant_expenses or contains_any(searchable, IP_CONTENT_TERMS)):
        base = min(base, 20)
        cautions.append("知財・IPは今回の主用途ではない")

    if len(requested) >= 2 and min(scores) < 20:
        base = min(base, 35)
    if {"marketing", "exhibition"}.issubset(set(requested)) and not any(x in grant_expenses for x in ["marketing", "sales", "exhibition"]):
        base = min(base, 15)
        cautions.append("販路開拓・展示会向けの経費が見当たらない")
    if "ip" in requested and contains_any(searchable, IP_CONTENT_TERMS) and not contains_any(searchable, ["特許", "商標", "意匠", "弁理士", "外国出願", "先行技術調査"]):
        base = min(base, 12)
        cautions.append("コンテンツIPであり知財費支援とはズレる")

    return component("用途", base, reason=" / ".join(unique(reasons)) or None, caution=" / ".join(unique(cautions)) or None)


def evaluate_sector(profile: ParsedProfile, searchable: str) -> Dict[str, Any]:
    if not profile.sectors:
        return component("分野", 60, "分野指定なし")
    grant_sectors = set(present_labels(searchable, SECTOR_KEYWORDS))
    requested = set(profile.sectors)
    if grant_sectors & requested:
        return component("分野", 95, reason=f"分野一致: {', '.join(sorted(grant_sectors & requested))}")
    if "space" in requested and "nuclear" in grant_sectors:
        return component("分野", 0, caution="宇宙ではなく原子力向け")
    if "space" in requested and contains_any(searchable, MEDIA_TERMS):
        return component("分野", 0, caution="宇宙ではなくコンテンツ産業向け")
    if "space" in requested and "fintech" in grant_sectors:
        return component("分野", 0, caution="宇宙ではなくフィンテック向け")
    if grant_sectors and not (grant_sectors & requested):
        return component("分野", 10, caution=f"想定分野が異なる: {', '.join(sorted(grant_sectors))}")
    if contains_any(searchable, MEDIA_TERMS) and requested & {"space", "deeptech", "energy", "healthcare", "agri"}:
        return component("分野", 5, caution="コンテンツ産業向けで分野が遠い")
    if contains_any(searchable, ["先端技術", "研究開発", "スタートアップ"]):
        return component("分野", 68, reason="分野特化ではないが近い可能性")
    return component("分野", 35, caution="分野適合が薄い")


def evaluate_attributes(profile: ParsedProfile, searchable: str) -> Dict[str, Any]:
    score = 50
    reasons: List[str] = []
    cautions: List[str] = []
    if profile.is_startup:
        if contains_any(searchable, STARTUP_TERMS):
            score += 25; reasons.append("スタートアップ向け文脈あり")
        else:
            score -= 12; cautions.append("スタートアップ特化の記載が薄い")
    if profile.university_origin:
        if contains_any(searchable, UNIVERSITY_TERMS):
            score += 15; reasons.append("大学発・共同研究との相性あり")
        else:
            cautions.append("大学発向けの記載は薄い")
    return component("属性", max(0, min(100, score)), reason=" / ".join(unique(reasons)) or None, caution=" / ".join(unique(cautions)) or None)


def evaluate_status(item: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    status = item.get("status")
    if status == "open":
        return component("募集状況", 100, "現在募集中"), True
    if status == "upcoming":
        return component("募集状況", 70, "募集予定"), True
    if status == "closed":
        return component("募集状況", 0, caution="締切済み"), False
    return component("募集状況", 40, caution="募集状況は要確認"), True


def evaluate_keyword_fit(profile: ParsedProfile, searchable: str) -> Dict[str, Any]:
    hits = sum(1 for token in profile.keywords if token and token.lower() in searchable)
    score = min(100, 35 + hits * 10)
    return component("語句一致", score, reason=f"関連語ヒット {hits}件")


def compute_fit(profile: ParsedProfile, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    searchable = build_searchable_text(item)
    region_component, ok_region = evaluate_region(profile, item)
    if not ok_region:
        return None
    budget_component, ok_budget = evaluate_budget(profile, item)
    if not ok_budget:
        return None
    size_component, ok_size = evaluate_size(profile, item, searchable)
    if not ok_size:
        return None
    status_component, ok_status = evaluate_status(item)
    if not ok_status:
        return None

    intent_component = evaluate_intent(profile, searchable)
    sector_component = evaluate_sector(profile, searchable)
    attr_component = evaluate_attributes(profile, searchable)
    keyword_component = evaluate_keyword_fit(profile, searchable)

    if profile.intents and intent_component["score"] <= 20:
        return None
    if profile.sectors and sector_component["score"] == 0:
        return None
    if "ip" in profile.intents and intent_component["score"] < 40:
        return None

    components = [intent_component, region_component, size_component, attr_component, sector_component, budget_component, status_component, keyword_component]
    weights = {"用途": 0.35, "地域": 0.15, "規模": 0.08, "属性": 0.10, "分野": 0.17, "予算": 0.08, "募集状況": 0.04, "語句一致": 0.03}
    fit_percent = int(round(sum(c["score"] * weights[c["name"]] for c in components)))
    if intent_component["score"] < 40:
        fit_percent = min(fit_percent, 42)
    if sector_component["score"] < 25:
        fit_percent = min(fit_percent, 38)
    if intent_component["score"] < 40 and sector_component["score"] < 30:
        fit_percent -= 18
    if profile.employee_count is not None and profile.employee_count <= 5 and attr_component["score"] < 40:
        fit_percent -= 8
    fit_percent = max(0, min(100, fit_percent))

    reasons = unique([c.get("reason") for c in components if c.get("reason")])[:6]
    cautions = unique([c.get("caution") for c in components if c.get("caution")])[:5]
    item = prepare_item(item)
    item.update({
        "fit_percent": fit_percent,
        "fit_label": fit_label(fit_percent),
        "fit_breakdown": components,
        "match_reasons": reasons,
        "match_cautions": cautions,
        "is_low_confidence": fit_percent < 45,
    })
    return item


def llm_rerank(profile: ParsedProfile, items: List[Dict[str, Any]], provider: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    diagnostics: List[Dict[str, str]] = []
    if provider == "heuristic" or not items:
        return items, diagnostics
    short_items = []
    for item in items[:8]:
        short_items.append({
            "id": item["id"],
            "title": item["title"],
            "detail": item.get("detail_plain", "")[:400],
            "region": item.get("target_area_search"),
            "employees": item.get("target_number_of_employees"),
            "subsidy_max_limit": item.get("subsidy_max_limit"),
            "subsidy_rate": item.get("subsidy_rate"),
            "current_fit_percent": item.get("fit_percent"),
        })
    prompt = "候補をユーザー条件への適合度順に並べ替えてください。ユーザーの背景説明と今回本当に欲しい用途を区別してください。negative_intents に入っている用途しか合わない制度は大きく下げてください。地域不一致、用途ずれ、予算不足は厳しく見てください。JSONで items:[{id,fit_percent,reason,caution}] を返してください。"
    payload_text = json.dumps({"profile": asdict(profile), "items": short_items}, ensure_ascii=False)
    data = None
    try:
        if provider == "gemini" and GEMINI_API_KEY:
            body = {
                "contents": [{"parts": [{"text": prompt + "\n" + payload_text}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": {
                        "type": "object",
                        "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "fit_percent": {"type": "integer"}, "reason": {"type": ["string", "null"]}, "caution": {"type": ["string", "null"]}}, "required": ["id", "fit_percent", "reason", "caution"], "additionalProperties": False}}},
                        "required": ["items"],
                        "additionalProperties": False,
                    },
                },
            }
            url = f"{GEMINI_BASE_URL}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
            req = Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=45) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            text = "\n".join(part.get("text", "") for part in (((out.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []) if isinstance(part, dict)).strip()
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
            data = json.loads(text)
        elif provider == "openai" and OPENAI_API_KEY:
            body = {"model": OPENAI_MODEL, "input": [{"role": "system", "content": prompt}, {"role": "user", "content": payload_text}], "text": {"format": {"type": "json_object"}}}
            req = Request(OPENAI_BASE_URL, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}, method="POST")
            with urlopen(req, timeout=45) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            data = json.loads(_extract_openai_text(out))
        elif provider == "anthropic" and ANTHROPIC_API_KEY:
            body = {"model": ANTHROPIC_MODEL, "max_tokens": 800, "messages": [{"role": "user", "content": prompt + "\n" + payload_text}]}
            req = Request(ANTHROPIC_BASE_URL, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"}, method="POST")
            with urlopen(req, timeout=45) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            text = "\n".join(block.get("text", "") for block in out.get("content", []) if block.get("type") == "text").strip()
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
            data = json.loads(text)
    except Exception as exc:
        LOGGER.warning("LLM rerank failed via %s: %s", provider, exc)
        diagnostics.append({"provider": provider, "stage": "rerank", "message": str(exc)[:300]})
        return items, diagnostics
    reranked = {entry.get("id"): entry for entry in (data or {}).get("items", []) if entry.get("id")}
    out_items: List[Dict[str, Any]] = []
    for item in items:
        override = reranked.get(item["id"])
        if override:
            item = dict(item)
            if isinstance(override.get("fit_percent"), int):
                item["fit_percent"] = max(0, min(100, override["fit_percent"]))
                item["fit_label"] = fit_label(item["fit_percent"])
            if override.get("reason"):
                item["match_reasons"] = unique([override["reason"], *item.get("match_reasons", [])])
            if override.get("caution"):
                item["match_cautions"] = unique([override["caution"], *item.get("match_cautions", [])])
        out_items.append(item)
    out_items.sort(key=lambda x: (x.get("fit_percent", 0), x.get("subsidy_max_limit") or 0), reverse=True)
    return out_items, diagnostics


def rank_grants(profile: ParsedProfile, query: str, *, include_closed: bool = False) -> List[Dict[str, Any]]:
    conn = db()
    rows = conn.execute("SELECT * FROM grants WHERE source LIKE 'jgrants%' ORDER BY status != 'open', subsidy_max_limit DESC, updated_at DESC").fetchall()
    conn.close()
    ranked: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if not include_closed and item.get("status") == "closed":
            continue
        scored = compute_fit(profile, item)
        if scored is None:
            continue
        if scored["fit_percent"] >= 25:
            ranked.append(scored)
    ranked.sort(key=lambda x: (x.get("fit_percent", 0), x.get("status") == "open", x.get("subsidy_max_limit") or 0), reverse=True)
    return ranked[:10]


