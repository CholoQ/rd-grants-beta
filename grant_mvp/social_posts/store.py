"""posts.csv の読み書き・重複検出ヘルパ.

CSVを単一データソースとし、grants.db には書き込まない。
すべて UTF-8 BOM付き (utf-8-sig) で統一。
"""
from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import CSV_ENCODING, CSV_FIELDS


def body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def init_csv(path: Path) -> bool:
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=CSV_ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
    return True


def load_existing(path: Path) -> List[Dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding=CSV_ENCODING, newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def existing_body_hashes(path: Path) -> Set[str]:
    return {
        row.get("body_hash", "")
        for row in load_existing(path)
        if row.get("body_hash")
    }


def append_posts(path: Path, posts: Iterable[Dict[str, str]]) -> int:
    path = Path(path)
    init_csv(path)
    count = 0
    with path.open("a", encoding=CSV_ENCODING, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        for post in posts:
            row = {field: post.get(field, "") for field in CSV_FIELDS}
            writer.writerow(row)
            count += 1
    return count


def _parse_iso(value: str) -> Optional[datetime]:
    """ISO8601 文字列を aware な datetime にパース。失敗時 None。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def latest_created_at_by_grant_sns(path: Path) -> Dict[Tuple[str, str], datetime]:
    """posts.csv の (grant_id, sns) ごとの最新 created_at を返す。

    - grant_id / sns が空、または created_at がパースできない行は除外。
    - cooldown 判定で aware datetime と比較する前提。
    """
    out: Dict[Tuple[str, str], datetime] = {}
    for row in load_existing(path):
        gid = row.get("grant_id", "")
        sns = row.get("sns", "")
        if not gid or not sns:
            continue
        ts = _parse_iso(row.get("created_at", ""))
        if ts is None:
            continue
        key = (gid, sns)
        prev = out.get(key)
        if prev is None or ts > prev:
            out[key] = ts
    return out


def recent_theme_grant_ids(path: Path, n: int = 5) -> Set[Tuple[str, str]]:
    """直近 n 件（ファイル末尾 n 行）の (theme, grant_id) セット。

    posts.csv は append-only なのでファイル順＝追加順とみなす。
    grant_id が空の行は除外。
    n <= 0 の場合はチェック無効化として空集合を返す。
    """
    if n <= 0:
        return set()
    rows = load_existing(path)
    return {
        (r.get("theme", ""), r.get("grant_id", ""))
        for r in rows[-n:]
        if r.get("grant_id")
    }
