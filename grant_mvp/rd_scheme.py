from __future__ import annotations

from typing import Any, Dict, List

from .models import ParsedProfile
from .ranking import build_recommendation_response, compute_fit, explain_match_label, fit_label, make_public_item
from .utils import normalize_region
from .nedo import search_nedo
from .jst import search_jst
from .amed import search_amed
from .accelerators import search_accelerators
from .repository import cache_live_items

RD_META = {
    "rd_phases": [
        {"value": "", "label": "今の段階を選ぶ"},
        {"value": "idea", "label": "アイデア・シーズ探索"},
        {"value": "poc", "label": "PoC・概念実証"},
        {"value": "prototype", "label": "試作・開発"},
        {"value": "demonstration", "label": "実証・社会実装前"},
        {"value": "commercialization", "label": "事業化・量産前"},
    ],
    "tech_domains": [
        {"value": "", "label": "技術分野を選ぶ"},
        {"value": "ai", "label": "AI・ソフトウェア"},
        {"value": "medical", "label": "医療・医療機器"},
        {"value": "bio", "label": "バイオ・創薬"},
        {"value": "healthcare", "label": "ヘルスケア"},
        {"value": "agri", "label": "アグリテック"},
        {"value": "foodtech", "label": "フードテック"},
        {"value": "energy", "label": "エネルギー・GX"},
        {"value": "space", "label": "宇宙"},
        {"value": "materials", "label": "材料・化学"},
        {"value": "robotics", "label": "ロボティクス・製造"},
        {"value": "semiconductor", "label": "半導体・電子"},
        {"value": "other", "label": "その他"},
    ],
    "support_types": [
        {"value": "any", "label": "研究開発資金全般"},
        {"value": "development", "label": "研究・試作を進めたい"},
        {"value": "validation", "label": "PoC・実証を進めたい"},
        {"value": "equipment", "label": "設備導入も含めたい"},
        {"value": "startup", "label": "スタートアップ向けを優先"},
        {"value": "grant_only", "label": "補助金・助成金を優先"},
        {"value": "accelerator", "label": "アクセラ・自治体実証も見たい"},
        {"value": "activity_fund", "label": "活動資金・協業費も見たい"},
        {"value": "gap_fund", "label": "GAPファンドも見たい"},
        {"value": "deeptech_startup", "label": "NEDO・SBIR系も見たい"},
        {"value": "municipality_poc", "label": "自治体PoC・実証も見たい"},
        {"value": "ip", "label": "知財・特許を取りたい"},
    ],
    "budget_ranges": [
        {"value": "", "label": "金額帯は未指定"},
        {"value": "under5m", "label": "500万円未満"},
        {"value": "5m_30m", "label": "500万円〜3000万円"},
        {"value": "30m_100m", "label": "3000万円〜1億円"},
        {"value": "over100m", "label": "1億円以上"},
    ],
    "source_options": [
        {"value": "jgrants", "label": "Jグランツ"},
        {"value": "nedo", "label": "NEDO"},
        {"value": "jst", "label": "JST"},
        {"value": "amed", "label": "AMED"},
        {"value": "accelerators", "label": "アクセラ・GAP等"},
    ],
}

PHASE_TEXT = {
    "idea": "研究シーズやアイデア探索の段階です。",
    "poc": "PoCや概念実証の段階です。",
    "prototype": "試作や開発を進めたい段階です。",
    "demonstration": "実証や導入前検証の段階です。",
    "commercialization": "社会実装や量産前の段階です。",
}
DOMAIN_TEXT = {
    "ai": "AIやソフトウェア関連です。",
    "medical": "医療、医療機器、診断、治療関連です。",
    "bio": "バイオ、創薬、細胞、遺伝子関連です。",
    "healthcare": "ヘルスケア、予防、介護、健康関連です。",
    "agri": "アグリテック、農業、農林水産関連です。",
    "foodtech": "フードテック、食品、食料、発酵、代替タンパク関連です。",
    "energy": "エネルギー、脱炭素、GX関連です。",
    "space": "宇宙関連です。",
    "materials": "材料、化学、素材関連です。",
    "robotics": "ロボティクスや製造関連です。",
    "semiconductor": "半導体や電子関連です。",
    "other": "技術分野はその他です。",
}
SUPPORT_TEXT = {
    "any": "研究開発資金全般を幅広く探したいです。",
    "development": "研究や試作を前に進める資金を探しています。",
    "validation": "PoCや実証、社会実装前の検証資金を探しています。",
    "equipment": "設備や装置の導入を含む資金も探しています。",
    "startup": "スタートアップ向け制度を優先して見たいです。",
    "grant_only": "補助金・助成金を優先して見たいです。",
    "accelerator": "補助金という名称でなくても、アクセラレーター、自治体実証、共創プログラムも探したいです。",
    "activity_fund": "活動資金、協業費、PoC費用、実証支援として出る資金も探したいです。",
    "gap_fund": "大学発・研究シーズ向けのGAPファンドも探したいです。",
    "deeptech_startup": "NEDO STS、SBIR、ディープテック系のスタートアップ支援も探したいです。",
    "municipality_poc": "自治体のPoC、実証フィールド、社会実験支援も探したいです。",
    "ip": "特許・商標・意匠などの知的財産の出願・取得に使える資金を探しています。",
}
BUDGET_TEXT = {
    "under5m": "希望金額は500万円未満です。",
    "5m_30m": "希望金額は500万円から3000万円です。",
    "30m_100m": "希望金額は3000万円から1億円です。",
    "over100m": "希望金額は1億円以上です。",
}

BUDGET_BOUNDS = {
    "under5m": (0, 5_000_000),
    "5m_30m": (5_000_000, 30_000_000),
    "30m_100m": (30_000_000, 100_000_000),
    "over100m": (100_000_000, None),
}

NEGATIVE_SECTOR_TEXT = {
    "medical": "医療、病院、臨床、医療DXは除外してください。",
    "drug_discovery": "創薬、医薬品開発は除外してください。",
}

NEGATIVE_SECTOR_TERMS = {
    "medical": ["医療", "医療機器", "病院", "臨床", "患者", "医療DX", "医療dx", "診断", "治療"],
    "drug_discovery": ["創薬", "医薬", "医薬品", "薬剤", "drug", "pharma"],
}

LATE_PHASE_TERMS = [
    "trl5以上", "trl 5以上", "trl6", "trl 6", "trl7", "trl 7", "フェーズ3", "大規模技術開発実証",
    "量産", "商用化", "本格実装",
]

CONSTRUCTION_HEAVY_TERMS = [
    "企業立地", "立地補助", "工場等", "工場", "倉庫", "建物", "建築", "建設", "新増設",
    "土地", "不動産取得", "用地", "造成", "コンビナート", "施設整備", "zeb",
]

SURVEY_ONLY_TERMS = [
    "俯瞰調査", "技術動向調査", "市場形成に関する調査",
]

ACCELERATOR_REQUEST_TERMS = [
    "アクセラ", "アクセラレーター", "活動資金", "実証支援", "協業費", "共創",
    "gap", "gapファンド", "ギャップファンド", "自治体poc", "実証フィールド",
    "nedo", "sts", "sbir", "dtsu", "bak", "yak", "agventure", "accelerator", "activity fund",
]


def _infer_phase_from_free_text(payload: Dict[str, Any]) -> str:
    phase = (payload.get("rd_phase") or "").strip()
    if phase:
        return phase
    text = (payload.get("free_text") or "").lower()
    if any(term in text for term in ["poc", "概念実証", "圃場"]):
        return "poc"
    if any(term in text for term in ["試作", "プロトタイプ"]):
        return "prototype"
    if any(term in text for term in ["実証", "検証"]):
        return "demonstration"
    return ""


def _compose_text(payload: Dict[str, Any]) -> str:
    parts: List[str] = []
    for mapping, key in [
        (PHASE_TEXT, 'rd_phase'),
        (DOMAIN_TEXT, 'tech_domain'),
        (SUPPORT_TEXT, 'support_type'),
        (BUDGET_TEXT, 'budget_range'),
    ]:
        value = (payload.get(key) or '').strip()
        if value and value in mapping:
            parts.append(mapping[value])

    region_raw = (payload.get('region_text') or '').strip()
    region = normalize_region(region_raw) or region_raw
    if region:
        parts.append(f"応募したい地域は{region}です。地域が合わない公募は除外してください。")

    negative_sectors = payload.get("negative_sectors") or []
    if isinstance(negative_sectors, list):
        for sector in negative_sectors:
            text = NEGATIVE_SECTOR_TEXT.get(str(sector))
            if text:
                parts.append(text)

    free_text = (payload.get('free_text') or '').strip()
    if free_text:
        parts.append(free_text)
    return ' '.join(parts).strip()


def _selected_sources(payload: Dict[str, Any]) -> List[str]:
    sources = payload.get('sources')
    if isinstance(sources, list):
        clean = [str(s).strip().lower() for s in sources if str(s).strip()]
        return clean or ['jgrants', 'nedo', 'jst', 'amed', 'accelerators']
    return ['jgrants', 'nedo', 'jst', 'amed', 'accelerators']


def _item_text(item: Dict[str, Any]) -> str:
    return " ".join(str(item.get(k) or "") for k in ["title", "detail_plain", "subsidy_catch_phrase", "granttype", "system_name"]).lower()


def _accelerator_requested(payload: Dict[str, Any]) -> bool:
    support_type = (payload.get("support_type") or "").strip()
    if support_type in {"accelerator", "activity_fund", "gap_fund", "deeptech_startup", "municipality_poc", "startup", "validation"}:
        return True
    text = f"{payload.get('free_text') or ''} {payload.get('region_text') or ''}".lower()
    return any(term.lower() in text for term in ACCELERATOR_REQUEST_TERMS)


def _boost_accelerator_item(public_item: Dict[str, Any], raw_item: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    if not str(public_item.get("source") or "").startswith("accelerator"):
        return public_item
    if not _accelerator_requested(payload):
        return public_item

    catalog_score = int(raw_item.get("_accelerator_score") or 0)
    floor = 58
    if catalog_score >= 70:
        floor = 64
    if catalog_score >= 90:
        floor = 72

    free_text = (payload.get("free_text") or "").lower()
    title = (public_item.get("title") or "").lower()
    explicit_terms = [
        "bak", "yak", "agventure", "jaアクセラ", "ja accelerator", "agventure lab",
        "nedo", "sbir", "sts", "dtsu", "gtie", "hsfc", "ksac", "oist", "nexs",
    ]
    if any(term in free_text and term in title for term in explicit_terms):
        floor = max(floor, 78)
    if any(term in free_text for term in ["アクセラ", "活動資金", "実証支援", "gap", "ギャップファンド", "nedo", "sts", "sbir", "自治体"]):
        floor = max(floor, 68)

    item = dict(public_item)
    route = str(raw_item.get("route") or raw_item.get("applicant_route") or "")
    if "大学・研究者経由" in route or "大学・研究者" in route and "中心" in route:
        item["match_cautions"] = list(dict.fromkeys([
            *(item.get("match_cautions") or []),
            "大学・研究者経由の応募が中心です。企業単独で応募できるか確認してください",
        ]))[:6]

    current = int(public_item.get("match_score") or public_item.get("fit_percent") or 0)
    if current >= floor:
        return item

    item["match_score"] = floor
    item["fit_percent"] = floor
    item["fit_label"] = fit_label(floor)
    item["match_level"] = item["fit_label"]
    item["match_summary"] = explain_match_label(floor)
    item["review_required"] = floor < 78
    item["match_reasons"] = list(dict.fromkeys([
        "アクセラ・活動資金の希望に一致",
        *(item.get("match_reasons") or []),
    ]))[:6]
    if item.get("subsidy_max_limit") is None:
        item["match_cautions"] = list(dict.fromkeys([
            *(item.get("match_cautions") or []),
            "支援金額は募集回ごとの確認が必要です",
        ]))[:6]
    return item


def _apply_scheme_filters(items: List[Dict[str, Any]], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    budget_min, budget_max = BUDGET_BOUNDS.get((payload.get("budget_range") or "").strip(), (None, None))
    phase = _infer_phase_from_free_text(payload)
    out: List[Dict[str, Any]] = []

    for original in items:
        item = dict(original)
        if item.get("status") == "closed":
            continue

        max_limit = item.get("subsidy_max_limit")
        text = _item_text(item)
        cautions = list(item.get("match_cautions") or [])
        reasons = list(item.get("match_reasons") or [])
        score = int(item.get("match_score", item.get("fit_percent", 0)) or 0)

        if isinstance(max_limit, (int, float)) and max_limit > 0:
            if budget_min is not None and max_limit < budget_min:
                score = min(score, 48)
                cautions.append("補助上限が希望金額帯を下回ります")
            if budget_max is not None and max_limit > budget_max:
                score = min(score, 50)
                cautions.append("補助上限が希望金額帯より大きく、制度規模が重い可能性があります")

        if phase in {"idea", "poc", "prototype"} and any(term in text for term in LATE_PHASE_TERMS) and not str(item.get("source", "")).startswith("accelerator"):
            score = min(score, 48)
            cautions.append("希望フェーズより後ろの大型実証・事業化寄りです")

        if any(term in text for term in CONSTRUCTION_HEAVY_TERMS):
            score = min(score, 42)
            cautions.append("建物・土地・立地整備寄りのため、研究開発テーマとの適合は低めです")

        if any(term in text for term in SURVEY_ONLY_TERMS):
            score = min(score, 45)
            cautions.append("調査業務の公募に近く、PoC費用としてはズレる可能性があります")

        if score < 25:
            continue

        if score < 45:
            item["match_level"] = "低"
            item["fit_label"] = "低"
        elif score < 60:
            item["match_level"] = "要確認"
            item["fit_label"] = "要確認"
        elif score < 78:
            item["match_level"] = "要確認"
            item["fit_label"] = "要確認"
        else:
            item["match_level"] = "中"
            item["fit_label"] = "中"

        item["match_score"] = score
        item["fit_percent"] = score
        item["match_cautions"] = list(dict.fromkeys(cautions))
        item["match_reasons"] = list(dict.fromkeys(reasons))
        out.append(item)

    out.sort(key=lambda x: (x.get("match_score", 0), -(x.get("subsidy_max_limit") or 0)), reverse=True)
    return out


def _external_search_payload(payload: Dict[str, Any], profile: ParsedProfile) -> Dict[str, Any]:
    out = dict(payload)
    negative_sectors = set(out.get("negative_sectors") or getattr(profile, "negative_sectors", []) or [])
    if not (out.get("rd_phase") or "").strip():
        out["rd_phase"] = _infer_phase_from_free_text(payload)
    if not (out.get("tech_domain") or "").strip():
        sector_map = {
            "medical": "medical", "bio": "bio", "healthcare": "healthcare",
            "agri": "agri", "foodtech": "foodtech", "energy": "energy", "space": "space",
        }
        sectors = list(profile.sectors or [])
        if "medical" in negative_sectors and "healthcare" in sectors:
            out["tech_domain"] = "healthcare"
        else:
            for sector in sectors:
                if sector in sector_map:
                    out["tech_domain"] = sector_map[sector]
                    break
    original = (payload.get("free_text") or "")
    if not (out.get("support_type") or "").strip() or out.get("support_type") == "any":
        lowered = original.lower()
        if any(term in lowered for term in ["gapファンド", "gap fund", "ギャップファンド"]):
            out["support_type"] = "gap_fund"
        elif any(term in lowered for term in ["nedo", "sts", "sbir", "dtsu"]):
            out["support_type"] = "deeptech_startup"
        elif any(term in lowered for term in ["自治体", "実証フィールド", "社会実験"]):
            out["support_type"] = "municipality_poc"
        elif any(term in lowered for term in ["アクセラ", "accelerator"]):
            out["support_type"] = "accelerator"
        elif any(term in lowered for term in ["活動資金", "協業費", "支援金"]):
            out["support_type"] = "activity_fund"
        else:
            out["support_type"] = "validation" if out.get("rd_phase") in {"poc", "demonstration"} else "development"

    compact_terms: List[str] = []
    for term in [
        "医療", "医療機器", "診断", "治療", "ヘルスケア", "健康", "予防",
        "腸内環境", "腸内細菌", "マイクロバイオーム",
        "バイオ", "創薬", "細胞", "遺伝子",
        "アグリ", "農業", "農林水産", "植物", "微生物", "マイクロバイオーム", "圃場",
        "PoC", "実証", "研究開発", "食品", "フードテック",
        "アクセラ", "活動資金", "実証支援", "自治体", "実証フィールド", "GAPファンド",
        "ギャップファンド", "NEDO", "STS", "SBIR", "DTSU", "BAK", "YAK", "AgVenture",
        "GTIE", "HSFC", "KSAC", "OIST", "NEXs", "福岡", "大阪", "愛知", "北海道", "広島", "沖縄",
    ]:
        if "medical" in negative_sectors and term in NEGATIVE_SECTOR_TERMS["medical"]:
            continue
        if "drug_discovery" in negative_sectors and term in NEGATIVE_SECTOR_TERMS["drug_discovery"]:
            continue
        if term.lower() in original.lower():
            compact_terms.append(term)
    if compact_terms:
        out["free_text"] = " ".join(dict.fromkeys(compact_terms))
    return out


def build_rd_meta() -> Dict[str, Any]:
    return {"meta": RD_META, "note": "研究開発向けに絞ったシンプル検索です。資金支援ではない募集や施設利用案内は除外します"}


def build_rd_search(payload: Dict[str, Any]) -> Dict[str, Any]:
    input_text = _compose_text(payload)
    if not input_text:
        raise ValueError('条件を1つ以上入れてください')
    selected_sources = _selected_sources(payload)

    if 'jgrants' in selected_sources:
        result = build_recommendation_response(input_text, include_closed=bool(payload.get('include_closed', False)), fast_mode=payload.get('fast_mode'))
        profile = ParsedProfile(**(result.get('profile') or {}))
        combined = list(result.get('items') or [])
    else:
        result = {
            'profile': {}, 'engine': 'heuristic', 'fast_mode': bool(payload.get('fast_mode', True)),
            'llm_debug': {'used_llm': False, 'provider': None, 'diagnostics': []}, 'items': [], 'live_fetch': {'skipped': True}
        }
        from .profile_parser import parse_profile_heuristic, postprocess_profile_from_text
        profile = postprocess_profile_from_text(parse_profile_heuristic(input_text), input_text)
        combined = []

    source_counts = {'jgrants_items': 0, 'nedo_items': 0, 'jst_items': 0, 'amed_items': 0, 'accelerator_items': 0}
    if 'jgrants' in selected_sources:
        source_counts['jgrants_items'] = sum(1 for item in combined if str(item.get('source', '')).startswith('jgrants'))

    external_items: List[Dict[str, Any]] = []
    external_info: Dict[str, List[str]] = {'nedo_keywords': [], 'jst_keywords': [], 'amed_keywords': [], 'accelerator_keywords': []}
    external_payload = _external_search_payload(payload, profile)

    if 'nedo' in selected_sources:
        nedo = search_nedo(external_payload)
        external_info['nedo_keywords'] = nedo.get('keywords', [])
        for item in nedo.get('items', []):
            scored = compute_fit(profile, item)
            if scored is not None:
                external_items.append(make_public_item(scored))
    if 'jst' in selected_sources:
        jst = search_jst(external_payload)
        external_info['jst_keywords'] = jst.get('keywords', [])
        for item in jst.get('items', []):
            scored = compute_fit(profile, item)
            if scored is not None:
                external_items.append(make_public_item(scored))
    if 'amed' in selected_sources:
        amed = search_amed(external_payload)
        external_info['amed_keywords'] = amed.get('keywords', [])
        for item in amed.get('items', []):
            scored = compute_fit(profile, item)
            if scored is not None:
                external_items.append(make_public_item(scored))
    if 'accelerators' in selected_sources:
        accelerators = search_accelerators(external_payload, profile)
        external_info['accelerator_keywords'] = accelerators.get('keywords', [])
        for item in accelerators.get('items', []):
            scored = compute_fit(profile, item)
            if scored is not None:
                external_items.append(_boost_accelerator_item(make_public_item(scored), item, payload))

    seen_ids = {str(item.get('id')) for item in combined}
    for item in external_items:
        if str(item.get('id')) not in seen_ids:
            combined.append(item)
            seen_ids.add(str(item.get('id')))

    combined = _apply_scheme_filters(combined, payload)
    cache_live_items(combined)

    combined.sort(key=lambda x: (x.get('match_score', 0), x.get('subsidy_max_limit') or 0), reverse=True)
    result['items'] = combined[:20]
    source_counts = {'jgrants_items': 0, 'nedo_items': 0, 'jst_items': 0, 'amed_items': 0, 'accelerator_items': 0}
    for item in result['items']:
        src = str(item.get('source', ''))
        if src.startswith('jgrants'):
            source_counts['jgrants_items'] += 1
        elif src.startswith('nedo'):
            source_counts['nedo_items'] += 1
        elif src.startswith('jst'):
            source_counts['jst_items'] += 1
        elif src.startswith('amed'):
            source_counts['amed_items'] += 1
        elif src.startswith('accelerator'):
            source_counts['accelerator_items'] += 1
    result['source_mix'] = {**source_counts, **external_info}
    result['search_scheme'] = {
        'rd_phase': payload.get('rd_phase') or None,
        'tech_domain': payload.get('tech_domain') or None,
        'support_type': payload.get('support_type') or None,
        'budget_range': payload.get('budget_range') or None,
        'region_text': payload.get('region_text') or '',
        'free_text': payload.get('free_text') or '',
        'normalized_input_text': input_text,
        'sources': selected_sources,
        'funding_only': True,
    }
    return result
