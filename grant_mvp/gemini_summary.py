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
                    "medical",
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
    vague_terms = [
        "公募要領に記載", "書類一式", "公式公募要領で確認", "公式要領で確認",
        "詳細は公式", "要確認のみ",
    ]
    for item in raw_items:
        text = _clean_text(item, fallback="", max_len=max_len)
        if not text or text in seen or any(term in text for term in vague_terms):
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


def build_focused_source_text(source_text: str, limit: int = 24000) -> str:
    """Keep the beginning plus decision-critical excerpts from long guidelines."""
    clean = re.sub(r"\s+", " ", source_text or "").strip()
    if len(clean) <= limit:
        return clean

    keywords = [
        "目的", "概要", "応募資格", "対象者", "補助対象者", "申請者", "提案者",
        "補助対象経費", "対象経費", "助成対象経費", "対象外経費", "補助率", "補助上限",
        "助成上限", "公募期間", "締切", "提出期限", "必要書類", "提出書類", "添付書類",
        "申請書", "事業計画", "経費明細", "見積", "決算", "GビズID", "審査", "採択",
    ]
    sentences = re.split(r"(?<=[。])|[\n\r]+", clean)
    focused: List[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        item = sentence.strip(" 　・-")
        if len(item) < 12:
            continue
        if not any(k in item for k in keywords):
            continue
        item = item[:240]
        if item in seen:
            continue
        seen.add(item)
        focused.append(item)
        if len(" ".join(focused)) >= 11000:
            break

    for keyword in keywords:
        if len(" ".join(focused)) >= 13000:
            break
        start = 0
        while True:
            pos = clean.find(keyword, start)
            if pos < 0:
                break
            item = clean[max(0, pos - 80):pos + 280].strip(" 　・-")
            item = item[:260]
            start = pos + len(keyword)
            if len(item) < 12 or item in seen:
                continue
            seen.add(item)
            focused.append(item)
            break

    head = clean[:9000]
    tail = clean[-2500:] if len(clean) > 18000 else ""
    parts = [head]
    if focused:
        parts.append("応募判断に関係しそうな抜粋: " + " / ".join(focused))
    if tail:
        parts.append("文末付近の情報: " + tail)
    return "\n\n".join(parts)[:limit]


def build_gemini_summary_prompt(source_text: str, title: str = "") -> str:
    focused_source = build_focused_source_text(source_text)
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
- 原文の文章をそのまま短縮しない。行政文を「誰が、何をするために、何円くらい使えるのか」に翻訳する
- overview は「誰向けの、何に使えるお金か」が一読で分かる1文にする
- purpose は制度の目的をやさしい日本語に言い換える。目次・章見出し・制度変更の羅列を入れない
- target_companies は「誰が応募できる？」への答えにする。対象地域、法人種別、企業単独応募の可否、従業員条件を分けて書く
- target_companies で「募集要項を参照」「対象者は別添参照」のような表現は禁止。分からない場合は「企業単独応募の可否を確認」など確認点に分解する
- suitable_for には、この公募が向いている企業像を入れる
- not_suitable_for には、この公募が重すぎる/合わない可能性がある企業像を入れる
- preparation_tasks には、応募前に準備すべき実務タスクを入れる
- expert_type_needed には、相談すべき専門家タイプを入れる
- first_questions_to_ask には、専門家や社内で最初に確認すべき質問を入れる
- required_documents には、資料本文に出ている書類名を具体的に入れる
- required_documents で「公募要領に記載の書類一式」「必要書類一式」「公式サイトを確認」のような抽象表現は禁止
- required_documents が本文から明確に読めない場合も、申請書、事業計画書、経費明細、会社概要、決算書、見積書、GビズIDなど実務上確認すべき書類候補に分解する
- cautions には「公式要領で確認」だけでなく、何を確認するのかを具体的に入れる
- first_questions_to_ask には、対象地域、対象経費、事前着手、締切、必要書類など具体的な質問にする
- overview と purpose は120文字以内の短文にする。制度の本質が伝わる内容を残す
- 各リスト項目は60文字以内の体言止めで書く
- 難しい行政用語は避け、初めて補助金を読む人にも伝わる言葉を選ぶ
- 短くするために制度の対象・条件・金額などの重要情報を削らない
- 「要確認」を使う場合も、何を確認するのかが分かる表現にする

	制度名:
	{title or '要確認'}

	公募本文:
	{focused_source}
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
