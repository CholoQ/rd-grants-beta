from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .config import logger, JGRANTS_REQUEST_TIMEOUT
from .utils import strip_html, unique
from .features import funding_type_label, is_funding_support_candidate

JST_TT_URL = 'https://www.jst.go.jp/tt/bosyu/'
JST_BOSYU_URL = 'https://www.jst.go.jp/bosyu/bosyu.html'

DOMAIN_TO_KEYWORDS = {
    'ai': ['AI', 'ソフトウェア', 'データ', 'DX'],
    'medical': ['医療', '医療機器', '診断', '治療'],
    'bio': ['バイオ', '創薬', '細胞', '遺伝子'],
    'healthcare': ['ヘルスケア', '健康', '介護', '予防'],
    'agri': ['農業', 'アグリ', 'バイオ'],
    'foodtech': ['食品', 'フード', 'バイオ'],
    'energy': ['エネルギー', 'GX', '脱炭素', '水素', '再エネ'],
    'space': ['宇宙', '衛星', 'ロケット'],
    'materials': ['材料', '化学', '素材'],
    'robotics': ['ロボット', '製造', 'ものづくり'],
    'semiconductor': ['半導体', '電子'],
}

SUPPORT_TO_KEYWORDS = {
    'research': ['研究開発', '技術開発', '研究'],
    'poc': ['PoC', '概念実証', '実証', '試作'],
    'equipment': ['設備', '装置', '機器'],
    'subsidy': ['補助', '助成', 'グラント', '支援'],
    'consortium': ['共同研究', 'コンソーシアム', '産学共同'],
}

PHASE_TO_KEYWORDS = {
    'idea': ['シーズ', '調査'],
    'poc': ['PoC', '概念実証'],
    'prototype': ['試作', '開発'],
    'demonstration': ['実証'],
    'commercialization': ['社会実装', '起業', '事業化'],
}

ALLOW_TITLE_TERMS = [
    'A-STEP', 'SBIR', 'D-Global', '大学発新産業創出基金', '早暁', '実装支援',
    '産学共同', '起業実証', 'START', '技術移転', 'スタートアップ', '企業化',
]
DENY_TITLE_TERMS = [
    'さきがけ', '創発', 'CREST', 'ERATO', 'ACT-X', '研究者', '学生', '博士',
]


def _fetch_html(url: str, params: Optional[Dict[str, Any]] = None) -> str:
    if params:
        url = f"{url}?{urlencode({k:v for k,v in params.items() if v not in (None, '')})}"
    req = Request(url, headers={'User-Agent': 'grant-mvp/rd-jst', 'Accept-Language': 'ja'})
    try:
        with urlopen(req, timeout=JGRANTS_REQUEST_TIMEOUT) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except (HTTPError, URLError) as exc:
        logger.info('JST fetch failed: %s', exc)
        return ''


def _clean_text(value: str) -> str:
    value = html.unescape(strip_html(value or ''))
    value = re.sub(r'\s+', ' ', value).strip()
    return value


def _parse_budget_from_text(text: str) -> Optional[int]:
    text = text.replace(',', '')
    m = re.search(r'(\d+(?:\.\d+)?)\s*億円', text)
    if m:
        return int(float(m.group(1)) * 100_000_000)
    m = re.search(r'(\d+(?:\.\d+)?)\s*万円', text)
    if m:
        return int(float(m.group(1)) * 10_000)
    return None


def _is_company_or_startup_friendly(title: str, detail: str) -> bool:
    hay = f"{title} {detail}".lower()
    allow = any(term.lower() in hay for term in ALLOW_TITLE_TERMS)
    deny = any(term.lower() in hay for term in DENY_TITLE_TERMS)
    return allow and not deny and is_funding_support_candidate(title, detail)


def _status_from_text(text: str) -> str:
    lowered = text.lower()
    if '終了' in text or '締切' in text and '済' in text:
        return 'closed'
    if '予告' in text:
        return 'upcoming'
    if '公募' in text or '募集' in text or '案内中' in text:
        return 'open'
    return 'unknown'


def _make_item(title: str, href: Optional[str], detail: str, deadline: str, extra: str) -> Dict[str, Any]:
    full_detail = ' / '.join([p for p in [detail, extra, f'締切: {deadline}' if deadline else ''] if p])
    return {
        'id': f"jst::{abs(hash((title, href or full_detail))) % (10 ** 12)}",
        'title': title,
        'institution_name': 'JST',
        'system_name': 'JST公募情報',
        'subsidy_catch_phrase': detail,
        'detail': full_detail,
        'use_purpose': extra or detail,
        'industry': detail,
        'target_area_search': '全国',
        'target_area_detail': '',
        'target_number_of_employees': '要確認',
        'subsidy_rate': None,
        'subsidy_max_limit': _parse_budget_from_text(title + ' ' + full_detail),
        'granttype': funding_type_label(title, full_detail),
        'acceptance_start_datetime': None,
        'acceptance_end_datetime': deadline,
        'project_end_deadline': None,
        'request_reception_presence': None,
        'is_enable_multiple_request': 0,
        'front_subsidy_detail_page_url': href,
        'status': _status_from_text(full_detail),
        'raw_json': '',
        'content_hash': '',
        'source': 'jst_live',
    }


def _parse_tt_rows(html_text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not html_text:
        return rows
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html_text, flags=re.I | re.S):
        tds = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, flags=re.I | re.S)
        if len(tds) < 2:
            continue
        deadline = _clean_text(tds[0])
        title_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', tr, flags=re.I | re.S)
        title = _clean_text(title_match.group(2)) if title_match else _clean_text(tds[1])
        href = title_match.group(1) if title_match else None
        if href and href.startswith('/'):
            href = 'https://www.jst.go.jp' + href
        detail = '産学連携・技術移転系'
        if not title or not _is_company_or_startup_friendly(title, detail):
            continue
        rows.append(_make_item(title, href, detail, deadline, '企業・スタートアップ向け候補'))
    return rows


def _parse_general_blocks(html_text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not html_text:
        return rows
    # fall back: scan list items / news blocks containing key programs
    for match in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html_text, flags=re.I | re.S):
        href = match.group(1)
        title = _clean_text(match.group(2))
        if not title or not _is_company_or_startup_friendly(title, title):
            continue
        if href.startswith('/'):
            href = 'https://www.jst.go.jp' + href
        window = html_text[max(0, match.start()-200): min(len(html_text), match.end()+300)]
        nearby = _clean_text(window)
        deadline_match = re.search(r'20\d{2}年\d{1,2}月\d{1,2}日[^ ]*', nearby)
        deadline = deadline_match.group(0) if deadline_match else ''
        rows.append(_make_item(title, href, 'JST公募中情報', deadline, nearby[:180]))
    return rows


def build_keywords(payload: Dict[str, Any]) -> List[str]:
    tokens: List[str] = []
    free_text = (payload.get('free_text') or '').strip()
    if free_text:
        tokens.extend(re.findall(r'[一-龥ぁ-んァ-ヴA-Za-z0-9\-]{2,}', free_text))
    for mapping, key in [
        (PHASE_TO_KEYWORDS, 'rd_phase'),
        (DOMAIN_TO_KEYWORDS, 'tech_domain'),
        (SUPPORT_TO_KEYWORDS, 'support_type'),
    ]:
        value = (payload.get(key) or '').strip()
        tokens.extend(mapping.get(value, []))
    return unique(tokens)[:8]


def search_jst(payload: Dict[str, Any], max_items: int = 12) -> Dict[str, Any]:
    keywords = build_keywords(payload)
    pages = [_fetch_html(JST_TT_URL), _fetch_html(JST_BOSYU_URL)]
    results: List[Dict[str, Any]] = []
    seen = set()
    parsers = [_parse_tt_rows, _parse_general_blocks]
    for html_text in pages:
        for parser in parsers:
            for row in parser(html_text):
                combined_text = f"{row.get('title','')} {row.get('detail','')}"
                if keywords and not any(kw.lower() in combined_text.lower() for kw in keywords[:4]):
                    # keep strong startup-oriented programs even if keyword overlap is weak
                    if not any(term.lower() in combined_text.lower() for term in ['a-step', 'sbir', 'd-global', 'スタートアップ']):
                        continue
                if row['id'] in seen:
                    continue
                seen.add(row['id'])
                results.append(row)
                if len(results) >= max_items:
                    return {'items': results, 'keywords': keywords, 'fetched': len([p for p in pages if p])}
    return {'items': results, 'keywords': keywords, 'fetched': len([p for p in pages if p])}
