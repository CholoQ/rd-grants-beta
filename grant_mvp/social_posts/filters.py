"""公募抽出ロジック.

S3 では deadline_near のみ。DB は repository.db() を読み取り専用で利用する。
タイトル・detail・catch は strip_html で HTMLタグを除去してから返す。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from ..repository import db
from ..utils import strip_html


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    """'2026-05-25T08:00Z' などから date を取り出す。失敗時 None。"""
    if not value:
        return None
    head = value.strip().split("T")[0]
    if not head:
        return None
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


def _prepare(row) -> Dict[str, Any]:
    d = dict(row)
    d["title"] = strip_html(d.get("title") or "")
    d["detail"] = strip_html(d.get("detail") or "")
    d["subsidy_catch_phrase"] = strip_html(d.get("subsidy_catch_phrase") or "")
    return d


def find_deadline_near(
    days: int = 14,
    limit: int = 200,
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """締切が今日〜+days 日以内の公募を返す（締切が近い順）。

    各レコードに `_days_until_deadline`（int）を付与する。
    """
    today = today or date.today()
    conn = db()
    rows = conn.execute(
        """
        SELECT * FROM grants
        WHERE acceptance_end_datetime IS NOT NULL
          AND acceptance_end_datetime != ''
        """
    ).fetchall()

    out: List[Dict[str, Any]] = []
    for row in rows:
        end = _parse_iso_date(row["acceptance_end_datetime"])
        if not end:
            continue
        d = (end - today).days
        if d < 0 or d > days:
            continue
        item = _prepare(row)
        item["_days_until_deadline"] = d
        out.append(item)

    out.sort(key=lambda x: x["_days_until_deadline"])
    return out[:limit]


# ===== S4: 仮置きキーワード（要見直し） =====
_POC_KEYWORDS = ("PoC", "ＰｏＣ", "実証", "概念実証", "プロトタイプ", "試作")
_IP_KEYWORDS = ("知財", "知的財産", "特許", "商標", "意匠")
_STARTUP_KEYWORDS = ("スタートアップ", "創業", "起業", "ベンチャー")
_SME_KEYWORDS = ("中小企業", "小規模事業者", "中小・小規模")


def _is_open(row, today: date) -> bool:
    """受付中（締切が今日以降、または締切不明）か。"""
    end = _parse_iso_date(row["acceptance_end_datetime"])
    if end is None:
        return True
    return end >= today


def _text_blob(row) -> str:
    """キーワード検索用に複数カラムを連結し strip_html。"""
    parts = (
        row["title"] or "",
        row["subsidy_catch_phrase"] or "",
        row["detail"] or "",
        row["use_purpose"] or "",
        row["industry"] or "",
    )
    return strip_html(" ".join(parts))


def _match_any(text: str, keywords) -> bool:
    text_lower = text.lower()
    return any(str(kw).lower() in text_lower for kw in keywords)


def _find_by_keywords(keywords, limit: int = 200) -> List[Dict[str, Any]]:
    today = date.today()
    conn = db()
    rows = conn.execute("SELECT * FROM grants").fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not _is_open(row, today):
            continue
        if not _match_any(_text_blob(row), keywords):
            continue
        out.append(_prepare(row))
    return out[:limit]


def find_today(
    hours: int = 24,
    limit: int = 200,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """直近 hours 時間以内に同期された公募（last_synced_at ベース）。受付中のみ。"""
    now = now or datetime.utcnow()
    threshold = now - timedelta(hours=hours)
    today = now.date()
    conn = db()
    rows = conn.execute(
        "SELECT * FROM grants "
        "WHERE last_synced_at IS NOT NULL AND last_synced_at != ''"
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        raw = (row["last_synced_at"] or "").replace("Z", "+00:00")
        try:
            synced = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if synced.tzinfo is not None:
            synced = synced.replace(tzinfo=None)
        if synced < threshold:
            continue
        if not _is_open(row, today):
            continue
        out.append(_prepare(row))
    out.sort(key=lambda x: x.get("last_synced_at") or "", reverse=True)
    return out[:limit]


def find_poc(limit: int = 200) -> List[Dict[str, Any]]:
    return _find_by_keywords(_POC_KEYWORDS, limit=limit)


def find_ip(limit: int = 200) -> List[Dict[str, Any]]:
    return _find_by_keywords(_IP_KEYWORDS, limit=limit)


def find_startup(limit: int = 200) -> List[Dict[str, Any]]:
    return _find_by_keywords(_STARTUP_KEYWORDS, limit=limit)


def find_sme(limit: int = 200) -> List[Dict[str, Any]]:
    return _find_by_keywords(_SME_KEYWORDS, limit=limit)
