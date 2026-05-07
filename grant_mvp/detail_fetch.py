from __future__ import annotations

import io
import re
from functools import lru_cache
from typing import Dict, List, Optional
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    from bs4 import BeautifulSoup
except ImportError:  # optional dependency for richer HTML extraction
    BeautifulSoup = None
try:
    from pypdf import PdfReader
except ImportError:  # optional dependency; PDF summary falls back to official page text
    PdfReader = None

from .config import JGRANTS_REQUEST_TIMEOUT, logger
from .utils import strip_html, unique

USER_AGENT = 'grant-mvp/detail-fetch'
MAX_PDF_PAGES = 8
MAX_HTML_CHARS = 20000
MAX_PDF_CHARS = 30000


@lru_cache(maxsize=256)
def fetch_detail_bundle(url: str) -> Dict[str, object]:
    out: Dict[str, object] = {
        'html_text': '',
        'pdf_text': '',
        'pdf_url': None,
        'notes': [],
    }
    if not url:
        out['notes'] = ['公式URLが未設定です']
        return out

    if url.lower().endswith('.pdf'):
        out['pdf_url'] = url
        out['pdf_text'] = _fetch_pdf_text(url)
        out['notes'] = ['PDF本文を取得しました'] if out['pdf_text'] else ['PDF本文は取得できませんでした']
        return out

    html_text = _fetch_html(url)
    out['html_text'] = html_text
    notes: List[str] = []
    if html_text:
        notes.append('詳細ページ本文を取得しました')
    else:
        notes.append('詳細ページ本文は取得できませんでした')

    pdf_links = _extract_pdf_links(url, html_text)
    if pdf_links:
        out['pdf_url'] = pdf_links[0]
        pdf_text = _fetch_pdf_text(pdf_links[0])
        out['pdf_text'] = pdf_text
        notes.append('公募要領PDF本文を取得しました' if pdf_text else '公募要領PDF本文は取得できませんでした')
    else:
        notes.append('公募要領PDFは見つかりませんでした')
    out['notes'] = notes
    return out


def _fetch_bytes(url: str) -> bytes:
    req = Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Language': 'ja'})
    with urlopen(req, timeout=JGRANTS_REQUEST_TIMEOUT) as resp:
        return resp.read()


def _fetch_html(url: str) -> str:
    try:
        body = _fetch_bytes(url)
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.info('detail html fetch failed: %s', exc)
        return ''
    text = body.decode('utf-8', errors='ignore')
    if BeautifulSoup is None:
        cleaned = strip_html(text)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned[:MAX_HTML_CHARS]
    soup = BeautifulSoup(text, 'html.parser')
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    main = soup.find('main') or soup.find('article') or soup.body or soup
    cleaned = strip_html(str(main))
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned[:MAX_HTML_CHARS]


def _extract_pdf_links(base_url: str, html_text: str) -> List[str]:
    if not html_text:
        return []
    # html_text is stripped; fetch raw anchors from source instead for links
    try:
        raw = _fetch_bytes(base_url).decode('utf-8', errors='ignore')
    except Exception:
        return []
    if BeautifulSoup is None:
        links = []
        for href in re.findall(r'href=[\"\']([^\"\']+\.pdf[^\"\']*)[\"\']', raw, flags=re.I):
            full = urljoin(base_url, href)
            if full not in links:
                links.append(full)
        return links
    soup = BeautifulSoup(raw, 'html.parser')
    links: List[str] = []
    preferred: List[str] = []
    for a in soup.find_all('a', href=True):
        href = urljoin(base_url, a['href'])
        label = strip_html(a.get_text(' '))
        if '.pdf' not in href.lower() and 'pdf' not in label.lower() and '公募要領' not in label and '募集要項' not in label:
            continue
        if href not in links:
            links.append(href)
        if any(key in label for key in ['公募要領', '募集要項', '応募要領', '公募概要']):
            if href not in preferred:
                preferred.append(href)
    return preferred + [x for x in links if x not in preferred]


def _fetch_pdf_text(url: str) -> str:
    if PdfReader is None:
        logger.info('detail pdf fetch skipped: pypdf is not installed')
        return ''
    try:
        body = _fetch_bytes(url)
        reader = PdfReader(io.BytesIO(body))
    except Exception as exc:
        logger.info('detail pdf fetch failed: %s', exc)
        return ''
    texts: List[str] = []
    for page in reader.pages[:MAX_PDF_PAGES]:
        try:
            txt = page.extract_text() or ''
        except Exception:
            txt = ''
        if txt:
            texts.append(txt)
    text = '\n'.join(texts)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:MAX_PDF_CHARS]


def merged_source_text(item: Dict[str, object], bundle: Dict[str, object]) -> str:
    parts = [
        str(item.get('title') or ''),
        str(item.get('detail') or ''),
        str(item.get('use_purpose') or ''),
        str(item.get('industry') or ''),
        str(bundle.get('html_text') or ''),
        str(bundle.get('pdf_text') or ''),
    ]
    return '\n'.join(p for p in parts if p).strip()


def extract_budget_text(text: str, fallback_rate: Optional[str] = None, fallback_max: Optional[int] = None) -> str:
    snippets = _find_sentences(text, ['補助率', '助成率', '補助上限', '助成上限', '上限', '下限', '研究開発費'])
    amount_bits = []
    for m in re.findall(r'(?:上限|下限)?\s*\d+(?:\.\d+)?\s*億円|(?:上限|下限)?\s*\d+(?:\.\d+)?\s*万円|\d+\s*千万円', text):
        if m not in amount_bits:
            amount_bits.append(m)
    rate = fallback_rate or _first_match(text, [r'補助率[^。\n]{0,20}', r'助成率[^。\n]{0,20}', r'\d+\s*/\s*\d+', r'\d+%'])
    if fallback_max:
        amount_bits.insert(0, f'上限{fallback_max:,}円')
    joined = ' / '.join(unique(amount_bits[:3]))
    if rate and joined:
        return f'{joined} / {rate}'
    if joined:
        return joined
    if rate:
        return rate
    if snippets:
        return snippets[0]
    return '要確認'


def extract_deadline_text(text: str, fallback_deadline: Optional[str] = None) -> str:
    if fallback_deadline:
        return fallback_deadline
    patterns = [
        r'20\d{2}年\d{1,2}月\d{1,2}日',
        r'令和\d+年\d{1,2}月\d{1,2}日',
        r'\d{4}[/-]\d{1,2}[/-]\d{1,2}',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0)
    snippets = _find_sentences(text, ['締切', '公募期間', '応募期間', '受付期間', '提出期限'])
    return snippets[0] if snippets else '要確認'


def extract_field_text(text: str, fallback: str = '要確認') -> str:
    mapping = [
        ('AI・ソフトウェア', ['ai', '人工知能', 'ソフトウェア', 'データ', 'dx']),
        ('バイオ・医療', ['バイオ', '医療', '創薬', 'ヘルスケア', '医療機器']),
        ('アグリ・フードテック', ['農業', 'アグリ', '食品', 'フード', '食']),
        ('エネルギー・GX', ['エネルギー', 'gx', '脱炭素', '水素', '再エネ']),
        ('宇宙', ['宇宙', '衛星', 'ロケット']),
        ('材料・化学', ['材料', '素材', '化学']),
        ('ロボティクス・製造', ['ロボ', '製造', 'ものづくり']),
        ('半導体・電子', ['半導体', '電子']),
    ]
    hay = text.lower()
    for label, kws in mapping:
        if any(k in hay for k in kws):
            return label
    return fallback


def _find_sentences(text: str, keywords: List[str], limit: int = 3) -> List[str]:
    if not text:
        return []
    chunks = re.split(r'[。\n]', text)
    hits: List[str] = []
    for chunk in chunks:
        chunk = chunk.strip(' ・:：\t ')
        if len(chunk) < 4:
            continue
        if any(k.lower() in chunk.lower() for k in keywords):
            hits.append(chunk)
        if len(hits) >= limit:
            break
    return hits


def _first_match(text: str, patterns: List[str]) -> Optional[str]:
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0)
    return None
