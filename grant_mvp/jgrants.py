from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import JGRANTS_BASE_URL, JGRANTS_MAX_ITEMS, JGRANTS_REQUEST_TIMEOUT, MIN_LIVE_KEYWORD_LEN
from .models import ParsedProfile
from .config import DISCOVERY_KEYWORDS, INTENT_KEYWORDS, EXPENSE_KEYWORDS, SECTOR_KEYWORDS, STOPWORDS
from .utils import unique
from .repository import upsert_grants

class JGrantsClient:
    def __init__(self, base_url: str = JGRANTS_BASE_URL):
        self.base_url = base_url

    def _build_url(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        url = f"{self.base_url}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url += "?" + urlencode(clean, doseq=True)
        return url

    def _fetch_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self._build_url(path, params)
        req = Request(url, headers={"Accept": "application/json", "User-Agent": "grant-mvp/3.0"})
        try:
            with urlopen(req, timeout=JGRANTS_REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTPError {exc.code} for {url}: {body[:300]}") from exc
        except URLError as exc:
            raise RuntimeError(f"URLError for {url}: {exc.reason}") from exc

    def search_subsidies(self, keyword: str, *, max_items: int = 40, acceptance: Optional[int] = 1) -> List[Dict[str, Any]]:
        if len(keyword.strip()) < MIN_LIVE_KEYWORD_LEN:
            return []
        base_params = {"keyword": keyword, "sort": "created_date", "order": "DESC"}
        if acceptance is not None:
            base_params["acceptance"] = acceptance
        first = self._fetch_json("/v1/public/subsidies", base_params)
        rows = list(first.get("result") or [])
        seen = {str(r.get("id")) for r in rows if r.get("id")}
        for page in range(2, 5):
            if len(rows) >= max_items:
                break
            try:
                payload = self._fetch_json("/v1/public/subsidies", {**base_params, "page": page})
            except Exception:
                break
            page_rows = payload.get("result") or []
            fresh = [r for r in page_rows if str(r.get("id")) not in seen and r.get("id")]
            for r in fresh:
                seen.add(str(r.get("id")))
            rows.extend(fresh)
            if not fresh:
                break
        enriched: List[Dict[str, Any]] = []
        for item in rows[:max_items]:
            subsidy_id = item.get("id")
            if not subsidy_id:
                continue
            try:
                detail_payload = self._fetch_json(f"/v2/public/subsidies/id/{subsidy_id}")
                detail_rows = detail_payload.get("result") or []
                enriched.append(detail_rows[0] if detail_rows else item)
            except Exception:
                enriched.append(item)
        return enriched


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


def refresh_data() -> Dict[str, Any]:
    result = sync_keywords_to_cache(DISCOVERY_KEYWORDS, source="jgrants_seed", max_items_per_keyword=max(20, min(40, JGRANTS_MAX_ITEMS)))
    result["warning"] = " | ".join(result.get("warnings") or []) if result.get("warnings") else None
    return result


def ensure_live_cache_for_query(query: str, profile: ParsedProfile) -> Dict[str, Any]:
    return sync_keywords_to_cache(extract_live_keywords(profile, query), source="jgrants_live", max_items_per_keyword=30)


