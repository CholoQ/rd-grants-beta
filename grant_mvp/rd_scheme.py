from __future__ import annotations

from typing import Any, Dict, List

from .models import ParsedProfile
from .ranking import build_recommendation_response, compute_fit, make_public_item
from .utils import normalize_region
from .nedo import search_nedo
from .jst import search_jst
from .amed import search_amed
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
        {"value": "bio", "label": "バイオ・医療"},
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
    "bio": "バイオ、医療、ヘルスケア関連です。",
    "agri": "アグリテック関連です。",
    "foodtech": "フードテック関連です。",
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
    "ip": "特許・商標・意匠などの知的財産の出願・取得に使える資金を探しています。",
}
BUDGET_TEXT = {
    "under5m": "希望金額は500万円未満です。",
    "5m_30m": "希望金額は500万円から3000万円です。",
    "30m_100m": "希望金額は3000万円から1億円です。",
    "over100m": "希望金額は1億円以上です。",
}


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

    free_text = (payload.get('free_text') or '').strip()
    if free_text:
        parts.append(free_text)
    return ' '.join(parts).strip()


def _selected_sources(payload: Dict[str, Any]) -> List[str]:
    sources = payload.get('sources')
    if isinstance(sources, list):
        clean = [str(s).strip().lower() for s in sources if str(s).strip()]
        return clean or ['jgrants', 'nedo', 'jst', 'amed']
    return ['jgrants', 'nedo', 'jst', 'amed']


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

    source_counts = {'jgrants_items': 0, 'nedo_items': 0, 'jst_items': 0, 'amed_items': 0}
    if 'jgrants' in selected_sources:
        source_counts['jgrants_items'] = sum(1 for item in combined if str(item.get('source', '')).startswith('jgrants'))

    external_items: List[Dict[str, Any]] = []
    external_info: Dict[str, List[str]] = {'nedo_keywords': [], 'jst_keywords': [], 'amed_keywords': []}

    if 'nedo' in selected_sources:
        nedo = search_nedo(payload)
        external_info['nedo_keywords'] = nedo.get('keywords', [])
        for item in nedo.get('items', []):
            scored = compute_fit(profile, item)
            if scored is not None:
                external_items.append(make_public_item(scored))
    if 'jst' in selected_sources:
        jst = search_jst(payload)
        external_info['jst_keywords'] = jst.get('keywords', [])
        for item in jst.get('items', []):
            scored = compute_fit(profile, item)
            if scored is not None:
                external_items.append(make_public_item(scored))
    if 'amed' in selected_sources:
        amed = search_amed(payload)
        external_info['amed_keywords'] = amed.get('keywords', [])
        for item in amed.get('items', []):
            scored = compute_fit(profile, item)
            if scored is not None:
                external_items.append(make_public_item(scored))

    seen_ids = {str(item.get('id')) for item in combined}
    for item in external_items:
        if str(item.get('id')) not in seen_ids:
            combined.append(item)
            seen_ids.add(str(item.get('id')))

    cache_live_items(combined)

    combined.sort(key=lambda x: (x.get('match_score', 0), x.get('subsidy_max_limit') or 0), reverse=True)
    result['items'] = combined[:10]
    for item in result['items']:
        src = str(item.get('source', ''))
        if src.startswith('jgrants'):
            source_counts['jgrants_items'] += 0  # already counted above
        elif src.startswith('nedo'):
            source_counts['nedo_items'] += 1
        elif src.startswith('jst'):
            source_counts['jst_items'] += 1
        elif src.startswith('amed'):
            source_counts['amed_items'] += 1
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
