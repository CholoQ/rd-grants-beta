from __future__ import annotations

import json
import re
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    ANTHROPIC_API_KEY, AUTO_REFRESH_MAX_AGE_HOURS, AUTO_REFRESH_ON_START, DB_PATH, GEMINI_API_KEY, GRANTS_SCHEMA,
    LEGAL_DISCLAIMER, OPENAI_API_KEY, SYNC_EVENTS_SCHEMA, LEADS_SCHEMA, GRANT_SUMMARIES_SCHEMA, FAST_MODE_DEFAULT,
    ENABLE_LIVE_FETCH_IN_FAST_MODE, ENABLE_LLM_PROFILE_IN_FAST_MODE, ENABLE_LLM_RERANK_IN_FAST_MODE, SNAPSHOT_DB_PATH,
    ANALYTICS_EVENTS_SCHEMA,
)
from .utils import strip_html, utcnow
from .status_utils import effective_status

LIVE_ITEM_CACHE: Dict[str, Dict[str, Any]] = {}


def cache_live_items(items: List[Dict[str, Any]]) -> None:
    for item in items or []:
        item_id = str(item.get("id") or "").strip()
        if item_id:
            LIVE_ITEM_CACHE[item_id] = dict(item)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    if not DB_PATH.exists() and SNAPSHOT_DB_PATH.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SNAPSHOT_DB_PATH, DB_PATH)
    conn = db()
    with conn:
        conn.execute(GRANTS_SCHEMA)
        conn.execute(SYNC_EVENTS_SCHEMA)
        conn.execute(LEADS_SCHEMA)
        conn.execute(GRANT_SUMMARIES_SCHEMA)
        conn.execute(ANALYTICS_EVENTS_SCHEMA)
    conn.close()




def safe_public_url(url: Optional[str]) -> Optional[str]:
    if not url or not isinstance(url, str):
        return None
    if not url.startswith(("http://", "https://")):
        return None
    return url


def preferred_public_url(item: Dict[str, Any]) -> Optional[str]:
    text = f"{item.get('detail') or ''} {item.get('subsidy_catch_phrase') or ''}"
    urls = re.findall(r"https?://[^\s\"'<>]+", text)
    for url in urls:
        cleaned = url.rstrip("。、）,)")
        if "jgrants-portal.go.jp" not in cleaned and safe_public_url(cleaned):
            return cleaned
    return safe_public_url(item.get("front_subsidy_detail_page_url"))


def prepare_item(item: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(item)
    item["detail_plain"] = strip_html(item.get("detail") or item.get("subsidy_catch_phrase") or "")
    item["safe_public_url"] = preferred_public_url(item)
    item["status"] = effective_status(item)
    return item

def get_grant_summary_cache(grant_id: str, source_text_hash: str) -> Optional[Dict[str, Any]]:
    """Return a cached fixed-shape Gemini summary when it matches the current source text."""
    if not grant_id or not source_text_hash:
        return None
    conn = db()
    row = conn.execute(
        "SELECT summary_json, source_text_hash, model, created_at, updated_at FROM grant_summaries WHERE grant_id = ?",
        (grant_id,),
    ).fetchone()
    conn.close()
    if not row or row["source_text_hash"] != source_text_hash:
        return None
    try:
        summary = json.loads(row["summary_json"] or "{}")
    except json.JSONDecodeError:
        return None
    return {
        "summary": summary,
        "source_text_hash": row["source_text_hash"],
        "model": row["model"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def upsert_grant_summary_cache(grant_id: str, summary: Dict[str, Any], source_text_hash: str, model: str) -> Dict[str, Any]:
    """Store or replace a fixed-shape Gemini summary for a grant."""
    if not grant_id:
        raise ValueError("grant_id is required")
    now = utcnow()
    conn = db()
    current = conn.execute("SELECT created_at FROM grant_summaries WHERE grant_id = ?", (grant_id,)).fetchone()
    payload = {
        "grant_id": grant_id,
        "summary_json": json.dumps(summary or {}, ensure_ascii=False, sort_keys=True),
        "source_text_hash": source_text_hash,
        "model": model,
        "created_at": current["created_at"] if current else now,
        "updated_at": now,
    }
    with conn:
        conn.execute(
            """
            INSERT INTO grant_summaries (grant_id, summary_json, source_text_hash, model, created_at, updated_at)
            VALUES (:grant_id, :summary_json, :source_text_hash, :model, :created_at, :updated_at)
            ON CONFLICT(grant_id) DO UPDATE SET
              summary_json=excluded.summary_json,
              source_text_hash=excluded.source_text_hash,
              model=excluded.model,
              updated_at=excluded.updated_at
            """,
            payload,
        )
    conn.close()
    return {"ok": True, "grant_id": grant_id, "model": model, "updated_at": now}


def _clean_analytics_text(value: Any, limit: int = 120) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    return text[:limit]


def log_analytics_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    event_type = _clean_analytics_text(payload.get("event_type") or payload.get("type") or "event", 40)
    if not re.match(r"^[a-zA-Z0-9_.:-]{1,40}$", event_type):
        event_type = "event"
    path = _clean_analytics_text(payload.get("path") or "/", 160)
    visitor_id = _clean_analytics_text(payload.get("visitor_id") or "", 160)
    visitor_hash = sha256(visitor_id.encode("utf-8")).hexdigest() if visitor_id else None
    raw_detail = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    safe_detail = {
        _clean_analytics_text(k, 40): _clean_analytics_text(v, 120)
        for k, v in (raw_detail or {}).items()
        if k not in {"free_text", "query", "message", "email", "name", "phone"}
    }
    conn = db()
    with conn:
        conn.execute(
            """
            INSERT INTO analytics_events (event_type, path, visitor_hash, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_type, path, visitor_hash, json.dumps(safe_detail, ensure_ascii=False), utcnow()),
        )
    conn.close()
    return {"ok": True}


def get_analytics_summary(days: int = 30) -> Dict[str, Any]:
    days = max(1, min(int(days or 30), 180))
    conn = db()
    since_expr = f"-{days - 1} days"
    event_rows = conn.execute(
        """
        SELECT event_type, COUNT(*) AS count
        FROM analytics_events
        WHERE datetime(created_at) >= datetime('now', ?)
        GROUP BY event_type
        ORDER BY count DESC
        """,
        (since_expr,),
    ).fetchall()
    daily_rows = conn.execute(
        """
        SELECT date(created_at) AS day,
               COUNT(CASE WHEN event_type = 'page_view' THEN 1 END) AS page_views,
               COUNT(CASE WHEN event_type LIKE 'search%' THEN 1 END) AS searches,
               COUNT(DISTINCT visitor_hash) AS visitors
        FROM analytics_events
        WHERE datetime(created_at) >= datetime('now', ?)
        GROUP BY date(created_at)
        ORDER BY day DESC
        """,
        (since_expr,),
    ).fetchall()
    total = conn.execute(
        """
        SELECT COUNT(CASE WHEN event_type = 'page_view' THEN 1 END) AS page_views,
               COUNT(CASE WHEN event_type LIKE 'search%' THEN 1 END) AS searches,
               COUNT(DISTINCT visitor_hash) AS visitors
        FROM analytics_events
        WHERE datetime(created_at) >= datetime('now', ?)
        """,
        (since_expr,),
    ).fetchone()
    top_paths = conn.execute(
        """
        SELECT path, COUNT(*) AS count
        FROM analytics_events
        WHERE event_type = 'page_view'
          AND datetime(created_at) >= datetime('now', ?)
        GROUP BY path
        ORDER BY count DESC
        LIMIT 10
        """,
        (since_expr,),
    ).fetchall()
    conn.close()
    return {
        "days": days,
        "totals": {
            "page_views": int(total["page_views"] or 0) if total else 0,
            "searches": int(total["searches"] or 0) if total else 0,
            "visitors": int(total["visitors"] or 0) if total else 0,
        },
        "events": [dict(row) for row in event_rows],
        "daily": [dict(row) for row in daily_rows],
        "top_paths": [dict(row) for row in top_paths],
    }


def normalize_status(start: Optional[str], end: Optional[str]) -> str:
    now = datetime.now(timezone.utc)
    try:
        if start:
            sdt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if now < sdt:
                return "upcoming"
        if end:
            edt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if now > edt:
                return "closed"
        return "open"
    except ValueError:
        return "unknown"


def workflow_label(workflow: Dict[str, Any]) -> Optional[str]:
    for key in ("name", "title", "fiscal_year_round"):
        value = workflow.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def explode_jgrants_record(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    workflows = record.get("workflow")
    if not isinstance(workflows, list) or not workflows:
        return [record]
    grant_id = str(record.get("id") or record.get("name") or "")
    title = record.get("title") or record.get("name") or "名称未設定"
    rows: List[Dict[str, Any]] = []
    for workflow in workflows:
        wf_id = str(workflow.get("id") or sha256(json.dumps(workflow, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12])
        label = workflow_label(workflow)
        row = dict(record)
        row["id"] = f"{grant_id}::{wf_id}" if grant_id else wf_id
        if label and label not in title:
            row["title"] = f"{title} / {label}"
        row["target_area_search"] = workflow.get("target_area_search") or record.get("target_area_search")
        row["target_area_detail"] = workflow.get("target_area_detail") or record.get("target_area_detail")
        row["acceptance_start_datetime"] = workflow.get("acceptance_start_datetime") or record.get("acceptance_start_datetime")
        row["acceptance_end_datetime"] = workflow.get("acceptance_end_datetime") or record.get("acceptance_end_datetime")
        row["project_end_deadline"] = workflow.get("project_end_deadline") or record.get("project_end_deadline")
        rows.append(row)
    return rows


def normalize_records(records: List[Dict[str, Any]], source: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for record in records:
        if source.startswith("jgrants"):
            out.extend(explode_jgrants_record(record))
        else:
            out.append(record)
    return out


def log_event(conn: sqlite3.Connection, grant_id: str, event_type: str, summary: str, payload: Dict[str, Any]) -> None:
    conn.execute("INSERT INTO sync_events (grant_id, event_type, summary, payload, created_at) VALUES (?, ?, ?, ?, ?)", (grant_id, event_type, summary, json.dumps(payload, ensure_ascii=False), utcnow()))


def upsert_grants(records: List[Dict[str, Any]], source: str) -> Dict[str, Any]:
    conn = db()
    inserted = 0
    updated = 0
    now = utcnow()
    normalized = normalize_records(records, source)
    with conn:
        for record in normalized:
            grant_id = str(record.get("id") or sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:18])
            title = record.get("title") or record.get("name") or "名称未設定"
            content_hash = sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            current = conn.execute("SELECT content_hash, created_at FROM grants WHERE id = ?", (grant_id,)).fetchone()
            payload = {
                "id": grant_id,
                "title": title,
                "institution_name": record.get("institution_name"),
                "system_name": record.get("system_name") or record.get("scheme_name") or record.get("institution_name"),
                "subsidy_catch_phrase": record.get("subsidy_catch_phrase"),
                "detail": record.get("detail"),
                "use_purpose": record.get("use_purpose"),
                "industry": record.get("industry"),
                "target_area_search": record.get("target_area_search"),
                "target_area_detail": record.get("target_area_detail"),
                "target_number_of_employees": record.get("target_number_of_employees"),
                "subsidy_rate": record.get("subsidy_rate"),
                "subsidy_max_limit": record.get("subsidy_max_limit"),
                "granttype": record.get("granttype"),
                "acceptance_start_datetime": record.get("acceptance_start_datetime"),
                "acceptance_end_datetime": record.get("acceptance_end_datetime"),
                "project_end_deadline": record.get("project_end_deadline"),
                "request_reception_presence": record.get("request_reception_presence"),
                "is_enable_multiple_request": 1 if record.get("is_enable_multiple_request") else 0,
                "front_subsidy_detail_page_url": record.get("front_subsidy_detail_page_url"),
                "status": normalize_status(record.get("acceptance_start_datetime"), record.get("acceptance_end_datetime")),
                "raw_json": json.dumps(record, ensure_ascii=False),
                "content_hash": content_hash,
                "source": source,
                "created_at": current[1] if current else now,
                "updated_at": now if current and current[0] != content_hash else now,
                "last_synced_at": now,
            }
            conn.execute(
                """
                INSERT INTO grants (
                  id, title, institution_name, system_name, subsidy_catch_phrase, detail, use_purpose, industry,
                  target_area_search, target_area_detail, target_number_of_employees, subsidy_rate, subsidy_max_limit,
                  granttype, acceptance_start_datetime, acceptance_end_datetime, project_end_deadline,
                  request_reception_presence, is_enable_multiple_request, front_subsidy_detail_page_url,
                  status, raw_json, content_hash, source, created_at, updated_at, last_synced_at
                ) VALUES (
                  :id, :title, :institution_name, :system_name, :subsidy_catch_phrase, :detail, :use_purpose, :industry,
                  :target_area_search, :target_area_detail, :target_number_of_employees, :subsidy_rate, :subsidy_max_limit,
                  :granttype, :acceptance_start_datetime, :acceptance_end_datetime, :project_end_deadline,
                  :request_reception_presence, :is_enable_multiple_request, :front_subsidy_detail_page_url,
                  :status, :raw_json, :content_hash, :source, :created_at, :updated_at, :last_synced_at
                )
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title,
                  institution_name=excluded.institution_name,
                  system_name=excluded.system_name,
                  subsidy_catch_phrase=excluded.subsidy_catch_phrase,
                  detail=excluded.detail,
                  use_purpose=excluded.use_purpose,
                  industry=excluded.industry,
                  target_area_search=excluded.target_area_search,
                  target_area_detail=excluded.target_area_detail,
                  target_number_of_employees=excluded.target_number_of_employees,
                  subsidy_rate=excluded.subsidy_rate,
                  subsidy_max_limit=excluded.subsidy_max_limit,
                  granttype=excluded.granttype,
                  acceptance_start_datetime=excluded.acceptance_start_datetime,
                  acceptance_end_datetime=excluded.acceptance_end_datetime,
                  project_end_deadline=excluded.project_end_deadline,
                  request_reception_presence=excluded.request_reception_presence,
                  is_enable_multiple_request=excluded.is_enable_multiple_request,
                  front_subsidy_detail_page_url=excluded.front_subsidy_detail_page_url,
                  status=excluded.status,
                  raw_json=excluded.raw_json,
                  content_hash=excluded.content_hash,
                  source=excluded.source,
                  updated_at=excluded.updated_at,
                  last_synced_at=excluded.last_synced_at
                """,
                payload,
            )
            if current is None:
                inserted += 1
                log_event(conn, grant_id, "new", f"{title} を新規登録しました", payload)
            elif current[0] != content_hash:
                updated += 1
                log_event(conn, grant_id, "updated", f"{title} を更新しました", payload)
    conn.close()
    return {"inserted": inserted, "updated": updated, "total_processed": len(normalized)}




def get_grant_by_id(grant_id: str) -> Optional[Dict[str, Any]]:
    cached = LIVE_ITEM_CACHE.get(grant_id)
    if cached:
        return dict(cached)
    conn = db()
    row = conn.execute("SELECT * FROM grants WHERE id = ?", (grant_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_grants_by_ids(ids: List[str]) -> List[Dict[str, Any]]:
    clean_ids = [i for i in ids if i]
    if not clean_ids:
        return []
    conn = db()
    placeholders = ','.join(['?'] * len(clean_ids))
    rows = conn.execute(f"SELECT * FROM grants WHERE id IN ({placeholders})", clean_ids).fetchall()
    conn.close()
    mapping = {str(row['id']): dict(row) for row in rows}
    for item_id in clean_ids:
        if item_id not in mapping and item_id in LIVE_ITEM_CACHE:
            mapping[item_id] = dict(LIVE_ITEM_CACHE[item_id])
    return [mapping[i] for i in clean_ids if i in mapping]

def fetch_news(limit: int = 20) -> List[Dict[str, Any]]:
    conn = db()
    rows = conn.execute(
        """
        SELECT e.id, e.grant_id, e.event_type, e.summary, e.created_at, g.title, g.front_subsidy_detail_page_url, g.status
        FROM sync_events e LEFT JOIN grants g ON g.id = e.grant_id
        WHERE g.source LIKE 'jgrants%'
        ORDER BY e.created_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    items = []
    for row in rows:
        item = dict(row)
        item["safe_public_url"] = safe_public_url(item.get("front_subsidy_detail_page_url"))
        items.append(item)
    return items


def list_grants(query: str = "", status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    conn = db()
    sql = "SELECT * FROM grants WHERE source LIKE 'jgrants%'"
    params: List[Any] = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if query:
        like = f"%{query}%"
        fields = ["title", "detail", "use_purpose", "institution_name", "industry", "target_area_search", "target_area_detail", "system_name", "granttype", "subsidy_catch_phrase", "target_number_of_employees"]
        sql += " AND (" + " OR ".join([f"COALESCE({f}, '') LIKE ?" for f in fields]) + ")"
        params.extend([like] * len(fields))
    sql += " ORDER BY status != 'open', acceptance_end_datetime ASC, subsidy_max_limit DESC, updated_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [prepare_item(dict(r)) for r in rows]


def refresh_data() -> Dict[str, Any]:
    from .jgrants import refresh_data as _refresh_data
    return _refresh_data()


def ensure_live_cache_for_query(query: str, profile):
    from .jgrants import ensure_live_cache_for_query as _ensure_live_cache_for_query
    return _ensure_live_cache_for_query(query, profile)


def get_meta() -> Dict[str, Any]:
    conn = db()
    counts = {row[0]: row[1] for row in conn.execute("SELECT status, COUNT(*) FROM grants WHERE source LIKE 'jgrants%' GROUP BY status").fetchall()}
    source_rows = conn.execute("SELECT source, COUNT(*) FROM grants WHERE source LIKE 'jgrants%' GROUP BY source ORDER BY COUNT(*) DESC").fetchall()
    latest = conn.execute("SELECT MAX(last_synced_at) FROM grants WHERE source LIKE 'jgrants%'").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM grants WHERE source LIKE 'jgrants%'").fetchone()[0]
    conn.close()
    source_breakdown = [{"source": row[0], "count": row[1]} for row in source_rows]
    return {
        "counts": counts,
        "last_synced_at": latest,
        "sample_mode": False,
        "total": total,
        "source_breakdown": source_breakdown,
        "primary_source": source_breakdown[0]["source"] if source_breakdown else "none",
        "fallback_reason": None,
        "live_ready": total > 0,
        "llm_enabled": bool(GEMINI_API_KEY or OPENAI_API_KEY or ANTHROPIC_API_KEY),
        "llm_provider": "gemini" if GEMINI_API_KEY else ("openai" if OPENAI_API_KEY else ("anthropic" if ANTHROPIC_API_KEY else None)),
        "fast_mode_default": FAST_MODE_DEFAULT,
        "fast_mode_settings": {
            "llm_profile": ENABLE_LLM_PROFILE_IN_FAST_MODE,
            "live_fetch": ENABLE_LIVE_FETCH_IN_FAST_MODE,
            "llm_rerank": ENABLE_LLM_RERANK_IN_FAST_MODE,
        },
    }


def bootstrap_data() -> None:
    init_db()
    conn = db()
    total = conn.execute("SELECT COUNT(*) FROM grants WHERE source LIKE 'jgrants%'").fetchone()[0]
    latest = conn.execute("SELECT MAX(last_synced_at) FROM grants WHERE source LIKE 'jgrants%'").fetchone()[0]
    conn.close()
    is_stale = True
    if latest:
        try:
            latest_dt = datetime.fromisoformat(str(latest).replace("Z", "+00:00"))
            is_stale = datetime.now(timezone.utc) - latest_dt > timedelta(hours=AUTO_REFRESH_MAX_AGE_HOURS)
        except ValueError:
            is_stale = True
    if AUTO_REFRESH_ON_START and (total == 0 or is_stale):
        refresh_data()



ALLOWED_LEAD_TYPES = {
    "consultation": "専門家相談",
    "automation_pack": "公募ウォッチ自動化パック",
    "expert_listing": "専門家掲載希望",
    "feedback": "β版フィードバック",
}


def _clean_lead_text(value: Any, limit: int = 2000) -> str:
    text = strip_html(str(value or ""))
    text = " ".join(text.split())
    return text[:limit]


def create_lead(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Store a lightweight business lead.

    This intentionally keeps the schema simple so the beta can validate
    consultation, automation-pack, and expert-listing demand without adding
    accounts, CRM, or payment infrastructure.
    """
    lead_type = _clean_lead_text(payload.get("lead_type"), 80) or "consultation"
    if lead_type not in ALLOWED_LEAD_TYPES:
        raise ValueError("lead_type must be consultation, automation_pack, expert_listing, or feedback")

    email = _clean_lead_text(payload.get("email"), 254)
    if not email or "@" not in email:
        raise ValueError("email is required")

    grant_id = _clean_lead_text(payload.get("grant_id"), 200) or None
    grant_title = _clean_lead_text(payload.get("grant_title"), 300) or None
    if grant_id and not grant_title:
        grant = get_grant_by_id(grant_id)
        if grant:
            grant_title = _clean_lead_text(grant.get("title"), 300)

    now = utcnow()
    record = {
        "lead_type": lead_type,
        "name": _clean_lead_text(payload.get("name"), 120),
        "company": _clean_lead_text(payload.get("company"), 160),
        "email": email,
        "phone": _clean_lead_text(payload.get("phone"), 80),
        "role": _clean_lead_text(payload.get("role"), 120),
        "message": _clean_lead_text(payload.get("message"), 2000),
        "grant_id": grant_id,
        "grant_title": grant_title,
        "source_page": _clean_lead_text(payload.get("source_page"), 300),
        "payload": json.dumps(payload, ensure_ascii=False),
        "created_at": now,
    }
    conn = db()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO leads (
                lead_type, name, company, email, phone, role, message,
                grant_id, grant_title, source_page, payload, created_at
            ) VALUES (
                :lead_type, :name, :company, :email, :phone, :role, :message,
                :grant_id, :grant_title, :source_page, :payload, :created_at
            )
            """,
            record,
        )
        lead_id = cur.lastrowid
    conn.close()
    return {
        "ok": True,
        "id": lead_id,
        "lead_type": lead_type,
        "lead_type_label": ALLOWED_LEAD_TYPES[lead_type],
        "created_at": now,
        "message": "お問い合わせを受け付けました。β版ではこの内容をもとに個別に確認します。",
    }


def list_leads(limit: int = 100, lead_type: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = db()
    sql = "SELECT * FROM leads"
    params: List[Any] = []
    if lead_type:
        sql += " WHERE lead_type = ?"
        params.append(lead_type)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]
