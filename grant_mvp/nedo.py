from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .config import logger, JGRANTS_REQUEST_TIMEOUT
from .utils import strip_html, unique
from .features import funding_type_label, is_funding_support_candidate

NEDO_BASE_URL = 'https://www.nedo.go.jp'
NEDO_LIST_PATH = '/form/event.php'

DOMAIN_TO_KEYWORDS = {
    'ai': ['AI', 'ソフトウェア', 'データ', 'DX'],
    'bio': ['バイオ', '医療', '創薬', 'ヘルスケア'],
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
    'any': [],
    'development': ['研究開発', '開発', '試作'],
    'validation': ['PoC', '概念実証', '実証'],
    'equipment': ['設備', '装置', '機器'],
    'startup': ['スタートアップ', '事業化', 'sbir'],
    'grant_only': ['補助', '助成'],
}

PHASE_TO_KEYWORDS = {
    'idea': ['シーズ', '調査'],
    'poc': ['PoC', '概念実証'],
    'prototype': ['試作', '開発'],
    'demonstration': ['実証'],
    'commercialization': ['社会実装', '量産'],
}


def _fetch_html(params: Optional[Dict[str, Any]] = None) -> str:
    query = {'f': 'koubo.html', 'o': '-date'}
    if params:
        query.update({k: v for k, v in params.items() if v not in (None, '')})
    url = f"{NEDO_BASE_URL}{NEDO_LIST_PATH}?{urlencode(query)}"
    req = Request(url, headers={'User-Agent': 'grant-mvp/rd-nedo', 'Accept-Language': 'ja'})
    try:
        with urlopen(req, timeout=JGRANTS_REQUEST_TIMEOUT) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except (HTTPError, URLError) as exc:
        logger.info('NEDO fetch failed: %s', exc)
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


def _parse_rows(html_text: str) -> List[Dict[str, Any]]:
    if not html_text:
        return []
    rows: List[Dict[str, Any]] = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html_text, flags=re.I | re.S):
        if '<th' in tr.lower():
            continue
        tds = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, flags=re.I | re.S)
        if len(tds) < 5:
            continue
        row_text = _clean_text(tr)
        if not row_text or '公募情報一覧' in row_text:
            continue
        title_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', tr, flags=re.I | re.S)
        title = _clean_text(title_match.group(2)) if title_match else _clean_text(tds[2] if len(tds) > 2 else '')
        href = urljoin(NEDO_BASE_URL, title_match.group(1)) if title_match else None
        if not title:
            continue
        posted = _clean_text(tds[0]) if len(tds) > 0 else ''
        domain = _clean_text(tds[1]) if len(tds) > 1 else ''
        status = _clean_text(tds[3]) if len(tds) > 3 else ''
        deadline = _clean_text(tds[4]) if len(tds) > 4 else ''
        category = _clean_text(tds[5]) if len(tds) > 5 else ''
        detail = ' / '.join([p for p in [domain, category, status, f'締切: {deadline}' if deadline else '', posted] if p])
        if not is_funding_support_candidate(title, detail, href):
            continue
        item = {
            'id': f"nedo::{abs(hash((title, href or detail))) % (10 ** 12)}",
            'title': title,
            'institution_name': 'NEDO',
            'system_name': 'NEDO公募情報',
            'subsidy_catch_phrase': status,
            'detail': detail,
            'use_purpose': category or domain,
            'industry': domain,
            'target_area_search': '全国',
            'target_area_detail': '',
            'target_number_of_employees': '要確認',
            'subsidy_rate': None,
            'subsidy_max_limit': _parse_budget_from_text(title + ' ' + detail),
            'granttype': funding_type_label(title, detail),
            'acceptance_start_datetime': None,
            'acceptance_end_datetime': deadline,
            'project_end_deadline': None,
            'request_reception_presence': None,
            'is_enable_multiple_request': 0,
            'front_subsidy_detail_page_url': href,
            'status': 'open' if '公募' in status else ('upcoming' if '予告' in status else ('closed' if '終了' in status else 'unknown')),
            'raw_json': '',
            'content_hash': '',
            'source': 'nedo_live',
        }
        rows.append(item)
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
    region = (payload.get('region_text') or '').strip()
    if region:
        tokens.append(region)
    return unique(tokens)[:8]


def search_nedo(payload: Dict[str, Any], max_items: int = 12) -> Dict[str, Any]:
    keywords = build_keywords(payload)
    pages: List[str] = []
    if keywords:
        for kw in keywords[:3]:
            html_text = _fetch_html({'keyword': kw})
            if html_text:
                pages.append(html_text)
    else:
        html_text = _fetch_html()
        if html_text:
            pages.append(html_text)
    results: List[Dict[str, Any]] = []
    seen = set()
    for html_text in pages:
        for row in _parse_rows(html_text):
            if row['id'] in seen:
                continue
            seen.add(row['id'])
            results.append(row)
            if len(results) >= max_items:
                break
        if len(results) >= max_items:
            break
    return {'items': results, 'keywords': keywords, 'fetched': len(pages)}
