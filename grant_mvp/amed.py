from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .config import logger, JGRANTS_REQUEST_TIMEOUT
from .utils import strip_html, unique
from .features import funding_type_label, is_funding_support_candidate

AMED_SEARCH_URL = 'https://www.amed.go.jp/search.php?nav=1&search=search&stage%5B%5D=%E7%8F%BE%E5%9C%A8%E5%85%AC%E5%8B%9F%E4%B8%AD&category%5B%5D=%E5%85%AC%E5%8B%9F%E6%83%85%E5%A0%B1&keyword={keyword}'
AMED_INDEX_URL = 'https://www.amed.go.jp/koubo/koubo_index.html'

DOMAIN_TO_KEYWORDS = {
    'ai': ['AI', '人工知能', 'ヘルスケア'],
    'bio': ['バイオ', '創薬', '医療', 'ヘルスケア', '医療機器'],
    'agri': ['バイオ', '食品', 'ヘルスケア'],
    'foodtech': ['食品', 'ヘルスケア', 'バイオ'],
    'energy': ['ヘルスケア'],
    'space': ['医療機器'],
    'materials': ['医療機器'],
    'robotics': ['ロボット', '介護', '医療機器'],
    'semiconductor': ['医療機器'],
    'other': [],
}

SUPPORT_TO_KEYWORDS = {
    'any': [],
    'development': ['研究開発', '開発', '試作'],
    'validation': ['実証', '社会実装', 'PoC'],
    'equipment': ['医療機器', '開発'],
    'startup': ['スタートアップ', '実用化'],
    'grant_only': ['補助', '支援'],
}

PHASE_TO_KEYWORDS = {
    'idea': ['シーズ'],
    'poc': ['PoC', '概念実証'],
    'prototype': ['試作', '開発'],
    'demonstration': ['実証', '社会実装'],
    'commercialization': ['実用化', '社会実装'],
}


def _fetch_html(url: str) -> str:
    req = Request(url, headers={'User-Agent': 'grant-mvp/rd-amed', 'Accept-Language': 'ja'})
    try:
        with urlopen(req, timeout=JGRANTS_REQUEST_TIMEOUT) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except (HTTPError, URLError) as exc:
        logger.info('AMED fetch failed: %s', exc)
        return ''


def _clean_text(value: str) -> str:
    value = html.unescape(strip_html(value or ''))
    return re.sub(r'\s+', ' ', value).strip()


def _parse_budget_from_text(text: str) -> Optional[int]:
    text = text.replace(',', '')
    m = re.search(r'(\d+(?:\.\d+)?)\s*億円', text)
    if m:
        return int(float(m.group(1)) * 100_000_000)
    m = re.search(r'(\d+(?:\.\d+)?)\s*万円', text)
    if m:
        return int(float(m.group(1)) * 10_000)
    return None


def _make_item(title: str, href: Optional[str], detail: str, deadline: str, field: str) -> Dict[str, Any]:
    full_detail = ' / '.join([p for p in [field, detail, f'締切: {deadline}' if deadline else ''] if p])
    return {
        'id': f"amed::{abs(hash((title, href or detail))) % (10 ** 12)}",
        'title': title,
        'institution_name': 'AMED',
        'system_name': 'AMED公募情報',
        'subsidy_catch_phrase': field,
        'detail': full_detail,
        'use_purpose': field,
        'industry': field,
        'target_area_search': '全国',
        'target_area_detail': '',
        'target_number_of_employees': '要確認',
        'subsidy_rate': None,
        'subsidy_max_limit': _parse_budget_from_text(title + ' ' + detail),
        'granttype': funding_type_label(title, full_detail),
        'acceptance_start_datetime': None,
        'acceptance_end_datetime': deadline,
        'project_end_deadline': None,
        'request_reception_presence': None,
        'is_enable_multiple_request': 0,
        'front_subsidy_detail_page_url': href,
        'status': 'open',
        'raw_json': '',
        'content_hash': '',
        'source': 'amed_live',
    }


def _parse_rows(html_text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not html_text:
        return rows
    table_blocks = re.findall(r'<tr[^>]*>(.*?)</tr>', html_text, flags=re.I | re.S)
    for tr in table_blocks:
        tds = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, flags=re.I | re.S)
        if len(tds) < 5:
            continue
        title_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', tr, flags=re.I | re.S)
        title = _clean_text(title_match.group(2)) if title_match else _clean_text(tds[2])
        href = title_match.group(1) if title_match else None
        if href and href.startswith('/'):
            href = 'https://www.amed.go.jp' + href
        field = _clean_text(tds[3] if len(tds) > 3 else '')
        deadline = _clean_text(tds[4] if len(tds) > 4 else '')
        detail = _clean_text(tr)
        if not title or not is_funding_support_candidate(title, detail, href):
            continue
        rows.append(_make_item(title, href, detail[:180], deadline, field))
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


def search_amed(payload: Dict[str, Any], max_items: int = 12) -> Dict[str, Any]:
    keywords = build_keywords(payload)
    pages: List[str] = []
    if keywords:
        for kw in keywords[:3]:
            pages.append(_fetch_html(AMED_SEARCH_URL.format(keyword=quote(kw))))
    else:
        pages.append(_fetch_html(AMED_INDEX_URL))
    results: List[Dict[str, Any]] = []
    seen = set()
    for html_text in pages:
        for row in _parse_rows(html_text):
            combined = f"{row.get('title','')} {row.get('detail','')}"
            if keywords and not any(kw.lower() in combined.lower() for kw in keywords[:4]):
                continue
            if row['id'] in seen:
                continue
            seen.add(row['id'])
            results.append(row)
            if len(results) >= max_items:
                break
        if len(results) >= max_items:
            break
    return {'items': results, 'keywords': keywords, 'fetched': len([p for p in pages if p])}
