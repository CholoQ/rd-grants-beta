from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

from .config import (
    logger as LOGGER,
    ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL, EXPENSE_KEYWORDS,
    GEMINI_API_KEY, GEMINI_BASE_URL, GEMINI_MODEL, INTENT_KEYWORDS, OPENAI_API_KEY,
    OPENAI_BASE_URL, OPENAI_MODEL, PROFILE_SCHEMA, SECTOR_KEYWORDS, STARTUP_TERMS, UNIVERSITY_TERMS, IP_CONTENT_TERMS, STOPWORDS
)
from .models import ParsedProfile
from .utils import (
    contains_any, infer_expenses_from_segment, infer_intents_from_segment, make_rationale,
    normalize_region, parse_budget_min, split_background_and_desired, unique
)

SECTOR_NEGATION_PATTERNS = {
    "medical": [
        r"医療(?:系|関連|dx|DX)?(?:は|を|も)?(?:除|外|いらない|不要|避け)",
        r"病院(?:向け|関連)?(?:は|を|も)?(?:除|外|いらない|不要|避け)",
        r"臨床(?:は|を|も)?(?:除|外|いらない|不要|避け)",
        r"(?:exclude|no|avoid)\s+(?:medical|hospital|clinical)",
    ],
    "drug_discovery": [
        r"創薬(?:は|を|も)?(?:除|外|いらない|不要|避け)",
        r"医薬(?:品)?(?:は|を|も)?(?:除|外|いらない|不要|避け)",
        r"(?:exclude|no|avoid)\s+(?:drug|pharma|drug discovery)",
    ],
}


def infer_negative_sectors_from_text(text: str) -> List[str]:
    lowered = text or ""
    hits: List[str] = []
    for sector, patterns in SECTOR_NEGATION_PATTERNS.items():
        if any(re.search(pattern, lowered, flags=re.I) for pattern in patterns):
            hits.append(sector)
    if "medical" in hits and contains_any(lowered, ["ヘルスケア", "healthcare", "腸内環境", "腸内細菌", "マイクロバイオーム", "microbiome", "未病", "予防"]):
        hits.append("drug_discovery")
    return unique(hits)


def parse_profile_heuristic(user_text: str) -> ParsedProfile:
    lower = user_text.lower()
    phases: List[str] = []
    if contains_any(lower, ["アイデア", "構想", "検証前"]):
        phases.append("idea")
    if contains_any(lower, ["シード", "創業", "立ち上げ", "設立直後"]):
        phases.append("seed")
    if contains_any(lower, ["アーリー", "poc", "実証", "試作", "プロトタイプ"]):
        phases.append("early")
    if contains_any(lower, ["グロース", "量産", "拡販", "スケール"]):
        phases.append("growth")

    background_text, desired_text, contrast_marker = split_background_and_desired(user_text)
    intents = infer_intents_from_segment(desired_text)
    expense_types = infer_expenses_from_segment(desired_text)
    background_intents = infer_intents_from_segment(background_text)
    negative_intents: List[str] = []

    # 明示的な対比がある場合は左側を背景として扱い、右側に別用途があれば左側用途を除外寄りにする
    if contrast_marker and intents:
        for intent in background_intents:
            if intent not in intents:
                negative_intents.append(intent)

    # 「Xは自社でやるが、欲しいのはY」系の補足
    if contains_any(lower, ["欲しい", "使える費用", "使いたい", "探してます", "教えてください"]):
        if background_intents and intents:
            for intent in background_intents:
                if intent not in intents:
                    negative_intents.append(intent)

    # 片側だけしか取れなかった場合は全文から補完
    if not intents:
        intents = [name for name, words in INTENT_KEYWORDS.items() if contains_any(lower, words)]
    if not expense_types:
        expense_types = [name for name, words in EXPENSE_KEYWORDS.items() if contains_any(lower, words)]

    sectors = [name for name, words in SECTOR_KEYWORDS.items() if contains_any(lower, words)]
    negative_sectors = infer_negative_sectors_from_text(user_text)
    region = normalize_region(user_text)

    employee_count = None
    m = re.search(r"(\d{1,4})\s*(?:人|名)", user_text)
    if m:
        employee_count = int(m.group(1))

    noun_candidates = re.findall(r"[一-龥ぁ-んァ-ヴA-Za-z0-9\-]{2,}", user_text)
    keywords = [t for t in noun_candidates if t not in STOPWORDS and not normalize_region(t)]

    profile = ParsedProfile(
        company_phases=unique(phases),
        intents=unique(intents),
        background_intents=unique(background_intents),
        negative_intents=unique(negative_intents),
        expense_types=unique(expense_types),
        region=region,
        employee_count=employee_count,
        entity_type="company" if contains_any(user_text, ["会社", "法人", "株式会社", "合同会社", "スタートアップ", "ベンチャー"]) else None,
        keywords=unique(keywords)[:10],
        sectors=unique(sectors),
        negative_sectors=negative_sectors,
        budget_min=parse_budget_min(user_text),
        is_startup=contains_any(user_text, STARTUP_TERMS),
        university_origin=contains_any(user_text, UNIVERSITY_TERMS),
        rationale="",
    )
    enrich_profile(profile)
    return profile


def merge_profiles(primary: ParsedProfile, fallback: ParsedProfile) -> ParsedProfile:
    primary.company_phases = unique(primary.company_phases + fallback.company_phases)
    primary.intents = unique(primary.intents + fallback.intents)
    primary.background_intents = unique(primary.background_intents + fallback.background_intents)
    primary.negative_intents = unique(primary.negative_intents + fallback.negative_intents)
    primary.expense_types = unique(primary.expense_types + fallback.expense_types)
    primary.sectors = unique(primary.sectors + fallback.sectors)
    primary.negative_sectors = unique(primary.negative_sectors + fallback.negative_sectors)
    primary.keywords = unique(primary.keywords + fallback.keywords)[:10]
    if not primary.region:
        primary.region = fallback.region
    if primary.employee_count is None:
        primary.employee_count = fallback.employee_count
    if primary.entity_type is None:
        primary.entity_type = fallback.entity_type
    if primary.budget_min is None:
        primary.budget_min = fallback.budget_min
    primary.is_startup = primary.is_startup or fallback.is_startup
    primary.university_origin = primary.university_origin or fallback.university_origin
    if not primary.rationale:
        primary.rationale = fallback.rationale
    return primary


def _extract_openai_text(payload: Dict[str, Any]) -> str:
    output = payload.get("output") or []
    texts: List[str] = []
    for block in output:
        for content in block.get("content", []) or []:
            txt = content.get("text")
            if txt:
                texts.append(txt)
    return "\n".join(texts).strip()


def parse_profile_with_openai(user_text: str) -> Optional[ParsedProfile]:
    if not OPENAI_API_KEY:
        return None
    body = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": "日本語の自由記述から補助金検索条件をJSONで抽出してください。推測しすぎず、分からないものは null や空配列にしてください。intents にはユーザーが今回本当に欲しい用途だけを入れてください。background_intents には背景説明の用途、negative_intents には今回は求めていない用途を入れてください。intents は research,equipment,marketing,exhibition,overseas_inspection,overseas_expansion,it,sustainability,ip から選ぶ。expense_types は travel,exhibition,marketing,sales,rd,equipment,ip から選ぶ。sectors は space,medical,bio,healthcare,agri,foodtech,energy,nuclear,deeptech,fintech から選ぶ。negative_sectors は medical,drug_discovery から選ぶ。company_phases は idea,seed,early,growth から選ぶ。地域は「本社は福岡」のような表現も都道府県名に正規化して region に入れる。"},
            {"role": "user", "content": user_text},
        ],
        "text": {"format": {"type": "json_schema", "name": "grant_profile", "strict": True, "schema": PROFILE_SCHEMA}},
    }
    req = Request(OPENAI_BASE_URL, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}, method="POST")
    with urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    parsed = json.loads(_extract_openai_text(payload))
    return ParsedProfile(**parsed)


def parse_profile_with_anthropic(user_text: str) -> Optional[ParsedProfile]:
    if not ANTHROPIC_API_KEY:
        return None
    prompt = (
        "日本語の自由記述から補助金検索条件をJSONで抽出してください。intents には今回ほしい用途だけ、background_intents には背景用途、negative_intents には今回ほしくない用途を入れてください。"
        "intents は research,equipment,marketing,exhibition,overseas_inspection,overseas_expansion,it,sustainability,ip から選ぶ。"
        "expense_types は travel,exhibition,marketing,sales,rd,equipment,ip から選ぶ。"
        "sectors は space,medical,bio,healthcare,agri,foodtech,energy,nuclear,deeptech,fintech から選ぶ。negative_sectors は medical,drug_discovery から選ぶ。地域は「本社は福岡」のような表現も都道府県名に正規化して region に入れる。"
        "company_phases は idea,seed,early,growth から選ぶ。"
        "JSON以外は返さないでください。\n\n"
        f"入力: {user_text}"
    )
    body = {"model": ANTHROPIC_MODEL, "max_tokens": 800, "messages": [{"role": "user", "content": prompt}]}
    req = Request(ANTHROPIC_BASE_URL, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"}, method="POST")
    with urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    text = "\n".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    return ParsedProfile(**json.loads(text))


def parse_profile_with_gemini(user_text: str) -> Optional[ParsedProfile]:
    if not GEMINI_API_KEY:
        return None
    prompt = (
        "あなたは日本の補助金検索条件を構造化するアシスタントです。"
        "自由記述からJSONだけを返してください。"
        "intents には今回ほしい用途だけ、background_intents には背景用途、negative_intents には今回は求めていない用途を入れてください。"
        "研究開発費と販路開拓・展示会・海外視察費は区別してください。"
        "intents は research,equipment,marketing,exhibition,overseas_inspection,overseas_expansion,it,sustainability,ip。"
        "expense_types は travel,exhibition,marketing,sales,rd,equipment,ip。"
        "sectors は space,medical,bio,healthcare,agri,foodtech,energy,nuclear,deeptech,fintech。negative_sectors は medical,drug_discovery。地域は「本社は福岡」のような表現も都道府県名に正規化して region に入れる。"
        "company_phases は idea,seed,early,growth。\n\n"
        f"入力: {user_text}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseJsonSchema": PROFILE_SCHEMA,
        },
    }
    url = f"{GEMINI_BASE_URL}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    req = Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    candidates = payload.get("candidates") or []
    parts = (((candidates[0] or {}).get("content") or {}).get("parts") or []) if candidates else []
    text = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    return ParsedProfile(**json.loads(text))


def enrich_profile(profile: ParsedProfile) -> None:
    profile.company_phases = unique(profile.company_phases)
    profile.intents = unique(profile.intents)
    profile.background_intents = unique(profile.background_intents)
    profile.negative_intents = unique(profile.negative_intents)
    profile.expense_types = unique(profile.expense_types)
    profile.sectors = unique(profile.sectors)
    profile.negative_sectors = unique(profile.negative_sectors)
    if profile.negative_sectors:
        profile.sectors = [s for s in profile.sectors if s not in profile.negative_sectors]
    profile.keywords = unique(profile.keywords)[:10]
    profile.region = normalize_region(profile.region)

    if "ip" in profile.intents and "ip" not in profile.expense_types:
        profile.expense_types.append("ip")
    if "research" in profile.intents and "rd" not in profile.expense_types:
        profile.expense_types.append("rd")
    if "equipment" in profile.intents and "equipment" not in profile.expense_types:
        profile.expense_types.append("equipment")
    if "marketing" in profile.intents and "sales" not in profile.expense_types:
        profile.expense_types.append("sales")
    if "exhibition" in profile.intents and "exhibition" not in profile.expense_types:
        profile.expense_types.append("exhibition")

    # 背景用途は希望用途から外す
    if profile.background_intents:
        profile.intents = [i for i in profile.intents if i not in profile.background_intents or i in profile.negative_intents]

    if "ip" in profile.expense_types and "ip" not in profile.intents and "ip" not in profile.negative_intents:
        profile.intents.append("ip")
    if "rd" in profile.expense_types and "research" not in profile.intents and "research" not in profile.negative_intents:
        profile.intents.append("research")
    if "equipment" in profile.expense_types and "equipment" not in profile.intents and "equipment" not in profile.negative_intents:
        profile.intents.append("equipment")

    profile.intents = unique(profile.intents)
    profile.expense_types = unique(profile.expense_types)

    tags: List[str] = []
    if profile.region:
        tags.append(profile.region)
    tags.extend(profile.company_phases)
    tags.extend(profile.sectors)
    tags.extend(profile.intents)
    if profile.background_intents:
        tags.extend([f"背景:{x}" for x in profile.background_intents])
    if profile.negative_intents:
        tags.extend([f"除外:{x}" for x in profile.negative_intents])
    if profile.negative_sectors:
        tags.extend([f"除外分野:{x}" for x in profile.negative_sectors])
    tags.extend(profile.expense_types)
    if profile.employee_count is not None:
        tags.append(f"{profile.employee_count}名")
    if profile.budget_min:
        tags.append(f"{profile.budget_min // 10000:,}万円以上" if profile.budget_min % 10000 == 0 else f"{profile.budget_min:,}円以上")
    if profile.is_startup:
        tags.append("スタートアップ")
    if profile.university_origin:
        tags.append("大学発")
    profile.extracted_tags = unique(tags)

    profile.rationale = make_rationale(profile)

    missing = []
    if not profile.region:
        missing.append("region")
    if not profile.intents and not profile.expense_types:
        missing.append("purpose")
    if not profile.budget_min:
        missing.append("budget")
    profile.missing_fields = missing
    if "region" in missing:
        profile.followup_question = "本社所在地または応募したい地域を教えてください。地域不一致の制度は除外します。"
    elif "purpose" in missing:
        profile.followup_question = "今回ほしい用途を一つだけ教えてください。研究開発、展示会、販路開拓、知財、設備、海外視察などです。"
    elif "budget" in missing and not (profile.intents or profile.expense_types):
        profile.followup_question = "最低でもどれくらいの補助上限が必要ですか。例: 1000万円以上"
    else:
        profile.followup_question = None


def postprocess_profile_from_text(profile: ParsedProfile, user_text: str) -> ParsedProfile:
    text = user_text or ""
    lower = text.lower()

    inferred_region = normalize_region(text)
    if inferred_region and not profile.region:
        profile.region = inferred_region

    background_text, desired_text, contrast_marker = split_background_and_desired(text)
    desired_intents = infer_intents_from_segment(desired_text)
    background_intents = infer_intents_from_segment(background_text)
    desired_expenses = infer_expenses_from_segment(desired_text)
    for sector in infer_negative_sectors_from_text(text):
        if sector not in profile.negative_sectors:
            profile.negative_sectors.append(sector)
    if "healthcare" in profile.sectors and "medical" in profile.negative_sectors:
        profile.sectors = [s for s in profile.sectors if s != "medical"]

    # 対比がある場合は右側を優先して希望用途として採用
    if contrast_marker and desired_intents:
        profile.intents = unique(desired_intents + profile.intents)
        profile.expense_types = unique(desired_expenses + profile.expense_types)
        for intent in background_intents:
            if intent not in profile.background_intents:
                profile.background_intents.append(intent)
            if intent not in profile.intents and intent not in profile.negative_intents:
                profile.negative_intents.append(intent)

    if contains_any(lower, INTENT_KEYWORDS["ip"]) or contains_any(lower, EXPENSE_KEYWORDS["ip"]):
        if "ip" not in profile.intents and not contains_any(desired_text.lower(), IP_CONTENT_TERMS):
            profile.intents.append("ip")
        if "ip" not in profile.expense_types and not contains_any(desired_text.lower(), IP_CONTENT_TERMS):
            profile.expense_types.append("ip")

    # 研究開発が背景文脈だけなら背景へ移す
    if background_intents and contrast_marker and desired_intents:
        if "research" in background_intents and any(i in desired_intents for i in ["marketing", "exhibition", "overseas_inspection", "overseas_expansion", "ip"]):
            if "research" in profile.intents:
                profile.intents = [i for i in profile.intents if i != "research"]
            if "rd" in profile.expense_types:
                profile.expense_types = [e for e in profile.expense_types if e != "rd"]
            if "research" not in profile.background_intents:
                profile.background_intents.append("research")
            if "research" not in profile.negative_intents:
                profile.negative_intents.append("research")

    # 明示的な希望用途を補完
    if contains_any(desired_text.lower(), ["販路", "販路開拓", "営業", "商談"]):
        if "marketing" not in profile.intents:
            profile.intents.append("marketing")
        if "sales" not in profile.expense_types:
            profile.expense_types.append("sales")
    if contains_any(desired_text.lower(), ["展示会", "見本市", "出展"]):
        if "exhibition" not in profile.intents:
            profile.intents.append("exhibition")
        if "exhibition" not in profile.expense_types:
            profile.expense_types.append("exhibition")
    if contains_any(desired_text.lower(), ["研究", "研究開発", "試作", "実証", "poc", "プロトタイプ"]) and not profile.intents:
        if "research" not in profile.intents:
            profile.intents.append("research")
        if "rd" not in profile.expense_types:
            profile.expense_types.append("rd")

    if parse_budget_min(text) and not profile.budget_min:
        profile.budget_min = parse_budget_min(text)

    enrich_profile(profile)
    return profile


def parse_profile(user_text: str) -> Tuple[ParsedProfile, str, List[Dict[str, str]]]:
    heuristic = postprocess_profile_from_text(parse_profile_heuristic(user_text), user_text)
    diagnostics: List[Dict[str, str]] = []
    for provider, fn in (("gemini", parse_profile_with_gemini), ("openai", parse_profile_with_openai), ("anthropic", parse_profile_with_anthropic)):
        try:
            parsed = fn(user_text)
            if parsed:
                parsed = merge_profiles(parsed, heuristic)
                parsed = postprocess_profile_from_text(parsed, user_text)
                return parsed, provider, diagnostics
        except Exception as exc:
            message = str(exc)[:300]
            lowered = message.lower()
            is_transient = "503" in lowered or "service unavailable" in lowered or "429" in lowered or "timeout" in lowered
            if is_transient:
                LOGGER.info("profile parsing transient failure via %s: %s", provider, message)
            else:
                LOGGER.warning("profile parsing failed via %s: %s", provider, message)
            diagnostics.append({
                "provider": provider,
                "stage": "profile_parse",
                "message": message,
                "severity": "info" if is_transient else "warning",
                "fallback": "heuristic",
            })
    return heuristic, "heuristic", diagnostics
