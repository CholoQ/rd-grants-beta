from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from .config import GEMINI_API_KEY, GEMINI_BASE_URL, GEMINI_MODEL, logger

# Gemini must return exactly this JSON shape.
# The values are designed for "application decision" rather than a generic summary.
GEMINI_SUMMARY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "purpose": {"type": "string"},
        "target_companies": {"type": "array", "items": {"type": "string"}},
        "suitable_for": {"type": "array", "items": {"type": "string"}},
        "not_suitable_for": {"type": "array", "items": {"type": "string"}},
        "rd_phase": {
            "type": "string",
            "enum": [
                "idea",
                "poc",
                "prototype",
                "demonstration",
                "commercialization",
                "unknown",
            ],
        },
        "fields": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "ai",
                    "bio",
                    "healthcare",
                    "agri",
                    "foodtech",
                    "energy",
                    "materials",
                    "robotics",
                    "semiconductor",
                    "space",
                    "gx",
                    "manufacturing",
                    "university_startup",
                    "other",
                ],
            },
        },
        "budget": {"type": "string"},
        "deadline": {"type": "string"},
        "eligible_expenses": {"type": "array", "items": {"type": "string"}},
        "required_documents": {"type": "array", "items": {"type": "string"}},
        "preparation_tasks": {"type": "array", "items": {"type": "string"}},
        "cautions": {"type": "array", "items": {"type": "string"}},
        "expert_type_needed": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "行政書士",
                    "中小企業診断士",
                    "認定支援機関",
                    "税理士",
                    "弁理士",
                    "研究開発コンサル",
                    "大学発ベンチャー支援者",
                    "技術顧問",
                    "法務専門家",
                    "要確認",
                ],
            },
        },
        "first_questions_to_ask": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "overview",
        "purpose",
        "target_companies",
        "suitable_for",
        "not_suitable_for",
        "rd_phase",
        "fields",
        "budget",
        "deadline",
        "eligible_expenses",
        "required_documents",
        "preparation_tasks",
        "cautions",
        "expert_type_needed",
        "first_questions_to_ask",
    ],
    "additionalProperties": False,
}

SUMMARY_KEYS: List[str] = list(GEMINI_SUMMARY_SCHEMA["required"])
ARRAY_KEYS = {
    "target_companies",
    "suitable_for",
    "not_suitable_for",
    "fields",
    "eligible_expenses",
    "required_documents",
    "preparation_tasks",
    "cautions",
    "expert_type_needed",
    "first_questions_to_ask",
}
STRING_KEYS = set(SUMMARY_KEYS) - ARRAY_KEYS
VALID_RD_PHASES = {
    "idea",
    "poc",
    "prototype",
    "demonstration",
    "commercialization",
    "unknown",
}


def _clean_text(value: Any, fallback: str = "要確認", max_len: int = 120) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return fallback
    if len(text) > max_len:
        text = text[:max_len].rstrip() + "…"
    return text


def _clean_list(value: Any, *, max_items: int = 6, max_len: int = 60) -> List[str]:
    if isinstance(value, list):
        raw_items = value
    elif value in (None, ""):
        raw_items = []
    else:
        raw_items = [value]

    out: List[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = _clean_text(item, fallback="", max_len=max_len)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= max_items:
            break
    return out or ["要確認"]


def normalize_gemini_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Gemini output so downstream UI can rely on a fixed shape."""
    normalized: Dict[str, Any] = {}
    for key in STRING_KEYS:
        normalized[key] = _clean_text(data.get(key))
    for key in ARRAY_KEYS:
        normalized[key] = _clean_list(data.get(key))

    rd_phase = normalized.get("rd_phase", "unknown")
    if rd_phase not in VALID_RD_PHASES:
        normalized["rd_phase"] = "unknown"

    # Keep the key order stable for JSON dumps and snapshots.
    return {key: normalized.get(key, ["要確認"] if key in ARRAY_KEYS else "要確認") for key in SUMMARY_KEYS}


def build_gemini_summary_prompt(source_text: str, title: str = "") -> str:
    return f"""
あなたは日本の研究開発資金公募を読むアナリストです。
以下の公募情報を、研究開発型企業が応募判断しやすいJSONに整理してください。

ルール:
- 必ず指定されたJSONスキーマだけで返す
- 原文にない断定はしない
- 分からない項目は「要確認」とする
- 採択可能性は断定しない
- 単なる要約ではなく、公募要領を読む前の一次判断に使える形にする
- 研究開発型スタートアップ、大学発ベンチャー、技術系中小企業が理解しやすい表現にする
- suitable_for には、この公募が向いている企業像を入れる
- not_suitable_for には、この公募が重すぎる/合わない可能性がある企業像を入れる
- preparation_tasks には、応募前に準備すべき実務タスクを入れる
- expert_type_needed には、相談すべき専門家タイプを入れる
- first_questions_to_ask には、専門家や社内で最初に確認すべき質問を入れる
- overview と purpose は120文字以内の短文にする。制度の本質が伝わる内容を残す
- 各リスト項目は60文字以内の体言止めで書く
- 難しい行政用語は避け、初めて補助金を読む人にも伝わる言葉を選ぶ
- 短くするために制度の対象・条件・金額などの重要情報を削らない

制度名:
{title or '要確認'}

公募本文:
{(source_text or '')[:18000]}
""".strip()


def summarize_grant_with_gemini(source_text: str, title: str = "", timeout: int = 45) -> Optional[Dict[str, Any]]:
    """Return a fixed-shape application-decision summary from Gemini.

    Returns None when Gemini is not configured or when generation fails.
    Callers should fall back to the existing rule-based summary in that case.
    """
    if not GEMINI_API_KEY:
        return None

    clean_source = (source_text or "").strip()
    if len(clean_source) < 200:
        return None

    body = {
        "contents": [{"parts": [{"text": build_gemini_summary_prompt(clean_source, title)}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseJsonSchema": GEMINI_SUMMARY_SCHEMA,
        },
    }
    url = f"{GEMINI_BASE_URL}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    try:
        req = Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        candidates = payload.get("candidates") or []
        parts = (((candidates[0] or {}).get("content") or {}).get("parts") or []) if candidates else []
        raw = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        if not raw:
            return None
        return normalize_gemini_summary(json.loads(raw))
    except Exception as exc:
        logger.info("Gemini fixed summary failed: %s", exc)
        return None
