from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from typing import Any, Mapping, Optional

JST = timezone(timedelta(hours=9))


def parse_deadline_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=JST)
        return parsed
    except ValueError:
        pass

    patterns = [
        (r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})", 0),
        (r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", 0),
        (r"令和\s*(\d{1,2})年\s*(\d{1,2})月\s*(\d{1,2})日", 2018),
    ]
    for pattern, era_offset in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        year = int(match.group(1)) + era_offset
        month = int(match.group(2))
        day = int(match.group(3))
        try:
            return datetime.combine(datetime(year, month, day).date(), time(23, 59, 59), tzinfo=JST)
        except ValueError:
            return None
    return None


def effective_status(item: Mapping[str, Any], *, now: Optional[datetime] = None) -> str:
    current = (item.get("status") or "unknown") if item else "unknown"
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    start_dt = parse_deadline_datetime(item.get("acceptance_start_datetime") if item else None)
    end_dt = parse_deadline_datetime(item.get("acceptance_end_datetime") if item else None)
    if end_dt and now_dt.astimezone(end_dt.tzinfo) > end_dt:
        return "closed"
    if start_dt and now_dt.astimezone(start_dt.tzinfo) < start_dt:
        return "upcoming"
    if current in {"open", "upcoming", "closed"}:
        return str(current)
    return "unknown"
