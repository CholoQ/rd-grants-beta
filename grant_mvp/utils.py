from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from .config import (
    CONTRAST_MARKERS, EXPENSE_KEYWORDS, INTENT_KEYWORDS, REGION_ALIASES, STOPWORDS
)
from .models import ParsedProfile

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def unique(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for item in items:
        item = (item or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_region(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value)
    for prefecture, aliases in REGION_ALIASES.items():
        if prefecture in text:
            return prefecture
        for alias in aliases:
            if alias in text:
                return prefecture
    return None


def contains_any(text: str, terms: List[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def parse_budget_min(text: str) -> Optional[int]:
    cleaned = text.replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*億円\s*(?:以上|超|程度|くらい)?", cleaned)
    if m:
        return int(float(m.group(1)) * 100_000_000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*万円\s*(?:以上|超|程度|くらい)?", cleaned)
    if m:
        return int(float(m.group(1)) * 10_000)
    m = re.search(r"(\d{4,})\s*円\s*(?:以上|超|程度|くらい)?", cleaned)
    if m:
        return int(m.group(1))
    return None

CONTRAST_MARKERS = ["ですが", "だが", "けれど", "けど", "ものの", "ただし", "一方で", "一方、", "ただ", "しかし"]

def infer_intents_from_segment(text: str) -> List[str]:
    lower = text.lower()
    return [name for name, words in INTENT_KEYWORDS.items() if contains_any(lower, words)]

def infer_expenses_from_segment(text: str) -> List[str]:
    lower = text.lower()
    return [name for name, words in EXPENSE_KEYWORDS.items() if contains_any(lower, words)]

def split_background_and_desired(user_text: str) -> Tuple[str, str, Optional[str]]:
    text = user_text or ""
    for marker in CONTRAST_MARKERS:
        if marker in text:
            left, right = text.split(marker, 1)
            if right.strip():
                return left.strip(), right.strip(), marker
    return "", text.strip(), None

def make_rationale(profile: ParsedProfile) -> str:
    parts: List[str] = []
    if profile.intents:
        parts.append("希望用途=" + ", ".join(profile.intents))
    if profile.background_intents:
        parts.append("背景=" + ", ".join(profile.background_intents))
    if profile.negative_intents:
        parts.append("除外=" + ", ".join(profile.negative_intents))
    if profile.region:
        parts.append(f"地域={profile.region}")
    if profile.budget_min:
        parts.append(f"予算下限={profile.budget_min:,}円")
    return " / ".join(parts) if parts else "入力文から主要条件を抽出しました"


