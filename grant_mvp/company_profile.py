from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.request import Request, urlopen

from .config import JGRANTS_REQUEST_TIMEOUT, logger
from .utils import strip_html, unique


DOMAIN_RULES = [
    ("medical", ["医療", "医療機器", "診断", "治療", "臨床", "病院", "患者", "医師", "画像診断"]),
    ("bio", ["創薬", "バイオ", "細胞", "遺伝子", "抗体", "タンパク質", "再生医療", "ゲノム"]),
    ("healthcare", ["ヘルスケア", "healthcare", "健康", "予防", "未病", "ウェルネス", "介護", "睡眠", "生活習慣", "腸内環境", "腸内細菌", "腸内フローラ", "菌叢", "マイクロバイオーム", "microbiome", "gut microbiome", "健康寿命"]),
    ("agri", [
        "農業", "農林水産", "スマート農業", "畜産", "水産", "栽培", "作物", "圃場",
        "植物", "根", "生育", "土壌", "肥料", "農薬", "共生", "微生物", "菌根",
        "内生菌", "エンドファイト", "endophyte", "食・農", "農・環境",
    ]),
    ("foodtech", ["フードテック", "食品", "食料", "発酵", "代替肉", "培養肉", "機能性食品", "代替タンパク"]),
    ("energy", ["脱炭素", "gx", "再エネ", "蓄電", "水素", "省エネ"]),
    ("ai", ["ai", "人工知能", "機械学習", "ソフトウェア", "saas", "データ解析"]),
    ("materials", ["材料", "素材", "化学", "樹脂", "フィルム"]),
    ("robotics", ["ロボット", "製造", "自動化", "センシング"]),
    ("semiconductor", ["半導体", "電子", "デバイス"]),
    ("space", ["宇宙", "衛星", "ロケット"]),
]


def _normalize_company_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("会社URLを入力してください")
    if not re.match(r"^https?://", raw, flags=re.I):
        if re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/.*)?$", raw):
            raw = f"https://{raw}"
        else:
            raise ValueError("会社URLを入力してください。例: https://example.co.jp")
    return raw


def _fetch_site_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "grant-mvp/company-profile", "Accept-Language": "ja"})
    try:
        with urlopen(req, timeout=JGRANTS_REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.info("company url fetch failed: %s", exc)
        raise ValueError("会社URLを読み取れませんでした。自由記述で概要を入力してください")
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", body, flags=re.I | re.S)
    return re.sub(r"\s+", " ", strip_html(body)).strip()[:12000]


def _negative_sectors(text: str) -> List[str]:
    hits: List[str] = []
    if re.search(r"医療(?:系|関連|dx|DX)?(?:は|を|も)?(?:除|外|いらない|不要|避け)|(?:exclude|no|avoid)\s+medical", text or "", flags=re.I):
        hits.append("medical")
    if re.search(r"病院(?:向け|関連)?(?:は|を|も)?(?:除|外|いらない|不要|避け)|(?:exclude|no|avoid)\s+hospital", text or "", flags=re.I):
        hits.append("medical")
    if re.search(r"創薬(?:は|を|も)?(?:除|外|いらない|不要|避け)|医薬(?:品)?(?:は|を|も)?(?:除|外|いらない|不要|避け)|(?:exclude|no|avoid)\s+(?:drug|pharma|drug discovery)", text or "", flags=re.I):
        hits.append("drug_discovery")
    if "medical" in hits and any(term in (text or "").lower() for term in ["ヘルスケア", "healthcare", "腸内環境", "腸内細菌", "マイクロバイオーム", "microbiome", "未病", "予防"]):
        hits.append("drug_discovery")
    return unique(hits)


def _pick_domain(text: str, preference_text: str = "") -> str:
    lowered = text.lower()
    preference_lower = (preference_text or "").lower()
    negatives = set(_negative_sectors(preference_text))
    healthcare_terms = ["ヘルスケア", "healthcare", "腸内環境", "腸内細菌", "腸内フローラ", "菌叢", "マイクロバイオーム", "microbiome", "gut microbiome", "未病", "予防", "健康寿命"]
    if any(term.lower() in preference_lower for term in healthcare_terms):
        return "healthcare"
    best = ("other", 0)
    for value, terms in DOMAIN_RULES:
        if value in negatives:
            continue
        score = sum(1 for term in terms if term.lower() in lowered)
        if value == "healthcare" and score:
            if any(term.lower() in lowered for term in healthcare_terms):
                score += 4
        if value == "agri" and score:
            if any(term in lowered for term in ["植物", "土壌", "圃場", "内生菌", "エンドファイト", "endophyte", "菌根", "共生"]):
                score += 3
        if score > best[1]:
            best = (value, score)
    return best[0]


def _pick_phase(text: str) -> str:
    lowered = text.lower()
    if any(k in lowered for k in ["poc", "概念実証", "圃場", "ラボ実証", "ラボで実証"]):
        return "poc"
    if any(k in lowered for k in ["量産", "販売中", "導入実績", "商用化", "社会実装"]):
        return "commercialization"
    if any(k in lowered for k in ["実証", "pilot", "β", "ベータ", "trl5", "trl6"]):
        return "demonstration"
    if any(k in lowered for k in ["試作", "プロトタイプ", "開発中", "poc"]):
        return "prototype"
    if any(k in lowered for k in ["研究", "シーズ", "特許"]):
        return "poc"
    return "prototype"


def _pick_budget_range(text: str) -> str:
    text = (text or "").replace(",", "").lower()

    def classify(amount_yen: int) -> str:
        if amount_yen >= 100_000_000:
            return "over100m"
        if amount_yen >= 30_000_000:
            return "30m_100m"
        if amount_yen >= 5_000_000:
            return "5m_30m"
        if amount_yen > 0:
            return "under5m"
        return ""

    range_to_oku = re.search(r"(\d+(?:\.\d+)?)\s*(?:万|万円)?\s*[〜~～\-]\s*(\d+(?:\.\d+)?)\s*億", text)
    if range_to_oku:
        return "30m_100m"
    m = re.search(r"(\d+(?:\.\d+)?)\s*億", text)
    if m:
        return classify(int(float(m.group(1)) * 100_000_000))
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", text)
    if m:
        return classify(int(float(m.group(1)) * 10_000))
    m = re.search(r"(\d{7,})\s*(?:円|yen)?", text)
    if m:
        return classify(int(m.group(1)))
    if re.search(r"(?:1|１)\s*億円|10000\s*万円", text):
        return "over100m"
    if re.search(r"3000\s*万円|5000\s*万円|1\s*億", text):
        return "30m_100m"
    if re.search(r"500\s*万円|1000\s*万円|2000\s*万円", text):
        return "5m_30m"
    return ""


def _pick_support_type(text: str) -> str:
    lowered = (text or "").lower()
    if any(k in lowered for k in ["poc", "実証", "圃場", "フィールド"]):
        return "validation"
    if any(k in lowered for k in ["設備", "装置", "機械"]):
        return "equipment"
    if any(k in lowered for k in ["知財", "特許", "出願"]):
        return "ip"
    if any(k in lowered for k in ["試作", "研究", "開発", "ラボ"]):
        return "development"
    return "development"


def _detected_signals(text: str) -> List[str]:
    signals: List[str] = []
    for term in [
        "植物", "土壌", "圃場", "内生菌", "エンドファイト", "微生物", "共生",
        "腸内環境", "腸内細菌", "マイクロバイオーム", "医療機器", "診断", "治療", "創薬", "ヘルスケア", "PoC", "実証", "試作",
        "資金調達", "シード", "シリーズA", "スタートアップ",
    ]:
        if term.lower() in (text or "").lower():
            signals.append(term)
    return unique(signals)[:10]


def infer_company_profile_from_url(url: str, need_text: str = "") -> Dict[str, Any]:
    normalized_url = _normalize_company_url(url)
    try:
        text = _fetch_site_text(normalized_url)
    except ValueError:
        summary = "会社URLを受け取りました。サイト本文は自動取得できなかったため、技術概要を少し足すと精度が上がります。"
        payload = {
            "rd_phase": "",
            "tech_domain": "",
            "support_type": _pick_support_type(need_text),
            "budget_range": _pick_budget_range(need_text),
            "region_text": "",
            "free_text": "\n".join([f"会社URL: {normalized_url}", need_text]).strip(),
            "sources": ["jgrants", "nedo", "jst", "amed"],
            "negative_sectors": _negative_sectors(need_text),
            "fast_mode": True,
        }
        return {
            "url": normalized_url,
            "summary": summary,
            "confidence": "URLのみ",
            "payload": payload,
            "detected_signals": _detected_signals(need_text),
            "needs_more_info": True,
        }
    combined_text = f"{text}\n{need_text}".strip()
    domain = _pick_domain(combined_text, need_text)
    phase = _pick_phase(combined_text)
    snippets: List[str] = []
    for sentence in re.split(r"[。\n]", text):
        cleaned = sentence.strip()
        if 20 <= len(cleaned) <= 120:
            snippets.append(cleaned)
        if len(snippets) >= 3:
            break
    summary = " / ".join(unique(snippets)) or "会社サイトの本文から概要を推定しました"
    payload = {
        "rd_phase": phase,
        "tech_domain": domain,
        "support_type": _pick_support_type(combined_text),
        "budget_range": _pick_budget_range(need_text),
        "region_text": "",
        "free_text": "\n".join([f"会社URL: {normalized_url}", f"技術概要: {summary}", need_text]).strip(),
        "sources": ["jgrants", "nedo", "jst", "amed"],
        "negative_sectors": _negative_sectors(need_text),
        "fast_mode": True,
    }
    return {
        "url": normalized_url,
        "summary": summary,
        "confidence": "初期推定",
        "detected_signals": _detected_signals(combined_text),
        "payload": payload,
    }
