#!/usr/bin/env python3
"""軽量スナップショットDB生成スクリプト.

使い方:
    python scripts/build_snapshot.py
    python scripts/build_snapshot.py --src path/to/grants.db --dst path/to/out.db

方針:
- grants: status='open' のみ。raw_json は捨て、detail は HTML 除去後 先頭1000文字。
- sync_events / leads / grant_summaries: スキーマだけ作って空。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from grant_mvp.config import (
    GRANTS_SCHEMA, SYNC_EVENTS_SCHEMA, LEADS_SCHEMA, GRANT_SUMMARIES_SCHEMA,
)
from grant_mvp.utils import strip_html

DETAIL_MAX_CHARS = 1000

KEEP_COLUMNS = [
    "id", "title", "institution_name", "system_name", "subsidy_catch_phrase",
    "detail", "use_purpose", "industry",
    "target_area_search", "target_area_detail", "target_number_of_employees",
    "subsidy_rate", "subsidy_max_limit", "granttype",
    "acceptance_start_datetime", "acceptance_end_datetime", "project_end_deadline",
    "request_reception_presence", "is_enable_multiple_request",
    "front_subsidy_detail_page_url", "status",
    "content_hash", "source", "created_at", "updated_at", "last_synced_at",
]


def transform_detail(raw):
    if not raw:
        return raw
    plain = strip_html(raw)
    if len(plain) > DETAIL_MAX_CHARS:
        plain = plain[:DETAIL_MAX_CHARS]
    return plain


def build(src_path: Path, dst_path: Path) -> dict:
    if not src_path.exists():
        raise FileNotFoundError(f"source db not found: {src_path}")
    if dst_path.exists():
        dst_path.unlink()

    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(dst_path)

    with dst:
        dst.execute(GRANTS_SCHEMA)
        dst.execute(SYNC_EVENTS_SCHEMA)
        dst.execute(LEADS_SCHEMA)
        dst.execute(GRANT_SUMMARIES_SCHEMA)

    cols = ", ".join(KEEP_COLUMNS)
    placeholders = ", ".join(["?"] * len(KEEP_COLUMNS))
    insert_sql = f"INSERT INTO grants ({cols}) VALUES ({placeholders})"

    rows = src.execute(
        f"SELECT {cols} FROM grants WHERE status = 'open'"
    ).fetchall()

    inserted = 0
    with dst:
        for row in rows:
            values = []
            for c in KEEP_COLUMNS:
                v = row[c]
                if c == "detail":
                    v = transform_detail(v)
                values.append(v)
            dst.execute(insert_sql, values)
            inserted += 1

    dst.execute("VACUUM")

    src.close()
    dst.close()

    return {
        "src": str(src_path),
        "dst": str(dst_path),
        "src_size_mb": round(src_path.stat().st_size / (1024 * 1024), 2),
        "dst_size_mb": round(dst_path.stat().st_size / (1024 * 1024), 2),
        "inserted": inserted,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default=str(ROOT / "grant_mvp" / "grants.db"))
    parser.add_argument("--dst", default=str(ROOT / "grant_mvp" / "grants.snapshot.db"))
    args = parser.parse_args()

    result = build(Path(args.src).resolve(), Path(args.dst).resolve())
    print(
        f"[snapshot] {result['inserted']} grants  "
        f"{result['src_size_mb']}MB -> {result['dst_size_mb']}MB"
    )
    print(f"  src: {result['src']}")
    print(f"  dst: {result['dst']}")


if __name__ == "__main__":
    main()
